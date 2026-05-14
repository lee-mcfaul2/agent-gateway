from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# OPA policy smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opa_allow_known_permission(integration_stack: dict[str, str]) -> None:
    """Smoke test: post a decision query directly to OPA with our shipped policy."""
    import httpx

    url = integration_stack["opa"] + "/v1/data/ag_gateway/authz/decision"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            json={
                "input": {
                    "user": {"sub": "alice", "permissions": ["kb:read"]},
                    "mcp": "kb",
                    "tool": "search",
                }
            },
        )
    assert r.status_code == 200
    assert r.json()["result"]["allow"] is True


@pytest.mark.asyncio
async def test_opa_deny_missing_permission(integration_stack: dict[str, str]) -> None:
    import httpx

    url = integration_stack["opa"] + "/v1/data/ag_gateway/authz/decision"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            json={
                "input": {
                    "user": {"sub": "alice", "permissions": []},
                    "mcp": "audit_db",
                    "tool": "search",
                }
            },
        )
    body = r.json()
    assert body["result"]["allow"] is False
    assert body["result"]["reason"].startswith("missing_permission")


# ---------------------------------------------------------------------------
# Tokenizer mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tokenizer_mock_init(integration_stack: dict[str, str]) -> None:
    import httpx

    async with httpx.AsyncClient() as client:
        r = await client.post(
            integration_stack["tokenizer"] + "/v1/init_request",
            json={"request_uuid": "11111111-1111-1111-1111-111111111111", "ttl_seconds": 60},
        )
    assert r.status_code == 200
    assert r.json()["request_uuid"] == "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# v1.0 bundle shape assertions
# ---------------------------------------------------------------------------


def test_bundle_manifest_v1_shape(bundle_v1_root: "pathlib.Path") -> None:  # noqa: F821
    """The fixture bundle has the canonical v1.0 manifest shape expected by MCPRegistry."""
    import json
    import pathlib

    manifest = json.loads((bundle_v1_root / "bundle-manifest.json").read_text())
    # Top-level version fields
    assert manifest["bundle_version"] == "1.0.0"
    assert "schema_library_version" in manifest
    # Each service entry uses 'mcp' key (not legacy 'name'), and has per-tool digests
    for svc in manifest["services"]:
        assert "mcp" in svc, "service entry must have 'mcp' key (v1.0 shape)"
        assert "name" not in svc, "legacy 'name' key must not appear"
        for tool in svc["tools"]:
            assert "request_digest" in tool
            assert "response_digest" in tool
            assert "requires_permissions" in tool


# ---------------------------------------------------------------------------
# Sandbox env-var set (v1.0 — 10 vars)
# ---------------------------------------------------------------------------


def test_sandbox_env_var_set() -> None:
    """The launcher passes exactly the 10 env vars defined by the v1.0 contract."""
    import inspect

    from ag_gateway.jobs.launcher import AgentJobLauncher

    src = inspect.getsource(AgentJobLauncher.launch_and_wait)
    expected_vars = [
        "REQUEST_UUID",
        "PROMPT_UUID",
        "LITELLM_URL",
        "GATEWAY_MCP_URL",
        "AVAILABLE_TOOLS",
        "TOKENIZED_USER_INPUT",
        "MODEL",
        "MAX_ITERATIONS",
        "WALLCLOCK_TIMEOUT_SECONDS",
        "TRACEPARENT",
    ]
    for var in expected_vars:
        assert f'"{var}"' in src, f"missing env var {var!r} in launcher.launch_and_wait"


# ---------------------------------------------------------------------------
# Request body shape (user-prompt.json)
# ---------------------------------------------------------------------------


def test_user_prompt_schema_required_fields(bundle_v1_root: "pathlib.Path") -> None:  # noqa: F821
    """The user-prompt.json schema mandates the v1.0 required fields."""
    import json
    import pathlib

    schema = json.loads(
        (bundle_v1_root / "schemas" / "user-prompt.json").read_text()
    )
    required = set(schema["required"])
    assert "schema_uuid" in required
    assert "prompt_uuid" in required
    assert "text" in required
    # model is optional; must NOT appear in required
    assert "model" not in required


# ---------------------------------------------------------------------------
# Gateway response shape (OpenAI chat-completion)
# ---------------------------------------------------------------------------


def test_gateway_openai_response_shape() -> None:
    """server_ingress returns an OpenAI-shape chat-completion dict.

    Verified by inspection: the response keys match the OpenAI spec and
    terminate.response maps to choices[0].message.content.
    """
    import inspect

    from ag_gateway.server_ingress import make_router

    src = inspect.getsource(make_router)
    # The return dict must contain the OpenAI envelope keys
    assert '"object": "chat.completion"' in src
    assert '"choices"' in src
    assert '"message"' in src
    assert '"content": final' in src
