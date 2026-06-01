"""Tests for the unified verdict classifier (spec D13).

One canonical verdict->{up,warn,down,unknown} mapping lives in
`reporting/verdicts.py`. It must reproduce the behaviour that previously
lived (divergently) in the dashboard template JS and in web/app.py's
private `_classify`, and it must emit a JS function whose branches mirror
the Python ones exactly.
"""
from __future__ import annotations

import re

import pytest

from health_check.reporting import verdicts


@pytest.mark.parametrize("raw,expected", [
    # up
    ("UP", "up"),
    ("HEALTHY", "up"),
    ("HEALTHY (all bots UP)", "up"),
    ("PASS", "up"),
    ("PASSED", "up"),
    # warn
    ("DEGRADED", "warn"),
    ("DEGRADED (some bots DOWN)", "warn"),   # warn must win over the DOWN substring
    ("AUTH_EXPIRED", "warn"),
    ("AUTH_EXPIRED (sign-in required — not a service outage)", "warn"),
    ("SLOW", "warn"),
    # down
    ("DOWN", "down"),
    ("FAIL", "down"),
    ("FAILED", "down"),
    ("TIMEOUT", "down"),
    ("ERROR", "down"),
    ("MISSING", "down"),
    # unknown — faithful to the prior classifiers, which matched ERROR/TIMEOUT/
    # MISSING only as EXACT verdicts (script/leaf verdicts are exact; the
    # "ERROR: ..." form only ever appears on the separate auth-probe signal).
    ("ERROR: ConnectionRefused", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
    ("WAT", "unknown"),
])
def test_classify(raw, expected):
    assert verdicts.classify(raw) == expected


def test_classify_is_case_insensitive():
    assert verdicts.classify("healthy") == "up"
    assert verdicts.classify("degraded") == "warn"
    assert verdicts.classify("down") == "down"


def test_degraded_beats_down_substring():
    # The single most important ordering guarantee: a verdict that mentions
    # both DEGRADED and DOWN is a warn, not a down (matches prior dashboard
    # + app.py behaviour for "DEGRADED (some bots DOWN)").
    assert verdicts.classify("DEGRADED (some bots DOWN)") == "warn"


def test_js_classifier_matches_python_for_known_verdicts():
    """The emitted JS must be a faithful transcription. We can't run JS here,
    but we can confirm the emitted function references every bucket and the
    same token set the Python rules use, and is syntactically a single fn."""
    js = verdicts.js_classifier("classifyVerdict")
    assert js.startswith("function classifyVerdict(")
    for bucket in ("up", "warn", "down", "unknown"):
        assert f'"{bucket}"' in js
    # Every token used by the Python rules must appear in the JS source.
    for _bucket, _kind, tokens in verdicts._RULES:
        for tok in tokens:
            assert tok in js, f"token {tok!r} missing from emitted JS"
    # Custom function name is honoured.
    assert "function liveClass(" in verdicts.js_classifier("liveClass")
