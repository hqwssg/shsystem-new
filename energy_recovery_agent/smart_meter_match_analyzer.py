# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math


DEFAULT_MATCH_CSV = Path("outputs") / "smart_meter_time_matching" / "smart_meter_time_window_matches.csv"
DEFAULT_OUTPUT_DIR = Path("outputs") / "smart_meter_time_matching"

CALIBRATION_STATUSES = {
    "matched_energy_consistent",
    "matched_energy_consistent_boundary_gap_large",
}
MISMATCH_STATUSES = {
    "matched_energy_mismatch",
}


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _optional_float(value: Any) -> Optional[float]:
    """函数 _optional_float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _float_for_sort(value: Any, default: float = 1e18) -> float:
    """函数 _float_for_sort：执行该模块中的相关处理逻辑。"""
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _whole_count(value: Any, field_name: str) -> int:
    """函数 _whole_count：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}")
    text = _clean(value)
    if not text:
        return 0
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}") from exc
    if not math.isfinite(number) or number < 0.0 or not number.is_integer():
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}")
    return int(number)


def read_match_rows(path: Path) -> list[dict[str, str]]:
    """函数 read_match_rows：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_rows(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    """函数 write_rows：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def candidate_row(row: dict[str, str]) -> dict[str, Any]:
    """函数 candidate_row：执行该模块中的相关处理逻辑。"""
    start_gap = _optional_float(row.get("start_time_gap_s"))
    end_gap = _optional_float(row.get("end_time_gap_s"))
    max_gap = None if start_gap is None or end_gap is None else max(start_gap, end_gap)
    return {
        "interval_source_file": row.get("interval_source_file", ""),
        "interval_source_row": row.get("interval_source_row", ""),
        "guid": row.get("guid", ""),
        "station_trainid": row.get("station_trainid", ""),
        "realtime_trainid": row.get("realtime_trainid", ""),
        "normalized_trainid": row.get("normalized_trainid", ""),
        "start_station": row.get("start_station", ""),
        "end_station": row.get("end_station", ""),
        "station_starttime": row.get("station_starttime", ""),
        "station_endtime": row.get("station_endtime", ""),
        "start_recordtime": row.get("start_recordtime", ""),
        "end_recordtime": row.get("end_recordtime", ""),
        "station_use_ygdn": row.get("station_use_ygdn", ""),
        "station_use_fkdn": row.get("station_use_fkdn", ""),
        "matched_use_ygdn": row.get("matched_use_ygdn", ""),
        "matched_use_fkdn": row.get("matched_use_fkdn", ""),
        "ygdn_diff": row.get("ygdn_diff", ""),
        "fkdn_diff": row.get("fkdn_diff", ""),
        "start_time_gap_s": row.get("start_time_gap_s", ""),
        "end_time_gap_s": row.get("end_time_gap_s", ""),
        "max_time_gap_s": "" if max_gap is None else round(max_gap, 6),
        "point_count_in_window": row.get("point_count_in_window", ""),
        "match_status": row.get("match_status", ""),
        "match_quality": row.get("match_quality", ""),
        "notes": row.get("notes", ""),
    }


def mismatch_row(row: dict[str, str]) -> dict[str, Any]:
    """函数 mismatch_row：执行该模块中的相关处理逻辑。"""
    ygdn_diff = _optional_float(row.get("ygdn_diff"))
    fkdn_diff = _optional_float(row.get("fkdn_diff"))
    total_abs_diff = None if ygdn_diff is None or fkdn_diff is None else ygdn_diff + fkdn_diff
    station_use_ygdn = _optional_float(row.get("station_use_ygdn"))
    station_use_fkdn = _optional_float(row.get("station_use_fkdn"))
    matched_use_ygdn = _optional_float(row.get("matched_use_ygdn"))
    matched_use_fkdn = _optional_float(row.get("matched_use_fkdn"))
    ygdn_ratio = None if station_use_ygdn in (None, 0.0) or matched_use_ygdn is None else matched_use_ygdn / station_use_ygdn
    fkdn_ratio = None if station_use_fkdn in (None, 0.0) or matched_use_fkdn is None else matched_use_fkdn / station_use_fkdn
    return {
        **candidate_row(row),
        "total_abs_energy_diff": "" if total_abs_diff is None else round(total_abs_diff, 6),
        "ygdn_ratio_matched_to_station": "" if ygdn_ratio is None else round(ygdn_ratio, 6),
        "fkdn_ratio_matched_to_station": "" if fkdn_ratio is None else round(fkdn_ratio, 6),
        "diagnosis_hint": diagnosis_hint(row, ygdn_ratio, fkdn_ratio),
    }


def diagnosis_hint(row: dict[str, str], ygdn_ratio: Optional[float], fkdn_ratio: Optional[float]) -> str:
    """函数 diagnosis_hint：执行该模块中的相关处理逻辑。"""
    point_count = _whole_count(row.get("point_count_in_window"), "point_count_in_window")
    start_gap = _float_for_sort(row.get("start_time_gap_s"), 1e18)
    end_gap = _float_for_sort(row.get("end_time_gap_s"), 1e18)
    if point_count <= 0:
        return "no_realtime_point_inside_interval"
    if start_gap > 300 or end_gap > 300:
        return "boundary_time_gap_large"
    ratios = [value for value in (ygdn_ratio, fkdn_ratio) if value is not None]
    if ratios and all(0.45 <= value <= 0.55 for value in ratios):
        return "matched_meter_about_half_of_station_energy_check_if_A_B_or_dual_meter_should_be_aggregated"
    if ratios and all(1.8 <= value <= 2.2 for value in ratios):
        return "matched_meter_about_double_station_energy_check_station_scope_or_duplicate_meter"
    return "energy_scope_or_meter_selection_mismatch"


def analyze_matches(match_csv: Path, output_dir: Path) -> dict[str, Any]:
    """函数 analyze_matches：执行该模块中的相关处理逻辑。"""
    rows = read_match_rows(match_csv)
    candidates = [candidate_row(row) for row in rows if row.get("match_status") in CALIBRATION_STATUSES]
    mismatches = [mismatch_row(row) for row in rows if row.get("match_status") in MISMATCH_STATUSES]
    candidates.sort(key=lambda row: (_float_for_sort(row.get("max_time_gap_s")), row.get("normalized_trainid", ""), row.get("station_starttime", "")))
    mismatches.sort(key=lambda row: (_float_for_sort(row.get("total_abs_energy_diff"), 0.0), row.get("normalized_trainid", "")), reverse=True)

    candidate_fields = [
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
        "max_time_gap_s",
        "point_count_in_window",
        "match_status",
        "match_quality",
        "notes",
    ]
    mismatch_fields = candidate_fields + [
        "total_abs_energy_diff",
        "ygdn_ratio_matched_to_station",
        "fkdn_ratio_matched_to_station",
        "diagnosis_hint",
    ]
    candidate_csv = output_dir / "smart_meter_calibration_candidates.csv"
    mismatch_csv = output_dir / "smart_meter_mismatch_analysis.csv"
    write_rows(candidate_csv, candidates, candidate_fields)
    write_rows(mismatch_csv, mismatches, mismatch_fields)

    status_counts: dict[str, int] = {}
    train_counts: dict[str, int] = {}
    diagnosis_counts: dict[str, int] = {}
    for row in rows:
        status = row.get("match_status", "")
        status_counts[status] = status_counts.get(status, 0) + 1
    for row in candidates:
        key = f"{row.get('normalized_trainid')}->{row.get('realtime_trainid')}"
        train_counts[key] = train_counts.get(key, 0) + 1
    for row in mismatches:
        key = str(row.get("diagnosis_hint", ""))
        diagnosis_counts[key] = diagnosis_counts.get(key, 0) + 1
    summary = {
        "input_csv": str(match_csv),
        "total_match_rows": len(rows),
        "candidate_count": len(candidates),
        "mismatch_count": len(mismatches),
        "status_counts": dict(sorted(status_counts.items())),
        "candidate_train_counts": dict(sorted(train_counts.items())),
        "mismatch_diagnosis_counts": dict(sorted(diagnosis_counts.items())),
        "outputs": {
            "calibration_candidates": str(candidate_csv),
            "mismatch_analysis": str(mismatch_csv),
        },
    }
    (output_dir / "smart_meter_match_analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Analyze smart-meter time-window matching results.")
    parser.add_argument("--match-csv", type=Path, default=DEFAULT_MATCH_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = analyze_matches(args.match_csv, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
