"""Tests for the low-risk hardening fixes D1-D7."""
from __future__ import annotations

import json
import os
import threading

import pytest


# ---- D1: runner concurrency — no duplicate job ids under parallel submit ----
def test_runner_submit_is_threadsafe():
    from health_check.web.runner import JobRunner

    r = JobRunner()
    ids: list[str] = []
    lock = threading.Lock()

    def worker():
        # empty step list -> the worker finishes the job without launching
        # any subprocess, so this stays a pure concurrency test.
        job = r.submit("t", [])
        with lock:
            ids.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ids) == 40
    assert len(set(ids)) == 40, "duplicate job ids minted under concurrent submit"


# ---- D3: atomic master_report.json write ----
def test_atomic_write_json_writes_and_leaves_no_tmp(tmp_path):
    from health_check.orchestration import master

    target = tmp_path / "master_report.json"
    master._atomic_write_json(target, {"a": 1, "b": [2, 3]})

    assert json.loads(target.read_text()) == {"a": 1, "b": [2, 3]}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "master_report.json"]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_atomic_write_json_failure_does_not_clobber_or_leak(tmp_path):
    from health_check.orchestration import master

    target = tmp_path / "master_report.json"
    target.write_text('{"good": true}')

    # A set isn't JSON-serialisable -> json.dump raises mid-write.
    with pytest.raises(TypeError):
        master._atomic_write_json(target, {"bad": {1, 2, 3}})

    # Original file is untouched (write was atomic) and no .tmp file remains.
    assert json.loads(target.read_text()) == {"good": True}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "master_report.json"]
    assert leftovers == [], f"temp files left behind: {leftovers}"


# ---- D4: /run validates the request body ----
@pytest.mark.parametrize("body,ctype", [
    ("not json at all", "application/json"),
    ("[1, 2, 3]", "application/json"),         # valid JSON, but not an object
    ("", "application/json"),
])
def test_run_rejects_bad_body(body, ctype):
    from health_check.web import app as web_app

    client = web_app.create_app().test_client()
    resp = client.post("/run", data=body, content_type=ctype)
    assert resp.status_code == 400


def test_run_unknown_kind_still_400():
    from health_check.web import app as web_app

    client = web_app.create_app().test_client()
    resp = client.post("/run", json={"kind": "nonsense"})
    assert resp.status_code == 400


# ---- D2: /report & /verdicts degrade to 503 (not 500) on unreadable report ----
def test_verdicts_returns_503_on_corrupt_report(monkeypatch, tmp_path):
    from health_check import paths
    from health_check.web import app as web_app

    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "master_report.json").write_text("{ this is not valid json ")

    client = web_app.create_app().test_client()
    resp = client.get("/verdicts")
    assert resp.status_code == 503


def test_report_returns_503_when_unreadable(monkeypatch, tmp_path):
    from health_check import paths
    from health_check.web import app as web_app

    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    # A *directory* named like the report makes read_text() raise OSError,
    # exercising the try/except path without a real race.
    (tmp_path / "master_report.json").mkdir()

    client = web_app.create_app().test_client()
    resp = client.get("/report")
    assert resp.status_code == 503


# ---- D6: LIVENESS_URLS is lazy, not an import-time global ----
def test_liveness_urls_is_lazy():
    from health_check.orchestration import master

    assert not hasattr(master, "LIVENESS_URLS"), "registry still loaded at import time"
    assert callable(master.get_liveness_urls)
    # Cached: same object across calls.
    assert master.get_liveness_urls() is master.get_liveness_urls()


# ---- D7: non-loopback host detection ----
@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True),
    ("localhost", True),
    ("::1", True),
    ("0.0.0.0", False),
    ("192.168.1.10", False),
    ("10.0.0.5", False),
])
def test_is_loopback(host, expected):
    from health_check.web import app as web_app

    assert web_app._is_loopback(host) is expected
