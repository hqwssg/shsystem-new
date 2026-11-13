"""验证组合站/分解站显式作业弧（技术方案 4.2.1.2(2) 第三类约束：分解站流平衡）。

本用例覆盖：
1. 组合/分解关系被装载与校验（数量守恒、列型守恒、站点/车底引用、接续性）；
2. ``combining`` / ``dismantling`` 弧是**真实网络弧**：有真实起讫节点、时刻与站场占用；
3. 到发时间一致：输入车底到站时刻 = 作业开始，作业结束 = 输出车底发车时刻；
4. 作业时间约束：站内作业时长不小于站点最小作业时间；
5. 站场能力约束：默认场景不产生冲突，时隙压缩后必须报冲突；
6. 输出投影：``combination_station_connection_rhythm.csv`` 报告
   ``explicit_combination_arcs``，``station_wait_bounds.csv`` 报告真实在站等待；
7. 非法声明必须被拒绝（数量不守恒、角色错误、站点不在区间内、输出车底凭空出现、
   同站重复作业）。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import heavy_empty_network_optimizer as optimizer_module
from heavy_empty_network_optimizer import (
    FORMATION_ARC_TYPES,
    FormationOperation,
    OperationNode,
    _build_candidate,
    _formation_operations_by_demand_leg,
    _validate_he_input_bundle,
    dispatch_plan_output_rows,
    load_he_input_template,
    optimize_heavy_empty_network,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("formation_operations")


def _load_bundle():
    return load_he_input_template(TEMPLATE)


def test_formation_operations_are_loaded(bundle) -> None:
    """组合/分解关系必须从模板装载，并带上守恒所需的服务类型与站点。"""

    operations = {operation.operation_id: operation for operation in bundle.formation_operations}
    if set(operations) != {"FO001", "FO002"}:
        raise AssertionError(f"unexpected formation operations: {sorted(operations)}")
    combine = operations["FO001"]
    dismantle = operations["FO002"]
    if combine.operation_type != "combine" or dismantle.operation_type != "dismantle":
        raise AssertionError("combine/dismantle kinds were not parsed")
    for operation in (combine, dismantle):
        if operation.leg != "heavy":
            raise AssertionError(f"{operation.operation_id} leg must be heavy")
        node = bundle.operation_nodes[operation.station_name]
        if node.role != "combine_split":
            raise AssertionError(f"{operation.station_name} must be a combine_split node")
        for service_name in (operation.upstream_service, operation.downstream_service):
            if service_name not in bundle.service_types:
                raise AssertionError(f"missing service type {service_name}")
    if not bundle.service_types["HeavySmall"].consist_unit < bundle.service_types["Heavy"].consist_unit:
        raise AssertionError("small train must carry fewer standard units than the large train")
    grouped = _formation_operations_by_demand_leg(bundle)
    if [operation.operation_id for operation in grouped[("OD001", "heavy")]] != ["FO001", "FO002"]:
        raise AssertionError("formation operations must be ordered along the running direction")


def test_quantity_and_train_type_conservation(bundle) -> None:
    """数量守恒：两侧标准列数必须相等；列型守恒：合并方向与拆解方向必须与声明一致。"""

    for operation in bundle.formation_operations:
        upstream = bundle.service_types[operation.upstream_service]
        downstream = bundle.service_types[operation.downstream_service]
        input_units = len(operation.input_copies) * upstream.consist_unit
        output_units = len(operation.output_copies) * downstream.consist_unit
        if input_units != output_units:
            raise AssertionError(
                f"{operation.operation_id} violates quantity conservation: "
                f"{input_units} != {output_units}"
            )
        if operation.operation_type == "combine":
            if not (len(operation.input_copies) > len(operation.output_copies)
                    and upstream.consist_unit < downstream.consist_unit):
                raise AssertionError(f"{operation.operation_id} is not a small->large merge")
        else:
            if not (len(operation.input_copies) < len(operation.output_copies)
                    and upstream.consist_unit > downstream.consist_unit):
                raise AssertionError(f"{operation.operation_id} is not a large->small split")


def test_invalid_declarations_are_rejected(bundle) -> None:
    """数量不守恒、角色错误、站点越界、车底凭空出现、同站重复作业都必须被拒绝。"""

    base = bundle.formation_operations[0]
    cases = [
        (
            replace(base, output_copies=(1, 2)),
            "quantity conservation",
            "数量不守恒（2×1 != 2×2）必须被拒绝",
        ),
        (
            replace(base, station_name="黄骅港"),
            "combine_split",
            "非组合/分解角色站点必须被拒绝",
        ),
        (
            replace(base, station_name="黄骅港", operation_type="combine"),
            "combine_split",
            "角色不符必须被拒绝",
        ),
        (
            replace(base, input_copies=(1, 2), output_copies=(3,)),
            "exceed",
            "超出 train_count 的车底序号必须被拒绝",
        ),
    ]
    for operation, expected_text, message in cases:
        try:
            _validate_he_input_bundle(replace(bundle, formation_operations=(operation,)))
        except ValueError as exc:
            if expected_text not in str(exc):
                raise AssertionError(f"{message}：错误信息不含 {expected_text!r}，实际 {exc}") from exc
        else:
            raise AssertionError(message)

    out_of_range_station = "越界测试站"
    out_of_range_bundle = replace(
        bundle,
        station_positions_km={**bundle.station_positions_km, out_of_range_station: 900.0},
        operation_nodes={
            **bundle.operation_nodes,
            out_of_range_station: OperationNode(out_of_range_station, "combine_split", 1800, 2),
        },
        formation_operations=(replace(base, station_name=out_of_range_station),),
    )
    try:
        _validate_he_input_bundle(out_of_range_bundle)
    except ValueError as exc:
        if "strictly between" not in str(exc):
            raise AssertionError(f"站点不在 OD 区间内必须被拒绝，实际错误 {exc}") from exc
    else:
        raise AssertionError("站点不在 OD 区间内必须被拒绝")

    # 只有分解作业、缺少前置组合作业时，输出车底 2 在分解站"凭空出现"，必须被拒绝。
    phantom = bundle.formation_operations[1]
    try:
        _validate_he_input_bundle(replace(bundle, formation_operations=(phantom,)))
    except ValueError as exc:
        if "never arrive" not in str(exc):
            raise AssertionError(f"凭空出现的输出车底必须被拒绝，实际错误 {exc}") from exc
    else:
        raise AssertionError("凭空出现的输出车底必须被拒绝")

    duplicate_station = (
        bundle.formation_operations[0],
        replace(bundle.formation_operations[1], station_name=bundle.formation_operations[0].station_name),
    )
    try:
        _validate_he_input_bundle(replace(bundle, formation_operations=duplicate_station))
    except ValueError as exc:
        if "same station" not in str(exc):
            raise AssertionError(f"同站重复作业必须被拒绝，实际错误 {exc}") from exc
    else:
        raise AssertionError("同站重复作业必须被拒绝")


def test_combining_and_dismantling_arcs_are_real(bundle) -> None:
    """组合/分解弧必须是真实网络弧，并满足到发时间一致与作业时间约束。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(bundle, scenario, "FORMATION", departure_shift_s=0, headway_s=scenario.min_headway_s)
    arc_types = {arc.arc_type for arc in candidate.arcs}
    for expected in ("combining", "dismantling"):
        if expected not in arc_types:
            raise AssertionError(f"候选网络缺少 {expected} 弧，实际类型 {sorted(arc_types)}")
    if candidate.conflict_count != 0:
        raise AssertionError(f"默认场景不应产生冲突：{candidate.diagnostics}")

    node_time = {node.node_id: node.time_s for node in candidate.nodes}
    node_state = {node.node_id: node.state for node in candidate.nodes}
    operation_arcs = {
        arc.arc_id: arc for arc in candidate.arcs
        if arc.arc_type in {"combining", "dismantling"}
    }
    if len(operation_arcs) != len(bundle.formation_operations):
        raise AssertionError(
            f"组合/分解弧数量 {len(operation_arcs)} 与声明数量 {len(bundle.formation_operations)} 不一致"
        )

    for operation in bundle.formation_operations:
        arc_id = f"{operation.operation_id}:{FORMATION_ARC_TYPES[operation.operation_type]}"
        arc = operation_arcs.get(arc_id)
        if arc is None:
            raise AssertionError(f"缺少作业弧 {arc_id}")
        if arc.start_station != operation.station_name or arc.end_station != operation.station_name:
            raise AssertionError(f"{arc_id} 必须发生在声明站点 {operation.station_name}")
        if arc.start_km != arc.end_km:
            raise AssertionError(f"{arc_id} 是站内作业，起讫公里标必须相同")
        if node_state.get(arc.from_node_id) != "formation_merge":
            raise AssertionError(f"{arc_id} 的起点必须是合并节点")
        if node_state.get(arc.to_node_id) != "formation_output":
            raise AssertionError(f"{arc_id} 的终点必须是输出节点")
        if node_time[arc.from_node_id] != arc.start_time_s or node_time[arc.to_node_id] != arc.end_time_s:
            raise AssertionError(f"{arc_id} 的节点时刻与弧时刻不一致")
        minimum = bundle.operation_nodes[operation.station_name].operation_min_s
        if arc.end_time_s - arc.start_time_s != minimum:
            raise AssertionError(
                f"{arc_id} 作业时长 {arc.end_time_s - arc.start_time_s} 不等于站点最小作业时间 {minimum}"
            )
        # 到发时间一致：每个输入车底都必须恰好在作业开始时刻到达合并节点。
        merge_incoming = [
            item for item in candidate.arcs
            if item.to_node_id == arc.from_node_id and item.arc_type in {"heavy_running", "empty_running", "waiting"}
        ]
        if not merge_incoming:
            raise AssertionError(f"{arc_id} 的合并节点没有任何输入车底到站")
        for item in merge_incoming:
            if item.end_time_s != arc.start_time_s:
                raise AssertionError(
                    f"{arc_id} 输入车底到站时刻 {item.end_time_s} 与作业开始 {arc.start_time_s} 不一致"
                )
        # 输出车底必须恰好在作业结束时刻发车。
        out_going = [
            item for item in candidate.arcs
            if item.from_node_id == arc.to_node_id and item.arc_type in {"heavy_running", "empty_running"}
        ]
        if not out_going:
            raise AssertionError(f"{arc_id} 的输出节点没有任何车底发车")
        for item in out_going:
            if item.start_time_s != arc.end_time_s:
                raise AssertionError(
                    f"{arc_id} 输出车底发车时刻 {item.start_time_s} 与作业结束 {arc.end_time_s} 不一致"
                )


def test_corridor_unit_conservation(bundle) -> None:
    """沿走廊的编组单元守恒：任一公里区段上运行的车底标准列数必须处处相等。

    组合站之前是两列小列（各 1 个标准列），组合站之后是一列大列（2 个标准列），
    分解站之后又是两列小列——同一区段上的标准列数不得发生变化，这才说明"并入大列"的
    车底没有凭空消失或凭空产生。
    """

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(bundle, scenario, "FORMATION_UNITS", departure_shift_s=0, headway_s=scenario.min_headway_s)
    demand_by_id = {item.demand_id: item for item in bundle.demands}
    intervals_by_demand: dict[str, list[tuple[float, float, int]]] = {}
    for arc in candidate.arcs:
        if arc.arc_type != "heavy_running":
            continue
        service = bundle.service_types[arc.train_type]
        intervals_by_demand.setdefault(arc.demand_id, []).append(
            (round(arc.start_km, 6), round(arc.end_km, 6), service.consist_unit)
        )
    if not intervals_by_demand:
        raise AssertionError("候选网络没有重列运行弧")

    for demand_id, intervals in intervals_by_demand.items():
        demand = demand_by_id[demand_id]
        origin_km = bundle.station_positions_km[demand.origin_station]
        destination_km = bundle.station_positions_km[demand.destination_station]
        breakpoints = sorted(
            {round(origin_km, 6), round(destination_km, 6)}
            | {km for item in intervals for km in (item[0], item[1])}
        )
        section_units: list[tuple[float, float, int]] = []
        for left, right in zip(breakpoints, breakpoints[1:]):
            midpoint = (left + right) / 2.0
            total = sum(
                units
                for start_km, end_km, units in intervals
                if min(start_km, end_km) <= midpoint <= max(start_km, end_km)
            )
            section_units.append((left, right, total))
        if not section_units:
            raise AssertionError(f"{demand_id} 没有可校验的运行区段")
        expected = section_units[0][2]
        if expected <= 0:
            raise AssertionError(f"{demand_id} 起点区段编组单元数为 {expected}")
        for left, right, total in section_units:
            if total != expected:
                raise AssertionError(
                    f"{demand_id} 在 {left}-{right} km 区段的编组单元数为 {total}，"
                    f"与起点区段的 {expected} 不一致（组合/分解处发生车底凭空增减）"
                )
        span_start = min(item[0] for item in intervals)
        span_end = max(item[1] for item in intervals)
        if abs(span_start - origin_km) > 1e-6 or abs(span_end - destination_km) > 1e-6:
            raise AssertionError(
                f"{demand_id} 重列运行公里标跨度 {(span_start, span_end)} 未覆盖 OD 区间"
            )


def test_station_capacity_is_enforced(bundle) -> None:
    """站场能力约束：时隙压缩到单一时隙后，超能力必须被计为冲突。"""

    base = bundle.scenarios["capacity_surplus_demo"]
    tight = replace(base, time_slice_s=86_400, section_capacity_per_slot=99)
    candidate = _build_candidate(bundle, tight, "FORMATION_TIGHT", departure_shift_s=0, headway_s=base.min_headway_s)
    if candidate.conflict_count == 0:
        raise AssertionError("单时隙下站场作业应超过 capacity_per_slot 并产生冲突")
    if not any("operation capacity" in message for message in candidate.diagnostics):
        raise AssertionError(f"应报告站场作业超能力诊断，实际 {candidate.diagnostics[:3]}")


def test_output_projection_reports_explicit_arcs(bundle) -> None:
    """五类派生输出必须反映显式组合弧与真实在站等待。"""

    result = optimize_heavy_empty_network(bundle, "capacity_surplus_demo")
    outputs = dispatch_plan_output_rows(result, bundle)
    rhythm = outputs["combination_station_connection_rhythm.csv"]
    by_station = {row["station_name"]: row for row in rhythm}
    for station in ("肃宁北", "黄骅南"):
        row = by_station.get(station)
        if row is None:
            raise AssertionError(f"接续节拍输出缺少 {station}")
        if row["connection_model_status"] != "explicit_combination_arcs":
            raise AssertionError(
                f"{station} 应报告 explicit_combination_arcs，实际 {row['connection_model_status']}"
            )
        if row["operation_count"] <= 0:
            raise AssertionError(f"{station} 应至少有一次显式作业")
    waits = {row["station_name"]: row for row in outputs["station_wait_bounds.csv"]}
    combine_wait = waits.get("肃宁北")
    if combine_wait is None:
        raise AssertionError("在站等待输出缺少 肃宁北")
    if combine_wait["data_status"] != "optimized_explicit_wait":
        raise AssertionError(f"肃宁北 应报告 optimized_explicit_wait，实际 {combine_wait['data_status']}")
    if combine_wait["wait_upper_bound_s"] <= 0:
        raise AssertionError("肃宁北 先到车底应在站等待至组合作业开始")
    if combine_wait["wait_lower_bound_s"] > combine_wait["wait_upper_bound_s"]:
        raise AssertionError("等待上下界关系不成立")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    optimizer_module.write_optimization_outputs(result, OUTPUT_ROOT, bundle=bundle)
    if not (OUTPUT_ROOT / "time_space_arcs.csv").exists():
        raise AssertionError("缺少 time_space_arcs.csv 产物")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""

    bundle = _load_bundle()
    test_formation_operations_are_loaded(bundle)
    test_quantity_and_train_type_conservation(bundle)
    test_invalid_declarations_are_rejected(bundle)
    test_combining_and_dismantling_arcs_are_real(bundle)
    test_corridor_unit_conservation(bundle)
    test_station_capacity_is_enforced(bundle)
    test_output_projection_reports_explicit_arcs(bundle)
    print("formation operation verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
