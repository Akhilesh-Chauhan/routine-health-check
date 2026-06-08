"""Liveness-only projects (no functional check mapping) still get a runnable
Liveness action from their web-panel tile.

UMANG Production is monitored by the HTTP liveness sweep only — it has no
entry in projects.PROJECT_CHECKS. The tile must still offer a Liveness run
instead of dead-ending at "No check mapping".
"""
from health_check.web.app import _plan
from health_check.web import projects


LIVENESS_ONLY = "UMANG Production"


def test_liveness_only_project_is_not_mapped():
    # Guard the premise: this project intentionally has no functional checks.
    assert LIVENESS_ONLY not in projects.PROJECT_CHECKS


def test_liveness_only_project_liveness_mode_runs_liveness():
    title, steps = _plan("project", LIVENESS_ONLY, "liveness")
    assert LIVENESS_ONLY in title
    assert len(steps) == 1
    assert steps[0].label == "hc liveness"


def test_liveness_only_project_all_mode_runs_liveness_only():
    title, steps = _plan("project", LIVENESS_ONLY, "all")
    # No functional checks exist, so "all" collapses to just the liveness step.
    assert [s.label for s in steps] == ["hc liveness"]


def test_liveness_only_project_functional_mode_is_empty():
    # Nothing functional to run -> empty plan (button wouldn't be rendered).
    title, steps = _plan("project", LIVENESS_ONLY, "functional")
    assert steps == []


def test_mapped_project_still_runs_functional_checks():
    # Regression guard: a normal mapped project is unaffected.
    title, steps = _plan("project", "CMS", "functional")
    labels = [s.label for s in steps]
    assert "hc check cms" in labels
