# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Second-pass audit for machine-readable simulation outputs."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
import json
import math


@dataclass(frozen=True)
class ResultIssue:
    """类 ResultIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    source: str
    code: str
    message: str
    observed: Any = None


NONNEGATIVE_FIELDS = (
    "total_gen_kwh", "total_con_kwh", "direct_used_kwh", "battery_charge_kwh",
    "battery_discharge_kwh", "battery_charge_limited_kwh", "battery_discharge_limited_kwh",
    "wasted_kwh", "grid_kwh", "energy_term", "final_soc_kwh", "parked_energy_kwh",
    "constraint_violation", "electrical_constraint_violation_kwh",
    "accepted_by_power_arm_kwh", "recovered_energy_kwh",
)


def _number(value: Any) -> Optional[float]:
    """函数 _number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json(path: Path, issues: List[ResultIssue]) -> Optional[Dict[str, Any]]:
    """函数 _json：执行该模块中的相关处理逻辑。"""
    if not path.is_file():
        issues.append(ResultIssue("error", str(path), "missing_summary", "结果汇总文件不存在。"))
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        issues.append(ResultIssue("error", str(path), "invalid_json", f"结果汇总无法解析：{exc}"))
        return None
    if not isinstance(payload, dict):
        issues.append(ResultIssue("error", str(path), "invalid_summary_shape", "结果汇总必须是 JSON 对象。"))
        return None
    return payload


def _check_nonnegative_numbers(obj: Any, source: str, issues: List[ResultIssue], prefix: str = "") -> None:
    """函数 _check_nonnegative_numbers：执行该模块中的相关处理逻辑。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in NONNEGATIVE_FIELDS:
                number = _number(value)
                if number is None or number < -1e-9:
                    issues.append(ResultIssue("error", source, "invalid_energy_value", f"{path} 必须是有限非负数。", value))
            _check_nonnegative_numbers(value, source, issues, path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _check_nonnegative_numbers(value, source, issues, f"{prefix}[{index}]")


def _close(a: Any, b: Any, tolerance: float = 1e-3) -> bool:
    """函数 _close：执行该模块中的相关处理逻辑。"""
    x, y = _number(a), _number(b)
    return x is not None and y is not None and abs(x - y) <= tolerance * max(1.0, abs(x), abs(y))


def _check_dispatch(path: Path, payload: Dict[str, Any], issues: List[ResultIssue]) -> None:
    """函数 _check_dispatch：执行该模块中的相关处理逻辑。"""
    required_fields = (
        "total_gen_kwh", "total_con_kwh", "direct_used_kwh", "battery_charge_kwh",
        "battery_discharge_kwh", "wasted_kwh", "grid_kwh", "final_soc_kwh",
    )
    for name in ("baseline", "optimized"):
        case = payload.get(name)
        if not isinstance(case, dict):
            continue
        source = f"{path}:{name}"
        missing = [field for field in required_fields if field not in case]
        if missing:
            issues.append(ResultIssue("error", source, "missing_dispatch_metrics", "dispatch 汇总缺少必需能量指标。", missing))
            continue
        gen, charge, direct, wasted = (case.get(k, 0.0) for k in ("total_gen_kwh", "battery_charge_kwh", "direct_used_kwh", "wasted_kwh"))
        con, grid, discharge = (case.get(k, 0.0) for k in ("total_con_kwh", "grid_kwh", "battery_discharge_kwh"))
        if all(_number(v) is not None for v in (gen, charge, direct, wasted)) and not _close(gen, charge + direct + wasted):
            issues.append(ResultIssue("error", source, "generation_not_conserved", "发电侧能量未守恒：total_gen != direct + charge + wasted。", {"total_gen_kwh": gen, "components": charge + direct + wasted}))
        if all(_number(v) is not None for v in (con, grid, direct, discharge)) and not _close(con, grid + direct + discharge):
            issues.append(ResultIssue("error", source, "traction_not_conserved", "用电侧能量未守恒：total_con != grid + direct + discharge。", {"total_con_kwh": con, "components": grid + direct + discharge}))
        accepted = case.get("accepted_by_power_arm_kwh")
        if accepted is not None and all(_number(v) is not None for v in (accepted, direct, charge)) and not _close(accepted, float(direct) + float(charge)):
            issues.append(ResultIssue("error", source, "accepted_energy_mismatch", "供电臂接纳量与直接利用量/储能充电量不一致。", {"accepted_by_power_arm_kwh": accepted, "components": float(direct) + float(charge)}))
        recovered = case.get("recovered_energy_kwh")
        efficiency = _number(case.get("storage_efficiency", 1.0))
        if recovered is not None and efficiency is not None and all(_number(v) is not None for v in (recovered, direct, charge)) and not _close(recovered, float(direct) + float(charge) * efficiency):
            issues.append(ResultIssue("error", source, "recovered_energy_mismatch", "有效回收量与直接利用量、储能充电量和效率不一致。", {"recovered_energy_kwh": recovered, "expected": float(direct) + float(charge) * efficiency}))
        rate = _number(case.get("recovery_rate"))
        if rate is not None and (rate < -1e-9 or rate > 1.0 + 1e-6):
            issues.append(ResultIssue("error", source, "recovery_rate_out_of_bounds", "回收率必须位于 [0, 1]。", rate))
        if rate is not None and recovered is not None and _number(gen) is not None and float(gen) > 1e-9 and not _close(rate, float(recovered) / float(gen), tolerance=2e-3):
            issues.append(ResultIssue("error", source, "recovery_rate_mismatch", "回收率与有效回收量/理论再生量不一致。", {"recovery_rate": rate, "expected": float(recovered) / float(gen)}))
        soc_map = case.get("final_soc_by_storage_kwh")
        if isinstance(soc_map, dict):
            soc_sum = sum((_number(v) or 0.0) for v in soc_map.values())
            if not _close(case.get("final_soc_kwh"), soc_sum):
                issues.append(ResultIssue("error", source, "soc_total_mismatch", "final_soc_kwh 与分设备 SOC 汇总不一致。", {"final_soc_kwh": case.get("final_soc_kwh"), "sum": soc_sum}))
            battery_payload = payload.get("battery") if isinstance(payload.get("battery"), dict) else {}
            if name == "optimized":
                selected = payload.get("selected_storage_preset")
                if isinstance(selected, dict) and isinstance(selected.get("optimized_battery"), dict):
                    battery_payload = selected["optimized_battery"]
            capacity = _number(battery_payload.get("capacity_kwh"))
            if capacity is not None and any((_number(v) is None or float(v) < -1e-9 or float(v) > capacity + 1e-6) for v in soc_map.values()):
                issues.append(ResultIssue("error", source, "soc_out_of_bounds", "分设备 SOC 超出 [0, capacity]。", {"capacity_kwh": capacity, "soc": soc_map}))


def _check_rolling(path: Path, payload: Dict[str, Any], issues: List[ResultIssue]) -> None:
    """检查滚动基准状态门禁与逐储能设备能量账本。"""

    source = str(path)
    cycles = payload.get("cycles")
    if payload.get("status") != "completed" or not isinstance(cycles, list) or not cycles:
        issues.append(
            ResultIssue("error", source, "invalid_rolling_result", "滚动结果未完成或缺少周期明细。")
        )
        return
    if payload.get("cycle_count") != len(cycles):
        issues.append(
            ResultIssue(
                "error", source, "rolling_cycle_count_mismatch",
                "cycle_count 与周期明细数量不一致。",
                {"cycle_count": payload.get("cycle_count"), "rows": len(cycles)},
            )
        )
    if payload.get("all_gates_passed") is not True:
        issues.append(
            ResultIssue("error", source, "rolling_gate_failed", "滚动基准存在未通过的质量门禁。")
        )
    gates = payload.get("gates")
    if not isinstance(gates, dict) or any(value is not True for value in gates.values()):
        issues.append(
            ResultIssue("error", source, "rolling_gate_details_invalid", "滚动门禁明细缺失或包含失败项。", gates)
        )

    previous_final = None
    for index, cycle in enumerate(cycles):
        cycle_source = f"{source}:cycle[{index}]"
        if not isinstance(cycle, dict):
            issues.append(ResultIssue("error", cycle_source, "invalid_rolling_cycle", "周期明细必须是对象。"))
            continue
        states = cycle.get("storage_device_states")
        parameters = cycle.get("storage_parameters_by_id")
        initial = cycle.get("initial_soc_by_storage_kwh")
        final = cycle.get("executed_final_soc_by_storage_kwh")
        charge = cycle.get("executed_charge_by_storage_kwh")
        discharge = cycle.get("executed_discharge_by_storage_kwh")
        wasted = cycle.get("executed_wasted_by_storage_kwh")
        maps = (initial, final, charge, discharge, wasted)
        if not isinstance(states, list) or not states or not isinstance(parameters, dict) or not all(
            isinstance(value, dict) for value in maps
        ):
            issues.append(
                ResultIssue("error", cycle_source, "missing_storage_device_result", "周期缺少逐设备状态或能量明细。")
            )
            continue
        state_by_id = {
            str(item.get("storage_section_id") or ""): item
            for item in states
            if isinstance(item, dict)
        }
        if "" in state_by_id or len(state_by_id) != len(states):
            issues.append(
                ResultIssue("error", cycle_source, "invalid_storage_device_ids", "设备ID为空或重复。")
            )
            continue
        expected_ids = set(state_by_id)
        if set(parameters) != expected_ids or any(set(value) != expected_ids for value in maps):
            issues.append(
                ResultIssue(
                    "error", cycle_source, "storage_device_coverage_mismatch",
                    "设备状态、SOC和能量明细未覆盖同一设备集合。",
                )
            )
            continue
        numeric_maps_valid = not any(
            _number(value) is None or float(value) < -1e-9
            for values in maps
            for value in values.values()
        )
        if not numeric_maps_valid:
            issues.append(
                ResultIssue("error", cycle_source, "invalid_storage_device_value", "逐设备SOC和能量必须为有限非负数。")
            )
        if numeric_maps_valid and not _close(
            cycle.get("initial_soc_kwh"), sum(float(value) for value in initial.values())
        ):
            issues.append(
                ResultIssue("error", cycle_source, "initial_soc_total_mismatch", "初始总SOC与逐设备汇总不一致。")
            )
        if numeric_maps_valid and not _close(
            cycle.get("executed_final_soc_kwh"), sum(float(value) for value in final.values())
        ):
            issues.append(
                ResultIssue("error", cycle_source, "final_soc_total_mismatch", "终端总SOC与逐设备汇总不一致。")
            )
        for storage_id, state in state_by_id.items():
            specification = parameters.get(storage_id)
            if not isinstance(specification, dict):
                issues.append(
                    ResultIssue("error", cycle_source, "invalid_storage_device_parameters", "逐设备额定参数必须是对象。", storage_id)
                )
                continue
            numeric_names = (
                "capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw",
                "charge_efficiency", "discharge_efficiency", "initial_soc_kwh",
                "min_soc_kwh", "max_soc_kwh",
            )
            numeric_values = {
                name: _number(specification.get(name)) for name in numeric_names
            }
            parameters_valid = all(value is not None for value in numeric_values.values())
            if parameters_valid:
                capacity = numeric_values["capacity_kwh"]
                minimum = numeric_values["min_soc_kwh"]
                maximum = numeric_values["max_soc_kwh"]
                configured_initial = numeric_values["initial_soc_kwh"]
                parameters_valid = bool(
                    capacity > 0.0
                    and numeric_values["max_charge_power_kw"] >= 0.0
                    and numeric_values["max_discharge_power_kw"] >= 0.0
                    and 0.0 < numeric_values["charge_efficiency"] <= 1.0
                    and 0.0 < numeric_values["discharge_efficiency"] <= 1.0
                    and 0.0 <= minimum <= configured_initial <= maximum <= capacity
                )
            if not parameters_valid or type(specification.get("available")) is not bool:
                issues.append(
                    ResultIssue("error", cycle_source, "invalid_storage_device_parameters", "逐设备容量、功率、效率、SOC边界或静态可用状态无效。", storage_id)
                )
            elif numeric_maps_valid and (
                float(initial[storage_id]) < numeric_values["min_soc_kwh"] - 1e-9
                or float(initial[storage_id]) > numeric_values["max_soc_kwh"] + 1e-9
                or float(final[storage_id]) < numeric_values["min_soc_kwh"] - 1e-9
                or float(final[storage_id]) > numeric_values["max_soc_kwh"] + 1e-9
            ):
                issues.append(
                    ResultIssue("error", cycle_source, "storage_soc_out_of_device_bounds", "逐设备SOC超出数据库额定上下限。", storage_id)
                )
            if (
                parameters_valid
                and specification.get("available") is False
                and numeric_maps_valid
                and (
                    abs(float(charge[storage_id])) > 1e-9
                    or abs(float(discharge[storage_id])) > 1e-9
                )
            ):
                issues.append(
                    ResultIssue("error", cycle_source, "disabled_storage_has_flow", "数据库静态停运设备仍发生充电或放电。", storage_id)
                )
            if type(state.get("available")) is not bool:
                issues.append(
                    ResultIssue("error", cycle_source, "invalid_storage_availability", "设备available必须是布尔值。", storage_id)
                )
            elif numeric_maps_valid and not state["available"] and (
                abs(float(charge[storage_id])) > 1e-9
                or abs(float(discharge[storage_id])) > 1e-9
            ):
                issues.append(
                    ResultIssue("error", cycle_source, "offline_storage_has_flow", "停运设备仍发生充电或放电。", storage_id)
                )
        if previous_final is not None:
            previous_ids = set(previous_final) if isinstance(previous_final, dict) else set()
            if previous_ids != expected_ids or (
                numeric_maps_valid
                and any(
                    not _close(initial[storage_id], previous_final[storage_id])
                    for storage_id in expected_ids
                )
            ):
                issues.append(
                    ResultIssue("error", cycle_source, "storage_soc_discontinuity", "合成基准的逐设备SOC未从上一执行窗口连续传递。")
                )
        previous_final = final


def audit_output_root(output_root: Path) -> Dict[str, Any]:
    """函数 audit_output_root：执行该模块中的相关处理逻辑。"""
    output_root = Path(output_root)
    issues: List[ResultIssue] = []
    found_artifact = False
    workflow_path = output_root / "simulation_workflow_summary.json"
    workflow = None
    if workflow_path.exists():
        found_artifact = True
        workflow = _json(workflow_path, issues)
    if workflow is not None:
        _check_nonnegative_numbers(workflow, str(workflow_path), issues)
        dispatch = workflow.get("dispatch-case")
        if isinstance(dispatch, dict):
            _check_dispatch(output_root / "dispatch-case", dispatch, issues)
    dispatch_paths = sorted(output_root.glob("dispatch_*/summary.json"))
    direct_dispatch_path = output_root / "summary.json"
    if direct_dispatch_path.is_file():
        dispatch_paths.append(direct_dispatch_path)
    dispatch_paths = sorted(set(dispatch_paths))
    for dispatch_path in dispatch_paths:
        found_artifact = True
        dispatch = _json(dispatch_path, issues)
        if dispatch is not None:
            _check_nonnegative_numbers(dispatch, str(dispatch_path), issues)
            _check_dispatch(dispatch_path, dispatch, issues)
    # 兼容两类输出结构：历史工作流使用固定的子目录名；正式实验总控则为每个
    # 方案直接建立独立目录，汇总文件位于该目录根部。两者都必须接受相同审计。
    timetable_summary_paths = (
        output_root / "audit_summary.json",
        output_root / "optimizer_summary.json",
        output_root / "timetable_energy_audit" / "audit_summary.json",
        output_root / "timetable_optimizer_nsga2" / "optimizer_summary.json",
    )
    for summary_path in timetable_summary_paths:
        if summary_path.exists():
            found_artifact = True
            payload = _json(summary_path, issues)
            if payload is not None and payload.get("valid") is False:
                issues.append(ResultIssue("error", str(summary_path), "invalid_pipeline_result", "流程汇总标记为 valid=false。"))
    rolling_path = output_root / "benchmark_summary.json"
    if rolling_path.is_file():
        found_artifact = True
        payload = _json(rolling_path, issues)
        if payload is not None:
            _check_nonnegative_numbers(payload, str(rolling_path), issues)
            _check_rolling(rolling_path, payload, issues)
    if not found_artifact:
        issues.append(ResultIssue("error", str(output_root), "no_recognized_outputs", "输出目录中没有可识别的结果汇总文件。"))
    error_count = sum(item.severity == "error" for item in issues)
    return {"accepted": error_count == 0, "output_root": str(output_root), "error_count": error_count, "warning_count": sum(item.severity == "warning" for item in issues), "issues": [asdict(item) for item in issues]}


def write_report(summary: Dict[str, Any], output_dir: Optional[Path] = None) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    target = Path(output_dir or summary["output_root"])
    target.mkdir(parents=True, exist_ok=True)
    (target / "result_quality_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (target / "result_quality_audit_issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("severity", "source", "code", "message", "observed"))
        writer.writeheader()
        for item in summary["issues"]:
            writer.writerow({**item, "observed": json.dumps(item.get("observed"), ensure_ascii=False)})
    lines = ["# 输出结果质量检查报告", "", f"- 检查通过：`{summary['accepted']}`", f"- 错误：`{summary['error_count']}`", "", "| 级别 | 来源 | 代码 | 说明 |", "| --- | --- | --- | --- |"]
    lines.extend(f"| {item['severity']} | `{item['source']}` | `{item['code']}` | {item['message']} |" for item in summary["issues"])
    (target / "RESULT_QUALITY_AUDIT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
