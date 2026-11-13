# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import argparse
import csv
import json
import math

import data_ingestion
from formation_modes import formation_mode_semantics, load_formation_modes, resolve_formation_mode
from smart_meter_adapter import load_smart_meter_directory
from smart_meter_time_matcher import find_station_interval_overlaps_from_dir
from timetable_input import load_canonical_timetable

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_SOURCE_DIR = Path("data") / "source"
DEFAULT_TIMETABLE_TEMPLATE = Path("data_templates") / "running_diagram_template.xlsx"
DEFAULT_OUTPUT_DIR = Path("outputs") / "data_quality_validation"
ROUTE_END_TOLERANCE_KM = 0.01


@dataclass(frozen=True)
class QualityIssue:
    """类 QualityIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    code: str
    source: str
    row: str
    field: str
    message: str
    suggestion: str = ""


class QualityReport:
    """类 QualityReport：执行该模块中的相关处理逻辑。"""
    def __init__(self) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        self.issues: List[QualityIssue] = []

    def add(
        self,
        severity: str,
        code: str,
        source: str,
        row: object = "",
        field: str = "",
        message: str = "",
        suggestion: str = "",
    ) -> None:
        """函数 add：执行该模块中的相关处理逻辑。"""
        self.issues.append(QualityIssue(severity, code, source, "" if row is None else str(row), field, message, suggestion))

    def error(self, code: str, source: str, row: object = "", field: str = "", message: str = "", suggestion: str = "") -> None:
        """函数 error：执行该模块中的相关处理逻辑。"""
        self.add("error", code, source, row, field, message, suggestion)

    def warning(
        self, code: str, source: str, row: object = "", field: str = "", message: str = "", suggestion: str = ""
    ) -> None:
        """函数 warning：执行该模块中的相关处理逻辑。"""
        self.add("warning", code, source, row, field, message, suggestion)

    @property
    def errors(self) -> List[QualityIssue]:
        """函数 errors：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[QualityIssue]:
        """函数 warnings：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """函数 is_valid：执行该模块中的相关处理逻辑。"""
        return not self.errors

    def to_rows(self) -> List[Dict[str, str]]:
        """函数 to_rows：执行该模块中的相关处理逻辑。"""
        return [asdict(issue) for issue in self.issues]

    def summary(self) -> Dict[str, object]:
        """函数 summary：执行该模块中的相关处理逻辑。"""
        by_source: Dict[str, Dict[str, int]] = {}
        by_code: Dict[str, int] = {}
        for issue in self.issues:
            bucket = by_source.setdefault(issue.source, {"errors": 0, "warnings": 0})
            bucket["errors" if issue.severity == "error" else "warnings"] += 1
            by_code[issue.code] = by_code.get(issue.code, 0) + 1
        blocking_flows: List[Dict[str, str]] = []
        if by_code.get("smart_meter_station_interval_overlap"):
            blocking_flows.append(
                {
                    "flow": "smart_meter_energy_calibration",
                    "status": "degraded",
                    "reason_code": "smart_meter_station_interval_overlap",
                    "reason": "nhtj_jkfile_station 中同一 trainid 存在重叠任务；代表性校准应剔除重叠站间区间，仅使用干净的匹配样本。",
                }
            )
        return {
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "blocking_flows": blocking_flows,
            "by_source": by_source,
            "by_code": dict(sorted(by_code.items())),
        }


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _optional_float(value: Any) -> Optional[float]:
    """函数 _optional_float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    try:
        value_float = float(text)
    except ValueError:
        return None
    if not math.isfinite(value_float):
        return None
    return value_float


_TRUE_VALUES = {"1", "true", "yes", "y", "是", "有", "available"}
_FALSE_VALUES = {"0", "false", "no", "n", "否", "无", "unavailable"}


def _optional_bool(value: Any) -> Optional[bool]:
    """函数 _optional_bool：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return None


def _xlsx_rows(path: Path, sheet_name: str, report: QualityReport, required_headers: Sequence[str]) -> List[Dict[str, Any]]:
    """函数 _xlsx_rows：执行该模块中的相关处理逻辑。"""
    source = f"{path}:{sheet_name}"
    if openpyxl is None:
        report.error("missing_openpyxl", str(path), "", "", "校验 Excel 源数据需要安装 openpyxl。")
        return []
    if not path.exists():
        report.error("missing_source_file", str(path), "", "", "应有的源工作簿缺失。")
        return []
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            report.error("missing_sheet", str(path), "", sheet_name, f"工作簿中不存在工作表 {sheet_name}。")
            return []
        sheet = workbook[sheet_name]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [_clean(value) for value in header_row]
        for header in required_headers:
            if header not in headers:
                report.error("missing_column", source, 1, header, f"缺少必需列 {header}。")
        rows: List[Dict[str, Any]] = []
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            item = {headers[idx]: value for idx, value in enumerate(values) if idx < len(headers) and headers[idx]}
            if any(_clean(value) for value in item.values()):
                item["_row_number"] = row_number
                rows.append(item)
        return rows
    finally:
        workbook.close()


def _csv_rows(path: Path, report: QualityReport, required_headers: Sequence[str]) -> List[Dict[str, str]]:
    """函数 _csv_rows：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        report.error("missing_algorithm_file", str(path), "", "", "算法输入 CSV 缺失。")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        for header in required_headers:
            if header not in headers:
                report.error("missing_column", str(path), 1, header, f"缺少必需列 {header}。")
        rows = [dict(row, _row_number=str(idx)) for idx, row in enumerate(reader, start=2)]
    return [row for row in rows if any(_clean(value) for key, value in row.items() if key != "_row_number")]


def _check_interval_order(
    items: List[Dict[str, Any]],
    source: str,
    report: QualityReport,
    gap_code: str,
    overlap_code: str,
    tolerance_km: float,
    group_label: str = "",
) -> None:
    """函数 _check_interval_order：执行该模块中的相关处理逻辑。"""
    ordered = sorted(items, key=lambda item: (item["min"], item["max"]))
    for left, right in zip(ordered[:-1], ordered[1:]):
        gap = right["min"] - left["max"]
        row = f"{left['row']}->{right['row']}"
        label = f"{group_label} " if group_label else ""
        if gap > tolerance_km:
            report.warning(
                gap_code,
                source,
                row,
                "start_km/end_km",
                f"{label}存在 {gap:.6f} 千米的断档。",
            )
        elif gap < -tolerance_km:
            report.error(
                overlap_code,
                source,
                row,
                "start_km/end_km",
                f"{label}与上一段重叠 {-gap:.6f} 千米。",
            )


def validate_real_data_directory(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_real_data_directory：执行该模块中的相关处理逻辑。"""
    validation = data_ingestion.validate_real_data_bundle(data_dir)
    for issue in validation.issues:
        report.add(
            issue.severity,
            f"real_data_{issue.code}",
            f"{data_dir}/{issue.file}",
            issue.row or "",
            issue.field,
            issue.message,
            issue.suggestion,
        )


def validate_power_arm_intervals(source_dir: Path, report: QualityReport) -> None:
    """函数 validate_power_arm_intervals：执行该模块中的相关处理逻辑。"""
    path = source_dir / "power_arm" / "power_arm_continuous_intervals.xlsx"
    rows = _xlsx_rows(
        path,
        "供电臂连续区间表",
        report,
        ("section_id", "direction", "start_km", "end_km", "length_km"),
    )
    _validate_power_arm_rows(rows, f"{path}:供电臂连续区间表", report, flag_manual_review=True)


def _validate_power_arm_rows(
    rows: List[Dict[str, Any]],
    source: str,
    report: QualityReport,
    flag_manual_review: bool,
    require_operational_fields: bool = False,
) -> None:
    """函数 _validate_power_arm_rows：执行该模块中的相关处理逻辑。"""
    intervals: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        row_number = row.get("_row_number", "")
        section_id = _clean(row.get("section_id"))
        road = _clean(row.get("road")) or "unknown_road"
        direction = _clean(row.get("direction"))
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        length = _optional_float(row.get("length_km"))
        if not section_id:
            report.error("power_arm_missing_id", source, row_number, "section_id", "供电臂区间缺少 section_id。")
        elif section_id in seen_ids:
            report.error("power_arm_duplicate_id", source, row_number, "section_id", f"section_id 重复：{section_id}。")
        seen_ids.add(section_id)
        if direction not in {"上行", "下行", "单线"}:
            report.warning("power_arm_unknown_direction", source, row_number, "direction", "Direction should be 上行、下行 or 单线.")
        if start is None or end is None:
            report.error("power_arm_invalid_km", source, row_number, "start_km/end_km", "start_km 与 end_km 必须为数值。")
            continue
        delta = abs(end - start)
        if delta <= 0:
            report.error("power_arm_nonpositive_length", source, row_number, "start_km/end_km", "供电臂区间长度必须为正。")
        if length is not None and abs(delta - length) > 0.01:
            report.warning(
                "power_arm_length_mismatch",
                source,
                row_number,
                "length_km",
                f"length_km={length:.6f} 与 abs(end-start)={delta:.6f} 不一致。",
            )
        operational_fields = (
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
            "storage_available",
            "storage_section_id",
            "storage_start_km",
            "storage_end_km",
        )
        if require_operational_fields or any(field in row for field in operational_fields):
            for field in (
                "max_traction_supply_kw",
                "max_regen_absorption_kw",
                "max_grid_feedback_kw",
            ):
                value = _optional_float(row.get(field))
                if value is None or value < 0.0:
                    report.error(
                        "power_arm_invalid_electrical_limit",
                        source,
                        row_number,
                        field,
                        f"{field} 必须为非负有限数值。",
                    )

            storage_text = _clean(row.get("storage_available"))
            storage_available = _optional_bool(storage_text)
            if not storage_text or storage_available is None:
                report.error(
                    "power_arm_invalid_storage_available",
                    source,
                    row_number,
                    "storage_available",
                    "storage_available 必须显式给出布尔值。",
                )
            storage_id = _clean(row.get("storage_section_id"))
            storage_start_text = _clean(row.get("storage_start_km"))
            storage_end_text = _clean(row.get("storage_end_km"))
            if storage_available is True and not storage_id:
                report.error(
                    "power_arm_storage_id_missing",
                    source,
                    row_number,
                    "storage_section_id",
                    "启用储能的区间必须提供 storage_section_id。",
                )
            if storage_available is False and storage_id:
                report.error(
                    "power_arm_storage_id_without_availability",
                    source,
                    row_number,
                    "storage_section_id",
                    "storage_available 为 false 时，storage_section_id 必须为空。",
                )
            if bool(storage_start_text) != bool(storage_end_text):
                report.error(
                    "power_arm_incomplete_storage_bounds",
                    source,
                    row_number,
                    "storage_start_km/storage_end_km",
                    "storage_start_km 与 storage_end_km 必须成对提供。",
                )
            elif storage_start_text and storage_end_text:
                storage_start = _optional_float(storage_start_text)
                storage_end = _optional_float(storage_end_text)
                if (
                    storage_start is None
                    or storage_end is None
                    or math.isclose(storage_start, storage_end, abs_tol=1e-9)
                ):
                    report.error(
                        "power_arm_invalid_storage_bounds",
                        source,
                        row_number,
                        "storage_start_km/storage_end_km",
                        "储能边界必须是互不相同的有限数值。",
                    )
                if storage_available is False:
                    report.error(
                        "power_arm_storage_bounds_without_availability",
                        source,
                        row_number,
                        "storage_start_km/storage_end_km",
                        "storage_available 为 false 时，储能边界必须为空。",
                    )
        review_status = _clean(row.get("needs_manual_review"))
        if flag_manual_review and (review_status in {"缺失", "待确认"} or review_status.lower() in {"true", "1", "yes", "y"}):
            report.warning(
                "power_arm_manual_review",
                source,
                row_number,
                "needs_manual_review",
                "该区间被标记为缺失或需人工复核。",
            )
        intervals.append({"row": row_number, "road": road, "direction": direction or "unknown", "min": min(start, end), "max": max(start, end)})

    group_keys = sorted({(item["road"], item["direction"]) for item in intervals})
    for road, direction in group_keys:
        group_rows = [item for item in intervals if item["road"] == road and item["direction"] == direction]
        _check_interval_order(
            group_rows,
            source,
            report,
            "power_arm_gap",
            "power_arm_overlap",
            0.001,
            f"{road}/{direction} 供电臂区间",
        )


def validate_gradient_table(source_dir: Path, report: QualityReport) -> None:
    """函数 validate_gradient_table：执行该模块中的相关处理逻辑。"""
    path = source_dir / "geometry" / "gradients.xlsx"
    rows = _xlsx_rows(path, "坡度表", report, ("source_image", "start_km", "end_km", "length(m)", "坡度(千分率)"))
    source = f"{path}:坡度表"
    segments: List[Dict[str, Any]] = []
    for row in rows:
        row_number = row["_row_number"]
        source_image = _clean(row.get("source_image"))
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        length_m = _optional_float(row.get("length(m)"))
        gradient = _optional_float(row.get("坡度(千分率)"))
        if not source_image:
            report.warning("gradient_missing_source_image", source, row_number, "source_image", "坡度记录没有来源图号。")
        if start is None or end is None or length_m is None or gradient is None:
            report.error("gradient_invalid_number", source, row_number, "", "start_km, end_km, length(m), and 坡度(千分率) must be numeric.")
            continue
        if abs(end - start) <= 0 or length_m <= 0:
            report.error("gradient_nonpositive_length", source, row_number, "length(m)", "坡度分段长度必须为正。")
        expected_m = abs(end - start) * 1000.0
        if abs(expected_m - length_m) > 1.0:
            report.warning(
                "gradient_length_mismatch",
                source,
                row_number,
                "length(m)",
                f"length(m)={length_m:.3f} 与 abs(end-start)*1000={expected_m:.3f} 不一致。",
                "若长度经过人工修正，需重新计算起止公里标累计值。",
            )
        if abs(gradient) > 35:
            report.warning(
                "gradient_large_value",
                source,
                row_number,
                "坡度(千分率)",
                f"本线坡度 {gradient:.3f}‰ 异常偏大，请确认正负号与单位。",
            )
        segments.append({"row": row_number, "min": min(start, end), "max": max(start, end)})

    _check_interval_order(segments, source, report, "gradient_gap", "gradient_overlap", 0.005, "坡度表")


def validate_algorithm_derived_tables(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_algorithm_derived_tables：执行该模块中的相关处理逻辑。"""
    validate_algorithm_gradients(data_dir, report)
    validate_algorithm_curves(data_dir, report)
    validate_algorithm_power_arms(data_dir, report)
    validate_algorithm_segments(data_dir, report)


def validate_algorithm_gradients(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_algorithm_gradients：执行该模块中的相关处理逻辑。"""
    path = data_dir / "gradients.csv"
    rows = _csv_rows(path, report, ("gradient_id", "source_image", "start_km", "end_km", "length_m", "gradient_per_mille"))
    intervals: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        row_number = row["_row_number"]
        gradient_id = _clean(row.get("gradient_id"))
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        length_m = _optional_float(row.get("length_m"))
        gradient = _optional_float(row.get("gradient_per_mille"))
        if not gradient_id:
            report.error("algorithm_gradient_missing_id", str(path), row_number, "gradient_id", "坡度记录缺少 gradient_id。")
        elif gradient_id in seen_ids:
            report.error("algorithm_gradient_duplicate_id", str(path), row_number, "gradient_id", f"gradient_id 重复：{gradient_id}。")
        seen_ids.add(gradient_id)
        if start is None or end is None or length_m is None or gradient is None:
            report.error("algorithm_gradient_invalid_number", str(path), row_number, "", "坡度 CSV 的起止里程、长度或坡度存在非数值。")
            continue
        if end <= start or length_m <= 0:
            report.error("algorithm_gradient_nonpositive_length", str(path), row_number, "start_km/end_km", "坡度 CSV 的分段长度必须为正。")
        if abs((end - start) * 1000.0 - length_m) > 1.0:
            report.warning("algorithm_gradient_length_mismatch", str(path), row_number, "length_m", "length_m 与「终点减起点」不一致。")
        if abs(gradient) > 35:
            report.warning("algorithm_gradient_large_value", str(path), row_number, "gradient_per_mille", "坡度数值异常偏大，请确认正负号与单位。")
        intervals.append({"row": row_number, "min": start, "max": end})
    _check_interval_order(intervals, str(path), report, "algorithm_gradient_gap", "algorithm_gradient_overlap", 0.005, "算法坡度 CSV")


def validate_algorithm_curves(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_algorithm_curves：执行该模块中的相关处理逻辑。"""
    path = data_dir / "curves.csv"
    rows = _csv_rows(path, report, ("curve_id", "start_km", "end_km", "radius_m", "length_m", "direction"))
    seen_ids: set[str] = set()
    for row in rows:
        row_number = row["_row_number"]
        curve_id = _clean(row.get("curve_id"))
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        radius = _optional_float(row.get("radius_m"))
        length_m = _optional_float(row.get("length_m"))
        if not curve_id:
            report.error("algorithm_curve_missing_id", str(path), row_number, "curve_id", "曲线记录缺少 curve_id。")
        elif curve_id in seen_ids:
            report.error("algorithm_curve_duplicate_id", str(path), row_number, "curve_id", f"curve_id 重复：{curve_id}。")
        seen_ids.add(curve_id)
        if start is None or end is None or radius is None:
            report.error("algorithm_curve_invalid_number", str(path), row_number, "", "曲线 CSV 的起止里程或半径存在非数值。")
            continue
        if end <= start or radius <= 0:
            report.error("algorithm_curve_nonpositive_value", str(path), row_number, "start_km/end_km/radius_m", "曲线分段长度与半径必须为正。")
        if length_m is not None and abs((end - start) * 1000.0 - length_m) > 80.0:
            report.warning(
                "algorithm_curve_length_mismatch",
                str(path),
                row_number,
                "length_m",
                "曲线长度与「终点减起点」差异较大；若源表长度取弦长或曲线长而非投影里程，可保留。",
            )


def validate_algorithm_power_arms(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_algorithm_power_arms：执行该模块中的相关处理逻辑。"""
    path = data_dir / "power_arm_intervals.csv"
    rows = _csv_rows(
        path,
        report,
        (
            "section_id",
            "road",
            "direction",
            "start_km",
            "end_km",
            "length_km",
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
            "storage_available",
            "storage_section_id",
        ),
    )
    _validate_power_arm_rows(
        rows,
        str(path),
        report,
        flag_manual_review=False,
        require_operational_fields=True,
    )


def validate_algorithm_segments(data_dir: Path, report: QualityReport) -> None:
    """函数 validate_algorithm_segments：执行该模块中的相关处理逻辑。"""
    path = data_dir / "segments.csv"
    rows = _csv_rows(path, report, ("segment_id", "start_km", "end_km", "gradient_per_mille", "terrain", "speed_limit_kmh"))
    intervals: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_end: Optional[float] = None
    for row in rows:
        row_number = row["_row_number"]
        segment_id = _clean(row.get("segment_id"))
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        gradient = _optional_float(row.get("gradient_per_mille"))
        speed = _optional_float(row.get("speed_limit_kmh"))
        if not segment_id:
            report.error("algorithm_segment_missing_id", str(path), row_number, "segment_id", "分段记录缺少 segment_id。")
        elif segment_id in seen_ids:
            report.error("algorithm_segment_duplicate_id", str(path), row_number, "segment_id", f"segment_id 重复：{segment_id}。")
        seen_ids.add(segment_id)
        if start is None or end is None or gradient is None or speed is None:
            report.error("algorithm_segment_invalid_number", str(path), row_number, "", "分段 CSV 的起止里程、坡度或限速存在非数值。")
            continue
        if end <= start:
            report.error("algorithm_segment_nonpositive_length", str(path), row_number, "start_km/end_km", "分段的区间长度必须为正。")
        if speed <= 0:
            report.error("algorithm_segment_invalid_speed", str(path), row_number, "speed_limit_kmh", "分段的限速必须为正。")
        if last_end is not None and start < last_end - 0.005:
            report.error("algorithm_segment_order_reversal", str(path), row_number, "start_km", "分段起点早于上一分段的终点。")
        last_end = end
        intervals.append({"row": row_number, "min": start, "max": end})

    _check_interval_order(intervals, str(path), report, "algorithm_segment_gap", "algorithm_segment_overlap", 0.005, "算法分段 CSV")
    route_end = _route_end_km(data_dir)
    if intervals:
        start_min = min(item["min"] for item in intervals)
        end_max = max(item["max"] for item in intervals)
        if abs(start_min) > ROUTE_END_TOLERANCE_KM:
            report.warning("algorithm_segment_start_not_zero", str(path), "", "start_km", f"分段起点为 {start_min:.6f} 千米，不是 0。")
        if route_end is not None and abs(end_max - route_end) > ROUTE_END_TOLERANCE_KM:
            report.warning(
                "algorithm_segment_route_end_mismatch",
                str(path),
                "",
                "end_km",
                f"分段终点为 {end_max:.6f} 千米，线路元数据 total_length_km={route_end:.6f}。",
            )


def _route_end_km(data_dir: Path) -> Optional[float]:
    """函数 _route_end_km：执行该模块中的相关处理逻辑。"""
    path = data_dir / "route_metadata.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _optional_float((payload.get("route") or {}).get("total_length_km"))


def validate_formation_mapping(data_dir: Path, timetable_path: Path, report: QualityReport) -> None:
    """函数 validate_formation_mapping：执行该模块中的相关处理逻辑。"""
    formation_path = data_dir / "train_formation_modes_2025.csv"
    source = str(formation_path)
    modes = list(load_formation_modes(formation_path))
    if not modes:
        report.error("formation_catalog_missing_or_empty", source, "", "", "编组目录缺失或为空。")
        return
    seen_keys: set[tuple[str, str, str, int]] = set()
    for idx, mode in enumerate(modes, start=2):
        key = (mode.category, mode.load_state, mode.formation_mode, mode.wagon_count)
        if key in seen_keys:
            report.error("formation_duplicate_key", source, idx, "category/load_state/formation_mode/wagon_count", f"编组键重复：{key}。")
        seen_keys.add(key)
        if mode.mass_tons <= 0:
            report.error("formation_invalid_mass", source, idx, "mass_tons", "编组质量 mass_tons 必须为正。")
        if mode.formation_mode and formation_mode_semantics(mode.formation_mode) is None:
            report.warning(
                "formation_mode_semantics_unknown",
                source,
                idx,
                "formation_mode",
                f"编组模式 {mode.formation_mode} 尚无确认的机车布置含义。",
            )

    by_common_key: Dict[tuple[str, str, int], Dict[str, float]] = {}
    for mode in modes:
        bucket = by_common_key.setdefault((mode.category, mode.formation_mode, mode.wagon_count), {})
        bucket[mode.load_state] = mode.mass_tons
    for key, masses in sorted(by_common_key.items()):
        if "heavy" in masses and "empty" in masses and masses["empty"] > masses["heavy"]:
            report.warning(
                "formation_empty_heavier_than_heavy",
                source,
                "",
                "mass_tons",
                f"{key} 的空车质量 {masses['empty']} 吨大于重车质量 {masses['heavy']} 吨。",
            )

    if timetable_path.exists():
        timetable = load_canonical_timetable(timetable_path)
        for train in timetable.trains:
            if train.mass_t is None:
                resolved = resolve_formation_mode(
                    modes,
                    category=train.formation_category,
                    load_state=train.load_state,
                    formation_mode=train.formation_mode,
                    wagon_count=train.wagon_count,
                    free_text=train.formation,
                )
                if resolved is None:
                    report.warning(
                        "timetable_formation_unresolved",
                        str(timetable_path),
                        train.train_id,
                        "formation_category/load_state/formation_mode/wagon_count",
                        f"列车 {train.train_id} 没有显式质量，且无法从编组目录唯一解析。",
                    )


def validate_timetable_template(timetable_path: Path, report: QualityReport) -> None:
    """函数 validate_timetable_template：执行该模块中的相关处理逻辑。"""
    if not timetable_path.exists():
        report.warning("missing_timetable_template", str(timetable_path), "", "", "运行图模板缺失。")
        return
    timetable = load_canonical_timetable(timetable_path)
    for issue in timetable.validation_report.issues:
        report.add(issue.severity, f"timetable_{issue.code}", f"{timetable_path}:{issue.sheet}", issue.row or "", issue.field, issue.message)
    for train in timetable.trains:
        if train.mass_t is None:
            report.warning("timetable_missing_train_mass", str(timetable_path), train.train_id, "mass_t", f"列车 {train.train_id} 按编组查表后仍无 mass_t。")
        if not train.mass_source:
            report.warning("timetable_missing_mass_source", str(timetable_path), train.train_id, "mass_source", f"列车 {train.train_id} 缺少 mass_source 来源标记。")
    stops_by_train: Dict[str, List[Any]] = {}
    for stop in timetable.stops:
        stops_by_train.setdefault(stop.train_id, []).append(stop)
    for train_id, stops in stops_by_train.items():
        ordered = sorted(stops, key=lambda item: item.seq)
        for left, right in zip(ordered[:-1], ordered[1:]):
            if right.seq <= left.seq:
                report.error("timetable_nonincreasing_seq", str(timetable_path), train_id, "seq", f"列车 {train_id} 的序号不是递增的。")
            if right.departure_time_s < left.departure_time_s:
                report.error("timetable_time_reversal", str(timetable_path), train_id, "departure_time", f"列车 {train_id} 的发车时刻倒序。")


def validate_smart_meter_data(smart_meter_dir: Path, report: QualityReport) -> None:
    """函数 validate_smart_meter_data：执行该模块中的相关处理逻辑。"""
    if not smart_meter_dir.exists():
        report.warning(
            "smart_meter_source_missing",
            str(smart_meter_dir),
            "",
            "",
            "电表源目录缺失；在供给方格式确认前，校准数据属可选项。",
        )
        return
    result = load_smart_meter_directory(smart_meter_dir, max_rows_per_file=200)
    unknown_direction_count = 0
    for issue in result.issues:
        if issue.code == "smart_meter_unknown_direction_code":
            unknown_direction_count += 1
            continue
        report.add(
            issue.severity,
            issue.code,
            issue.source,
            issue.row,
            issue.field,
            issue.message,
            issue.suggestion,
        )
    if unknown_direction_count:
        report.warning(
            "smart_meter_unknown_direction_codes",
            str(smart_meter_dir),
            "",
            "sxx",
            f"抽样的电表记录中有 {unknown_direction_count} 条的 sxx 方向码不在已确认的 1=下行、2=上行映射内。",
            "请向数据提供方确认 0 是否有效，以及它对应上行还是下行。",
        )
    if result.records and not any(record.direction_label != "unknown" for record in result.records):
        report.warning(
            "smart_meter_direction_all_unknown_in_sample",
            str(smart_meter_dir),
            "",
            "sxx",
            "抽样的电表记录中没有已确认的方向码 1/2。",
            "请向数据提供方确认 0 是否有效，以及它对应上行还是下行。",
        )


def validate_station_interval_overlaps(smart_meter_dir: Path, report: QualityReport) -> None:
    """函数 validate_station_interval_overlaps：执行该模块中的相关处理逻辑。"""
    if not smart_meter_dir.exists():
        return
    # 此处只流式读取站间区段 CSV。Ammeter_info 与该警告无关；此前为每个车站行构造完整 IntervalRecord，
    # 会使大规模电表导出的 validate-data 看起来像卡住。
    overlaps = find_station_interval_overlaps_from_dir(smart_meter_dir)
    if not overlaps:
        return
    examples = []
    for overlap in overlaps[:5]:
        examples.append(
            f"{overlap.trainid}: {overlap.left_source_file}:{overlap.left_source_row} "
            f"{overlap.left_starttime:%Y-%m-%d %H:%M:%S}-{overlap.left_endtime:%Y-%m-%d %H:%M:%S} "
            f"overlaps {overlap.right_source_file}:{overlap.right_source_row} "
            f"{overlap.right_starttime:%Y-%m-%d %H:%M:%S}-{overlap.right_endtime:%Y-%m-%d %H:%M:%S}"
        )
    report.warning(
        "smart_meter_station_interval_overlap",
        str(smart_meter_dir),
        "",
        "starttime/endtime",
        f"同一 trainid 的站间区间任务存在重叠。重叠对数：{len(overlaps)}。示例：" + "; ".join(examples),
        "代表性校准样本应排除重叠的站间区间；不重叠的干净记录仍可用于验证覆盖。",
    )


_PROVENANCE_PLACEHOLDER_TOKENS = (
    "virtual",
    "planning",
    "preset",
    "placeholder",
    "heuristic",
    "inferred",
    "assumption",
    "pending",
    "experimental",
    "unknown",
    "default",
    "non_binding",
    "scenario_controlled",
    "not_credited",
)
_PROVENANCE_CONFIRMED_TOKENS = ("official", "real", "measured", "verified", "confirmed")


def _provenance_severity(require_official_data: bool) -> str:
    """函数 _provenance_severity：执行该模块中的相关处理逻辑。"""
    return "error" if require_official_data else "warning"


def _add_provenance_issue(
    report: QualityReport,
    require_official_data: bool,
    code: str,
    source: str,
    field: str,
    message: str,
    suggestion: str,
    row: object = "",
) -> None:
    """函数 _add_provenance_issue：执行该模块中的相关处理逻辑。"""
    getattr(report, _provenance_severity(require_official_data))(
        code, source, row, field, message, suggestion
    )


def _status_is_placeholder(value: object) -> bool:
    """函数 _status_is_placeholder：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    return not text or any(token in text for token in _PROVENANCE_PLACEHOLDER_TOKENS)


def _status_is_confirmed(value: object) -> bool:
    """函数 _status_is_confirmed：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    return any(token in text for token in _PROVENANCE_CONFIRMED_TOKENS) and not _status_is_placeholder(text)


def validate_data_provenance(
    data_dir: Path,
    report: QualityReport,
    require_official_data: bool = False,
) -> None:
    """Check machine-readable provenance before results are treated as official.

    The normal workflow reports placeholders as warnings because the current
    project intentionally contains planning values. ``require_official_data``
    turns the same findings into blocking errors for production-style runs.
    """
    route_path = data_dir / "route_metadata.json"
    try:
        route = json.loads(route_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        route = {}
    if not isinstance(route, dict):
        route = {}
    route_status = route.get("data_status")
    if _status_is_placeholder(route_status):
        _add_provenance_issue(
            report,
            require_official_data,
            "provenance_route_status_missing_or_placeholder",
            str(route_path),
            "data_status",
            "route_metadata.json 必须声明已确认或官方的 data_status，才能用于生产。",
            "按已批准的数据源填写 data_status；规划值继续保持 virtual，仅用于仿真。",
        )
    source_metadata = route.get("source_metadata")
    if not isinstance(source_metadata, dict):
        _add_provenance_issue(
            report,
            require_official_data,
            "provenance_source_metadata_missing",
            str(route_path),
            "source_metadata",
            "route_metadata.json 缺少机器可读的 source_metadata 块。",
            "在将结果视为官方前，请登记来源文件、假设项与待确认事项。",
        )
    else:
        assumptions = source_metadata.get("explicit_assumptions", [])
        confirmations = source_metadata.get("needs_confirmation", [])
        if isinstance(assumptions, list) and assumptions:
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_explicit_assumptions_present",
                str(route_path),
                "source_metadata.explicit_assumptions",
                f"数据集声明了 {len(assumptions)} 条显式假设。",
                "在发布官方能耗结果前，请逐条解决或显式接受这些假设。",
            )
        if isinstance(confirmations, list) and confirmations:
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_confirmation_items_present",
                str(route_path),
                "source_metadata.needs_confirmation",
                f"数据集仍有 {len(confirmations)} 项待确认事项。",
                "请取得数据提供方确认后重建运行数据集。",
            )

    battery_path = data_dir / "battery.json"
    try:
        battery = json.loads(battery_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        battery = {}
    if isinstance(battery, dict):
        status = battery.get("data_status")
        planning = _optional_bool(battery.get("planning_assumption"))
        if _status_is_placeholder(status) or planning is True:
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_battery_placeholder",
                str(battery_path),
                "data_status/planning_assumption",
                "电池参数被标记为规划值、虚拟值或尚未确认。",
                "请用已批准的设备数据替换容量、功率、效率、电价与折旧参数。",
            )

    resource_path = data_dir / "resource_config.json"
    try:
        resource = json.loads(resource_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        resource = {}
    metadata = resource.get("_metadata") if isinstance(resource, dict) else None
    resource_status = metadata.get("data_status") if isinstance(metadata, dict) else None
    if _status_is_placeholder(resource_status):
        _add_provenance_issue(
            report,
            require_official_data,
            "provenance_resource_config_placeholder",
            str(resource_path),
            "_metadata.data_status",
            "资源配置未标记为已确认或官方。",
            "请用已批准的实际运营数据替换启发式车站、咽喉、区间与初始库存取值。",
        )

    trains_path = data_dir / "trains.csv"
    try:
        with trains_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError):
        rows = []
    if rows:
        status_columns = (
            "mass_data_status",
            "traction_data_status",
            "brake_data_status",
            "resistance_data_status",
            "power_data_status",
        )
        headers = set(rows[0])
        if "mass_data_status" not in headers:
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_train_status_column_missing",
                str(trains_path),
                "mass_data_status",
                "trains.csv 未标明质量取值的来源。",
                "请为质量与各项动力学参数补充逐行状态列。",
            )
        missing_dynamic = [name for name in status_columns[1:] if name not in headers]
        if missing_dynamic:
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_train_dynamic_status_columns_missing",
                str(trains_path),
                ",".join(missing_dynamic),
                "trains.csv 缺少牵引、制动、阻力或功率参数的来源字段。",
                "请补齐缺失的状态列；仅靠备注无法做机器可读的来源校验。",
            )
        for row_number, row in enumerate(rows, start=2):
            for field in status_columns:
                if field in headers and not _status_is_confirmed(row.get(field)):
                    _add_provenance_issue(
                        report,
                        require_official_data,
                        "provenance_train_parameter_unconfirmed",
                        str(trains_path),
                        field,
                        f"列车第 {row_number} 行的 {field} 缺少已确认来源。",
                        "请使用已批准的状态值，如 official、measured、verified 或 confirmed。",
                        row=row_number,
                    )

    zones_path = data_dir / "energy_transfer_zones.csv"
    try:
        with zones_path.open("r", encoding="utf-8-sig", newline="") as handle:
            zone_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError):
        zone_rows = []
    if zone_rows:
        if "data_status" not in set(zone_rows[0]):
            _add_provenance_issue(
                report,
                require_official_data,
                "provenance_energy_zone_status_column_missing",
                str(zones_path),
                "data_status",
                "能量转移分区没有逐行来源状态。",
                "请把每个分区标记为 official、measured、verified 或 planning_virtual。",
            )
        else:
            for row_number, row in enumerate(zone_rows, start=2):
                if _status_is_placeholder(row.get("data_status")):
                    _add_provenance_issue(
                        report,
                        require_official_data,
                        "provenance_energy_zone_placeholder",
                        str(zones_path),
                        "data_status",
                        f"能量转移分区第 {row_number} 行未确认或非官方。",
                        "请用已批准的设备数据替换规划的分区边界与效率。",
                        row=row_number,
                    )

    power_path = data_dir / "power_arm_intervals.csv"
    try:
        with power_path.open("r", encoding="utf-8-sig", newline="") as handle:
            power_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError):
        power_rows = []
    if power_rows:
        headers = set(power_rows[0])
        for field in ("electrical_limit_status", "storage_status"):
            if field not in headers:
                _add_provenance_issue(
                    report,
                    require_official_data,
                    "provenance_power_arm_status_column_missing",
                    str(power_path),
                    field,
                    f"power_arm_intervals.csv 缺少 {field} 来源字段。",
                    "请补充逐行状态，避免把默认电气限值误当作实测限值。",
                )
        if "electrical_limit_status" in headers:
            unconfirmed = sum(1 for row in power_rows if _status_is_placeholder(row.get("electrical_limit_status")))
            if unconfirmed:
                _add_provenance_issue(
                    report,
                    require_official_data,
                    "provenance_power_arm_limits_placeholder",
                    str(power_path),
                    "electrical_limit_status",
                    f"有 {unconfirmed} 行供电臂使用未确认的电气限值。",
                    "请用已批准的牵引、再生与反馈限值替换非约束性默认值。",
                )


def validate_all(
    data_dir: Path,
    source_dir: Path,
    timetable_path: Path,
    require_official_data: bool = False,
) -> QualityReport:
    """函数 validate_all：执行该模块中的相关处理逻辑。"""
    report = QualityReport()
    validate_real_data_directory(data_dir, report)
    validate_power_arm_intervals(source_dir, report)
    validate_gradient_table(source_dir, report)
    validate_algorithm_derived_tables(data_dir, report)
    validate_formation_mapping(data_dir, timetable_path, report)
    validate_timetable_template(timetable_path, report)
    validate_station_interval_overlaps(source_dir / "smart_meter", report)
    validate_smart_meter_data(source_dir / "smart_meter", report)
    validate_data_provenance(data_dir, report, require_official_data=require_official_data)
    return report


def write_report(report: QualityReport, output_dir: Path) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = report.to_rows()
    with (output_dir / "data_quality_issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["severity", "code", "source", "row", "field", "message", "suggestion"])
        writer.writeheader()
        writer.writerows(rows)
    summary = report.summary()
    (output_dir / "data_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 数据质量报告",
        "",
        f"- 是否通过：`{'是' if report.is_valid else '否'}`",
        f"- 错误：{len(report.errors)} 条",
        f"- 警告：{len(report.warnings)} 条",
        "",
        "## 主要发现",
        "",
    ]
    if summary.get("blocking_flows"):
        for item in summary["blocking_flows"]:
            lines.extend(
                [
                    f"- 流程 `{item['flow']}`：状态 `{item['status']}`。",
                    f"  原因：`{item['reason_code']}`，{item['reason']}",
                "  规则：重叠的站间作业必须从代表性校准样本中排除；不重叠的干净记录仍可用于验证覆盖。",
                    "",
                ]
            )
    else:
        lines.extend(["- 未发现会阻断当前算法流程的数据质量问题。", ""])
    lines.extend(
        [
            "## 问题清单",
            "",
            "| 级别 | 代码 | 来源 | 行号 | 字段 | 说明 | 建议 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for issue in rows[:250]:
        lines.append(
            "| {severity} | `{code}` | `{source}` | {row} | `{field}` | {message} | {suggestion} |".format(
                severity={"error": "错误", "warning": "警告"}.get(issue["severity"], issue["severity"]),
                code=issue["code"],
                source=issue["source"],
                row=issue["row"],
                field=issue["field"],
                message=str(issue["message"]).replace("|", "/"),
                suggestion=str(issue["suggestion"]).replace("|", "/"),
            )
        )
    if len(rows) > 250:
        lines.append("| 警告 | `report_truncated` | output |  |  | 只显示前 250 条，完整清单见同目录 CSV。 |  |")
    (output_dir / "DATA_QUALITY_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="校验真实源表与算法输入模板。")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="基础数据目录（线路、车辆、站场、供电臂）")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="数据源目录")
    parser.add_argument("--timetable-template", type=Path, default=DEFAULT_TIMETABLE_TEMPLATE, help="运行图模板路径")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="结果输出目录")
    parser.add_argument(
        "--require-official-data",
        action="store_true",
        help="把虚拟、规划、启发式、缺失或未确认来源一律视为阻塞错误。",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    report = validate_all(
        args.data_dir,
        args.source_dir,
        args.timetable_template,
        require_official_data=args.require_official_data,
    )
    write_report(report, args.output_dir)
    print(f"数据质量是否通过：{report.is_valid}")
    print(f"错误：{len(report.errors)} 条")
    print(f"警告：{len(report.warnings)} 条")
    print(f"输出目录：{args.output_dir}")
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
