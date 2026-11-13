"""双向 DC-DC 升降压变换器：T1/T2 双开关平均模型（含直流母线刚源）。

拓扑与建模口径
--------------

非隔离双向 Buck-Boost：T1 为 buck 侧开关，T2 为 boost 侧开关。

直流母线（输入侧）按「刚性电压源 + 源阻抗 + 输入电容」建模，这是变流器类
控制研究中标准的直流母线口径，也是本场景的真实物理来源：

    * 母线开路电压 v_oc 由牵引传动/接触网侧维持；
    * 源阻抗 R_src 承担母线电压偏差下的功率交换 —— 变流器少取的部分
      会经由母线返回牵引网（这正是"再生能量回馈电网"的物理通道）；
    * 输入电容 C_in 承担暂态。

平均模型状态方程（三阶）：

    L      di_L/dt   = d1 * v_in - (1 - d2) * v_out - R_L * i_L
    C_in   dv_in/dt  = eta * i_src + i_grid - d1 * i_L
    C_out  dv_out/dt = (1 - d2) * i_L - i_sink

    i_grid = (v_oc - v_in) / R_src          （直流母线侧：刚性源 + 源阻抗）
    i_sink = clamp((v_out - v_oc_st) / R_int)（储能侧：开路电压 + 内阻）

输出侧为什么用「储能开路电压 + 内阻」而不是「恒功率负载 P_load / v_out」：

    * 恒功率负载会让 sink 电流与 v_out 反向耦合，d1 过低时 v_out 会塌陷并发散；
    * 更致命的是，若把上一时刻的储能接受功率回灌成负载功率，会形成
      "负载 0 -> 输出 0 -> 接受 0 -> 负载 0" 的自锁，闭环永远启动不起来；
    * 用内阻形式后 i_sink 只是状态 v_out 的函数，ODE 自洽：
      只有占空比把 v_out 抬到储能开路电压之上才有充电电流，
      因此**占空比是真实的功率流执行器**，NSMC 才有可用的控制杠杆。
    * 该形式天然有界：v_out 上界趋于 d1 * v_in，i_L 随之自动回落，不会发散。

效率以「输入侧等效电流损失 (1-eta)*i_src」实现，保证节点 KCL 与能量守恒严格成立。

能量闭合关系（单元测试直接验证）：

    mechanical = friction + motor_loss + conversion_loss + inductor_loss
                 + storage_loss + storage_energy + curtailed
                 + ΔE_reactive + grid_export

其中 grid_export 为经直流母线返回牵引网的能量。

说明：本模型为平均模型，用于控制层仿真，不做开关级仿真。
所有电力电子参数当前均为 placeholder，非实测硬件参数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Tuple

from .train_braking_model import _finite, _non_negative

VOLTAGE_FLOOR_V = 1.0

#: 方案问题编号 **32**（实现期自行发现，非方案正文问题）：**「额定功率」有两个问题叠在一起**。
#:
#: ① **一符两义**：``DCConverterStepResult.power_limited_by_rating`` 的名字承诺
#:    一次**功率**额定值判定，但实现写的是
#:    ``abs(i_src) > params.max_input_current_a + 1e-9`` —— 与同一结果对象上的
#:    ``input_current_over_limit`` **逐位相同**（两行同一表达式）。任何按名字读
#:    ``power_limited_by_rating`` 的消费者（含审计者本人）都会拿到一个**电流**答案
#:    却以为是**功率**答案。
#:
#: ② **被读入却无消费点**：``DCConverterParameters.power_rating_w``（
#:    ``dc_dc_parameters.json`` 的 ``28800000.0 W``，``field_data_status = "assumed"``，
#:    provenance「沿用电机再生功率量级 28800 kW 作为额定功率上界」）只在
#:    ``__post_init__`` 里被校验为正数、在 ``from_parameters`` 里被读出，
#:    **全仓没有任何计算使用它**。于是"变流器是否越额定功率"这件事在代码里
#:    根本无法被判定，而算法文档 §8 的参数表把「额定功率」列为
#:    ``dc_dc_parameters.json`` 的关键 assumed 字段（读起来像在生效）。
#:
#: 实测（``tools/probe_converter_rating_audit.py``，官方套件配置，``dt = 2e-4``，
#: ``record_stride = 1``）：``s1_flat_braking`` / ``s4_power_step`` 的 ``max|p_in|``
#: 为 ``25.92 MW`` = 额定的 **``90.0%``**、``s2_long_downhill`` 为 ``19.13 MW``；
#: ``max|i_src|`` 为 ``16231 A`` = ``max_input_current_a``（``24000 A``）的 ``67.6%``。
#: 两者**在全部官方场景里都没有越限**，所以本条修复对交付数字**零影响**；
#: 但额定值只留 ``10%`` 余量，且越限时**没有任何输出会报出来**——
#: 这正是"静默"的成因。
#:
#: 修复：① ``power_limited_by_rating`` 改为按 ``power_rating_w`` 判定（名副其实）；
#: ② 给额定值补上**消费点**：``SimulationResult`` 携带 ``converter_limits``，
#: 场景指标新增 ``converter_over_rating_ratio`` 与
#: ``converter_input_current_over_limit_ratio``（与 ``duty_saturation_ratio``
#: 同一口径：按 ``record_stride`` 抽样后的逐步记录统计），运行备注同时给出
#: 越限拍数。两条限值仍然**只报告、不截断**（见 :meth:`BidirectionalDCDCConverter.step`
#: 的 Note：超出的部分抬高母线电压经 ``i_grid`` 回网，是真实物理去向）。
SCHEME_ISSUE_RATING_FLAG_CONFLATED = 32


class ConverterError(ValueError):
    """变流器参数或输入不合法。"""


class ConverterNumericalError(RuntimeError):
    """平均模型数值发散（通常意味着控制量不物理或步长过大）。"""


@dataclass(frozen=True)
class DutyLimits:
    """PWM 占空比硬边界。"""

    min_duty: float = 0.0
    max_duty: float = 1.0
    u0_max: float = 0.9

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_duty <= self.max_duty <= 1.0:
            raise ConverterError("必须满足 0 <= min_duty <= max_duty <= 1")
        if not 0.0 < self.u0_max <= 1.0:
            raise ConverterError("u0_max 必须在 (0, 1] 内")

    def clamp(self, duty: float) -> float:
        return min(max(_finite(duty, "duty"), self.min_duty), self.max_duty)

    def clamp_with_u0(self, duty: float) -> float:
        """按技术方案 u0=0.9 上限限幅（用于避免 IGBT 过流）。"""

        return min(max(_finite(duty, "duty"), self.min_duty), min(self.max_duty, self.u0_max))


@dataclass(frozen=True)
class StorageBusRequest:
    """储能侧母线（DC-DC 输出端）的电气边界。

    输出侧按「储能开路电压 v_oc + 内阻 R_int」建模，这是电池/飞轮挂在直流母线上的
    标准口径：

        i_sink = (v_out - v_oc) / R_int

    行为：
        * v_out > v_oc ：向储能充电，i_sink > 0；
        * v_out < v_oc ：regen 模式下 i_sink 截断为 0（储能不再吸收，能量留在母线回网）；
        * allow_discharge=True 时允许 i_sink < 0，即储能向母线放电
          （预留 discharge / support 模式，本阶段不启用）。

    功率上限按 `available_*_power_w / v_out` 折算成电流上限，从而把储能模型的
    SOC 余量与最大充放电功率约束带进变流器方程。
    """

    open_circuit_voltage_v: float
    internal_resistance_ohm: float
    available_charge_power_w: float
    available_discharge_power_w: float = 0.0
    allow_discharge: bool = False
    data_status: str = "unknown"

    def __post_init__(self) -> None:
        _non_negative(self.open_circuit_voltage_v, "storage_bus.open_circuit_voltage_v")
        if _finite(self.internal_resistance_ohm, "storage_bus.internal_resistance_ohm") <= 0.0:
            raise ConverterError("storage_bus.internal_resistance_ohm 必须为正（否则 sink 电流无界）")
        _non_negative(self.available_charge_power_w, "storage_bus.available_charge_power_w")
        _non_negative(self.available_discharge_power_w, "storage_bus.available_discharge_power_w")


@dataclass(frozen=True)
class DCConverterParameters:
    inductance_h: float
    inductor_resistance_ohm: float
    input_capacitance_f: float
    output_capacitance_f: float
    switching_frequency_hz: float
    efficiency: float
    power_rating_w: float
    max_input_current_a: float
    max_output_current_a: float
    input_voltage_min_v: float
    input_voltage_nominal_v: float
    input_voltage_max_v: float
    output_voltage_min_v: float
    output_voltage_nominal_v: float
    output_voltage_max_v: float
    source_open_circuit_voltage_v: float
    source_resistance_ohm: float
    duty_limits: DutyLimits
    data_status: str = "unknown"
    provenance: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in (
            "inductance_h",
            "input_capacitance_f",
            "output_capacitance_f",
            "switching_frequency_hz",
            "power_rating_w",
            "max_input_current_a",
            "max_output_current_a",
            "source_open_circuit_voltage_v",
            "source_resistance_ohm",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ConverterError(f"{name} 必须为正，实际为 {value!r}")
        _non_negative(self.inductor_resistance_ohm, "inductor_resistance_ohm")
        eta = _finite(self.efficiency, "efficiency")
        if not 0.0 < eta <= 1.0:
            raise ConverterError("efficiency 必须在 (0, 1] 内")
        for lo, mid, hi, tag in (
            (self.input_voltage_min_v, self.input_voltage_nominal_v, self.input_voltage_max_v, "input"),
            (self.output_voltage_min_v, self.output_voltage_nominal_v, self.output_voltage_max_v, "output"),
        ):
            if not lo < mid < hi:
                raise ConverterError(f"{tag} 电压窗口必须满足 min < nominal < max")

    @property
    def switching_period_s(self) -> float:
        return 1.0 / self.switching_frequency_hz

    @classmethod
    def from_parameters(cls, payload: Mapping[str, Any]) -> "DCConverterParameters":
        duty_raw = payload.get("duty_limit") or {}
        in_raw = payload.get("input_voltage_window") or {}
        out_raw = payload.get("output_voltage_window") or {}
        source_raw = payload.get("dc_bus_source") or {}
        return cls(
            inductance_h=_finite(payload.get("inductance_h"), "inductance_h"),
            inductor_resistance_ohm=_finite(payload.get("inductor_resistance_ohm", 0.0), "inductor_resistance_ohm"),
            input_capacitance_f=_finite(payload.get("input_capacitance_f"), "input_capacitance_f"),
            output_capacitance_f=_finite(payload.get("output_capacitance_f"), "output_capacitance_f"),
            switching_frequency_hz=_finite(payload.get("switching_frequency_hz"), "switching_frequency_hz"),
            efficiency=_finite(payload.get("converter_efficiency"), "converter_efficiency"),
            power_rating_w=_finite(payload.get("power_rating_w"), "power_rating_w"),
            max_input_current_a=_finite(payload.get("max_input_current_a"), "max_input_current_a"),
            max_output_current_a=_finite(payload.get("max_output_current_a"), "max_output_current_a"),
            input_voltage_min_v=_finite(in_raw.get("min_v"), "input_voltage_window.min_v"),
            input_voltage_nominal_v=_finite(in_raw.get("nominal_v"), "input_voltage_window.nominal_v"),
            input_voltage_max_v=_finite(in_raw.get("max_v"), "input_voltage_window.max_v"),
            output_voltage_min_v=_finite(out_raw.get("min_v"), "output_voltage_window.min_v"),
            output_voltage_nominal_v=_finite(out_raw.get("nominal_v"), "output_voltage_window.nominal_v"),
            output_voltage_max_v=_finite(out_raw.get("max_v"), "output_voltage_window.max_v"),
            source_open_circuit_voltage_v=_finite(
                source_raw.get("open_circuit_voltage_v", in_raw.get("nominal_v")), "dc_bus_source.open_circuit_voltage_v"
            ),
            source_resistance_ohm=_finite(source_raw.get("resistance_ohm"), "dc_bus_source.resistance_ohm"),
            duty_limits=DutyLimits(
                min_duty=_finite(duty_raw.get("min", 0.0), "duty_limit.min"),
                max_duty=_finite(duty_raw.get("max", 1.0), "duty_limit.max"),
                u0_max=_finite(duty_raw.get("u0_max", 0.9), "duty_limit.u0_max"),
            ),
            data_status=str(payload.get("data_status", "unknown")),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class DCConverterState:
    """变换器平均模型状态。"""

    inductor_current_a: float
    input_voltage_v: float
    output_voltage_v: float

    def reactive_energy_j(self, params: DCConverterParameters) -> float:
        return (
            0.5 * params.inductance_h * self.inductor_current_a**2
            + 0.5 * params.input_capacitance_f * self.input_voltage_v**2
            + 0.5 * params.output_capacitance_f * self.output_voltage_v**2
        )

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.inductor_current_a, self.input_voltage_v, self.output_voltage_v)


@dataclass(frozen=True)
class DCConverterStepResult:
    """单步结果（功率与电流，均为 SI）。

    .. warning::
       ``efficiency_effective`` **不是**一个有界效率，而是瞬时功率比
       ``output_power_w / |input_power_w|``（``|input_power_w| ≤ 1e-12`` 时记 0）。
       当输入功率近零、输出由电感/电容储能供给时该比值会发散——
       ``tools/probe_robustness_sweep.py`` 在 300 个随机工作点中实测 21 次 ``> 1``
       （最大约 9.6）。本项目的任何指标（``summary`` / ``comparison`` / ``manifest``）
       **都不消费该字段**；需要效率请用 ``efficiency_effective`` 之外的量
       （如 ``input_power_w`` 与 ``conversion_loss_w``）自行构造有界定义。
       保留该字段仅为诊断用，勿在报告里当作效率引用。
    """

    duty_cycle_T1: float
    duty_cycle_T2: float
    mode: str

    input_voltage_v: float
    input_current_a: float
    output_voltage_v: float
    output_current_a: float
    inductor_current_a: float

    input_power_w: float
    output_power_w: float
    conversion_loss_w: float
    inductor_loss_w: float
    grid_power_w: float
    grid_source_loss_w: float
    grid_terminal_power_w: float
    efficiency_effective: float
    power_limited_by_rating: bool

    input_voltage_out_of_window: bool
    output_voltage_out_of_window: bool
    input_current_over_limit: bool
    output_current_over_limit: bool

    @property
    def grid_export_power_w(self) -> float:
        """母线侧送出功率（>0 表示能量离开本项目边界，进入回网通道）。

        注意：这是**母线侧**口径，其中一部分会耗散在源阻抗 R_src 上，
        真正到达牵引网的是 grid_terminal_power_w。能量台账必须分开记，
        否则会把源阻抗损耗误记成"送网能量"。
        """

        return max(0.0, -self.grid_power_w)

    @property
    def grid_terminal_export_power_w(self) -> float:
        """真正到达牵引网（理想源端）的功率。"""

        return max(0.0, -self.grid_terminal_power_w)

    @property
    def grid_terminal_import_power_w(self) -> float:
        """从牵引网侧反向抽取的功率。

        物理来源：制动尾声电感电流衰减、以及启动瞬态电感建立电流时，
        直流母线需要从电网侧补入功率。这部分必须入账，
        否则能量台账会凭空多出等量的"缺口"。
        """

        return max(0.0, self.grid_terminal_power_w)

    @property
    def safety_violations(self) -> Tuple[str, ...]:
        issues: List[str] = []
        if self.input_voltage_out_of_window:
            issues.append("input_voltage_out_of_window")
        if self.output_voltage_out_of_window:
            issues.append("output_voltage_out_of_window")
        if self.input_current_over_limit:
            issues.append("input_current_over_limit")
        if self.output_current_over_limit:
            issues.append("output_current_over_limit")
        return tuple(issues)


class BidirectionalDCDCConverter:
    """双向 DC-DC 变换器平均模型（RK4 积分）。"""

    def __init__(self, params: DCConverterParameters, state: DCConverterState) -> None:
        self.params = params
        self.state = state

    @classmethod
    def at_nominal(cls, params: DCConverterParameters) -> "BidirectionalDCDCConverter":
        return cls(
            params,
            DCConverterState(
                inductor_current_a=0.0,
                input_voltage_v=params.source_open_circuit_voltage_v,
                output_voltage_v=params.output_voltage_nominal_v,
            ),
        )

    # ---------- 内部：导数 ----------
    @staticmethod
    def sink_current(v_out: float, bus: StorageBusRequest) -> float:
        """储能侧吸收电流（>0 充电，<0 放电，0 表示储能侧不吸收也不输出）。

        电流上限由储能可用功率折算：i_max = P_avail / v_out。
        该函数只依赖状态 v_out 与外生边界，因此不会与 ODE 形成代数环。
        """

        raw = (v_out - bus.open_circuit_voltage_v) / bus.internal_resistance_ohm
        voltage = max(v_out, VOLTAGE_FLOOR_V)
        if raw >= 0.0:
            cap = bus.available_charge_power_w / voltage
            return min(raw, max(cap, 0.0))
        if not bus.allow_discharge:
            return 0.0
        cap = bus.available_discharge_power_w / voltage
        return max(raw, -max(cap, 0.0))

    def _derivatives(
        self,
        state: Tuple[float, float, float],
        d1: float,
        d2: float,
        source_power_w: float,
        storage_bus: StorageBusRequest,
    ) -> Tuple[float, float, float]:
        i_l, v_in, v_out = state
        p = self.params
        # 电机侧按「功率源」建模：注入电流由当前母线电压解出 i_src = P / v_in。
        # 这样 ∫ v_in * i_src dt 恒等于 ∫ P dt，p_in 与电机电功率严格一致，
        # 避免"用步前电压算电流、用步后电压算功率"带来的 O(dt) 闭合缺口。
        i_src = source_power_w / max(v_in, VOLTAGE_FLOOR_V)
        i_grid = (p.source_open_circuit_voltage_v - v_in) / p.source_resistance_ohm
        i_sink = self.sink_current(v_out, storage_bus)
        # 续流二极管的单向性：regen_charge（buck）模式下电感电流只能由母线流向储能，
        # i_L >= 0；占空比为 0 时 i_L 衰减到 0 后由二极管截断并保持。
        # 若不截断，d1=0 会让 i_L 无界变负，把储能侧母线电压拉到负值（非物理）。
        i_l_coupled = max(0.0, i_l) if source_power_w >= 0.0 else min(0.0, i_l)
        di_l = (d1 * v_in - (1.0 - d2) * v_out - p.inductor_resistance_ohm * i_l) / p.inductance_h
        dv_in = (p.efficiency * i_src + i_grid - d1 * i_l_coupled) / p.input_capacitance_f
        dv_out = ((1.0 - d2) * i_l_coupled - i_sink) / p.output_capacitance_f
        return (di_l, dv_in, dv_out)

    def _rk4(
        self,
        dt: float,
        d1: float,
        d2: float,
        source_power_w: float,
        storage_bus: StorageBusRequest,
    ) -> Tuple[float, float, float]:
        y0 = self.state.as_tuple()
        k1 = self._derivatives(y0, d1, d2, source_power_w, storage_bus)
        y1 = tuple(y0[i] + 0.5 * dt * k1[i] for i in range(3))
        k2 = self._derivatives(y1, d1, d2, source_power_w, storage_bus)
        y2 = tuple(y0[i] + 0.5 * dt * k2[i] for i in range(3))
        k3 = self._derivatives(y2, d1, d2, source_power_w, storage_bus)
        y3 = tuple(y0[i] + dt * k3[i] for i in range(3))
        k4 = self._derivatives(y3, d1, d2, source_power_w, storage_bus)
        return tuple(y0[i] + dt / 6.0 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) for i in range(3))

    # ---------- 单步 ----------
    def step(
        self,
        dt: float,
        duty_cycle_T1: float,
        duty_cycle_T2: float,
        source_power_w: float,
        storage_bus: StorageBusRequest,
        apply_u0_limit: bool = False,
    ) -> DCConverterStepResult:
        """推进一步。

        Args:
            dt: 步长（s）。
            duty_cycle_T1: T1 占空比（buck 侧）。
            duty_cycle_T2: T2 占空比（boost 侧）。
            source_power_w: 电机侧注入直流母线的功率（>0 再生回馈，<0 放电支撑）。
            storage_bus: 储能侧母线电气边界（开路电压 / 内阻 / 可用充放电功率）。
            apply_u0_limit: 是否按技术方案 u0=0.9 限幅。

        Note:
            两条额定限值都只做**报告**，不由模型截断：超出部分会抬高母线电压并
            经 i_grid 通道回馈牵引网，这是真实系统的物理去向，因此不额外做钳位。

            方案问题 32：``power_limited_by_rating`` 与 ``input_current_over_limit``
            **不是**同一个判据——前者比较 ``|p_in|`` 与 ``power_rating_w``（额定**功率**），
            后者比较 ``|i_src|`` 与 ``max_input_current_a``（额定**输入电流**）。
            修复前两者共用同一表达式，见 :data:`SCHEME_ISSUE_RATING_FLAG_CONFLATED`。
        """

        dt = _finite(dt, "dt")
        if dt <= 0.0:
            raise ConverterError("dt 必须为正")
        if not isinstance(storage_bus, StorageBusRequest):
            raise ConverterError("storage_bus 必须是 StorageBusRequest")

        source_power = _finite(source_power_w, "source_power_w")

        limits = self.params.duty_limits
        raw_d1 = _finite(duty_cycle_T1, "duty_cycle_T1")
        raw_d2 = _finite(duty_cycle_T2, "duty_cycle_T2")
        d1 = limits.clamp_with_u0(raw_d1) if apply_u0_limit else limits.clamp(raw_d1)
        d2 = limits.clamp_with_u0(raw_d2) if apply_u0_limit else limits.clamp(raw_d2)

        new_state = self._rk4(dt, d1, d2, source_power, storage_bus)
        i_l, v_in, v_out = new_state
        # 二极管单向性：把电感电流投影回允许方向（见 _derivatives 的说明）。
        i_l = max(0.0, i_l) if source_power >= 0.0 else min(0.0, i_l)
        new_state = (i_l, v_in, v_out)
        if not all(math.isfinite(value) for value in new_state):
            raise ConverterNumericalError(f"平均模型数值发散：state={new_state!r}, dt={dt!r}")
        ceiling_in = 3.0 * self.params.input_voltage_max_v
        ceiling_out = 3.0 * self.params.output_voltage_max_v
        if abs(v_in) > ceiling_in or abs(v_out) > ceiling_out:
            raise ConverterNumericalError(
                "平均模型电压越出数值安全边界（3x 额定窗口上限）："
                f"v_in={v_in:.3f} V, v_out={v_out:.3f} V, d1={d1:.4f}, d2={d2:.4f}, dt={dt!r}"
            )

        i_src = source_power / max(v_in, VOLTAGE_FLOOR_V)
        i_grid = (self.params.source_open_circuit_voltage_v - v_in) / self.params.source_resistance_ohm
        i_sink = self.sink_current(v_out, storage_bus)
        # p_in 严格等于电机侧注入功率，保证能量台账闭合
        p_in = source_power
        p_out = v_out * i_sink
        p_grid = v_in * i_grid
        # 源阻抗 R_src 上的耗散：母线侧与理想源端之差，必须单独立项，
        # 否则这部分能量会被误记成"送网能量"，造成闭合残差。
        p_grid_source_loss = i_grid**2 * self.params.source_resistance_ohm
        p_grid_terminal = self.params.source_open_circuit_voltage_v * i_grid
        loss_conversion = max(0.0, (1.0 - self.params.efficiency) * abs(p_in))
        loss_inductor = i_l**2 * self.params.inductor_resistance_ohm

        if abs(source_power) < 1e-9:
            mode = "idle"
        elif source_power > 0.0:
            mode = "regen_charge"
        else:
            mode = "discharge_support"

        self.state = DCConverterState(
            inductor_current_a=i_l,
            input_voltage_v=v_in,
            output_voltage_v=v_out,
        )

        return DCConverterStepResult(
            duty_cycle_T1=d1,
            duty_cycle_T2=d2,
            mode=mode,
            input_voltage_v=v_in,
            input_current_a=i_src,
            output_voltage_v=v_out,
            output_current_a=i_sink,
            inductor_current_a=i_l,
            input_power_w=p_in,
            output_power_w=p_out,
            conversion_loss_w=loss_conversion,
            inductor_loss_w=loss_inductor,
            grid_power_w=p_grid,
            grid_source_loss_w=p_grid_source_loss,
            grid_terminal_power_w=p_grid_terminal,
            efficiency_effective=(p_out / abs(p_in)) if abs(p_in) > 1e-12 else 0.0,
            # 问题 32：按**额定功率**判定（修复前这里误用了 max_input_current_a，
            # 与下面的 input_current_over_limit 逐位相同）。
            power_limited_by_rating=abs(p_in) > self.params.power_rating_w + 1e-9,
            input_voltage_out_of_window=not (
                self.params.input_voltage_min_v <= v_in <= self.params.input_voltage_max_v
            ),
            output_voltage_out_of_window=not (
                self.params.output_voltage_min_v <= v_out <= self.params.output_voltage_max_v
            ),
            input_current_over_limit=abs(i_src) > self.params.max_input_current_a + 1e-9,
            output_current_over_limit=abs(i_sink) > self.params.max_output_current_a + 1e-9,
        )

    # ---------- 辅助 ----------
    def steady_state_output_voltage(self, duty_cycle_T1: float, duty_cycle_T2: float) -> float:
        """理想（无损耗）稳态输出电压，用于校验占空比与电压的定性关系。"""

        d1 = self.params.duty_limits.clamp(duty_cycle_T1)
        d2 = self.params.duty_limits.clamp(duty_cycle_T2)
        denominator = max(1.0 - d2, 1e-9)
        return self.state.input_voltage_v * d1 / denominator

    def copy_with_state(self, state: DCConverterState) -> "BidirectionalDCDCConverter":
        return BidirectionalDCDCConverter(self.params, state)


def buck_steady_state_duty(v_in: float, v_out: float) -> float:
    """纯 buck 模式的理想占空比 d = v_out / v_in。"""

    if v_in <= 0.0:
        raise ConverterError("v_in 必须为正")
    return min(max(v_out / v_in, 0.0), 1.0)


def boost_steady_state_duty(v_in: float, v_out: float) -> float:
    """纯 boost 模式的理想占空比 1 - d = v_in / v_out。"""

    if v_out <= 0.0:
        raise ConverterError("v_out 必须为正")
    return min(max(1.0 - v_in / v_out, 0.0), 1.0)
