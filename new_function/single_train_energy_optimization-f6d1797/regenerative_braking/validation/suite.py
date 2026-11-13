"""阶段 9 验证套件：场景 × baseline 矩阵的运行与落盘。

运行一次 ``run_validation_suite`` 会得到 ``SuiteRunRecord`` 序列，
再由 :func:`write_suite_outputs` 落成三份文件：

    summary.csv     一行一 (场景, baseline)，全部指标平铺
    comparison.csv  一行一 (场景, baseline, optimized, 指标)，含 delta / delta_percent
    manifest.json   运行元信息（场景清单、baseline 清单、dt、闭合残差、待确认项）

.. warning::
   全部结果为 ``仿真结果，不作为工程结论``。
   ``manifest.json`` 里带 ``PENDING_SCHEME_CONFIRMATION`` 与三处待确认项，
   由主算法的 ``audit()`` 透传，方案编写人确认前这些数字不得引用为工程结论。

组合规则（容易搞错，显式写明）：
    被控对象 = ``bundle`` → 叠加**场景**的扰动 → 叠加**baseline** 的扰动
    （后叠加者优先，因为"无储能"这类 baseline 级扰动必须能覆盖场景）
    控制器   = 由**标称** bundle 装配（除场景显式声明 ``controller_uses_nominal=False``）
    观测     = 场景带噪声时，在控制器外面包一层噪声装饰器
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..identification import PENDING_SCHEME_CONFIRMATION
from ..metrics import ENERGY_ACCOUNTING_DEFINITIONS
from ..simulation.closed_loop import CLOSED_LOOP_PENDING_ITEMS, ClosedLoopController
from ..simulation.regenerative_simulator import SimulationConfig
from ..simulation.scenario_runner import ComponentBundle, build_simulator
from .baselines import (
    CONTROLLER_PROFILE_DEFAULT,
    OPTIMIZED_LABEL,
    ValidationBaseline,
    baseline_catalog,
    filter_comparison_baselines,
)
from .comparison import build_comparison_rows
from .perturbation import (
    NoisyObservationController,
    PlantOverride,
    apply_plant_override,
)
from .scenarios import ValidationScenario


class SuiteError(RuntimeError):
    """验证套件配置或运行错误。"""


def merge_plant_overrides(
    first: Optional[PlantOverride], second: Optional[PlantOverride]
) -> Optional[PlantOverride]:
    """叠加两层被控对象扰动，``second`` 优先。"""

    if first is None or first.is_noop:
        return second
    if second is None or second.is_noop:
        return first
    return PlantOverride(
        train=second.train if second.train is not None else first.train,
        converter_params=(
            second.converter_params
            if second.converter_params is not None
            else first.converter_params
        ),
        storage_params=(
            second.storage_params if second.storage_params is not None else first.storage_params
        ),
        description=" + ".join(
            part for part in (first.description, second.description) if part
        ),
        data_status=f"{first.data_status}/{second.data_status}",
    )


@dataclass(frozen=True)
class SuiteRunRecord:
    """一次 (场景, baseline) 运行的完整记录。"""

    scenario_label: str
    scenario_family: str
    scenario_variant: str
    baseline_label: str
    is_optimized: bool
    metrics: Mapping[str, Any]
    closure_relative_residual: float
    steps: int
    duration_s: float
    notes: Tuple[str, ...] = ()
    filter_audit: Optional[Mapping[str, Any]] = None

    def to_summary_row(self) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "scenario": self.scenario_label,
            "scenario_family": self.scenario_family,
            "scenario_variant": self.scenario_variant,
            "baseline": self.baseline_label,
            "is_optimized": self.is_optimized,
            "steps": self.steps,
            "duration_s": self.duration_s,
            "closure_relative_residual": self.closure_relative_residual,
        }
        for key, value in sorted(self.metrics.items()):
            if key == "notes":
                continue
            row[key] = value
        if self.filter_audit is not None:
            # switch_count / final_mode 在 audit() 的 ``identification`` 子字典里，
            # 不在顶层——取错层级会静默得到 None，让"模式切换了多少次"这一列全空。
            identification = self.filter_audit.get("identification", {})
            row["filter_switch_count"] = identification.get("switch_count")
            row["filter_final_mode"] = identification.get("final_mode")
            row["filter_pending_scheme_confirmation"] = self.filter_audit.get(
                "pending_scheme_confirmation"
            )
        if self.notes:
            row["notes"] = " | ".join(self.notes)
        return row


def _extract_controller(controller):
    """剥掉噪声装饰器，取到真正的控制器（用于读 audit）。"""

    if isinstance(controller, NoisyObservationController):
        return controller.inner
    return controller


def _run_single(
    nominal_bundle: ComponentBundle,
    scenario: ValidationScenario,
    baseline: ValidationBaseline,
    *,
    dt: float,
    record_stride: int,
) -> SuiteRunRecord:
    # 被控对象：场景扰动 → baseline 扰动
    plant_bundle = apply_plant_override(nominal_bundle, scenario.perturbation.plant)
    plant_bundle = apply_plant_override(plant_bundle, baseline.plant_override(nominal_bundle))

    controller_bundle = (
        nominal_bundle if scenario.perturbation.controller_uses_nominal else plant_bundle
    )
    # 步长必须透传给装配层：主算法的控制通道增益先验（问题 18）按 **一步** 灵敏度
    # B = ∂x̂/∂u 构造，幅值正比于 dt，用错步长会按比例带偏且不会自己报错。
    controller = baseline.controller(controller_bundle, sample_time_s=dt)

    noise = scenario.perturbation.noise
    if noise is not None and not noise.is_noop:
        controller = NoisyObservationController(controller, noise)

    simulator = build_simulator(plant_bundle)
    result = simulator.run(
        scenario.series,
        controller=controller,
        config=SimulationConfig(dt=dt, record_stride=record_stride),
    )

    ledger = result.ledger
    reference = max(ledger.mechanical_braking_energy_j, 1.0)
    closure_relative = abs(ledger.closure_residual_j) / reference

    notes = list(scenario.notes)
    notes.extend(baseline.notes)
    notes.extend(scenario.perturbation.describe())

    filter_audit: Optional[Mapping[str, Any]] = None
    inner = _extract_controller(controller)
    if isinstance(inner, ClosedLoopController):
        filter_audit = inner.audit()
        identification = filter_audit.get("identification", {})
        notes.append(
            f"模式切换 {identification.get('switch_count', 0)} 次，"
            f"末态 {identification.get('final_mode', '?')}"
        )

    metrics = result.to_scenario_metrics().to_flat_dict()
    # 区间级参照（官方时分 / 实绩再生强度）只并入、不覆盖仿真自算的量，
    # 键名统一带 reference_ 前缀，避免被当成同口径实测。
    for key, value in dict(getattr(scenario, "reference", {}) or {}).items():
        metrics.setdefault(key, value)

    return SuiteRunRecord(
        scenario_label=scenario.label,
        scenario_family=scenario.family,
        scenario_variant=scenario.variant,
        baseline_label=baseline.label,
        is_optimized=baseline.is_optimized,
        metrics=metrics,
        closure_relative_residual=closure_relative,
        steps=len(scenario.series),
        duration_s=scenario.series.duration_s,
        notes=tuple(notes),
        filter_audit=filter_audit,
    )


def run_validation_suite(
    nominal_bundle: ComponentBundle,
    scenarios: Sequence[ValidationScenario],
    *,
    dt: float,
    baselines: Optional[Sequence[ValidationBaseline]] = None,
    record_stride: int = 50,
    extra_optimized: Optional[Mapping[str, Sequence[ValidationBaseline]]] = None,
    controller_profile: str = CONTROLLER_PROFILE_DEFAULT,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[SuiteRunRecord, ...]:
    """跑完 (场景 × baseline) 矩阵。

    ``extra_optimized`` 允许对**指定族**追加主算法变体（族 7 用它跑固定 EKF /
    固定 UKF 对照），键是 ``scenario.family``。
    """

    catalog = (
        tuple(baselines)
        if baselines is not None
        else baseline_catalog(controller_profile)
    )
    extra = dict(extra_optimized or {})

    records: List[SuiteRunRecord] = []
    for scenario in scenarios:
        targets = list(catalog)
        if scenario.family in extra:
            targets.extend(extra[scenario.family])
        for baseline in targets:
            if progress is not None:
                progress(f"{scenario.label} × {baseline.label}")
            records.append(
                _run_single(
                    nominal_bundle,
                    scenario,
                    baseline,
                    dt=dt,
                    record_stride=record_stride,
                )
            )
    return tuple(records)


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------

COMPARISON_COLUMNS = (
    "scenario",
    "baseline",
    "optimized",
    "metric",
    "metric_label",
    "unit",
    "prefer",
    "baseline_value",
    "optimized_value",
    "delta",
    "delta_percent",
    "improved",
)


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})
    return path


def write_suite_outputs(
    records: Sequence[SuiteRunRecord],
    out_dir: Path,
    *,
    dt: float,
    scenario_families: Sequence[str],
    optimized_labels: Sequence[str],
    baseline_labels: Sequence[str],
    extra: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Path]:
    """把运行记录落成 summary.csv / comparison.csv / manifest.json。"""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = [record.to_summary_row() for record in records]
    summary_columns: List[str] = []
    for row in summary_rows:
        for key in row:
            if key not in summary_columns:
                summary_columns.append(key)
    summary_path = _write_csv(out_dir / "summary.csv", summary_columns, summary_rows)

    comparison_rows = build_comparison_rows(records, optimized_labels=optimized_labels)
    comparison_path = _write_csv(out_dir / "comparison.csv", COMPARISON_COLUMNS, comparison_rows)

    worst_closure = max(
        (record.closure_relative_residual for record in records), default=0.0
    )
    exceedances = closure_exceedances(records)
    diagnosis = diagnose_optimized_controllers(
        records,
        optimized_labels=optimized_labels,
        baseline_labels=baseline_labels,
        min_fraction_of_best_baseline=MIN_CAPTURE_FRACTION_OF_BEST_BASELINE,
        min_mean_fraction_of_best_baseline=MIN_MEAN_CAPTURE_FRACTION_OF_BEST_BASELINE,
    )
    manifest: Dict[str, Any] = {
        "schema_version": "1.0",
        "energy_accounting_definitions": ENERGY_ACCOUNTING_DEFINITIONS,
        "dt": dt,
        "scenario_count": len({record.scenario_label for record in records}),
        "scenario_families": list(scenario_families),
        "baseline_labels": list(baseline_labels),
        "optimized_labels": list(optimized_labels),
        "run_count": len(records),
        "closure_relative_tolerance": CLOSURE_RELATIVE_TOLERANCE,
        "worst_closure_relative_residual": worst_closure,
        "closure_worst_by_family": closure_worst_by_family(records),
        "closure_exceedances": list(exceedances),
        "closure_note": (
            "闭合残差是求积误差（台账矩形法 1 阶 vs 状态 RK4 4 阶），随步长收敛；"
            "容差 1e-4 针对平滑激励在 dt=2e-4 下标定。观测噪声族（5% 相对噪声）下 "
            "PI/PID 因噪声抖振会超界，属已知数值现象，不隐藏、不放宽；"
            "需要正式结论时用 --dt 1e-4 重跑。"
            "（2026-09-25 已实测核对：默认步长下的全部超差条目在 dt=1e-4 下均进入容差，"
            "且族 R 的非主算法基线呈 1 阶收敛趋势；见 docs/bug_hunt_report_2026-09-25.md §5.1）"
            "注意：**闭合残差收敛不等于轨迹收敛**——前者只说明「该步的账记平了」，"
            "不说明「算的是同一条曲线」。主算法 rhonn_nsmc 的回收能量本身尚未随步长收敛"
            "（问题 22：u_eq 的一步死拍增益 ∝ 1/dt 使控制分支随 dt 翻转），"
            "引用主算法能量数值时**必须同时注明步长**；见同报告 §5.2。"
            "（2026-09-25 补充：问题 22 的根因**不在 u_eq 的定义式**——三场景 x_ref 全程恒定，"
            "该 1/dt 项就是调节动作本身，A 选项「改成 dt 无关形式」已实测否决"
            "（回收能量只剩基线的 0.6~2.3%）。真正的缺陷是问题 20 的 bang-bang 支路不连续。）"
            "（2026-09-26 落地：问题 20 的支路已改为**盒约束最小二乘**"
            "（u_eq = argmin_{‖u‖_∞≤u_0}‖(x_ref − g) − B·u‖²，连续、可达时逐位退化）；"
            "旧 bang-bang 读法保留为 reachability_fallback=\"bang_bang\" 供逐位复现。"
            "全量重跑（14 场景 × 128 次）后 128 行中 16 行变化、**全部是主算法**，"
            "112 行基线**逐位不变**；交付场景 s1/s2 由 4.167372/2.971038 变为"
            "4.167424/2.971089 kWh（差 ≤ 0.0033%），达成率仍 93.79%；"
            "闭合超差条数 3 → 1。**主算法能量数值仍必须与步长一同引用**"
            "（本次重跑只覆盖 dt=2e-4；dt=1e-4 一列为修订前读数）。"
            "见算法文档 §5.10.7/§5.10.8 与同报告 §5.5。）"
            "（2026-09-26 再次落地（问题 23）：保方向饱和律的范数口径由 2 球统一到**盒**"
            "（∞ 范数）——u_0 是逐通道上限，可行域是盒，2 球是其真子集。"
            "旧 2 球读法保留为 saturation_norm=\"l2_ball_legacy\" 供逐位复现，"
            "并可由 ClosedLoopController.audit() 的 saturation_norm 字段审计。"
            "全量重跑后仍 16 行变化、全部主算法、112 行基线逐位不变；"
            "s1/s2 变为 4.167619/2.971285 kWh（4 位小数 4.1676/2.9713），达成率仍 93.79%。"
            "**代价（已如实登记）**：噪声族 s8[noise_5pct] 的闭合残差由 5.842e-05 回到"
            "1.5115e-04（越出容差 1e-4），超差条数 1 → 2；该项是否随步长收敛由独立扫描回答，"
            "不在此处下结论。见算法文档 §5.11。）"
        ),
        "optimized_controller_diagnosis": {
            label: item.to_dict() for label, item in diagnosis.items()
        },
        "optimized_controllers_functional": all(
            item.functional for item in diagnosis.values()
        ),
        "pending_scheme_confirmation": PENDING_SCHEME_CONFIRMATION,
        "pending_scheme_items": [
            {
                "issue": item.issue_number,
                "title": item.title,
                "substitute": item.substitute,
                "consequence": item.consequence,
            }
            for item in CLOSED_LOOP_PENDING_ITEMS
        ],
        "data_status": "simulation_result_not_engineering_conclusion",
        "scenarios": sorted({record.scenario_label for record in records}),
    }
    if extra:
        manifest.update(dict(extra))
    manifest_path = out_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    return {
        "summary": summary_path,
        "comparison": comparison_path,
        "manifest": manifest_path,
    }


def default_extra_optimized() -> Mapping[str, Sequence[ValidationBaseline]]:
    """族 7 的额外主算法变体（固定 EKF / 固定 UKF 对照）。"""

    return {"7_强非线性触发UKF": filter_comparison_baselines()}


def optimized_labels(include_filter_variants: bool = True) -> Tuple[str, ...]:
    labels = [OPTIMIZED_LABEL]
    if include_filter_variants:
        labels.extend(item.label for item in filter_comparison_baselines())
    return tuple(labels)


# ---------------------------------------------------------------------------
# 主算法可用性诊断
# ---------------------------------------------------------------------------

#: 回收能量低于该值即视为「没有真正回收」（kWh）
CAPTURE_FLOOR_KWH = 1.0e-6

#: 主算法回收能量相对**同场景最好基线**的最低达成率（阶段 9 诊断的相对层门槛）。
#:
#: 2026-09-25 由「> 0」升级而来。绝对层门槛太松：问题 18 落地后主算法只回收
#: ``0.035 kWh``（同口径最好基线的 ``1/87``），"非零"这一条会放过
#: "勉强不为零、但工程上完全不可用"的结果。
#:
#: **门槛取值依据实测分布**（``tools/probe_capture_ratio.py``）：
#:
#: ==========================  =========  ==========================================
#: 口径                        达成率      说明
#: ==========================  =========  ==========================================
#: 退化态（问题 19/20 修正前）  ``0.8%``   主算法实质上没在工作
#: FAST_DT 13 场景最差         ``44.8%``  ``s6`` 储能 ``R_int ×2``，控制器用标称参数、
#:                                        被控对象已变——**合法模型失配**，不是故障
#: FAST_DT 13 场景均值         ``74.9%``  —
#: 全分辨率 ``s1``/``s2``       ``93.8%`` 标称工况
#: ==========================  =========  ==========================================
#:
#: 取 ``0.25`` 的理由：位于「退化态 ``0.8%``」与「最差合法场景 ``44.8%``」之间，
#: 距退化态约 ``31×``、距最差合法场景约 ``1.8×``，两侧都有余量。
#:
#: .. note::
#:     用户提议的 ``0.70``（依据标称场景实测 ``93.8%``）**被否决为逐场景门槛**：
#:     13 个场景中有 3 个（``s6`` 模型失配、``s7`` 强非线性、``s8`` 5% 噪声）
#:     合法地低于 ``0.70``，逐场景卡 ``0.70`` 会产生假告警。
#:     ``0.70`` 的量级改由**套件均值**门槛承载，见
#:     :data:`MIN_MEAN_CAPTURE_FRACTION_OF_BEST_BASELINE`。
MIN_CAPTURE_FRACTION_OF_BEST_BASELINE = 0.25

#: 主算法回收能量相对**同场景最好基线**的**套件均值**最低达成率。
#:
#: 逐场景门槛只能防「某场景静默退化」，防不住「每个场景都勉强过线」。
#: 本门槛要求整体达成率达标：实测 FAST_DT 均值 ``74.9%``、
#: 全分辨率标称场景 ``93.8%``，取 ``0.60``（距实测均值约 ``15`` 个百分点余量）。
MIN_MEAN_CAPTURE_FRACTION_OF_BEST_BASELINE = 0.60

#: 套件级闭合容差。**数值精度指标**，不是台账结构正确性指标。
#:
#: 口径与 ``tests/test_simulation_closure.py`` 一致：台账按「功率 × dt」矩形法（1 阶）
#: 累加，状态用 RK4（4 阶），因此残差是求积误差，大小由控制器的**开关活跃度**决定、
#: 随步长收敛。1e-4 是针对**平滑激励**在 ``dt = 2e-4`` 下标定的界。
#:
#: .. warning::
#:    观测噪声族（族 8，5% 相对噪声）下 PI/PID 会因噪声抖振而抬高求积误差，
#:    实测在 ``dt = 2e-4`` 下达 1.7e-4，**超出该界**。这不是台账 bug：
#:    ``dt`` 减半后实测降到 1.7e-5（约 8 倍），符合收敛趋势。
#:    本模块**不放宽界、也不隐藏**，而是把超界项逐条写进 ``manifest.json`` 的
#:    ``closure_exceedances``，由使用方决定是否用 ``--dt 1e-4`` 重跑。
CLOSURE_RELATIVE_TOLERANCE = 1.0e-4


@dataclass(frozen=True)
class OptimizedDiagnosis:
    """主算法在整轮验证里的可用性诊断。"""

    label: str
    functional: bool
    scenarios_total: int
    scenarios_with_zero_capture: int
    max_captured_energy_kWh: float
    #: 组内最大的 `duty_saturation_ratio`。该指标按**实际生效执行器可行域**判定贴轨
    #: （方案问题 25：曾写死 `[0, 1]`，使 `u0 = 0.9` 上的饱和恒不被统计）。
    #: 注意套件 `record_stride = 50`，与全分辨率探针的读数不可直接比较。
    max_duty_cycle: float
    reason: str
    blocking_issue: Optional[int] = None
    related_issues: Tuple[int, ...] = ()
    #: 相对判据（逐场景）：主算法回收能量 / 同场景最好基线回收能量 的最低要求
    min_fraction_of_best_baseline: float = 0.0
    #: 相对判据（套件均值）门槛
    min_mean_fraction_of_best_baseline: float = 0.0
    #: 低于逐场景要求的场景数
    scenarios_below_best_baseline: int = 0
    #: 各场景达成率的最小值（``None`` 表示该组没有任何可比基线的场景）
    worst_capture_ratio: Optional[float] = None
    #: 各场景达成率的均值（``None`` 表示没有可比基线的场景）
    mean_capture_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "functional": self.functional,
            "scenarios_total": self.scenarios_total,
            "scenarios_with_zero_capture": self.scenarios_with_zero_capture,
            "max_captured_energy_kWh": self.max_captured_energy_kWh,
            "max_duty_cycle": self.max_duty_cycle,
            "reason": self.reason,
            "blocking_issue": self.blocking_issue,
            "related_issues": list(self.related_issues),
            "min_fraction_of_best_baseline": self.min_fraction_of_best_baseline,
            "min_mean_fraction_of_best_baseline": self.min_mean_fraction_of_best_baseline,
            "scenarios_below_best_baseline": self.scenarios_below_best_baseline,
            "worst_capture_ratio": self.worst_capture_ratio,
            "mean_capture_ratio": self.mean_capture_ratio,
        }


def _recovered_energy_kwh(metrics: Mapping[str, Any]) -> float:
    """达成率用的「回收能量」：扣除电网回吸后的净再生量。

    2026-11 数据口径更新后，电制动力按机车曲线折算，同一剖面的可再生电量下降，
    储能上限不再必然成为紧约束。此时**从母线回吸电网**的控制器（固定占空比、
    理想上界）会把 ``captured_energy_kWh`` 抬高——那部分不是回收的再生能量。
    实测 s2：``fixed_duty_d1_0.85`` 净存入 2.88 kWh 中 1.67 kWh 来自电网，
    真再生只有 1.20 kWh，反而低于主算法的 1.38 kWh。

    因此优先用 ``storage_net_of_grid_import_energy_kWh``；老记录没有该字段时
    回退到 ``captured_energy_kWh``，保证历史归档仍可对比。
    """

    net = metrics.get("storage_net_of_grid_import_energy_kWh")
    if net is not None:
        return max(float(net), 0.0)
    return float(metrics.get("captured_energy_kWh", 0.0) or 0.0)


def diagnose_optimized_controllers(
    records: Sequence[SuiteRunRecord],
    *,
    optimized_labels: Sequence[str],
    capture_floor_kwh: float = CAPTURE_FLOOR_KWH,
    baseline_labels: Sequence[str] = (),
    min_fraction_of_best_baseline: float = 0.0,
    min_mean_fraction_of_best_baseline: float = 0.0,
) -> Mapping[str, OptimizedDiagnosis]:
    """判断主算法在各场景上是否**真的回收到了能量**。

    为什么需要这一步：阶段 9 最初实测发现主算法在全部场景上回收 0 kWh
    （问题 19/20/21 修正前），与「不控」逐位一致。如果只是把对比表交出去，
    读表的人会看到「优化算法 = 0」，却不知道这是**方案缺口导致的整体不可用**，
    还是"这个场景本来就没能量可回收"。因此把诊断显式写进结果文件。

    判据分两层：

    1. **绝对层** —— ``captured_energy_kWh`` 是否高于 ``capture_floor_kwh``。
       之所以保留这一层，是因为"回收不到能量"本身就已经让该行失去对比意义。
    2. **相对层**（2026-09-25 新增，问题 19/20/21 修正后加入）——
       ``captured_energy_kWh`` 相对**同场景最好基线**的达成率。分两个门槛：

       * ``min_fraction_of_best_baseline``（逐场景）—— 防「某场景静默退化」；
       * ``min_mean_fraction_of_best_baseline``（套件均值）—— 防「每个场景都勉强过线」。

       绝对层太松：修正前主算法只回收 ``0.035 kWh``（最好基线的 ``1/87``），
       "非零"这个门槛会放过"勉强不为零、但工程上完全不可用"的结果。
       相对层要求给出 ``baseline_labels`` 才有意义；未给出（或门槛为 0）时
       自动退化为只查绝对层。基线本身回收能量低于 ``capture_floor_kwh``
       的场景**不参与**相对层（分母近零时比值无意义）。
    """

    baseline_set = set(baseline_labels)
    best_baseline_by_scenario: Dict[str, float] = {}
    if (
        min_fraction_of_best_baseline > 0.0 or min_mean_fraction_of_best_baseline > 0.0
    ) and baseline_set:
        for record in records:
            if record.baseline_label not in baseline_set:
                continue
            value = _recovered_energy_kwh(record.metrics)
            key = record.scenario_label
            if value > best_baseline_by_scenario.get(key, float("-inf")):
                best_baseline_by_scenario[key] = value

    by_label: Dict[str, List[SuiteRunRecord]] = {}
    for record in records:
        if record.baseline_label in optimized_labels:
            by_label.setdefault(record.baseline_label, []).append(record)

    diagnosis: Dict[str, OptimizedDiagnosis] = {}
    for label in optimized_labels:
        group = by_label.get(label, [])
        if not group:
            continue
        captures = [_recovered_energy_kwh(r.metrics) for r in group]
        zeros = sum(1 for value in captures if value <= capture_floor_kwh)
        best = max(captures)
        duty_max = max(
            (
                float(r.metrics.get("duty_saturation_ratio", 0.0) or 0.0)
                for r in group
            ),
            default=0.0,
        )

        ratios: List[float] = []
        below = 0
        # strict=True：captures 由本函数的 group 派生，长度必须相等。
        # 若将来重构让两者错位，宁可在这里炸掉，也不要静默少算几个场景
        # 而让验收审计"看起来通过"。
        if len(group) != len(captures):
            raise ValueError("诊断记录与捕获结果数量不一致")
        for record, value in zip(group, captures):
            reference = best_baseline_by_scenario.get(record.scenario_label)
            if reference is None or reference <= capture_floor_kwh:
                continue
            ratio = value / reference
            ratios.append(ratio)
            if ratio < min_fraction_of_best_baseline:
                below += 1
        worst_ratio = min(ratios) if ratios else None
        mean_ratio = (sum(ratios) / len(ratios)) if ratios else None

        weak_mean = (
            mean_ratio is not None
            and min_mean_fraction_of_best_baseline > 0.0
            and mean_ratio < min_mean_fraction_of_best_baseline
        )
        functional = zeros < len(group) and below == 0 and not weak_mean
        if functional:
            reason = (
                f"{len(group) - zeros}/{len(group)} 个场景回收到能量，"
                f"最好 {best:.4f} kWh"
            )
            if ratios:
                reason += (
                    f"；相对最好基线的达成率 均值 {mean_ratio:.1%}、最低 {worst_ratio:.1%}"
                    f"（门槛 逐场景 {min_fraction_of_best_baseline:.0%} / "
                    f"均值 {min_mean_fraction_of_best_baseline:.0%}）"
                )
            blocking: Optional[int] = None
            related: Tuple[int, ...] = ()
        elif zeros == len(group):
            # 全部场景回收为 0 —— 绝对层就不过，先报绝对层病因（问题 15 曾为真·主阻塞项）
            reason = (
                f"**全部 {len(group)} 个场景回收能量为 0（与「不控」逐位一致）**："
                "方案问题 1（u_eq 定义式缺失）的正式实现 StandardEquivalentControl 依赖"
                "RHONN 的 ∂g/∂u，但方案公式 x̂ = ω^T·φ(x) + ω̄^T·φ(x,u) 里 u 只出现在"
                "**固定权重**项，故 ∂x̂/∂u 与可调权重逐位无关、在线辨识无法校正其符号"
                "（方案问题 15：实测 max|ΔB| = 0.0，12 个种子中 3 个 B 对角全负，符号纯随机）；"
                "又因状态 (v_out, i_out) 经储能母线代数相关，对象的 B 恒为秩 1、det ≡ 0"
                "（方案问题 16）；于是 u_eq 方向被带反，经 PWM 限幅截断为 0。"
                "方案问题 14（控制律 (34)(35) 量纲不一致，‖u_n‖ ≈ 148 ≫ u_0 = 0.9）"
                "使饱和分支恒触发、u_n 被完全丢弃，但它**不是**主阻塞项："
                "改 u_n 的候选（含 u_n ≡ 0）在通道 1 上给出同一结果，四个候选全部回收 0 kWh。"
            )
            blocking = 15
            related = (1, 14, 16)
        elif below > 0:
            # 回收到了能量，但某些场景相对基线明显不足 —— 问题 19/20/21 修正前的典型形态
            reason = (
                f"**部分场景回收能量低于同场景最好基线的 "
                f"{min_fraction_of_best_baseline:.0%}**："
                f"{below}/{len(group)} 个场景未达标，最低达成率 {worst_ratio:.1%}"
                f"（均值 {mean_ratio:.1%}，最好 {best:.4f} kWh）。"
                "主算法虽已回收到非零能量，但在这些场景上相对同口径常值/经典控制基线"
                "明显不足，须复核 u_eq 的可达性与参考量口径（方案问题 19/20/21）。"
            )
            blocking = 20
            related = (19, 21)
        else:
            # 每个场景都过了逐场景门槛，但整体达成率不足
            reason = (
                f"**整体达成率不足**：相对最好基线的均值 {mean_ratio:.1%} "
                f"低于门槛 {min_mean_fraction_of_best_baseline:.0%}"
                f"（最低 {worst_ratio:.1%}，最好 {best:.4f} kWh）。"
                "逐场景未出现退化，但整体明显落后于同口径基线，"
                "须复核参考量口径与等效控制的工作点假设（方案问题 19/20/21）。"
            )
            blocking = 20
            related = (19, 21)
        diagnosis[label] = OptimizedDiagnosis(
            label=label,
            functional=functional,
            scenarios_total=len(group),
            scenarios_with_zero_capture=zeros,
            max_captured_energy_kWh=best,
            max_duty_cycle=duty_max,
            reason=reason,
            blocking_issue=blocking,
            related_issues=related,
            min_fraction_of_best_baseline=min_fraction_of_best_baseline,
            min_mean_fraction_of_best_baseline=min_mean_fraction_of_best_baseline,
            scenarios_below_best_baseline=below,
            worst_capture_ratio=worst_ratio,
            mean_capture_ratio=mean_ratio,
        )
    return diagnosis


def closure_exceedances(
    records: Sequence[SuiteRunRecord],
    *,
    tolerance: float = CLOSURE_RELATIVE_TOLERANCE,
) -> Tuple[Mapping[str, Any], ...]:
    """列出闭合残差超出容差的运行（逐条，不隐藏）。"""

    items = [
        {
            "scenario": record.scenario_label,
            "scenario_family": record.scenario_family,
            "baseline": record.baseline_label,
            "closure_relative_residual": record.closure_relative_residual,
        }
        for record in records
        if record.closure_relative_residual > tolerance
    ]
    return tuple(sorted(items, key=lambda item: -item["closure_relative_residual"]))


def closure_worst_by_family(records: Sequence[SuiteRunRecord]) -> Mapping[str, float]:
    worst: Dict[str, float] = {}
    for record in records:
        current = worst.get(record.scenario_family)
        if current is None or record.closure_relative_residual > current:
            worst[record.scenario_family] = record.closure_relative_residual
    return worst
