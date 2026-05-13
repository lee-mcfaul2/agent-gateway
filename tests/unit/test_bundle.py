from __future__ import annotations

from pathlib import Path

import pytest

from ag_gateway.prompts.bundle import Bundle, BundleVerifyError, cleanup, pull_and_verify


async def test_pull_failure_raises_verify_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_run(*args: str) -> None:
        raise __import__("subprocess").CalledProcessError(1, args, "", "boom")

    monkeypatch.setattr("ag_gateway.prompts.bundle._run", _fake_run)
    with pytest.raises(BundleVerifyError):
        await pull_and_verify("oci://example/ref:v1", "/tmp/cosign.pub", tmp_path)


async def test_pull_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    async def _fake_run(*args: str) -> None:
        calls.append(args)

    async def _fake_digest(_ref: str) -> str:
        return "sha256:dead"

    async def _fake_resolve(v: str) -> str:
        return "/tmp/cosign.pub"

    monkeypatch.setattr("ag_gateway.prompts.bundle._run", _fake_run)
    monkeypatch.setattr("ag_gateway.prompts.bundle._resolve_digest", _fake_digest)
    monkeypatch.setattr(
        "ag_gateway.prompts.bundle._resolve_key",
        _fake_resolve,
    )

    bundle = await pull_and_verify("oci://x/y:v1", "/tmp/cosign.pub", tmp_path)
    assert isinstance(bundle, Bundle)
    assert bundle.digest == "sha256:dead"
    assert bundle.root == tmp_path
    assert any("cosign" in c[0] for c in calls)
    assert any("oras" in c[0] for c in calls)


def test_cleanup_removes_dir(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("x")
    cleanup(Bundle(ref="r", digest="d", root=tmp_path))
    assert not tmp_path.exists()
