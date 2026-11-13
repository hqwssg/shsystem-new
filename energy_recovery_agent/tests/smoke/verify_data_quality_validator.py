# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_quality_validator import QualityReport, _validate_power_arm_rows, validate_station_interval_overlaps
from power_arm_electrical_limits import power_arm_electrical_limit_from_row
from smart_meter_time_matcher import find_station_interval_overlaps_from_dir


def _write_overlapping_station_csv(path: Path) -> None:
    """函数 _write_overlapping_station_csv：执行该模块中的相关处理逻辑。"""
    rows = [
        {
            "guid": "g1",
            "trainid": "58",
            "starttime": "2026-01-01 00:00:00",
            "endtime": "2026-01-01 01:00:00",
            "start_station": "A",
            "end_station": "B",
            "use_ygdn": "10",
            "use_fkdn": "0",
        },
        {
            "guid": "g2",
            "trainid": "58",
            "starttime": "2026-01-01 00:30:00",
            "endtime": "2026-01-01 01:30:00",
            "start_station": "B",
            "end_station": "C",
            "use_ygdn": "8",
            "use_fkdn": "0",
        },
        {
            "guid": "g3",
            "trainid": "151",
            "starttime": "2026-01-01 02:00:00",
            "endtime": "2026-01-01 03:00:00",
            "start_station": "A",
            "end_station": "B",
            "use_ygdn": "5",
            "use_fkdn": "0",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory() as tmp:
        smart_dir = Path(tmp)
        station_csv = smart_dir / "nhtj_jkfile_station_smoke.csv"
        _write_overlapping_station_csv(station_csv)
        overlaps = find_station_interval_overlaps_from_dir(smart_dir)
        if len(overlaps) != 1:
            raise AssertionError(f"Expected one synthetic station overlap, got {len(overlaps)}")
        report = QualityReport()
        validate_station_interval_overlaps(smart_dir, report)
        overlap_warnings = [issue for issue in report.warnings if issue.code == "smart_meter_station_interval_overlap"]
        if not overlap_warnings:
            raise AssertionError("Expected smart_meter_station_interval_overlap warning from synthetic fixture.")

    invalid_row = {
        "_row_number": 2,
        "section_id": "bad_arm",
        "road": "main",
        "direction": "??",
        "start_km": "0",
        "end_km": "1",
        "length_km": "1",
        "max_traction_supply_kw": "not-a-number",
        "max_regen_absorption_kw": "-5",
        "max_grid_feedback_kw": "NaN",
        "storage_available": "maybe",
        "storage_section_id": "S-X",
        "storage_start_km": "bad",
        "storage_end_km": "1",
    }
    invalid_report = QualityReport()
    _validate_power_arm_rows(
        [invalid_row],
        "synthetic",
        invalid_report,
        flag_manual_review=False,
        require_operational_fields=True,
    )
    assert not invalid_report.is_valid
    assert any(issue.code == "power_arm_invalid_electrical_limit" for issue in invalid_report.errors)
    assert any(issue.code == "power_arm_invalid_storage_available" for issue in invalid_report.errors)
    try:
        power_arm_electrical_limit_from_row(invalid_row)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid electrical limits were silently replaced by non-binding defaults.")

    print("data quality validation correctly reported overlapping station intervals as representative-sample warnings")
    print(
        {
            "synthetic_overlap_count": 1,
            "overlap_warning_count": len(overlap_warnings),
            "invalid_power_arm_error_count": len(invalid_report.errors),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
