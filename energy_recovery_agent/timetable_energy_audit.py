# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import argparse
import csv
import json
import math
import warnings

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - 是否可用取决于运行环境。
    plt = None
    MATPLOTLIB_IMPORT_ERROR = str(exc)
else:
    MATPLOTLIB_IMPORT_ERROR = ""


# 报告图表使用中文标题和标签，需要显式选择支持中文的字体，否则会渲染成方框。
REPORT_CJK_FONTS = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
)


def _configure_report_font() -> None:
    """为报告图表选择可用的中文字体，并保持负号正常显示。"""
    if plt is None:
        return
    try:
        from matplotlib import font_manager

        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:  # pragma: no cover - 字体清单不可用时不应阻断报告生成。
        available = set()
    families = [name for name in REPORT_CJK_FONTS if name in available]
    if families:
        plt.rcParams["font.sans-serif"] = families + [
            name for name in plt.rcParams.get("font.sans-serif", []) if name not in families
        ]
        plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False

try:
    import openpyxl
except ImportError:  # pragma: no cover - 供电臂 XLSX 支持为可选功能。
    openpyxl = None

from timetable_input import (
    CanonicalTimetable,
    TimetableScenario,
    TimetableStop,
    TimetableTrain,
    format_s_as_hhmmss,
    load_canonical_timetable,
    timetable_arc_rows,
    timetable_node_rows,
)
from heavy_empty_network_optimizer import (
    HeArc,
    HeNode,
    InfrastructureProfile,
    ServiceType,
    energy_time_slice_rows,
    load_infrastructure_profile,
    _build_running_arc_segments,
)
from power_arm_electrical_limits import (
    PowerArmElectricalLimit,
    SHUOHUANG_DIRECT_USE_ENABLED,
    electrical_limit_fields,
    limit_for_power_arm,
    load_power_arm_electrical_limits,
    power_arm_electrical_limit_from_row,
    time_window_capacity_kwh,
)
from energy_settlement import (
    EnergyBucketRequest,
    EnergyBucketSettlement,
    enabled_storage_section_id,
    initialize_storage_settlement_state,
    power_arm_limit_is_explicit,
    settle_energy_bucket_group,
    storage_no_direct_effective_loss_kwh,
    storage_section_ids_from_limits,
)
from data_ingestion import load_storage_device_parameters
from train_simulator import StorageDeviceParameters


DEFAULT_OUTPUT_DIR = Path("outputs") / "timetable_energy_audit"
DEFAULT_POWER_ARM_XLSX = Path("data") / "real_shuohuang" / "power_arm_intervals.csv"
DEFAULT_ENERGY_ZONE_CSV = Path("data") / "real_shuohuang" / "energy_transfer_zones.csv"
DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_DOWNHILL_RANGE_KM = (62.0, 302.0)
DIRECT_MATCH_WINDOW_S = 15 * 60
# 正式运行图能量评价使用批准的 10 秒时间桶。旧输入缺少场景行时，回退值也必须遵守该契约，
# 不能扩大为粗粒度的 15 分钟时间桶。
DEFAULT_SETTLEMENT_STEP_S = 10
DEFAULT_STORAGE_EFFICIENCY = 0.9
ELECTRICAL_CONSTRAINT_TOLERANCE_KWH = 1e-9


REPORT_FIGURE_LABELS = {
    "timetable_profile": "运行图时空剖面",
    "scenario_energy_comparison": "场景能量对比",
    "power_arm_energy_timeline": "供电臂结算时间线",
    "top_power_arm_energy": "供电臂能耗排名",
}

REPORT_SCENARIO_LABELS = {
    "storage_no_direct": "储能（无直接利用）",
    "partial_route": "部分线路",
    "device_soc_imbalance": "设备荷电状态不平衡",
    "electrical_limit_probe": "电气限制探测",
    "formal_ten_second_graph": "正式十秒时间图",
}


def _report_yes_no(value: object) -> str:
    """将报告中的布尔状态转换为中文显示文本。"""
    return "是" if bool(value) else "否"


def _report_assessment(value: object) -> str:
    """将内部评价代码转换为中文显示文本，内部接口值保持不变。"""
    return {
        "reasonable": "合理",
        "needs_optimization": "需要优化",
    }.get(str(value), str(value))


def _report_scenario_label(value: object) -> str:
    """将场景内部编码转换为报告中的中文显示名。"""
    scenario_id = str(value)
    return REPORT_SCENARIO_LABELS.get(scenario_id, scenario_id)


REPORT_ISSUE_TYPE_LABELS = {
    "regen_without_traction_same_window": "同窗内无牵引需求",
    "regen_unusable_by_scenario": "场景未启用任何利用路径",
    "section_without_storage": "供电臂未接入储能",
    "storage_capacity_or_power_limit": "储能容量或充电功率不足",
    "regen_exceeds_traction_same_window": "同窗再生电量大于牵引需求",
    "traction_supply_capacity_exceeded": "牵引供电能力超限",
    "regen_absorption_capacity_exceeded": "再生吸收能力超限",
    "regeneration_unusable": "再生电量无可用利用路径",
    "no_matching_traction_window": "无同供电范围牵引需求",
    "storage_limit": "储能容量或充电功率不足",
    "regeneration_leftover": "仍有剩余再生电量",
}

REPORT_SEVERITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

REPORT_LOCATION_LABELS = {
    "unknown_power_section": "未知供电臂",
}

# 报告只展示影响最大的若干条问题与建议，完整清单仍在 CSV 中。
REPORT_ISSUE_PREVIEW_LIMIT = 20


def _report_issue_type_label(value: object) -> str:
    """将问题类型内部编码转换为报告中的中文显示名。"""
    issue_type = str(value)
    return REPORT_ISSUE_TYPE_LABELS.get(issue_type, issue_type)


def _report_severity_label(value: object) -> str:
    """将严重程度/优先级内部编码转换为报告中的中文显示名。"""
    severity = str(value)
    return REPORT_SEVERITY_LABELS.get(severity, severity)


def _report_issue_location(row: Dict[str, object]) -> Tuple[str, str]:
    """提取问题或建议的位置与时间窗，兼容时间片口径和能量事件口径的记录。"""
    location = str(row.get("power_arm_id") or row.get("section_id") or "")
    location = REPORT_LOCATION_LABELS.get(location, location)
    start = str(row.get("time_window_start") or row.get("start_time") or "")
    end = str(row.get("time_window_end") or row.get("end_time") or "")
    window = f"{start}—{end}" if (start or end) else ""
    return location, window


def _report_cell(value: object) -> str:
    """转义 Markdown 表格单元格中的竖线，避免破坏表格结构。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _report_issue_digest(issue_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """按“问题类型 + 供电臂/区段”合并问题，返回按影响电量降序的统计清单。

    审查明细按 10 秒结算时间窗逐条记录，直接罗列会淹没真实瓶颈；报告需要的是
    “哪类问题、发生在哪个供电臂、影响多大、持续多久”。
    """
    grouped: Dict[Tuple[str, str], Dict[str, object]] = {}
    for row in issue_rows:
        location, window = _report_issue_location(row)
        issue_type = str(row.get("issue_type", ""))
        key = (issue_type, location)
        item = grouped.get(key)
        if item is None:
            item = {
                "issue_type": issue_type,
                "location": location,
                "issue_count": 0,
                "impact_kwh": 0.0,
                "severity": str(row.get("severity", "")),
                "reason": str(row.get("reason", "")),
                "start": "",
                "end": "",
            }
            grouped[key] = item
        item["issue_count"] = int(item["issue_count"]) + 1
        item["impact_kwh"] = float(item["impact_kwh"]) + _as_float(row.get("estimated_wasted_kwh", 0.0))
        if _SEVERITY_RANK.get(str(row.get("severity", "")), 0) > _SEVERITY_RANK.get(str(item["severity"]), 0):
            item["severity"] = str(row.get("severity", ""))
        if window:
            start, _, end = window.partition("—")
            if not item["start"] or start < str(item["start"]):
                item["start"] = start
            if not item["end"] or end > str(item["end"]):
                item["end"] = end
    return sorted(grouped.values(), key=lambda item: float(item["impact_kwh"]), reverse=True)


def _report_suggestion_digest(suggestion_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """按“关联问题类型 + 建议动作”合并优化建议，返回按条数降序的统计清单。"""
    grouped: Dict[Tuple[str, str], Dict[str, object]] = {}
    for row in suggestion_rows:
        action = str(row.get("action", ""))
        issue_type = str(row.get("source_issue_type", ""))
        key = (issue_type, action)
        item = grouped.get(key)
        if item is None:
            item = {
                "source_issue_type": issue_type,
                "action": action,
                "expected_effect": str(row.get("expected_effect", "")),
                "priority": str(row.get("priority", "")),
                "suggestion_count": 0,
            }
            grouped[key] = item
        item["suggestion_count"] = int(item["suggestion_count"]) + 1
        if _SEVERITY_RANK.get(str(row.get("priority", "")), 0) > _SEVERITY_RANK.get(str(item["priority"]), 0):
            item["priority"] = str(row.get("priority", ""))
    return sorted(
        grouped.values(),
        key=lambda item: (int(item["suggestion_count"]), _SEVERITY_RANK.get(str(item["priority"]), 0)),
        reverse=True,
    )


def load_storage_efficiency(data_dir: Path = DEFAULT_DATA_DIR) -> float:
    """Load the configured battery round-trip efficiency for a data set.

    Older callers may provide an infrastructure-only directory without a
    battery file, so that case keeps the historical 0.9 fallback.  When a
    battery file is present, however, malformed or out-of-range values must
    fail loudly rather than silently changing the energy ranking.  Zero is
    accepted because the shared battery/data contracts use it to represent a
    disabled or unavailable storage device; settlement then correctly stores
    no usable energy.
    """
    device_path = Path(data_dir) / "storage_devices.json"
    if device_path.is_file():
        devices = load_storage_device_parameters(data_dir)
        total_capacity = sum(item.capacity_kwh for item in devices)
        return sum(
            item.capacity_kwh * item.charge_efficiency * item.discharge_efficiency
            for item in devices
        ) / total_capacity
    battery_path = Path(data_dir) / "battery.json"
    if not battery_path.exists():
        return DEFAULT_STORAGE_EFFICIENCY
    try:
        payload = json.loads(battery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Battery data could not be loaded from {battery_path}: {exc}") from exc
    if not isinstance(payload, dict) or "round_trip_efficiency" not in payload:
        raise ValueError(f"Battery data {battery_path} requires round_trip_efficiency")
    value = payload["round_trip_efficiency"]
    if isinstance(value, bool):
        raise ValueError(f"round_trip_efficiency must be finite and in [0, 1], got {value!r}")
    try:
        efficiency = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"round_trip_efficiency must be finite and in [0, 1], got {value!r}") from exc
    if not math.isfinite(efficiency) or not 0.0 <= efficiency <= 1.0:
        raise ValueError(f"round_trip_efficiency must be finite and in [0, 1], got {value!r}")
    return efficiency


@dataclass(frozen=True)
class PowerSection:
    """类 PowerSection：执行该模块中的相关处理逻辑。"""
    section_id: str
    name: str
    direction: str
    start_km: float
    end_km: float
    source: str
    needs_manual_review: bool = False
    boundary_policy: str = "power_arm_interval"
    electrical_limit: PowerArmElectricalLimit = PowerArmElectricalLimit()

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        section_id = str(self.section_id).strip()
        if not section_id:
            raise ValueError("power section_id must not be empty")
        if isinstance(self.start_km, bool) or isinstance(self.end_km, bool):
            raise ValueError("power section bounds must be finite")
        try:
            start_km = float(self.start_km)
            end_km = float(self.end_km)
        except (TypeError, ValueError) as exc:
            raise ValueError("power section bounds must be finite") from exc
        if not math.isfinite(start_km) or not math.isfinite(end_km):
            raise ValueError("power section bounds must be finite")
        if math.isclose(start_km, end_km, abs_tol=1e-12):
            raise ValueError("power section bounds must be distinct")
        if type(self.needs_manual_review) is not bool:
            raise ValueError("power section needs_manual_review must be a boolean")
        direction = _normalized_power_direction(self.direction)
        if not direction:
            direction = "unknown"
        object.__setattr__(self, "section_id", section_id)
        object.__setattr__(self, "start_km", start_km)
        object.__setattr__(self, "end_km", end_km)
        object.__setattr__(self, "direction", direction)

    @property
    def min_km(self) -> float:
        """函数 min_km：执行该模块中的相关处理逻辑。"""
        return min(self.start_km, self.end_km)

    @property
    def max_km(self) -> float:
        """函数 max_km：执行该模块中的相关处理逻辑。"""
        return max(self.start_km, self.end_km)


@dataclass(frozen=True)
class EnergyEvent:
    """类 EnergyEvent：执行该模块中的相关处理逻辑。"""
    event_id: str
    train_id: str
    train_type: str
    direction: str
    event_type: str
    start_time_s: int
    end_time_s: int
    start_km: float
    end_km: float
    section_id: str
    estimated_energy_kwh: float
    confidence: str
    basis: str


@dataclass(frozen=True)
class SplitArcSegment:
    """类 SplitArcSegment：执行该模块中的相关处理逻辑。"""
    start_km: float
    end_km: float
    start_time_s: int
    end_time_s: int
    section_id: str
    section_source: str
    confidence_note: str


@dataclass(frozen=True)
class TimetableArcCandidate:
    """类 TimetableArcCandidate：执行该模块中的相关处理逻辑。"""
    candidate_id: str
    arcs: Tuple[HeArc, ...]


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    return str(value).strip()


def _float(value: Any, default: float = 0.0) -> float:
    """函数 _float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return default
    if isinstance(value, bool):
        raise ValueError(f"value must be finite, got {value!r}")
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value must be finite, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"value must be finite, got {value!r}")
    return number


def _bool(value: Any) -> bool:
    """函数 _bool：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "是", "需复核", "需要复核", "缺失"}:
        return True
    if text in {"", "0", "false", "no", "n", "否", "无需复核", "已有"}:
        return False
    raise ValueError(f"value must be a recognized boolean, got {value!r}")


def _is_mainline_road(row: Dict[str, Any]) -> bool:
    """函数 _is_mainline_road：执行该模块中的相关处理逻辑。"""
    road = _clean(row.get("road") or row.get("line")).lower()
    return not road or road in {"朔黄线", "shuohuang"}


def _normalized_power_direction(value: Any) -> str:
    """函数 _normalized_power_direction：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"forward", "down", "downbound", "下行"}:
        return "forward"
    if text in {"reverse", "up", "upbound", "上行"}:
        return "reverse"
    if text in {"both", "single", "shared", "单线", "双向"}:
        return "both"
    return "" if not text else "unknown"


def _overlap_len(a0: float, a1: float, b0: float, b1: float) -> float:
    """函数 _overlap_len：执行该模块中的相关处理逻辑。"""
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return max(0.0, hi - lo)


def _time_overlap_s(a0: int, a1: int, b0: int, b1: int) -> int:
    """函数 _time_overlap_s：执行该模块中的相关处理逻辑。"""
    return max(0, min(a1, b1) - max(a0, b0))


def _midpoint_km(start_km: float, end_km: float) -> float:
    """函数 _midpoint_km：执行该模块中的相关处理逻辑。"""
    return (float(start_km) + float(end_km)) / 2.0


def load_power_sections(power_arm_xlsx: Path = DEFAULT_POWER_ARM_XLSX, fallback_csv: Path = DEFAULT_ENERGY_ZONE_CSV) -> List[PowerSection]:
    """函数 load_power_sections：执行该模块中的相关处理逻辑。"""
    sections: List[PowerSection] = []
    if power_arm_xlsx.exists() and power_arm_xlsx.suffix.lower() == ".csv":
        with power_arm_xlsx.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                section_id = _clean(row.get("section_id"))
                if not section_id:
                    continue
                if not _is_mainline_road(row):
                    continue
                start_km = _float(row.get("start_km"), math.nan)
                end_km = _float(row.get("end_km"), math.nan)
                if not math.isfinite(start_km) or not math.isfinite(end_km):
                    raise ValueError(f"Power section {section_id!r} requires finite start_km/end_km")
                sections.append(
                    PowerSection(
                        section_id=section_id,
                        name=_clean(row.get("power_arm_id")) or _clean(row.get("traction_substation_raw")),
                        direction=_clean(row.get("direction")) or "unknown",
                        start_km=start_km,
                        end_km=end_km,
                        source=str(power_arm_xlsx),
                        needs_manual_review=_bool(row.get("needs_manual_review")),
                        boundary_policy="continuous_power_arm_interval",
                        electrical_limit=power_arm_electrical_limit_from_row(row),
                    )
                )
    if sections:
        return sections

    if power_arm_xlsx.exists() and openpyxl is not None:
        workbook = openpyxl.load_workbook(power_arm_xlsx, data_only=True)
        target_sheet = None
        for sheet in workbook.worksheets:
            headers = [_clean(sheet.cell(1, col).value) for col in range(1, sheet.max_column + 1)]
            if {"section_id", "start_km", "end_km"}.issubset(set(headers)):
                target_sheet = sheet
                break
        if target_sheet is not None:
            headers = [_clean(target_sheet.cell(1, col).value) for col in range(1, target_sheet.max_column + 1)]
            for row_idx in range(2, target_sheet.max_row + 1):
                row = {headers[col_idx]: target_sheet.cell(row_idx, col_idx + 1).value for col_idx in range(len(headers))}
                if not _clean(row.get("section_id")):
                    continue
                if not _is_mainline_road(row):
                    continue
                start_km = _float(row.get("start_km"), math.nan)
                end_km = _float(row.get("end_km"), math.nan)
                if not math.isfinite(start_km) or not math.isfinite(end_km):
                    raise ValueError(
                        f"Power section {_clean(row.get('section_id'))!r} requires finite start_km/end_km"
                    )
                sections.append(
                    PowerSection(
                        section_id=_clean(row.get("section_id")),
                        name=_clean(row.get("power_arm_id")) or _clean(row.get("traction_substation_raw")),
                        direction=_clean(row.get("direction")) or "unknown",
                        start_km=start_km,
                        end_km=end_km,
                        source=str(power_arm_xlsx),
                        needs_manual_review=_bool(row.get("needs_manual_review")),
                        boundary_policy="continuous_power_arm_interval",
                        electrical_limit=power_arm_electrical_limit_from_row(row),
                    )
                )
    if sections:
        return sections

    # energy_transfer_zones.csv 是储能规划几何预设，不能替代供电臂区间表。
    # 必需的供电臂表缺失或为空时不能静默回退，调用方必须按保守原则失败。
    _ = fallback_csv  # 保留该参数以兼容既有函数签名。
    return sections


def load_phase_boundary_points(power_arm_xlsx: Path = DEFAULT_POWER_ARM_XLSX) -> List[float]:
    """Load neutral-section center mileages as non-crossable power boundaries.

    Confirmed modeling rule: electric phase separation is a de-energized
    boundary. Use the center mileage as the dispatch/energy settlement split
    point until exact start/end dead-zone modeling is required.
    """

    if not power_arm_xlsx.exists():
        return []
    if power_arm_xlsx.suffix.lower() == ".csv":
        points: set[float] = set()
        with power_arm_xlsx.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if not _is_mainline_road(row):
                    continue
                for key in ("start_km", "end_km"):
                    km = _float(row.get(key), math.nan)
                    if math.isfinite(km):
                        points.add(round(km, 6))
        return sorted(points)
    if openpyxl is None:
        return []
    workbook = openpyxl.load_workbook(power_arm_xlsx, data_only=True)
    points: set[float] = set()
    for sheet in workbook.worksheets:
        headers = [_clean(sheet.cell(1, col).value) for col in range(1, sheet.max_column + 1)]
        if "center_km" not in headers:
            continue
        for row_idx in range(2, sheet.max_row + 1):
            row = {headers[col_idx]: sheet.cell(row_idx, col_idx + 1).value for col_idx in range(len(headers))}
            if not _is_mainline_road(row):
                continue
            center = _float(row.get("center_km"), math.nan)
            if math.isfinite(center):
                points.add(round(center, 6))
    return sorted(points)


def find_power_section(
    sections: List[PowerSection],
    start_km: float,
    end_km: float,
    model_direction: str = "",
) -> Optional[PowerSection]:
    """函数 find_power_section：执行该模块中的相关处理逻辑。"""
    expected_direction = _normalized_power_direction(model_direction) if model_direction else ""
    candidates = [
        section
        for section in sections
        if not expected_direction or section.direction in {expected_direction, "both", ""}
    ]
    if not candidates:
        return None
    midpoint = _midpoint_km(start_km, end_km)
    containing = [section for section in candidates if section.min_km <= midpoint <= section.max_km]
    if containing:
        return max(containing, key=lambda section: section.max_km - section.min_km)
    best = max(candidates, key=lambda section: _overlap_len(start_km, end_km, section.start_km, section.end_km))
    overlap_km = _overlap_len(start_km, end_km, best.start_km, best.end_km)
    arc_len_km = abs(end_km - start_km)
    if overlap_km <= 0 or arc_len_km <= 0:
        return None
    # 较长的用户弧段可能跨越多个供电臂；除非重叠比例足够大，不能把它归给很小的中性区记录。
    return best if overlap_km / arc_len_km >= 0.25 else None


def _power_boundary_points(
    sections: List[PowerSection],
    phase_boundary_points: Optional[List[float]] = None,
    model_direction: str = "",
) -> List[float]:
    """函数 _power_boundary_points：执行该模块中的相关处理逻辑。"""
    points = set()
    expected_direction = _normalized_power_direction(model_direction) if model_direction else ""
    for section in sections:
        if expected_direction and section.direction not in {expected_direction, "both", ""}:
            continue
        if math.isfinite(section.min_km):
            points.add(round(section.min_km, 6))
        if math.isfinite(section.max_km):
            points.add(round(section.max_km, 6))
    for point in phase_boundary_points or []:
        if math.isfinite(point):
            points.add(round(point, 6))
    return sorted(points)


def _section_id_for_split(
    sections: List[PowerSection],
    start_km: float,
    end_km: float,
    boundary_points: List[float],
    model_direction: str = "",
) -> Tuple[str, str, str]:
    """函数 _section_id_for_split：执行该模块中的相关处理逻辑。"""
    section = find_power_section(sections, start_km, end_km, model_direction)
    if section is not None:
        note = " Power section is assigned after power-boundary splitting."
        if section.needs_manual_review:
            note += " Source record needs manual review."
        return section.section_id, section.source, note

    midpoint = _midpoint_km(start_km, end_km)
    lower = [point for point in boundary_points if point <= midpoint]
    upper = [point for point in boundary_points if point >= midpoint]
    if lower and upper:
        left = max(lower)
        right = min(upper)
        if left < right:
            section_id = f"inferred_power_arm:K{left:.3f}-K{right:.3f}"
            return (
                section_id,
                "inferred_from_power_arm_boundaries",
                " Power arm is inferred from adjacent boundary mileages; confirm against official supply-arm table.",
            )
    return "unknown_power_section", "", " No power section boundary matched this split segment."


def split_running_arc_by_power_boundaries(
    start_km: float,
    end_km: float,
    start_time_s: int,
    end_time_s: int,
    sections: List[PowerSection],
    phase_boundary_points: Optional[List[float]] = None,
    model_direction: str = "",
) -> List[SplitArcSegment]:
    """函数 split_running_arc_by_power_boundaries：执行该模块中的相关处理逻辑。"""
    distance_km = abs(end_km - start_km)
    duration_s = end_time_s - start_time_s
    if distance_km <= 0 or duration_s <= 0:
        return []

    lo = min(start_km, end_km)
    hi = max(start_km, end_km)
    boundary_points = _power_boundary_points(sections, phase_boundary_points, model_direction)
    cut_points = {round(start_km, 6), round(end_km, 6)}
    for point in boundary_points:
        if lo < point < hi:
            cut_points.add(round(point, 6))

    ordered = sorted(cut_points, reverse=start_km > end_km)
    segments: List[SplitArcSegment] = []
    for idx in range(len(ordered) - 1):
        seg_start = ordered[idx]
        seg_end = ordered[idx + 1]
        start_ratio = abs(seg_start - start_km) / distance_km
        end_ratio = abs(seg_end - start_km) / distance_km
        seg_start_time = int(round(start_time_s + duration_s * start_ratio))
        seg_end_time = int(round(start_time_s + duration_s * end_ratio))
        section_id, section_source, note = _section_id_for_split(
            sections,
            seg_start,
            seg_end,
            boundary_points,
            model_direction,
        )
        segments.append(
            SplitArcSegment(
                start_km=float(seg_start),
                end_km=float(seg_end),
                start_time_s=seg_start_time,
                end_time_s=seg_end_time,
                section_id=section_id,
                section_source=section_source,
                confidence_note=note,
            )
        )
    # 相近的电气边界可能映射到同一整数秒。应保留这些片段，直到既有短段合并逻辑将其距离和能量
    # 归并到相邻的可表示时间区间。
    return merge_short_split_segments(segments)


def merge_short_split_segments(segments: List[SplitArcSegment]) -> List[SplitArcSegment]:
    """Attach only fragments that cannot occupy a whole-second interval.

    A short electrical section can still have a positive, representable
    duration and must keep its own power-arm ID.  Spatial length alone is not a
    valid reason to merge it into a neighboring arm.
    """
    if not segments:
        return []
    merged: List[SplitArcSegment] = []
    pending: Optional[SplitArcSegment] = None
    for segment in segments:
        if segment.end_time_s <= segment.start_time_s:
            pending = (
                segment
                if pending is None
                else SplitArcSegment(
                    start_km=pending.start_km,
                    end_km=segment.end_km,
                    start_time_s=pending.start_time_s,
                    end_time_s=segment.end_time_s,
                    section_id="boundary_transition",
                    section_source="merged_short_power_boundary_segments",
                    confidence_note=" Short power-boundary fragments are merged into a transition segment.",
                )
            )
            continue

        if pending is not None:
            segment = SplitArcSegment(
                start_km=pending.start_km,
                end_km=segment.end_km,
                start_time_s=pending.start_time_s,
                end_time_s=segment.end_time_s,
                section_id=segment.section_id,
                section_source=segment.section_source,
                confidence_note=segment.confidence_note + " Includes adjacent short power-boundary fragments.",
            )
            pending = None
        merged.append(segment)

    if pending is not None:
        if merged:
            previous = merged[-1]
            merged[-1] = SplitArcSegment(
                start_km=previous.start_km,
                end_km=pending.end_km,
                start_time_s=previous.start_time_s,
                end_time_s=pending.end_time_s,
                section_id=previous.section_id,
                section_source=previous.section_source,
                confidence_note=previous.confidence_note + " Includes adjacent short power-boundary fragments.",
            )
        else:
            merged.append(pending)
    return merged


def _train_by_id(timetable: CanonicalTimetable) -> Dict[str, TimetableTrain]:
    """函数 _train_by_id：执行该模块中的相关处理逻辑。"""
    return {train.train_id: train for train in timetable.trains}


def _stops_by_train(timetable: CanonicalTimetable) -> Dict[str, List[TimetableStop]]:
    """函数 _stops_by_train：执行该模块中的相关处理逻辑。"""
    grouped: Dict[str, List[TimetableStop]] = {}
    for stop in timetable.stops:
        grouped.setdefault(stop.train_id, []).append(stop)
    return {train_id: sorted(stops, key=lambda item: item.seq) for train_id, stops in grouped.items()}


def estimate_event_energy_kwh(train: TimetableTrain, start_km: float, end_km: float, duration_s: int) -> Tuple[str, float, str, str]:
    """函数 estimate_event_energy_kwh：执行该模块中的相关处理逻辑。"""
    distance_km = abs(end_km - start_km)
    if distance_km <= 0 or duration_s <= 0:
        return "neutral", 0.0, "high", "zero-distance or zero-duration arc"

    train_type = train.train_type.lower()
    lo = min(start_km, end_km)
    hi = max(start_km, end_km)
    downhill_overlap_km = _overlap_len(lo, hi, DEFAULT_DOWNHILL_RANGE_KM[0], DEFAULT_DOWNHILL_RANGE_KM[1])
    downhill_ratio = downhill_overlap_km / distance_km if distance_km else 0.0

    mass_t = train.mass_t if train.mass_t is not None else (21600.0 if train_type == "heavy" else 6000.0)
    mass_scale = max(0.3, min(2.0, mass_t / 10000.0))

    if train_type == "heavy" and train.direction == "forward" and downhill_ratio >= 0.25:
        energy = distance_km * (18.0 + 18.0 * downhill_ratio) * mass_scale
        return "generation", energy, "medium", f"Heavy forward arc overlaps long downhill range by {downhill_ratio:.0%}."

    if train_type in {"empty", "light"} or train.direction == "reverse":
        energy = distance_km * 11.0 * mass_scale
        return "consumption", energy, "low", "Empty/light or reverse movement is treated as traction demand."

    energy = distance_km * 8.0 * mass_scale
    return "consumption", energy, "low", "Default running arc traction estimate."


def build_energy_events(
    timetable: CanonicalTimetable,
    power_sections: List[PowerSection],
    phase_boundary_points: Optional[List[float]] = None,
) -> List[EnergyEvent]:
    """函数 build_energy_events：执行该模块中的相关处理逻辑。"""
    trains = _train_by_id(timetable)
    events: List[EnergyEvent] = []
    for train_id, stops in _stops_by_train(timetable).items():
        train = trains.get(train_id)
        if train is None:
            continue
        for idx, stop in enumerate(stops[:-1]):
            next_stop = stops[idx + 1]
            duration_s = int(next_stop.arrival_time_s - stop.departure_time_s)
            if duration_s <= 0:
                continue
            split_segments = split_running_arc_by_power_boundaries(
                stop.station_km,
                next_stop.station_km,
                int(stop.departure_time_s),
                int(next_stop.arrival_time_s),
                power_sections,
                phase_boundary_points,
                train.direction,
            )
            if not split_segments:
                continue
            for split_segment in split_segments:
                split_duration_s = int(split_segment.end_time_s - split_segment.start_time_s)
                event_type, energy_kwh, confidence, basis = estimate_event_energy_kwh(
                    train,
                    split_segment.start_km,
                    split_segment.end_km,
                    split_duration_s,
                )
                if event_type == "neutral" or energy_kwh <= 0:
                    continue
                if split_segment.section_id == "unknown_power_section":
                    confidence = "low"
                elif split_segment.section_id.startswith("inferred_power_arm"):
                    confidence = "medium" if confidence == "medium" else "low"
                events.append(
                    EnergyEvent(
                        event_id=f"EV{len(events) + 1:04d}",
                        train_id=train_id,
                        train_type=train.train_type,
                        direction=train.direction,
                        event_type=event_type,
                        start_time_s=int(split_segment.start_time_s),
                        end_time_s=int(split_segment.end_time_s),
                        start_km=float(split_segment.start_km),
                        end_km=float(split_segment.end_km),
                        section_id=split_segment.section_id,
                        estimated_energy_kwh=round(energy_kwh, 3),
                        confidence=confidence,
                        basis=basis + " Running arc is split by power-arm boundary mileages." + split_segment.confidence_note,
                    )
                )
    return events


def _service_for_timetable_train(train: TimetableTrain) -> ServiceType:
    """函数 _service_for_timetable_train：执行该模块中的相关处理逻辑。"""
    train_type = train.train_type or "Unknown"
    type_key = train_type.lower()
    if type_key == "heavy":
        base_kwh_per_km = 25.0
        nominal_speed = 55.0
        mass_reference = 10000.0
    elif type_key in {"empty", "light"}:
        base_kwh_per_km = 11.0
        nominal_speed = 60.0
        mass_reference = 6000.0
    else:
        base_kwh_per_km = 16.0
        nominal_speed = 55.0
        mass_reference = 8000.0
    if train.mass_t is None:
        mass_scale = 1.0
    else:
        mass_scale = max(0.35, min(2.5, float(train.mass_t) / mass_reference))
    return ServiceType(
        train_type=train_type,
        direction=train.direction,
        consist_unit=1,
        fixed_cost=0.0,
        distance_cost_per_km=0.0,
        energy_cost_per_kwh=0.55,
        nominal_speed_kmh=nominal_speed,
        energy_kwh_per_km=base_kwh_per_km * mass_scale,
    )


def build_timetable_running_arcs(
    timetable: CanonicalTimetable,
    profile: InfrastructureProfile,
) -> Tuple[HeArc, ...]:
    """函数 build_timetable_running_arcs：执行该模块中的相关处理逻辑。"""
    trains = _train_by_id(timetable)
    arcs: List[HeArc] = []
    nodes: List[HeNode] = []
    infra_cache: Dict[Tuple[float, float], Any] = {}
    for train_id, stops in _stops_by_train(timetable).items():
        train = trains.get(train_id)
        if train is None:
            continue
        service = _service_for_timetable_train(train)
        for idx, stop in enumerate(stops[:-1]):
            next_stop = stops[idx + 1]
            if not math.isfinite(stop.station_km) or not math.isfinite(next_stop.station_km):
                raise ValueError(f"列车 {train_id} 第 {stop.seq}—{next_stop.seq} 站的里程无效。")
            if abs(next_stop.station_km - stop.station_km) <= 0:
                continue
            if next_stop.arrival_time_s <= stop.departure_time_s:
                raise ValueError(f"列车 {train_id} 第 {stop.seq}—{next_stop.seq} 站的跨站运行时长必须大于零。")
            parent_arc_id = f"{train_id}:run:{stop.seq:03d}-{next_stop.seq:03d}"
            split_arcs, _, _ = _build_running_arc_segments(
                profile,
                infra_cache,
                nodes,
                parent_arc_id,
                "timetable",
                "",
                train_id,
                train.train_type,
                f"{train_id}:n{stop.seq:03d}:depart",
                f"{train_id}:n{next_stop.seq:03d}:arrive",
                "timetable_running",
                stop.station_name,
                next_stop.station_name,
                int(stop.departure_time_s),
                int(next_stop.arrival_time_s),
                float(stop.station_km),
                float(next_stop.station_km),
                service,
                f"{stop.station_name}->{next_stop.station_name}",
            )
            if (
                not split_arcs
                or split_arcs[0].start_time_s != stop.departure_time_s
                or split_arcs[-1].end_time_s != next_stop.arrival_time_s
                or not math.isclose(split_arcs[0].start_km, stop.station_km, abs_tol=1e-9)
                or not math.isclose(split_arcs[-1].end_km, next_stop.station_km, abs_tol=1e-9)
                or any(
                    left.end_time_s != right.start_time_s
                    or not math.isclose(left.end_km, right.start_km, abs_tol=1e-9)
                    for left, right in zip(split_arcs, split_arcs[1:])
                )
            ):
                raise ValueError(f"列车 {train_id} 第 {stop.seq}—{next_stop.seq} 站的运行弧覆盖不完整。")
            arcs.extend(split_arcs)
    return tuple(arcs)


def _timetable_arc_candidate(arcs: Tuple[HeArc, ...]) -> TimetableArcCandidate:
    """函数 _timetable_arc_candidate：执行该模块中的相关处理逻辑。"""
    return TimetableArcCandidate(candidate_id="user_timetable", arcs=arcs)


def timetable_running_arc_rows(arcs: Iterable[HeArc]) -> List[Dict[str, object]]:
    """函数 timetable_running_arc_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    for arc in arcs:
        rows.append(
            {
                "candidate_id": "user_timetable",
                "arc_id": arc.arc_id,
                "parent_arc_id": arc.parent_arc_id,
                "segment_index": arc.segment_index,
                "segment_count": arc.segment_count,
                "power_arm_split": arc.power_arm_split,
                "train_id": arc.train_id,
                "train_type": arc.train_type,
                "arc_type": arc.arc_type,
                "start_station": arc.start_station,
                "end_station": arc.end_station,
                "start_time_s": arc.start_time_s,
                "end_time_s": arc.end_time_s,
                "start_time": format_s_as_hhmmss(arc.start_time_s),
                "end_time": format_s_as_hhmmss(arc.end_time_s),
                "start_km": round(arc.start_km, 6),
                "end_km": round(arc.end_km, 6),
                "distance_km": round(arc.distance_km, 6),
                "energy_kwh": round(arc.energy_kwh, 6),
                "base_energy_kwh": round(arc.base_energy_kwh, 6),
                "regen_energy_kwh": round(arc.regen_energy_kwh, 6),
                "traction_energy_kwh": round(arc.energy_kwh + arc.regen_energy_kwh, 6),
                "energy_adjustment_kwh": round(arc.energy_kwh - arc.base_energy_kwh, 6),
                "avg_gradient_promille": round(arc.avg_gradient_promille, 6),
                "curve_equivalent": round(arc.curve_equivalent, 6),
                "power_arm_ids": ";".join(arc.power_arm_ids),
                "power_arm_review_required": arc.power_arm_review_required,
                "capacity_resource_id": arc.capacity_resource_id,
                "source": arc.source,
            }
        )
    return rows


def _effective_time_step_s(scenario: TimetableScenario) -> int:
    # TimetableScenario 已校验该值为正整数。按原样保留配置分辨率：正式运行图通常使用 10 秒结算步长，
    # 静默扩大到 15 分钟会同时改变能量重合和储能结果。
    """函数 _effective_time_step_s：执行该模块中的相关处理逻辑。"""
    return scenario.settlement_time_step_s


def _group_time_slice_rows(
    time_slice_rows: Iterable[Dict[str, object]],
    scenario: TimetableScenario,
) -> Dict[Tuple[str, str, int, int], Dict[str, float]]:
    """函数 _group_time_slice_rows：执行该模块中的相关处理逻辑。"""
    grouped: Dict[Tuple[str, str, int, int], Dict[str, float]] = {}
    for row in time_slice_rows:
        power_arm_id = str(row["power_arm_id"])
        storage_section_id = str(row.get("storage_section_id") or "")
        if scenario.transfer_scope not in {"", "same_power_arm"}:
            power_arm_id = str(scenario.transfer_scope)
        key = (
            power_arm_id,
            storage_section_id,
            _as_int(row["time_window_start_s"]),
            _as_int(row["time_window_end_s"]),
        )
        bucket = grouped.setdefault(key, {"traction_kwh": 0.0, "regen_kwh": 0.0})
        bucket["traction_kwh"] += _as_float(row["traction_kwh"])
        bucket["regen_kwh"] += _as_float(row["regen_kwh"])
    return grouped


def evaluate_scenario_time_slices(
    time_slice_rows: List[Dict[str, object]],
    scenario: TimetableScenario,
    power_limits: Optional[Dict[str, PowerArmElectricalLimit]] = None,
    default_storage_efficiency: Optional[float] = None,
    storage_device_parameters: Sequence[StorageDeviceParameters] = (),
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    """函数 evaluate_scenario_time_slices：执行该模块中的相关处理逻辑。"""
    grouped = _group_time_slice_rows(time_slice_rows, scenario)
    settlement_rows: List[Dict[str, object]] = []
    issue_rows: List[Dict[str, object]] = []
    storage_capacity = scenario.storage_capacity_kwh or 0.0
    storage_power_kw = scenario.storage_power_kw or 0.0
    storage_ids = storage_section_ids_from_limits(power_limits)
    tagged_storage_ids = sorted(
        {
            enabled_storage_section_id(
                key[1],
                limit_for_power_arm(key[0], power_limits),
                power_arm_limit_is_explicit(key[0], power_limits),
            )
            for key in grouped
            if key[1]
        }
        - {""}
    )
    if tagged_storage_ids:
        storage_ids = sorted(set(storage_ids).union(tagged_storage_ids))
    configured_efficiency = (
        DEFAULT_STORAGE_EFFICIENCY
        if default_storage_efficiency is None
        else default_storage_efficiency
    )
    if isinstance(configured_efficiency, bool):
        raise ValueError("default_storage_efficiency must be finite and in [0, 1]")
    try:
        configured_efficiency = float(configured_efficiency)
    except (TypeError, ValueError) as exc:
        raise ValueError("default_storage_efficiency must be finite and in [0, 1]") from exc
    if not math.isfinite(configured_efficiency) or not 0.0 <= configured_efficiency <= 1.0:
        raise ValueError("default_storage_efficiency must be finite and in [0, 1]")
    storage_state = initialize_storage_settlement_state(
        storage_ids,
        storage_capacity,
        scenario.storage_charge_power_kw if scenario.storage_charge_power_kw is not None else storage_power_kw,
        scenario.storage_discharge_power_kw if scenario.storage_discharge_power_kw is not None else storage_power_kw,
        scenario.initial_soc_kwh or 0.0,
        scenario.storage_efficiency if scenario.storage_efficiency is not None else configured_efficiency,
        storage_device_parameters=storage_device_parameters,
        use_device_initial_soc=bool(storage_device_parameters),
    )
    initial_soc_by_storage = dict(storage_state.soc_by_storage_kwh)
    storage_flow_by_storage: Dict[str, Dict[str, float]] = {
        storage_id: {"charge": 0.0, "discharge": 0.0, "wasted": 0.0}
        for storage_id in storage_state.soc_by_storage_kwh
    }
    wasted_outside_storage_kwh = 0.0
    grouped_by_time: Dict[
        Tuple[int, int],
        List[Tuple[Tuple[str, str, int, int], Dict[str, float]]],
    ] = {}
    for key, values in grouped.items():
        _power_arm_id, _storage_section_id, start_s, end_s = key
        grouped_by_time.setdefault((start_s, end_s), []).append((key, values))
    bucket_results: Dict[Tuple[str, str, int, int], EnergyBucketSettlement] = {}
    for (_start_s, _end_s), group_items in sorted(grouped_by_time.items()):
        requests = [
            EnergyBucketRequest(
                traction_kwh=values["traction_kwh"],
                regen_kwh=values["regen_kwh"],
                non_transfer_traction_kwh=0.0,
                non_transfer_regen_kwh=0.0,
                start_s=key[2],
                end_s=key[3],
                storage_section_id=key[1],
                limit=limit_for_power_arm(key[0], power_limits),
                power_arm_id=key[0],
                storage_availability_explicit=power_arm_limit_is_explicit(
                    key[0], power_limits
                ),
            )
            for key, values in group_items
        ]
        results = settle_energy_bucket_group(
            requests,
            allow_direct_use=scenario.direct_use_enabled and SHUOHUANG_DIRECT_USE_ENABLED,
            allow_storage=scenario.storage_enabled,
            storage_state=storage_state,
        )
        for (key, _values), result in zip(group_items, results):
            bucket_results[key] = result
    total_traction = 0.0
    total_regen = 0.0
    total_direct = 0.0
    total_stored = 0.0
    total_discharged = 0.0
    total_wasted = 0.0
    total_grid = 0.0
    total_traction_supply_excess = 0.0
    total_regen_absorption_excess = 0.0

    for idx, ((power_arm_id, storage_section_id, start_s, end_s), values) in enumerate(
        sorted(grouped.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])),
        start=1,
    ):
        traction = values["traction_kwh"]
        regen = values["regen_kwh"]
        limit = limit_for_power_arm(power_arm_id, power_limits)
        traction_capacity_kwh = time_window_capacity_kwh(limit.max_traction_supply_kw, start_s, end_s)
        regen_absorption_capacity_kwh = time_window_capacity_kwh(limit.max_regen_absorption_kw, start_s, end_s)
        grid_feedback_capacity_kwh = time_window_capacity_kwh(limit.max_grid_feedback_kw, start_s, end_s)
        bucket_result = bucket_results[(power_arm_id, storage_section_id, start_s, end_s)]
        direct_used = bucket_result.direct_used_kwh
        stored = bucket_result.battery_charge_kwh
        discharged = bucket_result.battery_discharge_kwh
        remaining_regen = max(0.0, regen - direct_used)
        wasted = bucket_result.wasted_kwh
        grid = bucket_result.grid_kwh
        traction_supply_excess = bucket_result.traction_supply_excess_kwh
        regen_absorption_excess = bucket_result.regen_absorption_excess_kwh

        total_traction += traction
        total_regen += regen
        total_direct += direct_used
        total_stored += stored
        total_discharged += discharged
        total_wasted += wasted
        total_grid += grid
        total_traction_supply_excess += traction_supply_excess
        total_regen_absorption_excess += regen_absorption_excess

        storage_key = enabled_storage_section_id(
            storage_section_id,
            limit,
            power_arm_limit_is_explicit(power_arm_id, power_limits),
        )
        if storage_key:
            flow = storage_flow_by_storage.setdefault(
                storage_key,
                {"charge": 0.0, "discharge": 0.0, "wasted": 0.0},
            )
            flow["charge"] += stored
            flow["discharge"] += discharged
            flow["wasted"] += wasted
        else:
            wasted_outside_storage_kwh += wasted

        settlement_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "power_arm_id": power_arm_id,
                "storage_section_id": storage_section_id,
                "time_window_start_s": start_s,
                "time_window_end_s": end_s,
                "time_window_start": format_s_as_hhmmss(start_s),
                "time_window_end": format_s_as_hhmmss(end_s),
                "traction_kwh": round(traction, 6),
                "regen_kwh": round(regen, 6),
                "direct_used_kwh": round(direct_used, 6),
                "storage_absorbed_kwh": round(stored, 6),
                "storage_discharged_kwh": round(discharged, 6),
                "storage_soc_before_kwh": round(bucket_result.soc_before_kwh, 6),
                "storage_soc_after_kwh": round(bucket_result.soc_after_kwh, 6),
                "wasted_kwh": round(wasted, 6),
                "grid_kwh": round(grid, 6),
                "traction_capacity_kwh": round(traction_capacity_kwh, 6),
                "regen_absorption_capacity_kwh": round(regen_absorption_capacity_kwh, 6),
                "grid_feedback_capacity_kwh": round(grid_feedback_capacity_kwh, 6),
                # 约束值保持精确，使 API/CSV 使用方不会看到一个已被优化器拒绝的运行图被显示为零超限。
                "traction_supply_excess_kwh": traction_supply_excess,
                "regen_absorption_excess_kwh": regen_absorption_excess,
                **electrical_limit_fields(limit),
                "direct_use_ratio": round(direct_used / regen, 6) if regen > 0 else 0.0,
                "settlement_mode": _scenario_settlement_mode(scenario),
            }
        )
        if traction_supply_excess > ELECTRICAL_CONSTRAINT_TOLERANCE_KWH:
            issue_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "issue_id": f"TSI{idx:04d}-T",
                    "issue_type": "traction_supply_capacity_exceeded",
                    "severity": "high",
                    "power_arm_id": power_arm_id,
                    "time_window_start": format_s_as_hhmmss(start_s),
                    "time_window_end": format_s_as_hhmmss(end_s),
                    "traction_kwh": round(traction, 6),
                    "regen_kwh": round(regen, 6),
                    "electrical_excess_kwh": traction_supply_excess,
                    "reason": "牵引用电超过该供电臂在当前时间窗内的供电能力。",
                    "source": "time_slice_power_arm_electrical_constraint",
                }
            )
        if regen_absorption_excess > ELECTRICAL_CONSTRAINT_TOLERANCE_KWH:
            issue_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "issue_id": f"TSI{idx:04d}-R",
                    "issue_type": "regen_absorption_capacity_exceeded",
                    "severity": "high",
                    "power_arm_id": power_arm_id,
                    "time_window_start": format_s_as_hhmmss(start_s),
                    "time_window_end": format_s_as_hhmmss(end_s),
                    "traction_kwh": round(traction, 6),
                    "regen_kwh": round(regen, 6),
                    "electrical_excess_kwh": regen_absorption_excess,
                    "reason": "再生电量超过该供电臂在当前时间窗内的吸收能力。",
                    "source": "time_slice_power_arm_electrical_constraint",
                }
            )
        if wasted > 1e-6:
            if regen > 0 and traction <= 1e-6:
                issue_type = "regen_without_traction_same_window"
                reason = "同一结算范围和时间窗内存在再生电量，但没有牵引用电需求。"
            elif not scenario.direct_use_enabled and not scenario.storage_enabled:
                issue_type = "regen_unusable_by_scenario"
                reason = "当前场景既不允许直发直用，也没有储能吸收。"
            elif scenario.storage_enabled and stored < remaining_regen:
                if not limit.storage_available:
                    issue_type = "section_without_storage"
                    reason = "该供电臂未标记为储能接入区段，再生能量不能进入储能。"
                else:
                    issue_type = "storage_capacity_or_power_limit"
                    reason = "剩余再生电量超过储能可用容量或充电功率。"
            else:
                issue_type = "regen_exceeds_traction_same_window"
                reason = "同一结算范围和时间窗内再生电量大于牵引用电需求。"
            issue_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "issue_id": f"TSI{idx:04d}",
                    "issue_type": issue_type,
                    "severity": "high" if wasted >= 1000 else "medium",
                    "power_arm_id": power_arm_id,
                    "time_window_start": format_s_as_hhmmss(start_s),
                    "time_window_end": format_s_as_hhmmss(end_s),
                    "traction_kwh": round(traction, 6),
                    "regen_kwh": round(regen, 6),
                    "direct_used_kwh": round(direct_used, 6),
                    "storage_absorbed_kwh": round(stored, 6),
                    "estimated_wasted_kwh": round(wasted, 6),
                    "reason": reason,
                    "source": "time_slice_power_arm_settlement",
                }
            )

    initial_soc_kwh = sum(initial_soc_by_storage.values())
    final_soc_kwh = sum(storage_state.soc_by_storage_kwh.values())
    final_soc_deviation_kwh = abs(final_soc_kwh - initial_soc_kwh)
    final_soc_shortfall_kwh = max(0.0, initial_soc_kwh - final_soc_kwh)
    # 汇总 SOC 可能掩盖真实的设备级不平衡。例如一个区段充满，而另一区段释放初始库存；
    # 总量仍可能等于初始 SOC，但后一个设备已无法为下一调度窗口提供同等能力。
    # 为兼容性保留公开汇总值，同时跟踪设备级终端偏差并用于后续评价。
    final_soc_device_deviation_kwh = sum(
        abs(
            float(final_soc)
            - float(initial_soc_by_storage.get(storage_id, 0.0))
        )
        for storage_id, final_soc in storage_state.soc_by_storage_kwh.items()
    )
    final_soc_device_shortfall_kwh = sum(
        max(
            0.0,
            float(initial_soc_by_storage.get(storage_id, 0.0))
            - float(final_soc),
        )
        for storage_id, final_soc in storage_state.soc_by_storage_kwh.items()
    )
    # 分别评价相互独立的储能设备，否则一个区段的充电可能被另一区段的初始库存放电错误抵销。
    effective_regen_loss_kwh = wasted_outside_storage_kwh
    for storage_id, final_soc in storage_state.soc_by_storage_kwh.items():
        flow = storage_flow_by_storage.get(
            storage_id,
            {"charge": 0.0, "discharge": 0.0, "wasted": 0.0},
        )
        initial_soc = initial_soc_by_storage.get(storage_id, 0.0)
        device_deviation = abs(final_soc - initial_soc)
        device_shortfall = max(0.0, initial_soc - final_soc)
        effective_regen_loss_kwh += storage_no_direct_effective_loss_kwh(
            flow["wasted"],
            flow["charge"],
            flow["discharge"],
            device_deviation,
            storage_state.charge_efficiency_by_storage.get(
                storage_id, storage_state.efficiency
            ) * storage_state.discharge_efficiency_by_storage.get(storage_id, 1.0),
            device_shortfall,
        )
    total_device_capacity = sum(storage_state.capacity_by_storage_kwh.values())
    reported_storage_efficiency = (
        sum(
            storage_state.capacity_by_storage_kwh[storage_id]
            * storage_state.charge_efficiency_by_storage.get(
                storage_id, storage_state.efficiency
            )
            * storage_state.discharge_efficiency_by_storage.get(storage_id, 1.0)
            for storage_id in storage_state.capacity_by_storage_kwh
        ) / total_device_capacity
        if total_device_capacity > 0.0 else storage_state.efficiency
    )
    storage_parameters_by_id = {
        storage_id: {
            "capacity_kwh": storage_state.capacity_by_storage_kwh[storage_id],
            "max_charge_power_kw": storage_state.charge_power_by_storage_kw[storage_id],
            "max_discharge_power_kw": storage_state.discharge_power_by_storage_kw[storage_id],
            "charge_efficiency": storage_state.charge_efficiency_by_storage[storage_id],
            "discharge_efficiency": storage_state.discharge_efficiency_by_storage[storage_id],
            "min_soc_kwh": storage_state.min_soc_by_storage_kwh[storage_id],
            "max_soc_kwh": storage_state.max_soc_by_storage_kwh[storage_id],
            "available": storage_state.available_by_storage[storage_id],
        }
        for storage_id in storage_state.soc_by_storage_kwh
    }
    summary = {
        "scenario_id": scenario.scenario_id,
        "direct_use_enabled": scenario.direct_use_enabled,
        "storage_enabled": scenario.storage_enabled,
        "settlement_time_step_s": _effective_time_step_s(scenario),
        "settlement_mode": _scenario_settlement_mode(scenario),
        "storage_efficiency": reported_storage_efficiency,
        "storage_parameters_by_id": storage_parameters_by_id,
        "storage_charge_power_per_section_kw": storage_state.charge_power_per_storage_kw,
        "storage_discharge_power_per_section_kw": storage_state.discharge_power_per_storage_kw,
        "total_traction_kwh": round(total_traction, 6),
        "total_regen_kwh": round(total_regen, 6),
        "direct_used_kwh": round(total_direct, 6),
        "storage_absorbed_kwh": round(total_stored, 6),
        "storage_discharged_kwh": round(total_discharged, 6),
        "accepted_by_power_arm_kwh": round(total_direct + total_stored, 6),
        "recovered_energy_kwh": round(
            total_direct + total_stored * storage_state.efficiency,
            6,
        ),
        "initial_soc_kwh": round(initial_soc_kwh, 6),
        "final_soc_kwh": round(final_soc_kwh, 6),
        "final_soc_deviation_kwh": round(final_soc_deviation_kwh, 6),
        "final_soc_shortfall_kwh": round(final_soc_shortfall_kwh, 6),
        "final_soc_device_deviation_kwh": round(final_soc_device_deviation_kwh, 6),
        "final_soc_device_shortfall_kwh": round(final_soc_device_shortfall_kwh, 6),
        "effective_regen_loss_kwh": round(effective_regen_loss_kwh, 6),
        "final_soc_by_storage_kwh": {
            key: round(value, 6)
            for key, value in sorted(storage_state.soc_by_storage_kwh.items())
        },
        "wasted_kwh": round(total_wasted, 6),
        "grid_kwh": round(total_grid, 6),
        # 约束使用方必须读取未舍入值；此处格式化到六位小数可能把真实的小超限变成零，
        # 使运行图候选被错误判为可行。
        "traction_supply_excess_kwh": total_traction_supply_excess,
        "regen_absorption_excess_kwh": total_regen_absorption_excess,
        "electrical_constraint_violation_kwh": (
            total_traction_supply_excess + total_regen_absorption_excess
        ),
        "direct_use_ratio": round(total_direct / total_regen, 6) if total_regen > 0 else 0.0,
        "recovery_rate": round(
            (total_direct + total_stored * storage_state.efficiency) / total_regen,
            6,
        ) if total_regen > 0 else 0.0,
        "settlement_window_count": len(settlement_rows),
        "issue_count": len(issue_rows),
        "assessment": (
            "reasonable"
            if not issue_rows
            and final_soc_deviation_kwh <= 1e-6
            and final_soc_device_deviation_kwh <= 1e-6
            else "needs_optimization"
        ),
    }
    return settlement_rows, issue_rows, summary


def _scenario_settlement_mode(scenario: TimetableScenario) -> str:
    """函数 _scenario_settlement_mode：执行该模块中的相关处理逻辑。"""
    direct_enabled = scenario.direct_use_enabled and SHUOHUANG_DIRECT_USE_ENABLED
    if direct_enabled and scenario.storage_enabled:
        return "direct_same_power_arm_same_time_window_with_storage_absorption"
    if direct_enabled:
        return "direct_same_power_arm_same_time_window_no_storage"
    if scenario.storage_enabled:
        return "storage_absorption_no_direct_use_storage_sections_only"
    return "no_direct_use_no_storage"


def build_time_slice_suggestions(issue_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """函数 build_time_slice_suggestions：执行该模块中的相关处理逻辑。"""
    suggestions: List[Dict[str, object]] = []
    for idx, issue in enumerate(issue_rows, start=1):
        issue_type = str(issue.get("issue_type", ""))
        if issue_type == "regen_without_traction_same_window":
            action = "在该供电臂相邻时间窗内寻找可平移的牵引列车，优先尝试小幅调整发车或停站时间，使牵引需求与再生电量同窗出现。"
        elif issue_type == "traction_supply_capacity_exceeded":
            action = "降低该供电臂同窗牵引峰值：错开发车或运行时刻，并复核正式牵引供电能力参数。"
        elif issue_type == "regen_absorption_capacity_exceeded":
            action = "降低该供电臂同窗再生峰值，或复核再生吸收/储能接入能力后重新优化。"
        elif issue_type == "storage_capacity_or_power_limit":
            action = "若该储能场景作为规划假设，应提高储能容量/充电功率假设，或通过重定时降低同窗再生峰值。"
        elif issue_type == "regen_exceeds_traction_same_window":
            action = "优先把同供电臂内相邻牵引运行弧向该时间窗靠拢，或延长/压缩停站时间以改善重叠。"
        else:
            action = "该场景不具备当前再生电量利用路径，建议切换到允许直用或储能的方案假设后再评估。"
        suggestions.append(
            {
                "suggestion_id": f"TSS{idx:04d}",
                "scenario_id": issue.get("scenario_id", ""),
                "source_issue_id": issue.get("issue_id", ""),
                "source_issue_type": issue_type,
                "power_arm_id": issue.get("power_arm_id", ""),
                "time_window_start": issue.get("time_window_start", ""),
                "time_window_end": issue.get("time_window_end", ""),
                "priority": issue.get("severity", "medium"),
                "action": action,
                "expected_effect": "减少同供电臂同时间窗内未利用再生电量。",
                "requires_manual_confirmation": True,
            }
        )
    return suggestions


def _matching_consumption(
    generation: EnergyEvent,
    consumption_events: List[EnergyEvent],
    match_window_s: int,
    same_section: bool,
) -> Tuple[float, List[str], int]:
    """函数 _matching_consumption：执行该模块中的相关处理逻辑。"""
    matched_energy = 0.0
    matched_ids: List[str] = []
    best_gap_s = 10**9
    for event in consumption_events:
        if same_section and event.section_id != generation.section_id:
            continue
        if same_section and generation.section_id == "unknown_power_section":
            continue
        overlap_s = _time_overlap_s(generation.start_time_s, generation.end_time_s, event.start_time_s, event.end_time_s)
        if overlap_s <= 0:
            gap_s = min(
                abs(event.start_time_s - generation.end_time_s),
                abs(generation.start_time_s - event.end_time_s),
            )
            best_gap_s = min(best_gap_s, gap_s)
            if gap_s > match_window_s:
                continue
            overlap_factor = max(0.1, 1.0 - gap_s / max(1, match_window_s))
        else:
            best_gap_s = 0
            overlap_factor = overlap_s / max(1, min(generation.end_time_s - generation.start_time_s, event.end_time_s - event.start_time_s))
        matched_energy += event.estimated_energy_kwh * overlap_factor
        matched_ids.append(event.event_id)
    return min(generation.estimated_energy_kwh, matched_energy), matched_ids, best_gap_s


def evaluate_scenario(timetable: CanonicalTimetable, events: List[EnergyEvent], scenario: TimetableScenario) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """函数 evaluate_scenario：执行该模块中的相关处理逻辑。"""
    generation_events = [event for event in events if event.event_type == "generation"]
    consumption_events = [event for event in events if event.event_type == "consumption"]
    issue_rows: List[Dict[str, object]] = []
    total_generation = sum(event.estimated_energy_kwh for event in generation_events)
    total_consumption = sum(event.estimated_energy_kwh for event in consumption_events)
    direct_used = 0.0
    storage_absorbed = 0.0
    wasted = 0.0
    storage_remaining = scenario.storage_capacity_kwh or 0.0
    storage_power_limit = scenario.storage_power_kw or 0.0

    for event in generation_events:
        direct_match = 0.0
        matched_ids: List[str] = []
        best_gap_s = 10**9
        if scenario.direct_use_enabled:
            direct_match, matched_ids, best_gap_s = _matching_consumption(
                event,
                consumption_events,
                DIRECT_MATCH_WINDOW_S,
                same_section=scenario.transfer_scope == "same_power_arm",
            )
        direct_used += direct_match
        leftover = max(0.0, event.estimated_energy_kwh - direct_match)

        stored = 0.0
        if leftover > 0 and scenario.storage_enabled:
            duration_h = max(1.0 / 3600.0, (event.end_time_s - event.start_time_s) / 3600.0)
            # 可用充电功率为零表示设备不能吸收能量，不能提升为无界的旧版值，
            # 尤其是在功率字段缺失或设备停用时。
            by_power = max(0.0, storage_power_limit) * duration_h
            stored = min(leftover, storage_remaining, by_power)
            storage_remaining -= stored
            storage_absorbed += stored

        event_waste = max(0.0, leftover - stored)
        wasted += event_waste
        if event_waste > 1e-6:
            if not scenario.direct_use_enabled and not scenario.storage_enabled:
                issue_type = "regeneration_unusable"
                reason = "直接利用和储能均未启用。"
            elif scenario.direct_use_enabled and not matched_ids:
                issue_type = "no_matching_traction_window"
                reason = "匹配时间窗内未找到同一供电范围的牵引用电需求。"
            elif scenario.storage_enabled and stored < leftover:
                issue_type = "storage_limit"
                reason = "储能容量或充电功率不足，无法吸收剩余再生能量。"
            else:
                issue_type = "regeneration_leftover"
                reason = "可用利用路径处理后仍有剩余再生能量。"
            issue_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "issue_type": issue_type,
                    "severity": "high" if event_waste >= 1000 else "medium",
                    "event_id": event.event_id,
                    "train_id": event.train_id,
                    "section_id": event.section_id,
                    "start_time": format_s_as_hhmmss(event.start_time_s),
                    "end_time": format_s_as_hhmmss(event.end_time_s),
                    "estimated_wasted_kwh": round(event_waste, 3),
                    "matched_consumption_events": ";".join(matched_ids),
                    "nearest_gap_min": "" if best_gap_s == 10**9 else round(best_gap_s / 60.0, 2),
                    "reason": reason,
                }
            )

    grid_energy = max(0.0, total_consumption - direct_used - storage_absorbed)
    summary = {
        "scenario_id": scenario.scenario_id,
        "direct_use_enabled": scenario.direct_use_enabled,
        "storage_enabled": scenario.storage_enabled,
        "total_generation_kwh_est": round(total_generation, 3),
        "total_consumption_kwh_est": round(total_consumption, 3),
        "direct_used_kwh_est": round(direct_used, 3),
        "storage_absorbed_kwh_est": round(storage_absorbed, 3),
        "wasted_kwh_est": round(wasted, 3),
        "grid_kwh_est": round(grid_energy, 3),
        "issue_count": len(issue_rows),
        "assessment": "reasonable" if len(issue_rows) == 0 else "needs_optimization",
    }
    return issue_rows, summary


def build_suggestions(issue_rows: List[Dict[str, object]], events: List[EnergyEvent]) -> List[Dict[str, object]]:
    """函数 build_suggestions：执行该模块中的相关处理逻辑。"""
    events_by_id = {event.event_id: event for event in events}
    suggestions: List[Dict[str, object]] = []
    consumption_events = [event for event in events if event.event_type == "consumption"]
    for idx, issue in enumerate(issue_rows, start=1):
        event = events_by_id.get(str(issue.get("event_id")))
        if event is None:
            continue
        same_section = [item for item in consumption_events if item.section_id == event.section_id]
        nearest: Optional[EnergyEvent] = None
        nearest_gap = 10**9
        for candidate in same_section or consumption_events:
            overlap_s = _time_overlap_s(event.start_time_s, event.end_time_s, candidate.start_time_s, candidate.end_time_s)
            gap = 0 if overlap_s > 0 else min(
                abs(candidate.start_time_s - event.end_time_s),
                abs(event.start_time_s - candidate.end_time_s),
            )
            if gap < nearest_gap:
                nearest = candidate
                nearest_gap = gap
        if nearest is not None:
            shift_min = round(nearest_gap / 60.0, 1)
            if event.section_id == "unknown_power_section":
                action = (
                    f"调整时刻前，按真实供电臂边界拆分列车 {event.train_id} 的运行弧；"
                    "当前运行弧范围过宽，无法证明同一供电臂内的直接利用。"
                )
            elif issue.get("source_issue_type") == "storage_limit" and nearest_gap == 0:
                action = (
                    f"再生能量已与列车 {nearest.train_id} 的牵引用电重叠；请检查储能容量/充电功率，"
                    f"或拆分区段 {event.section_id} 附近的再生峰值。"
                )
            else:
                action = (
                    f"将列车 {nearest.train_id} 或 {event.train_id} 调整约 {shift_min} 分钟，"
                    f"使区段 {event.section_id} 内的再生能量与牵引用电重叠。"
                )
        else:
            action = (
                f"在 {format_s_as_hhmmss(event.start_time_s)}—{format_s_as_hhmmss(event.end_time_s)} 时间窗内，"
                f"于区段 {event.section_id} 增加或调整牵引列车。"
            )
        suggestions.append(
            {
                "suggestion_id": f"S{idx:04d}",
                "scenario_id": issue.get("scenario_id", ""),
                "source_issue_type": issue.get("issue_type", ""),
                "target_event_id": event.event_id,
                "priority": issue.get("severity", "medium"),
                "action": action,
                "expected_effect": "提高再生能量直接利用率，或降低储能和能量浪费压力。",
                "requires_manual_confirmation": True,
            }
        )
    return suggestions


def _event_rows(events: Iterable[EnergyEvent]) -> List[Dict[str, object]]:
    """函数 _event_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "event_id": event.event_id,
            "train_id": event.train_id,
            "train_type": event.train_type,
            "direction": event.direction,
            "event_type": event.event_type,
            "start_time_s": event.start_time_s,
            "end_time_s": event.end_time_s,
            "start_time": format_s_as_hhmmss(event.start_time_s),
            "end_time": format_s_as_hhmmss(event.end_time_s),
            "start_km": event.start_km,
            "end_km": event.end_km,
            "section_id": event.section_id,
            "estimated_energy_kwh": event.estimated_energy_kwh,
            "confidence": event.confidence,
            "basis": event.basis,
        }
        for event in events
    ]


def _write_csv(path: Path, rows: Iterable[Dict[str, object]], fieldnames: Optional[List[str]] = None) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: object, default: float = 0.0) -> float:
    """函数 _as_float：执行该模块中的相关处理逻辑。"""
    try:
        if value is None or value == "":
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    """将动态输入转换为整数，空值或非法值使用默认值。"""
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _plot_timetable_profile(path: Path, running_arcs: Iterable[HeArc]) -> Optional[Path]:
    """函数 _plot_timetable_profile：执行该模块中的相关处理逻辑。"""
    if plt is None:
        return None
    arcs = sorted(running_arcs, key=lambda item: (item.train_id, item.start_time_s))
    if not arcs:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6))
    train_ids = sorted({arc.train_id for arc in arcs})
    for train_id in train_ids:
        train_arcs = [arc for arc in arcs if arc.train_id == train_id]
        color = None
        for arc in train_arcs:
            line = ax.plot(
                [arc.start_time_s / 3600.0, arc.end_time_s / 3600.0],
                [arc.start_km, arc.end_km],
                marker="o",
                linewidth=1.8,
                label=train_id if color is None else None,
            )
            color = line[0].get_color()
    ax.set_title("运行图时空剖面")
    ax.set_xlabel("时间（小时）")
    ax.set_ylabel("里程（公里）")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_scenario_energy_comparison(path: Path, scenario_summaries: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_scenario_energy_comparison：执行该模块中的相关处理逻辑。"""
    if plt is None or not scenario_summaries:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    scenarios = [_report_scenario_label(row.get("scenario_id", "")) for row in scenario_summaries]
    metrics = [
        ("total_traction_kwh", "牵引能耗"),
        ("total_regen_kwh", "再生能量"),
        ("direct_used_kwh", "直接利用"),
        ("storage_absorbed_kwh", "储能吸收"),
        ("wasted_kwh", "浪费能量"),
        ("grid_kwh", "电网供能"),
    ]
    x = list(range(len(scenarios)))
    width = 0.13
    fig, ax = plt.subplots(figsize=(12, 6))
    for idx, (key, label) in enumerate(metrics):
        offset = (idx - (len(metrics) - 1) / 2) * width
        values = [_as_float(row.get(key)) for row in scenario_summaries]
        ax.bar([item + offset for item in x], values, width=width, label=label)
    ax.set_title("场景能量对比")
    ax.set_ylabel("能量（千瓦时）")
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, rotation=18, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_power_arm_timeline(path: Path, settlement_rows: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_power_arm_timeline：执行该模块中的相关处理逻辑。"""
    if plt is None or not settlement_rows:
        return None
    scenario_code = str(settlement_rows[0].get("scenario_id", ""))
    scenario_id = _report_scenario_label(scenario_code)
    rows = [row for row in settlement_rows if str(row.get("scenario_id", "")) == scenario_code]
    if not rows:
        return None
    by_time: Dict[float, Dict[str, float]] = {}
    for row in rows:
        t = _as_float(row.get("time_window_start_s")) / 3600.0
        bucket = by_time.setdefault(t, {"traction": 0.0, "regen": 0.0, "wasted": 0.0, "direct": 0.0, "storage": 0.0})
        bucket["traction"] += _as_float(row.get("traction_kwh"))
        bucket["regen"] += _as_float(row.get("regen_kwh"))
        bucket["wasted"] += _as_float(row.get("wasted_kwh"))
        bucket["direct"] += _as_float(row.get("direct_used_kwh"))
        bucket["storage"] += _as_float(row.get("storage_absorbed_kwh"))
    times = sorted(by_time)
    if not times:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(times, [by_time[t]["traction"] for t in times], label="牵引能耗", linewidth=1.8)
    ax.plot(times, [by_time[t]["regen"] for t in times], label="再生能量", linewidth=1.8)
    ax.plot(times, [by_time[t]["direct"] for t in times], label="直接利用", linewidth=1.5)
    ax.plot(times, [by_time[t]["storage"] for t in times], label="储能吸收", linewidth=1.5)
    ax.plot(times, [by_time[t]["wasted"] for t in times], label="浪费能量", linewidth=1.8)
    ax.set_title(f"供电臂结算时间线（{scenario_id}）")
    ax.set_xlabel("时间（小时）")
    ax.set_ylabel("时间窗能量（千瓦时）")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_power_arm_top_energy(path: Path, settlement_rows: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_power_arm_top_energy：执行该模块中的相关处理逻辑。"""
    if plt is None or not settlement_rows:
        return None
    scenario_code = str(settlement_rows[0].get("scenario_id", ""))
    scenario_id = _report_scenario_label(scenario_code)
    totals: Dict[str, Dict[str, float]] = {}
    for row in settlement_rows:
        if str(row.get("scenario_id", "")) != scenario_code:
            continue
        arm = str(row.get("power_arm_id", "unknown"))
        bucket = totals.setdefault(arm, {"traction": 0.0, "regen": 0.0, "wasted": 0.0})
        bucket["traction"] += _as_float(row.get("traction_kwh"))
        bucket["regen"] += _as_float(row.get("regen_kwh"))
        bucket["wasted"] += _as_float(row.get("wasted_kwh"))
    top = sorted(totals.items(), key=lambda item: item[1]["traction"] + item[1]["regen"] + item[1]["wasted"], reverse=True)[:12]
    if not top:
        return None
    labels = [item[0] for item in top]
    traction = [item[1]["traction"] for item in top]
    regen = [item[1]["regen"] for item in top]
    wasted = [item[1]["wasted"] for item in top]
    x = list(range(len(labels)))
    width = 0.25
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar([i - width for i in x], traction, width=width, label="牵引能耗")
    ax.bar(x, regen, width=width, label="再生能量")
    ax.bar([i + width for i in x], wasted, width=width, label="浪费能量")
    ax.set_title(f"供电臂能耗排名（{scenario_id}）")
    ax.set_ylabel("能量（千瓦时）")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def write_audit_visualizations(
    output_dir: Path,
    running_arcs: Iterable[HeArc],
    scenario_summaries: List[Dict[str, object]],
    settlement_rows: List[Dict[str, object]],
    strict: bool = False,
) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """函数 write_audit_visualizations：执行该模块中的相关处理逻辑。"""
    visual_dir = output_dir / "figures"
    outputs: Dict[str, str] = {}
    errors: List[Dict[str, str]] = []
    if plt is None:
        failure = {
            "figure": "matplotlib",
            "error_type": "RuntimeError",
            "message": f"Matplotlib is unavailable: {MATPLOTLIB_IMPORT_ERROR or 'import failed'}",
        }
        errors.append(failure)
        warnings.warn(failure["message"], RuntimeWarning, stacklevel=2)
        if strict:
            raise RuntimeError(failure["message"])
        return outputs, errors
    _configure_report_font()
    plotters = [
        ("timetable_profile", lambda: _plot_timetable_profile(visual_dir / "timetable_profile.png", running_arcs)),
        ("scenario_energy_comparison", lambda: _plot_scenario_energy_comparison(visual_dir / "scenario_energy_comparison.png", scenario_summaries)),
        ("power_arm_energy_timeline", lambda: _plot_power_arm_timeline(visual_dir / "power_arm_energy_timeline.png", settlement_rows)),
        ("top_power_arm_energy", lambda: _plot_power_arm_top_energy(visual_dir / "top_power_arm_energy.png", settlement_rows)),
    ]
    for key, plotter in plotters:
        try:
            result = plotter()
        except Exception as exc:
            failure = {
                "figure": key,
                "error_type": type(exc).__name__,
                "message": str(exc) or repr(exc),
            }
            errors.append(failure)
            if plt is not None:
                plt.close("all")
            message = f"可视化“{key}”失败：{failure['error_type']}：{failure['message']}"
            warnings.warn(message, RuntimeWarning, stacklevel=2)
            if strict:
                raise RuntimeError(message) from exc
            result = None
        if result is not None:
            outputs[key] = str(result)
    return outputs, errors


def write_markdown_report(
    path: Path,
    timetable: CanonicalTimetable,
    power_sections: List[PowerSection],
    scenario_summaries: List[Dict[str, object]],
    issue_rows: List[Dict[str, object]],
    suggestion_rows: List[Dict[str, object]],
    figure_outputs: Optional[Dict[str, str]] = None,
    visualization_errors: Optional[List[Dict[str, str]]] = None,
) -> None:
    """函数 write_markdown_report：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    best = min(
        scenario_summaries,
        key=lambda row: (
            _as_float(row.get("effective_regen_loss_kwh", row.get("wasted_kwh", 0.0))),
            _as_int(row.get("issue_count", 0)),
        ),
    ) if scenario_summaries else None
    lines = [
        "# 运行图能量审查报告",
        "",
        "## 输入摘要",
        "",
        f"- 列车数量：{len(timetable.trains)}",
        f"- 运行图停站/事件数量：{len(timetable.stops)}",
        f"- 能量场景数量：{len(timetable.scenarios)}",
        f"- 供电臂记录数量：{len(power_sections)}",
        "",
        "## 场景评估",
        "",
        "| 场景 | 直接利用 | 储能 | 牵引能耗（千瓦时） | 再生能量（千瓦时） | 直接利用（千瓦时） | 储能吸收（千瓦时） | 最终 SOC（千瓦时） | 有效再生损失（千瓦时） | 浪费能量（千瓦时） | 电网供能（千瓦时） | 问题数 | 评估 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in scenario_summaries:
        lines.append(
            "| {scenario_id} | {direct} | {storage} | {traction} | {regen} | {direct_used} | {stored} | {final_soc} | {effective_loss} | {waste} | {grid} | {issues} | {assessment} |".format(
                scenario_id=_report_scenario_label(row.get("scenario_id", "")),
                direct=_report_yes_no(row.get("direct_use_enabled")),
                storage=_report_yes_no(row.get("storage_enabled")),
                traction=row.get("total_traction_kwh", 0),
                regen=row.get("total_regen_kwh", 0),
                direct_used=row.get("direct_used_kwh", 0),
                stored=row.get("storage_absorbed_kwh", 0),
                final_soc=row.get("final_soc_kwh", 0),
                effective_loss=row.get("effective_regen_loss_kwh", row.get("wasted_kwh", 0)),
                waste=row.get("wasted_kwh", 0),
                grid=row.get("grid_kwh", 0),
                issues=row.get("issue_count", 0),
                assessment=_report_assessment(row.get("assessment", "")),
            )
        )
    lines.extend(["", "## 主要发现", ""])
    if best is None:
        lines.append("- 未生成可评估的场景。")
    elif (
        _as_float(best.get("wasted_kwh", 0.0)) <= 1e-6
        and _as_float(best.get("final_soc_deviation_kwh", 0.0)) <= 1e-6
        and _as_float(best.get("final_soc_device_deviation_kwh", 0.0)) <= 1e-6
        and _as_int(best.get("issue_count", 0)) == 0
    ):
        lines.append(f"- 在场景“{_report_scenario_label(best.get('scenario_id', ''))}”下未发现明显的再生能量浪费问题。")
    else:
        lines.append(f"- 当前运行图仍有优化空间，有效再生损失最低的场景为“{_report_scenario_label(best.get('scenario_id', ''))}”。")
        lines.append(f"- 所有场景共发现 {len(issue_rows)} 个问题，并生成 {len(suggestion_rows)} 条优化建议。")
    if issue_rows:
        issue_digest = _report_issue_digest(issue_rows)
        preview_issues = issue_digest[:REPORT_ISSUE_PREVIEW_LIMIT]
        lines.extend(["", "## 审查问题清单", ""])
        if len(issue_digest) > len(preview_issues):
            lines.append(
                f"- 共发现 {len(issue_rows)} 条问题记录，按“问题类型 + 供电臂/区段”合并为 {len(issue_digest)} 组；"
                f"下表按影响电量从高到低列出前 {len(preview_issues)} 组，逐条明细见 `audit_issues.csv`。"
            )
        else:
            lines.append(
                f"- 共发现 {len(issue_rows)} 条问题记录，合并为 {len(issue_digest)} 组，逐条明细见 `audit_issues.csv`。"
            )
        lines.extend(
            [
                "",
                "| 问题类型 | 供电臂/区段 | 记录数 | 影响电量合计（千瓦时） | 时间范围 | 严重程度 | 原因 |",
                "| --- | --- | ---: | ---: | --- | --- | --- |",
            ]
        )
        for item in preview_issues:
            window = (
                f"{item['start']}—{item['end']}" if item["start"] or item["end"] else "—"
            )
            lines.append(
                "| {issue_type} | {location} | {count} | {impact} | {window} | {severity} | {reason} |".format(
                    issue_type=_report_cell(_report_issue_type_label(item["issue_type"])),
                    location=_report_cell(item["location"] or "—"),
                    count=item["issue_count"],
                    impact=round(float(item["impact_kwh"]), 6),
                    window=_report_cell(window),
                    severity=_report_cell(_report_severity_label(item["severity"])),
                    reason=_report_cell(item["reason"]),
                )
            )
    if suggestion_rows:
        suggestion_digest = _report_suggestion_digest(suggestion_rows)
        preview_suggestions = suggestion_digest[:REPORT_ISSUE_PREVIEW_LIMIT]
        lines.extend(["", "## 优化建议", ""])
        lines.append(
            f"- 共生成 {len(suggestion_rows)} 条建议，合并为 {len(suggestion_digest)} 组；"
            f"下表按出现次数列出前 {len(preview_suggestions)} 组，逐条清单见 `optimization_suggestions.csv`。"
        )
        lines.extend(
            [
                "",
                "| 关联问题类型 | 优先级 | 出现次数 | 建议动作 | 预期效果 |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        for item in preview_suggestions:
            lines.append(
                "| {issue_type} | {priority} | {count} | {action} | {effect} |".format(
                    issue_type=_report_cell(_report_issue_type_label(item["source_issue_type"])),
                    priority=_report_cell(_report_severity_label(item["priority"])),
                    count=item["suggestion_count"],
                    action=_report_cell(item["action"]),
                    effect=_report_cell(item["expected_effect"]),
                )
            )
    if figure_outputs:
        lines.extend(["", "## 图表", ""])
        for label, figure_path in figure_outputs.items():
            lines.append(f"- {REPORT_FIGURE_LABELS.get(label, label)}：`{figure_path}`")
    if visualization_errors:
        lines.extend(["", "## 可视化失败", ""])
        for failure in visualization_errors:
            lines.append(
                f"- {REPORT_FIGURE_LABELS.get(str(failure.get('figure', '')), failure.get('figure', ''))}："
                f"{failure.get('error_type', '')}：{failure.get('message', '')}"
            )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 运行弧根据各车站到达/出发时刻生成，按真实或推断的供电臂边界拆分，并展开为时间片进行结算。",
            "- 再生能量仍根据原型坡度/曲线能耗修正进行估算，尚未采用完整的牵引—制动仿真。",
            "- 连续供电臂区间表仍属于推断草稿，形成正式结论前需要人工确认。",
            "- 在没有已安装储能设备时，储能参数应视为规划假设。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_timetable(
    input_path: Path,
    output_dir: Path,
    power_arm_path: Optional[Path] = None,
    strict_visualizations: bool = False,
    infrastructure_data_dir: Path = DEFAULT_DATA_DIR,
    settlement_time_step_s_override: Optional[int] = None,
) -> Dict[str, object]:
    """函数 audit_timetable：执行该模块中的相关处理逻辑。"""
    if settlement_time_step_s_override is not None and (
        isinstance(settlement_time_step_s_override, bool)
        or not isinstance(settlement_time_step_s_override, int)
        or settlement_time_step_s_override <= 0
    ):
        raise ValueError("settlement_time_step_s_override 必须是正整数。")
    timetable = load_canonical_timetable(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "validation_issues.csv", timetable.validation_report.to_rows())
    _write_csv(output_dir / "timetable_nodes_draft.csv", timetable_node_rows(timetable))
    _write_csv(output_dir / "timetable_arcs_draft.csv", timetable_arc_rows(timetable))
    if not timetable.validation_report.is_valid:
        summary = {
            "input_path": str(input_path),
            "valid": False,
            "error_count": len(timetable.validation_report.errors),
            "warning_count": len(timetable.validation_report.warnings),
        }
        (output_dir / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    infrastructure_data_dir = Path(infrastructure_data_dir)
    power_arm_path = (
        Path(power_arm_path)
        if power_arm_path is not None
        else infrastructure_data_dir / DEFAULT_POWER_ARM_XLSX.name
    )
    try:
        power_sections = load_power_sections(power_arm_path)
        power_limits = load_power_arm_electrical_limits(str(power_arm_path))
    except (OSError, ValueError, csv.Error) as exc:
        summary = {
            "input_path": str(input_path),
            "valid": False,
            "error_count": 1,
            "error_code": "invalid_power_arm_data",
            "error": f"Power-arm data could not be loaded: {exc}",
            "power_arm_path": str(power_arm_path),
        }
        (output_dir / "audit_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
    if not power_sections or not power_limits:
        summary = {
            "input_path": str(input_path),
            "valid": False,
            "error_count": 1,
            "error_code": "missing_or_empty_power_arm_data",
            "error": "Power-arm data is required and must contain valid mainline sections with electrical limits.",
            "power_arm_path": str(power_arm_path),
            "power_section_count": len(power_sections),
            "power_limit_count": len(power_limits),
        }
        (output_dir / "audit_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
    phase_boundary_points = load_phase_boundary_points(power_arm_path)
    infrastructure = load_infrastructure_profile(infrastructure_data_dir)
    storage_efficiency = load_storage_efficiency(infrastructure_data_dir)
    storage_device_parameters = load_storage_device_parameters(infrastructure_data_dir)
    running_arcs = build_timetable_running_arcs(timetable, infrastructure)
    candidate = _timetable_arc_candidate(running_arcs)
    events = build_energy_events(timetable, power_sections, phase_boundary_points)
    event_rows = _event_rows(events)

    issue_rows: List[Dict[str, object]] = []
    scenario_summaries: List[Dict[str, object]] = []
    settlement_rows: List[Dict[str, object]] = []
    time_slice_output_rows: List[Dict[str, object]] = []
    scenarios = [scenario for scenario in timetable.scenarios if scenario.scenario_id == "storage_no_direct"] or [
        TimetableScenario(
            scenario_id="storage_no_direct",
            direct_use_enabled=False,
            storage_enabled=True,
            storage_capacity_kwh=20000.0,
            storage_power_kw=10000.0,
            initial_soc_kwh=0.0,
            settlement_time_step_s=DEFAULT_SETTLEMENT_STEP_S,
            transfer_scope="same_power_arm",
        )
    ]
    if settlement_time_step_s_override is not None:
        scenarios = [replace(scenario, settlement_time_step_s=settlement_time_step_s_override) for scenario in scenarios]
    for scenario in scenarios:
        step_s = _effective_time_step_s(scenario)
        scenario_time_slices = energy_time_slice_rows(candidate, step_s)
        for row in scenario_time_slices:
            time_slice_output_rows.append({"scenario_id": scenario.scenario_id, **row})
        scenario_settlement, scenario_issues, scenario_summary = evaluate_scenario_time_slices(
            scenario_time_slices,
            scenario,
            power_limits,
            default_storage_efficiency=storage_efficiency,
            storage_device_parameters=storage_device_parameters,
        )
        settlement_rows.extend(scenario_settlement)
        issue_rows.extend(scenario_issues)
        scenario_summaries.append(scenario_summary)
    suggestion_rows = build_time_slice_suggestions(issue_rows)

    _write_csv(output_dir / "energy_events.csv", event_rows)
    _write_csv(output_dir / "timetable_running_arcs.csv", timetable_running_arc_rows(running_arcs))
    _write_csv(output_dir / "timetable_energy_time_slices.csv", time_slice_output_rows)
    _write_csv(output_dir / "timetable_power_arm_settlement.csv", settlement_rows)
    _write_csv(output_dir / "audit_issues.csv", issue_rows)
    _write_csv(output_dir / "optimization_suggestions.csv", suggestion_rows)
    _write_csv(output_dir / "scenario_summary.csv", scenario_summaries)
    figure_outputs, visualization_errors = write_audit_visualizations(
        output_dir,
        running_arcs,
        scenario_summaries,
        settlement_rows,
        strict=strict_visualizations,
    )
    visualization_diagnostics = output_dir / "visualization_diagnostics.json"
    visualization_diagnostics.write_text(
        json.dumps(
            {
                "status": "complete" if not visualization_errors else ("partial" if figure_outputs else "failed"),
                "generated_count": len(figure_outputs),
                "error_count": len(visualization_errors),
                "figures": figure_outputs,
                "errors": visualization_errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_markdown_report(
        output_dir / "TIMETABLE_ENERGY_AUDIT_REPORT.md",
        timetable,
        power_sections,
        scenario_summaries,
        issue_rows,
        suggestion_rows,
        figure_outputs,
        visualization_errors,
    )

    summary = {
        "input_path": str(input_path),
        "valid": True,
        "settlement_time_step_s_override": settlement_time_step_s_override,
        "infrastructure_data_dir": str(infrastructure_data_dir),
        "storage_efficiency": storage_efficiency,
        "storage_device_parameters": [
            {
                "storage_section_id": item.storage_section_id,
                "capacity_kwh": item.capacity_kwh,
                "max_charge_power_kw": item.max_charge_power_kw,
                "max_discharge_power_kw": item.max_discharge_power_kw,
                "charge_efficiency": item.charge_efficiency,
                "discharge_efficiency": item.discharge_efficiency,
                "initial_soc_kwh": item.initial_soc_kwh,
                "min_soc_kwh": item.min_soc_kwh,
                "max_soc_kwh": item.max_soc_kwh,
                "available": item.available,
                "data_status": item.data_status,
            }
            for item in storage_device_parameters
        ],
        "visualization_status": "complete" if not visualization_errors else ("partial" if figure_outputs else "failed"),
        "visualization_error_count": len(visualization_errors),
        "train_count": len(timetable.trains),
        "stop_count": len(timetable.stops),
        "power_section_count": len(power_sections),
        "running_arc_count": len(running_arcs),
        "covered_running_section_count": len({arc.parent_arc_id for arc in running_arcs}),
        "time_slice_count": len(time_slice_output_rows),
        "settlement_window_count": len(settlement_rows),
        "energy_event_count": len(events),
        "issue_count": len(issue_rows),
        "suggestion_count": len(suggestion_rows),
        "outputs": {
            "report": str(output_dir / "TIMETABLE_ENERGY_AUDIT_REPORT.md"),
            "events": str(output_dir / "energy_events.csv"),
            "running_arcs": str(output_dir / "timetable_running_arcs.csv"),
            "time_slices": str(output_dir / "timetable_energy_time_slices.csv"),
            "power_arm_settlement": str(output_dir / "timetable_power_arm_settlement.csv"),
            "issues": str(output_dir / "audit_issues.csv"),
            "suggestions": str(output_dir / "optimization_suggestions.csv"),
            "scenario_summary": str(output_dir / "scenario_summary.csv"),
            "figures": figure_outputs,
            "visualization_diagnostics": str(visualization_diagnostics),
            "visualization_error_count": len(visualization_errors),
        },
    }
    (output_dir / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="运行图能量审查：评估用户运行图的再生能量利用与浪费风险。")
    parser.add_argument("input_path", type=Path, help="待审查的运行图文件路径。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="审查结果输出目录。")
    parser.add_argument("--power-arm-path", type=Path, default=None, help="供电臂区间表路径，默认按数据目录推断。")
    parser.add_argument("--strict-visualizations", action="store_true", help="图表生成失败时直接报错，而不是记录为警告。")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础设施数据目录。")
    args = parser.parse_args()
    summary = audit_timetable(
        args.input_path,
        args.output_dir,
        args.power_arm_path,
        strict_visualizations=args.strict_visualizations,
        infrastructure_data_dir=args.data_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary.get("valid", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
