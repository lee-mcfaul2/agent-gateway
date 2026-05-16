from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess  # nosec B404 — required for cosign/oras shell-out
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import BUNDLE_VERIFY_FAILURES_TOTAL

log = get_logger(__name__)


class BundleVerifyError(Exception):
    """Raised when cosign verification fails for the bundle."""


@dataclass(frozen=True)
class Bundle:
    """A verified, extracted bundle on disk."""

    ref: str
    digest: str
    root: Path


async def pull_and_verify(
    ref: str, cosign_public_key: str, dest_root: Path | None = None
) -> Bundle:
    """Pull an OCI artifact, cosign-verify it, then extract to dest_root.

    Uses `cosign` + `oras` binaries. The cosign key may be a file path or PEM contents.
    Raises BundleVerifyError on any verification failure.
    """
    workdir = dest_root or Path(tempfile.mkdtemp(prefix="ag-bundle-"))
    workdir.mkdir(parents=True, exist_ok=True)

    key_arg = await _resolve_key(cosign_public_key)
    try:
        await _run("cosign", "verify", "--key", key_arg, ref)
    except subprocess.CalledProcessError as exc:
        BUNDLE_VERIFY_FAILURES_TOTAL.labels(reason="cosign_verify").inc()
        log.error("bundle.cosign_verify_failed", ref=ref, stderr=exc.stderr[-2000:])
        raise BundleVerifyError(f"cosign verify failed for {ref}") from exc

    digest = await _resolve_digest(ref)

    try:
        await _run("oras", "pull", ref, "-o", str(workdir))
    except subprocess.CalledProcessError as exc:
        BUNDLE_VERIFY_FAILURES_TOTAL.labels(reason="oras_pull").inc()
        log.error("bundle.oras_pull_failed", ref=ref, stderr=exc.stderr[-2000:])
        raise BundleVerifyError(f"oras pull failed for {ref}") from exc

    return Bundle(ref=ref, digest=digest, root=workdir)


async def load_local(path: Path | str) -> Bundle:
    """DEMO-ONLY: load a bundle from a local directory, skipping cosign/oras.

    Returns the SAME ``Bundle`` contract as :func:`pull_and_verify` after its
    ``oras pull`` step — i.e. ``root`` points at the on-disk bundle tree that
    downstream consumers (``BundleView.from_bundle`` etc.) parse and validate.
    No OCI artifact is pulled and no signature is verified. This MUST only be
    used by the loudly-flagged demo deployment.
    """
    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"local bundle directory not found: {root}")

    # No OCI manifest exists locally; derive a stable content digest so the
    # startup log line / digest field remains meaningful and non-empty.
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
            h.update(b"\x00")
    digest = "sha256:" + h.hexdigest()

    return Bundle(ref=f"local://{root}", digest=digest, root=root)


async def _resolve_key(cosign_public_key: str) -> str:
    """Treat the value as a path if it exists; otherwise write the PEM content to a temp file."""
    if os.path.exists(cosign_public_key):
        return cosign_public_key
    fd, path = tempfile.mkstemp(prefix="cosign-key-", suffix=".pub")
    with os.fdopen(fd, "w") as f:
        f.write(cosign_public_key)
    return path


async def _resolve_digest(ref: str) -> str:
    """Return the sha256 digest for the manifest ref."""
    proc = await asyncio.create_subprocess_exec(
        "oras",
        "manifest",
        "fetch",
        "--descriptor",
        ref,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode or -1, ["oras", "manifest", "fetch"],
            output=stdout.decode(), stderr=stderr.decode(),
        )
    import json as _json
    desc = _json.loads(stdout.decode())
    return str(desc.get("digest", ""))


async def _run(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode or -1, args, output=stdout.decode(), stderr=stderr.decode(),
        )


def cleanup(bundle: Bundle) -> None:
    """Remove the extracted bundle directory."""
    if bundle.root.exists():
        shutil.rmtree(bundle.root, ignore_errors=True)
