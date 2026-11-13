# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Pre-ingestion gate for official data delivered after the prototype stage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import argparse
import csv
import json
import math

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_TIMETABLE = Path("data_templates") / "running_diagram_template.xlsx"
DEFAULT_OUTPUT_DIR = Path("outputs") / "real_data_ingestion_check"
ROUTE_MIN_KM = 0.0
ROUTE_MAX_KM = 583.003


@dataclass(frozen=True)
class IngestionIssue:
    """类 IngestionIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    file: str
    table: str
    row: str
    field: str
    issue_code: str
    message: str
    suggestion: str = ""


@dataclass
class IngestionReport:
    """类 IngestionReport：执行该模块中的相关处理逻辑。"""
    issues: List[IngestionIssue] = field(default_factory=list)
    checked_files: List[str] = field(default_factory=list)

    def add(
        self,
        severity: str,
        path: Path,
        table: str,
        row: object,
        field_name: str,
        code: str,
        message: str,
        suggestion: str = "",
    ) -> None:
        """函数 add：执行该模块中的相关处理逻辑。"""
        self.issues.append(
            IngestionIssue(
                severity=severity,
                file=str(path),
                table=table,
                row=str(row) if row not in (None, "") else "",
                field=field_name,
                issue_code=code,
                message=message,
                suggestion=suggestion,
            )
        )

    def error(self, *args: object) -> None:
        """函数 error：执行该模块中的相关处理逻辑。"""
        self.add("error", *args)

    def warning(self, *args: object) -> None:
        """函数 warning：执行该模块中的相关处理逻辑。"""
        self.add("warning", *args)

    def info(self, *args: object) -> None:
        """函数 info：执行该模块中的相关处理逻辑。"""
        self.add("info", *args)

    @property
    def errors(self) -> List[IngestionIssue]:
        """函数 errors：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[IngestionIssue]:
        """函数 warnings：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """函数 is_valid：执行该模块中的相关处理逻辑。"""
        return not self.errors

    def summary(self) -> Dict[str, Any]:
        """函数 summary：执行该模块中的相关处理逻辑。"""
        return {
            "valid": self.is_valid,
            "checked_file_count": len(self.checked_files),
            "checked_files": self.checked_files,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len([item for item in self.issues if item.severity == "info"]),
        }


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _number(value: Any) -> Optional[float]:
    """函数 _number：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _boolean(value: Any) -> Optional[bool]:
    """函数 _boolean：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "是", "有", "available"}:
        return True
    if text in {"0", "false", "no", "n", "否", "无", "unavailable"}:
        return False
    return None


def _read_csv(path: Path, report: IngestionReport) -> List[Dict[str, Any]]:
    """函数 _read_csv：执行该模块中的相关处理逻辑。"""
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)]
            if encoding == "gb18030":
                report.warning(path, "", "", "encoding", "legacy_encoding", "文件使用 GB18030，可读取但建议交付为 UTF-8-SIG。", "转换编码后再纳入正式数据流水线。")
            return rows
        except UnicodeDecodeError as exc:
            last_error = exc
    report.error(path, "", "", "encoding", "unreadable_encoding", f"CSV 编码无法识别：{last_error}", "请提供 UTF-8-SIG 或 GB18030 编码文件。")
    return []


def _read_xlsx(path: Path, report: IngestionReport, sheet_name: Optional[str] = None) -> tuple[str, List[Dict[str, Any]]]:
    """函数 _read_xlsx：执行该模块中的相关处理逻辑。"""
    if openpyxl is None:
        report.error(path, "", "", "", "missing_openpyxl", "缺少 openpyxl，无法读取 Excel。", "安装 openpyxl 后重试。")
        return "", []
    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        report.error(path, "", "", "", "unreadable_excel", f"Excel 无法读取：{exc}", "确认文件未损坏且不是加密文件。")
        return "", []
    try:
        selected = sheet_name if sheet_name in workbook.sheetnames else workbook.sheetnames[0]
        sheet = workbook[selected]
        values = sheet.iter_rows(values_only=True)
        header_row = next(values, ())
        headers = [_clean(value) for value in header_row]
        rows: List[Dict[str, Any]] = []
        for values_row in values:
            if not any(_clean(value) for value in values_row):
                continue
            rows.append({headers[idx]: value for idx, value in enumerate(values_row) if idx < len(headers) and headers[idx]})
        return selected, rows
    finally:
        workbook.close()


def _read_table(path: Path, report: IngestionReport, sheet_name: Optional[str] = None) -> tuple[str, List[Dict[str, Any]]]:
    """函数 _read_table：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        report.error(path, "", "", "", "missing_file", "待接入文件不存在。", "检查路径或补充文件。")
        return "", []
    report.checked_files.append(str(path))
    if path.suffix.lower() == ".csv":
        return "", _read_csv(path, report)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _read_xlsx(path, report, sheet_name)
    report.error(path, "", "", "", "unsupported_file_type", f"暂不支持 {path.suffix}。", "转换为 CSV 或 XLSX。")
    return "", []


def _require_columns(path: Path, table: str, rows: List[Dict[str, Any]], required: Sequence[str], report: IngestionReport) -> bool:
    """函数 _require_columns：执行该模块中的相关处理逻辑。"""
    headers = set(rows[0]) if rows else set()
    missing = [name for name in required if name not in headers]
    if not rows:
        report.error(path, table, "", "", "empty_table", "数据表为空或没有可读记录。", "至少提供表头和一条记录。")
    for name in missing:
        report.error(path, table, 1, name, "missing_required_column", f"缺少必需字段 {name}。", "按项目数据模板补充该字段。")
    return bool(rows) and not missing


def _route_bounds(metadata_path: Path) -> tuple[float, float]:
    """函数 _route_bounds：执行该模块中的相关处理逻辑。"""
    if metadata_path.exists():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            end = _number((payload.get("route") or {}).get("total_length_km"))
            if end is not None and end > 0:
                return ROUTE_MIN_KM, end
        except (OSError, ValueError, TypeError):
            pass
    return ROUTE_MIN_KM, ROUTE_MAX_KM


def _check_km(value: Any, path: Path, table: str, row: int, field_name: str, bounds: tuple[float, float], report: IngestionReport) -> Optional[float]:
    """函数 _check_km：执行该模块中的相关处理逻辑。"""
    result = _number(value)
    if result is None:
        report.error(path, table, row, field_name, "invalid_number", f"{field_name} 不是有效数字。", "统一使用 km 数值，不附带 K、SK 等前缀。")
    elif result < bounds[0] - 1e-6 or result > bounds[1] + 1e-6:
        report.error(path, table, row, field_name, "km_out_of_mainline", f"里程 {result} km 超出朔黄主线范围 {bounds[0]}-{bounds[1]} km。", "确认里程体系并排除支线记录。")
    return result


def check_stations(path: Path, bounds: tuple[float, float], report: IngestionReport) -> set[str]:
    """函数 check_stations：执行该模块中的相关处理逻辑。"""
    table, rows = _read_table(path, report)
    if not _require_columns(path, table, rows, ("station_id", "name", "position_km"), report):
        return set()
    names: set[str] = set()
    ids: set[str] = set()
    positions: List[float] = []
    for index, row in enumerate(rows, start=2):
        station_id = _clean(row.get("station_id"))
        name = _clean(row.get("name"))
        if not station_id or station_id in ids:
            report.error(path, table, index, "station_id", "invalid_or_duplicate_station_id", "车站 ID 为空或重复。", "每个主线车站使用唯一 ID。")
        if not name or name in names:
            report.error(path, table, index, "name", "invalid_or_duplicate_station_name", "站名为空或重复。", "使用线路图确认后的唯一主线站名。")
        position = _check_km(row.get("position_km"), path, table, index, "position_km", bounds, report)
        if position is not None:
            positions.append(position)
        ids.add(station_id)
        names.add(name)
    if positions != sorted(positions):
        report.error(path, table, "", "position_km", "station_order_reversal", "车站里程没有按主线方向递增。", "按主线从起点到终点重新排序。")
    return names


def _check_interval_table(
    path: Path,
    required: Sequence[str],
    start_field: str,
    end_field: str,
    bounds: tuple[float, float],
    report: IngestionReport,
    continuity: bool = False,
) -> None:
    """函数 _check_interval_table：执行该模块中的相关处理逻辑。"""
    table, rows = _read_table(path, report)
    if not _require_columns(path, table, rows, required, report):
        return
    intervals: List[tuple[float, float, int]] = []
    for index, row in enumerate(rows, start=2):
        start = _check_km(row.get(start_field), path, table, index, start_field, bounds, report)
        end = _check_km(row.get(end_field), path, table, index, end_field, bounds, report)
        if start is None or end is None:
            continue
        if end <= start:
            report.error(path, table, index, f"{start_field}/{end_field}", "nonpositive_interval", "区间终点必须大于起点。", "检查里程方向、符号和单位。")
            continue
        intervals.append((start, end, index))
    if continuity:
        ordered = sorted(intervals)
        for left, right in zip(ordered[:-1], ordered[1:]):
            delta = right[0] - left[1]
            if delta > 0.005:
                report.warning(path, table, right[2], start_field, "interval_gap", f"与上一记录存在 {delta:.3f} km 空档。", "确认是否为真实无数据区间。")
            elif delta < -0.005:
                report.error(path, table, right[2], start_field, "interval_overlap", f"与上一记录重叠 {-delta:.3f} km。", "检查边界和里程体系。")


def check_power_arms(path: Path, bounds: tuple[float, float], report: IngestionReport) -> None:
    """函数 check_power_arms：执行该模块中的相关处理逻辑。"""
    _check_interval_table(
        path,
        (
            "section_id",
            "direction",
            "start_km",
            "end_km",
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
            "storage_available",
            "storage_section_id",
        ),
        "start_km",
        "end_km",
        bounds,
        report,
    )
    table, rows = _read_table(path, IngestionReport())
    if not rows:
        return
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=2):
        key = (_clean(row.get("section_id")), _clean(row.get("direction")))
        if key in seen:
            report.error(path, table, index, "section_id/direction", "duplicate_power_arm_key", f"供电臂键 {key} 重复。", "保持方向内 section_id 唯一。")
        seen.add(key)
        direction = key[1]
        if direction not in {"上行", "下行", "单线", "up", "down", "single", "both"}:
            report.warning(path, table, index, "direction", "unknown_direction", f"未识别方向 {direction}。", "使用上行/下行或 up/down。")
        for field_name in (
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
        ):
            value = _number(row.get(field_name))
            if value is None or value < 0.0:
                report.error(
                    path,
                    table,
                    index,
                    field_name,
                    "invalid_electrical_limit",
                    f"{field_name} must be a finite non-negative number.",
                    "Provide the reviewed electrical capability in kW.",
                )
        storage_text = _clean(row.get("storage_available"))
        storage_available = _boolean(storage_text)
        if not storage_text or storage_available is None:
            report.error(
                path,
                table,
                index,
                "storage_available",
                "invalid_storage_available",
                "storage_available must be an explicit boolean value.",
                "Use yes/no, true/false, 1/0, or 是/否.",
            )
        storage_id = _clean(row.get("storage_section_id"))
        storage_start_text = _clean(row.get("storage_start_km"))
        storage_end_text = _clean(row.get("storage_end_km"))
        if storage_available is True and not storage_id:
            report.error(
                path,
                table,
                index,
                "storage_section_id",
                "missing_storage_section_id",
                "A storage-enabled interval must provide storage_section_id.",
                "Provide the physical storage-device identifier.",
            )
        if storage_available is False and storage_id:
            report.error(
                path,
                table,
                index,
                "storage_section_id",
                "storage_id_without_availability",
                "storage_section_id must be empty when storage_available is false.",
                "Clear the ID or mark the interval as storage-enabled.",
            )
        if bool(storage_start_text) != bool(storage_end_text):
            report.error(
                path,
                table,
                index,
                "storage_start_km/storage_end_km",
                "incomplete_storage_bounds",
                "storage_start_km and storage_end_km must be provided together.",
                "Provide both bounds or leave both empty to use the power-arm interval.",
            )
        elif storage_start_text and storage_end_text:
            storage_start = _number(storage_start_text)
            storage_end = _number(storage_end_text)
            if (
                storage_start is None
                or storage_end is None
                or math.isclose(storage_start, storage_end, abs_tol=1e-9)
            ):
                report.error(
                    path,
                    table,
                    index,
                    "storage_start_km/storage_end_km",
                    "invalid_storage_bounds",
                    "Storage bounds must be distinct finite numbers.",
                    "Correct the storage interval geometry.",
                )
            if storage_available is False:
                report.error(
                    path,
                    table,
                    index,
                    "storage_start_km/storage_end_km",
                    "storage_bounds_without_availability",
                    "Storage bounds must be empty when storage_available is false.",
                    "Clear the bounds or mark the interval as storage-enabled.",
                )


def check_storage(path: Path, report: IngestionReport) -> None:
    """函数 check_storage：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        report.error(path, "", "", "", "missing_file", "储能参数文件不存在。", "提供 battery.json 或保留明确标记的预设值。")
        return
    report.checked_files.append(str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        report.error(path, "", "", "", "invalid_json", f"储能 JSON 无法读取：{exc}", "修复 JSON 格式。")
        return
    aliases = {
        "capacity_kwh": ("capacity_kwh",),
        "max_charge_power_kw": ("max_charge_power_kw", "max_charge_power_kW"),
        "max_discharge_power_kw": ("max_discharge_power_kw", "max_discharge_power_kW"),
        "round_trip_efficiency": ("round_trip_efficiency",),
    }
    for canonical, names in aliases.items():
        name = next((candidate for candidate in names if candidate in payload), names[0])
        value = _number(payload.get(name))
        if value is None or value <= 0:
            report.error(path, "", "", name, "invalid_storage_parameter", f"{canonical} 必须是正数。", "容量用 kWh，功率用 kW，效率使用 0-1 小数。")
        elif canonical == "round_trip_efficiency" and value > 1:
            report.error(path, "", "", name, "invalid_efficiency", "往返效率必须在 0-1 范围内。", "百分数需除以 100。")
    if payload.get("planning_assumption") is True or "placeholder" in _clean(payload.get("data_status")).lower():
        report.warning(path, "", "", "data_status", "placeholder_storage_data", "当前仍是储能规划预设值，不是正式设备参数。", "获得设备资料后替换并重新运行检查。")


def check_traction(path: Path, report: IngestionReport) -> None:
    """函数 check_traction：执行该模块中的相关处理逻辑。"""
    required = ("name", "mass_tons", "max_traction_kN", "max_brake_kN", "davis_a", "davis_b", "davis_c")
    table, rows = _read_table(path, report)
    if not _require_columns(path, table, rows, required, report):
        return
    for index, row in enumerate(rows, start=2):
        for field_name in required[1:]:
            value = _number(row.get(field_name))
            if value is None or value < 0 or (field_name in {"mass_tons", "max_traction_kN", "max_brake_kN"} and value == 0):
                report.error(path, table, index, field_name, "invalid_traction_parameter", f"{field_name} 必须是有效非负数，质量/牵引力/制动力必须大于 0。", "确认单位分别为 t、kN 和项目约定的 Davis 单位。")
        status_text = " ".join(_clean(row.get(name)) for name in ("mass_data_status", "notes", "mass_note"))
        if "placeholder" in status_text.lower() or "virtual" in status_text.lower():
            report.warning(path, table, index, "data_status", "placeholder_traction_data", "该车型仍含预设牵引、制动或阻力参数。", "正式标定前只能用于拟真流程和相对比较。")


def check_formations(path: Path, report: IngestionReport) -> None:
    """函数 check_formations：执行该模块中的相关处理逻辑。"""
    required = ("category", "load_state", "formation_mode", "wagon_count", "mass_tons")
    table, rows = _read_table(path, report)
    if not _require_columns(path, table, rows, required, report):
        return
    seen: set[tuple[str, str, str, str]] = set()
    for index, row in enumerate(rows, start=2):
        key = tuple(_clean(row.get(name)) for name in required[:4])
        if key in seen:
            report.error(path, table, index, "/".join(required[:4]), "duplicate_formation_key", f"编组映射键 {key} 重复。", "每种类别、载重状态、编组方式和辆数仅保留一条。")
        seen.add(key)
        if (_number(row.get("wagon_count")) or 0) <= 0 or (_number(row.get("mass_tons")) or 0) <= 0:
            report.error(path, table, index, "wagon_count/mass_tons", "invalid_formation_value", "辆数和整列质量必须大于 0。", "质量单位使用 t。")


def check_smart_meter(path: Path, report: IngestionReport) -> None:
    """函数 check_smart_meter：执行该模块中的相关处理逻辑。"""
    table, rows = _read_table(path, report)
    if not rows:
        _require_columns(path, table, rows, ("trainid", "starttime", "endtime"), report)
        return
    headers = set(rows[0])
    required = ("trainid", "starttime", "endtime")
    _require_columns(path, table, rows, required, report)
    traction_field = next((name for name in ("use_ygdn_kwh", "use_ygdn") if name in headers), None)
    regen_field = next((name for name in ("use_fkdn_kwh", "use_fkdn") if name in headers), None)
    if traction_field is None or regen_field is None:
        report.error(path, table, 1, "use_ygdn/use_fkdn", "missing_energy_fields", "缺少牵引或再生电量字段。", "提供 use_ygdn/use_fkdn，或明确使用带 _kwh 的标准字段。")
    for index, row in enumerate(rows, start=2):
        if not _clean(row.get("trainid")):
            report.error(path, table, index, "trainid", "missing_trainid", "trainid 为空。", "补充列车匹配标识。")
        for field_name in (traction_field, regen_field):
            if field_name and ((_number(row.get(field_name)) is None) or (_number(row.get(field_name)) or 0) < 0):
                report.error(path, table, index, field_name, "invalid_energy", f"{field_name} 必须是非负 kWh 数值。", "确认倍率和单位后再接入。")


def check_timetable(path: Path, station_names: set[str], bounds: tuple[float, float], report: IngestionReport) -> None:
    """函数 check_timetable：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        report.error(path, "", "", "", "missing_file", "运行图文件不存在。", "提供项目运行图模板格式的 XLSX 或目录 CSV。")
        return
    report.checked_files.append(str(path))
    try:
        from timetable_input import load_canonical_timetable

        timetable = load_canonical_timetable(path)
    except Exception as exc:
        report.error(path, "", "", "", "timetable_load_failed", f"运行图无法解析：{exc}", "按 data_templates/running_diagram_template.xlsx 整理字段。")
        return
    is_placeholder = "placeholder" in _clean(timetable.metadata.get("timetable_data_status")).lower()
    for issue in timetable.validation_report.issues:
        report.add(issue.severity, path, issue.sheet, issue.row or "", issue.field, f"timetable_{issue.code}", issue.message, "按运行图模板修正。")
    for stop in timetable.stops:
        if station_names and stop.station_name not in station_names:
            add_issue = report.warning if is_placeholder else report.error
            add_issue(
                path,
                "timetable",
                stop.train_id,
                "station_name",
                "placeholder_station" if is_placeholder else "unknown_mainline_station",
                f"站名 {stop.station_name} 不在朔黄主线站表中。" + (" 当前文件已标记为预设运行图。" if is_placeholder else ""),
                "正式运行图接入时必须统一为 stations.csv 中的主线站名。",
            )
        if stop.station_km < bounds[0] - 1e-6 or stop.station_km > bounds[1] + 1e-6:
            report.error(path, "timetable", stop.train_id, "station_km", "km_out_of_mainline", f"运行图里程 {stop.station_km} 超出主线范围。", "确认里程体系。")


def run_checks(
    input_path: Path,
    kind: str,
    timetable_path: Path,
    station_csv: Optional[Path] = None,
    route_metadata: Optional[Path] = None,
) -> IngestionReport:
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    report = IngestionReport()
    data_dir = input_path if input_path.is_dir() or kind == "all" else input_path.parent
    station_csv = Path(station_csv) if station_csv is not None else data_dir / "stations.csv"
    route_metadata = Path(route_metadata) if route_metadata is not None else data_dir / "route_metadata.json"
    bounds = _route_bounds(route_metadata)
    station_names: set[str] = set()
    if kind in {"all", "stations", "timetable"}:
        station_source = input_path if kind == "stations" else station_csv
        station_names = check_stations(station_source, bounds, report)

    resolve = lambda filename: data_dir / filename if input_path.is_dir() or kind == "all" else input_path
    if kind in {"all", "geometry"}:
        if input_path.is_dir() or kind == "all":
            _check_interval_table(resolve("gradients.csv"), ("gradient_id", "start_km", "end_km", "length_m", "gradient_per_mille"), "start_km", "end_km", bounds, report, continuity=True)
            _check_interval_table(resolve("curves.csv"), ("curve_id", "start_km", "end_km", "radius_m"), "start_km", "end_km", bounds, report)
        elif "gradient" in input_path.stem.lower() or "坡度" in input_path.stem:
            _check_interval_table(input_path, ("gradient_id", "start_km", "end_km", "length_m", "gradient_per_mille"), "start_km", "end_km", bounds, report, continuity=True)
        elif "curve" in input_path.stem.lower() or "曲线" in input_path.stem:
            _check_interval_table(input_path, ("curve_id", "start_km", "end_km", "radius_m"), "start_km", "end_km", bounds, report)
        else:
            report.error(input_path, "", "", "", "ambiguous_geometry_file", "无法判断单文件是坡度表还是平曲线表。", "文件名中保留 gradient/坡度 或 curve/曲线，或者传入包含两张表的目录。")
    if kind in {"all", "power-arm"}:
        check_power_arms(resolve("power_arm_intervals.csv"), bounds, report)
    if kind in {"all", "storage"}:
        check_storage(resolve("battery.json"), report)
    if kind in {"all", "traction"}:
        check_traction(resolve("trains.csv"), report)
    if kind in {"all", "formation"}:
        check_formations(resolve("train_formation_modes_2025.csv"), report)
    if kind in {"all", "smart-meter"}:
        check_smart_meter(resolve("smart_meter_representative_interval_samples.csv"), report)
    if kind in {"all", "timetable"}:
        check_timetable(timetable_path if kind == "all" else input_path, station_names, bounds, report)
    return report


def write_report(report: IngestionReport, output_dir: Path) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [issue.__dict__ for issue in report.issues]
    with (output_dir / "ingestion_check_issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("severity", "file", "table", "row", "field", "issue_code", "message", "suggestion"))
        writer.writeheader()
        writer.writerows(rows)
    summary = report.summary()
    (output_dir / "ingestion_check_summary.json").write_text(json.dumps({**summary, "issues": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 真实数据接入检查报告",
        "",
        "本报告用于新资料替换当前预设值之前的接入门禁，不会修改源文件。",
        "",
        "## 检查结论",
        "",
        f"- 是否可接入：`{report.is_valid}`",
        f"- 已检查文件：`{len(report.checked_files)}`",
        f"- 错误：`{len(report.errors)}`",
        f"- 警告：`{len(report.warnings)}`",
        "",
        "错误必须处理后再替换项目数据；警告允许进入原型流程，但必须保留来源或预设状态说明。",
        "",
        "## 问题明细",
        "",
        "| 级别 | 文件/表 | 行 | 字段 | 代码 | 说明 | 处理建议 |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for issue in report.issues:
        source = issue.file + (f":{issue.table}" if issue.table else "")
        values = [issue.severity, source, issue.row, issue.field, issue.issue_code, issue.message, issue.suggestion]
        lines.append("| " + " | ".join(str(value).replace("|", "/").replace("\n", " ") for value in values) + " |")
    if not report.issues:
        lines.append("| info | - | - | - | no_issue | 未发现接入问题。 | - |")
    (output_dir / "INGESTION_CHECK_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="检查甲方/现场新数据能否替换当前算法输入。")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--kind", choices=("all", "stations", "geometry", "timetable", "power-arm", "storage", "traction", "formation", "smart-meter"), default="all")
    parser.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE)
    parser.add_argument("--station-csv", type=Path, default=None)
    parser.add_argument("--route-metadata", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    report = run_checks(args.input, args.kind, args.timetable, args.station_csv, args.route_metadata)
    write_report(report, args.output_dir)
    print(json.dumps({**report.summary(), "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
