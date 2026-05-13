from __future__ import annotations

import tarfile
from pathlib import Path


def _import_compile_main():
    """Import the compile-policy main with fallback for the hyphenated directory."""
    try:
        from tools.compile_policy.main import main
    except ImportError:
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "compile_policy_main",
            Path(__file__).resolve().parents[2] / "tools" / "compile-policy" / "main.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["compile_policy_main"] = mod
        spec.loader.exec_module(mod)
        main = mod.main
    return main


compile_main = _import_compile_main()


def test_builds_tarball(tmp_path: Path) -> None:
    src = tmp_path / "policy"
    src.mkdir()
    (src / "authz.rego").write_text("package x")
    out = tmp_path / "out.tar.gz"

    rc = compile_main(["--src", str(src), "--out", str(out), "--skip-test"])
    assert rc == 0
    assert out.exists()
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert any(n.endswith("authz.rego") for n in names)


def test_missing_src(tmp_path: Path) -> None:
    rc = compile_main(["--src", str(tmp_path / "nope"), "--skip-test"])
    assert rc == 2
