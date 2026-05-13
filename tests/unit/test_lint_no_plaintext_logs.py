from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tools.lint_no_plaintext_logs import check_file  # noqa: E402


def test_flags_logger_with_plaintext_arg(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "def fn(args):\n"
        "    log.info(args)\n"
    )
    violations = check_file(f)
    assert len(violations) == 1
    assert "args" in violations[0]


def test_safe_marker_suppresses(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "def fn(args):\n"
        "    log.info(args)  # scrub: safe\n"
    )
    violations = check_file(f)
    assert violations == []


def test_unrelated_args_not_flagged(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "def fn(count):\n"
        "    log.info(count)\n"
    )
    violations = check_file(f)
    assert violations == []
