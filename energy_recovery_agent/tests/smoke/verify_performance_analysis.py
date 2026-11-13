"""Smoke checks for the observational performance profiler."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="performance_analysis_smoke_") as temp:
        output_dir = Path(temp) / "profile"
        command = [
            sys.executable,
            str(root / "tools" / "performance_analysis.py"),
            "--output-dir",
            str(output_dir),
            "--",
            "tests/smoke/verify_energy_settlement_correctness.py",
        ]
        completed = subprocess.run(command, cwd=Path(temp), capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(f"performance profiler failed: {completed.stdout}\n{completed.stderr}")
        summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        if summary["return_code"] != 0 or summary["wall_time_s"] <= 0:
            raise AssertionError(f"invalid performance summary: {summary}")
        if not summary["top_functions"] or not (output_dir / "profile.prof").is_file():
            raise AssertionError("profile did not include function data")
    print("performance analysis verification: PASS")


if __name__ == "__main__":
    main()
