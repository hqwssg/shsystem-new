"""Smoke check for repeatable capacity analysis output."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="capacity_analysis_smoke_") as temp:
        output_dir = Path(temp) / "capacity"
        command = [sys.executable, str(root / "tools" / "performance_capacity_analysis.py"), "--output-dir", str(output_dir), "--case", "1", "--case", "2"]
        completed = subprocess.run(command, cwd=Path(temp), capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
        summary = json.loads((output_dir / "capacity_summary.json").read_text(encoding="utf-8"))
        if summary["passed_count"] != 2 or summary["failed_count"] != 0:
            raise AssertionError(summary)
        if not (output_dir / "CAPACITY_ANALYSIS.md").is_file():
            raise AssertionError("capacity report missing")
    print("performance capacity verification: PASS")


if __name__ == "__main__":
    main()
