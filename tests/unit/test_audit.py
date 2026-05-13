from __future__ import annotations

import pytest

from ag_gateway.hooks.audit import AuditEvent, AuditLogger, AuditWriteError


@pytest.fixture
def small_logger(monkeypatch: pytest.MonkeyPatch) -> AuditLogger:
    """A logger that never starts the pool — so .log() exercises the queue only."""
    return AuditLogger("postgresql://stub", queue_size=2)


async def test_log_enqueues(small_logger: AuditLogger) -> None:
    await small_logger.log(AuditEvent(event_type="request"))
    assert small_logger._queue.qsize() == 1


async def test_queue_full_raises(small_logger: AuditLogger) -> None:
    await small_logger.log(AuditEvent(event_type="a"))
    await small_logger.log(AuditEvent(event_type="b"))
    with pytest.raises(AuditWriteError):
        await small_logger.log(AuditEvent(event_type="c"))
