# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json

from energy_calibration_alignment import load_station_positions, resolve_station
import math
from datetime import datetime


DEFAULT_CANDIDATE_CSV = Path("outputs") / "smart_meter_time_matching" / "smart_meter_calibration_candidates.csv"
DEFAULT_OUTPUT_CSV = Path("data") / "real_shuohuang" / "smart_meter_calibration_samples.csv"

OUTPUT_FIELDS = [
    "sample_id",
    "source_guid",
    "interval_source_file",
    "interval_source_row",
    "trainid",
    "normalized_trainid",
    "realtime_trainid",
    "starttime",
    "endtime",
    "start_station",
    "end_station",
    "traction_energy_raw",
    "regen_energy_raw",
    "net_energy_raw",
    "matched_traction_energy_raw",
    "matched_regen_energy_raw",
    "traction_energy_diff_raw",
    "regen_energy_diff_raw",
    "duration_s",
    "point_count_in_window",
    "start_time_gap_s",
    "end_time_gap_s",
    "max_time_gap_s",
    "energy_source",
    "energy_unit_status",
    "match_status",
    "match_quality",
    "calibration_status",
    "notes",
]

CONFIRMED_ENERGY_UNIT_STATUS = "confirmed_kwh_from_provider_reply"


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


def _fmt_number(value: Optional[float]) -> str:
    """函数 _fmt_number：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _parse_datetime(value: Any) -> Optional[datetime]:
    """函数 _parse_datetime：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _sort_number(value: Any, default: float = 1e18) -> float:
    """函数 _sort_number：执行该模块中的相关处理逻辑。"""
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _duration_s(start: str, end: str) -> str:
    """函数 _duration_s：执行该模块中的相关处理逻辑。"""
    start_dt = _parse_datetime(start)
    end_dt = _parse_datetime(end)
    if start_dt is None or end_dt is None:
        return ""
    return _fmt_number((end_dt - start_dt).total_seconds())


def build_sample(row: dict[str, str], index: int) -> dict[str, str]:
    """函数 build_sample：执行该模块中的相关处理逻辑。"""
    traction = _optional_float(row.get("station_use_ygdn"))
    regen = _optional_float(row.get("station_use_fkdn"))
    matched_traction = _optional_float(row.get("matched_use_ygdn"))
    matched_regen = _optional_float(row.get("matched_use_fkdn"))
    traction_diff = _optional_float(row.get("ygdn_diff"))
    regen_diff = _optional_float(row.get("fkdn_diff"))
    net = None if traction is None or regen is None else traction - regen
    match_status = _clean(row.get("match_status"))
    if (traction or 0.0) == 0.0 and (regen or 0.0) == 0.0:
        calibration_status = "zero_energy_review_only"
    elif match_status == "matched_energy_consistent":
        calibration_status = "usable_high_confidence"
    elif match_status == "matched_energy_consistent_boundary_gap_large":
        calibration_status = "usable_with_boundary_gap_review"
    else:
        calibration_status = "not_selected"
    return {
        "sample_id": f"SMC-{index:06d}",
        "source_guid": _clean(row.get("guid")),
        "interval_source_file": _clean(row.get("interval_source_file")),
        "interval_source_row": _clean(row.get("interval_source_row")),
        "trainid": _clean(row.get("station_trainid")),
        "normalized_trainid": _clean(row.get("normalized_trainid")),
        "realtime_trainid": _clean(row.get("realtime_trainid")),
        "starttime": _clean(row.get("station_starttime")),
        "endtime": _clean(row.get("station_endtime")),
        "start_station": _clean(row.get("start_station")),
        "end_station": _clean(row.get("end_station")),
        "traction_energy_raw": _fmt_number(traction),
        "regen_energy_raw": _fmt_number(regen),
        "net_energy_raw": _fmt_number(net),
        "matched_traction_energy_raw": _fmt_number(matched_traction),
        "matched_regen_energy_raw": _fmt_number(matched_regen),
        "traction_energy_diff_raw": _fmt_number(traction_diff),
        "regen_energy_diff_raw": _fmt_number(regen_diff),
        "duration_s": _duration_s(row.get("station_starttime", ""), row.get("station_endtime", "")),
        "point_count_in_window": _clean(row.get("point_count_in_window")),
        "start_time_gap_s": _clean(row.get("start_time_gap_s")),
        "end_time_gap_s": _clean(row.get("end_time_gap_s")),
        "max_time_gap_s": _clean(row.get("max_time_gap_s")),
        "energy_source": "station_interval_use_confirmed_by_ss4_time_window_match",
        "energy_unit_status": CONFIRMED_ENERGY_UNIT_STATUS,
        "match_status": match_status,
        "match_quality": _clean(row.get("match_quality")),
        "calibration_status": calibration_status,
        "notes": "; ".join(
            note
            for note in [
                _clean(row.get("notes")),
                "zero traction energy may indicate shunting/no-pantograph or statistics issue" if calibration_status == "zero_energy_review_only" else "",
            ]
            if note
        ),
    }


def select_representative_candidates(
    rows: Sequence[dict[str, str]],
    *,
    max_per_realtime_trainid: int,
) -> list[dict[str, str]]:
    """函数 select_representative_candidates：执行该模块中的相关处理逻辑。"""
    if max_per_realtime_trainid <= 0:
        raise ValueError("max_per_realtime_trainid must be positive.")

    def key(row: dict[str, str]) -> tuple[float, float, str, str]:
        """函数 key：执行该模块中的相关处理逻辑。"""
        status_penalty = 0.0 if row.get("match_status") == "matched_energy_consistent" else 1.0
        return (
            status_penalty,
            _sort_number(row.get("max_time_gap_s")),
            row.get("normalized_trainid", ""),
            row.get("station_starttime", ""),
        )

    selected: list[dict[str, str]] = []
    by_realtime_trainid: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        realtime_trainid = _clean(row.get("realtime_trainid")) or _clean(row.get("normalized_trainid")) or "unknown"
        by_realtime_trainid.setdefault(realtime_trainid, []).append(row)
    for realtime_trainid in sorted(by_realtime_trainid):
        group = sorted(by_realtime_trainid[realtime_trainid], key=key)
        selected.extend(group[:max_per_realtime_trainid])
    return selected



def filter_mainline_mapped_nonzero_samples(
    samples: Sequence[dict[str, str]],
    station_csv: Path,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Keep samples whose endpoints map to mainline stations with nonzero distance and traction."""
    station_map = load_station_positions(station_csv)
    kept: list[dict[str, str]] = []
    counts = {
        "input_count": len(samples),
        "excluded_unmapped": 0,
        "excluded_zero_distance": 0,
        "excluded_zero_traction": 0,
        "selected": 0,
    }
    for sample in samples:
        start_name, start_km, start_status = resolve_station(sample.get("start_station", ""), station_map)
        end_name, end_km, end_status = resolve_station(sample.get("end_station", ""), station_map)
        if start_status == "station_unmapped" or end_status == "station_unmapped" or start_km is None or end_km is None:
            counts["excluded_unmapped"] += 1
            continue
        if abs(end_km - start_km) <= 1e-9:
            counts["excluded_zero_distance"] += 1
            continue
        traction = _optional_float(sample.get("traction_energy_raw"))
        if traction is None or traction <= 0:
            counts["excluded_zero_traction"] += 1
            continue
        refined = dict(sample)
        refined["notes"] = "; ".join(
            note for note in [
                _clean(sample.get("notes")),
                f"mainline_mapped:{start_name}->{end_name}",
            ] if note
        )
        kept.append(refined)
    counts["selected"] = len(kept)
    return kept, counts


def build_calibration_samples(
    candidate_csv: Path,
    output_csv: Path,
    *,
    representative: bool = False,
    max_per_realtime_trainid: int = 20,
    station_csv: Optional[Path] = None,
    mainline_only: bool = False,
) -> dict[str, Any]:
    """函数 build_calibration_samples：执行该模块中的相关处理逻辑。"""
    with candidate_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        candidates = [dict(row) for row in csv.DictReader(handle)]
    selected = [
        row
        for row in candidates
        if row.get("match_status") in {"matched_energy_consistent", "matched_energy_consistent_boundary_gap_large"}
    ]
    raw_selected_count = len(selected)
    if representative:
        selected = select_representative_candidates(selected, max_per_realtime_trainid=max_per_realtime_trainid)
    samples = [build_sample(row, idx) for idx, row in enumerate(selected, start=1)]
    mainline_filter_counts: dict[str, int] = {}
    selection_policy = "representative_by_realtime_trainid" if representative else "all_usable_candidates"
    if mainline_only:
        if station_csv is None:
            raise ValueError("station_csv is required when mainline_only=True")
        samples, mainline_filter_counts = filter_mainline_mapped_nonzero_samples(samples, station_csv)
        # 过滤后重新编排样本 ID。
        for idx, sample in enumerate(samples, start=1):
            sample["sample_id"] = f"SMC-{idx:06d}"
        selection_policy = selection_policy + "+mainline_mapped_nonzero_traction"
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(samples)

    by_status: dict[str, int] = {}
    by_realtime_trainid: dict[str, int] = {}
    for sample in samples:
        by_status[sample["calibration_status"]] = by_status.get(sample["calibration_status"], 0) + 1
        by_realtime_trainid[sample["realtime_trainid"]] = by_realtime_trainid.get(sample["realtime_trainid"], 0) + 1
    summary = {
        "input_candidate_csv": str(candidate_csv),
        "output_csv": str(output_csv),
        "selection_policy": selection_policy,
        "raw_usable_candidate_count": raw_selected_count,
        "sample_count": len(samples),
        "max_per_realtime_trainid": max_per_realtime_trainid if representative else None,
        "covered_realtime_trainid_count": len(by_realtime_trainid),
        "calibration_status_counts": dict(sorted(by_status.items())),
        "realtime_trainid_counts": dict(sorted(by_realtime_trainid.items())),
        "energy_unit_status": CONFIRMED_ENERGY_UNIT_STATUS,
        "mainline_only": mainline_only,
        "mainline_filter_counts": mainline_filter_counts,
        "station_csv": str(station_csv) if station_csv is not None else "",
    }
    summary_path = output_csv.with_name(output_csv.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Build algorithm-ready smart-meter energy calibration samples.")
    parser.add_argument("--candidate-csv", type=Path, default=DEFAULT_CANDIDATE_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--representative", action="store_true", help="Select a compact representative sample set by realtime trainid.")
    parser.add_argument("--max-per-realtime-trainid", type=int, default=20)
    parser.add_argument("--station-csv", type=Path, default=None, help="Mainline stations.csv used when --mainline-only is set.")
    parser.add_argument("--mainline-only", action="store_true", help="Keep only samples mapped to mainline stations with nonzero distance and traction.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = build_calibration_samples(
        args.candidate_csv,
        args.output_csv,
        representative=args.representative,
        max_per_realtime_trainid=args.max_per_realtime_trainid,
        station_csv=args.station_csv,
        mainline_only=args.mainline_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
