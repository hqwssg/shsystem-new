"""验证到到间隔约束（技术方案 4.2.1.2(2) 第四类约束之"到到间隔 g"）。

本用例覆盖：
1. 到到间隔 g 与发发间隔 h 相互独立，按车站—运行方向—列型分类分组；
2. 不满足间隔时通过推迟空列发车时刻做可行性修复，并落成显式 ``waiting`` 弧；
3. 修复量超过 ``max_departure_shift_s`` 时记为违反，并使候选不可行；
4. ``arrival_headway_recommendations.csv`` 产物与候选字段一致；
5. 间隔参数可从模板装载，留空时回落到发发间隔。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import csv
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import (
    _build_candidate,
    _headway_group_key,
    arrival_headway_rows,
    load_he_input_template,
    optimize_heavy_empty_network,
    write_optimization_outputs,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("arrival_headway")


def _empty_arrivals(candidate, bundle) -> dict[tuple[str, str, str], list[int]]:
    """按分组键汇总候选网络中每条空列到达其终到站的时刻。"""

    arrivals: dict[str, int] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    for arc in candidate.arcs:
        if arc.arc_type != "empty_running":
            continue
        if arc.train_id not in arrivals or arc.end_time_s > arrivals[arc.train_id]:
            service = bundle.service_types[arc.train_type]
            arrivals[arc.train_id] = arc.end_time_s
            meta[arc.train_id] = _headway_group_key(
                arc.end_station, service, arc.start_km, arc.end_km
            )
    grouped: dict[tuple[str, str, str], list[int]] = {}
    for train_id, arrival_s in arrivals.items():
        grouped.setdefault(meta[train_id], []).append(arrival_s)
    return {key: sorted(values) for key, values in grouped.items()}


def test_headway_parameters_are_loaded(bundle) -> None:
    """到到间隔 g 必须能从模板装载，且与发发间隔 h 分开保存。"""

    for scenario in bundle.scenarios.values():
        if scenario.min_arrival_headway_s <= 0:
            raise AssertionError(f"{scenario.scenario_id} 的到到间隔未装载")
        if scenario.min_headway_s <= 0:
            raise AssertionError(f"{scenario.scenario_id} 的发发间隔未装载")
    surplus = bundle.scenarios["capacity_surplus_demo"]
    if surplus.min_arrival_headway_s != surplus.min_headway_s:
        raise AssertionError("模板留空时到到间隔应回落到发发间隔")


def test_arrival_headway_is_enforced_per_group(bundle) -> None:
    """默认场景必须无到到间隔违反，且同组空列到达间隔不小于 g。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(bundle, scenario, "HEADWAY", departure_shift_s=0, headway_s=scenario.min_headway_s)
    if candidate.arrival_headway_violation_count != 0:
        raise AssertionError(f"默认场景不应产生到到间隔违反：{candidate.diagnostics}")
    if candidate.conflict_count != 0:
        raise AssertionError(f"默认场景不应产生冲突：{candidate.diagnostics}")
    grouped = _empty_arrivals(candidate, bundle)
    if not grouped:
        raise AssertionError("候选网络没有空列到达事件")
    checked = 0
    for (station, direction, size_class), times in grouped.items():
        if len(times) < 2:
            continue
        checked += 1
        for left, right in zip(times, times[1:]):
            if right - left < scenario.min_arrival_headway_s:
                raise AssertionError(
                    f"{station}/{direction}/{size_class} 到达间隔 {right - left}s "
                    f"小于到到间隔 {scenario.min_arrival_headway_s}s"
                )
    if checked == 0:
        raise AssertionError("没有出现需要校验到到间隔的同组空列到达事件")


def test_repair_emits_explicit_waiting_arc(bundle) -> None:
    """修复必须落成显式 waiting 弧，而不是只改内部时刻。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(bundle, scenario, "HEADWAY_WAIT", departure_shift_s=0, headway_s=scenario.min_headway_s)
    repair_waits = [
        arc for arc in candidate.arcs
        if arc.arc_type == "waiting" and arc.source == "arrival_departure_headway_repair"
    ]
    if not repair_waits:
        raise AssertionError("应至少有一次空列在卸车站等待以满足发发/到到间隔")
    node_time = {node.node_id: node.time_s for node in candidate.nodes}
    for arc in repair_waits:
        if arc.end_time_s - arc.start_time_s <= 0:
            raise AssertionError(f"{arc.arc_id} 的等待弧时长为非正")
        if node_time[arc.from_node_id] != arc.start_time_s or node_time[arc.to_node_id] != arc.end_time_s:
            raise AssertionError(f"{arc.arc_id} 的等待弧与节点时刻不一致")


def test_violation_when_shift_limit_is_exceeded(bundle) -> None:
    """推迟量超过最大时移上限时必须记为违反，并使候选不可行。"""

    scenario = replace(
        bundle.scenarios["capacity_surplus_demo"],
        max_departure_shift_s=0,
        min_arrival_headway_s=6 * 3600,
        min_headway_s=6 * 3600,
    )
    candidate = _build_candidate(bundle, scenario, "HEADWAY_VIOLATION", departure_shift_s=0, headway_s=scenario.min_headway_s)
    if candidate.arrival_headway_violation_count <= 0:
        raise AssertionError("间隔要求超过时移上限时应记为违反")
    if candidate.feasible:
        raise AssertionError("存在到到间隔违反的候选必须不可行")
    if candidate.constraint_violation < candidate.arrival_headway_violation_count:
        raise AssertionError("到到间隔违反必须计入约束违反量")
    if not any("headway" in message for message in candidate.diagnostics):
        raise AssertionError(f"应输出到到间隔违反诊断，实际 {candidate.diagnostics[:3]}")


def test_output_artifact_matches_candidate(bundle) -> None:
    """到达间隔产物必须写出，并与候选字段/建议值一致。"""

    result = optimize_heavy_empty_network(bundle, "capacity_surplus_demo")
    rows = arrival_headway_rows(result, bundle)
    if not rows:
        raise AssertionError("到达间隔统计为空")
    expected_fields = {
        "candidate_id", "period_start_s", "period_end_s", "station_name", "direction",
        "train_size_class", "arrival_count", "recommended_arrival_headway_s",
        "observed_min_arrival_headway_s", "observed_avg_arrival_headway_s",
        "observed_max_arrival_headway_s", "violation_count", "basis",
    }
    for row in rows:
        if set(row) != expected_fields:
            raise AssertionError(f"到达间隔产物字段不一致：{sorted(set(row) ^ expected_fields)}")
        if row["recommended_arrival_headway_s"] != result.scenario.min_arrival_headway_s:
            raise AssertionError("建议到到间隔与场景参数不一致")
        if row["violation_count"] != result.best_candidate.arrival_headway_violation_count:
            raise AssertionError("产物中的违反数与候选字段不一致")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_optimization_outputs(result, OUTPUT_ROOT, bundle=bundle)
    path = OUTPUT_ROOT / "arrival_headway_recommendations.csv"
    if not path.exists():
        raise AssertionError("缺少 arrival_headway_recommendations.csv 产物")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        written = list(csv.DictReader(handle))
    if len(written) != len(rows):
        raise AssertionError("写出的到达间隔行数与统计结果不一致")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""

    bundle = load_he_input_template(TEMPLATE)
    test_headway_parameters_are_loaded(bundle)
    test_arrival_headway_is_enforced_per_group(bundle)
    test_repair_emits_explicit_waiting_arc(bundle)
    test_violation_when_shift_limit_is_exceeded(bundle)
    test_output_artifact_matches_candidate(bundle)
    print("arrival headway verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
