# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from timetable_input import TimetableScenario, load_canonical_timetable, parse_time_to_s
from timetable_input import CanonicalTimetable, TimetableStop, TimetableTrain, TimetableValidationReport
import timetable_optimizer as optimizer_module
import heavy_empty_network_optimizer as network_optimizer_module
from timetable_optimizer import optimize_timetable
from timetable_optimizer import (
    CandidatePlan,
    TimetableGenome,
    _dominates_objectives,
    _effective_objective_tuple,
    _headway_from_constraints,
    assign_crowding_distance,
    baseline_genome,
    decode_genome_to_timetable,
    evaluate_candidates,
    shift_train,
)
from timetable_energy_audit import (
    PowerSection,
    load_power_sections,
    split_running_arc_by_power_boundaries,
)
from smoke_paths import smoke_output
from power_arm_electrical_limits import PowerArmElectricalLimit
import csv


TEMPLATE = Path("data_templates") / "running_diagram_template.xlsx"
OUTPUT_DIR = smoke_output("timetable_optimizer_nsga2_smoke")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    midnight_train = TimetableTrain(
        "T0", "light", "forward", "A", "B", 6000.0, "", "", None
    )
    midnight_timetable = CanonicalTimetable(
        trains=(midnight_train,),
        stops=(
            TimetableStop("T0", 1, "A", 0.0, 0, 60, "stop", "", "", ""),
            TimetableStop("T0", 2, "B", 1.0, 180, 180, "stop", "", "", ""),
        ),
        scenarios=(),
        constraints=(),
        metadata={},
        validation_report=TimetableValidationReport("synthetic"),
    )
    shifted_midnight = shift_train(midnight_timetable, "T0", -300)
    original_durations = [
        midnight_timetable.stops[0].departure_time_s - midnight_timetable.stops[0].arrival_time_s,
        midnight_timetable.stops[1].arrival_time_s - midnight_timetable.stops[0].departure_time_s,
    ]
    shifted_durations = [
        shifted_midnight.stops[0].departure_time_s - shifted_midnight.stops[0].arrival_time_s,
        shifted_midnight.stops[1].arrival_time_s - shifted_midnight.stops[0].departure_time_s,
    ]
    assert shifted_durations == original_durations
    assert min(
        min(stop.arrival_time_s, stop.departure_time_s)
        for stop in shifted_midnight.stops
    ) == 0

    close_boundary_sections = [
        PowerSection("P1", "P1", "forward", 0.0, 4.0, "test"),
        PowerSection("P2", "P2", "forward", 4.0, 4.004, "test"),
        PowerSection("P3", "P3", "forward", 4.004, 10.0, "test"),
    ]
    close_boundary_segments = split_running_arc_by_power_boundaries(
        0.0,
        10.0,
        0,
        100,
        close_boundary_sections,
        model_direction="forward",
    )
    if any(segment.end_time_s <= segment.start_time_s for segment in close_boundary_segments):
        raise AssertionError("close power boundaries left a zero-duration event segment")
    if abs(
        sum(abs(segment.end_km - segment.start_km) for segment in close_boundary_segments)
        - 10.0
    ) > 1e-12:
        raise AssertionError("close power boundaries dropped route distance")

    representable_short_sections = [
        PowerSection("P1", "P1", "forward", 0.0, 4.0, "test"),
        PowerSection("P2", "P2", "forward", 4.0, 4.4, "test"),
        PowerSection("P3", "P3", "forward", 4.4, 10.0, "test"),
    ]
    representable_short_segments = split_running_arc_by_power_boundaries(
        0.0,
        10.0,
        0,
        100,
        representable_short_sections,
        model_direction="forward",
    )
    if [segment.section_id for segment in representable_short_segments] != ["P1", "P2", "P3"]:
        raise AssertionError("positive-duration short power section lost its own power-arm assignment")
    p2_segment = representable_short_segments[1]
    if (p2_segment.start_time_s, p2_segment.end_time_s) != (40, 44):
        raise AssertionError("positive-duration short power section was incorrectly time-merged")

    for invalid_time in (
        float("nan"),
        float("inf"),
        float("-inf"),
        -1,
        1.5,
        0.5 + 0.5 / 86400.0,
    ):
        assert parse_time_to_s(invalid_time) is None
    assert parse_time_to_s(0.5) == 12 * 3600

    with TemporaryDirectory() as temp_name:
        csv_dir = Path(temp_name)
        fixture_rows = {
            "trains.csv": [
                {
                    "train_id": "T1",
                    "train_type": "Heavy",
                    "direction": "forward",
                    "origin_station": "A",
                    "destination_station": "B",
                }
            ],
            "timetable.csv": [
                {
                    "train_id": "T1",
                    "seq": "1",
                    "station_name": "A",
                    "station_km": "0",
                    "arrival_time": "00:00:00",
                    "departure_time": "00:00:00",
                },
                {
                    "train_id": "T1",
                    "seq": "2",
                    "station_name": "B",
                    "station_km": "1",
                    "arrival_time": "00:01:00",
                    "departure_time": "00:01:00",
                },
            ],
            "scenario.csv": [
                {
                    "scenario_id": "valid",
                    "direct_use_enabled": "false",
                    "storage_enabled": "false",
                    "settlement_time_step_s": "10",
                    "transfer_scope": "same_power_arm",
                },
                {
                    "scenario_id": "invalid",
                    "direct_use_enabled": "flase",
                    "storage_enabled": "false",
                    "storage_capacity_kwh": "inf",
                    "settlement_time_step_s": "1.5",
                    "transfer_scope": "same_power_arm",
                },
                {
                    "scenario_id": "missing_step",
                    "direct_use_enabled": "false",
                    "storage_enabled": "false",
                    "transfer_scope": "same_power_arm",
                },
            ],
        }
        for file_name, rows in fixture_rows.items():
            with (csv_dir / file_name).open("w", encoding="utf-8", newline="") as handle:
                fieldnames = list(dict.fromkeys(key for row in rows for key in row))
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        csv_timetable = load_canonical_timetable(csv_dir)
        assert [scenario.scenario_id for scenario in csv_timetable.scenarios] == ["valid"]
        invalid_scenario_fields = {
            issue.field
            for issue in csv_timetable.validation_report.errors
            if issue.sheet == "scenario"
        }
        assert {
            "direct_use_enabled",
            "storage_capacity_kwh",
            "settlement_time_step_s",
        } <= invalid_scenario_fields
        missing_step_issues = [
            issue
            for issue in csv_timetable.validation_report.errors
            if issue.sheet == "scenario"
            and issue.row == 4
            and issue.field == "settlement_time_step_s"
        ]
        assert missing_step_issues, "missing settlement step must invalidate a scenario row"

        # 缺少活动场景时，不能生成能量评分为零且未执行电气检查的表面有效优化结果。
        (csv_dir / "scenario.csv").unlink()
        missing_scenario_summary = optimize_timetable(
            csv_dir,
            Path(temp_name) / "missing_scenario_optimizer",
            max_candidates=1,
            mode="rule",
        )
        assert missing_scenario_summary["valid"] is False
        assert missing_scenario_summary["error_code"] == "missing_active_energy_scenario"

    valid_scenario = {
        "scenario_id": "contract_probe",
        "direct_use_enabled": False,
        "storage_enabled": True,
        "storage_capacity_kwh": 100.0,
        "storage_power_kw": 10.0,
        "initial_soc_kwh": 0.0,
        "settlement_time_step_s": 10,
        "transfer_scope": "same_power_arm",
    }
    invalid_scenarios = (
        ({"settlement_time_step_s": 1.5}, "settlement_time_step_s"),
        ({"storage_capacity_kwh": float("nan")}, "storage_capacity_kwh"),
        ({"storage_efficiency": 0.0}, "storage_efficiency"),
        ({"initial_soc_kwh": 101.0}, "initial_soc_kwh"),
        ({"storage_power_kw": 0.0}, "charge power"),
    )
    for overrides, expected_field in invalid_scenarios:
        try:
            TimetableScenario(**{**valid_scenario, **overrides})
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid timetable scenario was accepted: {overrides!r}")

    precision_scenario = TimetableScenario(
        **{
            **valid_scenario,
            "scenario_id": "precision_probe",
            "storage_enabled": False,
        }
    )
    precision_settlement_rows, precision_issue_rows, precision_summary = (
        optimizer_module.evaluate_scenario_time_slices(
            [
                {
                    "power_arm_id": "A",
                    "storage_section_id": "",
                    "time_window_start_s": 0,
                    "time_window_end_s": 10,
                    "traction_kwh": 1.0000004,
                    "regen_kwh": 0.0,
                }
            ],
            precision_scenario,
            {"A": PowerArmElectricalLimit(max_traction_supply_kw=360.0)},
        )
    )
    precision_violation = float(
        precision_summary["electrical_constraint_violation_kwh"]
    )
    if not 0.0 < precision_violation < 1e-6:
        raise AssertionError(
            "small electrical excess was rounded away before optimization: "
            f"{precision_violation}"
        )
    if precision_settlement_rows[0]["traction_supply_excess_kwh"] != precision_violation:
        raise AssertionError("small electrical excess was rounded away in settlement details")
    if not precision_issue_rows or precision_summary["assessment"] != "needs_optimization":
        raise AssertionError(
            "small optimizer-blocking electrical excess was omitted from audit issues"
        )
    if precision_issue_rows[0]["electrical_excess_kwh"] != precision_violation:
        raise AssertionError("small electrical excess was rounded to zero in audit issue details")

    for offsets, dwells, expected_text in (
        ((("H001", 1.5),), (), "integer minutes"),
        ((("H001", 0), ("H001", 1)), (), "unique"),
        ((), (("H001", 1, -1),), "non-negative"),
    ):
        try:
            TimetableGenome(offsets, dwells)
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError("invalid timetable genome was accepted")

    first_resource_model = object()
    second_resource_model = object()
    with patch.object(
        optimizer_module,
        "load_real_data_bundle",
        side_effect=(
            SimpleNamespace(resource_model=first_resource_model),
            SimpleNamespace(resource_model=second_resource_model),
        ),
    ) as bundle_loader:
        assert optimizer_module._timetable_resource_model("same_path") is first_resource_model
        assert optimizer_module._timetable_resource_model("same_path") is second_resource_model
    assert bundle_loader.call_count == 2

    invalid_settings = (
        ({"mode": "unknown"}, "mode"),
        ({"mode": "rule", "step_min": 0}, "step_min"),
        ({"mode": "rule", "max_candidates": 0}, "max_candidates"),
        ({"mode": "nsga2", "population_size": 0}, "population_size"),
        ({"mode": "nsga2", "generations": -1}, "generations"),
        ({"mode": "nsga2", "crossover_rate": float("nan")}, "crossover_rate"),
        ({"mode": "nsga2", "mutation_rate": 1.1}, "mutation_rate"),
    )
    for kwargs, expected_field in invalid_settings:
        try:
            optimize_timetable(TEMPLATE, OUTPUT_DIR / "invalid_settings", **kwargs)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid optimizer settings were accepted: {kwargs!r}")

    summary = optimize_timetable(
        TEMPLATE,
        OUTPUT_DIR,
        mode="nsga2",
        population_size=8,
        generations=3,
        seed=42,
    )

    assert summary["valid"]
    assert summary["optimizer_mode"] == "nsga2"
    assert summary["candidate_count"] > 0
    assert summary["scenario_score_count"] > 0
    assert summary["pareto_count"] > 0
    assert (OUTPUT_DIR / "candidate_summary.csv").exists()
    assert (OUTPUT_DIR / "candidate_scenario_scores.csv").exists()
    assert (OUTPUT_DIR / "candidate_energy_issues.csv").exists()
    assert (OUTPUT_DIR / "pareto_candidates.csv").exists()
    optimizer_report = (OUTPUT_DIR / "TIMETABLE_OPTIMIZATION_REPORT.md").read_text(encoding="utf-8")
    assert "# 运行图候选方案优化报告" in optimizer_report
    assert "## 帕累托候选方案" in optimizer_report
    assert "储能（无直接利用）" in optimizer_report
    assert "Timetable Candidate Optimization Report" not in optimizer_report
    assert (OUTPUT_DIR / "generation_log.csv").exists()
    assert (OUTPUT_DIR / "final_population.csv").exists()
    assert (OUTPUT_DIR / "figures" / "evolution_progress.png").exists()
    attribution_files = {
        "OPTIMIZATION_ATTRIBUTION_REPORT.md",
        "optimization_attribution_summary.json",
        "optimization_kpi_attribution.csv",
        "optimization_candidate_decisions.csv",
        "optimization_candidate_funnel.csv",
        "optimization_bottlenecks.csv",
        "optimization_dimension_attribution.csv",
    }
    assert all((OUTPUT_DIR / name).is_file() for name in attribution_files)
    assert summary["optimization_attribution"]["decision"]["action"] in {
        "optimize",
        "keep_baseline",
        "no_feasible_solution",
    }
    attribution_output_keys = {
        "optimization_attribution_report",
        "optimization_attribution_summary",
        "optimization_kpi_attribution",
        "optimization_candidate_decisions",
        "optimization_candidate_funnel",
        "optimization_bottlenecks",
        "optimization_dimension_attribution",
    }
    assert attribution_output_keys <= set(summary["outputs"])
    diagnostics = json.loads((OUTPUT_DIR / "visualization_diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["status"] == "complete"
    assert diagnostics["error_count"] == 0
    assert summary["visualization_status"] == "complete"
    assert summary["visualization_error_count"] == 0
    assert _dominates_objectives(
        {"constraint_violation": 0.2, "effective_regen_loss_kwh_est": 100.0, "grid_kwh_est": 100.0, "total_adjustment_min": 10.0},
        {"constraint_violation": 0.5, "effective_regen_loss_kwh_est": 1.0, "grid_kwh_est": 1.0, "total_adjustment_min": 1.0},
    )
    noise_left = {"constraint_violation": 0.0, "effective_regen_loss_kwh_est": 100.000001, "grid_kwh_est": 200.000001, "total_adjustment_min": 10.0}
    noise_right = {"constraint_violation": 0.0, "effective_regen_loss_kwh_est": 100.000002, "grid_kwh_est": 200.000002, "total_adjustment_min": 10.0}
    assert _effective_objective_tuple(noise_left) == _effective_objective_tuple(noise_right)
    assert not _dominates_objectives(noise_left, noise_right)
    assert not _dominates_objectives(noise_right, noise_left)
    for invalid_objectives in (
        {**noise_left, "grid_kwh_est": float("nan")},
        {key: value for key, value in noise_left.items() if key != "total_adjustment_min"},
        {**noise_left, "constraint_violation": float("inf")},
    ):
        try:
            _dominates_objectives(invalid_objectives, noise_right)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid Pareto vector was accepted: {invalid_objectives!r}")
    infeasible_front = [
        SimpleNamespace(
            objectives={
                "constraint_violation": 1.0,
                "effective_regen_loss_kwh_est": 100.0 + idx,
                "grid_kwh_est": 200.0 - idx,
                "total_adjustment_min": float(idx),
            },
            crowding_distance=0.0,
        )
        for idx in range(3)
    ]
    assign_crowding_distance(infeasible_front)
    assert all(item.crowding_distance >= 0.0 for item in infeasible_front)
    with (OUTPUT_DIR / "pareto_candidates.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        pareto_rows = list(csv.DictReader(handle))
    objective_keys = {
        (
            row["scenario_id"],
            round(float(row["effective_regen_loss_kwh_est"]), 6),
            round(float(row["grid_kwh_est"]), 6),
            round(float(row["total_adjustment_min"]), 6),
        )
        for row in pareto_rows
    }
    assert len(objective_keys) == len(pareto_rows)
    assert all(float(row["constraint_violation"]) <= 1e-9 for row in pareto_rows)
    with (OUTPUT_DIR / "candidate_summary.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        candidate_rows = list(csv.DictReader(handle))
    assert all("resource_conflict_count" in row for row in candidate_rows)
    assert all(row["candidate_id"] for row in candidate_rows)
    candidate_ids = {row["candidate_id"] for row in candidate_rows}
    with (OUTPUT_DIR / "candidate_scenario_scores.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        scenario_rows_for_ids = list(csv.DictReader(handle))
    assert {row["candidate_id"] for row in scenario_rows_for_ids} <= candidate_ids
    assert all((float(row["constraint_violation"]) <= 1e-9) == (row["feasible"] == "True") for row in candidate_rows)

    electrical_timetable = load_canonical_timetable(TEMPLATE)
    precision_running_arcs = optimizer_module.build_timetable_running_arcs(
        electrical_timetable,
        optimizer_module.load_infrastructure_profile(Path("data") / "real_shuohuang"),
    )
    zero_duration_arcs = [
        arc for arc in precision_running_arcs if arc.end_time_s <= arc.start_time_s
    ]
    if zero_duration_arcs:
        raise AssertionError(
            f"power-boundary splitting created {len(zero_duration_arcs)} zero-duration arcs"
        )
    expected_traction_kwh = sum(
        network_optimizer_module._running_arc_energy_components(arc)[0]
        for arc in precision_running_arcs
    )
    sliced_traction_kwh = sum(
        float(row["traction_kwh"])
        for row in optimizer_module.energy_time_slice_rows(
            optimizer_module._timetable_arc_candidate(precision_running_arcs),
            900,
        )
    )
    if abs(expected_traction_kwh - sliced_traction_kwh) > 1e-9:
        raise AssertionError(
            "power-boundary time slicing lost traction energy: "
            f"{expected_traction_kwh - sliced_traction_kwh}"
        )
    electrical_candidate = CandidatePlan(
        candidate_id="ELECTRICAL_LIMIT_PROBE",
        parent_id="",
        action_type="probe",
        description="1 kW power-arm capacity probe",
        timetable=electrical_timetable,
        max_shift_min=0.0,
        total_adjustment_min=0.0,
        delay_min=0.0,
        constraint_warnings=(),
        constraint_violation=0.0,
    )
    limited_sections = [
        replace(
            section,
            electrical_limit=replace(
                section.electrical_limit,
                max_traction_supply_kw=1.0,
                max_regen_absorption_kw=1.0,
            ),
        )
        for section in load_power_sections(Path("data") / "real_shuohuang" / "power_arm_intervals.csv")
    ]
    no_conflict_model = SimpleNamespace(config=SimpleNamespace(min_depart_headway_s=1))
    with patch.object(
        optimizer_module,
        "check_timetable_resources",
        return_value=SimpleNamespace(conflicts=[], conflict_count=0),
    ):
        electrical_candidate_rows, electrical_scenario_rows = evaluate_candidates(
            [electrical_candidate],
            limited_sections,
            resource_model=no_conflict_model,
            infrastructure=optimizer_module.load_infrastructure_profile(Path("data") / "real_shuohuang"),
        )
    assert electrical_candidate_rows[0]["electrical_constraint_violation_kwh"] > 0.0
    assert electrical_candidate_rows[0]["feasible"] is False
    assert all(row["electrical_constraint_violation_kwh"] > 0.0 for row in electrical_scenario_rows)
    assert all(row["feasible"] is False for row in electrical_scenario_rows)
    assert all("traction_supply_capacity_exceeded" in row["issue_types"] for row in electrical_scenario_rows)

    stale_dir = OUTPUT_DIR / "rule_cleanup" / "candidate_timetables"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "STALE.csv").write_text("stale", encoding="ascii")
    optimize_timetable(
        TEMPLATE,
        OUTPUT_DIR / "rule_cleanup",
        mode="rule",
        max_candidates=2,
        seed=11,
    )
    assert not (stale_dir / "STALE.csv").exists()

    with (OUTPUT_DIR / "candidate_scenario_scores.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        scenario_rows = list(csv.DictReader(handle))
    with (OUTPUT_DIR / "candidate_energy_issues.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        issue_rows = list(csv.DictReader(handle))
    assert all("issue_details_json" in row and "issue_types" in row for row in scenario_rows)
    assert len(issue_rows) == sum(int(row["issue_count"]) for row in scenario_rows)
    assert all(row["candidate_id"] and row["scenario_id"] and row["reason"] for row in issue_rows)

    custom_resource_dir = Path("tests") / "fixtures" / "custom_timetable_resources"
    custom_resource_model = SimpleNamespace(config=SimpleNamespace(min_depart_headway_s=1))
    custom_infrastructure = optimizer_module.load_infrastructure_profile()
    checked_resource_models = []

    def record_resource_model(_timetable, resource_model):
        """函数 record_resource_model：执行该模块中的相关处理逻辑。"""
        checked_resource_models.append(resource_model)
        return SimpleNamespace(conflicts=[], conflict_count=0)

    with patch.object(
        optimizer_module,
        "_timetable_resource_model",
        return_value=custom_resource_model,
    ) as resource_loader, patch.object(
        optimizer_module,
        "load_infrastructure_profile",
        return_value=custom_infrastructure,
    ) as infrastructure_loader, patch.object(
        optimizer_module,
        "check_timetable_resources",
        side_effect=record_resource_model,
    ):
        custom_summary = optimize_timetable(
            TEMPLATE,
            OUTPUT_DIR / "custom_resource_model",
            mode="nsga2",
            population_size=2,
            generations=0,
            seed=7,
            resource_data_dir=custom_resource_dir,
        )
    assert custom_summary["valid"]
    assert custom_summary["resource_data_dir"] == str(custom_resource_dir)
    resource_loader.assert_called_once_with(str(custom_resource_dir))
    infrastructure_loader.assert_called_once_with(custom_resource_dir)
    assert checked_resource_models
    assert all(model is custom_resource_model for model in checked_resource_models)

    timetable = load_canonical_timetable(TEMPLATE)
    assert _headway_from_constraints(timetable) == 15
    for invalid_headway in (-1, 1.5, float("nan"), float("inf")):
        bad_constraints = replace(
            timetable,
            constraints=(
                {
                    "constraint_type": "minimum_headway",
                    "value": invalid_headway,
                    "unit": "min",
                },
            ),
        )
        try:
            _headway_from_constraints(bad_constraints)
        except ValueError as exc:
            assert "Headway constraint value" in str(exc)
        else:
            raise AssertionError(f"invalid headway was accepted: {invalid_headway!r}")

    shifted = decode_genome_to_timetable(
        timetable,
        TimetableGenome(train_offsets_min=(("H001", -600),), dwell_extensions_min=()),
    )
    original_heavy = sorted(
        (stop for stop in timetable.stops if stop.train_id == "H001"),
        key=lambda stop: stop.seq,
    )
    shifted_heavy = sorted(
        (stop for stop in shifted.stops if stop.train_id == "H001"),
        key=lambda stop: stop.seq,
    )
    arrival_deltas = {
        candidate.arrival_time_s - original.arrival_time_s
        for original, candidate in zip(original_heavy, shifted_heavy)
    }
    departure_deltas = {
        candidate.departure_time_s - original.departure_time_s
        for original, candidate in zip(original_heavy, shifted_heavy)
    }
    assert arrival_deltas == departure_deltas
    assert len(arrival_deltas) == 1
    assert min(
        min(stop.arrival_time_s, stop.departure_time_s) for stop in shifted_heavy
    ) == 0

    dwell_gene_keys = {(train_id, seq) for train_id, seq, _value in baseline_genome(timetable).dwell_extensions_min}
    stops_by_train = {}
    for stop in timetable.stops:
        stops_by_train.setdefault(stop.train_id, []).append(stop)
    for train_id, stops in stops_by_train.items():
        terminal_seq = max(stop.seq for stop in stops)
        assert (train_id, terminal_seq) not in dwell_gene_keys
        assert all((train_id, stop.seq) in dwell_gene_keys for stop in stops if stop.seq != terminal_seq)

    print("timetable optimizer NSGA-II verification passed")
    print(
        {
            "candidate_count": summary["candidate_count"],
            "scenario_score_count": summary["scenario_score_count"],
            "pareto_count": summary["pareto_count"],
            "population_size": summary["population_size"],
            "generations": summary["generations"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
