from __future__ import annotations

import pytest
import respx
from httpx import Response

from ag_gateway.hooks.tokenizer_client import (
    TokenizerClient,
    TokenizerError,
    TokenizerUnavailable,
)


@pytest.fixture
async def client() -> TokenizerClient:
    c = TokenizerClient("http://tok:8443")
    yield c
    await c.aclose()


@respx.mock
async def test_init_request_ok(client: TokenizerClient) -> None:
    respx.post("http://tok:8443/v1/init_request").mock(
        return_value=Response(
            201,
            json={"request_uuid": "abc", "expires_at": "2026-01-01T00:00:00Z"},
        )
    )
    res = await client.init_request("abc", 60)
    assert res.request_uuid == "abc"


@respx.mock
async def test_tokenize_ok(client: TokenizerClient) -> None:
    respx.post("http://tok:8443/v1/tokenize").mock(
        return_value=Response(200, json={"token": "TOKEN_EMAIL_ABC"})
    )
    tok = await client.tokenize("abc", "EMAIL", "alice@example.com")
    assert tok == "TOKEN_EMAIL_ABC"


@respx.mock
async def test_detokenize_aad_mismatch_raises(client: TokenizerClient) -> None:
    respx.post("http://tok:8443/v1/detokenize").mock(
        return_value=Response(
            400,
            json={"error_type": "AAD_MISMATCH", "retriable": False, "message": "bad"},
        )
    )
    with pytest.raises(TokenizerError) as exc:
        await client.detokenize("abc", "TOKEN_x")
    assert exc.value.error_type == "AAD_MISMATCH"


@respx.mock
async def test_503_raises_unavailable(client: TokenizerClient) -> None:
    respx.post("http://tok:8443/v1/init_request").mock(return_value=Response(503))
    with pytest.raises(TokenizerUnavailable):
        await client.init_request("abc", 60)


@respx.mock
async def test_network_error_raises_unavailable(client: TokenizerClient) -> None:
    import httpx as _httpx

    respx.post("http://tok:8443/v1/tokenize").mock(side_effect=_httpx.ConnectError("boom"))
    with pytest.raises(TokenizerUnavailable):
        await client.tokenize("abc", "EMAIL", "x")


@respx.mock
async def test_release_404_is_ok(client: TokenizerClient) -> None:
    respx.post("http://tok:8443/v1/release_request").mock(return_value=Response(404))
    await client.release_request("abc")
