# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resource_constraints import (
    ResourceConfig,
    ResourceCheckResult,
    ResourceInterval,
    ResourceModel,
    _resource_interval_validation,
    _train_runs,
    _normalize_resource_interval,
    detect_invalid_resource_intervals,
    detect_resource_conflicts,
    check_timetable_resources,
    normalized_resource_constraint_violation,
    resource_capacity_overlap_violation_s,
)


def test_inverted_interval_is_flagged() -> None:
    """函数 test_inverted_interval_is_flagged：执行该模块中的相关处理逻辑。"""
    intervals = [
        ResourceInterval("S", "S", "section", 1, "t1", "heavy", "up", 100.0, 50.0, 0.0, 10.0, "inverted"),
        ResourceInterval("S", "S", "section", 1, "t2", "heavy", "up", 40.0, 120.0, 0.0, 10.0, "ok"),
    ]
    invalid = detect_invalid_resource_intervals(intervals)
    if len(invalid) != 1:
        raise AssertionError(f"expected 1 invalid interval, got {len(invalid)}: {invalid}")
    if invalid[0].conflict_type != "invalid_resource_interval":
        raise AssertionError(invalid[0])
    conflicts = detect_resource_conflicts(intervals, ResourceConfig(min_overlap_s=1))
    if not any(c.conflict_type == "invalid_resource_interval" for c in conflicts):
        raise AssertionError(f"detect_resource_conflicts missed inverted interval: {conflicts}")


def test_valid_boundary_still_clean() -> None:
    """函数 test_valid_boundary_still_clean：执行该模块中的相关处理逻辑。"""
    intervals = [
        ResourceInterval("S", "S", "section", 1, "t1", "heavy", "up", 0.0, 100.0, 0.0, 10.0, "a"),
        ResourceInterval("S", "S", "section", 1, "t2", "heavy", "up", 100.0, 200.0, 0.0, 10.0, "b"),
    ]
    conflicts = detect_resource_conflicts(intervals, ResourceConfig(min_overlap_s=1))
    if conflicts:
        raise AssertionError(conflicts)


def test_normalize_swaps_inverted_window() -> None:
    """函数 test_normalize_swaps_inverted_window：执行该模块中的相关处理逻辑。"""
    inverted = ResourceInterval("S", "S", "section", 1, "t1", "heavy", "up", 100.0, 50.0, 0.0, 10.0, "inverted")
    fixed = _normalize_resource_interval(inverted)
    if not (fixed.start_time_s == 50.0 and fixed.end_time_s == 100.0):
        raise AssertionError(fixed)
    if "normalized inverted time window" not in fixed.detail:
        raise AssertionError(fixed.detail)


def test_invalid_config_and_zero_interval_are_rejected() -> None:
    """函数 test_invalid_config_and_zero_interval_are_rejected：执行该模块中的相关处理逻辑。"""
    for kwargs in (
        {"station_track_capacity": 0},
        {"section_capacity_spacing_km": float("nan")},
        {"min_overlap_s": -1},
        {"conflict_limit": 1.5},
        {"single_line_ranges_km": ((1.0, 1.0),)},
        {"station_track_capacity": True},
        {"section_capacity_spacing_km": True},
        {"single_line_ranges_km": ((True, 2.0),)},
        {"single_line_ranges_km": ((-1.0, 2.0),)},
        {"enforce_flow_continuity": "false"},
    ):
        try:
            ResourceConfig(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid resource config was accepted: {kwargs!r}")

    zero = ResourceInterval(
        "S", "S", "section", 1, "t1", "heavy", "up", 10.0, 10.0, 0.0, 10.0, "zero"
    )
    invalid = detect_invalid_resource_intervals([zero])
    if len(invalid) != 1 or "zero-duration" not in invalid[0].message:
        raise AssertionError(f"zero-duration resource interval was not rejected: {invalid}")

    invalid_intervals = [
        ResourceInterval(
            "S", "S", "section", True, "bool-cap", "heavy", "up", 0.0, 10.0, 0.0, 1.0, ""
        ),
        ResourceInterval(
            "S", "S", "section", 1, "bool-time", "heavy", "up", True, 10.0, 0.0, 1.0, ""
        ),
        ResourceInterval(
            "S", "S", "section", "invalid", "bad-a", "heavy", "up", 0.0, 10.0, 0.0, 1.0, ""
        ),
        ResourceInterval(
            "S", "S", "section", "invalid", "bad-b", "heavy", "up", 1.0, 9.0, 0.0, 1.0, ""
        ),
    ]
    invalid = detect_invalid_resource_intervals(invalid_intervals)
    if len(invalid) != len(invalid_intervals):
        raise AssertionError(f"invalid boolean/string resource values were accepted: {invalid}")
    conflicts = detect_resource_conflicts(invalid_intervals, ResourceConfig())
    if len(conflicts) != len(invalid_intervals):
        raise AssertionError(f"invalid resource intervals were not reported exactly once: {conflicts}")


def test_invalid_resource_model_overrides_are_rejected() -> None:
    """函数 test_invalid_resource_model_overrides_are_rejected：执行该模块中的相关处理逻辑。"""
    station = SimpleNamespace(name="S", position_km=0.0)
    invalid_cases = (
        ({"station_track_capacities": {"S": 1.5}}, "station_track_capacities"),
        ({"station_throat_capacities": {"S": 0}}, "station_throat_capacities"),
        ({"station_occupancy_s": {"S": float("nan")}}, "station_occupancy_s"),
        ({"station_operation_min_times_s": {"S": -1}}, "station_operation_min_times_s"),
        (
            {"station_operation_assignments": ({"station_name": "S", "applies_to": "nowhere"},)},
            "applies_to",
        ),
        (
            {"station_operation_assignments": ({"station_name": "missing"},)},
            "station_name",
        ),
        (
            {"station_operation_assignments": ({"station_name": "S", "min_occupancy_s": 0.5},)},
            "min_occupancy_s",
        ),
    )
    for kwargs, expected_field in invalid_cases:
        try:
            ResourceModel(stations=(station,), config=ResourceConfig(), **kwargs)
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid resource model was accepted: {kwargs!r}")

    cache = SimpleNamespace(direction="forward")
    for invalid_departure in (0.5, True):
        schedule = SimpleNamespace(heavy_departures_s=[invalid_departure], empty_departures_s=[])
        try:
            _train_runs(schedule, cache, cache)
        except ValueError as exc:
            if "departure time" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid resource departure time was accepted: {invalid_departure!r}")


def test_capacity_overlap_is_not_pairwise_double_counted() -> None:
    """函数 test_capacity_overlap_is_not_pairwise_double_counted：执行该模块中的相关处理逻辑。"""
    intervals = [
        ResourceInterval("R", "R", "section", 2, "A", "heavy", "up", 0.0, 100.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 2, "B", "heavy", "up", 0.0, 60.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 2, "C", "heavy", "up", 50.0, 200.0, 0.0, 1.0, ""),
    ]
    config = ResourceConfig(min_overlap_s=1)
    pairwise_total = sum(
        conflict.overlap_duration_s
        for conflict in detect_resource_conflicts(intervals, config)
    )
    exact_total = resource_capacity_overlap_violation_s(intervals, config)
    if pairwise_total != 60.0 or exact_total != 10.0:
        raise AssertionError((pairwise_total, exact_total))


def test_continuous_over_capacity_is_infeasible_when_pairs_are_short() -> None:
    """函数 test_continuous_over_capacity_is_infeasible_when_pairs_are_short：执行该模块中的相关处理逻辑。"""
    intervals = [
        ResourceInterval("R", "R", "section", 1, "A", "heavy", "up", 0.0, 20.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 1, "B", "heavy", "up", 0.0, 6.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 1, "C", "heavy", "up", 6.0, 12.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 1, "D", "heavy", "up", 12.0, 18.0, 0.0, 1.0, ""),
    ]
    model = SimpleNamespace(config=ResourceConfig(min_overlap_s=10))
    with patch("resource_constraints.build_timetable_resource_intervals", return_value=intervals), patch(
        "resource_constraints.detect_timetable_overtaking_conflicts", return_value=[]
    ):
        result = check_timetable_resources(SimpleNamespace(), model)
    if result.conflicts:
        raise AssertionError(f"unexpected pairwise conflicts: {result.conflicts}")
    if result.overlap_violation_s != 18.0 or result.feasible:
        raise AssertionError(result)


def test_zero_duration_conflict_has_positive_constraint_violation() -> None:
    """函数 test_zero_duration_conflict_has_positive_constraint_violation：执行该模块中的相关处理逻辑。"""
    interval = ResourceInterval(
        "R", "R", "section", 1, "A", "heavy", "up", 10.0, 10.0, 0.0, 1.0, ""
    )
    conflicts = detect_resource_conflicts([interval], ResourceConfig())
    result = ResourceCheckResult(
        feasible=False,
        conflicts=conflicts,
        intervals=[interval],
        overlap_violation_s=0.0,
    )
    if normalized_resource_constraint_violation(result, 300.0) <= 0.0:
        raise AssertionError("blocking zero-duration interval received zero constraint violation")


def test_schedule_check_validates_each_interval_once() -> None:
    """完整资源检查应复用区间校验结果，避免对同一批数据重复扫描。"""
    intervals = [
        ResourceInterval("R", "R", "section", 1, "A", "heavy", "up", 0.0, 20.0, 0.0, 1.0, ""),
        ResourceInterval("R", "R", "section", 1, "B", "heavy", "up", 10.0, 30.0, 0.0, 1.0, ""),
        ResourceInterval("S", "S", "section", 1, "C", "heavy", "up", 40.0, 60.0, 1.0, 2.0, ""),
    ]
    model = SimpleNamespace(config=ResourceConfig(), unavailabilities=())
    with patch("resource_constraints.build_resource_intervals", return_value=intervals), patch(
        "resource_constraints.detect_overtaking_conflicts", return_value=[]
    ), patch(
        "resource_constraints.check_flow_continuity", return_value=(True, [], [])
    ), patch(
        "resource_constraints._resource_interval_validation",
        wraps=_resource_interval_validation,
    ) as validation:
        from resource_constraints import check_schedule_resources

        check_schedule_resources(SimpleNamespace(), model, SimpleNamespace(), SimpleNamespace())
    if validation.call_count != len(intervals):
        raise AssertionError(
            f"expected one validation per interval, got {validation.call_count} for {len(intervals)} intervals"
        )


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_inverted_interval_is_flagged()
    test_valid_boundary_still_clean()
    test_normalize_swaps_inverted_window()
    test_invalid_config_and_zero_interval_are_rejected()
    test_invalid_resource_model_overrides_are_rejected()
    test_capacity_overlap_is_not_pairwise_double_counted()
    test_continuous_over_capacity_is_infeasible_when_pairs_are_short()
    test_zero_duration_conflict_has_positive_constraint_violation()
    test_schedule_check_validates_each_interval_once()
    print("resource interval contract verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
