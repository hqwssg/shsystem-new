"""heavy_empty_train_coordination → eco-driving 的只读输入接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from regenerative_braking.io.data_loader import SharedRailwayData, consist_mass_kg

from ..models import EcoDrivingScenario, RunConstraints


class HeavyEmptyInterfaceError(ValueError):
    """跨项目输入不满足契约。"""


@dataclass(frozen=True)
class HeavyEmptyTrainRequest:
    train_id: str
    train_type: str
    mass_kg: float
    load_tons: Optional[float]
    route_start_km: float
    route_end_km: float
    initial_speed_mps: float
    target_runtime_s: Optional[float]
    runtime_tolerance_s: float = 10.0
    terminal_speed_mps: float = 0.0
    data_status: str = "assumed"

    def __post_init__(self) -> None:
        if not self.train_id:
            raise HeavyEmptyInterfaceError("train_id 不能为空")
        if self.route_end_km <= self.route_start_km:
            raise HeavyEmptyInterfaceError("route_end_km 必须大于 route_start_km")
        if self.mass_kg <= 0.0 or self.initial_speed_mps < 0.0:
            raise HeavyEmptyInterfaceError("mass_kg 必须为正，initial_speed_mps 不得为负")

    def to_scenario(self) -> EcoDrivingScenario:
        return EcoDrivingScenario(
            start_km=self.route_start_km,
            end_km=self.route_end_km,
            initial_speed_mps=self.initial_speed_mps,
            train_profile_id=self.train_type,
            constraints=RunConstraints(
                target_runtime_s=self.target_runtime_s,
                runtime_tolerance_s=self.runtime_tolerance_s,
                terminal_speed_mps=self.terminal_speed_mps,
            ),
            data_status=self.data_status,
            description=f"重空协同列车编号={self.train_id}",
        )


def request_from_shared_data(
    railway: SharedRailwayData,
    *,
    train_id: str,
    train_type: str,
    route_start_km: float,
    route_end_km: float,
    initial_speed_mps: float,
    target_runtime_s: Optional[float] = None,
    runtime_tolerance_s: float = 10.0,
    terminal_speed_mps: float = 0.0,
) -> HeavyEmptyTrainRequest:
    """从 shared railway data 建立请求，不复制或修改 shared 文件。"""

    record = railway.trains.get(train_type)
    if record is None:
        raise HeavyEmptyInterfaceError(f"shared 数据中不存在 train_type={train_type!r}")
    total_mass_kg = consist_mass_kg(record, railway.locomotives)
    return HeavyEmptyTrainRequest(
        train_id=train_id,
        train_type=train_type,
        mass_kg=total_mass_kg,
        load_tons=record.mass_tons,
        route_start_km=route_start_km,
        route_end_km=route_end_km,
        initial_speed_mps=initial_speed_mps,
        target_runtime_s=target_runtime_s,
        runtime_tolerance_s=runtime_tolerance_s,
        terminal_speed_mps=terminal_speed_mps,
        data_status=record.mass_data_status or "assumed",
    )


def validate_request_against_shared_data(request: HeavyEmptyTrainRequest, railway: SharedRailwayData) -> Mapping[str, object]:
    """校验请求与 shared 列车记录的一致性，返回可审计报告。"""

    record = railway.trains.get(request.train_type)
    if record is None:
        raise HeavyEmptyInterfaceError(f"shared 数据中不存在 train_type={request.train_type!r}")
    expected = consist_mass_kg(record, railway.locomotives)
    relative_error = abs(request.mass_kg - expected) / expected
    if relative_error > 1e-9:
        raise HeavyEmptyInterfaceError(
            f"请求质量 {request.mass_kg:g} kg 与 shared 质量 {expected:g} kg 不一致"
        )
    return {
        "train_id": request.train_id,
        "train_type": request.train_type,
        "mass_kg": request.mass_kg,
        "mass_data_status": record.mass_data_status,
        "route_start_km": request.route_start_km,
        "route_end_km": request.route_end_km,
        "shared_data_read_only": True,
    }
