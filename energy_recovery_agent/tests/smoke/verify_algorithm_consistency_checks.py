# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = ROOT / "outputs" / "algorithm_consistency_smoke"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "algorithm_consistency_checks.py"), "--output-dir", str(output_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"algorithm consistency checks failed:\n{proc.stdout}\n{proc.stderr}")
    summary = json.loads((output_dir / "algorithm_consistency_summary.json").read_text(encoding="utf-8"))
    if summary.get("passed") is not True:
        raise AssertionError(summary)
    if any(value > 1e-5 for value in summary["cross_module"]["differences"].values()):
        raise AssertionError(summary["cross_module"])
    print("algorithm consistency, ablation, and monotonicity checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
