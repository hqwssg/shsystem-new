"""验证平台任务参数异常矩阵及失败工件。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.platform_parameter_anomaly_matrix import run_matrix


def main() -> int:
    output_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    output_dir = output_root / "platform_parameter_anomaly_matrix_smoke"
    summary = run_matrix(output_dir)
    assert summary["passed"] is True, summary
    assert summary["case_count"] == 49
    assert summary["failed_count"] == 0
    assert summary["categories"] == {
        "有效边界": {"case_count": 9, "passed_count": 9, "failed_count": 0},
        "结构与白名单": {"case_count": 5, "passed_count": 5, "failed_count": 0},
        "数值与枚举": {"case_count": 11, "passed_count": 11, "failed_count": 0},
        "快照路径": {"case_count": 11, "passed_count": 11, "failed_count": 0},
        "设备状态": {"case_count": 13, "passed_count": 13, "failed_count": 0},
    }
    failures = json.loads((output_dir / summary["outputs"]["failures"]).read_text(encoding="utf-8"))
    assert failures == {"failures": []}
    print("platform parameter anomaly matrix: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
