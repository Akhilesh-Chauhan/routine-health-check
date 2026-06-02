"""OTP login opens a headed browser, so the panel must point its login job at
a desktop DISPLAY — and give a clear message when it can't open a window.
"""
from __future__ import annotations

import sys
import time

from health_check.web.runner import JobRunner, JobStep, step_login


def _wait(predicate, timeout=15.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_login_step_is_marked_needs_display():
    assert step_login("prod").needs_display is True
    assert step_login("dev").needs_display is True


def test_runner_points_login_at_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)   # simulate a server with no DISPLAY
    r = JobRunner()
    job = r.submit("login-demo", [JobStep(
        label="echo display",
        argv=[sys.executable, "-c", "import os; print('DISP=' + os.environ.get('DISPLAY','none'))"],
        needs_display=True,
    )])
    assert _wait(lambda: job.state in ("done", "failed"))
    assert "DISP=:0" in "\n".join(job.log_ring), "login step was not given a DISPLAY"


def test_failed_login_step_emits_actionable_hint(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    r = JobRunner()
    job = r.submit("login-fail", [JobStep(
        label="hc login prod",
        argv=[sys.executable, "-c", "import sys; sys.exit(1)"],
        needs_display=True,
    )])
    assert _wait(lambda: job.state in ("done", "failed"))
    assert job.state == "failed"
    assert "OTP login needs a real browser window" in "\n".join(job.log_ring)
