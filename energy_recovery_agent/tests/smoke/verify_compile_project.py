"""Smoke check that project compilation excludes incompatible environments."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.compile_project import EXCLUDED


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = ROOT
    completed = subprocess.run([sys.executable, str(root / "tools" / "compile_project.py")], cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    if "project compile: PASS" not in completed.stdout:
        raise AssertionError(completed.stdout)
    assert "deliverables" in EXCLUDED
    print("project compile verification: PASS")


if __name__ == "__main__":
    main()
