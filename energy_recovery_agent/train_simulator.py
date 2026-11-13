# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""单列车运行与牵引/制动功率仿真，生成供能量结算和调度使用的运行记录。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import bisect
import json
import math
import weakref

import matplotlib

from matplotlib_chinese_font import configure_matplotlib_chinese_font

from operating_conditions import (
    OperatingConditions,
    adhesion_coefficient_at,
    default_operating_conditions as _default_operating_conditions,
    operating_conditions_from_dict,
    resistance_multipliers_at,
    speed_limit_kmh_at,
)
from locomotive_curves import default_curve_bank


# 积分器可能使列车停在名义终点目标外几厘米处。3 米吸附容差仍属于数值终点容差，
# 但可避免零速状态卡在到达判定条件之外。
_TERMINAL_ENDPOINT_TOLERANCE_M = 3.0

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def configure_matplotlib_fonts() -> None:
    """优先选择系统中可用的中文字体，避免绘图告警。"""

    configure_matplotlib_chinese_font()


def default_operating_conditions() -> OperatingConditions:
    """兼容旧调用方，从列车仿真模块公开默认工况构造函数。"""

    return _default_operating_conditions()


configure_matplotlib_fonts()

_ROUTE_SEGMENT_INDEX_CACHE: Dict[
    int,
    Tuple[weakref.ReferenceType[Any], List[float], List[Any]],
] = {}


def _discard_route_segment_index(
    cache_key: int,
    route_ref: weakref.ReferenceType[Any],
) -> None:
    """函数 _discard_route_segment_index：执行该模块中的相关处理逻辑。"""
    cached = _ROUTE_SEGMENT_INDEX_CACHE.get(cache_key)
    if cached is not None and cached[0] is route_ref:
        _ROUTE_SEGMENT_INDEX_CACHE.pop(cache_key, None)


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


def _boolean_value(value: Any, field_name: str) -> bool:
    """函数 _boolean_value：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip().lower()
    if text in {"", "0", "false", "no", "n"}:
        return False
    if text in {"1", "true", "yes", "y"}:
        return True
    raise ValueError(f"{field_name} must be a recognized boolean, got {value!r}")


def _normalized_signaling_system(raw: Dict[str, Any]) -> Dict[str, Any]:
    """函数 _normalized_signaling_system：执行该模块中的相关处理逻辑。"""
    signaling = dict(raw)
    if "mode" in signaling:
        mode = str(signaling["mode"]).strip().lower()
        aliases = {
            "fixed": "fixed_block",
            "fixed_block": "fixed_block",
            "moving": "moving_block",
            "moving_block": "moving_block",
            "hybrid": "hybrid",
        }
        if mode not in aliases:
            raise ValueError(f"route.signaling_system.mode is unsupported: {signaling['mode']!r}")
        signaling["mode"] = aliases[mode]
    numeric_fields = {
        "check_step_s": (True, True),
        "fixed_block_length_km": (True, False),
        "fixed_block_protection_blocks": (False, True),
        "moving_block_base_buffer_m": (False, False),
        "moving_block_reaction_time_s": (False, False),
        "moving_block_follower_service_decel_mps2": (True, False),
        "moving_block_lead_emergency_decel_mps2": (True, False),
    }
    for field_name, (positive, whole) in numeric_fields.items():
        if field_name not in signaling:
            continue
        value = _finite_number(
            signaling[field_name],
            f"route.signaling_system.{field_name}",
        )
        if positive and value <= 0.0:
            raise ValueError(f"route.signaling_system.{field_name} must be positive")
        if not positive and value < 0.0:
            raise ValueError(f"route.signaling_system.{field_name} must be non-negative")
        if whole and not value.is_integer():
            raise ValueError(f"route.signaling_system.{field_name} must be a whole number")
        signaling[field_name] = int(value) if whole else value
    return signaling


@dataclass(frozen=True)
class Station:
    """车站信息（单位：km）。"""

    name: str
    position_km: float

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        name = str(self.name).strip()
        position = _finite_number(self.position_km, "station.position_km")
        if not name:
            raise ValueError("station.name must not be empty")
        if position < 0.0:
            raise ValueError(f"station.position_km must be non-negative, got {position!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "position_km", position)


@dataclass(frozen=True)
class Segment:
    """线路区间坡度（单位：km，‰）。"""

    start_km: float
    end_km: float
    gradient_per_mille: float
    curve_radius_m: float | None = None
    terrain: str = "plain"

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        start = _finite_number(self.start_km, "segment.start_km")
        end = _finite_number(self.end_km, "segment.end_km")
        gradient = _finite_number(self.gradient_per_mille, "segment.gradient_per_mille")
        if start < 0.0 or end <= start:
            raise ValueError(
                f"segment bounds must satisfy 0 <= start_km < end_km, got {start!r}, {end!r}"
            )
        radius = None
        if self.curve_radius_m is not None:
            radius = _finite_number(self.curve_radius_m, "segment.curve_radius_m")
            if radius <= 0.0:
                raise ValueError(f"segment.curve_radius_m must be positive, got {radius!r}")
        object.__setattr__(self, "start_km", start)
        object.__setattr__(self, "end_km", end)
        object.__setattr__(self, "gradient_per_mille", gradient)
        object.__setattr__(self, "curve_radius_m", radius)


@dataclass(frozen=True)
class RouteData:
    """线路基础设施数据。"""

    total_length_km: float
    max_speed_kmh: float
    stations: List[Station]
    segments: List[Segment]
    long_downhill_range_km: Tuple[float, float]
    energy_transfer_ranges_km: List[Tuple[float, float]]
    signaling_system: Dict[str, Any]
    operating_conditions: OperatingConditions
    # Flexible traction-power transfer facilities are distinct from storage
    # service ranges.  The legacy range list is retained for train-overlap
    # calculations; this field carries the electrical constraints.
    flexible_energy_transfer_zones: Tuple[Dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        total_length = _finite_number(self.total_length_km, "route.total_length_km")
        max_speed = _finite_number(self.max_speed_kmh, "route.max_speed_kmh")
        if total_length <= 0.0:
            raise ValueError(f"route.total_length_km must be positive, got {total_length!r}")
        if max_speed <= 0.0:
            raise ValueError(f"route.max_speed_kmh must be positive, got {max_speed!r}")
        if len(self.stations) < 2:
            raise ValueError("route.stations must contain at least two stations")
        if not self.segments:
            raise ValueError("route.segments must not be empty")
        if not isinstance(self.signaling_system, dict):
            raise ValueError("route.signaling_system must be a dictionary")
        if not isinstance(self.operating_conditions, OperatingConditions):
            raise ValueError("route.operating_conditions must be an OperatingConditions object")
        if any(not isinstance(station, Station) for station in self.stations):
            raise ValueError("route.stations must contain Station objects")
        if any(not isinstance(segment, Segment) for segment in self.segments):
            raise ValueError("route.segments must contain Segment objects")
        if any(station.position_km > total_length for station in self.stations):
            raise ValueError("route station position exceeds total_length_km")
        station_positions = [station.position_km for station in self.stations]
        if any(right < left for left, right in zip(station_positions[:-1], station_positions[1:])):
            raise ValueError("route.stations must be ordered by increasing position_km")
        if any(segment.end_km > total_length + 1e-9 for segment in self.segments):
            raise ValueError("route segment exceeds total_length_km")
        ordered_segments = sorted(self.segments, key=lambda item: (item.start_km, item.end_km))
        if ordered_segments[0].start_km > 1e-9:
            raise ValueError("route.segments must start at position 0")
        for previous, current in zip(ordered_segments[:-1], ordered_segments[1:]):
            if current.start_km < previous.end_km - 1e-9:
                raise ValueError("route.segments must not overlap")
            if current.start_km > previous.end_km + 1e-9:
                raise ValueError("route.segments must cover the route without gaps")
        if ordered_segments[-1].end_km < total_length - 1e-9:
            raise ValueError("route.segments must cover the route through total_length_km")
        try:
            downhill_start, downhill_end = self.long_downhill_range_km
        except (TypeError, ValueError) as exc:
            raise ValueError("route.long_downhill_range_km must contain two bounds") from exc
        downhill_start = _finite_number(downhill_start, "route.long_downhill_range_km[0]")
        downhill_end = _finite_number(downhill_end, "route.long_downhill_range_km[1]")
        if not 0.0 <= downhill_start <= downhill_end <= total_length:
            raise ValueError(
                "route.long_downhill_range_km must be an ordered range inside the route; "
                "equal bounds are allowed as the disabled sentinel"
            )
        energy_ranges = []
        for index, raw_range in enumerate(self.energy_transfer_ranges_km):
            try:
                start, end = raw_range
            except (TypeError, ValueError) as exc:
                raise ValueError(f"route.energy_transfer_ranges_km[{index}] is invalid") from exc
            start = _finite_number(start, f"route.energy_transfer_ranges_km[{index}][0]")
            end = _finite_number(end, f"route.energy_transfer_ranges_km[{index}][1]")
            if not 0.0 <= min(start, end) < max(start, end) <= total_length:
                raise ValueError(f"route.energy_transfer_ranges_km[{index}] must lie inside the route")
            energy_ranges.append((min(start, end), max(start, end)))
        normalized_transfer_zones = []
        for index, raw_zone in enumerate(self.flexible_energy_transfer_zones):
            if not isinstance(raw_zone, dict):
                raise ValueError(f"route.flexible_energy_transfer_zones[{index}] must be a dictionary")
            start = _finite_number(raw_zone.get("start_km"), f"route.flexible_energy_transfer_zones[{index}].start_km")
            end = _finite_number(raw_zone.get("end_km"), f"route.flexible_energy_transfer_zones[{index}].end_km")
            power = _finite_number(raw_zone.get("max_transfer_power_kW"), f"route.flexible_energy_transfer_zones[{index}].max_transfer_power_kW")
            efficiency = _finite_number(raw_zone.get("efficiency"), f"route.flexible_energy_transfer_zones[{index}].efficiency")
            if not 0.0 <= min(start, end) < max(start, end) <= total_length:
                raise ValueError(f"route.flexible_energy_transfer_zones[{index}] must lie inside the route")
            if power <= 0.0:
                raise ValueError(f"route.flexible_energy_transfer_zones[{index}] max transfer power must be positive")
            if not 0.0 < efficiency <= 1.0:
                raise ValueError(f"route.flexible_energy_transfer_zones[{index}] efficiency must be in (0, 1]")
            normalized_transfer_zones.append({
                "zone_id": str(raw_zone.get("zone_id") or f"ZONE-{index + 1:03d}"),
                "start_km": min(start, end),
                "end_km": max(start, end),
                "max_transfer_power_kW": power,
                "efficiency": efficiency,
            })
        conditions = self.operating_conditions
        for condition in conditions.weather_conditions:
            for start, end in condition.affected_ranges_km:
                if start < 0.0 or end > total_length + 1e-9:
                    raise ValueError("weather affected range exceeds route.total_length_km")
        for zone in conditions.adhesion_zones:
            if zone.start_km < 0.0 or zone.end_km > total_length + 1e-9:
                raise ValueError("adhesion zone exceeds route.total_length_km")
        for restriction in conditions.speed_restrictions:
            if restriction.start_km < 0.0 or restriction.end_km > total_length + 1e-9:
                raise ValueError("speed restriction exceeds route.total_length_km")
        object.__setattr__(self, "total_length_km", total_length)
        object.__setattr__(self, "max_speed_kmh", max_speed)
        object.__setattr__(self, "long_downhill_range_km", (downhill_start, downhill_end))
        object.__setattr__(self, "energy_transfer_ranges_km", energy_ranges)
        object.__setattr__(self, "flexible_energy_transfer_zones", tuple(normalized_transfer_zones))
        object.__setattr__(self, "signaling_system", _normalized_signaling_system(self.signaling_system))


@dataclass(frozen=True)
class DavisCoefficients:
    """戴维斯方程阻力系数（单位随公式定义）。"""

    a: float
    b: float
    c: float

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        for field_name in ("a", "b", "c"):
            value = _finite_number(getattr(self, field_name), f"davis.{field_name}")
            if value < 0.0:
                raise ValueError(f"davis.{field_name} must be non-negative, got {value!r}")
            object.__setattr__(self, field_name, value)


def locomotive_mass_tons(locomotive_type: Optional[str], locomotive_count: int) -> float:
    """按表10 的「计算重量」返回机车总质量（t）。

    查不到机型或未配置台数时返回 0，调用方据此跳过质量口径归一化。
    """

    if not locomotive_type or locomotive_count <= 0:
        return 0.0
    params = default_curve_bank().locomotive_params(str(locomotive_type).strip())
    if not params:
        return 0.0
    unit_mass = params.get("computed_mass_t")
    if unit_mass is None:
        return 0.0
    return float(unit_mass) * int(locomotive_count)


def normalise_locomotive_consist(
    consist: Optional[Iterable[Tuple[str, int]]],
) -> Tuple[Tuple[str, int], ...]:
    """把混合编组的机车清单规范化成 ``((机型, 台数), ...)``。

    朔黄重载并非单一机型担当：《列车运行图及技术资料》内页 65 明确
    「2 万吨列车由国能号 12 轴 + 国能号 8 轴交流机车固定担当」。
    智能电表实测也印证：两万吨列车会留下 233（12 轴，300 t）与 231（8 轴，200 t）
    两条记录。单一 ``locomotive_type`` + ``locomotive_count`` 无法表达这种编组，
    会把电制动能力与牵引功率都算错。
    """

    if consist is None:
        return ()
    cleaned: List[Tuple[str, int]] = []
    for item in consist:
        try:
            raw_type, raw_count = item  # type: ignore[misc]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"locomotive_consist entries must be (type, count) pairs, got {item!r}"
            ) from exc
        loco_type = str(raw_type).strip()
        if not loco_type:
            raise ValueError("locomotive_consist entry has empty locomotive type")
        count = _finite_number(raw_count, "locomotive_consist count")
        if not count.is_integer() or count < 0:
            raise ValueError(
                f"locomotive_consist count must be a non-negative whole number, got {raw_count!r}"
            )
        if int(count) == 0:
            continue
        cleaned.append((loco_type, int(count)))
    if not cleaned:
        return ()
    # 同一机型合并台数，保持顺序稳定，便于逐位复现。
    merged: Dict[str, int] = {}
    order: List[str] = []
    for loco_type, count in cleaned:
        if loco_type not in merged:
            merged[loco_type] = 0
            order.append(loco_type)
        merged[loco_type] += count
    return tuple((loco_type, merged[loco_type]) for loco_type in order)


def consist_mass_tons(consist: Tuple[Tuple[str, int], ...]) -> float:
    """混合编组的机车总质量（t）。"""

    return sum(locomotive_mass_tons(loco_type, count) for loco_type, count in consist)


@dataclass(frozen=True)
class TrainParameters:
    """列车物理参数。

    质量口径约定（重要）
    --------------------
    ``mass_tons`` 是**整列车总重**（车辆 + 机车），这是所有动力学计算的唯一口径。
    编组资料（如《2025朔黄铁路编组模式》）给出的是**车辆总重**（216 辆 C80 重车
    21600 t = 216×100 t，空车 4320 t = 216×20 t），不含机车。

    因此：当 ``locomotive_type`` 与 ``locomotive_count`` 都给定时，构造过程会把
    传入的车辆质量加上机车自重，并把原始车辆质量记到 ``vehicle_mass_tons``。
    该字段同时充当幂等标记——``dataclasses.replace()`` 会带上它，从而不会重复加质量。
    """

    name: str
    mass_tons: float
    max_traction_kN: float
    max_brake_kN: float
    rotational_mass_factor: float
    davis: DavisCoefficients
    length_km: float = 0.0
    longitudinal_segments: int = 1
    direction: str = "forward"
    traction_adhesion_weight_fraction: float = 1.0
    brake_adhesion_weight_fraction: float = 1.0
    max_power_kW: float = 0.0
    mass_data_status: str = "fixed_parameter"
    mass_min_tons: Optional[float] = None
    mass_max_tons: Optional[float] = None
    mass_note: str = ""
    locomotive_type: Optional[str] = None
    locomotive_count: int = 0
    # 混合编组的机车清单 ((机型, 台数), ...)。非空时以它为准，
    # locomotive_type/locomotive_count 自动同步为「首台机型 + 合计台数」。
    # 用于 12 轴 + 8 轴这类双机型重联（两万吨列车的实际担当方式）。
    locomotive_consist: Optional[Tuple[Tuple[str, int], ...]] = None
    # 货车载重状态（"loaded"/"empty"）。提供时货车单位基本阻力从
    # locomotive_curves.json 的表5 系数取；缺省则回退 CSV 的 davis 系数。
    freight_load_state: Optional[str] = None
    # 车辆总重（不含机车）。None 表示调用方尚未区分，构造时会按「传入值即车辆质量」归一化。
    vehicle_mass_tons: Optional[float] = None
    # 牵引功率倍率（场景敏感性专用，默认 1.0 即不改变行为）。
    # 配置了 locomotive_consist 之后，功率上限由各机型特性表逐台累加得到，
    # 不再读 CSV 的 max_power_kW；若场景只缩放 max_power_kW，倍率会被静默忽略。
    # 因此敏感性/稳健性场景必须同时把倍率写到这里。
    power_scale: float = 1.0

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        name = str(self.name).strip()
        if not name:
            raise ValueError("train.name must not be empty")
        object.__setattr__(self, "name", name)
        positive_fields = ("mass_tons", "max_traction_kN", "max_brake_kN", "power_scale")
        non_negative_fields = ("length_km", "max_power_kW")
        for field_name in positive_fields + non_negative_fields:
            value = _finite_number(getattr(self, field_name), f"train.{field_name}")
            if field_name in positive_fields and value <= 0.0:
                raise ValueError(f"train.{field_name} must be positive, got {value!r}")
            if field_name in non_negative_fields and value < 0.0:
                raise ValueError(f"train.{field_name} must be non-negative, got {value!r}")
            object.__setattr__(self, field_name, value)
        rotational = _finite_number(self.rotational_mass_factor, "train.rotational_mass_factor")
        if rotational < 1.0:
            raise ValueError(
                f"train.rotational_mass_factor must be greater than or equal to 1, got {rotational!r}"
            )
        object.__setattr__(self, "rotational_mass_factor", rotational)
        segment_count = _finite_number(self.longitudinal_segments, "train.longitudinal_segments")
        if not segment_count.is_integer() or segment_count < 1.0:
            raise ValueError(
                f"train.longitudinal_segments must be a positive whole number, got {self.longitudinal_segments!r}"
            )
        object.__setattr__(self, "longitudinal_segments", int(segment_count))
        direction = str(self.direction).strip().lower()
        if direction not in {"forward", "reverse"}:
            raise ValueError(f"train.direction must be forward or reverse, got {self.direction!r}")
        object.__setattr__(self, "direction", direction)
        for field_name in ("traction_adhesion_weight_fraction", "brake_adhesion_weight_fraction"):
            value = _finite_number(getattr(self, field_name), f"train.{field_name}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"train.{field_name} must be between 0 and 1, got {value!r}")
            object.__setattr__(self, field_name, value)

        # ---- 机车字段先规范化，质量口径归一化依赖它们 ----
        loco_type = self.locomotive_type
        if loco_type is not None:
            loco_type = str(loco_type).strip()
            object.__setattr__(self, "locomotive_type", loco_type or None)
            loco_type = loco_type or None
        loco_count = self.locomotive_count
        if isinstance(loco_count, bool) or loco_count < 0 or not float(loco_count).is_integer():
            raise ValueError(
                f"train.locomotive_count must be a non-negative whole number, got {loco_count!r}"
            )
        object.__setattr__(self, "locomotive_count", int(loco_count))

        # ---- 混合编组：提供 consist 时以它为准 ----
        # 《列车运行图及技术资料》内页 65：「2 万吨列车由国能号 12 轴 + 国能号 8 轴
        # 交流机车固定担当」。单一机型字段表达不了 12 轴 + 8 轴，必须单独给出清单。
        # 规范化后把 locomotive_type/locomotive_count 同步成「首台机型 + 合计台数」，
        # 使日志与旧接口仍可读；所有能力计算一律走 consist。
        consist = normalise_locomotive_consist(self.locomotive_consist)
        if consist:
            object.__setattr__(self, "locomotive_consist", consist)
            object.__setattr__(self, "locomotive_type", consist[0][0])
            object.__setattr__(self, "locomotive_count", sum(count for _, count in consist))
            loco_type = consist[0][0]
            loco_count = sum(count for _, count in consist)
        else:
            object.__setattr__(self, "locomotive_consist", ())

        # ---- 质量口径归一化：车辆总重 + 机车自重 = 整列车总重 ----
        # 编组资料给的是车辆总重。若调用方尚未区分（vehicle_mass_tons is None），
        # 把传入的 mass_tons 视为车辆质量并加机车；随后写入 vehicle_mass_tons 作为
        # 幂等标记，使 dataclasses.replace() 不会重复叠加。
        declared_vehicle_mass = self.vehicle_mass_tons
        if declared_vehicle_mass is not None:
            declared_vehicle_mass = _finite_number(
                declared_vehicle_mass, "train.vehicle_mass_tons"
            )
            if declared_vehicle_mass <= 0.0:
                raise ValueError(
                    f"train.vehicle_mass_tons must be positive, got {declared_vehicle_mass!r}"
                )
            object.__setattr__(self, "vehicle_mass_tons", declared_vehicle_mass)

        if declared_vehicle_mass is None:
            locomotive_mass = (
                consist_mass_tons(consist)
                if consist
                else locomotive_mass_tons(loco_type, int(loco_count))
            )
            if locomotive_mass > 0.0:
                vehicle_mass = self.mass_tons
                object.__setattr__(self, "mass_tons", vehicle_mass + locomotive_mass)
                object.__setattr__(self, "vehicle_mass_tons", vehicle_mass)
                shifted_min = self.mass_min_tons
                shifted_max = self.mass_max_tons
                if shifted_min is not None:
                    object.__setattr__(self, "mass_min_tons", float(shifted_min) + locomotive_mass)
                if shifted_max is not None:
                    object.__setattr__(self, "mass_max_tons", float(shifted_max) + locomotive_mass)
                note = str(self.mass_note or "").strip()
                vehicle_text = f"{vehicle_mass:g}"
                loco_text = f"{locomotive_mass:g}"
                object.__setattr__(
                    self,
                    "mass_note",
                    (
                        f"{note}；" if note else ""
                    )
                    + (
                        f"质量口径已归一化：车辆 {vehicle_text} t + 机车 {loco_text} t"
                        f"（{int(loco_count)} 台 × {locomotive_mass / int(loco_count):g} t）"
                        f" = 整列车 {self.mass_tons:g} t。"
                    ),
                )

        mass_bounds: Dict[str, Optional[float]] = {}
        for field_name in ("mass_min_tons", "mass_max_tons"):
            raw_value = getattr(self, field_name)
            if raw_value is None:
                mass_bounds[field_name] = None
                continue
            value = _finite_number(raw_value, f"train.{field_name}")
            if value <= 0.0:
                raise ValueError(f"train.{field_name} must be positive, got {value!r}")
            mass_bounds[field_name] = value
            object.__setattr__(self, field_name, value)
        mass_min = mass_bounds["mass_min_tons"]
        mass_max = mass_bounds["mass_max_tons"]
        if mass_min is not None and mass_max is not None and mass_min > mass_max:
            raise ValueError("train.mass_min_tons must not exceed train.mass_max_tons")
        if mass_min is not None and self.mass_tons < mass_min:
            raise ValueError("train.mass_tons must not be below train.mass_min_tons")
        if mass_max is not None and self.mass_tons > mass_max:
            raise ValueError("train.mass_tons must not exceed train.mass_max_tons")
        load_state = self.freight_load_state
        if load_state is not None:
            normalized = str(load_state).strip().lower()
            if normalized not in ("loaded", "empty"):
                raise ValueError(
                    f'train.freight_load_state must be "loaded" or "empty", got {load_state!r}'
                )
            object.__setattr__(self, "freight_load_state", normalized)


@dataclass(frozen=True)
class StorageDeviceParameters:
    """一台储能设备的静态额定参数与SOC运行边界。"""

    storage_section_id: str
    capacity_kwh: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    initial_soc_kwh: float = 0.0
    min_soc_kwh: float = 0.0
    max_soc_kwh: float | None = None
    available: bool = True
    self_discharge_rate_per_hour: float = 0.0
    data_status: str = "unknown"
    source_note: str = ""

    def __post_init__(self) -> None:
        storage_id = str(self.storage_section_id).strip()
        if not storage_id:
            raise ValueError("storage_section_id must not be blank")
        object.__setattr__(self, "storage_section_id", storage_id)
        capacity = _finite_number(self.capacity_kwh, f"storage {storage_id!r} capacity_kwh")
        if capacity <= 0.0:
            raise ValueError(f"storage {storage_id!r} capacity_kwh must be positive")
        object.__setattr__(self, "capacity_kwh", capacity)
        for field_name in ("max_charge_power_kw", "max_discharge_power_kw"):
            value = _finite_number(getattr(self, field_name), f"storage {storage_id!r} {field_name}")
            if value < 0.0:
                raise ValueError(f"storage {storage_id!r} {field_name} must be non-negative")
            object.__setattr__(self, field_name, value)
        for field_name in ("charge_efficiency", "discharge_efficiency"):
            value = _finite_number(getattr(self, field_name), f"storage {storage_id!r} {field_name}")
            if not 0.0 < value <= 1.0:
                raise ValueError(f"storage {storage_id!r} {field_name} must be in (0, 1]")
            object.__setattr__(self, field_name, value)
        minimum = _finite_number(self.min_soc_kwh, f"storage {storage_id!r} min_soc_kwh")
        maximum = capacity if self.max_soc_kwh is None else _finite_number(
            self.max_soc_kwh, f"storage {storage_id!r} max_soc_kwh"
        )
        initial = _finite_number(self.initial_soc_kwh, f"storage {storage_id!r} initial_soc_kwh")
        if not 0.0 <= minimum <= initial <= maximum <= capacity:
            raise ValueError(
                f"storage {storage_id!r} SOC bounds must satisfy "
                "0 <= min_soc_kwh <= initial_soc_kwh <= max_soc_kwh <= capacity_kwh"
            )
        object.__setattr__(self, "min_soc_kwh", minimum)
        object.__setattr__(self, "max_soc_kwh", maximum)
        object.__setattr__(self, "initial_soc_kwh", initial)
        if type(self.available) is not bool:
            raise ValueError(f"storage {storage_id!r} available must be a boolean")
        self_discharge = _finite_number(
            self.self_discharge_rate_per_hour,
            f"storage {storage_id!r} self_discharge_rate_per_hour",
        )
        if not 0.0 <= self_discharge <= 1.0:
            raise ValueError(
                f"storage {storage_id!r} self_discharge_rate_per_hour must be in [0, 1]"
            )
        object.__setattr__(self, "self_discharge_rate_per_hour", self_discharge)


@dataclass(frozen=True)
class BatteryStorageParameters:
    """储能装置参数。

    data_status 用于区分已投运实测参数、设计参数和规划情景假设。
    计算仍使用数值字段；metadata 只进入报告和可追溯性说明。
    """

    capacity_kwh: float
    round_trip_efficiency: float
    depreciation_cost_per_kwh: float
    grid_price_per_kwh: float
    max_charge_power_kW: float = 0.0
    max_discharge_power_kW: float = 0.0
    data_status: str = "unknown"
    scenario_name: str = ""
    planning_assumption: bool = False
    note: str = ""
    storage_devices: Tuple[StorageDeviceParameters, ...] = ()
    depreciation_cost_basis: str = "total_throughput"

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        non_negative_fields = (
            "capacity_kwh",
            "depreciation_cost_per_kwh",
            "grid_price_per_kwh",
            "max_charge_power_kW",
            "max_discharge_power_kW",
        )
        for field_name in non_negative_fields:
            value = _finite_number(getattr(self, field_name), field_name)
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative, got {value!r}")
            object.__setattr__(self, field_name, value)
        efficiency = _finite_number(self.round_trip_efficiency, "round_trip_efficiency")
        if not 0.0 <= efficiency <= 1.0:
            raise ValueError(f"round_trip_efficiency must be between 0 and 1, got {efficiency!r}")
        object.__setattr__(self, "round_trip_efficiency", efficiency)
        if type(self.planning_assumption) is not bool:
            raise ValueError("planning_assumption must be a boolean")
        basis = str(self.depreciation_cost_basis).strip().lower()
        if basis not in {"total_throughput", "charge_energy", "discharge_energy"}:
            raise ValueError(
                "depreciation_cost_basis must be total_throughput, charge_energy, or discharge_energy"
            )
        object.__setattr__(self, "depreciation_cost_basis", basis)
        devices = tuple(self.storage_devices)
        if any(not isinstance(item, StorageDeviceParameters) for item in devices):
            raise TypeError("storage_devices must contain StorageDeviceParameters values")
        device_ids = [item.storage_section_id for item in devices]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("storage_devices must not contain duplicate storage_section_id values")
        if devices:
            expected_totals = {
                "capacity_kwh": sum(item.capacity_kwh for item in devices),
                "max_charge_power_kW": sum(item.max_charge_power_kw for item in devices),
                "max_discharge_power_kW": sum(item.max_discharge_power_kw for item in devices),
            }
            for field_name, expected in expected_totals.items():
                actual = float(getattr(self, field_name))
                if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6):
                    raise ValueError(
                        f"battery.{field_name} {actual} does not equal the storage-device total {expected}"
                    )
        object.__setattr__(self, "storage_devices", devices)


@dataclass(frozen=True)
class SpeedProfileTarget:
    """按里程给定的目标速度曲线（前瞻式速度规划的产物）。

    用途：把「一开始就规划好整条剖面」的方案喂给仿真器，检验它**作为
    目标**是否可被真实控制器跟踪。这与仿真器原有的「看前方限速、反应
    式地压速」是完全不同的控制律：

    * 反应式：只根据当前速度与前方限速决定加/减/惰行，天然滞后；
    * 前瞻式：整条剖面的升降速早就定好了，控制器只需跟住。

    ``positions_km`` 必须单调递增，``speeds_mps`` 与之等长。
    ``slack_mps`` 是允许超出剖面的松弛量：取 0 时把剖面当硬上限，
    调大一点可以得到「剖面 + 余量」的折中（追不上时不至于一直顶着牵引上限）。

    ``lead_m`` 是读取剖面的**前视距离**，默认取一个网格步长（100 m）。
    这不是可调参数而是必需项：剖面在起点与终点被强制为 0（否则等于允许
    列车凭空有初速/到站不停），若按当前里程直读，列车在起点拿到的目标
    就是 0，永远起不来。前视一个步长既解决起步，也让降速段提前一个
    步长开始收油，与剖面的离散分辨率一致。
    """

    positions_km: Tuple[float, ...]
    speeds_mps: Tuple[float, ...]
    slack_mps: float = 0.0
    lead_m: float = 100.0
    label: str = ""

    def __post_init__(self) -> None:
        if len(self.positions_km) != len(self.speeds_mps):
            raise ValueError("速度剖面的位置与速度长度不一致")
        if len(self.positions_km) < 2:
            raise ValueError("速度剖面至少需要两个点")
        previous = None
        for position in self.positions_km:
            if previous is not None and position <= previous:
                raise ValueError("速度剖面的位置必须严格单调递增")
            previous = position
        if not math.isfinite(self.slack_mps) or self.slack_mps < 0.0:
            raise ValueError(f"slack_mps 必须为非负有限值，实际 {self.slack_mps!r}")
        if not math.isfinite(self.lead_m) or self.lead_m < 0.0:
            raise ValueError(f"lead_m 必须为非负有限值，实际 {self.lead_m!r}")

    def target_mps(self, position_km: float) -> Optional[float]:
        """线性插值出该里程处的目标速度；里程越界时返回端点值。"""

        position = float(position_km)
        positions = self.positions_km
        if position <= positions[0]:
            return self.speeds_mps[0]
        if position >= positions[-1]:
            return self.speeds_mps[-1]
        # 二分定位，避免每步线性扫描（396 km / 100 m = 3960 点 × 上万步）。
        low, high = 0, len(positions) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if positions[middle] <= position:
                low = middle
            else:
                high = middle
        span = positions[high] - positions[low]
        if span <= 0.0:
            return self.speeds_mps[low]
        ratio = (position - positions[low]) / span
        return self.speeds_mps[low] + ratio * (self.speeds_mps[high] - self.speeds_mps[low])


@dataclass(frozen=True)
class StepRecord:
    """单步仿真记录。"""
    time_s: int
    position_km: float
    speed_mps: float
    traction_kN: float
    brake_kN: float
    power_kW: float
    energy_transfer_ratio: float
    speed_limit_mps: float = 0.0
    adhesion_coefficient: float = 0.0
    traction_limit_kN: float = 0.0
    brake_limit_kN: float = 0.0
    adhesion_limited_decel_mps2: float = 0.0


def _segment_fingerprint(route: RouteData) -> Tuple[Tuple[float, float, float, float | None, str], ...]:
    """函数 _segment_fingerprint：执行该模块中的相关处理逻辑。"""
    return tuple(
        (
            float(segment.start_km),
            float(segment.end_km),
            float(segment.gradient_per_mille),
            None if segment.curve_radius_m is None else float(segment.curve_radius_m),
            str(segment.terrain),
        )
        for segment in route.segments
    )


def route_simulation_fingerprint(route: RouteData) -> tuple:
    """Return all mutable route content that affects a train trajectory."""

    conditions = route.operating_conditions
    condition_key = (
        float(conditions.default_adhesion_coefficient),
        float(conditions.traction_adhesion_safety_factor),
        float(conditions.braking_adhesion_safety_factor),
        tuple(
            (
                str(item.name),
                float(item.start_time_s),
                float(item.end_time_s),
                tuple((float(start), float(end)) for start, end in item.affected_ranges_km),
                float(item.adhesion_multiplier),
                float(item.rolling_resistance_multiplier),
                float(item.aerodynamic_resistance_multiplier),
                None if item.speed_limit_kmh is None else float(item.speed_limit_kmh),
            )
            for item in conditions.weather_conditions
        ),
        tuple(
            (
                str(item.name),
                float(item.start_km),
                float(item.end_km),
                float(item.start_time_s),
                float(item.end_time_s),
                float(item.adhesion_coefficient),
            )
            for item in conditions.adhesion_zones
        ),
        tuple(
            (
                str(item.name),
                float(item.start_km),
                float(item.end_km),
                float(item.speed_limit_kmh),
                float(item.start_time_s),
                float(item.end_time_s),
                str(item.reason),
                str(item.direction),
            )
            for item in conditions.speed_restrictions
        ),
    )
    return (
        float(route.total_length_km),
        float(route.max_speed_kmh),
        _segment_fingerprint(route),
        tuple(float(value) for value in route.long_downhill_range_km),
        tuple((float(start), float(end)) for start, end in route.energy_transfer_ranges_km),
        condition_key,
    )


def _refresh_route_segment_index(route: RouteData) -> None:
    """函数 _refresh_route_segment_index：执行该模块中的相关处理逻辑。"""
    ordered = sorted(route.segments, key=lambda item: (item.start_km, item.end_km))
    cache_key = id(route)
    route_ref = weakref.ref(
        route,
        lambda released_ref, key=cache_key: _discard_route_segment_index(
            key,
            released_ref,
        ),
    )
    _ROUTE_SEGMENT_INDEX_CACHE[cache_key] = (
        route_ref,
        [segment.start_km for segment in ordered],
        ordered,
    )


def load_config(file_path: Path) -> Tuple[RouteData, Dict[str, TrainParameters], BatteryStorageParameters]:
    """读取并解析 sandbox_config.json，或读取真实数据接口目录。"""

    if file_path.is_dir():
        from data_ingestion import load_real_data_bundle

        bundle = load_real_data_bundle(file_path)
        return bundle.route, bundle.trains, bundle.battery

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a JSON object")

    route_raw = raw.get("route")
    trains_raw = raw.get("trains")
    battery_raw = raw.get("battery")
    if not isinstance(route_raw, dict):
        raise ValueError("configuration route must be a JSON object")
    if not isinstance(trains_raw, list):
        raise ValueError("configuration trains must be a JSON array")
    if not isinstance(battery_raw, dict):
        raise ValueError("configuration battery must be a JSON object")
    station_rows = route_raw.get("stations")
    segment_rows = route_raw.get("segments")
    if not isinstance(station_rows, list):
        raise ValueError("configuration route.stations must be a JSON array")
    if not isinstance(segment_rows, list):
        raise ValueError("configuration route.segments must be a JSON array")
    if any(not isinstance(item, dict) for item in station_rows):
        raise ValueError("configuration route.stations entries must be JSON objects")
    if any(not isinstance(item, dict) for item in segment_rows):
        raise ValueError("configuration route.segments entries must be JSON objects")
    stations = [Station(**item) for item in station_rows]
    segments = [Segment(**item) for item in segment_rows]
    route = RouteData(
        total_length_km=route_raw["total_length_km"],
        max_speed_kmh=route_raw["max_speed_kmh"],
        stations=stations,
        segments=segments,
        long_downhill_range_km=tuple(route_raw["long_downhill_range_km"]),
        energy_transfer_ranges_km=[tuple(item) for item in route_raw.get("energy_transfer_ranges_km", [])],
        signaling_system=route_raw.get("signaling_system", {}),
        operating_conditions=operating_conditions_from_dict(route_raw.get("operating_conditions")),
        flexible_energy_transfer_zones=tuple(route_raw.get("flexible_energy_transfer_zones", ())),
    )

    trains: Dict[str, TrainParameters] = {}
    for index, item in enumerate(trains_raw):
        if not isinstance(item, dict):
            raise ValueError(f"configuration trains[{index}] must be a JSON object")
        davis_raw = item.get("davis")
        if not isinstance(davis_raw, dict):
            raise ValueError(f"configuration trains[{index}].davis must be a JSON object")
        davis = DavisCoefficients(**davis_raw)
        train = TrainParameters(
            name=item["name"],
            mass_tons=item["mass_tons"],
            max_traction_kN=item["max_traction_kN"],
            max_brake_kN=item["max_brake_kN"],
            rotational_mass_factor=item["rotational_mass_factor"],
            davis=davis,
            length_km=item.get("length_km", 0.0),
            longitudinal_segments=item.get("longitudinal_segments", 1),
            direction=item.get("direction", "forward"),
            traction_adhesion_weight_fraction=item.get("traction_adhesion_weight_fraction", 1.0),
            brake_adhesion_weight_fraction=item.get("brake_adhesion_weight_fraction", 1.0),
            max_power_kW=item.get("max_power_kW", 0.0),
            mass_data_status=item.get("mass_data_status", "fixed_parameter"),
            mass_min_tons=item.get("mass_min_tons"),
            mass_max_tons=item.get("mass_max_tons"),
            mass_note=item.get("mass_note", ""),
            locomotive_type=item.get("locomotive_type"),
            locomotive_count=item.get("locomotive_count", 0),
            freight_load_state=item.get("freight_load_state"),
        )
        if train.name in trains:
            raise ValueError(f"duplicate normalized train name: {train.name!r}")
        trains[train.name] = train

    battery = BatteryStorageParameters(
        capacity_kwh=battery_raw["capacity_kwh"],
        max_charge_power_kW=battery_raw.get("max_charge_power_kW", 0.0),
        max_discharge_power_kW=battery_raw.get("max_discharge_power_kW", 0.0),
        round_trip_efficiency=battery_raw["round_trip_efficiency"],
        depreciation_cost_per_kwh=battery_raw["depreciation_cost_per_kwh"],
        grid_price_per_kwh=battery_raw["grid_price_per_kwh"],
        data_status=battery_raw.get("data_status", "unknown"),
        scenario_name=battery_raw.get("scenario_name", ""),
        planning_assumption=_boolean_value(
            battery_raw.get("planning_assumption", False), "battery.planning_assumption"
        ),
        note=battery_raw.get("note", ""),
    )
    return route, trains, battery


def get_gradient_per_mille(route: RouteData, current_x_km: float) -> float:
    """按里程查找当前坡度（‰）。"""

    segment = get_segment(route, current_x_km)
    return 0.0 if segment is None else segment.gradient_per_mille


def get_segment(route: RouteData, current_x_km: float) -> Segment | None:
    """按里程查找当前线路分段。"""

    if not route.segments:
        return None
    cache_key = id(route)
    cached = _ROUTE_SEGMENT_INDEX_CACHE.get(cache_key)
    if cached is None or cached[0]() is not route:
        _refresh_route_segment_index(route)
        cached = _ROUTE_SEGMENT_INDEX_CACHE[cache_key]
    _route_ref, starts, ordered = cached
    position = max(0.0, min(current_x_km, route.total_length_km - 1e-6))
    idx = bisect.bisect_right(starts, position) - 1
    idx = max(0, min(idx, len(ordered) - 1))
    segment = ordered[idx]
    if segment.start_km <= position < segment.end_km:
        return segment
    if idx + 1 < len(ordered) and ordered[idx + 1].start_km <= position < ordered[idx + 1].end_km:
        return ordered[idx + 1]
    return segment


def get_curve_equivalent_per_mille(route: RouteData, current_x_km: float) -> float:
    """将曲线附加阻力近似折算为等效坡度（‰）。"""

    segment = get_segment(route, current_x_km)
    if segment is None or segment.curve_radius_m is None or segment.curve_radius_m <= 0.0:
        return 0.0
    return 600.0 / segment.curve_radius_m


def position_in_ranges(position_km: float, ranges_km: List[Tuple[float, float]]) -> bool:
    """判断里程是否处于任一区间。"""

    return any(start <= position_km <= end for start, end in ranges_km)


def train_sample_positions(route: RouteData, train: TrainParameters, head_position_km: float) -> List[float]:
    """沿列车长度生成采样点，0 为车头，末点接近车尾。"""

    sample_count = max(1, int(train.longitudinal_segments))
    train_length_km = max(0.0, train.length_km)
    if sample_count == 1 or train_length_km == 0.0:
        return [max(0.0, min(head_position_km, route.total_length_km - 1e-6))]

    positions = []
    direction_sign = -1.0 if train.direction == "forward" else 1.0
    for idx in range(sample_count):
        offset_km = train_length_km * idx / (sample_count - 1)
        position_km = head_position_km + direction_sign * offset_km
        positions.append(max(0.0, min(position_km, route.total_length_km - 1e-6)))
    return positions


def _normalized_ranges_km(ranges_km: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Drop empty/tiny placeholder ranges that must not activate control logic.

    Datasets still ship long_downhill_range_km=[0.0, 0.001] as a disabled stub.
    Treating that stub as a real zone incorrectly forces braking near the origin.
    """
    cleaned: List[Tuple[float, float]] = []
    for start, end in ranges_km or []:
        lo = float(min(start, end))
        hi = float(max(start, end))
        if hi - lo < 0.05:
            continue
        cleaned.append((lo, hi))
    return cleaned


def train_range_ratio(
    route: RouteData,
    train: TrainParameters,
    head_position_km: float,
    ranges_km: List[Tuple[float, float]],
) -> float:
    """???????????????????"""

    cleaned = _normalized_ranges_km(list(ranges_km or []))
    if not cleaned:
        return 0.0
    positions = train_sample_positions(route, train, head_position_km)
    hits = sum(1 for position in positions if position_in_ranges(position, cleaned))
    return hits / len(positions)


def effective_mass_factor(train: TrainParameters) -> float:
    """Return the configured equivalent-mass multiplier.

    ``TrainParameters.rotational_mass_factor`` is a multiplicative factor
    (the input contract requires ``>= 1``), not an additive ``rho`` term.
    Treating the valid boundary value ``1.0`` as ``1 + rho`` would therefore
    double the train mass and distort both traction and regenerative energy.
    """

    return float(train.rotational_mass_factor)


def _average_capped_force_power_kW(
    force_kN: float,
    start_speed_mps: float,
    end_speed_mps: float,
    active_fraction: float,
    power_cap_kW: float,
) -> float:
    """Integrate min(force * speed, power cap) over a linear-speed interval."""

    if force_kN <= 0.0 or active_fraction <= 0.0:
        return 0.0
    fraction = max(0.0, min(1.0, active_fraction))
    start_speed = max(0.0, start_speed_mps)
    end_speed = max(0.0, end_speed_mps)
    if power_cap_kW <= 0.0:
        return force_kN * 0.5 * (start_speed + end_speed) * fraction

    threshold_speed = power_cap_kW / force_kN

    def capped_power_antiderivative(speed_mps: float) -> float:
        """函数 capped_power_antiderivative：执行该模块中的相关处理逻辑。"""
        if speed_mps <= threshold_speed:
            return 0.5 * force_kN * speed_mps * speed_mps
        return power_cap_kW * speed_mps - 0.5 * power_cap_kW * power_cap_kW / force_kN

    speed_delta = end_speed - start_speed
    if abs(speed_delta) <= 1e-12:
        active_average_kW = min(force_kN * start_speed, power_cap_kW)
    else:
        active_average_kW = (
            capped_power_antiderivative(end_speed)
            - capped_power_antiderivative(start_speed)
        ) / speed_delta
    return max(0.0, active_average_kW) * fraction


def _fraction_to_cover_distance(
    start_speed_mps: float,
    end_speed_mps: float,
    step_s: float,
    distance_m: float,
) -> float:
    """Return the fraction of a step needed to cover ``distance_m``.

    The simulator integrates a linear within-step speed profile.  When that
    profile reaches a terminal before the nominal step ends, using the full
    step's average power overstates traction/regeneration.  A short bisection
    keeps the calculation stable for acceleration, braking, and speed-clamped
    profiles without introducing a second kinematic model.
    """

    if step_s <= 0.0 or distance_m <= 0.0:
        return 0.0
    start_speed = max(0.0, float(start_speed_mps))
    end_speed = max(0.0, float(end_speed_mps))
    total_distance = 0.5 * (start_speed + end_speed) * step_s
    if distance_m >= total_distance - 1e-12:
        return 1.0
    if total_distance <= 1e-12:
        return 0.0
    low = 0.0
    high = step_s
    for _ in range(60):
        mid = 0.5 * (low + high)
        fraction = mid / step_s
        speed_mid = start_speed + (end_speed - start_speed) * fraction
        travelled = 0.5 * (start_speed + speed_mid) * mid
        if travelled < distance_m:
            low = mid
        else:
            high = mid
    return max(0.0, min(1.0, high / step_s))


def calculate_forces(
    train: TrainParameters,
    route: RouteData,
    current_x_km: float,
    current_v_mps: float,
    global_time_s: int = 0,
) -> Tuple[float, float, float]:
    """计算基本阻力与坡道阻力（单位：kN）。"""

    sample_positions = train_sample_positions(route, train, current_x_km)
    mass_kg = train.mass_tons * 1000.0
    segment_mass_kg = mass_kg / len(sample_positions)

    rolling_multiplier_sum = 0.0
    aerodynamic_multiplier_sum = 0.0
    rg_kN = 0.0
    rc_kN = 0.0
    gradient_sum = 0.0
    for position_km in sample_positions:
        rolling_multiplier, aerodynamic_multiplier = resistance_multipliers_at(
            route.operating_conditions,
            position_km,
            global_time_s,
        )
        rolling_multiplier_sum += rolling_multiplier
        aerodynamic_multiplier_sum += aerodynamic_multiplier

        gradient = get_gradient_per_mille(route, position_km)
        if train.direction == "reverse":
            gradient = -gradient
        curve_equivalent = get_curve_equivalent_per_mille(route, position_km)
        gradient_sum += gradient
        rg_kN += (segment_mass_kg * 9.81 * (gradient / 1000.0)) / 1000.0
        rc_kN += (segment_mass_kg * 9.81 * (curve_equivalent / 1000.0)) / 1000.0

    average_gradient = gradient_sum / len(sample_positions)
    rolling_multiplier = rolling_multiplier_sum / len(sample_positions)
    aerodynamic_multiplier = aerodynamic_multiplier_sum / len(sample_positions)
    # 单位基本阻力 w0' = a + b*v + c*v^2，单位 N/kN（v 单位 km/h，见 TB/T 1407.1-2018 式(1)/(3)）。
    # 总基本阻力(kN) = w0'(N/kN) × 质量(t) × 9.81(kN/t) / 1000。
    # 坡道阻力 rg_kN 已按同一量纲（i‰ × 质量 × 9.81 / 1000）计算，两者可直接相加。
    v_kmh = max(0.0, current_v_mps * 3.6)
    rb_kN = _basic_resistance_kN(train, v_kmh, rolling_multiplier, aerodynamic_multiplier)
    return rb_kN + rc_kN, rg_kN, average_gradient


def _basic_resistance_kN(
    train: TrainParameters,
    v_kmh: float,
    rolling_multiplier: float,
    aerodynamic_multiplier: float,
) -> float:
    """计算列车基本阻力（kN）。

    优先按机车（表2系数）+ 货车（表5系数）分开加权；当未配置 locomotive_type
    或查不到机车系数时，回退到 ``train.davis`` 作为整列车系数（向后兼容）。
    """

    # 货车单位基本阻力系数：优先用 TB/T 1407.1-2018 表5 的系数（按载重状态），
    # 未配置载重状态时回退 CSV 的 davis 列（向后兼容）。
    bank = default_curve_bank()
    freight_a, freight_b, freight_c = train.davis.a, train.davis.b, train.davis.c
    if train.freight_load_state and (freight_a == 0.0 and freight_b == 0.0 and freight_c == 0.0):
        table5 = bank.freight_resistance_coeffs(train.freight_load_state)
        if table5 and all(table5.get(k) is not None for k in ("A", "B", "C")):
            freight_a, freight_b, freight_c = table5["A"], table5["B"], table5["C"]
    freight_w0 = (
        (freight_a + freight_b * v_kmh) * rolling_multiplier
        + freight_c * v_kmh**2 * aerodynamic_multiplier
    )
    if not (train.locomotive_consist or (train.locomotive_type and train.locomotive_count and train.locomotive_count > 0)):
        return freight_w0 * train.mass_tons * 9.81 / 1000.0

    wagon_w0 = freight_w0  # 货车系数（表5 或回退的 CSV davis）

    if train.locomotive_consist:
        loco_rb = 0.0
        total_loco_mass_t = 0.0
        has_any = False
        for l_type, l_count in train.locomotive_consist:
            if l_count <= 0:
                continue
            coeffs = bank.locomotive_resistance_coeffs(l_type)
            params = bank.locomotive_params(l_type)
            if not coeffs or not params or not params.get("computed_mass_t"):
                continue
            has_any = True
            m_t = float(params["computed_mass_t"]) * l_count
            total_loco_mass_t += m_t
            w0 = (
                (coeffs["A"] + coeffs["B"] * v_kmh) * rolling_multiplier
                + coeffs["C"] * v_kmh**2 * aerodynamic_multiplier
            )
            loco_rb += w0 * m_t * 9.81 / 1000.0
        if not has_any:
            return freight_w0 * train.mass_tons * 9.81 / 1000.0
        total_loco_mass_t = min(total_loco_mass_t, train.mass_tons)
        wagon_mass_t = train.mass_tons - total_loco_mass_t
        wagon_rb = wagon_w0 * wagon_mass_t * 9.81 / 1000.0
        return loco_rb + wagon_rb

    loco_coeffs = bank.locomotive_resistance_coeffs(train.locomotive_type)
    loco_params = bank.locomotive_params(train.locomotive_type)
    if not loco_coeffs or not loco_params or not loco_params.get("computed_mass_t"):
        # 查不到机车系数或单机质量时，退回整列车单套系数。
        return freight_w0 * train.mass_tons * 9.81 / 1000.0

    loco_mass_t = float(loco_params["computed_mass_t"]) * train.locomotive_count
    loco_mass_t = min(loco_mass_t, train.mass_tons)
    wagon_mass_t = train.mass_tons - loco_mass_t

    loco_w0 = (
        (loco_coeffs["A"] + loco_coeffs["B"] * v_kmh) * rolling_multiplier
        + loco_coeffs["C"] * v_kmh**2 * aerodynamic_multiplier
    )

    loco_rb = loco_w0 * loco_mass_t * 9.81 / 1000.0
    wagon_rb = wagon_w0 * wagon_mass_t * 9.81 / 1000.0
    return loco_rb + wagon_rb


def train_speed_limit_mps(
    route: RouteData,
    train: TrainParameters,
    head_position_km: float,
    global_time_s: int,
) -> float:
    """Return the most restrictive speed limit over the sampled train length."""

    # 朔黄线路基础场景通常没有天气和临时限速。此时整列车的限速就是线路
    # 上限，不需要为每个纵向采样点重复查询同一个静态条件。
    profile = route.operating_conditions
    if not profile.weather_conditions and not profile.speed_restrictions:
        return max(5.0, route.max_speed_kmh) / 3.6

    limits_kmh = [
        speed_limit_kmh_at(
            route.operating_conditions,
            route.max_speed_kmh,
            position_km,
            global_time_s,
            train.direction,
        )
        for position_km in train_sample_positions(route, train, head_position_km)
    ]
    return min(limits_kmh) / 3.6


def train_adhesion_coefficient(
    route: RouteData,
    train: TrainParameters,
    head_position_km: float,
    global_time_s: int,
) -> float:
    """Return a conservative train-level adhesion coefficient."""

    return min(
        adhesion_coefficient_at(route.operating_conditions, position_km, global_time_s)
        for position_km in train_sample_positions(route, train, head_position_km)
    )


def adhesion_force_limits(
    route: RouteData,
    train: TrainParameters,
    head_position_km: float,
    global_time_s: int,
    current_v_mps: float = 0.0,
) -> Tuple[float, float, float, float]:
    """Return adhesion-limited traction/brake forces and brake deceleration.

    制动黏着系数采用 TB/T 1407.1-2018 式(52)干燥轨面的速度相关公式，
    与线路/天气调制后的基准值取较小者（保留保守性）。
    牵引黏着：SS 系列用式(55) 计算；HXD 等交流传动机车标准未给静态黏着公式，
    沿用基准系数（交流机车黏着由牵引控制动态调节）。
    """

    mu = train_adhesion_coefficient(route, train, head_position_km, global_time_s)
    brake_mu = mu
    bank = default_curve_bank()
    speed_kmh = max(0.0, current_v_mps * 3.6)
    std_brake_mu = bank.brake_adhesion_coefficient(speed_kmh, "dry")
    if std_brake_mu is not None:
        # 标准式(52)干燥轨面制动黏着；取较小值避免在低速/潮湿区段高估黏着。
        brake_mu = min(mu, std_brake_mu)
    # 牵引黏着：SS 系列（直流传动）标准给出式(55) 速度相关公式，直接采用；
    # HXD 等交流传动无静态公式，保持基准系数不变。
    traction_mu = mu
    locomotive_types = (
        [l_type for l_type, _ in train.locomotive_consist]
        if train.locomotive_consist
        else ([train.locomotive_type] if train.locomotive_type else [])
    )
    if any("SS" in lt.upper() for lt in locomotive_types):
        std_traction_mu = bank.traction_adhesion_coefficient(speed_kmh, "SS")
        if std_traction_mu is not None:
            traction_mu = std_traction_mu
    mass_kg = train.mass_tons * 1000.0
    traction_weight = max(0.0, min(1.0, train.traction_adhesion_weight_fraction))
    brake_weight = max(0.0, min(1.0, train.brake_adhesion_weight_fraction))
    # 牵引黏着重量：只有机车产生牵引黏着，货车不参与。
    # 配置了 locomotive_consist 或 locomotive_type 时用表10 的黏着重量 × 台数（真实值）；
    # 否则回退到「整列车质量 × traction_adhesion_weight_fraction」的旧估算。
    loco_adhesion_mass_t = None
    if train.locomotive_consist:
        total_adh_mass = 0.0
        has_any = False
        for l_type, l_count in train.locomotive_consist:
            if l_count <= 0:
                continue
            l_params = bank.locomotive_params(l_type)
            if l_params and l_params.get("adhesion_mass_t"):
                total_adh_mass += float(l_params["adhesion_mass_t"]) * l_count
                has_any = True
        if has_any:
            loco_adhesion_mass_t = min(total_adh_mass, train.mass_tons)
    elif train.locomotive_type and train.locomotive_count and train.locomotive_count > 0:
        loco_params = bank.locomotive_params(train.locomotive_type)
        if loco_params and loco_params.get("adhesion_mass_t"):
            loco_adhesion_mass_t = float(loco_params["adhesion_mass_t"]) * train.locomotive_count
            loco_adhesion_mass_t = min(loco_adhesion_mass_t, train.mass_tons)
    if loco_adhesion_mass_t is not None:
        traction_limit_kN = (
            traction_mu
            * loco_adhesion_mass_t
            * 1000.0
            * 9.81
            * route.operating_conditions.traction_adhesion_safety_factor
            / 1000.0
        )
    else:
        traction_limit_kN = (
            traction_mu
            * mass_kg
            * 9.81
            * traction_weight
            * route.operating_conditions.traction_adhesion_safety_factor
            / 1000.0
        )
    brake_limit_kN = (
        brake_mu
        * mass_kg
        * 9.81
        * brake_weight
        * route.operating_conditions.braking_adhesion_safety_factor
        / 1000.0
    )
    available_brake_decel = (brake_limit_kN * 1000.0) / (mass_kg * effective_mass_factor(train))
    return mu, traction_limit_kN, brake_limit_kN, available_brake_decel


def lookahead_speed_target_mps(
    route: RouteData,
    train: TrainParameters,
    head_position_km: float,
    current_v_mps: float,
    global_time_s: int,
    local_speed_limit_mps: float,
    adhesion_limited_decel_mps2: float,
    schedule: Optional["TrainSchedule"] = None,
    elapsed_s: Optional[float] = None,
) -> float:
    """Reduce target speed before a lower temporary speed limit or the terminal."""

    direction_sign = 1.0 if train.direction == "forward" else -1.0
    # 规划减速度低于黏着限制，使离散步仍可修正而不产生较大超调。
    comfortable_decel = max(0.06, min(0.25, adhesion_limited_decel_mps2 * 0.55))
    lookahead_km = max(3.0, (current_v_mps**2 / (2.0 * comfortable_decel)) / 1000.0 + 1.5)
    lookahead_km = min(12.0, lookahead_km)

    # 相对于公布限速保留低速裕度。
    target_mps = max(0.0, local_speed_limit_mps - 0.6)
    step_km = 0.25
    step_count = max(1, int(lookahead_km / step_km))
    for idx in range(1, step_count + 1):
        distance_km = idx * step_km
        future_head_km = head_position_km + direction_sign * distance_km
        if future_head_km < 0.0 or future_head_km > route.total_length_km:
            break

        travel_time_s = int((distance_km * 1000.0) / max(current_v_mps, 1.0))
        future_limit_mps = train_speed_limit_mps(route, train, future_head_km, global_time_s + travel_time_s)
        future_target_mps = max(0.0, future_limit_mps - 0.6)
        if future_target_mps >= target_mps:
            continue

        # 提前开始制动：在下限边界前预留缓冲。
        distance_m = max(0.0, distance_km * 1000.0 - 1500.0)
        allowed_now_mps = math.sqrt(max(0.0, future_target_mps**2 + 2.0 * comfortable_decel * distance_m))
        target_mps = min(target_mps, allowed_now_mps)

    # 检查运行图中的停站约束（dep > arr）提前开始减速
    if schedule is not None and elapsed_s is not None:
        direction_forward = train.direction == "forward"
        for stop_pos, arr_s, dep_s in schedule.stops:
            if dep_s <= arr_s + 1e-9:
                continue
            if elapsed_s >= dep_s:
                continue
            dist_km = (stop_pos - head_position_km) if direction_forward else (head_position_km - stop_pos)
            if 0.0 < dist_km <= 5.0:
                remain_stop_m = max(0.0, dist_km * 1000.0 - 2.0)
                sched_stop_target = math.sqrt(max(0.0, 2.0 * comfortable_decel * remain_stop_m))
                if remain_stop_m <= 1000.0:
                    sched_stop_target = min(sched_stop_target, max(0.0, remain_stop_m / 25.0))
                target_mps = min(target_mps, sched_stop_target)

    # 终点接近阶段采用更早、更保守的停车曲线，避免离散积分器以线路速度到达终点。
    if train.direction == "forward":
        remain_m = max(0.0, (route.total_length_km - head_position_km) * 1000.0)
    else:
        remain_m = max(0.0, head_position_km * 1000.0)
    # 使用低于绝对黏着限制的规划减速度。
    stop_decel = max(0.05, min(0.22, adhesion_limited_decel_mps2 * 0.55))
    # 只预留数值终点容差。减去过大的固定缓冲会使目标在到达终点前很早变为零，
    # 从而形成牵引/制动限幅循环，而不是连续停车。
    braking_distance_m = max(0.0, remain_m - 2.0)
    terminal_target_mps = math.sqrt(max(0.0, 2.0 * stop_decel * braking_distance_m))
    # 进入最后一公里后，施加独立于规划加速度的更严格速度上限。
    if remain_m <= 1000.0:
        terminal_target_mps = min(terminal_target_mps, max(0.0, remain_m / 25.0))
    return min(target_mps, terminal_target_mps)




@dataclass(frozen=True)
class TrainSchedule:
    """按图定区间时分约束的运行图（「按图定时」）。

    每个区间的时长来自《列车运行图及技术资料》的「列车区间运行时分」表。

    **约束方式：剩余时间驱动。** 每一步计算「到下一站（或终点）的剩余距离
    ÷ 剩余图定时间」，把它作为速度上限，与线路允许速度取小：

    * 若列车跑得快、时间有富余，该比值小 → 压制速度，慢下来；
    * 若列车在加速段落后，该比值自动变大 → 放开限制，追回时间；
    * 因此到站时刻会收敛到图定时刻，而不是像「区间均速当上限」那样
      因为加速损失而系统性晚点。

    ``stops`` 为 ``((position_km, arrive_s, depart_s), ...)``，
    **按行车方向排列**（forward 里程递增，reverse 递减）。
    ``arrive_s`` 是到达该站的图定时刻，``depart_s`` 是发车时刻；
    两者之差即**停站作业时分**（含起车/停车附加与技术作业）。

    为兼容旧调用，也接受 ``(position_km, cumulative_s)`` 二元组，
    此时视作 ``arrive = depart = cumulative``（不停站）。

    已知简化
    --------
    * 区间约束用「通通时分」；起车/停车附加与站停作业通过 ``dwell`` 施加。
    * 距下一站不足 ``terminal_buffer_m`` 时不再压制，避免速度被压到零而停滞。
    * 已晚点（剩余时间为负）时不再压制，保持物理可行性。
    """

    stops: Tuple[Tuple[float, float, float], ...]
    label: str = ""
    terminal_buffer_m: float = 120.0

    def __post_init__(self) -> None:
        cleaned: List[Tuple[float, float, float]] = []
        for stop in self.stops:
            if len(stop) == 2:
                position, arrive = stop  # type: ignore[misc]
                depart = arrive
            elif len(stop) == 3:
                position, arrive, depart = stop  # type: ignore[misc]
            else:
                raise ValueError(f"schedule 停靠点应为 2 或 3 元组，实际 {stop!r}")
            pos_f = float(position)
            arr_f = float(arrive)
            dep_f = float(depart)
            if not (math.isfinite(pos_f) and math.isfinite(arr_f) and math.isfinite(dep_f)):
                raise ValueError(f"schedule 停靠点存在非有限值：{stop!r}")
            if arr_f < 0.0:
                raise ValueError(f"schedule 到站时间不能为负：{arr_f!r}")
            if dep_f < arr_f - 1e-9:
                raise ValueError(
                    f"schedule 发车时刻不能早于到站时刻：{arr_f!r} -> {dep_f!r}"
                )
            cleaned.append((pos_f, arr_f, dep_f))
        if len(cleaned) < 2:
            raise ValueError("schedule 至少需要 2 个停靠点")
        for (_, _, d0), (_, a1, _) in zip(cleaned, cleaned[1:]):
            # 上一站发车必须早于下一站到达
            if a1 <= d0:
                raise ValueError(f"schedule 时刻必须递增：发车 {d0!r} -> 到站 {a1!r}")
        positions = [p for p, _, _ in cleaned]
        increasing = all(b > a for a, b in zip(positions, positions[1:]))
        decreasing = all(b < a for a, b in zip(positions, positions[1:]))
        if not (increasing or decreasing):
            raise ValueError("schedule 停靠点里程必须单调（递增或递减）")
        object.__setattr__(self, "stops", tuple(cleaned))

    @property
    def forward(self) -> bool:
        return self.stops[1][0] > self.stops[0][0]

    @classmethod
    def from_sections(
        cls,
        sections: Sequence[Tuple[float, float, float]],
        dwell_minutes: Optional[Sequence[float]] = None,
        label: str = "",
    ) -> "TrainSchedule":
        """由 ``((start_km, end_km, through_minutes), ...)`` 构造。

        ``dwell_minutes[i]`` 是第 ``i`` 段**末站**的停站作业时分（分钟），
        应已包含起车/停车附加。缺省全为 0（不停站通过）。
        """

        if not sections:
            raise ValueError("sections 不能为空")
        dwells = list(dwell_minutes) if dwell_minutes is not None else []
        stops: List[Tuple[float, float, float]] = [(float(sections[0][0]), 0.0, 0.0)]
        clock = 0.0
        for index, (_, end, minutes) in enumerate(sections):
            arrive = clock + float(minutes) * 60.0
            dwell = float(dwells[index]) * 60.0 if index < len(dwells) else 0.0
            if dwell < 0.0:
                raise ValueError(f"停站时分不能为负：{dwell!r}")
            depart = arrive + dwell
            stops.append((float(end), arrive, depart))
            clock = depart
        return cls(stops=tuple(stops), label=label)

    def speed_cap_mps(
        self,
        position_km: float,
        elapsed_s: float,
        dwell_only: bool = False,
    ) -> Optional[float]:
        """返回剩余时间驱动的速度上限（m/s）；不需要压制时返回 None。

        若列车已到站但尚未到图定发车时刻，返回 ``0.0`` —— 仿真会据此
        把速度压到零，实现「停车等待」而不是「区间内慢行」。

        ``dwell_only=True`` 时只返回「到站等待」这一条约束（``0.0`` 或 ``None``），
        不再用「剩余距离 ÷ 剩余时间」压区间平均速度。

        两种模式对**通过点**的处理不同，这一点必须分开：
        通过点的 ``arr == dep``，它表达的是「不得晚于这个时刻到达」，
        而不是「不得早到」。若也按「早到就等」处理，跑得快反而要在每个
        通过点停一次——实测会凭空多出 30 次起停、约 +8,000 kWh
        （见 outputs/traction_attribution/）。所以 ``dwell_only`` 下只在
        ``dep > arr``（真的停站作业）的位置等待。
        """

        position = float(position_km)
        elapsed = float(elapsed_s)
        forward = self.forward
        for (pos_a, arr_a, dep_a), (pos_b, arr_b, _dep_b) in zip(self.stops, self.stops[1:]):
            inside = (
                pos_a <= position < pos_b if forward else pos_b < position <= pos_a
            )
            if not inside:
                continue
            if elapsed < dep_a:
                if dwell_only and dep_a <= arr_a + 1e-9:
                    # 通过点：早到不算违章，直接放行，不在这里停车等待。
                    pass
                else:
                    # 列车已进入本区间的起点站范围，但图定发车时刻未到 -> 站停
                    return 0.0
            if dwell_only:
                return None
            remaining_m = abs(pos_b - position) * 1000.0
            remaining_s = arr_b - elapsed
            if remaining_s <= 0.0:
                return None  # 已晚点，不再压制
            if remaining_m <= self.terminal_buffer_m:
                return None  # 贴近下一站，避免压到停滞
            return remaining_m / remaining_s
        return None

    def total_minutes(self) -> float:
        return (self.stops[-1][2] - self.stops[0][1]) / 60.0

    def running_minutes(self) -> float:
        """纯区间运行时分（不含站停）。"""

        return sum(arr_b - dep_a for (_, _, dep_a), (_, arr_b, _) in zip(self.stops, self.stops[1:]))

    def dwell_minutes(self) -> float:
        """总停站作业时分。"""

        return sum(dep - arr for _, arr, dep in self.stops)


@dataclass(frozen=True)
class BrakeStrategy:
    """制动分配策略：需求制动力如何在电制动与空气制动之间分摊。

    背景
    ----
    原实现假定「电制动优先、用满曲线能力」：
    ``electrical_brake = min(需求制动力, 机车电制动曲线能力)``。
    这等价于认为司机把电制动手柄放到最大级位、直到曲线允许为止。

    实绩（智能电表 5,869 趟，神池南→肃宁北Ⅱ场）显示并非如此：
    两万吨双机合并反馈约 27,600 kWh，只相当于下坡势能的 28%；
    若按满级位测算，同一线路可回收约 48%。差额被空气制动（闸瓦）吃掉。

    参数
    ----
    ``electrical_level``
        电制动**投入级位**，即实际电制动力占「机车电制动曲线能力」的份额。
        ``1.0`` 表示用满曲线，``0.0`` 表示完全不用电制动。
        物理含义是司机把手柄放在某一固定级位循环制动，而不是按需求逐级调节；
        这也是重载长下坡的常规操纵方式（电制动粗调 + 空气制动细调）。

        默认 ``0.48`` 由实绩标定得到（``tools/calibrate_brake_strategy.py``）：
        神池南→肃宁北Ⅱ场 396 km，12 轴机车单机拉两万吨的最优级位 0.50、
        拉万吨的最优级位 0.46，两者极差 0.04。取中位 0.48。

        该值标定在**按图定时**的操纵轨迹上（仿真均速 56.9 km/h，实绩 58.1 km/h，
        来自电表 ``lxsd`` 字段——注意不能用 ``endtime − starttime`` 算，
        那里面含 97 min 出库/挂车/入库）。若今后修正了轨迹，需要重标。

    制动力总量不变
    --------------
    该参数**只改变电制动与空气制动的分摊**，不改变总制动力，
    因此列车速度轨迹逐位不变，仅再生电量随级位变化。
    这使得标定可以离线完成：记录一次 ``brake_kN`` 与速度序列即可扫遍所有级位。

    ``coast_band_mps``
        惰行带宽度（m/s）。目标速度是一个点，但真实司机不会拿它当伺服给定：
        实际操纵里速度在一个带内浮动，超出上沿才上闸、低于下沿才提手柄，
        中间**惰行**（既不给牵引也不给制动）。

        ``0.02`` 是原实现的等效值——目标速度外 0.02 m/s 就立刻制动，
        等价于没有惰行带，列车在下坡上「贴线跑」：一超速就制动耗散势能，
        一上坡又得重新牵引。重载长下坡的真实操纵是让速度在带内自由漂。

        该参数不改变限速安全约束（``local_speed_limit_mps`` 仍逐位生效），
        只放宽「相对目标速度」的容差。

    ``traction_droop_mps``
        允许的**掉速**（m/s）。原实现只容许比目标速度低 1.8 m/s 就提手柄，
        相当于把速度死死钉在目标上。真实重载司机不会追速：上坡就让它掉，
        掉到某个下限才补，靠下坡再挣回来。

        与 ``coast_band_mps`` 一起构成速度带的下沿与上沿，中间是惰行。
        默认 0.0 逐位保持原行为。

    ``downhill_traction_fraction``
        下坡牵引允许份额。判据是**剩余力**：当坡度与阻力之和使列车惰行时加速
        （``-(rb + rg) > 0``），司机通常把牵引手柄回零，让它自己漂；
        原实现不做区分，在需要维持目标速度时照样给牵引。
        实测后果是 **52.5% 的牵引电量花在下坡上**（见 ``tools/diagnose_energy_balance.py``），
        这在物理上说不通——下坡的重力本来就在推着车走。

        ``1.0`` 表示下坡与平路同等对待（原行为，逐位不变）；
        ``0.0`` 表示下坡完全不牵引，只惰行或制动。

        该参数是**策略**层面的，不是机车能力：机车在下坡当然能出力，
        是司机不这么做。因此它改变了速度轨迹（不再追目标速度），
        与 ``electrical_level`` 那种「只改分摊、不改轨迹」的参数性质不同。

    """

    electrical_level: float = 0.48
    # 标定来源：tools/calibrate_brake_strategy.py，报告见 outputs/brake_calibration/
    coast_band_mps: float = 0.02
    traction_droop_mps: float = 0.0
    downhill_traction_fraction: float = 1.0
    note: str = ""

    def __post_init__(self) -> None:
        level = _finite_number(self.electrical_level, "brake_strategy.electrical_level")
        if not 0.0 <= level <= 1.0:
            raise ValueError(
                f"brake_strategy.electrical_level must be between 0 and 1, got {level!r}"
            )
        object.__setattr__(self, "electrical_level", level)
        band = _finite_number(self.coast_band_mps, "brake_strategy.coast_band_mps")
        if band < 0.0:
            raise ValueError(
                f"brake_strategy.coast_band_mps must be non-negative, got {band!r}"
            )
        object.__setattr__(self, "coast_band_mps", band)
        droop = _finite_number(self.traction_droop_mps, "brake_strategy.traction_droop_mps")
        if droop < 0.0:
            raise ValueError(
                f"brake_strategy.traction_droop_mps must be non-negative, got {droop!r}"
            )
        object.__setattr__(self, "traction_droop_mps", droop)
        downhill = _finite_number(
            self.downhill_traction_fraction,
            "brake_strategy.downhill_traction_fraction",
        )
        if not 0.0 <= downhill <= 1.0:
            raise ValueError(
                "brake_strategy.downhill_traction_fraction must be between 0 and 1, "
                f"got {downhill!r}"
            )
        object.__setattr__(self, "downhill_traction_fraction", downhill)


class TrainSimulator:
    """单车运动学仿真器（欧拉法）。"""

    def __init__(
        self,
        route: RouteData,
        train: TrainParameters,
        delta_t_s: float = 1.0,
        start_time_s: int = 0,
        schedule: Optional[TrainSchedule] = None,
        brake_strategy: Optional[BrakeStrategy] = None,
        schedule_speed_cap: str = "strict",
        speed_profile: Optional[SpeedProfileTarget] = None,
        profile_mode: str = "cap",
    ) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        self.route = route
        self.train = train
        # 前瞻式速度剖面：为 None 时行为与原先完全一致（反应式控制）。
        # 非 None 时把剖面当作目标速度上限，用于检验「规划出的剖面能否被真正开出来」。
        self.speed_profile = speed_profile
        # 剖面的用法：
        #   "cap"   —— 只把剖面当速度上限，控制律仍是反应式的追限值逻辑；
        #   "track" —— 前馈跟踪：按剖面斜率反算所需合力，直接下指令。
        if profile_mode not in {"cap", "track"}:
            raise ValueError(
                f"profile_mode must be 'cap' or 'track', got {profile_mode!r}"
            )
        if profile_mode == "track" and speed_profile is None:
            raise ValueError("profile_mode='track' 需要同时提供 speed_profile")
        self.profile_mode = profile_mode
        # 「按图定时」约束：为 None 时行为与原先完全一致。
        self.schedule = schedule
        # 按图定时的**实现方式**：
        #   "strict" —— 逐区间用「剩余距离 ÷ 剩余时间」压速（原行为，逐位不变）。
        #               效果等价于把车速钉在该区间的平均速度上，因此下坡也不许跑快。
        #   "dwell"  —— 区间内允许跑满线路限速，富余时间在**车站等待**里吸收。
        #               这是真实运营方式（区间是纯运行时分，冗余放在站停/缓冲）。
        #               只保留「已到站但未到发车时刻 → 停车等待」这一条约束。
        if schedule_speed_cap not in {"strict", "dwell"}:
            raise ValueError(
                "schedule_speed_cap must be 'strict' or 'dwell', "
                f"got {schedule_speed_cap!r}"
            )
        self.schedule_speed_cap = schedule_speed_cap
        # 制动分配策略：为 None 时等价于「电制动用满曲线能力」，与原先一致。
        self.brake_strategy = brake_strategy or BrakeStrategy()
        # RouteData 本身不可变，但其区段列表可变；每次仿真重新构建一次，避免原地修改线路后复用过期索引。
        _refresh_route_segment_index(route)
        # 当前步记录使用整数秒时间戳；非整数步长会把多个样本压到同一秒，破坏能量积分。
        if isinstance(delta_t_s, bool):
            raise ValueError(f"delta_t_s must be a finite positive whole number, got {delta_t_s!r}")
        try:
            delta = float(delta_t_s)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"delta_t_s must be a finite positive whole number, got {delta_t_s!r}") from exc
        if not math.isfinite(delta) or delta <= 0.0:
            raise ValueError(f"delta_t_s must be a finite positive whole number, got {delta_t_s!r}")
        if abs(delta - round(delta)) > 1e-9:
            raise ValueError(
                f"delta_t_s must be an integer number of seconds for stable energy sampling, got {delta_t_s}"
            )
        self.delta_t_s = float(int(round(delta)))
        if isinstance(start_time_s, bool):
            raise ValueError(f"start_time_s must be a finite non-negative whole number, got {start_time_s!r}")
        try:
            start_time = float(start_time_s)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"start_time_s must be a finite non-negative whole number, got {start_time_s!r}") from exc
        if not math.isfinite(start_time) or not start_time.is_integer() or start_time < 0.0:
            raise ValueError(f"start_time_s must be a finite non-negative whole number, got {start_time_s!r}")
        self.start_time_s = int(start_time)
        self.speed_limit_mps = route.max_speed_kmh / 3.6
        # 式(72) 再生电量电流积分校核路径的累积量（run() 结束后可读）。
        self.regen_current_time_a_s = 0.0
        self.regen_energy_from_current_kWh: Optional[float] = None
        self.regen_current_network_voltage_kV: Optional[float] = None

    def locomotive_units(self) -> Tuple[Tuple[str, int], ...]:
        """整列车的机车清单 ``((机型, 台数), ...)``，混合编组时为多项。

        优先使用 ``locomotive_consist``；未配置时退化为单一机型的
        ``locomotive_type``/``locomotive_count``，保持旧数据行为不变。
        """

        consist = getattr(self.train, "locomotive_consist", ()) or ()
        if consist:
            return tuple(consist)
        loco_type = self.train.locomotive_type
        count = self.train.locomotive_count
        if loco_type and count > 0:
            return ((loco_type, int(count)),)
        return ()

    def electrical_brake_force_limit_kN(self, current_v_mps: float) -> float:
        """整列车在当前速度下可用的电制动力上限（kN）。

        由机车特性曲线（``locomotive_curves.json``）插值得到单台机车电制动力，
        按编组清单逐机型累加；电阻制动机车（SS4 系列）不产生可回收的再生能量，
        对总和无贡献。未配置任何机车时返回 0，由调用方回退到旧的功率截断逻辑。
        """

        units = self.locomotive_units()
        if not units:
            return 0.0
        bank = default_curve_bank()
        speed_kmh = max(0.0, current_v_mps * 3.6)
        total = 0.0
        for loco_type, count in units:
            if count <= 0 or not bank.is_regenerative(loco_type):
                continue
            per_loco_kN = bank.brake_force_kN(loco_type, speed_kmh)
            if per_loco_kN is None:
                continue
            total += float(per_loco_kN) * count
        return total

    def effective_electrical_brake_limit_kN(self, current_v_mps: float) -> float:
        """当前速度下**实际投入**的电制动力上限（kN）。

        等于「电制动曲线能力 × 投入级位」。级位来自 ``BrakeStrategy``：
        重载长下坡时司机把手柄放在固定级位循环制动，电制动只承担一部分
        需求制动力，其余由空气制动补足。``electrical_level=1.0`` 时与原行为一致。
        """

        return self.brake_strategy.electrical_level * self.electrical_brake_force_limit_kN(
            current_v_mps
        )

    def locomotive_traction_limit_kN(self) -> float:
        """整列车由机车牵引能力决定的牵引力上限（kN）。

        由表 10 的单台机车最大起动牵引力 × 台数 × 多机折减系数推导；
        未配置 ``locomotive_type`` 时返回 0，由调用方回退到 CSV 的 max_traction_kN。
        朔黄重载为重联同步操纵，折减系数取全值 1.0（TB/T 1407.1-2018 5.4 节）。
        """

        units = self.locomotive_units()
        if not units:
            return 0.0
        bank = default_curve_bank()
        total = 0.0
        saw_any = False
        for loco_type, count in units:
            if count <= 0:
                continue
            params = bank.locomotive_params(loco_type)
            if not params:
                continue
            max_start_kN = params.get("max_start_traction_kN")
            if max_start_kN is None:
                continue
            # 多机折减：系数从 locomotive_curves.json 的 multi_loco_derating（5.4 节）读取。
            # 朔黄重载为多机重联同步操纵，系数为 1.0（全值）；分别操纵 0.98、推送补机 0.95。
            derating = bank.multi_loco_derating_factor("coupled")
            total += float(max_start_kN) * count * derating
            saw_any = True
        return total if saw_any else 0.0

    def power_cap_kW(self) -> float:
        """整列车牵引功率上限（kW），控制逻辑与能耗结算共用同一口径。

        配置了 ``locomotive_type`` 时，用表 10 的持续牵引力 × 持续速度反推单台持续功率，
        再乘台数；未配置时回退到 CSV 的 ``max_power_kW``。两种路径最后都乘
        ``train.power_scale``（场景倍率，默认 1.0）。

        此前控制逻辑与能耗结算各算一遍功率上限，前者用表 10 反推值、后者用 CSV 值，
        当两者不等时（例如 4×HXD1 反推 38 400 kW 而 CSV 写 28 800 kW），
        牵引力按高值给、电量按低值记，能耗被系统性低估。
        """

        units = self.locomotive_units()
        if units:
            bank = default_curve_bank()
            total_power_kW = 0.0
            saw_power = False
            for loco_type, count in units:
                if count <= 0:
                    continue
                per_loco_power_kW = bank.locomotive_power_kW(loco_type)
                if per_loco_power_kW:
                    total_power_kW += float(per_loco_power_kW) * count
                    saw_power = True
            if saw_power:
                # 场景倍率必须作用在这里：consist 生效时 CSV 的 max_power_kW 不再参与计算。
                return total_power_kW * self.train.power_scale
        cap_kW = float(getattr(self.train, "max_power_kW", 0.0) or 0.0)
        if cap_kW <= 0.0:
            # 根据低基础速度（约 18 km/h）下的力近似连续功率。
            cap_kW = max(self.train.max_traction_kN, self.train.max_brake_kN) * 5.0
        return cap_kW * self.train.power_scale

    def _profile_tracking_forces(
        self,
        current_x_km: float,
        current_v_mps: float,
        rb_kN: float,
        rg_kN: float,
        traction_limit_kN: float,
        brake_limit_kN: float,
        power_cap_kW: float,
    ) -> Tuple[float, float]:
        """前馈跟踪：按剖面「下一步应该在哪」反算合力。

        做法是取**前视点**上剖面的速度，用运动学反算「要在该点达到计划速度
        所需的加速度」：

            Δ      = max(v·Δt, 50 m)                 前视距离
            a_cmd  = (v_plan(x+Δ)² − v²) / (2·Δ)     匀加速运动学
            F      = m_eff · a_cmd + 基本阻力 + 坡道阻力

        ``F > 0`` 牵引，``F < 0`` 制动，再按牵引/制动/功率上限截断。

        **写成 v² 差而不是速度差，是这个控制律能同时适配任意步长的关键。**
        最初写成 ``(v_plan(x+Δ) − v_plan(x)) / Δt``：前视距离里有 ``v·Δt``
        而在低速时被下限钳到 50 m，Δ 与 Δt 就不再匹配，``dt=10`` 时系数
        偏小、``dt=1`` 时被放大 10 倍，同一份剖面在 ``dt=1`` 下直接死锁在
        3.3 km。用 v² 差后 Δ 与 Δt 解耦，两种步长给出同一条轨迹。

        Δ 的下限是必需的：起步时 ``v = 0 ⇒ Δ = 0``，取到的两点重合，
        加速度恒为 0，列车永远不动。50 m 对应起步段 0.06 m/s² 的下限，
        与牵引力上限同量级，不会给出超过车辆能力的指令。
        """

        profile = self.speed_profile
        assert profile is not None  # 由 profile_mode 校验保证
        lead_m = max(current_v_mps * float(self.delta_t_s), 50.0)
        direction_sign = 1.0 if self.train.direction == "forward" else -1.0
        v_plan_next = profile.target_mps(current_x_km + direction_sign * lead_m / 1000.0)
        if v_plan_next is None:  # pragma: no cover - target_mps 不会返回 None
            return 0.0, 0.0
        planned_accel = (v_plan_next * v_plan_next - current_v_mps * current_v_mps) / (
            2.0 * lead_m
        )
        mass_kg = self.train.mass_tons * 1000.0 * effective_mass_factor(self.train)
        force_kN = mass_kg * planned_accel / 1000.0 + rb_kN + rg_kN
        if force_kN >= 0.0:
            traction_kN = min(force_kN, traction_limit_kN)
            if current_v_mps > 0.5 and power_cap_kW > 0.0:
                traction_kN = min(traction_kN, power_cap_kW / current_v_mps)
            return traction_kN, 0.0
        return 0.0, min(-force_kN, brake_limit_kN)

    def control_traction_brake(
        self,
        current_x_km: float,
        current_v_mps: float,
        rb_kN: float,
        rg_kN: float,
        global_time_s: int,
        elapsed_s: Optional[float] = None,
    ) -> Tuple[float, float, bool, float, float, float, float, float]:
        """基于动态限速和黏着上限的牵引/制动控制。"""

        local_speed_limit_mps = train_speed_limit_mps(self.route, self.train, current_x_km, global_time_s)
        # 按图定时：用「剩余距离 ÷ 剩余图定时间」压制速度。
        # 只收紧、不放宽，因此不会突破线路允许速度；已晚点时该方法返回 None。
        # 注意 cap 可以为 0：表示列车已到站但未到图定发车时刻，需要停车等待。
        # 这一步不能过滤 0，否则站停会退化成「在区间里继续跑」。
        if self.schedule is not None and elapsed_s is not None:
            schedule_cap_mps = self.schedule.speed_cap_mps(
                current_x_km,
                elapsed_s,
                dwell_only=self.schedule_speed_cap == "dwell",
            )
            if schedule_cap_mps is not None:
                # "dwell" 模式只保留 cap == 0（到站等待）这一条，
                # 区间内的平均速度压制不再生效——否则下坡也被钉在均速上，
                # 势能一点都存不下来（见 outputs/traction_attribution/）。
                if self.schedule_speed_cap == "strict" or schedule_cap_mps <= 1e-9:
                    local_speed_limit_mps = min(local_speed_limit_mps, schedule_cap_mps)
        (
            adhesion_coefficient,
            traction_adhesion_limit_kN,
            brake_adhesion_limit_kN,
            adhesion_limited_decel_mps2,
        ) = adhesion_force_limits(self.route, self.train, current_x_km, global_time_s, current_v_mps)
        traction_limit_kN = min(self.train.max_traction_kN, traction_adhesion_limit_kN)
        # 配置了 locomotive_type 时，牵引力上限改用机车台数 × 单机最大起动牵引力（表10），
        # 更贴近实际机车能力；未配置时回退到 CSV 的 max_traction_kN 虚拟值。
        loco_traction_limit = self.locomotive_traction_limit_kN()
        if loco_traction_limit > 0.0:
            traction_limit_kN = min(traction_limit_kN, loco_traction_limit)
        # 机械制动仍受制动力和黏着限制。功率只限制牵引和制动中可回收的电气部分，
        # 剩余制动部分仍为机械制动。
        brake_limit_kN = min(self.train.max_brake_kN, brake_adhesion_limit_kN)
        # 仅使用占位牵引力限制会在高速下产生异常大的牵引功率（F*v）。
        # 功率上限统一由 self.power_cap_kW() 给出，保证控制与能耗结算口径一致。
        power_cap_kW = self.power_cap_kW()
        if current_v_mps > 0.5 and power_cap_kW > 0.0:
            force_from_power_kN = power_cap_kW / current_v_mps
            traction_limit_kN = min(traction_limit_kN, force_from_power_kN)

        # 前瞻式剖面的**前馈跟踪**模式：直接按剖面的斜率要求合力，
        # 而不是「低于目标才牵引、高于目标才制动」的追限值逻辑。
        # 两者差别就是「按计划开」与「看见限速才反应」的差别，
        # 这正是 `verify_speed_profile_realizable` 要测量的东西。
        if self.speed_profile is not None and self.profile_mode == "track":
            traction_kN, brake_kN = self._profile_tracking_forces(
                current_x_km,
                current_v_mps,
                rb_kN,
                rg_kN,
                traction_limit_kN,
                brake_limit_kN,
                power_cap_kW,
            )
            return (
                traction_kN,
                brake_kN,
                False,
                local_speed_limit_mps,
                adhesion_coefficient,
                traction_limit_kN,
                brake_limit_kN,
                adhesion_limited_decel_mps2,
            )

        v_target = lookahead_speed_target_mps(
            self.route,
            self.train,
            current_x_km,
            current_v_mps,
            global_time_s,
            local_speed_limit_mps,
            adhesion_limited_decel_mps2,
            schedule=self.schedule,
            elapsed_s=elapsed_s,
        )
        if self.train.direction == "forward":
            remain_m = max(0.0, (self.route.total_length_km - current_x_km) * 1000.0)
        else:
            remain_m = max(0.0, current_x_km * 1000.0)
        # 接近终点时逐步收紧目标速度，但在进入终点容差前仍允许低速牵引。
        near_terminal = remain_m <= 800.0
        terminal_stop_zone = remain_m <= _TERMINAL_ENDPOINT_TOLERANCE_M
        if near_terminal:
            terminal_approach_target_mps = max(0.5, remain_m / 30.0)
            v_target = min(v_target, terminal_approach_target_mps)
            if terminal_stop_zone:
                v_target = 0.0
        # 与步长相关的低速裕度：积分步越大，越需要相对于公布限速保留更大缓冲，
        # 以避免下坡惰行时 Euler 积分超调。经验上 dt=10 需要约 1.2—1.5 m/s 缓冲；
        # 设置软上限，避免细步长受到过度限制。
        step_margin_mps = min(2.2, max(0.35, 0.14 * float(self.delta_t_s)))
        v_target = min(v_target, max(0.0, local_speed_limit_mps - step_margin_mps))
        # 前瞻式剖面：把规划好的目标速度也作为上限。只收紧、不放宽，
        # 因此不会突破线路允许速度与按图定时约束——剖面是「建议怎么开」，
        # 不是「允许开多快」。
        # 终点接近段（最后 800 m）不套剖面：剖面末点被强制为 0，加上前视
        # 会把目标提前压到 0，列车会停在离终点一个前视距离的地方出不来；
        # 这一段本来就由下面的终点停车曲线专门负责。
        if self.speed_profile is not None and not near_terminal:
            lead_km = self.speed_profile.lead_m / 1000.0
            if self.train.direction != "forward":
                lead_km = -lead_km
            profile_target_mps = self.speed_profile.target_mps(current_x_km + lead_km)
            if profile_target_mps is not None:
                v_target = min(v_target, profile_target_mps + self.speed_profile.slack_mps)
        in_long_downhill = (
            train_range_ratio(self.route, self.train, current_x_km, [self.route.long_downhill_range_km]) > 0.0
        )
        # 坡度/阻力剩余力。正值表示列车惰行时会加速，长下坡中较常见。
        residual_force_kN = -(rb_kN + rg_kN)
        speed_error = current_v_mps - v_target
        limit_error = current_v_mps - local_speed_limit_mps
        # 下坡牵引策略：剩余力为正时重力已经在推车，司机一般把牵引手柄回零。
        # 只收缩牵引上限，不触碰制动与限速——安全约束不受影响。
        downhill_fraction = self.brake_strategy.downhill_traction_fraction
        if downhill_fraction < 1.0 and residual_force_kN > 0.0:
            traction_limit_kN *= downhill_fraction
        mass_kg = self.train.mass_tons * 1000.0 * effective_mass_factor(self.train)
        coast_accel = (residual_force_kN * 1000.0) / max(mass_kg, 1.0)
        projected_coast_v = max(0.0, current_v_mps + coast_accel * float(self.delta_t_s))
        # 惰行带：超出目标速度这个宽度才上闸，带内自由惰行（见 BrakeStrategy）。
        coast_band = self.brake_strategy.coast_band_mps
        gravity_will_overspeed = residual_force_kN > 0.0 and (
            projected_coast_v > local_speed_limit_mps - 0.05
            or projected_coast_v > v_target + coast_band
        )
        traction_deadband_mps = (
            max(0.8, step_margin_mps + 0.4) + self.brake_strategy.traction_droop_mps
        )
        if near_terminal:
            traction_deadband_mps = max(
                0.05,
                min(traction_deadband_mps, 0.25 * v_target),
            )

        traction_kN = 0.0
        brake_kN = 0.0

        # 出现超速、预计下坡超调、长下坡停车或接近终点时优先制动；
        # 不能在一个积分步内可能突破限速的坡段继续惰行。
        if (
            speed_error > coast_band
            or limit_error > -0.05
            or gravity_will_overspeed
            or (in_long_downhill and current_v_mps >= v_target - 0.1)
            or terminal_stop_zone
        ):
            # 一次求解单步运动方程。预计惰行误差已包含下坡/阻力剩余项；
            # 再加入单独的保持力和比例修正会重复计算同一坡度加速度，导致制动/牵引循环。
            projected_error = max(0.0, projected_coast_v - v_target)
            brake_kN = (
                mass_kg
                * projected_error
                / max(1000.0 * float(self.delta_t_s), 1.0)
            )
            if near_terminal:
                mass_kg = self.train.mass_tons * 1000.0
                desired_stop_decel = min(
                    0.35,
                    (current_v_mps ** 2) / max(2.0 * max(remain_m, 1.0), 1.0),
                )
                # 滚动/曲线阻力和上坡已经提供部分所需减速度；此处下坡剩余力为负，
                # 因此会增加所需制动力。
                stop_demand_kN = max(
                    0.0,
                    (
                        mass_kg
                        * effective_mass_factor(self.train)
                        * desired_stop_decel
                    )
                    / 1000.0
                    - (rb_kN + rg_kN),
                )
                brake_kN = max(brake_kN, stop_demand_kN)
            brake_kN = min(brake_kN, brake_limit_kN)
        # 只有明显低于目标且远离终点时才加速；接近目标的区间保持惰行，避免限值追逐。
        elif (not terminal_stop_zone) and current_v_mps < v_target - traction_deadband_mps:
            # 温和接近目标；列车接近目标速度时逐步减小加速度。
            speed_gap = max(0.0, v_target - current_v_mps)
            desired_accel = min(0.12, 0.03 + 0.03 * speed_gap)
            desired_accel = min(
                desired_accel,
                speed_gap / float(self.delta_t_s),
            )
            mass_kg = self.train.mass_tons * 1000.0
            traction_needed_kN = (mass_kg * effective_mass_factor(self.train) * desired_accel) / 1000.0
            traction_needed_kN += rb_kN + rg_kN
            if traction_needed_kN < 0.0:
                traction_needed_kN = 0.0
            traction_kN = min(traction_needed_kN, traction_limit_kN)
            # 仅在粗步长开始时限制牵引力，列车加速后可能超过连续功率额定值。
            # 求解恒力终点关系 F * v_end <= P 并直接降低指令，避免运动模型接收未计量能量。
            effective_mass_kg = mass_kg * effective_mass_factor(self.train)
            speed_gain_per_kN = 1000.0 * float(self.delta_t_s) / effective_mass_kg
            projected_end_speed_mps = current_v_mps + speed_gain_per_kN * (
                traction_kN - rb_kN - rg_kN
            )
            if (
                traction_kN > 0.0
                and projected_end_speed_mps > current_v_mps
                and traction_kN * projected_end_speed_mps > power_cap_kW
            ):
                linear_term = current_v_mps - speed_gain_per_kN * (rb_kN + rg_kN)
                endpoint_power_force_kN = (
                    -linear_term
                    + math.sqrt(
                        linear_term * linear_term
                        + 4.0 * speed_gain_per_kN * power_cap_kW
                    )
                ) / (2.0 * speed_gain_per_kN)
                traction_kN = min(traction_kN, endpoint_power_force_kN)

        return (
            traction_kN,
            brake_kN,
            in_long_downhill,
            local_speed_limit_mps,
            adhesion_coefficient,
            traction_limit_kN,
            brake_limit_kN,
            adhesion_limited_decel_mps2,
        )

    def run(self, max_time_s: int = 40000) -> List[StepRecord]:
        """Run single-train simulation and return step records."""

        results: List[StepRecord] = []
        total_length_m = self.route.total_length_km * 1000.0
        direction_sign = 1.0 if self.train.direction == "forward" else -1.0
        x_m = 0.0 if self.train.direction == "forward" else total_length_m
        v_mps = 0.0
        # 式(72) 电流积分校核：只对具备再生能力的机车累加 I_z·t。
        # 混合编组时按机型分别查 I_z(v)，再乘各自台数。
        regen_bank = default_curve_bank()
        loco_units = self.locomotive_units()
        regen_units = [
            (loco_type, count)
            for loco_type, count in loco_units
            if count > 0 and regen_bank.is_regenerative(loco_type)
        ]
        regen_enabled = bool(regen_units)
        regen_current_time_a_s = 0.0
        # 使用浮点累计时钟，避免小数 delta_t_s 使循环停滞。
        elapsed_s = 0.0
        delta_t_s = float(self.delta_t_s)
        if delta_t_s <= 0.0:
            raise ValueError(f"delta_t_s must be positive, got {self.delta_t_s}")
        max_time = _finite_number(max_time_s, "max_time_s")
        if not max_time.is_integer() or max_time <= 0.0:
            raise ValueError(f"max_time_s must be a finite positive whole number, got {max_time_s!r}")

        def not_arrived(position_m: float) -> bool:
            """函数 not_arrived：执行该模块中的相关处理逻辑。"""
            if self.train.direction == "forward":
                return position_m < total_length_m - 1e-6
            return position_m > 1e-6

        def append_record(
            time_s: int,
            position_km: float,
            speed_mps: float,
            traction_kN: float,
            brake_kN: float,
            power_kW: float,
            energy_transfer_ratio: float,
            speed_limit_mps: float,
            adhesion_coefficient: float,
            traction_limit_kN: float,
            brake_limit_kN: float,
            adhesion_limited_decel_mps2: float,
        ) -> None:
            """函数 append_record：执行该模块中的相关处理逻辑。"""
            results.append(
                StepRecord(
                    time_s=int(time_s),
                    position_km=position_km,
                    speed_mps=speed_mps,
                    traction_kN=traction_kN,
                    brake_kN=brake_kN,
                    power_kW=power_kW,
                    energy_transfer_ratio=energy_transfer_ratio,
                    speed_limit_mps=speed_limit_mps,
                    adhesion_coefficient=adhesion_coefficient,
                    traction_limit_kN=traction_limit_kN,
                    brake_limit_kN=brake_limit_kN,
                    adhesion_limited_decel_mps2=adhesion_limited_decel_mps2,
                )
            )

        while not_arrived(x_m) and elapsed_s < max_time:
            current_x_km = x_m / 1000.0
            t_s = int(round(elapsed_s))
            global_time_s = self.start_time_s + t_s

            rb_kN, rg_kN, _gradient = calculate_forces(
                self.train,
                self.route,
                current_x_km,
                v_mps,
                global_time_s,
            )
            (
                traction_kN,
                brake_kN,
                _in_long_downhill,
                speed_limit_mps,
                adhesion_coefficient,
                traction_limit_kN,
                brake_limit_kN,
                adhesion_limited_decel_mps2,
            ) = self.control_traction_brake(
                current_x_km,
                v_mps,
                rb_kN,
                rg_kN,
                global_time_s,
                elapsed_s,
            )

            # 下方指令作用于整个积分区间，因此电能必须使用区间平均速度，而不是区间起始速度。
            # 此处计算 F*v 曾使首次加速步被记为零能量，并系统性高估减速过程的再生能量。
            # 功率上限与 control_traction_brake 共用 self.power_cap_kW()，避免两处口径不一致。
            power_cap_kW = self.power_cap_kW()
            energy_transfer_ratio = train_range_ratio(
                self.route,
                self.train,
                current_x_km,
                self.route.energy_transfer_ranges_km,
            )

            # ????????
            f_net_kN = traction_kN - brake_kN - rb_kN - rg_kN
            mass_kg = self.train.mass_tons * 1000.0
            accel = (f_net_kN * 1000.0) / (mass_kg * effective_mass_factor(self.train))

            # ???????????
            unconstrained_v_next = v_mps + accel * delta_t_s
            v_next = max(0.0, unconstrained_v_next)
            # 粗粒度 Euler 步的硬安全限制：积分后不得报告超过当地公布限速的状态。
            # 超出的动能视为在该步内由额外机械制动消除。
            if speed_limit_mps >= 0.0 and v_next > speed_limit_mps:
                v_next = speed_limit_mps
            # 保留名义线性曲线的末速度。下方到达处理会将报告状态设为零，但跨过终点时该状态
            # 不代表列车实际到达终点时的速度。
            profile_end_speed_mps = v_next
            # 计算指令生效期间的平均速度。若指令减速度会使列车在本步结束前停车，只有实际运动的
            # 时间部分能够产生再生功率。
            if unconstrained_v_next < 0.0 and accel < 0.0:
                stop_time_s = min(delta_t_s, v_mps / -accel)
                motion_fraction = stop_time_s / delta_t_s
                power_end_speed_mps = 0.0
                average_motion_speed_mps = 0.5 * v_mps * motion_fraction
            else:
                motion_fraction = 1.0
                power_end_speed_mps = v_next
                average_motion_speed_mps = 0.5 * (v_mps + v_next)
            # 使用与能量计算相同的步内速度曲线积分距离。整个区间使用 v_next 会使加速步走得过远，
            # 也会使制动至停车的步长移动零米，从而在车站附近产生虚假的牵引/制动循环。
            x_next = x_m + direction_sign * average_motion_speed_mps * delta_t_s
            arrived = False
            if self.train.direction == "forward":
                remain_m = max(0.0, total_length_m - x_m)
            else:
                remain_m = max(0.0, x_m)
            # 只有进入数值终点容差后才算完全到达。较宽的终点接近区仍允许控制器施加牵引，
            # 避免低速列车被直接“传送”数百米。
            stopped_near_terminal = (
                v_next <= 0.05
                and remain_m <= _TERMINAL_ENDPOINT_TOLERANCE_M
            )
            # 粗步长即使在低速下也可能跨过数米。若跨越距离超过终点数值容差，不能直接将车头吸附到终点，
            # 应让下一步完成最后的接近过程。
            crawl_distance_limit_m = min(3.0, abs(v_next) * delta_t_s + 0.5)
            crawl_onto_terminal = remain_m <= max(1.0, crawl_distance_limit_m) and v_next <= 1.0
            if stopped_near_terminal or crawl_onto_terminal:
                x_next = total_length_m if self.train.direction == "forward" else 0.0
                v_next = 0.0
                arrived = True
            elif self.train.direction == "forward" and x_next >= total_length_m:
                x_next = total_length_m
                v_next = 0.0
                arrived = True
            elif self.train.direction == "reverse" and x_next <= 0.0:
                x_next = 0.0
                v_next = 0.0
                arrived = True

            # 粗步长可能在列车仍运动时跨过终点。此前实现保留整个步长的平均功率，
            # 但实际只走过部分区间，造成再生/牵引能量过多。下游结算仍保留名义时间网格，
            # 但将有效功率区间按实际行驶距离缩放。
            if arrived and motion_fraction >= 1.0:
                travel_fraction = _fraction_to_cover_distance(
                    v_mps,
                    profile_end_speed_mps,
                    delta_t_s,
                    remain_m,
                )
                motion_fraction = min(motion_fraction, travel_fraction)
                power_end_speed_mps = max(
                    0.0,
                    v_mps + (profile_end_speed_mps - v_mps) * travel_fraction,
                )
            traction_power_kW = _average_capped_force_power_kW(
                traction_kN,
                v_mps,
                power_end_speed_mps,
                motion_fraction,
                power_cap_kW,
            )
            # 电气制动功率由机车电制动曲线限定的电制动力决定；超出部分为空气/电阻制动，
            # 不能计入可回收再生能量。未配置 locomotive_type 时回退到旧功率截断逻辑。
            # 「投入级位」由 BrakeStrategy 给出：实际电制动力只占曲线能力的一部分，
            # 其余制动力需求由空气制动承担（总制动力不变，速度轨迹不受影响）。
            electric_brake_force_limit_kN = self.effective_electrical_brake_limit_kN(
                0.5 * (v_mps + power_end_speed_mps)
            )
            if self.train.locomotive_type and self.train.locomotive_count > 0:
                # 机车特性曲线模式：电气制动力 = min(需求制动力, 实际投入的电制动上限)。
                electrical_brake_kN = min(brake_kN, electric_brake_force_limit_kN)
                electrical_brake_power_kW = _average_capped_force_power_kW(
                    electrical_brake_kN,
                    v_mps,
                    power_end_speed_mps,
                    motion_fraction,
                    power_cap_kW,
                )
            else:
                # 旧回退：用功率上限截断，超出功率的制动力属于机械制动。
                electrical_brake_kN = 0.0
                electrical_brake_power_kW = _average_capped_force_power_kW(
                    brake_kN,
                    v_mps,
                    power_end_speed_mps,
                    motion_fraction,
                    power_cap_kW,
                )
            # 式(72) 再生电量电流积分校核路径：按当前速度查单台满负荷再生电流 I_z(v)，
            # 用「实际电制动力 / 满级位电制动曲线能力」的负荷率缩放，再乘台数与有效时长。
            # 电阻制动（非再生）机车 regen_enabled=False，不累加。
            if regen_enabled and electrical_brake_kN > 0.0 and electric_brake_force_limit_kN > 0.0:
                avg_v_mps = max(0.0, 0.5 * (v_mps + power_end_speed_mps))
                avg_v_kmh = avg_v_mps * 3.6
                full_electric_brake_limit_kN = self.electrical_brake_force_limit_kN(avg_v_mps)
                denom_limit_kN = (
                    full_electric_brake_limit_kN
                    if full_electric_brake_limit_kN > 0.0
                    else electric_brake_force_limit_kN
                )
                load_ratio = min(1.0, electrical_brake_kN / denom_limit_kN)
                for regen_loco_type, regen_count in regen_units:
                    per_loco_current_A = regen_bank.regen_current_A(regen_loco_type, avg_v_kmh)
                    if not per_loco_current_A:
                        continue
                    regen_current_time_a_s += (
                        per_loco_current_A * regen_count * load_ratio * delta_t_s * motion_fraction
                    )
            power_kW = traction_power_kW - electrical_brake_power_kW

            append_record(
                t_s,
                current_x_km,
                v_mps,
                traction_kN,
                brake_kN,
                power_kW,
                energy_transfer_ratio,
                speed_limit_mps,
                adhesion_coefficient,
                traction_limit_kN,
                brake_limit_kN,
                adhesion_limited_decel_mps2,
            )

            x_m = x_next
            v_mps = v_next
            elapsed_s += delta_t_s

            if arrived:
                # 记录停车到达状态，使功率缓存包含终点。
                final_t = int(round(elapsed_s))
                final_x_km = x_m / 1000.0
                final_limit = train_speed_limit_mps(
                    self.route, self.train, final_x_km, self.start_time_s + final_t
                )
                mu, t_lim, b_lim, decel = adhesion_force_limits(
                    self.route, self.train, final_x_km, self.start_time_s + final_t
                )
                append_record(
                    final_t,
                    final_x_km,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    train_range_ratio(
                        self.route,
                        self.train,
                        final_x_km,
                        self.route.energy_transfer_ranges_km,
                    ),
                    final_limit,
                    mu,
                    t_lim,
                    b_lim,
                    decel,
                )
                break

        if not_arrived(x_m):
            raise RuntimeError(
                f"Train simulation did not reach the terminal within {int(max_time)} s; "
                f"last_position_km={x_m / 1000.0:.6f}, train={self.train.name!r}"
            )
        # 记录式(72) 电流积分校核结果，供外部与力学折算路径对比（不改变 records 内容）。
        self.regen_current_time_a_s = regen_current_time_a_s
        self.regen_current_network_voltage_kV = regen_bank.regen_network_voltage_kV()
        if regen_enabled:
            self.regen_energy_from_current_kWh = regen_bank.regen_energy_kWh_from_current_A_s(
                regen_current_time_a_s
            )
        else:
            self.regen_energy_from_current_kWh = 0.0 if loco_units else None
        return results




def run_train_simulation(
    route: RouteData,
    train: TrainParameters,
    start_time_s: int = 0,
    delta_t_s: float = 1.0,
) -> List[StepRecord]:
    """运行单车仿真并返回记录。"""

    simulator = TrainSimulator(route, train, delta_t_s=delta_t_s, start_time_s=start_time_s)
    return simulator.run()


def print_downhill_samples(records: List[StepRecord], sample_km: List[float]) -> None:
    """打印下坡区间内的典型位置速度与功率。"""

    if not records:
        print("仿真无有效记录。")
        return

    positions = [record.position_km for record in records]
    for target in sample_km:
        idx = min(range(len(positions)), key=lambda i: abs(positions[i] - target))
        record = records[idx]
        print(
            "  - {:.1f} km: 速度 {:.2f} km/h, 功率 {:.1f} kW".format(
                record.position_km,
                record.speed_mps * 3.6,
                record.power_kW,
            )
        )


def plot_results(route: RouteData, records: List[StepRecord], output_path: Optional[Path] = None) -> None:
    """绘制速度-里程与功率-里程曲线，并可保存为 PNG。"""

    distances = [record.position_km for record in records]
    speeds_kmh = [record.speed_mps * 3.6 for record in records]
    powers_kW = [record.power_kW for record in records]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    axes[0].plot(distances, speeds_kmh, color="#1f77b4", label="Speed")
    axes[0].set_ylabel("Speed (km/h)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(distances, powers_kW, color="#d62728", label="Power")
    axes[1].set_xlabel("Distance (km)")
    axes[1].set_ylabel("Power (kW)")
    axes[1].grid(True, alpha=0.3)

    long_start, long_end = route.long_downhill_range_km
    axes[0].axvspan(long_start, long_end, color="#ffcc99", alpha=0.3)
    axes[1].axvspan(long_start, long_end, color="#ffcc99", alpha=0.3)

    plt.tight_layout()
    if output_path is not None:
        fig.savefig(output_path, dpi=150)
    if output_path is None:
        plt.show()
    plt.close(fig)


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    config_path = Path("sandbox_config.json")
    if not config_path.exists():
        raise FileNotFoundError("sandbox_config.json 不存在，请先运行 sandbox_data.py 生成配置文件。")

    route, trains, _battery = load_config(config_path)
    heavy_train = trains.get("Heavy")
    if heavy_train is None:
        raise ValueError("未找到 Heavy 列车参数，请检查配置文件。")

    records = run_train_simulation(route, heavy_train)

    total_time_s = records[-1].time_s if records else 0
    print("=== 单车仿真结果 ===")
    print("总耗时: {:.1f} 分钟".format(total_time_s / 60.0))
    print("长下坡区间典型点速度/功率:")
    long_start, long_end = route.long_downhill_range_km
    sample_points = [
        long_start,
        long_start + (long_end - long_start) * 0.33,
        long_start + (long_end - long_start) * 0.66,
        long_end,
    ]
    print_downhill_samples(records, sample_points)

    plot_results(route, records, output_path=Path("train_simulation.png"))


if __name__ == "__main__":
    main()
