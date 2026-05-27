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
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from health_check import paths


# How many trailing log lines a late-joining SSE client receives.
RING_SIZE = 2000


@dataclass
class JobStep:
    """One subprocess invocation inside a job."""
    label: str
    argv: list[str]
    exit_code: int | None = None
    duration_s: float | None = None


@dataclass
class Job:
    id: str
    title: str                          # human-readable, e.g. "Production env sweep"
    steps: list[JobStep]
    state: str = "queued"               # queued | running | done | failed
    started_at: float | None = None
    ended_at: float | None = None
    overall_exit: int | None = None     # 0 only if every step exited 0
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

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._counter = itertools.count(1)
        self._current_id: str | None = None
        self._worker: threading.Thread | None = None
        self._pending: queue.Queue[Job] = queue.Queue()

    # ---- public ----------------------------------------------------------

    def submit(self, title: str, steps: list[JobStep]) -> Job:
        job = Job(id=str(next(self._counter)), title=title, steps=steps)
        with self._lock:
            self._jobs[job.id] = job
        self._pending.put(job)
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def current_id(self) -> str | None:
        return self._current_id

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
        self._current_id = job.id
        job.state = "running"
        job.started_at = time.time()
        job.publish(f"=== {job.title} ===")

        overall_ok = True
        for step in job.steps:
            t0 = time.time()
            job.publish(f"\n[step] {step.label}")
            job.publish(f"[step] cwd={paths.ROOT}  cmd={' '.join(step.argv)}")
            env = dict(os.environ)
            # Default to non-interactive so the orchestrator doesn't pop
            # OTP windows from the web context — the operator triggers
            # those explicitly via the Login buttons.
            env.setdefault("HC_NONINTERACTIVE", "1")
            try:
                proc = subprocess.Popen(
                    step.argv,
                    cwd=str(paths.ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError as e:
                job.publish(f"[step] launch failed: {e}")
                step.exit_code = 127
                step.duration_s = time.time() - t0
                overall_ok = False
                continue

            assert proc.stdout is not None
            for line in proc.stdout:
                job.publish(line.rstrip("\n"))
            rc = proc.wait()
            step.exit_code = rc
            step.duration_s = time.time() - t0
            job.publish(f"[step] {step.label} -> exit={rc} ({step.duration_s:.1f}s)")
            if rc != 0:
                overall_ok = False

        job.state = "done" if overall_ok else "failed"
        job.ended_at = time.time()
        job.overall_exit = 0 if overall_ok else 1
        job.publish(f"\n=== {job.title} ended (state={job.state}, "
                    f"total={job.ended_at - (job.started_at or 0):.1f}s) ===")
        # Sentinel that SSE consumers treat as end-of-stream.
        job.publish("__JOB_END__")
        self._current_id = None


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
                   argv=[PYTHON, "-m", "health_check.cli", "login", tenant])


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
