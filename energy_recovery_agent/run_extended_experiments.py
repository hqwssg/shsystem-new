# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from energy_settlement import EnergySettlementSystem
from operating_conditions import OperatingConditions, adverse_weather_operating_conditions
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    ScheduleTemplate,
    ScheduleScore,
    TemplateSearchConfig,
    apply_scenario,
    build_power_series,
    default_scenarios,
    evaluate_schedule,
    generate_schedule,
    nsga2_template_search,
    pareto_template_front,
    robust_evaluate_schedule,
)
from run_ablation_experiments import (
    optimized_schedule,
    precise_settlement,
    result_row,
    write_csv,
)
from scheduler_nsga2 import PowerSeriesCache, build_power_cache, violates_signal_system
from train_simulator import BatteryStorageParameters, load_config


OUTPUT_DIR = Path("outputs") / "extended_experiments"


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


def run_timestep_experiment(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
) -> List[Dict[str, float | int]]:
    """函数 run_timestep_experiment：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, float | int]] = []
    reference_cost = None
    reference_grid = None
    reference_wasted = None

    for step_s in [1, 5, 10, 30, 60]:
        system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, settlement_time_step_s=step_s, allow_direct_use=False, allow_storage=True)
        start = time.perf_counter()
        settlement = system.settle(power_series_for_schedule(schedule, heavy_cache, empty_cache, step_s))
        elapsed_s = time.perf_counter() - start

        if reference_cost is None:
            reference_cost = settlement.total_cost
            reference_grid = settlement.grid_kwh
            reference_wasted = settlement.wasted_kwh

        rows.append(
            {
                "time_step_s": step_s,
                "runtime_s": round(elapsed_s, 5),
                "total_cost": round(settlement.total_cost, 3),
                "grid_kwh": round(settlement.grid_kwh, 3),
                "wasted_kwh": round(settlement.wasted_kwh, 3),
                "cost_error_pct_vs_1s": round((settlement.total_cost - reference_cost) / reference_cost * 100.0, 5),
                "grid_error_pct_vs_1s": round((settlement.grid_kwh - reference_grid) / reference_grid * 100.0, 5),
                "wasted_error_pct_vs_1s": round((settlement.wasted_kwh - reference_wasted) / reference_wasted * 100.0, 5),
            }
        )
    return rows


def run_robustness_experiment(
    schedules: Dict[str, GeneratedSchedule],
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
) -> List[Dict[str, object]]:
    """函数 run_robustness_experiment：执行该模块中的相关处理逻辑。"""
    scenarios = [
        DisturbanceScenario("normal"),
        DisturbanceScenario("heavy_delay_5min", heavy_delay_s=300),
        DisturbanceScenario("empty_delay_5min", empty_delay_s=300),
        DisturbanceScenario("both_delay_5min", heavy_delay_s=300, empty_delay_s=300),
        DisturbanceScenario("progressive_headway_stretch", heavy_headway_stretch_s=60, empty_headway_stretch_s=60),
        DisturbanceScenario("low_adhesion_weather_limit"),
    ]

    rows: List[Dict[str, object]] = []
    for schedule_name, schedule in schedules.items():
        for scenario in scenarios:
            disturbed_schedule = apply_scenario(schedule, scenario)
            scenario_route = route
            scenario_heavy_cache = heavy_cache
            scenario_empty_cache = empty_cache
            if scenario.name == "low_adhesion_weather_limit":
                if heavy_cache.train is None or empty_cache.train is None:
                    raise ValueError("Power cache is missing train metadata for physical weather scenarios.")
                scenario_route = replace(
                    route,
                    operating_conditions=_merge_operating_conditions(
                        route.operating_conditions,
                        adverse_weather_operating_conditions(),
                    ),
                )
                scenario_heavy_cache = _rebuild_cache_for_route(heavy_cache, scenario_route)
                scenario_empty_cache = _rebuild_cache_for_route(empty_cache, scenario_route)

            fast_system = EnergySettlementSystem(
                battery,
                scenario_route.energy_transfer_ranges_km,
                settlement_time_step_s=10,
                allow_direct_use=False,
                allow_storage=True,
            )
            score = evaluate_schedule(
                disturbed_schedule,
                scenario_heavy_cache,
                scenario_empty_cache,
                fast_system,
                scenario_route.signaling_system,
            )
            score = ScheduleScore(
                feasible=score.feasible,
                total_cost=score.total_cost * scenario.cost_multiplier,
                headway_deviation=score.headway_deviation,
                worst_case_cost=score.total_cost * scenario.cost_multiplier,
                worst_case_headway_deviation=score.headway_deviation,
                scenario_count=1,
            )
            settlement = precise_settlement(
                disturbed_schedule,
                scenario_heavy_cache,
                scenario_empty_cache,
                battery,
                scenario_route.energy_transfer_ranges_km,
            )
            row = result_row(
                f"{schedule_name}__{scenario.name}",
                disturbed_schedule,
                score,
                settlement,
                battery,
            )
            row["schedule_name"] = schedule_name
            row["scenario_name"] = scenario.name
            rows.append(row)
    return rows


def _rebuild_cache_for_route(cache: PowerSeriesCache, route) -> PowerSeriesCache:
    """Re-simulate a physical scenario without changing cache resolution or infrastructure."""

    if cache.train is None:
        raise ValueError("Power cache is missing train metadata for physical scenarios.")
    return build_power_cache(
        cache.train,
        route,
        simulation_step_s=cache.simulation_step_s,
        power_arm_interval_path=cache.power_arm_interval_path,
        storage_sections=cache.storage_sections,
    )


def _merge_operating_conditions(
    base: OperatingConditions,
    overlay: OperatingConditions,
) -> OperatingConditions:
    """Add an adverse scenario without discarding stricter infrastructure rules."""

    return OperatingConditions(
        default_adhesion_coefficient=min(
            base.default_adhesion_coefficient,
            overlay.default_adhesion_coefficient,
        ),
        traction_adhesion_safety_factor=min(
            base.traction_adhesion_safety_factor,
            overlay.traction_adhesion_safety_factor,
        ),
        braking_adhesion_safety_factor=min(
            base.braking_adhesion_safety_factor,
            overlay.braking_adhesion_safety_factor,
        ),
        weather_conditions=[*base.weather_conditions, *overlay.weather_conditions],
        adhesion_zones=[*base.adhesion_zones, *overlay.adhesion_zones],
        speed_restrictions=[*base.speed_restrictions, *overlay.speed_restrictions],
    )


def run_pareto_experiment(
    base_template: ScheduleTemplate,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """函数 run_pareto_experiment：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, settlement_time_step_s=10, allow_direct_use=False, allow_storage=True)
    scenarios = default_scenarios()

    def evaluate_template(template: ScheduleTemplate) -> ScheduleScore:
        """函数 evaluate_template：执行该模块中的相关处理逻辑。"""
        schedule = generate_schedule(template)
        return robust_evaluate_schedule(schedule, scenarios, heavy_cache, empty_cache, system, route.signaling_system)

    config = TemplateSearchConfig(method="nsga2", population_size=18, generations=5, elite_count=5, seed=7)
    ranked = nsga2_template_search(base_template, config, evaluate_template)
    front = pareto_template_front(ranked)

    def row_for(template: ScheduleTemplate, score: ScheduleScore, is_front: bool) -> Dict[str, object]:
        """函数 row_for：执行该模块中的相关处理逻辑。"""
        schedule = generate_schedule(template)
        settlement = precise_settlement(schedule, heavy_cache, empty_cache, battery, route.energy_transfer_ranges_km)
        return result_row("pareto_front" if is_front else "candidate", schedule, score, settlement, battery) | {
            "is_pareto_front": is_front,
        }

    candidate_rows = [row_for(template, score, False) for template, score in ranked]
    front_keys = {
        (template.heavy_headway_s, template.empty_headway_s, template.heavy_empty_phase_s, template.flex_zone_hold_s)
        for template, _score in front
    }
    front_rows = [
        row_for(template, score, True)
        for template, score in ranked
        if (template.heavy_headway_s, template.empty_headway_s, template.heavy_empty_phase_s, template.flex_zone_hold_s)
        in front_keys
    ]
    return candidate_rows, front_rows


def run_signaling_gap_experiment(
    route,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> List[Dict[str, object]]:
    """函数 run_signaling_gap_experiment：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    for cache_name, cache in [("heavy_forward", heavy_cache), ("empty_reverse", empty_cache)]:
        for mode in ["fixed_block", "moving_block", "hybrid"]:
            cfg = dict(route.signaling_system)
            cfg["mode"] = mode
            min_safe_gap = None
            for gap_s in range(60, 1801, 60):
                if not violates_signal_system([0, gap_s], cache, cfg):
                    min_safe_gap = gap_s
                    break
            rows.append(
                {
                    "train_type": cache_name,
                    "signaling_mode": mode,
                    "min_safe_departure_gap_s": min_safe_gap if min_safe_gap is not None else -1,
                    "min_safe_departure_gap_min": -1 if min_safe_gap is None else round(min_safe_gap / 60.0, 3),
                }
            )
    return rows


def plot_timestep(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_timestep：执行该模块中的相关处理逻辑。"""
    x = [int(row["time_step_s"]) for row in rows]
    runtime = [float(row["runtime_s"]) for row in rows]
    cost_error = [float(row["cost_error_pct_vs_1s"]) for row in rows]

    fig, ax1 = plt.subplots(1, 1, figsize=(9, 5))
    ax1.plot(x, runtime, marker="o", color="#4c78a8", label="Runtime")
    ax1.set_xlabel("Settlement time step (s)")
    ax1.set_ylabel("Runtime (s)")
    ax1.grid(True, alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, cost_error, marker="s", color="#e45756", label="Cost error vs 1s")
    ax2.set_ylabel("Cost error (%)")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="best")
    fig.suptitle("Settlement Time Step Accuracy and Runtime")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_robustness(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_robustness：执行该模块中的相关处理逻辑。"""
    scenarios = list(dict.fromkeys(str(row["scenario_name"]) for row in rows))
    schedule_names = list(dict.fromkeys(str(row["schedule_name"]) for row in rows))
    x = range(len(scenarios))
    width = 0.8 / len(schedule_names)

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    for idx, schedule_name in enumerate(schedule_names):
        values = [
            float(next(row for row in rows if row["schedule_name"] == schedule_name and row["scenario_name"] == scenario)["grid_kwh"])
            for scenario in scenarios
        ]
        offsets = [pos + idx * width for pos in x]
        ax.bar(offsets, values, width=width, label=schedule_name)
    ax.set_xticks([pos + width * (len(schedule_names) - 1) / 2 for pos in x])
    ax.set_xticklabels(scenarios, rotation=20, ha="right")
    ax.set_ylabel("Grid kWh")
    ax.set_title("Robustness Stress Test")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_pareto(candidates: List[Dict[str, object]], front: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_pareto：执行该模块中的相关处理逻辑。"""
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    ax.scatter(
        [float(row["grid_kwh"]) for row in candidates],
        [float(row["wasted_kwh"]) for row in candidates],
        s=35,
        color="#9ecae9",
        label="NSGA-II candidates",
    )
    ax.scatter(
        [float(row["grid_kwh"]) for row in front],
        [float(row["wasted_kwh"]) for row in front],
        s=55,
        color="#d62728",
        label="Pareto front",
    )
    ax.set_xlabel("Grid kWh")
    ax.set_ylabel("Wasted kWh")
    ax.set_title("Low-Dimensional NSGA-II Pareto Candidates")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_signaling_gap(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_signaling_gap：执行该模块中的相关处理逻辑。"""
    labels = [f"{row['train_type']}\n{row['signaling_mode']}" for row in rows]
    gaps = [float(row["min_safe_departure_gap_min"]) for row in rows]
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    ax.bar(labels, gaps, color="#59a14f")
    ax.set_ylabel("Minimum safe departure gap (min)")
    ax.set_title("Signal Mode Minimum Safe Gap")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def write_report(
    timestep_rows: List[Dict[str, object]],
    robustness_rows: List[Dict[str, object]],
    pareto_front_rows: List[Dict[str, object]],
    signaling_rows: List[Dict[str, object]],
    output_path: Path,
) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    best_timestep = min(timestep_rows, key=lambda row: float(row["runtime_s"]))
    max_cost_error = max(abs(float(row["cost_error_pct_vs_1s"])) for row in timestep_rows)
    best_pareto = min(pareto_front_rows, key=lambda row: float(row["energy_loss_kwh"]))

    report = f"""# 扩展实验报告

## 1. 实验范围

在已有消融实验和储能敏感性分析基础上，本轮补充了四类实验：

- 低维 NSGA-II 策略 Pareto 前沿
- 扰动鲁棒性压力测试
- 能量结算降采样精度与耗时测试
- 固定闭塞/移动闭塞/混合闭塞最小安全发车间隔测试

## 2. 降采样精度与耗时

本实验比较 `1s / 5s / 10s / 30s / 60s` 结算时间步长。

- 最快时间步长：{best_timestep['time_step_s']} s
- 最大成本误差：{max_cost_error:.5f}%

当前虚拟数据下，10s/30s 结算可以显著降低运行时间，但相对 1s 精确结算仍存在约 4%-5% 的成本偏差。它更适合作为滚动优化中的候选筛选口径，最终推荐方案仍建议使用 1s 精度复核。

## 3. 鲁棒性压力测试

扰动场景包括：

- 正常运行
- 重车晚点 5 分钟
- 空车晚点 5 分钟
- 重空车同时晚点 5 分钟
- 逐列车间隔拉伸
- 低黏着/雨天/临时限速物理场景

结果文件 `robustness_stress.csv` 给出了固定发车基准和完整优化方案在各场景下的购电、弃电和成本。

## 4. Pareto 前沿

本实验从低维 NSGA-II 生成的候选策略中提取非支配解。

当前 Pareto 前沿中综合能源损失最低的方案：

- 购电量：{best_pareto['grid_kwh']} kWh
- 弃电量：{best_pareto['wasted_kwh']} kWh
- 综合损失：{best_pareto['energy_loss_kwh']} kWh
- 重车间隔：{best_pareto['heavy_headway_s']} s
- 空车间隔：{best_pareto['empty_headway_s']} s
- 相位差：{best_pareto['phase_s']} s

## 5. 信号模式最小安全间隔

`signaling_gap_results.csv` 给出了重车正向和空车反向在不同闭塞模式下的最小安全发车间隔。混合闭塞取固定闭塞和移动闭塞中更保守的结果。

## 6. 输出图表

- `settlement_timestep_accuracy.png`
- `robustness_stress.png`
- `pareto_candidates.png`
- `signaling_min_gap.png`

## 7. 后续建议

1. 将 Pareto 前沿进一步扩展为经济成本、购电量、弃电量、发车偏差四目标展示。
2. 进一步用真实天气、限速命令和轮轨黏着统计替换当前虚拟物理场景参数。
3. 引入储能初始 SOC 和日终目标 SOC 约束。
4. 在真实闭塞分区和站场进路数据到位后，替换当前简化信号模型。
"""
    output_path.write_text(report, encoding="utf-8")


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    route, trains, battery = load_config(Path("sandbox_config.json"))
    heavy_cache = build_power_cache(trains["Heavy"], route)
    empty_cache = build_power_cache(trains["Empty"], route)
    base_template = ScheduleTemplate(900, 900, 420, 6, 6)
    baseline_schedule = generate_schedule(base_template)
    full_schedule = optimized_schedule(base_template, heavy_cache, empty_cache, battery, route)

    timestep_rows = run_timestep_experiment(full_schedule, heavy_cache, empty_cache, battery, route)
    robustness_rows = run_robustness_experiment(
        {
            "fixed_headway_baseline": baseline_schedule,
            "full_nsga2_mpc": full_schedule,
        },
        heavy_cache,
        empty_cache,
        battery,
        route,
    )
    pareto_candidates, pareto_front_rows = run_pareto_experiment(base_template, heavy_cache, empty_cache, battery, route)
    signaling_rows = run_signaling_gap_experiment(route, heavy_cache, empty_cache)

    write_csv(timestep_rows, OUTPUT_DIR / "settlement_timestep_accuracy.csv")
    write_csv(robustness_rows, OUTPUT_DIR / "robustness_stress.csv")
    write_csv(pareto_candidates, OUTPUT_DIR / "pareto_candidates.csv")
    write_csv(pareto_front_rows, OUTPUT_DIR / "pareto_front.csv")
    write_csv(signaling_rows, OUTPUT_DIR / "signaling_gap_results.csv")

    summary = {
        "settlement_timestep_accuracy": timestep_rows,
        "robustness_stress": robustness_rows,
        "pareto_candidates": pareto_candidates,
        "pareto_front": pareto_front_rows,
        "signaling_gap_results": signaling_rows,
    }
    (OUTPUT_DIR / "extended_experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    plot_timestep(timestep_rows, OUTPUT_DIR / "settlement_timestep_accuracy.png")
    plot_robustness(robustness_rows, OUTPUT_DIR / "robustness_stress.png")
    plot_pareto(pareto_candidates, pareto_front_rows, OUTPUT_DIR / "pareto_candidates.png")
    plot_signaling_gap(signaling_rows, OUTPUT_DIR / "signaling_min_gap.png")
    write_report(
        timestep_rows,
        robustness_rows,
        pareto_front_rows,
        signaling_rows,
        OUTPUT_DIR / "EXTENDED_EXPERIMENT_REPORT.md",
    )

    print("=== Extended Experiment Summary ===")
    print("Output directory:", OUTPUT_DIR.resolve())
    print("Timestep rows:", len(timestep_rows))
    print("Robustness rows:", len(robustness_rows))
    print("Pareto candidates:", len(pareto_candidates))
    print("Pareto front:", len(pareto_front_rows))
    print("Signaling rows:", len(signaling_rows))


if __name__ == "__main__":
    main()
