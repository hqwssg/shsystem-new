"""场景装配与运行入口。

把「配置文件 + 共享真实数据」装配成可运行的仿真器，并给出阶段 1/2 的场景：

    Scenario 1  平直线路常规制动
    Scenario 2  长大下坡制动（减速至目标速度后恒速保持，持续再生）
    Scenario R  真实线路区段制动（坡度/曲线/限速取自共享数据）

后续阶段（3-9）的 RHONN / EKF / UKF / NSMC 场景在这里逐步接入，
本模块只负责装配与运行，不包含控制算法本身。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..dynamics.dc_dc_converter import BidirectionalDCDCConverter, DCConverterParameters
from ..dynamics.motor_model import MotorParameters
from ..dynamics.storage_model import StorageParameters, StorageSystem
from ..dynamics.train_braking_model import ElectricalBrakeCurve, TrainBrakingProfile
from ..io.data_loader import (
    DataLoadError,
    ParameterFile,
    SharedRailwayData,
    combine_regen_curves,
    consist_entries_for,
    find_contested_assumption,
    load_shared_railway_data,
    load_single_train_parameters,
    power_cap_w,
)
from ..io.data_paths import ProjectPaths, load_project_paths
from ..tracking import build_reference_state
from .controllers import (
    FixedDutyController,
    PIController,
    PIDController,
    RegenController,
    TraditionalSMCController,
    ZeroDutyController,
)
from .profiles import (
    ProfileSeries,
    constant_deceleration_series,
    grade_hold_series,
    route_braking_series,
)
from .regenerative_simulator import (
    RegenerativeBrakingSimulator,
    SimulationConfig,
    SimulationResult,
)


@dataclass(frozen=True)
class ComponentBundle:
    """装配好的物理模型组件（未绑定控制器）。"""

    train: TrainBrakingProfile
    motor: MotorParameters
    converter_params: DCConverterParameters
    storage_params: StorageParameters
    paths: ProjectPaths
    parameter_status: Mapping[str, str]


#: 装配所需的参数组，顺序即装配顺序
PARAMETER_GROUPS: tuple = ("train", "motor", "dc_dc", "storage")

#: 共享数据 ``trains.csv`` 中代表本工况编组的行（2 万吨 C80 重车）
SHARED_TRAIN_KEY = "Heavy"


def build_component_bundle(
    parameters: Mapping[str, ParameterFile],
    *,
    paths: Optional[ProjectPaths] = None,
    shared: Optional[SharedRailwayData] = None,
    locomotive_count: Optional[int] = None,
) -> ComponentBundle:
    """用已加载的参数对象装配组件包。

    文件模式与数据库模式都走这里：参数从哪来由调用方决定，装配规则只有一份。

    ``shared`` 提供时，列车侧的三个口径以**共享数据为权威**：
    整备质量（车辆总重 + 台数 × 机车自重）、电制动力曲线（按台数与级位折算）、
    功率上限（``max_power_kW`` × 台数）。参数文件里的对应数值退化为校验镜像，
    不一致直接报错——防止控制侧与结算侧各算一遍。

    ``locomotive_count`` 用于 1 台 / 2 台情景对比，缺省取参数文件的取值。
    """

    paths = paths or load_project_paths()
    missing = [group for group in PARAMETER_GROUPS if group not in parameters]
    if missing:
        raise DataLoadError(f"装配缺少参数组：{missing}")

    train_file = parameters["train"]
    motor_file = parameters["motor"]
    converter_file = parameters["dc_dc"]
    storage_file = parameters["storage"]

    profile = TrainBrakingProfile.from_parameters(train_file.payload)
    motor = MotorParameters.from_parameters(motor_file.payload)
    converter = DCConverterParameters.from_parameters(converter_file.payload)

    status = {
        f"{group}_parameters": parameters[group].data_status for group in PARAMETER_GROUPS
    }
    consist_audit: Optional[dict] = None

    if shared is not None:
        profile, motor, converter, consist_audit = _apply_shared_rolling_stock(
            profile, motor, converter, shared, locomotive_count=locomotive_count
        )
        status["shared_rolling_stock"] = "real"
        labels = "+".join(
            f"{code}×{count}" for code, count in consist_audit["entries"]
        )
        status["locomotive_consist"] = (
            f"{labels} = {consist_audit['total_count']} 台"
            f"（{consist_audit['source']}）；整备含机车 "
            f"{consist_audit['mass_t']:.0f} t、轮周功率 "
            f"{consist_audit['power_kW']:.0f} kW、电制动峰值 "
            f"{consist_audit['peak_force_kn']:.1f} kN"
            + (
                "；多机型曲线按并集速度栅格逐点求和"
                if consist_audit["multi_type"]
                else ""
            )
        )
        status["rolling_stock_basis"] = (
            f"{consist_audit['total_count']} 台（"
            + (
                "编组取自 trains.csv:locomotive_consist，参数文件镜像已按新口径校验"
                if consist_audit["source"].startswith("trains.csv")
                else "单机型覆盖（情景对比），不校验参数文件镜像"
            )
            + "）"
        )
    else:
        # 不注入共享数据时没有电制动曲线，再生力只能用「峰值 × 级位」的常数近似
        # （速度衰减段缺失）。这不是静默降级，而是必须在状态里显式标出来的近似。
        status["shared_rolling_stock"] = "absent"
        status["rolling_stock_basis"] = "未注入共享数据：无电制动曲线，再生力按「单台峰值 × 台数 × 级位」常数近似"

    # 式(72) 电流积分校核的可用性：曲线与网压缺一不可，缺了要显式说明
    consist_note = consist_audit or {}
    missing_current = consist_note.get("regen_current_missing") or []
    if profile.regen_force_curve is None:
        status["regen_current_check"] = "absent：无电制动曲线，电流表无法按速度查表"
    elif not profile.regen_force_curve.has_regen_current:
        status["regen_current_check"] = "absent：机车曲线中没有再生电流表 I_z(v)"
    elif profile.catenary_voltage_v is None:
        status["regen_current_check"] = "absent：共享数据没有 regen_energy_formula.U_w_kV（网压）"
    else:
        status["regen_current_check"] = (
            f"enabled：U_w = {profile.catenary_voltage_v / 1000.0:.3f} kV，"
            "Q_z = U_w·Σ(I_z·λ·dt)，λ = 实际再生力 / 曲线力上限"
            + (
                f"；**下限**——{'、'.join(missing_current)} 无 I_z 表，"
                "Q_z 只含有机型电流之和，不能当精确值用"
                if missing_current
                else ""
            )
        )

    # 台数口径争议：1 台（电表记录）与 2 台（电量付不起爬升功）都讲得通，
    # 甲方未裁定。凡是台数、功率、再生力相关的数字，对外必须同时说明另一套口径。
    contested = find_contested_assumption("two_wan_ton_locomotive_count", paths)
    if contested is None:
        status["locomotive_count_basis"] = "未在 data_manifest 登记台数口径争议（无法判断）"
    elif str(contested.get("status", "")).strip() == "contested":
        alternatives = "、".join(
            str(item.get("value"))
            for item in (contested.get("alternatives") or [])
            if isinstance(item, dict)
        )
        status["locomotive_count_basis"] = (
            f"contested：本方案默认 {contested.get('project_default')}，"
            f"另一套为 {alternatives or '未登记'}；甲方未裁定，对外须同时披露另一套口径"
        )
    else:
        status["locomotive_count_basis"] = (
            f"settled（已裁定）：{contested.get('project_default') or contested.get('value')}；"
            f"依据见 data_manifest §四与 docs/locomotive_consist_2026-11-07.md"
        )

    return ComponentBundle(
        train=profile,
        motor=motor,
        converter_params=converter,
        storage_params=StorageParameters.from_parameters(storage_file.payload),
        paths=paths,
        parameter_status=status,
    )


def _apply_shared_rolling_stock(
    profile: TrainBrakingProfile,
    motor: "MotorParameters",
    converter: "DCConverterParameters",
    shared: SharedRailwayData,
    *,
    locomotive_count: Optional[int] = None,
) -> Tuple[TrainBrakingProfile, "MotorParameters", "DCConverterParameters", dict]:
    """把共享数据的机车口径注入列车 / 电机 / 变流器三处。

    三处量的来源必须唯一，因此这里一次性算完并回写，随后校验参数文件里的
    镜像值；不一致说明有人只改了一边，直接报错而不是静默取其一。

    **编组可以是多机型**（两万吨 = 12 轴 + 8 轴）。此时质量、功率、电制动力
    都按各机型分别求和，不能再拿「首型 × 总台数」——8 轴补机是 200 t / 9 600 kW，
    按 12 轴的 300 t / 14 400 kW 算会把整备质量与功率上限同时放大。
    """

    shared_train = shared.trains.get(SHARED_TRAIN_KEY)
    if shared_train is None:
        raise DataLoadError(
            f"共享数据缺少列车 {SHARED_TRAIN_KEY!r}；可用：{sorted(shared.trains)}"
        )

    # 谁说了算，按优先级：显式入参 > 参数文件显式覆盖 > trains.csv 的编组。
    # 判「参数文件显式覆盖」要与共享数据比对，而不是只看它写了什么——默认值 1
    # 和「写死 1 台」无法区分，直接拿来当覆盖会让共享数据的 1+1 编组永远不生效。
    override = locomotive_count
    if override is None:
        profile_type = profile.locomotive_type or shared_train.locomotive_type
        if (
            profile_type != shared_train.locomotive_type
            or int(profile.locomotive_count) != int(shared_train.locomotive_count)
        ):
            override = int(profile.locomotive_count)

    entries = consist_entries_for(shared_train, locomotive_count=override)
    if not entries:
        raise DataLoadError("编组为空（台数为 0），无法装配机车口径")
    # 未适配 consist 的消费方（以及 1 台/2 台情景对比）走单机型口径时，
    # 机型来自参数文件；混编时以 trains.csv 的 consist 为准。
    if override is not None:
        entries = ((profile.locomotive_type or shared_train.locomotive_type, override),)

    combined = combine_regen_curves(entries, shared.locomotives)
    uses_shared_consist = override is None
    total_count = sum(count for _, count in entries)

    result = profile.with_locomotives(combined.mass_t * 1000.0, count=1).with_regen_curve(
        # 曲线已经按编组求和，台数信息含在曲线里，这里恒为 1——再乘一次台数
        # 会把 8 轴补机算两遍。
        ElectricalBrakeCurve(
            points_kmh_kn=combined.points_kmh_kn,
            locomotive_count=1,
            electrical_level=profile.electrical_level,
            current_points_kmh_a=combined.current_points_kmh_a,
        )
    )
    # 式(72) 的牵引网电压：来自共享数据，只服务电流积分校核，不进直流母线计算。
    # 数据里没有这一块时保持 None，由仿真器显式标注「交叉校验不可用」。
    formula = shared.regen_energy_formula
    result = replace(
        result,
        catenary_voltage_v=formula.u_w_v if formula is not None else None,
        locomotive_count=total_count,
    )

    cap_w = power_cap_w(
        shared_train, locomotive_count=override, locomotives=shared.locomotives
    )
    peak_force_n = combined.peak_force_kn * 1000.0

    if uses_shared_consist:
        # 走共享数据编组时，参数文件里的镜像值必须与新口径一致
        _check_mirror(
            "train.mass_kg",
            profile.mass_kg,
            (profile.vehicle_mass_kg or profile.mass_kg) + combined.mass_t * 1000.0,
        )
        _check_mirror("motor.max_regen_power_w", motor.max_regen_power_w, cap_w)
        _check_mirror("dc_dc.power_rating_w", converter.power_rating_w, cap_w)
        _check_mirror("motor.max_regen_force_n", motor.max_regen_force_n, peak_force_n)

    # base_speed 必须跟着新的 (P, F) 重算：replace 不会重跑 from_parameters 的推导
    motor = replace(
        motor,
        max_regen_power_w=cap_w,
        max_regen_force_n=peak_force_n,
        base_speed_m_per_s=cap_w / peak_force_n,
    )
    converter = replace(converter, power_rating_w=cap_w)
    audit = {
        "entries": [[code, count] for code, count in combined.entries],
        "source": "trains.csv:locomotive_consist" if uses_shared_consist else "override",
        "total_count": total_count,
        "mass_t": combined.mass_t,
        "power_kW": combined.power_kW,
        "peak_force_kn": combined.peak_force_kn,
        "multi_type": combined.is_multi_type,
        "regen_current_complete": combined.current_complete,
        "regen_current_missing": list(combined.current_missing),
    }
    return result, motor, converter, audit


def _check_mirror(name: str, mirror: float, authoritative: float) -> None:
    """参数文件里的镜像值必须与共享数据导出值一致。"""

    scale = max(abs(authoritative), 1.0)
    if abs(float(mirror) - authoritative) > 1e-6 * scale:
        raise DataLoadError(
            f"{name} 的镜像值 {mirror} 与共享数据导出值 {authoritative} 不一致；"
            f"该量的唯一来源是共享数据，请同步参数文件而不是只改一边。"
        )


def load_component_bundle(paths: Optional[ProjectPaths] = None) -> ComponentBundle:
    """从配置、参数文件与共享数据装配物理模型组件。"""

    paths = paths or load_project_paths()
    parameters = {
        group: load_single_train_parameters(f"{group}_parameters", paths)
        for group in PARAMETER_GROUPS
    }
    shared = load_shared_railway_data(paths)
    return build_component_bundle(parameters, paths=paths, shared=shared)


def build_simulator(bundle: ComponentBundle) -> RegenerativeBrakingSimulator:
    """按组件装配一个全新的仿真器（每次调用返回独立实例）。"""

    return RegenerativeBrakingSimulator(
        train=bundle.train,
        motor=bundle.motor,
        converter=BidirectionalDCDCConverter.at_nominal(bundle.converter_params),
        storage=StorageSystem(bundle.storage_params),
    )


# ------------------------------------------------------------------
# 场景构造
# ------------------------------------------------------------------


def scenario_1_flat_braking(
    bundle: ComponentBundle,
    dt: float = 1e-4,
    v0_kmh: float = 60.0,
    decel_mps2: float = 0.15,
) -> ProfileSeries:
    """Scenario 1：平直线路常规制动。

    减速度取 0.15 m/s^2：朔黄 2 万吨编组在 min(车辆最大制动力 6200 kN, 黏着上限)
    约束下平直道可达减速度约 0.28 m/s^2，0.15 留有约一倍裕度，属于常规制动区间。
    """

    return constant_deceleration_series(
        bundle.train,
        v0_mps=v0_kmh / 3.6,
        decel_mps2=decel_mps2,
        dt=dt,
        v_end_mps=0.0,
        gradient_per_mille=0.0,
        curve_radius_m=None,
        speed_limit_mps=80.0 / 3.6,
        scenario_id="scenario_1_flat_braking",
        description="Scenario 1 平直线路常规制动（等减速度）",
    )


def scenario_2_long_downhill(
    bundle: ComponentBundle,
    dt: float = 1e-4,
    entry_kmh: float = 70.0,
    target_kmh: float = 60.0,
    decel_mps2: float = 0.15,
    gradient_per_mille: float = -9.0,
    hold_duration_s: float = 6.0,
) -> ProfileSeries:
    """Scenario 2：长大下坡制动（减速后恒速保持，持续再生）。

    -9 ‰ 下坡下重力沿运动方向，可用制动力预算被占用，70 km/h 处可达减速度约
    0.20 m/s^2，因此取 0.15 留裕度。恒速保持段才是再生制动的典型持续工况。
    """

    return grade_hold_series(
        bundle.train,
        entry_speed_mps=entry_kmh / 3.6,
        target_speed_mps=target_kmh / 3.6,
        decel_mps2=decel_mps2,
        gradient_per_mille=gradient_per_mille,
        dt=dt,
        hold_duration_s=hold_duration_s,
        speed_limit_mps=80.0 / 3.6,
        scenario_id="scenario_2_long_downhill",
        description="Scenario 2 长大下坡制动（恒速保持段持续再生）",
    )


def scenario_route_braking(
    bundle: ComponentBundle,
    shared: SharedRailwayData,
    start_km: float,
    v0_kmh: float,
    dt: float = 1e-4,
    brake_command: float = 0.25,
    end_km: Optional[float] = None,
    max_time_s: float = 60.0,
) -> ProfileSeries:
    """真实线路区段制动剖面（坡度/曲线/限速取自共享数据）。"""

    return route_braking_series(
        bundle.train,
        shared,
        start_km=start_km,
        v0_mps=v0_kmh / 3.6,
        dt=dt,
        brake_command=brake_command,
        end_km=end_km,
        max_time_s=max_time_s,
        scenario_id=f"route_braking_{start_km:.0f}km",
    )


# ------------------------------------------------------------------
# 运行
# ------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineCase:
    """一个 baseline 配置。"""

    controller: RegenController
    label: str


def default_baseline_cases(bundle: ComponentBundle) -> Tuple[BaselineCase, ...]:
    """阶段 2 基础 baseline 集合。

    占空比取值的物理依据：输出侧是「储能开路电压 1100 V + 内阻」的母线，
    buck 稳态近似 v_out ≈ d1 * v_in（v_in ≈ 1500 V）。因此
        d1 < 1100/1500 = 0.733 时 v_out < 储能开路电压，充电电流恒为 0（回收不到能量）。
    取 0.75（刚过门槛，轻载）与 0.85（逼近 u0=0.9 上限，受储能功率上限约束），
    两个档位分别暴露"占空比不足"与"储能功率受限"两种典型失效模式。

    闭环 baseline（PI / PID / 传统 SMC）与主算法**共用**同一套滑模面/参考量定义
    （`regenerative_braking.tracking`），避免口径漂移。

    .. note::
       参考状态 ``x_{ref,k}`` 的构造式（方案问题 13）已由编写人裁定，见
       :class:`~regenerative_braking.tracking.RegenerativeReferenceState`
       （``data_status = scheme_authored``）。参考量从**同一个**
       ``bundle.converter_params`` 取电压窗口与电感电流上限，
       保证控制器与被控对象同源。每个控制器的 ``note`` 里都带
       ``x_ref_status=scheme_authored``，便于在下游结果里识别口径来源。

    .. warning::
       **问题 30 修订（2026-09-26）—— 参考量改走唯一装配入口**。

       本函数此前调用 ``RegenerativeReferenceState.from_converter_params``，
       即**问题 21 修正前**的历史口径（电压分量「窗口内就地保持」、无储能功率上限）；
       而 ``validation/baselines.py::_reference`` 在问题 21 落地时已改走正式口径。
       于是 ``pi`` / ``pid`` / ``traditional_smc`` 三个标签在本入口（阶段 1/2）
       与阶段 9 套件下**不是同一个控制器**——实测 ``pid`` 回收能量差 ``0.28%``、
       ``i_L`` 峰值 ``3118 → 1821 A``、``v_out`` 峰值 ``1731 → 1149 V``。

       现在改走 :func:`~regenerative_braking.tracking.build_reference_state`
       （问题 21 裁定的正式口径，两个参数都必需）。因此本入口的闭环 baseline
       读数会变——这是**口径对齐**，不是精度变化；阶段 9 套件的 128 行逐位不变
       （该路径本就已走正式口径）。
    """

    limits = bundle.converter_params.duty_limits
    # 问题 30：走唯一生产装配入口，与 validation/baselines.py::_reference 同源。
    reference = build_reference_state(bundle.converter_params, bundle.storage_params)
    return (
        BaselineCase(controller=ZeroDutyController(limits), label="uncontrolled_zero_duty"),
        BaselineCase(controller=FixedDutyController(0.75, 0.0, limits), label="fixed_duty_d1_0.75"),
        BaselineCase(controller=FixedDutyController(0.85, 0.0, limits), label="fixed_duty_d1_0.85"),
        BaselineCase(controller=PIController(reference, limits=limits), label="pi"),
        BaselineCase(controller=PIDController(reference, limits=limits), label="pid"),
        BaselineCase(
            controller=TraditionalSMCController(reference, limits=limits),
            label="traditional_smc",
        ),
    )


def run_case(
    bundle: ComponentBundle,
    series: ProfileSeries,
    case: BaselineCase,
    config: Optional[SimulationConfig] = None,
) -> SimulationResult:
    """运行单个 baseline 场景。"""

    simulator = build_simulator(bundle)
    return simulator.run(series, controller=case.controller, config=config)


def run_baseline_matrix(
    bundle: ComponentBundle,
    series: ProfileSeries,
    config: Optional[SimulationConfig] = None,
) -> List[Tuple[str, SimulationResult]]:
    """在同一工况下跑完全部基础 baseline。"""

    results: List[Tuple[str, SimulationResult]] = []
    for case in default_baseline_cases(bundle):
        results.append((case.label, run_case(bundle, series, case, config)))
    return results


def summarize_results(results: Sequence[Tuple[str, SimulationResult]]) -> List[Dict[str, Any]]:
    """把结果整理成可比较的行（baseline 对比表的雏形）。"""

    rows: List[Dict[str, Any]] = []
    for label, result in results:
        metrics = result.to_scenario_metrics()
        row = metrics.to_flat_dict()
        row["baseline_label"] = label
        rows.append(row)
    return rows
