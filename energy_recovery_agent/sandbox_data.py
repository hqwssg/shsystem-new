# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
import json
import random

from operating_conditions import OperatingConditions, default_operating_conditions


@dataclass(frozen=True)
class Station:
    """Station information, unit: km."""

    name: str
    position_km: float


@dataclass(frozen=True)
class Segment:
    """Route segment data, unit: km / per mille / m."""

    start_km: float
    end_km: float
    gradient_per_mille: float
    curve_radius_m: float | None = None
    terrain: str = "plain"


@dataclass(frozen=True)
class RouteData:
    """Infrastructure data for a Shuohuang-like heavy haul railway."""

    total_length_km: float
    max_speed_kmh: float
    stations: List[Station]
    segments: List[Segment]
    long_downhill_range_km: Tuple[float, float]
    energy_transfer_ranges_km: List[Tuple[float, float]]
    signaling_system: Dict[str, Any]
    operating_conditions: OperatingConditions


@dataclass(frozen=True)
class DavisCoefficients:
    """Davis equation coefficients."""

    a: float
    b: float
    c: float


@dataclass(frozen=True)
class TrainParameters:
    """Train physical parameters."""

    name: str
    mass_tons: float
    max_traction_kN: float
    max_brake_kN: float
    rotational_mass_factor: float
    davis: DavisCoefficients
    length_km: float
    longitudinal_segments: int
    direction: str
    traction_adhesion_weight_fraction: float
    brake_adhesion_weight_fraction: float


@dataclass(frozen=True)
class BatteryStorageParameters:
    """Battery storage parameters."""

    capacity_kwh: float
    max_charge_power_kW: float
    max_discharge_power_kW: float
    round_trip_efficiency: float
    depreciation_cost_per_kwh: float
    grid_price_per_kwh: float


def _build_station_list(total_length_km: float) -> List[Station]:
    """Build a virtual 33-station list matching the public Shuohuang scale."""

    known_stations = [
        ("Shenchi South", 0.0),
        ("Yinshanzhuang", 118.0),
        ("Dongye", 145.0),
        ("Diliudeng", 164.0),
        ("Xiaojue", 200.7),
        ("Suning North", 362.0),
        ("Huanghua Port", total_length_km),
    ]
    station_count = 33
    positions = {round(pos, 1): name for name, pos in known_stations}

    idx = 0
    while len(positions) < station_count:
        pos = round(total_length_km * idx / (station_count - 1), 1)
        if all(abs(pos - known_pos) > 3.0 for _name, known_pos in known_stations):
            positions.setdefault(pos, f"Virtual Station {idx + 1:02d}")
        idx += 1

    stations = [Station(name=name, position_km=pos) for pos, name in sorted(positions.items())]
    return stations


def _terrain_for_position(km: float) -> str:
    """函数 _terrain_for_position：执行该模块中的相关处理逻辑。"""
    if km < 210.0:
        return "mountain"
    if km < 380.0:
        return "hill"
    return "plain"


def _base_gradient(rng: random.Random, km: float) -> float:
    """函数 _base_gradient：执行该模块中的相关处理逻辑。"""
    terrain = _terrain_for_position(km)
    if terrain == "mountain":
        return rng.uniform(-9.0, 5.0)
    if terrain == "hill":
        return rng.uniform(-5.0, 4.0)
    return rng.uniform(-2.0, 1.5)


def _curve_radius(rng: random.Random, km: float) -> float | None:
    """函数 _curve_radius：执行该模块中的相关处理逻辑。"""
    terrain = _terrain_for_position(km)
    probability = {"mountain": 0.46, "hill": 0.26, "plain": 0.08}[terrain]
    if rng.random() > probability:
        return None
    if terrain == "mountain":
        return rng.choice([450.0, 500.0, 600.0, 800.0, 1000.0])
    if terrain == "hill":
        return rng.choice([800.0, 1000.0, 1200.0, 1600.0])
    return rng.choice([1600.0, 2000.0, 2500.0])


def generate_route_data(rng: random.Random) -> RouteData:
    """Generate a virtual route constrained by public Shuohuang Railway facts."""

    # 公开资料将正线长度置于约 594—598 km；使用 594 km 作为可复现规划长度，
    # 运行速度上限保持 120 km/h。
    total_length_km = 594.0
    max_speed_kmh = 120.0

    # 西向东重车方向按向港口长下坡建模。公开资料提到重车约有 240 km 长下坡，
    # 坡度保持在千分之十二上限以内。
    long_downhill_start_km = 62.0
    long_downhill_end_km = 302.0

    # 公开报告将柔性牵引供电应用指向东冶—地流墩—小觉三站两区段供电区。
    # 完整线路里程公开信息不足，因此本虚拟线路将地流墩锚定在约 164 km、小觉锚定在 K200+689 附近，
    # 东冶位置采用估计值。
    energy_transfer_ranges_km = [(145.0, 164.0), (164.0, 200.7)]
    signaling_system = {
        "mode": "hybrid",
        "fixed_block_length_km": 2.0,
        "fixed_block_protection_blocks": 2,
        "moving_block_base_buffer_m": 500.0,
        "moving_block_reaction_time_s": 30.0,
        "moving_block_follower_service_decel_mps2": 0.28,
        "moving_block_lead_emergency_decel_mps2": 0.50,
        "check_step_s": 5,
    }

    segment_length_km = 1.0
    segment_count = int(total_length_km / segment_length_km)
    segments: List[Segment] = []

    for idx in range(segment_count):
        start_km = idx * segment_length_km
        end_km = start_km + segment_length_km
        terrain = _terrain_for_position(start_km)
        gradient = _base_gradient(rng, start_km)

        if long_downhill_start_km <= start_km < long_downhill_end_km:
            progress = (start_km - long_downhill_start_km) / (long_downhill_end_km - long_downhill_start_km)
            if progress < 0.18:
                gradient = rng.uniform(-11.8, -9.2)
            elif progress < 0.72:
                gradient = rng.uniform(-10.8, -7.0)
            else:
                gradient = rng.uniform(-7.5, -3.5)

        gradient = max(-12.0, min(12.0, gradient))
        segments.append(
            Segment(
                start_km=start_km,
                end_km=end_km,
                gradient_per_mille=gradient,
                curve_radius_m=_curve_radius(rng, start_km),
                terrain=terrain,
            )
        )

    return RouteData(
        total_length_km=total_length_km,
        max_speed_kmh=max_speed_kmh,
        stations=_build_station_list(total_length_km),
        segments=segments,
        long_downhill_range_km=(long_downhill_start_km, long_downhill_end_km),
        energy_transfer_ranges_km=energy_transfer_ranges_km,
        signaling_system=signaling_system,
        operating_conditions=default_operating_conditions(),
    )


def build_train_parameters() -> List[TrainParameters]:
    """Define heavy loaded and empty train parameters."""

    heavy_davis = DavisCoefficients(a=6.5, b=0.12, c=0.003)
    empty_davis = DavisCoefficients(a=5.0, b=0.10, c=0.0025)

    heavy_train = TrainParameters(
        name="Heavy",
        mass_tons=10000.0,
        max_traction_kN=6000.0,
        max_brake_kN=7000.0,
        rotational_mass_factor=1.08,
        davis=heavy_davis,
        length_km=2.7,
        longitudinal_segments=20,
        direction="forward",
        traction_adhesion_weight_fraction=0.22,
        brake_adhesion_weight_fraction=1.0,
    )
    empty_train = TrainParameters(
        name="Empty",
        mass_tons=2000.0,
        max_traction_kN=3000.0,
        max_brake_kN=3500.0,
        rotational_mass_factor=1.05,
        davis=empty_davis,
        length_km=2.7,
        longitudinal_segments=20,
        direction="reverse",
        traction_adhesion_weight_fraction=0.55,
        brake_adhesion_weight_fraction=1.0,
    )

    return [heavy_train, empty_train]


def build_battery_parameters() -> BatteryStorageParameters:
    """Define example battery storage parameters."""

    return BatteryStorageParameters(
        capacity_kwh=20000.0,
        max_charge_power_kW=20000.0,
        max_discharge_power_kW=20000.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.15,
        grid_price_per_kwh=0.55,
    )


def print_overview(route: RouteData, trains: List[TrainParameters], battery: BatteryStorageParameters) -> None:
    """Print a compact overview for sanity checking."""

    long_start, long_end = route.long_downhill_range_km
    transfer_ranges = ", ".join(f"{start:.1f}-{end:.1f} km" for start, end in route.energy_transfer_ranges_km)
    curved_segments = sum(1 for segment in route.segments if segment.curve_radius_m is not None)
    mountain_segments = sum(1 for segment in route.segments if segment.terrain == "mountain")
    min_gradient = min(segment.gradient_per_mille for segment in route.segments)
    max_gradient = max(segment.gradient_per_mille for segment in route.segments)

    print("=== Shuohuang-like Virtual Route ===")
    print(f"Total length: {route.total_length_km:.1f} km")
    print(f"Operation speed cap: {route.max_speed_kmh:.1f} km/h")
    print(f"Stations: {len(route.stations)}")
    print(f"Mountain section share: {mountain_segments / len(route.segments):.1%}")
    print(f"Curved segment share: {curved_segments / len(route.segments):.1%}")
    print(f"Gradient range: {min_gradient:.1f} to {max_gradient:.1f} per mille")
    print(f"Loaded-train long downhill: {long_start:.1f} km -> {long_end:.1f} km")
    print(f"Flexible traction power zones: {transfer_ranges}")
    print(
        "Signal safety mode: {mode}, fixed block {block:.1f} km, protection {protect} blocks".format(
            mode=route.signaling_system["mode"],
            block=route.signaling_system["fixed_block_length_km"],
            protect=route.signaling_system["fixed_block_protection_blocks"],
        )
    )
    print(
        "Operating conditions: default adhesion {:.2f}, weather {}, low-adhesion zones {}, TSR {}".format(
            route.operating_conditions.default_adhesion_coefficient,
            len(route.operating_conditions.weather_conditions),
            len(route.operating_conditions.adhesion_zones),
            len(route.operating_conditions.speed_restrictions),
        )
    )

    print("\n=== Train Parameters ===")
    for train in trains:
        print(
            f"{train.name}: length {train.length_km:.2f} km, "
            f"longitudinal segments {train.longitudinal_segments}, "
            f"direction {train.direction}"
        )

    print("\n=== Battery Parameters ===")
    print(f"Capacity: {battery.capacity_kwh:.0f} kWh")
    print(f"Max charge power: {battery.max_charge_power_kW:.0f} kW")
    print(f"Max discharge power: {battery.max_discharge_power_kW:.0f} kW")
    print(f"Round-trip efficiency: {battery.round_trip_efficiency:.2f}")
    print(f"Depreciation cost: {battery.depreciation_cost_per_kwh:.2f} CNY/kWh")
    print(f"Grid price: {battery.grid_price_per_kwh:.2f} CNY/kWh")


def save_config(
    route: RouteData,
    trains: List[TrainParameters],
    battery: BatteryStorageParameters,
    file_path: Path,
) -> None:
    """Serialize the sandbox config."""

    data = {
        "route": asdict(route),
        "trains": [asdict(train) for train in trains],
        "battery": asdict(battery),
    }
    file_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    rng = random.Random(42)

    route = generate_route_data(rng)
    trains = build_train_parameters()
    battery = build_battery_parameters()

    save_config(route, trains, battery, Path("sandbox_config.json"))
    print_overview(route, trains, battery)


if __name__ == "__main__":
    main()
