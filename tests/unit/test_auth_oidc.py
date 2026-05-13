from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ag_gateway.hooks.auth_oidc import JWTValidationError, OIDCValidator


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, bytes, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_priv = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pem_pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem_priv, pem_pub, "test-kid"


def _make_validator_with_key(monkeypatch: pytest.MonkeyPatch, pem_pub: bytes) -> OIDCValidator:
    monkeypatch.setattr(
        OIDCValidator, "_discover_jwks", staticmethod(lambda _issuer: "http://x/jwks")
    )
    v = OIDCValidator(issuer="http://idp.test", audience="ag-gateway")

    class _FakeKey:
        def __init__(self, key: object) -> None:
            self.key = key

    pub = serialization.load_pem_public_key(pem_pub)
    monkeypatch.setattr(v._jwk_client, "get_signing_key_from_jwt", lambda _t: _FakeKey(pub))
    return v


def _make_token(pem_priv: bytes, **claims: object) -> str:
    return jwt.encode(claims, pem_priv, algorithm="RS256")


def test_validate_ok(monkeypatch: pytest.MonkeyPatch, keypair: tuple[bytes, bytes, str]) -> None:
    pem_priv, pem_pub, _ = keypair
    v = _make_validator_with_key(monkeypatch, pem_pub)
    token = _make_token(
        pem_priv,
        iss="http://idp.test",
        aud="ag-gateway",
        sub="alice",
        groups=["support"],
        permissions=["kb:read"],
        exp=int(time.time()) + 300,
    )
    claims = v.validate(token)
    assert claims.sub == "alice"
    assert "kb:read" in claims.permissions


def test_validate_expired(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[bytes, bytes, str]
) -> None:
    pem_priv, pem_pub, _ = keypair
    v = _make_validator_with_key(monkeypatch, pem_pub)
    token = _make_token(
        pem_priv,
        iss="http://idp.test",
        aud="ag-gateway",
        sub="alice",
        exp=int(time.time()) - 10,
    )
    with pytest.raises(JWTValidationError) as exc:
        v.validate(token)
    assert exc.value.reason == "expired"


def test_validate_wrong_audience(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[bytes, bytes, str]
) -> None:
    pem_priv, pem_pub, _ = keypair
    v = _make_validator_with_key(monkeypatch, pem_pub)
    token = _make_token(
        pem_priv,
        iss="http://idp.test",
        aud="someone-else",
        sub="alice",
        exp=int(time.time()) + 60,
    )
    with pytest.raises(JWTValidationError) as exc:
        v.validate(token)
    assert exc.value.reason == "audience"


def test_validate_missing_sub(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[bytes, bytes, str]
) -> None:
    pem_priv, pem_pub, _ = keypair
    v = _make_validator_with_key(monkeypatch, pem_pub)
    token = _make_token(
        pem_priv,
        iss="http://idp.test",
        aud="ag-gateway",
        exp=int(time.time()) + 60,
    )
    with pytest.raises(JWTValidationError) as exc:
        v.validate(token)
    assert exc.value.reason == "missing_claim"
