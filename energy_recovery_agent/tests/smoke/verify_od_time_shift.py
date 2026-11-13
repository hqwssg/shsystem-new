"""验证逐 OD 流时移约束（技术方案 4.2.1.2(2) 扩展约束 (16)–(23)）。

本用例覆盖：
1. 逐 OD 时移可从模板装载，留空/缺省时不改变既有行为（回落为全局发车时移）；
2. 时间调整唯一性：同一 OD 只允许一个调整量，重复声明与未知 OD 必须被拒绝；
3. OD 链起终一致：始发发车偏移量必须等于终到到达偏移量（约束 18–22），且真实网络
   发车时刻按声明量整体平移；
4. 上下界：超过 ``max_departure_shift_s`` 必须记为违反并夹紧到边界；
5. 移位后时间可行性：负向时移把发车推到发车窗口之前必须记为违反；
6. 组合列车两支一致：同一组合站各来源 OD 必须取相同时移（约束 23）；
7. 能力复核：移位后发车若造成区段时段越限，必须记为冲突并反映在产物中；
8. 产物一致：``od_time_shift.csv`` 与候选字段、summary.json 登记项一致。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import (
    FormationOperation,
    HeOdDemand,
    _build_candidate,
    _combined_train_shift_issues,
    _od_time_shift_map,
    _validate_he_input_bundle,
    load_he_input_template,
    od_time_shift_rows,
    optimize_heavy_empty_network,
    write_optimization_outputs,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("od_time_shift")

EXPECTED_FIELDS = {
    "candidate_id", "demand_id", "origin_station", "destination_station", "train_count",
    "selected_train_count", "requested_shift_s", "applied_shift_s", "within_bounds",
    "post_shift_feasible", "departure_shift_s", "arrival_shift_s", "od_chain_consistent",
    "capacity_recheck",
}


def _row(rows, demand_id):
    matched = [row for row in rows if row["demand_id"] == demand_id]
    if len(matched) != 1:
        raise AssertionError(f"expected exactly one od_time_shift row for {demand_id}, got {matched}")
    return matched[0]


def _heavy_departure_s(candidate, demand_id) -> int:
    times = [
        node.time_s
        for node in candidate.nodes
        if node.demand_id == demand_id and node.state == "heavy_departure"
    ]
    if not times:
        raise AssertionError(f"{demand_id} has no heavy_departure node")
    return min(times)


def test_shift_parameters_are_loaded(bundle) -> None:
    """模板缺省不得声明逐 OD 时移，从而保证既有行为不被改变。"""

    if bundle.od_time_shifts:
        raise AssertionError(f"默认模板不应声明逐 OD 时移，实际 {bundle.od_time_shifts}")
    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(bundle, scenario, "LOAD", 0, scenario.min_headway_s)
    if candidate.od_time_shift_violation_count != 0:
        raise AssertionError("缺省时移不应产生违反")
    for row in candidate.od_time_shift_rows:
        if row["requested_shift_s"] != 0 or row["applied_shift_s"] != 0:
            raise AssertionError(f"缺省时移应回落为全局 0，实际 {row}")


def test_uniqueness_is_enforced(bundle) -> None:
    """时间调整唯一性：重复 demand_id 与未知 demand_id 必须被拒绝。"""

    try:
        _od_time_shift_map([("OD001", 60), ("OD001", 120)])
    except ValueError as exc:
        if "duplicate" not in str(exc):
            raise AssertionError(f"重复声明的报错信息不正确：{exc}")
    else:
        raise AssertionError("同一 OD 的重复时移声明必须被拒绝")

    try:
        _validate_he_input_bundle(replace(bundle, od_time_shifts=(("NOPE", 60),)))
    except ValueError as exc:
        if "unknown" not in str(exc):
            raise AssertionError(f"未知 OD 的报错信息不正确：{exc}")
    else:
        raise AssertionError("引用未知 OD 的时移声明必须被拒绝")


def test_shift_is_applied_and_od_chain_is_consistent(bundle) -> None:
    """OD 链起终一致：发车偏移量 == 到达偏移量，且网络发车时刻整体平移。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    baseline = _build_candidate(bundle, scenario, "CHAIN_BASE", 0, scenario.min_headway_s)
    shifted = _build_candidate(
        bundle, scenario, "CHAIN_SHIFT", 0, scenario.min_headway_s,
        od_time_shifts={"OD002": 600},
    )
    row = _row(shifted.od_time_shift_rows, "OD002")
    if row["applied_shift_s"] != 600:
        raise AssertionError(f"声明的时移未被施加：{row}")
    if row["departure_shift_s"] != 600 or row["arrival_shift_s"] != 600:
        raise AssertionError(f"OD 链起终偏移量不一致：{row}")
    if row["od_chain_consistent"] is not True:
        raise AssertionError(f"OD 链一致性标记错误：{row}")
    if shifted.od_time_shift_violation_count != 0 or not shifted.feasible:
        raise AssertionError(f"合法时移不应产生违反：{shifted.diagnostics}")
    # 真实网络：OD002 重列发车时刻必须整体后移 600s，其余 OD 不受影响。
    delta = _heavy_departure_s(shifted, "OD002") - _heavy_departure_s(baseline, "OD002")
    if delta != 600:
        raise AssertionError(f"OD002 发车时刻实际偏移 {delta}s，应为 600s")
    if _heavy_departure_s(shifted, "OD003") != _heavy_departure_s(baseline, "OD003"):
        raise AssertionError("未声明时移的 OD 不应被影响")
    # 同一 OD 的多个车底共用同一个调整量（唯一性口径）。
    row_od001 = _row(
        _build_candidate(
            bundle, scenario, "CHAIN_OD001", 0, scenario.min_headway_s,
            od_time_shifts={"OD001": 300},
        ).od_time_shift_rows,
        "OD001",
    )
    if row_od001["applied_shift_s"] != 300 or row_od001["selected_train_count"] != 2:
        raise AssertionError(f"同一 OD 的多车底必须共用同一时移：{row_od001}")


def test_od_chain_guard_catches_inconsistent_arrival() -> None:
    """故障注入：到达未随时移等量平移时，OD 链一致性守卫必须报出不一致。"""

    import heavy_empty_network_optimizer as optimizer_module

    bundle = load_he_input_template(TEMPLATE)
    scenario = bundle.scenarios["capacity_surplus_demo"]
    original = optimizer_module._formation_leg_plan
    calls = {"count": 0}

    def _perturbed(*args, **kwargs):
        plan, operations = original(*args, **kwargs)
        calls["count"] += 1
        # 偶数次调用是核对用的基线重排：人为把到达整体推后 60s，制造"到达未等量平移"。
        if calls["count"] % 2 == 0:
            perturbed = {
                index: {**entry, "time": int(entry["time"]) + 60}
                for index, entry in plan.items()
            }
            return perturbed, operations
        return plan, operations

    with patch.object(optimizer_module, "_formation_leg_plan", side_effect=_perturbed):
        candidate = optimizer_module._build_candidate(
            bundle, scenario, "CHAIN_FAULT", 0, scenario.min_headway_s,
            od_time_shifts={"OD002": 600},
        )
    row = _row(candidate.od_time_shift_rows, "OD002")
    if row["od_chain_consistent"] is not False:
        raise AssertionError(f"到达未等量平移时必须报出 OD 链不一致：{row}")
    if candidate.feasible:
        raise AssertionError("OD 链不一致的候选必须不可行")
    if not any("OD-chain consistency" in message for message in candidate.diagnostics):
        raise AssertionError(f"应输出 OD 链不一致诊断：{candidate.diagnostics[:3]}")


def test_bounds_are_enforced(bundle) -> None:
    """上下界：超过 max_departure_shift_s 必须记为违反，并夹紧到边界。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(
        bundle, scenario, "BOUNDS", 0, scenario.min_headway_s,
        od_time_shifts={"OD002": scenario.max_departure_shift_s + 3600},
    )
    row = _row(candidate.od_time_shift_rows, "OD002")
    if row["within_bounds"] is not False:
        raise AssertionError(f"越界时移必须标记 within_bounds=False：{row}")
    if row["applied_shift_s"] != scenario.max_departure_shift_s:
        raise AssertionError(f"越界时移必须夹紧到边界：{row}")
    if candidate.od_time_shift_violation_count <= 0:
        raise AssertionError("越界时移必须记为违反")
    if candidate.feasible:
        raise AssertionError("存在越界时移的候选必须不可行")
    if candidate.constraint_violation < candidate.od_time_shift_violation_count:
        raise AssertionError("时移违反必须计入约束违反量")


def test_post_shift_time_feasibility(bundle) -> None:
    """移位后时间可行性：负向时移不得把发车推到发车窗口之前。"""

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(
        bundle, scenario, "INFEASIBLE_TIME", 0, scenario.min_headway_s,
        od_time_shifts={"OD002": -600},
    )
    row = _row(candidate.od_time_shift_rows, "OD002")
    if row["post_shift_feasible"] is not False:
        raise AssertionError(f"负向越窗时移必须标记 post_shift_feasible=False：{row}")
    if candidate.od_time_shift_violation_count <= 0 or candidate.feasible:
        raise AssertionError(f"越窗时移必须使候选不可行：{candidate.diagnostics}")


def test_combined_train_two_branch_consistency(bundle) -> None:
    """组合列车两支一致：同一组合站各来源 OD 必须取相同时移（约束 23）。"""

    # 构造 OD001 与 OD002 同时在肃宁北组合的场景（OD002 复制为 2 个车底以满足组合数量守恒）。
    od002 = replace(bundle.demands[1], train_count=2)
    synthetic_ops = bundle.formation_operations + (
        FormationOperation(
            operation_id="FO900",
            station_name="肃宁北",
            operation_type="combine",
            leg="heavy",
            demand_id="OD002",
            input_copies=(1, 2),
            output_copies=(1,),
            upstream_service="HeavySmall",
            downstream_service="Heavy",
        ),
    )
    synthetic = replace(
        bundle,
        demands=(bundle.demands[0], od002, bundle.demands[2]),
        formation_operations=synthetic_ops,
    )
    if _combined_train_shift_issues(synthetic, {"OD001": 300, "OD002": 300}):
        raise AssertionError("同一组合站取相同时移时不应报告不一致")
    issues = _combined_train_shift_issues(synthetic, {"OD001": 300, "OD002": 900})
    if len(issues) != 1 or "肃宁北" not in issues[0]:
        raise AssertionError(f"组合列车两支时移不一致必须被检出：{issues}")

    scenario = bundle.scenarios["capacity_surplus_demo"]
    candidate = _build_candidate(
        synthetic, scenario, "COMBINED", 0, scenario.min_headway_s,
        od_time_shifts={"OD001": 300, "OD002": 900},
    )
    if candidate.combined_train_shift_violation_count != 1:
        raise AssertionError(
            f"组合列车两支不一致必须计入违反：{candidate.combined_train_shift_violation_count}"
        )
    if candidate.feasible:
        raise AssertionError("组合列车两支时移不一致的候选必须不可行")


def test_capacity_recheck(bundle) -> None:
    """能力复核：移位后发车造成区段时段越限时必须记为冲突并反映在产物中。"""

    origin = bundle.demands[0].origin_station
    destination = bundle.demands[0].destination_station
    first = replace(
        bundle.demands[0],
        demand_id="OD_A",
        train_count=1,
        earliest_departure_s=3600,
        latest_departure_s=8 * 3600,
        due_arrival_s=20 * 3600,
    )
    second = replace(
        bundle.demands[0],
        demand_id="OD_B",
        train_count=1,
        earliest_departure_s=4 * 3600,
        latest_departure_s=8 * 3600,
        due_arrival_s=20 * 3600,
    )
    scenario = replace(
        bundle.scenarios["capacity_surplus_demo"],
        time_slice_s=900,
        section_capacity_per_slot=1,
        min_headway_s=600,
        max_departure_shift_s=12 * 3600,
    )
    tight = replace(bundle, demands=(first, second), formation_operations=())

    baseline = _build_candidate(tight, scenario, "CAP_BASE", 0, scenario.min_headway_s)
    if baseline.conflict_count != 0:
        raise AssertionError(f"基线不应越限：{baseline.diagnostics}")
    # 把 OD_A 后移到 OD_B 的时段内，容量 1 下必然越限。
    shifted = _build_candidate(
        tight, scenario, "CAP_SHIFT", 0, scenario.min_headway_s,
        od_time_shifts={"OD_A": 4 * 3600 - 3600},
    )
    if shifted.conflict_count <= 0:
        raise AssertionError("移位造成的区段越限必须记为冲突")
    if not any(row["capacity_recheck"] == "overflow" for row in shifted.od_time_shift_rows):
        raise AssertionError(f"产物必须反映能力复核越限：{shifted.od_time_shift_rows}")


def test_output_artifact_matches_candidate(bundle) -> None:
    """od_time_shift.csv 必须写出，并与候选字段、summary.json 登记项一致。"""

    result = optimize_heavy_empty_network(bundle, "capacity_surplus_demo")
    rows = od_time_shift_rows(result, bundle)
    if not rows:
        raise AssertionError("逐 OD 时移产物为空")
    for row in rows:
        if set(row) != EXPECTED_FIELDS:
            raise AssertionError(f"时移产物字段不一致：{sorted(set(row) ^ EXPECTED_FIELDS)}")
        if row["candidate_id"] != result.best_candidate.candidate_id:
            raise AssertionError("时移产物的候选编号与最优候选不一致")
        if row["within_bounds"] is not True or row["post_shift_feasible"] is not True:
            raise AssertionError(f"最优候选的时移应合法：{row}")
        if row["od_chain_consistent"] is not True:
            raise AssertionError(f"最优候选的 OD 链必须一致：{row}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_optimization_outputs(result, OUTPUT_ROOT, bundle=bundle)
    path = OUTPUT_ROOT / "od_time_shift.csv"
    if not path.exists():
        raise AssertionError("缺少 od_time_shift.csv 产物")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        written = list(csv.DictReader(handle))
    if len(written) != len(rows):
        raise AssertionError("写出的时移行数与统计结果不一致")
    if set(written[0]) != EXPECTED_FIELDS:
        raise AssertionError(f"写出的时移表头不一致：{sorted(set(written[0]) ^ EXPECTED_FIELDS)}")

    summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    if summary.get("od_time_shift_output") != "od_time_shift.csv":
        raise AssertionError("summary.json 必须登记 od_time_shift_output")
    if summary.get("declared_od_time_shift_count") != len(rows):
        raise AssertionError("summary.json 的时移条目数与产物不一致")
    if "best_od_time_shift_violation_count" not in summary:
        raise AssertionError("summary.json 必须登记最优候选的时移违反数")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""

    bundle = load_he_input_template(TEMPLATE)
    test_shift_parameters_are_loaded(bundle)
    test_uniqueness_is_enforced(bundle)
    test_shift_is_applied_and_od_chain_is_consistent(bundle)
    test_od_chain_guard_catches_inconsistent_arrival()
    test_bounds_are_enforced(bundle)
    test_post_shift_time_feasibility(bundle)
    test_combined_train_two_branch_consistency(bundle)
    test_capacity_recheck(bundle)
    test_output_artifact_matches_candidate(bundle)
    print("od time shift verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
