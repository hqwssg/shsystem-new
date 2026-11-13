"""制动工况剖面：把列车动力学与线路条件变成时间序列输入。

再生制动算法不能只接受一条固定功率曲线，因此本模块提供输入层：

    * 平直线路常规制动      -> constant_deceleration_series
    * 长大下坡制动（保持速度）-> grade_hold_series
    * 分段恒减速度制动      -> segmented_braking_series
    * 真实线路区段制动      -> route_braking_series（读取共享真实坡度/曲线/限速）

约定：``BrakingInput.acceleration_mps2`` 是**实际加速度**，出厂样本的
``brake_command`` 固定为 **1.0**——因为 ``evaluate_braking`` 会把需求力再乘一次
``brake_command``，而剖面的加速度已经包含了制动力，故回填时不能再乘一次
（见 :func:`route_braking_series` 里"用实际加速度回填当前样本"那段）。
制动力大小由加速度与阻力共同决定。

**线路限速**（问题 29）：四个构造器都会在返回前调用
:func:`_check_speed_limit_respected` 逐点校验，越限直接报错——限速不再是
"只读入不消费"的字段。限速的**物理作用**（超速保护 / 空气制动补足）不在本项目
范围内：全部工况都是制动工况、速度单调下降。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..dynamics.train_braking_model import (
    BrakingInput,
    TrainBrakingProfile,
    evaluate_braking,
    max_achievable_deceleration,
)
from ..io.data_loader import SharedRailwayData


class ProfileError(ValueError):
    """工况剖面构造参数不合法。"""


#: 方案问题编号 **29**（实现期自行发现，非方案正文问题）：共享线路的**限速**
#: 被逐点读入 ``BrakingInput.speed_limit_mps``，却**从未参与任何计算**——
#: 既不校验也不截断速度，全仓没有任何消费点（``SharedRailwayData.speed_limit_kmh_at()``
#: 同样无调用者）。作为对照，曲线半径是有消费点的（``train_braking_model``
#: 的 ``curve_resistance_n``），所以「线路几何取自共享数据」这句声明对限速
#: 只兑现了「搬运」、没兑现「约束」：把 ``brake_command`` 调大或抬高入口速度
#: 就会静默越限，而剖面、能量台账、回收率全都不报错。
#:
#: 裁定：在剖面构造处**显式校验**（越限直接报错，不静默把速度截到限速值）——
#: 与 :func:`_check_deceleration_is_achievable` 同一纪律：不静默选一种解释。
#: 限速的**物理**作用（超速保护/空气制动补足）不在本项目范围内（本项目的工况
#: 都是制动工况，速度单调下降），故只做校验、不引入超速动力学。
SCHEME_ISSUE_SPEED_LIMIT_NOT_ENFORCED = 29


def _validate_speed_limit(limit: float, where: str) -> float:
    """把限速校验成正有限值。"""

    value = float(limit)
    if not math.isfinite(value) or value <= 0.0:
        raise ProfileError(f"{where} 必须为正有限值，实际为 {limit!r}")
    return value


def _check_speed_limit_respected(
    samples: Sequence[BrakingInput], speed_limit_mps: Optional[float] = None
) -> None:
    """校验剖面里没有任何一步越过线路限速（方案问题 29）。

    两类限速都要满足：

    * ``speed_limit_mps``（本次调用显式给出的**全局**限速，``None`` 表示不声明）；
    * ``sample.speed_limit_mps``（**逐样本**限速，真实线路剖面按里程逐点取，
      :func:`route_braking_series` 走这一路）。

    为什么必须校验：``speed_limit_mps`` 被定义为线路的**客观约束**，随每个样本
    一起出厂到 ``cross_project_export``。若剖面本身越限，那份"基础事实数据"
    就是自相矛盾的，而下游（能量核算、跨项目导出）无从察觉。
    因此这里直接报错，而不是静默把速度截到限速值——后者等于用一条
    "跑不出来"的曲线去做能量核算。

    注意本函数**不施加**限速的物理作用（超速保护/空气制动补足）：本项目全部
    工况都是制动工况，速度单调下降，限速只在起点可能绑定。
    """

    if speed_limit_mps is not None:
        limit = _validate_speed_limit(speed_limit_mps, "speed_limit_mps")
        worst = max((sample.speed_mps for sample in samples), default=0.0)
        if worst > limit + 1e-9:
            raise ProfileError(
                f"剖面越过线路限速：最高速度 {worst * 3.6:.2f} km/h > 限速 {limit * 3.6:.2f} km/h"
                f"（超出 {(worst - limit) * 3.6:.2f} km/h）。"
                "请下调入口速度或降低制动指令，使剖面本身满足线路限速；"
                "本函数不静默截断速度，因为截断会让剖面速度与真实动力学不一致。"
            )

    for index, sample in enumerate(samples):
        if sample.speed_limit_mps is None:
            continue
        limit = _validate_speed_limit(sample.speed_limit_mps, f"第 {index} 步的 speed_limit_mps")
        if sample.speed_mps > limit + 1e-9:
            raise ProfileError(
                f"第 {index} 步越过所在区段限速：速度 {sample.speed_mps * 3.6:.2f} km/h > "
                f"限速 {limit * 3.6:.2f} km/h（里程 {sample.position_km:.4f} km）。"
                "真实线路剖面的限速逐点取自共享数据，越限即剖面与线路不自洽。"
            )


def _check_deceleration_is_achievable(
    profile: TrainBrakingProfile,
    decel_mps2: float,
    speeds_mps: Sequence[float],
    gradient_per_mille: float,
    curve_radius_m: Optional[float],
) -> None:
    """校验请求的减速度不超过列车物理可达上限。

    为什么必须校验：剖面里的 acceleration_mps2 被定义为**实际加速度**。
    若请求的减速度超过 min(车辆最大制动力, 黏着上限) 所能提供的水平，
    制动力会在 evaluate_braking 中被截断，剖面速度与真实动力学就不一致了
    —— 那等于用一条"跑不出来"的曲线去做能量核算。
    因此这里直接报错，而不是静默把减速度改小。
    """

    worst_cap = min(
        max_achievable_deceleration(profile, speed, gradient_per_mille, curve_radius_m) for speed in speeds_mps
    )
    if decel_mps2 > worst_cap + 1e-9:
        raise ProfileError(
            f"请求减速度 {decel_mps2:.4f} m/s^2 超过列车可达上限 {worst_cap:.4f} m/s^2"
            f"（坡度 {gradient_per_mille:.2f} ‰，车辆最大制动力 {profile.max_brake_force_n / 1e3:.1f} kN，"
            f"黏着上限 {profile.adhesion.max_brake_force_n(profile.mass_kg) / 1e3:.1f} kN，"
            f"等效质量 {profile.effective_mass_kg / 1e3:.0f} t）。"
            "请下调 decel_mps2，或提供正式牵引/制动特性资料后再提高上限。"
        )


@dataclass(frozen=True)
class ProfileSeries:
    """离散时间制动工况序列。"""

    scenario_id: str
    samples: Tuple[BrakingInput, ...]
    dt: float
    description: str = ""
    notes: Tuple[str, ...] = ()
    shared_data_refs: Tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def duration_s(self) -> float:
        return len(self.samples) * self.dt

    def summary(self) -> str:
        if not self.samples:
            return f"{self.scenario_id}: 空序列"
        speeds = [sample.speed_mps for sample in self.samples]
        gradients = [sample.gradient_per_mille for sample in self.samples]
        return (
            f"{self.scenario_id}: {len(self.samples)} 步 / {self.duration_s:.2f} s, "
            f"速度 {min(speeds) * 3.6:.2f}~{max(speeds) * 3.6:.2f} km/h, "
            f"坡度 {min(gradients):.2f}~{max(gradients):.2f} ‰"
        )


def _check_dt(dt: float) -> float:
    value = float(dt)
    if not math.isfinite(value) or value <= 0.0:
        raise ProfileError(f"dt 必须为正有限值，实际为 {dt!r}")
    return value


def _check_speed(speed: float, name: str) -> float:
    value = float(speed)
    if not math.isfinite(value) or value < 0.0:
        raise ProfileError(f"{name} 必须为非负有限值，实际为 {speed!r}")
    return value


# ------------------------------------------------------------------
# 场景 1：平直线路常规制动
# ------------------------------------------------------------------


def constant_deceleration_series(
    profile: TrainBrakingProfile,
    v0_mps: float,
    decel_mps2: float,
    dt: float,
    v_end_mps: float = 0.0,
    gradient_per_mille: float = 0.0,
    curve_radius_m: Optional[float] = None,
    speed_limit_mps: Optional[float] = None,
    start_position_km: float = 0.0,
    scenario_id: str = "scenario_1_flat_constant_deceleration",
    description: str = "平直线路常规制动（等减速度）",
) -> ProfileSeries:
    """等减速度制动剖面（Scenario 1）。"""

    dt = _check_dt(dt)
    v0 = _check_speed(v0_mps, "v0_mps")
    v_end = _check_speed(v_end_mps, "v_end_mps")
    decel = float(decel_mps2)
    if not math.isfinite(decel) or decel <= 0.0:
        raise ProfileError("decel_mps2 必须为正有限值")
    if v_end > v0:
        raise ProfileError("v_end_mps 不得大于 v0_mps")
    _check_deceleration_is_achievable(profile, decel, (v0, v_end), gradient_per_mille, curve_radius_m)

    samples: List[BrakingInput] = []
    speed = v0
    position_km = start_position_km
    time_s = 0.0
    while speed > v_end + 1e-9:
        samples.append(
            BrakingInput(
                time_s=time_s,
                position_km=position_km,
                speed_mps=speed,
                acceleration_mps2=-decel,
                gradient_per_mille=gradient_per_mille,
                curve_radius_m=curve_radius_m,
                speed_limit_mps=speed_limit_mps,
                brake_command=1.0,
            )
        )
        position_km += speed * dt / 1000.0
        speed = max(v_end, speed - decel * dt)
        time_s += dt

    _check_speed_limit_respected(samples, speed_limit_mps)

    return ProfileSeries(
        scenario_id=scenario_id,
        samples=tuple(samples),
        dt=dt,
        description=description,
        notes=(f"等减速度 {decel:.3f} m/s^2，由 {v0 * 3.6:.2f} km/h 制动至 {v_end * 3.6:.2f} km/h",),
        shared_data_refs=(),
    )


# ------------------------------------------------------------------
# 场景 2：长大下坡制动（先减速至目标速度，再恒速保持）
# ------------------------------------------------------------------


def grade_hold_series(
    profile: TrainBrakingProfile,
    entry_speed_mps: float,
    target_speed_mps: float,
    decel_mps2: float,
    gradient_per_mille: float,
    dt: float,
    hold_duration_s: float,
    curve_radius_m: Optional[float] = None,
    speed_limit_mps: Optional[float] = None,
    start_position_km: float = 0.0,
    scenario_id: str = "scenario_2_long_downhill",
    description: str = "长大下坡制动（减速至目标速度后恒速保持）",
) -> ProfileSeries:
    """长大下坡工况：先在坡道上减速到目标速度，再恒速运行持续再生制动。

    恒速段是再生制动的典型持续工况：坡道下滑力由制动力平衡，
    电制动需要长时间稳定输出，这正是 SOC 与热约束最容易触发的阶段。
    """

    dt = _check_dt(dt)
    entry = _check_speed(entry_speed_mps, "entry_speed_mps")
    target = _check_speed(target_speed_mps, "target_speed_mps")
    decel = float(decel_mps2)
    if not math.isfinite(decel) or decel <= 0.0:
        raise ProfileError("decel_mps2 必须为正有限值")
    if target > entry:
        raise ProfileError("target_speed_mps 不得大于 entry_speed_mps")
    if hold_duration_s < 0.0:
        raise ProfileError("hold_duration_s 必须非负")
    _check_deceleration_is_achievable(profile, decel, (entry, target), gradient_per_mille, curve_radius_m)

    samples: List[BrakingInput] = []
    speed = entry
    position_km = start_position_km
    time_s = 0.0

    while speed > target + 1e-9:
        samples.append(
            BrakingInput(
                time_s=time_s,
                position_km=position_km,
                speed_mps=speed,
                acceleration_mps2=-decel,
                gradient_per_mille=gradient_per_mille,
                curve_radius_m=curve_radius_m,
                speed_limit_mps=speed_limit_mps,
                brake_command=1.0,
            )
        )
        position_km += speed * dt / 1000.0
        speed = max(target, speed - decel * dt)
        time_s += dt

    hold_steps = int(round(hold_duration_s / dt))
    for _ in range(hold_steps):
        samples.append(
            BrakingInput(
                time_s=time_s,
                position_km=position_km,
                speed_mps=target,
                acceleration_mps2=0.0,
                gradient_per_mille=gradient_per_mille,
                curve_radius_m=curve_radius_m,
                speed_limit_mps=speed_limit_mps,
                brake_command=1.0,
            )
        )
        position_km += target * dt / 1000.0
        time_s += dt

    _check_speed_limit_respected(samples, speed_limit_mps)

    return ProfileSeries(
        scenario_id=scenario_id,
        samples=tuple(samples),
        dt=dt,
        description=description,
        notes=(
            f"坡度 {gradient_per_mille:.2f} ‰，由 {entry * 3.6:.2f} km/h 减速至 {target * 3.6:.2f} km/h，"
            f"恒速保持 {hold_duration_s:.1f} s",
        ),
        shared_data_refs=(),
    )


# ------------------------------------------------------------------
# 真实线路区段剖面
# ------------------------------------------------------------------


def route_braking_series(
    profile: TrainBrakingProfile,
    shared: SharedRailwayData,
    start_km: float,
    v0_mps: float,
    dt: float,
    brake_command: float = 1.0,
    v_stop_mps: float = 0.0,
    end_km: Optional[float] = None,
    max_time_s: float = 600.0,
    scenario_id: str = "route_braking",
    description: str = "真实线路区段制动（坡度/曲线/限速取自共享数据）",
) -> ProfileSeries:
    """在真实线路上做前向制动积分，坡度/曲线逐点取自共享数据。

    制动力按 brake_command 取可用制动力（车辆上限与黏着上限的较小者）的比例，
    加速度由动力学决定，因此本剖面同时给出真实的制动力需求变化。
    """

    dt = _check_dt(dt)
    v0 = _check_speed(v0_mps, "v0_mps")
    command = float(brake_command)
    if not 0.0 <= command <= 1.0:
        raise ProfileError("brake_command 必须在 [0, 1] 内")

    if end_km is None:
        end_km = shared.total_length_km()
    if not math.isfinite(start_km) or not math.isfinite(end_km):
        raise ProfileError("start_km 和 end_km 必须为有限值")
    if end_km <= start_km:
        raise ProfileError("end_km 必须大于 start_km")
    route_end_km = shared.total_length_km()
    if shared.segment_at(start_km) is None or end_km > route_end_km:
        raise ProfileError(
            f"制动区段必须位于共享线路范围内：start_km={start_km}, end_km={end_km}, "
            f"线路终点={route_end_km}"
        )

    samples: List[BrakingInput] = []
    speed = v0
    position_km = start_km
    time_s = 0.0
    max_steps = int(max_time_s / dt) + 1

    for _ in range(max_steps):
        if speed <= v_stop_mps + 1e-9 or position_km >= end_km:
            break

        segment = shared.segment_at(position_km)
        if segment is None:
            raise ProfileError(f"共享线路在 {position_km:.6f} km 缺少区段数据")
        gradient = segment.gradient_per_mille
        curve_radius = segment.curve_radius_m
        speed_limit_kmh = segment.speed_limit_kmh
        speed_limit_mps = speed_limit_kmh / 3.6 if speed_limit_kmh else None

        samples.append(
            BrakingInput(
                time_s=time_s,
                position_km=position_km,
                speed_mps=speed,
                acceleration_mps2=0.0,
                gradient_per_mille=gradient,
                curve_radius_m=curve_radius,
                speed_limit_mps=speed_limit_mps,
                brake_command=command,
            )
        )

        breakdown = evaluate_braking(
            profile,
            BrakingInput(
                time_s=time_s,
                position_km=position_km,
                speed_mps=speed,
                acceleration_mps2=0.0,
                gradient_per_mille=gradient,
                curve_radius_m=curve_radius,
                speed_limit_mps=speed_limit_mps,
                brake_command=command,
            ),
        )
        # 制动力上限 = min(车辆最大制动力, 黏着上限)
        brake_ceiling = min(profile.max_brake_force_n, breakdown.adhesion_limit_n)
        applied_brake_n = command * brake_ceiling
        resistance_n = breakdown.basic_resistance_n + breakdown.gradient_resistance_n + breakdown.curve_resistance_n
        acceleration = (-applied_brake_n - resistance_n) / profile.effective_mass_kg

        # 用实际加速度回填当前样本。
        # ``brake_command`` 必须是 **1.0** 而不是上面的 ``command``：
        # ``evaluate_braking`` 里 ``brake_demand_n = −required_n · brake_command``，
        # 而这里的 ``required_n = m_eff·a + 阻力 = −applied_brake_n = −command·brake_ceiling``
        # 已经含过一次 ``command``；再乘一次会变成 ``command²``（双重施加）。
        # 取 1.0 时 ``brake_demand_n = command·brake_ceiling``，与被控对象当步
        # 实际施加的制动力**逐位一致**（``brake_ceiling = min(车辆上限, 黏着上限)``）。
        samples[-1] = BrakingInput(
            time_s=time_s,
            position_km=position_km,
            speed_mps=speed,
            acceleration_mps2=acceleration,
            gradient_per_mille=gradient,
            curve_radius_m=curve_radius,
            speed_limit_mps=speed_limit_mps,
            brake_command=1.0,
        )

        speed = max(v_stop_mps, speed + acceleration * dt)
        position_km += speed * dt / 1000.0
        time_s += dt

    # 问题 29：限速逐点取自共享数据，必须逐点校验（每个样本自带所在区段的限速）。
    _check_speed_limit_respected(samples)

    return ProfileSeries(
        scenario_id=scenario_id,
        samples=tuple(samples),
        dt=dt,
        description=description,
        notes=(f"区段 {start_km:.3f}~{end_km:.3f} km，入口速度 {v0 * 3.6:.2f} km/h，制动指令 {command:.2f}",),
        shared_data_refs=("shared/segments.csv", "shared/gradients.csv", "shared/curves.csv"),
    )


def segmented_braking_series(
    profile: TrainBrakingProfile,
    v0_mps: float,
    segments: Sequence[Tuple[float, float, float]],
    dt: float,
    v_end_mps: float = 0.0,
    curve_radius_m: Optional[float] = None,
    speed_limit_mps: Optional[float] = None,
    start_position_km: float = 0.0,
    scenario_id: str = "segmented_braking",
    description: str = "分段恒减速度制动（段间有减速度/坡度阶跃）",
) -> ProfileSeries:
    """分段恒减速度制动剖面（阶段 9 的"制动功率突变"与"强非线性"场景用）。

    ``segments`` 每项为 ``(duration_s, decel_mps2, gradient_per_mille)``。
    段内减速度与坡度恒定，**段与段之间是阶跃**——这正是触发模式切换判据的激励：

    * 减速度阶跃 → 请求再生功率阶跃（``power_step``）与速度变化率的导数尖峰
      （``speed_jerk``）；
    * 坡度阶跃 → ``gradient_step``。

    每段的减速度都会按该段的**首末速度**分别做可达性校验（取更严的一侧），
    校验不通过直接报错，而不是静默截断——理由同
    :func:`_check_deceleration_is_achievable`。
    """

    dt = _check_dt(dt)
    v0 = _check_speed(v0_mps, "v0_mps")
    v_end = _check_speed(v_end_mps, "v_end_mps")
    if v_end > v0:
        raise ProfileError("v_end_mps 不得大于 v0_mps")
    if not segments:
        raise ProfileError("segments 不得为空")

    samples: List[BrakingInput] = []
    speed = v0
    position_km = start_position_km
    time_s = 0.0
    notes: List[str] = []

    for index, segment in enumerate(segments):
        if len(segment) != 3:
            raise ProfileError(f"第 {index} 段必须为 (duration_s, decel_mps2, gradient_per_mille)")
        duration, decel, gradient = float(segment[0]), float(segment[1]), float(segment[2])
        if not math.isfinite(duration) or duration < 0.0:
            raise ProfileError(f"第 {index} 段 duration_s 必须为非负有限值，实际为 {duration!r}")
        if not math.isfinite(decel) or decel < 0.0:
            raise ProfileError(f"第 {index} 段 decel_mps2 必须为非负有限值，实际为 {decel!r}")
        if not math.isfinite(gradient):
            raise ProfileError(f"第 {index} 段 gradient_per_mille 必须为有限值，实际为 {gradient!r}")

        segment_end_speed = max(v_end, speed - decel * duration)
        if decel > 0.0:
            _check_deceleration_is_achievable(
                profile, decel, (speed, segment_end_speed), gradient, curve_radius_m
            )

        steps = int(round(duration / dt))
        for _ in range(steps):
            if speed <= v_end + 1e-9:
                break
            samples.append(
                BrakingInput(
                    time_s=time_s,
                    position_km=position_km,
                    speed_mps=speed,
                    acceleration_mps2=-decel,
                    gradient_per_mille=gradient,
                    curve_radius_m=curve_radius_m,
                    speed_limit_mps=speed_limit_mps,
                    brake_command=1.0,
                )
            )
            position_km += speed * dt / 1000.0
            speed = max(v_end, speed - decel * dt)
            time_s += dt

        notes.append(f"段{index}: {duration:.2f}s / {decel:.3f} m/s^2 / {gradient:.2f} ‰")

    if not samples:
        raise ProfileError("segments 未产生任何样本（检查 duration 与 v_end_mps）")

    _check_speed_limit_respected(samples, speed_limit_mps)

    return ProfileSeries(
        scenario_id=scenario_id,
        samples=tuple(samples),
        dt=dt,
        description=description,
        notes=tuple(notes),
        shared_data_refs=(),
    )


def long_downhill_ranges_from_shared(
    shared: SharedRailwayData,
    max_gradient_per_mille: float = -6.0,
    min_length_km: float = 1.0,
) -> List[Tuple[float, float]]:
    """便捷入口：直接从共享真实坡度数据给出长大下坡区段。"""

    from ..io.data_loader import find_long_downhill_ranges

    return find_long_downhill_ranges(
        shared,
        max_gradient_per_mille=max_gradient_per_mille,
        min_length_km=min_length_km,
    )
