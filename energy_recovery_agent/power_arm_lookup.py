# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict
import csv
import math
import threading

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


DEFAULT_POWER_ARM_INTERVAL_PATH = Path("data") / "real_shuohuang" / "power_arm_intervals.csv"


_POWER_ARM_INDEX_CACHE_CAPACITY = 64
_POWER_ARM_INDEX_CACHE: "OrderedDict[int, Tuple[tuple[PowerArmInterval, ...], Dict[str, tuple]]]" = OrderedDict()
_POWER_ARM_INDEX_LOCK = threading.RLock()


@dataclass(frozen=True)
class PowerArmInterval:
    """类 PowerArmInterval：执行该模块中的相关处理逻辑。"""
    section_id: str
    direction: str
    start_km: float
    end_km: float
    min_km: float
    max_km: float

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        section_id = str(self.section_id).strip()
        if not section_id:
            raise ValueError("power-arm section_id must not be empty")
        numbers = {}
        for field_name in ("start_km", "end_km", "min_km", "max_km"):
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"power-arm {field_name} must be finite, got {raw_value!r}")
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"power-arm {field_name} must be finite, got {raw_value!r}") from exc
            if not math.isfinite(number):
                raise ValueError(f"power-arm {field_name} must be finite, got {raw_value!r}")
            numbers[field_name] = number
        if numbers["min_km"] > numbers["max_km"]:
            raise ValueError("power-arm min_km must not exceed max_km")
        if numbers["start_km"] == numbers["end_km"]:
            raise ValueError("power-arm start_km and end_km must be distinct")
        object.__setattr__(self, "section_id", section_id)
        for field_name, number in numbers.items():
            object.__setattr__(self, field_name, number)


MODEL_DIRECTION_TO_POWER_ARM = {
    "forward": "下行",
    "reverse": "上行",
}


def _is_mainline_road(value: Any) -> bool:
    """函数 _is_mainline_road：执行该模块中的相关处理逻辑。"""
    road = _clean(value)
    return not road or road in {"朔黄线", "Shuohuang", "shuohuang"}


def power_arm_direction_for_model(direction: str) -> str:
    """Map the model's forward/reverse direction to the mainline arm table."""

    return MODEL_DIRECTION_TO_POWER_ARM.get(_clean(direction).lower(), _clean(direction))


def _direction_matches(model_direction: Optional[str], arm_direction: str) -> bool:
    """函数 _direction_matches：执行该模块中的相关处理逻辑。"""
    if not model_direction:
        return True
    expected = power_arm_direction_for_model(model_direction)
    actual = _clean(arm_direction).lower()
    if actual in {"", "single", "both", "shared", "bidirectional"}:
        return True
    aliases = {
        "上行": {"上行", "up"},
        "下行": {"下行", "down"},
        "单线": {"单线", "single"},
    }
    return actual in {item.lower() for item in aliases.get(expected, {expected})}


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _optional_float(value: Any) -> Optional[float]:
    """函数 _optional_float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _required_csv_bound(value: Any, field_name: str, section_id: str) -> float:
    """函数 _required_csv_bound：执行该模块中的相关处理逻辑。"""
    number = _optional_float(value)
    if number is None:
        raise ValueError(
            f"power-arm {field_name} must be a finite number for section {section_id or '<unknown>'}"
        )
    return number


def load_power_arm_intervals(path: Path = DEFAULT_POWER_ARM_INTERVAL_PATH) -> tuple[PowerArmInterval, ...]:
    """函数 load_power_arm_intervals：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    if path.suffix.lower() == ".csv":
        rows: list[PowerArmInterval] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                if not _is_mainline_road(item.get("road") or item.get("line")):
                    continue
                section_id = _clean(item.get("section_id")) or _clean(item.get("power_arm_id"))
                start = _required_csv_bound(item.get("start_km"), "start_km", section_id)
                end = _required_csv_bound(item.get("end_km"), "end_km", section_id)
                if not section_id:
                    section_id = f"power_arm:{min(start, end):.6f}-{max(start, end):.6f}"
                rows.append(
                    PowerArmInterval(
                        section_id=section_id,
                        direction=_clean(item.get("direction")),
                        start_km=float(start),
                        end_km=float(end),
                        min_km=float(min(start, end)),
                        max_km=float(max(start, end)),
                    )
                )
        return tuple(sorted(rows, key=lambda item: (item.min_km, item.max_km, item.section_id)))
    if openpyxl is None:
        return ()
    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet_name = "供电臂连续区间表"
    if sheet_name not in workbook.sheetnames:
        return ()
    sheet = workbook[sheet_name]
    headers = [_clean(cell.value) for cell in sheet[1]]
    rows: list[PowerArmInterval] = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        item = {headers[idx]: value for idx, value in enumerate(row) if idx < len(headers)}
        if not _is_mainline_road(item.get("road") or item.get("line")):
            continue
        start = _optional_float(item.get("start_km"))
        end = _optional_float(item.get("end_km"))
        if start is None or end is None:
            continue
        section_id = _clean(item.get("section_id")) or _clean(item.get("power_arm_id"))
        if not section_id:
            section_id = f"power_arm:{min(start, end):.6f}-{max(start, end):.6f}"
        rows.append(
            PowerArmInterval(
                section_id=section_id,
                direction=_clean(item.get("direction")),
                start_km=float(start),
                end_km=float(end),
                min_km=float(min(start, end)),
                max_km=float(max(start, end)),
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.min_km, item.max_km, item.section_id)))


def _directional_power_arm_index(
    intervals: tuple[PowerArmInterval, ...],
    normalized_model_direction: str,
) -> Tuple[tuple[PowerArmInterval, ...], Dict[int, tuple[PowerArmInterval, ...]]]:
    """按区间对象和方向缓存供电臂空间桶，同时保留输入顺序。"""

    cache_key = id(intervals)
    with _POWER_ARM_INDEX_LOCK:
        cached = _POWER_ARM_INDEX_CACHE.get(cache_key)
        if cached is None or cached[0] is not intervals:
            cached = (intervals, {})
            _POWER_ARM_INDEX_CACHE[cache_key] = cached
        _POWER_ARM_INDEX_CACHE.move_to_end(cache_key)
        while len(_POWER_ARM_INDEX_CACHE) > _POWER_ARM_INDEX_CACHE_CAPACITY:
            _POWER_ARM_INDEX_CACHE.popitem(last=False)

        direction_indexes = cached[1]
        direction_index = direction_indexes.get(normalized_model_direction)
        if direction_index is not None:
            return direction_index

        candidates = tuple(
            item
            for item in intervals
            if _direction_matches(normalized_model_direction or None, item.direction)
        )
        mutable_bins: Dict[int, list[PowerArmInterval]] = {}
        for interval in candidates:
            first_bin = int(math.floor(interval.min_km))
            last_bin = int(math.floor(interval.max_km))
            for bin_index in range(first_bin, last_bin + 1):
                mutable_bins.setdefault(bin_index, []).append(interval)
        direction_index = (
            candidates,
            {key: tuple(values) for key, values in mutable_bins.items()},
        )
        direction_indexes[normalized_model_direction] = direction_index
        return direction_index


def find_power_arm_id(
    intervals: tuple[PowerArmInterval, ...],
    position_km: float,
    model_direction: Optional[str] = None,
) -> str:
    """函数 find_power_arm_id：执行该模块中的相关处理逻辑。"""
    if isinstance(position_km, bool):
        raise ValueError(f"position_km must be finite, got {position_km!r}")
    try:
        position = float(position_km)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"position_km must be finite, got {position_km!r}") from exc
    if not math.isfinite(position):
        raise ValueError(f"position_km must be finite, got {position_km!r}")
    normalized_model_direction = _clean(model_direction).lower()
    candidates, spatial_bins = _directional_power_arm_index(
        intervals,
        normalized_model_direction,
    )
    if not candidates:
        return ""
    local_candidates = spatial_bins.get(int(math.floor(position)), ())
    for interval in local_candidates:
        if normalized_model_direction == "forward":
            contains = interval.min_km <= position < interval.max_km
        elif normalized_model_direction == "reverse":
            contains = interval.min_km < position <= interval.max_km
        else:
            contains = interval.min_km <= position <= interval.max_km
        if contains:
            return interval.section_id
    nearest = min(candidates, key=lambda item: min(abs(position - item.min_km), abs(position - item.max_km)))
    if min(abs(position - nearest.min_km), abs(position - nearest.max_km)) <= 1e-6:
        return nearest.section_id
    return ""
