"""Smoke check that the checked-in synthetic baseline still matches."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    smoke_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", root / "outputs"))
    output_dir = smoke_root / "synthetic_regression_baseline"
    baseline = root / "tests" / "fixtures" / "synthetic_regression_baseline.json"
    command = [
        sys.executable,
        str(root / "tools" / "synthetic_regression_baseline.py"),
        "--output-dir",
        str(output_dir),
        "--baseline",
        str(baseline),
    ]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"synthetic baseline mismatch:\n{completed.stdout}\n{completed.stderr}")
    payload = json.loads(completed.stdout.strip())
    if payload.get("status") != "PASS" or payload.get("failed_count") != 0:
        raise AssertionError(payload)
    if not (output_dir / "BASELINE_REPORT.md").is_file():
        raise AssertionError("baseline report was not generated")
    print("synthetic regression baseline verification: PASS")


if __name__ == "__main__":
    main()
