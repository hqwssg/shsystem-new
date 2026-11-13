"""把现有共享铁路数据适配为 eco-driving 输入。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from regenerative_braking.dynamics.train_braking_model import ElectricalBrakeCurve, TrainBrakingProfile
from regenerative_braking.io.data_loader import (
    SharedRailwayData,
    combine_regen_curves,
    consist_mass_kg,
    load_shared_railway_data,
)
from regenerative_braking.io.data_paths import ProjectPaths, load_project_paths


@dataclass(frozen=True)
class EcoDrivingData:
    railway: SharedRailwayData
    train: TrainBrakingProfile
    train_name: str
    traction_limit_n: float

    def route_speed_limit_mps(self, position_km: float) -> Optional[float]:
        value = self.railway.speed_limit_kmh_at(position_km)
        return value / 3.6 if value is not None else None


def load_eco_driving_data(
    train_name: str = "Heavy", paths: Optional[ProjectPaths] = None
) -> EcoDrivingData:
    paths = paths or load_project_paths()
    railway = load_shared_railway_data(paths)
    record = railway.trains.get(train_name)
    if record is None:
        raise ValueError(f"共享数据中不存在列车 {train_name!r}")
    from regenerative_braking.io.data_loader import load_single_train_parameters

    payload = load_single_train_parameters("train_parameters", paths)
    profile = TrainBrakingProfile.from_parameters(payload.payload)
    # train_parameters.json 提供阻力、黏着和储能侧算法参数。列车质量和再生能力
    # 必须从当前共享编组计算，不能继续把 legacy trains.csv 的车辆总重当整备质量，
    # 也不能把全列空气制动总量当成再生制动力。
    entries = record.consist_entries()
    consist = combine_regen_curves(entries, railway.locomotives)
    total_mass_kg = consist_mass_kg(record, railway.locomotives)
    regen_curve = ElectricalBrakeCurve(
        points_kmh_kn=consist.points_kmh_kn,
        current_points_kmh_a=consist.current_points_kmh_a,
        electrical_level=profile.electrical_level,
    )
    # 基本阻力必须随车型（重车/空车）取共享 trains.csv 的 Davis 系数；
    # train_parameters.json 只登记了重车表5系数，空车若沿用会把阻力低估约3倍。
    # 两处同为 TB/T 1407.1 表5 口径（N/kN，速度 km/h），重车数值逐位相同。
    resistance = replace(
        profile.resistance,
        a_n_per_kn=float(record.davis_a),
        b_n_per_kn_per_kmh=float(record.davis_b),
        c_n_per_kn_per_kmh2=float(record.davis_c),
    )
    formula = getattr(railway, "regen_energy_formula", None)
    profile = replace(
        profile,
        name=f"{train_name}[shared]",
        mass_kg=total_mass_kg,
        vehicle_mass_kg=record.mass_kg,
        locomotive_mass_kg=max(0.0, total_mass_kg - record.mass_kg),
        rotational_mass_factor=record.rotational_mass_factor,
        max_brake_force_n=record.max_brake_kN * 1000.0,
        max_regen_force_n=consist.peak_force_kn * 1000.0,
        length_m=record.length_km * 1000.0,
        regen_force_curve=regen_curve,
        resistance=resistance,
        locomotive_type=record.locomotive_type,
        # 混编（12 轴 + 8 轴）时总台数为各机型之和，不能只取首型台数。
        locomotive_count=sum(int(count) for _, count in entries) if entries else record.locomotive_count,
        catenary_voltage_v=(
            formula.u_w_v if formula is not None else profile.catenary_voltage_v
        ),
        data_status=record.mass_data_status or payload.data_status,
        provenance={
            **dict(profile.provenance or {}),
            "train_type": train_name,
            "shared_vehicle_mass_kg": record.mass_kg,
            "shared_consist_mass_kg": total_mass_kg,
            "shared_max_brake_force_n": record.max_brake_kN * 1000.0,
            "shared_regen_consist": record.locomotive_consist,
            "basic_resistance": (
                f"shared trains.csv Davis ({train_name}): a={record.davis_a}, "
                f"b={record.davis_b}, c={record.davis_c} N/kN, v in km/h"
            ),
        },
    )
    return EcoDrivingData(
        railway=railway,
        train=profile,
        train_name=train_name,
        traction_limit_n=record.max_traction_kN * 1000.0,
    )
