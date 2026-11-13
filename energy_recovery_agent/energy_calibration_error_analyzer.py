# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math
import statistics


DEFAULT_ALIGNMENT_CSV = Path("outputs") / "energy_calibration" / "arc_energy_vs_meter_samples.csv"
DEFAULT_OUTPUT_DIR = Path("outputs") / "energy_calibration"
MIN_GROUP_SAMPLE_COUNT = 30


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


def _mean(values: list[float]) -> Optional[float]:
    """函数 _mean：执行该模块中的相关处理逻辑。"""
    return None if not values else sum(values) / len(values)


def _median(values: list[float]) -> Optional[float]:
    """函数 _median：执行该模块中的相关处理逻辑。"""
    return None if not values else statistics.median(values)


def _percentile(values: list[float], q: float) -> Optional[float]:
    """函数 _percentile：执行该模块中的相关处理逻辑。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _fmt(value: Optional[float]) -> str:
    """函数 _fmt：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def read_rows(path: Path) -> list[dict[str, str]]:
    """函数 read_rows：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def usable_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """函数 usable_rows：执行该模块中的相关处理逻辑。"""
    result = []
    for row in rows:
        if row.get("alignment_status") != "aligned":
            continue
        if row.get("estimate_status") != "prototype_estimate_not_calibrated":
            continue
        meter = _optional_float(row.get("meter_traction_energy_raw"))
        proto = _optional_float(row.get("prototype_traction_energy_raw"))
        if meter is None or proto is None or meter <= 0 or proto <= 0:
            continue
        result.append(row)
    return result


def sample_stratum(row: dict[str, str]) -> str:
    """Classify samples for fit vs review-only diagnostics.

    - fit_core: energy-consistent aggregated A/B samples suitable for coefficient fitting
    - review_boundary_gap: energy matches but boundary time gap is large
    - review_single_meter: only one of A/B matched; not used for default fit
    - review_short_stop: very short/low-distance intervals kept for diagnostics only
    - review_zero_or_invalid: zero/nonpositive energy or invalid kinematics
    - review_low_intensity: traction intensity too low for default heavy-haul fit
    - out_of_ratio_band: otherwise eligible but ratio is extreme
    """
    ratio = ratio_for(row)
    distance = _optional_float(row.get("distance_km"))
    speed = _optional_float(row.get("avg_speed_kmh"))
    duration = _optional_float(row.get("duration_s"))
    meter = _optional_float(row.get("meter_traction_energy_raw"))
    calibration_status = _clean(row.get("calibration_status"))
    realtime = _clean(row.get("realtime_trainid"))
    agg = aggregation_type(realtime)

    if meter is None or meter <= 0 or calibration_status == "zero_energy_review_only":
        return "review_zero_or_invalid"
    if distance is None or speed is None or duration is None:
        return "review_zero_or_invalid"
    if distance < 1.0 or speed < 5.0 or speed > 100.0:
        return "review_zero_or_invalid"
    # 短停或类似站场的诊断样本保留供复核，但不纳入默认拟合。
    if duration < 20 * 60 or distance < 8.0:
        return "review_short_stop"
    # 极低强度通常不能代表重载牵引，不适合用于系数拟合。
    intensity = meter / distance
    if intensity < 5.0:
        return "review_low_intensity"
    if agg != "aggregated_ab":
        return "review_single_meter"
    if calibration_status == "usable_with_boundary_gap_review":
        return "review_boundary_gap"
    if ratio is None or ratio < 0.05 or ratio > 3.0:
        return "out_of_ratio_band"
    if calibration_status and calibration_status not in {"usable_high_confidence", "usable_with_boundary_gap_review"}:
        # 优先选择高置信度样本；边界缺口已在前面处理。
        return "review_zero_or_invalid"
    return "fit_core"


def robust_fit_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Default coefficient fitting set: only fit_core samples.

    Zero-energy, short-stop/yard-like, single-meter and extreme-ratio samples remain
    available for diagnostics/review, but do not drive default traction scales.
    """
    return [row for row in rows if sample_stratum(row) == "fit_core"]


def ratio_for(row: dict[str, str]) -> Optional[float]:
    """函数 ratio_for：执行该模块中的相关处理逻辑。"""
    meter = _optional_float(row.get("meter_traction_energy_raw"))
    proto = _optional_float(row.get("prototype_traction_energy_raw"))
    if meter is None or proto is None or proto <= 0:
        return None
    return meter / proto


def abs_pct_error_for(row: dict[str, str], scale: float = 1.0) -> Optional[float]:
    """函数 abs_pct_error_for：执行该模块中的相关处理逻辑。"""
    meter = _optional_float(row.get("meter_traction_energy_raw"))
    proto = _optional_float(row.get("prototype_traction_energy_raw"))
    if meter is None or proto is None or meter <= 0:
        return None
    return abs(proto * scale - meter) / meter * 100.0


def summarize_group(rows: Sequence[dict[str, str]], group_name: str, group_value: str, scale: float = 1.0) -> dict[str, str]:
    """函数 summarize_group：执行该模块中的相关处理逻辑。"""
    ratios = [value for row in rows if (value := ratio_for(row)) is not None]
    abs_errors = [value for row in rows if (value := abs_pct_error_for(row, scale=scale)) is not None]
    distances = [value for row in rows if (value := _optional_float(row.get("distance_km"))) is not None]
    return {
        "group_name": group_name,
        "group_value": group_value,
        "sample_count": str(len(rows)),
        "distance_km_mean": _fmt(_mean(distances)),
        "ratio_meter_to_prototype_mean": _fmt(_mean(ratios)),
        "ratio_meter_to_prototype_median": _fmt(_median(ratios)),
        "ratio_meter_to_prototype_p10": _fmt(_percentile(ratios, 0.10)),
        "ratio_meter_to_prototype_p90": _fmt(_percentile(ratios, 0.90)),
        "abs_pct_error_mean_after_scale": _fmt(_mean(abs_errors)),
        "abs_pct_error_median_after_scale": _fmt(_median(abs_errors)),
        "abs_pct_error_p90_after_scale": _fmt(_percentile(abs_errors, 0.90)),
    }


def group_rows(rows: Sequence[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    """函数 group_rows：执行该模块中的相关处理逻辑。"""
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        value = _clean(row.get(key)) or "<blank>"
        groups.setdefault(value, []).append(row)
    return groups


def aggregation_type(realtime_trainid: str) -> str:
    """函数 aggregation_type：执行该模块中的相关处理逻辑。"""
    text = _clean(realtime_trainid)
    return "aggregated_ab" if "+" in text else "single_meter"


def build_scaled_error_rows(rows: Sequence[dict[str, str]], scale: float) -> list[dict[str, str]]:
    """函数 build_scaled_error_rows：执行该模块中的相关处理逻辑。"""
    output = []
    for row in rows:
        meter = _optional_float(row.get("meter_traction_energy_raw"))
        proto = _optional_float(row.get("prototype_traction_energy_raw"))
        calibrated = None if proto is None else proto * scale
        error = None if meter is None or calibrated is None else calibrated - meter
        abs_pct = None if error is None or meter is None or meter <= 0 else abs(error) / meter * 100.0
        output.append(
            {
                "sample_id": row.get("sample_id", ""),
                "trainid": row.get("trainid", ""),
                "realtime_trainid": row.get("realtime_trainid", ""),
                "aggregation_type": aggregation_type(row.get("realtime_trainid", "")),
                "travel_direction": row.get("travel_direction", ""),
                "start_station": row.get("start_station", ""),
                "end_station": row.get("end_station", ""),
                "distance_km": row.get("distance_km", ""),
                "meter_traction_energy_raw": row.get("meter_traction_energy_raw", ""),
                "prototype_traction_energy_raw": row.get("prototype_traction_energy_raw", ""),
                "calibrated_prototype_traction_energy_raw": _fmt(calibrated),
                "calibrated_traction_error_raw": _fmt(error),
                "calibrated_abs_pct_error": _fmt(abs_pct),
                "avg_gradient_promille": row.get("avg_gradient_promille", ""),
                "curve_equivalent": row.get("curve_equivalent", ""),
                "energy_multiplier": row.get("energy_multiplier", ""),
            }
        )
    return output


def group_key(row: dict[str, str], level: str) -> str:
    """函数 group_key：执行该模块中的相关处理逻辑。"""
    if level == "direction_aggregation":
        return f"{row.get('travel_direction', '')}|{aggregation_type(row.get('realtime_trainid', ''))}"
    if level == "travel_direction":
        return row.get("travel_direction", "")
    if level == "aggregation_type":
        return aggregation_type(row.get("realtime_trainid", ""))
    if level == "realtime_trainid":
        return row.get("realtime_trainid", "")
    return "all"


def build_group_coefficients(
    rows: Sequence[dict[str, str]],
    *,
    global_scale: float,
    min_group_count: int = MIN_GROUP_SAMPLE_COUNT,
) -> tuple[list[dict[str, str]], dict[tuple[str, str], float]]:
    """函数 build_group_coefficients：执行该模块中的相关处理逻辑。"""
    coefficient_rows: list[dict[str, str]] = []
    coefficient_lookup: dict[tuple[str, str], float] = {}
    for level in ("direction_aggregation", "travel_direction", "aggregation_type", "realtime_trainid"):
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault(group_key(row, level), []).append(row)
        for key, items in sorted(grouped.items()):
            ratios = [value for item in items if (value := ratio_for(item)) is not None]
            if len(ratios) < min_group_count:
                status = "insufficient_samples"
                scale = None
            else:
                status = "usable"
                scale = _median(ratios)
                if scale is not None:
                    coefficient_lookup[(level, key)] = scale
            coefficient_rows.append(
                {
                    "group_level": level,
                    "group_value": key,
                    "sample_count": str(len(items)),
                    "usable_ratio_count": str(len(ratios)),
                    "scale_median": _fmt(scale),
                    "ratio_p10": _fmt(_percentile(ratios, 0.10)),
                    "ratio_p90": _fmt(_percentile(ratios, 0.90)),
                    "coefficient_status": status,
                    "fallback_scale": _fmt(global_scale),
                }
            )
    coefficient_rows.insert(
        0,
        {
            "group_level": "global",
            "group_value": "all",
            "sample_count": str(len(rows)),
            "usable_ratio_count": str(len([row for row in rows if ratio_for(row) is not None])),
            "scale_median": _fmt(global_scale),
            "ratio_p10": "",
            "ratio_p90": "",
            "coefficient_status": "usable",
            "fallback_scale": "",
        },
    )
    return coefficient_rows, coefficient_lookup


def choose_group_scale(row: dict[str, str], coefficient_lookup: dict[tuple[str, str], float], global_scale: float) -> tuple[float, str, str]:
    """函数 choose_group_scale：执行该模块中的相关处理逻辑。"""
    for level in ("direction_aggregation", "travel_direction", "aggregation_type"):
        key = group_key(row, level)
        scale = coefficient_lookup.get((level, key))
        if scale is not None:
            return scale, level, key
    return global_scale, "global", "all"


def build_group_scaled_error_rows(
    rows: Sequence[dict[str, str]],
    coefficient_lookup: dict[tuple[str, str], float],
    global_scale: float,
) -> list[dict[str, str]]:
    """函数 build_group_scaled_error_rows：执行该模块中的相关处理逻辑。"""
    output = []
    for row in rows:
        scale, level, key = choose_group_scale(row, coefficient_lookup, global_scale)
        meter = _optional_float(row.get("meter_traction_energy_raw"))
        proto = _optional_float(row.get("prototype_traction_energy_raw"))
        calibrated = None if proto is None else proto * scale
        error = None if meter is None or calibrated is None else calibrated - meter
        abs_pct = None if error is None or meter is None or meter <= 0 else abs(error) / meter * 100.0
        output.append(
            {
                "sample_id": row.get("sample_id", ""),
                "trainid": row.get("trainid", ""),
                "realtime_trainid": row.get("realtime_trainid", ""),
                "aggregation_type": aggregation_type(row.get("realtime_trainid", "")),
                "travel_direction": row.get("travel_direction", ""),
                "start_station": row.get("start_station", ""),
                "end_station": row.get("end_station", ""),
                "distance_km": row.get("distance_km", ""),
                "meter_traction_energy_raw": row.get("meter_traction_energy_raw", ""),
                "prototype_traction_energy_raw": row.get("prototype_traction_energy_raw", ""),
                "applied_scale": _fmt(scale),
                "scale_group_level": level,
                "scale_group_value": key,
                "group_calibrated_prototype_traction_energy_raw": _fmt(calibrated),
                "group_calibrated_traction_error_raw": _fmt(error),
                "group_calibrated_abs_pct_error": _fmt(abs_pct),
            }
        )
    return output


def write_csv(path: Path, rows: Sequence[dict[str, str]], fieldnames: Sequence[str]) -> None:
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def analyze_energy_errors(alignment_csv: Path, output_dir: Path) -> dict[str, Any]:
    """函数 analyze_energy_errors：执行该模块中的相关处理逻辑。"""
    rows = read_rows(alignment_csv)
    usable = usable_rows(rows)
    ratios = [value for row in usable if (value := ratio_for(row)) is not None]
    robust_rows = robust_fit_rows(usable)
    robust_ratios = [value for row in robust_rows if (value := ratio_for(row)) is not None]
    all_median_scale = _median(ratios) or 1.0
    suggested_scale = _median(robust_ratios) or all_median_scale

    summary_rows: list[dict[str, str]] = [
        summarize_group(usable, "all", "all", scale=suggested_scale),
    ]
    for key in ("travel_direction", "realtime_trainid"):
        for value, items in sorted(group_rows(usable, key).items()):
            summary_rows.append(summarize_group(items, key, value, scale=suggested_scale))
    by_aggregation: dict[str, list[dict[str, str]]] = {}
    for row in usable:
        by_aggregation.setdefault(aggregation_type(row.get("realtime_trainid", "")), []).append(row)
    for value, items in sorted(by_aggregation.items()):
        summary_rows.append(summarize_group(items, "aggregation_type", value, scale=suggested_scale))

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = output_dir / "energy_calibration_error_summary.csv"
    summary_fields = list(summary_rows[0].keys()) if summary_rows else []
    write_csv(summary_csv, summary_rows, summary_fields)

    scaled_rows = build_scaled_error_rows(usable, suggested_scale)
    scaled_csv = output_dir / "energy_calibration_scaled_errors.csv"
    scaled_fields = list(scaled_rows[0].keys()) if scaled_rows else []
    write_csv(scaled_csv, scaled_rows, scaled_fields)

    coefficient_rows, coefficient_lookup = build_group_coefficients(
        robust_rows,
        global_scale=suggested_scale,
        min_group_count=MIN_GROUP_SAMPLE_COUNT,
    )
    coefficient_csv = output_dir / "energy_calibration_group_coefficients.csv"
    coefficient_fields = list(coefficient_rows[0].keys()) if coefficient_rows else []
    write_csv(coefficient_csv, coefficient_rows, coefficient_fields)

    group_scaled_rows = build_group_scaled_error_rows(usable, coefficient_lookup, suggested_scale)
    group_scaled_csv = output_dir / "energy_calibration_group_scaled_errors.csv"
    group_scaled_fields = list(group_scaled_rows[0].keys()) if group_scaled_rows else []
    write_csv(group_scaled_csv, group_scaled_rows, group_scaled_fields)

    abs_before = [value for row in usable if (value := abs_pct_error_for(row, scale=1.0)) is not None]
    abs_after = [value for row in usable if (value := abs_pct_error_for(row, scale=suggested_scale)) is not None]
    robust_abs_before = [value for row in robust_rows if (value := abs_pct_error_for(row, scale=1.0)) is not None]
    robust_abs_after = [value for row in robust_rows if (value := abs_pct_error_for(row, scale=suggested_scale)) is not None]
    group_abs_after = [
        _optional_float(row.get("group_calibrated_abs_pct_error"))
        for row in group_scaled_rows
        if _optional_float(row.get("group_calibrated_abs_pct_error")) is not None
    ]
    summary = {
        "input_csv": str(alignment_csv),
        "total_rows": len(rows),
        "usable_aligned_nonzero_traction_count": len(usable),
        "robust_fit_sample_count": len(robust_rows),
        "stratum_counts": {
            key: sum(1 for row in usable if sample_stratum(row) == key)
            for key in [
                "fit_core",
                "review_short_stop",
                "review_low_intensity",
                "review_boundary_gap",
                "review_single_meter",
                "out_of_ratio_band",
                "review_zero_or_invalid",
            ]
        },
        "fit_policy": "fit_core_only_aggregated_ab_exclude_zero_energy_short_stop_low_intensity_single_meter",
        "all_sample_median_traction_scale": all_median_scale,
        "suggested_global_traction_scale": suggested_scale,
        "median_abs_pct_error_before_scale": _median(abs_before),
        "median_abs_pct_error_after_scale": _median(abs_after),
        "mean_abs_pct_error_before_scale": _mean(abs_before),
        "mean_abs_pct_error_after_scale": _mean(abs_after),
        "robust_median_abs_pct_error_before_scale": _median(robust_abs_before),
        "robust_median_abs_pct_error_after_scale": _median(robust_abs_after),
        "robust_mean_abs_pct_error_before_scale": _mean(robust_abs_before),
        "robust_mean_abs_pct_error_after_scale": _mean(robust_abs_after),
        "group_scaled_median_abs_pct_error_after_scale": _median([value for value in group_abs_after if value is not None]),
        "group_scaled_mean_abs_pct_error_after_scale": _mean([value for value in group_abs_after if value is not None]),
        "outputs": {
            "error_summary": str(summary_csv),
            "scaled_errors": str(scaled_csv),
            "group_coefficients": str(coefficient_csv),
            "group_scaled_errors": str(group_scaled_csv),
        },
        "note": "Default scales are fitted only on fit_core samples (aggregated A/B, non-short-stop, energy-consistent). Zero-energy/short-stop/single-meter samples are review-only diagnostics. Energy unit is confirmed kWh from provider reply, but coverage/physics are still experimental.",
    }
    (output_dir / "energy_calibration_error_analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Analyze prototype arc-energy errors against smart-meter calibration samples.")
    parser.add_argument("--alignment-csv", type=Path, default=DEFAULT_ALIGNMENT_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = analyze_energy_errors(args.alignment_csv, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
