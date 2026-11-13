"""执行参数区间与运行扰动的联合稳健性评价。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Sequence
import argparse
import csv
import json
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joint_parameter_robustness import (
    apply_battery_factors,
    apply_electrical_factors,
    apply_train_factors,
    build_joint_parameter_scenarios,
    config_sha256,
    load_joint_range_config,
    scenario_parameter_rows,
)
from rolling_optimizer import ScheduleTemplate, default_scenarios, generate_schedule, robust_evaluate_schedule
from run_dispatch_case import effective_min_depart_gap_s, load_case_inputs, make_settlement_system
from scheduler_nsga2 import build_power_cache


DEFAULT_CONFIG = ROOT / "data_templates" / "joint_parameter_ranges_template.json"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E13_joint_parameter_robustness"


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """写出 UTF-8 BOM CSV。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _semantic_sha256(rows: Sequence[dict[str, Any]]) -> str:
    """计算不含耗时和路径的结果摘要。"""

    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    """生成中文联合稳健性评价报告。"""

    counts = summary["coverage"]
    outcome = summary["outcome"]
    limiting = outcome.get("limiting_combination") or {}
    lines = [
        "# 参数区间联合稳健性评价报告",
        "",
        "## 评价结论",
        "",
        f"- 已测试核心联合场景稳健：`{str(outcome['tested_joint_robust']).lower()}`；",
        f"- 核心场景可行组合：`{outcome['core_feasible_combination_count']}/{counts['core_combination_count']}`；",
        f"- 全部运行扰动均可行组合：`{outcome['fully_feasible_combination_count']}/{counts['combination_count']}`；",
        f"- 最差组合：参数场景 `{limiting.get('parameter_scenario_id', '')}` + 运行扰动 `{limiting.get('disturbance_scenario', '')}`，约束违反量 `{limiting.get('constraint_violation', 0)}`。",
        "",
        "这里的“稳健”仅表示本次生成并实际计算的离散核心联合场景全部通过；非核心压力场景另行报告。它不代表对连续参数盒的数学证明。正式参数及误差分布到位后，应更新区间合同并重新运行。",
        "",
        "## 覆盖范围",
        "",
        f"- 参数维数：`{counts['parameter_dimension_count']}`；物理参数场景：`{counts['parameter_scenario_count']}`；",
        f"- 运行扰动：`{counts['disturbance_scenario_count']}`；联合组合：`{counts['combination_count']}`；",
        "- 设计：名义值、定向不利/有利角点、全低/全高角点、单参数上下边界、固定种子拉丁超立方内部样本。",
        "",
        "## 关键结果",
        "",
        f"- 最大购电量：`{outcome['max_grid_kwh']:.6f} kWh`；",
        f"- 最大弃能量：`{outcome['max_wasted_kwh']:.6f} kWh`；",
        f"- 最大电气约束违反量：`{outcome['max_electrical_constraint_violation_kwh']:.6f} kWh`；",
        f"- 最大资源冲突数：`{outcome['max_resource_conflict_count']}`。",
        "",
        "## 分扰动结果",
        "",
        "| 运行扰动 | 核心场景 | 可行/总数 |",
        "| --- | --- | ---: |",
    ]
    for row in summary["disturbance_outcomes"]:
        lines.append(
            f"| `{row['disturbance_scenario']}` | {str(row['core_for_feasibility']).lower()} | "
            f"{row['feasible_count']}/{row['combination_count']} |"
        )
    lines.extend([
        "",
        "## 输出文件",
        "",
        "- `joint_parameter_scenarios.csv`：每个物理场景的区间和实际因子；",
        "- `joint_robustness_results.csv`：每个物理参数场景与运行扰动组合的详细结果；",
        "- `joint_robustness_summary.json`：机器可读覆盖率、结论、最差组合和追溯信息。",
    ])
    (output_dir / "JOINT_PARAMETER_ROBUSTNESS_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_benchmark(
    *,
    data_dir: Path,
    parameter_ranges: Path,
    output_dir: Path,
    heavy_count: int = 2,
    empty_count: int = 2,
    heavy_headway_s: int = 3300,
    empty_headway_s: int = 3300,
    phase_s: int = 840,
    settlement_step_s: int = 10,
) -> dict[str, Any]:
    """对固定运行图执行物理参数区间与运行扰动联合评价。"""

    if min(heavy_count, empty_count, heavy_headway_s, empty_headway_s, settlement_step_s) <= 0:
        raise ValueError("列车数、追踪间隔和结算步长必须为正数。")
    if phase_s < 0:
        raise ValueError("相位必须是非负数。")
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    config = load_joint_range_config(parameter_ranges)
    parameter_scenarios = build_joint_parameter_scenarios(config)
    disturbance_scenarios = list(default_scenarios())
    case_inputs = load_case_inputs(data_dir, output_dir / "data_validation")
    schedule = generate_schedule(ScheduleTemplate(
        heavy_headway_s=heavy_headway_s,
        empty_headway_s=empty_headway_s,
        heavy_empty_phase_s=phase_s,
        heavy_count=heavy_count,
        empty_count=empty_count,
    ))
    min_gap = effective_min_depart_gap_s(900, case_inputs.resource_model)
    result_rows: list[dict[str, Any]] = []

    for parameter_scenario in parameter_scenarios:
        factors = parameter_scenario.factors
        trains = apply_train_factors(case_inputs.trains, factors)
        battery = apply_battery_factors(case_inputs.battery, factors)
        electrical_limits = apply_electrical_factors(case_inputs.power_arm_limits, factors)
        heavy_cache = build_power_cache(
            trains["Heavy"], case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        empty_cache = build_power_cache(
            trains["Empty"], case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        settlement = make_settlement_system(
            battery, case_inputs.route, settlement_step_s,
            None, None, 0.0, 0.0, 0.05, "storage_no_direct", electrical_limits,
        )
        scenario_scores: list[Any] = []
        robust_score = robust_evaluate_schedule(
            schedule,
            disturbance_scenarios,
            heavy_cache,
            empty_cache,
            settlement,
            case_inputs.route.signaling_system,
            resource_model=case_inputs.resource_model,
            storage_sections=case_inputs.storage_sections,
            min_depart_gap_s=min_gap,
            target_gap_s=int(round((heavy_headway_s + empty_headway_s) / 2.0)),
            scenario_score_sink=scenario_scores,
        )
        for disturbance, score in scenario_scores:
            result_rows.append({
                "parameter_scenario_id": parameter_scenario.scenario_id,
                "parameter_design_role": parameter_scenario.design_role,
                "disturbance_scenario": disturbance.name,
                "core_for_feasibility": disturbance.core_for_feasibility,
                "feasible": score.feasible,
                "parameter_scenario_core_robust_feasible": robust_score.feasible,
                "constraint_violation": round(float(score.constraint_violation), 9),
                "resource_conflict_count": score.resource_conflict_count,
                "flow_continuity_violation_count": score.flow_continuity_violation_count,
                "electrical_constraint_violation_kwh": round(float(score.electrical_constraint_violation_kwh), 9),
                "traction_supply_excess_kwh": round(float(score.traction_supply_excess_kwh), 9),
                "regen_absorption_excess_kwh": round(float(score.regen_absorption_excess_kwh), 9),
                "grid_kwh": round(float(score.grid_kwh), 9),
                "wasted_kwh": round(float(score.wasted_kwh), 9),
                "battery_charge_kwh": round(float(score.battery_charge_kwh), 9),
                "battery_discharge_kwh": round(float(score.battery_discharge_kwh), 9),
                "final_soc_kwh": round(float(score.final_soc_kwh), 9),
                "final_soc_deviation_kwh": round(float(score.final_soc_deviation_kwh), 9),
                "total_cost": round(float(score.total_cost), 9),
            })

    core_rows = [row for row in result_rows if row["core_for_feasibility"]]
    limiting = max(
        result_rows,
        key=lambda row: (
            float(row["constraint_violation"]),
            int(row["resource_conflict_count"]),
            float(row["grid_kwh"]),
        ),
    )
    all_core_feasible = all(bool(row["feasible"]) for row in core_rows)
    disturbance_outcomes = []
    for disturbance in disturbance_scenarios:
        rows = [row for row in result_rows if row["disturbance_scenario"] == disturbance.name]
        disturbance_outcomes.append({
            "disturbance_scenario": disturbance.name,
            "core_for_feasibility": disturbance.core_for_feasibility,
            "combination_count": len(rows),
            "feasible_count": sum(bool(row["feasible"]) for row in rows),
            "infeasible_count": sum(not bool(row["feasible"]) for row in rows),
        })
    parameter_scenario_outcomes = []
    for parameter_scenario in parameter_scenarios:
        rows = [
            row for row in result_rows
            if row["parameter_scenario_id"] == parameter_scenario.scenario_id
        ]
        core = [row for row in rows if row["core_for_feasibility"]]
        parameter_scenario_outcomes.append({
            "parameter_scenario_id": parameter_scenario.scenario_id,
            "parameter_design_role": parameter_scenario.design_role,
            "core_robust_feasible": all(bool(row["feasible"]) for row in core),
            "all_disturbances_feasible": all(bool(row["feasible"]) for row in rows),
            "feasible_disturbance_count": sum(bool(row["feasible"]) for row in rows),
            "disturbance_count": len(rows),
        })
    summary = {
        "schema_version": "1.0",
        "evaluation_code": config.evaluation_code,
        "data_status": config.data_status,
        "claim_scope": "tested_discrete_joint_scenarios_only",
        "continuous_interval_certified": False,
        "coverage": {
            "parameter_dimension_count": len(config.ranges),
            "parameter_scenario_count": len(parameter_scenarios),
            "disturbance_scenario_count": len(disturbance_scenarios),
            "combination_count": len(result_rows),
            "core_combination_count": len(core_rows),
            "interior_sample_count_requested": config.interior_sample_count,
            "sampling_seed": config.seed,
        },
        "schedule": {
            "heavy_count": heavy_count,
            "empty_count": empty_count,
            "heavy_headway_s": heavy_headway_s,
            "empty_headway_s": empty_headway_s,
            "phase_s": phase_s,
            "settlement_step_s": settlement_step_s,
        },
        "outcome": {
            "tested_joint_robust": all_core_feasible,
            "core_feasible_combination_count": sum(bool(row["feasible"]) for row in core_rows),
            "fully_feasible_combination_count": sum(bool(row["feasible"]) for row in result_rows),
            "max_constraint_violation": max(float(row["constraint_violation"]) for row in result_rows),
            "max_electrical_constraint_violation_kwh": max(float(row["electrical_constraint_violation_kwh"]) for row in result_rows),
            "max_resource_conflict_count": max(int(row["resource_conflict_count"]) for row in result_rows),
            "max_grid_kwh": max(float(row["grid_kwh"]) for row in result_rows),
            "max_wasted_kwh": max(float(row["wasted_kwh"]) for row in result_rows),
            "limiting_combination": limiting,
        },
        "disturbance_outcomes": disturbance_outcomes,
        "parameter_scenario_outcomes": parameter_scenario_outcomes,
        "optimization_decision": {
            "action": "keep_baseline" if all_core_feasible else "no_feasible_solution",
            "reason": (
                "tested_joint_scenarios_all_core_feasible"
                if all_core_feasible else "tested_joint_scenarios_include_core_infeasibility"
            ),
        },
        "provenance": {
            "parameter_ranges_path": str(parameter_ranges),
            "parameter_ranges_sha256": config_sha256(parameter_ranges),
            "source_kind": case_inputs.source_kind,
            "semantic_results_sha256": _semantic_sha256(result_rows),
        },
        "runtime": {"wall_time_s": round(time.perf_counter() - started, 6)},
    }
    _write_csv(output_dir / "joint_parameter_scenarios.csv", scenario_parameter_rows(parameter_scenarios, config))
    _write_csv(output_dir / "joint_robustness_results.csv", result_rows)
    (output_dir / "joint_robustness_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    _write_report(output_dir, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="参数区间与运行扰动联合稳健性评价")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "real_shuohuang")
    parser.add_argument("--parameter-ranges", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--heavy-count", type=int, default=2)
    parser.add_argument("--empty-count", type=int, default=2)
    parser.add_argument("--heavy-headway-s", type=int, default=3300)
    parser.add_argument("--empty-headway-s", type=int, default=3300)
    parser.add_argument("--phase-s", type=int, default=840)
    parser.add_argument("--settlement-step-s", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_benchmark(**vars(args))
    print(json.dumps({
        "tested_joint_robust": summary["outcome"]["tested_joint_robust"],
        "combination_count": summary["coverage"]["combination_count"],
        "summary": str(args.output_dir / "joint_robustness_summary.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
