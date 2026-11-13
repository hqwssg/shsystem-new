"""共享铁路基础数据 + 本项目专用参数的加载器。

边界（重要）：

* 本模块**只读**共享数据，绝不写回；
* 共享数据里的字段状态（real / assumed / planning_assumption）原样保留，
  不因为"能读到"就当作工程值；
* 缺数据就抛错，不猜、不补、不伪造。
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .data_paths import (
    ProjectPaths,
    ensure_read_only,
    load_project_paths,
    require_shared_data,
)


class DataLoadError(RuntimeError):
    """数据文件缺失或内容不合法。"""


# ------------------------------------------------------------------
# 通用读取工具
# ------------------------------------------------------------------


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise DataLoadError(f"数据文件不存在：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise DataLoadError(f"参数文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise DataLoadError(f"参数文件应为 JSON object：{path}")
    return payload


def _read_csv_rows_from_bytes(blob: bytes, label: str) -> List[Dict[str, str]]:
    """从字节解析 CSV。文件与数据库两条来源共用同一解析。"""

    text = blob.decode("utf-8-sig")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _read_json_from_bytes(blob: bytes, label: str) -> Dict[str, Any]:
    """从字节解析 JSON。"""

    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataLoadError(f"{label} 不是合法的 UTF-8 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise DataLoadError(f"{label} 应为 JSON object")
    return payload


def _to_float(value: Any, field_name: str, allow_none: bool = False) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise DataLoadError(f"字段 {field_name} 缺失数值，实际为 {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DataLoadError(f"字段 {field_name} 无法解析为数值：{value!r}") from exc


# ------------------------------------------------------------------
# 共享铁路基础数据
# ------------------------------------------------------------------


@dataclass(frozen=True)
class SharedStation:
    station_id: str
    name: str
    position_km: float


@dataclass(frozen=True)
class SharedSectionRunTime:
    """官方站间运行时分（``section_run_times.csv`` 的一行）。

    一个 (区间, 方向, 列车档, 量别) 组合一行，量别 ``quantity`` 取
    ``run_time`` / ``start_add`` / ``stop_add``。通通时分保留原表全部分档，
    本算法只消费 ``train_class="20000t"`` 的 ``run_time``。
    """

    start_station: str
    end_station: str
    direction: str
    train_class: str
    quantity: str
    minutes: Optional[float]
    distance_km: Optional[float]
    line_code: str = ""
    source_page: int = 0

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise DataLoadError(f"section_run_times.direction 只能是 up/down，实际 {self.direction!r}")
        if self.quantity not in ("run_time", "start_add", "stop_add"):
            raise DataLoadError(f"section_run_times.quantity 非法：{self.quantity!r}")


@dataclass(frozen=True)
class SharedIntervalRegenReference:
    """实绩区间再生强度（``smart_meter_interval_feedback.csv`` 的一行）。

    由 56 万条「每趟每区间」电表台账聚合而来，``regen_kwh_per_km_p50`` 是本区间
    该重量桶下的**中位**再生强度，用于给仿真结果做量级校核，不是逐趟真值。
    """

    start_station: str
    end_station: str
    direction: str
    weight_bucket: str
    samples: int
    regen_kwh_per_km_p50: float
    regen_kwh_per_km_p90: float
    pure_run_time_min_p50: Optional[float]
    distance_km_p50: float


@dataclass(frozen=True)
class SharedRouteSegment:
    """共享区段几何（真实坡度/平曲线/限速合成结果）。"""

    segment_id: str
    start_km: float
    end_km: float
    gradient_per_mille: float
    curve_radius_m: Optional[float]
    speed_limit_kmh: Optional[float]
    terrain: str = ""

    @property
    def length_m(self) -> float:
        return max(0.0, (self.end_km - self.start_km) * 1000.0)


@dataclass(frozen=True)
class SharedTrainRecord:
    """共享列车参数记录。字段状态原样保留，不做工程化"修正"。

    ``mass_tons`` 的语义是**车辆总重**（不含机车），机车另按
    ``locomotive_type`` / ``locomotive_count`` 追加。这一口径与共享数据
    ``trains.csv`` 的 ``mass_note`` 一致，禁止就地改写 ``mass_tons``。
    """

    name: str
    mass_tons: float
    max_traction_kN: float
    max_brake_kN: float
    rotational_mass_factor: float
    davis_a: float
    davis_b: float
    davis_c: float
    length_km: float
    max_power_kW: float
    mass_data_status: str = ""
    mass_note: str = ""
    locomotive_type: str = ""
    locomotive_count: int = 1
    #: 整列编组，形如 ``SHENHUA_12:1|SHENHUA_8:1``（机型:台数，``|`` 分隔）。
    #: 这是**权威表示**；``locomotive_type`` / ``locomotive_count`` 只描述首型，
    #: 供尚未适配混编的消费方退回使用。为空时整列等同首型 × ``locomotive_count``。
    locomotive_consist: str = ""
    freight_load_state: str = ""

    @property
    def mass_kg(self) -> float:
        """车辆总重（kg），**不含机车**。整备质量请用 ``consist_mass_kg()``。"""

        return self.mass_tons * 1000.0

    def consist_entries(self) -> Tuple[Tuple[str, int], ...]:
        """解析 ``locomotive_consist`` 为 ``((机型, 台数), ...)``。

        空值或退化为「首型 × ``locomotive_count``」时返回单项元组，因此调用方
        可以统一按「多机型求和」处理，不必分两条路径。

        格式错误一律报错而不是忽略：编组解析错一格就会把 8 轴补机悄悄丢掉，
        整备质量与电制动能力同时算小，而仿真照样跑完、不报任何异常。
        """

        raw = (self.locomotive_consist or "").strip()
        if not raw:
            return ((self.locomotive_type, int(self.locomotive_count)),)
        entries = []
        seen = set()
        for chunk in raw.split("|"):
            item = chunk.strip()
            if not item:
                continue
            code, _, count_text = item.partition(":")
            code = code.strip()
            if not code:
                raise DataLoadError(f"编组 {raw!r} 中有空机型名")
            if code in seen:
                raise DataLoadError(f"编组 {raw!r} 中机型 {code!r} 重复出现，请合并台数")
            seen.add(code)
            try:
                count = int(count_text) if count_text.strip() else 1
            except ValueError as exc:
                raise DataLoadError(f"编组 {raw!r} 中 {code!r} 的台数不是整数：{count_text!r}") from exc
            if count < 0:
                raise DataLoadError(f"编组 {raw!r} 中 {code!r} 的台数为负：{count}")
            if count:
                entries.append((code, count))
        if not entries:
            raise DataLoadError(f"编组 {raw!r} 解析后没有任何机车")
        return tuple(entries)


@dataclass(frozen=True)
class SharedLocomotiveCurve:
    """机车特性曲线（来自共享数据 ``locomotive_curves.json``）。

    曲线点的单位保持原文：速度 km/h、制动力 kN、电流 A。换算成 SI 与
    「按台数、按级位折算」一律在使用侧完成，避免在数据层混入口径。
    """

    locomotive_type: str
    computed_mass_t: float
    continuous_power_kW: float
    brake_points_kmh_kn: Tuple[Tuple[float, float], ...] = ()
    regen_current_points_kmh_a: Tuple[Tuple[float, float], ...] = ()
    data_status: str = ""
    source: str = ""
    #: 该机型是否具备再生（回馈）制动能力。``locomotive_curves.json`` 的原生字段：
    #: SS4 系列是电阻制动（regenerative=false，能量转为热量），交流传动机型为 true。
    #: 缺该字段时保持 None（未知），装配侧只在明确为 False 时拒绝。
    regenerative: Optional[bool] = None
    brake_type: str = ""

    def brake_force_kn_at(self, speed_kmh: float) -> float:
        """单台机车在给定速度下的电制动力（kN），按曲线线性插值。

        超出曲线首尾点时取端点值（曲线首点是 0 km/h → 0 kN，尾点是最高
        构造速度），不做外推。
        """

        return _interp_on_points(self.brake_points_kmh_kn, speed_kmh)

    def regen_current_a_at(self, speed_kmh: float) -> float:
        """单台机车在给定速度下的再生发电有功电流（A）。"""

        return _interp_on_points(self.regen_current_points_kmh_a, speed_kmh)


@dataclass(frozen=True)
class RegenEnergyFormula:
    """标准式(72) 的口径参数（``locomotive_curves.json: regen_energy_formula``）。

    这是**独立于「力 × 速度 × 效率」的第二条再生电量路径**：

        Q_z = U_w · Σ(I_z · t_z) / 60      （t_z 以 min 计，Q_z 为 kWh）

    ``I_z`` 是附录 L 的再生电流曲线（按速度查表），``U_w`` 是牵引网电压。
    两条路径互相独立：一条走机械功率与电机效率，一条走标准电流表，
    差异过大说明电制动曲线、电流曲线或效率假设里至少有一处不自洽。

    **``U_w`` 是接触网侧电压，不是本仿真 1500 V 直流母线电压**——两者差约
    18 倍，用错会把校核值算成真值的 5% 左右，而且看不出任何异常。
    """

    u_w_kv: float
    formula: str = ""
    source_section: str = ""
    u_w_data_status: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        value = _to_float(self.u_w_kv, "regen_energy_formula.U_w_kV")
        if not math.isfinite(value) or value <= 0.0:
            raise DataLoadError(f"牵引网电压 U_w 必须为有限正数，实际 {value!r} kV")

    @property
    def u_w_v(self) -> float:
        return self.u_w_kv * 1000.0

    def energy_kwh(self, charge_a_s: float) -> float:
        """按电流对时间积分量（A·s）折算电量：``U_w[kV] × A·s / 3600``。"""

        return self.u_w_kv * charge_a_s / 3600.0


def _interp_on_points(points: Tuple[Tuple[float, float], ...], x: float) -> float:
    """在 (x, y) 点列上做线性插值，端点外取端点值。"""

    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 <= x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def consist_entries_for(
    train: SharedTrainRecord, *, locomotive_count: Optional[int] = None
) -> Tuple[Tuple[str, int], ...]:
    """决定本次装配用哪套编组。

    - 显式传 ``locomotive_count`` → 「``locomotive_type`` × 该台数」的单机型口径，
      用于 1 台 / 2 台情景对比，语义与历史一致；
    - 否则读 ``trains.csv:locomotive_consist``（多机型混编的权威表示）。

    **参数文件不再是台数来源**：``train_parameters.json`` 里的 ``locomotive_count``
    只是共享数据的镜像，混编时它无法表达「12 轴 1 台 + 8 轴 1 台」。
    """

    if locomotive_count is not None:
        count = int(locomotive_count)
        if count < 0:
            raise DataLoadError(f"locomotive_count 不能为负：{count}")
        return ((train.locomotive_type, count),) if count else ()
    return train.consist_entries()


def consist_mass_kg(
    train: SharedTrainRecord,
    locomotives: Mapping[str, SharedLocomotiveCurve],
    *,
    locomotive_count: Optional[int] = None,
) -> float:
    """整备质量 = 车辆总重 + Σ(各机型台数 × 该型自重)。

    单机型时与历史口径完全一致；混编时逐型求和。机型不在曲线表里时抛错——
    静默按 0 处理会把整备质量算小、进而低估制动力需求。
    """

    vehicle_kg = train.mass_kg
    entries = consist_entries_for(train, locomotive_count=locomotive_count)
    if not entries:
        return vehicle_kg
    added = 0.0
    for code, count in entries:
        curve = locomotives.get(code)
        if curve is None:
            raise DataLoadError(
                f"共享数据缺少机型 {code!r} 的机车曲线，无法计算机车自重；"
                f"可用机型：{sorted(locomotives)}"
            )
        added += count * curve.computed_mass_t * 1000.0
    return vehicle_kg + added


def power_cap_w(
    train: SharedTrainRecord,
    *,
    locomotive_count: Optional[int] = None,
    locomotives: Optional[Mapping[str, SharedLocomotiveCurve]] = None,
) -> float:
    """全列功率上限（W）的**唯一来源**。

    - 显式 ``locomotive_count``：``max_power_kW``（单机持续功率）× 台数，历史口径；
    - 编组模式（``locomotive_consist``）：Σ(各机型台数 × 该型 ``continuous_power_kW``)。
      8 轴补机是 9 600 kW 而不是 14 400 kW，用首型的功率乘总台数会把它算大 50%。

    控制侧（电机再生包络）与结算侧（变流器额定）都必须读这里，不得各自
    维护一份常数——两处各算一遍会让能耗被系统性低估。
    """

    if locomotive_count is not None:
        count = int(locomotive_count)
        if count <= 0:
            raise DataLoadError(f"locomotive_count 必须为正才能定功率上限：{count}")
        return float(train.max_power_kW) * 1000.0 * count
    entries = train.consist_entries()
    if len(entries) == 1 and entries[0][0] == train.locomotive_type:
        # 单一机型且就是首型：直接用 trains.csv 的登记值，避免依赖曲线表
        count = entries[0][1]
        if count <= 0:
            raise DataLoadError(f"locomotive_count 必须为正才能定功率上限：{count}")
        return float(train.max_power_kW) * 1000.0 * count
    if locomotives is None:
        raise DataLoadError(
            "编组含多种机型，功率上限需要各机型的 continuous_power_kW；请传入 locomotives"
        )
    total = 0.0
    for code, count in entries:
        curve = locomotives.get(code)
        if curve is None:
            raise DataLoadError(
                f"共享数据缺少机型 {code!r} 的机车曲线，无法定功率上限；"
                f"可用机型：{sorted(locomotives)}"
            )
        if not curve.continuous_power_kW:
            raise DataLoadError(f"机型 {code!r} 缺少 continuous_power_kW，无法定功率上限")
        total += count * curve.continuous_power_kW * 1000.0
    return total


@dataclass(frozen=True)
class CombinedRegenCurve:
    """多机型编组折算成的**全列等效**再生曲线（单台口径，未乘级位）。

    为什么可以合成：电制动力曲线是分片线性的 ``F(v)``，多台同类机车的和仍是
    分片线性；在「所有机型速度点的并集」上逐点求和后再线性插值，与真实分段
    函数之和**逐点相等**，不是近似。电流曲线同理。

    合成后 ``locomotive_count`` 恒为 1——台数已经含在曲线上，再乘一次会把
    8 轴补机算两遍。
    """

    points_kmh_kn: Tuple[Tuple[float, float], ...]
    current_points_kmh_a: Tuple[Tuple[float, float], ...]
    peak_force_kn: float
    mass_t: float
    power_kW: float
    entries: Tuple[Tuple[str, int], ...]
    #: 提供了再生电流表的机型。混编时可能只覆盖一部分（8 轴补机没有附录 L 那类
    #: 电流表），此时合成电流只是**下限**，不是在真值附近波动。
    current_entries: Tuple[Tuple[str, int], ...] = ()
    #: 是否所有机型都提供了再生电流曲线。
    current_complete: bool = True

    @property
    def is_multi_type(self) -> bool:
        return len(self.entries) > 1

    @property
    def current_missing(self) -> Tuple[str, ...]:
        covered = {code for code, _ in self.current_entries}
        return tuple(code for code, _ in self.entries if code not in covered)


def combine_regen_curves(
    entries: Sequence[Tuple[str, int]],
    locomotives: Mapping[str, SharedLocomotiveCurve],
) -> CombinedRegenCurve:
    """把编组折算成全列等效的再生曲线、整备质量与功率上限。

    单机型单台时**原样返回**该机型曲线（不做并集重采样），保证历史读数逐位不变。
    """

    if not entries:
        raise DataLoadError("编组为空，无法折算再生能力")
    picked = []
    for code, count in entries:
        curve = locomotives.get(code)
        if curve is None:
            raise DataLoadError(
                f"共享数据缺少机型 {code!r} 的机车曲线；可用：{sorted(locomotives)}"
            )
        if count <= 0:
            raise DataLoadError(f"机型 {code!r} 的台数必须为正：{count}")
        # 电阻制动不是再生制动：能量在制动电阻上变成热量，不可能回馈。
        # 混编里只要有一台是电阻制动，全列口径就不能按「都是再生」算。
        if curve.regenerative is False:
            raise DataLoadError(
                f"机型 {code!r} 的制动方式为 {curve.brake_type or '电阻制动'}"
                "（regenerative=false），不具备再生（回馈）能力"
            )
        if not curve.brake_points_kmh_kn:
            raise DataLoadError(f"机型 {code!r} 缺少电制动力曲线，无法折算再生能力")
        picked.append((code, count, curve))

    mass_t = sum(count * curve.computed_mass_t for _, count, curve in picked)
    if len(picked) == 1 and picked[0][1] == 1:
        code, _, curve = picked[0]
        has_current = bool(curve.regen_current_points_kmh_a)
        return CombinedRegenCurve(
            points_kmh_kn=curve.brake_points_kmh_kn,
            current_points_kmh_a=curve.regen_current_points_kmh_a,
            peak_force_kn=max(y for _, y in curve.brake_points_kmh_kn),
            mass_t=mass_t,
            power_kW=curve.continuous_power_kW,
            entries=((code, 1),),
            current_entries=((code, 1),) if has_current else (),
            current_complete=has_current,
        )

    speeds = sorted({v for _, _, curve in picked for v, _ in curve.brake_points_kmh_kn})
    points = tuple(
        (speed, sum(count * curve.brake_force_kn_at(speed) for _, count, curve in picked))
        for speed in speeds
    )
    # 电流表按**有数据的机型**求和。缺数据的机型不能按 0 补齐，也不能按同族
    # 比例硬造——前者把结果系统性算小却看不出来，后者是造数。保留已知部分并把
    # 缺口显式写进 status，读到的值就是**下限**。
    covered = [item for item in picked if item[2].regen_current_points_kmh_a]
    current_complete = len(covered) == len(picked)
    currents: Tuple[Tuple[float, float], ...] = ()
    if covered:
        current_speeds = sorted({v for _, _, curve in covered for v, _ in curve.regen_current_points_kmh_a})
        currents = tuple(
            (speed, sum(count * curve.regen_current_a_at(speed) for _, count, curve in covered))
            for speed in current_speeds
        )
    return CombinedRegenCurve(
        points_kmh_kn=points,
        current_points_kmh_a=currents,
        peak_force_kn=max(y for _, y in points),
        mass_t=mass_t,
        power_kW=sum(count * curve.continuous_power_kW for _, count, curve in picked),
        entries=tuple((code, count) for code, count, _ in picked),
        current_entries=tuple((code, count) for code, count, _ in covered),
        current_complete=current_complete,
    )


@dataclass(frozen=True)
class SharedAdhesion:
    default_adhesion_coefficient: float
    traction_adhesion_safety_factor: float
    braking_adhesion_safety_factor: float


@dataclass(frozen=True)
class SharedStorageRecord:
    """共享储能参数（来自 battery.json），保留原始字段状态。"""

    capacity_kwh: float
    round_trip_efficiency: float
    max_charge_power_kW: float
    max_discharge_power_kW: float
    data_status: str
    field_data_status: Mapping[str, str]
    planning_max_discharge_power_assumption_kW: Optional[float] = None
    source_document: str = ""


@dataclass
class SharedRailwayData:
    """共享铁路基础数据的只读视图。"""

    paths: ProjectPaths
    stations: Tuple[SharedStation, ...]
    segments: Tuple[SharedRouteSegment, ...]
    trains: Mapping[str, SharedTrainRecord]
    adhesion: SharedAdhesion
    storage: SharedStorageRecord
    route_metadata: Mapping[str, Any]
    #: 机型 -> 机车曲线（制动/再生电流/自重/持续功率）
    locomotives: Mapping[str, SharedLocomotiveCurve] = field(default_factory=dict)
    #: 标准式(72) 的口径参数（牵引网电压 U_w）；数据里没有时交叉校验不可用，
    #: 由消费方显式标注「不可用」，绝不按 0 或默认值代替
    regen_energy_formula: Optional[RegenEnergyFormula] = None
    #: 官方站间运行时分（PDF 运行图技术资料）。缺失时为空元组。
    section_run_times: Tuple[SharedSectionRunTime, ...] = ()
    #: 实绩区间再生强度（智能电表台账聚合）。缺失时为空元组。
    interval_regen_reference: Tuple[SharedIntervalRegenReference, ...] = ()

    # ---------- 区间参照 ----------
    def official_section(
        self,
        position_km: float,
    ) -> Optional[Tuple[SharedStation, SharedStation]]:
        """返回 ``position_km`` 所在区间的前后站（左闭右开，末站归末区间）。"""

        ordered = sorted(self.stations, key=lambda item: item.position_km)
        for start, end in zip(ordered, ordered[1:]):
            if start.position_km <= position_km < end.position_km:
                return start, end
        if ordered and position_km == ordered[-1].position_km:
            return ordered[-2], ordered[-1]
        return None

    def section_run_time(
        self,
        start_station: str,
        end_station: str,
        *,
        direction: str = "down",
        train_class: str = "20000t",
        quantity: str = "run_time",
    ) -> Optional[float]:
        """查官方时分（min）。无该记录或无值时返回 ``None``，不回落到近似区间。"""

        for row in self.section_run_times:
            if (
                row.start_station == start_station
                and row.end_station == end_station
                and row.direction == direction
                and row.train_class == train_class
                and row.quantity == quantity
            ):
                return row.minutes
        return None

    def interval_regen(
        self,
        start_station: str,
        end_station: str,
        *,
        weight_bucket: str = "ge_20000t",
    ) -> Optional[SharedIntervalRegenReference]:
        """查实绩区间再生强度；找不到返回 ``None``。"""

        for row in self.interval_regen_reference:
            if (
                row.start_station == start_station
                and row.end_station == end_station
                and row.weight_bucket == weight_bucket
            ):
                return row
        return None

    # ---------- 里程查询 ----------
    def segment_at(self, position_km: float) -> Optional[SharedRouteSegment]:
        # 相邻区段在边界共点；按左闭右开归给新段。线路终点仍归末段。
        for index, segment in enumerate(self.segments):
            if segment.start_km <= position_km < segment.end_km:
                return segment
            if index == len(self.segments) - 1 and position_km == segment.end_km:
                return segment
        return None

    def gradient_per_mille_at(self, position_km: float) -> float:
        segment = self.segment_at(position_km)
        return segment.gradient_per_mille if segment else 0.0

    def curve_radius_at(self, position_km: float) -> Optional[float]:
        segment = self.segment_at(position_km)
        return segment.curve_radius_m if segment else None

    def speed_limit_kmh_at(self, position_km: float) -> Optional[float]:
        segment = self.segment_at(position_km)
        return segment.speed_limit_kmh if segment else None

    def total_length_km(self) -> float:
        route = self.route_metadata.get("route") or {}
        value = route.get("total_length_km")
        if isinstance(value, (int, float)):
            return float(value)
        return max((s.end_km for s in self.segments), default=0.0)


def validate_route_segments(segments: Sequence[SharedRouteSegment]) -> Tuple[SharedRouteSegment, ...]:
    """校验区段几何连续性，拒绝异常、缺段和重叠数据。

    区段采用左闭右开语义，因此相邻区段必须满足
    ``previous.end_km == current.start_km``。允许任意有效的限速突变，
    因为限速是分段属性而不是连续性约束。
    """

    ordered = tuple(sorted(segments, key=lambda item: (item.start_km, item.end_km, item.segment_id)))
    if not ordered:
        raise DataLoadError("segments 不能为空")

    seen_ids = set()
    for segment in ordered:
        if not segment.segment_id:
            raise DataLoadError("segments.segment_id 不能为空")
        if segment.segment_id in seen_ids:
            raise DataLoadError(f"segments 存在重复 segment_id：{segment.segment_id}")
        seen_ids.add(segment.segment_id)
        numeric_values = (
            ("start_km", segment.start_km),
            ("end_km", segment.end_km),
            ("gradient_per_mille", segment.gradient_per_mille),
        )
        for field_name, value in numeric_values:
            if not math.isfinite(value):
                raise DataLoadError(f"segments.{field_name} 必须为有限数值：{value!r}")
        if segment.curve_radius_m is not None and not math.isfinite(segment.curve_radius_m):
            raise DataLoadError(f"segments.curve_radius_m 必须为有限数值：{segment.curve_radius_m!r}")
        if segment.speed_limit_kmh is not None:
            if not math.isfinite(segment.speed_limit_kmh) or segment.speed_limit_kmh <= 0.0:
                raise DataLoadError(f"segments.speed_limit_kmh 必须为正有限数值：{segment.speed_limit_kmh!r}")
        if segment.start_km >= segment.end_km:
            raise DataLoadError(
                f"segments 区间必须满足 start_km < end_km：{segment.segment_id}"
            )

    tolerance = 1e-9
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_km < previous.end_km - tolerance:
            raise DataLoadError(
                f"segments 存在重叠或重复区段：{previous.segment_id} / {current.segment_id}"
            )
        if current.start_km > previous.end_km + tolerance:
            raise DataLoadError(
                f"segments 存在缺段：{previous.end_km:g} 至 {current.start_km:g} km"
            )
    return ordered


#: 解析共享铁路数据所需的最小文件集（文件模式与数据库模式一致）
SHARED_PARSE_FILES: tuple = (
    "stations.csv",
    "segments.csv",
    "trains.csv",
    "operating_conditions.json",
    "battery.json",
    "route_metadata.json",
    "locomotive_curves.json",
)

#: 可选共享文件：存在就加载、缺失不影响历史口径。
#:
#: 2026-11-07 新接入的两份真实数据。放成可选而不是必需，是因为它们晚于
#: 既有数据集加入：强制必需会让缺件的旧工作副本直接加载失败，而它们对
#: 主算法读数**没有**影响（只用于区间级参考校核）。
OPTIONAL_SHARED_FILES: tuple = (
    "section_run_times.csv",
    "smart_meter_interval_feedback.csv",
)


def build_shared_railway_data(
    files: Mapping[str, bytes],
    paths: "ProjectPaths",
    *,
    source: str = "file",
) -> SharedRailwayData:
    """从文件字节解析共享铁路数据。

    `files` 的键为文件名（如 ``stations.csv``）。文件读取与数据库读取都走这里，
    保证两条来源的解析规则、校验顺序、错误信息完全一致。
    """

    missing = [name for name in SHARED_PARSE_FILES if name not in files]
    if missing:
        raise DataLoadError(f"共享数据缺少解析所需文件（来源：{source}）：{missing}")

    def rows(name: str) -> List[Dict[str, str]]:
        return _read_csv_rows_from_bytes(files[name], f"{source}:{name}")

    def payload(name: str) -> Dict[str, Any]:
        return _read_json_from_bytes(files[name], f"{source}:{name}")

    stations = tuple(
        SharedStation(
            station_id=row.get("station_id", ""),
            name=row.get("name", ""),
            position_km=_to_float(row.get("position_km"), "stations.position_km"),
        )
        for row in rows("stations.csv")
    )

    segments = []
    for row in rows("segments.csv"):
        segments.append(
            SharedRouteSegment(
                segment_id=row.get("segment_id", ""),
                start_km=_to_float(row.get("start_km"), "segments.start_km"),
                end_km=_to_float(row.get("end_km"), "segments.end_km"),
                gradient_per_mille=_to_float(row.get("gradient_per_mille", 0.0), "segments.gradient_per_mille"),
                curve_radius_m=_to_float(row.get("curve_radius_m"), "segments.curve_radius_m", allow_none=True),
                speed_limit_kmh=_to_float(row.get("speed_limit_kmh"), "segments.speed_limit_kmh", allow_none=True),
                terrain=row.get("terrain", "") or "",
            )
        )
    segments = list(validate_route_segments(segments))

    trains: Dict[str, SharedTrainRecord] = {}
    for row in rows("trains.csv"):
        record = SharedTrainRecord(
            name=row.get("name", ""),
            mass_tons=_to_float(row.get("mass_tons"), "trains.mass_tons"),
            max_traction_kN=_to_float(row.get("max_traction_kN"), "trains.max_traction_kN"),
            max_brake_kN=_to_float(row.get("max_brake_kN"), "trains.max_brake_kN"),
            rotational_mass_factor=_to_float(row.get("rotational_mass_factor", 1.0), "trains.rotational_mass_factor"),
            davis_a=_to_float(row.get("davis_a", 0.0), "trains.davis_a"),
            davis_b=_to_float(row.get("davis_b", 0.0), "trains.davis_b"),
            davis_c=_to_float(row.get("davis_c", 0.0), "trains.davis_c"),
            length_km=_to_float(row.get("length_km", 0.0), "trains.length_km"),
            max_power_kW=_to_float(row.get("max_power_kW", 0.0), "trains.max_power_kW"),
            mass_data_status=row.get("mass_data_status", "") or "",
            mass_note=row.get("mass_note", "") or "",
            locomotive_type=(row.get("locomotive_type", "") or "").strip(),
            locomotive_count=int(
                _to_float(row.get("locomotive_count", 1.0), "trains.locomotive_count")
            ),
            locomotive_consist=(row.get("locomotive_consist", "") or "").strip(),
            freight_load_state=row.get("freight_load_state", "") or "",
        )
        trains[record.name] = record

    locomotives = _parse_locomotive_curves(payload("locomotive_curves.json"))
    regen_formula = _parse_regen_energy_formula(payload("locomotive_curves.json"))

    conditions = payload("operating_conditions.json")
    adhesion = SharedAdhesion(
        default_adhesion_coefficient=_to_float(
            conditions.get("default_adhesion_coefficient"), "operating_conditions.default_adhesion_coefficient"
        ),
        traction_adhesion_safety_factor=_to_float(
            conditions.get("traction_adhesion_safety_factor"), "operating_conditions.traction_adhesion_safety_factor"
        ),
        braking_adhesion_safety_factor=_to_float(
            conditions.get("braking_adhesion_safety_factor"), "operating_conditions.braking_adhesion_safety_factor"
        ),
    )

    battery = payload("battery.json")
    storage = SharedStorageRecord(
        capacity_kwh=_to_float(battery.get("capacity_kwh"), "battery.capacity_kwh"),
        round_trip_efficiency=_to_float(battery.get("round_trip_efficiency"), "battery.round_trip_efficiency"),
        max_charge_power_kW=_to_float(battery.get("max_charge_power_kW"), "battery.max_charge_power_kW"),
        max_discharge_power_kW=_to_float(battery.get("max_discharge_power_kW"), "battery.max_discharge_power_kW"),
        data_status=str(battery.get("data_status", "")),
        field_data_status=dict(battery.get("field_data_status") or {}),
        planning_max_discharge_power_assumption_kW=_to_float(
            battery.get("planning_max_discharge_power_assumption_kW"),
            "battery.planning_max_discharge_power_assumption_kW",
            allow_none=True,
        ),
        source_document=str(battery.get("source_document", "")),
    )

    route_metadata = payload("route_metadata.json")

    section_run_times = _parse_section_run_times(files.get("section_run_times.csv"), source)
    interval_regen = _parse_interval_regen(files.get("smart_meter_interval_feedback.csv"), source)

    return SharedRailwayData(
        paths=paths,
        stations=stations,
        segments=tuple(segments),
        trains=trains,
        adhesion=adhesion,
        storage=storage,
        route_metadata=route_metadata,
        locomotives=locomotives,
        regen_energy_formula=regen_formula,
        section_run_times=section_run_times,
        interval_regen_reference=interval_regen,
    )


def _optional_rows(raw: Optional[bytes], name: str, source: str) -> List[Dict[str, str]]:
    if raw is None:
        return []
    return _read_csv_rows_from_bytes(raw, f"{source}:{name}")


def _parse_section_run_times(raw: Optional[bytes], source: str) -> Tuple[SharedSectionRunTime, ...]:
    """解析官方站间时分（可选文件，缺失返回空元组）。"""

    rows = []
    for row in _optional_rows(raw, "section_run_times.csv", source):
        start = (row.get("start_station") or "").strip()
        end = (row.get("end_station") or "").strip()
        minutes_raw = (row.get("minutes") or "").strip()
        minutes = _to_float(minutes_raw, "section_run_times.minutes") if minutes_raw else None
        distance_raw = (row.get("distance_km") or "").strip()
        distance = _to_float(distance_raw, "section_run_times.distance_km") if distance_raw else None
        rows.append(
            SharedSectionRunTime(
                start_station=start,
                end_station=end,
                direction=(row.get("direction") or "").strip(),
                train_class=(row.get("train_class") or "").strip(),
                quantity=(row.get("quantity") or "").strip(),
                minutes=minutes,
                distance_km=distance,
                line_code=(row.get("line_code") or "").strip(),
                source_page=int(row.get("source_page") or 0),
            )
        )
    return tuple(rows)


def _parse_interval_regen(raw: Optional[bytes], source: str) -> Tuple[SharedIntervalRegenReference, ...]:
    """解析实绩区间再生强度（可选文件，缺失返回空元组）。"""

    rows = []
    for row in _optional_rows(raw, "smart_meter_interval_feedback.csv", source):
        time_raw = (row.get("pure_run_time_min_p50") or "").strip()
        rows.append(
            SharedIntervalRegenReference(
                start_station=(row.get("start_station") or "").strip(),
                end_station=(row.get("end_station") or "").strip(),
                direction=(row.get("direction") or "").strip(),
                weight_bucket=(row.get("weight_bucket") or "").strip(),
                samples=int(float(row.get("samples") or 0)),
                regen_kwh_per_km_p50=_to_float(
                    row.get("regen_kwh_per_km_p50"), "smart_meter.regen_kwh_per_km_p50"
                ),
                regen_kwh_per_km_p90=_to_float(
                    row.get("regen_kwh_per_km_p90"), "smart_meter.regen_kwh_per_km_p90"
                ),
                pure_run_time_min_p50=_to_float(time_raw, "smart_meter.pure_run_time_min_p50") if time_raw else None,
                distance_km_p50=_to_float(row.get("distance_km_p50"), "smart_meter.distance_km_p50"),
            )
        )
    return tuple(rows)


def _parse_regen_energy_formula(raw: Mapping[str, Any]) -> Optional[RegenEnergyFormula]:
    """解析标准式(72) 的 ``U_w``。

    块不存在时返回 ``None``（交叉校验不可用，消费方必须显式标注）；块存在但
    ``U_w_kV`` 缺失或非正数时**报错**——这是"数据在、但读不懂"，不能悄悄降级成
    不可用，否则两条路径的差异会以"没数据"的名义被掩盖。
    """

    block = raw.get("regen_energy_formula")
    if not isinstance(block, Mapping):
        return None
    return RegenEnergyFormula(
        u_w_kv=_to_float(block.get("U_w_kV"), "locomotive_curves.regen_energy_formula.U_w_kV"),
        formula=str(block.get("formula", "") or ""),
        source_section=str(block.get("source_section", "") or ""),
        u_w_data_status=str(block.get("U_w_data_status", "") or ""),
        note=str(block.get("U_w_note", "") or ""),
    )


def _parse_locomotive_curves(raw: Mapping[str, Any]) -> Dict[str, SharedLocomotiveCurve]:
    """解析 ``locomotive_curves.json``。

    只取本项目用得到的量：自重、持续功率、电制动曲线、再生电流曲线。曲线点
    按速度升序排列，重复速度保留先出现的点（原文有时插入说明行）。
    """

    models = raw.get("locomotives") or {}
    if not isinstance(models, Mapping):
        raise DataLoadError("locomotive_curves.json 的 locomotives 应为对象")

    parsed: Dict[str, SharedLocomotiveCurve] = {}
    for name, entry in models.items():
        if not isinstance(entry, Mapping):
            continue
        params = entry.get("params") or {}
        computed_mass_t = params.get("computed_mass_t")
        if computed_mass_t is None:
            # 没有自重的机型无法参与整备质量计算，但仍保留曲线供其他用途
            computed_mass_t = 0.0
        brake_points = _curve_points(
            (entry.get("brake_curve") or {}).get("points"), "v", "Bd"
        )
        current_points = _curve_points(
            (entry.get("regen_current_curve") or {}).get("points"), "v", "I"
        )
        parsed[str(name)] = SharedLocomotiveCurve(
            locomotive_type=str(name),
            computed_mass_t=_to_float(computed_mass_t, f"locomotive_curves.{name}.computed_mass_t"),
            continuous_power_kW=_to_float(
                params.get("continuous_power_kW", 0.0),
                f"locomotive_curves.{name}.continuous_power_kW",
            ),
            brake_points_kmh_kn=brake_points,
            regen_current_points_kmh_a=current_points,
            data_status=str(entry.get("data_status", "") or ""),
            source=str(entry.get("alias", "") or ""),
            regenerative=(
                None if entry.get("regenerative") is None else bool(entry.get("regenerative"))
            ),
            brake_type=str(entry.get("brake_type", "") or ""),
        )
    return parsed


def _curve_points(
    points: Any, x_key: str, y_key: str
) -> Tuple[Tuple[float, float], ...]:
    """把曲线点列表解析为按 x 升序的 (x, y) 元组。"""

    if not isinstance(points, (list, tuple)):
        return ()
    cleaned: List[Tuple[float, float]] = []
    seen: set = set()
    for item in points:
        if not isinstance(item, Mapping):
            continue
        x = item.get(x_key)
        y = item.get(y_key)
        if x is None or y is None:
            continue
        xf = float(x)
        if xf in seen:
            continue
        seen.add(xf)
        cleaned.append((xf, float(y)))
    cleaned.sort(key=lambda pair: pair[0])
    return tuple(cleaned)


def load_shared_railway_data(
    paths: Optional[ProjectPaths] = None,
    check_required: bool = True,
) -> SharedRailwayData:
    """从共享数据目录加载铁路基础数据（只读）。"""

    paths = paths or load_project_paths()
    if check_required:
        require_shared_data(paths)
    files = {name: paths.shared_file(name).read_bytes() for name in SHARED_PARSE_FILES}
    # 可选文件：缺失不报错（它们是后加的区间级参考数据，不影响主算法口径）。
    for name in OPTIONAL_SHARED_FILES:
        candidate = paths.shared_file(name)
        if candidate.is_file():
            files[name] = candidate.read_bytes()
    return build_shared_railway_data(files, paths, source="file")


def find_long_downhill_ranges(
    data: SharedRailwayData,
    max_gradient_per_mille: float = -6.0,
    min_length_km: float = 1.0,
) -> List[Tuple[float, float]]:
    """识别长大下坡区段（再生制动潜力区）。

    判据完全来自共享真实坡度数据，不含任何虚拟区间。
    """

    ranges: List[Tuple[float, float]] = []
    start: Optional[float] = None
    end: Optional[float] = None
    for segment in data.segments:
        if segment.gradient_per_mille <= max_gradient_per_mille:
            if start is None:
                start = segment.start_km
            end = segment.end_km
        else:
            if start is not None and end is not None and (end - start) >= min_length_km:
                ranges.append((start, end))
            start, end = None, None
    if start is not None and end is not None and (end - start) >= min_length_km:
        ranges.append((start, end))
    return ranges


# ------------------------------------------------------------------
# 本项目专用参数
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterFile:
    """带数据状态标记的参数文件包装。"""

    payload: Mapping[str, Any]
    path: Path

    @property
    def data_status(self) -> str:
        return str(self.payload.get("data_status", "unknown"))

    @property
    def field_data_status(self) -> Mapping[str, str]:
        raw = self.payload.get("field_data_status") or {}
        return dict(raw) if isinstance(raw, Mapping) else {}

    def require(self, key: str) -> Any:
        if key not in self.payload:
            raise DataLoadError(f"{self.path.name} 缺少必需字段 {key}")
        return self.payload[key]

    def optional(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


def load_single_train_parameters(
    name: str,
    paths: Optional[ProjectPaths] = None,
) -> ParameterFile:
    """加载本项目专用参数文件。

    name: train_parameters / motor_parameters / dc_dc_parameters / storage_parameters
    """

    paths = paths or load_project_paths()
    path = paths.single_train_data_root / f"{name}.json"
    return ParameterFile(payload=_read_json(path), path=path)


def assert_not_writing_to_shared(paths: ProjectPaths, target: Path) -> None:
    """对外暴露的写入保护入口。"""

    ensure_read_only(paths, target)


def load_data_manifest(paths: Optional[ProjectPaths] = None) -> Mapping[str, Any]:
    """读取 data_manifest.yaml（供校验脚本使用）。"""

    import yaml

    paths = paths or load_project_paths()
    if not paths.data_manifest_path.is_file():
        raise DataLoadError(f"数据清单不存在：{paths.data_manifest_path}")
    with paths.data_manifest_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, Mapping):
        raise DataLoadError(f"数据清单格式错误：{paths.data_manifest_path}")
    return payload


def find_contested_assumption(
    key: str, paths: Optional[ProjectPaths] = None
) -> Optional[Mapping[str, Any]]:
    """按 id 取 data_manifest 里「口径争议」登记的一条。

    争议条目不是数据输入，读不到时**返回 None**，由调用方显式标注
    「未登记」，不得假装口径已明确。
    """

    try:
        manifest = load_data_manifest(paths)
    except DataLoadError:
        return None
    entries = manifest.get("contested_assumptions") or []
    if not isinstance(entries, (list, tuple)):
        return None
    for entry in entries:
        if isinstance(entry, Mapping) and str(entry.get("id", "")) == key:
            return entry
    return None


def iter_manifest_entries(manifest: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """展平 data_manifest.yaml 的三类条目，附带 section 标记。"""

    flat: List[Mapping[str, Any]] = []
    for section in ("shared", "single_train", "missing"):
        entries = manifest.get(section) or []
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                enriched = dict(entry)
                enriched["_section"] = section
                flat.append(enriched)
    return flat
