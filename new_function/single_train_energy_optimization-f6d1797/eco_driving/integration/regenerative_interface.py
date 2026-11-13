"""eco-driving → regenerative_braking 的制动轨迹和能量接口。

边界约定：

* eco-driving 只提供运行轨迹，不计算储能端回收能量；
* 本适配层只把轨迹映射为 regenerative_braking 的 ``ProfileSeries``；
* 再生制动 simulator 是唯一的回收能量和 SOC 生产者，避免重复扣减；
* 输入和输出都保留 simulation/data-status 说明。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from regenerative_braking.io.data_paths import ProjectPaths
from regenerative_braking.simulation.controllers import RegenController
from regenerative_braking.simulation.profiles import ProfileSeries
from regenerative_braking.simulation.regenerative_simulator import (
    RegenerativeBrakingSimulator,
    SimulationConfig,
    SimulationResult,
)
from regenerative_braking.simulation.scenario_runner import (
    ComponentBundle,
    build_simulator,
    load_component_bundle,
)
from regenerative_braking.dynamics.train_braking_model import BrakingInput

from ..models import ControlMode, EcoDrivingResult


class RegenerativeInterfaceError(ValueError):
    """eco-driving 与 regenerative_braking 接口数据不一致。"""


@dataclass(frozen=True)
class RegenerativeEvaluation:
    """制动轨迹经再生制动模型评估后的结果。"""

    source_profile: ProfileSeries
    simulation: SimulationResult
    metrics: Mapping[str, Any]
    data_status: str
    disclaimer: str = "仿真结果，不作为工程结论"


def _infer_dt(result: EcoDrivingResult) -> float:
    if len(result.samples) < 2:
        raise RegenerativeInterfaceError("至少需要两个 eco-driving 采样点才能建立制动轨迹")
    differences = [
        result.samples[index + 1].time_s - result.samples[index].time_s
        for index in range(len(result.samples) - 1)
    ]
    dt = differences[0]
    if not math.isfinite(dt) or dt <= 0.0:
        raise RegenerativeInterfaceError(f"eco-driving 时间轴必须严格递增，实际 dt={dt!r}")
    if any(not math.isfinite(value) or value <= 0.0 for value in differences):
        raise RegenerativeInterfaceError("时间轴必须为有限数值且严格递增")
    return dt


def _is_uniform_profile(profile: ProfileSeries) -> bool:
    return all(
        math.isclose(right.time_s - left.time_s, profile.dt, rel_tol=1e-7, abs_tol=1e-9)
        for left, right in zip(profile.samples, profile.samples[1:])
    )


def build_regenerative_profile(
    result: EcoDrivingResult,
    *,
    start_km: float = 0.0,
    scenario_id: str = "eco_driving_regenerative_recovery",
) -> ProfileSeries:
    """把 eco-driving 轨迹转换为 regenerative_braking 的 ``ProfileSeries``。

    ``acceleration_mps2`` 使用 eco-driving 的实际状态加速度，
    ``brake_command=1``，因为 regenerative_braking 会依据实际加速度和阻力
    反解制动力；再次乘一个策略比例会造成制动力重复缩放。
    """

    dt = _infer_dt(result)
    samples = tuple(
        BrakingInput(
            time_s=sample.time_s,
            position_km=start_km + sample.position_m / 1000.0,
            speed_mps=sample.speed_mps,
            acceleration_mps2=sample.acceleration_mps2,
            gradient_per_mille=sample.gradient_per_mille,
            curve_radius_m=sample.curve_radius_m,
            speed_limit_mps=sample.speed_limit_mps,
            # 终点状态样本没有控制区间；标成 0 供仿真侧安全移除。
            brake_command=(
                0.0
                if index == len(result.samples) - 1
                and sample.mode is ControlMode.COAST
                and abs(sample.acceleration_mps2) <= 1.0e-12
                and abs(sample.traction_force_n) <= 1.0e-12
                and abs(sample.braking_force_n) <= 1.0e-12
                else 1.0
            ),
        )
        for index, sample in enumerate(result.samples)
    )
    return ProfileSeries(
        scenario_id=scenario_id,
        samples=samples,
        dt=dt,
        description="节能速度曲线的制动轨迹 → 再生制动回收",
        notes=(
            "轨迹来源：节能速度曲线模块",
            "制动指令固定为1.0，实际制动状态由加速度承载",
            "再生回收能量仅由再生制动模块计算",
            result.disclaimer,
        ),
    )


def _resample_profile(profile: ProfileSeries, target_dt: float) -> ProfileSeries:
    """按线性状态插值把 eco-driving 轨迹细化到变流器仿真步长。"""

    if target_dt <= 0.0 or not math.isfinite(target_dt):
        raise RegenerativeInterfaceError(f"target_dt 必须为正有限值，实际为 {target_dt!r}")
    source = profile.samples
    if len(source) < 2:
        raise RegenerativeInterfaceError("重采样至少需要两个原始采样点")
    out: list[BrakingInput] = []
    for left, right in zip(source, source[1:]):
        duration = right.time_s - left.time_s
        if not math.isfinite(duration) or duration <= 0.0:
            raise RegenerativeInterfaceError("时间轴必须为有限数值且严格递增")
        count = max(1, int(math.ceil(duration / target_dt - 1e-9)))
        for index in range(count):
            elapsed = index * target_dt
            alpha = elapsed / duration
            # Controls and route facts apply on [left, right). Interpolating
            # acceleration or gradient across a switch invents braking demand.
            out.append(BrakingInput(
                time_s=left.time_s + elapsed,
                position_km=left.position_km + alpha * (right.position_km - left.position_km),
                speed_mps=left.speed_mps + alpha * (right.speed_mps - left.speed_mps),
                acceleration_mps2=left.acceleration_mps2,
                gradient_per_mille=left.gradient_per_mille,
                curve_radius_m=left.curve_radius_m,
                speed_limit_mps=left.speed_limit_mps,
                brake_command=left.brake_command,
            ))
    out.append(source[-1])
    return ProfileSeries(
        scenario_id=profile.scenario_id,
        samples=tuple(out),
        dt=target_dt,
        description=profile.description + f"；重采样步长={target_dt:g}秒",
        notes=profile.notes + (f"为再生制动仿真重采样，步长={target_dt:g}秒",),
        shared_data_refs=profile.shared_data_refs,
    )


def _drop_terminal_state_sample(profile: ProfileSeries) -> ProfileSeries:
    """移除只表示终点状态、并不代表一个控制区间的末端样本。

    eco-driving 为了输出完整轨迹会追加一个零力终点样本。再生仿真按每个
    ``ProfileSeries`` 样本推进一个区间；若直接消费该样本，就会在终点之后
    再积分一个 ``dt``，产生额外制动能量和越过线路边界的电气响应。
    """

    if len(profile.samples) < 2:
        return profile
    last = profile.samples[-1]
    previous = profile.samples[-2]
    if (
        last.time_s > previous.time_s
        and last.position_km >= previous.position_km
        and abs(last.acceleration_mps2) <= 1.0e-12
        and abs(last.brake_command) <= 1.0e-12
    ):
        return ProfileSeries(
            scenario_id=profile.scenario_id,
            samples=profile.samples[:-1],
            dt=profile.dt,
            description=profile.description + "；已移除末端状态采样点",
            notes=profile.notes + ("终点状态采样点不代表控制区间",),
            shared_data_refs=profile.shared_data_refs,
        )
    return profile


def evaluate_regenerative_recovery(
    result: EcoDrivingResult,
    *,
    bundle: Optional[ComponentBundle] = None,
    paths: Optional[ProjectPaths] = None,
    controller: Optional[RegenController] = None,
    config: Optional[SimulationConfig] = None,
    start_km: float = 0.0,
    scenario_id: str = "eco_driving_regenerative_recovery",
    check=None,
) -> RegenerativeEvaluation:
    """运行 regenerative_braking 闭环并返回可用能量、回收能量和 SOC 指标。"""

    profile = build_regenerative_profile(result, start_km=start_km, scenario_id=scenario_id)
    simulation_profile = profile
    bundle = bundle or load_component_bundle(paths)
    simulator: RegenerativeBrakingSimulator = build_simulator(bundle)
    # eco-driving 轨迹的采样步长是 1 s 量级，直接当作 DC-DC 平均模型的积分步长
    # 会导致电压数值发散。变流器步长与轨迹步长必须解耦：默认用 1e-4 s，
    # 并把轨迹重采样到该步长。显式传入的 config 保持不变。
    if config is None:
        simulation_config = SimulationConfig(dt=1e-4, record_stride=1)
    else:
        simulation_config = config
    if (
        not math.isclose(simulation_config.dt, simulation_profile.dt, rel_tol=1e-9, abs_tol=1e-12)
        or not _is_uniform_profile(simulation_profile)
    ):
        simulation_profile = _resample_profile(simulation_profile, simulation_config.dt)
    simulation_profile = _drop_terminal_state_sample(simulation_profile)
    ticks = [0]
    def monitor(time_s, simulator):
        ticks[0] += 1
        if check is not None and ticks[0] % 1000 == 1:
            check()
    simulation = simulator.run(simulation_profile, controller=controller, config=simulation_config,
                               plant_update=monitor if check is not None else None)
    metrics = simulation.ledger.to_dict(kwh=True)
    metrics = {
        **metrics,
        "source": "eco_driving",
        "source_data_status": result.data_status,
        "regenerative_data_status": bundle.parameter_status,
        "available_regenerative_energy_kwh": metrics["available_regenerative_energy_kWh"],
        "captured_regenerative_energy_kwh": metrics["captured_energy_kWh"],
        "soc_start": metrics["soc_start"],
        "soc_end": metrics["soc_end"],
    }
    return RegenerativeEvaluation(
        source_profile=profile,
        simulation=simulation,
        metrics=metrics,
        data_status=result.data_status,
    )
