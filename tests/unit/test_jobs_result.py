from __future__ import annotations

import pytest

from ag_gateway.jobs.result import TerminateInvalid, extract_terminate
from ag_gateway.prompts.registry import Prompt


def test_no_schema_passes_through() -> None:
    p = Prompt(uuid="x", name="n", body={"allowed_responses": {}})
    res = extract_terminate(p, {"answer": "hi"})
    assert res.body == {"answer": "hi"}


def test_schema_match() -> None:
    p = Prompt(
        uuid="x",
        name="n",
        body={
            "allowed_responses": {
                "terminate": {"schema": {"type": "object", "required": ["answer"]}}
            }
        },
    )
    res = extract_terminate(p, {"answer": "hi"})
    assert res.body == {"answer": "hi"}


def test_schema_violation_raises() -> None:
    p = Prompt(
        uuid="x",
        name="n",
        body={
            "allowed_responses": {
                "terminate": {"schema": {"type": "object", "required": ["answer"]}}
            }
        },
    )
    with pytest.raises(TerminateInvalid):
        extract_terminate(p, {"oops": True})
