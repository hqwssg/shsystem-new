# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv


FIELDS = (
    "interval_source_file",
    "interval_source_row",
    "guid",
    "station_trainid",
    "realtime_trainid",
    "normalized_trainid",
    "start_station",
    "end_station",
    "station_starttime",
    "station_endtime",
    "start_recordtime",
    "end_recordtime",
    "station_use_ygdn",
    "station_use_fkdn",
    "matched_use_ygdn",
    "matched_use_fkdn",
    "ygdn_diff",
    "fkdn_diff",
    "start_time_gap_s",
    "end_time_gap_s",
    "point_count_in_window",
    "match_status",
    "match_quality",
    "notes",
)


def write_success_fixture(path: Path) -> Path:
    """函数 write_success_fixture：执行该模块中的相关处理逻辑。"""
    base = {
        "interval_source_file": "synthetic_station_intervals.csv",
        "station_trainid": "151",
        "realtime_trainid": "SS4-151",
        "normalized_trainid": "151",
        "start_station": "A",
        "end_station": "B",
        "station_starttime": "2026-01-01 10:00:00",
        "station_endtime": "2026-01-01 10:10:00",
        "start_recordtime": "2026-01-01 10:00:05",
        "end_recordtime": "2026-01-01 10:09:55",
        "station_use_ygdn": "120",
        "station_use_fkdn": "20",
        "start_time_gap_s": "5",
        "end_time_gap_s": "5",
        "point_count_in_window": "11",
        "match_quality": "synthetic_smoke",
        "notes": "deterministic successful-path fixture",
    }
    rows = [
        {
            **base,
            "interval_source_row": "2",
            "guid": "fixture-consistent",
            "matched_use_ygdn": "119.5",
            "matched_use_fkdn": "20.2",
            "ygdn_diff": "0.5",
            "fkdn_diff": "0.2",
            "match_status": "matched_energy_consistent",
        },
        {
            **base,
            "interval_source_row": "3",
            "guid": "fixture-mismatch",
            "matched_use_ygdn": "60",
            "matched_use_fkdn": "10",
            "ygdn_diff": "60",
            "fkdn_diff": "10",
            "match_status": "matched_energy_mismatch",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path
