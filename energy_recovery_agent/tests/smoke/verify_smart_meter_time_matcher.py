# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
import csv
import sys
from tempfile import TemporaryDirectory

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smart_meter_time_matcher import (
    IntervalOverlapError,
    RealtimePoint,
    count_points_in_window,
    match_smart_meter_time_windows,
)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    base_time = datetime(2025, 1, 1, 0, 0, 0)
    points = [
        RealtimePoint("x", 1, "T", "T", base_time, 0.0, 0.0, "A"),
        RealtimePoint("x", 2, "T", "T", base_time + timedelta(seconds=10), 0.0, 0.0, "A"),
    ]
    assert count_points_in_window(
        points, base_time + timedelta(seconds=5), base_time + timedelta(seconds=15)
    ) == 1
    points[1] = RealtimePoint(
        "x", 2, "T", "T", base_time + timedelta(seconds=20), 0.0, 0.0, "A"
    )
    assert count_points_in_window(
        points, base_time + timedelta(seconds=5), base_time + timedelta(seconds=15)
    ) == 0

    temporary = TemporaryDirectory(prefix="smart_meter_time_matcher_source_")
    source_dir = Path(temporary.name)
    fields = [
        "guid", "trainid", "starttime", "endtime", "start_station", "end_station",
        "use_ygdn", "use_fkdn", "start_ygdn", "end_ygdn", "start_fkdn", "end_fkdn",
    ]
    with (source_dir / "nhtj_jkfile_station_fixture.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"guid": "S1", "trainid": "58A", "starttime": "2026-01-01 00:00:00", "endtime": "2026-01-01 00:08:00"})
        writer.writerow({"guid": "S2", "trainid": "58A", "starttime": "2026-01-01 00:05:00", "endtime": "2026-01-01 00:12:00"})
    with (source_dir / "nhtj_jkfile_ammeter_info_fixture.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"guid": "A1", "trainid": "151B", "starttime": "2026-01-01 01:00:00", "endtime": "2026-01-01 01:10:00", "start_station": "A", "end_station": "B", "use_ygdn": 5, "use_fkdn": 1, "start_ygdn": 20, "end_ygdn": 25, "start_fkdn": 4, "end_fkdn": 5})
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["trainid", "recordtime", "ygdn", "fk_dn", "ammeterid"])
    worksheet.append(["58A", "2026-01-01 00:00:00", 10, 3, "M58"])
    worksheet.append(["58A", "2026-01-01 00:12:00", 16, 5, "M58"])
    worksheet.append(["151B", "2026-01-01 01:00:00", 20, 4, "M151"])
    worksheet.append(["151B", "2026-01-01 01:10:00", 25, 5, "M151"])
    workbook.save(source_dir / "SS4-151.xlsx")
    try:
        match_smart_meter_time_windows(
            source_dir,
            boundary_tolerance_s=300.0,
            energy_tolerance=1.0,
            max_interval_rows_per_file=2000,
            max_realtime_rows_per_file=5000,
            overlap_policy="strict",
            restrict_to_realtime_coverage=False,
        )
    except IntervalOverlapError as exc:
        if not exc.overlaps:
            raise AssertionError("Expected overlap examples in IntervalOverlapError.")
        first = exc.overlaps[0]
        print("smart meter time matcher strict mode correctly rejected overlapping station intervals")
        print(
            {
                "overlap_count": len(exc.overlaps),
                "first_trainid": first.trainid,
                "first_left_row": first.left_source_row,
                "first_right_row": first.right_source_row,
            }
        )
    else:
        raise AssertionError("Expected overlapping nhtj_jkfile_station intervals to be rejected in strict mode.")

    rows = match_smart_meter_time_windows(
        source_dir,
        boundary_tolerance_s=300.0,
        energy_tolerance=1.0,
        max_interval_rows_per_file=2000,
        max_realtime_rows_per_file=5000,
        overlap_policy="exclude",
        # 在行数上限很小的情况下关闭覆盖率限制，使冒烟测试保持确定性。
        restrict_to_realtime_coverage=False,
    )
    if not rows:
        raise AssertionError("Expected exclude mode to produce non-overlapping match rows.")
    temporary.cleanup()
    print("smart meter time matcher exclude mode produced representative-safe match rows")
    print({"exclude_match_count": len(rows), "first_status": rows[0].match_status})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
