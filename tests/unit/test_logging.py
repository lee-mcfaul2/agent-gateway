from __future__ import annotations

import json

from ag_gateway.obs.logging import get_logger, setup_logging


def test_setup_emits_json(capsys: object) -> None:
    setup_logging("info", "test-service")
    log = get_logger("t")
    log.info("hello", k=1)
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = captured.err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["k"] == 1
    assert record["service"] == "test-service"


def test_setup_is_idempotent() -> None:
    setup_logging("info", "test-service")
    setup_logging("info", "test-service")
    # no exception
