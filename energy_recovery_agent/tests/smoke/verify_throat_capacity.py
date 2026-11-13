"""验证车站咽喉能力约束（技术方案 4.2.1.2(1) 约束体系新增"咽喉能力"）。

覆盖：
1. 默认模板不声明咽喉能力 ⇒ 行为与既有完全一致（无咽喉冲突，默认 no-op）；
2. ``ThroatCapacity`` 与 ``_throat_capacity_map`` / ``_validate_throat_capacity`` 的校验
   （空站名、能力下界、重复站、未知站）；
3. 声明过紧的咽喉能力（每时间片 1 次）⇒ 记为冲突并给出诊断；
4. 声明宽松的咽喉能力 ⇒ 不产生冲突；
5. ``summary.json`` 含咽喉能力登记项。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import (
    ThroatCapacity,
    _build_candidate,
    _throat_capacity_map,
    _validate_he_input_bundle,
    load_he_input_template,
    optimize_heavy_empty_network,
    write_optimization_outputs,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("throat_capacity")
SURPLUS = "capacity_surplus_demo"
ORIGIN = "神池南"
DESTINATION = "黄骅港"


def _small(bundle):
    return replace(
        bundle,
        scenarios={
            name: replace(scenario, population_size=4, generations=2)
            for name, scenario in bundle.scenarios.items()
        },
    )


def test_default_declares_no_throat(bundle) -> None:
    """默认模板不声明咽喉能力，行为与既有一致。"""

    if bundle.throat_capacity:
        raise AssertionError(f"默认模板不应声明咽喉能力，实际 {bundle.throat_capacity}")
    scenario = bundle.scenarios[SURPLUS]
    candidate = _build_candidate(bundle, scenario, "DEFAULT", 0, scenario.min_headway_s)
    if candidate.throat_conflict_count != 0:
        raise AssertionError("未声明咽喉能力时不应产生咽喉冲突")
    if any("throat capacity" in message for message in candidate.diagnostics):
        raise AssertionError("未声明咽喉能力时不应给出咽喉诊断")


def test_throat_capacity_validation(bundle) -> None:
    """咽喉能力声明的校验。"""

    try:
        ThroatCapacity(station_name="", capacity_per_slot=1)
    except ValueError:
        pass
    else:
        raise AssertionError("空 station_name 应被拒绝")
    try:
        ThroatCapacity(station_name=ORIGIN, capacity_per_slot=0)
    except ValueError:
        pass
    else:
        raise AssertionError("能力小于 1 应被拒绝")

    try:
        _throat_capacity_map(
            (
                ThroatCapacity(station_name=ORIGIN, capacity_per_slot=1),
                ThroatCapacity(station_name=ORIGIN, capacity_per_slot=2),
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("重复 station_name 应被拒绝")

    unknown = replace(
        bundle,
        throat_capacity=(ThroatCapacity(station_name="不存在的站", capacity_per_slot=1),),
    )
    try:
        _validate_he_input_bundle(unknown)
    except ValueError:
        pass
    else:
        raise AssertionError("装载期应拒绝未知车站的咽喉能力声明")


def test_tight_throat_records_conflict(bundle) -> None:
    """过紧的咽喉能力应记为冲突。"""

    scenario = bundle.scenarios[SURPLUS]
    base = _build_candidate(bundle, scenario, "BASE", 0, scenario.min_headway_s)
    tight = replace(
        bundle,
        throat_capacity=(ThroatCapacity(station_name=ORIGIN, capacity_per_slot=1),),
    )
    candidate = _build_candidate(tight, scenario, "TIGHT", 0, scenario.min_headway_s)
    if candidate.throat_conflict_count <= 0:
        raise AssertionError("每时间片 1 次的咽喉能力应产生咽喉冲突")
    if candidate.conflict_count <= base.conflict_count:
        raise AssertionError("咽喉冲突应计入总冲突数")
    if not any("throat capacity" in message for message in candidate.diagnostics):
        raise AssertionError("应给出咽喉能力诊断")


def test_loose_throat_no_conflict(bundle) -> None:
    """宽松的咽喉能力不应产生冲突。"""

    scenario = bundle.scenarios[SURPLUS]
    loose = replace(
        bundle,
        throat_capacity=(
            ThroatCapacity(station_name=ORIGIN, capacity_per_slot=99),
            ThroatCapacity(station_name=DESTINATION, capacity_per_slot=99),
        ),
    )
    candidate = _build_candidate(loose, scenario, "LOOSE", 0, scenario.min_headway_s)
    if candidate.throat_conflict_count != 0:
        raise AssertionError("宽松的咽喉能力不应产生咽喉冲突")


def test_outputs_written_and_consistent(bundle) -> None:
    """summary.json 含咽喉能力登记项。"""

    small = _small(bundle)
    result = optimize_heavy_empty_network(small, SURPLUS)
    write_optimization_outputs(result, OUTPUT_ROOT, bundle=small)
    summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    for key in ("declared_throat_capacity_count", "best_throat_conflict_count"):
        if key not in summary:
            raise AssertionError(f"summary.json 缺少咽喉能力登记项：{key}")


def main() -> int:
    bundle = load_he_input_template(TEMPLATE)
    test_default_declares_no_throat(bundle)
    test_throat_capacity_validation(bundle)
    test_tight_throat_records_conflict(bundle)
    test_loose_throat_no_conflict(bundle)
    test_outputs_written_and_consistent(bundle)
    print("throat capacity verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
