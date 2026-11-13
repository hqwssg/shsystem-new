# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from power_arm_lookup import (
    PowerArmInterval,
    _direction_matches,
    find_power_arm_id,
    load_power_arm_intervals,
)
from power_arm_electrical_limits import (
    PowerArmElectricalLimit,
    StorageSectionInterval,
    limit_for_power_arm,
    storage_boundary_kms,
    storage_section_for_position,
    storage_section_intervals_from_rows,
    time_window_capacity_kwh,
)
from timetable_energy_audit import find_power_section, load_power_sections


intervals = load_power_arm_intervals(Path("data") / "real_shuohuang" / "power_arm_intervals.csv")
assert all("黄大线" not in item.section_id for item in intervals)
assert find_power_arm_id(intervals, 150.0, "forward") == "PAI-041"
assert find_power_arm_id(intervals, 150.0, "reverse") == "PAI-010"
shared_interval = (PowerArmInterval("SHARED", "single", 0.0, 10.0, 0.0, 10.0),)
assert find_power_arm_id(shared_interval, 5.0, "forward") == "SHARED"
assert find_power_arm_id(shared_interval, 5.0, "reverse") == "SHARED"
unspecified_interval = (PowerArmInterval("UNSPECIFIED", "", 0.0, 10.0, 0.0, 10.0),)
assert find_power_arm_id(unspecified_interval, 5.0, "forward") == "UNSPECIFIED"
forward_boundary_intervals = (
    PowerArmInterval("F1", "down", 0.0, 10.0, 0.0, 10.0),
    PowerArmInterval("F2", "down", 10.0, 20.0, 10.0, 20.0),
)
reverse_boundary_intervals = (
    PowerArmInterval("R1", "up", 0.0, 10.0, 0.0, 10.0),
    PowerArmInterval("R2", "up", 10.0, 20.0, 10.0, 20.0),
)
assert find_power_arm_id(forward_boundary_intervals, 10.0, "forward") == "F2"
assert find_power_arm_id(reverse_boundary_intervals, 10.0, "reverse") == "R1"


def brute_force_power_arm_id(
    source_intervals: tuple[PowerArmInterval, ...],
    position: float,
    model_direction: str | None,
) -> str:
    """按优化前的全表扫描口径生成供电臂查询参考值。"""

    candidates = tuple(
        item for item in source_intervals if _direction_matches(model_direction, item.direction)
    )
    if not candidates:
        return ""
    normalized_direction = "" if model_direction is None else str(model_direction).strip().lower()
    for interval in candidates:
        if normalized_direction == "forward":
            contains = interval.min_km <= position < interval.max_km
        elif normalized_direction == "reverse":
            contains = interval.min_km < position <= interval.max_km
        else:
            contains = interval.min_km <= position <= interval.max_km
        if contains:
            return interval.section_id
    nearest = min(
        candidates,
        key=lambda item: min(abs(position - item.min_km), abs(position - item.max_km)),
    )
    if min(abs(position - nearest.min_km), abs(position - nearest.max_km)) <= 1e-6:
        return nearest.section_id
    return ""


synthetic_intervals = (
    *forward_boundary_intervals,
    *reverse_boundary_intervals,
    PowerArmInterval("SHARED_LONG", "single", 0.0, 25.5, 0.0, 25.5),
)
random_generator = random.Random(20260905)
lookup_points = [-0.000001, 0.0, 9.999999, 10.0, 20.0, 20.000001, 25.5]
lookup_points.extend(random_generator.uniform(-1.0, 27.0) for _ in range(2000))
for lookup_direction in (None, "forward", "reverse", "down", "up"):
    for lookup_position in lookup_points:
        indexed = find_power_arm_id(synthetic_intervals, lookup_position, lookup_direction)
        reference = brute_force_power_arm_id(
            synthetic_intervals,
            lookup_position,
            lookup_direction,
        )
        if indexed != reference:
            raise AssertionError(
                f"供电臂空间索引不等价: direction={lookup_direction}, "
                f"position={lookup_position}, indexed={indexed}, reference={reference}"
            )
assert storage_section_for_position(145.0).startswith("storage_section_1")
assert storage_section_for_position(164.0).startswith("storage_section_2")
assert storage_section_for_position(200.7).startswith("storage_section_2")
assert storage_section_for_position(200.7001) == ""
custom_storage = storage_section_intervals_from_rows(
    [
        {
            "direction": "下行",
            "start_km": "300.5",
            "end_km": "320.25",
            "storage_available": "是",
            "storage_section_id": "CUSTOM_STORAGE_ID",
            "storage_start_km": "305.25",
            "storage_end_km": "315.75",
        }
    ]
)
assert storage_boundary_kms(custom_storage, "forward") == (305.25, 315.75)
assert storage_section_for_position(310.0, custom_storage, "forward") == "CUSTOM_STORAGE_ID"
assert storage_section_for_position(302.0, custom_storage, "forward") == ""
assert storage_section_for_position(310.0, custom_storage, "reverse") == ""
for invalid_lookup_direction in ("sideways", "east", 123):
    for lookup in (
        lambda value=invalid_lookup_direction: storage_section_for_position(310.0, custom_storage, value),
        lambda value=invalid_lookup_direction: storage_boundary_kms(custom_storage, value),
    ):
        try:
            lookup()
        except ValueError as exc:
            assert "Direction" in str(exc)
        else:
            raise AssertionError(
                f"Invalid storage lookup direction was silently accepted: {invalid_lookup_direction!r}"
            )
# 直接构造接口对象时，必须与 CSV 导入使用相同的别名规范化规则。
for alias, expected, query_direction in (
    ("forward", "forward", "forward"),
    ("down", "forward", "forward"),
    ("下行", "forward", "forward"),
    ("reverse", "reverse", "reverse"),
    ("up", "reverse", "reverse"),
    ("上行", "reverse", "reverse"),
):
    direct_storage = (StorageSectionInterval("DIRECT", 400.0, 410.0, alias),)
    assert direct_storage[0].direction == expected
    assert storage_section_for_position(405.0, direct_storage, query_direction) == "DIRECT"
for invalid_direction in ("sideways", "east", 123):
    try:
        StorageSectionInterval("DIRECT_INVALID", 400.0, 410.0, invalid_direction)
    except ValueError as exc:
        assert "direction" in str(exc)
    else:
        raise AssertionError(f"Invalid direct storage direction was accepted: {invalid_direction!r}")
try:
    storage_section_intervals_from_rows(
        [
            {
                "direction": "down",
                "start_km": "0",
                "end_km": "10",
                "storage_available": "true",
                "storage_section_id": "A;B",
                "storage_start_km": "2",
                "storage_end_km": "8",
            }
        ]
    )
except ValueError as exc:
    assert "Overlapping storage sections" in str(exc)
else:
    raise AssertionError("Ambiguous co-located storage IDs were accepted.")
for bad_limit in (float("nan"), float("inf"), float("-inf"), -1.0):
    try:
        time_window_capacity_kwh(bad_limit, 0, 3600)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid electrical limit was accepted: {bad_limit!r}")
    try:
        PowerArmElectricalLimit(max_traction_supply_kw=bad_limit)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid PowerArmElectricalLimit was accepted: {bad_limit!r}")
for bad_limit in (True,):
    for constructor in (
        lambda: PowerArmElectricalLimit(max_traction_supply_kw=bad_limit),
        lambda: time_window_capacity_kwh(bad_limit, 0, 3600),
    ):
        try:
            constructor()
        except ValueError:
            pass
        else:
            raise AssertionError("Boolean electrical limit was accepted")
same_limit = PowerArmElectricalLimit(max_traction_supply_kw=100.0, max_regen_absorption_kw=100.0)
assert limit_for_power_arm("A;B", {"A": same_limit, "B": same_limit}) == same_limit
conflicting_limits = {
    "A": same_limit,
    "B": PowerArmElectricalLimit(
        max_traction_supply_kw=1000.0,
        max_regen_absorption_kw=1000.0,
    ),
}
for composite_id in ("A;B", "B;A"):
    try:
        limit_for_power_arm(composite_id, conflicting_limits)
    except ValueError as exc:
        assert "conflicting" in str(exc)
    else:
        raise AssertionError("Conflicting composite power-arm limits were order-dependently accepted")
for composite_id in ("A;MISSING", "MISSING;A", "MISSING_1;MISSING_2"):
    try:
        limit_for_power_arm(composite_id, {"A": same_limit})
    except ValueError as exc:
        assert "unconfigured" in str(exc)
    else:
        raise AssertionError("Unconfigured composite power-arm IDs were accepted")
try:
    PowerArmElectricalLimit(storage_available="false")
except ValueError as exc:
    assert "storage_available" in str(exc)
else:
    raise AssertionError("String storage_available was accepted by the runtime model")
for inconsistent_storage in (
    {"storage_available": True, "storage_section_id": ""},
    {"storage_available": False, "storage_section_id": "S"},
):
    try:
        PowerArmElectricalLimit(**inconsistent_storage)
    except ValueError as exc:
        assert "storage_section_id" in str(exc)
    else:
        raise AssertionError(f"inconsistent storage limit was accepted: {inconsistent_storage!r}")
for invalid_bound in (True, float("inf")):
    try:
        StorageSectionInterval("S", invalid_bound, 2.0)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid storage bound was accepted: {invalid_bound!r}")
try:
    storage_section_intervals_from_rows(
        [{"storage_available": "true", "storage_section_id": "NO_GEOMETRY"}]
    )
except ValueError as exc:
    assert "bounds" in str(exc)
else:
    raise AssertionError("Storage section without geometry was silently discarded")
for invalid_position in (True, float("inf")):
    for lookup in (
        lambda value=invalid_position: find_power_arm_id(intervals, value),
        lambda value=invalid_position: storage_section_for_position(value),
    ):
        try:
            lookup()
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid lookup position was accepted: {invalid_position!r}")
try:
    PowerArmInterval("P", "forward", 0.0, float("inf"), 0.0, float("inf"))
except ValueError:
    pass
else:
    raise AssertionError("Infinite power-arm interval was accepted")
with TemporaryDirectory() as temp_name:
    invalid_path = Path(temp_name) / "power_arms.csv"
    invalid_path.write_text(
        "section_id,road,direction,start_km,end_km\nP,Shuohuang,down,inf,10\n",
        encoding="utf-8",
    )
    try:
        load_power_arm_intervals(invalid_path)
    except ValueError as exc:
        assert "start_km" in str(exc)
    else:
        raise AssertionError("Infinite CSV power-arm bound was silently discarded")
    duplicate_limit_path = Path(temp_name) / "duplicate_limits.csv"
    duplicate_limit_path.write_text(
        "section_id,power_arm_id,road,direction,start_km,end_km,max_traction_supply_kw,max_regen_absorption_kw,max_grid_feedback_kw,storage_available,storage_section_id\n"
        "P1,A,Shuohuang,down,0,10,100,100,100,false,\n"
        "P2,A,Shuohuang,down,10,20,1000,1000,1000,false,\n",
        encoding="utf-8",
    )
    try:
        from power_arm_electrical_limits import load_power_arm_electrical_limits

        load_power_arm_electrical_limits(duplicate_limit_path)
    except ValueError as exc:
        assert "conflicting" in str(exc)
    else:
        raise AssertionError("Conflicting duplicate power-arm limits were silently overwritten")
    english_path = Path(temp_name) / "english_power_sections.csv"
    english_path.write_text(
        "section_id,road,direction,start_km,end_km,storage_available,storage_section_id\n"
        "P,Shuohuang,down,0,10,false,\n",
        encoding="utf-8",
    )
    english_sections = load_power_sections(english_path)
    assert len(english_sections) == 1 and english_sections[0].section_id == "P"
    assert find_power_section(english_sections, 1.0, 2.0, "forward").section_id == "P"
    assert find_power_section(english_sections, 1.0, 2.0, "reverse") is None
    invalid_review_path = Path(temp_name) / "invalid_review.csv"
    invalid_review_path.write_text(
        "section_id,road,direction,start_km,end_km,needs_manual_review,storage_available,storage_section_id\n"
        "P,Shuohuang,down,0,10,maybe,false,\n",
        encoding="utf-8",
    )
    try:
        load_power_sections(invalid_review_path)
    except ValueError as exc:
        assert "boolean" in str(exc)
    else:
        raise AssertionError("Invalid power-section review flag was accepted")
for start_s, end_s in ((0, 0), (10, 0), (0.5, 1), (0, float("inf")), (True, 2)):
    try:
        time_window_capacity_kwh(100.0, start_s, end_s)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid electrical time window was accepted: {start_s!r}, {end_s!r}")
assert abs(time_window_capacity_kwh(100.0, 0, 10) - (1000.0 / 3600.0)) < 1e-12
sections = load_power_sections(Path("data") / "real_shuohuang" / "power_arm_intervals.csv")
assert find_power_section(sections, 149.0, 151.0, "forward").section_id == "PAI-041"
assert find_power_section(sections, 151.0, 149.0, "reverse").section_id == "PAI-010"
print("power arm mainline and direction lookup passed")
