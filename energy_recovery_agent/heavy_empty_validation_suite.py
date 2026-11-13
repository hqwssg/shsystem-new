"""技术方案 4.1.2.4「节能策略有效性验证方法」——四类验证场景（场景 1–4）。

方案原文（`docs/reference/251216-技术方案-…(基础版)(1).docx` 4.1.2.4）给出的验证场景表：

| 场景 | 验证对象 | 对比基准 | 优化方案 | 关键评估指标 |
| --- | --- | --- | --- | --- |
| 场景 1 | 重列能耗优化 | 现行发车计划 | 基于 NSGA-II 的能耗最小化方案 | 系统总能耗、单位运量能耗 |
| 场景 2 | 空列调配优化 | 现行空列调配 | 时空网络多目标优化方案 | 空列走行距离、接续等待时间 |
| 场景 3 | 重空协同优化 | 割裂规划方案 | Pareto 优化协同方案 | 总能耗、货物周转量、虚拟车底使用量 |
| 场景 4 | 特殊路段运行优化 | 经验操纵曲线 | 能耗最优速度曲线 | 区段能耗、运行时分 |

本模块把场景 1–3 落成可复算的对照实验（基准方案 vs 优化方案），场景 4 按项目边界**只登记状态**，
不实现（能耗最优速度曲线属后续 `single_train_energy_optimization` 项目，见
`docs/migration/old_workspace_context.md` §15）。

所有结果写入 `outputs/validation/`，汇总于 `validation_summary.json`。结果为原型级对照，
不能作为正式节能量结论。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import csv
import json

from heavy_empty_network_optimizer import (
    COORDINATION_MODE_DECOUPLED,
    COORDINATION_MODE_INTEGRATED,
    OBJECTIVE_MODE_CAPACITY_TIGHT,
    HeCandidate,
    HeOptimizationResult,
    _build_candidate,
    _headway_group_key,
    load_he_input_template,
    optimize_heavy_empty_network,
)


SCHEMA_VERSION = "1.0"
TECHNICAL_CLAUSE = "4.1.2.4"
DEFAULT_SCENARIO_ID = "capacity_surplus_demo"
DEFAULT_TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
DEFAULT_OUTPUT_DIR = Path("outputs") / "validation"

VALIDATION_METRIC_UNITS: Dict[str, str] = {
    "total_energy_kwh": "kWh",
    "energy_objective_kwh": "kWh",
    "energy_per_1000_ton_km": "kWh/(千吨·km)",
    "throughput_ton_km": "ton-km",
    "total_cost": "CNY",
    "electrical_constraint_violation_kwh": "kWh",
    "max_delay_s": "s",
    "conflict_count": "次",
    "constraint_violation": "-",
    "feasible": "bool",
    "empty_travel_distance_km": "km",
    "connection_wait_s": "s",
    "empty_train_count": "列",
    "observed_min_empty_arrival_headway_s": "s",
    "arrival_headway_violation_count": "次",
    "virtual_trainset_count": "次",
    "pareto_candidate_count": "个",
    "candidate_count": "个",
}

SCENARIO_NAMES: Dict[str, str] = {
    "scenario_1_heavy_energy": "场景1 重列能耗优化",
    "scenario_2_empty_dispatch": "场景2 空列调配优化",
    "scenario_3_coordination": "场景3 重空协同优化",
}

SCENARIO_BASELINE_LABEL: Dict[str, str] = {
    "scenario_1_heavy_energy": "现行发车计划",
    "scenario_2_empty_dispatch": "现行空列调配",
    "scenario_3_coordination": "割裂规划方案",
}

SCENARIO_OPTIMIZED_LABEL: Dict[str, str] = {
    "scenario_1_heavy_energy": "基于 NSGA-II 的能耗最小化方案",
    "scenario_2_empty_dispatch": "时空网络多目标优化方案",
    "scenario_3_coordination": "Pareto 优化协同方案",
}


def _as_result(candidate: HeCandidate, scenario: Any) -> HeOptimizationResult:
    """把单个候选包装成结果对象，便于复用到达间隔统计等既有投影函数。"""
    return HeOptimizationResult(
        scenario=scenario,
        candidates=(candidate,),
        pareto_candidates=(candidate,),
        best_candidate=candidate,
        infrastructure_notes=(),
    )


def empty_travel_distance_km(candidate: HeCandidate) -> float:
    """空列走行距离：候选网络中所有空列运行弧的距离之和。"""
    return round(sum(arc.distance_km for arc in candidate.arcs if arc.arc_type == "empty_running"), 6)


def connection_wait_s(candidate: HeCandidate) -> int:
    """接续等待时间：候选网络中显式等待弧（含联合间隔修复等待）的时长之和。"""
    return int(sum(arc.end_time_s - arc.start_time_s for arc in candidate.arcs if arc.arc_type == "waiting"))


def empty_train_count(candidate: HeCandidate) -> int:
    """空列车数：出现空列运行弧的车底数。"""
    return len({arc.train_id for arc in candidate.arcs if arc.arc_type == "empty_running"})


def observed_min_empty_arrival_headway_s(
    candidate: HeCandidate,
    scenario: Any,
    bundle: Any,
) -> Optional[int]:
    """全时域内按车站—方向—列型分组的最小空列到到间隔。

    不使用时段切分，保证基准与优化方案在同一口径下可比：同组至少两列空列到达时给出最小间隔，
    只有一列时返回 ``None``。
    """
    arrivals: Dict[str, int] = {}
    meta: Dict[str, Tuple[str, str, str]] = {}
    for arc in candidate.arcs:
        if arc.arc_type != "empty_running":
            continue
        if arc.train_id not in arrivals or arc.end_time_s > arrivals[arc.train_id]:
            service = bundle.service_types.get(arc.train_type)
            if service is None:
                continue
            arrivals[arc.train_id] = arc.end_time_s
            meta[arc.train_id] = _headway_group_key(
                arc.end_station, service, arc.start_km, arc.end_km
            )
    groups: Dict[Tuple[str, str, str], List[int]] = {}
    for train_id, arrival_s in arrivals.items():
        groups.setdefault(meta[train_id], []).append(arrival_s)
    gaps: List[int] = []
    for times in groups.values():
        ordered = sorted(times)
        gaps.extend(right - left for left, right in zip(ordered, ordered[1:]))
    return min(gaps) if gaps else None


def energy_per_1000_ton_km(candidate: HeCandidate) -> float:
    """单位运量能耗：能量目标 / 货物周转量 × 1000。"""
    if candidate.throughput_ton_km <= 0:
        return 0.0
    return round(candidate.energy_objective_kwh / candidate.throughput_ton_km * 1000.0, 6)


def _candidate_metrics(
    scenario_key: str,
    candidate: HeCandidate,
    scenario: Any,
    bundle: Any,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按场景收集候选的关键评估指标。"""
    metrics: Dict[str, Any] = {
        "feasible": bool(candidate.feasible),
        "constraint_violation": round(candidate.constraint_violation, 6),
        "electrical_constraint_violation_kwh": round(candidate.electrical_constraint_violation_kwh, 6),
        "total_energy_kwh": round(candidate.energy_kwh, 6),
        "energy_objective_kwh": round(candidate.energy_objective_kwh, 6),
        "energy_per_1000_ton_km": energy_per_1000_ton_km(candidate),
        "throughput_ton_km": round(candidate.throughput_ton_km, 6),
        "total_cost": round(candidate.total_cost, 6),
        "max_delay_s": int(candidate.max_delay_s),
        "conflict_count": int(candidate.conflict_count),
        "arrival_headway_violation_count": int(candidate.arrival_headway_violation_count),
        "virtual_trainset_count": int(candidate.virtual_trainset_count),
        "empty_travel_distance_km": empty_travel_distance_km(candidate),
        "connection_wait_s": connection_wait_s(candidate),
        "empty_train_count": empty_train_count(candidate),
    }
    observed = observed_min_empty_arrival_headway_s(candidate, scenario, bundle)
    metrics["observed_min_empty_arrival_headway_s"] = observed
    if extra:
        metrics.update(extra)
    return metrics


def _scenario_1(bundle: Any, scenario_id: str) -> Dict[str, Any]:
    """场景 1：重列能耗优化（现行发车计划 vs 基于 NSGA-II 的能耗最小化方案）。"""
    scenario = bundle.scenarios[scenario_id]
    # 现行发车计划：各车底按最早发车窗口发车，发车间隔取模板最小间隔，不做时刻调整。
    baseline = _build_candidate(
        bundle, scenario, "S1_BASELINE", departure_shift_s=0, headway_s=scenario.min_headway_s
    )
    # 优化方案：能量目标权重独占的 NSGA-II 搜索（能耗最小化）。
    energy_scenario = replace(
        scenario,
        weight_energy=1.0,
        weight_distance=0.0,
        weight_connection=0.0,
        weight_virtual=0.0,
        weight_throughput=0.0,
    )
    energy_bundle = replace(bundle, scenarios={scenario_id: energy_scenario})
    optimized_result = optimize_heavy_empty_network(energy_bundle, scenario_id)
    # 用同一把尺子比较：把能耗最优方案的发车决策在原场景权重下重新评价，避免"权重不同导致
    # 成本不可比"。搜索用能耗权重，评价用原场景权重。
    searched = optimized_result.best_candidate
    max_services = (
        searched.delivered_train_count
        if scenario.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT
        else None
    )
    optimized = _build_candidate(
        bundle,
        scenario,
        "S1_OPTIMIZED",
        departure_shift_s=searched.departure_shift_s,
        headway_s=searched.headway_s,
        max_heavy_services=max_services,
    )
    return {
        "scenario": "scenario_1_heavy_energy",
        "baseline": _candidate_metrics("scenario_1_heavy_energy", baseline, scenario, bundle),
        "optimized": _candidate_metrics(
            "scenario_1_heavy_energy",
            optimized,
            scenario,
            bundle,
            extra={"candidate_count": len(optimized_result.candidates)},
        ),
        "baseline_candidate": baseline,
        "optimized_candidate": optimized,
    }


def _scenario_2(bundle: Any, scenario_id: str) -> Dict[str, Any]:
    """场景 2：空列调配优化（现行空列调配 vs 时空网络多目标优化方案）。"""
    scenario = bundle.scenarios[scenario_id]
    # 现行空列调配：空列卸车后即刻回送，不与重列到达做联合间隔协同。
    baseline = _build_candidate(
        bundle,
        scenario,
        "S2_BASELINE",
        departure_shift_s=0,
        headway_s=scenario.min_headway_s,
        coordination_mode=COORDINATION_MODE_DECOUPLED,
    )
    optimized_result = optimize_heavy_empty_network(bundle, scenario_id)
    optimized = optimized_result.best_candidate
    return {
        "scenario": "scenario_2_empty_dispatch",
        "baseline": _candidate_metrics("scenario_2_empty_dispatch", baseline, scenario, bundle),
        "optimized": _candidate_metrics(
            "scenario_2_empty_dispatch",
            optimized,
            scenario,
            bundle,
            extra={"candidate_count": len(optimized_result.candidates)},
        ),
        "baseline_candidate": baseline,
        "optimized_candidate": optimized,
    }


def _scenario_3(bundle: Any, scenario_id: str) -> Dict[str, Any]:
    """场景 3：重空协同优化（割裂规划方案 vs Pareto 优化协同方案）。"""
    scenario = bundle.scenarios[scenario_id]
    decoupled_result = optimize_heavy_empty_network(
        bundle, scenario_id, coordination_mode=COORDINATION_MODE_DECOUPLED
    )
    integrated_result = optimize_heavy_empty_network(
        bundle, scenario_id, coordination_mode=COORDINATION_MODE_INTEGRATED
    )
    baseline = decoupled_result.best_candidate
    optimized = integrated_result.best_candidate
    return {
        "scenario": "scenario_3_coordination",
        "baseline": _candidate_metrics(
            "scenario_3_coordination",
            baseline,
            scenario,
            bundle,
            extra={
                "pareto_candidate_count": len(decoupled_result.pareto_candidates),
                "candidate_count": len(decoupled_result.candidates),
            },
        ),
        "optimized": _candidate_metrics(
            "scenario_3_coordination",
            optimized,
            scenario,
            bundle,
            extra={
                "pareto_candidate_count": len(integrated_result.pareto_candidates),
                "candidate_count": len(integrated_result.candidates),
            },
        ),
        "baseline_candidate": baseline,
        "optimized_candidate": optimized,
    }


def scenario_4_status() -> Dict[str, Any]:
    """场景 4：特殊路段运行优化（能耗最优速度曲线）——按项目边界只登记状态。"""
    return {
        "scenario": "scenario_4_special_section",
        "scenario_name": "场景4 特殊路段运行优化",
        "validation_target": "特殊路段运行优化",
        "baseline": "经验操纵曲线",
        "optimized": "能耗最优速度曲线",
        "key_metrics": ["区段能耗", "运行时分"],
        "implemented": False,
        "status": "external_project",
        "owner": "single_train_energy_optimization",
        "reason": (
            "能耗最优速度曲线属车辆/控制层内容，技术方案 4.1.2.4 场景4 与 2.1.1.1 监测样机均划归"
            "后续单列车能量优化项目；本项目（重空协同，线路/网络层）不实现。"
        ),
        "boundary_reference": "docs/migration/old_workspace_context.md §15.2/§15.3",
        "technical_clause": TECHNICAL_CLAUSE,
    }


def _scenario_rows(scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把单场景的基准/优化指标展开为长表行。"""
    key = scenario["scenario"]
    rows: List[Dict[str, Any]] = []
    baseline_metrics = scenario["baseline"]
    optimized_metrics = scenario["optimized"]
    for metric in sorted(set(baseline_metrics) | set(optimized_metrics)):
        base_value = baseline_metrics.get(metric)
        opt_value = optimized_metrics.get(metric)
        delta: Any = ""
        if isinstance(base_value, (int, float)) and isinstance(opt_value, (int, float)) and not isinstance(base_value, bool) and not isinstance(opt_value, bool):
            delta = round(opt_value - base_value, 6)
        elif isinstance(base_value, bool) and isinstance(opt_value, bool):
            delta = "" if base_value == opt_value else "changed"
        rows.append(
            {
                "scenario_id": key,
                "scenario_name": SCENARIO_NAMES[key],
                "metric": metric,
                "unit": VALIDATION_METRIC_UNITS.get(metric, "-"),
                "baseline_label": SCENARIO_BASELINE_LABEL[key],
                "baseline_value": "" if base_value is None else base_value,
                "optimized_label": SCENARIO_OPTIMIZED_LABEL[key],
                "optimized_value": "" if opt_value is None else opt_value,
                "delta": delta,
            }
        )
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


def _report_markdown(
    scenario_id: str,
    scenarios: Dict[str, Dict[str, Any]],
    scenario_4: Dict[str, Any],
) -> str:
    lines = [
        "# 节能策略有效性验证报告（技术方案 4.1.2.4）",
        "",
        f"- 模板场景：`{scenario_id}`",
        f"- 方案条款：{TECHNICAL_CLAUSE}",
        "- 结论边界：原型级对照，**不能**作为正式节能量结论。",
        "",
    ]
    for key in ("scenario_1_heavy_energy", "scenario_2_empty_dispatch", "scenario_3_coordination"):
        scenario = scenarios[key]
        lines.extend(
            [
                f"## {SCENARIO_NAMES[key]}",
                "",
                f"- 对比基准：{SCENARIO_BASELINE_LABEL[key]}",
                f"- 优化方案：{SCENARIO_OPTIMIZED_LABEL[key]}",
                "",
                "| 指标 | 基准 | 优化 | 差值 | 单位 |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in _scenario_rows(scenario):
            lines.append(
                f"| `{row['metric']}` | {row['baseline_value']} | {row['optimized_value']} | "
                f"{row['delta']} | {row['unit']} |"
            )
        lines.append("")
    lines.extend(
        [
            f"## {scenario_4['scenario_name']}",
            "",
            f"- 状态：`{scenario_4['status']}`（未实现，归属 `{scenario_4['owner']}`）",
            f"- 原因：{scenario_4['reason']}",
            f"- 边界依据：{scenario_4['boundary_reference']}",
            "",
            "## 复算命令",
            "",
            "```powershell",
            "python run_project.py validation",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _interpretation(scenarios: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """给出各场景的可读结论，并显式标注原型边界（不夸大差异、不隐藏无差异）。"""
    def _delta(key: str, metric: str) -> Any:
        base = scenarios[key]["baseline"].get(metric)
        opt = scenarios[key]["optimized"].get(metric)
        if isinstance(base, (int, float)) and isinstance(opt, (int, float)) and not isinstance(base, bool):
            return round(opt - base, 6)
        return None

    energy_delta = _delta("scenario_1_heavy_energy", "energy_objective_kwh")
    return {
        "scenario_1_heavy_energy": (
            "对照现行发车计划与基于 NSGA-II 的能耗最小化方案。当前原型的能量结算只与各弧的"
            "坡度/曲线/供电臂属性及相对时间窗重叠有关，不含起停与制动回流的时刻耦合，因此"
            f"时刻调整带来的能耗差为 {energy_delta} kWh（即总能耗与单位运量能耗在两者间一致）；"
            "差异体现在接续等待时间与平均延误等组织指标上。该「无能耗差异」是原型模型边界，"
            "不是优化失败；真实牵引制动物理模型到位后需复算。"
        ),
        "scenario_2_empty_dispatch": (
            "对照现行空列调配（空列卸车后即刻回送、不与重列到达协同）与时空网络多目标优化方案。"
            "空列径路在本原型中固定，故空列走行距离不变；差别体现在联合到发间隔约束的满足性"
            f"（违反数差 {_delta('scenario_2_empty_dispatch', 'arrival_headway_violation_count')}）"
            f"与由此产生的接续等待时间（差 {_delta('scenario_2_empty_dispatch', 'connection_wait_s')}s）。"
        ),
        "scenario_3_coordination": (
            "对照割裂规划方案与 Pareto 协同方案。两者重列计划一致，故总能耗与货物周转量相同；"
            "虚拟车底使用量在本单日时域内也无差异（空列回送车底均在重列发车之后才到达，周转复用"
            "在当前时域内不可用）。差别体现在联合到发间隔约束与 Pareto 前沿："
            f"协同方案 {scenarios['scenario_3_coordination']['optimized'].get('pareto_candidate_count')} 个"
            f" Pareto 候选、联合间隔违反 {scenarios['scenario_3_coordination']['optimized'].get('arrival_headway_violation_count')} 次，"
            f"割裂方案 {scenarios['scenario_3_coordination']['baseline'].get('pareto_candidate_count')} 个"
            f" Pareto 候选、联合间隔违反 {scenarios['scenario_3_coordination']['baseline'].get('arrival_headway_violation_count')} 次。"
        ),
    }


def run_validation_suite(
    bundle: Any,
    output_dir: Path,
    scenario_id: str = DEFAULT_SCENARIO_ID,
) -> Dict[str, Any]:
    """执行四类验证场景并写出对照产物。"""
    if scenario_id not in bundle.scenarios:
        raise KeyError(f"Scenario {scenario_id!r} not found in template.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = {
        "scenario_1_heavy_energy": _scenario_1(bundle, scenario_id),
        "scenario_2_empty_dispatch": _scenario_2(bundle, scenario_id),
        "scenario_3_coordination": _scenario_3(bundle, scenario_id),
    }
    scenario_4 = scenario_4_status()

    file_map = {
        "scenario_1_heavy_energy": "scenario_1_heavy_energy.csv",
        "scenario_2_empty_dispatch": "scenario_2_empty_dispatch.csv",
        "scenario_3_coordination": "scenario_3_coordination.csv",
    }
    for key, filename in file_map.items():
        _write_csv(output_dir / filename, _scenario_rows(scenarios[key]))

    (output_dir / "scenario_4_special_section_status.json").write_text(
        json.dumps(scenario_4, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "technical_clause": TECHNICAL_CLAUSE,
        "template_scenario_id": scenario_id,
        "result_boundary": "prototype_level_not_official_energy_saving",
        "scenarios": {
            key: {
                "scenario_name": SCENARIO_NAMES[key],
                "baseline_label": SCENARIO_BASELINE_LABEL[key],
                "optimized_label": SCENARIO_OPTIMIZED_LABEL[key],
                "baseline": scenario["baseline"],
                "optimized": scenario["optimized"],
                "output": file_map[key],
            }
            for key, scenario in scenarios.items()
        },
        "scenario_4": scenario_4,
        "interpretation": _interpretation(scenarios),
        "output_files": {
            **file_map,
            "scenario_4_special_section_status": "scenario_4_special_section_status.json",
            "report": "VALIDATION_REPORT.md",
        },
    }
    (output_dir / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "VALIDATION_REPORT.md").write_text(
        _report_markdown(scenario_id, scenarios, scenario_4), encoding="utf-8"
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口：加载模板并执行四类验证场景。"""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--data-dir", type=Path, default=Path("data") / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scenario-id", default=DEFAULT_SCENARIO_ID)
    args = parser.parse_args(argv)

    bundle = load_he_input_template(args.template, real_data_dir=args.data_dir)
    summary = run_validation_suite(bundle, args.output_dir, scenario_id=args.scenario_id)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "scenarios": list(summary["scenarios"]),
                "scenario_4_status": summary["scenario_4"]["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
