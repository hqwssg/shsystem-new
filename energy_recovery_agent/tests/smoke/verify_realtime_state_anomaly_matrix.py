"""验证实时状态异常注入矩阵及可信游标隔离合同。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime_state_guard import validate_realtime_batch
from tools.realtime_state_anomaly_matrix import run_matrix


def main() -> int:
    smoke_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    output_dir = smoke_root / "realtime_state_anomaly_matrix_smoke"
    summary = run_matrix(output_dir)
    assert summary["passed"] is True, summary
    assert summary["case_count"] == 40
    assert summary["failed_count"] == 0
    assert summary["categories"] == {
        "字段与时钟": {"case_count": 16, "passed_count": 16, "failed_count": 0},
        "顺序与位置": {"case_count": 6, "passed_count": 6, "failed_count": 0},
        "断流与恢复": {"case_count": 9, "passed_count": 9, "failed_count": 0},
        "设备状态": {"case_count": 4, "passed_count": 4, "failed_count": 0},
        "滚动恢复": {"case_count": 5, "passed_count": 5, "failed_count": 0},
    }

    for relative_path in summary["outputs"].values():
        assert (output_dir / relative_path).is_file(), relative_path
    with (output_dir / summary["outputs"]["cases"]).open(encoding="utf-8-sig", newline="") as handle:
        case_rows = list(csv.DictReader(handle))
    case_ids = [row["case_id"] for row in case_rows]
    assert len(case_ids) == len(set(case_ids)) == 40
    assert {
        "RT-F02", "RT-C04", "RT-S01", "RT-S05", "RT-O03", "RT-O04",
        "RT-O08", "RT-O09", "RT-D01", "RT-R01", "RT-R02", "RT-R03", "RT-R04", "RT-R05",
    }.issubset(case_ids)
    assert all(row["passed"] == "True" for row in case_rows)
    failure_payload = json.loads(
        (output_dir / summary["outputs"]["failures"]).read_text(encoding="utf-8")
    )
    assert failure_payload["failures"] == []
    report = (output_dir / summary["outputs"]["report"]).read_text(encoding="utf-8")
    assert report.count("| RT-") == 40
    assert "hold_new_decisions_and_keep_last_trusted_state" not in report
    assert "扣留新决策" in report and "人工处置" in report

    # 倒退消息被拒绝后不得推进游标；位于原可信游标之后的消息仍应接受。
    batch = validate_realtime_batch([
        {
            "timestamp_s": 100, "train_id": "T001", "direction": "forward",
            "position_km": 10.0, "speed_mps": 10.0, "power_kW": 1000.0,
        },
        {
            "timestamp_s": 110, "train_id": "T001", "direction": "forward",
            "position_km": 9.0, "speed_mps": 10.0, "power_kW": 1000.0,
        },
        {
            "timestamp_s": 105, "train_id": "T001", "direction": "forward",
            "position_km": 10.5, "speed_mps": 10.0, "power_kW": 1000.0,
        },
    ])
    assert batch["accepted_indices"] == [0, 2]
    assert batch["rejected_count"] == 1
    assert batch["errors"][0]["index"] == 1
    print("realtime state anomaly matrix smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
