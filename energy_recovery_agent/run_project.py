# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Unified command-line entry for the current project workflow.

This file is intentionally a thin wrapper around the existing module-level
entry points. It keeps daily commands consistent without hiding the original
scripts that are still useful for focused reproduction and debugging.
"""

from pathlib import Path
from typing import Optional, Sequence, Tuple
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_SOURCE_DIR = Path("data") / "source"
DEFAULT_SMART_METER_DIR = DEFAULT_SOURCE_DIR / "smart_meter"
DEFAULT_TIMETABLE = Path("data_templates") / "running_diagram_template.xlsx"
DEFAULT_STORAGE_PLANNING_TIMETABLE = (
    Path(__file__).resolve().parent.parent
    / "shared_data"
    / "runtime"
    / "storage_planning"
    / "measured_20260613"
    / "mixed_running_diagram.xlsx"
)
if not DEFAULT_STORAGE_PLANNING_TIMETABLE.is_file():
    DEFAULT_STORAGE_PLANNING_TIMETABLE = DEFAULT_TIMETABLE
DEFAULT_HEAVY_EMPTY_TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
DEFAULT_OUTPUT_ROOT = Path("outputs")
DEFAULT_POWER_ARM_PATH = DEFAULT_DATA_DIR / "power_arm_intervals.csv"
DEFAULT_REPRESENTATIVE_METER_SAMPLES = DEFAULT_OUTPUT_ROOT / "smart_meter_representative_interval_samples.csv"
LONG_SMOKE_STEMS = {
    "verify_heavy_empty_network_optimizer",
    "verify_rolling_optimizer_constraints",
    "verify_timetable_optimizer_nsga2",
    "verify_timetable_resource_constraints",
    "verify_dispatch_output_path",
}


def _dispatch_output_dir(args: argparse.Namespace) -> Path:
    """Return a non-colliding default dispatch output directory.

    The default path historically contained ``phase2600`` even when callers
    overrode ``--baseline-phase-s``. That allowed a second scenario to
    silently overwrite the first scenario's report. Keep the established
    default for the default phase, but derive the phase suffix for overrides;
    an explicitly different ``--output-dir`` always wins.
    """

    requested = Path(args.output_dir)
    mode = str(getattr(args, "optimization_mode", "joint_energy_planning"))
    default_stem = "dispatch_no_storage_phase2600" if mode == "dispatch_only" else "dispatch_storage_no_direct_phase2600"
    default_path = DEFAULT_OUTPUT_ROOT / default_stem
    phase_s = int(args.baseline_phase_s)
    if requested == default_path and phase_s != 2600:
        stem = "dispatch_no_storage" if mode == "dispatch_only" else "dispatch_storage_no_direct"
        return requested.parent / f"{stem}_phase{phase_s}"
    return requested


def _print_summary(title: str, summary: object) -> None:
    """函数 _print_summary：执行该模块中的相关处理逻辑。"""
    print(f"=== {title} ===")
    if isinstance(summary, (dict, list)):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(summary)


def _related_data_path(args: argparse.Namespace, attr_name: str, filename: str, data_attr: str = "data_dir") -> Path:
    """函数 _related_data_path：执行该模块中的相关处理逻辑。"""
    explicit = getattr(args, attr_name, None)
    if explicit is not None:
        return Path(explicit)
    return Path(getattr(args, data_attr, DEFAULT_DATA_DIR)) / filename


def cmd_build_data(args: argparse.Namespace) -> int:
    """函数 cmd_build_data：执行该模块中的相关处理逻辑。"""
    from tools.build_real_shuohuang_dataset import main as build_main

    build_main(args.data_dir, args.source_dir)
    return 0


def cmd_validate_data(args: argparse.Namespace) -> int:
    """函数 cmd_validate_data：执行该模块中的相关处理逻辑。"""
    from data_quality_validator import validate_all, write_report

    report = validate_all(
        args.data_dir,
        args.source_dir,
        args.timetable,
        require_official_data=getattr(args, "require_official_data", False),
    )
    write_report(report, args.output_dir)
    summary = report.summary()
    _print_summary(
        "数据质量",
        {
            "valid": report.is_valid,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "blocking_flows": summary.get("blocking_flows", []),
            "output_dir": str(args.output_dir),
        },
    )
    return 0 if report.is_valid else 1


def cmd_validate_storage_planning(args: argparse.Namespace) -> int:
    """校验储能选址定容阶段A输入合同并写出质量报告。"""
    from storage_planning_contract import write_storage_planning_validation_report

    summary = write_storage_planning_validation_report(
        args.input_dir,
        args.output_dir,
        args.power_arm_path,
    )
    _print_summary(
        "储能规划输入契约",
        {
            "valid": summary["valid"],
            "error_count": summary["error_count"],
            "site_count": summary.get("site_count", 0),
            "technology_count": summary.get("technology_count", 0),
            "scenario_count": summary.get("scenario_count", 0),
            "power_arm_reference_check_applied": summary.get("power_arm_reference_check_applied", False),
            "recommendation_level": summary.get("recommendation_level"),
            "input_fingerprint_sha256": summary.get("input_fingerprint_sha256"),
            "summary_path": summary["summary_path"],
            "issues_path": summary["issues_path"],
        },
    )
    return 0 if summary["valid"] else 1


def cmd_run_storage_planning(args: argparse.Namespace) -> int:
    """执行固定运行图下的储能选址定容阶段B MVP。"""

    from storage_planning_mvp import run_storage_planning_mvp
    from database.planning import validate_planning_directory
    validate_planning_directory(args.input_dir, {
        "planning_policy_code": args.planning_policy_code,
        "scenario_set_code": args.scenario_set_code,
    }, check_codes=bool(args.planning_policy_code or args.scenario_set_code),
       power_arm_path=args.power_arm_path or args.data_dir / "power_arm_intervals.csv")

    summary = run_storage_planning_mvp(
        args.input_dir,
        args.data_dir,
        args.output_dir,
        power_arm_path=args.power_arm_path,
        max_levels_per_dimension=args.max_levels_per_dimension,
        settlement_step_s=args.settlement_step_s,
        search_mode=args.search_mode,
        refinement_shortlist_size=args.refinement_shortlist_size,
        expected_policy_code=getattr(args, "planning_policy_code", None),
        expected_scenario_set_code=getattr(args, "scenario_set_code", None),
    )
    selected = summary["selected_plan"]
    _print_summary(
        "储能选址与定容规划",
        {
            "decision": summary["decision"],
            "selected_plan_id": selected["plan_id"],
            "selected_sites": selected["site_codes"],
            "annual_saving_cny": selected["annual_saving_vs_no_build_cny"],
            "grid_reduction_kwh_per_year": selected["grid_reduction_vs_no_build_kwh_per_year"],
            "recommendation_level": summary["recommendation_level"],
            "search_status": summary["search_status"],
            "complete_for_declared_domain": summary["declared_search_domain"]["complete_for_declared_domain"],
            "output_dir": str(args.output_dir),
        },
    )
    return 0 if summary["declared_search_domain"]["complete_for_declared_domain"] else 1


def cmd_plan_storage_mixed(args: argparse.Namespace) -> int:
    """由当前混合数据生成规划输入并立即运行选址定容。"""

    from storage_planning_mixed import build_storage_planning_mixed_inputs
    from storage_planning_mvp import run_storage_planning_mvp

    input_summary = build_storage_planning_mixed_inputs(args.data_dir, args.timetable, args.input_dir)
    summary = run_storage_planning_mvp(
        args.input_dir,
        args.data_dir,
        args.output_dir,
        max_levels_per_dimension=args.max_levels_per_dimension,
        settlement_step_s=args.settlement_step_s,
        search_mode=args.search_mode,
        refinement_shortlist_size=args.refinement_shortlist_size,
    )
    selected = summary["selected_plan"]
    _print_summary("储能规划混合数据闭环", {
        "input_valid": input_summary["valid"],
        "candidate_site_count": input_summary["site_count"],
        "decision": summary["decision"],
        "selected_sites": selected["site_codes"],
        "total_capacity_kwh": selected["total_capacity_kwh"],
        "total_charge_power_kw": selected["total_charge_power_kw"],
        "total_discharge_power_kw": selected["total_discharge_power_kw"],
        "recommendation_level": summary["recommendation_level"],
        "search_status": summary["search_status"],
        "complete_for_declared_domain": summary["declared_search_domain"]["complete_for_declared_domain"],
        "input_dir": str(args.input_dir),
        "output_dir": str(args.output_dir),
    })
    return 0 if summary["declared_search_domain"]["complete_for_declared_domain"] else 1


def cmd_assess_storage_credibility(args: argparse.Namespace) -> int:
    """执行储能规划参数敏感性、推荐稳定性和质量门禁。"""

    from storage_planning_credibility import run_storage_planning_credibility

    summary = run_storage_planning_credibility(
        args.data_dir,
        args.timetable,
        args.output_dir,
        settlement_step_s=args.settlement_step_s,
    )
    _print_summary("储能规划可信度第三轮", {
        "case_count": summary["case_count"],
        "all_quality_gates_passed": summary["all_quality_gates_passed"],
        "stability_grade": summary["stability"]["stability_grade"],
        "decision_counts": summary["stability"]["decision_counts"],
        "recommendation_level": summary["recommendation_level"],
        "output_dir": str(args.output_dir),
    })
    return 0 if summary["all_quality_gates_passed"] else 1


def cmd_calibrate_energy(args: argparse.Namespace) -> int:
    """函数 cmd_calibrate_energy：执行该模块中的相关处理逻辑。"""
    from run_energy_calibration_pipeline import run_pipeline
    from smart_meter_time_matcher import IntervalOverlapError

    try:
        summary = run_pipeline(
            smart_meter_dir=args.smart_meter_dir,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            boundary_tolerance_s=args.boundary_tolerance_s,
            energy_tolerance=args.energy_tolerance,
            max_interval_rows_per_file=args.max_interval_rows_per_file,
            max_realtime_rows_per_file=args.max_realtime_rows_per_file,
            overlap_policy=args.overlap_policy,
            representative_samples=args.representative_samples,
            max_per_realtime_trainid=args.max_per_realtime_trainid,
            publish_calibration=getattr(args, "publish_calibration", False),
            restrict_to_realtime_coverage=not getattr(args, "no_restrict_to_realtime_coverage", False),
            mainline_only=not getattr(args, "no_mainline_only", False),
            min_fit_samples=getattr(args, "min_fit_samples", 30),
            min_validation_samples=getattr(args, "min_validation_samples", 10),
            validation_fraction=getattr(args, "validation_fraction", 0.20),
            validation_model=getattr(args, "validation_model", "grouped"),
            validation_alignment_csv=getattr(args, "validation_alignment_csv", None),
            max_median_ape_pct=getattr(args, "max_median_ape_pct", 30.0),
            max_p90_ape_pct=getattr(args, "max_p90_ape_pct", 60.0),
            max_wape_pct=getattr(args, "max_wape_pct", 30.0),
            min_scale=getattr(args, "min_scale", 0.2),
            max_scale=getattr(args, "max_scale", 5.0),
        )
    except IntervalOverlapError as exc:
        first = exc.overlaps[0] if exc.overlaps else None
        _print_summary(
            "能耗校准受阻",
            {
                "valid": False,
                "reason": "nhtj_jkfile_station 中同一 trainid 存在重叠任务。",
                "rule": "在重叠被解释或清洗前，不得生成智能电表时间匹配、校准样本与校准系数。",
                "overlap_count": len(exc.overlaps),
                "first_overlap": None
                if first is None
                else {
                    "trainid": first.trainid,
                    "left": f"{first.left_source_file}:{first.left_source_row}",
                    "right": f"{first.right_source_file}:{first.right_source_row}",
                },
            },
        )
        return 1
    _print_summary(
        "能耗校准",
        {
            "valid": summary.get("valid", False),
            "status": summary.get("status", "unknown"),
            "publication_status": summary.get("publication_status", "not_requested"),
            "match_count": summary["time_matching"]["match_count"],
            "candidate_count": summary["match_analysis"]["candidate_count"],
            "sample_count": summary["calibration_samples"]["sample_count"],
            "fit_sample_count": summary["quality_audit"]["fit_sample_count"],
            "validation_sample_count": summary["quality_audit"]["validation_sample_count"],
            "publication_ready": summary["publication_ready"],
            "failed_quality_checks": summary["quality_audit"]["failed_checks"],
            "output_dir": str(args.output_dir),
        },
    )
    return 0 if summary.get("valid", False) else 2


def cmd_meter_samples(args: argparse.Namespace) -> int:
    """函数 cmd_meter_samples：执行该模块中的相关处理逻辑。"""
    from energy_calibration_alignment import build_alignment
    from smart_meter_representative_sampler import build_representative_samples

    sample_summary = build_representative_samples(
        args.smart_meter_dir,
        args.output_csv,
        max_per_normalized_trainid=args.max_per_normalized_trainid,
        max_realtime_rows_per_file=args.max_realtime_rows_per_file,
    )
    station_csv = _related_data_path(args, "station_csv", "stations.csv")
    factor_json = _related_data_path(args, "factor_json", "energy_calibration_factors.json")
    alignment_summary = build_alignment(
        args.output_csv,
        station_csv,
        args.alignment_output_dir,
        energy_calibration_mode=args.energy_calibration_mode,
        factor_json=factor_json,
        infrastructure_data_dir=getattr(args, "data_dir", DEFAULT_DATA_DIR),
    )
    _print_summary(
        "智能电表代表性样本",
        {
            "sample_count": sample_summary["sample_count"],
            "sample_counts_by_normalized_trainid": sample_summary["sample_counts_by_normalized_trainid"],
            "sample_counts_by_source_table": sample_summary["sample_counts_by_source_table"],
            "aligned_count": alignment_summary["alignment_status_counts"].get("aligned", 0),
            "zero_distance_count": alignment_summary["alignment_status_counts"].get("zero_distance", 0),
            "station_unmapped_count": alignment_summary["alignment_status_counts"].get("station_unmapped", 0),
            "output_csv": str(args.output_csv),
            "alignment_output_dir": str(args.alignment_output_dir),
        },
    )
    return 0


def cmd_audit_timetable(args: argparse.Namespace) -> int:
    """函数 cmd_audit_timetable：执行该模块中的相关处理逻辑。"""
    from timetable_energy_audit import audit_timetable

    power_arm_path = _related_data_path(args, "power_arm_path", "power_arm_intervals.csv")
    summary = audit_timetable(
        args.timetable,
        args.output_dir,
        power_arm_path,
        strict_visualizations=getattr(args, "strict_visualizations", False),
        infrastructure_data_dir=getattr(args, "data_dir", DEFAULT_DATA_DIR),
        settlement_time_step_s_override=getattr(args, "settlement_time_step_s", None),
    )
    _print_summary("运行图能耗审查", summary)
    return 0 if summary.get("valid", False) else 1


def cmd_optimize_timetable(args: argparse.Namespace) -> int:
    """函数 cmd_optimize_timetable：执行该模块中的相关处理逻辑。"""
    from timetable_optimizer import optimize_timetable

    power_arm_path = _related_data_path(
        args,
        "power_arm_path",
        "power_arm_intervals.csv",
        data_attr="resource_data_dir",
    )
    summary = optimize_timetable(
        args.timetable,
        args.output_dir,
        power_arm_path=power_arm_path,
        max_shift_min=args.max_shift_min,
        step_min=args.step_min,
        max_dwell_extension_min=args.max_dwell_extension_min,
        max_candidates=args.max_candidates,
        mode=args.mode,
        population_size=args.population_size,
        generations=args.generations,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        seed=args.seed,
        resource_data_dir=getattr(args, "resource_data_dir", DEFAULT_DATA_DIR),
        strict_visualizations=getattr(args, "strict_visualizations", False),
    )
    _print_summary("运行图优化", summary)
    return 0 if summary.get("valid", False) else 1


def cmd_explain_optimization(args: argparse.Namespace) -> int:
    """为既有优化结果补生成收益归因与瓶颈解释工件。"""
    from tools.generate_optimization_attribution import generate

    summary = generate(args.result_dir, args.workflow, force=args.force)
    _print_summary(
        "优化归因",
        {
            "workflow": summary["workflow"],
            "decision": summary["decision"],
            "counts": summary["counts"],
            "report": str(args.result_dir / "OPTIMIZATION_ATTRIBUTION_REPORT.md"),
        },
    )
    return 0


def cmd_dispatch_case(args: argparse.Namespace) -> int:
    """函数 cmd_dispatch_case：执行该模块中的相关处理逻辑。"""
    from run_dispatch_case import main as dispatch_main

    if (
        str(getattr(args, "optimization_mode", "dispatch_only")) == "dispatch_only"
        and Path(args.output_dir) == DEFAULT_OUTPUT_ROOT / "dispatch_storage_no_direct_phase2600"
    ):
        args.output_dir = DEFAULT_OUTPUT_ROOT / "dispatch_no_storage_phase2600"
    output_dir = _dispatch_output_dir(args)

    argv = [
        "--optimization-mode",
        str(getattr(args, "optimization_mode", "dispatch_only")),
        "--input",
        str(args.data_dir),
        "--output-dir",
        str(output_dir),
        "--energy-scenario",
        args.energy_scenario,
        "--objective-mode",
        args.objective_mode,
        "--objective-priority",
        str(getattr(args, "objective_priority", "energy_first")),
        "--search-profile",
        str(getattr(args, "search_profile", "standard")),
        "--search-method",
        args.search_method,
        "--population-size",
        str(args.population_size),
        "--generations",
        str(args.generations),
        "--seed",
        str(args.seed),
        "--heavy-count",
        str(args.heavy_count),
        "--empty-count",
        str(args.empty_count),
        "--baseline-phase-s",
        str(args.baseline_phase_s),
        "--baseline-heavy-headway-s",
        str(getattr(args, "baseline_heavy_headway_s", 3300)),
        "--baseline-empty-headway-s",
        str(getattr(args, "baseline_empty_headway_s", 2700)),
        "--min-depart-gap-s",
        str(args.min_depart_gap_s),
        "--horizon-s",
        str(getattr(args, "horizon_s", 14400)),
        "--execute-window-s",
        str(getattr(args, "execute_window_s", 1800)),
        "--settlement-step-s",
        str(args.settlement_step_s),
        "--wasted-energy-penalty-per-kwh",
        str(getattr(args, "wasted_energy_penalty_per_kwh", 0.0)),
        "--storage-shift-mutation-s",
        str(getattr(args, "storage_shift_mutation_s", 300)),
        "--search-max-storage-align-shift-s",
        str(getattr(args, "search_max_storage_align_shift_s", 1200)),
        "--search-max-hold-s",
        str(getattr(args, "search_max_hold_s", 900)),
        "--search-max-phase-s",
        str(getattr(args, "search_max_phase_s", 5400)),
        "--phase-mutation-s",
        str(getattr(args, "phase_mutation_s", 300)),
        "--hold-mutation-s",
        str(getattr(args, "hold_mutation_s", 180)),
        "--headway-mutation-s",
        str(getattr(args, "headway_mutation_s", 300)),
        "--search-min-headway-s",
        str(getattr(args, "search_min_headway_s", 2400)),
        "--search-max-headway-s",
        str(getattr(args, "search_max_headway_s", 4200)),
        "--elite-count",
        str(getattr(args, "elite_count", 4)),
    ]
    if getattr(args, "disable_energy_observability", False):
        argv.append("--disable-energy-observability")
    elif getattr(args, "enable_energy_observability", True):
        argv.append("--enable-energy-observability")
    if getattr(args, "disable_storage_preset_search", False):
        argv.append("--disable-storage-preset-search")
    elif getattr(args, "enable_storage_preset_search", True):
        argv.append("--enable-storage-preset-search")
    if getattr(args, "storage_preset_ids", None):
        argv.extend(["--storage-preset-ids", str(args.storage_preset_ids)])
    if args.empty_mass_tons is not None:
        argv.extend(["--empty-mass-tons", str(args.empty_mass_tons)])
    if args.battery_capacity_kwh is not None:
        argv.extend(["--battery-capacity-kwh", str(args.battery_capacity_kwh)])
    if args.battery_max_charge_power_kw is not None:
        argv.extend(["--battery-max-charge-power-kw", str(args.battery_max_charge_power_kw)])
    if args.battery_max_discharge_power_kw is not None:
        argv.extend(["--battery-max-discharge-power-kw", str(args.battery_max_discharge_power_kw)])
    if args.battery_round_trip_efficiency is not None:
        argv.extend(["--battery-round-trip-efficiency", str(args.battery_round_trip_efficiency)])
    if getattr(args, "battery_depreciation_per_kwh", None) is not None:
        argv.extend(["--battery-depreciation-per-kwh", str(args.battery_depreciation_per_kwh)])
    if getattr(args, "battery_grid_price_per_kwh", None) is not None:
        argv.extend(["--battery-grid-price-per-kwh", str(args.battery_grid_price_per_kwh)])
    return dispatch_main(argv)


def cmd_heavy_empty_plan(args: argparse.Namespace) -> int:
    """运行重空协同运行图优化主流程，产出五类业务输出（工作区级正式产物）。"""

    from dataclasses import replace as _dataclass_replace

    from heavy_empty_network_optimizer import (
        DISPATCH_SCHEME_OUTPUT_FILES,
        load_he_input_template,
        optimize_heavy_empty_network,
        write_optimization_outputs,
    )

    template = Path(args.template)
    data_dir = Path(args.data_dir)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    bundle = load_he_input_template(template, real_data_dir=data_dir)
    available = sorted(bundle.scenarios)
    requested = list(args.scenario_id) if args.scenario_id else available
    unknown = [name for name in requested if name not in bundle.scenarios]
    if unknown:
        print(f"未知的重空车场景：{unknown}；可选场景：{available}")
        return 2

    if args.population_size or args.generations:
        bundle = _dataclass_replace(
            bundle,
            scenarios={
                name: _dataclass_replace(
                    scenario,
                    population_size=args.population_size or scenario.population_size,
                    generations=args.generations or scenario.generations,
                )
                for name, scenario in bundle.scenarios.items()
            },
        )

    manifest: dict[str, object] = {
        "command": "heavy-empty-plan",
        "template": str(template),
        "data_dir": str(data_dir),
        "output_root": str(output_root),
        "scheme_output_files": list(DISPATCH_SCHEME_OUTPUT_FILES),
        "scenarios": {},
    }
    for scenario_id in requested:
        result = optimize_heavy_empty_network(bundle, scenario_id=scenario_id)
        scenario_dir = output_root / scenario_id
        write_optimization_outputs(result, scenario_dir, bundle=bundle)
        manifest["scenarios"][scenario_id] = {
            "output_dir": str(scenario_dir),
            "feasible": bool(result.best_candidate.feasible),
            "candidate_count": len(result.candidates),
            "pareto_candidate_count": len(result.pareto_candidates),
            "best_candidate_id": result.best_candidate.candidate_id,
            "scheme_outputs": {
                name: str(scenario_dir / name) for name in DISPATCH_SCHEME_OUTPUT_FILES
            },
        }
        print(
            f"重空车方案场景 {scenario_id}："
            f"最优候选={result.best_candidate.candidate_id} 可行={result.best_candidate.feasible} "
            f"-> {scenario_dir}"
        )
    manifest_path = output_root / "heavy_empty_plan_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"重空车方案清单：{manifest_path}")
    return 0


def cmd_validation(args: argparse.Namespace) -> int:
    """执行技术方案 4.1.2.4 的四类验证场景，产出 outputs/validation/ 对照结果。"""

    from heavy_empty_validation_suite import (
        DEFAULT_SCENARIO_ID,
        load_he_input_template,
        run_validation_suite,
    )

    template = Path(args.template)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    scenario_id = args.scenario_id or DEFAULT_SCENARIO_ID

    bundle = load_he_input_template(template, real_data_dir=data_dir)
    summary = run_validation_suite(bundle, output_dir, scenario_id=scenario_id)
    print(
        "校验场景："
        + "、".join(summary["scenarios"])
        + f"；场景四={summary['scenario_4']['status']} -> {output_dir}"
    )
    print(f"校验汇总：{output_dir / 'validation_summary.json'}")
    return 0


def cmd_sensitivity(args: argparse.Namespace) -> int:
    """执行技术方案 4.2.1.2(1) 敏感性与稳健性情景集，产出 outputs/sensitivity/。"""

    from heavy_empty_network_optimizer import load_he_input_template
    from heavy_empty_sensitivity_suite import DEFAULT_SCENARIO_ID, run_sensitivity_suite

    template = Path(args.template)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    scenario_id = args.scenario_id or DEFAULT_SCENARIO_ID

    bundle = load_he_input_template(template, real_data_dir=data_dir)
    summary = run_sensitivity_suite(
        bundle,
        output_dir,
        scenario_id=scenario_id,
        population_size=args.population_size,
        generations=args.generations,
    )
    high = [
        row["section_key"]
        for row in summary["high_sensitivity_sections"]
        if row["is_high_sensitivity"]
    ]
    print(
        f"敏感性场景数：{summary['scenario_count']}；"
        f"高敏感区段：{high or '无'} -> {output_dir}"
    )
    print(f"敏感性汇总：{output_dir / 'sensitivity_summary.json'}")
    return 0


def cmd_algorithm_benchmark(args: argparse.Namespace) -> int:
    """执行算法规模、跨种子稳定性和同种子复现基准。"""
    from tools.algorithm_scale_stability_benchmark import run_benchmark

    summary = run_benchmark(
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        timetable=args.timetable,
        targets=args.targets or ("timetable", "dispatch"),
        scales=args.scales,
        seeds=args.seeds,
        reference_scale=args.reference_scale,
        replay_count=args.replay_count,
        population_size=args.population_size,
        generations=args.generations,
        timeout_s=args.timeout_s,
        stability_timeout_s=args.stability_timeout_s,
        timetable_copy_shift_s=args.timetable_copy_shift_s,
        min_seed_feasible_rate=args.min_seed_feasible_rate,
        max_seed_objective_cv=args.max_seed_objective_cv,
    )
    _print_summary("算法规模与稳定性基准", {
        "accepted": summary["accepted"],
        "run_count": summary["run_count"],
        "failed_checks": summary["failed_checks"],
        "report": str(args.output_dir / "ALGORITHM_SCALE_STABILITY_REPORT.md"),
    })
    return 0 if summary["accepted"] else 2


def cmd_random_synthetic_differential(args: argparse.Namespace) -> int:
    """执行随机合成案例的独立参考实现差分测试。"""
    from tools.random_synthetic_differential import run_differential_tests

    summary = run_differential_tests(
        args.output_dir,
        seeds=args.seeds,
        energy_cases=args.energy_cases,
        time_slicing_cases=args.time_slicing_cases,
        resource_cases=args.resource_cases,
        pareto_cases=args.pareto_cases,
    )
    _print_summary("随机合成差分测试", {
        "passed": summary["passed"],
        "total_case_count": summary["total_case_count"],
        "failed_count": summary["failed_count"],
        "case_set_sha256": summary["case_set_sha256"],
        "report": str(args.output_dir / "RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md"),
    })
    return 0 if summary["passed"] else 1


def cmd_realtime_state_anomaly_matrix(args: argparse.Namespace) -> int:
    """执行实时状态异常注入、可信状态保护和滚动恢复矩阵。"""
    from tools.realtime_state_anomaly_matrix import run_matrix

    summary = run_matrix(args.output_dir)
    _print_summary("实时状态异常矩阵", {
        "passed": summary["passed"],
        "case_count": summary["case_count"],
        "failed_count": summary["failed_count"],
        "report": str(args.output_dir / "REALTIME_STATE_ANOMALY_MATRIX_REPORT.md"),
    })
    return 0 if summary["passed"] else 1


def cmd_verify_interface_contract(args: argparse.Namespace) -> int:
    """核验平台数据库接口冻结清单和当前实现的一致性。"""
    from tools.verify_interface_contract_freeze import _write_report, verify_contract

    result = verify_contract(Path(__file__).resolve().parent)
    _write_report(args.output_dir, result)
    _print_summary("接口契约冻结", {
        "freeze_version": result["freeze_version"],
        "status": result["status"],
        "check_count": result["check_count"],
        "failed_count": result["failed_count"],
        "report": str(args.output_dir / "INTERFACE_CONTRACT_FREEZE_REPORT.md"),
    })
    return 0 if result["status"] == "PASS" else 1


def cmd_synthetic_data_anomaly_matrix(args: argparse.Namespace) -> int:
    """执行合成输入数据包异常注入和统一校验门禁矩阵。"""
    from tools.synthetic_data_anomaly_matrix import run_matrix

    summary = run_matrix(args.source_dir, args.output_dir)
    _print_summary("合成数据异常矩阵", {
        "passed": summary["passed"],
        "case_count": summary["case_count"],
        "failed_count": summary["failed_count"],
        "baseline_unchanged": summary["baseline_unchanged"],
        "report": str(args.output_dir / "SYNTHETIC_DATA_ANOMALY_REPORT.md"),
    })
    return 0 if summary["passed"] else 1


def cmd_abnormal_extreme_input_suite(args: argparse.Namespace) -> int:
    """执行静态、平台、实时、核心极端和随机差分总验收。"""
    from tools.abnormal_extreme_input_suite import run_suite

    summary = run_suite(
        args.output_dir,
        seeds=args.seeds,
        energy_cases=args.energy_cases,
        time_slicing_cases=args.time_slicing_cases,
        resource_cases=args.resource_cases,
        pareto_cases=args.pareto_cases,
    )
    _print_summary("异常与极端输入测试集", {
        "passed": summary["passed"],
        "enumerated_case_count": summary["enumerated_case_count"],
        "failed_component_count": summary["failed_component_count"],
        "report": str(args.output_dir / "ABNORMAL_EXTREME_INPUT_TEST_REPORT.md"),
    })
    return 0 if summary["passed"] else 1


def cmd_platform_task_stress_fault(args: argparse.Namespace) -> int:
    """在专用测试库中执行平台任务压力与故障测试。"""
    from tools.platform_task_stress_fault import run_stress_fault_test

    database_url = os.environ.get("SIMULATION_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("必须设置SIMULATION_TEST_DATABASE_URL；统一入口不会接收或记录数据库连接串。")
    summary = run_stress_fault_test(
        database_url,
        output_dir=args.output_dir,
        task_count=args.task_count,
        worker_count=args.worker_count,
        idempotency_burst=args.idempotency_burst,
        max_operation_p95_ms=args.max_operation_p95_ms,
        min_claim_throughput_per_s=args.min_claim_throughput_per_s,
    )
    _print_summary("平台任务压力与故障测试", {
        "passed": summary["passed"],
        "task_count": summary["pressure"]["configuration"]["task_count"],
        "claim_throughput_per_s": summary["pressure"]["claim_throughput_per_s"],
        "fault_cases": summary["fault_injection"],
        "report": str(args.output_dir / "PLATFORM_TASK_STRESS_FAULT_REPORT.md"),
    })
    return 0 if summary["passed"] else 1


def cmd_dispatch_capacity_benchmark(args: argparse.Namespace) -> int:
    """执行重空协同调度容量边界和搜索预算质量基准。"""
    from tools.dispatch_capacity_quality_benchmark import run_benchmark

    summary = run_benchmark(
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        scales=args.scales,
        reference_scale=args.reference_scale,
        seed=args.seed,
        timeout_s=args.timeout_s,
    )
    _print_summary("调度能力与质量基准", {
        **summary["capacity_boundary"],
        "report": str(args.output_dir / "DISPATCH_CAPACITY_QUALITY_REPORT.md"),
    })
    return 0 if summary["benchmark_completed"] else 2


def cmd_dispatch_feasibility_probe(args: argparse.Namespace) -> int:
    """扫描重空调度核心稳健资源可行区域。"""
    from tools.dispatch_robust_feasibility_probe import run_probe, run_targeted_probe

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
        feasible_count = summary["resource_feasible_seed_count"]
        summary_path = args.output_dir / "targeted_probe_summary.json"
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
        feasible_count = summary["robust_resource_feasible_count"]
        summary_path = args.output_dir / "probe_summary.json"
    _print_summary("调度稳健可行性探测", {
        "evaluated_template_count": summary["evaluated_template_count"],
        "robust_resource_feasible_count": feasible_count,
        "summary": str(summary_path),
    })
    return 0


def cmd_dispatch_single_candidate_profile(args: argparse.Namespace) -> int:
    """剖析一个固定重空调度候选的完整稳健评价。"""
    from tools.dispatch_single_candidate_profile import run_profile

    summary = run_profile(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
        heavy_headway_s=args.heavy_headway_s,
        empty_headway_s=args.empty_headway_s,
        phase_s=args.phase_s,
        storage_preset_id=args.storage_preset_id,
        settlement_step_s=args.settlement_step_s,
        repeat_count=args.repeat_count,
        top=args.top,
    )
    _print_summary("调度单候选画像", {
        "median_wall_time_s": summary["benchmark"]["median_wall_time_s"],
        "semantic_stable": summary["benchmark"]["semantic_stable"],
        "report": summary["outputs"]["report"],
    })
    return 0 if summary["benchmark"]["semantic_stable"] else 2


def cmd_joint_parameter_robustness(args: argparse.Namespace) -> int:
    """执行参数区间与运行扰动的联合稳健性评价。"""

    from tools.joint_parameter_robustness_benchmark import run_benchmark

    summary = run_benchmark(
        data_dir=args.data_dir,
        parameter_ranges=args.parameter_ranges,
        output_dir=args.output_dir,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
        heavy_headway_s=args.heavy_headway_s,
        empty_headway_s=args.empty_headway_s,
        phase_s=args.phase_s,
        settlement_step_s=args.settlement_step_s,
    )
    _print_summary("联合参数稳健性", {
        "tested_joint_robust": summary["outcome"]["tested_joint_robust"],
        "combination_count": summary["coverage"]["combination_count"],
        "report": str(args.output_dir / "JOINT_PARAMETER_ROBUSTNESS_REPORT.md"),
    })
    return 0


def cmd_dispatch_extended_scale_benchmark(args: argparse.Namespace) -> int:
    """受监控执行固定时域或扩展时域的12/16列车基准。"""
    from tools.dispatch_extended_scale_benchmark import run_benchmark

    summary = run_benchmark(
        plan_path=args.plan,
        output_dir=args.output_dir,
        case_ids=args.cases,
    )
    _print_summary("调度扩展规模基准", {
        "all_requested_completed": summary["all_requested_completed"],
        "report": str(args.output_dir / "DISPATCH_EXTENDED_SCALE_REPORT.md"),
    })
    return 0 if summary["all_requested_completed"] else 2


def cmd_small_scale_optimality_gap(args: argparse.Namespace) -> int:
    """运行有限离散域的小规模精确最优与启发式差距测试。"""

    from tools.small_scale_optimality_gap_benchmark import run_benchmark

    summary = run_benchmark(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        scales=args.scales,
        seeds=args.seeds,
        profiles=args.profiles,
        horizon_s=args.horizon_s,
        settlement_step_s=args.settlement_step_s,
    )
    _print_summary(
        "小规模最优性差距",
        {
            "benchmark_completed": summary["benchmark_completed"],
            **summary["aggregate"],
            "report": summary["outputs"]["report"],
        },
    )
    return 0 if summary["benchmark_completed"] else 2


def cmd_synthetic_rolling_rescheduling(args: argparse.Namespace) -> int:
    """运行合成状态测试或历史扰动回放。"""

    from tools.synthetic_rolling_rescheduling_benchmark import run_benchmark
    from energy_settlement import StorageDeviceRuntimeState
    from historical_disturbance_replay import load_historical_disturbance_replay
    from rolling_optimizer import RollingSafetyPolicy

    storage_device_states = None
    if args.storage_devices_json:
        try:
            storage_rows = json.loads(args.storage_devices_json)
        except json.JSONDecodeError as exc:
            raise ValueError("--storage-devices-json 必须是合法JSON数组。") from exc
        if not isinstance(storage_rows, list):
            raise ValueError("--storage-devices-json 必须是JSON数组。")
        parsed_states = []
        for index, row in enumerate(storage_rows):
            if not isinstance(row, dict):
                raise ValueError(f"storage_devices[{index}]必须是JSON对象。")
            parsed_states.append(StorageDeviceRuntimeState(**row))
        storage_device_states = tuple(parsed_states)
    disturbance_replay = (
        load_historical_disturbance_replay(
            args.disturbance_history,
            source_label=args.disturbance_history_label,
        )
        if args.disturbance_history is not None else None
    )

    summary = run_benchmark(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        population_size=args.population_size,
        generations=args.generations,
        seed=args.seed,
        enable_recovery=not args.disable_recovery,
        safety_policy=RollingSafetyPolicy(
            enable_automatic_retry=not args.disable_safety_retry,
            max_retries_per_cycle=args.max_safety_retries,
            manual_after_consecutive_withheld=args.manual_after_withheld,
        ),
        initial_storage_device_states=storage_device_states,
        disturbance_replay=disturbance_replay,
    )
    report_name = (
        "HISTORICAL_DISTURBANCE_REPLAY_REPORT.md"
        if disturbance_replay is not None
        else "SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md"
    )
    _print_summary(
        (
            "历史扰动回放"
            if disturbance_replay is not None
            else "合成滚动重排"
        ),
        {
            "all_gates_passed": summary["all_gates_passed"],
            "cycle_count": summary["cycle_count"],
            "robust_feasible_cycle_count": summary["robust_feasible_cycle_count"],
            "wall_time_s": summary["wall_time_s"],
            "input_mode": summary["input_mode"],
            "report": str(args.output_dir / report_name),
        },
    )
    return 0 if summary["all_gates_passed"] else 2


def cmd_rolling_budgeted_shadow(args: argparse.Namespace) -> int:
    """运行显式实验开关下的预算化影子滚动联调。"""

    from rolling_shadow import run_shadow

    summary = run_shadow(
        data_dir=Path(args.data_dir),
        request_path=Path(args.shadow_request),
        output_dir=Path(args.output_dir),
        experimental_budgeted_shadow=args.experimental_budgeted_shadow,
        population_size=args.population_size,
        generations=args.generations,
        seed=args.seed,
        job_wall_limit_s=args.shadow_job_wall_limit_s,
    )
    _print_summary(
        "预算化滚动影子联调",
        {
            "window_count": summary["cycle_count"],
            "shadow_only": summary.get("shadow_only"),
            "execution_allowed": summary.get("execution_allowed"),
            "dispatch_allowed": summary.get("dispatch_allowed"),
            "report": str(Path(args.output_dir) / "shadow_summary.json"),
        },
    )
    return 0


def cmd_recovery_ablation(args: argparse.Namespace) -> int:
    """运行恢复级联关闭/开启的同口径消融对照实验。"""

    from tools.recovery_ablation_benchmark import run_ablation

    summary = run_ablation(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        population_size=args.population_size,
        generations=args.generations,
        seed=args.seed,
    )
    _print_summary(
        "恢复消融",
        {
            "all_gates_passed": summary["all_gates_passed"],
            "recovered_cycle_numbers": summary["recovered_cycle_numbers"],
            "without_recovery_robust_feasible_cycles": summary["without_recovery"]["robust_feasible_cycle_count"],
            "with_recovery_robust_feasible_cycles": summary["with_recovery"]["robust_feasible_cycle_count"],
            "report": str(args.output_dir / "RECOVERY_ABLATION_REPORT.md"),
        },
    )
    return 0 if summary["all_gates_passed"] else 2

def cmd_storage_energy_search(args: argparse.Namespace) -> int:
    """函数 cmd_storage_energy_search：执行该模块中的相关处理逻辑。"""
    from run_storage_energy_search import main as storage_search_main

    argv = [
        "--input",
        str(args.data_dir),
        "--output-dir",
        str(args.output_dir),
        "--heavy-headway-s",
        str(args.heavy_headway_s),
        "--empty-headway-s",
        str(args.empty_headway_s),
        "--phase-s",
        str(args.phase_s),
        "--heavy-count",
        str(args.heavy_count),
        "--empty-count",
        str(args.empty_count),
        "--settlement-step-s",
        str(args.settlement_step_s),
        "--wasted-energy-penalty-per-kwh",
        str(args.wasted_energy_penalty_per_kwh),
        "--min-depart-gap-s",
        str(args.min_depart_gap_s),
    ]
    return storage_search_main(argv)


def cmd_energy_sensitivity(args: argparse.Namespace) -> int:
    """函数 cmd_energy_sensitivity：执行该模块中的相关处理逻辑。"""
    import importlib.util

    module_path = Path(__file__).resolve().parent / "tools_energy_sensitivity_scan.py"
    spec = importlib.util.spec_from_file_location("tools_energy_sensitivity_scan", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载能耗敏感性模块：{module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 允许通过模块参数使用命令行覆盖默认输出根目录。
    if hasattr(module, "OUTPUT_DIR"):
        module.OUTPUT_DIR = Path(args.output_dir)
    return int(module.main())


def cmd_smoke(args: argparse.Namespace) -> int:
    # 旧版检查保留在 tests/legacy；长耗时项由独立运行器提供逐项超时和日志。
    """函数 cmd_smoke：执行该模块中的相关处理逻辑。"""
    scripts = sorted((Path("tests") / "smoke").glob("verify_*.py"))
    if args.only:
        selected = [path for path in scripts if path.stem in set(args.only)]
    elif getattr(args, "include_long", False):
        selected = scripts
    else:
        selected = [path for path in scripts if path.stem not in LONG_SMOKE_STEMS]
    if not selected:
        print("没有匹配 --only 的短测用例。")
        return 1
    with tempfile.TemporaryDirectory(prefix="heavy_empty_train_coordination_smoke_") as temp_name:
        smoke_root = Path(temp_name)
        environment = os.environ.copy()
        environment["HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT"] = str(smoke_root)
        failures: list[str] = []
        for script in selected:
            print(f"=== 短测：{script} ===")
            completed = subprocess.run(
                [sys.executable, str(script)], check=False, env=environment
            )
            if completed.returncode != 0:
                # 记录失败并继续执行后续用例：只在首个失败处返回会让字母序靠后的
                # 测试长期不被执行，却看起来像「全部通过」。
                failures.append(script.stem)
                failure_root = (
                    DEFAULT_OUTPUT_ROOT
                    / "smoke_failures"
                    / f"smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}_{script.stem}"
                )
                try:
                    shutil.copytree(smoke_root, failure_root)
                    print(f"短测失败证据：{failure_root}")
                except OSError as exc:
                    print(f"警告：无法保留短测失败证据：{exc}")
        if failures:
            print(f"=== 短测失败 {len(failures)}/{len(selected)}：{', '.join(failures)} ===")
            return 1
        print(f"=== 短测全部通过：{len(selected)} 个 ===")
    return 0


def cmd_experiment_suite(args: argparse.Namespace) -> int:
    """函数 cmd_experiment_suite：执行该模块中的相关处理逻辑。"""
    from run_simulation_experiment_suite import main as suite_main

    return suite_main(["--data-dir", str(args.data_dir), "--output-root", str(args.output_root)])



def cmd_official_intake_dry_run(args: argparse.Namespace) -> int:
    """函数 cmd_official_intake_dry_run：执行该模块中的相关处理逻辑。"""
    import importlib.util

    module_path = Path(__file__).resolve().parent / "tools" / "official_intake_dry_run.py"
    spec = importlib.util.spec_from_file_location("official_intake_dry_run", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载官方数据入库试跑模块：{module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    argv = [
        "--inbox-dir", str(args.inbox_dir),
        "--template-dir", str(args.template_dir),
        "--status-json", str(args.status_json),
        "--output-dir", str(args.output_dir),
    ]
    if getattr(args, "update_status", False):
        argv.append("--update-status")
    return module.main(argv)


def cmd_check_ingestion(args: argparse.Namespace) -> int:
    """函数 cmd_check_ingestion：执行该模块中的相关处理逻辑。"""
    from real_data_ingestion_checker import main as checker_main

    input_path = Path(args.input)
    related_data_dir = input_path if input_path.is_dir() or not input_path.suffix else input_path.parent
    station_csv = Path(args.station_csv) if args.station_csv is not None else related_data_dir / "stations.csv"
    route_metadata = (
        Path(args.route_metadata)
        if args.route_metadata is not None
        else related_data_dir / "route_metadata.json"
    )
    return checker_main(
        [
            "--input",
            str(args.input),
            "--kind",
            args.kind,
            "--timetable",
            str(args.timetable),
            "--station-csv",
            str(station_csv),
            "--route-metadata",
            str(route_metadata),
            "--output-dir",
            str(args.output_dir),
        ]
    )


def cmd_profile_external_data(args: argparse.Namespace) -> int:
    """剖析外部数据文件并输出候选字段映射，不修改源文件。"""

    from tools.profile_external_data import _markdown, profile_directory

    if args.max_rows < 1:
        raise ValueError("--max-rows 必须为正整数。")
    output_dir = Path(args.output_dir)
    report = profile_directory(Path(args.input), output_dir, args.max_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "external_data_profile.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "EXTERNAL_DATA_PROFILE.md").write_text(_markdown(report), encoding="utf-8")
    _print_summary(
        "外部数据剖析",
        {
            "file_count": report["file_count"],
            "ok_file_count": report["ok_file_count"],
            "error_file_count": report["error_file_count"],
            "unsupported_file_count": report["unsupported_file_count"],
            "confirmation_count": report["confirmation_count"],
            "report": str(output_dir / "EXTERNAL_DATA_PROFILE.md"),
        },
    )
    return 0 if report["error_file_count"] == 0 else 2


def cmd_real_data_workflow(args: argparse.Namespace) -> int:
    # 数据重建必须显式执行，不能仅因某数据集被用于仿真就覆盖它。
    """函数 cmd_real_data_workflow：执行该模块中的相关处理逻辑。"""
    meter_sample_csv = args.output_root / "smart_meter_representative_interval_samples.csv"
    steps: list[tuple[str, object, argparse.Namespace]] = []
    if args.rebuild_data:
        steps.append(
            (
                "build-data",
                cmd_build_data,
                argparse.Namespace(data_dir=args.data_dir, source_dir=args.source_dir),
            )
        )
    steps.extend([
        (
            "validate-data",
            cmd_validate_data,
            argparse.Namespace(
                data_dir=args.data_dir,
                source_dir=args.source_dir,
                timetable=args.timetable,
                output_dir=args.output_root / "data_quality_validation",
                require_official_data=getattr(args, "require_official_data", False),
            ),
        ),
        (
            "meter-samples",
            cmd_meter_samples,
            argparse.Namespace(
                smart_meter_dir=args.smart_meter_dir,
                data_dir=args.data_dir,
                output_csv=meter_sample_csv,
                station_csv=args.data_dir / "stations.csv",
                alignment_output_dir=args.output_root / "energy_calibration_alignment",
                factor_json=args.data_dir / "energy_calibration_factors.json",
                energy_calibration_mode="grouped",
                max_per_normalized_trainid=args.max_per_normalized_trainid,
                max_realtime_rows_per_file=args.max_realtime_rows_per_file,
            ),
        ),
        (
            "audit-timetable",
            cmd_audit_timetable,
            argparse.Namespace(
                timetable=args.timetable,
                output_dir=args.output_root / "timetable_energy_audit",
                power_arm_path=args.data_dir / "power_arm_intervals.csv",
                data_dir=args.data_dir,
            ),
        ),
        (
            "optimize-timetable",
            cmd_optimize_timetable,
            argparse.Namespace(
                timetable=args.timetable,
                output_dir=args.output_root / "timetable_optimizer_nsga2",
                power_arm_path=args.data_dir / "power_arm_intervals.csv",
                resource_data_dir=args.data_dir,
                max_shift_min=args.max_shift_min,
                step_min=args.step_min,
                max_dwell_extension_min=args.max_dwell_extension_min,
                max_candidates=args.max_candidates,
                mode="nsga2",
                population_size=args.timetable_population_size,
                generations=args.timetable_generations,
                crossover_rate=args.crossover_rate,
                mutation_rate=args.mutation_rate,
                seed=args.seed,
            ),
        ),
        (
            "dispatch-case",
            cmd_dispatch_case,
            argparse.Namespace(
                data_dir=args.data_dir,
                output_dir=args.output_root / (
                    f"dispatch_no_storage_phase{int(args.baseline_phase_s)}"
                    if getattr(args, "optimization_mode", "dispatch_only") == "dispatch_only"
                    else f"dispatch_storage_no_direct_phase{int(args.baseline_phase_s)}"
                ),
                optimization_mode=getattr(args, "optimization_mode", "dispatch_only"),
                energy_scenario=(
                    "direct_no_storage"
                    if getattr(args, "optimization_mode", "dispatch_only") == "dispatch_only"
                    else "storage_no_direct"
                ),
                objective_mode="balanced",
                search_method="nsga2",
                population_size=args.dispatch_population_size,
                generations=args.dispatch_generations,
                heavy_count=args.heavy_count,
                empty_count=args.empty_count,
                baseline_phase_s=args.baseline_phase_s,
                baseline_heavy_headway_s=getattr(args, "baseline_heavy_headway_s", 3300),
                baseline_empty_headway_s=getattr(args, "baseline_empty_headway_s", 2700),
                min_depart_gap_s=args.min_depart_gap_s,
                settlement_step_s=args.settlement_step_s,
                wasted_energy_penalty_per_kwh=getattr(args, "wasted_energy_penalty_per_kwh", 0.0),
                enable_energy_observability=(
                    False
                    if getattr(args, "disable_energy_observability", False)
                    else getattr(args, "enable_energy_observability", True)
                ),
                disable_energy_observability=getattr(args, "disable_energy_observability", False),
                enable_storage_preset_search=(
                    False
                    if getattr(args, "disable_storage_preset_search", False)
                    else getattr(args, "enable_storage_preset_search", True)
                ),
                disable_storage_preset_search=getattr(args, "disable_storage_preset_search", False),
                storage_preset_ids=getattr(
                    args,
                    "storage_preset_ids",
                    "virtual_two_section_base,virtual_two_section_high_power,virtual_two_section_high_capacity,virtual_two_section_high_power_capacity,virtual_expanded_regen_corridor",
                ),
                storage_shift_mutation_s=getattr(args, "storage_shift_mutation_s", 300),
                search_max_storage_align_shift_s=getattr(args, "search_max_storage_align_shift_s", 1200),
                search_max_hold_s=getattr(args, "search_max_hold_s", 900),
                search_max_phase_s=getattr(args, "search_max_phase_s", 5400),
                phase_mutation_s=getattr(args, "phase_mutation_s", 300),
                hold_mutation_s=getattr(args, "hold_mutation_s", 180),
                headway_mutation_s=getattr(args, "headway_mutation_s", 300),
                elite_count=getattr(args, "elite_count", 4),
                empty_mass_tons=None,
                battery_capacity_kwh=None,
                battery_max_charge_power_kw=None,
                battery_max_discharge_power_kw=None,
                battery_round_trip_efficiency=None,
                battery_depreciation_per_kwh=getattr(args, "battery_depreciation_per_kwh", None),
                battery_grid_price_per_kwh=getattr(args, "battery_grid_price_per_kwh", None),
                objective_priority=getattr(args, "objective_priority", "energy_first"),
                search_profile=getattr(args, "search_profile", "standard"),
            ),
        ),
        (
            "heavy-empty-plan",
            cmd_heavy_empty_plan,
            argparse.Namespace(
                template=DEFAULT_HEAVY_EMPTY_TEMPLATE,
                data_dir=args.data_dir,
                output_dir=args.output_root / "heavy_empty_plan",
                scenario_id=None,
                population_size=getattr(args, "heavy_empty_population_size", None),
                generations=getattr(args, "heavy_empty_generations", None),
            ),
        ),
    ])
    results: dict[str, object] = {}
    for name, func, step_args in steps:
        print(f"\n>>> 正在运行 {name}")
        code = func(step_args)
        if code != 0:
            print(f"步骤失败：{name}（退出码 {code}）")
            return code
        results[name] = _load_step_summary(name, step_args)
    dispatch_output_dir = args.output_root / f"dispatch_storage_no_direct_phase{int(args.baseline_phase_s)}"
    write_simulation_report(
        args.output_root,
        results,
        dispatch_output_dir=dispatch_output_dir,
    )
    return 0


def cmd_accept_official_data(args: argparse.Namespace) -> int:
    """函数 cmd_accept_official_data：执行该模块中的相关处理逻辑。"""
    from formal_data_acceptance import run_acceptance, write_report

    summary = run_acceptance(args.data_dir, args.source_dir, args.timetable)
    write_report(summary, args.output_dir)
    _print_summary(
        "正式数据验收",
        {
            "accepted": summary["accepted"],
            "error_count": summary["error_count"],
            "warning_count": summary["warning_count"],
            "output_dir": str(args.output_dir),
        },
    )
    return 0 if summary["accepted"] else 1


def cmd_check_results(args: argparse.Namespace) -> int:
    """函数 cmd_check_results：执行该模块中的相关处理逻辑。"""
    from result_quality_audit import audit_output_root, write_report

    summary = audit_output_root(args.output_root)
    write_report(summary, args.report_dir)
    _print_summary(
        "结果质量审计",
        {
            "accepted": summary["accepted"],
            "error_count": summary["error_count"],
            "warning_count": summary["warning_count"],
            "report_dir": str(args.report_dir or args.output_root),
        },
    )
    return 0 if summary["accepted"] else 1


def cmd_official_data_readiness(args: argparse.Namespace) -> int:
    """函数 cmd_official_data_readiness：执行该模块中的相关处理逻辑。"""
    from tools.official_data_readiness_pipeline import run_pipeline

    result = run_pipeline(
        args.data_dir,
        args.source_dir,
        args.timetable,
        args.output_dir,
        run_simulation=args.run_simulation,
        baseline_output=args.baseline_output,
    )
    simulation = result.get("simulation")
    passed = bool(result["accepted"])
    if simulation is not None:
        passed = passed and simulation.get("returncode") == 0 and simulation.get("audit", {}).get("accepted", False)
    _print_summary("官方数据就绪度", {
        "accepted": result["accepted"],
        "simulation_checked": simulation is not None,
        "simulation_passed": None if simulation is None else passed,
        "output_dir": str(args.output_dir),
    })
    return 0 if passed else 1


def cmd_formal_experiment_suite(args: argparse.Namespace) -> int:
    """函数 cmd_formal_experiment_suite：执行正式数据对比实验总控。"""
    from tools.formal_experiment_controller import run_formal_experiment_suite

    summary = run_formal_experiment_suite(
        data_dir=args.data_dir,
        source_dir=args.source_dir,
        timetable=args.timetable,
        output_root=args.output_root,
        window_id=args.window_id,
        seeds=args.seeds,
        max_shift_min=args.max_shift_min,
        step_min=args.step_min,
        max_dwell_extension_min=args.max_dwell_extension_min,
        max_candidates=args.max_candidates,
        population_size=args.population_size,
        generations=args.generations,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        strict_visualizations=not args.no_strict_visualizations,
        calibration_summary=args.calibration_summary,
        require_calibration=args.require_calibration,
        settlement_steps_s=args.settlement_steps_s,
    )
    _print_summary(
        "正式实验套件",
        {
            "status": summary["status"],
            "formal_data_accepted": summary["readiness"]["accepted"],
            "scenario_count": len(summary["scenarios"]),
            "output_root": summary["output_root"],
        },
    )
    return 0 if summary["status"] == "completed" else 1


def cmd_create_official_data_marker(args: argparse.Namespace) -> int:
    """为复制完成的正式交付包生成最终到件标记。"""
    from tools.official_data_auto_trigger import create_delivery_marker

    experiment = {
        "seeds": args.seeds,
        "settlement_steps_s": args.settlement_steps_s,
        "max_shift_min": args.max_shift_min,
        "step_min": args.step_min,
        "max_dwell_extension_min": args.max_dwell_extension_min,
        "max_candidates": args.max_candidates,
        "population_size": args.population_size,
        "generations": args.generations,
        "strict_visualizations": not args.no_strict_visualizations,
        "require_calibration": args.require_calibration,
    }
    marker = create_delivery_marker(
        args.package_dir,
        delivery_id=args.delivery_id,
        data_dir=args.data_dir,
        source_dir=args.source_dir,
        timetable=args.timetable,
        window_id=args.window_id,
        calibration_summary=args.calibration_summary,
        experiment=experiment,
        marker_name=args.marker_name,
    )
    _print_summary("官方数据交付标记", {
        "delivery_id": marker["delivery_id"],
        "file_count": len(marker["files"]),
        "marker": str(args.package_dir / args.marker_name),
    })
    return 0


def cmd_official_data_auto_trigger(args: argparse.Namespace) -> int:
    """单次检查或持续监控正式数据交付包。"""
    from tools.official_data_auto_trigger import process_delivery_once, watch_deliveries

    if args.watch:
        return watch_deliveries(
            args.package_dir,
            args.output_root,
            marker_name=args.marker_name,
            poll_seconds=args.poll_seconds,
        )
    result = process_delivery_once(
        args.package_dir,
        args.output_root,
        marker_name=args.marker_name,
        retry=args.retry,
    )
    _print_summary("官方数据自动触发", result)
    return {"completed": 0, "duplicate": 0, "waiting": 0, "blocked": 2}.get(result["status"], 1)


def cmd_paper_experiment_pipeline(args: argparse.Namespace) -> int:
    """批量执行评价窗，并生成论文统计表、检验结果和图形。"""
    from tools.paper_experiment_pipeline import run_paper_experiment_pipeline

    summary = run_paper_experiment_pipeline(
        study_manifest=args.study_manifest,
        output_root=args.output_root,
        aggregate_only=args.aggregate_only,
    )
    _print_summary(
        "论文实验流水线",
        {
            "status": summary["status"],
            "study_id": summary["study_id"],
            "completed_windows": summary["completed_window_count"],
            "included_windows": summary["included_window_count"],
            "statistical_rows": summary["statistical_row_count"],
            "output_root": str(args.output_root),
        },
    )
    return 0 if summary["status"] == "completed" else 1


def cmd_aggregate_paper_experiments(args: argparse.Namespace) -> int:
    """汇总当前异构论文实验，生成证据矩阵、指标、缺口和总报告。"""
    from tools.paper_experiment_aggregator import aggregate_paper_experiments

    summary = aggregate_paper_experiments(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        report_path=args.report_path,
    )
    _print_summary(
        "论文实验汇总",
        {
            "aggregation_completed": summary["aggregation_completed"],
            "registered_experiments": summary["registered_experiment_count"],
            "completed": summary["completed_count"],
            "quality_blocked": summary["quality_blocked_count"],
            "failed": summary["failed_count"],
            "missing": summary["missing_count"],
            "formal_claim_ready": summary["formal_claim_ready"],
            "report": summary["outputs"]["report"],
        },
    )
    return 0 if summary["failed_count"] == 0 and summary["missing_count"] == 0 else 1


def _read_json_if_exists(path: Path) -> object:
    """函数 _read_json_if_exists：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return {"missing": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_step_summary(name: str, args: argparse.Namespace) -> object:
    """函数 _load_step_summary：执行该模块中的相关处理逻辑。"""
    if name == "validate-data":
        return _read_json_if_exists(args.output_dir / "data_quality_summary.json")
    if name == "meter-samples":
        sample_summary = _read_json_if_exists(args.output_csv.with_name(args.output_csv.stem + "_summary.json"))
        alignment_summary = _read_json_if_exists(args.alignment_output_dir / "arc_energy_vs_meter_summary.json")
        return {"samples": sample_summary, "alignment": alignment_summary}
    if name == "audit-timetable":
        return _read_json_if_exists(args.output_dir / "audit_summary.json")
    if name == "optimize-timetable":
        return _read_json_if_exists(args.output_dir / "optimizer_summary.json")
    if name == "dispatch-case":
        return _read_json_if_exists(args.output_dir / "summary.json")
    if name == "build-data":
        return _read_json_if_exists(Path(args.data_dir) / "build_summary.json")
    return {}


def write_simulation_report(
    output_root: Path,
    results: dict[str, object],
    *,
    dispatch_output_dir: Optional[Path] = None,
) -> None:
    """函数 write_simulation_report：执行该模块中的相关处理逻辑。"""
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "SIMULATION_TEST_REPORT.md"
    summary_path = output_root / "simulation_workflow_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    data_quality = results.get("validate-data", {})
    meter = results.get("meter-samples", {})
    audit = results.get("audit-timetable", {})
    optimizer = results.get("optimize-timetable", {})
    dispatch = results.get("dispatch-case", {})

    def get(mapping: object, *keys: str, default: object = "") -> object:
        """函数 get：执行该模块中的相关处理逻辑。"""
        value = mapping
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key, default)
        return value

    dispatch_output_dir = dispatch_output_dir or output_root / "dispatch_storage_no_direct_phase2600"
    output_paths = {
        "data_quality": output_root / "data_quality_validation",
        "meter_alignment": output_root / "energy_calibration_alignment",
        "timetable_audit": output_root / "timetable_energy_audit",
        "timetable_optimizer": output_root / "timetable_optimizer_nsga2",
        "dispatch": dispatch_output_dir,
    }
    lines = [
        "# 拟真测试汇总报告",
        "",
        "本报告由 `python run_project.py simulate` 自动生成，用于说明当前算法在真实主线数据和明确预设值下的端到端运行情况。",
        "",
        "## 当前口径",
        "",
        "- 线路范围：只考虑线路图 1、2、3 覆盖的朔黄主线。",
        "- 供电规则：上下行不能直发直用，再生能量仅在标记为储能可用的区段通过储能利用。",
        "- 未取得的正式数据：采用有标记的预设/占位参数，不把占位值解释为真实工程结论。",
        "- 电表数据：用于代表性验证覆盖，重叠或重复 station 区间不阻塞流程，代表样本中排除。",
        "",
        "## 运行结果",
        "",
        f"- 数据校验：error={get(data_quality, 'error_count', default='N/A')}，warning={get(data_quality, 'warning_count', default='N/A')}。",
        f"- 电表代表样本：sample_count={get(meter, 'samples', 'sample_count', default='N/A')}，aligned={get(meter, 'alignment', 'alignment_status_counts', 'aligned', default='N/A')}。",
        f"- 运行图审查：valid={get(audit, 'valid', default='N/A')}，issue_count={get(audit, 'issue_count', default='N/A')}。",
        f"- 运行图优化：candidate_count={get(optimizer, 'candidate_count', default='N/A')}，pareto_count={get(optimizer, 'pareto_count', default='N/A')}。",
        f"- 调度拟真：baseline_feasible={get(dispatch, 'baseline', 'feasible', default='N/A')}，optimized_feasible={get(dispatch, 'optimized', 'feasible', default='N/A')}。",
        f"- 调度优化：cost_reduction_pct={get(dispatch, 'comparison', 'cost_reduction_pct', default='N/A')}，optimized_conflicts={get(dispatch, 'optimized', 'resource_conflict_count', default='N/A')}。",
        f"- 调度候选：pareto_count={get(dispatch, 'pareto_candidates', 'count', default='N/A')}，basis={get(dispatch, 'pareto_candidates', 'basis', default='N/A')}。",
        "",
        "## 主要输出",
        "",
        f"- 数据质量报告：`{output_paths['data_quality']}/`",
        f"- 电表代表样本与线路能耗对齐：`{output_paths['meter_alignment']}/`",
        f"- 运行图能量审查：`{output_paths['timetable_audit']}/`",
        f"- 运行图多目标优化：`{output_paths['timetable_optimizer']}/`",
        f"- 重空列协同调度拟真：`{output_paths['dispatch']}/`",
        "",
        "## 可信边界",
        "",
        "- 当前结果可以用于验证流程、比较候选方案、检查约束逻辑和展示帕累托方案输出。",
        "- 当前结果不应作为最终节能量、储能容量或工程投资收益结论。",
        "- 后续拿到正式运行图、真实储能设备参数、牵引/制动/阻力参数后，可替换预设值并复跑同一入口。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _print_summary(
        "仿真流程",
        {
            "summary_json": str(summary_path),
            "report": str(report_path),
        },
    )


def add_common_real_data_args(parser: argparse.ArgumentParser) -> None:
    """函数 add_common_real_data_args：执行该模块中的相关处理逻辑。"""
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="数据源目录")
    parser.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE, help="运行图 Excel 路径")


# argparse 内置英文错误提示的改写规则，按键值对的「正则 → 中文模板」顺序尝试。
_ERROR_MESSAGE_RULES: Tuple[Tuple[str, str], ...] = (
    (r"^argument ([^:]+): invalid choice: (.*) \(choose from (.*)\)$", r"参数 \1 取值无效：\2（可选值：\3）"),
    (r"^argument ([^:]+): expected one argument$", r"参数 \1 需要一个取值"),
    (r"^argument ([^:]+): invalid ([^ ]+) value: (.*)$", r"参数 \1 取值无效（期望 \2）：\3"),
    (r"^unrecognized arguments: (.*)$", r"无法识别的参数：\1"),
    (r"^the following arguments are required: (.*)$", r"缺少必需参数：\1"),
    (r"^ambiguous option: (.*)$", r"选项存在歧义：\1"),
)


def _localize_help_text(text: str) -> str:
    """替换帮助文本中由 argparse 硬编码的英文前缀与分组标题冒号。"""

    return (
        text.replace("usage: ", "用法：", 1)
        .replace("位置参数:", "位置参数：")
        .replace("选项:", "选项：")
    )


def _localize_error_message(message: str) -> str:
    """把 argparse 组装的英文错误提示改写为中文，未命中规则时原样返回。"""

    for pattern, replacement in _ERROR_MESSAGE_RULES:
        if re.match(pattern, message):
            return re.sub(pattern, replacement, message)
    return message


class _ChineseArgumentParser(argparse.ArgumentParser):
    """把 argparse 的英文用法前缀、分组标题与错误提示替换为中文。"""

    def format_usage(self) -> str:
        """函数 format_usage：输出中文「用法」前缀的用法行。"""
        return _localize_help_text(super().format_usage())

    def format_help(self) -> str:
        """函数 format_help：输出中文「用法」前缀的帮助正文。"""
        return _localize_help_text(super().format_help())

    def error(self, message: str) -> None:
        """函数 error：以中文输出用法与错误说明后以状态码 2 退出。"""
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}：错误：{_localize_error_message(message)}\n")


def _localize_parser_labels(root: argparse.ArgumentParser) -> None:
    """递归把 argparse 内置的英文分组标题与帮助项说明改为中文。"""
    pending = [root]
    while pending:
        current = pending.pop()
        current._positionals.title = "位置参数"
        current._optionals.title = "选项"
        for action in current._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = "显示本帮助并退出"
            elif isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = _ChineseArgumentParser(
        description="朔黄重空车调度、运行图审查、运行图优化、能耗校准与数据检查的统一入口。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_data = subparsers.add_parser("build-data", help="从已复核的源表重建数据目录。")
    build_data.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    build_data.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="数据源目录")
    build_data.set_defaults(func=cmd_build_data)

    validate = subparsers.add_parser("validate-data", help="校验真实源表与算法输入文件。")
    add_common_real_data_args(validate)
    validate.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "data_quality_validation", help="结果输出目录")
    validate.add_argument(
        "--require-official-data",
        action="store_true",
        help="输入未通过正式来源核验时直接阻塞",
    )
    validate.set_defaults(func=cmd_validate_data)

    storage_planning = subparsers.add_parser(
        "validate-storage-planning",
        help="校验储能选址定容阶段A输入文件与语义指纹。",
    )
    storage_planning.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data_templates") / "storage_planning_synthetic",
        help="输入契约目录",
    )
    storage_planning.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "storage_planning_input_validation",
        help="结果输出目录",
    )
    storage_planning.add_argument(
        "--power-arm-path",
        type=Path,
        default=None,
        help="供电臂区间表路径（power_arm_intervals.csv）",
    )
    storage_planning.set_defaults(func=cmd_validate_storage_planning)

    run_storage_planning = subparsers.add_parser(
        "plan-storage",
        help="运行固定运行图下的无储能基线、热点分析与离散储能选址定容。",
    )
    run_storage_planning.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data_templates") / "storage_planning_synthetic",
        help="输入契约目录",
    )
    run_storage_planning.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data_templates") / "shuohuang_virtual",
        help="基础数据目录（线路、车辆、站场、供电臂）",
    )
    run_storage_planning.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "storage_planning_mvp",
        help="结果输出目录",
    )
    run_storage_planning.add_argument("--power-arm-path", type=Path, default=None, help="供电臂区间表路径（power_arm_intervals.csv）")
    run_storage_planning.add_argument(
        "--max-levels-per-dimension",
        type=int,
        default=2,
        help="每个离散维度最多取几个水平",
    )
    run_storage_planning.add_argument("--settlement-step-s", type=int, default=60, help="结算时间步长（秒）")
    run_storage_planning.add_argument(
        "--search-mode", choices=("coarse", "coarse_to_fine", "exhaustive"), default="coarse",
        help="搜索模式",
    )
    run_storage_planning.add_argument("--refinement-shortlist-size", type=int, default=3, help="进入精细化搜索的候选数")
    run_storage_planning.add_argument("--planning-policy-code", type=str, default=None, help="期望的规划策略编码")
    run_storage_planning.add_argument("--scenario-set-code", type=str, default=None, help="期望的规划场景集编码")
    run_storage_planning.set_defaults(func=cmd_run_storage_planning)

    mixed_storage_planning = subparsers.add_parser(
        "plan-storage-mixed",
        help="用当前混合数据集生成规划输入并执行储能选址定容。",
    )
    mixed_storage_planning.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    mixed_storage_planning.add_argument("--timetable", type=Path, default=DEFAULT_STORAGE_PLANNING_TIMETABLE, help="运行图 Excel 路径")
    mixed_storage_planning.add_argument(
        "--input-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "storage_planning_mixed_inputs",
        help="输入契约目录",
    )
    mixed_storage_planning.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "storage_planning_mixed",
        help="结果输出目录",
    )
    mixed_storage_planning.add_argument("--max-levels-per-dimension", type=int, default=2, help="每个离散维度最多取几个水平")
    mixed_storage_planning.add_argument("--settlement-step-s", type=int, default=60, help="结算时间步长（秒）")
    mixed_storage_planning.add_argument(
        "--search-mode", choices=("coarse", "coarse_to_fine", "exhaustive"), default="coarse_to_fine",
        help="搜索模式",
    )
    mixed_storage_planning.add_argument(
        "--refinement-shortlist-size",
        type=int,
        default=2,
        help="进入精细化搜索的候选数",
    )
    mixed_storage_planning.set_defaults(func=cmd_plan_storage_mixed)

    storage_credibility = subparsers.add_parser(
        "assess-storage-credibility",
        help="重算储能规划敏感性案例，核查推荐结论的稳定性与质量。",
    )
    storage_credibility.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    storage_credibility.add_argument("--timetable", type=Path, default=DEFAULT_STORAGE_PLANNING_TIMETABLE, help="运行图 Excel 路径")
    storage_credibility.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "storage_planning_credibility",
        help="结果输出目录",
    )
    storage_credibility.add_argument("--settlement-step-s", type=int, default=300, help="结算时间步长（秒）")
    storage_credibility.set_defaults(func=cmd_assess_storage_credibility)

    calibrate = subparsers.add_parser(
        "calibrate-energy",
        help="运行电表能耗校准链路；重叠站间样本不参与验证，样本为空时不发布。",
    )
    calibrate.add_argument("--smart-meter-dir", type=Path, default=DEFAULT_SMART_METER_DIR, help="电表数据目录")
    calibrate.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    calibrate.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "energy_calibration_pipeline", help="结果输出目录")
    calibrate.add_argument("--boundary-tolerance-s", type=float, default=300.0, help="供电臂边界匹配容差（秒）")
    calibrate.add_argument("--energy-tolerance", type=float, default=1.0, help="能耗对比容差")
    calibrate.add_argument("--max-interval-rows-per-file", type=int, help="单文件区间样本行数上限")
    calibrate.add_argument("--max-realtime-rows-per-file", type=int, help="单文件实时样本行数上限")
    calibrate.add_argument("--overlap-policy", choices=("strict", "exclude"), default="exclude", help="电表站区间重叠的处理策略")
    calibrate.add_argument(
        "--no-restrict-to-realtime-coverage",
        action="store_true",
        help="不限制在实时数据覆盖范围内",
    )
    calibrate.add_argument(
        "--no-mainline-only",
        action="store_true",
        help="不限定正线区间",
    )
    calibrate.add_argument("--representative-samples", action="store_true", default=True, help="代表性样本数量")
    calibrate.add_argument("--max-per-realtime-trainid", type=int, default=50, help="每个实时车次保留的样本数上限")
    calibrate.add_argument("--min-fit-samples", type=int, default=30, help="参数拟合所需最少样本数")
    calibrate.add_argument("--min-validation-samples", type=int, default=10, help="验证所需最少样本数")
    calibrate.add_argument("--validation-fraction", type=float, default=0.20, help="验证集比例")
    calibrate.add_argument(
        "--validation-model",
        choices=("global", "grouped"),
        default="grouped",
        help="预先指定质量门禁评价的系数模型，避免查看验证误差后再选择口径。",
    )
    calibrate.add_argument(
        "--validation-alignment-csv",
        type=Path,
        help="使用不同日期或来源批次的已对齐样本进行真正的外部独立验证。",
    )
    calibrate.add_argument("--max-median-ape-pct", type=float, default=30.0, help="中位绝对百分比误差上限（%）")
    calibrate.add_argument("--max-p90-ape-pct", type=float, default=60.0, help="P90 绝对百分比误差上限（%）")
    calibrate.add_argument("--max-wape-pct", type=float, default=30.0, help="加权绝对百分比误差上限（%）")
    calibrate.add_argument("--min-scale", type=float, default=0.2, help="规模扫描的列车数下限")
    calibrate.add_argument("--max-scale", type=float, default=5.0, help="规模扫描的列车数上限")
    calibrate.add_argument(
        "--publish-calibration",
        action="store_true",
        help="发布校准系数",
    )
    calibrate.set_defaults(func=cmd_calibrate_energy)

    meter = subparsers.add_parser(
        "meter-samples",
        help="构建代表性电表验证样本并与线路弧对齐。",
    )
    meter.add_argument("--smart-meter-dir", type=Path, default=DEFAULT_SMART_METER_DIR, help="电表数据目录")
    meter.add_argument("--output-csv", type=Path, default=DEFAULT_REPRESENTATIVE_METER_SAMPLES, help="结果 CSV 输出路径")
    meter.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    meter.add_argument("--station-csv", type=Path, default=None, help="车站表 CSV 路径")
    meter.add_argument("--alignment-output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "energy_calibration_alignment", help="样本对齐结果输出目录")
    meter.add_argument("--factor-json", type=Path, default=None, help="能耗校准系数 JSON 路径")
    meter.add_argument("--energy-calibration-mode", choices=("none", "global", "grouped"), default="grouped", help="能耗校准口径（是否启用校准系数）")
    meter.add_argument("--max-per-normalized-trainid", type=int, default=50, help="每个归一化车次保留的样本数上限")
    meter.add_argument("--max-realtime-rows-per-file", type=int, default=100000, help="单文件实时样本行数上限")
    meter.set_defaults(func=cmd_meter_samples)

    audit = subparsers.add_parser("audit-timetable", help="审查用户运行图：评估再生能量利用与浪费风险。")
    audit.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE, help="运行图 Excel 路径")
    audit.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "timetable_energy_audit", help="结果输出目录")
    audit.add_argument("--power-arm-path", type=Path, default=None, help="供电臂区间表路径（power_arm_intervals.csv）")
    audit.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    audit.add_argument(
        "--settlement-time-step-s",
        type=int,
        default=None,
        help="覆盖 storage_no_direct 场景的结算时间步长，用于敏感性分析。",
    )
    audit.add_argument(
        "--strict-visualizations",
        action="store_true",
        help="任一预期图表生成失败时直接判定审查失败。",
    )
    audit.set_defaults(func=cmd_audit_timetable)

    optimize = subparsers.add_parser("optimize-timetable", help="生成运行图优化候选方案。")
    optimize.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE, help="运行图 Excel 路径")
    optimize.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "timetable_optimizer_nsga2", help="结果输出目录")
    optimize.add_argument("--power-arm-path", type=Path, default=None, help="供电臂区间表路径（power_arm_intervals.csv）")
    optimize.add_argument(
        "--data-dir",
        "--resource-data-dir",
        dest="resource_data_dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="基础数据目录（线路、车辆、站场、供电臂）",
    )
    optimize.add_argument("--mode", choices=("rule", "nsga2"), default="nsga2", help="运行模式")
    optimize.add_argument("--max-shift-min", type=int, default=30, help="时刻最大平移量（分钟）")
    optimize.add_argument("--step-min", type=int, default=5, help="时刻平移步长（分钟）")
    optimize.add_argument("--max-dwell-extension-min", type=int, default=15, help="单站停站最大延长量（分钟）")
    optimize.add_argument("--max-candidates", type=int, default=120, help="候选方案数量上限")
    optimize.add_argument("--population-size", type=int, default=30, help="种群规模")
    optimize.add_argument("--generations", type=int, default=10, help="进化代数")
    optimize.add_argument("--crossover-rate", type=float, default=0.8, help="交叉概率")
    optimize.add_argument("--mutation-rate", type=float, default=0.12, help="变异概率")
    optimize.add_argument("--seed", type=int, default=42, help="随机种子")
    optimize.add_argument(
        "--strict-visualizations",
        action="store_true",
        help="任一预期图表生成失败时直接判定优化失败。",
    )
    optimize.set_defaults(func=cmd_optimize_timetable)

    explain = subparsers.add_parser(
        "explain-optimization",
        help="为已有优化结果目录生成收益归因与瓶颈解释报告。",
    )
    explain.add_argument("--result-dir", type=Path, required=True, help="结果读取目录")
    explain.add_argument(
        "--workflow",
        choices=("auto", "timetable_optimization", "dispatch"),
        default="auto",
        help="工作流名称",
    )
    explain.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已有产物",
    )
    explain.set_defaults(func=cmd_explain_optimization)

    dispatch = subparsers.add_parser("dispatch-case", help="按指定能量场景运行重空车调度算例。")
    dispatch.add_argument(
        "--optimization-mode",
        choices=("joint_energy_planning", "dispatch_only"),
        default="dispatch_only",
        help="优化模式：dispatch_only 独立调度，joint_energy_planning 联合储能规划。",
    )
    dispatch.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    dispatch.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "dispatch_storage_no_direct_phase2600", help="结果输出目录")
    dispatch.add_argument(
        "--energy-scenario",
        choices=("storage_no_direct", "auto"),
        default="storage_no_direct",
        help="能量场景：storage_no_direct（仅储能复用）或 auto（自动判定）",
    )
    dispatch.add_argument(
        "--objective-mode",
        choices=("balanced", "capacity_surplus", "capacity_tight"),
        default="balanced",
        help="调度目标模式：balanced、capacity_surplus 或 capacity_tight",
    )
    dispatch.add_argument("--search-method", choices=("nsga2", "grid", "evolutionary"), default="nsga2", help="搜索算法：nsga2、grid 或 evolutionary")
    dispatch.add_argument("--population-size", type=int, default=12, help="种群规模")
    dispatch.add_argument("--generations", type=int, default=4, help="进化代数")
    dispatch.add_argument("--seed", type=int, default=101, help="随机种子")
    dispatch.add_argument("--heavy-count", type=int, default=3, help="重车列数")
    dispatch.add_argument("--empty-count", type=int, default=3, help="空车列数")
    dispatch.add_argument(
        "--baseline-phase-s",
        type=int,
        default=2600,
        help="基线发车相位（秒）",
    )
    dispatch.add_argument("--baseline-heavy-headway-s", type=int, default=3300, help="基线重车追踪间隔（秒）")
    dispatch.add_argument("--baseline-empty-headway-s", type=int, default=2700, help="基线空车追踪间隔（秒）")
    dispatch.add_argument("--min-depart-gap-s", type=int, default=300, help="相邻列车最小发车间隔（秒）")
    dispatch.add_argument("--horizon-s", type=int, default=14400, help="优化时间窗长度（秒）")
    dispatch.add_argument("--execute-window-s", type=int, default=1800, help="滚动执行窗口长度（秒）")
    dispatch.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    dispatch.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.0, help="弃能惩罚（元/千瓦时）")
    dispatch.add_argument("--battery-depreciation-per-kwh", type=float, default=None, help="储能每千瓦时折旧成本（元/千瓦时）")
    dispatch.add_argument("--battery-grid-price-per-kwh", type=float, default=None, help="储能购电电价（元/千瓦时）")
    dispatch.add_argument(
        "--objective-priority",
        choices=("energy_first", "cost_first", "balanced"),
        default="energy_first",
        help="候选排序优先级：energy_first、cost_first 或 balanced",
    )
    dispatch.add_argument(
        "--search-profile",
        choices=("quick", "standard", "large"),
        default="standard",
        help="搜索档位：quick、standard 或 large",
    )
    dispatch.add_argument(
        "--enable-energy-observability",
        action="store_true",
        default=True,
        help="启用能量可观测性（弃能得到显式可视化）",
    )
    dispatch.add_argument("--storage-shift-mutation-s", type=int, default=300, help="储能对齐位移变异幅度（秒）")
    dispatch.add_argument("--search-max-storage-align-shift-s", type=int, default=1200, help="搜索用储能对齐位移上限（秒）")
    dispatch.add_argument("--search-max-hold-s", type=int, default=900, help="搜索用停站延长上限（秒）")
    dispatch.add_argument("--search-max-phase-s", type=int, default=5400, help="搜索用相位偏移上限（秒）")
    dispatch.add_argument("--phase-mutation-s", type=int, default=300, help="发车相位变异幅度（秒）")
    dispatch.add_argument("--hold-mutation-s", type=int, default=180, help="停站延长变异幅度（秒）")
    dispatch.add_argument("--headway-mutation-s", type=int, default=300, help="追踪间隔变异幅度（秒）")
    dispatch.add_argument("--search-min-headway-s", type=int, default=2400, help="搜索用追踪间隔下限（秒）")
    dispatch.add_argument("--search-max-headway-s", type=int, default=4200, help="搜索用追踪间隔上限（秒）")
    dispatch.add_argument("--elite-count", type=int, default=4, help="每代保留的精英个体数")
    dispatch.add_argument("--empty-mass-tons", type=float, help="空车编组质量（吨）")
    dispatch.add_argument("--battery-capacity-kwh", type=float, help="储能可用容量（千瓦时）")
    dispatch.add_argument("--battery-max-charge-power-kw", type=float, help="储能最大充电功率（千瓦）")
    dispatch.add_argument("--battery-max-discharge-power-kw", type=float, help="储能最大放电功率（千瓦）；未提供时按 0 保守处理")
    dispatch.add_argument("--battery-round-trip-efficiency", type=float, help="储能往返效率，取值 (0, 1]")
    dispatch.add_argument(
        "--enable-storage-preset-search",
        action="store_true",
        default=True,
        help="启用储能预设搜索",
    )
    dispatch.add_argument(
        "--disable-storage-preset-search",
        action="store_true",
        help="关闭储能预设搜索",
    )
    dispatch.add_argument(
        "--storage-preset-ids",
        type=str,
        default="virtual_two_section_base,virtual_two_section_high_power,virtual_two_section_high_capacity,virtual_two_section_high_power_capacity,virtual_expanded_regen_corridor",
        help="储能预设编号列表",
    )
    dispatch.add_argument(
        "--disable-energy-observability",
        action="store_true",
        help="关闭能量可观测性设置",
    )
    dispatch.set_defaults(func=cmd_dispatch_case)

    heavy_empty_plan = subparsers.add_parser(
        "heavy-empty-plan",
        help="运行重空车网络优化并输出五类调度方案结果。",
    )
    heavy_empty_plan.add_argument("--template", type=Path, default=DEFAULT_HEAVY_EMPTY_TEMPLATE, help="输入模板文件")
    heavy_empty_plan.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    heavy_empty_plan.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "heavy_empty_plan",
        help="结果输出目录",
    )
    heavy_empty_plan.add_argument(
        "--scenario-id",
        action="append",
        default=None,
        help="场景编号",
    )
    heavy_empty_plan.add_argument("--population-size", type=int, default=None, help="种群规模")
    heavy_empty_plan.add_argument("--generations", type=int, default=None, help="进化代数")
    heavy_empty_plan.set_defaults(func=cmd_heavy_empty_plan)

    validation = subparsers.add_parser(
        "validation",
        help="运行技术方案 4.1.2.4 的四组验证场景。",
    )
    validation.add_argument("--template", type=Path, default=DEFAULT_HEAVY_EMPTY_TEMPLATE, help="输入模板文件")
    validation.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    validation.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "validation",
        help="结果输出目录",
    )
    validation.add_argument("--scenario-id", default=None, help="场景编号")
    validation.set_defaults(func=cmd_validation)

    sensitivity = subparsers.add_parser(
        "sensitivity",
        help="运行技术方案 4.2.1.2(1) 的敏感性/稳健性场景集。",
    )
    sensitivity.add_argument("--template", type=Path, default=DEFAULT_HEAVY_EMPTY_TEMPLATE, help="输入模板文件")
    sensitivity.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    sensitivity.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "sensitivity",
        help="结果输出目录",
    )
    sensitivity.add_argument("--scenario-id", default=None, help="场景编号")
    sensitivity.add_argument("--population-size", type=int, default=None, help="种群规模")
    sensitivity.add_argument("--generations", type=int, default=None, help="进化代数")
    sensitivity.set_defaults(func=cmd_sensitivity)

    benchmark = subparsers.add_parser(
        "benchmark-algorithm",
        help="运行列车数规模扫描、多种子稳定性与同种子复现实验。",
    )
    benchmark.add_argument("--output-dir", type=Path, default=Path("paper") / "experiments" / "algorithm_scale_stability", help="结果输出目录")
    benchmark.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    benchmark.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE, help="运行图 Excel 路径")
    benchmark.add_argument("--target", action="append", choices=("timetable", "dispatch"), dest="targets", help="目标对象（数据目录或结果目录）")
    benchmark.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3, 4], help="规模扫描的列车数取值")
    benchmark.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71], help="多种子取值列表")
    benchmark.add_argument("--reference-scale", type=int, default=3, help="参照规模（列车数）")
    benchmark.add_argument("--replay-count", type=int, default=2, help="扰动回放轮次")
    benchmark.add_argument("--population-size", type=int, default=8, help="种群规模")
    benchmark.add_argument("--generations", type=int, default=3, help="进化代数")
    benchmark.add_argument("--timeout-s", type=int, default=900, help="单步超时（秒）")
    benchmark.add_argument("--stability-timeout-s", type=int, default=1200, help="稳定性扫描单次超时（秒）")
    benchmark.add_argument("--timetable-copy-shift-s", type=int, default=7200, help="运行图副本整体平移量（秒）")
    benchmark.add_argument("--min-seed-feasible-rate", type=float, default=0.8, help="多种子可行率下限")
    benchmark.add_argument("--max-seed-objective-cv", type=float, default=0.25, help="多种子目标值变异系数上限")
    benchmark.set_defaults(func=cmd_algorithm_benchmark)

    differential = subparsers.add_parser(
        "test-random-differential",
        help="在随机合成算例上用独立参考模型与生产算法做差分比对。",
    )
    differential.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "random_synthetic_differential_current",
        help="结果输出目录",
    )
    differential.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[20260909, 20260910, 20260911],
        help="多种子取值列表",
    )
    differential.add_argument("--energy-cases", type=int, default=500, help="能耗场景集合")
    differential.add_argument("--time-slicing-cases", type=int, default=300, help="时间片粒度用例集合")
    differential.add_argument("--resource-cases", type=int, default=500, help="资源场景集合")
    differential.add_argument("--pareto-cases", type=int, default=300, help="帕累托对比用例集合")
    differential.set_defaults(func=cmd_random_synthetic_differential)

    realtime_matrix = subparsers.add_parser(
        "test-realtime-anomalies",
        help="注入失效、滞后、重复、乱序与中断的实时状态并核验恢复动作。",
    )
    realtime_matrix.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "realtime_state_anomaly_matrix_current",
        help="结果输出目录",
    )
    realtime_matrix.set_defaults(func=cmd_realtime_state_anomaly_matrix)

    data_anomaly_matrix = subparsers.add_parser(
        "test-synthetic-data-anomalies",
        help="注入格式错误与前后不一致的合成输入包，核验校验门禁。",
    )
    data_anomaly_matrix.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="数据源目录",
    )
    data_anomaly_matrix.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "synthetic_data_anomaly_matrix_current",
        help="结果输出目录",
    )
    data_anomaly_matrix.set_defaults(func=cmd_synthetic_data_anomaly_matrix)

    abnormal_extreme = subparsers.add_parser(
        "test-abnormal-extreme-inputs",
        help="运行静态数据、平台参数、实时状态、核心极端与随机差分合并输入套件。",
    )
    abnormal_extreme.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "abnormal_extreme_input_current",
        help="结果输出目录",
    )
    abnormal_extreme.add_argument("--seeds", nargs="+", type=int, default=[20260909, 20260910, 20260911], help="多种子取值列表")
    abnormal_extreme.add_argument("--energy-cases", type=int, default=500, help="能耗场景集合")
    abnormal_extreme.add_argument("--time-slicing-cases", type=int, default=300, help="时间片粒度用例集合")
    abnormal_extreme.add_argument("--resource-cases", type=int, default=500, help="资源场景集合")
    abnormal_extreme.add_argument("--pareto-cases", type=int, default=300, help="帕累托对比用例集合")
    abnormal_extreme.set_defaults(func=cmd_abnormal_extreme_input_suite)

    interface_contract = subparsers.add_parser(
        "verify-interface-contract",
        help="对照实现与 DDL 核验冻结的平台/数据库接口契约。",
    )
    interface_contract.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "interface_contract_freeze",
        help="结果输出目录",
    )
    interface_contract.set_defaults(func=cmd_verify_interface_contract)

    platform_stress = subparsers.add_parser(
        "test-platform-tasks",
        help="对 PostgreSQL 任务队列施压，注入租约、取消、过期写入与事务故障。",
    )
    platform_stress.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "platform_task_stress_fault_current",
        help="结果输出目录",
    )
    platform_stress.add_argument("--task-count", type=int, default=120, help="并发任务数")
    platform_stress.add_argument("--worker-count", type=int, default=12, help="并行进程数")
    platform_stress.add_argument("--idempotency-burst", type=int, default=32, help="幂等重复提交次数（数据库联调）")
    platform_stress.add_argument("--max-operation-p95-ms", type=float, default=2000.0, help="单次操作 P95 耗时上限（毫秒）")
    platform_stress.add_argument("--min-claim-throughput-per-s", type=float, default=10.0, help="最低声明吞吐量（条/秒）")
    platform_stress.set_defaults(func=cmd_platform_task_stress_fault)

    dispatch_capacity = subparsers.add_parser(
        "benchmark-dispatch-capacity",
        help="测定重空调度能力边界与搜索预算的质量权衡。",
    )
    dispatch_capacity.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "dispatch_capacity_quality",
        help="结果输出目录",
    )
    dispatch_capacity.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    dispatch_capacity.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3, 4], help="规模扫描的列车数取值")
    dispatch_capacity.add_argument("--reference-scale", type=int, default=2, help="参照规模（列车数）")
    dispatch_capacity.add_argument("--seed", type=int, default=11, help="随机种子")
    dispatch_capacity.add_argument("--timeout-s", type=int, default=600, help="单步超时（秒）")
    dispatch_capacity.set_defaults(func=cmd_dispatch_capacity_benchmark)

    optimality_gap = subparsers.add_parser(
        "benchmark-small-optimality-gap",
        help="对比小规模全域最优解与离散域 NSGA-II 结果的差距。",
    )
    optimality_gap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "E12_small_scale_optimality_gap",
        help="结果输出目录",
    )
    optimality_gap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    optimality_gap.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3], help="规模扫描的列车数取值")
    optimality_gap.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71], help="多种子取值列表")
    optimality_gap.add_argument(
        "--profiles",
        nargs="+",
        choices=("quick", "standard", "large"),
        default=["quick", "standard", "large"],
        help="搜索档位集合",
    )
    optimality_gap.add_argument("--horizon-s", type=int, default=14400, help="优化时间窗长度（秒）")
    optimality_gap.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    optimality_gap.set_defaults(func=cmd_small_scale_optimality_gap)

    rolling_benchmark = subparsers.add_parser(
        "benchmark-rolling-rescheduling",
        help="运行状态驱动的多轮滚动重调度测试。",
    )
    rolling_benchmark.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "E15_synthetic_rolling_rescheduling",
        help="结果输出目录",
    )
    rolling_benchmark.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    rolling_benchmark.add_argument("--population-size", type=int, default=2, help="种群规模")
    rolling_benchmark.add_argument("--generations", type=int, default=1, help="进化代数")
    rolling_benchmark.add_argument("--seed", type=int, default=20260907, help="随机种子")
    rolling_benchmark.add_argument("--disable-recovery", action="store_true", help="关闭冲突恢复与精确恢复，只做常规搜索")
    rolling_benchmark.add_argument("--disable-safety-retry", action="store_true", help="关闭安全降级重试")
    rolling_benchmark.add_argument("--max-safety-retries", type=int, default=1, help="安全降级最大重试次数")
    rolling_benchmark.add_argument("--manual-after-withheld", type=int, default=2, help="扣留后转人工处置")
    rolling_benchmark.add_argument(
        "--disturbance-history",
        type=Path,
        default=None,
        help="历史扰动回放JSON；提供后替代内置合成扰动序列。",
    )
    rolling_benchmark.add_argument(
        "--disturbance-history-label",
        default=None,
        help=argparse.SUPPRESS,
    )
    rolling_benchmark.add_argument(
        "--storage-devices-json",
        default="",
        help="滚动窗口起点的逐设备SOC、可用状态和临时功率上限JSON数组。",
    )
    rolling_benchmark.set_defaults(func=cmd_synthetic_rolling_rescheduling)

    rolling_shadow = subparsers.add_parser(
        "rolling-budgeted-shadow",
        help="显式实验开关下的多窗口影子联调，不允许现场执行。",
    )
    rolling_shadow.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    rolling_shadow.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "rolling_budgeted_shadow",
        help="结果输出目录（必须是新目录）",
    )
    rolling_shadow.add_argument("--shadow-request", type=Path, required=True, help="影子联调请求 JSON 路径")
    rolling_shadow.add_argument(
        "--experimental-budgeted-shadow",
        action="store_true",
        help="启用受预算约束的影子联调实验开关（不显式开启则拒绝运行）",
    )
    rolling_shadow.add_argument("--population-size", type=int, default=12, help="种群规模")
    rolling_shadow.add_argument("--generations", type=int, default=10, help="进化代数")
    rolling_shadow.add_argument("--seed", type=int, default=11, help="随机种子")
    rolling_shadow.add_argument("--shadow-job-wall-limit-s", type=float, default=240, help="影子作业墙钟上限（秒）")
    rolling_shadow.set_defaults(func=cmd_rolling_budgeted_shadow)

    recovery_ablation = subparsers.add_parser(
        "benchmark-recovery-ablation",
        help="对比关闭与开启恢复级联时的滚动重调度效果。",
    )
    recovery_ablation.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "E15_recovery_ablation",
        help="结果输出目录",
    )
    recovery_ablation.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    recovery_ablation.add_argument("--population-size", type=int, default=2, help="种群规模")
    recovery_ablation.add_argument("--generations", type=int, default=1, help="进化代数")
    recovery_ablation.add_argument("--seed", type=int, default=20260907, help="随机种子")
    recovery_ablation.set_defaults(func=cmd_recovery_ablation)

    feasibility_probe = subparsers.add_parser(
        "probe-dispatch-feasibility",
        help="扫描核心稳健的资源可行发车相位与追踪间隔组合。",
    )
    feasibility_probe.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "dispatch_robust_feasibility_probe",
        help="结果输出目录",
    )
    feasibility_probe.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    feasibility_probe.add_argument("--heavy-count", type=int, default=3, help="重车列数")
    feasibility_probe.add_argument("--empty-count", type=int, default=3, help="空车列数")
    feasibility_probe.add_argument(
        "--headways-s",
        nargs="+",
        type=int,
        default=[2700, 3000, 3300, 3600, 3900, 4200],
        help="追踪间隔候选取值集合（秒）",
    )
    feasibility_probe.add_argument("--offset-step-s", type=int, default=60, help="相位偏移步长（秒）")
    feasibility_probe.add_argument("--max-offset-s", type=int, default=5400, help="允许的最大相位偏移（秒）")
    feasibility_probe.add_argument("--horizon-s", type=int, default=14400, help="优化时间窗长度（秒）")
    feasibility_probe.add_argument("--targeted-local", action="store_true", help="只做定向局部修复")
    feasibility_probe.add_argument("--heavy-headway-s", type=int, default=3300, help="重车追踪间隔（秒）")
    feasibility_probe.add_argument("--empty-headway-s", type=int, default=2700, help="空车追踪间隔（秒）")
    feasibility_probe.add_argument("--phase-s", type=int, default=2600, help="基准发车相位（秒）")
    feasibility_probe.add_argument("--initial-scan-csv", type=Path, help="初始状态扫描结果 CSV 路径")
    feasibility_probe.add_argument("--adjustment-step-s", type=int, default=60, help="运行图调整步长（秒）")
    feasibility_probe.add_argument("--max-absolute-adjustment-s", type=int, default=600, help="单列车最大绝对调整量（秒）")
    feasibility_probe.add_argument("--max-iterations", type=int, default=8, help="最大迭代轮数")
    feasibility_probe.add_argument("--beam-width", type=int, default=6, help="束搜索每层保留的候选数")
    feasibility_probe.set_defaults(func=cmd_dispatch_feasibility_probe)

    single_candidate_profile = subparsers.add_parser(
        "profile-dispatch-candidate",
        help="对单个完整稳健候选方案做隔离性能剖析。",
    )
    single_candidate_profile.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "dispatch_single_candidate_profile",
        help="结果输出目录",
    )
    single_candidate_profile.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    single_candidate_profile.add_argument("--heavy-count", type=int, default=4, help="重车列数")
    single_candidate_profile.add_argument("--empty-count", type=int, default=4, help="空车列数")
    single_candidate_profile.add_argument("--heavy-headway-s", type=int, default=3300, help="重车追踪间隔（秒）")
    single_candidate_profile.add_argument("--empty-headway-s", type=int, default=3300, help="空车追踪间隔（秒）")
    single_candidate_profile.add_argument("--phase-s", type=int, default=840, help="基准发车相位（秒）")
    single_candidate_profile.add_argument("--storage-preset-id", default="virtual_two_section_base", help="指定储能预设编号")
    single_candidate_profile.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    single_candidate_profile.add_argument("--repeat-count", type=int, default=3, help="重复运行次数")
    single_candidate_profile.add_argument("--top", type=int, default=40, help="只输出前 N 条")
    single_candidate_profile.set_defaults(func=cmd_dispatch_single_candidate_profile)

    joint_robustness = subparsers.add_parser(
        "benchmark-joint-parameter-robustness",
        help="在联合物理参数区间与运行扰动下评价同一张运行图。",
    )
    joint_robustness.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    joint_robustness.add_argument(
        "--parameter-ranges",
        type=Path,
        default=Path("data_templates") / "joint_parameter_ranges_template.json",
        help="参数区间定义 JSON 路径",
    )
    joint_robustness.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "E13_joint_parameter_robustness",
        help="结果输出目录",
    )
    joint_robustness.add_argument("--heavy-count", type=int, default=2, help="重车列数")
    joint_robustness.add_argument("--empty-count", type=int, default=2, help="空车列数")
    joint_robustness.add_argument("--heavy-headway-s", type=int, default=3300, help="重车追踪间隔（秒）")
    joint_robustness.add_argument("--empty-headway-s", type=int, default=3300, help="空车追踪间隔（秒）")
    joint_robustness.add_argument("--phase-s", type=int, default=840, help="基准发车相位（秒）")
    joint_robustness.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    joint_robustness.set_defaults(func=cmd_joint_parameter_robustness)

    extended_scale = subparsers.add_parser(
        "benchmark-dispatch-extended",
        help="运行定长与扩展时间窗的 12/16 列车调度监控算例。",
    )
    extended_scale.add_argument(
        "--plan",
        type=Path,
        default=Path("paper") / "experiments" / "dispatch_extended_scale_test_plan.json",
        help="执行计划文件（dry-run 生成的计划）",
    )
    extended_scale.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "dispatch_extended_scale_benchmark",
        help="结果输出目录",
    )
    extended_scale.add_argument(
        "--cases",
        nargs="+",
        choices=("F12", "F16", "E12", "E16"),
        default=["F12", "F16", "E12", "E16"],
        help="本次运行的用例集合",
    )
    extended_scale.set_defaults(func=cmd_dispatch_extended_scale_benchmark)

    energy_sensitivity = subparsers.add_parser(
        "energy-sensitivity",
        help="对当前基线做相位、模板、储能与惩罚项的能量敏感性扫描。",
    )
    energy_sensitivity.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    energy_sensitivity.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "energy_sensitivity_scan",
        help="结果输出目录",
    )
    energy_sensitivity.set_defaults(func=cmd_energy_sensitivity)

    storage_search = subparsers.add_parser(
        "storage-energy-search",
        help="搜索可编辑的虚拟储能预设（容量、功率、覆盖范围）以降低能耗。",
    )
    storage_search.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    storage_search.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "storage_energy_search", help="结果输出目录")
    storage_search.add_argument("--heavy-headway-s", type=int, default=3300, help="重车追踪间隔（秒）")
    storage_search.add_argument("--empty-headway-s", type=int, default=2700, help="空车追踪间隔（秒）")
    storage_search.add_argument("--phase-s", type=int, default=2600, help="基准发车相位（秒）")
    storage_search.add_argument("--heavy-count", type=int, default=3, help="重车列数")
    storage_search.add_argument("--empty-count", type=int, default=3, help="空车列数")
    storage_search.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    storage_search.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.05, help="弃能惩罚（元/千瓦时）")
    storage_search.add_argument("--min-depart-gap-s", type=int, default=900, help="相邻列车最小发车间隔（秒）")
    storage_search.set_defaults(func=cmd_storage_energy_search)


    smoke = subparsers.add_parser("smoke", help="运行当前短测校验脚本。")
    smoke.add_argument("--only", nargs="*", help="只运行指定用例")
    smoke.add_argument(
        "--include-long",
        action="store_true",
        help="同时运行长测用例",
    )
    smoke.set_defaults(func=cmd_smoke)

    experiment_suite = subparsers.add_parser(
        "experiment-suite",
        help="运行多算例仿真实验与敏感性测试，并输出中文解读报告。",
    )
    experiment_suite.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    experiment_suite.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "simulation_experiment_suite",
        help="实验产物根目录",
    )
    experiment_suite.set_defaults(func=cmd_experiment_suite)

    ingestion = subparsers.add_parser(
        "check-ingestion",
        help="在替换现有算法输入前检查新到的正式数据。",
    )
    ingestion.add_argument("--input", type=Path, default=DEFAULT_DATA_DIR, help="待检查的输入文件或目录")
    ingestion.add_argument(
        "--kind",
        choices=("all", "stations", "geometry", "timetable", "power-arm", "storage", "traction", "formation", "smart-meter"),
        default="all",
        help="用例类别",
    )
    ingestion.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE, help="运行图 Excel 路径")
    ingestion.add_argument("--station-csv", type=Path, default=None, help="车站表 CSV 路径")
    ingestion.add_argument("--route-metadata", type=Path, default=None, help="线路元数据 JSON 路径")
    ingestion.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "real_data_ingestion_check", help="结果输出目录")
    ingestion.set_defaults(func=cmd_check_ingestion)

    acceptance = subparsers.add_parser(
        "accept-official-data",
        help="执行严格的正式数据验收门禁，不修改数据目录。",
    )
    add_common_real_data_args(acceptance)
    acceptance.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "formal_data_acceptance", help="结果输出目录")
    acceptance.set_defaults(func=cmd_accept_official_data)

    result_check = subparsers.add_parser(
        "check-results",
        help="核查仿真与优化输出汇总的守恒性与一致性。",
    )
    result_check.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="实验产物根目录")
    result_check.add_argument("--report-dir", type=Path, default=None, help="报告输出目录")
    result_check.set_defaults(func=cmd_check_results)

    readiness = subparsers.add_parser(
        "official-data-readiness",
        help="执行只读的正式数据验收，可选隔离仿真并比对结果。",
    )
    readiness.add_argument("--data-dir", type=Path, required=True, help="基础数据目录（线路、车辆、站场、供电臂）")
    readiness.add_argument("--source-dir", type=Path, required=True, help="数据源目录")
    readiness.add_argument("--timetable", type=Path, required=True, help="运行图 Excel 路径")
    readiness.add_argument("--output-dir", type=Path, required=True, help="结果输出目录")
    readiness.add_argument("--run-simulation", action="store_true", help="完成后接着运行一次仿真")
    readiness.add_argument("--baseline-output", type=Path, default=None, help="基线结果输出路径")
    readiness.set_defaults(func=cmd_official_data_readiness)

    formal_experiments = subparsers.add_parser(
        "formal-experiment-suite",
        help="正式数据严格验收后，运行基线、储能消融、规则、多种子 NSGA-II、质量审计与一份 KPI 汇总。",
    )
    formal_experiments.add_argument("--data-dir", type=Path, required=True, help="基础数据目录（线路、车辆、站场、供电臂）")
    formal_experiments.add_argument("--source-dir", type=Path, required=True, help="数据源目录")
    formal_experiments.add_argument("--timetable", type=Path, required=True, help="运行图 Excel 路径")
    formal_experiments.add_argument("--output-root", type=Path, required=True, help="实验产物根目录")
    formal_experiments.add_argument("--window-id", required=True, help="滚动窗口编号")
    formal_experiments.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71], help="多种子取值列表")
    formal_experiments.add_argument("--settlement-steps-s", nargs="+", type=int, default=[1, 5, 10], help="待评估的结算时间步长集合（秒）")
    formal_experiments.add_argument("--max-shift-min", type=int, default=10, help="时刻最大平移量（分钟）")
    formal_experiments.add_argument("--step-min", type=int, default=5, help="时刻平移步长（分钟）")
    formal_experiments.add_argument("--max-dwell-extension-min", type=int, default=5, help="单站停站最大延长量（分钟）")
    formal_experiments.add_argument("--max-candidates", type=int, default=50, help="候选方案数量上限")
    formal_experiments.add_argument("--population-size", type=int, default=20, help="种群规模")
    formal_experiments.add_argument("--generations", type=int, default=20, help="进化代数")
    formal_experiments.add_argument("--crossover-rate", type=float, default=0.9, help="交叉概率")
    formal_experiments.add_argument("--mutation-rate", type=float, default=0.2, help="变异概率")
    formal_experiments.add_argument(
        "--no-strict-visualizations",
        action="store_true",
        help="图表生成失败不判为任务失败",
    )
    formal_experiments.add_argument(
        "--calibration-summary",
        type=Path,
        default=None,
        help="能耗校准结果汇总文件路径",
    )
    formal_experiments.add_argument(
        "--require-calibration",
        action="store_true",
        help="缺少校准系数时中断",
    )
    formal_experiments.set_defaults(func=cmd_formal_experiment_suite)

    delivery_marker = subparsers.add_parser(
        "create-official-data-marker",
        help="正式交付包完整拷贝后，生成最终清单与 SHA-256 标记。",
    )
    delivery_marker.add_argument("--package-dir", type=Path, required=True, help="交付包目录")
    delivery_marker.add_argument("--delivery-id", required=True, help="交付批次标识，用于产物命名与追溯")
    delivery_marker.add_argument("--data-dir", required=True, help="基础数据目录（线路、车辆、站场、供电臂）")
    delivery_marker.add_argument("--source-dir", required=True, help="数据源目录")
    delivery_marker.add_argument("--timetable", required=True, help="运行图 Excel 路径")
    delivery_marker.add_argument("--window-id", required=True, help="滚动窗口编号")
    delivery_marker.add_argument("--calibration-summary", default=None, help="能耗校准结果汇总文件路径")
    delivery_marker.add_argument("--marker-name", default="OFFICIAL_DATA_READY.json", help="正式数据标记文件名")
    delivery_marker.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71], help="多种子取值列表")
    delivery_marker.add_argument("--settlement-steps-s", nargs="+", type=int, default=[1, 5, 10], help="待评估的结算时间步长集合（秒）")
    delivery_marker.add_argument("--max-shift-min", type=int, default=10, help="时刻最大平移量（分钟）")
    delivery_marker.add_argument("--step-min", type=int, default=5, help="时刻平移步长（分钟）")
    delivery_marker.add_argument("--max-dwell-extension-min", type=int, default=5, help="单站停站最大延长量（分钟）")
    delivery_marker.add_argument("--max-candidates", type=int, default=50, help="候选方案数量上限")
    delivery_marker.add_argument("--population-size", type=int, default=20, help="种群规模")
    delivery_marker.add_argument("--generations", type=int, default=20, help="进化代数")
    delivery_marker.add_argument("--no-strict-visualizations", action="store_true", help="图表生成失败不判为任务失败")
    delivery_marker.add_argument("--require-calibration", action="store_true", help="缺少校准系数时中断")
    delivery_marker.set_defaults(func=cmd_create_official_data_marker)

    auto_trigger = subparsers.add_parser(
        "official-data-auto-trigger",
        help="对已完成的正式交付执行一次校验、快照与处理。",
    )
    auto_trigger.add_argument("--package-dir", type=Path, required=True, help="交付包目录")
    auto_trigger.add_argument(
        "--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT / "official_data_auto_trigger",
        help="实验产物根目录",
    )
    auto_trigger.add_argument("--marker-name", default="OFFICIAL_DATA_READY.json", help="正式数据标记文件名")
    auto_trigger.add_argument("--watch", action="store_true", help="持续监听目录")
    auto_trigger.add_argument("--poll-seconds", type=float, default=30.0, help="轮询间隔（秒）")
    auto_trigger.add_argument("--retry", action="store_true", help="失败重试次数")
    auto_trigger.set_defaults(func=cmd_official_data_auto_trigger)

    paper_experiments = subparsers.add_parser(
        "paper-experiment-pipeline",
        help="运行清单定义的多窗口研究，产出配对统计、表格与图。",
    )
    paper_experiments.add_argument("--study-manifest", type=Path, required=True, help="实验清单文件路径")
    paper_experiments.add_argument("--output-root", type=Path, required=True, help="实验产物根目录")
    paper_experiments.add_argument(
        "--aggregate-only",
        action="store_true",
        help="只做汇总，不重跑实验",
    )
    paper_experiments.set_defaults(func=cmd_paper_experiment_pipeline)

    paper_aggregate = subparsers.add_parser(
        "aggregate-paper-experiments",
        help="把当前分散的论文证据汇总为一份报告、矩阵、指标表与缺口清单。",
    )
    paper_aggregate.add_argument(
        "--manifest",
        type=Path,
        default=Path("paper") / "实验设计" / "论文实验自动汇总清单.json",
        help="交付清单文件路径",
    )
    paper_aggregate.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "论文实验自动汇总",
        help="结果输出目录",
    )
    paper_aggregate.add_argument(
        "--report-path",
        type=Path,
        default=Path("paper") / "experiments" / "实验结果汇总.md",
        help="报告文件输出路径",
    )
    paper_aggregate.set_defaults(func=cmd_aggregate_paper_experiments)

    intake = subparsers.add_parser(
        "official-intake-dry-run",
        help="在不替换运行数据的前提下试运行正式数据收件流程。",
    )
    intake.add_argument("--inbox-dir", type=Path, default=DEFAULT_DATA_DIR.parent / "official_inbox", help="待处理请求收件目录")
    intake.add_argument("--template-dir", type=Path, default=Path("data_templates") / "official_intake", help="模板目录")
    intake.add_argument("--status-json", type=Path, default=Path("docs") / "official_data_intake_status.json", help="状态文件路径")
    intake.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "official_intake_dry_run", help="结果输出目录")
    intake.add_argument("--update-status", action="store_true", help="处理后回写状态文件")
    intake.set_defaults(func=cmd_official_intake_dry_run)


    external_profile = subparsers.add_parser(
        "profile-external-data",
        help="剖析外部供给方文件并给出候选字段映射，不修改源文件。",
    )
    external_profile.add_argument("--input", type=Path, required=True, help="待检查的输入文件或目录")
    external_profile.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "external_data_profile",
        help="结果输出目录",
    )
    external_profile.add_argument("--max-rows", type=int, default=5000, help="单文件读取行数上限")
    external_profile.set_defaults(func=cmd_profile_external_data)

    workflow = subparsers.add_parser(
        "simulate",
        help="用已复核真实数据与显式占位值运行端到端仿真流程。",
    )
    add_common_real_data_args(workflow)
    workflow.add_argument("--smart-meter-dir", type=Path, default=DEFAULT_SMART_METER_DIR, help="电表数据目录")
    workflow.add_argument(
        "--rebuild-data",
        action="store_true",
        help="重建基础数据",
    )
    workflow.add_argument(
        "--require-official-data",
        action="store_true",
        help="输入未通过正式来源核验时直接阻塞",
    )
    workflow.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="实验产物根目录")
    workflow.add_argument("--max-per-normalized-trainid", type=int, default=50, help="每个归一化车次保留的样本数上限")
    workflow.add_argument("--max-realtime-rows-per-file", type=int, default=100000, help="单文件实时样本行数上限")
    workflow.add_argument("--dispatch-population-size", type=int, default=12, help="重空调度种群规模")
    workflow.add_argument("--dispatch-generations", type=int, default=4, help="重空调度进化代数")
    workflow.add_argument(
        "--optimization-mode",
        choices=("joint_energy_planning", "dispatch_only"),
        default="dispatch_only",
        help="重空调度模式：默认独立调度，可显式启用联合储能规划。",
    )
    workflow.add_argument(
        "--enable-energy-observability",
        action="store_true",
        default=True,
        help="启用能量可观测性（弃能得到显式可视化）",
    )
    workflow.add_argument(
        "--disable-energy-observability",
        action="store_true",
        help="关闭能量可观测性设置",
    )
    workflow.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.0, help="弃能惩罚（元/千瓦时）")
    workflow.add_argument("--battery-depreciation-per-kwh", type=float, default=None, help="储能每千瓦时折旧成本（元/千瓦时）")
    workflow.add_argument("--battery-grid-price-per-kwh", type=float, default=None, help="储能购电电价（元/千瓦时）")
    workflow.add_argument(
        "--objective-priority",
        choices=("energy_first", "cost_first", "balanced"),
        default="energy_first",
        help="候选排序优先级：energy_first、cost_first 或 balanced",
    )
    workflow.add_argument(
        "--search-profile",
        choices=("quick", "standard", "large"),
        default="standard",
        help="搜索档位：quick、standard 或 large",
    )
    workflow.add_argument(
        "--enable-storage-preset-search",
        action="store_true",
        default=True,
        help="启用储能预设搜索",
    )
    workflow.add_argument(
        "--disable-storage-preset-search",
        action="store_true",
        help="关闭储能预设搜索",
    )
    workflow.add_argument(
        "--storage-preset-ids",
        type=str,
        default="virtual_two_section_base,virtual_two_section_high_power,virtual_two_section_high_capacity,virtual_two_section_high_power_capacity,virtual_expanded_regen_corridor",
        help="储能预设编号列表",
    )
    workflow.add_argument("--heavy-count", type=int, default=3, help="重车列数")
    workflow.add_argument("--empty-count", type=int, default=3, help="空车列数")
    workflow.add_argument(
        "--baseline-phase-s",
        type=int,
        default=2600,
        help="基线发车相位（秒）",
    )
    workflow.add_argument("--baseline-heavy-headway-s", type=int, default=3300, help="基线重车追踪间隔（秒）")
    workflow.add_argument("--baseline-empty-headway-s", type=int, default=2700, help="基线空车追踪间隔（秒）")
    workflow.add_argument("--min-depart-gap-s", type=int, default=300, help="相邻列车最小发车间隔（秒）")
    workflow.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    workflow.add_argument("--timetable-population-size", type=int, default=30, help="运行图优化种群规模")
    workflow.add_argument("--timetable-generations", type=int, default=10, help="运行图优化代数")
    workflow.add_argument("--max-shift-min", type=int, default=30, help="时刻最大平移量（分钟）")
    workflow.add_argument("--step-min", type=int, default=5, help="时刻平移步长（分钟）")
    workflow.add_argument("--max-dwell-extension-min", type=int, default=15, help="单站停站最大延长量（分钟）")
    workflow.add_argument("--max-candidates", type=int, default=120, help="候选方案数量上限")
    workflow.add_argument("--crossover-rate", type=float, default=0.8, help="交叉概率")
    workflow.add_argument("--mutation-rate", type=float, default=0.12, help="变异概率")
    workflow.add_argument("--seed", type=int, default=42, help="随机种子")
    workflow.set_defaults(func=cmd_real_data_workflow)

    real_workflow = subparsers.add_parser(
        "real-data-workflow",
        help="simulate 的别名，保留以兼容旧命令。",
    )
    add_common_real_data_args(real_workflow)
    real_workflow.add_argument("--smart-meter-dir", type=Path, default=DEFAULT_SMART_METER_DIR, help="电表数据目录")
    real_workflow.add_argument(
        "--rebuild-data",
        action="store_true",
        help="重建基础数据",
    )
    real_workflow.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="实验产物根目录")
    real_workflow.add_argument("--max-per-normalized-trainid", type=int, default=50, help="每个归一化车次保留的样本数上限")
    real_workflow.add_argument("--max-realtime-rows-per-file", type=int, default=100000, help="单文件实时样本行数上限")
    real_workflow.add_argument("--dispatch-population-size", type=int, default=12, help="重空调度种群规模")
    real_workflow.add_argument("--dispatch-generations", type=int, default=4, help="重空调度进化代数")
    real_workflow.add_argument(
        "--optimization-mode",
        choices=("joint_energy_planning", "dispatch_only"),
        default="dispatch_only",
        help="重空调度模式：默认独立调度，可显式启用联合储能规划。",
    )
    real_workflow.add_argument(
        "--enable-energy-observability",
        action="store_true",
        default=True,
        help="启用能量可观测性（弃能得到显式可视化）",
    )
    real_workflow.add_argument(
        "--disable-energy-observability",
        action="store_true",
        help="关闭能量可观测性设置",
    )
    real_workflow.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.0, help="弃能惩罚（元/千瓦时）")
    real_workflow.add_argument("--battery-depreciation-per-kwh", type=float, default=None, help="储能每千瓦时折旧成本（元/千瓦时）")
    real_workflow.add_argument("--battery-grid-price-per-kwh", type=float, default=None, help="储能购电电价（元/千瓦时）")
    real_workflow.add_argument(
        "--objective-priority",
        choices=("energy_first", "cost_first", "balanced"),
        default="energy_first",
        help="候选排序优先级：energy_first、cost_first 或 balanced",
    )
    real_workflow.add_argument(
        "--search-profile",
        choices=("quick", "standard", "large"),
        default="standard",
        help="搜索档位：quick、standard 或 large",
    )
    real_workflow.add_argument(
        "--enable-storage-preset-search",
        action="store_true",
        default=True,
        help="启用储能预设搜索",
    )
    real_workflow.add_argument(
        "--disable-storage-preset-search",
        action="store_true",
        help="关闭储能预设搜索",
    )
    real_workflow.add_argument(
        "--storage-preset-ids",
        type=str,
        default="virtual_two_section_base,virtual_two_section_high_power,virtual_two_section_high_capacity,virtual_two_section_high_power_capacity,virtual_expanded_regen_corridor",
        help="储能预设编号列表",
    )
    real_workflow.add_argument("--heavy-count", type=int, default=3, help="重车列数")
    real_workflow.add_argument("--empty-count", type=int, default=3, help="空车列数")
    real_workflow.add_argument(
        "--baseline-phase-s",
        type=int,
        default=2600,
        help="基线发车相位（秒）",
    )
    real_workflow.add_argument("--baseline-heavy-headway-s", type=int, default=3300, help="基线重车追踪间隔（秒）")
    real_workflow.add_argument("--baseline-empty-headway-s", type=int, default=2700, help="基线空车追踪间隔（秒）")
    real_workflow.add_argument("--min-depart-gap-s", type=int, default=300, help="相邻列车最小发车间隔（秒）")
    real_workflow.add_argument("--settlement-step-s", type=int, default=10, help="结算时间步长（秒）")
    real_workflow.add_argument("--timetable-population-size", type=int, default=30, help="运行图优化种群规模")
    real_workflow.add_argument("--timetable-generations", type=int, default=10, help="运行图优化代数")
    real_workflow.add_argument("--max-shift-min", type=int, default=30, help="时刻最大平移量（分钟）")
    real_workflow.add_argument("--step-min", type=int, default=5, help="时刻平移步长（分钟）")
    real_workflow.add_argument("--max-dwell-extension-min", type=int, default=15, help="单站停站最大延长量（分钟）")
    real_workflow.add_argument("--max-candidates", type=int, default=120, help="候选方案数量上限")
    real_workflow.add_argument("--crossover-rate", type=float, default=0.8, help="交叉概率")
    real_workflow.add_argument("--mutation-rate", type=float, default=0.12, help="变异概率")
    real_workflow.add_argument("--seed", type=int, default=42, help="随机种子")
    real_workflow.set_defaults(func=cmd_real_data_workflow)

    _localize_parser_labels(parser)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    from run_manifest import create_run_manifest, finalize_run_manifest

    manifest_context = create_run_manifest(args, raw_argv)
    try:
        result = args.func(args)
        return_code = int(result) if result is not None else 0
    except BaseException as exc:
        finalize_run_manifest(manifest_context, args, return_code=1, error=exc)
        raise
    finalize_run_manifest(manifest_context, args, return_code=return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
