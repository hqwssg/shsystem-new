# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import csv
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_dispatch_case import build_parser as build_dispatch_parser
from run_dispatch_case import run_case


OUTPUT_ROOT = Path("outputs") / "simulation_experiment_suite"


CASE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "experiment_group": "preset_timetable_case",
        "case_id": "case_01_low_density_2x2",
        "case_name": "低密度相位探测 2重2空",
        "purpose": "观察低密度预设运行图是否仍可能受重空列相遇相位影响。",
        "heavy_count": 2,
        "empty_count": 2,
        "phase_s": 2600,
        "heavy_headway_s": 3600,
        "empty_headway_s": 3600,
    },
    {
        "experiment_group": "preset_timetable_case",
        "case_id": "case_02_current_3x3",
        "case_name": "当前推荐 3重3空",
        "purpose": "当前主线拟真默认方案，作为对比基准。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
    },
    {
        "experiment_group": "preset_timetable_case",
        "case_id": "case_03_dense_4x4",
        "case_name": "密集 4重4空",
        "purpose": "验证更密集预设运行图下资源约束是否暴露冲突。",
        "heavy_count": 4,
        "empty_count": 4,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
    },
    {
        "experiment_group": "preset_timetable_case",
        "case_id": "case_04_conflict_phase_3x3",
        "case_name": "冲突相位 3重3空",
        "purpose": "复现 2400s 相位下的安国咽喉冲突，用于说明相位调整的必要性。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2400,
        "heavy_headway_s": 3000,
        "empty_headway_s": 3000,
    },
    {
        "experiment_group": "empty_mass_sensitivity",
        "case_id": "sens_01_empty_mass_2160",
        "case_name": "空车质量 1500t",
        "purpose": "测试较轻回空列质量对能耗和储能利用的影响。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
        "empty_mass_tons": 2160,
    },
    {
        "experiment_group": "empty_mass_sensitivity",
        "case_id": "sens_02_empty_mass_4320",
        "case_name": "空车质量 4320t",
        "purpose": "按 1+1 空车编组总重假设测试较重回空列影响。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
        "empty_mass_tons": 4320,
    },
    {
        "experiment_group": "storage_sensitivity",
        "case_id": "sens_03_storage_capacity_5000",
        "case_name": "储能容量 5000kWh",
        "purpose": "测试较小储能容量下再生能量受限情况。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
        "battery_capacity_kwh": 5000,
    },
    {
        "experiment_group": "storage_sensitivity",
        "case_id": "sens_04_storage_capacity_40000",
        "case_name": "储能容量 40000kWh",
        "purpose": "测试较大储能容量是否显著提升再生能量吸收。",
        "heavy_count": 3,
        "empty_count": 3,
        "phase_s": 2600,
        "heavy_headway_s": 3300,
        "empty_headway_s": 2700,
        "battery_capacity_kwh": 40000,
    },
]


CASE_LABELS = {
    "case_01_low_density_2x2": "低密度相位探索 2重2空",
    "case_02_current_3x3": "当前推荐 3重3空",
    "case_03_dense_4x4": "密集 4重4空",
    "case_04_conflict_phase_3x3": "冲突相位 3重3空",
    "sens_01_empty_mass_2160": "空车质量 1500t",
    "sens_02_empty_mass_4320": "空车质量 4320t",
    "sens_03_storage_capacity_5000": "储能容量 5000kWh",
    "sens_04_storage_capacity_40000": "储能容量 40000kWh",
}

CASE_PURPOSES = {
    "case_01_low_density_2x2": "验证低密度预设运行图的资源可行性和能量结算。",
    "case_02_current_3x3": "验证当前推荐的主线 3重3空基准方案。",
    "case_03_dense_4x4": "观察密集预设运行图下的资源约束压力。",
    "case_04_conflict_phase_3x3": "复现 2400s 相位附近的资源冲突风险。",
    "sens_01_empty_mass_2160": "测试较轻回空列质量对能耗和储能利用的影响。",
    "sens_02_empty_mass_4320": "测试较重回空列质量对能耗和储能利用的影响。",
    "sens_03_storage_capacity_5000": "测试较小储能容量下的再生能量受限情况。",
    "sens_04_storage_capacity_40000": "测试较大储能容量对再生能量吸收的影响。",
}


FIELDS = [
    "experiment_group",
    "case_id",
    "case_name",
    "purpose",
    "heavy_count",
    "empty_count",
    "phase_s",
    "heavy_headway_s",
    "empty_headway_s",
    "empty_mass_tons",
    "battery_capacity_kwh",
    "baseline_feasible",
    "optimized_feasible",
    "optimized_resource_conflicts",
    "pareto_count",
    "pareto_basis",
    "grid_kwh",
    "wasted_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "battery_charge_limited_kwh",
    "recovered_or_stored_ratio",
    "final_soc_kwh",
    "time_space_node_count",
    "time_space_arc_count",
    "output_dir",
]


def parse_case_args(case: dict[str, Any], output_dir: Path, data_dir: Path = Path("data") / "real_shuohuang"):
    """函数 parse_case_args：执行该模块中的相关处理逻辑。"""
    argv = [
        "--input",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--energy-scenario",
        "storage_no_direct",
        "--objective-mode",
        "balanced",
        "--search-method",
        "nsga2",
        "--population-size",
        "2",
        "--generations",
        "1",
        "--heavy-count",
        str(case["heavy_count"]),
        "--empty-count",
        str(case["empty_count"]),
        "--baseline-heavy-headway-s",
        str(case["heavy_headway_s"]),
        "--baseline-empty-headway-s",
        str(case["empty_headway_s"]),
        "--baseline-phase-s",
        str(case["phase_s"]),
        "--min-depart-gap-s",
        "300",
        "--settlement-step-s",
        "20",
    ]
    if case.get("empty_mass_tons") is not None:
        argv.extend(["--empty-mass-tons", str(case["empty_mass_tons"])])
    if case.get("battery_capacity_kwh") is not None:
        argv.extend(["--battery-capacity-kwh", str(case["battery_capacity_kwh"])])
    return build_dispatch_parser().parse_args(argv)


def row_from_summary(case: dict[str, Any], summary: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """函数 row_from_summary：执行该模块中的相关处理逻辑。"""
    optimized = summary["optimized"]
    pareto = summary.get("pareto_candidates", {})
    return {
        "experiment_group": case["experiment_group"],
        "case_id": case["case_id"],
        "case_name": CASE_LABELS[case["case_id"]],
        "purpose": CASE_PURPOSES[case["case_id"]],
        "heavy_count": case["heavy_count"],
        "empty_count": case["empty_count"],
        "phase_s": case["phase_s"],
        "heavy_headway_s": case["heavy_headway_s"],
        "empty_headway_s": case["empty_headway_s"],
        "empty_mass_tons": case.get("empty_mass_tons", ""),
        "battery_capacity_kwh": case.get("battery_capacity_kwh", ""),
        "baseline_feasible": summary["baseline"]["feasible"],
        "optimized_feasible": optimized["feasible"],
        "optimized_resource_conflicts": optimized["resource_conflict_count"],
        "pareto_count": pareto.get("count", 0),
        "pareto_basis": pareto.get("basis", ""),
        "grid_kwh": optimized["grid_kwh"],
        "wasted_kwh": optimized["wasted_kwh"],
        "battery_charge_kwh": optimized["battery_charge_kwh"],
        "battery_discharge_kwh": optimized["battery_discharge_kwh"],
        "battery_charge_limited_kwh": optimized["battery_charge_limited_kwh"],
        "recovered_or_stored_ratio": optimized["recovered_or_stored_ratio"],
        "final_soc_kwh": optimized["final_soc_kwh"],
        "time_space_node_count": optimized["time_space_node_count"],
        "time_space_arc_count": optimized["time_space_arc_count"],
        "output_dir": str(output_dir),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any, digits: int = 3) -> str:
    """函数 fmt：执行该模块中的相关处理逻辑。"""
    if value == "" or value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def write_figures(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    """函数 write_figures：执行该模块中的相关处理逻辑。"""
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    labels = [row["case_id"] for row in rows]

    energy_path = fig_dir / "case_energy_comparison.png"
    x = range(len(rows))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar([i - 0.2 for i in x], [float(row["wasted_kwh"]) for row in rows], width=0.4, label="wasted_kwh")
    ax.bar([i + 0.2 for i in x], [float(row["battery_charge_kwh"]) for row in rows], width=0.4, label="battery_charge_kwh")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("kWh")
    ax.set_title("Simulation Case Energy Comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(energy_path, dpi=150)
    plt.close(fig)

    feasible_path = fig_dir / "case_feasibility_and_conflicts.png"
    fig, ax = plt.subplots(figsize=(12, 4))
    colors = ["#2ca02c" if row["optimized_feasible"] else "#d62728" for row in rows]
    ax.bar(labels, [int(row["optimized_resource_conflicts"]) for row in rows], color=colors)
    ax.set_ylabel("Resource conflict count")
    ax.set_title("Optimized Feasibility and Resource Conflicts")
    ax.tick_params(axis="x", labelrotation=35, labelsize=8)
    fig.tight_layout()
    fig.savefig(feasible_path, dpi=150)
    plt.close(fig)

    return {
        "energy_comparison": str(energy_path),
        "feasibility_conflicts": str(feasible_path),
    }


def _write_report_legacy_mojibake(output_dir: Path, rows: list[dict[str, Any]], figures: dict[str, str]) -> None:
    """函数 _write_report_legacy_mojibake：执行该模块中的相关处理逻辑。"""
    report = output_dir / "SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md"
    case_rows = [row for row in rows if row["experiment_group"] == "preset_timetable_case"]
    sensitivity_rows = [row for row in rows if row["experiment_group"] != "preset_timetable_case"]
    feasible_count = sum(1 for row in rows if row["optimized_feasible"])

    lines = [
        "# 拟真测试结果解读报告",
        "",
        "本报告汇总当前项目在真实朔黄主线数据和明确预设参数下的拟真测试结果，包含多组预设运行图 case 与关键参数敏感性测试。",
        "",
        "## 一、实验输入口径",
        "",
        "- 线路范围：线路图 1、2、3 覆盖的朔黄主线。",
        "- 能量规则：上下行不能直发直用，再生能量只能在储能可用区段进入储能后再利用。",
        "- 运行图：正式运行图尚未到位，当前使用预设发车间隔、重空列相位和列车数量构造拟真 case。",
        "- 储能、牵引/制动、阻力和部分能力参数：采用明确标记的预设值或场景覆盖值。",
        "- 智能电表：用于代表性验证覆盖，不作为全量统计结论。",
        "",
        "## 二、多组预设运行图 Case",
        "",
        "| Case | 含义 | 重车/空车 | 相位(s) | 可行 | 冲突数 | 浪费能量(kWh) | 储能充电(kWh) | Pareto |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in case_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['case_name']} | {row['heavy_count']}/{row['empty_count']} | "
            f"{row['phase_s']} | {fmt(row['optimized_feasible'])} | {row['optimized_resource_conflicts']} | "
            f"{fmt(row['wasted_kwh'])} | {fmt(row['battery_charge_kwh'])} | "
            f"{row['pareto_count']} ({row['pareto_basis']}) |"
        )

    lines.extend(
        [
            "",
            "解读：",
            "",
            "- `case_02_current_3x3` 是当前推荐默认拟真方案，调度可行且资源冲突为 0。",
            "- `case_04_conflict_phase_3x3` 用 2400s 相位复现冲突，用于说明将默认合成 baseline 调整为 3300/2700/2600 的必要性。",
            "- 密集 case 用于观察约束压力，不代表正式运行图。",
            "",
            "## 三、敏感性测试",
            "",
            "| Case | 测试项 | 空车质量(t) | 储能容量(kWh) | 可行 | 浪费能量(kWh) | 储能充电(kWh) | 受限充电(kWh) | 回收/储能比例 |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sensitivity_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['case_name']} | {fmt(row['empty_mass_tons'])} | "
            f"{fmt(row['battery_capacity_kwh'])} | {fmt(row['optimized_feasible'])} | "
            f"{fmt(row['wasted_kwh'])} | {fmt(row['battery_charge_kwh'])} | "
            f"{fmt(row['battery_charge_limited_kwh'])} | {fmt(float(row['recovered_or_stored_ratio']) * 100)}% |"
        )

    empty_mass_rows = sorted(
        (row for row in sensitivity_rows if row["experiment_group"] == "empty_mass_sensitivity"),
        key=lambda row: float(row["empty_mass_tons"]),
    )
    if len(empty_mass_rows) >= 2:
        light, heavy = empty_mass_rows[0], empty_mass_rows[-1]
        empty_mass_explanation = (
            f"- 修复功率序列跨场景缓存复用问题后，空车质量从 {fmt(light['empty_mass_tons'])} t "
            f"增加到 {fmt(heavy['empty_mass_tons'])} t 时，电网取电从 {fmt(light['grid_kwh'])} kWh "
            f"增加到 {fmt(heavy['grid_kwh'])} kWh，储能放电从 {fmt(light['battery_discharge_kwh'])} kWh "
            f"增加到 {fmt(heavy['battery_discharge_kwh'])} kWh，质量敏感性已经能够被模型识别。"
        )
        empty_mass_cache_note = (
            "- 原先结果不明显的主要原因是 `PowerSeriesCache` 使用模块级缓存并以 `id(self)` 为键；"
            "批量场景中对象 ID 可能被复用，导致后续质量场景读取旧功率序列。现已改为实例私有缓存。"
        )
    else:
        empty_mass_explanation = "- 当前没有足够的空车质量敏感性场景用于比较。"
        empty_mass_cache_note = ""

    lines.extend(
        [
            "",
            "解读：",
            "",
            empty_mass_explanation,
            empty_mass_cache_note,
            "- 空车质量变化主要用于观察回空列牵引需求变化，目前属于场景假设，不是实测质量结论。",
            "- 储能容量变化用于观察容量占位值对再生能量吸收的影响；真实储能设备参数到位后应替换并复跑。",
            "- 当前输出的 kWh 数值可用于比较趋势，不应直接作为最终节能量。",
            "",
            "## 四、汇总判断",
            "",
            f"- 本批次共运行 {len(rows)} 个实验，其中优化方案可行 {feasible_count} 个。",
            "- 当前算法已经可以跑拟真测试，并能输出约束检查、能量结算、候选方案和报告产物。",
            "- 运行图优化模块另有 `outputs/timetable_optimizer_nsga2/pareto_candidates.csv`，当前默认流程可输出 30 个运行图 Pareto 候选。",
            "- 调度侧如果没有鲁棒可行候选，会导出 `nominal_feasible_fallback`，表示名义可行候选，不应误读为扰动鲁棒方案。",
            "",
            "## 五、图表",
            "",
            f"- 能量对比图：`{figures['energy_comparison']}`",
            f"- 可行性与冲突图：`{figures['feasibility_conflicts']}`",
            "",
            "## 六、输出文件",
            "",
            "- `simulation_experiment_summary.csv`：实验汇总表。",
            "- `simulation_experiment_summary.json`：机器可读汇总。",
            "- `SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md`：本报告。",
            "- `cases/*/`：每个 case 的完整调度拟真输出。",
            "",
            "## 七、可信边界",
            "",
            "- 可以用于阶段汇报：说明真实数据接入、拟真流程、约束检查和参数敏感性。",
            "- 不可用于最终工程结论：正式运行图、真实储能设备、牵引/制动曲线、阻力参数仍需替换预设值。",
            "",
        ]
    )
    report.write_text("\n".join(lines), encoding="utf-8")


def write_report(output_dir: Path, rows: list[dict[str, Any]], figures: dict[str, str]) -> None:
    """Write a data-driven Chinese report without hard-coded feasibility claims."""

    report = output_dir / "SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md"
    case_rows = [row for row in rows if row["experiment_group"] == "preset_timetable_case"]
    sensitivity_rows = [row for row in rows if row["experiment_group"] != "preset_timetable_case"]
    feasible_count = sum(bool(row["optimized_feasible"]) for row in rows)
    lines = [
        "# 拟真与敏感性实验结果解读报告",
        "",
        "本报告基于朔黄主线真实线路数据和明确标注的预设参数生成。正式运行图、正式储能设备参数及部分车辆动力学参数到位后，应使用真实值重新运行。",
        "",
        "## 一、实验口径",
        "",
        "- 线路范围：线路图 1、2、3 覆盖的朔黄主线。",
        "- 能量规则：上下行不直发直用；再生能量只能在储能区段先充电、后按独立 SOC 放电。",
        "- 运行图：当前使用预设发车间隔、重空列相位和列车数量。",
        "- 优化输出：优先采用鲁棒可行方案；不存在时回退到名义可行方案，并在结果中标记。",
        "",
        "## 二、预设运行图 Case",
        "",
        "| Case | 含义 | 重车/空车 | 相位(s) | 可行 | 冲突数 | 弃能(kWh) | 购电(kWh) | 储能充/放电(kWh) | Pareto |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in case_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['case_name']} | {row['heavy_count']}/{row['empty_count']} | "
            f"{row['phase_s']} | {'是' if row['optimized_feasible'] else '否'} | {row['optimized_resource_conflicts']} | "
            f"{fmt(row['wasted_kwh'])} | {fmt(row['grid_kwh'])} | "
            f"{fmt(row['battery_charge_kwh'])}/{fmt(row['battery_discharge_kwh'])} | "
            f"{row['pareto_count']} ({row['pareto_basis']}) |"
        )

    lines.extend(
        [
            "",
            "## 三、参数敏感性",
            "",
            "| Case | 测试项 | 空车质量(t) | 储能容量(kWh) | 可行 | 弃能(kWh) | 购电(kWh) | 储能充/放电(kWh) | 最终 SOC(kWh) |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sensitivity_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['case_name']} | {fmt(row['empty_mass_tons'])} | "
            f"{fmt(row['battery_capacity_kwh'])} | {'是' if row['optimized_feasible'] else '否'} | "
            f"{fmt(row['wasted_kwh'])} | {fmt(row['grid_kwh'])} | "
            f"{fmt(row['battery_charge_kwh'])}/{fmt(row['battery_discharge_kwh'])} | {fmt(row['final_soc_kwh'])} |"
        )

    lines.extend(
        [
            "",
            "## 四、结果判断",
            "",
            f"- 共运行 {len(rows)} 组实验，其中优化结果可行 {feasible_count} 组。",
            "- 可行性必须结合 `optimized_resource_conflicts` 和 Pareto 基础字段判断，不能仅按能耗大小判断。",
            "- 空车质量与储能容量实验用于确认参数变化能够传递到能量结果，不代表正式工程参数结论。",
            "- `nominal_feasible_fallback` 表示名义场景可行，不代表所有扰动场景均可行。",
            "",
            "## 五、输出",
            "",
            f"- 能量对比图：`{figures['energy_comparison']}`",
            f"- 可行性与冲突图：`{figures['feasibility_conflicts']}`",
            "- 汇总表：`simulation_experiment_summary.csv`",
            "- 机器可读汇总：`simulation_experiment_summary.json`",
            "- 各 case 完整结果：`cases/*/`",
            "",
        ]
    )
    report.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Run Shuohuang simulation and sensitivity experiment cases.")
    parser.add_argument("--data-dir", type=Path, default=Path("data") / "real_shuohuang")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in CASE_DEFINITIONS:
        output_dir = output_root / "cases" / case["case_id"]
        case_args = parse_case_args(case, output_dir, args.data_dir)
        print(f">>> Running {case['case_id']} - {CASE_LABELS[case['case_id']]}")
        summary = run_case(case_args)
        rows.append(row_from_summary(case, summary, output_dir))

    write_csv(output_root / "simulation_experiment_summary.csv", rows)
    (output_root / "simulation_experiment_summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    figures = write_figures(rows, output_root)
    write_report(output_root, rows, figures)

    print(
        json.dumps(
            {
                "data_dir": str(args.data_dir),
                "output_dir": str(output_root),
                "case_count": len(rows),
                "feasible_count": sum(1 for row in rows if row["optimized_feasible"]),
                "report": str(output_root / "SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md"),
                "summary_csv": str(output_root / "simulation_experiment_summary.csv"),
                "figures": figures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
