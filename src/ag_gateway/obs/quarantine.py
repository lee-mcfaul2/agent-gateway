from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import asyncpg

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS quarantine (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_uuid UUID NOT NULL,
    user_sub TEXT NOT NULL,
    prompt_uuid UUID,
    reason TEXT NOT NULL,
    category TEXT,
    snapshot JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS quarantine_ts_idx ON quarantine (ts DESC);
CREATE INDEX IF NOT EXISTS quarantine_user_sub_idx ON quarantine (user_sub, ts DESC);
"""


@dataclass
class QuarantineRecord:
    request_uuid: str
    user_sub: str
    reason: str
    snapshot: dict[str, Any]
    prompt_uuid: str | None = None
    category: str | None = None


class QuarantineError(Exception):
    pass


class QuarantineStore:
    """Synchronous-write quarantine. Failure = 500 to caller."""

    def __init__(self, dsn: str, snapshot_max_bytes: int = 256 * 1024) -> None:
        self._dsn = dsn
        self._max_bytes = snapshot_max_bytes
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)

    async def stop(self) -> None:
        if self._pool:
            await self._pool.close()

    async def write(self, record: QuarantineRecord) -> int:
        if self._pool is None:
            raise QuarantineError("not started")

        snapshot_json = self._trim(record.snapshot)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO quarantine (
                    request_uuid, user_sub, prompt_uuid, reason, category, snapshot
                )
                VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6::jsonb)
                RETURNING id
                """,
                record.request_uuid,
                record.user_sub,
                record.prompt_uuid,
                record.reason,
                record.category,
                snapshot_json,
            )
        return int(row["id"])

    def _trim(self, snapshot: dict[str, Any]) -> str:
        s = json.dumps(snapshot)
        if len(s.encode("utf-8")) <= self._max_bytes:
            return s
        return json.dumps(
            {
                "_truncated": True,
                "_original_bytes": len(s.encode("utf-8")),
                "head": s[: self._max_bytes - 256],
            }
        )
