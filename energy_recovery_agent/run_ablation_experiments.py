# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from energy_settlement import (
    EnergySettlementSystem,
    storage_no_direct_effective_loss_kwh,
)
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    RollingOptimizer,
    RollingWindowState,
    ScheduleTemplate,
    TemplateSearchConfig,
    build_power_series,
    default_scenarios,
    generate_schedule,
    robust_evaluate_schedule,
)
from scheduler_nsga2 import PowerSeriesCache, build_power_cache
from train_simulator import BatteryStorageParameters, load_config


OUTPUT_DIR = Path("outputs") / "experiments"


def _relative_reduction_pct(base: float, value: float) -> float | None:
    """Return a reduction percentage without dividing by a zero baseline."""

    if abs(base) <= 1e-9:
        return 0.0 if abs(value) <= 1e-9 else None
    return round((base - value) / base * 100.0, 3)


def battery_variant(
    base: BatteryStorageParameters,
    *,
    capacity_kwh: float | None = None,
    max_charge_power_kW: float | None = None,
    max_discharge_power_kW: float | None = None,
) -> BatteryStorageParameters:
    """函数 battery_variant：执行该模块中的相关处理逻辑。"""
    return BatteryStorageParameters(
        capacity_kwh=base.capacity_kwh if capacity_kwh is None else capacity_kwh,
        round_trip_efficiency=base.round_trip_efficiency,
        depreciation_cost_per_kwh=base.depreciation_cost_per_kwh,
        grid_price_per_kwh=base.grid_price_per_kwh,
        max_charge_power_kW=base.max_charge_power_kW if max_charge_power_kW is None else max_charge_power_kW,
        max_discharge_power_kW=base.max_discharge_power_kW if max_discharge_power_kW is None else max_discharge_power_kW,
    )


def result_row(
    experiment: str,
    schedule: GeneratedSchedule,
    score,
    settlement,
    battery: BatteryStorageParameters,
) -> Dict[str, float | int | str | bool]:
    """函数 result_row：执行该模块中的相关处理逻辑。"""
    target_soc = getattr(settlement, "target_final_soc_kwh", None)
    if target_soc is None:
        target_soc = getattr(settlement, "initial_soc_kwh", 0.0)
    final_soc_deviation_kwh = abs(settlement.final_soc_kwh - float(target_soc))
    final_soc_shortfall_kwh = max(0.0, float(target_soc) - settlement.final_soc_kwh)
    energy_loss_kwh = settlement.grid_kwh + getattr(
        settlement,
        "effective_regen_loss_kwh",
        storage_no_direct_effective_loss_kwh(
            settlement.wasted_kwh,
            settlement.battery_charge_kwh,
            settlement.battery_discharge_kwh,
            final_soc_deviation_kwh,
            battery.round_trip_efficiency,
            final_soc_shortfall_kwh,
        ),
    )
    recovered_kwh = settlement.direct_used_kwh + settlement.battery_discharge_kwh
    return {
        "experiment": experiment,
        "feasible": score.feasible,
        "scenario_count": score.scenario_count,
        "avg_cost": round(score.total_cost, 3),
        "worst_cost": round(score.worst_case_cost, 3),
        "avg_headway_deviation": round(score.headway_deviation, 3),
        "settlement_total_cost": round(settlement.total_cost, 3),
        "grid_kwh": round(settlement.grid_kwh, 3),
        "grid_cost": round(settlement.grid_cost, 3),
        "wasted_kwh": round(settlement.wasted_kwh, 3),
        "wasted_energy_penalty": round(getattr(settlement, "wasted_energy_penalty", 0.0), 3),
        "final_soc_penalty": round(getattr(settlement, "final_soc_penalty", 0.0), 3),
        "direct_used_kwh": round(settlement.direct_used_kwh, 3),
        "battery_charge_kwh": round(settlement.battery_charge_kwh, 3),
        "battery_discharge_kwh": round(settlement.battery_discharge_kwh, 3),
        "battery_charge_limited_kwh": round(settlement.battery_charge_limited_kwh, 3),
        "battery_discharge_limited_kwh": round(settlement.battery_discharge_limited_kwh, 3),
        "energy_loss_kwh": round(energy_loss_kwh, 3),
        "recovered_kwh": round(recovered_kwh, 3),
        "battery_capacity_kwh": round(battery.capacity_kwh, 3),
        "initial_soc_kwh": round(getattr(settlement, "initial_soc_kwh", 0.0), 3),
        "final_soc_kwh": round(getattr(settlement, "final_soc_kwh", 0.0), 3),
        "final_soc_deviation_kwh": round(final_soc_deviation_kwh, 3),
        "target_final_soc_kwh": (
            ""
            if getattr(settlement, "target_final_soc_kwh", None) is None
            else round(getattr(settlement, "target_final_soc_kwh"), 3)
        ),
        "final_soc_shortfall_kwh": round(getattr(settlement, "final_soc_shortfall_kwh", 0.0), 3),
        "final_soc_excess_kwh": round(getattr(settlement, "final_soc_excess_kwh", 0.0), 3),
        "battery_charge_power_kW": round(battery.max_charge_power_kW, 3),
        "battery_discharge_power_kW": round(battery.max_discharge_power_kW, 3),
        "heavy_count": len(schedule.heavy_departures_s),
        "empty_count": len(schedule.empty_departures_s),
        "heavy_headway_s": schedule.template.heavy_headway_s,
        "empty_headway_s": schedule.template.empty_headway_s,
        "phase_s": schedule.template.heavy_empty_phase_s,
        "hold_s": schedule.template.flex_zone_hold_s,
        "heavy_departures_s": " ".join(str(t) for t in schedule.heavy_departures_s),
        "empty_departures_s": " ".join(str(t) for t in schedule.empty_departures_s),
    }


def add_relative_metrics(rows: List[Dict[str, object]], baseline_name: str) -> None:
    """函数 add_relative_metrics：执行该模块中的相关处理逻辑。"""
    baseline = next((row for row in rows if row["experiment"] == baseline_name), None)
    if baseline is None:
        return
    base_grid = float(baseline["grid_kwh"])
    base_wasted = float(baseline["wasted_kwh"])
    base_loss = float(baseline["energy_loss_kwh"])
    base_cost = float(baseline["settlement_total_cost"])
    for row in rows:
        row["grid_reduction_pct_vs_baseline"] = _relative_reduction_pct(
            base_grid, float(row["grid_kwh"])
        )
        row["wasted_reduction_pct_vs_baseline"] = _relative_reduction_pct(
            base_wasted, float(row["wasted_kwh"])
        )
        row["energy_loss_reduction_pct_vs_baseline"] = _relative_reduction_pct(
            base_loss, float(row["energy_loss_kwh"])
        )
        row["cost_reduction_pct_vs_baseline"] = _relative_reduction_pct(
            base_cost, float(row["settlement_total_cost"])
        )


def precise_settlement(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    energy_transfer_ranges,
) -> object:
    """函数 precise_settlement：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(battery, energy_transfer_ranges, settlement_time_step_s=1, allow_direct_use=False, allow_storage=True)
    power_series = build_power_series(
        heavy_cache,
        schedule.heavy_departures_s,
        sample_step_s=1,
    )
    power_series.extend(
        build_power_series(
            empty_cache,
            schedule.empty_departures_s,
            sample_step_s=1,
            storage_hold_s=schedule.template.flex_zone_hold_s,
        )
    )
    return system.settle(power_series)


def evaluate_experiment(
    name: str,
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
    scenarios: List[DisturbanceScenario],
) -> Dict[str, float | int | str | bool]:
    """函数 evaluate_experiment：执行该模块中的相关处理逻辑。"""
    fast_system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, settlement_time_step_s=10, allow_direct_use=False, allow_storage=True)
    score = robust_evaluate_schedule(
        schedule,
        scenarios,
        heavy_cache,
        empty_cache,
        fast_system,
        route.signaling_system,
    )
    settlement = precise_settlement(schedule, heavy_cache, empty_cache, battery, route.energy_transfer_ranges_km)
    return result_row(name, schedule, score, settlement, battery)


def best_phase_schedule(
    base_template: ScheduleTemplate,
    phases_s: Iterable[int],
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
    scenarios: List[DisturbanceScenario],
) -> GeneratedSchedule:
    """函数 best_phase_schedule：执行该模块中的相关处理逻辑。"""
    best_schedule: GeneratedSchedule | None = None
    best_value = float("inf")
    system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, settlement_time_step_s=10, allow_direct_use=False, allow_storage=True)
    for phase_s in phases_s:
        schedule = generate_schedule(replace(base_template, heavy_empty_phase_s=phase_s))
        score = robust_evaluate_schedule(schedule, scenarios, heavy_cache, empty_cache, system, route.signaling_system)
        value = score.total_cost + 0.25 * score.headway_deviation + 0.35 * score.worst_case_cost
        if value < best_value:
            best_value = value
            best_schedule = schedule
    if best_schedule is None:
        raise RuntimeError("No phase schedule generated.")
    return best_schedule


def optimized_schedule(
    base_template: ScheduleTemplate,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    battery: BatteryStorageParameters,
    route,
) -> GeneratedSchedule:
    """函数 optimized_schedule：执行该模块中的相关处理逻辑。"""
    optimizer = RollingOptimizer(
        route,
        heavy_cache,
        empty_cache,
        EnergySettlementSystem(battery, route.energy_transfer_ranges_km, settlement_time_step_s=10, allow_direct_use=False, allow_storage=True),
    )
    search_config = TemplateSearchConfig(method="nsga2", population_size=10, generations=3, elite_count=3)
    result = optimizer.optimize_once(
        RollingWindowState(0, [], []),
        base_template,
        horizon_s=5400,
        execute_window_s=900,
        search_config=search_config,
    )
    return result.schedule


def write_csv(rows: List[Dict[str, object]], path: Path) -> None:
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_metric_bars(rows: List[Dict[str, object]], output_path: Path) -> None:
    """函数 plot_metric_bars：执行该模块中的相关处理逻辑。"""
    labels = [str(row["experiment"]) for row in rows]
    grid = [float(row["grid_kwh"]) for row in rows]
    wasted = [float(row["wasted_kwh"]) for row in rows]
    cost = [float(row["settlement_total_cost"]) for row in rows]

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    axes[0].bar(labels, grid, color="#f58518")
    axes[0].set_ylabel("Grid kWh")
    axes[1].bar(labels, wasted, color="#b279a2")
    axes[1].set_ylabel("Wasted kWh")
    axes[2].bar(labels, cost, color="#4c78a8")
    axes[2].set_ylabel("Cost")
    axes[2].tick_params(axis="x", rotation=20)
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Ablation Experiment Comparison")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_sensitivity(rows: List[Dict[str, object]], x_key: str, output_path: Path, title: str) -> None:
    """函数 plot_sensitivity：执行该模块中的相关处理逻辑。"""
    sorted_rows = sorted(rows, key=lambda row: float(row[x_key]))
    x_values = [float(row[x_key]) for row in sorted_rows]
    cost = [float(row["settlement_total_cost"]) for row in sorted_rows]
    grid = [float(row["grid_kwh"]) for row in sorted_rows]
    wasted = [float(row["wasted_kwh"]) for row in sorted_rows]

    fig, ax1 = plt.subplots(1, 1, figsize=(10, 5))
    ax1.plot(x_values, cost, marker="o", color="#4c78a8", label="Cost")
    ax1.set_xlabel(x_key)
    ax1.set_ylabel("Cost")
    ax1.grid(True, alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(x_values, grid, marker="s", color="#f58518", label="Grid kWh")
    ax2.plot(x_values, wasted, marker="^", color="#b279a2", label="Wasted kWh")
    ax2.set_ylabel("Energy (kWh)")

    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="best")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    route, trains, battery = load_config(Path("sandbox_config.json"))
    heavy_cache = build_power_cache(trains["Heavy"], route)
    empty_cache = build_power_cache(trains["Empty"], route)
    base_template = ScheduleTemplate(
        heavy_headway_s=900,
        empty_headway_s=900,
        heavy_empty_phase_s=420,
        heavy_count=6,
        empty_count=6,
    )
    scenarios = default_scenarios()

    baseline_schedule = generate_schedule(base_template)
    phase_schedule = best_phase_schedule(
        base_template,
        phases_s=range(0, 1501, 120),
        heavy_cache=heavy_cache,
        empty_cache=empty_cache,
        battery=battery,
        route=route,
        scenarios=scenarios,
    )
    optimized = optimized_schedule(base_template, heavy_cache, empty_cache, battery, route)
    no_storage_battery = battery_variant(battery, capacity_kwh=0.0, max_charge_power_kW=0.0, max_discharge_power_kW=0.0)

    ablation_rows = [
        evaluate_experiment("fixed_headway_baseline", baseline_schedule, heavy_cache, empty_cache, battery, route, scenarios),
        evaluate_experiment("phase_only_optimized", phase_schedule, heavy_cache, empty_cache, battery, route, scenarios),
        evaluate_experiment("no_storage", optimized, heavy_cache, empty_cache, no_storage_battery, route, scenarios),
        evaluate_experiment("full_nsga2_mpc", optimized, heavy_cache, empty_cache, battery, route, scenarios),
    ]

    capacity_rows: List[Dict[str, object]] = []
    for capacity in [5000.0, 10000.0, 20000.0, 40000.0]:
        variant = battery_variant(battery, capacity_kwh=capacity)
        capacity_rows.append(
            evaluate_experiment(
                f"capacity_{int(capacity)}",
                optimized,
                heavy_cache,
                empty_cache,
                variant,
                route,
                scenarios,
            )
        )

    power_rows: List[Dict[str, object]] = []
    for power in [5000.0, 10000.0, 20000.0, 40000.0]:
        variant = battery_variant(battery, max_charge_power_kW=power, max_discharge_power_kW=power)
        power_rows.append(
            evaluate_experiment(
                f"power_{int(power)}",
                optimized,
                heavy_cache,
                empty_cache,
                variant,
                route,
                scenarios,
            )
        )

    add_relative_metrics(ablation_rows, "fixed_headway_baseline")
    add_relative_metrics(capacity_rows, "capacity_5000")
    add_relative_metrics(power_rows, "power_5000")

    write_csv(ablation_rows, OUTPUT_DIR / "ablation_results.csv")
    write_csv(capacity_rows, OUTPUT_DIR / "storage_capacity_sensitivity.csv")
    write_csv(power_rows, OUTPUT_DIR / "storage_power_sensitivity.csv")

    summary = {
        "ablation": ablation_rows,
        "storage_capacity_sensitivity": capacity_rows,
        "storage_power_sensitivity": power_rows,
    }
    (OUTPUT_DIR / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    plot_metric_bars(ablation_rows, OUTPUT_DIR / "ablation_comparison.png")
    plot_sensitivity(
        capacity_rows,
        "battery_capacity_kwh",
        OUTPUT_DIR / "storage_capacity_sensitivity.png",
        "Storage Capacity Sensitivity",
    )
    plot_sensitivity(
        power_rows,
        "battery_charge_power_kW",
        OUTPUT_DIR / "storage_power_sensitivity.png",
        "Storage Power Sensitivity",
    )

    print("=== Ablation Experiment Summary ===")
    print("Output directory:", OUTPUT_DIR.resolve())
    for row in ablation_rows:
        print(
            row["experiment"],
            "cost=", row["settlement_total_cost"],
            "grid=", row["grid_kwh"],
            "wasted=", row["wasted_kwh"],
        )


if __name__ == "__main__":
    main()
