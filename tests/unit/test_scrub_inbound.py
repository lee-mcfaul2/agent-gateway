from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.scrub_inbound import REDACTION_MARKER, scrub_inbound
from ag_gateway.schemas.scrub_categories import ScrubCatalog


class _StubPresidio:
    def analyze(self, text: str, language: str = "en") -> list[object]:
        return []


class _FakeTokenizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def tokenize(self, request_uuid: str, type_: str, plaintext: str) -> str:
        self.calls.append((request_uuid, type_, plaintext))
        return f"TOKEN_{type_}_ABC"


@pytest.fixture
def engine(tmp_path: Path) -> ScrubEngine:
    p = tmp_path / "schemas" / "shared"
    p.mkdir(parents=True)
    (p / "scrub-types.json").write_text(  # noqa: E501
        json.dumps(
            {
                "categories": [
                    {
                        "name": "EMAIL",
                        "severity": "pii",
                        "patterns": [r"\b\S+@\S+\.\S+\b"],
                    },
                    {
                        "name": "SECRET_API_KEY",
                        "severity": "secret",
                        "patterns": [r"sk-[A-Za-z0-9]+"],
                    },
                    {
                        "name": "CODEWORD_PROJECT",
                        "severity": "codeword",
                        "patterns": [r"\bFalcon\b"],
                    },
                ]
            }
        )
    )
    return ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_StubPresidio())  # type: ignore[arg-type]


async def test_pii_is_tokenized(engine: ScrubEngine) -> None:
    tok = _FakeTokenizer()
    res = await scrub_inbound("mail alice@example.com please", "req-1", engine, tok)  # type: ignore[arg-type]
    assert "TOKEN_EMAIL_ABC" in res.scrubbed_text
    assert tok.calls == [("req-1", "EMAIL", "alice@example.com")]
    assert res.secret_events == []


async def test_codeword_is_redacted(engine: ScrubEngine) -> None:
    tok = _FakeTokenizer()
    res = await scrub_inbound("about Falcon project", "req-1", engine, tok)  # type: ignore[arg-type]
    assert REDACTION_MARKER in res.scrubbed_text
    assert res.secret_events == []


async def test_secret_is_redacted_and_surfaced(engine: ScrubEngine) -> None:
    tok = _FakeTokenizer()
    res = await scrub_inbound(
        "my key sk-ABC123 today", "req-1", engine, tok  # type: ignore[arg-type]
    )
    assert "sk-ABC123" not in res.scrubbed_text
    assert REDACTION_MARKER in res.scrubbed_text
    assert len(res.secret_events) == 1
    ev = res.secret_events[0]
    assert ev.category == "SECRET_API_KEY"
    assert "sk-ABC123" not in ev.text_with_redaction


async def test_mixed_categories(engine: ScrubEngine) -> None:
    tok = _FakeTokenizer()
    res = await scrub_inbound(
        "user alice@example.com asks about Falcon with sk-A1B2C3",
        "req-1",
        engine,
        tok,  # type: ignore[arg-type]
    )
    assert "TOKEN_EMAIL_ABC" in res.scrubbed_text
    assert res.scrubbed_text.count(REDACTION_MARKER) >= 2
    assert any(e.category == "SECRET_API_KEY" for e in res.secret_events)
