"""Domain roll-up semantics for the dev + UMANG multi-check scripts.

`aggregate_verdict` collapses a domain's sub-checks to a single verdict using
the single status vocabulary (UP, not HEALTHY).
"""
from __future__ import annotations

import pytest

from health_check.checks.dev import environment as dev
from health_check.checks.umang import integration as umang


@pytest.mark.parametrize("agg", [dev.aggregate_verdict, umang.aggregate_verdict])
class TestAggregateVerdict:
    def test_all_up_is_up(self, agg):
        assert agg([{"verdict": "UP"}, {"verdict": "UP"}]) == "UP"

    def test_any_down_is_down(self, agg):
        assert agg([{"verdict": "UP"}, {"verdict": "DOWN"}]) == "DOWN"

    def test_degraded_is_degraded(self, agg):
        assert agg([{"verdict": "UP"}, {"verdict": "DEGRADED"}]) == "DEGRADED"
