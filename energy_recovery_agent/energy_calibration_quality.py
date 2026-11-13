# 模块功能说明：本模块对模型—电表校准执行独立留出验证、误差统计和发布质量门禁。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import csv
import hashlib
import json
import math
import statistics

from energy_calibration_error_analyzer import (
    _optional_float,
    aggregation_type,
    build_group_coefficients,
    choose_group_scale,
    ratio_for,
    robust_fit_rows,
    usable_rows,
)


DEFAULT_MIN_FIT_SAMPLES = 30
DEFAULT_MIN_VALIDATION_SAMPLES = 10
DEFAULT_VALIDATION_FRACTION = 0.20
DEFAULT_MAX_MEDIAN_APE_PCT = 30.0
DEFAULT_MAX_P90_APE_PCT = 60.0
DEFAULT_MAX_WAPE_PCT = 30.0
DEFAULT_SCALE_RANGE = (0.2, 5.0)
DEFAULT_VALIDATION_MODEL = "grouped"


def _read_rows(path: Path) -> list[dict[str, str]]:
    """读取对齐样本表。"""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _stable_key(row: dict[str, str]) -> str:
    """生成不依赖输入行顺序的稳定样本键。"""
    parts = (
        row.get("sample_id", ""),
        row.get("trainid", ""),
        row.get("realtime_trainid", ""),
        row.get("travel_direction", ""),
        row.get("start_station", ""),
        row.get("end_station", ""),
        row.get("duration_s", ""),
    )
    return "|".join(str(value) for value in parts)


def deterministic_holdout(
    rows: Sequence[dict[str, str]],
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """按方向和电表聚合口径分层，确定性拆分拟合集与留出验证集。

    每层按样本稳定哈希排序，以便输入行顺序变化时仍能复现。样本较少的层
    至少保留一个拟合样本；只有一条记录的层不进入验证集。
    """
    if not 0.0 < validation_fraction < 0.5:
        raise ValueError("validation_fraction 必须位于 (0, 0.5)。")
    strata: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = f"{row.get('travel_direction', '')}|{aggregation_type(row.get('realtime_trainid', ''))}"
        strata.setdefault(key, []).append(row)
    fit_rows: list[dict[str, str]] = []
    validation_rows: list[dict[str, str]] = []
    for key in sorted(strata):
        items = sorted(
            strata[key],
            key=lambda row: hashlib.sha256(_stable_key(row).encode("utf-8")).hexdigest(),
        )
        if len(items) <= 1:
            fit_rows.extend(items)
            continue
        validation_count = max(1, int(round(len(items) * validation_fraction)))
        validation_count = min(validation_count, len(items) - 1)
        validation_rows.extend(items[:validation_count])
        fit_rows.extend(items[validation_count:])
    return fit_rows, validation_rows


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    """使用线性插值计算分位数。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def error_metrics(rows: Sequence[dict[str, str]], scales: Sequence[float]) -> dict[str, Optional[float]]:
    """计算 MAE、RMSE、偏差、MAPE、中位 APE、P90 APE、WAPE 和 R²。"""
    if len(rows) != len(scales):
        raise ValueError("rows 与 scales 数量必须一致。")
    actuals: list[float] = []
    estimates: list[float] = []
    for row, scale in zip(rows, scales):
        actual = _optional_float(row.get("meter_traction_energy_raw"))
        prototype = _optional_float(row.get("prototype_traction_energy_raw"))
        if actual is None or prototype is None or actual <= 0 or prototype <= 0:
            continue
        actuals.append(actual)
        estimates.append(prototype * scale)
    if not actuals:
        return {
            "sample_count": 0,
            "mae_kwh": None,
            "rmse_kwh": None,
            "bias_kwh": None,
            "bias_pct": None,
            "mape_pct": None,
            "median_ape_pct": None,
            "p90_ape_pct": None,
            "wape_pct": None,
            "r2": None,
        }
    errors = [estimate - actual for estimate, actual in zip(estimates, actuals)]
    abs_errors = [abs(error) for error in errors]
    ape = [abs(error) / actual * 100.0 for error, actual in zip(errors, actuals)]
    actual_sum = sum(actuals)
    actual_mean = sum(actuals) / len(actuals)
    ss_res = sum(error * error for error in errors)
    ss_tot = sum((actual - actual_mean) ** 2 for actual in actuals)
    return {
        "sample_count": len(actuals),
        "mae_kwh": sum(abs_errors) / len(abs_errors),
        "rmse_kwh": math.sqrt(ss_res / len(errors)),
        "bias_kwh": sum(errors) / len(errors),
        "bias_pct": None if actual_sum <= 0 else sum(errors) / actual_sum * 100.0,
        "mape_pct": sum(ape) / len(ape),
        "median_ape_pct": statistics.median(ape),
        "p90_ape_pct": _percentile(ape, 0.90),
        "wape_pct": None if actual_sum <= 0 else sum(abs_errors) / actual_sum * 100.0,
        "r2": None if ss_tot <= 1e-12 else 1.0 - ss_res / ss_tot,
    }


def audit_calibration_quality(
    alignment_csv: Path,
    *,
    validation_alignment_csv: Optional[Path] = None,
    min_fit_samples: int = DEFAULT_MIN_FIT_SAMPLES,
    min_validation_samples: int = DEFAULT_MIN_VALIDATION_SAMPLES,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    validation_model: str = DEFAULT_VALIDATION_MODEL,
    max_median_ape_pct: float = DEFAULT_MAX_MEDIAN_APE_PCT,
    max_p90_ape_pct: float = DEFAULT_MAX_P90_APE_PCT,
    max_wape_pct: float = DEFAULT_MAX_WAPE_PCT,
    min_scale: float = DEFAULT_SCALE_RANGE[0],
    max_scale: float = DEFAULT_SCALE_RANGE[1],
) -> dict[str, Any]:
    """拟合只使用训练子集，并在未参与拟合的留出子集上判定质量。"""
    if min_fit_samples <= 0 or min_validation_samples <= 0:
        raise ValueError("最小拟合和验证样本数必须为正数。")
    if min_scale <= 0 or max_scale <= min_scale:
        raise ValueError("校准系数范围必须满足 0 < min_scale < max_scale。")
    if validation_model not in {"global", "grouped"}:
        raise ValueError("validation_model 必须为 global 或 grouped。")
    rows = _read_rows(Path(alignment_csv))
    usable = usable_rows(rows)
    core = robust_fit_rows(usable)
    if validation_alignment_csv is None:
        fit_rows, validation_rows = deterministic_holdout(core, validation_fraction)
        validation_source_rows = rows
        split_strategy = "deterministic_stratified_holdout"
    else:
        validation_source_rows = _read_rows(Path(validation_alignment_csv))
        validation_rows = robust_fit_rows(usable_rows(validation_source_rows))
        fit_rows = core
        split_strategy = "external_validation_file"

    fit_keys = {_stable_key(row) for row in fit_rows}
    validation_keys = {_stable_key(row) for row in validation_rows}
    overlap_count = len(fit_keys & validation_keys)
    fit_ratios = [ratio for row in fit_rows if (ratio := ratio_for(row)) is not None]
    global_scale = statistics.median(fit_ratios) if fit_ratios else None
    coefficient_lookup: dict[tuple[str, str], float] = {}
    min_group_samples = max(5, min_fit_samples // 2)
    if global_scale is not None:
        _, coefficient_lookup = build_group_coefficients(
            fit_rows,
            global_scale=global_scale,
            min_group_count=min_group_samples,
        )

    uncalibrated = error_metrics(validation_rows, [1.0] * len(validation_rows))
    global_metrics = error_metrics(
        validation_rows,
        [global_scale if global_scale is not None else 1.0] * len(validation_rows),
    )
    group_scales = []
    for row in validation_rows:
        if global_scale is None:
            group_scales.append(1.0)
        else:
            scale, _, _ = choose_group_scale(row, coefficient_lookup, global_scale)
            group_scales.append(scale)
    grouped_metrics = error_metrics(validation_rows, group_scales)
    selected_mode = validation_model
    selected_metrics = grouped_metrics if selected_mode == "grouped" else global_metrics

    checks = [
        {
            "code": "independent_validation_no_overlap",
            "passed": overlap_count == 0,
            "observed": overlap_count,
            "required": 0,
        },
        {
            "code": "minimum_fit_samples",
            "passed": len(fit_rows) >= min_fit_samples,
            "observed": len(fit_rows),
            "required": min_fit_samples,
        },
        {
            "code": "minimum_validation_samples",
            "passed": len(validation_rows) >= min_validation_samples,
            "observed": len(validation_rows),
            "required": min_validation_samples,
        },
        {
            "code": "plausible_global_scale",
            "passed": global_scale is not None and min_scale <= global_scale <= max_scale,
            "observed": global_scale,
            "required": [min_scale, max_scale],
        },
        {
            "code": "validation_median_ape",
            "passed": selected_metrics["median_ape_pct"] is not None and selected_metrics["median_ape_pct"] <= max_median_ape_pct,
            "observed": selected_metrics["median_ape_pct"],
            "required": max_median_ape_pct,
        },
        {
            "code": "validation_p90_ape",
            "passed": selected_metrics["p90_ape_pct"] is not None and selected_metrics["p90_ape_pct"] <= max_p90_ape_pct,
            "observed": selected_metrics["p90_ape_pct"],
            "required": max_p90_ape_pct,
        },
        {
            "code": "validation_wape",
            "passed": selected_metrics["wape_pct"] is not None and selected_metrics["wape_pct"] <= max_wape_pct,
            "observed": selected_metrics["wape_pct"],
            "required": max_wape_pct,
        },
        {
            "code": "out_of_sample_improvement",
            "passed": (
                selected_metrics["median_ape_pct"] is not None
                and uncalibrated["median_ape_pct"] is not None
                and selected_metrics["median_ape_pct"] < uncalibrated["median_ape_pct"]
            ),
            "observed": {
                "uncalibrated_median_ape_pct": uncalibrated["median_ape_pct"],
                "calibrated_median_ape_pct": selected_metrics["median_ape_pct"],
            },
            "required": "calibrated < uncalibrated",
        },
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "accepted": passed,
        "publication_ready": passed,
        "alignment_csv": str(alignment_csv),
        "validation_alignment_csv": str(validation_alignment_csv or ""),
        "validation_strategy": split_strategy,
        "total_alignment_rows": len(rows),
        "total_validation_alignment_rows": len(validation_source_rows),
        "usable_rows": len(usable),
        "fit_core_rows": len(core),
        "fit_sample_count": len(fit_rows),
        "validation_sample_count": len(validation_rows),
        "validation_fraction": validation_fraction,
        "global_scale_fit_only": global_scale,
        "minimum_group_fit_samples": min_group_samples,
        "selected_validation_mode": selected_mode,
        "validation_metrics": {
            "uncalibrated": uncalibrated,
            "global": global_metrics,
            "grouped": grouped_metrics,
            "selected": selected_metrics,
        },
        "thresholds": {
            "min_fit_samples": min_fit_samples,
            "min_validation_samples": min_validation_samples,
            "max_median_ape_pct": max_median_ape_pct,
            "max_p90_ape_pct": max_p90_ape_pct,
            "max_wape_pct": max_wape_pct,
            "global_scale_range": [min_scale, max_scale],
            "validation_model": validation_model,
        },
        "checks": checks,
        "failed_checks": [check["code"] for check in checks if not check["passed"]],
        "note": (
            "质量结论来自外部独立验证文件，且验证样本未参与系数拟合；正式发布阈值应在查看结果前由项目方确认并冻结。"
            if validation_alignment_csv is not None
            else "质量结论来自未参与系数拟合的确定性分层留出集；正式发布阈值应在查看结果前由项目方确认并冻结。"
        ),
    }


def write_quality_outputs(summary: dict[str, Any], output_dir: Path) -> None:
    """写出机器可读摘要、检查表和中文审计报告。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "calibration_quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "calibration_quality_checks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("code", "passed", "observed", "required"))
        writer.writeheader()
        for check in summary["checks"]:
            writer.writerow({
                **check,
                "observed": json.dumps(check["observed"], ensure_ascii=False),
                "required": json.dumps(check["required"], ensure_ascii=False),
            })
    metrics = summary["validation_metrics"]
    lines = [
        "# 模型结果—电表数据校准质量报告",
        "",
        f"- 质量门禁通过：`{summary['accepted']}`",
        f"- 鲁棒候选样本：{summary['fit_core_rows']}",
        f"- 拟合样本：{summary['fit_sample_count']}",
        f"- 独立留出验证样本：{summary['validation_sample_count']}",
        f"- 验证策略：`{summary['validation_strategy']}`",
        f"- 仅拟合集得到的全局系数：{summary['global_scale_fit_only']}",
        f"- 留出集选择口径：`{summary['selected_validation_mode']}`",
        "",
        "## 留出集误差",
        "",
        "| 口径 | MAE kWh | RMSE kWh | 偏差 % | MAPE % | 中位 APE % | P90 APE % | WAPE % | R² |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("uncalibrated", "global", "grouped"):
        item = metrics[name]
        lines.append(
            f"| {name} | {item['mae_kwh']} | {item['rmse_kwh']} | {item['bias_pct']} | {item['mape_pct']} | {item['median_ape_pct']} | {item['p90_ape_pct']} | {item['wape_pct']} | {item['r2']} |"
        )
    lines.extend([
        "",
        "## 门禁检查",
        "",
        "| 检查 | 通过 | 观测值 | 要求 |",
        "| --- | --- | --- | --- |",
    ])
    for check in summary["checks"]:
        lines.append(f"| `{check['code']}` | {check['passed']} | `{check['observed']}` | `{check['required']}` |")
    lines.extend([
        "",
        "质量门禁未通过时仍保留诊断输出，但禁止发布校准系数或把结果称为正式校准。",
        "",
    ])
    (output_dir / "CALIBRATION_QUALITY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
