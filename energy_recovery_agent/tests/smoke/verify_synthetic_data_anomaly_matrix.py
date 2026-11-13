"""验证合成输入数据异常矩阵、输出合同和母本隔离。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.synthetic_data_anomaly_matrix import run_matrix


def main() -> int:
    smoke_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    output_dir = smoke_root / "synthetic_data_anomaly_matrix_smoke"
    summary = run_matrix(ROOT / "data" / "real_shuohuang", output_dir)
    assert summary["passed"] is True, summary
    assert summary["baseline_valid"] is True
    assert summary["baseline_unchanged"] is True
    assert summary["case_count"] == 29
    assert summary["failed_count"] == 0
    assert summary["categories"] == {
        "文件与模式": {"case_count": 4, "passed_count": 4, "failed_count": 0},
        "线路与拓扑": {"case_count": 10, "passed_count": 10, "failed_count": 0},
        "车辆物理": {"case_count": 5, "passed_count": 5, "failed_count": 0},
        "储能与电气": {"case_count": 5, "passed_count": 5, "failed_count": 0},
        "资源与跨表": {"case_count": 5, "passed_count": 5, "failed_count": 0},
    }
    with (output_dir / summary["outputs"]["cases"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len({row["case_id"] for row in rows}) == 29
    assert all(row["passed"] == "True" for row in rows)
    assert {"missing_file", "invalid_json", "segment_overlap", "invalid_efficiency", "unknown_station"} <= {
        row["expected_code"] for row in rows
    }
    failures = json.loads((output_dir / summary["outputs"]["failures"]).read_text(encoding="utf-8"))
    assert failures == {"failures": []}
    print("synthetic data anomaly matrix smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
