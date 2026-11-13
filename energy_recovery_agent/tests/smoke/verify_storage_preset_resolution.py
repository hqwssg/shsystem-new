# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from power_arm_electrical_limits import load_power_arm_electrical_limits
from run_dispatch_case import resolve_storage_eval_context, resolve_storage_preset_search, storage_comparison_scope
from rolling_optimizer import StorageEvalContext
from storage_presets import (
    StoragePresetScenario,
    apply_storage_ranges_to_power_arm_limits,
    default_storage_preset_library,
)
from train_simulator import BatteryStorageParameters


def _battery() -> BatteryStorageParameters:
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    return BatteryStorageParameters(
        capacity_kwh=20000.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.25,
        grid_price_per_kwh=0.65,
        max_charge_power_kW=10000.0,
        max_discharge_power_kW=10000.0,
    )


def test_unknown_ids_are_reported() -> None:
    """函数 test_unknown_ids_are_reported：执行该模块中的相关处理逻辑。"""
    args = argparse.Namespace(
        enable_storage_preset_search=True,
        disable_storage_preset_search=False,
        storage_preset_ids="virtual_two_section_base,not_a_real_preset,virtual_two_section_high_power",
    )
    resolved = resolve_storage_preset_search(args, _battery())
    if "not_a_real_preset" not in resolved.get("unknown_ids", []):
        raise AssertionError(f"expected unknown id tracking: {resolved}")
    if "virtual_two_section_base" not in resolved["preset_ids"]:
        raise AssertionError(resolved["preset_ids"])
    if "not_a_real_preset" in resolved["preset_ids"]:
        raise AssertionError("unknown id should not enter selected preset_ids")
    if "search_summary" not in resolved:
        raise AssertionError("search_summary must always be exported")


def test_all_unknown_ids_are_rejected_instead_of_falling_back() -> None:
    """函数 test_all_unknown_ids_are_rejected_instead_of_falling_back：执行该模块中的相关处理逻辑。"""
    args = argparse.Namespace(
        enable_storage_preset_search=True,
        disable_storage_preset_search=False,
        storage_preset_ids="not_a_real_preset,another_unknown_preset",
    )
    try:
        resolve_storage_preset_search(args, _battery())
    except ValueError as exc:
        if "did not contain any known preset IDs" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("all-invalid storage preset IDs silently fell back to a default")


def test_report_context_resolution_rejects_unknown_optimized_preset() -> None:
    """函数 test_report_context_resolution_rejects_unknown_optimized_preset：执行该模块中的相关处理逻辑。"""
    context = StorageEvalContext(
        preset_id="base",
        route=object(),
        heavy_cache=object(),
        empty_cache=object(),
        settlement_system=object(),
    )
    try:
        resolve_storage_eval_context({"base": context}, "missing", "base")
    except ValueError as exc:
        if "Unknown storage_preset_id" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError(
            "report context resolution silently substituted the baseline preset"
        )


def test_disable_keeps_single_preset() -> None:
    """函数 test_disable_keeps_single_preset：执行该模块中的相关处理逻辑。"""
    args = argparse.Namespace(
        enable_storage_preset_search=True,
        disable_storage_preset_search=True,
        storage_preset_ids="virtual_two_section_base,virtual_two_section_high_power",
    )
    resolved = resolve_storage_preset_search(args, _battery())
    if resolved["enabled"]:
        raise AssertionError("disable flag should turn search off")
    if len(resolved["preset_ids"]) != 1:
        raise AssertionError(resolved["preset_ids"])


def test_disable_preserves_explicit_fixed_preset() -> None:
    """函数 test_disable_preserves_explicit_fixed_preset：执行该模块中的相关处理逻辑。"""
    args = argparse.Namespace(
        enable_storage_preset_search=True,
        disable_storage_preset_search=True,
        storage_preset_ids="virtual_two_section_high_capacity",
    )
    resolved = resolve_storage_preset_search(args, _battery())
    if resolved["preset_ids"] != ["virtual_two_section_high_capacity"]:
        raise AssertionError(
            "disabled search ignored the explicitly selected fixed preset: "
            f"{resolved['preset_ids']}"
        )


def test_storage_comparison_scope_prevents_dispatch_only_misattribution() -> None:
    """函数 test_storage_comparison_scope_prevents_dispatch_only_misattribution：执行该模块中的相关处理逻辑。"""
    fixed = storage_comparison_scope("base", "base")
    if fixed["comparison_scope"] != "fixed_storage_dispatch_only":
        raise AssertionError(fixed)
    if fixed["dispatch_only_attribution_allowed"] is not True:
        raise AssertionError(fixed)

    changed = storage_comparison_scope("base", "high_power")
    if changed["comparison_scope"] != "joint_dispatch_and_virtual_storage_planning":
        raise AssertionError(changed)
    if changed["dispatch_only_attribution_allowed"] is not False:
        raise AssertionError(changed)
    if changed["storage_preset_changed"] is not True:
        raise AssertionError(changed)
    if "同时包含调度与储能规划变化" not in changed["comparison_note"]:
        raise AssertionError(changed)


def test_zero_base_storage_is_not_promoted_to_virtual_capacity() -> None:
    """函数 test_zero_base_storage_is_not_promoted_to_virtual_capacity：执行该模块中的相关处理逻辑。"""
    no_storage = BatteryStorageParameters(
        capacity_kwh=0.0,
        round_trip_efficiency=0.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=0.0,
        max_discharge_power_kW=0.0,
    )
    presets = default_storage_preset_library(no_storage)
    for preset in presets:
        if (
            preset.capacity_kwh != 0.0
            or preset.max_charge_power_kw != 0.0
            or preset.max_discharge_power_kw != 0.0
            or preset.round_trip_efficiency != 0.0
        ):
            raise AssertionError(f"zero storage was promoted by preset {preset}")


def test_search_settings_are_strict() -> None:
    """函数 test_search_settings_are_strict：执行该模块中的相关处理逻辑。"""
    base = {
        "enable_storage_preset_search": True,
        "disable_storage_preset_search": False,
        "storage_preset_ids": "virtual_two_section_base",
    }
    for override, expected_text in (
        ({"enable_storage_preset_search": "false"}, "enable_storage_preset_search"),
        ({"disable_storage_preset_search": 0}, "disable_storage_preset_search"),
        ({"storage_preset_ids": ["virtual_two_section_base"]}, "storage_preset_ids"),
    ):
        try:
            resolve_storage_preset_search(argparse.Namespace(**{**base, **override}), _battery())
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid storage search setting was accepted: {override!r}")


def test_adjacent_preset_sections_remain_distinct() -> None:
    """函数 test_adjacent_preset_sections_remain_distinct：执行该模块中的相关处理逻辑。"""
    power_arm_path = (
        Path(__file__).resolve().parents[2]
        / "data_templates"
        / "shuohuang_virtual"
        / "power_arm_intervals.csv"
    )
    limits = load_power_arm_electrical_limits(power_arm_path)
    _updated, sections = apply_storage_ranges_to_power_arm_limits(
        limits,
        power_arm_path,
        ((145.0, 164.0), (164.0, 200.7)),
    )
    ids = {item.storage_section_id for item in sections}
    bounds = {(item.min_km, item.max_km) for item in sections}
    if len(ids) != 2 or bounds != {(145.0, 164.0), (164.0, 200.7)}:
        raise AssertionError(f"adjacent storage sections were collapsed: {sections}")


def test_storage_preset_validation_and_normalization() -> None:
    """函数 test_storage_preset_validation_and_normalization：执行该模块中的相关处理逻辑。"""
    normalized = StoragePresetScenario(
        scenario_id="normalized",
        label="normalized",
        ranges_km=(("10", "2"), (10, 12), (11, 15)),
        capacity_kwh=1,
        max_charge_power_kw=1,
        max_discharge_power_kw=1,
        round_trip_efficiency=0.9,
    )
    if normalized.ranges_km != ((2.0, 10.0), (10.0, 15.0)):
        raise AssertionError(f"storage ranges were not normalized correctly: {normalized.ranges_km}")
    base = {
        "scenario_id": "invalid",
        "label": "invalid",
        "ranges_km": ((1, 2),),
        "capacity_kwh": 1,
        "max_charge_power_kw": 1,
        "max_discharge_power_kw": 1,
        "round_trip_efficiency": 0.9,
    }
    for override in (
        {"ranges_km": ((True, 2),)},
        {"ranges_km": ((1, float("inf")),)},
        {"ranges_km": ((1,),)},
        {"capacity_kwh": True},
        {"capacity_kwh": -1},
        {"max_charge_power_kw": -1},
        {"round_trip_efficiency": -0.1},
        {"round_trip_efficiency": 1.1},
        {"round_trip_efficiency": float("nan")},
    ):
        try:
            StoragePresetScenario(**{**base, **override})
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid storage preset was accepted: {override!r}")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_unknown_ids_are_reported()
    test_all_unknown_ids_are_rejected_instead_of_falling_back()
    test_report_context_resolution_rejects_unknown_optimized_preset()
    test_disable_keeps_single_preset()
    test_disable_preserves_explicit_fixed_preset()
    test_storage_comparison_scope_prevents_dispatch_only_misattribution()
    test_zero_base_storage_is_not_promoted_to_virtual_capacity()
    test_search_settings_are_strict()
    test_adjacent_preset_sections_remain_distinct()
    test_storage_preset_validation_and_normalization()
    print("storage preset resolution verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
