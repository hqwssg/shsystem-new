# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
from datetime import datetime
import json
import math
import re

from energy_calibration_factors import load_energy_calibration_config, resolve_energy_calibration_factor
from heavy_empty_network_optimizer import _arc_infrastructure_attributes, load_infrastructure_profile


DEFAULT_SAMPLE_CSV = Path("data") / "real_shuohuang" / "smart_meter_calibration_samples.csv"
DEFAULT_REPRESENTATIVE_SAMPLE_CSV = Path("data") / "real_shuohuang" / "smart_meter_representative_interval_samples.csv"
DEFAULT_STATION_CSV = Path("data") / "real_shuohuang" / "stations.csv"
DEFAULT_OUTPUT_DIR = Path("outputs") / "energy_calibration"
DEFAULT_BASE_TRACTION_RAW_PER_KM = 25.0
DEFAULT_REGEN_RECOVERY_RATIO = 0.65
DEFAULT_FACTOR_JSON = Path("data") / "real_shuohuang" / "energy_calibration_factors.json"
DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
CALIBRATION_MODES = {"none", "global", "grouped"}


OUTPUT_FIELDS = [
    "sample_id",
    "trainid",
    "realtime_trainid",
    "starttime",
    "endtime",
    "start_station",
    "end_station",
    "matched_start_station",
    "matched_end_station",
    "start_km",
    "end_km",
    "distance_km",
    "duration_s",
    "avg_speed_kmh",
    "travel_direction",
    "meter_traction_energy_raw",
    "meter_regen_energy_raw",
    "meter_net_energy_raw",
    "prototype_base_energy_raw",
    "prototype_traction_energy_raw",
    "prototype_regen_energy_raw",
    "prototype_net_energy_raw",
    "energy_calibration_mode",
    "calibration_applied",
    "calibration_factor_status",
    "applied_traction_scale",
    "applied_scale_level",
    "applied_scale_value",
    "calibrated_prototype_traction_energy_raw",
    "calibrated_prototype_net_energy_raw",
    "traction_error_raw",
    "regen_error_raw",
    "net_error_raw",
    "calibrated_traction_error_raw",
    "calibrated_net_error_raw",
    "traction_error_pct",
    "regen_error_pct",
    "calibrated_traction_error_pct",
    "avg_gradient_promille",
    "curve_equivalent",
    "energy_multiplier",
    "gradient_sample_count",
    "curve_positioned_count",
    "power_arm_ids",
    "power_arm_review_required",
    "match_status",
    "calibration_status",
    "alignment_status",
    "estimate_status",
    "notes",
]


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


def _first_float(row: dict[str, str], *keys: str) -> Optional[float]:
    """函数 _first_float：执行该模块中的相关处理逻辑。"""
    for key in keys:
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    return None


def _first_text(row: dict[str, str], *keys: str) -> str:
    """函数 _first_text：执行该模块中的相关处理逻辑。"""
    for key in keys:
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _fmt(value: Optional[float]) -> str:
    """函数 _fmt：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def normalize_station_name(value: str) -> str:
    """函数 normalize_station_name：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    text = re.sub(r"\s+", "", text)
    text = text.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    text = re.sub(r"(I|II|III|1|2|3)?场$", "", text)
    text = text.replace("（", "(").replace("）", ")")
    return text


def load_station_positions(path: Path) -> dict[str, tuple[str, float]]:
    """函数 load_station_positions：执行该模块中的相关处理逻辑。"""
    mapping: dict[str, tuple[str, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = _clean(row.get("name"))
            km = _optional_float(row.get("position_km"))
            if not name or km is None:
                continue
            mapping[normalize_station_name(name)] = (name, km)
    return mapping


def resolve_station(raw_name: str, station_map: dict[str, tuple[str, float]]) -> tuple[str, Optional[float], str]:
    """函数 resolve_station：执行该模块中的相关处理逻辑。"""
    key = normalize_station_name(raw_name)
    if key in station_map:
        name, km = station_map[key]
        return name, km, "exact_or_normalized"
    for candidate_key, (name, km) in station_map.items():
        if key and (key.startswith(candidate_key) or candidate_key in key):
            return name, km, "contains_station_name"
    return "", None, "station_unmapped"


def _direction(start_km: float, end_km: float) -> str:
    """函数 _direction：执行该模块中的相关处理逻辑。"""
    if end_km > start_km:
        return "down"
    if end_km < start_km:
        return "up"
    return "stationary"


def _parse_time(value: Any) -> Optional[datetime]:
    """函数 _parse_time：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _duration_seconds(row: dict[str, str]) -> Optional[float]:
    """函数 _duration_seconds：执行该模块中的相关处理逻辑。"""
    duration = _optional_float(row.get("duration_s"))
    if duration is not None:
        return duration
    start = _parse_time(row.get("starttime"))
    end = _parse_time(row.get("endtime"))
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    return seconds if seconds > 0 else None


def _pct_error(error: Optional[float], actual: Optional[float]) -> Optional[float]:
    """函数 _pct_error：执行该模块中的相关处理逻辑。"""
    if error is None or actual is None or abs(actual) < 1e-9:
        return None
    return error / actual * 100.0


def align_sample(
    row: dict[str, str],
    station_map: dict[str, tuple[str, float]],
    profile,
    *,
    base_traction_raw_per_km: float,
    regen_recovery_ratio: float,
    calibration_mode: str,
    factor_config: dict[str, Any],
) -> dict[str, str]:
    """函数 align_sample：执行该模块中的相关处理逻辑。"""
    start_station = _clean(row.get("start_station"))
    end_station = _clean(row.get("end_station"))
    matched_start, start_km, start_status = resolve_station(start_station, station_map)
    matched_end, end_km, end_status = resolve_station(end_station, station_map)
    traction = _first_float(row, "traction_energy_raw", "use_ygdn_kwh")
    regen = _first_float(row, "regen_energy_raw", "use_fkdn_kwh")
    meter_net = _first_float(row, "net_energy_raw")
    if meter_net is None and traction is not None and regen is not None:
        meter_net = traction - regen

    base_energy = prototype_traction = prototype_regen = prototype_net = None
    traction_error = regen_error = net_error = None
    calibrated_traction = calibrated_net = calibrated_traction_error = calibrated_net_error = None
    applied_scale = 1.0
    applied_scale_level = "none"
    applied_scale_value = "none"
    calibration_applied = False
    calibration_factor_status = "not_requested"
    avg_speed = distance = None
    infra = None
    estimate_status = "not_estimated_station_unmapped"
    alignment_status = start_status if start_status != "exact_or_normalized" else end_status
    if start_km is not None and end_km is not None:
        distance = abs(end_km - start_km)
        duration = _duration_seconds(row)
        avg_speed = None if not duration or duration <= 0 else distance / duration * 3600.0
        if distance <= 1e-9:
            estimate_status = "not_estimated_zero_distance"
            alignment_status = "zero_distance"
        else:
            infra = _arc_infrastructure_attributes(profile, start_km, end_km)
            base_energy = distance * base_traction_raw_per_km
            prototype_traction = max(0.0, base_energy * infra.energy_multiplier)
            downhill_reduction = max(0.0, base_energy - prototype_traction)
            prototype_regen = downhill_reduction * regen_recovery_ratio
            prototype_net = prototype_traction - prototype_regen
            if calibration_mode == "global":
                factor = resolve_energy_calibration_factor(config=factor_config)
                calibration_factor_status = factor.coefficient_status
                if factor.coefficient_status == "usable":
                    applied_scale = factor.traction_scale
                    applied_scale_level = factor.group_level
                    applied_scale_value = factor.group_value
                    calibration_applied = True
            elif calibration_mode == "grouped":
                factor = resolve_energy_calibration_factor(
                    travel_direction=_direction(start_km, end_km),
                    aggregation_type="aggregated_ab" if "+" in _first_text(row, "realtime_trainid", "realtime_trainid_coverage_key") else "single_meter",
                    config=factor_config,
                )
                calibration_factor_status = factor.coefficient_status
                if factor.coefficient_status == "usable":
                    applied_scale = factor.traction_scale
                    applied_scale_level = factor.group_level
                    applied_scale_value = factor.group_value
                    calibration_applied = True
            calibrated_traction = prototype_traction * applied_scale
            calibrated_net = calibrated_traction - prototype_regen
            traction_error = None if traction is None else prototype_traction - traction
            regen_error = None if regen is None else prototype_regen - regen
            net_error = None if meter_net is None else prototype_net - meter_net
            calibrated_traction_error = None if traction is None else calibrated_traction - traction
            calibrated_net_error = None if meter_net is None else calibrated_net - meter_net
            estimate_status = "prototype_estimate_not_calibrated"
            if calibration_applied:
                estimate_status = f"prototype_estimate_with_{calibration_mode}_calibration"
            alignment_status = "aligned"

    notes = []
    if start_status != "exact_or_normalized":
        notes.append(f"start_station_match={start_status}")
    if end_status != "exact_or_normalized":
        notes.append(f"end_station_match={end_status}")
    if calibration_mode != "none" and not calibration_applied:
        notes.append(f"requested_calibration_unavailable={calibration_factor_status}")
    notes.append("prototype estimate uses infrastructure multiplier and uncalibrated base raw/km")

    return {
        "sample_id": _clean(row.get("sample_id")),
        "trainid": _clean(row.get("trainid")),
        "realtime_trainid": _first_text(row, "realtime_trainid", "realtime_trainid_coverage_key"),
        "starttime": _clean(row.get("starttime")),
        "endtime": _clean(row.get("endtime")),
        "start_station": start_station,
        "end_station": end_station,
        "matched_start_station": matched_start,
        "matched_end_station": matched_end,
        "start_km": _fmt(start_km),
        "end_km": _fmt(end_km),
        "distance_km": _fmt(distance),
        "duration_s": _fmt(_duration_seconds(row)),
        "avg_speed_kmh": _fmt(avg_speed),
        "travel_direction": "" if start_km is None or end_km is None else _direction(start_km, end_km),
        "meter_traction_energy_raw": _fmt(traction),
        "meter_regen_energy_raw": _fmt(regen),
        "meter_net_energy_raw": _fmt(meter_net),
        "prototype_base_energy_raw": _fmt(base_energy),
        "prototype_traction_energy_raw": _fmt(prototype_traction),
        "prototype_regen_energy_raw": _fmt(prototype_regen),
        "prototype_net_energy_raw": _fmt(prototype_net),
        "energy_calibration_mode": calibration_mode,
        "calibration_applied": str(calibration_applied),
        "calibration_factor_status": calibration_factor_status,
        "applied_traction_scale": _fmt(applied_scale if prototype_traction is not None else None),
        "applied_scale_level": applied_scale_level,
        "applied_scale_value": applied_scale_value,
        "calibrated_prototype_traction_energy_raw": _fmt(calibrated_traction),
        "calibrated_prototype_net_energy_raw": _fmt(calibrated_net),
        "traction_error_raw": _fmt(traction_error),
        "regen_error_raw": _fmt(regen_error),
        "net_error_raw": _fmt(net_error),
        "calibrated_traction_error_raw": _fmt(calibrated_traction_error),
        "calibrated_net_error_raw": _fmt(calibrated_net_error),
        "traction_error_pct": _fmt(_pct_error(traction_error, traction)),
        "regen_error_pct": _fmt(_pct_error(regen_error, regen)),
        "calibrated_traction_error_pct": _fmt(_pct_error(calibrated_traction_error, traction)),
        "avg_gradient_promille": "" if infra is None else _fmt(infra.avg_gradient_promille),
        "curve_equivalent": "" if infra is None else _fmt(infra.curve_equivalent),
        "energy_multiplier": "" if infra is None else _fmt(infra.energy_multiplier),
        "gradient_sample_count": "" if infra is None else str(infra.gradient_sample_count),
        "curve_positioned_count": "" if infra is None else str(infra.curve_positioned_count),
        "power_arm_ids": "" if infra is None else ";".join(infra.power_arm_ids),
        "power_arm_review_required": "" if infra is None else str(infra.power_arm_review_required),
        "match_status": _first_text(row, "match_status", "data_status"),
        "calibration_status": _first_text(row, "calibration_status", "calibration_role"),
        "alignment_status": alignment_status,
        "estimate_status": estimate_status,
        "notes": "; ".join(notes),
    }


def build_alignment(
    sample_csv: Path,
    station_csv: Path,
    output_dir: Path,
    *,
    base_traction_raw_per_km: float = DEFAULT_BASE_TRACTION_RAW_PER_KM,
    regen_recovery_ratio: float = DEFAULT_REGEN_RECOVERY_RATIO,
    energy_calibration_mode: str = "none",
    factor_json: Path = DEFAULT_FACTOR_JSON,
    infrastructure_data_dir: Optional[Path] = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    """函数 build_alignment：执行该模块中的相关处理逻辑。"""
    if energy_calibration_mode not in CALIBRATION_MODES:
        raise ValueError(f"energy_calibration_mode must be one of {sorted(CALIBRATION_MODES)}")
    station_map = load_station_positions(station_csv)
    profile = load_infrastructure_profile(infrastructure_data_dir)
    factor_config = load_energy_calibration_config(factor_json) if energy_calibration_mode != "none" else {}
    with sample_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    aligned = [
        align_sample(
            row,
            station_map,
            profile,
            base_traction_raw_per_km=base_traction_raw_per_km,
            regen_recovery_ratio=regen_recovery_ratio,
            calibration_mode=energy_calibration_mode,
            factor_config=factor_config,
        )
        for row in rows
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "arc_energy_vs_meter_samples.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(aligned)

    status_counts: dict[str, int] = {}
    estimate_counts: dict[str, int] = {}
    calibration_factor_counts: dict[str, int] = {}
    for row in aligned:
        status_counts[row["alignment_status"]] = status_counts.get(row["alignment_status"], 0) + 1
        estimate_counts[row["estimate_status"]] = estimate_counts.get(row["estimate_status"], 0) + 1
        factor_status = row["calibration_factor_status"]
        calibration_factor_counts[factor_status] = calibration_factor_counts.get(factor_status, 0) + 1
    summary = {
        "sample_count": len(aligned),
        "alignment_status_counts": dict(sorted(status_counts.items())),
        "estimate_status_counts": dict(sorted(estimate_counts.items())),
        "calibration_factor_status_counts": dict(sorted(calibration_factor_counts.items())),
        "calibration_applied_count": sum(row["calibration_applied"] == "True" for row in aligned),
        "base_traction_raw_per_km": base_traction_raw_per_km,
        "regen_recovery_ratio": regen_recovery_ratio,
        "energy_calibration_mode": energy_calibration_mode,
        "factor_json": str(factor_json) if energy_calibration_mode != "none" else "",
        "infrastructure_data_dir": str(infrastructure_data_dir),
        "output_csv": str(output_csv),
        "estimate_note": (
            "Calibration was applied only to rows whose selected coefficient status is usable."
            if any(row["calibration_applied"] == "True" for row in aligned)
            else "No usable calibration coefficient was applied; estimates remain uncalibrated prototypes."
        ),
    }
    (output_dir / "arc_energy_vs_meter_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Align smart-meter calibration samples with route arcs and prototype energy estimates.")
    parser.add_argument("--sample-csv", type=Path, default=DEFAULT_SAMPLE_CSV)
    parser.add_argument("--station-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-traction-raw-per-km", type=float, default=DEFAULT_BASE_TRACTION_RAW_PER_KM)
    parser.add_argument("--regen-recovery-ratio", type=float, default=DEFAULT_REGEN_RECOVERY_RATIO)
    parser.add_argument("--energy-calibration", choices=sorted(CALIBRATION_MODES), default="none")
    parser.add_argument("--factor-json", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    station_csv = args.station_csv or args.data_dir / DEFAULT_STATION_CSV.name
    factor_json = args.factor_json or args.data_dir / DEFAULT_FACTOR_JSON.name
    summary = build_alignment(
        args.sample_csv,
        station_csv,
        args.output_dir,
        base_traction_raw_per_km=args.base_traction_raw_per_km,
        regen_recovery_ratio=args.regen_recovery_ratio,
        energy_calibration_mode=args.energy_calibration,
        factor_json=factor_json,
        infrastructure_data_dir=args.data_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
