# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from energy_settlement import EnergySettlementSystem, build_power_series
from rolling_optimizer import (
    RollingOptimizer,
    RollingWindowState,
    ScheduleTemplate,
    TemplateSearchConfig,
)
from scheduler_nsga2 import build_power_cache
from train_simulator import StepRecord, load_config, run_train_simulation


OUTPUT_DIR = Path("outputs")


def write_train_profile_csv(records: List[StepRecord], output_path: Path) -> None:
    """函数 write_train_profile_csv：执行该模块中的相关处理逻辑。"""
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "time_s",
                "position_km",
                "speed_kmh",
                "traction_kN",
                "brake_kN",
                "power_kW",
                "energy_transfer_ratio",
                "speed_limit_kmh",
                "adhesion_coefficient",
                "traction_limit_kN",
                "brake_limit_kN",
                "adhesion_limited_decel_mps2",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.time_s,
                    round(record.position_km, 4),
                    round(record.speed_mps * 3.6, 4),
                    round(record.traction_kN, 4),
                    round(record.brake_kN, 4),
                    round(record.power_kW, 4),
                    round(record.energy_transfer_ratio, 4),
                    round(record.speed_limit_mps * 3.6, 4),
                    round(record.adhesion_coefficient, 4),
                    round(record.traction_limit_kN, 4),
                    round(record.brake_limit_kN, 4),
                    round(record.adhesion_limited_decel_mps2, 4),
                ]
            )


def plot_route_profile(route, output_path: Path) -> None:
    """函数 plot_route_profile：执行该模块中的相关处理逻辑。"""
    distances = [segment.start_km for segment in route.segments]
    gradients = [segment.gradient_per_mille for segment in route.segments]
    curve_radii = [
        segment.curve_radius_m if segment.curve_radius_m is not None else 0.0
        for segment in route.segments
    ]

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(distances, gradients, color="#1f77b4", linewidth=1.0)
    axes[0].axhline(0, color="#333333", linewidth=0.8)
    axes[0].set_ylabel("Gradient (per mille)")
    axes[0].grid(True, alpha=0.25)

    axes[1].plot(distances, curve_radii, color="#9467bd", linewidth=1.0)
    axes[1].set_ylabel("Curve radius (m)")
    axes[1].set_xlabel("Mileage (km)")
    axes[1].grid(True, alpha=0.25)

    for start, end in route.energy_transfer_ranges_km:
        for ax in axes:
            ax.axvspan(start, end, color="#2ca02c", alpha=0.18)
    long_start, long_end = route.long_downhill_range_km
    for ax in axes:
        ax.axvspan(long_start, long_end, color="#ff7f0e", alpha=0.08)

    fig.suptitle("Virtual Shuohuang Route Profile")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_train_power_profiles(heavy_records: List[StepRecord], empty_records: List[StepRecord], output_path: Path) -> None:
    """函数 plot_train_power_profiles：执行该模块中的相关处理逻辑。"""
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(
        [record.position_km for record in heavy_records],
        [record.power_kW for record in heavy_records],
        color="#d62728",
        linewidth=1.0,
        label="Heavy forward",
    )
    axes[1].plot(
        [record.position_km for record in empty_records],
        [record.power_kW for record in empty_records],
        color="#1f77b4",
        linewidth=1.0,
        label="Empty reverse",
    )

    axes[0].set_ylabel("Power (kW)")
    axes[1].set_ylabel("Power (kW)")
    axes[1].set_xlabel("Mileage (km)")
    for ax in axes:
        ax.axhline(0, color="#333333", linewidth=0.8)
        ax.grid(True, alpha=0.25)
        ax.legend()

    fig.suptitle("Train Power Profiles")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_rolling_schedule(heavy_departures: List[int], empty_departures: List[int], output_path: Path) -> None:
    """函数 plot_rolling_schedule：执行该模块中的相关处理逻辑。"""
    fig, ax = plt.subplots(1, 1, figsize=(10, 3.5))
    ax.scatter([time / 60.0 for time in heavy_departures], [1] * len(heavy_departures), color="#d62728", label="Heavy")
    ax.scatter([time / 60.0 for time in empty_departures], [0] * len(empty_departures), color="#1f77b4", label="Empty")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Empty reverse", "Heavy forward"])
    ax.set_xlabel("Departure time (min)")
    ax.set_title("Rolling Optimization Departure Plan")
    ax.grid(True, axis="x", alpha=0.25)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    OUTPUT_DIR.mkdir(exist_ok=True)

    route, trains, battery = load_config(Path("sandbox_config.json"))
    heavy_train = trains["Heavy"]
    empty_train = trains["Empty"]

    heavy_records = run_train_simulation(route, heavy_train)
    empty_records = run_train_simulation(route, empty_train)

    write_train_profile_csv(heavy_records, OUTPUT_DIR / "heavy_profile.csv")
    write_train_profile_csv(empty_records, OUTPUT_DIR / "empty_profile.csv")

    system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, allow_direct_use=False, allow_storage=True)
    settlement = system.settle(
        [
            build_power_series(heavy_records, 0),
            build_power_series(empty_records, 1000),
        ]
    )

    heavy_cache = build_power_cache(heavy_train, route)
    empty_cache = build_power_cache(empty_train, route)
    rolling_system = EnergySettlementSystem(
        battery,
        route.energy_transfer_ranges_km,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
    )
    optimizer = RollingOptimizer(route, heavy_cache, empty_cache, rolling_system)
    template = ScheduleTemplate(
        heavy_headway_s=900,
        empty_headway_s=900,
        heavy_empty_phase_s=420,
        heavy_count=6,
        empty_count=6,
    )
    search_config = TemplateSearchConfig(method="nsga2", population_size=10, generations=3, elite_count=3)
    rolling_result = optimizer.optimize_once(
        RollingWindowState(0, [], []),
        template,
        horizon_s=5400,
        execute_window_s=900,
        search_config=search_config,
    )

    with (OUTPUT_DIR / "rolling_schedule.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["train_type", "direction", "depart_time_s", "depart_time_min"])
        for time_s in rolling_result.schedule.heavy_departures_s:
            writer.writerow(["Heavy", "forward", time_s, round(time_s / 60.0, 3)])
        for time_s in rolling_result.schedule.empty_departures_s:
            writer.writerow(["Empty", "reverse", time_s, round(time_s / 60.0, 3)])

    summary = {
        "route": {
            "total_length_km": route.total_length_km,
            "max_speed_kmh": route.max_speed_kmh,
            "station_count": len(route.stations),
            "long_downhill_range_km": route.long_downhill_range_km,
            "energy_transfer_ranges_km": route.energy_transfer_ranges_km,
            "signaling_system": route.signaling_system,
            "operating_conditions": {
                "default_adhesion_coefficient": route.operating_conditions.default_adhesion_coefficient,
                "traction_adhesion_safety_factor": route.operating_conditions.traction_adhesion_safety_factor,
                "braking_adhesion_safety_factor": route.operating_conditions.braking_adhesion_safety_factor,
                "weather_condition_count": len(route.operating_conditions.weather_conditions),
                "adhesion_zone_count": len(route.operating_conditions.adhesion_zones),
                "speed_restriction_count": len(route.operating_conditions.speed_restrictions),
            },
        },
        "battery": {
            "capacity_kwh": battery.capacity_kwh,
            "max_charge_power_kW": battery.max_charge_power_kW,
            "max_discharge_power_kW": battery.max_discharge_power_kW,
            "round_trip_efficiency": battery.round_trip_efficiency,
            "depreciation_cost_per_kwh": battery.depreciation_cost_per_kwh,
            "grid_price_per_kwh": battery.grid_price_per_kwh,
        },
        "train_simulation": {
            "heavy": {
                "direction": heavy_train.direction,
                "length_km": heavy_train.length_km,
                "total_time_min": round(heavy_records[-1].time_s / 60.0, 3),
                "start_position_km": heavy_records[0].position_km,
                "end_position_km": round(heavy_records[-1].position_km, 3),
                "min_power_kW": round(min(record.power_kW for record in heavy_records), 3),
                "max_power_kW": round(max(record.power_kW for record in heavy_records), 3),
                "min_adhesion_coefficient": round(min(record.adhesion_coefficient for record in heavy_records), 4),
                "min_speed_limit_kmh": round(min(record.speed_limit_mps for record in heavy_records) * 3.6, 3),
            },
            "empty": {
                "direction": empty_train.direction,
                "length_km": empty_train.length_km,
                "total_time_min": round(empty_records[-1].time_s / 60.0, 3),
                "start_position_km": empty_records[0].position_km,
                "end_position_km": round(empty_records[-1].position_km, 3),
                "min_power_kW": round(min(record.power_kW for record in empty_records), 3),
                "max_power_kW": round(max(record.power_kW for record in empty_records), 3),
                "min_adhesion_coefficient": round(min(record.adhesion_coefficient for record in empty_records), 4),
                "min_speed_limit_kmh": round(min(record.speed_limit_mps for record in empty_records) * 3.6, 3),
            },
        },
        "energy_settlement": {
            "total_gen_kwh": round(settlement.total_gen_kwh, 3),
            "total_con_kwh": round(settlement.total_con_kwh, 3),
            "direct_used_kwh": round(settlement.direct_used_kwh, 3),
            "battery_charge_kwh": round(settlement.battery_charge_kwh, 3),
            "battery_discharge_kwh": round(settlement.battery_discharge_kwh, 3),
            "battery_charge_limited_kwh": round(settlement.battery_charge_limited_kwh, 3),
            "battery_discharge_limited_kwh": round(settlement.battery_discharge_limited_kwh, 3),
            "wasted_kwh": round(settlement.wasted_kwh, 3),
            "grid_kwh": round(settlement.grid_kwh, 3),
            "grid_cost": round(settlement.grid_cost, 3),
            "battery_cost": round(settlement.battery_cost, 3),
            "wasted_energy_penalty": round(settlement.wasted_energy_penalty, 3),
            "final_soc_penalty": round(settlement.final_soc_penalty, 3),
            "initial_soc_kwh": round(settlement.initial_soc_kwh, 3),
            "final_soc_kwh": round(settlement.final_soc_kwh, 3),
            "target_final_soc_kwh": settlement.target_final_soc_kwh,
            "final_soc_shortfall_kwh": round(settlement.final_soc_shortfall_kwh, 3),
            "final_soc_excess_kwh": round(settlement.final_soc_excess_kwh, 3),
            "total_cost": round(settlement.total_cost, 3),
        },
        "rolling_optimization": {
            "feasible": rolling_result.score.feasible,
            "average_cost": round(rolling_result.score.total_cost, 3),
            "worst_case_cost": round(rolling_result.score.worst_case_cost, 3),
            "average_headway_deviation": round(rolling_result.score.headway_deviation, 3),
            "chosen_heavy_departures_s": rolling_result.schedule.heavy_departures_s,
            "chosen_empty_departures_s": rolling_result.schedule.empty_departures_s,
            "execute_now_heavy_s": rolling_result.executable_heavy_departures_s,
            "execute_now_empty_s": rolling_result.executable_empty_departures_s,
        },
    }
    (OUTPUT_DIR / "virtual_algorithm_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    plot_route_profile(route, OUTPUT_DIR / "route_profile.png")
    plot_train_power_profiles(heavy_records, empty_records, OUTPUT_DIR / "train_power_profiles.png")
    plot_rolling_schedule(
        rolling_result.schedule.heavy_departures_s,
        rolling_result.schedule.empty_departures_s,
        OUTPUT_DIR / "rolling_schedule.png",
    )

    print("=== Virtual Algorithm Output Summary ===")
    print("Output directory:", OUTPUT_DIR.resolve())
    print("Energy total cost:", summary["energy_settlement"]["total_cost"])
    print("Rolling feasible:", rolling_result.score.feasible)
    print("Rolling average cost:", round(rolling_result.score.total_cost, 3))
    print("Heavy departures:", rolling_result.schedule.heavy_departures_s)
    print("Empty departures:", rolling_result.schedule.empty_departures_s)


if __name__ == "__main__":
    main()
