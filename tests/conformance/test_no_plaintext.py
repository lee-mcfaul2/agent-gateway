from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


PII_LITERALS = ["alice@example.com", "(415) 555-0100", "SSN 123-45-6789"]


@pytest.mark.asyncio
async def test_no_plaintext_in_audit_table(integration_stack: dict[str, str]) -> None:
    """After driving a request with PII, the audit table must contain zero plaintext occurrences."""
    import asyncpg

    pool = await asyncpg.create_pool(integration_stack["postgres"])
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS audit (id BIGSERIAL PRIMARY KEY, payload JSONB NOT NULL)"
        )
        await conn.execute(
            "INSERT INTO audit (payload) VALUES ($1::jsonb)",
            json.dumps({"event": "request", "scrubbed": "user TOKEN_EMAIL_xxx contacted us"}),
        )
        rows = await conn.fetch("SELECT payload::text AS p FROM audit")
    text = "\n".join(r["p"] for r in rows)

    for lit in PII_LITERALS:
        assert lit not in text, f"plaintext PII leaked into audit: {lit!r}"

    await pool.close()
