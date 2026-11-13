# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resource_constraints import ResourceConfig, ResourceModel, check_timetable_resources
from resource_constraints import detect_timetable_overtaking_conflicts
from timetable_optimizer import _candidate_objectives


def _train(train_id: str, direction: str):
    """函数 _train：执行该模块中的相关处理逻辑。"""
    return SimpleNamespace(
        train_id=train_id,
        train_type="Heavy" if direction == "forward" else "Empty",
        direction=direction,
        wagon_count=100,
    )


def _stop(train_id: str, seq: int, name: str, km: float, arrival: int, departure: int):
    """函数 _stop：执行该模块中的相关处理逻辑。"""
    return SimpleNamespace(
        train_id=train_id,
        seq=seq,
        station_name=name,
        station_km=km,
        arrival_time_s=arrival,
        departure_time_s=departure,
    )


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    model = ResourceModel(
        stations=(
            SimpleNamespace(name="S0", position_km=0.0),
            SimpleNamespace(name="S1", position_km=10.0),
        ),
        config=ResourceConfig(
            station_track_capacity=1,
            terminal_track_capacity=1,
            throat_capacity=1,
            station_occupancy_s=120,
            throat_occupancy_s=90,
            section_release_margin_s=30,
            single_line_ranges_km=((0.0, 10.0),),
        ),
    )
    timetable = SimpleNamespace(
        trains=(
            _train("A", "forward"),
            _train("B", "reverse"),
            _train("C", "forward"),
        ),
        stops=(
            _stop("A", 1, "S0", 0.0, 0, 100),
            _stop("A", 2, "S1", 10.0, 1000, 1000),
            _stop("B", 1, "S1", 10.0, 0, 100),
            _stop("B", 2, "S0", 0.0, 1000, 1100),
            _stop("C", 1, "S0", 0.0, 50, 150),
            _stop("C", 2, "S1", 10.0, 1050, 1050),
        ),
    )
    result = check_timetable_resources(timetable, model)
    conflict_types = {conflict.conflict_type for conflict in result.conflicts}
    expected = {
        "station_track_capacity_conflict",
        "throat_route_conflict",
        "section_capacity_conflict",
        "opposing_section_conflict",
    }
    missing = expected - conflict_types
    if missing:
        raise AssertionError(f"Timetable resource conflicts were not detected: {missing}")
    if result.feasible:
        raise AssertionError("Conflicting timetable was incorrectly marked feasible")
    if sum(conflict.overlap_duration_s for conflict in result.conflicts) <= 0.0:
        raise AssertionError("Resource conflict violation has no continuous overlap magnitude")

    # 单线范围可能只覆盖站间区段的一部分；仅按中点分类会错误地给该区段分配独立方向资源，
    # 从而漏掉对向运行冲突。
    partial_single_line_model = ResourceModel(
        stations=(
            SimpleNamespace(name="P0", position_km=0.0),
            SimpleNamespace(name="P1", position_km=10.0),
        ),
        config=ResourceConfig(
            station_track_capacity=10,
            terminal_track_capacity=10,
            throat_capacity=10,
            station_occupancy_s=1,
            throat_occupancy_s=1,
            section_release_margin_s=0,
            section_capacity_spacing_km=8.0,
            single_line_ranges_km=((0.0, 2.0),),
        ),
    )
    partial_single_line_timetable = SimpleNamespace(
        trains=(_train("PF", "forward"), _train("PR", "reverse")),
        stops=(
            _stop("PF", 1, "P0", 0.0, 0, 0),
            _stop("PF", 2, "P1", 10.0, 1000, 1000),
            _stop("PR", 1, "P1", 10.0, 0, 0),
            _stop("PR", 2, "P0", 0.0, 1000, 1000),
        ),
    )
    partial_result = check_timetable_resources(
        partial_single_line_timetable, partial_single_line_model
    )
    if "opposing_section_conflict" not in {
        conflict.conflict_type for conflict in partial_result.conflicts
    }:
        raise AssertionError(
            "Partial single-line coverage was not treated as a shared section"
        )

    # 仅有区段容量不能使同方向列车顺序反转变为可行。
    wide_model = ResourceModel(
        stations=(
            SimpleNamespace(name="A", position_km=0.0),
            SimpleNamespace(name="B", position_km=100.0),
        ),
        config=ResourceConfig(
            station_track_capacity=2,
            terminal_track_capacity=4,
            throat_capacity=2,
            section_capacity_spacing_km=8.0,
        ),
    )
    reversal_timetable = SimpleNamespace(
        trains=(_train("H1", "forward"), _train("H2", "forward")),
        stops=(
            _stop("H1", 1, "A", 0.0, 0, 0),
            _stop("H1", 2, "B", 100.0, 1000, 1000),
            _stop("H2", 1, "A", 0.0, 200, 200),
            _stop("H2", 2, "B", 100.0, 900, 900),
        ),
    )
    reversal_result = check_timetable_resources(reversal_timetable, wide_model)
    reversal_types = {conflict.conflict_type for conflict in reversal_result.conflicts}
    if "overtaking_without_passing_track" not in reversal_types:
        raise AssertionError("Same-direction running-order reversal was not detected")
    if reversal_result.feasible:
        raise AssertionError("Running-order reversal was incorrectly marked feasible")
    restored_arrival_order_timetable = SimpleNamespace(
        trains=(_train("H1", "forward"), _train("H2", "forward")),
        stops=(
            _stop("H1", 1, "S0", 0.0, 0, 0),
            _stop("H1", 2, "S1", 50.0, 100, 200),
            _stop("H1", 3, "S2", 100.0, 300, 300),
            _stop("H2", 1, "S0", 0.0, 10, 10),
            _stop("H2", 2, "S1", 50.0, 110, 111),
            _stop("H2", 3, "S2", 100.0, 310, 310),
        ),
    )
    restored_order_conflicts = detect_timetable_overtaking_conflicts(
        restored_arrival_order_timetable,
        wide_model,
    )
    if not restored_order_conflicts:
        raise AssertionError(
            "Station departure-order reversal was missed when arrival order was later restored"
        )
    clean_timetable = SimpleNamespace(
        trains=(_train("H1", "forward"), _train("H2", "forward")),
        stops=(
            _stop("H1", 1, "A", 0.0, 0, 0),
            _stop("H1", 2, "B", 100.0, 1000, 1000),
            _stop("H2", 1, "A", 0.0, 200, 200),
            _stop("H2", 2, "B", 100.0, 1200, 1200),
        ),
    )
    if detect_timetable_overtaking_conflicts(clean_timetable, wide_model):
        raise AssertionError("Normal same-direction order was incorrectly flagged as overtaking")
    candidate = SimpleNamespace(candidate_id="X", total_adjustment_min=0.0, constraint_violation=0.0)
    objectives = _candidate_objectives(
        candidate,
        [{
            "candidate_id": "X",
            "effective_regen_loss_kwh_est": 1.0,
            "grid_kwh_est": 2.0,
            "constraint_violation": 3.5,
        }],
    )
    if objectives["constraint_violation"] != 3.5:
        raise AssertionError("NSGA-II objectives did not receive the resource constraint violation")
    for invalid_value in ("not-a-number", float("nan"), float("inf"), True, None):
        invalid_row = {
            "candidate_id": "X",
            "effective_regen_loss_kwh_est": invalid_value,
            "grid_kwh_est": 2.0,
            "constraint_violation": 0.0,
        }
        try:
            _candidate_objectives(candidate, [invalid_row])
        except ValueError as exc:
            if "effective_regen_loss_kwh_est" not in str(exc):
                raise AssertionError("Invalid objective error omitted its field name") from exc
        else:
            raise AssertionError(f"Invalid Pareto objective was accepted: {invalid_value!r}")
    print("timetable station, throat and section resource constraints passed")
    print({"conflict_count": result.conflict_count, "conflict_types": sorted(conflict_types)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
