"""列车制动工况模型：机械制动力与制动功率的物理计算。

单位约定（全项目统一，SI）：

    长度 m | 时间 s | 质量 kg | 力 N | 功率 W | 能量 J | 电压 V | 电流 A
    坡度 ‰（gradient_per_mille） | 曲线半径 m | 速度 m/s

符号约定（关键，避免功率正负号混乱）：

    * 沿线路方向：牵引力为正、制动力为负；
    * 阻力 F_res 以"阻碍运动为正"（上坡坡道阻力为正、下坡为负）；
    * 制动功率 mechanical_braking_power_w 以"列车动能流向制动系统为正"，
      即制动工况下恒为非负；牵引工况下为 0。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

GRAVITY_M_PER_S2 = 9.81

# 曲线附加阻力折算系数：w_r = 600 / R [N/kN]，与共享项目同一折算约定。
DEFAULT_CURVE_NUMERATOR = 600.0


class TrainModelError(ValueError):
    """列车参数或输入不合法。"""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TrainModelError(f"{name} 必须为有限数值，实际为 {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TrainModelError(f"{name} 必须为有限数值，实际为 {value!r}") from exc
    if not math.isfinite(number):
        raise TrainModelError(f"{name} 必须为有限数值，实际为 {value!r}")
    return number


def _non_negative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise TrainModelError(f"{name} 必须非负，实际为 {number!r}")
    return number


# ------------------------------------------------------------------
# 阻力模型
# ------------------------------------------------------------------


@dataclass(frozen=True)
class BasicResistanceModel:
    """基本阻力（戴维斯形式）。

    basis = "per_kN_speed_kmh"：
        w0 [N/kN] = a + b * v[km/h] + c * v[km/h]^2
        F0 [N]    = w0 / 1000 * m[kg] * g

    这是国内重载货车常用口径，量纲自洽。
    """

    a_n_per_kn: float
    b_n_per_kn_per_kmh: float
    c_n_per_kn_per_kmh2: float
    basis: str = "per_kN_speed_kmh"
    curve_equivalent_per_mille_numerator: float = DEFAULT_CURVE_NUMERATOR

    def __post_init__(self) -> None:
        for name in ("a_n_per_kn", "b_n_per_kn_per_kmh", "c_n_per_kn_per_kmh2"):
            _non_negative(getattr(self, name), name)
        if self.basis != "per_kN_speed_kmh":
            raise TrainModelError(
                f"暂不支持的基本阻力基准 {self.basis!r}；"
                "共享 trains.csv 的 Davis 系数基准与之不同，需先确认后再接入。"
            )

    def specific_resistance_n_per_kn(self, speed_mps: float) -> float:
        speed_kmh = _non_negative(speed_mps, "speed_mps") * 3.6
        return self.a_n_per_kn + self.b_n_per_kn_per_kmh * speed_kmh + self.c_n_per_kn_per_kmh2 * speed_kmh**2

    def force_n(self, mass_kg: float, speed_mps: float) -> float:
        return self.specific_resistance_n_per_kn(speed_mps) / 1000.0 * mass_kg * GRAVITY_M_PER_S2

    def curve_equivalent_per_mille(self, curve_radius_m: Optional[float]) -> float:
        if curve_radius_m is None or curve_radius_m <= 0.0:
            return 0.0
        return self.curve_equivalent_per_mille_numerator / curve_radius_m


@dataclass(frozen=True)
class AdhesionLimit:
    """黏着限制（制动方向）。"""

    coefficient: float
    braking_safety_factor: float

    def __post_init__(self) -> None:
        _non_negative(self.coefficient, "adhesion.coefficient")
        _non_negative(self.braking_safety_factor, "adhesion.braking_safety_factor")

    def max_brake_force_n(self, mass_kg: float) -> float:
        return self.coefficient * mass_kg * GRAVITY_M_PER_S2 * self.braking_safety_factor


# ------------------------------------------------------------------
# 电制动曲线
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ElectricalBrakeCurve:
    """电制动力上限曲线，按机车台数与投入级位折算到全列。

    曲线来源是机车手册的**单台**电制动力表（速度 km/h → 制动力 kN）：它描述的是
    「电机 + 变流器能给出多少电制动力」，与车辆闸瓦/空气制动的总量
    ``max_brake_force_n`` 不是一回事。把后者当作再生能力上限会把可回收电量
    高估一个数量级。

    ``electrical_level`` 是电制动投入级位（占曲线能力的份额）：司机不是每次都
    满级位投入，该系数只改变「电制动 / 空气制动」的分摊比例，**不改变总制动力**，
    因此速度轨迹不变、可离线标定。
    """

    points_kmh_kn: Tuple[Tuple[float, float], ...]
    locomotive_count: int = 1
    electrical_level: float = 1.0
    #: 单台机车的再生发电有功电流曲线（速度 km/h → 电流 A），附录 L。
    #: 与 ``points_kmh_kn`` 成对使用：前者描述「能给出多少力」，后者描述「对应
    #: 多少电流」，两条曲线都来自标准表，是互相独立的两个口径。
    current_points_kmh_a: Tuple[Tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.locomotive_count < 1:
            raise TrainModelError(f"locomotive_count 必须 >= 1：{self.locomotive_count}")
        level = _finite(self.electrical_level, "electrical_level")
        if not 0.0 <= level <= 1.0:
            raise TrainModelError(f"electrical_level 必须在 [0, 1] 内：{level}")
        if not self.points_kmh_kn:
            raise TrainModelError("电制动曲线至少需要一个点")

    @property
    def peak_force_n(self) -> float:
        return max(y for _, y in self.points_kmh_kn) * 1000.0 * self.locomotive_count * self.electrical_level

    def force_limit_n(self, speed_mps: float) -> float:
        """全列电制动力上限（N）。曲线端点外取端点值，不外推。"""

        speed_kmh = max(0.0, speed_mps) * 3.6
        points = self.points_kmh_kn
        if speed_kmh <= points[0][0]:
            kn = points[0][1]
        elif speed_kmh >= points[-1][0]:
            kn = points[-1][1]
        else:
            kn = points[-1][1]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if x0 <= speed_kmh <= x1:
                    kn = y1 if x1 <= x0 else y0 + (y1 - y0) * (speed_kmh - x0) / (x1 - x0)
                    break
        return kn * 1000.0 * self.locomotive_count * self.electrical_level

    @property
    def has_regen_current(self) -> bool:
        return bool(self.current_points_kmh_a)

    def regen_current_limit_a(self, speed_mps: float) -> float:
        """全列再生发电电流上限（A），按台数与级位折算。

        曲线是**单台、满级位**的电流表；台数与级位按线性折算——级位降低时
        电制动力按比例减小，同一网压下电流也按比例减小（``P = U·I`` 且
        ``P ∝ F·v``）。因此这里的值只在「电制动力用满曲线」时成立，实际拍
        还要乘以利用率 λ = 实际再生力 / 曲线力上限。
        """

        if not self.current_points_kmh_a:
            return 0.0
        speed_kmh = max(0.0, speed_mps) * 3.6
        points = self.current_points_kmh_a
        if speed_kmh <= points[0][0]:
            amps = points[0][1]
        elif speed_kmh >= points[-1][0]:
            amps = points[-1][1]
        else:
            amps = points[-1][1]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if x0 <= speed_kmh <= x1:
                    amps = y1 if x1 <= x0 else y0 + (y1 - y0) * (speed_kmh - x0) / (x1 - x0)
                    break
        return amps * self.locomotive_count * self.electrical_level


# ------------------------------------------------------------------
# 列车剖面
# ------------------------------------------------------------------


@dataclass(frozen=True)
class TrainBrakingProfile:
    """单列车制动仿真所需的列车侧参数。"""

    name: str
    mass_kg: float
    rotational_mass_factor: float
    max_brake_force_n: float
    max_regen_force_n: float
    regen_fraction_cap: float
    resistance: BasicResistanceModel
    adhesion: AdhesionLimit
    length_m: float = 0.0
    data_status: str = "unknown"
    provenance: Mapping[str, Any] = None  # type: ignore[assignment]
    #: 电制动力上限曲线；为 None 时退化为常数 max_regen_force_n
    regen_force_curve: Optional[ElectricalBrakeCurve] = None
    #: 车辆总重（kg，不含机车）。非 None 表示 mass_kg 已按「车重 + 机车」组合过，
    #: 再次叠加机车时以它为基准，保证 ``with_locomotives`` 幂等
    vehicle_mass_kg: Optional[float] = None
    #: 已叠加的机车质量（kg），仅作记录与幂等校验
    locomotive_mass_kg: float = 0.0
    #: 机车机型与台数（来自共享数据 trains.csv，用于定标定与审计）
    locomotive_type: str = ""
    locomotive_count: int = 1
    #: 电制动投入级位（占曲线能力的份额），只影响电/空制动分摊
    electrical_level: float = 1.0
    #: 牵引网电压（V），来自共享数据 ``regen_energy_formula.U_w_kV``。
    #: 只用于标准式(72) 的电流积分校核，**不参与**本仿真的直流母线计算
    #: （母线是 1500 V 级，接触网是 27.2 kV 级，两者不可混用）。
    catenary_voltage_v: Optional[float] = None

    def __post_init__(self) -> None:
        _non_negative(self.mass_kg, "mass_kg")
        if self.mass_kg <= 0.0:
            raise TrainModelError("mass_kg 必须为正")
        factor = _finite(self.rotational_mass_factor, "rotational_mass_factor")
        if factor < 1.0:
            raise TrainModelError("rotational_mass_factor 必须 >= 1.0（含回转质量）")
        _non_negative(self.max_brake_force_n, "max_brake_force_n")
        _non_negative(self.max_regen_force_n, "max_regen_force_n")
        cap = _finite(self.regen_fraction_cap, "regen_fraction_cap")
        if not 0.0 <= cap <= 1.0:
            raise TrainModelError("regen_fraction_cap 必须在 [0, 1] 内")
        if self.catenary_voltage_v is not None:
            voltage = _finite(self.catenary_voltage_v, "catenary_voltage_v")
            if voltage <= 0.0:
                raise TrainModelError(f"catenary_voltage_v 必须为正：{voltage}")

    @property
    def effective_mass_kg(self) -> float:
        """含回转质量的等效质量。"""

        return self.mass_kg * self.rotational_mass_factor

    def with_locomotives(
        self, locomotive_mass_kg: float, *, count: int = 1
    ) -> "TrainBrakingProfile":
        """按「车辆总重 + 台数 × 单台机车自重」重算整备质量。

        **幂等**：以 `vehicle_mass_kg` 为基准重算，重复调用不会叠加。共享数据的
        ``trains.csv:mass_tons`` 永远是车辆总重，机车质量必须在这里加，不能
        就地改写 ``mass_tons`` 的语义。
        """

        if count < 0:
            raise TrainModelError(f"locomotive_count 不能为负：{count}")
        _non_negative(locomotive_mass_kg, "locomotive_mass_kg")
        base = self.vehicle_mass_kg if self.vehicle_mass_kg is not None else self.mass_kg
        added = count * locomotive_mass_kg
        return replace(
            self,
            mass_kg=base + added,
            vehicle_mass_kg=base,
            locomotive_mass_kg=added,
        )

    def with_regen_curve(self, curve: Optional[ElectricalBrakeCurve]) -> "TrainBrakingProfile":
        """挂上电制动力曲线（曲线按台数与级位折算到全列）。"""

        return replace(self, regen_force_curve=curve)

    @classmethod
    def from_parameters(cls, payload: Mapping[str, Any]) -> "TrainBrakingProfile":
        """从 data/single_train/train_parameters.json 构造。

        ``vehicle_mass_tons`` 存在时，``vehicle_mass_kg`` 作为「车重基准」记入，
        后续叠加机车质量都从它重算——这是 ``with_locomotives`` 幂等的前提。
        """

        resistance_raw = payload.get("basic_resistance") or {}
        adhesion_raw = payload.get("adhesion") or {}
        vehicle_tons = payload.get("vehicle_mass_tons")
        vehicle_mass_kg = (
            _finite(vehicle_tons, "vehicle_mass_tons") * 1000.0
            if vehicle_tons is not None
            else None
        )
        return cls(
            name=str(payload.get("profile_id", "unknown")),
            mass_kg=_finite(payload.get("mass_kg"), "mass_kg"),
            rotational_mass_factor=_finite(payload.get("rotational_mass_factor", 1.0), "rotational_mass_factor"),
            max_brake_force_n=_finite(payload.get("max_brake_force_n"), "max_brake_force_n"),
            max_regen_force_n=_finite(payload.get("max_regen_force_n"), "max_regen_force_n"),
            regen_fraction_cap=_finite(payload.get("regen_fraction_cap", 1.0), "regen_fraction_cap"),
            resistance=BasicResistanceModel(
                a_n_per_kn=_finite(resistance_raw.get("a_n_per_kn"), "basic_resistance.a_n_per_kn"),
                b_n_per_kn_per_kmh=_finite(resistance_raw.get("b_n_per_kn_per_kmh"), "basic_resistance.b"),
                c_n_per_kn_per_kmh2=_finite(resistance_raw.get("c_n_per_kn_per_kmh2"), "basic_resistance.c"),
                basis=str(resistance_raw.get("basis", "per_kN_speed_kmh")),
                curve_equivalent_per_mille_numerator=_finite(
                    resistance_raw.get("curve_equivalent_per_mille_numerator", DEFAULT_CURVE_NUMERATOR),
                    "basic_resistance.curve_equivalent_per_mille_numerator",
                ),
            ),
            adhesion=AdhesionLimit(
                coefficient=_finite(adhesion_raw.get("coefficient"), "adhesion.coefficient"),
                braking_safety_factor=_finite(adhesion_raw.get("braking_safety_factor"), "adhesion.braking_safety_factor"),
            ),
            length_m=_finite(payload.get("train_length_m", 0.0), "train_length_m"),
            data_status=str(payload.get("data_status", "unknown")),
            provenance=dict(payload.get("provenance") or {}),
            locomotive_type=str(payload.get("locomotive_type", "") or ""),
            locomotive_count=int(
                _finite(payload.get("locomotive_count", 1.0), "locomotive_count")
            ),
            electrical_level=_finite(payload.get("electrical_level", 1.0), "electrical_level"),
            vehicle_mass_kg=vehicle_mass_kg,
        )


# ------------------------------------------------------------------
# 制动工况输入
# ------------------------------------------------------------------


@dataclass(frozen=True)
class BrakingInput:
    """某一时刻的列车运行输入（全部 SI）。"""

    time_s: float
    position_km: float
    speed_mps: float
    acceleration_mps2: float
    gradient_per_mille: float = 0.0
    curve_radius_m: Optional[float] = None
    speed_limit_mps: Optional[float] = None
    brake_command: float = 1.0

    def __post_init__(self) -> None:
        _non_negative(self.speed_mps, "speed_mps")
        _finite(self.acceleration_mps2, "acceleration_mps2")
        _finite(self.gradient_per_mille, "gradient_per_mille")
        cmd = _finite(self.brake_command, "brake_command")
        if not 0.0 <= cmd <= 1.0:
            raise TrainModelError(f"brake_command 必须在 [0, 1] 内，实际为 {cmd!r}")


# ------------------------------------------------------------------
# 制动功率分解
# ------------------------------------------------------------------


@dataclass(frozen=True)
class BrakingPowerBreakdown:
    """单步制动力的完整分解（力 N，功率 W）。"""

    basic_resistance_n: float
    gradient_resistance_n: float
    curve_resistance_n: float
    inertia_force_n: float

    total_resistance_n: float
    required_force_n: float
    traction_force_n: float

    brake_demand_n: float
    adhesion_limit_n: float
    brake_force_n: float
    regen_wheel_force_n: float
    friction_brake_force_n: float

    mechanical_braking_power_w: float
    regen_wheel_power_w: float
    friction_braking_power_w: float

    @property
    def is_braking(self) -> bool:
        return self.brake_force_n > 0.0

    @property
    def brake_force_saturated(self) -> bool:
        """制动力是否被上限（车辆上限或黏着上限）截断。"""

        return self.brake_force_n + 1e-9 < self.brake_demand_n

    def as_dict(self) -> Mapping[str, float]:
        return {
            "basic_resistance_n": self.basic_resistance_n,
            "gradient_resistance_n": self.gradient_resistance_n,
            "curve_resistance_n": self.curve_resistance_n,
            "inertia_force_n": self.inertia_force_n,
            "total_resistance_n": self.total_resistance_n,
            "required_force_n": self.required_force_n,
            "traction_force_n": self.traction_force_n,
            "brake_demand_n": self.brake_demand_n,
            "adhesion_limit_n": self.adhesion_limit_n,
            "brake_force_n": self.brake_force_n,
            "regen_wheel_force_n": self.regen_wheel_force_n,
            "friction_brake_force_n": self.friction_brake_force_n,
            "mechanical_braking_power_w": self.mechanical_braking_power_w,
            "regen_wheel_power_w": self.regen_wheel_power_w,
            "friction_braking_power_w": self.friction_braking_power_w,
        }


def evaluate_braking(profile: TrainBrakingProfile, state: BrakingInput) -> BrakingPowerBreakdown:
    """计算某时刻的制动力分解与制动功率。

    物理链条：
        1) 基本阻力 + 坡道阻力 + 曲线阻力 -> 总阻力
        2) 惯性力 = 含回转质量的等效质量 x 加速度
        3) 需求力 = 惯性力 + 总阻力；为负说明需要制动
        4) 制动力受 [车辆最大制动力, 黏着上限, 制动指令] 三重限制
        5) 制动力再拆成 再生（电制动） + 摩擦（空气/踏面制动）
    """

    mass_kg = profile.mass_kg
    speed_mps = state.speed_mps

    basic_n = profile.resistance.force_n(mass_kg, speed_mps)
    gradient_n = mass_kg * GRAVITY_M_PER_S2 * (state.gradient_per_mille / 1000.0)
    curve_permille = profile.resistance.curve_equivalent_per_mille(state.curve_radius_m)
    curve_n = mass_kg * GRAVITY_M_PER_S2 * (curve_permille / 1000.0)

    total_resistance_n = basic_n + gradient_n + curve_n
    inertia_n = profile.effective_mass_kg * state.acceleration_mps2
    required_n = inertia_n + total_resistance_n

    if required_n < 0.0:
        brake_demand_n = -required_n * state.brake_command
        traction_force_n = 0.0
    else:
        brake_demand_n = 0.0
        traction_force_n = required_n

    adhesion_limit_n = profile.adhesion.max_brake_force_n(mass_kg)
    brake_force_n = min(brake_demand_n, profile.max_brake_force_n, adhesion_limit_n)

    # 可回收的再生力上限：车辆绝对上限、电制动能力、可再生比例上限三者取小。
    # 曲线存在时它才是真正的瓶颈——车辆制动力上限描述的是闸瓦+电制动总量，
    # 直接拿它当再生能力会高估一个数量级。
    #
    # 电制动能力只有一个来源，两种形态：
    #   * 有曲线（注入共享数据）：`force_limit_n(v)` 已按台数与级位折算到位，
    #     **它单独说了算**。此时再乘一个常数上限是错的——参数文件里的
    #     `max_regen_force_n` 是**单台**曲线峰值，台数 ≠ 1 时它会把全列能力卡回 1 台
    #     （实测：2 台在 60 km/h 应有的 663.8 kN 被压到 331.9 kN，λ 恒为 0.5）。
    #   * 无曲线（未注入共享数据）：只能用「单台峰值 × 级位」的常数近似，
    #     缺速度衰减段，必须由 `parameter_status.shared_rolling_stock=absent` 显式标注。
    if profile.regen_force_curve is not None:
        regen_capacity_n = profile.regen_force_curve.force_limit_n(speed_mps)
    else:
        regen_capacity_n = profile.max_regen_force_n * profile.electrical_level
    regen_limit_n = min(
        brake_force_n,
        regen_capacity_n,
        profile.regen_fraction_cap * brake_force_n,
    )
    regen_wheel_force_n = regen_limit_n
    friction_brake_force_n = brake_force_n - regen_wheel_force_n

    return BrakingPowerBreakdown(
        basic_resistance_n=basic_n,
        gradient_resistance_n=gradient_n,
        curve_resistance_n=curve_n,
        inertia_force_n=inertia_n,
        total_resistance_n=total_resistance_n,
        required_force_n=required_n,
        traction_force_n=traction_force_n,
        brake_demand_n=brake_demand_n,
        adhesion_limit_n=adhesion_limit_n,
        brake_force_n=brake_force_n,
        regen_wheel_force_n=regen_wheel_force_n,
        friction_brake_force_n=friction_brake_force_n,
        mechanical_braking_power_w=brake_force_n * speed_mps,
        regen_wheel_power_w=regen_wheel_force_n * speed_mps,
        friction_braking_power_w=friction_brake_force_n * speed_mps,
    )


def coasting_deceleration(profile: TrainBrakingProfile, speed_mps: float, gradient_per_mille: float) -> float:
    """无制动无牵引时的自然减速度（用于构造工况剖面）。"""

    resistance_n = profile.resistance.force_n(profile.mass_kg, speed_mps) + (
        profile.mass_kg * GRAVITY_M_PER_S2 * (gradient_per_mille / 1000.0)
    )
    return -resistance_n / profile.effective_mass_kg


def total_resistance_n(
    profile: TrainBrakingProfile,
    speed_mps: float,
    gradient_per_mille: float = 0.0,
    curve_radius_m: Optional[float] = None,
) -> float:
    """总阻力（阻碍运动为正）：基本 + 坡道 + 曲线。"""

    basic = profile.resistance.force_n(profile.mass_kg, speed_mps)
    gradient = profile.mass_kg * GRAVITY_M_PER_S2 * (_finite(gradient_per_mille, "gradient_per_mille") / 1000.0)
    curve_permille = profile.resistance.curve_equivalent_per_mille(curve_radius_m)
    curve = profile.mass_kg * GRAVITY_M_PER_S2 * (curve_permille / 1000.0)
    return basic + gradient + curve


def brake_force_ceiling_n(profile: TrainBrakingProfile) -> float:
    """可用制动力的物理上限 = min(车辆最大制动力, 黏着限制)。"""

    return min(profile.max_brake_force_n, profile.adhesion.max_brake_force_n(profile.mass_kg))


def max_achievable_deceleration(
    profile: TrainBrakingProfile,
    speed_mps: float,
    gradient_per_mille: float = 0.0,
    curve_radius_m: Optional[float] = None,
) -> float:
    """给定速度与线路条件下，列车能实现的**最大减速度**（m/s²，正值表示减速能力）。

    推导：制动工况下
        m_eff * a = -F_brake + F_res
    要求减速度大小 decel = -a，且 F_brake <= F_brake_ceiling，于是
        decel <= (F_brake_ceiling + F_res) / m_eff

    关键物理含义（易被写反，这里显式固化）：
        * 下坡时 F_res 为负（重力沿运动方向），可用制动力的"预算"被重力占用，
          因此**同样减速度在下坡需要更大的制动力**；
          极端情况下 decel 上限会低于平直道，甚至为负（坡度大到靠制动都压不住）。
        * 上坡时 F_res 为正，阻力本身参与减速，可达减速度更大。
    """

    speed = _non_negative(speed_mps, "speed_mps")
    resistance = total_resistance_n(profile, speed, gradient_per_mille, curve_radius_m)
    return (brake_force_ceiling_n(profile) + resistance) / profile.effective_mass_kg
