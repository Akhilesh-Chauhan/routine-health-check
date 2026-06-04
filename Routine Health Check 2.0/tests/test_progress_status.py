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
