"""Smoke check for the synthetic scenario catalog and report contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    output_dir = root / "outputs" / "synthetic_scenario_matrix"
    command = [sys.executable, str(root / "tools" / "synthetic_scenario_matrix.py"), "--output-dir", str(output_dir)]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"scenario matrix failed:\n{completed.stdout}\n{completed.stderr}")
    report = json.loads((output_dir / "scenario_matrix.json").read_text(encoding="utf-8"))
    if report.get("scenario_count") != 9 or report.get("failed_count") != 0:
        raise AssertionError(report)
    ids = {item["scenario_id"] for item in report["scenarios"]}
    required = {"storage_no_direct", "multi_storage_terminal_soc", "zero_length_train", "resource_conflict_detection", "invalid_input_guards"}
    if not required <= ids:
        raise AssertionError(f"scenario coverage missing: {required - ids}")
    print("synthetic scenario matrix verification: PASS")


if __name__ == "__main__":
    main()
