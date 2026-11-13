"""技术方案 4.2.1.2(1) 敏感性与稳健性情景集。

方案原文要求围绕"组织参数—方案响应—能耗曲线"的闭环，以**发车间隔、大小列比例、组合站能力与需求扰动**
为核心变量设计情景集，分别求解并统计系统总能耗、单位运量能耗、能力利用率、平均追踪间隔、在站等待分布
与瓶颈拥堵风险等指标；对高敏区段设置软惩罚或弹性边界。

本模块对四个核心变量各取若干水平构造情景集并逐一求解，输出：

- 各情景的解释性指标（含单位运量能耗、拥堵风险指数）；
- 各变量对各指标的敏感性（相对变化范围）与影响排序；
- 高敏区段识别与弹性边界建议（可直接填入模板 ``section_elasticity`` 工作表）。

所有结果写入 ``outputs/sensitivity/``，汇总于 ``sensitivity_summary.json``。结果为原型级对照，
不能作为正式节能量结论。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import csv
import json

from heavy_empty_network_optimizer import (
    HeInputBundle,
    _capacity_utilization_rows,
    _first_running_arcs,
    congestion_risk_rows,
    corridor_capacity_rows,
    energy_per_transport,
    optimize_heavy_empty_network,
)


SCHEMA_VERSION = "1.0"
TECHNICAL_CLAUSE = "4.2.1.2(1)"
DEFAULT_SCENARIO_ID = "capacity_surplus_demo"
DEFAULT_TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
DEFAULT_OUTPUT_DIR = Path("outputs") / "sensitivity"

SENSITIVITY_VARIABLES: Tuple[str, ...] = (
    "headway",
    "formation_ratio",
    "combine_capacity",
    "demand",
)
"""四个核心敏感性变量（技术方案 4.2.1.2(1)）。"""

SENSITIVITY_LEVELS: Dict[str, Tuple[Any, ...]] = {
    "headway": (0.5, 1.0, 1.5),
    "formation_ratio": ("small", "baseline", "large"),
    "combine_capacity": (0.5, 1.0, 2.0),
    "demand": (0.5, 1.0, 1.5),
}
"""各变量的水平。float 为倍率；formation_ratio 为列型取向（small/baseline/large）。"""

BASELINE_LEVELS: Dict[str, Any] = {
    "headway": 1.0,
    "formation_ratio": "baseline",
    "combine_capacity": 1.0,
    "demand": 1.0,
}
"""各变量的基准水平（不改变模板）。"""

VARIABLE_LABELS: Dict[str, str] = {
    "headway": "发车间隔 h/g",
    "formation_ratio": "大小列比例",
    "combine_capacity": "组合站能力",
    "demand": "需求扰动",
}

SENSITIVITY_METRICS: Tuple[str, ...] = (
    "total_energy_kwh",
    "energy_per_1000_ton_km",
    "capacity_utilization_max",
    "avg_tracking_headway_s",
    "station_wait_mean_s",
    "max_corridor_congestion_risk_index",
)
"""纳入敏感性排序的解释性指标。"""

METRIC_UNITS: Dict[str, str] = {
    "total_energy_kwh": "kWh",
    "energy_per_1000_ton_km": "kWh/(千吨·km)",
    "throughput_ton_km": "ton-km",
    "capacity_utilization_max": "-",
    "capacity_utilization_mean": "-",
    "avg_tracking_headway_s": "s",
    "station_wait_mean_s": "s",
    "station_wait_max_s": "s",
    "max_congestion_risk_index": "-",
    "mean_congestion_risk_index": "-",
    "max_corridor_congestion_risk_index": "-",
    "constraint_violation": "-",
    "elastic_soft_penalty": "CNY",
}

HIGH_SENSITIVITY_RISK_THRESHOLD = 0.5
"""高敏区段判定阈值：走廊最大拥堵风险指数不低于该值即视为高敏。"""

RECOMMENDED_CAPACITY_MULTIPLIER = 1.5
"""高敏区段建议的弹性容量倍率。"""

RECOMMENDED_SOFT_PENALTY_WEIGHT = 500.0
"""高敏区段建议的软惩罚系数。"""


def _level_label(variable: str, level: Any) -> str:
    """把水平值转为可读标签。"""
    if isinstance(level, str):
        return level
    return f"x{float(level):.1f}"


def _formation_locked_demands(bundle: HeInputBundle) -> set:
    """被 formation_operations 引用的需求（受数量守恒约束，扰动时需保护）。"""
    return {operation.demand_id for operation in bundle.formation_operations}


def _scale_headway(bundle: HeInputBundle, factor: float) -> HeInputBundle:
    """按倍率缩放发发间隔 h 与到到间隔 g（不低于 1 分钟）。"""
    scenarios = {
        name: replace(
            scenario,
            min_headway_s=max(60, int(round(scenario.min_headway_s * factor))),
            min_arrival_headway_s=max(60, int(round(scenario.min_arrival_headway_s * factor))),
        )
        for name, scenario in bundle.scenarios.items()
    }
    return replace(bundle, scenarios=scenarios)


def _direction_service_variants(bundle: HeInputBundle) -> Dict[str, Tuple[str, str]]:
    """按运行方向给出（大列服务名, 小列服务名）；无大小列区分的方向不返回。"""
    groups: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for name, service in bundle.service_types.items():
        groups[service.direction].append((service.consist_unit, name))
    variants: Dict[str, Tuple[str, str]] = {}
    for direction, items in groups.items():
        items.sort()
        small_unit, small_name = items[0]
        large_unit, large_name = items[-1]
        if small_unit == large_unit:
            continue
        variants[direction] = (large_name, small_name)
    return variants


def _apply_formation_ratio(bundle: HeInputBundle, mode: str) -> HeInputBundle:
    """按列型取向调整非组合需求的大/小列服务（大小列比例敏感性）。

    被 ``formation_operations`` 引用的需求保持不变（组合数量守恒要求其列型固定）。
    """
    if mode == "baseline":
        return bundle
    if mode not in {"small", "large"}:
        raise ValueError(f"unsupported formation_ratio level: {mode!r}")
    variants = _direction_service_variants(bundle)
    locked = _formation_locked_demands(bundle)
    demands = []
    for demand in bundle.demands:
        service = bundle.service_types.get(demand.train_type)
        if demand.demand_id in locked or service is None:
            demands.append(demand)
            continue
        pair = variants.get(service.direction)
        if pair is None:
            demands.append(demand)
            continue
        large_name, small_name = pair
        demands.append(replace(demand, train_type=small_name if mode == "small" else large_name))
    return replace(bundle, demands=tuple(demands))


def _apply_combine_capacity(bundle: HeInputBundle, factor: float) -> HeInputBundle:
    """按倍率缩放组合/分解站作业能力（组合站能力敏感性）。"""
    nodes = {}
    for name, node in bundle.operation_nodes.items():
        if node.role == "combine_split":
            nodes[name] = replace(
                node, capacity_per_slot=max(1, int(round(node.capacity_per_slot * factor)))
            )
        else:
            nodes[name] = node
    return replace(bundle, operation_nodes=nodes)


def _apply_demand(bundle: HeInputBundle, factor: float) -> HeInputBundle:
    """按倍率缩放 OD 需求吨位 ``cargo_tons``（需求扰动敏感性）。

    只缩放需求吨位、不改 ``train_count``，以免破坏组合/分解站的数量守恒（组合作业按车底副本数配对）。
    """
    demands = tuple(
        replace(demand, cargo_tons=demand.cargo_tons * factor) for demand in bundle.demands
    )
    return replace(bundle, demands=demands)


def build_variant_bundle(bundle: HeInputBundle, variable: str, level: Any) -> HeInputBundle:
    """按变量与水平构造情景 bundle。"""
    if variable == "headway":
        return _scale_headway(bundle, float(level))
    if variable == "formation_ratio":
        return _apply_formation_ratio(bundle, str(level))
    if variable == "combine_capacity":
        return _apply_combine_capacity(bundle, float(level))
    if variable == "demand":
        return _apply_demand(bundle, float(level))
    raise ValueError(f"unsupported sensitivity variable: {variable!r}")


def _average_tracking_headway_s(candidate) -> float:
    """平均追踪间隔（同列型首发车相邻间隔的均值）。"""
    by_type: Dict[str, List[int]] = defaultdict(list)
    for arc in _first_running_arcs(candidate):
        by_type[arc.train_type].append(arc.start_time_s)
    gaps: List[int] = []
    for times in by_type.values():
        ordered = sorted(times)
        gaps.extend(right - left for left, right in zip(ordered, ordered[1:]))
    return sum(gaps) / len(gaps) if gaps else 0.0


def _station_wait_stats(candidate) -> Tuple[float, float]:
    """在站等待分布的均值与最大值（基于显式 waiting 弧）。"""
    waits = [
        max(0, arc.end_time_s - arc.start_time_s)
        for arc in candidate.arcs
        if arc.arc_type == "waiting"
    ]
    if not waits:
        return 0.0, 0.0
    return sum(waits) / len(waits), float(max(waits))


def _corridor_risk_map(result, bundle: HeInputBundle) -> Dict[str, float]:
    """走廊键 → 该情景下的最大拥堵风险指数。"""
    risk: Dict[str, float] = defaultdict(float)
    for row in corridor_capacity_rows(result.best_candidate, result.scenario, bundle):
        risk[row["section_key"]] = max(risk[row["section_key"]], float(row["congestion_risk_index"]))
    return dict(risk)


def scenario_metrics(result, bundle: HeInputBundle) -> Dict[str, Any]:
    """收集一个情景的解释性指标。"""
    candidate = result.best_candidate
    per_transport = energy_per_transport(candidate)
    risk_rows = congestion_risk_rows(result, bundle)
    risks = [float(row["congestion_risk_index"]) for row in risk_rows]
    utilization = [
        float(row["utilization_ratio"])
        for row in _capacity_utilization_rows(candidate, result.scenario, bundle)
    ]
    wait_mean, wait_max = _station_wait_stats(candidate)
    corridor = corridor_capacity_rows(candidate, result.scenario, bundle)
    corridor_risks = [float(row["congestion_risk_index"]) for row in corridor]
    return {
        "total_energy_kwh": round(candidate.energy_kwh, 6),
        "energy_per_1000_ton_km": per_transport["energy_per_1000_ton_km"],
        "throughput_ton_km": round(candidate.throughput_ton_km, 6),
        "capacity_utilization_max": round(max(utilization), 6) if utilization else 0.0,
        "capacity_utilization_mean": (
            round(sum(utilization) / len(utilization), 6) if utilization else 0.0
        ),
        "avg_tracking_headway_s": round(_average_tracking_headway_s(candidate), 3),
        "station_wait_mean_s": round(wait_mean, 3),
        "station_wait_max_s": round(wait_max, 3),
        "max_congestion_risk_index": round(max(risks), 6) if risks else 0.0,
        "mean_congestion_risk_index": (
            round(sum(risks) / len(risks), 6) if risks else 0.0
        ),
        "max_corridor_congestion_risk_index": round(max(corridor_risks), 6) if corridor_risks else 0.0,
        "feasible": candidate.feasible,
        "conflict_count": candidate.conflict_count,
        "constraint_violation": round(candidate.constraint_violation, 6),
        "elastic_soft_penalty": round(candidate.elastic_soft_penalty, 6),
    }


def run_sensitivity_suite(
    bundle: HeInputBundle,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    scenario_id: str = DEFAULT_SCENARIO_ID,
    *,
    population_size: Optional[int] = None,
    generations: Optional[int] = None,
) -> Dict[str, Any]:
    """执行敏感性情景集并写出产物。"""
    if scenario_id not in bundle.scenarios:
        raise KeyError(f"Scenario {scenario_id!r} not found in template.")
    run_bundle = bundle
    if population_size is not None or generations is not None:
        run_bundle = replace(
            bundle,
            scenarios={
                name: replace(
                    scenario,
                    population_size=population_size or scenario.population_size,
                    generations=generations or scenario.generations,
                )
                for name, scenario in bundle.scenarios.items()
            },
        )

    scenario_rows: List[Dict[str, Any]] = []
    per_variable: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    corridor_risk: Dict[str, float] = defaultdict(float)
    for variable in SENSITIVITY_VARIABLES:
        for level in SENSITIVITY_LEVELS[variable]:
            variant = build_variant_bundle(run_bundle, variable, level)
            result = optimize_heavy_empty_network(variant, scenario_id)
            metrics = scenario_metrics(result, variant)
            per_variable[variable].append(metrics)
            scenario_rows.append(
                {
                    "variable": variable,
                    "variable_label": VARIABLE_LABELS[variable],
                    "level": _level_label(variable, level),
                    "level_value": str(level),
                    "is_baseline": level == BASELINE_LEVELS[variable],
                    **metrics,
                }
            )
            for section_key, value in _corridor_risk_map(result, variant).items():
                corridor_risk[section_key] = max(corridor_risk[section_key], value)

    ranking_rows = _sensitivity_ranking(per_variable)
    high_sensitivity_rows = _high_sensitivity_rows(corridor_risk)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "technical_clause": TECHNICAL_CLAUSE,
        "template_scenario_id": scenario_id,
        "result_boundary": "prototype_level_not_official_energy_saving",
        "variables": list(SENSITIVITY_VARIABLES),
        "levels": {name: [_level_label(name, level) for level in levels] for name, levels in SENSITIVITY_LEVELS.items()},
        "scenario_count": len(scenario_rows),
        "metric_units": METRIC_UNITS,
        "sensitivity_ranking": ranking_rows,
        "high_sensitivity_sections": high_sensitivity_rows,
        "high_sensitivity_risk_threshold": HIGH_SENSITIVITY_RISK_THRESHOLD,
        "recommended_elasticity": {
            "capacity_multiplier": RECOMMENDED_CAPACITY_MULTIPLIER,
            "soft_penalty_weight": RECOMMENDED_SOFT_PENALTY_WEIGHT,
        },
        "output_files": {
            "scenarios": "sensitivity_scenarios.csv",
            "ranking": "sensitivity_ranking.csv",
            "high_sensitivity_sections": "high_sensitivity_sections.csv",
            "report": "SENSITIVITY_REPORT.md",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "sensitivity_scenarios.csv", scenario_rows)
    _write_csv(output_dir / "sensitivity_ranking.csv", ranking_rows)
    _write_csv(output_dir / "high_sensitivity_sections.csv", high_sensitivity_rows)
    (output_dir / "sensitivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "SENSITIVITY_REPORT.md").write_text(
        _report_markdown(summary, scenario_rows), encoding="utf-8"
    )
    return summary


def _sensitivity_ranking(per_variable: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """按变量×指标计算相对变化范围，并给出变量影响排序。"""
    rows: List[Dict[str, Any]] = []
    variable_influence: Dict[str, List[float]] = defaultdict(list)
    for variable in SENSITIVITY_VARIABLES:
        items = per_variable[variable]
        for metric in SENSITIVITY_METRICS:
            values = [float(item[metric]) for item in items]
            span = max(values) - min(values)
            baseline = float(items[_baseline_index(variable)][metric])
            relative = span / abs(baseline) if abs(baseline) > 1e-12 else 0.0
            variable_influence[variable].append(relative)
            rows.append(
                {
                    "variable": variable,
                    "variable_label": VARIABLE_LABELS[variable],
                    "metric": metric,
                    "unit": METRIC_UNITS.get(metric, "-"),
                    "min_value": round(min(values), 6),
                    "max_value": round(max(values), 6),
                    "span": round(span, 6),
                    "baseline_value": round(baseline, 6),
                    "relative_span": round(relative, 6),
                }
            )
    for row in rows:
        row["variable_influence"] = round(
            sum(variable_influence[row["variable"]]) / len(variable_influence[row["variable"]]), 6
        )
    rows.sort(key=lambda item: (-item["variable_influence"], item["variable"], item["metric"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _baseline_index(variable: str) -> int:
    """基准水平在水平列表中的下标。"""
    return list(SENSITIVITY_LEVELS[variable]).index(BASELINE_LEVELS[variable])


def _high_sensitivity_rows(corridor_risk: Dict[str, float]) -> List[Dict[str, Any]]:
    """高敏区段识别与弹性边界建议。"""
    rows: List[Dict[str, Any]] = []
    for section_key, risk in sorted(corridor_risk.items()):
        is_high = risk >= HIGH_SENSITIVITY_RISK_THRESHOLD
        rows.append(
            {
                "section_key": section_key,
                "max_corridor_congestion_risk_index": round(risk, 6),
                "is_high_sensitivity": is_high,
                "recommended_capacity_multiplier": (
                    RECOMMENDED_CAPACITY_MULTIPLIER if is_high else 1.0
                ),
                "recommended_soft_penalty_weight": (
                    RECOMMENDED_SOFT_PENALTY_WEIGHT if is_high else 0.0
                ),
            }
        )
    rows.sort(key=lambda item: (-item["max_corridor_congestion_risk_index"], item["section_key"]))
    return rows


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _report_markdown(summary: Dict[str, Any], scenario_rows: List[Dict[str, Any]]) -> str:
    lines = [
        "# 敏感性与稳健性情景集报告（技术方案 4.2.1.2(1)）",
        "",
        f"- 模板场景：`{summary['template_scenario_id']}`",
        f"- 方案条款：{summary['technical_clause']}",
        f"- 情景数：{summary['scenario_count']}",
        "- 结论边界：原型级对照，**不能**作为正式节能量结论。",
        "",
        "## 变量影响排序（按各指标相对变化范围的均值）",
        "",
        "| 排名 | 变量 | 指标 | 基准 | 最小 | 最大 | 相对变化 |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    seen_variables: set = set()
    for row in summary["sensitivity_ranking"]:
        if row["variable"] in seen_variables:
            continue
        seen_variables.add(row["variable"])
        lines.append(
            f"| {row['rank']} | {row['variable_label']} | {row['metric']} | "
            f"{row['baseline_value']} | {row['min_value']} | {row['max_value']} | {row['relative_span']} |"
        )
    lines += [
        "",
        "## 高敏区段与弹性边界建议",
        "",
        f"- 判定阈值：走廊最大拥堵风险指数 ≥ {summary['high_sensitivity_risk_threshold']}",
        f"- 建议弹性容量倍率：{summary['recommended_elasticity']['capacity_multiplier']}",
        f"- 建议软惩罚系数：{summary['recommended_elasticity']['soft_penalty_weight']}",
        "",
        "| 区段走廊 | 最大拥堵风险 | 高敏 | 建议倍率 | 建议软惩罚 |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for row in summary["high_sensitivity_sections"]:
        lines.append(
            f"| {row['section_key']} | {row['max_corridor_congestion_risk_index']} | "
            f"{row['is_high_sensitivity']} | {row['recommended_capacity_multiplier']} | "
            f"{row['recommended_soft_penalty_weight']} |"
        )
    lines += [
        "",
        "## 各情景指标",
        "",
        "| 变量 | 水平 | 总能耗 kWh | 单位运量能耗 | 能力利用率(max) | 平均追踪间隔 s | 在站等待均值 s | 走廊拥堵风险 | 可行 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in scenario_rows:
        lines.append(
            f"| {row['variable_label']} | {row['level']} | {row['total_energy_kwh']} | "
            f"{row['energy_per_1000_ton_km']} | {row['capacity_utilization_max']} | "
            f"{row['avg_tracking_headway_s']} | {row['station_wait_mean_s']} | "
            f"{row['max_corridor_congestion_risk_index']} | {row['feasible']} |"
        )
    lines += ["", "## 复算命令", "", "```powershell", "python run_project.py sensitivity", "```", ""]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口：加载模板并执行敏感性情景集。"""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--data-dir", type=Path, default=Path("data") / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scenario-id", default=DEFAULT_SCENARIO_ID)
    parser.add_argument("--population-size", type=int, default=None)
    parser.add_argument("--generations", type=int, default=None)
    args = parser.parse_args(argv)

    from heavy_empty_network_optimizer import load_he_input_template

    bundle = load_he_input_template(args.template, real_data_dir=args.data_dir)
    summary = run_sensitivity_suite(
        bundle,
        args.output_dir,
        scenario_id=args.scenario_id,
        population_size=args.population_size,
        generations=args.generations,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "scenario_count": summary["scenario_count"],
                "high_sensitivity_sections": [
                    row["section_key"]
                    for row in summary["high_sensitivity_sections"]
                    if row["is_high_sensitivity"]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
