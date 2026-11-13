"""Smoke check for the local CI-style gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="ci_checks_smoke_") as temp:
        output_dir = Path(temp) / "ci"
        completed = subprocess.run([sys.executable, str(root / "tools" / "run_ci_checks.py"), "--output-dir", str(output_dir)], cwd=root, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
        summary = json.loads((output_dir / "ci_summary.json").read_text(encoding="utf-8"))
        if summary["failed_count"] != 0 or summary["passed_count"] < 6:
            raise AssertionError(summary)
    print("CI checks verification: PASS")


if __name__ == "__main__":
    main()
