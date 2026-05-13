from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ag_gateway.prompts.registry import Prompt
from ag_gateway.schemas.validate import validate_against


class TerminateInvalid(Exception):
    pass


@dataclass(frozen=True)
class TerminateResult:
    body: dict[str, Any]


def extract_terminate(prompt: Prompt, raw: dict[str, Any]) -> TerminateResult:
    """Validate raw terminate body against the prompt's allowed_responses.terminate schema."""
    allowed = prompt.allowed_responses
    terminate_schema = allowed.get("terminate", {}).get("schema")
    if terminate_schema is None:
        return TerminateResult(body=raw)
    err = validate_against(terminate_schema, raw)
    if err is not None:
        raise TerminateInvalid(err)
    return TerminateResult(body=raw)
