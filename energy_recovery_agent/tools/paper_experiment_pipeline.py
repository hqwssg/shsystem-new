"""清单驱动的正式实验批量执行与论文统计汇总。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.formal_experiment_controller import DEFAULT_SEEDS, run_formal_experiment_suite


DEFAULT_METRICS = (
    "grid_kwh",
    "wasted_kwh",
    "effective_regen_loss_kwh",
    "recovery_rate",
)
METRIC_LABELS = {
    "grid_kwh": "牵引侧购电量（kWh）",
    "wasted_kwh": "弃能（kWh）",
    "effective_regen_loss_kwh": "有效再生损失（kWh）",
    "recovery_rate": "回收率",
    "battery_charge_kwh": "储能充电量（kWh）",
    "battery_discharge_kwh": "储能放电量（kWh）",
    "total_adjustment_min": "总调整时间（min）",
    "delay_min": "延误时间（min）",
    "runtime_s": "方案运行耗时（s）",
}
HIGHER_IS_BETTER = {"recovery_rate"}
STRATEGY_ORDER = ("no_storage", "rule", "nsga2")
STRATEGY_LABELS = {
    "baseline": "现行运行图基线",
    "no_storage": "无储能消融",
    "rule": "规则优化",
    "nsga2": "NSGA-II（窗内种子中位数）",
    "nsga2_vs_rule": "NSGA-II 相对规则优化",
}
COMPARISONS = (
    ("no_storage", "baseline", "no_storage"),
    ("rule", "baseline", "rule"),
    ("nsga2", "baseline", "nsga2"),
    ("nsga2_vs_rule", "rule", "nsga2"),
)
COMPARISON_ORDER = tuple(item[0] for item in COMPARISONS)
NUMERIC_FIELDS = (
    "total_traction_kwh",
    "total_regen_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "wasted_kwh",
    "grid_kwh",
    "effective_regen_loss_kwh",
    "recovery_rate",
    "issue_count",
    "max_shift_min",
    "total_adjustment_min",
    "delay_min",
    "constraint_violation",
    "runtime_s",
)


def _configure_matplotlib_fonts() -> None:
    """选择可显示中文的字体，避免论文图表出现方框。"""

    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"):
        if name in available:
            matplotlib.rcParams["font.sans-serif"] = [name]
            matplotlib.rcParams["font.family"] = "sans-serif"
            matplotlib.rcParams["axes.unicode_minus"] = False
            break


_configure_matplotlib_fonts()


def _read_json(path: Path) -> Dict[str, Any]:
    """读取 JSON 对象，并将文件位置写入错误信息。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"无法读取 JSON：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    """写出稳定缩进的 UTF-8 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """写出列顺序固定且便于表格软件读取的 CSV。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    """计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(path: Path) -> str:
    """根据相对路径和文件内容计算目录的确定性摘要。"""

    if path.is_file():
        return _sha256(path)
    if not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for item in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(item).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _number(value: Any) -> Optional[float]:
    """把可用数值转换为有限浮点数。"""

    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    """忽略空值后计算中位数。"""

    usable = [value for value in values if value is not None]
    return statistics.median(usable) if usable else None


def _quantile(values: Sequence[float], probability: float) -> float:
    """使用线性插值计算样本分位数。"""

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _stable_seed(base_seed: int, *parts: str) -> int:
    """为每个统计量派生与执行顺序无关的随机种子。"""

    payload = "|".join((str(base_seed), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _bootstrap_interval(
    values: Sequence[float],
    statistic_name: str,
    confidence_level: float,
    replicates: int,
    seed: int,
) -> Tuple[float, float]:
    """计算确定性百分位 Bootstrap 置信区间。"""

    if not values:
        raise ValueError("Bootstrap 至少需要一个样本。")
    if len(values) == 1:
        return values[0], values[0]
    statistic = statistics.mean if statistic_name == "mean" else statistics.median
    rng = random.Random(seed)
    size = len(values)
    samples = [statistic([values[rng.randrange(size)] for _ in range(size)]) for _ in range(replicates)]
    alpha = (1.0 - confidence_level) / 2.0
    return _quantile(samples, alpha), _quantile(samples, 1.0 - alpha)


def _paired_sign_flip_p_value(values: Sequence[float], replicates: int, seed: int) -> Tuple[float, str]:
    """对配对差值均值执行双侧符号翻转检验。"""

    if not values:
        raise ValueError("配对检验至少需要一个差值。")
    observed = abs(statistics.mean(values))
    tolerance = 1e-12
    if len(values) <= 20:
        total = 1 << len(values)
        extreme = 0
        for mask in range(total):
            trial = sum(value if mask & (1 << index) else -value for index, value in enumerate(values)) / len(values)
            if abs(trial) + tolerance >= observed:
                extreme += 1
        return extreme / total, "exact"
    rng = random.Random(seed)
    extreme = 0
    for _ in range(replicates):
        trial = sum(value if rng.random() < 0.5 else -value for value in values) / len(values)
        if abs(trial) + tolerance >= observed:
            extreme += 1
    return (extreme + 1) / (replicates + 1), "monte_carlo"


def _holm_adjust(rows: Sequence[Dict[str, Any]]) -> None:
    """对同一研究中的主检验执行 Holm 多重比较校正。"""

    indexed = [(index, float(row["p_value_raw"])) for index, row in enumerate(rows) if row.get("p_value_raw") is not None]
    ordered = sorted(indexed, key=lambda item: item[1])
    running = 0.0
    count = len(ordered)
    for rank, (index, p_value) in enumerate(ordered):
        adjusted = min(1.0, (count - rank) * p_value)
        running = max(running, adjusted)
        rows[index]["p_value_holm"] = running


def _validate_manifest(manifest: Mapping[str, Any], *, aggregate_only: bool) -> Dict[str, Any]:
    """规范化研究清单并拒绝会造成统计歧义的配置。"""

    study_id = str(manifest.get("study_id", "")).strip()
    dataset_version = str(manifest.get("dataset_version", "")).strip()
    windows = manifest.get("windows")
    if not study_id or not dataset_version:
        raise ValueError("研究清单必须提供 study_id 和 dataset_version。")
    if not isinstance(windows, list) or not windows:
        raise ValueError("研究清单 windows 必须为非空数组。")
    normalized_windows: List[Dict[str, Any]] = []
    identifiers = set()
    for raw in windows:
        if not isinstance(raw, dict):
            raise ValueError("每个评价窗配置必须是对象。")
        window_id = str(raw.get("window_id", "")).strip()
        if not window_id or window_id in identifiers:
            raise ValueError(f"window_id 为空或重复：{window_id or '<空>'}")
        identifiers.add(window_id)
        include = bool(raw.get("include", True))
        exclusion_reason = str(raw.get("exclusion_reason", "")).strip()
        if not include and not exclusion_reason:
            raise ValueError(f"排除评价窗必须填写 exclusion_reason：{window_id}")
        if include and not aggregate_only:
            for field in ("data_dir", "source_dir", "timetable"):
                if not str(raw.get(field, "")).strip():
                    raise ValueError(f"执行模式下评价窗 {window_id} 缺少 {field}。")
        normalized_windows.append({**raw, "window_id": window_id, "include": include, "exclusion_reason": exclusion_reason})

    analysis = dict(manifest.get("analysis") or {})
    metrics = tuple(str(value) for value in analysis.get("metrics", DEFAULT_METRICS))
    if not metrics or any(metric not in METRIC_LABELS for metric in metrics):
        raise ValueError(f"analysis.metrics 含不支持的指标：{metrics}")
    confidence_level = float(analysis.get("confidence_level", 0.95))
    bootstrap_replicates = int(analysis.get("bootstrap_replicates", 5000))
    permutation_replicates = int(analysis.get("permutation_replicates", 100000))
    min_windows = int(analysis.get("min_windows_for_inference", 3))
    if not 0.8 <= confidence_level < 1.0:
        raise ValueError("confidence_level 必须位于 [0.8, 1.0)。")
    if bootstrap_replicates < 100 or permutation_replicates < 100 or min_windows < 2:
        raise ValueError("Bootstrap/置换重复数至少为100，推断统计最少评价窗数至少为2。")

    parameters = dict(manifest.get("experiment_parameters") or {})
    parameters.setdefault("seeds", list(DEFAULT_SEEDS))
    parameters.setdefault("max_shift_min", 10)
    parameters.setdefault("step_min", 5)
    parameters.setdefault("max_dwell_extension_min", 5)
    parameters.setdefault("max_candidates", 50)
    parameters.setdefault("population_size", 20)
    parameters.setdefault("generations", 20)
    parameters.setdefault("crossover_rate", 0.9)
    parameters.setdefault("mutation_rate", 0.2)
    parameters.setdefault("strict_visualizations", True)
    parameters.setdefault("settlement_steps_s", [1, 5, 10])
    seeds = [int(value) for value in parameters["seeds"]]
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("experiment_parameters.seeds 必须为非空且互不重复。")
    parameters["seeds"] = seeds
    settlement_steps = [int(value) for value in parameters["settlement_steps_s"]]
    if 1 not in settlement_steps or len(settlement_steps) != len(settlement_steps) or any(value <= 0 for value in settlement_steps):
        raise ValueError("experiment_parameters.settlement_steps_s 必须包含1且为互不重复的正整数。")
    parameters["settlement_steps_s"] = settlement_steps
    return {
        **manifest,
        "schema_version": "1.0",
        "study_id": study_id,
        "dataset_version": dataset_version,
        "windows": normalized_windows,
        "experiment_parameters": parameters,
        "analysis": {
            **analysis,
            "metrics": list(metrics),
            "confidence_level": confidence_level,
            "bootstrap_replicates": bootstrap_replicates,
            "permutation_replicates": permutation_replicates,
            "statistics_seed": int(analysis.get("statistics_seed", 20260909)),
            "min_windows_for_inference": min_windows,
        },
    }


def _load_result_rows(result_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """读取并交叉核验一个评价窗的正式实验汇总和 KPI 表。"""

    summary_path = result_dir / "formal_experiment_summary.json"
    kpi_path = result_dir / "formal_experiment_kpi.csv"
    if not summary_path.is_file() or not kpi_path.is_file():
        raise ValueError(f"评价窗结果缺少正式汇总或 KPI 表：{result_dir}")
    summary = _read_json(summary_path)
    with kpi_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"评价窗 KPI 表为空：{kpi_path}")
    summary_codes = {str(row.get("scenario_code", "")) for row in summary.get("scenarios", [])}
    csv_codes = {str(row.get("scenario_code", "")) for row in rows}
    if summary_codes != csv_codes:
        raise ValueError(f"正式汇总与 KPI 表方案集合不一致：{result_dir}")
    return summary, rows


def _resolve_project_path(value: Any) -> Path:
    """将研究清单中的相对路径稳定解析到项目根目录。"""

    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _usable(row: Mapping[str, Any]) -> bool:
    """只允许完成、质量门禁通过且没有约束违反的结果进入统计。"""

    quality = str(row.get("quality_accepted", "")).strip().lower() in {"true", "1", "yes"}
    violation = _number(row.get("constraint_violation"))
    return str(row.get("status", "")) == "completed" and quality and (violation is None or violation <= 1e-9)


def _strategy_name(row: Mapping[str, Any]) -> Optional[str]:
    """把正式实验方案映射为论文统计策略。"""

    algorithm = str(row.get("algorithm", "")).strip().lower()
    code = str(row.get("scenario_code", ""))
    if code == "F01_B0_baseline" or algorithm == "baseline_audit":
        return "baseline"
    if code == "F02_B1_no_storage" or algorithm == "no_storage_ablation":
        return "no_storage"
    if algorithm == "rule":
        return "rule"
    if algorithm == "nsga2":
        return "nsga2"
    return None


def _validate_window_design(rows: Sequence[Mapping[str, Any]], expected_seeds: Sequence[int]) -> None:
    """确认每个评价窗严格包含完整且质量合格的预注册方案。"""

    grouped: Dict[str, List[Mapping[str, Any]]] = {name: [] for name in ("baseline", *STRATEGY_ORDER)}
    for row in rows:
        strategy = _strategy_name(row)
        if strategy is not None:
            grouped[strategy].append(row)
    for strategy in ("baseline", "no_storage", "rule"):
        if len(grouped[strategy]) != 1 or not _usable(grouped[strategy][0]):
            raise ValueError(f"策略 {strategy} 必须且只能有一个质量合格结果。")
    actual_seeds = []
    for row in grouped["nsga2"]:
        seed = _number(row.get("seed"))
        if seed is None or not float(seed).is_integer() or not _usable(row):
            raise ValueError("NSGA-II 结果存在无效种子或未通过质量门禁。")
        actual_seeds.append(int(seed))
    if sorted(actual_seeds) != sorted(int(seed) for seed in expected_seeds):
        raise ValueError(f"NSGA-II 种子集合与研究清单不一致：实际 {sorted(actual_seeds)}")


def _validate_timestep_design(summary: Mapping[str, Any], expected_steps: Sequence[int]) -> List[Dict[str, Any]]:
    """核验 F08 是否覆盖预注册时间步长且全部通过质量门禁。"""

    raw_rows = summary.get("timestep_sensitivity")
    if not isinstance(raw_rows, list):
        raise ValueError("正式实验汇总缺少 F08 timestep_sensitivity。")
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    actual_steps = []
    for row in rows:
        step = _number(row.get("time_step_s"))
        quality = row.get("quality_accepted") is True or str(row.get("quality_accepted", "")).lower() == "true"
        if step is None or not float(step).is_integer() or row.get("status") != "completed" or not quality:
            raise ValueError("F08 存在无效时间步长或未通过质量门禁的结果。")
        actual_steps.append(int(step))
    if sorted(actual_steps) != sorted(int(step) for step in expected_steps):
        raise ValueError(f"F08 时间步长集合与研究清单不一致：实际 {sorted(actual_steps)}")
    return rows


def _aggregate_window(
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
    metrics: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """在评价窗内汇总随机种子，确保跨窗统计不发生伪重复。"""

    accepted: Dict[str, List[Mapping[str, Any]]] = {name: [] for name in ("baseline", *STRATEGY_ORDER)}
    rejected: List[Dict[str, Any]] = []
    for row in rows:
        strategy = _strategy_name(row)
        if strategy is None:
            continue
        if _usable(row):
            accepted[strategy].append(row)
        else:
            rejected.append(
                {
                    "window_id": window_id,
                    "scenario_code": row.get("scenario_code", ""),
                    "algorithm": row.get("algorithm", ""),
                    "seed": row.get("seed", ""),
                    "reason": "结果未完成、质量门禁未通过或存在约束违反",
                }
            )

    aggregated: List[Dict[str, Any]] = []
    seed_rows: List[Dict[str, Any]] = []
    for strategy, group in accepted.items():
        if not group:
            continue
        record: Dict[str, Any] = {
            "window_id": window_id,
            "strategy": strategy,
            "strategy_label": STRATEGY_LABELS[strategy],
            "replicate_count": len(group),
            "aggregation": "median_across_seeds" if strategy == "nsga2" else "single_run",
            "optimize_count": sum(str(row.get("decision_action", "")) == "optimize" for row in group),
            "keep_baseline_count": sum(str(row.get("decision_action", "")) == "keep_baseline" for row in group),
        }
        for field in NUMERIC_FIELDS:
            record[field] = _median(_number(row.get(field)) for row in group)
        aggregated.append(record)

        if strategy == "nsga2":
            for metric in metrics:
                values = [_number(row.get(metric)) for row in group]
                usable_values = [value for value in values if value is not None]
                if not usable_values:
                    continue
                mean_value = statistics.mean(usable_values)
                seed_rows.append(
                    {
                        "window_id": window_id,
                        "metric": metric,
                        "metric_label": METRIC_LABELS[metric],
                        "seed_count": len(usable_values),
                        "mean": mean_value,
                        "median": statistics.median(usable_values),
                        "sample_std": statistics.stdev(usable_values) if len(usable_values) >= 2 else 0.0,
                        "cv": (statistics.stdev(usable_values) / abs(mean_value)) if len(usable_values) >= 2 and abs(mean_value) > 1e-12 else None,
                        "min": min(usable_values),
                        "max": max(usable_values),
                        "range": max(usable_values) - min(usable_values),
                    }
                )
    return aggregated, seed_rows, rejected


def _paired_rows(window_rows: Sequence[Mapping[str, Any]], metrics: Sequence[str]) -> List[Dict[str, Any]]:
    """构造每个评价窗内基线与策略的成对差值。"""

    grouped: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for row in window_rows:
        grouped.setdefault(str(row["window_id"]), {})[str(row["strategy"])] = row
    result: List[Dict[str, Any]] = []
    for window_id, strategies in sorted(grouped.items()):
        baseline = strategies.get("baseline")
        if baseline is None:
            continue
        for comparison, reference_strategy, treatment_strategy in COMPARISONS:
            reference = strategies.get(reference_strategy)
            treatment = strategies.get(treatment_strategy)
            if reference is None or treatment is None:
                continue
            for metric in metrics:
                baseline_value = _number(reference.get(metric))
                treatment_value = _number(treatment.get(metric))
                if baseline_value is None or treatment_value is None:
                    continue
                difference = treatment_value - baseline_value
                improvement = difference if metric in HIGHER_IS_BETTER else -difference
                result.append(
                    {
                        "window_id": window_id,
                        "strategy": comparison,
                        "strategy_label": STRATEGY_LABELS[comparison],
                        "reference_strategy": reference_strategy,
                        "treatment_strategy": treatment_strategy,
                        "metric": metric,
                        "metric_label": METRIC_LABELS[metric],
                        "direction": "higher_is_better" if metric in HIGHER_IS_BETTER else "lower_is_better",
                        "reference_value": baseline_value,
                        "treatment_value": treatment_value,
                        "raw_difference_treatment_minus_reference": difference,
                        "improvement": improvement,
                        "improvement_pct": improvement / abs(baseline_value) * 100.0 if abs(baseline_value) > 1e-12 else None,
                    }
                )
    return result


def _strategy_summary_rows(window_rows: Sequence[Mapping[str, Any]], metrics: Sequence[str]) -> List[Dict[str, Any]]:
    """汇总各策略跨评价窗的绝对 KPI，供论文主结果表直接使用。"""

    result: List[Dict[str, Any]] = []
    for strategy in ("baseline", *STRATEGY_ORDER):
        strategy_rows = [row for row in window_rows if row["strategy"] == strategy]
        for metric in metrics:
            values = [_number(row.get(metric)) for row in strategy_rows]
            usable = [value for value in values if value is not None]
            if not usable:
                continue
            result.append(
                {
                    "strategy": strategy,
                    "strategy_label": STRATEGY_LABELS[strategy],
                    "metric": metric,
                    "metric_label": METRIC_LABELS[metric],
                    "statistical_unit": "evaluation_window",
                    "n_windows": len(usable),
                    "mean": statistics.mean(usable),
                    "median": statistics.median(usable),
                    "sample_std": statistics.stdev(usable) if len(usable) >= 2 else 0.0,
                    "q1": _quantile(usable, 0.25),
                    "q3": _quantile(usable, 0.75),
                    "min": min(usable),
                    "max": max(usable),
                }
            )
    return result


def _statistical_rows(paired: Sequence[Mapping[str, Any]], analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """按策略和指标计算描述统计、区间估计与配对检验。"""

    groups: Dict[Tuple[str, str], List[float]] = {}
    for row in paired:
        groups.setdefault((str(row["strategy"]), str(row["metric"])), []).append(float(row["improvement"]))
    result: List[Dict[str, Any]] = []
    base_seed = int(analysis["statistics_seed"])
    confidence_level = float(analysis["confidence_level"])
    bootstrap_replicates = int(analysis["bootstrap_replicates"])
    permutation_replicates = int(analysis["permutation_replicates"])
    min_windows = int(analysis["min_windows_for_inference"])
    for strategy in COMPARISON_ORDER:
        for metric in analysis["metrics"]:
            values = groups.get((strategy, metric), [])
            if not values:
                continue
            mean_ci = _bootstrap_interval(
                values,
                "mean",
                confidence_level,
                bootstrap_replicates,
                _stable_seed(base_seed, strategy, metric, "mean"),
            )
            median_ci = _bootstrap_interval(
                values,
                "median",
                confidence_level,
                bootstrap_replicates,
                _stable_seed(base_seed, strategy, metric, "median"),
            )
            inference_ready = len(values) >= min_windows
            p_value, method = _paired_sign_flip_p_value(
                values,
                permutation_replicates,
                _stable_seed(base_seed, strategy, metric, "sign_flip"),
            )
            sample_std = statistics.stdev(values) if len(values) >= 2 else 0.0
            result.append(
                {
                    "strategy": strategy,
                    "strategy_label": STRATEGY_LABELS[strategy],
                    "metric": metric,
                    "metric_label": METRIC_LABELS[metric],
                    "statistical_unit": "evaluation_window",
                    "n_windows": len(values),
                    "inference_ready": inference_ready,
                    "mean_improvement": statistics.mean(values),
                    "median_improvement": statistics.median(values),
                    "sample_std": sample_std,
                    "q1": _quantile(values, 0.25),
                    "q3": _quantile(values, 0.75),
                    "min": min(values),
                    "max": max(values),
                    "positive_window_rate": sum(value > 0 for value in values) / len(values),
                    "mean_ci_low": mean_ci[0],
                    "mean_ci_high": mean_ci[1],
                    "median_ci_low": median_ci[0],
                    "median_ci_high": median_ci[1],
                    "cohen_dz": statistics.mean(values) / sample_std if sample_std > 1e-12 else None,
                    "p_value_raw": p_value if inference_ready else None,
                    "p_value_holm": None,
                    "test_method": method if inference_ready else "descriptive_only",
                }
            )
    _holm_adjust(result)
    return result


def _plot_paired_effects(rows: Sequence[Mapping[str, Any]], metrics: Sequence[str], output_path: Path) -> None:
    """绘制各评价窗成对改善量和均值置信区间。"""

    figure, axes = plt.subplots(len(metrics), 1, figsize=(10, max(4, 3.2 * len(metrics))), squeeze=False)
    colors = {"no_storage": "#c44e52", "rule": "#4c72b0", "nsga2": "#55a868", "nsga2_vs_rule": "#8172b3"}
    for metric_index, metric in enumerate(metrics):
        axis = axes[metric_index][0]
        for strategy_index, strategy in enumerate(COMPARISON_ORDER):
            values = [float(row["improvement"]) for row in rows if row["metric"] == metric and row["strategy"] == strategy]
            if not values:
                continue
            offsets = [strategy_index + (index - (len(values) - 1) / 2.0) * 0.035 for index in range(len(values))]
            axis.scatter(offsets, values, color=colors[strategy], alpha=0.7, s=30)
            axis.scatter([strategy_index], [statistics.mean(values)], color="black", marker="D", s=34, zorder=4)
        axis.axhline(0.0, color="#555555", linewidth=0.9)
        axis.set_xticks(range(len(COMPARISON_ORDER)))
        axis.set_xticklabels([STRATEGY_LABELS[name] for name in COMPARISON_ORDER])
        axis.set_ylabel("改善量（正值更优）")
        axis.set_title(METRIC_LABELS[metric])
        axis.grid(True, axis="y", alpha=0.22)
    figure.suptitle("各评价窗相对基线的成对改善")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _plot_seed_stability(rows: Sequence[Mapping[str, Any]], output_path: Path) -> None:
    """绘制每个评价窗的 NSGA-II 跨种子离散范围。"""

    grid_rows = [row for row in rows if row["metric"] == "grid_kwh"]
    figure, axis = plt.subplots(figsize=(10, 5))
    if grid_rows:
        x = list(range(len(grid_rows)))
        medians = [float(row["median"]) for row in grid_rows]
        lower = [median - float(row["min"]) for median, row in zip(medians, grid_rows)]
        upper = [float(row["max"]) - median for median, row in zip(medians, grid_rows)]
        axis.errorbar(x, medians, yerr=[lower, upper], fmt="o", color="#4c72b0", capsize=4)
        axis.set_xticks(x)
        axis.set_xticklabels([str(row["window_id"]) for row in grid_rows], rotation=25, ha="right")
    else:
        axis.text(0.5, 0.5, "没有可用的 NSGA-II 种子结果", ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
    axis.set_ylabel("购电量（kWh）")
    axis.set_title("NSGA-II 跨随机种子稳定性（中位数及范围）")
    axis.grid(True, axis="y", alpha=0.22)
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _plot_timestep_sensitivity(rows: Sequence[Mapping[str, Any]], output_path: Path) -> None:
    """绘制各评价窗相对 1 秒结算的误差。"""

    metrics = (
        ("grid_error_pct_vs_1s", "购电量误差（%）"),
        ("wasted_error_pct_vs_1s", "弃能误差（%）"),
        ("effective_loss_error_pct_vs_1s", "有效再生损失误差（%）"),
    )
    steps = sorted({int(row["time_step_s"]) for row in rows})
    figure, axes = plt.subplots(len(metrics), 1, figsize=(9, 9), squeeze=False)
    for index, (field, label) in enumerate(metrics):
        axis = axes[index][0]
        for step_index, step in enumerate(steps):
            values = [_number(row.get(field)) for row in rows if int(row["time_step_s"]) == step]
            usable = [value for value in values if value is not None]
            if not usable:
                continue
            offsets = [step_index + (item - (len(usable) - 1) / 2.0) * 0.035 for item in range(len(usable))]
            axis.scatter(offsets, usable, color="#4c72b0", alpha=0.7, s=28)
            axis.scatter([step_index], [statistics.median(usable)], color="black", marker="D", s=32, zorder=4)
        axis.axhline(0.0, color="#555555", linewidth=0.9)
        axis.set_xticks(range(len(steps)))
        axis.set_xticklabels([f"{step}s" for step in steps])
        axis.set_ylabel(label)
        axis.grid(True, axis="y", alpha=0.22)
    figure.suptitle("F08 时间步长敏感性（相对1秒结算）")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_report(
    path: Path,
    *,
    study: Mapping[str, Any],
    window_status: Sequence[Mapping[str, Any]],
    statistics_rows: Sequence[Mapping[str, Any]],
    exclusions: Sequence[Mapping[str, Any]],
    timestep_rows: Sequence[Mapping[str, Any]],
    calibration_rows: Sequence[Mapping[str, Any]],
) -> None:
    """生成可以直接用于论文实验复核的中文统计报告。"""

    completed = sum(row["status"] == "completed" for row in window_status if row["include"])
    included = sum(bool(row["include"]) for row in window_status)
    lines = [
        "# 论文实验与统计自动化报告",
        "",
        f"- 研究编号：`{study['study_id']}`",
        f"- 数据版本：`{study['dataset_version']}`",
        f"- 总体状态：`{study['status']}`",
        f"- 纳入评价窗：{included}；完成：{completed}",
        "- 统计单位：评价窗；NSGA-II 多随机种子先在窗内取中位数",
        f"- 置信水平：{float(study['analysis']['confidence_level']) * 100:.1f}%",
        "",
        "各策略的绝对 KPI 均值、中位数和四分位数见 `paper_strategy_summary.csv`；下表报告同窗相对基线的改善量。",
        "",
        "## 核心统计结果",
        "",
        "改善量统一转换为正值更优。前三组以 B0 为参照，F05 以规则法为参照；低值优指标使用“参照减方案”，回收率使用“方案减参照”。",
        "",
        f"| 策略 | 指标 | 窗口数 | 均值改善 | {float(study['analysis']['confidence_level']) * 100:.1f}%区间 | 中位数改善 | 正改善比例 | Holm校正p值 | 结论级别 |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in statistics_rows:
        adjusted = row.get("p_value_holm")
        inference = "推断统计" if row["inference_ready"] else "仅描述统计"
        lines.append(
            f"| {row['strategy_label']} | {row['metric_label']} | {row['n_windows']} | "
            f"{float(row['mean_improvement']):.6g} | [{float(row['mean_ci_low']):.6g}, {float(row['mean_ci_high']):.6g}] | "
            f"{float(row['median_improvement']):.6g} | {float(row['positive_window_rate']):.1%} | "
            f"{'' if adjusted is None else f'{float(adjusted):.6g}'} | {inference} |"
        )
    lines.extend(["", "## F08 时间步长敏感性", ""])
    if timestep_rows:
        lines.extend(
            [
                "| 步长 | 评价窗数 | 购电误差中位数 % | 弃能误差中位数 % | 有效损失误差中位数 % | 耗时中位数 s |",
                "| ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for step in sorted({int(row["time_step_s"]) for row in timestep_rows}):
            selected = [row for row in timestep_rows if int(row["time_step_s"]) == step]
            values = []
            for field in ("grid_error_pct_vs_1s", "wasted_error_pct_vs_1s", "effective_loss_error_pct_vs_1s", "runtime_s"):
                usable = [_number(row.get(field)) for row in selected]
                values.append(_median(usable))
            rendered = ["" if value is None else f"{float(value):.6g}" for value in values]
            lines.append(f"| {step} | {len(selected)} | {rendered[0]} | {rendered[1]} | {rendered[2]} | {rendered[3]} |")
    else:
        lines.append("没有通过完整性门禁的 F08 时间步长结果。")
    calibration_provided = sum(bool(row.get("provided")) for row in calibration_rows)
    calibration_accepted = sum(bool(row.get("accepted")) for row in calibration_rows)
    lines.extend(
        [
            "",
            "## F10 校准证据",
            "",
            f"- 已完成评价窗：{len(calibration_rows)}",
            f"- 提供模型—电表校准证据：{calibration_provided}",
            f"- 校准质量门禁通过：{calibration_accepted}",
            "- 逐窗证据路径、SHA-256、失败门禁和验证指标见 `paper_calibration_evidence.csv`。",
        ]
    )
    lines.extend(
        [
            "",
            "## 统计口径",
            "",
            "- 同一评价窗内的基线与对照方案构成一对；不同评价窗是跨窗统计样本。",
            "- NSGA-II 的随机种子用于衡量算法随机性，不作为额外独立工程样本。",
            "- 区间为确定性百分位 Bootstrap 区间；p 值来自双侧配对符号翻转检验，并对本报告中的主检验做 Holm 校正。",
            "- 评价窗数量未达到预设门槛时仍输出描述统计，但不得据此宣称统计显著。",
            "",
            "## 数据排除与失败",
            "",
        ]
    )
    if exclusions:
        lines.extend(["| 评价窗 | 方案 | 种子 | 原因 |", "| --- | --- | --- | --- |"])
        for row in exclusions:
            lines.append(f"| {row.get('window_id', '')} | {row.get('scenario_code', '')} | {row.get('seed', '')} | {row.get('reason', '')} |")
    else:
        lines.append("没有被排除的评价窗或方案结果。")
    lines.extend(
        [
            "",
            "## 论文使用边界",
            "",
            "只有正式数据准入、单方案质量门禁和本统计链路均通过时，结果才可表述为正式数据实验。没有电表校准时只能称为基于正式输入的仿真比较；使用规划参数或合成数据时只能用于机制验证。",
            "",
            "## 输出文件",
            "",
            "- `paper_analysis_rows.csv`：以评价窗和策略为粒度的分析表。",
            "- `paper_paired_effects.csv`：每个评价窗相对基线的成对差值。",
            "- `paper_strategy_summary.csv`：各策略跨评价窗的绝对 KPI 描述统计。",
            "- `paper_statistical_summary.csv`：描述统计、效应量、置信区间和检验结果。",
            "- `paper_seed_stability.csv`：NSGA-II 窗内跨种子稳定性。",
            "- `paper_exclusions.csv`：预先排除、执行失败和质量门禁拒绝记录。",
            "- `paper_window_status.csv`：每个预注册评价窗的执行或排除状态。",
            "- `paper_timestep_sensitivity.csv`：F08 各窗时间步长误差和耗时。",
            "- `paper_calibration_evidence.csv`：F10 模型—电表校准证据索引。",
            "- `figures/paired_effects.png`、`figures/nsga2_seed_stability.png`、`figures/timestep_sensitivity.png`：论文统计图。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _freeze_entry(window: Mapping[str, Any], result_dir: Path, aggregate_only: bool) -> Dict[str, Any]:
    """记录评价窗输入或既有结果的不可变摘要。"""

    entry: Dict[str, Any] = {
        "window_id": window["window_id"],
        "include": window["include"],
        "exclusion_reason": window["exclusion_reason"],
        "result_dir": str(result_dir),
    }
    if aggregate_only:
        for name in ("formal_experiment_summary.json", "formal_experiment_kpi.csv"):
            path = result_dir / name
            entry[f"{name}_sha256"] = _sha256(path) if path.is_file() else ""
    elif window["include"]:
        for name in ("data_dir", "source_dir", "timetable"):
            path = _resolve_project_path(window[name])
            entry[name] = str(path)
            entry[f"{name}_sha256"] = _tree_sha256(path)
    return entry


def run_paper_experiment_pipeline(
    *,
    study_manifest: Path,
    output_root: Path,
    aggregate_only: bool = False,
) -> Dict[str, Any]:
    """执行研究清单并形成从原始方案结果到论文统计表图的完整链路。"""

    study_manifest = Path(study_manifest)
    output_root = Path(output_root)
    manifest = _validate_manifest(_read_json(study_manifest), aggregate_only=aggregate_only)
    output_root.mkdir(parents=True, exist_ok=True)
    statistics_dir = output_root / "statistics"
    if statistics_dir.exists() and any(statistics_dir.iterdir()):
        raise FileExistsError(f"统计输出目录非空，拒绝覆盖既有研究结果：{statistics_dir}")
    statistics_dir.mkdir(parents=True, exist_ok=True)

    parameters = manifest["experiment_parameters"]
    status_rows: List[Dict[str, Any]] = []
    exclusions: List[Dict[str, Any]] = []
    freeze_windows: List[Dict[str, Any]] = []
    analysis_rows: List[Dict[str, Any]] = []
    seed_rows: List[Dict[str, Any]] = []
    timestep_rows: List[Dict[str, Any]] = []
    calibration_rows: List[Dict[str, Any]] = []

    for window in manifest["windows"]:
        window_id = window["window_id"]
        result_dir = _resolve_project_path(window["result_dir"]) if window.get("result_dir") else output_root / "windows" / window_id
        freeze_windows.append(_freeze_entry(window, result_dir, aggregate_only))
        status = {
            "window_id": window_id,
            "include": window["include"],
            "status": "excluded" if not window["include"] else "pending",
            "result_dir": str(result_dir),
            "reason": window["exclusion_reason"],
        }
        if not window["include"]:
            exclusions.append({"window_id": window_id, "scenario_code": "", "algorithm": "", "seed": "", "reason": window["exclusion_reason"]})
            status_rows.append(status)
            continue
        try:
            if not aggregate_only:
                result = run_formal_experiment_suite(
                    data_dir=_resolve_project_path(window["data_dir"]),
                    source_dir=_resolve_project_path(window["source_dir"]),
                    timetable=_resolve_project_path(window["timetable"]),
                    output_root=result_dir,
                    window_id=window_id,
                    seeds=parameters["seeds"],
                    max_shift_min=int(parameters["max_shift_min"]),
                    step_min=int(parameters["step_min"]),
                    max_dwell_extension_min=int(parameters["max_dwell_extension_min"]),
                    max_candidates=int(parameters["max_candidates"]),
                    population_size=int(parameters["population_size"]),
                    generations=int(parameters["generations"]),
                    crossover_rate=float(parameters["crossover_rate"]),
                    mutation_rate=float(parameters["mutation_rate"]),
                    strict_visualizations=bool(parameters["strict_visualizations"]),
                    calibration_summary=_resolve_project_path(window["calibration_summary"]) if window.get("calibration_summary") else None,
                    require_calibration=bool(window.get("require_calibration", manifest.get("require_calibration", False))),
                    settlement_steps_s=parameters["settlement_steps_s"],
                )
                if result.get("status") != "completed":
                    raise ValueError(f"正式实验总控状态为 {result.get('status')}")
            summary, raw_rows = _load_result_rows(result_dir)
            if str(summary.get("window_id", "")) != window_id:
                raise ValueError(f"结果 window_id 与研究清单不一致：{summary.get('window_id')} != {window_id}")
            if summary.get("status") != "completed":
                raise ValueError(f"既有正式实验结果状态不是 completed：{summary.get('status')}")
            _validate_window_design(raw_rows, parameters["seeds"])
            window_timestep_rows = _validate_timestep_design(summary, parameters["settlement_steps_s"])
            aggregated, stability, rejected = _aggregate_window(window_id, raw_rows, manifest["analysis"]["metrics"])
            if not any(row["strategy"] == "baseline" for row in aggregated):
                raise ValueError("没有可用的质量合格基线，无法进行成对统计。")
            analysis_rows.extend(aggregated)
            seed_rows.extend(stability)
            timestep_rows.extend({"window_id": window_id, **row} for row in window_timestep_rows)
            calibration = summary.get("calibration") if isinstance(summary.get("calibration"), dict) else {}
            calibration_rows.append(
                {
                    "window_id": window_id,
                    "provided": bool(calibration.get("provided", False)),
                    "accepted": bool(calibration.get("accepted", False)),
                    "status": calibration.get("status", "not_recorded"),
                    "summary_path": calibration.get("summary_path", ""),
                    "sha256": calibration.get("sha256", ""),
                    "failed_checks_json": json.dumps(calibration.get("failed_checks", []), ensure_ascii=False, sort_keys=True),
                    "validation_metrics_json": json.dumps(calibration.get("validation_metrics", {}), ensure_ascii=False, sort_keys=True),
                }
            )
            exclusions.extend(rejected)
            status["status"] = "completed"
            status["reason"] = ""
        except Exception as exc:
            status["status"] = "failed"
            status["reason"] = str(exc)
            exclusions.append({"window_id": window_id, "scenario_code": "", "algorithm": "", "seed": "", "reason": str(exc)})
        status_rows.append(status)

    paired = _paired_rows(analysis_rows, manifest["analysis"]["metrics"])
    strategy_summary = _strategy_summary_rows(analysis_rows, manifest["analysis"]["metrics"])
    statistical = _statistical_rows(paired, manifest["analysis"])
    included_statuses = [row["status"] for row in status_rows if row["include"]]
    pipeline_status = "completed" if included_statuses and all(value == "completed" for value in included_statuses) else "failed"
    visualization = {"accepted": True, "failures": []}
    try:
        _plot_paired_effects(paired, manifest["analysis"]["metrics"], statistics_dir / "figures" / "paired_effects.png")
        _plot_seed_stability(seed_rows, statistics_dir / "figures" / "nsga2_seed_stability.png")
        _plot_timestep_sensitivity(timestep_rows, statistics_dir / "figures" / "timestep_sensitivity.png")
    except Exception as exc:
        visualization = {"accepted": False, "failures": [str(exc)]}
        pipeline_status = "failed"

    freeze = {
        "schema_version": "1.0",
        "study_id": manifest["study_id"],
        "dataset_version": manifest["dataset_version"],
        "source_manifest": str(study_manifest),
        "source_manifest_sha256": _sha256(study_manifest),
        "pipeline_sha256": _sha256(Path(__file__)),
        "experiment_parameters": parameters,
        "analysis": manifest["analysis"],
        "windows": freeze_windows,
    }
    summary = {
        "schema_version": "1.0",
        "status": pipeline_status,
        "study_id": manifest["study_id"],
        "dataset_version": manifest["dataset_version"],
        "aggregate_only": aggregate_only,
        "statistical_unit": "evaluation_window",
        "window_status": status_rows,
        "included_window_count": len(included_statuses),
        "completed_window_count": sum(value == "completed" for value in included_statuses),
        "analysis_row_count": len(analysis_rows),
        "paired_effect_row_count": len(paired),
        "strategy_summary_row_count": len(strategy_summary),
        "statistical_row_count": len(statistical),
        "seed_stability_row_count": len(seed_rows),
        "timestep_sensitivity_row_count": len(timestep_rows),
        "calibration_evidence_row_count": len(calibration_rows),
        "exclusion_count": len(exclusions),
        "analysis": manifest["analysis"],
        "visualization": visualization,
        "outputs": {
            "freeze_manifest": "STUDY_FREEZE_MANIFEST.json",
            "analysis_rows": "statistics/paper_analysis_rows.csv",
            "paired_effects": "statistics/paper_paired_effects.csv",
            "strategy_summary": "statistics/paper_strategy_summary.csv",
            "statistical_summary": "statistics/paper_statistical_summary.csv",
            "seed_stability": "statistics/paper_seed_stability.csv",
            "exclusions": "statistics/paper_exclusions.csv",
            "window_status": "statistics/paper_window_status.csv",
            "timestep_sensitivity": "statistics/paper_timestep_sensitivity.csv",
            "calibration_evidence": "statistics/paper_calibration_evidence.csv",
            "report": "statistics/PAPER_STATISTICS_REPORT.md",
        },
    }

    analysis_fields = ["window_id", "strategy", "strategy_label", "replicate_count", "aggregation", "optimize_count", "keep_baseline_count", *NUMERIC_FIELDS]
    paired_fields = ["window_id", "strategy", "strategy_label", "reference_strategy", "treatment_strategy", "metric", "metric_label", "direction", "reference_value", "treatment_value", "raw_difference_treatment_minus_reference", "improvement", "improvement_pct"]
    strategy_summary_fields = ["strategy", "strategy_label", "metric", "metric_label", "statistical_unit", "n_windows", "mean", "median", "sample_std", "q1", "q3", "min", "max"]
    statistic_fields = ["strategy", "strategy_label", "metric", "metric_label", "statistical_unit", "n_windows", "inference_ready", "mean_improvement", "median_improvement", "sample_std", "q1", "q3", "min", "max", "positive_window_rate", "mean_ci_low", "mean_ci_high", "median_ci_low", "median_ci_high", "cohen_dz", "p_value_raw", "p_value_holm", "test_method"]
    seed_fields = ["window_id", "metric", "metric_label", "seed_count", "mean", "median", "sample_std", "cv", "min", "max", "range"]
    exclusion_fields = ["window_id", "scenario_code", "algorithm", "seed", "reason"]
    timestep_fields = ["window_id", "time_step_s", "status", "quality_accepted", "runtime_s", "grid_kwh", "wasted_kwh", "effective_regen_loss_kwh", "recovery_rate", "grid_difference_vs_1s", "grid_error_pct_vs_1s", "wasted_difference_vs_1s", "wasted_error_pct_vs_1s", "effective_loss_difference_vs_1s", "effective_loss_error_pct_vs_1s", "recovery_rate_difference_vs_1s", "error", "output_dir"]
    calibration_fields = ["window_id", "provided", "accepted", "status", "summary_path", "sha256", "failed_checks_json", "validation_metrics_json"]
    _write_csv(statistics_dir / "paper_analysis_rows.csv", analysis_rows, analysis_fields)
    _write_csv(statistics_dir / "paper_paired_effects.csv", paired, paired_fields)
    _write_csv(statistics_dir / "paper_strategy_summary.csv", strategy_summary, strategy_summary_fields)
    _write_csv(statistics_dir / "paper_statistical_summary.csv", statistical, statistic_fields)
    _write_csv(statistics_dir / "paper_seed_stability.csv", seed_rows, seed_fields)
    _write_csv(statistics_dir / "paper_exclusions.csv", exclusions, exclusion_fields)
    _write_csv(statistics_dir / "paper_window_status.csv", status_rows, ["window_id", "include", "status", "result_dir", "reason"])
    _write_csv(statistics_dir / "paper_timestep_sensitivity.csv", timestep_rows, timestep_fields)
    _write_csv(statistics_dir / "paper_calibration_evidence.csv", calibration_rows, calibration_fields)
    _write_json(output_root / "STUDY_FREEZE_MANIFEST.json", freeze)
    _write_json(statistics_dir / "paper_statistics_summary.json", summary)
    _write_json(statistics_dir / "visualization_diagnostics.json", visualization)
    _write_report(
        statistics_dir / "PAPER_STATISTICS_REPORT.md",
        study={**summary, "analysis": manifest["analysis"]},
        window_status=status_rows,
        statistics_rows=statistical,
        exclusions=exclusions,
        timestep_rows=timestep_rows,
        calibration_rows=calibration_rows,
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """提供独立命令行入口。"""

    parser = argparse.ArgumentParser(description="批量执行正式评价窗并生成论文统计表图。")
    parser.add_argument("--study-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--aggregate-only", action="store_true", help="不运行算法，只汇总清单引用的既有正式实验结果。")
    args = parser.parse_args(argv)
    summary = run_paper_experiment_pipeline(
        study_manifest=args.study_manifest,
        output_root=args.output_root,
        aggregate_only=args.aggregate_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
