"""Tests for the dashboard staleness fix.

Background: the dashboard is generated from master_report.json (the full
functional sweep). Recovery, however, is detected by the liveness monitor,
which writes liveness_latest.json and never rebuilds the dashboard. So a
recovered URL kept showing DOWN on the dashboard until the next full sweep.

These tests pin the fix: the dashboard must fold in the *fresher*
liveness_latest.json (sitting next to the report) so a recovery is visible
without waiting for a full sweep.
"""
from __future__ import annotations

import json

from health_check.orchestration import dashboard


def _write(p, obj):
    p.write_text(json.dumps(obj))


def test_dashboard_injects_fresh_liveness_latest(tmp_path):
    """`dashboard.main` folds liveness_latest.json (beside the report) into
    the embedded page data, so the dashboard reflects the latest HTTP probe
    rather than only the (older) liveness block frozen in the sweep report."""
    report = tmp_path / "master_report.json"
    out = tmp_path / "dashboard.html"

    # Full sweep snapshot — taken DURING an outage (UMANG URLs DOWN).
    _write(report, {
        "started_ist": "2026-05-29T11:01:15+05:30",
        "ended_ist":   "2026-05-29T11:10:00+05:30",
        "scripts": [],
        "liveness": {
            "results": [
                {"url": "https://myapp.umangapp.in/", "status": "DOWN", "http": 503},
            ],
            "counts": {"UP": 0, "SLOW": 0, "DOWN": 1},
        },
    })

    # Liveness monitor ran LATER and saw UMANG recover (HTTP 200, UP).
    _write(tmp_path / "liveness_latest.json", {
        "checked_ist": "2026-05-29T12:07:30+05:30",
        "results": [
            {"url": "https://myapp.umangapp.in/", "status": "UP", "http": 200},
        ],
        "counts": {"UP": 1, "SLOW": 0, "DOWN": 0},
    })

    dashboard.main(["--report", str(report), "--out", str(out)])
    html = out.read_text()

    # The fresher liveness probe (and its timestamp) must reach the page.
    assert "liveness_latest" in html, "liveness_latest.json was not injected into the dashboard data"
    assert "2026-05-29T12:07:30+05:30" in html, "fresh liveness checked_ist missing from dashboard"


def test_fresher_probe_becomes_authoritative_liveness():
    """When the standalone probe is newer than the sweep, it replaces the
    sweep's liveness block so the reachability bar + overall verdict reflect
    the recovery — while the sweep's own liveness is preserved for reference."""
    data = {
        "ended_ist": "2026-05-29T11:10:00+05:30",
        "liveness": {"results": [{"url": "u", "status": "DOWN"}],
                     "counts": {"UP": 0, "SLOW": 0, "DOWN": 1}},
    }
    probe = {
        "checked_ist": "2026-05-29T12:07:30+05:30",
        "results": [{"url": "u", "status": "UP"}],
        "counts": {"UP": 1, "SLOW": 0, "DOWN": 0},
    }

    dashboard._apply_fresh_liveness(data, probe)

    assert data["liveness"]["counts"]["DOWN"] == 0, "recovery not reflected in authoritative liveness"
    assert data["liveness"]["counts"]["UP"] == 1
    assert data["liveness_is_fresh"] is True
    assert data["liveness_checked_ist"] == "2026-05-29T12:07:30+05:30"
    # The sweep's own liveness must be preserved (not lost).
    assert data["liveness_sweep"]["counts"]["DOWN"] == 1


def test_stale_probe_does_not_override_newer_sweep():
    """A probe OLDER than the sweep must not replace fresher sweep data
    (no regressing the dashboard to older liveness)."""
    data = {
        "ended_ist": "2026-05-29T12:25:00+05:30",
        "liveness": {"results": [{"url": "u", "status": "UP"}],
                     "counts": {"UP": 1, "SLOW": 0, "DOWN": 0}},
    }
    probe = {
        "checked_ist": "2026-05-29T11:00:00+05:30",   # older than the sweep
        "results": [{"url": "u", "status": "DOWN"}],
        "counts": {"UP": 0, "SLOW": 0, "DOWN": 1},
    }

    dashboard._apply_fresh_liveness(data, probe)

    assert data["liveness"]["counts"]["UP"] == 1, "stale probe wrongly overrode newer sweep"
    assert data["liveness_is_fresh"] is False


def _stub_monitor(monkeypatch, tmp_path, prev_state, sweep):
    """Wire liveness_monitor for an offline run: temp state files, no SMTP,
    and a controlled sweep result. Returns the module and a rebuild-call log."""
    from health_check.orchestration import liveness_monitor as lm
    monkeypatch.setattr(lm, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(lm, "LATEST", str(tmp_path / "latest.json"))
    monkeypatch.setattr(lm, "send_email", lambda *a, **k: None)
    monkeypatch.setattr(lm.m, "liveness_sweep", lambda: sweep)
    (tmp_path / "state.json").write_text(json.dumps(prev_state))
    calls = []
    monkeypatch.setattr(lm, "_rebuild_dashboard", lambda: calls.append(1))
    return lm, calls


def test_liveness_monitor_rebuilds_dashboard_on_recovery(monkeypatch, tmp_path):
    """A URL recovering (DOWN->UP) must rebuild the dashboard so the recovery
    shows up without waiting for the next full sweep."""
    lm, calls = _stub_monitor(
        monkeypatch, tmp_path,
        prev_state={"https://x/": "DOWN"},
        sweep={"results": [{"url": "https://x/", "status": "UP", "label": "X",
                            "http": 200, "ms": 10}],
               "counts": {"UP": 1, "SLOW": 0, "DOWN": 0}},
    )
    lm.main()
    assert calls == [1], "recovery should trigger exactly one dashboard rebuild"


def test_liveness_monitor_skips_rebuild_when_unchanged(monkeypatch, tmp_path):
    """No state change => no rebuild (don't churn the dashboard every cron tick)."""
    lm, calls = _stub_monitor(
        monkeypatch, tmp_path,
        prev_state={"https://x/": "UP"},
        sweep={"results": [{"url": "https://x/", "status": "UP", "label": "X",
                            "http": 200, "ms": 10}],
               "counts": {"UP": 1, "SLOW": 0, "DOWN": 0}},
    )
    lm.main()
    assert calls == [], "unchanged liveness should not rebuild the dashboard"


def test_verdicts_endpoint_uses_fresh_liveness(monkeypatch, tmp_path):
    """The web overview (/verdicts) must fold in the fresher probe too, so it
    doesn't disagree with the dashboard about whether a URL has recovered."""
    from health_check import paths
    from health_check.web import app as web_app

    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    _write(tmp_path / "master_report.json", {
        "started_ist": "2026-05-29T11:01:00+05:30",
        "ended_ist":   "2026-05-29T11:10:00+05:30",
        "scripts": [],
        "liveness": {"results": [{"url": "https://myapp.umangapp.in/", "status": "DOWN"}],
                     "counts": {"UP": 0, "SLOW": 0, "DOWN": 1}},
    })
    _write(tmp_path / "liveness_latest.json", {
        "checked_ist": "2026-05-29T12:30:00+05:30",
        "results": [{"url": "https://myapp.umangapp.in/", "status": "UP"}],
        "counts": {"UP": 1, "SLOW": 0, "DOWN": 0},
    })

    client = web_app.create_app().test_client()
    body = client.get("/verdicts").get_json()

    assert body["liveness_counts"].get("DOWN") == 0, "overview used stale sweep liveness, not the fresh probe"
