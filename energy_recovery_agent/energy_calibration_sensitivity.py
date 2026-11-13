# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math
import statistics

from energy_calibration_factors import load_energy_calibration_config, resolve_energy_calibration_factor


DEFAULT_ALIGNMENT_CSV = Path("outputs") / "energy_calibration" / "arc_energy_vs_meter_samples.csv"
DEFAULT_FACTOR_JSON = Path("data") / "real_shuohuang" / "energy_calibration_factors.json"
DEFAULT_OUTPUT_DIR = Path("outputs") / "energy_calibration"

OUTPUT_FIELDS = [
    "sample_id",
    "trainid",
    "realtime_trainid",
    "travel_direction",
    "aggregation_type",
    "start_station",
    "end_station",
    "distance_km",
    "meter_traction_energy_raw",
    "prototype_traction_energy_raw",
    "uncalibrated_estimate_raw",
    "global_scale",
    "global_estimate_raw",
    "group_scale",
    "group_scale_level",
    "group_scale_value",
    "group_estimate_raw",
    "uncalibrated_abs_pct_error",
    "global_abs_pct_error",
    "group_abs_pct_error",
    "best_scenario",
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


def _fmt(value: Optional[float]) -> str:
    """函数 _fmt：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _abs_pct(estimate: Optional[float], actual: Optional[float]) -> Optional[float]:
    """函数 _abs_pct：执行该模块中的相关处理逻辑。"""
    if estimate is None or actual is None or actual <= 0:
        return None
    return abs(estimate - actual) / actual * 100.0


def _median(values: list[float]) -> Optional[float]:
    """函数 _median：执行该模块中的相关处理逻辑。"""
    return None if not values else statistics.median(values)


def _mean(values: list[float]) -> Optional[float]:
    """函数 _mean：执行该模块中的相关处理逻辑。"""
    return None if not values else sum(values) / len(values)


def aggregation_type(realtime_trainid: str) -> str:
    """函数 aggregation_type：执行该模块中的相关处理逻辑。"""
    return "aggregated_ab" if "+" in _clean(realtime_trainid) else "single_meter"


def read_alignment_rows(path: Path) -> list[dict[str, str]]:
    """函数 read_alignment_rows：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            if row.get("alignment_status") != "aligned":
                continue
            actual = _optional_float(row.get("meter_traction_energy_raw"))
            proto = _optional_float(row.get("prototype_traction_energy_raw"))
            if actual is None or proto is None or actual <= 0 or proto <= 0:
                continue
            rows.append(dict(row))
        return rows


def build_sensitivity_rows(rows: Sequence[dict[str, str]], factor_config: dict[str, Any]) -> list[dict[str, str]]:
    """函数 build_sensitivity_rows：执行该模块中的相关处理逻辑。"""
    global_scale = resolve_energy_calibration_factor(config=factor_config).traction_scale
    output = []
    for row in rows:
        actual = _optional_float(row.get("meter_traction_energy_raw"))
        proto = _optional_float(row.get("prototype_traction_energy_raw"))
        if actual is None or proto is None:
            continue
        agg = aggregation_type(row.get("realtime_trainid", ""))
        factor = resolve_energy_calibration_factor(
            travel_direction=row.get("travel_direction", ""),
            aggregation_type=agg,
            config=factor_config,
        )
        uncalibrated = proto
        global_estimate = proto * global_scale
        group_estimate = proto * factor.traction_scale
        errors = {
            "uncalibrated": _abs_pct(uncalibrated, actual),
            "global": _abs_pct(global_estimate, actual),
            "group": _abs_pct(group_estimate, actual),
        }
        best = min((key for key, value in errors.items() if value is not None), key=lambda key: errors[key], default="")
        output.append(
            {
                "sample_id": row.get("sample_id", ""),
                "trainid": row.get("trainid", ""),
                "realtime_trainid": row.get("realtime_trainid", ""),
                "travel_direction": row.get("travel_direction", ""),
                "aggregation_type": agg,
                "start_station": row.get("start_station", ""),
                "end_station": row.get("end_station", ""),
                "distance_km": row.get("distance_km", ""),
                "meter_traction_energy_raw": _fmt(actual),
                "prototype_traction_energy_raw": _fmt(proto),
                "uncalibrated_estimate_raw": _fmt(uncalibrated),
                "global_scale": _fmt(global_scale),
                "global_estimate_raw": _fmt(global_estimate),
                "group_scale": _fmt(factor.traction_scale),
                "group_scale_level": factor.group_level,
                "group_scale_value": factor.group_value,
                "group_estimate_raw": _fmt(group_estimate),
                "uncalibrated_abs_pct_error": _fmt(errors["uncalibrated"]),
                "global_abs_pct_error": _fmt(errors["global"]),
                "group_abs_pct_error": _fmt(errors["group"]),
                "best_scenario": best,
            }
        )
    return output


def summarize(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    """函数 summarize：执行该模块中的相关处理逻辑。"""
    scenarios = {
        "uncalibrated": "uncalibrated_abs_pct_error",
        "global": "global_abs_pct_error",
        "group": "group_abs_pct_error",
    }
    summary: dict[str, Any] = {"sample_count": len(rows)}
    for name, field in scenarios.items():
        values = [value for row in rows if (value := _optional_float(row.get(field))) is not None]
        summary[f"{name}_median_abs_pct_error"] = _median(values)
        summary[f"{name}_mean_abs_pct_error"] = _mean(values)
    best_counts: dict[str, int] = {}
    for row in rows:
        best = row.get("best_scenario", "")
        best_counts[best] = best_counts.get(best, 0) + 1
    summary["best_scenario_counts"] = dict(sorted(best_counts.items()))
    return summary


def write_csv(path: Path, rows: Sequence[dict[str, str]], fieldnames: Sequence[str]) -> None:
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def run_sensitivity(alignment_csv: Path, factor_json: Path, output_dir: Path) -> dict[str, Any]:
    """函数 run_sensitivity：执行该模块中的相关处理逻辑。"""
    factor_config = load_energy_calibration_config(factor_json)
    rows = read_alignment_rows(alignment_csv)
    sensitivity_rows = build_sensitivity_rows(rows, factor_config)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "energy_calibration_sensitivity_comparison.csv"
    write_csv(output_csv, sensitivity_rows, OUTPUT_FIELDS)
    summary = summarize(sensitivity_rows)
    summary.update(
        {
            "alignment_csv": str(alignment_csv),
            "factor_json": str(factor_json),
            "output_csv": str(output_csv),
            "note": "Sensitivity comparison uses experimental raw-unit factors; optimizer defaults are unchanged.",
        }
    )
    (output_dir / "energy_calibration_sensitivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Compare uncalibrated/global/group energy calibration scenarios.")
    parser.add_argument("--alignment-csv", type=Path, default=DEFAULT_ALIGNMENT_CSV)
    parser.add_argument("--factor-json", type=Path, default=DEFAULT_FACTOR_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = run_sensitivity(args.alignment_csv, args.factor_json, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
