import json
from health_check.reporting.status import Verdict


def test_verdict_is_str_compatible():
    assert Verdict.UP == "UP"
    assert Verdict.DOWN in ("DOWN", "FAILED")
    assert Verdict.UP.upper() == "UP"


def test_verdict_serialises_as_plain_string():
    assert json.dumps({"verdict": Verdict.UP}) == '{"verdict": "UP"}'


def test_all_members_present():
    assert {v.value for v in Verdict} == {
        "UP", "DOWN", "DEGRADED", "AUTH_EXPIRED", "KNOWN-ISSUE",
        "SLOW", "PASS", "PASSED", "MISSING", "TIMEOUT", "ERROR",
    }
