# 模块功能说明：在完整能量评价前快速扫描重空调度的核心稳健资源可行区域。

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence
import argparse
import csv
import json
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resource_constraints import ResourceModel, check_schedule_resources
from rolling_optimizer import (
    DisturbanceScenario,
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    GeneratedSchedule,
    OBJECTIVE_MODE_BALANCED,
    OBJECTIVE_PRIORITY_ENERGY_FIRST,
    ScheduleTemplate,
    apply_scenario,
    default_scenarios,
    generate_schedule,
    robust_evaluate_schedule,
    targeted_resource_feasibility_repair_templates,
)
from run_dispatch_case import load_case_inputs, make_settlement_system
from scheduler_nsga2 import PowerSeriesCache, build_power_cache


DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "dispatch_robust_feasibility_probe"


@dataclass(frozen=True)
class FeasibilityProbeRow:
    """一个模板在核心扰动场景下的资源可行性摘要。"""

    heavy_count: int
    empty_count: int
    heavy_headway_s: int
    empty_headway_s: int
    effective_empty_offset_s: int
    flex_zone_hold_s: int
    robust_resource_feasible: bool
    total_conflict_count: int
    total_overlap_violation_s: float
    blocking_scenarios: str
    normal_conflicts: int
    heavy_delay_light_conflicts: int
    empty_delay_light_conflicts: int


def core_scenarios() -> tuple[DisturbanceScenario, ...]:
    """返回参与核心稳健可行性判定的扰动场景。"""

    return tuple(scenario for scenario in default_scenarios() if scenario.core_for_feasibility)


def resource_probe_row(
    template: ScheduleTemplate,
    *,
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> FeasibilityProbeRow:
    """使用项目正式资源检查器评价一个模板的核心稳健资源可行性。"""

    schedule = generate_schedule(template)
    conflicts_by_scenario: dict[str, int] = {}
    blocking: list[str] = []
    total_conflicts = 0
    total_overlap = 0.0
    for scenario in scenarios:
        disturbed = apply_scenario(schedule, scenario)
        result = check_schedule_resources(
            disturbed,
            resource_model,
            heavy_cache,
            empty_cache,
        )
        conflict_count = int(result.conflict_count)
        conflicts_by_scenario[scenario.name] = conflict_count
        total_conflicts += conflict_count
        total_overlap += float(result.overlap_violation_s)
        if not result.feasible:
            blocking.append(scenario.name)
    return FeasibilityProbeRow(
        heavy_count=template.heavy_count,
        empty_count=template.empty_count,
        heavy_headway_s=template.heavy_headway_s,
        empty_headway_s=template.empty_headway_s,
        effective_empty_offset_s=(
            template.heavy_empty_phase_s + template.storage_align_shift_s
        ),
        flex_zone_hold_s=template.flex_zone_hold_s,
        robust_resource_feasible=not blocking,
        total_conflict_count=total_conflicts,
        total_overlap_violation_s=round(total_overlap, 6),
        blocking_scenarios=";".join(blocking),
        normal_conflicts=conflicts_by_scenario.get("normal", 0),
        heavy_delay_light_conflicts=conflicts_by_scenario.get("heavy_delay_light", 0),
        empty_delay_light_conflicts=conflicts_by_scenario.get("empty_delay_light", 0),
    )


def scan_resource_feasibility(
    *,
    heavy_count: int,
    empty_count: int,
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    headways_s: Sequence[int],
    offset_step_s: int = 60,
    max_offset_s: int = 5400,
    horizon_s: int = 14400,
    hold_values_s: Sequence[int] = (0,),
) -> list[FeasibilityProbeRow]:
    """扫描可保持服务数量的相位和追踪间隔组合。"""

    if heavy_count <= 0 or empty_count <= 0:
        raise ValueError("重车和空车数量必须为正整数。")
    if offset_step_s <= 0 or max_offset_s < 0 or horizon_s <= 0:
        raise ValueError("相位步长和时域参数无效。")
    rows: list[FeasibilityProbeRow] = []
    scenarios = core_scenarios()
    for heavy_headway_s in headways_s:
        if (heavy_count - 1) * heavy_headway_s > horizon_s:
            continue
        for empty_headway_s in headways_s:
            latest_offset_s = min(
                max_offset_s,
                horizon_s - (empty_count - 1) * empty_headway_s,
            )
            if latest_offset_s < 0:
                continue
            for hold_s in hold_values_s:
                for offset_s in range(0, latest_offset_s + 1, offset_step_s):
                    template = ScheduleTemplate(
                        heavy_headway_s=heavy_headway_s,
                        empty_headway_s=empty_headway_s,
                        heavy_empty_phase_s=offset_s,
                        heavy_count=heavy_count,
                        empty_count=empty_count,
                        flex_zone_hold_s=hold_s,
                    )
                    rows.append(
                        resource_probe_row(
                            template,
                            scenarios=scenarios,
                            resource_model=resource_model,
                            heavy_cache=heavy_cache,
                            empty_cache=empty_cache,
                        )
                    )
    return sorted(
        rows,
        key=lambda row: (
            not row.robust_resource_feasible,
            row.total_overlap_violation_s,
            row.total_conflict_count,
            abs(row.heavy_headway_s - 3300) + abs(row.empty_headway_s - 2700),
            abs(row.effective_empty_offset_s - 2600),
        ),
    )


def write_probe_outputs(
    output_dir: Path,
    rows: Sequence[FeasibilityProbeRow],
    *,
    elapsed_s: float,
) -> dict:
    """写出完整扫描表和供后续完整评价使用的可行模板摘要。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "resource_feasibility_scan.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FeasibilityProbeRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    feasible_rows = [row for row in rows if row.robust_resource_feasible]
    summary = {
        "schema_version": "1.0",
        "data_status": "planning_and_placeholder_inputs",
        "elapsed_s": round(elapsed_s, 6),
        "evaluated_template_count": len(rows),
        "robust_resource_feasible_count": len(feasible_rows),
        "best_feasible_templates": [asdict(row) for row in feasible_rows[:20]],
        "best_near_feasible_templates": [asdict(row) for row in rows[:20]],
        "output_csv": str(csv_path),
        "interpretation": (
            "Resource-feasible templates are seeds for full robust energy/electrical evaluation; "
            "they are not final feasible solutions by themselves."
        ),
    }
    (output_dir / "probe_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def run_probe(
    *,
    data_dir: Path,
    output_dir: Path,
    heavy_count: int,
    empty_count: int,
    headways_s: Sequence[int],
    offset_step_s: int,
    max_offset_s: int,
    horizon_s: int,
) -> dict:
    """加载当前项目数据并执行资源可行性扫描。"""

    case_inputs = load_case_inputs(data_dir, output_dir)
    heavy_cache = build_power_cache(
        case_inputs.trains["Heavy"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    empty_cache = build_power_cache(
        case_inputs.trains["Empty"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    started = time.perf_counter()
    rows = scan_resource_feasibility(
        heavy_count=heavy_count,
        empty_count=empty_count,
        resource_model=case_inputs.resource_model,
        heavy_cache=heavy_cache,
        empty_cache=empty_cache,
        headways_s=headways_s,
        offset_step_s=offset_step_s,
        max_offset_s=max_offset_s,
        horizon_s=horizon_s,
    )
    return write_probe_outputs(
        output_dir,
        rows,
        elapsed_s=time.perf_counter() - started,
    )


def run_targeted_probe(
    *,
    data_dir: Path,
    output_dir: Path,
    heavy_count: int,
    empty_count: int,
    heavy_headway_s: int,
    empty_headway_s: int,
    phase_s: int,
    horizon_s: int,
    initial_scan_csv: Path | None = None,
    adjustment_step_s: int = 60,
    max_absolute_adjustment_s: int = 600,
    max_iterations: int = 8,
    beam_width: int = 6,
) -> dict:
    """从基线或既有全局扫描的近可行模板启动冲突驱动局部修复。"""

    case_inputs = load_case_inputs(data_dir, output_dir)
    heavy_cache = build_power_cache(
        case_inputs.trains["Heavy"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    empty_cache = build_power_cache(
        case_inputs.trains["Empty"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    initial_templates = [ScheduleTemplate(
        heavy_headway_s=heavy_headway_s,
        empty_headway_s=empty_headway_s,
        heavy_empty_phase_s=phase_s,
        heavy_count=heavy_count,
        empty_count=empty_count,
    )]
    if initial_scan_csv is not None and Path(initial_scan_csv).is_file():
        with Path(initial_scan_csv).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in list(csv.DictReader(handle))[:4]:
                initial_templates.append(ScheduleTemplate(
                    heavy_headway_s=int(row["heavy_headway_s"]),
                    empty_headway_s=int(row["empty_headway_s"]),
                    heavy_empty_phase_s=int(row["effective_empty_offset_s"]),
                    heavy_count=heavy_count,
                    empty_count=empty_count,
                    flex_zone_hold_s=int(row.get("flex_zone_hold_s", 0)),
                ))

    def schedule_in_window(template: ScheduleTemplate) -> GeneratedSchedule:
        schedule = generate_schedule(template)
        return GeneratedSchedule(
            heavy_departures_s=[time_s for time_s in schedule.heavy_departures_s if time_s <= horizon_s],
            empty_departures_s=[time_s for time_s in schedule.empty_departures_s if time_s <= horizon_s],
            template=template,
        )

    started = time.perf_counter()
    seeds, diagnostics = targeted_resource_feasibility_repair_templates(
        initial_templates,
        core_scenarios(),
        case_inputs.resource_model,
        heavy_cache,
        empty_cache,
        schedule_in_window,
        required_heavy_count=heavy_count,
        required_empty_count=empty_count,
        adjustment_step_s=adjustment_step_s,
        max_absolute_adjustment_s=max_absolute_adjustment_s,
        max_iterations=max_iterations,
        beam_width=beam_width,
    )
    full_robust_seed_evaluations = []
    if seeds:
        settlement_system = make_settlement_system(
            case_inputs.battery,
            case_inputs.route,
            settlement_step_s=10,
            initial_soc_kwh=0.0,
            target_final_soc_kwh=0.0,
            final_soc_tolerance_kwh=0.0,
            final_soc_penalty_per_kwh=0.05,
            wasted_energy_penalty_per_kwh=0.05,
            energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
            power_arm_limits=case_inputs.power_arm_limits,
        )
        min_depart_gap_s = max(
            300,
            int(case_inputs.resource_model.config.min_depart_headway_s),
        )
        for seed_rank, seed in enumerate(seeds, start=1):
            scenario_scores = []
            robust_score = robust_evaluate_schedule(
                schedule_in_window(seed),
                list(default_scenarios()),
                heavy_cache,
                empty_cache,
                settlement_system,
                case_inputs.route.signaling_system,
                resource_model=case_inputs.resource_model,
                storage_sections=case_inputs.storage_sections,
                min_depart_gap_s=min_depart_gap_s,
                target_gap_s=int(round((seed.heavy_headway_s + seed.empty_headway_s) / 2.0)),
                objective_mode=OBJECTIVE_MODE_BALANCED,
                energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
                objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST,
                disturbance_from_time_s=0,
                scenario_score_sink=scenario_scores,
            )
            full_robust_seed_evaluations.append({
                "seed_rank": seed_rank,
                "feasible": bool(robust_score.feasible),
                "constraint_violation": round(float(robust_score.constraint_violation), 6),
                "resource_conflict_count": int(robust_score.resource_conflict_count),
                "signal_violation_count": int(robust_score.signal_violation_count),
                "electrical_constraint_violation_kwh": round(
                    float(robust_score.electrical_constraint_violation_kwh), 6
                ),
                "final_soc_shortfall_kwh": round(
                    float(robust_score.final_soc_shortfall_kwh), 6
                ),
                "scenario_results": [
                    {
                        "scenario": scenario.name,
                        "core_for_feasibility": bool(scenario.core_for_feasibility),
                        "feasible": bool(score.feasible),
                        "constraint_violation": round(float(score.constraint_violation), 6),
                        "resource_conflict_count": int(score.resource_conflict_count),
                        "signal_violation_count": int(score.signal_violation_count),
                        "electrical_constraint_violation_kwh": round(
                            float(score.electrical_constraint_violation_kwh), 6
                        ),
                        "final_soc_shortfall_kwh": round(
                            float(score.final_soc_shortfall_kwh), 6
                        ),
                    }
                    for scenario, score in scenario_scores
                ],
            })
    output_dir.mkdir(parents=True, exist_ok=True)
    seed_rows = []
    for index, seed in enumerate(seeds, start=1):
        schedule = generate_schedule(seed)
        seed_rows.append({
            "seed_rank": index,
            "heavy_headway_s": seed.heavy_headway_s,
            "empty_headway_s": seed.empty_headway_s,
            "phase_s": seed.heavy_empty_phase_s,
            "heavy_departure_adjustments_s": json.dumps(list(seed.heavy_departure_adjustments_s)),
            "empty_departure_adjustments_s": json.dumps(list(seed.empty_departure_adjustments_s)),
            "heavy_departures_s": json.dumps(schedule.heavy_departures_s),
            "empty_departures_s": json.dumps(schedule.empty_departures_s),
        })
    seed_csv = output_dir / "targeted_resource_feasible_seeds.csv"
    if seed_rows:
        with seed_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(seed_rows[0]))
            writer.writeheader()
            writer.writerows(seed_rows)
    summary = {
        "schema_version": "1.0",
        "data_status": "planning_and_placeholder_inputs",
        "mode": "conflict_driven_local_departure_repair",
        "elapsed_s": round(time.perf_counter() - started, 6),
        "initial_template_count": len(initial_templates),
        **diagnostics,
        "full_robust_seed_evaluations": full_robust_seed_evaluations,
        "seed_csv": str(seed_csv) if seed_rows else None,
    }
    (output_dir / "targeted_probe_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立命令行入口。"""

    parser = argparse.ArgumentParser(description="扫描重空调度核心稳健资源可行区域。")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--heavy-count", type=int, default=3)
    parser.add_argument("--empty-count", type=int, default=3)
    parser.add_argument("--headways-s", nargs="+", type=int, default=[2700, 3000, 3300, 3600, 3900, 4200])
    parser.add_argument("--offset-step-s", type=int, default=60)
    parser.add_argument("--max-offset-s", type=int, default=5400)
    parser.add_argument("--horizon-s", type=int, default=14400)
    parser.add_argument("--targeted-local", action="store_true")
    parser.add_argument("--heavy-headway-s", type=int, default=3300)
    parser.add_argument("--empty-headway-s", type=int, default=2700)
    parser.add_argument("--phase-s", type=int, default=2600)
    parser.add_argument("--initial-scan-csv", type=Path)
    parser.add_argument("--adjustment-step-s", type=int, default=60)
    parser.add_argument("--max-absolute-adjustment-s", type=int, default=600)
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--beam-width", type=int, default=6)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """执行探针并打印关键结果。"""

    args = build_parser().parse_args(argv)
    if args.targeted_local:
        summary = run_targeted_probe(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            heavy_count=args.heavy_count,
            empty_count=args.empty_count,
            heavy_headway_s=args.heavy_headway_s,
            empty_headway_s=args.empty_headway_s,
            phase_s=args.phase_s,
            horizon_s=args.horizon_s,
            initial_scan_csv=args.initial_scan_csv,
            adjustment_step_s=args.adjustment_step_s,
            max_absolute_adjustment_s=args.max_absolute_adjustment_s,
            max_iterations=args.max_iterations,
            beam_width=args.beam_width,
        )
    else:
        summary = run_probe(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            heavy_count=args.heavy_count,
            empty_count=args.empty_count,
            headways_s=args.headways_s,
            offset_step_s=args.offset_step_s,
            max_offset_s=args.max_offset_s,
            horizon_s=args.horizon_s,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
