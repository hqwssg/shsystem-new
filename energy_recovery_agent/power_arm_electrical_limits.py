# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
import csv
import hashlib
import math
import re


DEFAULT_POWER_ARM_LIMIT_KW = 1_000_000.0
SHUOHUANG_DIRECT_USE_ENABLED = False
DEFAULT_STORAGE_RANGES_KM = ((145.0, 164.0), (164.0, 200.7))
DEFAULT_LIMIT_STATUS = "default_large_non_binding_until_official_limits"
DEFAULT_LIMIT_NOTE = "未获得供电臂电气能力资料前采用较大值，避免电气能力成为当前原型约束；后续按真实资料替换。"
DEFAULT_STORAGE_STATUS = "planning_assumption_two_storage_sections_pending_official_boundaries"
DEFAULT_STORAGE_NOTE = "根据当前方案，朔黄上下行不能直发直用；两段储能区段按145-164km、164-200.7km规划假设接入，后续按正式储能设备区段替换。"
DEFAULT_POWER_ARM_INTERVAL_PATH = Path("data") / "real_shuohuang" / "power_arm_intervals.csv"
REQUIRED_OPERATIONAL_COLUMNS = (
    "max_traction_supply_kw",
    "max_regen_absorption_kw",
    "max_grid_feedback_kw",
    "storage_available",
    "storage_section_id",
)


@dataclass(frozen=True)
class PowerArmElectricalLimit:
    """类 PowerArmElectricalLimit：执行该模块中的相关处理逻辑。"""
    max_traction_supply_kw: float = DEFAULT_POWER_ARM_LIMIT_KW
    max_regen_absorption_kw: float = DEFAULT_POWER_ARM_LIMIT_KW
    max_grid_feedback_kw: float = DEFAULT_POWER_ARM_LIMIT_KW
    up_down_feed_rule: str = "scenario_controlled"
    grid_feedback_rule: str = "not_credited_by_current_dispatch_model"
    electrical_limit_status: str = DEFAULT_LIMIT_STATUS
    electrical_limit_note: str = DEFAULT_LIMIT_NOTE
    storage_available: bool = False
    storage_section_id: str = ""
    storage_status: str = "no_storage_in_current_section"
    storage_note: str = "当前供电臂未标记为储能接入区段。"

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        for field_name in (
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
        ):
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(
                    f"{field_name} must be a finite non-negative number; got {raw_value!r}"
                )
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{field_name} must be a finite non-negative number; got {raw_value!r}"
                ) from exc
            if not math.isfinite(number) or number < 0.0:
                raise ValueError(
                    f"{field_name} must be a finite non-negative number; got {raw_value!r}"
                )
            object.__setattr__(self, field_name, number)
        if type(self.storage_available) is not bool:
            raise ValueError("storage_available must be a boolean")
        storage_id = str(self.storage_section_id).strip()
        if self.storage_available and not storage_id:
            raise ValueError("storage_section_id is required when storage_available is true")
        if not self.storage_available and storage_id:
            raise ValueError("storage_section_id must be empty when storage_available is false")
        object.__setattr__(self, "storage_section_id", storage_id)


@dataclass(frozen=True)
class DynamicPowerArmLimit:
    """供电臂在绝对时间窗内生效的临时电气上限。"""

    event_id: str
    power_arm_id: str
    start_time_s: int
    end_time_s: int
    max_traction_supply_kw: float | None = None
    max_regen_absorption_kw: float | None = None
    max_grid_feedback_kw: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not str(self.event_id).strip() or not str(self.power_arm_id).strip():
            raise ValueError("动态供电限值的event_id和power_arm_id不能为空。")
        start_s = int(self.start_time_s)
        end_s = int(self.end_time_s)
        if isinstance(self.start_time_s, bool) or isinstance(self.end_time_s, bool) or start_s != self.start_time_s or end_s != self.end_time_s or start_s < 0 or end_s <= start_s:
            raise ValueError("动态供电限值时间窗必须为非负整数且非空。")
        names = ("max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw")
        if all(getattr(self, name) is None for name in names):
            raise ValueError("动态供电限值至少需要一个功率字段。")
        for name in names:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _float_or_default(value, 0.0, name))
        object.__setattr__(self, "event_id", str(self.event_id).strip())
        object.__setattr__(self, "power_arm_id", str(self.power_arm_id).strip())
        object.__setattr__(self, "start_time_s", start_s)
        object.__setattr__(self, "end_time_s", end_s)

    def applies_at(self, power_arm_id: str, time_s: float) -> bool:
        return self.power_arm_id == str(power_arm_id).strip() and self.start_time_s <= time_s < self.end_time_s

    def overlaps(self, power_arm_id: str, start_time_s: float, end_time_s: float) -> bool:
        return (
            self.power_arm_id == str(power_arm_id).strip()
            and max(self.start_time_s, start_time_s) < min(self.end_time_s, end_time_s)
        )

    def overlay(self, base: PowerArmElectricalLimit) -> PowerArmElectricalLimit:
        changes = {
            name: min(float(getattr(base, name)), float(getattr(self, name)))
            for name in ("max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw")
            if getattr(self, name) is not None
        }
        return replace(
            base,
            **changes,
            electrical_limit_status="dynamic_runtime_limit",
            electrical_limit_note=self.reason or f"动态事件{self.event_id}在指定时间窗生效。",
        )


@dataclass(frozen=True)
class StorageSectionInterval:
    """类 StorageSectionInterval：执行该模块中的相关处理逻辑。"""
    storage_section_id: str
    start_km: float
    end_km: float
    direction: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        storage_id = str(self.storage_section_id).strip()
        if isinstance(self.start_km, bool) or isinstance(self.end_km, bool):
            raise ValueError("Storage section bounds must be finite")
        try:
            start_km = float(self.start_km)
            end_km = float(self.end_km)
        except (TypeError, ValueError) as exc:
            raise ValueError("Storage section bounds must be finite") from exc
        if not storage_id:
            raise ValueError("storage_section_id must be non-empty")
        if not math.isfinite(start_km) or not math.isfinite(end_km):
            raise ValueError("Storage section bounds must be finite")
        if math.isclose(start_km, end_km, abs_tol=1e-12):
            raise ValueError("Storage section bounds must be distinct")
        object.__setattr__(self, "storage_section_id", storage_id)
        object.__setattr__(self, "start_km", start_km)
        object.__setattr__(self, "end_km", end_km)

        # 在模型边界统一所有支持的方向别名，使直接调用接口与 CSV 导入行为一致。
        raw_direction = self.direction
        normalized_direction = _normalized_direction(raw_direction)
        if _clean(raw_direction) and not normalized_direction:
            raise ValueError(
                "Storage section direction must be forward/reverse "
                "(or down/up, 下行/上行); "
                f"got {raw_direction!r}"
            )
        object.__setattr__(self, "direction", normalized_direction)

    @property
    def min_km(self) -> float:
        """函数 min_km：执行该模块中的相关处理逻辑。"""
        return min(self.start_km, self.end_km)

    @property
    def max_km(self) -> float:
        """函数 max_km：执行该模块中的相关处理逻辑。"""
        return max(self.start_km, self.end_km)


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _float_or_default(value: Any, default: float, field_name: str = "value") -> float:
    """函数 _float_or_default：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return default
    try:
        parsed = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite non-negative number; got {text!r}") from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{field_name} must be a finite non-negative number; got {text!r}")
    return parsed


def _boolish(value: Any) -> bool:
    """函数 _boolish：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "是", "有", "available"}:
        return True
    if text in {"", "0", "false", "no", "n", "否", "无", "unavailable"}:
        return False
    raise ValueError(
        "storage_available must be an explicit boolean value "
        f"(yes/no, true/false, 1/0, 是/否); got {text!r}"
    )


def _normalized_direction(value: Any) -> str:
    """函数 _normalized_direction：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"forward", "down", "downbound", "下行"}:
        return "forward"
    if text in {"reverse", "up", "upbound", "上行"}:
        return "reverse"
    return ""


def _normalized_query_direction(value: Any) -> str:
    """Normalize a lookup direction, preserving empty-string wildcard semantics."""

    normalized = _normalized_direction(value)
    if _clean(value) and not normalized:
        raise ValueError(
            "Direction must be forward/reverse (or down/up, 下行/上行); "
            f"got {value!r}"
        )
    return normalized


_STORAGE_RANGE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])K\s*(-?\d+(?:\.\d+)?)\s*-\s*K?\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _storage_range_from_id(storage_section_id: str) -> Tuple[float, float] | None:
    """函数 _storage_range_from_id：执行该模块中的相关处理逻辑。"""
    match = _STORAGE_RANGE_RE.search(storage_section_id)
    if match is None:
        return None
    start_km = float(match.group(1))
    end_km = float(match.group(2))
    return min(start_km, end_km), max(start_km, end_km)


def storage_section_intervals_from_rows(rows: Iterable[Mapping[str, Any]]) -> Tuple[StorageSectionInterval, ...]:
    """Build runtime storage geometry from power-arm rows.

    Explicit ``storage_start_km``/``storage_end_km`` fields take precedence.
    Existing planning IDs such as ``storage_section_1:K145-K164`` carry their
    own range. For arbitrary IDs, the marked power-arm interval is used.
    """

    intervals: List[StorageSectionInterval] = []
    seen: set[Tuple[str, float, float, str]] = set()
    for row in rows:
        storage_ids = [item.strip() for item in _clean(row.get("storage_section_id")).split(";") if item.strip()]
        if not storage_ids or not _boolish(row.get("storage_available")):
            continue
        row_start = _float_or_default(
            row.get("storage_start_km"),
            _float_or_default(row.get("start_km"), float("nan"), "start_km"),
            "storage_start_km",
        )
        row_end = _float_or_default(
            row.get("storage_end_km"),
            _float_or_default(row.get("end_km"), float("nan"), "end_km"),
            "storage_end_km",
        )
        explicit_bounds = bool(_clean(row.get("storage_start_km")) and _clean(row.get("storage_end_km")))
        direction = _normalized_direction(row.get("direction"))
        if _clean(row.get("direction")) and not direction:
            raise ValueError(f"Unrecognized storage section direction: {row.get('direction')!r}")
        for storage_id in storage_ids:
            parsed_range = None if explicit_bounds else _storage_range_from_id(storage_id)
            if parsed_range is not None:
                start_km, end_km = parsed_range
            else:
                start_km, end_km = row_start, row_end
            if not math.isfinite(start_km) or not math.isfinite(end_km) or start_km == end_km:
                raise ValueError(
                    f"Storage section {storage_id!r} must have finite, distinct bounds"
                )
            start_km, end_km = min(start_km, end_km), max(start_km, end_km)
            key = (storage_id, start_km, end_km, direction)
            if key in seen:
                continue
            seen.add(key)
            intervals.append(StorageSectionInterval(storage_id, start_km, end_km, direction))
    for index, left in enumerate(intervals):
        for right in intervals[index + 1 :]:
            if left.storage_section_id == right.storage_section_id:
                continue
            directions_overlap = (
                not left.direction
                or not right.direction
                or left.direction == right.direction
            )
            geometry_overlaps = max(left.min_km, right.min_km) < min(
                left.max_km,
                right.max_km,
            )
            if directions_overlap and geometry_overlaps:
                raise ValueError(
                    "Overlapping storage sections are ambiguous for a single-position lookup: "
                    f"{left.storage_section_id!r} and {right.storage_section_id!r}"
                )
    return tuple(sorted(intervals, key=lambda item: (item.min_km, item.max_km, item.direction, item.storage_section_id)))


def _power_arm_csv_path(path: str | Path) -> Path:
    """函数 _power_arm_csv_path：执行该模块中的相关处理逻辑。"""
    csv_path = Path(path)
    if csv_path.exists() and csv_path.is_dir():
        candidate = csv_path / DEFAULT_POWER_ARM_INTERVAL_PATH.name
        if candidate.exists():
            csv_path = candidate
    return csv_path


def power_arm_file_revision(path: str | Path = DEFAULT_POWER_ARM_INTERVAL_PATH) -> Tuple[str, int, int, str]:
    """Return a cache key that changes when a power-arm input file changes."""

    csv_path = _power_arm_csv_path(path)
    resolved = str(csv_path.resolve())
    try:
        stat = csv_path.stat()
    except OSError:
        return resolved, -1, -1, ""
    try:
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return resolved, int(stat.st_mtime_ns), int(stat.st_size), digest


@lru_cache(maxsize=8)
def _load_storage_section_intervals_cached(
    resolved_path: str,
    _mtime_ns: int,
    _size: int,
    _sha256: str,
) -> Tuple[StorageSectionInterval, ...]:
    """函数 _load_storage_section_intervals_cached：执行该模块中的相关处理逻辑。"""
    csv_path = Path(resolved_path)
    if not csv_path.exists() or csv_path.suffix.lower() != ".csv":
        return ()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if _is_mainline_road(row)]
    return storage_section_intervals_from_rows(rows)


def load_storage_section_intervals(
    path: str | Path = DEFAULT_POWER_ARM_INTERVAL_PATH,
) -> Tuple[StorageSectionInterval, ...]:
    """函数 load_storage_section_intervals：执行该模块中的相关处理逻辑。"""
    return _load_storage_section_intervals_cached(*power_arm_file_revision(path))


def storage_boundary_kms(
    intervals: Sequence[StorageSectionInterval],
    direction: str = "",
) -> Tuple[float, ...]:
    """函数 storage_boundary_kms：执行该模块中的相关处理逻辑。"""
    selected_direction = _normalized_query_direction(direction)
    return tuple(
        sorted(
            {
                boundary
                for item in intervals
                if not selected_direction or not item.direction or item.direction == selected_direction
                for boundary in (item.min_km, item.max_km)
            }
        )
    )


def _is_mainline_road(row: Mapping[str, Any]) -> bool:
    """函数 _is_mainline_road：执行该模块中的相关处理逻辑。"""
    road = _clean(row.get("road") or row.get("line")).lower()
    return not road or road in {"朔黄线", "shuohuang"}


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    """函数 _overlaps：执行该模块中的相关处理逻辑。"""
    return max(min(a0, a1), min(b0, b1)) < min(max(a0, a1), max(b0, b1))


def storage_fields_for_interval(start_km: float, end_km: float) -> Dict[str, object]:
    """函数 storage_fields_for_interval：执行该模块中的相关处理逻辑。"""
    matched = [
        f"storage_section_{idx}:K{start:g}-K{end:g}"
        for idx, (start, end) in enumerate(DEFAULT_STORAGE_RANGES_KM, start=1)
        if _overlaps(float(start_km), float(end_km), start, end)
    ]
    if matched:
        return {
            "storage_available": "是",
            "storage_section_id": ";".join(matched),
            "storage_start_km": "",
            "storage_end_km": "",
            "storage_status": DEFAULT_STORAGE_STATUS,
            "storage_note": DEFAULT_STORAGE_NOTE,
        }
    return {
        "storage_available": "否",
        "storage_section_id": "",
        "storage_start_km": "",
        "storage_end_km": "",
        "storage_status": "no_storage_in_current_section",
        "storage_note": "当前供电臂未标记为储能接入区段。",
    }


def storage_section_for_position(
    position_km: float,
    intervals: Sequence[StorageSectionInterval] | None = None,
    direction: str = "",
) -> str:
    """Return exactly one storage section for a route position.

    Boundaries use half-open intervals so K164 belongs to section 2 rather
    than both sections. The final section endpoint remains inclusive.
    """

    if isinstance(position_km, bool):
        raise ValueError(f"position_km must be finite, got {position_km!r}")
    position = float(position_km)
    if not math.isfinite(position):
        raise ValueError(f"position_km must be finite, got {position_km!r}")
    selected_direction = _normalized_query_direction(direction)
    selected = tuple(intervals) if intervals is not None else load_storage_section_intervals()
    eligible = [
        item
        for item in selected
        if not selected_direction or not item.direction or item.direction == selected_direction
    ]
    for item in eligible:
        if item.min_km <= position < item.max_km:
            return item.storage_section_id
    # 保留配置区段外侧端点的包含关系；共享边界仍归属于从该位置开始的区段。
    for item in eligible:
        if math.isclose(position, item.max_km, abs_tol=1e-9):
            return item.storage_section_id
    return ""


def default_power_arm_electrical_limit() -> PowerArmElectricalLimit:
    """函数 default_power_arm_electrical_limit：执行该模块中的相关处理逻辑。"""
    return PowerArmElectricalLimit()


def power_arm_electrical_limit_from_row(row: Mapping[str, Any]) -> PowerArmElectricalLimit:
    """函数 power_arm_electrical_limit_from_row：执行该模块中的相关处理逻辑。"""
    default = default_power_arm_electrical_limit()
    return PowerArmElectricalLimit(
        max_traction_supply_kw=_float_or_default(
            row.get("max_traction_supply_kw"),
            default.max_traction_supply_kw,
            "max_traction_supply_kw",
        ),
        max_regen_absorption_kw=_float_or_default(
            row.get("max_regen_absorption_kw"),
            default.max_regen_absorption_kw,
            "max_regen_absorption_kw",
        ),
        max_grid_feedback_kw=_float_or_default(
            row.get("max_grid_feedback_kw"),
            default.max_grid_feedback_kw,
            "max_grid_feedback_kw",
        ),
        up_down_feed_rule=_clean(row.get("up_down_feed_rule")) or default.up_down_feed_rule,
        grid_feedback_rule=_clean(row.get("grid_feedback_rule")) or default.grid_feedback_rule,
        electrical_limit_status=_clean(row.get("electrical_limit_status")) or default.electrical_limit_status,
        electrical_limit_note=_clean(row.get("electrical_limit_note")) or default.electrical_limit_note,
        storage_available=_boolish(row.get("storage_available")),
        storage_section_id=_clean(row.get("storage_section_id")),
        storage_status=_clean(row.get("storage_status")) or default.storage_status,
        storage_note=_clean(row.get("storage_note")) or default.storage_note,
    )


def electrical_limit_fields(limit: PowerArmElectricalLimit | None = None) -> Dict[str, object]:
    """函数 electrical_limit_fields：执行该模块中的相关处理逻辑。"""
    item = limit or default_power_arm_electrical_limit()
    return {
        "max_traction_supply_kw": item.max_traction_supply_kw,
        "max_regen_absorption_kw": item.max_regen_absorption_kw,
        "max_grid_feedback_kw": item.max_grid_feedback_kw,
        "up_down_feed_rule": item.up_down_feed_rule,
        "grid_feedback_rule": item.grid_feedback_rule,
        "electrical_limit_status": item.electrical_limit_status,
        "electrical_limit_note": item.electrical_limit_note,
        "storage_available": "是" if item.storage_available else "否",
        "storage_section_id": item.storage_section_id,
        "storage_status": item.storage_status,
        "storage_note": item.storage_note,
    }


def _whole_second(value: Any, field_name: str) -> int:
    """函数 _whole_second：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite whole second; got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole second; got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field_name} must be a finite whole second; got {value!r}")
    return int(number)


def time_window_capacity_kwh(limit_kw: float, start_s: int, end_s: int) -> float:
    """函数 time_window_capacity_kwh：执行该模块中的相关处理逻辑。"""
    if isinstance(limit_kw, bool):
        raise ValueError(f"limit_kw must be a finite non-negative number; got {limit_kw!r}")
    try:
        limit = float(limit_kw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit_kw must be a finite non-negative number; got {limit_kw!r}") from exc
    if not math.isfinite(limit) or limit < 0.0:
        raise ValueError(f"limit_kw must be a finite non-negative number; got {limit_kw!r}")
    start = _whole_second(start_s, "start_s")
    end = _whole_second(end_s, "end_s")
    if end <= start:
        raise ValueError(f"time window must satisfy end_s > start_s; got {start_s!r}, {end_s!r}")
    duration_h = (end - start) / 3600.0
    return limit * duration_h


def non_binding_direct_use_kwh(traction_kwh: float, regen_kwh: float, start_s: int, end_s: int, limit: PowerArmElectricalLimit) -> float:
    """函数 non_binding_direct_use_kwh：执行该模块中的相关处理逻辑。"""
    if not SHUOHUANG_DIRECT_USE_ENABLED:
        return 0.0
    traction_room = time_window_capacity_kwh(limit.max_traction_supply_kw, start_s, end_s)
    regen_room = time_window_capacity_kwh(limit.max_regen_absorption_kw, start_s, end_s)
    return min(max(0.0, traction_kwh), max(0.0, regen_kwh), traction_room, regen_room)


@lru_cache(maxsize=8)
def _load_power_arm_electrical_limits_cached(
    resolved_path: str,
    _mtime_ns: int,
    _size: int,
    _sha256: str,
) -> Tuple[Tuple[str, PowerArmElectricalLimit], ...]:
    """函数 _load_power_arm_electrical_limits_cached：执行该模块中的相关处理逻辑。"""
    csv_path = Path(resolved_path)
    if not csv_path.exists() or csv_path.suffix.lower() != ".csv":
        return ()
    limits: Dict[str, PowerArmElectricalLimit] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or ())
        missing_columns = [field for field in REQUIRED_OPERATIONAL_COLUMNS if field not in headers]
        if missing_columns:
            raise ValueError(
                f"Power-arm CSV is missing required operational columns {missing_columns}: {csv_path}"
            )
        for row_number, row in enumerate(reader, start=2):
            if not _is_mainline_road(row):
                continue
            for field in REQUIRED_OPERATIONAL_COLUMNS[:-1]:
                if not _clean(row.get(field)):
                    raise ValueError(
                        f"Power-arm CSV row {row_number} has an empty required field {field}: {csv_path}"
                    )
            limit = power_arm_electrical_limit_from_row(row)
            storage_id = _clean(row.get("storage_section_id"))
            if limit.storage_available and not storage_id:
                raise ValueError(
                    f"Power-arm CSV row {row_number} enables storage without storage_section_id: {csv_path}"
                )
            if not limit.storage_available and storage_id:
                raise ValueError(
                    f"Power-arm CSV row {row_number} provides storage_section_id while storage is disabled: {csv_path}"
                )
            storage_start = _clean(row.get("storage_start_km"))
            storage_end = _clean(row.get("storage_end_km"))
            if bool(storage_start) != bool(storage_end):
                raise ValueError(
                    f"Power-arm CSV row {row_number} must provide storage_start_km and storage_end_km together: {csv_path}"
                )
            if storage_start and storage_end:
                parsed_start = _float_or_default(storage_start, float("nan"), "storage_start_km")
                parsed_end = _float_or_default(storage_end, float("nan"), "storage_end_km")
                if math.isclose(parsed_start, parsed_end, abs_tol=1e-9):
                    raise ValueError(
                        f"Power-arm CSV row {row_number} has identical storage bounds: {csv_path}"
                    )
                if not limit.storage_available:
                    raise ValueError(
                        f"Power-arm CSV row {row_number} provides storage bounds while storage is disabled: {csv_path}"
                    )
            for key in ("section_id", "power_arm_id"):
                arm_id = _clean(row.get(key))
                if arm_id:
                    previous = limits.get(arm_id)
                    if previous is not None:
                        signature = lambda item: (
                            item.max_traction_supply_kw,
                            item.max_regen_absorption_kw,
                            item.max_grid_feedback_kw,
                            item.up_down_feed_rule,
                            item.grid_feedback_rule,
                            item.storage_available,
                            item.storage_section_id,
                        )
                        if signature(previous) != signature(limit):
                            raise ValueError(
                                "Power-arm ID is defined with conflicting electrical/storage "
                                f"limits at row {row_number}: {arm_id!r}"
                            )
                    else:
                        limits[arm_id] = limit
    return tuple(limits.items())


def load_power_arm_electrical_limits(path: str | Path = DEFAULT_POWER_ARM_INTERVAL_PATH) -> Dict[str, PowerArmElectricalLimit]:
    """Load limits without returning mutable state owned by the file cache."""

    return dict(_load_power_arm_electrical_limits_cached(*power_arm_file_revision(path)))


def limit_for_power_arm(power_arm_id: str, limits: Mapping[str, PowerArmElectricalLimit] | None = None) -> PowerArmElectricalLimit:
    """函数 limit_for_power_arm：执行该模块中的相关处理逻辑。"""
    if limits:
        arm_ids = [_clean(arm_id) for arm_id in str(power_arm_id).split(";") if _clean(arm_id)]
        # 只有弧段跨越多个供电臂时才生成组合 ID。静默丢弃缺失成员并使用已知成员限制，
        # 可能低估真实瓶颈或在未知馈线上错误启用储能。单个未配置 ID 保留旧版默认回退，
        # 但部分配置的组合 ID 必须按保守原则判为不可用。
        missing_ids = [arm_id for arm_id in arm_ids if arm_id not in limits]
        if len(arm_ids) > 1 and missing_ids:
            raise ValueError(
                "Composite power-arm ID contains unconfigured members: "
                f"{';'.join(missing_ids)!r}"
            )
        matched = [
            item
            for arm_id in arm_ids
            if (item := limits.get(_clean(arm_id))) is not None
        ]
        if matched:
            # 运行弧段可能跨越多个配置供电臂，使用确定性的组合 ID（如 ``A;B``）表示。
            # 若只取第一项，``A;B`` 与 ``B;A`` 可能得到不同的容量违反和回收能量结果。
            # 元数据冲突的组合 ID 在当前模型中含义不明确，因此保守判为不可用；
            # 限制完全一致时则可以安全保留共享限制值。
            first = matched[0]
            signature = lambda item: (
                item.max_traction_supply_kw,
                item.max_regen_absorption_kw,
                item.max_grid_feedback_kw,
                item.up_down_feed_rule,
                item.grid_feedback_rule,
                item.storage_available,
                item.storage_section_id,
            )
            first_signature = signature(first)
            if any(signature(item) != first_signature for item in matched[1:]):
                ids = ";".join(
                    _clean(arm_id)
                    for arm_id in arm_ids
                    if _clean(arm_id)
                )
                raise ValueError(
                    "Composite power-arm ID has conflicting electrical/storage "
                    f"limits and cannot be settled safely: {ids!r}"
                )
            return first
    return default_power_arm_electrical_limit()
