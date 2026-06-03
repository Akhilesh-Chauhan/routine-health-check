"""Parity gate: locks the PURE report-processing behaviour (no browser/network)
so Phases 1-4 can refactor underneath without changing observable output.

If a refactor is meant to preserve behaviour and one of these fails, the refactor
changed something. If a change is intentional, update the golden values in the
SAME commit with a message explaining the behaviour change.
"""
from __future__ import annotations

from pathlib import Path

from health_check import paths
from health_check.orchestration import master
from health_check.reporting import verdicts
from health_check.web import app as web_app

FIXTURE = Path(__file__).parent / "fixtures" / "golden_master_report.json"


def test_classify_corpus_is_stable():
    corpus = ["UP", "DOWN", "DEGRADED", "DEGRADED (some bots DOWN)",
              "AUTH_EXPIRED", "SLOW", "PASS", "PASSED", "KNOWN-ISSUE",
              "TIMEOUT", "ERROR", "MISSING", "", "WAT"]
    got = {v: verdicts.classify(v) for v in corpus}
    assert got == {
        "UP": "up", "DOWN": "down", "DEGRADED": "warn",
        "DEGRADED (some bots DOWN)": "warn", "AUTH_EXPIRED": "warn",
        "SLOW": "warn", "PASS": "up", "PASSED": "up", "KNOWN-ISSUE": "unknown",
        "TIMEOUT": "down", "ERROR": "down", "MISSING": "down",
        "": "unknown", "WAT": "unknown",
    }


def test_derive_verdict_is_stable():
    assert master.derive_verdict({"overall": "UP"}, 0) == "UP"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "UP"}]}, 0) == "UP"
    assert master.derive_verdict({"steps": [{"verdict": "UP"}, {"verdict": "UP"}]}, 0) == "UP"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DEGRADED (some bots DOWN)"
    assert master.derive_verdict({"steps": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DOWN"


def test_verdicts_endpoint_rollup_is_stable(monkeypatch, tmp_path):
    rep = tmp_path / "master_report.json"
    rep.write_text(FIXTURE.read_text())
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    data = web_app.create_app().test_client().get("/verdicts").get_json()
    # _walk_leaves only counts top-level steps/bots verdicts (nested `checks` are
    # NOT walked), which is why total=7 rather than the deeper leaf count.
    assert data["summary"] == {"up": 3, "warn": 1, "down": 2, "total": 7}
    assert data["checks"]["myscheme"] == "UP"
    assert data["checks"]["devenv"] == "DOWN"
    assert data["checks"]["umang"] == "AUTH_EXPIRED"


def test_js_classifier_snapshot_matches_rules():
    # Locks the Python->JS transcription of the verdict classifier so the
    # emitted client-side function can't silently drift from the Python rules.
    expected = (
        'function classifyVerdict(v) {\n'
        '  if (!v) return "unknown";\n'
        '  const s = String(v).toUpperCase();\n'
        '  if (s.includes("HEALTHY")) return "up";\n'
        '  if (s === "UP" || s === "PASS" || s === "PASSED") return "up";\n'
        '  if (s.includes("AUTH_EXPIRED") || s.includes("DEGRADED")) return "warn";\n'
        '  if (s === "SLOW") return "warn";\n'
        '  if (s === "TIMEOUT" || s === "ERROR" || s === "MISSING") return "down";\n'
        '  if (s.includes("DOWN") || s.includes("FAIL")) return "down";\n'
        '  return "unknown";\n'
        '}'
    )
    assert verdicts.js_classifier("classifyVerdict") == expected
