from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
from pathlib import Path


def _build_tarball(src: Path, out: Path) -> None:
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname="policy")


def _opa_test(src: Path) -> None:
    subprocess.run(["opa", "test", str(src)], check=True)


def _push_oci(tarball: Path, ref: str) -> None:
    subprocess.run(["oras", "push", ref, str(tarball)], check=True)


def _cosign_sign(ref: str, key: str) -> None:
    subprocess.run(["cosign", "sign", "--key", key, "--yes", ref], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compile-policy")
    parser.add_argument("--src", type=Path, default=Path("policy"))
    parser.add_argument("--out", type=Path, default=Path("policy.tar.gz"))
    parser.add_argument("--ref", help="OCI ref to push to (optional)")
    parser.add_argument("--cosign-key", help="cosign key path or KMS uri (optional)")
    parser.add_argument("--skip-test", action="store_true")
    args = parser.parse_args(argv)

    if not args.src.exists():
        print(f"error: source dir {args.src} not found", file=sys.stderr)
        return 2

    if not args.skip_test:
        _opa_test(args.src)

    _build_tarball(args.src, args.out)
    print(f"built: {args.out}")

    if args.ref:
        _push_oci(args.out, args.ref)
        print(f"pushed: {args.ref}")
        if args.cosign_key:
            _cosign_sign(args.ref, args.cosign_key)
            print(f"signed: {args.ref}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
