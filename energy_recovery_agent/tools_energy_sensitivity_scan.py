# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean

from run_dispatch_case import (
    apply_battery_scenario,
    apply_train_mass_scenario,
    build_parser,
    effective_min_depart_gap_s,
    evaluate_dispatch_schedule,
    load_case_inputs,
    make_settlement_system,
)
from rolling_optimizer import ScheduleTemplate, generate_schedule
from scheduler_nsga2 import build_power_cache
from energy_settlement import storage_no_direct_effective_loss_kwh


OUTPUT_DIR = Path("outputs") / "energy_sensitivity_scan"


def eval_case(
    *,
    label: str,
    group: str,
    hh: int,
    eh: int,
    phase: int,
    capacity_kwh: float | None,
    charge_kw: float | None,
    discharge_kw: float | None,
    efficiency: float | None = None,
    waste_penalty: float,
    route,
    heavy_cache,
    empty_cache,
    resource_model,
    storage_sections,
    base_battery,
    power_arm_limits,
    min_depart_gap_s: int,
    settlement_step_s: int,
):
    """函数 eval_case：执行该模块中的相关处理逻辑。"""
    battery = apply_battery_scenario(
        base_battery,
        capacity_kwh=capacity_kwh,
        max_charge_power_kW=charge_kw,
        max_discharge_power_kW=discharge_kw,
        round_trip_efficiency=efficiency,
    )
    settlement_system = make_settlement_system(
        battery,
        route,
        settlement_step_s,
        0.0,
        None,
        0.0,
        0.0,
        waste_penalty,
        "storage_no_direct",
        power_arm_limits,
    )
    template = ScheduleTemplate(
        heavy_headway_s=max(hh, min_depart_gap_s),
        empty_headway_s=max(eh, min_depart_gap_s),
        heavy_empty_phase_s=phase,
        heavy_count=3,
        empty_count=3,
    )
    schedule = generate_schedule(template)
    target_gap_s = int(round((template.heavy_headway_s + template.empty_headway_s) / 2.0))
    evaluation = evaluate_dispatch_schedule(
        label,
        schedule,
        route,
        heavy_cache,
        empty_cache,
        settlement_system,
        resource_model,
        storage_sections,
        target_gap_s=target_gap_s,
        min_depart_gap_s=min_depart_gap_s,
        objective_mode="balanced",
        energy_scenario="storage_no_direct",
    )
    settlement = evaluation.settlement
    final_soc_deviation_kwh = abs(settlement.final_soc_kwh - settlement.initial_soc_kwh)
    effective_regen_loss_kwh = getattr(
        settlement,
        "effective_regen_loss_kwh",
        storage_no_direct_effective_loss_kwh(
            settlement.wasted_kwh,
            settlement.battery_charge_kwh,
            settlement.battery_discharge_kwh,
            final_soc_deviation_kwh,
            battery.round_trip_efficiency,
        ),
    )
    return {
        "group": group,
        "case_id": label,
        "heavy_headway_s": template.heavy_headway_s,
        "empty_headway_s": template.empty_headway_s,
        "phase_s": phase,
        "battery_capacity_kwh": battery.capacity_kwh,
        "battery_max_charge_power_kW": battery.max_charge_power_kW,
        "battery_max_discharge_power_kW": battery.max_discharge_power_kW,
        "battery_round_trip_efficiency": battery.round_trip_efficiency,
        "wasted_energy_penalty_per_kwh": waste_penalty,
        "feasible": evaluation.feasible,
        "resource_feasible": evaluation.resource_feasible,
        "resource_conflict_count": evaluation.resource_check.conflict_count,
        "total_cost": round(settlement.total_cost, 3),
        "grid_cost": round(settlement.grid_cost, 3),
        "battery_cost": round(settlement.battery_cost, 3),
        "wasted_energy_penalty": round(settlement.wasted_energy_penalty, 3),
        "total_gen_kwh": round(settlement.total_gen_kwh, 3),
        "total_con_kwh": round(settlement.total_con_kwh, 3),
        "grid_kwh": round(settlement.grid_kwh, 3),
        "wasted_kwh": round(settlement.wasted_kwh, 3),
        "direct_used_kwh": round(settlement.direct_used_kwh, 3),
        "battery_charge_kwh": round(settlement.battery_charge_kwh, 3),
        "battery_discharge_kwh": round(settlement.battery_discharge_kwh, 3),
        "battery_charge_limited_kwh": round(settlement.battery_charge_limited_kwh, 3),
        "battery_discharge_limited_kwh": round(settlement.battery_discharge_limited_kwh, 3),
        "final_soc_kwh": round(settlement.final_soc_kwh, 3),
        "final_soc_deviation_kwh": round(final_soc_deviation_kwh, 3),
        "effective_regen_loss_kwh": round(effective_regen_loss_kwh, 3),
        "accepted_by_power_arm_kwh": round(
            settlement.direct_used_kwh + settlement.battery_charge_kwh, 3
        ),
        "recovered_energy_kwh": round(
            settlement.direct_used_kwh
            + settlement.battery_charge_kwh * battery.round_trip_efficiency,
            3,
        ),
        "recovery_rate": round(
            (
                settlement.direct_used_kwh
                + settlement.battery_charge_kwh * battery.round_trip_efficiency
            )
            / settlement.total_gen_kwh,
            6,
        ) if settlement.total_gen_kwh > 0 else 0.0,
        "heavy_departures_s": json.dumps(schedule.heavy_departures_s),
        "empty_departures_s": json.dumps(schedule.empty_departures_s),
    }


def summarize_group(rows, metric):
    """函数 summarize_group：执行该模块中的相关处理逻辑。"""
    values = [float(r[metric]) for r in rows]
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "span": max(values) - min(values),
        "unique_count": len(set(values)),
    }


def write_csv(path: Path, rows):
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    cli = argparse.ArgumentParser(description="Run energy sensitivity scan for current synthetic baseline.")
    cli.add_argument("--output-dir", type=Path, default=Path("outputs") / "energy_sensitivity_scan")
    cli.add_argument("--input", type=Path, default=Path("data") / "real_shuohuang")
    cli.add_argument("--only-interval", action="store_true", help="run only the bounded parameter interval corner cases")
    ns = cli.parse_args(argv)
    output_dir = Path(ns.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    globals()["OUTPUT_DIR"] = output_dir
    parser = build_parser()
    args = parser.parse_args(
        [
            "--input",
            str(ns.input),
            "--output-dir",
            str(output_dir / "_case_cache"),
            "--energy-scenario",
            "storage_no_direct",
            "--heavy-count",
            "3",
            "--empty-count",
            "3",
        ]
    )
    print("loading case inputs...", flush=True)
    case_inputs = load_case_inputs(Path(args.input), Path(args.output_dir))
    route = case_inputs.route
    trains = apply_train_mass_scenario(case_inputs.trains, None)
    base_battery = case_inputs.battery
    min_depart_gap_s = effective_min_depart_gap_s(args.min_depart_gap_s, case_inputs.resource_model)
    print("min_depart_gap_s", min_depart_gap_s, flush=True)
    print("building heavy cache...", flush=True)
    heavy_cache = build_power_cache(
        trains["Heavy"],
        route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    print("building empty cache...", flush=True)
    empty_cache = build_power_cache(
        trains["Empty"],
        route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    print("caches ready", flush=True)

    cases = []
    # A. 在当前可行追踪间隔下扫描相位。
    for phase in range(1800, 3601, 200):
        cases.append(
            {
                "group": "phase_scan_h3300_e2700",
                "label": f"phase_{phase}",
                "hh": 3300,
                "eh": 2700,
                "phase": phase,
                "capacity_kwh": None,
                "charge_kw": None,
                "discharge_kw": None,
                "waste_penalty": 0.0,
            }
        )
    # B. 围绕当前默认值扫描追踪间隔和相位变体。
    for hh, eh, phase in [
        (3300, 2700, 2600),
        (3000, 3000, 2480),
        (2700, 2700, 2300),
        (3600, 3600, 2600),
        (3300, 3300, 2600),
        (3000, 2700, 2600),
    ]:
        cases.append(
            {
                "group": "template_variants",
                "label": f"tpl_h{hh}_e{eh}_p{phase}",
                "hh": hh,
                "eh": eh,
                "phase": phase,
                "capacity_kwh": None,
                "charge_kw": None,
                "discharge_kw": None,
                "waste_penalty": 0.0,
            }
        )
    # C. 在固定可行模板上扫描储能容量。
    for cap in [0, 5000, 10000, 20000, 40000, 80000]:
        cases.append(
            {
                "group": "storage_capacity_scan",
                "label": f"cap_{cap}",
                "hh": 3300,
                "eh": 2700,
                "phase": 2600,
                "capacity_kwh": float(cap),
                "charge_kw": None,
                "discharge_kw": None,
                "waste_penalty": 0.0,
            }
        )
    # D. 在固定可行模板上扫描储能功率。
    for power in [1000, 5000, 10000, 20000]:
        cases.append(
            {
                "group": "storage_power_scan",
                "label": f"power_{power}",
                "hh": 3300,
                "eh": 2700,
                "phase": 2600,
                "capacity_kwh": 20000.0,
                "charge_kw": float(power),
                "discharge_kw": float(power),
                "waste_penalty": 0.0,
            }
        )
    # E. 在固定能量模板上扫描弃电惩罚。
    for penalty in [0.0, 0.05, 0.10, 0.20]:
        cases.append(
            {
                "group": "waste_penalty_scan",
                "label": f"waste_pen_{penalty}",
                "hh": 3300,
                "eh": 2700,
                "phase": 2600,
                "capacity_kwh": None,
                "charge_kw": None,
                "discharge_kw": None,
                "waste_penalty": float(penalty),
            }
        )

    # F. 围绕当前规划值扫描有界参数区间的角点。
    base_capacity = float(base_battery.capacity_kwh)
    base_charge = float(base_battery.max_charge_power_kW)
    base_discharge = float(base_battery.max_discharge_power_kW)
    base_efficiency = float(base_battery.round_trip_efficiency)
    capacity_bounds = (base_capacity * 0.8, base_capacity * 1.2)
    charge_bounds = (base_charge * 0.8, base_charge * 1.2)
    discharge_bounds = (base_discharge * 0.8, base_discharge * 1.2)
    efficiency_bounds = (max(0.0, base_efficiency - 0.05), min(1.0, base_efficiency + 0.05))
    interval_points = [
        (capacity_bounds[0], charge_bounds[0], discharge_bounds[0], efficiency_bounds[0]),
        (capacity_bounds[0], charge_bounds[1], discharge_bounds[1], efficiency_bounds[1]),
        (capacity_bounds[1], charge_bounds[0], discharge_bounds[0], efficiency_bounds[1]),
        (capacity_bounds[1], charge_bounds[1], discharge_bounds[1], efficiency_bounds[0]),
        (base_capacity, base_charge, base_discharge, base_efficiency),
    ]
    for idx, (cap, charge, discharge, efficiency) in enumerate(interval_points):
        cases.append({
            "group": "parameter_interval_corners",
            "label": f"interval_corner_{idx}",
            "hh": 3300, "eh": 2700, "phase": 2600,
            "capacity_kwh": cap, "charge_kw": charge,
            "discharge_kw": discharge, "efficiency": efficiency,
            "waste_penalty": 0.0,
        })

    if ns.only_interval:
        cases = [case for case in cases if case["group"] == "parameter_interval_corners"]

    rows = []
    for idx, case in enumerate(cases, start=1):
        print(
            f"[{idx}/{len(cases)}] {case['group']} {case['label']}",
            flush=True,
        )
        row = eval_case(
            label=case["label"],
            group=case["group"],
            hh=case["hh"],
            eh=case["eh"],
            phase=case["phase"],
            capacity_kwh=case["capacity_kwh"],
            charge_kw=case["charge_kw"],
            discharge_kw=case["discharge_kw"],
            efficiency=case.get("efficiency"),
            waste_penalty=case["waste_penalty"],
            route=route,
            heavy_cache=heavy_cache,
            empty_cache=empty_cache,
            resource_model=case_inputs.resource_model,
            storage_sections=case_inputs.storage_sections,
            base_battery=base_battery,
            power_arm_limits=case_inputs.power_arm_limits,
            min_depart_gap_s=min_depart_gap_s,
            settlement_step_s=args.settlement_step_s,
        )
        rows.append(row)
        print(
            "  feasible={feasible} conflicts={resource_conflict_count} cost={total_cost} "
            "grid={grid_kwh} wasted={wasted_kwh} charge={battery_charge_kwh} discharge={battery_discharge_kwh}".format(
                **row
            ),
            flush=True,
        )

    detail_csv = OUTPUT_DIR / "energy_sensitivity_detail.csv"
    write_csv(detail_csv, rows)

    groups = sorted({r["group"] for r in rows})
    group_summary = {}
    for group in groups:
        group_rows = [r for r in rows if r["group"] == group]
        group_summary[group] = {
            "case_count": len(group_rows),
            "feasible_count": sum(1 for r in group_rows if r["feasible"]),
            "metrics": {
                metric: summarize_group(group_rows, metric)
                for metric in [
                    "total_cost",
                    "grid_kwh",
                    "wasted_kwh",
                    "battery_charge_kwh",
                    "battery_discharge_kwh",
                    "effective_regen_loss_kwh",
                    "recovery_rate",
                    "direct_used_kwh",
                    "resource_conflict_count",
                ]
            },
            "rows": group_rows,
        }

    summary = {
        "output_dir": str(OUTPUT_DIR),
        "detail_csv": str(detail_csv),
        "base_route_length_km": route.total_length_km if hasattr(route, "total_length_km") else None,
        "storage_zones_km": route.energy_transfer_ranges_km,
        "default_battery": {
            "capacity_kwh": base_battery.capacity_kwh,
            "max_charge_power_kW": base_battery.max_charge_power_kW,
            "max_discharge_power_kW": base_battery.max_discharge_power_kW,
            "data_status": base_battery.data_status,
        },
        "groups": {
            group: {
                "case_count": data["case_count"],
                "feasible_count": data["feasible_count"],
                "metrics": data["metrics"],
            }
            for group, data in group_summary.items()
        },
    }
    interval_data = group_summary.get("parameter_interval_corners")
    if interval_data:
        interval_rows = interval_data["rows"]
        summary["interval_robustness"] = {
            "case_count": len(interval_rows),
            "feasible_count": sum(1 for row in interval_rows if row["feasible"]),
            "feasibility_rate": sum(1 for row in interval_rows if row["feasible"]) / max(1, len(interval_rows)),
            "resource_feasible_count": sum(1 for row in interval_rows if row["resource_feasible"]),
            "resource_feasibility_rate": sum(1 for row in interval_rows if row["resource_feasible"]) / max(1, len(interval_rows)),
            "resource_conflict_types": sorted({str(row.get("resource_conflict_count", "")) for row in interval_rows}),
            "metric_ranges": {
                metric: {
                    "min": min(float(row[metric]) for row in interval_rows),
                    "max": max(float(row[metric]) for row in interval_rows),
                    "span": max(float(row[metric]) for row in interval_rows) - min(float(row[metric]) for row in interval_rows),
                }
                for metric in ("grid_kwh", "wasted_kwh", "effective_regen_loss_kwh", "recovery_rate", "total_cost")
            },
            "conclusion": (
                "blocked_by_baseline_resource_infeasibility"
                if not all(row["resource_feasible"] for row in interval_rows)
                else ("stable_feasible" if all(row["feasible"] for row in interval_rows)
                      else "not_robust_across_current_interval")
            ),
        }
    summary_json = OUTPUT_DIR / "energy_sensitivity_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 生成 Markdown 报告。
    lines = [
        "# Energy Sensitivity Scan Report",
        "",
        "Purpose: check whether schedule phase/headway changes or storage parameter changes can create energy KPI differences under the current synthetic baseline.",
        "",
        "## Setup",
        "",
        "- Input: `data/real_shuohuang`",
        "- Scenario: `storage_no_direct` (direct use disabled)",
        "- Train counts: 3 heavy + 3 empty",
        f"- Storage zones: `{route.energy_transfer_ranges_km}`",
        f"- Default battery: capacity={base_battery.capacity_kwh} kWh, charge/discharge power={base_battery.max_charge_power_kW}/{base_battery.max_discharge_power_kW} kW",
        f"- Detail table: `{detail_csv}`",
        "",
        "## Group Results",
        "",
    ]
    for group, data in group_summary.items():
        metrics = data["metrics"]
        lines.extend(
            [
                f"### {group}",
                "",
                f"- cases: {data['case_count']}, feasible: {data['feasible_count']}",
                f"- total_cost span: {metrics['total_cost']['span']:.3f} (unique={metrics['total_cost']['unique_count']})",
                f"- grid_kwh span: {metrics['grid_kwh']['span']:.3f} (unique={metrics['grid_kwh']['unique_count']})",
                f"- wasted_kwh span: {metrics['wasted_kwh']['span']:.3f} (unique={metrics['wasted_kwh']['unique_count']})",
                f"- battery_charge_kwh span: {metrics['battery_charge_kwh']['span']:.3f} (unique={metrics['battery_charge_kwh']['unique_count']})",
                f"- battery_discharge_kwh span: {metrics['battery_discharge_kwh']['span']:.3f} (unique={metrics['battery_discharge_kwh']['unique_count']})",
                "",
            ]
        )
        # 选择差异最大的行。
        sorted_rows = sorted(
            data["rows"],
            key=lambda r: (
                0 if r["feasible"] else 1,
                r["resource_conflict_count"],
                r["effective_regen_loss_kwh"],
                r["grid_kwh"],
                r["total_cost"],
            ),
        )
        lines.append("| case | feasible | conflicts | effective_regen_loss_kwh | total_cost | grid_kwh | wasted_kwh | charge_kwh | discharge_kwh | final_soc_kwh |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        show = sorted_rows
        if len(show) > 8:
            show = sorted_rows[:3] + sorted_rows[-3:]
            # 去重并保持顺序。
            seen = set()
            compact = []
            for row in show:
                key = row["case_id"]
                if key not in seen:
                    seen.add(key)
                    compact.append(row)
            show = compact
        for row in show:
            lines.append(
                f"| {row['case_id']} | {row['feasible']} | {row['resource_conflict_count']} | "
                f"{row['effective_regen_loss_kwh']:.3f} | {row['total_cost']:.3f} | "
                f"{row['grid_kwh']:.3f} | {row['wasted_kwh']:.3f} | "
                f"{row['battery_charge_kwh']:.3f} | {row['battery_discharge_kwh']:.3f} | "
                f"{row['final_soc_kwh']:.3f} |"
            )
        lines.append("")

    # 根据区间跨度生成总体结论要点。
    phase_span = group_summary.get("phase_scan_h3300_e2700", {}).get("metrics", {})
    cap_span = group_summary.get("storage_capacity_scan", {}).get("metrics", {})
    power_span = group_summary.get("storage_power_scan", {}).get("metrics", {})
    waste_span = group_summary.get("waste_penalty_scan", {}).get("metrics", {})
    lines.extend(
        [
            "## Interpretation",
            "",
            f"- Phase scan energy flatness: grid span={phase_span.get('grid_kwh', {}).get('span', 'n/a')}, wasted span={phase_span.get('wasted_kwh', {}).get('span', 'n/a')}, cost span={phase_span.get('total_cost', {}).get('span', 'n/a')}.",
            f"- Storage capacity sensitivity: charge span={cap_span.get('battery_charge_kwh', {}).get('span', 'n/a')}, grid span={cap_span.get('grid_kwh', {}).get('span', 'n/a')}, cost span={cap_span.get('total_cost', {}).get('span', 'n/a')}.",
            f"- Storage power sensitivity: charge span={power_span.get('battery_charge_kwh', {}).get('span', 'n/a')}, grid span={power_span.get('grid_kwh', {}).get('span', 'n/a')}, cost span={power_span.get('total_cost', {}).get('span', 'n/a')}.",
            f"- Waste penalty sensitivity: cost span={waste_span.get('total_cost', {}).get('span', 'n/a')} with energy quantities expected unchanged.",
            "",
            "## Bottom Line",
            "",
            "- If phase/template groups show near-zero energy spans, schedule-only optimization cannot produce savings under current fixed power curves and storage zones.",
            "- If storage capacity/power groups show non-zero spans, energy KPIs are more limited by storage assumptions than by the NSGA-II search quality.",
            "- If only waste-penalty group changes total_cost, current cost equality is partly an objective/pricing setup issue.",
            "",
        ]
    )
    report_path = OUTPUT_DIR / "ENERGY_SENSITIVITY_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", detail_csv, flush=True)
    print("wrote", summary_json, flush=True)
    print("wrote", report_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
