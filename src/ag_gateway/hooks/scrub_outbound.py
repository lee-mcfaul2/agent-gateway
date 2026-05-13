from __future__ import annotations

from dataclasses import dataclass, field

from ag_gateway.hooks.scrub_engine import Detection, ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import (
    REDACTIONS_TOTAL,
    SCRUB_FAILURES_TOTAL,
    TOKENS_GENERATED_TOTAL,
)

log = get_logger(__name__)

REDACTION_MARKER = "[REDACTED]"


@dataclass
class OutboundSecretLeak:
    """An MCP returned a SECRET_* value — paging-class but distinct from inbound exfiltration."""

    category: str
    span_text: str


@dataclass
class ScrubResult:
    scrubbed_text: str
    leaks: list[OutboundSecretLeak] = field(default_factory=list)


async def scrub_outbound(
    text: str,
    request_uuid: str,
    engine: ScrubEngine,
    tokenizer: TokenizerClient,
) -> ScrubResult:
    """Scrub `text` coming back from an MCP or LLM provider."""
    detections = engine.scan(text)
    detections.sort(key=lambda d: d.start)

    out: list[str] = []
    cursor = 0
    leaks: list[OutboundSecretLeak] = []

    for det in detections:
        out.append(text[cursor : det.start])
        replacement = await _apply_one(text, det, request_uuid, tokenizer, leaks)
        out.append(replacement)
        cursor = det.end

    out.append(text[cursor:])
    return ScrubResult(scrubbed_text="".join(out), leaks=leaks)


async def _apply_one(
    text: str,
    det: Detection,
    request_uuid: str,
    tokenizer: TokenizerClient,
    leaks: list[OutboundSecretLeak],
) -> str:
    span_text = text[det.start : det.end]
    if det.category.severity == "pii":
        token = await tokenizer.tokenize(request_uuid, det.category.name, span_text)
        TOKENS_GENERATED_TOTAL.labels(category=det.category.name).inc()
        return token
    if det.category.severity == "codeword":
        REDACTIONS_TOTAL.labels(category=det.category.name).inc()
        return REDACTION_MARKER
    SCRUB_FAILURES_TOTAL.labels(direction="outbound").inc()
    leaks.append(OutboundSecretLeak(category=det.category.name, span_text=span_text))
    return REDACTION_MARKER
