"""Tests for the decided fixes D8 (secrets), D9 (probe_auth), D10 (CSRF), D11 (cancel/timeout)."""
from __future__ import annotations

import os
import sys
import time

import pytest

from health_check import paths, secrets


# ---- D8: credentials come from env / secrets.env, never a source default ----
def _clear_cog_env(monkeypatch):
    for k in ("HC_DEV_COGNITO_USER", "HC_DEV_COGNITO_PASS",
              "DEV_COGNITO_USER", "DEV_COGNITO_PASS"):
        monkeypatch.delenv(k, raising=False)


def test_no_password_default(monkeypatch, tmp_path):
    _clear_cog_env(monkeypatch)
    monkeypatch.setattr(paths, "SECRETS_ENV", tmp_path / "absent.env")
    secrets._load_secrets_env.cache_clear()
    user, pwd = secrets.cognito_credentials()
    assert user == "devadmin"        # non-secret username default is fine
    assert pwd is None               # NO literal password default in source


def test_password_from_env(monkeypatch, tmp_path):
    _clear_cog_env(monkeypatch)
    monkeypatch.setenv("HC_DEV_COGNITO_PASS", "env-secret")
    monkeypatch.setattr(paths, "SECRETS_ENV", tmp_path / "absent.env")
    secrets._load_secrets_env.cache_clear()
    _, pwd = secrets.cognito_credentials()
    assert pwd == "env-secret"


def test_credentials_from_secrets_file(monkeypatch, tmp_path):
    _clear_cog_env(monkeypatch)
    f = tmp_path / "secrets.env"
    f.write_text('# dev cognito\nHC_DEV_COGNITO_USER=fileuser\nHC_DEV_COGNITO_PASS="file-secret"\n')
    monkeypatch.setattr(paths, "SECRETS_ENV", f)
    secrets._load_secrets_env.cache_clear()
    try:
        user, pwd = secrets.cognito_credentials()
        assert user == "fileuser"
        assert pwd == "file-secret"
    finally:
        for k in ("HC_DEV_COGNITO_USER", "HC_DEV_COGNITO_PASS"):
            os.environ.pop(k, None)


def test_real_env_overrides_secrets_file(monkeypatch, tmp_path):
    _clear_cog_env(monkeypatch)
    monkeypatch.setenv("HC_DEV_COGNITO_PASS", "from-env")
    f = tmp_path / "secrets.env"
    f.write_text("HC_DEV_COGNITO_PASS=from-file\n")
    monkeypatch.setattr(paths, "SECRETS_ENV", f)
    secrets._load_secrets_env.cache_clear()
    _, pwd = secrets.cognito_credentials()
    assert pwd == "from-env", "real environment must win over secrets.env"


# ---- D9: probe_auth no-signal branch must NOT optimistically return AUTHED ----
def test_probe_verdict():
    from health_check.orchestration.master import probe_verdict
    assert probe_verdict(True, False) == "AUTHED"
    assert probe_verdict(True, True) == "AUTHED"     # positive signal wins
    assert probe_verdict(False, True) == "LOGGED_OUT"
    assert probe_verdict(False, False) == "UNKNOWN"  # the fix: was wrongly AUTHED


# ---- D10: cross-origin POSTs are rejected ----
def test_same_origin_helper():
    from health_check.web.app import _same_origin

    class Req:
        def __init__(self, host, headers):
            self.host = host
            self.headers = headers

    assert _same_origin(Req("localhost:5050", {})) is True
    assert _same_origin(Req("localhost:5050", {"Origin": "http://localhost:5050"})) is True
    assert _same_origin(Req("127.0.0.1:5050", {"Referer": "http://127.0.0.1:5050/"})) is True
    assert _same_origin(Req("localhost:5050", {"Origin": "http://evil.example"})) is False
    assert _same_origin(Req("localhost:5050", {"Referer": "http://evil.example/x"})) is False


def test_run_rejects_cross_origin():
    from health_check.web import app as web_app
    client = web_app.create_app().test_client()
    resp = client.post("/run", json={"kind": "liveness"},
                       headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


# ---- D11: cancel + per-step timeout ----
def _wait(predicate, timeout=15.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_cancel_unknown_job_returns_false():
    from health_check.web.runner import JobRunner
    assert JobRunner().cancel("does-not-exist") is False


def test_cancel_kills_running_job():
    from health_check.web.runner import JobRunner, JobStep
    r = JobRunner()
    step = JobStep(label="sleep", argv=[sys.executable, "-c", "import time; time.sleep(30)"])
    job = r.submit("long-job", [step])

    assert _wait(lambda: r.current_id() == job.id and r._current_proc is not None), \
        "job never started running"
    t0 = time.time()
    assert r.cancel(job.id) is True
    assert _wait(lambda: job.state in ("cancelled", "done", "failed")), "job never ended"
    assert job.state == "cancelled"
    assert time.time() - t0 < 15, "cancel did not promptly kill the 30s sleep"


def test_step_timeout_kills_job():
    from health_check.web.runner import JobRunner, JobStep
    r = JobRunner()
    step = JobStep(label="sleep", argv=[sys.executable, "-c", "import time; time.sleep(30)"],
                   timeout_s=1)
    job = r.submit("timeout-job", [step])
    assert _wait(lambda: job.state in ("done", "failed", "cancelled")), "job never ended"
    assert job.state == "failed", "timed-out job should be failed, not done"
    assert job.steps[0].exit_code is not None


def test_cancel_endpoint_404_for_unknown():
    from health_check.web import app as web_app
    client = web_app.create_app().test_client()
    assert client.post("/cancel/no-such-job").status_code == 404


def test_cancel_endpoint_rejects_cross_origin():
    from health_check.web import app as web_app
    client = web_app.create_app().test_client()
    resp = client.post("/cancel/1", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403
