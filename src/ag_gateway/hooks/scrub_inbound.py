from __future__ import annotations

from dataclasses import dataclass, field

from ag_gateway.hooks.scrub_engine import Detection, ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import (
    REDACTIONS_TOTAL,
    SECRET_EXFIL_TOTAL,
    TOKENS_GENERATED_TOTAL,
)

log = get_logger(__name__)

REDACTION_MARKER = "[REDACTED]"


@dataclass
class SecretEvent:
    category: str
    text_with_redaction: str


@dataclass
class ScrubResult:
    scrubbed_text: str
    secret_events: list[SecretEvent] = field(default_factory=list)


async def scrub_inbound(
    text: str,
    request_uuid: str,
    engine: ScrubEngine,
    tokenizer: TokenizerClient,
) -> ScrubResult:
    """Scrub `text`. Tokenize PII via tokenizer; redact CODEWORD/SECRET."""
    detections = engine.scan(text)
    detections.sort(key=lambda d: d.start)

    out: list[str] = []
    cursor = 0
    secret_events: list[SecretEvent] = []

    for det in detections:
        out.append(text[cursor : det.start])
        replacement = await _apply_one(text, det, request_uuid, tokenizer)
        out.append(replacement)
        if det.category.severity == "secret":
            secret_events.append(
                SecretEvent(
                    category=det.category.name,
                    text_with_redaction=_redact_one_span(text, det, REDACTION_MARKER),
                )
            )
        cursor = det.end

    out.append(text[cursor:])
    return ScrubResult(scrubbed_text="".join(out), secret_events=secret_events)


async def _apply_one(
    text: str, det: Detection, request_uuid: str, tokenizer: TokenizerClient
) -> str:
    span_text = text[det.start : det.end]
    if det.category.severity == "pii":
        token = await tokenizer.tokenize(request_uuid, det.category.name, span_text)
        TOKENS_GENERATED_TOTAL.labels(category=det.category.name).inc()
        return token
    if det.category.severity == "codeword":
        REDACTIONS_TOTAL.labels(category=det.category.name).inc()
        return REDACTION_MARKER
    SECRET_EXFIL_TOTAL.labels(category=det.category.name).inc()
    return REDACTION_MARKER


def _redact_one_span(text: str, det: Detection, marker: str) -> str:
    return text[: det.start] + marker + text[det.end :]
