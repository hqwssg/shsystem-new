"""阶段 11：与重空协同项目（``heavy_empty_train_coordination``）的导出接口。

边界纪律
--------
依据 ``docs/data_sharing_boundary.md`` §9 与 ``docs/technical_scheme_code_mapping.md`` §D：

    只允许导出**基础事实数据**（时间桶、速度、坡度、曲线半径、限速、SOC、能量桶）；
    **禁止**导出**算法内部状态**（RHONN 权重、EKF/UKF 协方差、滑模面、模式切换原因、
    占空比、母线纹波、跟踪误差）。

本模块用**三道闸**把这个纪律变成可执行的代码约束，而不是靠自觉：

1. **字段白名单（allow-list）**——导出行的键必须**全部**落在
   :data:`SHARED_FACT_COLUMNS` 内。多一个键就报错，**不静默丢弃**：
   静默丢弃会让"忘了导"和"故意不导"无法区分，而这两件事的审计含义完全不同。
2. **元数据键名哨兵**——导出 payload 的键名（递归）不得命中
   :data:`FORBIDDEN_INTERNAL_TOKENS`。只扫**键名**不扫值，是刻意的：
   要防的是"把内部状态当成一个字段导出去"，而 ``source_controller="rhonn_nsmc"``
   这类**溯源标识**不是内部状态，不应被误伤。为让这条规则真正闭环，
   payload 内**不设自由文本字段**（没有 notes），值只有数值、标识符与固定免责声明。
3. **路径越界检查**——目标目录落在共享数据根、或落在重空协同项目目录内，一律报错。
   注意这一步**不依赖** ``shared_data_read_only`` 开关：即使有人把开关关掉，
   本项目也绝不写入重空协同项目的任何文件（边界文档 §1 第 4 条）。

落点
----
按边界文档 §9，导出物落在**本项目**的 ``experiments_root`` 下（形如
``data/experiments/<run_id>/cross_project/``），由重空协同项目**只读消费**；
本项目不往对方目录写任何东西。

.. warning::
   桶汇总基于**抽样记录**（每 ``record_stride`` 步一条），不是逐步累加。
   因此"桶合计"与能量台账的合计存在抽样差异，**不得用于闭合校验**——
   闭合校验请用 ``metrics.EnergyLedger`` 的全步台账。
   本模块把抽样间隔 ``sample_interval_s`` 写进元数据，让消费方能自行判断粒度。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .data_paths import DataPathError, ProjectPaths, ensure_read_only

# ---------------------------------------------------------------------------
# 常量：白名单 / 黑名单 / 版本
# ---------------------------------------------------------------------------

#: 重空协同项目目录名（用于路径越界检查）
COORDINATION_PROJECT_DIRNAME = "heavy_empty_train_coordination"

#: 白名单版本。任何增删列都必须同步 +1，否则消费方无法判断口径是否变了。
FIELD_WHITELIST_VERSION = "1.0"

#: 导出物类别标识（写进 payload，供消费方校验）
EXPORT_KIND = "cross_project_energy_buckets"

#: 导出 schema 版本
EXPORT_SCHEMA_VERSION = "1.0"

CROSS_PROJECT_DISCLAIMER = (
    "仿真结果，不作为工程结论 —— "
    "本导出由单列车再生制动仿真得到，电力电子与储能参数当前包含占位或假设值，"
    "未经硬件资料或实测数据确认，不得作为工程结论使用。"
    "导出内容仅限基础事实数据与按时间桶汇总的能量，不含任何算法内部状态。"
)

#: 允许出现在导出行里的列（**白名单**，不是黑名单）。
#:
#: 判定口径（边界文档 §1）：这一列是不是"线路 / 列车 / 供电客观事实"，
#: 或是"该客观事实上的能量汇总"？是 → 允许；不是（是某套算法的中间状态）→ 不允许。
SHARED_FACT_COLUMNS: Tuple[str, ...] = (
    # ---- 时间桶骨架 ----
    "bucket_index",
    "t_start_s",
    "t_end_s",
    "covered_duration_s",
    "sample_count",
    "is_partial",
    # ---- 客观事实：运动与线路 ----
    "distance_m",
    "speed_mean_m_per_s",
    "speed_min_m_per_s",
    "speed_max_m_per_s",
    "gradient_per_mille",
    "curve_radius_m",
    "speed_limit_kmh",
    # ---- 客观事实：储能状态 ----
    "soc_start",
    "soc_end",
    "soc_min",
    "soc_max",
    # ---- 能量桶 ----
    "mechanical_braking_energy_kWh",
    "available_regenerative_energy_kWh",
    "captured_energy_kWh",
    "curtailed_energy_kWh",
    "grid_export_energy_kWh",
    "grid_import_energy_kWh",
)

#: 元数据键名中禁止出现的片段（算法内部状态）。
#:
#: 只做**子串**匹配且只扫键名，因此每一条都必须足够特异，避免误伤客观字段
#: （例如不收录 "gradient"——它在铁路语境里是"坡度"，是允许导出的客观事实）。
FORBIDDEN_INTERNAL_TOKENS: Tuple[str, ...] = (
    "rhonn",
    "neural",
    "weight",
    "covariance",
    "kalman",
    "ekf",
    "ukf",
    "sliding",
    "sigma",
    "duty",
    "switch_count",
    "mode_switch",
    "final_mode",
    "jacobian",
    "ripple",
    "tracking",
    "rmse",
    "control_effort",
    "derivative",
    "adaptive_law",
)


class CrossProjectExportError(RuntimeError):
    """跨项目导出被边界纪律拒绝，或导出输入不合法。"""


# ---------------------------------------------------------------------------
# 时间桶规格与列定义
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeBucketSpec:
    """时间桶规格。

    Args:
        bucket_seconds: 桶宽（s）。样本按 ``floor(t / bucket_seconds)`` 归桶。
        require_full: True 时丢弃末尾不满一桶的残段（默认保留并标 ``is_partial``）。
    """

    bucket_seconds: float = 1.0
    require_full: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.bucket_seconds) or self.bucket_seconds <= 0.0:
            raise CrossProjectExportError(
                f"bucket_seconds 必须为正有限值，实际为 {self.bucket_seconds!r}"
            )


#: 允许的聚合方式
REDUCERS: Tuple[str, ...] = ("mean", "min", "max", "first", "last", "integral")


@dataclass(frozen=True)
class BucketColumn:
    """一列的来源与聚合方式。

    Args:
        name: 导出列名，**必须**在 :data:`SHARED_FACT_COLUMNS` 内。
        source: 逐步记录里的键名（对应 ``SimulationArrays`` 或派生数组）。
        reduce: 见 :data:`REDUCERS`。
        scale: 聚合后乘以的系数（如 J→kWh 用 ``1/3.6e6``）。
        required: True 时源数组缺失即报错；False 时该列整体跳过
            （用于"限速资料可能缺失"这类客观事实列）。
    """

    name: str
    source: str
    reduce: str
    scale: float = 1.0
    required: bool = True

    def __post_init__(self) -> None:
        if self.name not in SHARED_FACT_COLUMNS:
            raise CrossProjectExportError(
                f"列 {self.name!r} 不在共享事实白名单内。"
                f"允许的列见 SHARED_FACT_COLUMNS（白名单版本 {FIELD_WHITELIST_VERSION}）。"
            )
        if self.reduce not in REDUCERS:
            raise CrossProjectExportError(
                f"未知聚合方式 {self.reduce!r}，允许：{', '.join(REDUCERS)}"
            )
        if not math.isfinite(self.scale):
            raise CrossProjectExportError(f"scale 必须有限，实际为 {self.scale!r}")


_J_PER_KWH = 1.0 / 3.6e6


def default_bucket_columns() -> Tuple[BucketColumn, ...]:
    """本项目默认的桶列定义（白名单的一个子集）。"""

    return (
        BucketColumn("distance_m", "speed_mps", "integral"),
        BucketColumn("speed_mean_m_per_s", "speed_mps", "mean"),
        BucketColumn("speed_min_m_per_s", "speed_mps", "min"),
        BucketColumn("speed_max_m_per_s", "speed_mps", "max"),
        BucketColumn("gradient_per_mille", "gradient_per_mille", "mean", required=False),
        BucketColumn("curve_radius_m", "curve_radius_m", "mean", required=False),
        BucketColumn("speed_limit_kmh", "speed_limit_kmh", "mean", required=False),
        BucketColumn("soc_start", "soc", "first"),
        BucketColumn("soc_end", "soc", "last"),
        BucketColumn("soc_min", "soc", "min"),
        BucketColumn("soc_max", "soc", "max"),
        BucketColumn(
            "mechanical_braking_energy_kWh",
            "mechanical_braking_power_w",
            "integral",
            scale=_J_PER_KWH,
        ),
        BucketColumn(
            "available_regenerative_energy_kWh",
            "motor_electrical_power_w",
            "integral",
            scale=_J_PER_KWH,
        ),
        BucketColumn("captured_energy_kWh", "accepted_power_w", "integral", scale=_J_PER_KWH),
        BucketColumn("curtailed_energy_kWh", "curtailed_power_w", "integral", scale=_J_PER_KWH),
        BucketColumn("grid_export_energy_kWh", "grid_export_power_w", "integral", scale=_J_PER_KWH),
        BucketColumn("grid_import_energy_kWh", "grid_import_power_w", "integral", scale=_J_PER_KWH),
    )


#: 桶骨架列（由分桶机制自己填，不由 :class:`BucketColumn` 提供）
BUCKET_SKELETON_COLUMNS: Tuple[str, ...] = (
    "bucket_index",
    "t_start_s",
    "t_end_s",
    "covered_duration_s",
    "sample_count",
    "is_partial",
)


# ---------------------------------------------------------------------------
# 分桶
# ---------------------------------------------------------------------------


def _uniform_interval(time_s: np.ndarray) -> float:
    if time_s.size < 2:
        raise CrossProjectExportError(
            f"时间轴至少需要 2 个样本才能确定抽样间隔，实际 {time_s.size} 个。"
            "单点运行不构成可导出的时间桶。"
        )
    deltas = np.diff(time_s)
    interval = float(deltas[0])
    if not math.isfinite(interval) or interval <= 0.0:
        raise CrossProjectExportError(f"时间轴必须严格递增，实际首个间隔 {interval!r}")
    if not np.allclose(deltas, interval, rtol=1e-6, atol=1e-12):
        worst = float(np.max(np.abs(deltas - interval)))
        raise CrossProjectExportError(
            "时间轴必须等间隔（导出按矩形法累加，等间隔是前提）。"
            f"首个间隔 {interval!r}，最大偏差 {worst!r}。"
        )
    return interval


def _reduce_numeric(
    values: np.ndarray, how: str, interval_s: float, scale: float
) -> Optional[float]:
    """单列聚合。全为缺失值（NaN）时返回 None（如实表达"该桶没有资料"）。"""

    if how == "integral":
        if not np.all(np.isfinite(values)):
            bad = int(np.sum(~np.isfinite(values)))
            raise CrossProjectExportError(
                f"积分列含 {bad} 个非有限值，拒绝静默按 0 处理（会污染能量桶）。"
            )
        return float(np.sum(values)) * interval_s * scale

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    if how == "mean":
        raw = float(np.mean(finite))
    elif how == "min":
        raw = float(np.min(finite))
    elif how == "max":
        raw = float(np.max(finite))
    elif how == "first":
        raw = float(finite[0])
    elif how == "last":
        raw = float(finite[-1])
    else:  # pragma: no cover - BucketColumn 已在构造期校验
        raise CrossProjectExportError(f"未知聚合方式 {how!r}")
    return raw * scale


def bucket_series(
    time_s: Sequence[float],
    series: Mapping[str, Sequence[float]],
    columns: Sequence[BucketColumn],
    spec: TimeBucketSpec,
) -> Tuple[Mapping[str, Any], ...]:
    """把逐步记录按时间桶汇总。

    Args:
        time_s: 等间隔时间轴（s）。
        series: 逐步记录，键为列来源名；缺失的 ``required=False`` 列会被跳过。
        columns: 列定义。
        spec: 桶规格。

    Returns:
        每个桶一个 mapping，键为 ``BUCKET_SKELETON_COLUMNS`` ∪ 实际生效的列名。
    """

    t = np.asarray(time_s, dtype=float)
    if t.ndim != 1 or t.size == 0:
        raise CrossProjectExportError("time_s 必须是非空一维序列")
    if not np.all(np.isfinite(t)):
        raise CrossProjectExportError("time_s 含非有限值")
    if np.any(np.diff(t) <= 0.0):
        raise CrossProjectExportError("time_s 必须严格递增")

    interval = _uniform_interval(t)

    if spec.bucket_seconds < interval - 1e-12:
        raise CrossProjectExportError(
            f"bucket_seconds={spec.bucket_seconds!r} 小于抽样间隔 {interval!r}，"
            "分桶没有意义（每桶不足一个样本）。"
        )

    arrays: Dict[str, np.ndarray] = {}
    for column in columns:
        if column.source in arrays:
            continue
        if column.source not in series:
            if column.required:
                raise CrossProjectExportError(
                    f"列 {column.name!r} 需要逐步记录 {column.source!r}，但输入里没有。"
                    f"可用的键：{', '.join(sorted(series))}"
                )
            continue
        array = np.asarray(series[column.source], dtype=float)
        if array.ndim != 1 or array.size != t.size:
            raise CrossProjectExportError(
                f"逐步记录 {column.source!r} 长度 {array.size} 与时间轴 {t.size} 不一致"
            )
        arrays[column.source] = array

    active: List[BucketColumn] = [c for c in columns if c.source in arrays]

    indices = np.floor(t / spec.bucket_seconds + 1e-9).astype(int)
    rows: List[Mapping[str, Any]] = []
    for bucket_index in np.unique(indices):
        mask = indices == bucket_index
        count = int(np.sum(mask))
        covered = count * interval
        is_partial = covered < spec.bucket_seconds - 1e-9
        if spec.require_full and is_partial:
            continue
        row: Dict[str, Any] = {
            "bucket_index": int(bucket_index),
            "t_start_s": float(bucket_index) * spec.bucket_seconds,
            "t_end_s": float(bucket_index) * spec.bucket_seconds + covered,
            "covered_duration_s": covered,
            "sample_count": count,
            "is_partial": is_partial,
        }
        for column in active:
            row[column.name] = _reduce_numeric(
                arrays[column.source][mask], column.reduce, interval, column.scale
            )
        rows.append(row)
    return tuple(rows)


# ---------------------------------------------------------------------------
# 导出 payload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossProjectExport:
    """一份跨项目导出物。"""

    source_run_id: str
    source_scenario: str
    bucket_seconds: float
    sample_interval_s: float
    columns: Tuple[str, ...]
    buckets: Tuple[Mapping[str, Any], ...]
    parameter_data_status: Mapping[str, str] = field(default_factory=dict)
    data_status: str = "simulation_result_not_engineering_conclusion"
    export_kind: str = EXPORT_KIND
    schema_version: str = EXPORT_SCHEMA_VERSION
    field_whitelist_version: str = FIELD_WHITELIST_VERSION
    disclaimer: str = CROSS_PROJECT_DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "export_kind": self.export_kind,
            "schema_version": self.schema_version,
            "field_whitelist_version": self.field_whitelist_version,
            "source_run_id": self.source_run_id,
            "source_scenario": self.source_scenario,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "bucket_seconds": self.bucket_seconds,
            "sample_interval_s": self.sample_interval_s,
            "bucket_count": len(self.buckets),
            "columns": list(self.columns),
            "parameter_data_status": dict(self.parameter_data_status),
            "shared_data_read_only": True,
            "buckets": [dict(row) for row in self.buckets],
        }


def _scan_forbidden_keys(node: Any, path: str, hits: List[str]) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            lowered = key_text.lower()
            for token in FORBIDDEN_INTERNAL_TOKENS:
                if token in lowered:
                    hits.append(f"{path}.{key_text} ← 命中禁止片段 {token!r}")
            _scan_forbidden_keys(value, f"{path}.{key_text}", hits)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _scan_forbidden_keys(value, f"{path}[{index}]", hits)


def validate_export_payload(payload: Mapping[str, Any]) -> None:
    """导出前校验：白名单 + 元数据键名哨兵。不合法即报错，不静默修补。"""

    if not isinstance(payload, Mapping):
        raise CrossProjectExportError(f"导出 payload 必须是 mapping，实际 {type(payload)!r}")

    hits: List[str] = []
    _scan_forbidden_keys(payload, "export", hits)
    if hits:
        raise CrossProjectExportError(
            "导出 payload 出现疑似算法内部状态的字段（边界文档 §9 禁止导出）：\n  "
            + "\n  ".join(hits)
        )

    columns = payload.get("columns")
    if not isinstance(columns, (list, tuple)):
        raise CrossProjectExportError("导出 payload 缺少 columns 列表")
    illegal = [str(name) for name in columns if name not in SHARED_FACT_COLUMNS]
    if illegal:
        raise CrossProjectExportError(
            "导出列超出共享事实白名单："
            + ", ".join(sorted(illegal))
            + f"\n允许的列见 SHARED_FACT_COLUMNS（白名单版本 {FIELD_WHITELIST_VERSION}）。"
        )

    buckets = payload.get("buckets")
    if not isinstance(buckets, (list, tuple)):
        raise CrossProjectExportError("导出 payload 缺少 buckets 列表")
    for index, row in enumerate(buckets):
        if not isinstance(row, Mapping):
            raise CrossProjectExportError(f"第 {index} 个桶不是 mapping，实际 {type(row)!r}")
        extra = [str(key) for key in row if key not in SHARED_FACT_COLUMNS]
        if extra:
            raise CrossProjectExportError(
                f"第 {index} 个桶出现白名单外的列：{', '.join(sorted(extra))}"
            )
        missing = [name for name in columns if name not in row]
        if missing:
            raise CrossProjectExportError(
                f"第 {index} 个桶缺少声明过的列：{', '.join(sorted(missing))}"
            )


def build_cross_project_export(
    result: Any,
    *,
    bucket_spec: TimeBucketSpec,
    source_run_id: str,
    profile: Optional[Any] = None,
    parameter_data_status: Optional[Mapping[str, str]] = None,
    columns: Optional[Sequence[BucketColumn]] = None,
) -> CrossProjectExport:
    """由一次 ``SimulationResult``（可选带 ``ProfileSeries``）构造导出物。

    ``profile`` 提供线路客观事实（坡度 / 曲线半径 / 限速）。剖面采样间隔与记录
    采样间隔不同，因此这里按 **最近邻** 重采样到记录时间轴
    （``index = round(t / profile.dt)``）——记录时间轴恰为 ``profile.dt`` 的整数倍，
    所以该重采样是精确的，不是插值近似。
    """

    arrays = getattr(result, "arrays", None)
    config = getattr(result, "config", None)
    if arrays is None or config is None:
        raise CrossProjectExportError("result 必须带有 arrays 与 config（SimulationResult）")

    time_s = np.asarray(arrays.time_s, dtype=float)
    interval = float(config.dt) * int(config.record_stride)

    series: Dict[str, np.ndarray] = {
        "speed_mps": np.asarray(arrays.speed_mps, dtype=float),
        "soc": np.asarray(arrays.soc, dtype=float),
        "mechanical_braking_power_w": np.asarray(arrays.mechanical_braking_power_w, dtype=float),
        "motor_electrical_power_w": np.asarray(arrays.motor_electrical_power_w, dtype=float),
        "accepted_power_w": np.asarray(arrays.accepted_power_w, dtype=float),
        "curtailed_power_w": np.asarray(arrays.curtailed_power_w, dtype=float),
        "grid_export_power_w": np.asarray(arrays.grid_export_power_w, dtype=float),
        "grid_import_power_w": np.asarray(arrays.grid_import_power_w, dtype=float),
    }

    if profile is not None:
        samples = tuple(profile.samples)
        if not samples:
            raise CrossProjectExportError("profile.samples 为空，无法导出线路客观事实")
        profile_dt = float(profile.dt)
        indices = np.clip(
            np.round(time_s / profile_dt).astype(int), 0, len(samples) - 1
        )
        series["gradient_per_mille"] = np.array(
            [float(samples[i].gradient_per_mille) for i in indices], dtype=float
        )
        series["curve_radius_m"] = np.array(
            [
                float(samples[i].curve_radius_m)
                if samples[i].curve_radius_m is not None
                else math.nan
                for i in indices
            ],
            dtype=float,
        )
        series["speed_limit_kmh"] = np.array(
            [
                float(samples[i].speed_limit_mps) * 3.6
                if samples[i].speed_limit_mps is not None
                else math.nan
                for i in indices
            ],
            dtype=float,
        )

    active_columns = tuple(columns) if columns is not None else default_bucket_columns()
    rows = bucket_series(time_s, series, active_columns, bucket_spec)

    emitted: List[str] = list(BUCKET_SKELETON_COLUMNS)
    for column in active_columns:
        if column.source in series and column.name not in emitted:
            emitted.append(column.name)

    export = CrossProjectExport(
        source_run_id=str(source_run_id),
        source_scenario=str(getattr(result, "scenario_id", "")),
        bucket_seconds=float(bucket_spec.bucket_seconds),
        sample_interval_s=interval,
        columns=tuple(emitted),
        buckets=rows,
        parameter_data_status=dict(parameter_data_status or {}),
    )
    validate_export_payload(export.to_dict())
    return export


# ---------------------------------------------------------------------------
# 路径越界检查与落盘
# ---------------------------------------------------------------------------


def coordination_project_roots(paths: ProjectPaths) -> Tuple[Path, ...]:
    """返回禁止写入的目录集合（共享数据根 + 重空协同项目根）。

    两条独立线索，取并集，避免任何一条失效就失去保护：

    * 从 ``shared_data_root`` 向上找名为 ``heavy_empty_train_coordination`` 的目录；
    * 本项目根目录的同级目录 ``../heavy_empty_train_coordination``（若存在）。
    """

    roots: List[Path] = [paths.shared_data_root.resolve()]

    shared = paths.shared_data_root.resolve()
    for candidate in (shared, *shared.parents):
        if candidate.name == COORDINATION_PROJECT_DIRNAME:
            roots.append(candidate)
            break

    sibling = (paths.project_root.resolve().parent / COORDINATION_PROJECT_DIRNAME)
    if sibling.is_dir():
        roots.append(sibling.resolve())

    unique: List[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def assert_export_target_allowed(paths: ProjectPaths, target: Path) -> Path:
    """确认导出目标不在任何"他人领地"内。

    与 :func:`io.data_paths.ensure_read_only` 的区别：本函数**不依赖**
    ``shared_data_read_only`` 开关。边界文档 §1 第 4 条是硬约束
    （本项目不写入重空协同项目任何文件），不能被一个配置项关掉。
    """

    resolved = Path(target).resolve()
    for root in coordination_project_roots(paths):
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        raise CrossProjectExportError(
            "拒绝写入重空协同项目的目录（边界文档 §1 第 4 条）："
            f"{resolved}\n命中禁写根：{root}\n"
            f"请把导出写到本项目 experiments_root = {paths.experiments_root}"
        )
    return resolved


def write_cross_project_export(
    export: CrossProjectExport,
    target_dir: Path,
    *,
    paths: ProjectPaths,
    stem: str = "energy_buckets",
) -> Mapping[str, Path]:
    """落盘：``<stem>.csv`` + ``<stem>.json``。

    顺序刻意如此——**先校验 payload，再校验路径，最后才 mkdir**：
    任何一步不过都不应留下半个目录。
    """

    payload = export.to_dict()
    validate_export_payload(payload)

    resolved_dir = assert_export_target_allowed(paths, target_dir)
    try:
        ensure_read_only(paths, resolved_dir)
    except DataPathError as exc:  # pragma: no cover - 已由上一行覆盖，保留双保险
        raise CrossProjectExportError(str(exc)) from exc

    resolved_dir.mkdir(parents=True, exist_ok=True)

    csv_path = resolved_dir / f"{stem}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(export.columns), extrasaction="raise")
        writer.writeheader()
        for row in export.buckets:
            writer.writerow(
                {
                    key: ("" if row.get(key) is None else row.get(key))
                    for key in export.columns
                }
            )

    json_path = resolved_dir / f"{stem}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)

    return {"csv": csv_path, "json": json_path}


def export_result_to_directory(
    result: Any,
    target_dir: Path,
    *,
    paths: ProjectPaths,
    bucket_spec: TimeBucketSpec,
    source_run_id: str,
    profile: Optional[Any] = None,
    parameter_data_status: Optional[Mapping[str, str]] = None,
    stem: str = "energy_buckets",
) -> Tuple[CrossProjectExport, Mapping[str, Path]]:
    """便捷入口：构造 + 落盘。"""

    export = build_cross_project_export(
        result,
        bucket_spec=bucket_spec,
        source_run_id=source_run_id,
        profile=profile,
        parameter_data_status=parameter_data_status,
    )
    written = write_cross_project_export(export, target_dir, paths=paths, stem=stem)
    return export, written
