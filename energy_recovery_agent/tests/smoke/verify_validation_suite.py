"""验证技术方案 4.1.2.4 四类验证场景（场景 1–4）。

本用例覆盖：
1. 场景 1–3 按方案表给出"对比基准 vs 优化方案"，关键评估指标齐全；
2. 场景 1：现行发车计划 vs 基于 NSGA-II 的能耗最小化方案，两方案在同一权重口径下可比；
3. 场景 2：现行空列调配（割裂）必须如实报出联合到发间隔违反，优化方案必须为 0；
4. 场景 3：割裂规划方案 vs Pareto 协同方案，协同方案必须可行且 Pareto 前沿非空；
5. 割裂（decoupled）与协同（integrated）模式在候选层确有差异：割裂不修复联合间隔但记账；
6. 场景 4 按项目边界只登记状态（`external_project`，未实现）；
7. 产物齐全、表头一致、summary.json 结构自洽。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import (
    COORDINATION_MODE_DECOUPLED,
    COORDINATION_MODE_INTEGRATED,
    _build_candidate,
    load_he_input_template,
)
from heavy_empty_validation_suite import (
    SCENARIO_BASELINE_LABEL,
    SCENARIO_NAMES,
    SCENARIO_OPTIMIZED_LABEL,
    run_validation_suite,
    scenario_4_status,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("validation")
SCENARIO_ID = "capacity_surplus_demo"

SCENARIO_KEYS = (
    "scenario_1_heavy_energy",
    "scenario_2_empty_dispatch",
    "scenario_3_coordination",
)

REQUIRED_METRICS = {
    "scenario_1_heavy_energy": {"total_energy_kwh", "energy_per_1000_ton_km"},
    "scenario_2_empty_dispatch": {"empty_travel_distance_km", "connection_wait_s"},
    "scenario_3_coordination": {"total_energy_kwh", "throughput_ton_km", "virtual_trainset_count"},
}


def _small_bundle(bundle):
    """缩小搜索规模，保持场景结构不变。"""
    return replace(
        bundle,
        scenarios={
            name: replace(scenario, population_size=4, generations=2)
            for name, scenario in bundle.scenarios.items()
        },
    )


def test_coordination_modes_differ_at_candidate_level(bundle) -> None:
    """割裂模式不修复联合到发间隔，但必须如实记账；协同模式修复且无违反。"""

    scenario = bundle.scenarios[SCENARIO_ID]
    integrated = _build_candidate(
        bundle, scenario, "MODE_INT", 0, scenario.min_headway_s,
        coordination_mode=COORDINATION_MODE_INTEGRATED,
    )
    decoupled = _build_candidate(
        bundle, scenario, "MODE_DEC", 0, scenario.min_headway_s,
        coordination_mode=COORDINATION_MODE_DECOUPLED,
    )
    if integrated.arrival_headway_violation_count != 0 or not integrated.feasible:
        raise AssertionError(f"协同模式不应有联合间隔违反：{integrated.diagnostics}")
    if decoupled.arrival_headway_violation_count <= 0:
        raise AssertionError("割裂模式必须如实报出联合到发间隔违反")
    if decoupled.feasible:
        raise AssertionError("割裂模式存在联合间隔违反时必须不可行")
    if not any("decoupled" in message for message in decoupled.diagnostics):
        raise AssertionError(f"割裂模式应给出明确诊断：{decoupled.diagnostics[:3]}")
    integrated_repairs = [
        arc for arc in integrated.arcs
        if arc.source == "arrival_departure_headway_repair"
    ]
    decoupled_repairs = [
        arc for arc in decoupled.arcs
        if arc.source == "arrival_departure_headway_repair"
    ]
    if not integrated_repairs:
        raise AssertionError("协同模式应有联合间隔修复等待弧")
    if decoupled_repairs:
        raise AssertionError("割裂模式不应产生联合间隔修复等待弧")
    if integrated.coordination_mode != COORDINATION_MODE_INTEGRATED:
        raise AssertionError("候选未记录协同模式")


def test_scenario_table_matches_scheme(summary) -> None:
    """场景编号、名称与基准/优化方案标签必须与方案 4.1.2.4 表一致。"""

    for key in SCENARIO_KEYS:
        if key not in summary["scenarios"]:
            raise AssertionError(f"缺少场景 {key}")
        entry = summary["scenarios"][key]
        if entry["scenario_name"] != SCENARIO_NAMES[key]:
            raise AssertionError(f"{key} 场景名不一致：{entry['scenario_name']}")
        if entry["baseline_label"] != SCENARIO_BASELINE_LABEL[key]:
            raise AssertionError(f"{key} 对比基准标签不一致")
        if entry["optimized_label"] != SCENARIO_OPTIMIZED_LABEL[key]:
            raise AssertionError(f"{key} 优化方案标签不一致")
        for plan in ("baseline", "optimized"):
            metrics = entry[plan]
            missing = REQUIRED_METRICS[key] - set(metrics)
            if missing:
                raise AssertionError(f"{key}/{plan} 缺少关键指标：{sorted(missing)}")


def test_scenario_2_and_3_show_coordination_benefit(summary) -> None:
    """场景 2/3 的优化方案必须消除联合间隔违反，且协同方案 Pareto 前沿非空。"""

    scenario_2 = summary["scenarios"]["scenario_2_empty_dispatch"]
    if scenario_2["baseline"]["arrival_headway_violation_count"] <= 0:
        raise AssertionError("场景2 基准（现行空列调配）必须报出联合间隔违反")
    if scenario_2["optimized"]["arrival_headway_violation_count"] != 0:
        raise AssertionError("场景2 优化方案不得有联合间隔违反")

    scenario_3 = summary["scenarios"]["scenario_3_coordination"]
    baseline = scenario_3["baseline"]
    optimized = scenario_3["optimized"]
    if baseline["arrival_headway_violation_count"] <= 0:
        raise AssertionError("场景3 割裂规划方案必须报出联合间隔违反")
    if optimized["arrival_headway_violation_count"] != 0 or not optimized["feasible"]:
        raise AssertionError("场景3 Pareto 协同方案必须可行且无联合间隔违反")
    if optimized["pareto_candidate_count"] <= 0:
        raise AssertionError("场景3 协同方案必须有非空 Pareto 前沿")
    if baseline["pareto_candidate_count"] > 0:
        raise AssertionError("场景3 割裂方案不应产生 Pareto 前沿（不可行）")
    for metric in REQUIRED_METRICS["scenario_3_coordination"]:
        if metric not in baseline or metric not in optimized:
            raise AssertionError(f"场景3 缺少方案表指标 {metric}")


def test_scenario_1_is_comparable(summary) -> None:
    """场景 1 两方案必须在同一权重口径下可比，且显式记录原型边界。"""

    scenario_1 = summary["scenarios"]["scenario_1_heavy_energy"]
    baseline = scenario_1["baseline"]
    optimized = scenario_1["optimized"]
    # 同一把尺子：两方案的货物周转量必须一致（同一批运输需求）。
    if baseline["throughput_ton_km"] != optimized["throughput_ton_km"]:
        raise AssertionError("场景1 两方案的货物周转量应一致，说明评价口径不同")
    if optimized["candidate_count"] <= 0:
        raise AssertionError("场景1 优化方案应记录搜索候选数")
    interpretation = summary["interpretation"]["scenario_1_heavy_energy"]
    if "原型" not in interpretation:
        raise AssertionError("场景1 必须显式说明原型模型边界，不得夸大能耗差异")


def test_scenario_4_is_status_only() -> None:
    """场景 4 必须只登记状态，不实现。"""

    status = scenario_4_status()
    if status["implemented"] is not False:
        raise AssertionError("场景4 不应被实现")
    if status["status"] != "external_project":
        raise AssertionError(f"场景4 状态应为 external_project，实际 {status['status']}")
    if status["owner"] != "single_train_energy_optimization":
        raise AssertionError("场景4 归属项目不正确")
    if status["technical_clause"] != "4.1.2.4":
        raise AssertionError("场景4 未标注方案条款")


def test_outputs_are_written_and_consistent(summary) -> None:
    """产物齐全、表头一致、summary.json 自洽。"""

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    expected_files = {
        "scenario_1_heavy_energy.csv",
        "scenario_2_empty_dispatch.csv",
        "scenario_3_coordination.csv",
        "scenario_4_special_section_status.json",
        "validation_summary.json",
        "VALIDATION_REPORT.md",
    }
    for filename in expected_files:
        if not (OUTPUT_ROOT / filename).is_file():
            raise AssertionError(f"缺少验证产物：{filename}")

    header = {
        "scenario_id", "scenario_name", "metric", "unit",
        "baseline_label", "baseline_value", "optimized_label", "optimized_value", "delta",
    }
    for key in SCENARIO_KEYS:
        filename = summary["scenarios"][key]["output"]
        with (OUTPUT_ROOT / filename).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise AssertionError(f"{filename} 为空")
        if set(rows[0]) != header:
            raise AssertionError(f"{filename} 表头不一致：{sorted(set(rows[0]) ^ header)}")
        metrics_in_csv = {row["metric"] for row in rows}
        missing = REQUIRED_METRICS[key] - metrics_in_csv
        if missing:
            raise AssertionError(f"{filename} 缺少关键指标行：{sorted(missing)}")

    written = json.loads((OUTPUT_ROOT / "validation_summary.json").read_text(encoding="utf-8"))
    if written["technical_clause"] != "4.1.2.4":
        raise AssertionError("summary.json 未标注方案条款")
    if written["scenario_4"]["status"] != "external_project":
        raise AssertionError("summary.json 的场景4状态不正确")
    if set(written["scenarios"]) != set(SCENARIO_KEYS):
        raise AssertionError("summary.json 场景集合不一致")
    status = json.loads(
        (OUTPUT_ROOT / "scenario_4_special_section_status.json").read_text(encoding="utf-8")
    )
    if status != written["scenario_4"]:
        raise AssertionError("场景4状态文件与 summary.json 不一致")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""

    bundle = load_he_input_template(TEMPLATE)
    test_coordination_modes_differ_at_candidate_level(bundle)
    test_scenario_4_is_status_only()
    small = _small_bundle(bundle)
    summary = run_validation_suite(small, OUTPUT_ROOT, scenario_id=SCENARIO_ID)
    test_scenario_table_matches_scheme(summary)
    test_scenario_2_and_3_show_coordination_benefit(summary)
    test_scenario_1_is_comparable(summary)
    test_outputs_are_written_and_consistent(summary)
    print("validation suite verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
