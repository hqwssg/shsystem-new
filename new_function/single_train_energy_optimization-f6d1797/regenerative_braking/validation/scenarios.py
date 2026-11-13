"""阶段 9 验证场景目录（对应算法文档 §9 的 9 类场景）。

场景 = **剖面 + 被控对象扰动 + 观测扰动** 的三元组。每个场景都带
``family``（对应算法文档 §9 表的行号）与 ``variant``（同一族内的参数档），
因此"9 个场景"落地为"9 个族 / 若干档"，对比表按 (族, 档) 出行。

===================================  ==========================  ================
族                                   本实现                           档
===================================  ==========================  ================
1  平直常规制动（基准工况）            等减速度                          nominal
2  长大下坡（持续再生 + SOC 增长）      减速后恒速保持                     nominal
R  真实线路区段制动                   坡度/曲线/限速取自共享数据          nominal
3  载重变化                           缩放列车质量                      0.6x / 1.4x
4  制动功率突变                       分段恒减速度（段间阶跃）            nominal
5  SOC 接近上限                       提高初始 SOC 后持续再生           0.85 / 0.89
6  参数扰动                           变流器/储能参数按比例缩放          2 档
7  强非线性触发 UKF                   大阶跃分段剖面                      nominal
8  测量噪声                           观测噪声装饰器                     1% / 5%
9  模型失配                           被控对象 1.8 倍质量、模型仍标称      nominal
===================================  ==========================  ================

.. warning::
   全部场景结果为 ``仿真结果，不作为工程结论``。
   剖面时长按"能在数分钟内跑完全矩阵"选取，不代表工程运营时长；
   需要正式结论时必须用 ``tools/run_validation_suite.py --dt 1e-4``
   与全长剖面重跑。

.. warning::
   每个剖面的速度必须显著高于**再生投入门限 1.0 m/s（3.6 km/h）**，
   否则电机再生力包络归零、整个场景退化成"无再生"却仍然"跑通"。
   本模块用 :func:`_assert_regen_active` 对每个场景强制校验，不允许静默退化。

.. note::
   族 5（SOC 接近上限）的初始 SOC 取 0.85 / 0.89，而 ``soc_max = 0.90``
   （工程预设，非实测）。选择依据是"让 SOC 在剖面内真的逼近上限、
   触发储能侧功率约束"，而不是让结果好看。储能触限的单元级行为由
   ``tests/test_storage_model.py::test_full_soc_curtails_all_charging`` 单独把关。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..io.data_loader import SharedRailwayData
from ..simulation.profiles import ProfileSeries, segmented_braking_series
from ..simulation.scenario_runner import (
    ComponentBundle,
    scenario_2_long_downhill,
    scenario_route_braking,
)
from .perturbation import (
    ObservationNoise,
    PlantOverride,
    PerturbationBundle,
    scale_converter_parameter,
    scale_mass,
    scale_storage_parameter,
    set_storage_soc_initial,
)


class ScenarioError(ValueError):
    """验证场景定义不合法。"""


@dataclass(frozen=True)
class ValidationScenario:
    """一个可运行的验证场景。"""

    scenario_id: str
    family: str
    variant: str
    description: str
    series: ProfileSeries
    perturbation: PerturbationBundle = field(default_factory=PerturbationBundle)
    data_status: str = "simulation"
    notes: Tuple[str, ...] = ()
    reference: Mapping[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.scenario_id}" if not self.variant else f"{self.scenario_id}[{self.variant}]"

    def describe(self) -> str:
        parts = [self.label, f"({self.family})", self.description]
        parts.extend(self.perturbation.describe())
        return " | ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# 默认剖面参数（可在命令行覆盖）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioProfileConfig:
    """各场景的剖面参数。

    三条硬约束（**必须同时满足**，否则场景会静默退化或失去意义）：

    1. **速度下限**：电机模型的再生投入门限是
       ``min_regen_speed_m_per_s = 1.0 m/s（3.6 km/h）``，速度低于它时
       ``regen_force_limit_n`` 直接返回 0，再生力包络归零。
       因此每个剖面的**最低速度**必须高于该门限至少 ``regen_speed_margin`` 倍。
       本模块不靠"记得把速度调高"来保证这一点，而是由
       :func:`_assert_regen_active` 对**每一个**场景强制校验——违反即报错。
       （踩过的坑：最初为了压缩剖面时长把入口速度压到 3.6 km/h，
       第一步之后速度就跌破门限，整条剖面退化为"无再生"，
       而对比表仍然"跑通了"，全是 0——静默退化比报错危险得多。）

    2. **步长** ``dt ≤ 2e-4 s``。这不是保守，是实测：4e-4 s 下 PID baseline 的
       能量闭合相对残差为 2.95e-3，2e-4 s 下骤降到 2.92e-7（**差 4 个数量级**）。
       原因是粗步长下 **PID 自身的轨迹就变了**（同一现象已在
       ``tools/diagnose_energy_closure.py`` 的 warning 中记录）。
       即 4e-4 s 不是"精度差一点"，而是**控制器已经不在设计工况上**，
       用它跑出来的对比表没有意义。

    3. **剖面时长**按"全矩阵可在数分钟内跑完"选取，不代表工程运营时长。
       需要正式结论时必须用 ``tools/run_validation_suite.py --dt 1e-4``
       配全长剖面重跑。
    """

    #: 最低速度相对再生门限的裕度倍数（见类 docstring 约束 1）
    regen_speed_margin: float = 1.5

    #: 族 1 / 族 3 / 族 6 / 族 8 / 族 9：平直制动**速度窗口**
    #: 入口 36 km/h（10 m/s）、减速度 0.25 m/s²、窗口 8 s → 末速 28.8 km/h，
    #: 距再生门限（3.6 km/h）有 8 倍裕度，整段都在有效再生区。
    flat_v0_kmh: float = 36.0
    flat_decel_mps2: float = 0.25
    flat_window_s: float = 8.0

    #: 族 2 / 族 5：长大下坡参数
    #: 减速度 0.15 m/s²：-9 ‰ 下坡下可达上限实测 0.1964 m/s²，取 0.15 留约 1.3 倍裕度。
    #: 入口/目标速度取 18/16 km/h：恒速保持段是再生制动的典型持续工况，
    #: 必须显著高于 3.6 km/h 门限。
    downhill_entry_kmh: float = 18.0
    downhill_target_kmh: float = 16.0
    downhill_decel_mps2: float = 0.15
    downhill_gradient_per_mille: float = -9.0
    downhill_hold_s: float = 2.0

    #: 族 R：真实线路区段
    route_start_km: float = 0.0
    route_v0_kmh: float = 30.0
    route_max_time_s: float = 2.0

    #: 族 4 / 族 7：分段剖面段长（入口速度沿用 ``flat_v0_kmh``）
    segmented_segment_s: float = 1.0

    #: 族 3 / 族 9：重车档参数
    #: 质量放大后可达减速度下降（``scale_mass`` 不放大最大制动力），
    #: 因此重车档的请求减速度必须单独下调，否则可达性校验会报错。
    heavy_mass_factor: float = 1.4
    heavy_decel_mps2: float = 0.18
    mismatch_mass_factor: float = 1.8
    mismatch_decel_mps2: float = 0.1375

    def __post_init__(self) -> None:
        for name in (
            "regen_speed_margin",
            "flat_v0_kmh",
            "flat_decel_mps2",
            "flat_window_s",
            "downhill_entry_kmh",
            "downhill_target_kmh",
            "downhill_decel_mps2",
            "route_v0_kmh",
            "segmented_segment_s",
            "heavy_mass_factor",
            "heavy_decel_mps2",
            "mismatch_mass_factor",
            "mismatch_decel_mps2",
        ):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0.0:
                raise ScenarioError(f"{name} 必须为正有限值，实际为 {value!r}")
        if self.regen_speed_margin <= 1.0:
            raise ScenarioError(
                "regen_speed_margin 必须 > 1（否则剖面最低速度只是勉强碰到再生门限）"
            )
        if self.downhill_target_kmh > self.downhill_entry_kmh:
            raise ScenarioError("downhill_target_kmh 不得大于 downhill_entry_kmh")
        if self.downhill_hold_s < 0.0:
            raise ScenarioError("downhill_hold_s 必须非负")
        if self.route_max_time_s <= 0.0:
            raise ScenarioError("route_max_time_s 必须为正")


# ---------------------------------------------------------------------------
# 场景目录
# ---------------------------------------------------------------------------


def build_validation_scenarios(
    bundle: ComponentBundle,
    dt: float,
    *,
    shared: Optional[SharedRailwayData] = None,
    config: Optional[ScenarioProfileConfig] = None,
    selected_keys: Optional[Sequence[str]] = None,
) -> Tuple[ValidationScenario, ...]:
    """构造验证场景；未传 selected_keys 时保持完整目录及原有顺序。

    ``shared`` 为 ``None`` 时**跳过**族 R（真实线路区段），并在
    ``scenario_id`` 中以 ``skipped`` 形式不留空行——跳过是有意行为，
    不是静默降级：调用方可以通过返回序列里是否存在族 R 来判断。
    """

    cfg = config or ScenarioProfileConfig()
    wanted = None
    if selected_keys is not None:
        if isinstance(selected_keys, str) or not selected_keys or any(not isinstance(k, str) for k in selected_keys):
            raise ScenarioError("请选择有效的场景标签")
        wanted = set(selected_keys)
        if len(wanted) != len(selected_keys):
            raise ScenarioError("场景不可重复")

    def selected(scenario_id: str, variant: str) -> bool:
        return wanted is None or f"{scenario_id}[{variant}]" in wanted

    if wanted is not None:
        available = {
            "s1_flat_braking[nominal]", "s2_long_downhill[nominal]",
            "s3_mass_variation[mass_0.6x]", f"s3_mass_variation[mass_{cfg.heavy_mass_factor:.1f}x]",
            "s4_power_step[nominal]", "s5_soc_near_limit[soc0_0.85]", "s5_soc_near_limit[soc0_0.89]",
            "s6_parameter_perturbation[converter_L_plus50pct]", "s6_parameter_perturbation[storage_R_plus100pct]",
            "s7_strong_nonlinearity[nominal]", "s8_measurement_noise[noise_1pct]",
            "s8_measurement_noise[noise_5pct]", "s9_model_mismatch[nominal]",
        }
        if shared is not None:
            available.add("sR_route_braking[nominal]")
        if wanted - available:
            raise ScenarioError("所选场景不存在于当前数据版本：" + "、".join(sorted(wanted - available)))
    #: 电机再生投入门限（m/s）。所有剖面最低速度都必须高于它，见 _assert_regen_active。
    regen_floor_mps = float(bundle.motor.min_regen_speed_m_per_s)
    scenarios: list[ValidationScenario] = []

    # ---- 族 1：平直常规制动（基准工况）-----------------------------------
    if selected("s1_flat_braking", "nominal"):
        scenarios.append(
            ValidationScenario(
                scenario_id="s1_flat_braking",
                family="1_平直常规制动",
                variant="nominal",
                description=(
                    f"等减速度 {cfg.flat_decel_mps2:.2f} m/s²，"
                    f"入口 {cfg.flat_v0_kmh:.1f} km/h，窗口 {cfg.flat_window_s:.1f} s"
                ),
                series=_flat_window(
                    bundle.train,
                    dt=dt,
                    v0_kmh=cfg.flat_v0_kmh,
                    decel_mps2=cfg.flat_decel_mps2,
                    window_s=cfg.flat_window_s,
                    scenario_id="s1_flat_braking",
                    description="Scenario 1 平直线路常规制动（等减速度，取制动窗口）",
                ),
            )
        )

    # ---- 族 2：长大下坡 ---------------------------------------------------
    if selected("s2_long_downhill", "nominal"):
        scenarios.append(
            ValidationScenario(
                scenario_id="s2_long_downhill",
                family="2_长大下坡",
                variant="nominal",
                description=(
                    f"{cfg.downhill_gradient_per_mille:.1f} ‰ 坡道，"
                    f"{cfg.downhill_entry_kmh:.1f}→{cfg.downhill_target_kmh:.1f} km/h 后恒速 "
                    f"{cfg.downhill_hold_s:.1f} s"
                ),
                series=scenario_2_long_downhill(
                    bundle,
                    dt=dt,
                    entry_kmh=cfg.downhill_entry_kmh,
                    target_kmh=cfg.downhill_target_kmh,
                    decel_mps2=cfg.downhill_decel_mps2,
                    gradient_per_mille=cfg.downhill_gradient_per_mille,
                    hold_duration_s=cfg.downhill_hold_s,
                ),
            )
        )

    # ---- 族 R：真实线路区段（依赖共享数据）-------------------------------
    if shared is not None and selected("sR_route_braking", "nominal"):
        scenarios.append(
            ValidationScenario(
                scenario_id="sR_route_braking",
                family="R_真实线路区段制动",
                variant="nominal",
                description=f"区段自 {cfg.route_start_km:.2f} km 起，入口 {cfg.route_v0_kmh:.1f} km/h",
                series=scenario_route_braking(
                    bundle,
                    shared,
                    start_km=cfg.route_start_km,
                    v0_kmh=cfg.route_v0_kmh,
                    dt=dt,
                    brake_command=0.25,
                    max_time_s=cfg.route_max_time_s,
                ),
                notes=("坡度/曲线/限速逐点取自共享数据",),
                reference=_section_reference(shared, cfg.route_start_km),
            )
        )

    # ---- 族 3：载重变化 ---------------------------------------------------
    # 只缩质量、不缩最大制动力（见 scale_mass 的 warning），因此请求减速度
    # 必须按最重的一档下调，否则可达性校验会报错。
    for factor, decel in (
        (0.6, cfg.flat_decel_mps2),
        (cfg.heavy_mass_factor, cfg.heavy_decel_mps2),
    ):
        if not selected("s3_mass_variation", f"mass_{factor:.1f}x"):
            continue
        heavy = scale_mass(bundle.train, factor, label=f"mass_{factor:.1f}x")
        scenarios.append(
            ValidationScenario(
                scenario_id="s3_mass_variation",
                family="3_载重变化",
                variant=f"mass_{factor:.1f}x",
                description=(
                    f"质量 {factor:.1f}×（{heavy.mass_kg / 1e3:.0f} t），"
                    f"请求减速度 {decel:.3f} m/s²"
                ),
                series=_flat_window(
                    heavy,
                    dt=dt,
                    v0_kmh=cfg.flat_v0_kmh,
                    decel_mps2=decel,
                    window_s=cfg.flat_window_s,
                    scenario_id="s3_mass_variation",
                    description=f"平直制动窗口（质量 ×{factor:.1f}）",
                ),
                perturbation=PerturbationBundle(
                    plant=PlantOverride(
                        train=heavy,
                        description=f"被控对象质量 ×{factor:.1f}（最大制动力不变）",
                    ),
                ),
                notes=("最大制动力未随质量缩放：共享数据无依据，见 scale_mass 的 warning",),
            )
        )

    # ---- 族 4：制动功率突变 ----------------------------------------------
    seg = cfg.segmented_segment_s
    # 减速度取 0.05 ↔ 0.22 m/s²：平直道可达上限实测约 0.28 m/s²（2 万吨、
    # 最大制动力 6200 kN），0.22 留约 1.27 倍裕度；0.05 与 0.22 之间是 4.4 倍阶跃，
    # 足以在请求再生功率上产生阶跃。
    decel_lo, decel_hi = 0.05, 0.22
    if selected("s4_power_step", "nominal"):
        scenarios.append(
            ValidationScenario(
                scenario_id="s4_power_step",
                family="4_制动功率突变",
                variant="nominal",
                description=f"减速度在 {decel_lo:.2f} 与 {decel_hi:.2f} m/s² 间阶跃（每 {seg:.1f} s 一段）",
                series=segmented_braking_series(
                    bundle.train,
                    v0_mps=cfg.flat_v0_kmh / 3.6,
                    segments=(
                        (seg, decel_lo, 0.0),
                        (seg, decel_hi, 0.0),
                        (seg, decel_lo, 0.0),
                        (seg, decel_hi, 0.0),
                    ),
                    dt=dt,
                    speed_limit_mps=80.0 / 3.6,
                    scenario_id="s4_power_step",
                    description="制动功率突变（减速度阶跃）",
                ),
                notes=("期望触发 switch_to_ukf_power_step / current_rate",),
            )
        )

    # ---- 族 5：SOC 接近上限 ----------------------------------------------
    for soc_initial in (0.85, 0.89):
        if not selected("s5_soc_near_limit", f"soc0_{soc_initial:.2f}"):
            continue
        scenarios.append(
            ValidationScenario(
                scenario_id="s5_soc_near_limit",
                family="5_SOC接近上限",
                variant=f"soc0_{soc_initial:.2f}",
                description=f"初始 SOC {soc_initial:.2f}（上限 0.90）下持续再生",
                series=scenario_2_long_downhill(
                    bundle,
                    dt=dt,
                    entry_kmh=cfg.downhill_entry_kmh,
                    target_kmh=cfg.downhill_target_kmh,
                    decel_mps2=cfg.downhill_decel_mps2,
                    gradient_per_mille=cfg.downhill_gradient_per_mille,
                    hold_duration_s=cfg.downhill_hold_s,
                ),
                perturbation=PerturbationBundle(
                    plant=PlantOverride(
                        storage_params=set_storage_soc_initial(bundle.storage_params, soc_initial),
                        description=f"储能初始 SOC = {soc_initial:.2f}",
                    ),
                ),
                notes=("SOC 上限 0.90 为工程预设，非实测",),
            )
        )

    # ---- 族 6：参数扰动 ---------------------------------------------------
    perturbations = (
        (
            "converter_L_plus50pct",
            lambda: PlantOverride(
                converter_params=scale_converter_parameter(
                    bundle.converter_params, "inductance_h", 1.5
                ),
                description="变流器电感 L ×1.5（参数扰动）",
            ),
        ),
        (
            "storage_R_plus100pct",
            lambda: PlantOverride(
                storage_params=scale_storage_parameter(
                    bundle.storage_params, "internal_resistance_ohm", 2.0
                ),
                description="储能内阻 R ×2.0（参数扰动）",
            ),
        ),
    )
    for variant, make_override in perturbations:
        if not selected("s6_parameter_perturbation", variant):
            continue
        override = make_override()
        scenarios.append(
            ValidationScenario(
                scenario_id="s6_parameter_perturbation",
                family="6_参数扰动",
                variant=variant,
                description=override.description,
                series=_flat_window(
                    bundle.train,
                    dt=dt,
                    v0_kmh=cfg.flat_v0_kmh,
                    decel_mps2=cfg.flat_decel_mps2,
                    window_s=cfg.flat_window_s,
                    scenario_id="s6_parameter_perturbation",
                    description="平直制动窗口（参数扰动）",
                ),
                perturbation=PerturbationBundle(plant=override),
                notes=("控制器/辨识器仍按标称参数装配——本族考察参数不确定性的影响",),
            )
        )

    # ---- 族 7：强非线性触发 UKF ------------------------------------------
    # 减速度 0.02 ↔ 0.18 m/s²、坡度 0 ↔ −6 ‰ 同时阶跃。
    # 上限依据：−6 ‰ 下可达减速度实测约 0.224 m/s²（−9 ‰ 时为 0.1963），
    # 0.18 留约 1.24 倍裕度。
    if selected("s7_strong_nonlinearity", "nominal"):
        scenarios.append(
            ValidationScenario(
                scenario_id="s7_strong_nonlinearity",
                family="7_强非线性触发UKF",
                variant="nominal",
                description="大阶跃分段剖面（减速度 0.02↔0.18 m/s²，坡度 0↔−6 ‰）",
                series=segmented_braking_series(
                    bundle.train,
                    v0_mps=cfg.flat_v0_kmh / 3.6,
                    segments=(
                        (seg, 0.02, 0.0),
                        (seg, 0.18, -6.0),
                        (seg, 0.02, 0.0),
                        (seg, 0.18, -6.0),
                    ),
                    dt=dt,
                    speed_limit_mps=80.0 / 3.6,
                    scenario_id="s7_strong_nonlinearity",
                    description="强非线性（减速度与坡度同时阶跃）",
                ),
                notes=("同时激励 residual / nonlinearity / speed_jerk / gradient_step",),
            )
        )

    # ---- 族 8：测量噪声 ---------------------------------------------------
    for relative in (0.01, 0.05):
        if not selected("s8_measurement_noise", f"noise_{relative:.0%}".replace("%", "pct")):
            continue
        scenarios.append(
            ValidationScenario(
                scenario_id="s8_measurement_noise",
                family="8_测量噪声",
                variant=f"noise_{relative:.0%}".replace("%", "pct"),
                description=f"电压/电流相对噪声 {relative:.0%}（另加 SOC/速度噪声）",
                series=_flat_window(
                    bundle.train,
                    dt=dt,
                    v0_kmh=cfg.flat_v0_kmh,
                    decel_mps2=cfg.flat_decel_mps2,
                    window_s=cfg.flat_window_s,
                    scenario_id="s8_measurement_noise",
                    description="平直制动窗口（测量噪声）",
                ),
                perturbation=PerturbationBundle(
                    noise=ObservationNoise(
                        relative_std=relative,
                        absolute_std_v=2.0,
                        absolute_std_a=2.0,
                        soc_std=1.0e-3,
                        speed_std=1.0e-3,
                    )
                ),
                notes=("噪声同时作用于控制与辨识（两者读同一观测对象）",),
            )
        )

    # ---- 族 9：模型失配 ---------------------------------------------------
    if selected("s9_model_mismatch", "nominal"):
        mismatch_factor = cfg.mismatch_mass_factor
        heavy = scale_mass(bundle.train, mismatch_factor, label=f"mismatch_{mismatch_factor:.1f}x")
        scenarios.append(
            ValidationScenario(
                scenario_id="s9_model_mismatch",
                family="9_模型失配",
                variant="nominal",
                description=(
                    f"被控对象质量 ×{mismatch_factor:.1f}（{heavy.mass_kg / 1e3:.0f} t），"
                    "控制器/辨识器仍用标称参数"
                ),
                series=_flat_window(
                    heavy,
                    dt=dt,
                    v0_kmh=cfg.flat_v0_kmh,
                    decel_mps2=cfg.mismatch_decel_mps2,
                    window_s=cfg.flat_window_s,
                    scenario_id="s9_model_mismatch",
                    description="平直制动窗口（被控对象质量放大、模型未同步）",
                ),
                perturbation=PerturbationBundle(
                    plant=PlantOverride(
                        train=heavy,
                        description=f"被控对象质量 ×{mismatch_factor:.1f}，模型未同步",
                    ),
                    controller_uses_nominal=True,
                ),
                notes=(
                    "标称模型（2 万吨 + state_scale 1400V/1500A）对 1.8 倍质量对象",
                    "这是「模型失配」的核心：辨识模型的归一化尺度与参考量都不再匹配对象",
                ),
            )
        )

    # 强制校验：每个场景的最低速度都必须显著高于再生投入门限。
    # 这一步是"不允许静默退化"的落点——见 ScenarioProfileConfig 的约束 1。
    for scenario in scenarios:
        _assert_regen_active(scenario, regen_floor_mps, cfg.regen_speed_margin)

    return tuple(scenarios)


def _flat_window(
    train,
    *,
    dt: float,
    v0_kmh: float,
    decel_mps2: float,
    window_s: float,
    scenario_id: str,
    description: str,
) -> ProfileSeries:
    """构造一段**平直制动窗口**（不制动到停车）。

    为什么是"窗口"而不是"制动到停车"：``dt`` 必须 ≤ 2e-4 s，
    若从 36 km/h 一路制动到 0，在 0.25 m/s² 下需要 40 s（20 万步），
    全矩阵跑不完；而且末段速度会跌破 3.6 km/h 的再生门限，那部分本来也不产生再生。
    因此统一取前 ``window_s`` 秒：末速由 ``v0 − decel·window_s`` 决定，
    并交给 :func:`_assert_regen_active` 校验它仍在有效再生区。

    ``train`` 必须显式传入（而不是用 bundle 的标称列车）：载重变化/模型失配
    场景里剖面速度轨迹由列车动力学决定，用标称列车生成剖面再换重车去跑，
    等于给重车喂一条它跑不出来的曲线。
    """

    v0_mps = v0_kmh / 3.6
    v_end_mps = max(0.0, v0_mps - decel_mps2 * window_s)

    from ..simulation.profiles import constant_deceleration_series

    return constant_deceleration_series(
        train,
        v0_mps=v0_mps,
        decel_mps2=decel_mps2,
        dt=dt,
        v_end_mps=v_end_mps,
        gradient_per_mille=0.0,
        curve_radius_m=None,
        speed_limit_mps=80.0 / 3.6,
        scenario_id=scenario_id,
        description=description,
    )


def _assert_regen_active(
    scenario: ValidationScenario,
    regen_floor_mps: float,
    margin: float,
) -> None:
    """校验场景剖面的最低速度仍在有效再生区（见配置类约束 1）。

    违反时**报错而不是告警**：一个速度全程低于再生门限的场景，
    所有 baseline 的回收能量都会是 0 或来自母线倒灌，对比表看起来"跑通了"
    却什么都没测——这正是最危险的静默失败。
    """

    if not scenario.series.samples:
        raise ScenarioError(f"场景 {scenario.label} 的剖面为空")
    lowest = min(sample.speed_mps for sample in scenario.series.samples)
    required = margin * regen_floor_mps
    if lowest < required:
        raise ScenarioError(
            f"场景 {scenario.label} 的最低速度 {lowest:.4f} m/s"
            f"（{lowest * 3.6:.2f} km/h）低于再生投入门限 {regen_floor_mps:.4f} m/s 的 "
            f"{margin:.2f} 倍（{required:.4f} m/s，{required * 3.6:.2f} km/h）："
            "该剖面会退化为「无再生」，请调高入口速度或缩短剖面窗口。"
        )


def scenario_ids(scenarios: Sequence[ValidationScenario]) -> Tuple[str, ...]:
    """场景标签序列（含 variant），便于落盘与断言。"""

    return tuple(scenario.label for scenario in scenarios)


def scenario_families(scenarios: Sequence[ValidationScenario]) -> Tuple[str, ...]:
    """出现过的族（去重、保持顺序）——用于检查"9 个场景"是否齐备。"""

    seen: list[str] = []
    for scenario in scenarios:
        if scenario.family not in seen:
            seen.append(scenario.family)
    return tuple(seen)


def _section_reference(shared: SharedRailwayData, position_km: float) -> Mapping[str, Any]:
    """起点所在官方区间的参照值（官方时分 + 实绩再生强度）。

    这些值描述的是**整段区间运行**，而族 R 只跑制动窗口，两者不可直接相减。
    放在指标里是为了让读数带上真实区间背景，字段一律以 ``reference_`` 开头。
    """

    section = shared.official_section(position_km)
    if section is None:
        return {}
    start, end = section
    reference: dict = {
        "reference_section_distance_km": round(end.position_km - start.position_km, 3),
    }
    run_time = shared.section_run_time(start.name, end.name, direction="down")
    if run_time is not None:
        reference["reference_official_run_time_min"] = run_time
    regen = shared.interval_regen(start.name, end.name)
    if regen is not None:
        reference["reference_meter_regen_kwh_per_km_p50"] = regen.regen_kwh_per_km_p50
        reference["reference_meter_regen_kwh_per_km_p90"] = regen.regen_kwh_per_km_p90
        reference["reference_meter_samples"] = float(regen.samples)
    return reference
