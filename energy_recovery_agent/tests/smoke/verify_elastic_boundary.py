"""验证高敏区段软惩罚/弹性边界（技术方案 4.2.1.2(1)）。

覆盖：
1. 默认模板不声明弹性边界 ⇒ 行为与既有完全一致（软惩罚 0、无弹性放宽）；
2. ``SectionElasticity`` 与 ``_section_elasticity_map`` 的校验（倍率下界、空键、重复键）；
3. 声明弹性边界后：名义能力外的占用不再判硬冲突，转为软惩罚并使候选可行；
4. 弹性边界不越界：倍率为 1.0 时仍按硬冲突处理；
5. ``corridor_capacity_rows`` 的利用率/超容量/风险自洽；
6. 产物齐全、``summary.json`` 含弹性边界登记项。
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
    SectionElasticity,
    _build_candidate,
    _section_elasticity_map,
    _validate_he_input_bundle,
    corridor_capacity_rows,
    load_he_input_template,
    optimize_heavy_empty_network,
    write_optimization_outputs,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("elastic_boundary")
SURPLUS = "capacity_surplus_demo"
TIGHT = "capacity_tight_demo"
SECTION_KEY = "神池南->黄骅港"


def _small(bundle):
    return replace(
        bundle,
        scenarios={
            name: replace(scenario, population_size=4, generations=2)
            for name, scenario in bundle.scenarios.items()
        },
    )


def test_default_declares_no_elasticity(bundle) -> None:
    """默认模板不声明弹性边界，行为与既有一致。"""

    if bundle.section_elasticity:
        raise AssertionError(f"默认模板不应声明弹性边界，实际 {bundle.section_elasticity}")
    scenario = bundle.scenarios[SURPLUS]
    candidate = _build_candidate(bundle, scenario, "DEFAULT", 0, scenario.min_headway_s)
    if candidate.elastic_soft_penalty != 0.0 or candidate.elastic_relief_count != 0:
        raise AssertionError("未声明弹性边界时不应产生软惩罚或弹性放宽")


def test_section_elasticity_validation(bundle) -> None:
    """弹性边界声明的校验。"""

    try:
        SectionElasticity(section_key=SECTION_KEY, capacity_multiplier=0.5)
    except ValueError:
        pass
    else:
        raise AssertionError("容量倍率小于 1.0 应被拒绝")
    try:
        SectionElasticity(section_key="")
    except ValueError:
        pass
    else:
        raise AssertionError("空 section_key 应被拒绝")

    try:
        _section_elasticity_map(
            (
                SectionElasticity(section_key=SECTION_KEY),
                SectionElasticity(section_key=SECTION_KEY, capacity_multiplier=1.5),
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("重复 section_key 应被拒绝")

    duplicate = replace(
        bundle,
        section_elasticity=(
            SectionElasticity(section_key=SECTION_KEY),
            SectionElasticity(section_key=SECTION_KEY, capacity_multiplier=1.5),
        ),
    )
    try:
        _validate_he_input_bundle(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("装载期应拒绝重复的弹性边界声明")


def test_elastic_boundary_relaxes_hard_conflict(bundle) -> None:
    """声明弹性边界后，名义能力外的占用转为软惩罚而非硬冲突。"""

    scenario = bundle.scenarios[TIGHT]
    if scenario.section_capacity_per_slot != 1:
        raise AssertionError("能力紧张场景的名义区段能力应为 1（本用例前提）")
    base = _build_candidate(bundle, scenario, "BASE", 0, scenario.min_headway_s)
    if base.conflict_count <= 0 or base.feasible:
        raise AssertionError("基准应出现区段能力冲突且不可行")

    elasticity = SectionElasticity(
        section_key=SECTION_KEY, capacity_multiplier=2.0, soft_penalty_weight=100.0
    )
    relaxed_bundle = replace(bundle, section_elasticity=(elasticity,))
    relaxed = _build_candidate(relaxed_bundle, scenario, "ELAS", 0, scenario.min_headway_s)
    if relaxed.conflict_count != 0 or not relaxed.feasible:
        raise AssertionError("弹性边界内不应判硬冲突，候选应可行")
    if relaxed.elastic_relief_count <= 0 or relaxed.elastic_soft_penalty <= 0.0:
        raise AssertionError("应记录弹性放宽次数与软惩罚")
    if relaxed.score >= base.score:
        raise AssertionError("软惩罚应显著低于 1e6 硬惩罚，综合分应更低")
    if not any("elastic boundary" in message for message in relaxed.diagnostics):
        raise AssertionError("应给出弹性边界诊断")

    same_capacity = replace(
        bundle,
        section_elasticity=(
            SectionElasticity(section_key=SECTION_KEY, capacity_multiplier=1.0, soft_penalty_weight=100.0),
        ),
    )
    strict = _build_candidate(same_capacity, scenario, "STRICT", 0, scenario.min_headway_s)
    if strict.conflict_count <= 0 or strict.feasible:
        raise AssertionError("倍率为 1.0 时不应放宽，仍应判硬冲突")


def test_corridor_capacity_rows_consistent(bundle) -> None:
    """走廊容量视图自洽。"""

    result = optimize_heavy_empty_network(_small(bundle), SURPLUS)
    rows = corridor_capacity_rows(result.best_candidate, result.scenario, bundle)
    if not rows:
        raise AssertionError("走廊容量明细不应为空")
    for row in rows:
        used = int(row["used_train_count"])
        capacity = int(row["capacity_per_slot"])
        if abs(float(row["utilization_ratio"]) - used / capacity) > 1e-6:
            raise AssertionError("利用率与占用/能力不一致")
        if bool(row["over_capacity"]) != (used > capacity):
            raise AssertionError("over_capacity 与占用/能力不一致")
        if not (0.0 <= float(row["congestion_risk_index"]) <= 1.0):
            raise AssertionError("走廊拥堵风险越界")


def test_outputs_written_and_consistent(bundle) -> None:
    """产物齐全、summary.json 含弹性边界登记项。"""

    small = _small(bundle)
    result = optimize_heavy_empty_network(small, SURPLUS)
    write_optimization_outputs(result, OUTPUT_ROOT, bundle=small)

    corridor_path = OUTPUT_ROOT / "corridor_capacity_utilization.csv"
    if not corridor_path.exists():
        raise AssertionError("缺少 corridor_capacity_utilization.csv")
    with corridor_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AssertionError("corridor_capacity_utilization.csv 不应为空")
    for key in ("section_key", "utilization_ratio", "congestion_risk_index", "over_capacity"):
        if key not in rows[0]:
            raise AssertionError(f"走廊容量明细缺少字段：{key}")

    summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    for key in (
        "declared_section_elasticity_count",
        "best_elastic_soft_penalty",
        "best_elastic_relief_count",
        "corridor_capacity_output",
        "max_corridor_congestion_risk_index",
        "over_capacity_corridor_period_count",
    ):
        if key not in summary:
            raise AssertionError(f"summary.json 缺少弹性边界登记项：{key}")


def main() -> int:
    bundle = load_he_input_template(TEMPLATE)
    test_default_declares_no_elasticity(bundle)
    test_section_elasticity_validation(bundle)
    test_elastic_boundary_relaxes_hard_conflict(bundle)
    test_corridor_capacity_rows_consistent(bundle)
    test_outputs_written_and_consistent(bundle)
    print("elastic boundary verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
