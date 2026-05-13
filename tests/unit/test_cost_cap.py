from __future__ import annotations

import pytest

from ag_gateway.hooks.cost_cap import CostCap, CostCapExceeded, CostMeter


def test_under_cap_no_exception() -> None:
    meter = CostMeter()
    meter.record("p1", "alice", 0.10)
    meter.check("p1", "alice", CostCap(max_usd=1.00))


def test_over_cap_raises() -> None:
    meter = CostMeter()
    for _ in range(11):
        meter.record("p1", "alice", 0.10)
    with pytest.raises(CostCapExceeded):
        meter.check("p1", "alice", CostCap(max_usd=1.00))


def test_caps_isolated_per_user() -> None:
    meter = CostMeter()
    meter.record("p1", "alice", 0.99)
    meter.check("p1", "alice", CostCap(max_usd=1.00))
    meter.check("p1", "bob", CostCap(max_usd=1.00))
