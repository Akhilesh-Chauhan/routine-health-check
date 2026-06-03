"""Panel /verdicts must show each project's OWN status, in sync with the
dashboard — not a shared check's aggregate.

Regression: the five chatbot projects all map to the single `chatbots` check.
Its aggregate verdict goes DEGRADED when ANY one bot is down, which used to
paint all five tiles degraded even though the dashboard (per-bot) showed the
healthy ones UP. Each tile must instead reflect its own bot (matched by URL).
"""
from __future__ import annotations

import json

from health_check import paths
from health_check.web import app as web_app


def _verdicts(monkeypatch, tmp_path, report):
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "master_report.json").write_text(json.dumps(report))
    return web_app.create_app().test_client().get("/verdicts").get_json()


def test_chatbot_tiles_reflect_their_own_bot(monkeypatch, tmp_path):
    # One bot down, the rest up — exactly the situation that mis-painted tiles.
    report = {
        "started_ist": "2026-06-01T10:00:00+05:30",
        "ended_ist": "2026-06-01T10:08:00+05:30",
        "liveness": {"results": [], "counts": {"UP": 0, "SLOW": 0, "DOWN": 0}},
        "scripts": [{
            "label": "Public — 6 standalone bots",
            "filename": "health_check.checks.public.chatbots",
            "duration_s": 60.0,
            "verdict": "DEGRADED (one or more bots unresponsive)",
            "payload": {"bots": [
                {"name": "D.o.E Sahayak", "url": "https://doe.myscheme.in/", "verdict": "DOWN"},
                {"name": "PSQ", "url": "https://psq.myscheme.in/", "verdict": "UP"},
                {"name": "Sandarbh", "url": "https://sandarbh.myscheme.in/", "verdict": "UP"},
                {"name": "NMC", "url": "https://nmc.myscheme.in/", "verdict": "UP"},
                {"name": "TATHYA (PIB)", "url": "https://pib.myscheme.in/", "verdict": "UP"},
                {"name": "SAI Sahayak", "url": "https://sports-psq.myscheme.in/", "verdict": "DOWN"},
            ]},
        }],
    }
    v = _verdicts(monkeypatch, tmp_path, report)
    proj = v["projects"]
    # Only the genuinely-down bots' tiles are down; the rest are UP (in sync
    # with the dashboard) — NOT all six degraded from the aggregate.
    assert proj["DoE Chatbot"] == "DOWN"
    assert proj["PSQ Chatbot"] == "UP"
    assert proj["Sandarbh Chatbot"] == "UP"
    assert proj["NMC Chatbot"] == "UP"
    assert proj["TATHYA (PIB) Chatbot"] == "UP"
    # The sixth bot now has its own tile (was previously invisible).
    assert proj["SAI Sahayak Chatbot"] == "DOWN"
    # The aggregate check verdict is still reported (one bot really is down).
    assert v["checks"]["chatbots"].upper().startswith("DEGRADED")


def test_dedicated_check_still_uses_aggregate(monkeypatch, tmp_path):
    # A check serving ONE project keeps using its aggregate verdict (no regress).
    report = {
        "started_ist": "2026-06-01T10:00:00+05:30",
        "ended_ist": "2026-06-01T10:08:00+05:30",
        "liveness": {"results": [], "counts": {"UP": 0, "SLOW": 0, "DOWN": 0}},
        "scripts": [{
            "label": "Prod — cms workspace",
            "filename": "health_check.checks.prod.cms",
            "duration_s": 30.0,
            "verdict": "UP",
            "payload": {"steps": [{"name": "Dashboard", "verdict": "UP"}]},
        }],
    }
    v = _verdicts(monkeypatch, tmp_path, report)
    assert v["projects"]["CMS"] == "UP"
