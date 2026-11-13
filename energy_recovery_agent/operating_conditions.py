# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math


OPEN_ENDED_TIME_S = 10**9


def _finite_number(value: Any, field_name: str) -> float:
    """函数 _finite_number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return number


def _whole_time(value: Any, field_name: str) -> int:
    """函数 _whole_time：执行该模块中的相关处理逻辑。"""
    number = _finite_number(value, field_name)
    if not number.is_integer() or number < 0.0:
        raise ValueError(f"{field_name} must be a finite non-negative whole number, got {value!r}")
    return int(number)


def _time_window(start_value: Any, end_value: Any, prefix: str) -> Tuple[int, int]:
    """函数 _time_window：执行该模块中的相关处理逻辑。"""
    start = _whole_time(start_value, f"{prefix}.start_time_s")
    end = _whole_time(end_value, f"{prefix}.end_time_s")
    if end < start:
        raise ValueError(f"{prefix}.end_time_s must not precede start_time_s")
    return start, end


@dataclass(frozen=True)
class WeatherCondition:
    """Weather rule that can reduce adhesion, raise resistance, and impose a speed cap."""

    name: str
    start_time_s: int = 0
    end_time_s: int = OPEN_ENDED_TIME_S
    affected_ranges_km: List[Tuple[float, float]] = field(default_factory=list)
    adhesion_multiplier: float = 1.0
    rolling_resistance_multiplier: float = 1.0
    aerodynamic_resistance_multiplier: float = 1.0
    speed_limit_kmh: Optional[float] = None

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        name = str(self.name).strip()
        if not name:
            raise ValueError("weather.name must not be empty")
        start, end = _time_window(self.start_time_s, self.end_time_s, "weather")
        ranges = []
        for index, raw_range in enumerate(self.affected_ranges_km):
            try:
                left, right = raw_range
            except (TypeError, ValueError) as exc:
                raise ValueError(f"weather.affected_ranges_km[{index}] is invalid") from exc
            left = _finite_number(left, f"weather.affected_ranges_km[{index}][0]")
            right = _finite_number(right, f"weather.affected_ranges_km[{index}][1]")
            if left < 0.0 or right < 0.0 or left == right:
                raise ValueError(f"weather.affected_ranges_km[{index}] must be a non-empty non-negative range")
            ranges.append((min(left, right), max(left, right)))
        for field_name in (
            "adhesion_multiplier",
            "rolling_resistance_multiplier",
            "aerodynamic_resistance_multiplier",
        ):
            value = _finite_number(getattr(self, field_name), f"weather.{field_name}")
            if value <= 0.0:
                raise ValueError(f"weather.{field_name} must be positive, got {value!r}")
            object.__setattr__(self, field_name, value)
        speed_limit = self.speed_limit_kmh
        if speed_limit is not None:
            speed_limit = _finite_number(speed_limit, "weather.speed_limit_kmh")
            if speed_limit <= 0.0:
                raise ValueError(f"weather.speed_limit_kmh must be positive, got {speed_limit!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start_time_s", start)
        object.__setattr__(self, "end_time_s", end)
        object.__setattr__(self, "affected_ranges_km", ranges)
        object.__setattr__(self, "speed_limit_kmh", speed_limit)


@dataclass(frozen=True)
class AdhesionZone:
    """Explicit low-adhesion zone, for example wet leaves, rain, snow, or sanded track limits."""

    name: str
    start_km: float
    end_km: float
    start_time_s: int = 0
    end_time_s: int = OPEN_ENDED_TIME_S
    adhesion_coefficient: float = 0.12

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        name = str(self.name).strip()
        if not name:
            raise ValueError("adhesion_zone.name must not be empty")
        left = _finite_number(self.start_km, "adhesion_zone.start_km")
        right = _finite_number(self.end_km, "adhesion_zone.end_km")
        if left < 0.0 or right < 0.0 or left == right:
            raise ValueError("adhesion zone bounds must form a non-empty non-negative range")
        start, end = _time_window(self.start_time_s, self.end_time_s, "adhesion_zone")
        coefficient = _finite_number(self.adhesion_coefficient, "adhesion_zone.adhesion_coefficient")
        if not 0.0 < coefficient <= 1.0:
            raise ValueError("adhesion_zone.adhesion_coefficient must be in (0, 1]")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start_km", min(left, right))
        object.__setattr__(self, "end_km", max(left, right))
        object.__setattr__(self, "start_time_s", start)
        object.__setattr__(self, "end_time_s", end)
        object.__setattr__(self, "adhesion_coefficient", coefficient)


@dataclass(frozen=True)
class TemporarySpeedRestriction:
    """按线路区间、时间窗和运行方向生效的临时限速。"""

    name: str
    start_km: float
    end_km: float
    speed_limit_kmh: float
    start_time_s: int = 0
    end_time_s: int = OPEN_ENDED_TIME_S
    reason: str = ""
    direction: str = "both"

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        name = str(self.name).strip()
        if not name:
            raise ValueError("speed_restriction.name must not be empty")
        left = _finite_number(self.start_km, "speed_restriction.start_km")
        right = _finite_number(self.end_km, "speed_restriction.end_km")
        if left < 0.0 or right < 0.0 or left == right:
            raise ValueError("speed restriction bounds must form a non-empty non-negative range")
        speed = _finite_number(self.speed_limit_kmh, "speed_restriction.speed_limit_kmh")
        if speed <= 0.0:
            raise ValueError("speed_restriction.speed_limit_kmh must be positive")
        start, end = _time_window(self.start_time_s, self.end_time_s, "speed_restriction")
        direction = normalize_speed_restriction_direction(self.direction)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start_km", min(left, right))
        object.__setattr__(self, "end_km", max(left, right))
        object.__setattr__(self, "speed_limit_kmh", speed)
        object.__setattr__(self, "start_time_s", start)
        object.__setattr__(self, "end_time_s", end)
        object.__setattr__(self, "direction", direction)


def normalize_speed_restriction_direction(value: Any) -> str:
    """将临时限速方向别名统一为 forward、reverse 或 both。"""

    text = str(value or "both").strip().lower()
    aliases = {
        "both": "both",
        "all": "both",
        "shared": "both",
        "forward": "forward",
        "down": "forward",
        "下行": "forward",
        "heavy": "forward",
        "reverse": "reverse",
        "up": "reverse",
        "上行": "reverse",
        "empty": "reverse",
    }
    if text not in aliases:
        raise ValueError(
            "speed_restriction.direction must be forward, reverse, both, down, up, heavy, or empty"
        )
    return aliases[text]


@dataclass(frozen=True)
class OperatingConditions:
    """All external operation constraints used by the physical train simulator."""

    default_adhesion_coefficient: float = 0.28
    traction_adhesion_safety_factor: float = 0.85
    braking_adhesion_safety_factor: float = 0.65
    weather_conditions: List[WeatherCondition] = field(default_factory=list)
    adhesion_zones: List[AdhesionZone] = field(default_factory=list)
    speed_restrictions: List[TemporarySpeedRestriction] = field(default_factory=list)
    _speed_restriction_bins: Dict[int, Tuple[TemporarySpeedRestriction, ...]] = field(
        init=False,
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _all_speed_restrictions_static: bool = field(
        init=False,
        default=False,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        adhesion = _finite_number(
            self.default_adhesion_coefficient, "operating_conditions.default_adhesion_coefficient"
        )
        if not 0.0 < adhesion <= 1.0:
            raise ValueError("operating_conditions.default_adhesion_coefficient must be in (0, 1]")
        object.__setattr__(self, "default_adhesion_coefficient", adhesion)
        for field_name in ("traction_adhesion_safety_factor", "braking_adhesion_safety_factor"):
            value = _finite_number(getattr(self, field_name), f"operating_conditions.{field_name}")
            if not 0.0 < value <= 1.0:
                raise ValueError(f"operating_conditions.{field_name} must be in (0, 1]")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "weather_conditions", list(self.weather_conditions))
        object.__setattr__(self, "adhesion_zones", list(self.adhesion_zones))
        object.__setattr__(self, "speed_restrictions", list(self.speed_restrictions))
        for field_name, expected_type in (
            ("weather_conditions", WeatherCondition),
            ("adhesion_zones", AdhesionZone),
            ("speed_restrictions", TemporarySpeedRestriction),
        ):
            if any(not isinstance(item, expected_type) for item in getattr(self, field_name)):
                raise ValueError(f"operating_conditions.{field_name} must contain {expected_type.__name__} objects")

        # 运行仿真的前视控制会高频查询线路限速。正式线路由大量相邻分段组成，
        # 若每个采样点都遍历全表，调用量会随“仿真步数 x 前视点数 x 分段数”增长。
        # 一公里空间桶只缩小候选集合，最终仍执行原有时间窗和精确区间判断。
        mutable_bins: Dict[int, List[TemporarySpeedRestriction]] = {}
        for restriction in self.speed_restrictions:
            first_bin = int(math.floor(restriction.start_km))
            last_bin = int(math.floor(restriction.end_km))
            for bin_index in range(first_bin, last_bin + 1):
                mutable_bins.setdefault(bin_index, []).append(restriction)
        object.__setattr__(
            self,
            "_speed_restriction_bins",
            {key: tuple(values) for key, values in mutable_bins.items()},
        )
        object.__setattr__(
            self,
            "_all_speed_restrictions_static",
            all(
                item.start_time_s == 0 and item.end_time_s >= OPEN_ENDED_TIME_S
                for item in self.speed_restrictions
            ),
        )


def default_operating_conditions() -> OperatingConditions:
    """Return a dry-clear baseline profile."""

    return OperatingConditions()


def adverse_weather_operating_conditions() -> OperatingConditions:
    """Return a virtual adverse-weather profile used by experiments and verification."""

    return OperatingConditions(
        default_adhesion_coefficient=0.28,
        traction_adhesion_safety_factor=0.85,
        braking_adhesion_safety_factor=0.65,
        weather_conditions=[
            WeatherCondition(
                name="rain_mountain_section",
                start_time_s=0,
                end_time_s=18_000,
                affected_ranges_km=[(62.0, 302.0)],
                adhesion_multiplier=0.70,
                rolling_resistance_multiplier=1.04,
                aerodynamic_resistance_multiplier=1.02,
                speed_limit_kmh=110.0,
            )
        ],
        adhesion_zones=[
            AdhesionZone(
                name="wet_flexible_power_zone",
                start_km=145.0,
                end_km=200.7,
                start_time_s=0,
                end_time_s=18_000,
                adhesion_coefficient=0.08,
            )
        ],
        speed_restrictions=[
            TemporarySpeedRestriction(
                name="temporary_limit_diliudeng_xiaojue",
                start_km=164.0,
                end_km=200.7,
                start_time_s=1_800,
                end_time_s=18_000,
                speed_limit_kmh=80.0,
                reason="virtual weather and maintenance restriction",
            )
        ],
    )


def _ranges_from_raw(raw_ranges: Iterable[Iterable[float]]) -> List[Tuple[float, float]]:
    """函数 _ranges_from_raw：执行该模块中的相关处理逻辑。"""
    if isinstance(raw_ranges, (str, bytes)):
        raise ValueError("affected_ranges_km must be an iterable of two-value ranges")
    ranges: List[Tuple[float, float]] = []
    for index, item in enumerate(raw_ranges):
        try:
            values = list(item)
        except TypeError as exc:
            raise ValueError(f"affected_ranges_km[{index}] is invalid") from exc
        if len(values) != 2:
            raise ValueError(f"affected_ranges_km[{index}] must contain exactly two values")
        ranges.append((values[0], values[1]))
    return ranges


def operating_conditions_from_dict(raw: Optional[dict[str, Any]]) -> OperatingConditions:
    """Parse operating conditions from sandbox_config.json."""

    if raw is None:
        return default_operating_conditions()
    if not isinstance(raw, dict):
        raise ValueError("operating_conditions must be a JSON object or null")
    if not raw:
        return default_operating_conditions()

    weather = []
    weather_rows = raw.get("weather_conditions", [])
    adhesion_rows = raw.get("adhesion_zones", [])
    restriction_rows = raw.get("speed_restrictions", [])
    for field_name, rows in (
        ("weather_conditions", weather_rows),
        ("adhesion_zones", adhesion_rows),
        ("speed_restrictions", restriction_rows),
    ):
        if not isinstance(rows, list):
            raise ValueError(f"operating_conditions.{field_name} must be a JSON array")
        if any(not isinstance(item, dict) for item in rows):
            raise ValueError(f"operating_conditions.{field_name} entries must be JSON objects")
    for item in weather_rows:
        item = dict(item)
        item["affected_ranges_km"] = _ranges_from_raw(item.get("affected_ranges_km", []))
        weather.append(WeatherCondition(**item))

    adhesion_zones = [AdhesionZone(**item) for item in adhesion_rows]
    speed_restrictions = [
        TemporarySpeedRestriction(**item)
        for item in restriction_rows
    ]

    return OperatingConditions(
        default_adhesion_coefficient=raw.get("default_adhesion_coefficient", 0.28),
        traction_adhesion_safety_factor=raw.get("traction_adhesion_safety_factor", 0.85),
        braking_adhesion_safety_factor=raw.get("braking_adhesion_safety_factor", 0.65),
        weather_conditions=weather,
        adhesion_zones=adhesion_zones,
        speed_restrictions=speed_restrictions,
    )


def active_in_time(start_time_s: int, end_time_s: int, time_s: int) -> bool:
    """函数 active_in_time：执行该模块中的相关处理逻辑。"""
    return int(start_time_s) <= int(time_s) <= int(end_time_s)


def position_in_range(position_km: float, start_km: float, end_km: float) -> bool:
    """函数 position_in_range：执行该模块中的相关处理逻辑。"""
    lo = min(start_km, end_km)
    hi = max(start_km, end_km)
    return lo <= position_km <= hi


def position_in_ranges(position_km: float, ranges_km: List[Tuple[float, float]]) -> bool:
    """函数 position_in_ranges：执行该模块中的相关处理逻辑。"""
    if not ranges_km:
        return True
    return any(position_in_range(position_km, start, end) for start, end in ranges_km)


def active_weather_at(
    profile: OperatingConditions,
    position_km: float,
    time_s: int,
) -> List[WeatherCondition]:
    """函数 active_weather_at：执行该模块中的相关处理逻辑。"""
    return [
        weather
        for weather in profile.weather_conditions
        if active_in_time(weather.start_time_s, weather.end_time_s, time_s)
        and position_in_ranges(position_km, weather.affected_ranges_km)
    ]


def adhesion_coefficient_at(
    profile: OperatingConditions,
    position_km: float,
    time_s: int,
) -> float:
    """函数 adhesion_coefficient_at：执行该模块中的相关处理逻辑。"""
    mu = profile.default_adhesion_coefficient
    for weather in active_weather_at(profile, position_km, time_s):
        mu *= weather.adhesion_multiplier

    for zone in profile.adhesion_zones:
        if active_in_time(zone.start_time_s, zone.end_time_s, time_s) and position_in_range(
            position_km,
            zone.start_km,
            zone.end_km,
        ):
            mu = min(mu, zone.adhesion_coefficient)

    return max(0.03, min(0.45, mu))


def speed_limit_kmh_at(
    profile: OperatingConditions,
    route_max_speed_kmh: float,
    position_km: float,
    time_s: int,
    direction: Optional[str] = None,
) -> float:
    """函数 speed_limit_kmh_at：执行该模块中的相关处理逻辑。"""
    speed_limit = route_max_speed_kmh
    # 无天气限速和临时限速时，这是列车仿真中最常见的热路径；避免创建列表和进入多层辅助函数。
    if not profile.weather_conditions and not profile.speed_restrictions:
        return max(5.0, speed_limit)

    if direction is None:
        normalized_direction = None
    elif direction in {"forward", "reverse"}:
        normalized_direction = direction
    else:
        normalized_direction = normalize_speed_restriction_direction(direction)

    if not profile.weather_conditions and profile._all_speed_restrictions_static:
        for restriction in profile._speed_restriction_bins.get(int(math.floor(position_km)), ()):
            if (
                normalized_direction is None
                or restriction.direction == "both"
                or restriction.direction == normalized_direction
            ) and min(restriction.start_km, restriction.end_km) <= position_km <= max(
                restriction.start_km,
                restriction.end_km,
            ):
                speed_limit = min(speed_limit, float(restriction.speed_limit_kmh))
        return max(5.0, speed_limit)

    for weather in profile.weather_conditions:
        if (
            weather.speed_limit_kmh is not None
            and weather.start_time_s <= time_s <= weather.end_time_s
            and (
                not weather.affected_ranges_km
                or any(
                    min(start_km, end_km) <= position_km <= max(start_km, end_km)
                    for start_km, end_km in weather.affected_ranges_km
                )
            )
        ):
            speed_limit = min(speed_limit, float(weather.speed_limit_kmh))

    candidate_restrictions = profile._speed_restriction_bins.get(
        int(math.floor(position_km)),
        (),
    )
    for restriction in candidate_restrictions:
        direction_matches = (
            normalized_direction is None
            or restriction.direction == "both"
            or restriction.direction == normalized_direction
        )
        if (
            direction_matches
            and restriction.start_time_s <= time_s <= restriction.end_time_s
            and min(restriction.start_km, restriction.end_km)
            <= position_km
            <= max(restriction.start_km, restriction.end_km)
        ):
            speed_limit = min(speed_limit, float(restriction.speed_limit_kmh))

    return max(5.0, speed_limit)


def resistance_multipliers_at(
    profile: OperatingConditions,
    position_km: float,
    time_s: int,
) -> Tuple[float, float]:
    """函数 resistance_multipliers_at：执行该模块中的相关处理逻辑。"""
    rolling_multiplier = 1.0
    aerodynamic_multiplier = 1.0
    for weather in active_weather_at(profile, position_km, time_s):
        rolling_multiplier *= weather.rolling_resistance_multiplier
        aerodynamic_multiplier *= weather.aerodynamic_resistance_multiplier
    return rolling_multiplier, aerodynamic_multiplier


def is_time_dependent(profile: OperatingConditions) -> bool:
    """Return True when cache shifting must account for absolute departure time."""

    for weather in profile.weather_conditions:
        if weather.start_time_s != 0 or weather.end_time_s < OPEN_ENDED_TIME_S:
            return True
    for zone in profile.adhesion_zones:
        if zone.start_time_s != 0 or zone.end_time_s < OPEN_ENDED_TIME_S:
            return True
    for restriction in profile.speed_restrictions:
        if restriction.start_time_s != 0 or restriction.end_time_s < OPEN_ENDED_TIME_S:
            return True
    return False
