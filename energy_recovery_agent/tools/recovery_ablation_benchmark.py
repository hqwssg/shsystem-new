"""执行恢复级联关闭/开启的同口径多轮滚动对照实验。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
import argparse
import csv
import json
import math

from tools.synthetic_rolling_rescheduling_benchmark import (
    DEFAULT_DATA_DIR,
    DEFAULT_DELAYS,
    run_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E15_recovery_ablation"
STRUCTURAL_GATES = (
    "all_cycles_completed",
    "observation_sequence_applied",
    "observations_reach_scenario_evaluation",
    "soc_continuity",
    "locked_history_monotonic",
    "realized_departures_committed_to_next_cycle",
    "execution_state_matches_observed_delays",
    "energy_window_moves_with_cycle",
    "feasible_cycles_have_executable_service",
    "infeasible_new_decisions_withheld_unless_experimental",
    "settlement_uses_committed_schedule",
    "soc_within_physical_bounds",
    "conflict_chains_fully_classified",
    "infeasible_cycles_have_extracted_conflicts",
)


def _sum_cycles(summary: dict[str, Any], field: str) -> float:
    """汇总不重叠执行时间片指标。"""

    return sum(float(row.get(field, 0.0)) for row in summary["cycles"])


def _case_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    """提取可直接比较且不会重复计算预测窗口的指标。"""

    cycles = summary["cycles"]
    return {
        "robust_feasible_cycle_count": int(summary["robust_feasible_cycle_count"]),
        "robust_infeasible_cycle_count": int(summary["robust_infeasible_cycle_count"]),
        "total_resource_conflict_count": sum(
            int(row["resource_conflict_count"]) for row in cycles
        ),
        "total_core_scenario_conflict_count": sum(
            int(row["recovery_conflict_count"]) for row in cycles
        ),
        "total_constraint_violation": _sum_cycles(summary, "constraint_violation"),
        "recovery_triggered_cycle_count": int(
            summary["recovery_repair_triggered_cycle_count"]
        ) + int(summary["exact_recovery_solver_triggered_cycle_count"]),
        "recovery_adopted_cycle_count": int(
            summary["recovery_repair_adopted_cycle_count"]
        ) + int(summary["exact_recovery_adopted_cycle_count"]),
        "total_recovery_adjustment_s": sum(
            int(row["recovery_repair_total_adjustment_s"]) for row in cycles
        ),
        "executed_grid_kwh": _sum_cycles(summary, "executed_grid_kwh"),
        "executed_wasted_kwh": _sum_cycles(summary, "executed_wasted_kwh"),
        "executed_charge_kwh": _sum_cycles(summary, "executed_charge_kwh"),
        "executed_discharge_kwh": _sum_cycles(summary, "executed_discharge_kwh"),
        "final_soc_kwh": float(cycles[-1]["executed_final_soc_kwh"]),
        "wall_time_s": float(summary["wall_time_s"]),
    }


def compare_summaries(
    without_recovery: dict[str, Any],
    with_recovery: dict[str, Any],
) -> dict[str, Any]:
    """在相同外生输入下形成恢复机制消融比较。"""

    if len(without_recovery.get("cycles", [])) != len(with_recovery.get("cycles", [])):
        raise ValueError("两个对照分支的滚动周期数不一致。")
    no_metrics = _case_metrics(without_recovery)
    yes_metrics = _case_metrics(with_recovery)
    cycle_comparison = []
    recovered_cycle_indexes = []
    directly_repaired_cycle_indexes = []
    for no_row, yes_row in zip(without_recovery["cycles"], with_recovery["cycles"]):
        if int(no_row["cycle_index"]) != int(yes_row["cycle_index"]):
            raise ValueError("两个对照分支的周期编号不一致。")
        recovered = not bool(no_row["robust_feasible"]) and bool(
            yes_row["robust_feasible"]
        )
        if recovered:
            recovered_cycle_indexes.append(int(no_row["cycle_index"]))
        if recovered and bool(yes_row["recovery_repair_adopted"]):
            directly_repaired_cycle_indexes.append(int(no_row["cycle_index"]))
        cycle_comparison.append(
            {
                "cycle_index": int(no_row["cycle_index"]),
                "observed_heavy_delay_s": int(no_row["observed_heavy_delay_s"]),
                "observed_empty_delay_s": int(no_row["observed_empty_delay_s"]),
                "without_recovery_robust_feasible": bool(no_row["robust_feasible"]),
                "with_recovery_robust_feasible": bool(yes_row["robust_feasible"]),
                "recovered_by_cascade": recovered,
                "without_recovery_resource_conflicts": int(
                    no_row["resource_conflict_count"]
                ),
                "with_recovery_resource_conflicts": int(
                    yes_row["resource_conflict_count"]
                ),
                "without_recovery_core_scenario_conflicts": int(
                    no_row["recovery_conflict_count"]
                ),
                "with_recovery_core_scenario_conflicts": int(
                    yes_row["recovery_conflict_count"]
                ),
                "without_recovery_constraint_violation": float(
                    no_row["constraint_violation"]
                ),
                "with_recovery_constraint_violation": float(
                    yes_row["constraint_violation"]
                ),
                "recovery_status": yes_row["recovery_repair_status"],
                "recovery_adopted": bool(yes_row["recovery_repair_adopted"]),
                "recovery_adjustment_s": int(
                    yes_row["recovery_repair_total_adjustment_s"]
                ),
                "executed_grid_delta_kwh": float(yes_row["executed_grid_kwh"])
                - float(no_row["executed_grid_kwh"]),
                "executed_wasted_delta_kwh": float(yes_row["executed_wasted_kwh"])
                - float(no_row["executed_wasted_kwh"]),
            }
        )

    same_exogenous_inputs = all(
        without_recovery.get(key) == with_recovery.get(key)
        for key in (
            "cycle_count",
            "delay_sequence",
            "horizon_s",
            "execute_window_s",
            "storage_preset_id",
            "search_config",
            "allow_infeasible_commit_for_experiment",
        )
    )
    structural_gates_pass = all(
        bool(summary.get("gates", {}).get(gate))
        for summary in (without_recovery, with_recovery)
        for gate in STRUCTURAL_GATES
    )
    service_counts_match = all(
        int(no_row["executable_heavy_count"])
        == int(yes_row["executable_heavy_count"])
        and int(no_row["executable_empty_count"])
        == int(yes_row["executable_empty_count"])
        for no_row, yes_row in zip(
            without_recovery["cycles"], with_recovery["cycles"]
        )
    )
    finite_energy_metrics = all(
        math.isfinite(float(metrics[field]))
        for metrics in (no_metrics, yes_metrics)
        for field in (
            "executed_grid_kwh",
            "executed_wasted_kwh",
            "executed_charge_kwh",
            "executed_discharge_kwh",
            "final_soc_kwh",
        )
    )
    gates = {
        "same_exogenous_inputs": same_exogenous_inputs,
        "recovery_is_only_policy_difference": (
            without_recovery.get("recovery_enabled") is False
            and with_recovery.get("recovery_enabled") is True
            and without_recovery.get("allow_infeasible_commit_for_experiment") is True
            and with_recovery.get("allow_infeasible_commit_for_experiment") is True
        ),
        "both_runs_structurally_valid": structural_gates_pass,
        "without_recovery_layers_not_triggered": (
            no_metrics["recovery_triggered_cycle_count"] == 0
            and no_metrics["recovery_adopted_cycle_count"] == 0
        ),
        "with_recovery_layer_exercised": (
            yes_metrics["recovery_triggered_cycle_count"] > 0
            and yes_metrics["recovery_adopted_cycle_count"] > 0
        ),
        "recovery_does_not_reduce_robust_feasible_cycles": (
            yes_metrics["robust_feasible_cycle_count"]
            >= no_metrics["robust_feasible_cycle_count"]
        ),
        "at_least_one_cycle_recovered": bool(recovered_cycle_indexes),
        "recovery_reduces_conflicts_or_violation": (
            yes_metrics["total_core_scenario_conflict_count"]
            < no_metrics["total_core_scenario_conflict_count"]
            or yes_metrics["total_constraint_violation"]
            < no_metrics["total_constraint_violation"]
        ),
        "submitted_service_counts_match": service_counts_match,
        "energy_accounting_complete": finite_energy_metrics,
    }
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "completed",
        "data_status": with_recovery.get("data_status"),
        "comparison_design": {
            "control": "同一常规搜索、扰动、初始SOC、随机种子和预算，关闭局部及精确恢复级联",
            "treatment": "同一配置，开启局部及精确恢复级联",
            "energy_scope": "仅累计互不重叠的实际执行时间片，不累计重叠预测窗口",
        },
        "without_recovery": no_metrics,
        "with_recovery": yes_metrics,
        "delta_with_minus_without": {
            key: float(yes_metrics[key]) - float(no_metrics[key])
            for key in (
                "robust_feasible_cycle_count",
                "robust_infeasible_cycle_count",
                "total_resource_conflict_count",
                "total_core_scenario_conflict_count",
                "total_constraint_violation",
                "executed_grid_kwh",
                "executed_wasted_kwh",
                "executed_charge_kwh",
                "executed_discharge_kwh",
                "final_soc_kwh",
                "wall_time_s",
            )
        },
        "recovered_cycle_indexes": recovered_cycle_indexes,
        "recovered_cycle_numbers": [index + 1 for index in recovered_cycle_indexes],
        "directly_repaired_cycle_indexes": directly_repaired_cycle_indexes,
        "downstream_prevented_infeasible_cycle_indexes": [
            index
            for index in recovered_cycle_indexes
            if index not in directly_repaired_cycle_indexes
        ],
        "cycles": cycle_comparison,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "limitations": [
            "当前结论只适用于固定合成扰动和规划/工程占位参数。",
            "单次固定种子对照用于机制验证，不构成统计显著性或现场节能结论。",
            "能量差包含运行图变化造成的SOC路径差异，正式论文需在真实数据上增加多扰动、多种子统计。",
            "控制组第2至4轮不是核心稳健可行方案，因此当前能量差不能解释为同等可行方案之间的节能收益。",
            "关闭恢复分支会继续提交其明确标记为不可行的回退方案，仅用于观察连锁影响，不应作为现场执行策略。",
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    no = summary["without_recovery"]
    yes = summary["with_recovery"]
    delta = summary["delta_with_minus_without"]
    direct_numbers = "、".join(
        str(index + 1) for index in summary["directly_repaired_cycle_indexes"]
    ) or "无"
    downstream_numbers = "、".join(
        str(index + 1)
        for index in summary["downstream_prevented_infeasible_cycle_indexes"]
    ) or "无"
    lines = [
        "# 扰动恢复第五阶段：恢复机制消融对照实验",
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "## 结论",
        "",
        f"- 综合门禁：`{summary['all_gates_passed']}`。",
        f"- 开启恢复后，核心稳健可行轮次由 `{no['robust_feasible_cycle_count']}` 提升到 `{yes['robust_feasible_cycle_count']}`，恢复的轮次为 `{summary['recovered_cycle_numbers']}`。",
        f"- 第 `{direct_numbers}` 轮由恢复器直接修复；第 `{downstream_numbers}` 轮是前序修复避免的连锁不可行。",
        f"- 全部核心场景累计冲突由 `{no['total_core_scenario_conflict_count']}` 降至 `{yes['total_core_scenario_conflict_count']}`；其中正常场景冲突由 `{no['total_resource_conflict_count']}` 降至 `{yes['total_resource_conflict_count']}`，所选结果记录的累计约束违反量变化为 `{delta['total_constraint_violation']:.6f}`。",
        f"- 恢复级联触发/采用 `{yes['recovery_triggered_cycle_count']}/{yes['recovery_adopted_cycle_count']}` 轮，累计绝对调整 `{yes['total_recovery_adjustment_s']}` 秒。",
        f"- 实际执行片段购电量变化 `{delta['executed_grid_kwh']:.6f} kWh`，弃电量变化 `{delta['executed_wasted_kwh']:.6f} kWh`，末端SOC变化 `{delta['final_soc_kwh']:.6f} kWh`。控制组后3轮不可行，因此能量差只用于追踪机制影响，不是同等可行方案间的节能收益，也不单独作为恢复采用条件。",
        "",
        "## 逐轮对照",
        "",
        "| 轮次 | 重/空晚点(s) | 关闭恢复可行 | 开启恢复可行 | 被恢复 | 核心场景冲突(关/开) | 违反量(关/开) | 修复状态 | 调整(s) |",
        "| ---: | ---: | :---: | :---: | :---: | ---: | ---: | --- | ---: |",
    ]
    for row in summary["cycles"]:
        lines.append(
            f"| {row['cycle_index'] + 1} | {row['observed_heavy_delay_s']}/{row['observed_empty_delay_s']} | "
            f"{row['without_recovery_robust_feasible']} | {row['with_recovery_robust_feasible']} | "
            f"{row['recovered_by_cascade']} | {row['without_recovery_core_scenario_conflicts']}/{row['with_recovery_core_scenario_conflicts']} | "
            f"{row['without_recovery_constraint_violation']:.6f}/{row['with_recovery_constraint_violation']:.6f} | "
            f"{row['recovery_status']} | {row['recovery_adjustment_s']} |"
        )
    lines.extend([
        "",
        "## 公平性与验收门禁",
        "",
        *[f"- `{key}`：`{value}`" for key, value in summary["gates"].items()],
        "",
        "## 结果边界",
        "",
        *[f"- {item}" for item in summary["limitations"]],
        "",
        "完整分支产物分别位于 `without_recovery/` 和 `with_recovery/`。",
    ])
    (output_dir / "RECOVERY_ABLATION_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_ablation(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    delays: Sequence[tuple[int, int]] = DEFAULT_DELAYS,
    population_size: int = 2,
    generations: int = 1,
    seed: int = 20260907,
) -> dict[str, Any]:
    """依次运行控制组和恢复组并写出对照结果。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    without_recovery = run_benchmark(
        data_dir=data_dir,
        output_dir=output_dir / "without_recovery",
        delays=delays,
        population_size=population_size,
        generations=generations,
        seed=seed,
        enable_recovery=False,
        allow_infeasible_commit_for_experiment=True,
    )
    with_recovery = run_benchmark(
        data_dir=data_dir,
        output_dir=output_dir / "with_recovery",
        delays=delays,
        population_size=population_size,
        generations=generations,
        seed=seed,
        enable_recovery=True,
        allow_infeasible_commit_for_experiment=True,
    )
    summary = compare_summaries(without_recovery, with_recovery)
    _write_csv(output_dir / "cycle_comparison.csv", summary["cycles"])
    (output_dir / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(summary, output_dir)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--population-size", type=int, default=2)
    parser.add_argument("--generations", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260907)
    args = parser.parse_args(argv)
    summary = run_ablation(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        population_size=args.population_size,
        generations=args.generations,
        seed=args.seed,
    )
    print(json.dumps({
        "status": summary["status"],
        "all_gates_passed": summary["all_gates_passed"],
        "recovered_cycle_indexes": summary["recovered_cycle_indexes"],
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["all_gates_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
