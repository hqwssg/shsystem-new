"""Compile project-owned Python files, excluding data, outputs and environments."""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path


EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "env",
    "outputs",
    "data",
    "deliverables",
    "shuohuang_data",
    "__pycache__",
}


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    for path in sorted(root.rglob("*.py")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in EXCLUDED for part in relative.parts):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except (OSError, py_compile.PyCompileError) as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("project compile: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
