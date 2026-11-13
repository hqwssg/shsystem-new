# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math


DEFAULT_GROUP_COEFFICIENT_CSV = Path("outputs") / "energy_calibration" / "energy_calibration_group_coefficients.csv"
DEFAULT_ERROR_SUMMARY_JSON = Path("outputs") / "energy_calibration" / "energy_calibration_error_analysis_summary.json"
DEFAULT_OUTPUT_JSON = Path("data") / "real_shuohuang" / "energy_calibration_factors.json"


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
    except ValueError as exc:
        raise ValueError(f"calibration value must be numeric, got {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"calibration value must be finite, got {value!r}")
    return parsed


def _whole_count(value: Any, field_name: str) -> int:
    """函数 _whole_count：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return 0
    try:
        parsed = float(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0.0 or not parsed.is_integer():
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    return int(parsed)


def read_group_coefficients(path: Path) -> list[dict[str, str]]:
    """函数 read_group_coefficients：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_factor_config(
    group_csv: Path,
    summary_json: Path,
    output_json: Path,
    sample_source: Optional[Path] = None,
    quality_summary_json: Optional[Path] = None,
) -> dict[str, Any]:
    """函数 build_factor_config：执行该模块中的相关处理逻辑。"""
    rows = read_group_coefficients(group_csv)
    summary = json.loads(summary_json.read_text(encoding="utf-8")) if summary_json.exists() else {}
    quality = {}
    if quality_summary_json is not None and Path(quality_summary_json).exists():
        quality = json.loads(Path(quality_summary_json).read_text(encoding="utf-8"))
        if not isinstance(quality, dict) or not quality.get("publication_ready", False):
            raise ValueError("quality_summary_json 未通过发布质量门禁。")

    global_scale = _optional_float(summary.get("suggested_global_traction_scale"))
    if global_scale is None:
        global_row = next((row for row in rows if row.get("group_level") == "global"), None)
        global_scale = _optional_float(global_row.get("scale_median")) if global_row else None
    if global_scale is None:
        global_scale = 1.0

    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        level = _clean(row.get("group_level"))
        value = _clean(row.get("group_value"))
        scale = _optional_float(row.get("scale_median"))
        if not level or level == "global" or not value:
            continue
        groups.setdefault(level, {})[value] = {
            "traction_scale": scale,
            "sample_count": _whole_count(row.get("sample_count"), "sample_count"),
            "usable_ratio_count": _whole_count(row.get("usable_ratio_count"), "usable_ratio_count"),
            "coefficient_status": _clean(row.get("coefficient_status")),
            "ratio_p10": _optional_float(row.get("ratio_p10")),
            "ratio_p90": _optional_float(row.get("ratio_p90")),
        }

    config = {
        "schema_version": "1.0",
        "enabled_by_default": False,
        "data_status": "validated_kwh_calibration" if quality else "experimental_kwh_calibration",
        "source": {
            "group_coefficients_csv": str(group_csv),
            "error_summary_json": str(summary_json),
            "sample_source": str(sample_source or DEFAULT_OUTPUT_JSON.with_name("smart_meter_calibration_samples.csv")),
            "quality_summary_json": str(quality_summary_json or ""),
        },
        "applicability": {
            "line": "朔黄线",
            "energy_unit_status": "confirmed_kwh_from_provider_reply",
            "fit_scope": "SS4 realtime meter samples matched to station/ammeter_info by trainid and time window",
            "recommended_use": "comparison and sensitivity testing only; unit is confirmed as kWh but sample coverage and model physics are not final engineering calibration",
        },
        "global": {
            "traction_scale": global_scale,
            "sample_count": _whole_count(summary.get("robust_fit_sample_count"), "robust_fit_sample_count"),
            "median_abs_pct_error_after_scale": summary.get("robust_median_abs_pct_error_after_scale"),
        },
        "groups": groups,
        "resolution_order": [
            "direction_aggregation",
            "travel_direction",
            "aggregation_type",
            "global",
        ],
        "quality_evidence": {
            "publication_ready": bool(quality.get("publication_ready", False)),
            "selected_validation_mode": quality.get("selected_validation_mode"),
            "fit_sample_count": quality.get("fit_sample_count"),
            "validation_sample_count": quality.get("validation_sample_count"),
            "validation_metrics": quality.get("validation_metrics", {}).get("selected", {}),
            "thresholds": quality.get("thresholds", {}),
        },
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Build algorithm-readable energy calibration factor config.")
    parser.add_argument("--group-csv", type=Path, default=DEFAULT_GROUP_COEFFICIENT_CSV)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_ERROR_SUMMARY_JSON)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--sample-source", type=Path)
    parser.add_argument("--quality-summary-json", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    config = build_factor_config(
        args.group_csv,
        args.summary_json,
        args.output_json,
        sample_source=args.sample_source,
        quality_summary_json=args.quality_summary_json,
    )
    print(json.dumps({"output_json": str(args.output_json), "enabled_by_default": config["enabled_by_default"], "global_scale": config["global"]["traction_scale"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
