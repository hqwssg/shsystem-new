# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import csv
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import energy_calibration_alignment as alignment_module
from energy_calibration_alignment import build_alignment
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    sample_csv = Path("data") / "real_shuohuang" / "smart_meter_representative_interval_samples.csv"
    station_csv = Path("data") / "real_shuohuang" / "stations.csv"
    if not sample_csv.exists():
        print("energy calibration alignment skipped: representative smart-meter samples are unavailable.")
        return 0
    output_dir = smoke_output("energy_calibration_alignment_smoke")
    data_dir = Path("data") / "real_shuohuang"
    profile = alignment_module.load_infrastructure_profile(data_dir)
    with patch.object(
        alignment_module,
        "load_infrastructure_profile",
        return_value=profile,
    ) as profile_loader:
        summary = build_alignment(
            sample_csv,
            station_csv,
            output_dir,
            energy_calibration_mode="grouped",
            factor_json=data_dir / "energy_calibration_factors.json",
            infrastructure_data_dir=data_dir,
        )
    profile_loader.assert_called_once_with(data_dir)
    if summary["infrastructure_data_dir"] != str(data_dir):
        raise AssertionError("Alignment summary did not record the selected infrastructure data directory.")
    if summary["sample_count"] <= 0:
        raise AssertionError("Expected aligned sample rows.")
    if summary["alignment_status_counts"].get("aligned", 0) <= 0:
        raise AssertionError("Expected at least one station-aligned sample.")
    output_csv = output_dir / "arc_energy_vs_meter_samples.csv"
    with output_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), None)
    if first is None or "alignment_status" not in first or "energy_calibration_mode" not in first:
        raise AssertionError("Alignment output CSV is malformed.")
    if summary["energy_calibration_mode"] != "grouped":
        raise AssertionError("Expected grouped calibration mode in summary.")

    zero_factor_json = output_dir / "zero_sample_factors.json"
    zero_factor_json.write_text(
        json.dumps(
            {
                "data_status": "incomplete",
                "global": {"traction_scale": 1.0, "sample_count": 0},
                "groups": {},
            }
        ),
        encoding="utf-8",
    )
    zero_output_dir = output_dir / "zero_sample_case"
    with patch.object(alignment_module, "load_infrastructure_profile", return_value=profile):
        zero_summary = build_alignment(
            sample_csv,
            station_csv,
            zero_output_dir,
            energy_calibration_mode="grouped",
            factor_json=zero_factor_json,
            infrastructure_data_dir=data_dir,
        )
    if zero_summary["calibration_applied_count"] != 0:
        raise AssertionError("Zero-sample calibration factors must not be applied.")
    if any(status.startswith("prototype_estimate_with_") for status in zero_summary["estimate_status_counts"]):
        raise AssertionError("Zero-sample factors were incorrectly reported as applied calibration.")
    if zero_summary["calibration_factor_status_counts"].get("no_calibration_samples", 0) <= 0:
        raise AssertionError("Zero-sample factor status was not reported.")
    print("energy calibration alignment passed")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
