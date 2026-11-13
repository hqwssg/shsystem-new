# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from energy_settlement import EnergySettlementSystem
from rolling_optimizer import (
    GeneratedSchedule,
    RollingOptimizer,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    batch_evaluate_templates,
    build_power_series,
    candidate_templates,
    default_scenarios,
    generate_schedule,
    robust_evaluate_schedule,
)
from run_ablation_experiments import result_row, write_csv
from scheduler_nsga2 import PowerSeriesCache, build_power_cache
from train_simulator import BatteryStorageParameters, load_config


OUTPUT_DIR = Path("outputs") / "engineering_solver"


def engineering_system(
    battery: BatteryStorageParameters,
    route,
    *,
    settlement_time_step_s: int = 30,
) -> EnergySettlementSystem:
    """Create an MPC settlement system with engineering penalties enabled."""

    return EnergySettlementSystem(
        battery,
        route.energy_transfer_ranges_km,
        settlement_time_step_s=settlement_time_step_s,
        initial_soc_kwh=5_000.0,
        target_final_soc_kwh=5_000.0,
        final_soc_tolerance_kwh=1_000.0,
        final_soc_penalty_per_kwh=1.0,
        wasted_energy_penalty_per_kwh=0.03,
        allow_direct_use=False,
        allow_storage=True,
    )


def economic_system(
    battery: BatteryStorageParameters,
    route,
    *,
    settlement_time_step_s: int = 30,
) -> EnergySettlementSystem:
    """函数 economic_system：执行该模块中的相关处理逻辑。"""
    return EnergySettlementSystem(
        battery,
        route.energy_transfer_ranges_km,
        settlement_time_step_s=settlement_time_step_s,
        allow_direct_use=False,
        allow_storage=True,
    )


def power_series_for_schedule(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    sample_step_s: int,
):
    """函数 power_series_for_schedule：执行该模块中的相关处理逻辑。"""
    series = build_power_series(
        heavy_cache,
        schedule.heavy_departures_s,
        sample_step_s=sample_step_s,
    )
    series.extend(
        build_power_series(
            empty_cache,
            schedule.empty_departures_s,
            sample_step_s=sample_step_s,
            storage_hold_s=schedule.template.flex_zone_hold_s,
        )
    )
    return series


def settle_schedule(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    system: EnergySettlementSystem,
):
    """函数 settle_schedule：执行该模块中的相关处理逻辑。"""
    return system.settle(
        power_series_for_schedule(
            schedule,
            heavy_cache,
            empty_cache,
            sample_step_s=system.settlement_time_step_s,
        )
    )


def score_schedule(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    system: EnergySettlementSystem,
    route,
) -> ScheduleScore:
    """函数 score_schedule：执行该模块中的相关处理逻辑。"""
    return robust_evaluate_schedule(
        schedule,
        default_scenarios(),
        heavy_cache,
        empty_cache,
        system,
        route.signaling_system,
    )


def optimize_with_system(
    template: ScheduleTemplate,
    system: EnergySettlementSystem,
    route,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    horizon_s: int,
    execute_window_s: int,
    search_config: TemplateSearchConfig,
) -> Tuple[GeneratedSchedule, ScheduleScore, float]:
    """函数 optimize_with_system：执行该模块中的相关处理逻辑。"""
    optimizer = RollingOptimizer(route, heavy_cache, empty_cache, system)
    start = time.perf_counter()
    result = optimizer.optimize_once(
        RollingWindowState(0, [], []),
        template,
        horizon_s=horizon_s,
        execute_window_s=execute_window_s,
        search_config=search_config,
    )
    elapsed_s = time.perf_counter() - start
    return result.schedule, result.score, elapsed_s


def schedule_row(
    experiment: str,
    schedule: GeneratedSchedule,
    score: ScheduleScore,
    settlement,
    battery: BatteryStorageParameters,
    runtime_s: float,
    horizon_s: int,
    search_config: TemplateSearchConfig,
) -> Dict[str, object]:
    """函数 schedule_row：执行该模块中的相关处理逻辑。"""
    row = result_row(experiment, schedule, score, settlement, battery)
    row.update(
        {
            "runtime_s": round(runtime_s, 3),
            "horizon_s": horizon_s,
            "total_departures": len(schedule.heavy_departures_s) + len(schedule.empty_departures_s),
            "search_method": search_config.method,
            "population_size": search_config.population_size,
            "generations": search_config.generations,
            "parallel_workers": search_config.parallel_workers,
        }
    )
    return row


def run_soc_waste_penalty_experiment(
    route,
    battery: BatteryStorageParameters,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> List[Dict[str, object]]:
    """函数 run_soc_waste_penalty_experiment：执行该模块中的相关处理逻辑。"""
    template = ScheduleTemplate(900, 900, 420, heavy_count=12, empty_count=12)
    horizon_s = 10_800
    search_config = TemplateSearchConfig(
        method="nsga2",
        population_size=12,
        generations=3,
        elite_count=4,
        parallel_workers=2,
        seed=11,
    )

    systems = {
        "economic_cost_only": economic_system(battery, route, settlement_time_step_s=30),
        "engineering_soc_waste_penalty": engineering_system(battery, route, settlement_time_step_s=30),
    }

    rows: List[Dict[str, object]] = []
    for experiment, system in systems.items():
        schedule, score, runtime_s = optimize_with_system(
            template,
            system,
            route,
            heavy_cache,
            empty_cache,
            horizon_s=horizon_s,
            execute_window_s=1_800,
            search_config=search_config,
        )
        settlement = settle_schedule(schedule, heavy_cache, empty_cache, system)
        rows.append(
            schedule_row(
                experiment,
                schedule,
                score,
                settlement,
                battery,
                runtime_s,
                horizon_s,
                search_config,
            )
        )
    return rows


def run_large_window_stress_experiment(
    route,
    battery: BatteryStorageParameters,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> List[Dict[str, object]]:
    """函数 run_large_window_stress_experiment：执行该模块中的相关处理逻辑。"""
    template = ScheduleTemplate(960, 960, 480, heavy_count=18, empty_count=18)
    horizon_s = 16_200
    search_config = TemplateSearchConfig(
        method="nsga2",
        population_size=14,
        generations=3,
        elite_count=4,
        parallel_workers=2,
        seed=23,
    )
    system = engineering_system(battery, route, settlement_time_step_s=30)
    schedule, score, runtime_s = optimize_with_system(
        template,
        system,
        route,
        heavy_cache,
        empty_cache,
        horizon_s=horizon_s,
        execute_window_s=1_800,
        search_config=search_config,
    )
    settlement = settle_schedule(schedule, heavy_cache, empty_cache, system)
    return [
        schedule_row(
            "large_window_engineering_mpc",
            schedule,
            score,
            settlement,
            battery,
            runtime_s,
            horizon_s,
            search_config,
        )
    ]


def benchmark_batch_evaluation(
    route,
    battery: BatteryStorageParameters,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> List[Dict[str, object]]:
    """函数 benchmark_batch_evaluation：执行该模块中的相关处理逻辑。"""
    template = ScheduleTemplate(900, 900, 420, heavy_count=10, empty_count=10)
    templates = candidate_templates(
        template,
        headway_offsets_s=(-120, 0, 120),
        phase_offsets_s=(-180, 0, 180),
        hold_options_s=(0, 120),
    )
    system = engineering_system(battery, route, settlement_time_step_s=30)

    def evaluate_template(item: ScheduleTemplate) -> ScheduleScore:
        """函数 evaluate_template：执行该模块中的相关处理逻辑。"""
        return score_schedule(generate_schedule(item), heavy_cache, empty_cache, system, route)

    rows: List[Dict[str, object]] = []
    reference_scores: List[ScheduleScore] | None = None
    for workers in [1, 2, 4]:
        start = time.perf_counter()
        evaluated = batch_evaluate_templates(templates, evaluate_template, max_workers=workers)
        elapsed_s = time.perf_counter() - start
        scores = [score for _template, score in evaluated]
        if reference_scores is None:
            reference_scores = scores
            max_cost_diff = 0.0
        else:
            max_cost_diff = max(
                abs(score.total_cost - ref.total_cost)
                for score, ref in zip(scores, reference_scores)
            )
        feasible_count = sum(1 for score in scores if score.feasible)
        rows.append(
            {
                "workers": workers,
                "candidate_count": len(templates),
                "runtime_s": round(elapsed_s, 3),
                "feasible_count": feasible_count,
                "max_cost_diff_vs_single_worker": round(max_cost_diff, 6),
                "best_cost": round(min(score.total_cost for score in scores), 3),
                "best_worst_case_cost": round(min(score.worst_case_cost for score in scores), 3),
            }
        )
    return rows


def plot_engineering_cost(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_engineering_cost：执行该模块中的相关处理逻辑。"""
    labels = [str(row["experiment"]) for row in rows]
    total_cost = [float(row["settlement_total_cost"]) for row in rows]
    grid = [float(row["grid_kwh"]) for row in rows]
    wasted = [float(row["wasted_kwh"]) for row in rows]

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axes[0].bar(labels, total_cost, color="#4c78a8")
    axes[0].set_ylabel("Total cost")
    axes[1].bar(labels, grid, color="#f58518")
    axes[1].set_ylabel("Grid kWh")
    axes[2].bar(labels, wasted, color="#b279a2")
    axes[2].set_ylabel("Wasted kWh")
    axes[2].tick_params(axis="x", rotation=15)
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Engineering Cost and Energy Comparison")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_batch_benchmark(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_batch_benchmark：执行该模块中的相关处理逻辑。"""
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.5))
    ax.bar([str(row["workers"]) for row in rows], [float(row["runtime_s"]) for row in rows], color="#59a14f")
    ax.set_xlabel("Parallel workers")
    ax.set_ylabel("Runtime (s)")
    ax.set_title("Batch Candidate Evaluation Benchmark")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def write_report(
    engineering_rows: List[Dict[str, object]],
    large_window_rows: List[Dict[str, object]],
    batch_rows: List[Dict[str, object]],
    output_path: Path,
) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    large = large_window_rows[0]
    best_batch = min(batch_rows, key=lambda row: float(row["runtime_s"]))
    report = f"""# 工程化求解能力实验报告

## 1. 本轮增强

- 储能结算支持初始 SOC、日终目标 SOC、SOC 偏差惩罚。
- 能量结算支持弃电惩罚，避免优化器只因储能折旧成本而偏向弃电。
- 低维模板搜索支持批量候选评估和 `parallel_workers` 并行参数。
- 新增 18 对重/空列车的大窗口 MPC 压力测试。

## 2. SOC 与弃电惩罚

`engineering_solver_comparison.csv` 对比了纯经济成本优化和工程约束成本优化。工程约束成本口径会把弃电惩罚与日终 SOC 偏差纳入 `settlement_total_cost`。

## 3. 大窗口 MPC 压力测试

- 测试场景：18 趟重车 + 18 趟空车的模板，统计窗口内实际纳入 {large['total_departures']} 趟发车
- 规划窗口：{large['horizon_s']} s
- 搜索方法：{large['search_method']}
- 种群规模：{large['population_size']}
- 代数：{large['generations']}
- 并行 worker：{large['parallel_workers']}
- 运行时间：{large['runtime_s']} s
- 可行性：{large['feasible']}
- 总发车数：{large['total_departures']}

## 4. 候选批量评估

`batch_evaluation_benchmark.csv` 比较了不同 worker 数下的候选模板评估耗时。最快配置为 `{best_batch['workers']}` 个 worker，耗时 `{best_batch['runtime_s']}` s。`max_cost_diff_vs_single_worker` 用于确认并行评估没有改变目标函数结果。

如果多 worker 未带来明显提速，说明当前瓶颈仍主要在 Python 层闭塞检查和结算循环；后续可继续向进程池、NumPy 向量化或 Numba/C 扩展推进。

## 5. 输出图表

- `engineering_cost_comparison.png`
- `batch_evaluation_benchmark.png`
"""
    output_path.write_text(report, encoding="utf-8")


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    route, trains, battery = load_config(Path("sandbox_config.json"))
    heavy_cache = build_power_cache(trains["Heavy"], route)
    empty_cache = build_power_cache(trains["Empty"], route)

    engineering_rows = run_soc_waste_penalty_experiment(route, battery, heavy_cache, empty_cache)
    large_window_rows = run_large_window_stress_experiment(route, battery, heavy_cache, empty_cache)
    batch_rows = benchmark_batch_evaluation(route, battery, heavy_cache, empty_cache)

    assert all(row["feasible"] for row in engineering_rows)
    assert large_window_rows[0]["feasible"]
    assert all(float(row["max_cost_diff_vs_single_worker"]) == 0.0 for row in batch_rows)

    write_csv(engineering_rows, OUTPUT_DIR / "engineering_solver_comparison.csv")
    write_csv(large_window_rows, OUTPUT_DIR / "large_window_mpc_stress.csv")
    write_csv(batch_rows, OUTPUT_DIR / "batch_evaluation_benchmark.csv")

    summary = {
        "engineering_solver_comparison": engineering_rows,
        "large_window_mpc_stress": large_window_rows,
        "batch_evaluation_benchmark": batch_rows,
    }
    (OUTPUT_DIR / "engineering_solver_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    plot_engineering_cost(engineering_rows + large_window_rows, OUTPUT_DIR / "engineering_cost_comparison.png")
    plot_batch_benchmark(batch_rows, OUTPUT_DIR / "batch_evaluation_benchmark.png")
    write_report(
        engineering_rows,
        large_window_rows,
        batch_rows,
        OUTPUT_DIR / "ENGINEERING_SOLVER_REPORT.md",
    )

    large = large_window_rows[0]
    print("=== Engineering Solver Experiment Summary ===")
    print("Output directory:", OUTPUT_DIR.resolve())
    print("SOC/waste rows:", len(engineering_rows))
    print("Large-window feasible:", large["feasible"])
    print("Large-window total departures:", large["total_departures"])
    print("Large-window runtime_s:", large["runtime_s"])
    print("Batch benchmark rows:", len(batch_rows))


if __name__ == "__main__":
    main()
