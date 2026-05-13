from __future__ import annotations

import json

from ag_gateway.obs.quarantine import QuarantineStore


def test_trim_under_limit() -> None:
    store = QuarantineStore("postgresql://stub", snapshot_max_bytes=1000)
    s = store._trim({"a": "x"})
    assert json.loads(s) == {"a": "x"}


def test_trim_over_limit() -> None:
    store = QuarantineStore("postgresql://stub", snapshot_max_bytes=64)
    huge = {"a": "x" * 1000}
    s = store._trim(huge)
    data = json.loads(s)
    assert data["_truncated"] is True
    assert data["_original_bytes"] > 64
