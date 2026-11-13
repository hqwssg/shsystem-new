"""验证五类数据库任务参数对异常类型、数值、路径和设备状态的拒绝行为。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.parameters import validate_run_parameters


@dataclass(frozen=True)
class ParameterCase:
    """定义一个参数边界案例及其预期结果。"""

    case_id: str
    category: str
    name: str
    run_type: str
    parameters: Any
    expected_accept: bool
    expected_text: str = ""


def _device(**overrides: Any) -> dict[str, Any]:
    row = {"storage_section_id": "S1", "soc_kwh": 50.0, "available": True}
    row.update(overrides)
    return row


def _cases() -> tuple[ParameterCase, ...]:
    """覆盖所有任务类型及共享参数校验分支。"""

    valid_timetable = {"timetable_relative_path": "platform/running_diagram.xlsx"}
    return (
        ParameterCase("PP-V01", "有效边界", "最小dispatch请求", "dispatch", {}, True),
        ParameterCase("PP-V02", "有效边界", "运行图审查请求", "timetable_audit", valid_timetable, True),
        ParameterCase("PP-V03", "有效边界", "运行图优化请求", "timetable_optimization", valid_timetable, True),
        ParameterCase("PP-V04", "有效边界", "最小滚动请求", "rolling_rescheduling", {}, True),
        ParameterCase("PP-V05", "有效边界", "联合稳健请求", "joint_parameter_robustness", {"parameter_ranges_relative_path": "platform/ranges.json"}, True),
        ParameterCase("PP-V06", "有效边界", "概率闭区间下界", "timetable_optimization", {**valid_timetable, "mutation_rate": 0.0}, True),
        ParameterCase("PP-V07", "有效边界", "概率闭区间上界", "timetable_optimization", {**valid_timetable, "crossover_rate": 1.0}, True),
        ParameterCase("PP-V08", "有效边界", "零值非负整数", "dispatch", {"seed": 0, "baseline_phase_s": 0}, True),
        ParameterCase("PP-V09", "有效边界", "设备停运零功率", "rolling_rescheduling", {"storage_devices": [_device(available=False, max_charge_power_kw=0, max_discharge_power_kw=0)]}, True),
        ParameterCase("PP-F01", "结构与白名单", "任务参数不是对象", "dispatch", [], False, "JSON对象"),
        ParameterCase("PP-F02", "结构与白名单", "未知任务类型", "unknown", {}, False, "不支持"),
        ParameterCase("PP-F03", "结构与白名单", "白名单外字段", "dispatch", {"shell_command": "bad"}, False, "未批准参数"),
        ParameterCase("PP-F04", "结构与白名单", "数值字段使用布尔值", "dispatch", {"population_size": True}, False, "必须是数值"),
        ParameterCase("PP-F05", "结构与白名单", "布尔字段使用字符串", "dispatch", {"disable_energy_observability": "false"}, False, "必须是布尔值"),
        ParameterCase("PP-N01", "数值与枚举", "正整数为零", "dispatch", {"population_size": 0}, False, "大于0"),
        ParameterCase("PP-N02", "数值与枚举", "非负整数为负", "dispatch", {"seed": -1}, False, "不能小于0"),
        ParameterCase("PP-N03", "数值与枚举", "整数参数为小数", "dispatch", {"heavy_count": 1.5}, False, "必须是整数"),
        ParameterCase("PP-N04", "数值与枚举", "整数秒为小数", "dispatch", {"settlement_step_s": 0.5}, False, "必须是整数"),
        ParameterCase("PP-N05", "数值与枚举", "NaN", "dispatch", {"wasted_energy_penalty_per_kwh": float("nan")}, False, "有限数值"),
        ParameterCase("PP-N06", "数值与枚举", "正无穷", "dispatch", {"empty_mass_tons": float("inf")}, False, "有限数值"),
        ParameterCase("PP-N07", "数值与枚举", "负无穷", "timetable_optimization", {**valid_timetable, "max_shift_min": float("-inf")}, False, "有限数值"),
        ParameterCase("PP-N08", "数值与枚举", "概率低于零", "timetable_optimization", {**valid_timetable, "mutation_rate": -0.01}, False, "0到1"),
        ParameterCase("PP-N09", "数值与枚举", "概率高于一", "timetable_optimization", {**valid_timetable, "crossover_rate": 1.01}, False, "0到1"),
        ParameterCase("PP-N10", "数值与枚举", "非法目标模式", "dispatch", {"objective_mode": "invalid"}, False, "允许枚举"),
        ParameterCase("PP-N11", "数值与枚举", "非法搜索方法", "dispatch", {"search_method": "random-shell"}, False, "允许枚举"),
        ParameterCase("PP-P01", "快照路径", "审查缺少运行图路径", "timetable_audit", {}, False, "必须提供"),
        ParameterCase("PP-P02", "快照路径", "优化运行图路径为空", "timetable_optimization", {"timetable_relative_path": " "}, False, "必须提供"),
        ParameterCase("PP-P03", "快照路径", "运行图绝对路径", "timetable_audit", {"timetable_relative_path": "C:/secret/file.xlsx"}, False, "快照目录内"),
        ParameterCase("PP-P04", "快照路径", "运行图目录穿越", "timetable_audit", {"timetable_relative_path": "../file.xlsx"}, False, "快照目录内"),
        ParameterCase("PP-P05", "快照路径", "混合分隔符目录穿越", "timetable_optimization", {"timetable_relative_path": "platform\\..\\..\\file.xlsx"}, False, "快照目录内"),
        ParameterCase("PP-P06", "快照路径", "运行图路径不是字符串", "timetable_audit", {"timetable_relative_path": 123}, False, "路径字符串"),
        ParameterCase("PP-P07", "快照路径", "扰动路径为空", "rolling_rescheduling", {"disturbance_history_relative_path": ""}, False, "不能为空"),
        ParameterCase("PP-P08", "快照路径", "扰动路径越界", "rolling_rescheduling", {"disturbance_history_relative_path": "../../replay.json"}, False, "快照目录内"),
        ParameterCase("PP-P09", "快照路径", "联合区间路径缺失", "joint_parameter_robustness", {}, False, "必须提供"),
        ParameterCase("PP-P10", "快照路径", "联合区间绝对路径", "joint_parameter_robustness", {"parameter_ranges_relative_path": "/tmp/ranges.json"}, False, "快照目录内"),
        ParameterCase("PP-P11", "快照路径", "逻辑路径过长", "timetable_audit", {"timetable_relative_path": "a" * 501}, False, "长度不能超过500"),
        ParameterCase("PP-S01", "设备状态", "设备数组为空", "rolling_rescheduling", {"storage_devices": []}, False, "非空"),
        ParameterCase("PP-S02", "设备状态", "设备值不是数组", "rolling_rescheduling", {"storage_devices": {}}, False, "对象数组"),
        ParameterCase("PP-S03", "设备状态", "设备行不是对象", "rolling_rescheduling", {"storage_devices": ["S1"]}, False, "JSON对象"),
        ParameterCase("PP-S04", "设备状态", "设备缺少SOC", "rolling_rescheduling", {"storage_devices": [{"storage_section_id": "S1"}]}, False, "必须包含"),
        ParameterCase("PP-S05", "设备状态", "设备ID为空", "rolling_rescheduling", {"storage_devices": [_device(storage_section_id=" ")]}, False, "不能为空"),
        ParameterCase("PP-S06", "设备状态", "设备ID重复", "rolling_rescheduling", {"storage_devices": [_device(), _device(soc_kwh=20)]}, False, "重复设备ID"),
        ParameterCase("PP-S07", "设备状态", "SOC为负", "rolling_rescheduling", {"storage_devices": [_device(soc_kwh=-1)]}, False, "非负有限"),
        ParameterCase("PP-S08", "设备状态", "SOC为无穷", "rolling_rescheduling", {"storage_devices": [_device(soc_kwh=float("inf"))]}, False, "非负有限"),
        ParameterCase("PP-S09", "设备状态", "可用状态不是布尔值", "rolling_rescheduling", {"storage_devices": [_device(available=1)]}, False, "必须是布尔值"),
        ParameterCase("PP-S10", "设备状态", "运行功率为负", "rolling_rescheduling", {"storage_devices": [_device(max_charge_power_kw=-1)]}, False, "非负有限"),
        ParameterCase("PP-S11", "设备状态", "设备含未批准字段", "rolling_rescheduling", {"storage_devices": [_device(command="charge")]}, False, "未批准字段"),
        ParameterCase("PP-S12", "设备状态", "设备ID过长", "rolling_rescheduling", {"storage_devices": [_device(storage_section_id="S" * 129)]}, False, "长度不能超过128"),
        ParameterCase("PP-S13", "设备状态", "回放与设备状态同时提供", "rolling_rescheduling", {"disturbance_history_relative_path": "platform/replay.json", "storage_devices": [_device()]}, False, "不能与"),
    )


def run_matrix(output_dir: Path) -> dict[str, Any]:
    """运行参数矩阵并输出逐案例证据。"""

    rows: list[dict[str, Any]] = []
    for case in _cases():
        error = ""
        accepted = False
        try:
            validate_run_parameters(case.run_type, case.parameters)
            accepted = True
        except (TypeError, ValueError) as exc:
            error = str(exc)
        passed = accepted == case.expected_accept and (
            case.expected_accept or case.expected_text in error
        )
        rows.append({
            "case_id": case.case_id,
            "category": case.category,
            "name": case.name,
            "run_type": case.run_type,
            "expected": "accept" if case.expected_accept else "reject",
            "actual": "accept" if accepted else "reject",
            "expected_text": case.expected_text,
            "error": error,
            "passed": passed,
        })

    failed = [row for row in rows if not row["passed"]]
    categories: dict[str, dict[str, int]] = {}
    for row in rows:
        item = categories.setdefault(row["category"], {"case_count": 0, "passed_count": 0, "failed_count": 0})
        item["case_count"] += 1
        item["passed_count" if row["passed"] else "failed_count"] += 1
    stable = [{key: row[key] for key in ("case_id", "category", "run_type", "expected", "actual", "passed")} for row in rows]
    fingerprint = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    summary = {
        "schema_version": "1.0",
        "passed": not failed,
        "case_count": len(rows),
        "passed_count": len(rows) - len(failed),
        "failed_count": len(failed),
        "categories": categories,
        "case_set_sha256": fingerprint,
        "outputs": {
            "report": "PLATFORM_PARAMETER_ANOMALY_REPORT.md",
            "summary": "platform_parameter_anomaly_summary.json",
            "cases": "platform_parameter_anomaly_cases.csv",
            "failures": "platform_parameter_anomaly_failures.json",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / summary["outputs"]["summary"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / summary["outputs"]["failures"]).write_text(json.dumps({"failures": failed}, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (output_dir / summary["outputs"]["cases"]).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# 平台任务参数异常测试报告", "",
        f"- 案例数：{summary['case_count']}", f"- 通过：{summary['passed_count']}",
        f"- 失败：{summary['failed_count']}", f"- 案例指纹：`{fingerprint}`", "",
        "| 案例 | 类别 | 任务 | 输入 | 预期 | 实际 | 结果 |", "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| `{row['case_id']}` | {row['category']} | `{row['run_type']}` | {row['name']} | {row['expected']} | {row['actual']} | {'PASS' if row['passed'] else 'FAIL'} |")
    lines.extend(["", "通过只表示任务参数在入队前得到确定性校验，不替代数据库权限、并发、租约或现场接口测试。", ""])
    (output_dir / summary["outputs"]["report"]).write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/platform_parameter_anomaly_matrix")
    args = parser.parse_args()
    summary = run_matrix(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
