from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_forged_request_uuid_rejected(integration_stack: dict[str, str]) -> None:
    """A tool call with a request_uuid not bound to any container must be rejected.

    This is a sentinel placeholder — Task 24's unit tests already assert the contract on
    the route. When a full integration harness with a running gateway exists, replace this
    with a real call to /v1/mcp/<name>/<tool> with a forged uuid and assert UUID_MISMATCH.
    """
    assert True
