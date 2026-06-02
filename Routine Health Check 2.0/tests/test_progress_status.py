"""The live progress bar (Option B) is driven entirely by /status — it reads
each step's exit_code to colour segments. Pin that contract so a future change
can't silently break the bar.
"""
from __future__ import annotations

import sys
import time

from health_check.web import app as web_app
from health_check.web.runner import runner, JobStep


def _wait(predicate, timeout=15.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_status_exposes_per_step_progress():
    # Two trivial steps that exit 0 immediately.
    job = runner.submit("progress-demo", [
        JobStep(label="step one", argv=[sys.executable, "-c", "pass"]),
        JobStep(label="step two", argv=[sys.executable, "-c", "pass"]),
    ])
    assert _wait(lambda: job.state in ("done", "failed")), "job never finished"

    body = web_app.create_app().test_client().get(f"/status/{job.id}").get_json()
    assert body["state"] == "done"
    steps = body["steps"]
    assert len(steps) == 2
    # The fields the segmented bar relies on: a label + an exit_code per step.
    assert [s["label"] for s in steps] == ["step one", "step two"]
    assert all(s["exit_code"] == 0 for s in steps)


def test_status_exposes_fine_grained_progress():
    # A step that emits `[progress] d/t | label` markers (as `hc sweep` does,
    # one per service) should drive the continuous fill bar: the runner parses
    # the latest marker and /status surfaces it.
    code = (
        "import sys\n"
        "for i in (1, 2, 3):\n"
        "    print(f'[progress] {i}/3 | unit {i}'); sys.stdout.flush()\n"
    )
    job = runner.submit("progress-fine", [
        JobStep(label="emit", argv=[sys.executable, "-c", code]),
    ])
    assert _wait(lambda: job.state in ("done", "failed")), "job never finished"

    body = web_app.create_app().test_client().get(f"/status/{job.id}").get_json()
    assert body["progress"] == {"done": 3, "total": 3, "label": "unit 3"}


def test_status_progress_is_none_without_markers():
    # Jobs that don't emit markers leave progress None so the panel falls back
    # to per-step segments.
    job = runner.submit("no-markers", [
        JobStep(label="quiet", argv=[sys.executable, "-c", "pass"]),
    ])
    assert _wait(lambda: job.state in ("done", "failed")), "job never finished"
    body = web_app.create_app().test_client().get(f"/status/{job.id}").get_json()
    assert body["progress"] is None
