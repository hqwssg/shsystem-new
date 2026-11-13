# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List

from run_dispatch_case import (
    apply_train_mass_scenario,
    evaluate_dispatch_schedule,
    load_case_inputs,
    make_settlement_system,
    safe_pct,
)
from energy_settlement import storage_no_direct_effective_loss_kwh
from rolling_optimizer import ScheduleTemplate, generate_schedule
from scheduler_nsga2 import build_power_cache
from storage_presets import (
    apply_storage_preset_to_battery,
    apply_storage_preset_to_route,
    apply_storage_ranges_to_power_arm_limits,
    default_storage_preset_library,
    preset_to_dict,
)


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _rounded_reduction_pct(base: float, optimized: float) -> float | None:
    """函数 _rounded_reduction_pct：执行该模块中的相关处理逻辑。"""
    value = safe_pct(float(base), float(optimized))
    return None if value is None else round(value, 3)


def storage_preset_ranking_key(row: Dict[str, Any]) -> tuple[float, ...]:
    """Rank feasible presets by reused energy rather than terminal charging."""

    feasible = row.get("feasible", False)
    if type(feasible) is not bool:
        raise ValueError(f"feasible must be a boolean, got {feasible!r}")

    def ranking_number(field_name: str, default: float | None = None) -> float:
        """函数 ranking_number：执行该模块中的相关处理逻辑。"""
        raw_value = row.get(field_name, default)
        if isinstance(raw_value, bool) or raw_value is None:
            raise ValueError(f"{field_name} must be a finite number, got {raw_value!r}")
        try:
            number = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a finite number, got {raw_value!r}") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field_name} must be a finite number, got {raw_value!r}")
        return number

    return (
        0.0 if feasible else 1.0,
        ranking_number("resource_conflict_count", 0.0),
        ranking_number("effective_regen_loss_kwh"),
        ranking_number("grid_kwh"),
        ranking_number("total_cost"),
    )


def main(argv: List[str] | None = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(
        description=(
            "Search editable virtual storage presets for energy savings under storage_no_direct. "
            "This path is for planning diagnosis while official storage parameters are unavailable."
        )
    )
    parser.add_argument("--input", type=Path, default=Path("data") / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "storage_energy_search")
    parser.add_argument("--heavy-headway-s", type=int, default=3300)
    parser.add_argument("--empty-headway-s", type=int, default=2700)
    parser.add_argument("--phase-s", type=int, default=2600)
    parser.add_argument("--heavy-count", type=int, default=3)
    parser.add_argument("--empty-count", type=int, default=3)
    parser.add_argument("--settlement-step-s", type=int, default=10)
    parser.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.05)
    parser.add_argument("--min-depart-gap-s", type=int, default=900)
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    case = load_case_inputs(args.input, output_dir)
    trains = apply_train_mass_scenario(case.trains, None)
    base_battery = case.battery
    presets = default_storage_preset_library(base_battery)

    template = ScheduleTemplate(
        heavy_headway_s=args.heavy_headway_s,
        empty_headway_s=args.empty_headway_s,
        heavy_empty_phase_s=args.phase_s,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
    )
    schedule = generate_schedule(template)
    target_gap_s = int(round((template.heavy_headway_s + template.empty_headway_s) / 2.0))

    rows: List[Dict[str, Any]] = []
    print("=== Virtual Storage Energy Search ===", flush=True)
    print(f"Schedule template: H{template.heavy_headway_s}/E{template.empty_headway_s}/P{template.heavy_empty_phase_s}", flush=True)

    for preset in presets:
        print(f"Evaluating {preset.scenario_id} ...", flush=True)
        route = apply_storage_preset_to_route(case.route, preset)
        battery = apply_storage_preset_to_battery(base_battery, preset)
        power_arm_limits, storage_sections = apply_storage_ranges_to_power_arm_limits(
            case.power_arm_limits,
            case.power_arm_path,
            preset.ranges_km,
            note=preset.note,
        )
        heavy_cache = build_power_cache(
            trains["Heavy"],
            route,
            power_arm_interval_path=case.power_arm_path,
            storage_sections=storage_sections,
        )
        empty_cache = build_power_cache(
            trains["Empty"],
            route,
            power_arm_interval_path=case.power_arm_path,
            storage_sections=storage_sections,
        )
        settlement = make_settlement_system(
            battery,
            route,
            args.settlement_step_s,
            0.0,
            None,
            0.0,
            0.0,
            args.wasted_energy_penalty_per_kwh,
            "storage_no_direct",
            power_arm_limits,
        )
        evaluation = evaluate_dispatch_schedule(
            preset.scenario_id,
            schedule,
            route,
            heavy_cache,
            empty_cache,
            settlement,
            case.resource_model,
            storage_sections,
            target_gap_s=target_gap_s,
            min_depart_gap_s=args.min_depart_gap_s,
            objective_mode="balanced",
            energy_scenario="storage_no_direct",
        )
        settlement_result = evaluation.settlement
        final_soc_deviation_kwh = abs(
            settlement_result.final_soc_kwh - settlement_result.initial_soc_kwh
        )
        effective_regen_loss_kwh = getattr(
            settlement_result,
            "effective_regen_loss_kwh",
            storage_no_direct_effective_loss_kwh(
                settlement_result.wasted_kwh,
                settlement_result.battery_charge_kwh,
                settlement_result.battery_discharge_kwh,
                final_soc_deviation_kwh,
                battery.round_trip_efficiency,
            ),
        )
        row = {
            "scenario_id": preset.scenario_id,
            "label": preset.label,
            "ranges_km": json.dumps([list(x) for x in preset.ranges_km], ensure_ascii=False),
            "capacity_kwh": battery.capacity_kwh,
            "max_charge_power_kW": battery.max_charge_power_kW,
            "max_discharge_power_kW": battery.max_discharge_power_kW,
            "round_trip_efficiency": battery.round_trip_efficiency,
            "storage_section_count": len({item.storage_section_id for item in storage_sections}),
            "feasible": evaluation.feasible,
            "resource_conflict_count": evaluation.resource_check.conflict_count,
            "total_cost": round(settlement_result.total_cost, 3),
            "grid_cost": round(settlement_result.grid_cost, 3),
            "battery_cost": round(settlement_result.battery_cost, 3),
            "wasted_energy_penalty": round(settlement_result.wasted_energy_penalty, 3),
            "grid_kwh": round(settlement_result.grid_kwh, 3),
            "wasted_kwh": round(settlement_result.wasted_kwh, 3),
            "battery_charge_kwh": round(settlement_result.battery_charge_kwh, 3),
            "battery_discharge_kwh": round(settlement_result.battery_discharge_kwh, 3),
            "initial_soc_kwh": round(settlement_result.initial_soc_kwh, 3),
            "final_soc_kwh": round(settlement_result.final_soc_kwh, 3),
            "final_soc_deviation_kwh": round(final_soc_deviation_kwh, 3),
            "effective_regen_loss_kwh": round(effective_regen_loss_kwh, 3),
            "direct_used_kwh": round(settlement_result.direct_used_kwh, 3),
            "total_gen_kwh": round(settlement_result.total_gen_kwh, 3),
            "total_con_kwh": round(settlement_result.total_con_kwh, 3),
            "recovered_or_stored_ratio": round(
                (settlement_result.battery_charge_kwh / settlement_result.total_gen_kwh)
                if settlement_result.total_gen_kwh > 1e-9
                else 0.0,
                6,
            ),
            "note": preset.note,
            "data_status": "planning_virtual_preset_search",
        }
        rows.append(row)
        print(
            f"  feasible={row['feasible']} wasted={row['wasted_kwh']} grid={row['grid_kwh']} "
            f"charge={row['battery_charge_kwh']} cost={row['total_cost']}",
            flush=True,
        )

    baseline = next(row for row in rows if row["scenario_id"] == "virtual_two_section_base")
    for row in rows:
        row["wasted_reduction_vs_base_pct"] = _rounded_reduction_pct(
            baseline["wasted_kwh"],
            row["wasted_kwh"],
        )
        row["grid_reduction_vs_base_pct"] = _rounded_reduction_pct(
            baseline["grid_kwh"],
            row["grid_kwh"],
        )
        row["cost_reduction_vs_base_pct"] = _rounded_reduction_pct(
            baseline["total_cost"],
            row["total_cost"],
        )

    ranked = sorted(rows, key=storage_preset_ranking_key)
    best = ranked[0]
    detail_csv = output_dir / "storage_energy_search_detail.csv"
    _write_csv(detail_csv, ranked)

    summary = {
        "purpose": "Search editable virtual storage presets to restore energy non-flatness and identify energy-saving directions while official storage strategy data is unavailable.",
        "schedule_template": {
            "heavy_headway_s": template.heavy_headway_s,
            "empty_headway_s": template.empty_headway_s,
            "phase_s": template.heavy_empty_phase_s,
            "heavy_count": template.heavy_count,
            "empty_count": template.empty_count,
        },
        "baseline_scenario_id": baseline["scenario_id"],
        "best_scenario_id": best["scenario_id"],
        "best_label": best["label"],
        "energy_flat_across_presets": len({row["effective_regen_loss_kwh"] for row in rows}) <= 1
        and len({row["grid_kwh"] for row in rows}) <= 1,
        "unique_effective_regen_loss_kwh": len({row["effective_regen_loss_kwh"] for row in rows}),
        "unique_wasted_kwh": len({row["wasted_kwh"] for row in rows}),
        "unique_grid_kwh": len({row["grid_kwh"] for row in rows}),
        "baseline": baseline,
        "best": best,
        "improvements_vs_base": {
            "effective_regen_loss_reduction_pct": _rounded_reduction_pct(
                baseline["effective_regen_loss_kwh"],
                best["effective_regen_loss_kwh"],
            ),
            "wasted_reduction_pct": best["wasted_reduction_vs_base_pct"],
            "grid_reduction_pct": best["grid_reduction_vs_base_pct"],
            "cost_reduction_pct": best["cost_reduction_vs_base_pct"],
            "battery_charge_kwh_delta": round(best["battery_charge_kwh"] - baseline["battery_charge_kwh"], 3),
        },
        "presets": [preset_to_dict(item) for item in presets],
        "ranked_scenario_ids": [row["scenario_id"] for row in ranked],
        "detail_csv": str(detail_csv),
        "data_status": "planning_virtual_preset_search",
        "note": "Results are virtual planning diagnostics, not official energy-saving claims.",
    }
    summary_json = output_dir / "storage_energy_search_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# Virtual Storage Energy Search Report",
        "",
        "## Purpose",
        "",
        "- Official storage strategy/parameters are unavailable.",
        "- Two storage sections and battery values are editable virtual presets.",
        "- This search checks whether changing virtual storage capacity/power/coverage can create real energy savings under the current schedule template.",
        "",
        "## Fixed Schedule Template",
        "",
        f"- Heavy headway: `{template.heavy_headway_s}` s",
        f"- Empty headway: `{template.empty_headway_s}` s",
        f"- Phase: `{template.heavy_empty_phase_s}` s",
        f"- Train counts: `{template.heavy_count}` heavy + `{template.empty_count}` empty",
        "",
        "## Result",
        "",
        f"- Energy flat across presets: `{summary['energy_flat_across_presets']}`",
        f"- Unique effective_regen_loss_kwh values: `{summary['unique_effective_regen_loss_kwh']}`",
        f"- Unique wasted_kwh values: `{summary['unique_wasted_kwh']}`",
        f"- Unique grid_kwh values: `{summary['unique_grid_kwh']}`",
        f"- Baseline scenario: `{baseline['scenario_id']}`",
        f"- Best scenario: `{best['scenario_id']}` ({best['label']})",
        f"- Wasted reduction vs base: `{best['wasted_reduction_vs_base_pct']}` %",
        f"- Grid reduction vs base: `{best['grid_reduction_vs_base_pct']}` %",
        f"- Cost reduction vs base: `{best['cost_reduction_vs_base_pct']}` %",
        f"- Battery charge delta: `{summary['improvements_vs_base']['battery_charge_kwh_delta']}` kWh",
        "",
        "## Ranked Presets",
        "",
        "| rank | scenario | effective_regen_loss_kwh | wasted_kwh | grid_kwh | charge/discharge_kwh | final_soc_kwh | cost | wasted_reduction_pct |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, row in enumerate(ranked, start=1):
        report_lines.append(
            f"| {idx} | `{row['scenario_id']}` | {row['effective_regen_loss_kwh']} | {row['wasted_kwh']} | {row['grid_kwh']} | "
            f"{row['battery_charge_kwh']} / {row['battery_discharge_kwh']} | {row['final_soc_kwh']} | "
            f"{row['total_cost']} | {row['wasted_reduction_vs_base_pct']} |"
        )
    report_lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- If expanded/high-power virtual storage reduces wasted/grid, the previous NSGA-II energy-flat result was caused by storage structure, not by a broken selector.",
            "- These numbers remain planning diagnostics until official storage boundaries and device parameters replace the virtual presets.",
            "",
            f"- Detail CSV: `{detail_csv}`",
            f"- Summary JSON: `{summary_json}`",
        ]
    )
    report_path = output_dir / "STORAGE_ENERGY_SEARCH_REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("=== Storage Energy Search Complete ===", flush=True)
    print("Best scenario:", best["scenario_id"], flush=True)
    print("Wasted reduction pct:", best["wasted_reduction_vs_base_pct"], flush=True)
    print("Grid reduction pct:", best["grid_reduction_vs_base_pct"], flush=True)
    print("Cost reduction pct:", best["cost_reduction_vs_base_pct"], flush=True)
    print("Energy flat:", summary["energy_flat_across_presets"], flush=True)
    print("Report:", report_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
