from __future__ import annotations

from pathlib import Path

import pytest

from ag_gateway.prompts.bundle import (
    Bundle,
    BundleVerifyError,
    cleanup,
    load_local,
    pull_and_verify,
)

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


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


async def test_load_local_returns_bundle_without_cosign_or_oras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Demo-mode local loader must return the same Bundle shape and never
    shell out to cosign/oras."""

    async def _boom_run(*args: str) -> None:
        raise AssertionError(f"local mode must not shell out: {args!r}")

    async def _boom_digest(_ref: str) -> str:
        raise AssertionError("local mode must not resolve OCI digest")

    async def _boom_key(_v: str) -> str:
        raise AssertionError("local mode must not resolve cosign key")

    monkeypatch.setattr("ag_gateway.prompts.bundle._run", _boom_run)
    monkeypatch.setattr("ag_gateway.prompts.bundle._resolve_digest", _boom_digest)
    monkeypatch.setattr("ag_gateway.prompts.bundle._resolve_key", _boom_key)

    bundle = await load_local(FIXTURE_BUNDLE)
    assert isinstance(bundle, Bundle)
    assert bundle.root == FIXTURE_BUNDLE
    assert bundle.digest.startswith("sha256:")

    # The returned bundle must be parseable by the exact same downstream
    # consumer as the OCI path (identical return contract).
    from ag_gateway.prompts.bundle_view import BundleView

    view = BundleView.from_bundle(bundle.root)
    assert "kb" in view.services


async def test_load_local_missing_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        await load_local(Path("/tmp/definitely-not-a-bundle-xyz"))


async def test_pull_success_still_invokes_cosign_and_oras(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Production path (no local path) is unchanged: cosign + oras still run."""
    calls: list[tuple[str, ...]] = []

    async def _fake_run(*args: str) -> None:
        calls.append(args)

    async def _fake_digest(_ref: str) -> str:
        return "sha256:beef"

    async def _fake_resolve(v: str) -> str:
        return "/tmp/cosign.pub"

    monkeypatch.setattr("ag_gateway.prompts.bundle._run", _fake_run)
    monkeypatch.setattr("ag_gateway.prompts.bundle._resolve_digest", _fake_digest)
    monkeypatch.setattr("ag_gateway.prompts.bundle._resolve_key", _fake_resolve)

    bundle = await pull_and_verify("oci://x/y:v1", "/tmp/cosign.pub", tmp_path)
    assert isinstance(bundle, Bundle)
    assert any("cosign" in c[0] for c in calls)
    assert any("oras" in c[0] for c in calls)


def test_cleanup_removes_dir(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("x")
    cleanup(Bundle(ref="r", digest="d", root=tmp_path))
    assert not tmp_path.exists()
