"""验证敏感性与稳健性情景集（技术方案 4.2.1.2(1)）。

覆盖：
1. 四个核心变量（发车间隔/大小列比例/组合站能力/需求扰动）的情景构造符合预期，且保护组合数量守恒；
2. 情景集产物齐全（scenarios/ranking/high_sensitivity_sections/summary/report）；
3. 敏感性排序覆盖全部变量×指标，并给出变量影响排序；
4. 高敏区段识别：能力紧张场景下走廊能力受限 ⇒ 至少识别出一个高敏区段并给出弹性边界建议；
5. 情景指标含单位运量能耗、能力利用率、平均追踪间隔、在站等待与走廊拥堵风险。
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

from heavy_empty_network_optimizer import load_he_input_template
from heavy_empty_sensitivity_suite import (
    SENSITIVITY_METRICS,
    SENSITIVITY_VARIABLES,
    build_variant_bundle,
    run_sensitivity_suite,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("sensitivity")
SURPLUS = "capacity_surplus_demo"
TIGHT = "capacity_tight_demo"


def _small(bundle):
    return replace(
        bundle,
        scenarios={
            name: replace(scenario, population_size=4, generations=2)
            for name, scenario in bundle.scenarios.items()
        },
    )


def test_variant_bundles(bundle) -> None:
    """四个变量的情景构造符合预期。"""

    scenario_id = SURPLUS
    base_headway = bundle.scenarios[scenario_id].min_headway_s

    slowed = build_variant_bundle(bundle, "headway", 0.5)
    if slowed.scenarios[scenario_id].min_headway_s != max(60, base_headway // 2):
        raise AssertionError("发车间隔倍率未生效")

    locked = {operation.demand_id for operation in bundle.formation_operations}
    small_ratio = build_variant_bundle(bundle, "formation_ratio", "small")
    small_by_id = {demand.demand_id: demand.train_type for demand in small_ratio.demands}
    for demand in bundle.demands:
        if demand.demand_id in locked:
            if small_by_id[demand.demand_id] != demand.train_type:
                raise AssertionError("组合数量守恒要求被引用需求的列型不变")
        else:
            service = small_ratio.service_types[small_by_id[demand.demand_id]]
            if service.consist_unit != 1:
                raise AssertionError("small 取向应把非组合需求切换为小列服务")

    doubled = build_variant_bundle(bundle, "combine_capacity", 2.0)
    for name, node in bundle.operation_nodes.items():
        if node.role == "combine_split":
            if doubled.operation_nodes[name].capacity_per_slot != node.capacity_per_slot * 2:
                raise AssertionError("组合站能力倍率未生效")

    halved = build_variant_bundle(bundle, "demand", 0.5)
    for before, after in zip(bundle.demands, halved.demands):
        if abs(after.cargo_tons - before.cargo_tons * 0.5) > 1e-9:
            raise AssertionError("需求吨位倍率未生效")


def _read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_suite_outputs(bundle) -> None:
    """情景集产物齐全、排序完整。"""

    summary = run_sensitivity_suite(_small(bundle), OUTPUT_ROOT, scenario_id=SURPLUS)
    for name in (
        "sensitivity_scenarios.csv",
        "sensitivity_ranking.csv",
        "high_sensitivity_sections.csv",
        "sensitivity_summary.json",
        "SENSITIVITY_REPORT.md",
    ):
        if not (OUTPUT_ROOT / name).exists():
            raise AssertionError(f"缺少产物：{name}")

    if summary["scenario_count"] != len(SENSITIVITY_VARIABLES) * 3:
        raise AssertionError("情景数应等于变量数 × 水平数")

    scenario_rows = _read_csv(OUTPUT_ROOT / "sensitivity_scenarios.csv")
    for row in scenario_rows:
        for metric in SENSITIVITY_METRICS:
            if metric not in row:
                raise AssertionError(f"情景指标缺少 {metric}")
    baseline_rows = [row for row in scenario_rows if row["is_baseline"] in {"True", "true", "1"}]
    if len(baseline_rows) != len(SENSITIVITY_VARIABLES):
        raise AssertionError("每个变量应恰有一个基准水平")

    ranking_rows = _read_csv(OUTPUT_ROOT / "sensitivity_ranking.csv")
    if len(ranking_rows) != len(SENSITIVITY_VARIABLES) * len(SENSITIVITY_METRICS):
        raise AssertionError("敏感性排序应覆盖全部变量×指标")

    payload = json.loads((OUTPUT_ROOT / "sensitivity_summary.json").read_text(encoding="utf-8"))
    for key in (
        "technical_clause",
        "variables",
        "sensitivity_ranking",
        "high_sensitivity_sections",
        "recommended_elasticity",
        "result_boundary",
    ):
        if key not in payload:
            raise AssertionError(f"sensitivity_summary.json 缺少 {key}")


def test_high_sensitivity_detection(bundle) -> None:
    """能力紧张场景应识别出高敏区段并给出弹性边界建议。"""

    summary = run_sensitivity_suite(
        _small(bundle), OUTPUT_ROOT / "tight", scenario_id=TIGHT
    )
    high = [row for row in summary["high_sensitivity_sections"] if row["is_high_sensitivity"]]
    if not high:
        raise AssertionError("能力紧张场景应识别出至少一个高敏区段")
    for row in high:
        if row["recommended_capacity_multiplier"] <= 1.0:
            raise AssertionError("高敏区段的弹性容量倍率应大于 1.0")
        if row["recommended_soft_penalty_weight"] <= 0.0:
            raise AssertionError("高敏区段的软惩罚系数应大于 0")


def main() -> int:
    bundle = load_he_input_template(TEMPLATE)
    test_variant_bundles(bundle)
    test_suite_outputs(bundle)
    test_high_sensitivity_detection(bundle)
    print("sensitivity suite verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
