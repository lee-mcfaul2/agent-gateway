from __future__ import annotations

import ast
import sys
from pathlib import Path


GUARDED_MODULES = (
    "src/ag_gateway/mcp_proxy/routes.py",
    "src/ag_gateway/mcp_proxy/client.py",
)

# Names that, if used as arguments to log/print, signal plaintext leakage in these modules.
PLAINTEXT_LIKE_NAMES = {"args", "detokenized", "plaintext", "raw_body", "tool_args"}

# Allow override per call via a `# scrub: safe` trailing comment.
SAFE_MARKER = "scrub: safe"


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    src_lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_log = isinstance(func, ast.Name) and func.id in {"print", "log", "logger"}
        is_attr_log = (
            isinstance(func, ast.Attribute)
            and func.attr in {"debug", "info", "warning", "error", "critical", "exception"}
        )
        if not (is_log or is_attr_log):
            continue
        risky = False
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Name) and arg.id in PLAINTEXT_LIKE_NAMES:
                risky = True
                break
        if not risky:
            continue
        line = src_lines[node.lineno - 1] if node.lineno - 1 < len(src_lines) else ""
        if SAFE_MARKER in line:
            continue
        violations.append(f"{path}:{node.lineno}: logging plaintext-named arg: `{line.strip()}`")
    return violations


def main(roots: list[str] | None = None) -> int:
    paths = [Path(p) for p in (roots or GUARDED_MODULES)]
    all_violations: list[str] = []
    for p in paths:
        if p.exists():
            all_violations.extend(check_file(p))
    for v in all_violations:
        print(v, file=sys.stderr)
    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
