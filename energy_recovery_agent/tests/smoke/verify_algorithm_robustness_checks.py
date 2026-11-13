# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = ROOT / "outputs" / "algorithm_robustness_smoke"
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "algorithm_robustness_checks.py"), "--output-dir", str(output_dir)], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    result = json.loads((output_dir / "algorithm_robustness_summary.json").read_text(encoding="utf-8"))
    assert result["passed"] is True, result
    print("algorithm robustness checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
