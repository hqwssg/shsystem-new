"""再生制动闭环仿真器（阶段 1 物理底座 + 阶段 2 baseline）。

单步执行顺序（与总体控制链一致）：

    1) 列车制动模型      -> 机械制动力 / 制动功率分解
    2) 电机模型          -> 再生制动力包络、效率、直流侧电流
    3) 控制器            -> T1 / T2 占空比（当前阶段：固定占空比 baseline）
    4) 双向 DC-DC 平均模型 -> 母线电压、电感电流、储能侧电压/电流
    5) 储能模型          -> SOC 更新、功率与 SOC 约束
    6) 能量台账          -> 逐步累积，保证能量守恒可验证

数值口径：
    * 变换器用 RK4 积分，列车/电机/储能为代数模型；
    * 储能侧不再以「上一步接受功率」回灌负载（那会形成 0 值自锁），
      改为把储能的 SOC 余量与功率上限折算成 StorageBusRequest 交给变流器，
      由变流器按状态解出 sink 电流。占空比因此是真实的功率流执行器。
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..dynamics.dc_dc_converter import (
    BidirectionalDCDCConverter,
    DCConverterParameters,
    StorageBusRequest,
)
from ..dynamics.motor_model import MotorParameters, convert_wheel_regen
from ..dynamics.storage_model import StorageParameters, StorageSystem
from ..dynamics.train_braking_model import TrainBrakingProfile, evaluate_braking
from ..metrics.regenerative_metrics import (
    EnergyLedger,
    ScenarioMetrics,
    build_scenario_metrics,
    converter_limit_ratios,
)
from ..tracking import build_reference_state
from .controllers import (
    ControllerCommand,
    ControllerObservation,
    RegenController,
    ZeroDutyController,
)
from .profiles import ProfileSeries


class SimulationError(RuntimeError):
    """仿真配置或运行错误。"""


@dataclass
class SimulationConfig:
    """仿真数值配置。"""

    dt: float = 1e-4
    record_stride: int = 10
    apply_u0_limit: bool = True
    max_steps: int = 2_000_000
    control_period_s: Optional[float] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.dt) or self.dt <= 0.0:
            raise SimulationError(f"dt 必须为正有限值，实际为 {self.dt!r}")
        if self.record_stride < 1:
            raise SimulationError("record_stride 必须 >= 1")
        period = self.control_period
        ratio = period / self.dt
        if not math.isfinite(period) or not math.isfinite(ratio) or period <= 0 or ratio < 1 or not math.isclose(
            ratio, round(ratio), rel_tol=1e-9, abs_tol=0.0
        ):
            raise SimulationError("控制周期必须是积分步长的正整数倍（至少 1 倍）")

    @property
    def control_period(self) -> float:
        return self.dt if self.control_period_s is None else float(self.control_period_s)

    @property
    def control_stride(self) -> int:
        return round(self.control_period / self.dt)


@dataclass
class SimulationArrays:
    """逐步记录（numpy 数组，便于指标计算与落盘）。"""

    time_s: np.ndarray
    speed_mps: np.ndarray
    mechanical_braking_power_w: np.ndarray
    regen_wheel_power_w: np.ndarray
    friction_braking_power_w: np.ndarray
    motor_electrical_power_w: np.ndarray
    duty_cycle_T1: np.ndarray
    duty_cycle_T2: np.ndarray
    input_voltage_v: np.ndarray
    input_current_a: np.ndarray
    inductor_current_a: np.ndarray
    output_voltage_v: np.ndarray
    output_current_a: np.ndarray
    output_power_w: np.ndarray
    reference_power_w: np.ndarray
    accepted_power_w: np.ndarray
    curtailed_power_w: np.ndarray
    grid_export_power_w: np.ndarray
    grid_import_power_w: np.ndarray
    grid_source_loss_w: np.ndarray
    soc: np.ndarray
    motor_efficiency: np.ndarray
    dc_link_derating: np.ndarray
    regen_limit_reason: List[str] = field(default_factory=list)
    # 每步能量增量用于阶段归因；旧调用方未提供时保留空数组，诊断器显式拒绝。
    stored_energy_delta_j: np.ndarray = field(default_factory=lambda: np.empty(0))
    storage_loss_j: np.ndarray = field(default_factory=lambda: np.empty(0))
    converter_loss_power_w: np.ndarray = field(default_factory=lambda: np.empty(0))
    converter_inductor_loss_power_w: np.ndarray = field(default_factory=lambda: np.empty(0))
    reactive_energy_delta_j: np.ndarray = field(default_factory=lambda: np.empty(0))
    storage_charge_power_limit_w: np.ndarray = field(default_factory=lambda: np.empty(0))
    control_update: np.ndarray = field(default_factory=lambda: np.empty(0))
    charge_safety_override: np.ndarray = field(default_factory=lambda: np.empty(0))

    def to_columns(self) -> Mapping[str, np.ndarray]:
        return {key: value for key, value in self.__dict__.items() if key != "regen_limit_reason"}


@dataclass
class SimulationResult:
    """仿真结果。

    ``duty_bounds`` 是本次运行**实际生效**的占空比可行域 ``(下界, 上界)``：
    ``apply_u0_limit=True`` 时为 ``(min_duty, min(max_duty, u0_max))``，
    否则为 ``(min_duty, max_duty)``。它随结果一起保存，使
    ``duty_saturation_ratio`` 能按真实执行器边界判定贴轨
    （见方案问题 25：曾写死 ``[0, 1]`` 导致 ``u0 = 0.9`` 上的饱和被静默漏报）。

    ``converter_limits`` 是变流器的两条额定限值 ``(power_rating_w, max_input_current_a)``，
    同理随结果一起保存，使场景指标能报出
    ``converter_over_rating_ratio`` 与 ``converter_input_current_over_limit_ratio``
    （见方案问题 32：``power_rating_w`` 此前被读入却无任何消费点，
    ``power_limited_by_rating`` 又误用输入电流判据，于是"是否越额定"在代码里无法判定）。
    """

    scenario_id: str
    controller_name: str
    config: SimulationConfig
    ledger: EnergyLedger
    arrays: SimulationArrays
    profile_notes: Sequence[str] = ()
    extra_notes: Sequence[str] = ()
    duty_bounds: Tuple[float, float] = (0.0, 1.0)
    converter_limits: Tuple[float, float] = (math.inf, math.inf)

    def to_scenario_metrics(self, filter_mode: str = "none") -> ScenarioMetrics:
        arrays = self.arrays
        return build_scenario_metrics(
            self.scenario_id,
            self.controller_name,
            self.ledger,
            voltage_series=arrays.output_voltage_v,
            current_series=arrays.output_current_a,
            power_series=arrays.accepted_power_w,
            # 问题 33：参考量取**储能侧**可吸收功率（``reference_power_w``），
            # 与实测量 ``accepted_power_w`` 同侧；修复前取的是轮端可用再生功率
            # ``regen_wheel_power_w``，与实测量跨了整条变换链。
            reference_power=arrays.reference_power_w,
            time_s=arrays.time_s,
            duty_series=arrays.duty_cycle_T1,
            soc_series=arrays.soc,
            dt=self.config.dt * self.config.record_stride,
            filter_mode=filter_mode,
            extra_ripple={
                "input_voltage": arrays.input_voltage_v,
                "input_current": arrays.input_current_a,
                "inductor_current": arrays.inductor_current_a,
            },
            notes=list(self.profile_notes) + list(self.extra_notes),
            duty_lower_bound=self.duty_bounds[0],
            duty_upper_bound=self.duty_bounds[1],
            extra_ratios=converter_limit_ratios(
                arrays.motor_electrical_power_w,
                arrays.input_current_a,
                power_rating_w=self.converter_limits[0],
                max_input_current_a=self.converter_limits[1],
            ),
        )

    def to_csv(self, path: Path) -> Path:
        """把逐步记录写到 CSV。"""

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = self.arrays.to_columns()
        keys = list(columns.keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(keys)
            for index in range(len(self.arrays.time_s)):
                writer.writerow([columns[key][index] for key in keys])
        return path


def _source_current_from_motor(electrical_power_w: float, input_voltage_v: float) -> float:
    """电机侧注入电流（仅供观测/诊断使用；变流器内部按功率源自行解算）。"""

    if input_voltage_v <= 1e-6:
        return 0.0
    return electrical_power_w / input_voltage_v


class RegenerativeBrakingSimulator:
    """把列车 / 电机 / 变换器 / 储能串成闭环。"""

    def __init__(
        self,
        train: TrainBrakingProfile,
        motor: MotorParameters,
        converter: BidirectionalDCDCConverter,
        storage: StorageSystem,
    ) -> None:
        self.train = train
        self.motor = motor
        self.converter = converter
        self.storage = storage

    @classmethod
    def from_parameters(
        cls,
        train: TrainBrakingProfile,
        motor: MotorParameters,
        converter_params: DCConverterParameters,
        storage_params: StorageParameters,
    ) -> "RegenerativeBrakingSimulator":
        return cls(
            train=train,
            motor=motor,
            converter=BidirectionalDCDCConverter.at_nominal(converter_params),
            storage=StorageSystem(storage_params),
        )

    def reset(self) -> None:
        """把被控对象恢复到**初始状态**（变流器回标称点、储能回 ``soc_initial``）。"""

        self.converter = BidirectionalDCDCConverter.at_nominal(self.converter.params)
        self.storage.reset()

    def storage_bus_request(self, dt: float) -> StorageBusRequest:
        """把储能模型的 SOC 余量与功率上限折算成变流器可见的储能侧边界。

        这是"储能约束进入变流器方程"的唯一通道：SOC 接近上限时
        available_charge_power_w 迅速降到 0，sink 电流随之归零，
        主算法据同一拍许可降低充电参考并退出充电，剩余再生功率经输入
        母线回网。输出电压不做钳位，剩余电感能量仍由平均模型结算。
        """

        return StorageBusRequest(
            open_circuit_voltage_v=self.storage.params.nominal_voltage_v,
            internal_resistance_ohm=self.storage.params.internal_resistance_ohm,
            available_charge_power_w=self.storage.available_charge_power_w(dt),
            available_discharge_power_w=self.storage.available_discharge_power_w(dt),
            allow_discharge=False,
            data_status=self.storage.params.data_status,
        )

    def run(
        self,
        series: ProfileSeries,
        controller: Optional[RegenController] = None,
        config: Optional[SimulationConfig] = None,
        *,
        plant_update: Optional[Callable[[float, "RegenerativeBrakingSimulator"], None]] = None,
    ) -> SimulationResult:
        """推进一个工况序列。

        .. warning::
           ``run()`` 在开始处**把被控对象复位到初始状态**（``self.reset()``）。
           这是为了消除一个静默退化陷阱：``run()`` 原先只复位控制器、不复位被控对象，
           于是**在同一实例上连续 ``run()`` 会让后一次继承前一次的末态**
           （实测 ``s2`` 由 ``2.971285 kWh`` 变成 ``2.971728 kWh``，且不报任何错）。
           ``build_simulator()`` 的契约是「每次调用返回独立实例」，
           但契约一旦被违反就会静默出错，故改为在 ``run()`` 内显式复位——
           对「每次新建实例」的调用方是**逐位无变化**的（问题 24）。
        """

        controller = controller or ZeroDutyController(self.converter.params.duty_limits)
        config = config or SimulationConfig()

        if plant_update is not None and not callable(plant_update):
            raise SimulationError("plant_update 必须可调用或为 None")

        if len(series) == 0:
            raise SimulationError(f"工况序列为空：{series.scenario_id}")
        if series.dt != config.dt:
            raise SimulationError(
                f"工况序列步长 {series.dt} 与仿真步长 {config.dt} 不一致；"
                "请在构造剖面时使用同一 dt，避免插值引入隐性误差。"
            )
        if len(series) > config.max_steps:
            raise SimulationError(f"步数 {len(series)} 超过 max_steps={config.max_steps}")

        # 问题 31（实现期自行发现）：控制器**自带**的采样周期必须与本次控制周期一致。
        #
        # 为什么必须在这里拦：``ClosedLoopController.sample_time_s`` 不是装饰性字段——
        # 它是控制通道增益先验（问题 18）的 ``B_target`` 标定基准，而
        # ``B = ∂x̂/∂u`` 是**一步**灵敏度、幅值正比于 ``dt``。若控制器按 ``2e-4``
        # 标定而仿真跑在 ``1e-4``，``B`` 的幅值就差 2 倍，``u_eq`` 随之被放大/缩小，
        # 而**不会报任何错**——``audit()`` 里能看见 ``sample_time_s``，但没有比对点。
        #
        # 与 ``series.dt != config.dt`` 是同一纪律：宁可在这里炸掉，
        # 也不要让「先验按哪个步长标定」变成调用方是否记得传参的偶然结果。
        # 只对**声明了**该属性的控制器生效（PID 等 baseline 不声明，不受影响）。
        controller_dt = getattr(controller, "sample_time_s", None)
        if controller_dt is not None:
            value = float(controller_dt)
            if not math.isclose(value, config.control_period, rel_tol=1e-9, abs_tol=0.0):
                raise SimulationError(
                    f"控制器自带的采样步长 sample_time_s={value!r} 与本次仿真的控制周期 "
                    f"control_period={config.control_period!r} 不一致。控制通道增益先验（问题 18）的 "
                    "B_target 幅值正比于控制周期 Ts，用错周期会把幅值热启动按比例带偏，"
                    "且不会自己报错。请按实际控制周期装配控制器"
                    "（build_closed_loop_controller(..., sample_time_s=control_period)）。"
                )

        # 被控对象复位（问题 24）：必须在读 state 之前，否则初值取自上一次运行的末态。
        self.reset()

        ledger = EnergyLedger()
        ledger.observe_reactive_energy(self.converter.state.reactive_energy_j(self.converter.params), first=True)
        ledger.observe_soc(self.storage.state.soc)
        controller.reset()
        # 复合控制器 reset 时保留权重（热启动）。同一个实例连续跑多个场景时，
        # 第二个场景的前若干拍用的是上一场景学到的权重，读数会漂移——这不是
        # 物理差异，必须显式标出来，否则「同一输入同一输出」就不成立。
        controller_runs = getattr(controller, "run_count", None)

        # 问题 33（实现期自行发现）：``tracking_*`` 指标组的**参考功率**。
        #
        # 取 ③ 的**储能侧**可吸收功率 ``P_abs``，而不是 ``regen_wheel_power_w``
        # （轮端可用再生功率）。后者与实测量 ``accepted_power_w`` 跨了
        # 「电机 → 变流器 → 储能」整条链（官方 s1 实测 ``max|act| / max|ref|``
        # 仅 ``0.069``，跨场景 ``0.066 ~ 0.092``），会把"跟踪误差"变成结构性缺口：``tracking_rmse``
        # 对全部控制器都是 ``19.30 ~ 20.52 MW``（回收 ``0.000 kWh`` 的
        # ``uncontrolled_zero_duty`` 只比主算法差 ``5.9%``）、``overshoot`` 恒 ``0``、
        # ``settling_time`` 恒 ``None``——与问题 25 同形的「指标说了假话」。
        #
        # 为什么仿真器可以替**所有**控制器算这一列：``P_abs`` 只依赖观测与被控对象
        # 参数（``inductor_current_limit_a`` / ``efficiency`` / ``storage_max_charge_power_w``），
        # **与「谁在控制」无关**，是**被控对象属性**。因此无需改动控制器协议，
        # 也不会出现"同一参考功率两个来源"。装配走问题 30 的唯一生产入口。
        reference_model = build_reference_state(self.converter.params, self.storage.params)

        records: Dict[str, List[float]] = {key: [] for key in SimulationArrays.__dataclass_fields__ if key != "regen_limit_reason"}
        reasons: List[str] = []

        limits = self.converter.params.duty_limits
        # 本次运行实际生效的执行器可行域（方案问题 25）：与 converter.step() 内
        # `clamp_with_u0` / `clamp` 的选择保持一致，供 duty_saturation_ratio 判定贴轨。
        duty_ceiling = min(limits.max_duty, limits.u0_max) if config.apply_u0_limit else limits.max_duty
        duty_bounds = (limits.min_duty, duty_ceiling)
        record_stride = config.record_stride
        previous_output_current_a = 0.0
        previous_output_power_w = 0.0
        command = None
        control_stride = config.control_stride

        for step, sample in enumerate(series.samples):
            if plant_update is not None:
                # 仅供显式 assumed 真实对象漂移实验；不向控制器透传参数真值。
                plant_update(sample.time_s, self)
            reactive_before = self.converter.state.reactive_energy_j(self.converter.params)
            breakdown = evaluate_braking(self.train, sample)

            motor_result = convert_wheel_regen(
                self.motor,
                wheel_regen_force_n=breakdown.regen_wheel_force_n,
                wheel_regen_power_w=breakdown.regen_wheel_power_w,
                total_brake_force_n=breakdown.brake_force_n,
                total_brake_power_w=breakdown.mechanical_braking_power_w,
                speed_mps=sample.speed_mps,
                dc_link_voltage_v=self.converter.state.input_voltage_v,
            )

            # 控制器与 ODE 共用同一拍储能许可，避免 SOC 触顶后参考仍要求充电。
            storage_bus = self.storage_bus_request(config.dt)
            # 控制目标使用一整个控制周期的 SOC 预算，sink 每个积分步独立结算。
            # 两周期相同时保留原路径，避免默认模式发生任何数值变化。
            control_charge_limit = storage_bus.available_charge_power_w
            if control_stride > 1:
                control_charge_limit = min(control_charge_limit,
                    self.storage.available_charge_power_w(config.control_period))
            observation = ControllerObservation(
                time_s=sample.time_s,
                speed_mps=sample.speed_mps,
                input_voltage_v=self.converter.state.input_voltage_v,
                output_voltage_v=self.converter.state.output_voltage_v,
                inductor_current_a=self.converter.state.inductor_current_a,
                output_current_a=previous_output_current_a,
                soc=self.storage.state.soc,
                requested_regen_power_w=motor_result.electrical_power_w,
                available_regen_power_w=motor_result.envelope_power_limit_w * motor_result.dc_link_derating,
                output_power_w=previous_output_power_w,
                # 坡度只供模式切换判据使用（阶段 6），不参与任何控制律
                gradient_per_mille=sample.gradient_per_mille,
                storage_charge_power_limit_w=control_charge_limit,
            )

            control_update = step % control_stride == 0
            if control_update:
                command = controller.compute(observation)
            # ZOH 期间 BMS 拒充仍即时退出；不增加控制/辨识/噪声更新次数。
            safety_override = False
            if (not control_update and storage_bus.available_charge_power_w == 0.0
                    and (command.duty_cycle_T1 != 0.0 or command.duty_cycle_T2 != 0.0)):
                command = ControllerCommand(0.0, 0.0, note="inter_sample_storage_charge_exit")
                notify = getattr(controller, "accept_applied_command", None)
                if notify is not None:
                    notify(command)
                safety_override = True
            command.validate(limits)

            converter_result = self.converter.step(
                dt=config.dt,
                duty_cycle_T1=command.duty_cycle_T1,
                duty_cycle_T2=command.duty_cycle_T2,
                source_power_w=motor_result.electrical_power_w,
                storage_bus=storage_bus,
                apply_u0_limit=config.apply_u0_limit,
            )

            storage_result = self.storage.step(converter_result.output_power_w, config.dt)
            previous_output_current_a = converter_result.output_current_a
            previous_output_power_w = converter_result.output_power_w

            ledger.add_step(
                config.dt,
                mechanical_braking_power_w=breakdown.mechanical_braking_power_w,
                regen_wheel_power_w=motor_result.wheel_regen_power_w,
                friction_braking_power_w=motor_result.friction_power_w,
                motor_electrical_power_w=motor_result.electrical_power_w,
                converter_input_power_w=converter_result.duty_cycle_T1 * converter_result.input_voltage_v * converter_result.inductor_current_a,
                converter_output_power_w=converter_result.output_power_w,
                converter_loss_w=converter_result.conversion_loss_w,
                converter_inductor_loss_w=converter_result.inductor_loss_w,
                storage_accepted_power_w=storage_result.accepted_power_w,
                storage_energy_delta_j=storage_result.stored_energy_delta_j,
                storage_loss_j=storage_result.loss_j,
                curtailed_power_w=storage_result.curtailed_power_w,
                grid_export_power_w=converter_result.grid_terminal_export_power_w,
                grid_import_power_w=converter_result.grid_terminal_import_power_w,
                grid_source_loss_w=converter_result.grid_source_loss_w,
                traction_power_w=breakdown.traction_force_n * sample.speed_mps,
            )
            ledger.observe_soc(storage_result.soc_after)
            ledger.observe_reactive_energy(self.converter.state.reactive_energy_j(self.converter.params))
            # 式(72) 电流积分路径：Q_z = U_w·Σ(I_z(v)·λ·dt)。
            # λ = 实际再生力 / 曲线力上限，把「力用了几成」折算成「电流用了几成」；
            # 两条曲线（B_d(v)、I_z(v)）都来自标准表，与「力 × 速度 × 效率」这条
            # 路径的输入互不重叠，因此可以用来互校。U_w 取接触网电压（27.2 kV 级），
            # **不是**本仿真的 1500 V 直流母线电压。
            curve = self.train.regen_force_curve
            u_w_v = self.train.catenary_voltage_v or 0.0
            if curve is not None and curve.has_regen_current and u_w_v > 0.0:
                force_limit_n = curve.force_limit_n(sample.speed_mps)
                if force_limit_n > 0.0:
                    utilisation = min(max(breakdown.regen_wheel_force_n / force_limit_n, 0.0), 1.0)
                    ledger.observe_regen_current_step(
                        u_w_v * curve.regen_current_limit_a(sample.speed_mps) * utilisation,
                        u_w_v,
                        config.dt,
                    )

            if step % record_stride == 0:
                values = {
                    "time_s": sample.time_s,
                    "speed_mps": sample.speed_mps,
                    "mechanical_braking_power_w": breakdown.mechanical_braking_power_w,
                    "regen_wheel_power_w": motor_result.wheel_regen_power_w,
                    "friction_braking_power_w": motor_result.friction_power_w,
                    "motor_electrical_power_w": motor_result.electrical_power_w,
                    "duty_cycle_T1": converter_result.duty_cycle_T1,
                    "duty_cycle_T2": converter_result.duty_cycle_T2,
                    "input_voltage_v": converter_result.input_voltage_v,
                    "input_current_a": converter_result.input_current_a,
                    "inductor_current_a": converter_result.inductor_current_a,
                    "output_voltage_v": converter_result.output_voltage_v,
                    "output_current_a": converter_result.output_current_a,
                    "output_power_w": converter_result.output_power_w,
                    # 问题 33：储能侧可吸收功率参考（被控对象属性，与控制器无关）
                    "reference_power_w": reference_model.absorbable_power(observation),
                    "accepted_power_w": storage_result.accepted_power_w,
                    "curtailed_power_w": storage_result.curtailed_power_w,
                    "grid_export_power_w": converter_result.grid_terminal_export_power_w,
                    "grid_import_power_w": converter_result.grid_terminal_import_power_w,
                    "grid_source_loss_w": converter_result.grid_source_loss_w,
                    "soc": storage_result.soc_after,
                    "motor_efficiency": motor_result.efficiency,
                    "dc_link_derating": motor_result.dc_link_derating,
                    "stored_energy_delta_j": storage_result.stored_energy_delta_j,
                    "storage_loss_j": storage_result.loss_j,
                    "converter_loss_power_w": converter_result.conversion_loss_w,
                    "converter_inductor_loss_power_w": converter_result.inductor_loss_w,
                    "reactive_energy_delta_j": (
                        self.converter.state.reactive_energy_j(self.converter.params) - reactive_before
                    ),
                    "storage_charge_power_limit_w": storage_bus.available_charge_power_w,
                    "control_update": control_update,
                    "charge_safety_override": safety_override,
                }
                for key, value in values.items():
                    records[key].append(float(value))
                reasons.append(motor_result.limited_by)

        ledger.observe_reactive_energy(self.converter.state.reactive_energy_j(self.converter.params))

        arrays = SimulationArrays(
            **{key: np.asarray(value, dtype=float) for key, value in records.items()},
            regen_limit_reason=reasons,
        )

        # 问题 32：把变流器的两条额定限值随结果带走，并给出越限拍数。
        # 修复前 power_rating_w 被读入却无任何消费点，而 power_limited_by_rating
        # 又误用输入电流判据，"是否越额定"在代码里无法判定。
        over_rating_steps = sum(
            1
            for power in arrays.motor_electrical_power_w
            if abs(float(power)) > self.converter.params.power_rating_w + 1.0e-9
        )
        over_input_current_steps = sum(
            1
            for current in arrays.input_current_a
            if abs(float(current)) > self.converter.params.max_input_current_a + 1.0e-9
        )

        extra_notes: List[str] = [
            f"控制器 = {controller.name}",
            f"步长 dt = {config.dt} s，记录间隔 = {config.dt * record_stride} s",
            f"仿真步数 = {len(series)}",
            f"控制周期 = {config.control_period} s，ZOH 保持，"
            f"控制更新次数 = {math.ceil(len(series) / control_stride)}；"
            "BMS 拒充可在控制采样间隔内即时关闭实际 PWM",
            f"能量闭合残差 = {ledger.closure_residual_j / 3.6e6:.6e} kWh",
            f"变流器额定功率 = {self.converter.params.power_rating_w:.6g} W，"
            f"越额定拍数 = {over_rating_steps}/{len(arrays.motor_electrical_power_w)}"
            "（只报告不截断，问题 32）",
            f"变流器额定输入电流 = {self.converter.params.max_input_current_a:.6g} A，"
            f"越限拍数 = {over_input_current_steps}/{len(arrays.input_current_a)}"
            "（只报告不截断）",
        ]

        ratio = ledger.regen_current_to_motor_ratio
        if controller_runs is not None and controller_runs > 1:
            extra_notes.append(
                f"⚠ 控制器实例第 {controller_runs} 次运行：辨识权重为上一次运行的热启动，"
                "本结果的读数依赖此前跑过什么；生产路径每次新建控制器"
            )
        if ratio is None:
            extra_notes.append(
                "式(72) 电流积分校核：不可用（无再生电流表 I_z(v) 或无牵引网电压 U_w，"
                "或本场景未产生再生电量）"
            )
        else:
            extra_notes.append(
                f"式(72) 电流积分校核：Q_z = {ledger.regen_current_energy_j / 3.6e6:.6f} kWh"
                f"（U_w = {ledger.regen_current_reference_voltage_v / 1000.0:.3f} kV），"
                f"与「力 × 速度 × 效率」路径之比 = {ratio:.4f}"
                f"（偏差 {ratio - 1.0:+.2%}，判据 ±10%）"
            )

        return SimulationResult(
            scenario_id=series.scenario_id,
            controller_name=controller.name,
            config=config,
            ledger=ledger,
            arrays=arrays,
            profile_notes=series.notes,
            extra_notes=extra_notes,
            duty_bounds=duty_bounds,
            converter_limits=(
                self.converter.params.power_rating_w,
                self.converter.params.max_input_current_a,
            ),
        )
