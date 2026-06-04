"""A single `hc check <name>` must update master_report.json so the dashboard
and the web overview reflect it — previously only a full `hc sweep` did.
"""
from __future__ import annotations

import json

from health_check import paths
from health_check.orchestration import master
from health_check.web import app as web_app


def test_derive_verdict():
    assert master.derive_verdict({"overall": "HEALTHY"}, 0) == "HEALTHY"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "UP"}]}, 0) == "HEALTHY"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DEGRADED (some bots DOWN)"
    assert master.derive_verdict({"steps": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DOWN"
    assert master.derive_verdict(None, 0) == "PASSED"
    assert master.derive_verdict(None, 1) == "FAILED"


def test_single_check_merges_and_overview_reflects_it(monkeypatch, tmp_path):
    rep = tmp_path / "master_report.json"
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "MASTER_REPORT", rep)

    # Last sweep recorded SAI Sahayak DOWN.
    rep.write_text(json.dumps({
        "started_ist": "2026-06-01T10:00:00+05:30",
        "ended_ist": "2026-06-01T10:08:00+05:30",
        "liveness": {"results": [], "counts": {"UP": 0, "SLOW": 0, "DOWN": 0}},
        "scripts": [{
            "label": "Public — 6 standalone bots",
            "filename": "health_check.checks.public.chatbots",
            "verdict": "DEGRADED (some bots DOWN)", "duration_s": 60.0, "exit_code": 0,
            "payload": {"bots": [
                {"name": "DoE", "url": "https://doe.myscheme.in/", "verdict": "UP"},
                {"name": "SAI", "url": "https://sports-psq.myscheme.in/", "verdict": "DOWN"},
            ]},
        }],
    }))

    client = web_app.create_app().test_client()
    assert client.get("/verdicts").get_json()["projects"]["SAI Sahayak Chatbot"] == "DOWN"

    # SAI recovered — a single `hc check chatbots` (its captured stdout) merges in.
    new_stdout = "noise...\n" + json.dumps({
        "bots": [
            {"name": "DoE", "url": "https://doe.myscheme.in/", "verdict": "UP"},
            {"name": "SAI", "url": "https://sports-psq.myscheme.in/", "verdict": "UP"},
        ]
    })
    verdict = master.merge_script_result("health_check.checks.public.chatbots", new_stdout, 0, 1.2)
    assert verdict == "HEALTHY"

    # The overview now reflects the single run — no full sweep needed.
    proj = client.get("/verdicts").get_json()["projects"]
    assert proj["SAI Sahayak Chatbot"] == "UP", "overview did not pick up the single check run"
    # And the report kept a single chatbots entry (replaced in place, not duplicated).
    scripts = json.loads(rep.read_text())["scripts"]
    assert sum(1 for s in scripts if s["filename"].endswith("chatbots")) == 1
