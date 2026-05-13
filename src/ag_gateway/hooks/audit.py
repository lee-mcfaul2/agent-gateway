from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from ag_gateway.obs.logging import get_logger

log = get_logger(__name__)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    request_uuid UUID,
    user_sub TEXT,
    prompt_uuid UUID,
    mcp TEXT,
    tool TEXT,
    outcome TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_ts_idx ON audit (ts DESC);
CREATE INDEX IF NOT EXISTS audit_user_sub_idx ON audit (user_sub, ts DESC);
CREATE INDEX IF NOT EXISTS audit_event_type_idx ON audit (event_type, ts DESC);
"""


@dataclass
class AuditEvent:
    event_type: str
    request_uuid: str | None = None
    user_sub: str | None = None
    prompt_uuid: str | None = None
    mcp: str | None = None
    tool: str | None = None
    outcome: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class AuditWriteError(Exception):
    """Audit DB unreachable / unwritable beyond the buffer."""


class AuditLogger:
    """Async audit logger with a bounded in-memory queue."""

    def __init__(self, dsn: str, queue_size: int = 1024) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pool:
            await self._pool.close()

    async def log(self, event: AuditEvent) -> None:
        """Enqueue an audit event. Raises AuditWriteError if the queue is full."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            raise AuditWriteError("audit queue full") from exc

    async def _drain(self) -> None:
        assert self._pool is not None
        while True:
            event = await self._queue.get()
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO audit (event_type, request_uuid, user_sub, prompt_uuid,
                                           mcp, tool, outcome, payload)
                        VALUES ($1, $2::uuid, $3, $4::uuid, $5, $6, $7, $8::jsonb)
                        """,
                        event.event_type,
                        event.request_uuid,
                        event.user_sub,
                        event.prompt_uuid,
                        event.mcp,
                        event.tool,
                        event.outcome,
                        json.dumps(event.payload),
                    )
            except Exception as exc:
                log.error("audit.write_failed", err=str(exc))
                await asyncio.sleep(1.0)
