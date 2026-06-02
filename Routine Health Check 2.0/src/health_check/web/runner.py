"""Background job runner for the web control panel.

One job at a time, globally. Each job is a sequence of CLI commands
(e.g. `hc sweep`, `hc check govai`) run as subprocesses. stdout/stderr
lines are captured in a ring buffer and republished on a pubsub queue
that the Flask SSE endpoint consumes.
"""
from __future__ import annotations

import itertools
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from health_check import paths


# How many trailing log lines a late-joining SSE client receives.
RING_SIZE = 2000

# A step (the sweep) may emit fine-grained progress as
# `[progress] done/total | label` on its output stream. The runner parses
# these to drive a continuous progress bar in the panel.
_PROGRESS_RE = re.compile(r"\[progress\]\s+(\d+)\s*/\s*(\d+)\s*(?:\|\s*(.*))?$")

# Emit a "still running" heartbeat into the log every this-many seconds while a
# step is producing no output, so the panel never looks frozen.
HEARTBEAT_SECONDS = 10


def _env_timeout() -> float | None:
    """Default per-step timeout from HC_STEP_TIMEOUT (seconds). 0/unset/bad
    -> None (no timeout), preserving the prior unbounded behaviour unless an
    operator opts in."""
    try:
        v = float(os.environ.get("HC_STEP_TIMEOUT", "0"))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _kill_proc_tree(proc: "subprocess.Popen") -> None:
    """Terminate a step subprocess AND its children (Playwright spawns a
    Chromium tree). Started with start_new_session=True, so the pid is its own
    process-group leader and we can signal the whole group. SIGTERM, then
    SIGKILL if it doesn't exit promptly."""
    if proc.poll() is not None:
        return
    def _signal(sig):
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), sig)
            else:  # pragma: no cover - non-POSIX fallback
                proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass
    _signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _signal(getattr(signal, "SIGKILL", signal.SIGTERM))


@dataclass
class JobStep:
    """One subprocess invocation inside a job."""
    label: str
    argv: list[str]
    # OTP login opens a HEADED browser, which needs an X display. Mark such
    # steps so the runner points them at the desktop's DISPLAY.
    needs_display: bool = False
    exit_code: int | None = None
    duration_s: float | None = None
    # Per-step wall-clock budget (seconds). None -> fall back to the runner's
    # HC_STEP_TIMEOUT default (also None unless set).
    timeout_s: float | None = None


@dataclass
class Job:
    id: str
    title: str                          # human-readable, e.g. "Production env sweep"
    steps: list[JobStep]
    state: str = "queued"               # queued | running | done | failed | cancelled
    started_at: float | None = None
    ended_at: float | None = None
    overall_exit: int | None = None     # 0 only if every step exited 0
    # Fine-grained sub-step progress parsed from `[progress] d/t | label`
    # markers (the sweep emits one per service). None for jobs that don't
    # emit them, in which case the panel falls back to per-step segments.
    progress: dict | None = None
    log_ring: list[str] = field(default_factory=list)
    _subs: list[queue.Queue] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def publish(self, line: str) -> None:
        with self._lock:
            self.log_ring.append(line)
            if len(self.log_ring) > RING_SIZE:
                del self.log_ring[: len(self.log_ring) - RING_SIZE]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(line)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=4096)
        with self._lock:
            backlog = list(self.log_ring)
            self._subs.append(q)
        for line in backlog:
            q.put_nowait(line)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


class JobRunner:
    """Globally serialized job runner. One job at a time."""

    def __init__(self, default_timeout: float | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._counter = itertools.count(1)
        self._current_id: str | None = None
        self._current_proc: "subprocess.Popen | None" = None
        self._cancelled: set[str] = set()
        self._worker: threading.Thread | None = None
        self._pending: queue.Queue[Job] = queue.Queue()
        self.default_timeout = default_timeout if default_timeout is not None else _env_timeout()

    # ---- public ----------------------------------------------------------

    def submit(self, title: str, steps: list[JobStep]) -> Job:
        # itertools.count is NOT thread-safe; mint the id and register the
        # job under the same lock so concurrent submits can't collide on an id.
        with self._lock:
            job = Job(id=str(next(self._counter)), title=title, steps=steps)
            self._jobs[job.id] = job
        self._pending.put(job)
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def current_id(self) -> str | None:
        with self._lock:
            return self._current_id

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a job. Returns False if no such job.

        If it's the running job, its current step's process tree is killed and
        no further steps run. If it's still queued, it is marked cancelled and
        skipped when the worker reaches it.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            self._cancelled.add(job_id)
            if job.state == "queued":
                job.state = "cancelled"
            proc = self._current_proc if self._current_id == job_id else None
        if proc is not None:
            job.publish("[cancel] operator requested cancellation — killing step")
            _kill_proc_tree(proc)
        return True

    # ---- internal --------------------------------------------------------

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            try:
                job = self._pending.get(timeout=30)
            except queue.Empty:
                return
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        with self._lock:
            self._current_id = job.id
        job.state = "running"
        job.started_at = time.time()
        job.publish(f"=== {job.title} ===")

        overall_ok = True
        cancelled = False
        for step in job.steps:
            with self._lock:
                if job.id in self._cancelled:
                    cancelled = True
            if cancelled:
                job.publish(f"\n[step] {step.label} -> skipped (job cancelled)")
                overall_ok = False
                break

            t0 = time.time()
            job.publish(f"\n[step] {step.label}")
            job.publish(f"[step] cwd={paths.ROOT}  cmd={' '.join(step.argv)}")
            env = dict(os.environ)
            # Default to non-interactive so the orchestrator doesn't pop
            # OTP windows from the web context — the operator triggers
            # those explicitly via the Login buttons.
            env.setdefault("HC_NONINTERACTIVE", "1")
            if step.needs_display:
                # OTP login opens a headed browser; point it at the desktop's X
                # display (matches the sweep's run_login). Respects an existing
                # DISPLAY if the server was started from a desktop session.
                env.setdefault("DISPLAY", ":0")
            # Stream child stdout live instead of letting Python block-buffer it
            # (otherwise `hc check <name>`, which only print()s at the end, shows
            # nothing in the panel until it exits).
            env.setdefault("PYTHONUNBUFFERED", "1")
            try:
                proc = subprocess.Popen(
                    step.argv,
                    cwd=str(paths.ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,   # own process group -> killable as a tree
                )
            except FileNotFoundError as e:
                job.publish(f"[step] launch failed: {e}")
                step.exit_code = 127
                step.duration_s = time.time() - t0
                overall_ok = False
                continue

            with self._lock:
                self._current_proc = proc

            # Per-step timeout watchdog.
            timeout_s = step.timeout_s if step.timeout_s is not None else self.default_timeout
            timed_out = threading.Event()
            timer: threading.Timer | None = None
            if timeout_s and timeout_s > 0:
                def _on_timeout(p=proc):
                    timed_out.set()
                    _kill_proc_tree(p)
                timer = threading.Timer(timeout_s, _on_timeout)
                timer.daemon = True
                timer.start()

            # Heartbeat: while a step runs without emitting output (a functional
            # check only print()s its result at the very end), publish an
            # elapsed marker every few seconds so the live log keeps updating.
            hb_stop = threading.Event()

            def _heartbeat(p=proc, started=t0, label=step.label):
                while not hb_stop.wait(HEARTBEAT_SECONDS):
                    if p.poll() is not None:
                        return
                    job.publish(f"[hc] {label} — still running, "
                                f"{int(time.time() - started)}s elapsed…")

            hb = threading.Thread(target=_heartbeat, daemon=True)
            hb.start()

            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    m = _PROGRESS_RE.search(line)
                    if m:
                        job.progress = {
                            "done": int(m.group(1)),
                            "total": int(m.group(2)),
                            "label": (m.group(3) or "").strip(),
                        }
                    job.publish(line)
                rc = proc.wait()
            finally:
                hb_stop.set()
                if timer is not None:
                    timer.cancel()
                with self._lock:
                    self._current_proc = None
                    cancelled = job.id in self._cancelled

            step.exit_code = rc
            step.duration_s = time.time() - t0
            if timed_out.is_set():
                job.publish(f"[step] {step.label} -> TIMEOUT after {timeout_s:.0f}s "
                            f"(killed, exit={rc})")
                overall_ok = False
                break
            if cancelled:
                job.publish(f"[step] {step.label} -> cancelled (killed, exit={rc})")
                overall_ok = False
                break
            job.publish(f"[step] {step.label} -> exit={rc} ({step.duration_s:.1f}s)")
            if rc != 0:
                overall_ok = False
                if step.needs_display:
                    job.publish(
                        "[hc] OTP login needs a real browser window on a desktop "
                        "display. If `hc serve` is running headless (SSH / systemd / "
                        "no screen), it can't open one — run the login from a terminal "
                        "ON the desktop instead:  DISPLAY=:0 hc login <prod|dev|umang>")

        if cancelled:
            job.state = "cancelled"
        else:
            job.state = "done" if overall_ok else "failed"
        job.ended_at = time.time()
        job.overall_exit = 0 if (overall_ok and not cancelled) else 1
        job.publish(f"\n=== {job.title} ended (state={job.state}, "
                    f"total={job.ended_at - (job.started_at or 0):.1f}s) ===")
        # Sentinel that SSE consumers treat as end-of-stream.
        job.publish("__JOB_END__")
        with self._lock:
            self._current_id = None
            self._current_proc = None


# Shared singleton — Flask routes import this.
runner = JobRunner()


# ---- helpers to build canonical step lists --------------------------------

PYTHON = sys.executable

def step_sweep() -> JobStep:
    return JobStep(label="hc sweep",
                   argv=[PYTHON, "-m", "health_check.cli", "sweep"])

def step_dashboard() -> JobStep:
    return JobStep(label="hc dashboard",
                   argv=[PYTHON, "-m", "health_check.cli", "dashboard"])

def step_check(name: str) -> JobStep:
    return JobStep(label=f"hc check {name}",
                   argv=[PYTHON, "-m", "health_check.cli", "check", name])

def step_liveness() -> JobStep:
    return JobStep(label="hc liveness",
                   argv=[PYTHON, "-m", "health_check.cli", "liveness"])

def step_login(tenant: str) -> JobStep:
    return JobStep(label=f"hc login {tenant}",
                   argv=[PYTHON, "-m", "health_check.cli", "login", tenant],
                   needs_display=True)


def stream_lines(job: Job) -> Iterator[str]:
    """Yield job log lines until the __JOB_END__ sentinel. Used by SSE."""
    q = job.subscribe()
    try:
        while True:
            try:
                line = q.get(timeout=15)
            except queue.Empty:
                # SSE keep-alive comment — keeps proxies / browsers from
                # closing the connection during long checks.
                yield ":keepalive\n\n"
                continue
            if line == "__JOB_END__":
                return
            yield f"data: {line}\n\n"
    finally:
        job.unsubscribe(q)
