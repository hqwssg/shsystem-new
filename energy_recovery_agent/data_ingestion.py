# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import argparse
import csv
import json
import math

from operating_conditions import (
    OPEN_ENDED_TIME_S,
    normalize_speed_restriction_direction,
    operating_conditions_from_dict,
)
from resource_constraints import ResourceConfig, ResourceModel
from train_simulator import (
    BatteryStorageParameters,
    DavisCoefficients,
    RouteData,
    Segment,
    Station,
    StorageDeviceParameters,
    TrainParameters,
)


SCHEMA_VERSION = "1.0"
MODEL_LINE_NAME = "朔黄线"
MODEL_SCOPE_NAME = "mainline_only"

ROUTE_METADATA_FILE = "route_metadata.json"
STATIONS_FILE = "stations.csv"
SEGMENTS_FILE = "segments.csv"
ENERGY_ZONES_FILE = "energy_transfer_zones.csv"
SIGNAL_BLOCKS_FILE = "signaling_blocks.csv"
STATION_RESOURCES_FILE = "station_resources.csv"
HEADWAY_CONSTRAINTS_FILE = "headway_constraints.csv"
TECHNICAL_OPERATION_TIMES_FILE = "technical_operation_times.csv"
STATION_OPERATION_ASSIGNMENTS_FILE = "station_operation_assignments.csv"
PDF_STATION_MASTER_FILE = "pdf_station_master.csv"
TRAINS_FILE = "trains.csv"
BATTERY_FILE = "battery.json"
STORAGE_DEVICES_FILE = "storage_devices.json"
OPERATING_CONDITIONS_FILE = "operating_conditions.json"
RESOURCE_CONFIG_FILE = "resource_config.json"
POWER_ARM_INTERVALS_FILE = "power_arm_intervals.csv"

REQUIRED_FILES = (
    ROUTE_METADATA_FILE,
    STATIONS_FILE,
    SEGMENTS_FILE,
    TRAINS_FILE,
    BATTERY_FILE,
)

TRAIN_TYPE_HEADWAY_PRIORITY = (
    ("2万吨", "Heavy"),
    ("万吨", "Heavy"),
    ("普通", "Freight"),
)


@dataclass(frozen=True)
class DataValidationIssue:
    """类 DataValidationIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    code: str
    file: str
    row: Optional[int]
    field: str
    message: str
    suggestion: str = ""


@dataclass
class DataValidationReport:
    """类 DataValidationReport：执行该模块中的相关处理逻辑。"""
    source_dir: str
    issues: List[DataValidationIssue] = field(default_factory=list)

    def add(
        self,
        severity: str,
        code: str,
        file: str,
        row: Optional[int],
        field: str,
        message: str,
        suggestion: str = "",
    ) -> None:
        """函数 add：执行该模块中的相关处理逻辑。"""
        self.issues.append(
            DataValidationIssue(
                severity=severity,
                code=code,
                file=file,
                row=row,
                field=field,
                message=message,
                suggestion=suggestion,
            )
        )

    def error(
        self,
        code: str,
        file: str,
        row: Optional[int],
        field: str,
        message: str,
        suggestion: str = "",
    ) -> None:
        """函数 error：执行该模块中的相关处理逻辑。"""
        self.add("error", code, file, row, field, message, suggestion)

    def warning(
        self,
        code: str,
        file: str,
        row: Optional[int],
        field: str,
        message: str,
        suggestion: str = "",
    ) -> None:
        """函数 warning：执行该模块中的相关处理逻辑。"""
        self.add("warning", code, file, row, field, message, suggestion)

    @property
    def errors(self) -> List[DataValidationIssue]:
        """函数 errors：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[DataValidationIssue]:
        """函数 warnings：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """函数 is_valid：执行该模块中的相关处理逻辑。"""
        return not self.errors

    def to_rows(self) -> List[Dict[str, object]]:
        """函数 to_rows：执行该模块中的相关处理逻辑。"""
        return [
            {
                "severity": issue.severity,
                "code": issue.code,
                "file": issue.file,
                "row": "" if issue.row is None else issue.row,
                "field": issue.field,
                "message": issue.message,
                "suggestion": issue.suggestion,
            }
            for issue in self.issues
        ]

    def summary(self) -> Dict[str, object]:
        """函数 summary：执行该模块中的相关处理逻辑。"""
        return {
            "source_dir": self.source_dir,
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": self.to_rows(),
        }

    def raise_for_errors(self) -> None:
        """函数 raise_for_errors：执行该模块中的相关处理逻辑。"""
        if self.is_valid:
            return
        preview = "; ".join(
            f"{issue.file}:{issue.row or ''} {issue.field} {issue.message}"
            for issue in self.errors[:5]
        )
        raise ValueError(f"real-data validation failed with {len(self.errors)} errors: {preview}")


@dataclass(frozen=True)
class IngestedDataBundle:
    """类 IngestedDataBundle：执行该模块中的相关处理逻辑。"""
    source_dir: Path
    route: RouteData
    trains: Dict[str, TrainParameters]
    battery: BatteryStorageParameters
    resource_model: ResourceModel
    validation_report: DataValidationReport
    route_metadata: Dict[str, Any]


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    if value is None:
        return ""
    return str(value).strip()


def _optional_float(value: Any) -> Optional[float]:
    """函数 _optional_float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"value must be finite, got {value!r}")
    return number


def _float(value: Any, default: float = 0.0) -> float:
    """函数 _float：执行该模块中的相关处理逻辑。"""
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _optional_int(value: Any) -> Optional[int]:
    """函数 _optional_int：执行该模块中的相关处理逻辑。"""
    number = _optional_float(value)
    if number is None:
        return None
    if not number.is_integer():
        raise ValueError(f"value must be a whole number, got {value!r}")
    return int(number)


def _int(value: Any, default: int = 0) -> int:
    """函数 _int：执行该模块中的相关处理逻辑。"""
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _bool(value: Any) -> bool:
    """函数 _bool：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "single", "shared"}:
        return True
    if text in {"", "0", "false", "no", "n", "double", "separate"}:
        return False
    raise ValueError(f"value must be a recognized boolean, got {value!r}")


def _read_json(path: Path, report: DataValidationReport, required: bool) -> Dict[str, Any]:
    """函数 _read_json：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        if required:
            report.error("missing_file", path.name, None, "", f"缺少必需文件 {path.name}。")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error("invalid_json", path.name, exc.lineno, "", f"JSON 格式无效：{exc.msg}。")
        return {}
    except OSError as exc:
        report.error("read_error", path.name, None, "", str(exc))
        return {}
    if not isinstance(payload, dict):
        report.error(
            "invalid_json_object",
            path.name,
            None,
            "",
            f"{path.name} 的根节点必须是 JSON 对象。",
        )
        return {}
    return payload


def _read_csv(
    path: Path,
    report: DataValidationReport,
    required: bool,
    required_columns: Iterable[str],
) -> List[Dict[str, str]]:
    """函数 _read_csv：执行该模块中的相关处理逻辑。"""
    required_columns = tuple(required_columns)
    if not path.exists():
        if required:
            report.error("missing_file", path.name, None, "", f"缺少必需文件 {path.name}。")
        return []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in required_columns if column not in fieldnames]
            for column in missing:
                report.error(
                    "missing_column",
                    path.name,
                    1,
                    column,
                    f"Required column {column} is missing.",
                )
            return [dict(row) for row in reader]
    except OSError as exc:
        report.error("read_error", path.name, None, "", str(exc))
        return []


def _field_float(
    raw: Dict[str, Any],
    key: str,
    report: DataValidationReport,
    file_name: str,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    """函数 _field_float：执行该模块中的相关处理逻辑。"""
    if key not in raw or _clean(raw.get(key)) == "":
        report.error("missing_field", file_name, None, key, f"缺少必需字段 {key}。")
        return None
    if isinstance(raw[key], bool):
        report.error("invalid_number", file_name, None, key, f"字段 {key} 必须为数值，不能是布尔值。")
        return None
    try:
        value = float(raw[key])
    except (TypeError, ValueError):
        report.error("invalid_number", file_name, None, key, f"字段 {key} 必须为数值。")
        return None
    if not math.isfinite(value):
        report.error("invalid_number", file_name, None, key, f"字段 {key} 必须是有限数值。")
        return None
    if minimum is not None and value < minimum:
        report.error("number_too_small", file_name, None, key, f"字段 {key} 必须不小于 {minimum}。")
    if maximum is not None and value > maximum:
        report.error("number_too_large", file_name, None, key, f"字段 {key} 必须不大于 {maximum}。")
    return value


def _row_float(
    row: Dict[str, Any],
    key: str,
    report: DataValidationReport,
    file_name: str,
    row_number: int,
    required: bool = True,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    """函数 _row_float：执行该模块中的相关处理逻辑。"""
    if key not in row or _clean(row.get(key)) == "":
        if required:
            report.error("missing_value", file_name, row_number, key, f"缺少必需列 {key}。")
        return None
    if isinstance(row[key], bool):
        report.error(
            "invalid_number",
            file_name,
            row_number,
            key,
            f"列 {key} 必须为数值，不能是布尔值。",
        )
        return None
    try:
        value = float(row[key])
    except (TypeError, ValueError):
        report.error("invalid_number", file_name, row_number, key, f"列 {key} 必须为数值。")
        return None
    if not math.isfinite(value):
        report.error("invalid_number", file_name, row_number, key, f"列 {key} 必须是有限数值。")
        return None
    if minimum is not None and value < minimum:
        report.error("number_too_small", file_name, row_number, key, f"列 {key} 必须不小于 {minimum}。")
    if maximum is not None and value > maximum:
        report.error("number_too_large", file_name, row_number, key, f"列 {key} 必须不大于 {maximum}。")
    return value


def _row_int(
    row: Dict[str, Any],
    key: str,
    report: DataValidationReport,
    file_name: str,
    row_number: int,
    required: bool = True,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> Optional[int]:
    """函数 _row_int：执行该模块中的相关处理逻辑。"""
    value = _row_float(row, key, report, file_name, row_number, required, minimum, maximum)
    if value is None:
        return None
    if not math.isclose(value, round(value), abs_tol=1e-9):
        report.error("invalid_integer", file_name, row_number, key, f"列 {key} 必须为整数。")
    return int(round(value))


def _route_meta(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """函数 _route_meta：执行该模块中的相关处理逻辑。"""
    raw_route = metadata.get("route")
    if isinstance(raw_route, dict):
        return raw_route
    return metadata


def _is_model_line_name(value: Any) -> bool:
    """函数 _is_model_line_name：执行该模块中的相关处理逻辑。"""
    return _clean(value) == MODEL_LINE_NAME


def _as_range(value: Any, default: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    """函数 _as_range：执行该模块中的相关处理逻辑。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
        if len(parts) != 2:
            raise ValueError(f"range must contain exactly two values, got {value!r}")
        raw_start, raw_end = parts
    elif isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"range must contain exactly two values, got {value!r}")
        raw_start, raw_end = value
    else:
        raise ValueError(f"range must contain exactly two values, got {value!r}")
    if isinstance(raw_start, bool) or isinstance(raw_end, bool):
        raise ValueError(f"range bounds must be finite numbers, got {value!r}")
    start, end = float(raw_start), float(raw_end)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError(f"range bounds must be finite numbers, got {value!r}")
    return start, end



def _normalized_long_downhill_range(value: Any) -> Tuple[float, float]:
    """Treat tiny placeholder ranges as disabled."""
    start, end = _as_range(value, (0.0, 0.0))
    if abs(end - start) < 0.05:
        return 0.0, 0.0
    return (min(start, end), max(start, end))


def _range_inside_route(
    start_km: Optional[float],
    end_km: Optional[float],
    total_length_km: Optional[float],
    report: DataValidationReport,
    file_name: str,
    row_number: Optional[int],
    start_field: str = "start_km",
    end_field: str = "end_km",
) -> None:
    """函数 _range_inside_route：执行该模块中的相关处理逻辑。"""
    if start_km is None or end_km is None or total_length_km is None:
        return
    if end_km <= start_km:
        report.error(
            "invalid_range",
            file_name,
            row_number,
            f"{start_field},{end_field}",
            "区间终点必须大于起点。",
        )
    if start_km < -1e-6 or end_km > total_length_km + 1e-6:
        report.error(
            "range_outside_route",
            file_name,
            row_number,
            f"{start_field},{end_field}",
            "区间必须落在 0 与线路总长 total_length_km 之间。",
        )


def _validate_route_metadata(
    route_raw: Dict[str, Any],
    report: DataValidationReport,
) -> Tuple[Optional[float], Optional[float]]:
    """函数 _validate_route_metadata：执行该模块中的相关处理逻辑。"""
    total_length_km = _field_float(route_raw, "total_length_km", report, ROUTE_METADATA_FILE, minimum=0.1)
    max_speed_kmh = _field_float(route_raw, "max_speed_kmh", report, ROUTE_METADATA_FILE, minimum=1.0)

    downhill = route_raw.get("long_downhill_range_km", [0.0, 0.0])
    try:
        start_km, end_km = _as_range(downhill)
        if abs(end_km - start_km) >= 0.05:
            _range_inside_route(start_km, end_km, total_length_km, report, ROUTE_METADATA_FILE, None)
    except (TypeError, ValueError):
        report.error(
            "invalid_range",
            ROUTE_METADATA_FILE,
            None,
            "long_downhill_range_km",
            "long_downhill_range_km 必须包含两个数值。",
        )

    signaling = route_raw.get("signaling_system", {})
    if signaling is None:
        signaling = {}
    if not isinstance(signaling, dict):
        report.error(
            "invalid_signaling_config",
            ROUTE_METADATA_FILE,
            None,
            "signaling_system",
            "signaling_system 必须是对象。",
        )
        return total_length_km, max_speed_kmh

    mode = _clean(signaling.get("mode")).lower() or "hybrid"
    if mode not in {
        "fixed",
        "fixed_block",
        "moving",
        "moving_block",
        "hybrid",
    }:
        report.error(
            "invalid_signaling_mode",
            ROUTE_METADATA_FILE,
            None,
            "signaling_system.mode",
            "信号制式必须为固定闭塞、移动闭塞或混合。",
        )

    def validate_signaling_number(
        field_name: str,
        *,
        positive: bool = False,
        whole: bool = False,
    ) -> None:
        """函数 validate_signaling_number：执行该模块中的相关处理逻辑。"""
        if field_name not in signaling or _clean(signaling.get(field_name)) == "":
            return
        if isinstance(signaling[field_name], bool):
            report.error(
                "invalid_signaling_parameter",
                ROUTE_METADATA_FILE,
                None,
                f"signaling_system.{field_name}",
                f"{field_name} 必须为数值，不能是布尔值。",
            )
            return
        try:
            value = float(signaling[field_name])
        except (TypeError, ValueError):
            report.error(
                "invalid_signaling_parameter",
                ROUTE_METADATA_FILE,
                None,
                f"signaling_system.{field_name}",
                f"{field_name} must be numeric.",
            )
            return
        if not math.isfinite(value):
            message = f"{field_name} must be finite."
        elif positive and value <= 0.0:
            message = f"{field_name} must be positive."
        elif not positive and value < 0.0:
            message = f"{field_name} must be non-negative."
        elif whole and not value.is_integer():
            message = f"{field_name} must be a whole number."
        else:
            return
        report.error(
            "invalid_signaling_parameter",
            ROUTE_METADATA_FILE,
            None,
            f"signaling_system.{field_name}",
            message,
        )

    validate_signaling_number("check_step_s", positive=True, whole=True)
    validate_signaling_number("fixed_block_length_km", positive=True)
    validate_signaling_number("fixed_block_protection_blocks", whole=True)
    validate_signaling_number("moving_block_base_buffer_m")
    validate_signaling_number("moving_block_reaction_time_s")
    validate_signaling_number("moving_block_follower_service_decel_mps2", positive=True)
    validate_signaling_number("moving_block_lead_emergency_decel_mps2", positive=True)
    return total_length_km, max_speed_kmh


def _validate_stations(
    rows: List[Dict[str, str]],
    total_length_km: Optional[float],
    report: DataValidationReport,
) -> None:
    """函数 _validate_stations：执行该模块中的相关处理逻辑。"""
    if len(rows) < 2:
        report.error("too_few_rows", STATIONS_FILE, None, "", "至少需要两个车站。")
        return

    seen_names: set[str] = set()
    positions: List[Tuple[float, int]] = []
    for row_idx, row in enumerate(rows, start=2):
        name = _clean(row.get("name"))
        if not name:
            report.error("missing_value", STATIONS_FILE, row_idx, "name", "车站名称必填。")
        elif name in seen_names:
            report.error("duplicate_station", STATIONS_FILE, row_idx, "name", f"Duplicate station name {name}.")
        seen_names.add(name)

        position = _row_float(row, "position_km", report, STATIONS_FILE, row_idx, minimum=0.0)
        if position is not None:
            positions.append((position, row_idx))
            if total_length_km is not None and position > total_length_km + 1e-6:
                report.error(
                    "station_outside_route",
                    STATIONS_FILE,
                    row_idx,
                    "position_km",
                    "Station position must not exceed route total_length_km.",
                )

    sorted_positions = sorted(positions)
    for (prev_pos, _prev_row), (cur_pos, cur_row) in zip(sorted_positions[:-1], sorted_positions[1:]):
        if cur_pos <= prev_pos + 1e-6:
            report.error(
                "station_order",
                STATIONS_FILE,
                cur_row,
                "position_km",
                "车站里程必须严格递增。",
            )

    if positions and abs(min(pos for pos, _row in positions)) > 1e-6:
        report.warning(
            "missing_origin_station",
            STATIONS_FILE,
            None,
            "position_km",
            "没有车站位于线路起点 0 千米处。",
            "请确认首个车站里程是否为有意偏移。",
        )
    if positions and total_length_km is not None and abs(max(pos for pos, _row in positions) - total_length_km) > 1.0:
        report.warning(
            "missing_terminal_station",
            STATIONS_FILE,
            None,
            "position_km",
            "没有车站接近线路终点里程。",
            "请补充终点车站，或确认建模线路终点不在车站范围内。",
        )


def _validate_segments(
    rows: List[Dict[str, str]],
    total_length_km: Optional[float],
    max_speed_kmh: Optional[float],
    report: DataValidationReport,
) -> None:
    """函数 _validate_segments：执行该模块中的相关处理逻辑。"""
    if not rows:
        report.error("too_few_rows", SEGMENTS_FILE, None, "", "至少需要一个线路分段。")
        return

    ranges: List[Tuple[float, float, int]] = []
    for row_idx, row in enumerate(rows, start=2):
        start_km = _row_float(row, "start_km", report, SEGMENTS_FILE, row_idx, minimum=0.0)
        end_km = _row_float(row, "end_km", report, SEGMENTS_FILE, row_idx, minimum=0.0)
        gradient = _row_float(row, "gradient_per_mille", report, SEGMENTS_FILE, row_idx)
        curve_radius = _row_float(row, "curve_radius_m", report, SEGMENTS_FILE, row_idx, required=False)
        speed_limit = _row_float(row, "speed_limit_kmh", report, SEGMENTS_FILE, row_idx, required=False)

        _range_inside_route(start_km, end_km, total_length_km, report, SEGMENTS_FILE, row_idx)
        if start_km is not None and end_km is not None:
            ranges.append((start_km, end_km, row_idx))
        if gradient is not None and abs(gradient) > 35.0:
            report.warning(
                "large_gradient",
                SEGMENTS_FILE,
                row_idx,
                "gradient_per_mille",
                "坡度绝对值对重载铁路数据而言异常偏大。",
                "请确认单位是千分率而不是百分比。",
            )
        if curve_radius is not None and curve_radius <= 0.0:
            report.error("invalid_curve_radius", SEGMENTS_FILE, row_idx, "curve_radius_m", "曲线半径必须为正。")
        if speed_limit is not None:
            if speed_limit <= 0.0:
                report.error("invalid_speed_limit", SEGMENTS_FILE, row_idx, "speed_limit_kmh", "Speed limit must be positive.")
            elif max_speed_kmh is not None and speed_limit > max_speed_kmh + 1e-6:
                report.warning(
                    "segment_speed_above_route_max",
                    SEGMENTS_FILE,
                    row_idx,
                    "speed_limit_kmh",
                    "Segment speed is higher than route max_speed_kmh and will not raise the route cap.",
                )

    ranges.sort(key=lambda item: (item[0], item[1]))
    if not ranges:
        return
    if abs(ranges[0][0]) > 1e-6:
        report.error(
            "segment_coverage_gap",
            SEGMENTS_FILE,
            ranges[0][2],
            "start_km",
            "分段必须从 0 千米起连续覆盖，不能有起始缺口。",
        )
    for prev, cur in zip(ranges[:-1], ranges[1:]):
        prev_end = prev[1]
        cur_start = cur[0]
        if cur_start > prev_end + 1e-6:
            report.error(
                "segment_coverage_gap",
                SEGMENTS_FILE,
                cur[2],
                "start_km",
                f"分段之间存在缺口：{prev_end:.3f} 千米至 {cur_start:.3f} 千米。",
            )
        elif cur_start < prev_end - 1e-6:
            report.error(
                "segment_overlap",
                SEGMENTS_FILE,
                cur[2],
                "start_km",
                f"Segment overlaps previous segment ending at {prev_end:.3f} km.",
            )
    if total_length_km is not None and abs(ranges[-1][1] - total_length_km) > 1e-6:
        report.error(
            "segment_coverage_gap",
            SEGMENTS_FILE,
            ranges[-1][2],
            "end_km",
            "分段必须恰好覆盖到线路总长。",
        )


def _validate_energy_zones(
    rows: List[Dict[str, str]],
    total_length_km: Optional[float],
    report: DataValidationReport,
) -> None:
    """函数 _validate_energy_zones：执行该模块中的相关处理逻辑。"""
    if not rows:
        report.warning(
            "missing_energy_zones",
            ENERGY_ZONES_FILE,
            None,
            "",
            "未提供柔性供电或再生能量转移区段。",
        )
        return
    for row_idx, row in enumerate(rows, start=2):
        start_km = _row_float(row, "start_km", report, ENERGY_ZONES_FILE, row_idx, minimum=0.0)
        end_km = _row_float(row, "end_km", report, ENERGY_ZONES_FILE, row_idx, minimum=0.0)
        _range_inside_route(start_km, end_km, total_length_km, report, ENERGY_ZONES_FILE, row_idx)
        efficiency = _row_float(row, "efficiency", report, ENERGY_ZONES_FILE, row_idx, required=False)
        if efficiency is not None and not 0.0 < efficiency <= 1.0:
            report.error("invalid_efficiency", ENERGY_ZONES_FILE, row_idx, "efficiency", "效率必须落在 (0, 1] 区间。")
        max_transfer_power = _row_float(
            row, "max_transfer_power_kW", report, ENERGY_ZONES_FILE, row_idx, minimum=0.0, required=False
        )
        if max_transfer_power is not None and max_transfer_power <= 0.0:
            report.error(
                "invalid_transfer_power", ENERGY_ZONES_FILE, row_idx, "max_transfer_power_kW",
                "提供最大转移功率时必须大于 0。",
            )
        implementation_status = _clean(row.get("implementation_status")).lower()
        if implementation_status and implementation_status not in {"implemented", "planned"}:
            report.error(
                "invalid_implementation_status", ENERGY_ZONES_FILE, row_idx, "implementation_status",
                "implementation_status 必须为 implemented 或 planned。",
            )
        if _clean(row.get("active_in_operational_baseline")):
            try:
                _bool(row.get("active_in_operational_baseline"))
            except ValueError:
                report.error(
                    "invalid_boolean", ENERGY_ZONES_FILE, row_idx, "active_in_operational_baseline",
                    "active_in_operational_baseline must be a recognized true/false value.",
                )


def _validate_signaling_blocks(
    rows: List[Dict[str, str]],
    total_length_km: Optional[float],
    report: DataValidationReport,
) -> None:
    """函数 _validate_signaling_blocks：执行该模块中的相关处理逻辑。"""
    if not rows:
        report.warning(
            "missing_signaling_blocks",
            SIGNAL_BLOCKS_FILE,
            None,
            "",
            "未提供实际闭塞分区表，将按线路元数据中的固定闭塞分区长度近似。",
        )
        return

    allowed_directions = {"forward", "reverse", "both", "shared"}
    by_direction: Dict[str, List[Tuple[float, float, int]]] = {}
    for row_idx, row in enumerate(rows, start=2):
        start_km = _row_float(row, "start_km", report, SIGNAL_BLOCKS_FILE, row_idx, minimum=0.0)
        end_km = _row_float(row, "end_km", report, SIGNAL_BLOCKS_FILE, row_idx, minimum=0.0)
        direction = _clean(row.get("direction")).lower() or "both"
        if direction not in allowed_directions:
            report.error(
                "invalid_direction",
                SIGNAL_BLOCKS_FILE,
                row_idx,
                "direction",
                "方向必须为 forward、reverse、both 或 shared。",
            )
        if _clean(row.get("is_single_line")):
            try:
                _bool(row.get("is_single_line"))
            except ValueError:
                report.error(
                    "invalid_boolean",
                    SIGNAL_BLOCKS_FILE,
                    row_idx,
                    "is_single_line",
                    "is_single_line must be a recognized true/false value.",
                )
        _range_inside_route(start_km, end_km, total_length_km, report, SIGNAL_BLOCKS_FILE, row_idx)
        if start_km is not None and end_km is not None:
            by_direction.setdefault(direction, []).append((start_km, end_km, row_idx))

    for direction, ranges in by_direction.items():
        ranges.sort(key=lambda item: (item[0], item[1]))
        for prev, cur in zip(ranges[:-1], ranges[1:]):
            if cur[0] < prev[1] - 1e-6:
                report.error(
                    "block_overlap",
                    SIGNAL_BLOCKS_FILE,
                    cur[2],
                    "start_km",
                    f"{direction} block overlaps previous block ending at {prev[1]:.3f} km.",
                )


def _validate_station_resources(
    rows: List[Dict[str, str]],
    station_names: set[str],
    report: DataValidationReport,
) -> None:
    """函数 _validate_station_resources：执行该模块中的相关处理逻辑。"""
    if not rows:
        report.warning(
            "missing_station_resources",
            STATION_RESOURCES_FILE,
            None,
            "",
            "未提供车站能力表，将使用默认资源能力。",
        )
        return

    seen: set[str] = set()
    for row_idx, row in enumerate(rows, start=2):
        station_name = _clean(row.get("station_name") or row.get("name"))
        if not station_name:
            report.error("missing_value", STATION_RESOURCES_FILE, row_idx, "station_name", "车站名称必填。")
            continue
        if station_name in seen:
            report.error(
                "duplicate_station_resource",
                STATION_RESOURCES_FILE,
                row_idx,
                "station_name",
                f"车站 {station_name} 的能力记录重复。",
            )
        seen.add(station_name)
        if station_name not in station_names:
            report.error(
                "unknown_station",
                STATION_RESOURCES_FILE,
                row_idx,
                "station_name",
                f"车站 {station_name} 不在 stations.csv 中。",
            )
        _row_int(row, "track_capacity", report, STATION_RESOURCES_FILE, row_idx, minimum=1)
        _row_int(row, "throat_capacity", report, STATION_RESOURCES_FILE, row_idx, minimum=1)


def _headway_train_category(scope: str) -> str:
    """函数 _headway_train_category：执行该模块中的相关处理逻辑。"""
    for marker, category in TRAIN_TYPE_HEADWAY_PRIORITY:
        if marker in scope:
            return category
    return "Freight"


def _validate_headway_constraints(rows: List[Dict[str, str]], report: DataValidationReport) -> None:
    """函数 _validate_headway_constraints：执行该模块中的相关处理逻辑。"""
    for row_idx, row in enumerate(rows, start=2):
        line = _clean(row.get("line"))
        scope = _clean(row.get("scope"))
        if not line:
            report.error("missing_value", HEADWAY_CONSTRAINTS_FILE, row_idx, "line", "线路名称必填。")
        if not scope:
            report.error("missing_value", HEADWAY_CONSTRAINTS_FILE, row_idx, "scope", "追踪间隔的适用范围必填。")
        _row_float(row, "headway_min", report, HEADWAY_CONSTRAINTS_FILE, row_idx, minimum=0.0)


def _validate_technical_operation_times(
    rows: List[Dict[str, str]],
    station_names: set[str],
    known_pdf_station_names: set[str],
    report: DataValidationReport,
) -> None:
    """函数 _validate_technical_operation_times：执行该模块中的相关处理逻辑。"""
    unmatched: List[str] = []
    off_model: List[str] = []
    for row_idx, row in enumerate(rows, start=2):
        station_name = _clean(row.get("station_name"))
        normalized_station_name = station_name.removesuffix("站")
        if not station_name:
            report.error(
                "missing_value",
                TECHNICAL_OPERATION_TIMES_FILE,
                row_idx,
                "station_name",
                "车站名称必填。",
            )
        elif station_name in station_names or normalized_station_name in station_names:
            pass
        elif station_name in known_pdf_station_names or normalized_station_name in known_pdf_station_names:
            off_model.append(station_name)
        else:
            unmatched.append(station_name)
        for key in ("spotting_min", "loading_unloading_min", "pickup_min", "total_min"):
            _row_float(row, key, report, TECHNICAL_OPERATION_TIMES_FILE, row_idx, minimum=0.0)
        cars_text = _clean(row.get("cars"))
        if cars_text:
            try:
                cars_number = float(cars_text)
            except ValueError:
                # 来源文档在此处可能使用描述性区间或编组标签。
                pass
            else:
                if not math.isfinite(cars_number) or cars_number < 0.0 or not cars_number.is_integer():
                    report.error(
                        "invalid_integer",
                        TECHNICAL_OPERATION_TIMES_FILE,
                        row_idx,
                        "cars",
                        "A numeric cars value must be a non-negative integer.",
                    )
    if off_model:
        preview = ", ".join(sorted(set(off_model))[:8])
        report.warning(
            "technical_operation_station_outside_current_model",
            TECHNICAL_OPERATION_TIMES_FILE,
            None,
            "station_name",
            f"PDF 车站表中存在技术作业站，但当前 stations.csv 中没有：{preview}。",
            "在模型扩展到对应 PDF 线路或确认线别映射后再使用这些记录。",
        )
    if unmatched:
        preview = ", ".join(sorted(set(unmatched))[:8])
        report.warning(
            "technical_operation_station_unmatched",
            TECHNICAL_OPERATION_TIMES_FILE,
            None,
            "station_name",
            f"以下技术作业站既不在 stations.csv，也不在 pdf_station_master.csv 中：{preview}。",
            "在 PDF 站名或模型映射确认前，这些记录仅作旁路数据保留。",
        )


def _validate_station_operation_assignments(
    rows: List[Dict[str, str]],
    station_names: set[str],
    report: DataValidationReport,
) -> None:
    """函数 _validate_station_operation_assignments：执行该模块中的相关处理逻辑。"""
    allowed_train_types = {"", "Heavy", "Empty"}
    allowed_directions = {"", "forward", "reverse"}
    allowed_applies_to = {"", "origin", "destination", "terminal", "all"}
    for row_idx, row in enumerate(rows, start=2):
        station_name = _clean(row.get("station_name"))
        if not station_name:
            report.error(
                "missing_value",
                STATION_OPERATION_ASSIGNMENTS_FILE,
                row_idx,
                "station_name",
                "车站名称必填。",
            )
        elif station_name not in station_names:
            report.error(
                "unknown_station",
                STATION_OPERATION_ASSIGNMENTS_FILE,
                row_idx,
                "station_name",
                f"车站 {station_name} 不在 stations.csv 中。",
            )
        train_type = _clean(row.get("train_type"))
        if train_type not in allowed_train_types:
            report.error(
                "invalid_train_type",
                STATION_OPERATION_ASSIGNMENTS_FILE,
                row_idx,
                "train_type",
                "train_type 必须为 Heavy、Empty 或留空。",
            )
        direction = _clean(row.get("direction"))
        if direction not in allowed_directions:
            report.error(
                "invalid_direction",
                STATION_OPERATION_ASSIGNMENTS_FILE,
                row_idx,
                "direction",
                "direction 必须为 forward、reverse 或留空。",
            )
        applies_to = _clean(row.get("applies_to"))
        if applies_to not in allowed_applies_to:
            report.error(
                "invalid_applies_to",
                STATION_OPERATION_ASSIGNMENTS_FILE,
                row_idx,
                "applies_to",
                "applies_to 必须为 origin、destination、terminal、all 或留空。",
            )
        _row_float(row, "min_occupancy_min", report, STATION_OPERATION_ASSIGNMENTS_FILE, row_idx, required=False, minimum=0.0)


def _validate_trains(rows: List[Dict[str, str]], report: DataValidationReport) -> None:
    """函数 _validate_trains：执行该模块中的相关处理逻辑。"""
    if not rows:
        report.error("too_few_rows", TRAINS_FILE, None, "", "至少需要重车与空车各一条记录。")
        return
    names: set[str] = set()
    allowed_directions = {"forward", "reverse"}
    for row_idx, row in enumerate(rows, start=2):
        name = _clean(row.get("name"))
        if not name:
            report.error("missing_value", TRAINS_FILE, row_idx, "name", "列车名称必填。")
        elif name in names:
            report.error("duplicate_train", TRAINS_FILE, row_idx, "name", f"Duplicate train name {name}.")
        names.add(name)

        _row_float(row, "mass_tons", report, TRAINS_FILE, row_idx, minimum=1.0)
        max_traction = _row_float(
            row,
            "max_traction_kN",
            report,
            TRAINS_FILE,
            row_idx,
            minimum=0.0,
        )
        if max_traction == 0.0:
            report.error(
                "number_too_small",
                TRAINS_FILE,
                row_idx,
                "max_traction_kN",
                "可运行列车的 max_traction_kN 必须大于 0。",
            )
        max_brake = _row_float(
            row,
            "max_brake_kN",
            report,
            TRAINS_FILE,
            row_idx,
            minimum=0.0,
        )
        if max_brake == 0.0:
            report.error(
                "number_too_small",
                TRAINS_FILE,
                row_idx,
                "max_brake_kN",
                "可运行列车的 max_brake_kN 必须大于 0。",
            )
        _row_float(row, "rotational_mass_factor", report, TRAINS_FILE, row_idx, minimum=1.0)
        _row_float(row, "davis_a", report, TRAINS_FILE, row_idx, minimum=0.0)
        _row_float(row, "davis_b", report, TRAINS_FILE, row_idx, minimum=0.0)
        _row_float(row, "davis_c", report, TRAINS_FILE, row_idx, minimum=0.0)
        _row_float(row, "length_km", report, TRAINS_FILE, row_idx, minimum=0.0)
        _row_int(row, "longitudinal_segments", report, TRAINS_FILE, row_idx, minimum=1)
        direction = _clean(row.get("direction")).lower()
        if direction not in allowed_directions:
            report.error("invalid_direction", TRAINS_FILE, row_idx, "direction", "方向必须为 forward 或 reverse。")
        _row_float(
            row,
            "traction_adhesion_weight_fraction",
            report,
            TRAINS_FILE,
            row_idx,
            minimum=0.0,
            maximum=1.0,
        )
        _row_float(
            row,
            "brake_adhesion_weight_fraction",
            report,
            TRAINS_FILE,
            row_idx,
            minimum=0.0,
            maximum=1.0,
        )

    for required_name in ("Heavy", "Empty"):
        if required_name not in names:
            report.error(
                "missing_train_type",
                TRAINS_FILE,
                None,
                "name",
                f"缺少必需的列车记录 {required_name}。",
            )


def _validate_battery(raw: Dict[str, Any], report: DataValidationReport) -> None:
    """函数 _validate_battery：执行该模块中的相关处理逻辑。"""
    for key in ("capacity_kwh", "round_trip_efficiency", "depreciation_cost_per_kwh", "grid_price_per_kwh"):
        if key not in raw:
            report.error("missing_field", BATTERY_FILE, None, key, f"缺少必需字段 {key}。")
    capacity = _field_float(raw, "capacity_kwh", report, BATTERY_FILE, minimum=0.0) if raw else None
    efficiency = (
        _field_float(raw, "round_trip_efficiency", report, BATTERY_FILE, minimum=0.0, maximum=1.0)
        if raw
        else None
    )
    _field_float(raw, "depreciation_cost_per_kwh", report, BATTERY_FILE, minimum=0.0) if raw else None
    _field_float(raw, "grid_price_per_kwh", report, BATTERY_FILE, minimum=0.0) if raw else None
    if raw and "planning_assumption" in raw:
        try:
            _bool(raw.get("planning_assumption"))
        except ValueError:
            report.error(
                "invalid_boolean",
                BATTERY_FILE,
                None,
                "planning_assumption",
                "planning_assumption must be a recognized true/false value.",
            )
    if capacity == 0.0:
        report.warning("zero_battery_capacity", BATTERY_FILE, None, "capacity_kwh", "储能容量为 0。")
    if efficiency == 0.0:
        report.warning(
            "zero_battery_efficiency",
            BATTERY_FILE,
            None,
            "round_trip_efficiency",
            "储能效率为 0，无法回馈可用能量。",
        )
    for key in ("max_charge_power_kW", "max_discharge_power_kW"):
        if key in raw:
            _field_float(raw, key, report, BATTERY_FILE, minimum=0.0)


def _validate_operating_conditions(
    raw: Dict[str, Any],
    total_length_km: Optional[float],
    max_speed_kmh: Optional[float],
    report: DataValidationReport,
) -> None:
    """函数 _validate_operating_conditions：执行该模块中的相关处理逻辑。"""
    if not raw:
        return
    for field_name in (
        "default_adhesion_coefficient",
        "traction_adhesion_safety_factor",
        "braking_adhesion_safety_factor",
    ):
        if field_name not in raw:
            continue
        value = _field_float(
            raw,
            field_name,
            report,
            OPERATING_CONDITIONS_FILE,
            minimum=0.0,
            maximum=1.0,
        )
        if value is not None and value <= 0.0:
            report.error(
                "number_too_small",
                OPERATING_CONDITIONS_FILE,
                None,
                field_name,
                f"Field {field_name} must be greater than 0.",
            )
        if field_name == "default_adhesion_coefficient" and value is not None and value > 0.45:
            report.warning(
                "high_adhesion",
                OPERATING_CONDITIONS_FILE,
                None,
                field_name,
                "Default adhesion is unusually high.",
            )
    for section_name, rows in (
        ("weather_conditions", raw.get("weather_conditions", [])),
        ("adhesion_zones", raw.get("adhesion_zones", [])),
        ("speed_restrictions", raw.get("speed_restrictions", [])),
    ):
        if not isinstance(rows, list):
            report.error("invalid_list", OPERATING_CONDITIONS_FILE, None, section_name, f"{section_name} must be a list.")
            continue
        for idx, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                report.error("invalid_object", OPERATING_CONDITIONS_FILE, idx, section_name, "Entry must be an object.")
                continue
            if section_name == "weather_conditions":
                ranges = item.get("affected_ranges_km", [])
                if not isinstance(ranges, list):
                    report.error(
                        "invalid_list",
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        "affected_ranges_km",
                        "affected_ranges_km must be a list of two-value ranges.",
                    )
                    ranges = []
                for range_idx, raw_range in enumerate(ranges):
                    if not isinstance(raw_range, (list, tuple)) or len(raw_range) != 2:
                        report.error(
                            "invalid_range",
                            OPERATING_CONDITIONS_FILE,
                            idx,
                            f"affected_ranges_km[{range_idx}]",
                            "Each affected range must contain exactly two numeric values.",
                        )
                        continue
                    start_field = f"affected_ranges_km[{range_idx}].start"
                    end_field = f"affected_ranges_km[{range_idx}].end"
                    range_row = {start_field: raw_range[0], end_field: raw_range[1]}
                    start_km = _row_float(
                        range_row,
                        start_field,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        minimum=0.0,
                    )
                    end_km = _row_float(
                        range_row,
                        end_field,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        minimum=0.0,
                    )
                    _range_inside_route(
                        start_km,
                        end_km,
                        total_length_km,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        start_field,
                        end_field,
                    )
                for field_name in (
                    "adhesion_multiplier",
                    "rolling_resistance_multiplier",
                    "aerodynamic_resistance_multiplier",
                    "speed_limit_kmh",
                ):
                    if field_name not in item or item[field_name] is None:
                        continue
                    value = _row_float(
                        item,
                        field_name,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        minimum=0.0,
                    )
                    if value is not None and value <= 0.0:
                        report.error(
                            "number_too_small",
                            OPERATING_CONDITIONS_FILE,
                            idx,
                            field_name,
                            f"Column {field_name} must be greater than 0.",
                        )
                speed = _row_float(
                    item,
                    "speed_limit_kmh",
                    report,
                    OPERATING_CONDITIONS_FILE,
                    idx,
                    required=False,
                    minimum=0.0,
                )
                if speed is not None and max_speed_kmh is not None and speed > max_speed_kmh:
                    report.warning(
                        "weather_speed_above_route_max",
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        "speed_limit_kmh",
                        "Weather speed limit is above route maximum and has no effect.",
                    )
            elif section_name in {"adhesion_zones", "speed_restrictions"}:
                start_km = _row_float(
                    item,
                    "start_km",
                    report,
                    OPERATING_CONDITIONS_FILE,
                    idx,
                    minimum=0.0,
                )
                end_km = _row_float(
                    item,
                    "end_km",
                    report,
                    OPERATING_CONDITIONS_FILE,
                    idx,
                    minimum=0.0,
                )
                if start_km is not None and end_km is not None:
                    _range_inside_route(
                        start_km,
                        end_km,
                        total_length_km,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                    )
                numeric_field = (
                    "adhesion_coefficient"
                    if section_name == "adhesion_zones"
                    else "speed_limit_kmh"
                )
                numeric_value = _row_float(
                    item,
                    numeric_field,
                    report,
                    OPERATING_CONDITIONS_FILE,
                    idx,
                    minimum=0.0,
                    maximum=1.0 if section_name == "adhesion_zones" else None,
                )
                if numeric_value is not None and numeric_value <= 0.0:
                    report.error(
                        "number_too_small",
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        numeric_field,
                        f"Column {numeric_field} must be greater than 0.",
                    )
                if section_name == "speed_restrictions" and "direction" in item:
                    try:
                        normalize_speed_restriction_direction(item["direction"])
                    except ValueError:
                        report.error(
                            "invalid_direction",
                            OPERATING_CONDITIONS_FILE,
                            idx,
                            "direction",
                            "Direction must be forward, reverse, both, down, up, heavy, or empty.",
                        )

            parsed_times: Dict[str, int] = {}
            for time_field in ("start_time_s", "end_time_s"):
                if time_field in item:
                    parsed_time = _row_int(
                        item,
                        time_field,
                        report,
                        OPERATING_CONDITIONS_FILE,
                        idx,
                        minimum=0,
                    )
                    if parsed_time is not None:
                        parsed_times[time_field] = parsed_time
            if (
                "start_time_s" in parsed_times
                and "end_time_s" in parsed_times
                and parsed_times["end_time_s"] < parsed_times["start_time_s"]
            ):
                report.error(
                    "invalid_time_window",
                    OPERATING_CONDITIONS_FILE,
                    idx,
                    "start_time_s,end_time_s",
                    "end_time_s must not precede start_time_s.",
                )


def validate_real_data_bundle(input_dir: Path | str) -> DataValidationReport:
    """函数 validate_real_data_bundle：执行该模块中的相关处理逻辑。"""
    source_dir = Path(input_dir)
    report = DataValidationReport(source_dir=str(source_dir))

    if not source_dir.exists():
        report.error("missing_directory", str(source_dir), None, "", "输入目录不存在。")
        return report
    if not source_dir.is_dir():
        report.error("not_directory", str(source_dir), None, "", "输入路径必须是目录。")
        return report

    for file_name in REQUIRED_FILES:
        if not (source_dir / file_name).exists():
            report.error("missing_file", file_name, None, "", f"Required file {file_name} is missing.")

    metadata = _read_json(source_dir / ROUTE_METADATA_FILE, report, required=True)
    route_raw = _route_meta(metadata)
    total_length_km, max_speed_kmh = _validate_route_metadata(route_raw, report)

    station_rows = _read_csv(source_dir / STATIONS_FILE, report, True, ("name", "position_km"))
    segment_rows = _read_csv(
        source_dir / SEGMENTS_FILE,
        report,
        True,
        ("start_km", "end_km", "gradient_per_mille"),
    )
    energy_rows = _read_csv(source_dir / ENERGY_ZONES_FILE, report, False, ("start_km", "end_km"))
    block_rows = _read_csv(source_dir / SIGNAL_BLOCKS_FILE, report, False, ("start_km", "end_km"))
    station_resource_rows = _read_csv(
        source_dir / STATION_RESOURCES_FILE,
        report,
        False,
        ("station_name", "track_capacity", "throat_capacity"),
    )
    headway_rows = _read_csv(
        source_dir / HEADWAY_CONSTRAINTS_FILE,
        report,
        False,
        ("line", "scope", "headway_min"),
    )
    technical_operation_rows = _read_csv(
        source_dir / TECHNICAL_OPERATION_TIMES_FILE,
        report,
        False,
        (
            "station_name",
            "operation_location",
            "operation_type",
            "spotting_min",
            "loading_unloading_min",
            "pickup_min",
            "total_min",
        ),
    )
    station_operation_assignment_rows = _read_csv(
        source_dir / STATION_OPERATION_ASSIGNMENTS_FILE,
        report,
        False,
        ("station_name", "train_type", "direction", "applies_to"),
    )
    pdf_station_master_rows = _read_csv(
        source_dir / PDF_STATION_MASTER_FILE,
        report,
        False,
        ("line", "station_name", "position_km"),
    )
    train_rows = _read_csv(
        source_dir / TRAINS_FILE,
        report,
        True,
        (
            "name",
            "mass_tons",
            "max_traction_kN",
            "max_brake_kN",
            "rotational_mass_factor",
            "davis_a",
            "davis_b",
            "davis_c",
            "length_km",
            "longitudinal_segments",
            "direction",
            "traction_adhesion_weight_fraction",
            "brake_adhesion_weight_fraction",
        ),
    )
    battery_raw = _read_json(source_dir / BATTERY_FILE, report, required=True)
    operating_raw = _read_json(source_dir / OPERATING_CONDITIONS_FILE, report, required=False)
    resource_config_raw = _read_json(source_dir / RESOURCE_CONFIG_FILE, report, required=False)

    _validate_stations(station_rows, total_length_km, report)
    _validate_segments(segment_rows, total_length_km, max_speed_kmh, report)
    _validate_energy_zones(energy_rows, total_length_km, report)
    _validate_signaling_blocks(block_rows, total_length_km, report)
    station_names = {_clean(row.get("name")) for row in station_rows if _clean(row.get("name"))}
    model_pdf_station_master_rows = [row for row in pdf_station_master_rows if _is_model_line_name(row.get("line"))]
    out_of_scope_pdf_station_master_rows = [row for row in pdf_station_master_rows if not _is_model_line_name(row.get("line"))]
    known_pdf_station_names = {
        _clean(row.get("station_name"))
        for row in model_pdf_station_master_rows
        if _clean(row.get("station_name"))
    }
    _validate_station_resources(station_resource_rows, station_names, report)
    _validate_headway_constraints(headway_rows, report)
    _validate_technical_operation_times(technical_operation_rows, station_names, known_pdf_station_names, report)
    _validate_station_operation_assignments(station_operation_assignment_rows, station_names, report)
    _validate_trains(train_rows, report)
    _validate_battery(battery_raw, report)

    if out_of_scope_pdf_station_master_rows:
        preview = ", ".join(sorted({f"{_clean(row.get('line'))}:{_clean(row.get('station_name'))}" for row in out_of_scope_pdf_station_master_rows})[:8])
        report.warning(
            "pdf_station_master_out_of_scope",
            PDF_STATION_MASTER_FILE,
            None,
            "line",
            f"PDF 车站表含非正线记录，当前仅正线建模已将其排除：{preview}。",
            "这些记录仅作旁路参考，不参与正线调度模型。",
        )

    route_operating_raw = route_raw.get("operating_conditions", {})
    if operating_raw and route_operating_raw:
        report.warning(
            "operating_conditions_override",
            OPERATING_CONDITIONS_FILE,
            None,
            "",
            "route_metadata.json 与 operating_conditions.json 都定义了运营条件，以独立文件为准。",
        )
    _validate_operating_conditions(operating_raw or route_operating_raw, total_length_km, max_speed_kmh, report)

    if resource_config_raw:
        positive_whole_fields = {
            "station_track_capacity",
            "terminal_track_capacity",
            "throat_capacity",
            "station_occupancy_s",
            "throat_occupancy_s",
            "conflict_limit",
        }
        non_negative_whole_fields = {
            "section_release_margin_s",
            "min_depart_headway_s",
            "min_overlap_s",
            "initial_heavy_flow_count",
            "initial_empty_flow_count",
        }
        for key in positive_whole_fields | non_negative_whole_fields | {"section_capacity_spacing_km"}:
            if key not in resource_config_raw:
                continue
            value = resource_config_raw[key]
            if isinstance(value, bool):
                report.error(
                    "invalid_number",
                    RESOURCE_CONFIG_FILE,
                    None,
                    key,
                    f"{key} must be numeric, not boolean.",
                )
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                report.error("invalid_number", RESOURCE_CONFIG_FILE, None, key, f"{key} must be numeric.")
                continue
            if not math.isfinite(parsed):
                report.error("invalid_number", RESOURCE_CONFIG_FILE, None, key, f"{key} must be finite.")
                continue
            if key in positive_whole_fields and parsed < 1.0:
                report.error("number_too_small", RESOURCE_CONFIG_FILE, None, key, f"{key} must be positive.")
            elif key in non_negative_whole_fields and parsed < 0.0:
                report.error("number_too_small", RESOURCE_CONFIG_FILE, None, key, f"{key} must be non-negative.")
            elif key == "section_capacity_spacing_km" and parsed <= 0.0:
                report.error("number_too_small", RESOURCE_CONFIG_FILE, None, key, f"{key} must be positive.")
            if key != "section_capacity_spacing_km" and not parsed.is_integer():
                report.error("invalid_integer", RESOURCE_CONFIG_FILE, None, key, f"{key} must be an integer.")
        raw_single_line_ranges = resource_config_raw.get("single_line_ranges_km", [])
        if not isinstance(raw_single_line_ranges, list):
            report.error(
                "invalid_list",
                RESOURCE_CONFIG_FILE,
                None,
                "single_line_ranges_km",
                "single_line_ranges_km must be a list of two-value ranges.",
            )
        else:
            for index, raw_range in enumerate(raw_single_line_ranges):
                field_name = f"single_line_ranges_km[{index}]"
                try:
                    start_km, end_km = _as_range(raw_range)
                except (TypeError, ValueError):
                    report.error(
                        "invalid_range",
                        RESOURCE_CONFIG_FILE,
                        None,
                        field_name,
                        "Each single-line range must contain exactly two finite numeric values.",
                    )
                    continue
                _range_inside_route(
                    start_km,
                    end_km,
                    total_length_km,
                    report,
                    RESOURCE_CONFIG_FILE,
                    None,
                    f"{field_name}.start",
                    f"{field_name}.end",
                )
        if "enforce_flow_continuity" in resource_config_raw:
            try:
                _bool(resource_config_raw["enforce_flow_continuity"])
            except ValueError:
                report.error(
                    "invalid_boolean",
                    RESOURCE_CONFIG_FILE,
                    None,
                    "enforce_flow_continuity",
                    "enforce_flow_continuity must be a recognized true/false value.",
                )

    return report


def _load_stations(source_dir: Path) -> List[Station]:
    """函数 _load_stations：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(source_dir / STATIONS_FILE, DataValidationReport(str(source_dir)), True, ("name", "position_km"))
    stations = [Station(name=_clean(row["name"]), position_km=_float(row["position_km"])) for row in rows]
    return sorted(stations, key=lambda station: station.position_km)


def _load_segments_and_speed_limits(
    source_dir: Path,
    max_speed_kmh: float,
) -> Tuple[List[Segment], List[Dict[str, Any]]]:
    """函数 _load_segments_and_speed_limits：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(
        source_dir / SEGMENTS_FILE,
        DataValidationReport(str(source_dir)),
        True,
        ("start_km", "end_km", "gradient_per_mille"),
    )
    segments: List[Segment] = []
    static_restrictions: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        start_km = _float(row.get("start_km"))
        end_km = _float(row.get("end_km"))
        speed_limit = _optional_float(row.get("speed_limit_kmh"))
        segments.append(
            Segment(
                start_km=start_km,
                end_km=end_km,
                gradient_per_mille=_float(row.get("gradient_per_mille")),
                curve_radius_m=_optional_float(row.get("curve_radius_m")),
                terrain=_clean(row.get("terrain")) or "plain",
            )
        )
        if speed_limit is not None and speed_limit < max_speed_kmh - 1e-6:
            static_restrictions.append(
                {
                    "name": f"static_segment_speed_{idx:04d}",
                    "start_km": start_km,
                    "end_km": end_km,
                    "speed_limit_kmh": speed_limit,
                    "start_time_s": 0,
                    "end_time_s": OPEN_ENDED_TIME_S,
                    "reason": "static infrastructure speed limit from segments.csv",
                }
            )
    return sorted(segments, key=lambda segment: segment.start_km), static_restrictions


def _load_energy_ranges(source_dir: Path) -> List[Tuple[float, float]]:
    """函数 _load_energy_ranges：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(source_dir / ENERGY_ZONES_FILE, DataValidationReport(str(source_dir)), False, ("start_km", "end_km"))
    active_rows = []
    for row in rows:
        active_raw = _clean(row.get("active_in_operational_baseline"))
        if active_raw and not _bool(active_raw):
            continue
        if not active_raw and _clean(row.get("implementation_status")).lower() == "planned":
            continue
        active_rows.append(row)
    return [(_float(row.get("start_km")), _float(row.get("end_km"))) for row in active_rows]


def _load_flexible_energy_transfer_zones(source_dir: Path) -> Tuple[Dict[str, Any], ...]:
    """Load active flexible-transfer facilities with their electrical limits."""
    rows = _read_csv(source_dir / ENERGY_ZONES_FILE, DataValidationReport(str(source_dir)), False, ("start_km", "end_km"))
    zones = []
    for index, row in enumerate(rows, start=1):
        active_raw = _clean(row.get("active_in_operational_baseline"))
        if active_raw and not _bool(active_raw):
            continue
        if not active_raw and _clean(row.get("implementation_status")).lower() == "planned":
            continue
        power_raw = _clean(row.get("max_transfer_power_kW"))
        efficiency_raw = _clean(row.get("efficiency"))
        if not power_raw or not efficiency_raw:
            continue
        zones.append({
            "zone_id": _clean(row.get("zone_id")) or f"ZONE-{index:03d}",
            "start_km": _float(row.get("start_km")),
            "end_km": _float(row.get("end_km")),
            "max_transfer_power_kW": _float(power_raw),
            "efficiency": _float(efficiency_raw),
        })
    return tuple(zones)


def _parse_locomotive_consist(text: str) -> Optional[tuple]:
    """解析 ``"SHENHUA_12:1|HXD1_25t:1"`` 形式的混合编组清单。

    为空时返回 ``None``，让 ``TrainParameters`` 回退到
    ``locomotive_type`` + ``locomotive_count`` 的单一机型口径。
    """

    raw = _clean(text)
    if not raw:
        return None
    items: list[tuple[str, int]] = []
    for chunk in raw.replace(";", "|").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(
                f"locomotive_consist entry must be 'TYPE:COUNT', got {chunk!r} in {raw!r}"
            )
        loco_type, count_text = chunk.rsplit(":", 1)
        loco_type = loco_type.strip()
        if not loco_type:
            raise ValueError(f"locomotive_consist entry has empty type, got {raw!r}")
        count = _int(count_text.strip(), 0)
        if count < 0:
            raise ValueError(f"locomotive_consist count must be non-negative, got {count!r}")
        items.append((loco_type, count))
    return tuple(items) if items else None


def _serialise_locomotive_consist(consist) -> str:
    """把混合编组清单写回 ``"TYPE:COUNT|TYPE:COUNT"`` 形式，保证数据往返不丢信息。"""

    if not consist:
        return ""
    return "|".join(f"{loco_type}:{count}" for loco_type, count in consist)


def _load_trains(source_dir: Path) -> Dict[str, TrainParameters]:
    """函数 _load_trains：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(
        source_dir / TRAINS_FILE,
        DataValidationReport(str(source_dir)),
        True,
        ("name", "mass_tons"),
    )
    trains: Dict[str, TrainParameters] = {}
    for row in rows:
        name = _clean(row.get("name"))
        davis = DavisCoefficients(
            a=_float(row.get("davis_a")),
            b=_float(row.get("davis_b")),
            c=_float(row.get("davis_c")),
        )
        trains[name] = TrainParameters(
            name=name,
            mass_tons=_float(row.get("mass_tons")),
            max_traction_kN=_float(row.get("max_traction_kN")),
            max_brake_kN=_float(row.get("max_brake_kN")),
            rotational_mass_factor=_float(row.get("rotational_mass_factor"), 1.0),
            davis=davis,
            length_km=_float(row.get("length_km")),
            longitudinal_segments=_int(row.get("longitudinal_segments"), 1),
            direction=_clean(row.get("direction")).lower() or "forward",
            traction_adhesion_weight_fraction=_float(row.get("traction_adhesion_weight_fraction"), 1.0),
            brake_adhesion_weight_fraction=_float(row.get("brake_adhesion_weight_fraction"), 1.0),
            max_power_kW=_float(row.get("max_power_kW"), 0.0),
            mass_data_status=_clean(row.get("mass_data_status")) or "fixed_parameter",
            mass_min_tons=_optional_float(row.get("mass_min_tons")),
            mass_max_tons=_optional_float(row.get("mass_max_tons")),
            mass_note=_clean(row.get("mass_note")),
            locomotive_type=_clean(row.get("locomotive_type")) or None,
            locomotive_count=_int(row.get("locomotive_count"), 0),
            locomotive_consist=_parse_locomotive_consist(row.get("locomotive_consist") or ""),
            freight_load_state=_clean(row.get("freight_load_state")) or None,
        )
    return trains


def _load_battery(source_dir: Path, *, ignore_installed_storage: bool = False) -> BatteryStorageParameters:
    """函数 _load_battery：执行该模块中的相关处理逻辑。"""
    raw = json.loads((source_dir / BATTERY_FILE).read_text(encoding="utf-8"))
    devices: Tuple[StorageDeviceParameters, ...] = ()
    device_path = source_dir / STORAGE_DEVICES_FILE
    if device_path.is_file() and not ignore_installed_storage:
        device_rows = json.loads(device_path.read_text(encoding="utf-8"))
        if not isinstance(device_rows, list) or not device_rows:
            raise ValueError(f"{STORAGE_DEVICES_FILE} must contain a non-empty JSON array")
        if any(not isinstance(item, dict) for item in device_rows):
            raise ValueError(f"{STORAGE_DEVICES_FILE} entries must be JSON objects")
        devices = tuple(
            StorageDeviceParameters(
                storage_section_id=item.get("storage_section_id") or item.get("storage_code"),
                capacity_kwh=item.get("capacity_kwh"),
                max_charge_power_kw=item.get("max_charge_power_kw"),
                max_discharge_power_kw=item.get("max_discharge_power_kw"),
                charge_efficiency=item.get("charge_efficiency"),
                discharge_efficiency=item.get("discharge_efficiency"),
                initial_soc_kwh=item.get("initial_soc_kwh", 0.0),
                min_soc_kwh=item.get("min_soc_kwh", 0.0),
                max_soc_kwh=item.get("max_soc_kwh"),
                available=item.get("available", True),
                self_discharge_rate_per_hour=item.get("self_discharge_rate_per_hour", 0.0),
                data_status=str(item.get("data_status", "unknown")),
                source_note=str(item.get("source_note", "")),
            )
            for item in device_rows
        )
    capacity_kwh = sum(item.capacity_kwh for item in devices) if devices else raw.get("capacity_kwh", 0.0)
    max_charge_power_kw = (
        sum(item.max_charge_power_kw for item in devices)
        if devices else raw.get("max_charge_power_kW", 0.0)
    )
    max_discharge_power_kw = (
        sum(item.max_discharge_power_kw for item in devices)
        if devices else raw.get("max_discharge_power_kW", 0.0)
    )
    if devices:
        capacity_total = sum(item.capacity_kwh for item in devices)
        round_trip_efficiency = sum(
            item.capacity_kwh * item.charge_efficiency * item.discharge_efficiency
            for item in devices
        ) / capacity_total
    else:
        round_trip_efficiency = raw.get("round_trip_efficiency", 0.0)
    return BatteryStorageParameters(
        capacity_kwh=capacity_kwh,
        max_charge_power_kW=max_charge_power_kw,
        max_discharge_power_kW=max_discharge_power_kw,
        round_trip_efficiency=round_trip_efficiency,
        depreciation_cost_per_kwh=raw.get("depreciation_cost_per_kwh", 0.0),
        grid_price_per_kwh=raw.get("grid_price_per_kwh", 0.0),
        data_status=str(raw.get("data_status", "unknown")),
        scenario_name=str(raw.get("scenario_name", "")),
        planning_assumption=_bool(raw.get("planning_assumption", False)),
        note=str(raw.get("note", "")),
        storage_devices=devices,
        depreciation_cost_basis=raw.get("depreciation_cost_basis", "total_throughput"),
    )


def load_storage_device_parameters(
    source_dir: Path | str,
) -> Tuple[StorageDeviceParameters, ...]:
    """读取数据库快照适配文件中的逐设备静态参数。"""

    root = Path(source_dir)
    if not (root / STORAGE_DEVICES_FILE).is_file():
        return ()
    return _load_battery(root).storage_devices


def _load_resource_config(source_dir: Path) -> ResourceConfig:
    """函数 _load_resource_config：执行该模块中的相关处理逻辑。"""
    raw: Dict[str, Any] = {}
    path = source_dir / RESOURCE_CONFIG_FILE
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))

    single_line_ranges: List[Tuple[float, float]] = []
    for item in raw.get("single_line_ranges_km", []):
        single_line_ranges.append(_as_range(item))

    block_rows = _read_csv(source_dir / SIGNAL_BLOCKS_FILE, DataValidationReport(str(source_dir)), False, ("start_km", "end_km"))
    for row in block_rows:
        direction = _clean(row.get("direction")).lower()
        if _bool(row.get("is_single_line")) or direction == "shared":
            single_line_ranges.append((_float(row.get("start_km")), _float(row.get("end_km"))))

    defaults = ResourceConfig()
    min_depart_headway_s = _int(raw.get("min_depart_headway_s"), defaults.min_depart_headway_s)
    min_depart_headway_source = _clean(raw.get("min_depart_headway_source"))
    for row in _read_csv(
        source_dir / HEADWAY_CONSTRAINTS_FILE,
        DataValidationReport(str(source_dir)),
        False,
        ("line", "scope", "headway_min"),
    ):
        if not _is_model_line_name(row.get("line")):
            continue
        if _headway_train_category(_clean(row.get("scope"))) != "Heavy":
            continue
        candidate_s = int(round(_float(row.get("headway_min")) * 60.0))
        if candidate_s > min_depart_headway_s:
            min_depart_headway_s = candidate_s
            min_depart_headway_source = (
                f"{HEADWAY_CONSTRAINTS_FILE}: "
                f"{_clean(row.get('line'))} {_clean(row.get('scope'))}"
            )

    return ResourceConfig(
        station_track_capacity=_int(raw.get("station_track_capacity"), defaults.station_track_capacity),
        terminal_track_capacity=_int(raw.get("terminal_track_capacity"), defaults.terminal_track_capacity),
        throat_capacity=_int(raw.get("throat_capacity"), defaults.throat_capacity),
        station_occupancy_s=_int(raw.get("station_occupancy_s"), defaults.station_occupancy_s),
        throat_occupancy_s=_int(raw.get("throat_occupancy_s"), defaults.throat_occupancy_s),
        section_release_margin_s=_int(raw.get("section_release_margin_s"), defaults.section_release_margin_s),
        section_capacity_spacing_km=_float(raw.get("section_capacity_spacing_km"), defaults.section_capacity_spacing_km),
        single_line_ranges_km=tuple(single_line_ranges),
        min_depart_headway_s=min_depart_headway_s,
        min_depart_headway_source=min_depart_headway_source,
        min_overlap_s=_int(raw.get("min_overlap_s"), defaults.min_overlap_s),
        conflict_limit=_int(raw.get("conflict_limit"), defaults.conflict_limit),
        initial_heavy_flow_count=_int(raw.get("initial_heavy_flow_count"), defaults.initial_heavy_flow_count),
        initial_empty_flow_count=_int(raw.get("initial_empty_flow_count"), defaults.initial_empty_flow_count),
        enforce_flow_continuity=_bool(raw.get("enforce_flow_continuity"))
        if "enforce_flow_continuity" in raw
        else defaults.enforce_flow_continuity,
    )


def _load_station_capacity_maps(source_dir: Path) -> Tuple[Dict[str, int], Dict[str, int]]:
    """函数 _load_station_capacity_maps：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(
        source_dir / STATION_RESOURCES_FILE,
        DataValidationReport(str(source_dir)),
        False,
        ("station_name", "track_capacity", "throat_capacity"),
    )
    track_capacities: Dict[str, int] = {}
    throat_capacities: Dict[str, int] = {}
    for row in rows:
        name = _clean(row.get("station_name") or row.get("name"))
        if not name:
            continue
        track_capacities[name] = max(1, _int(row.get("track_capacity"), 1))
        throat_capacities[name] = max(1, _int(row.get("throat_capacity"), 1))
    return track_capacities, throat_capacities


def _load_station_operation_maps(
    source_dir: Path,
    station_names: set[str],
) -> Tuple[Dict[str, int], Dict[str, str], Dict[str, Dict[str, Any]]]:
    """函数 _load_station_operation_maps：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(
        source_dir / TECHNICAL_OPERATION_TIMES_FILE,
        DataValidationReport(str(source_dir)),
        False,
        ("station_name", "total_min"),
    )
    occupancies: Dict[str, int] = {}
    sources: Dict[str, str] = {}
    details: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = _clean(row.get("station_name"))
        if not name or name not in station_names:
            continue
        total_min = _optional_float(row.get("total_min"))
        if total_min is None:
            continue
        total_s = int(round(total_min * 60.0))
        if total_s > occupancies.get(name, 0):
            cars_text = _clean(row.get("cars"))
            try:
                cars_value = _optional_int(cars_text) or 0
            except ValueError:
                try:
                    float(cars_text)
                except ValueError:
                    cars_value = 0
                else:
                    raise
            occupancies[name] = total_s
            sources[name] = (
                f"{TECHNICAL_OPERATION_TIMES_FILE}: "
                f"{name} {_clean(row.get('operation_location'))} {_clean(row.get('operation_type'))}"
            )
            details[name] = {
                "station_name": name,
                "source_station_name": _clean(row.get("source_station_name")),
                "operation_location": _clean(row.get("operation_location")),
                "cars": cars_value,
                "cars_text": cars_text,
                "operation_type": _clean(row.get("operation_type")),
                "spotting_s": int(round((_optional_float(row.get("spotting_min")) or 0.0) * 60.0)),
                "loading_unloading_s": int(round((_optional_float(row.get("loading_unloading_min")) or 0.0) * 60.0)),
                "pickup_s": int(round((_optional_float(row.get("pickup_min")) or 0.0) * 60.0)),
                "total_s": total_s,
                "source_pages": _clean(row.get("source_pages")),
                "confidence": _clean(row.get("confidence")),
                "note": _clean(row.get("note")),
                "source": sources[name],
            }
    return occupancies, sources, details


def _load_station_operation_assignments(source_dir: Path) -> Tuple[Dict[str, Any], ...]:
    """函数 _load_station_operation_assignments：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(
        source_dir / STATION_OPERATION_ASSIGNMENTS_FILE,
        DataValidationReport(str(source_dir)),
        False,
        ("station_name", "train_type", "direction", "applies_to"),
    )
    assignments: List[Dict[str, Any]] = []
    for row in rows:
        station_name = _clean(row.get("station_name"))
        if not station_name:
            continue
        min_occupancy_min = _optional_float(row.get("min_occupancy_min"))
        assignments.append(
            {
                "station_name": station_name,
                "train_type": _clean(row.get("train_type")),
                "direction": _clean(row.get("direction")),
                "applies_to": _clean(row.get("applies_to")) or "all",
                "min_occupancy_s": 0 if min_occupancy_min is None else int(round(min_occupancy_min * 60.0)),
                "source": _clean(row.get("source")),
                "note": _clean(row.get("note")),
            }
        )
    return tuple(assignments)


def _load_block_boundaries(source_dir: Path) -> List[Dict[str, Any]]:
    """函数 _load_block_boundaries：执行该模块中的相关处理逻辑。"""
    rows = _read_csv(source_dir / SIGNAL_BLOCKS_FILE, DataValidationReport(str(source_dir)), False, ("start_km", "end_km"))
    blocks: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        blocks.append(
            {
                "block_id": _clean(row.get("block_id")) or f"B{idx:04d}",
                "start_km": _float(row.get("start_km")),
                "end_km": _float(row.get("end_km")),
                "direction": _clean(row.get("direction")) or "both",
                "block_type": _clean(row.get("block_type")) or "fixed",
                "is_single_line": _bool(row.get("is_single_line")),
            }
        )
    return blocks


def load_real_data_bundle(input_dir: Path | str, validate: bool = True, *, ignore_installed_storage: bool = False) -> IngestedDataBundle:
    """函数 load_real_data_bundle：执行该模块中的相关处理逻辑。"""
    source_dir = Path(input_dir)
    from locomotive_curves import use_snapshot_curve_bank
    curve_path = source_dir / "locomotive_curves.json"
    if not curve_path.is_file():
        with (source_dir / TRAINS_FILE).open(encoding="utf-8-sig", newline="") as handle:
            if any(row.get("locomotive_type") or row.get("locomotive_consist") for row in csv.DictReader(handle)):
                raise ValueError("列车配置了机车编组，但冻结输入缺少locomotive_curves.json，请创建并补齐新数据版本。")
    use_snapshot_curve_bank(curve_path)
    report = validate_real_data_bundle(source_dir)
    if validate:
        report.raise_for_errors()

    metadata = json.loads((source_dir / ROUTE_METADATA_FILE).read_text(encoding="utf-8"))
    route_raw = _route_meta(metadata)
    total_length_km = float(route_raw["total_length_km"])
    max_speed_kmh = float(route_raw["max_speed_kmh"])

    segments, static_speed_restrictions = _load_segments_and_speed_limits(source_dir, max_speed_kmh)
    operating_raw = {}
    operating_path = source_dir / OPERATING_CONDITIONS_FILE
    if operating_path.exists():
        operating_raw = json.loads(operating_path.read_text(encoding="utf-8"))
    elif isinstance(route_raw.get("operating_conditions"), dict):
        operating_raw = dict(route_raw["operating_conditions"])
    else:
        operating_raw = {}

    if static_speed_restrictions:
        operating_raw = dict(operating_raw)
        operating_raw["speed_restrictions"] = list(operating_raw.get("speed_restrictions", [])) + static_speed_restrictions

    signaling_system = dict(route_raw.get("signaling_system", {}))
    block_boundaries = _load_block_boundaries(source_dir)
    if block_boundaries:
        signaling_system["block_boundaries"] = block_boundaries

    route = RouteData(
        total_length_km=total_length_km,
        max_speed_kmh=max_speed_kmh,
        stations=_load_stations(source_dir),
        segments=segments,
        long_downhill_range_km=_normalized_long_downhill_range(route_raw.get("long_downhill_range_km", [0.0, 0.0])),
        energy_transfer_ranges_km=_load_energy_ranges(source_dir),
        signaling_system=signaling_system,
        operating_conditions=operating_conditions_from_dict(operating_raw),
        flexible_energy_transfer_zones=_load_flexible_energy_transfer_zones(source_dir),
    )
    trains = _load_trains(source_dir)
    battery = _load_battery(source_dir, ignore_installed_storage=ignore_installed_storage)
    track_capacities, throat_capacities = _load_station_capacity_maps(source_dir)
    station_names = {station.name for station in route.stations}
    (
        station_operation_min_times_s,
        station_operation_sources,
        station_operation_details,
    ) = _load_station_operation_maps(source_dir, station_names)
    resource_model = ResourceModel(
        stations=tuple(route.stations),
        config=_load_resource_config(source_dir),
        station_track_capacities=track_capacities,
        station_throat_capacities=throat_capacities,
        station_operation_min_times_s=station_operation_min_times_s,
        station_operation_sources=station_operation_sources,
        station_operation_details=station_operation_details,
        station_operation_assignments=_load_station_operation_assignments(source_dir),
    )
    return IngestedDataBundle(
        source_dir=source_dir,
        route=route,
        trains=trains,
        battery=battery,
        resource_model=resource_model,
        validation_report=report,
        route_metadata=metadata,
    )


def write_validation_report(report: DataValidationReport, output_dir: Path | str) -> None:
    """函数 write_validation_report：执行该模块中的相关处理逻辑。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = report.to_rows()
    csv_path = output_dir / "data_validation_report.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["severity", "code", "file", "row", "field", "message", "suggestion"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "data_validation_summary.json").write_text(
        json.dumps(report.summary(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_sandbox_config(bundle: IngestedDataBundle, output_path: Path | str) -> None:
    """函数 write_sandbox_config：执行该模块中的相关处理逻辑。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "route": asdict(bundle.route),
        "trains": [asdict(train) for train in bundle.trains.values()],
        "battery": asdict(bundle.battery),
    }
    output_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _clear_output_dir(output_dir: Path) -> None:
    """函数 _clear_output_dir：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    for file_name in (
        ROUTE_METADATA_FILE,
        STATIONS_FILE,
        SEGMENTS_FILE,
        ENERGY_ZONES_FILE,
        SIGNAL_BLOCKS_FILE,
        STATION_RESOURCES_FILE,
        TRAINS_FILE,
        BATTERY_FILE,
        OPERATING_CONDITIONS_FILE,
        RESOURCE_CONFIG_FILE,
        POWER_ARM_INTERVALS_FILE,
    ):
        path = output_dir / file_name
        if path.exists():
            path.unlink()


def write_real_data_template_from_config(
    config_path: Path | str,
    output_dir: Path | str,
    overwrite: bool = True,
) -> None:
    """函数 write_real_data_template_from_config：执行该模块中的相关处理逻辑。"""
    from train_simulator import load_config

    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"{output_dir} is not empty.")
    _clear_output_dir(output_dir)

    route, trains, battery = load_config(Path(config_path))
    raw_block_length = route.signaling_system.get("fixed_block_length_km", 2.0)
    if isinstance(raw_block_length, bool):
        raise ValueError(
            "route.signaling_system.fixed_block_length_km must be a finite positive number"
        )
    try:
        block_length_km = float(raw_block_length)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "route.signaling_system.fixed_block_length_km must be a finite positive number"
        ) from exc
    if not math.isfinite(block_length_km) or block_length_km <= 0.0:
        raise ValueError(
            "route.signaling_system.fixed_block_length_km must be a finite positive number"
        )
    route_metadata = {
        "schema_version": SCHEMA_VERSION,
        "line_name": "shuohuang_virtual_template",
        "data_status": "virtual_template_waiting_for_official_data",
        "route": {
            "total_length_km": route.total_length_km,
            "max_speed_kmh": route.max_speed_kmh,
            "long_downhill_range_km": list(route.long_downhill_range_km),
            "signaling_system": route.signaling_system,
        },
    }
    (output_dir / ROUTE_METADATA_FILE).write_text(
        json.dumps(route_metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _write_csv(
        output_dir / STATIONS_FILE,
        ["station_id", "name", "position_km"],
        [
            {
                "station_id": f"S{idx:03d}",
                "name": station.name,
                "position_km": f"{station.position_km:.3f}",
            }
            for idx, station in enumerate(route.stations, start=1)
        ],
    )

    _write_csv(
        output_dir / SEGMENTS_FILE,
        ["segment_id", "start_km", "end_km", "gradient_per_mille", "curve_radius_m", "terrain", "speed_limit_kmh"],
        [
            {
                "segment_id": f"G{idx:04d}",
                "start_km": f"{segment.start_km:.3f}",
                "end_km": f"{segment.end_km:.3f}",
                "gradient_per_mille": f"{segment.gradient_per_mille:.6f}",
                "curve_radius_m": "" if segment.curve_radius_m is None else f"{segment.curve_radius_m:.3f}",
                "terrain": segment.terrain,
                "speed_limit_kmh": "",
            }
            for idx, segment in enumerate(route.segments, start=1)
        ],
    )

    _write_csv(
        output_dir / ENERGY_ZONES_FILE,
        ["zone_id", "name", "start_km", "end_km", "max_transfer_power_kW", "efficiency"],
        [
            {
                "zone_id": f"F{idx:03d}",
                "name": f"flexible_power_zone_{idx:03d}",
                "start_km": f"{start:.3f}",
                "end_km": f"{end:.3f}",
                "max_transfer_power_kW": "",
                "efficiency": "",
            }
            for idx, (start, end) in enumerate(route.energy_transfer_ranges_km, start=1)
        ],
    )

    storage_zones = []
    for idx, (raw_start, raw_end) in enumerate(route.energy_transfer_ranges_km, start=1):
        start_km = max(0.0, min(float(raw_start), float(raw_end)))
        end_km = min(float(route.total_length_km), max(float(raw_start), float(raw_end)))
        if end_km <= start_km:
            continue
        storage_zones.append(
            {
                "storage_section_id": f"virtual_storage_section_{idx}:K{start_km:g}-K{end_km:g}",
                "start_km": start_km,
                "end_km": end_km,
            }
        )

    boundaries = {0.0, float(route.total_length_km)}
    for zone in storage_zones:
        boundaries.update((zone["start_km"], zone["end_km"]))
    ordered_boundaries = sorted(boundaries)
    power_arm_rows = []
    for direction_code, direction_name in (("F", "down"), ("R", "up")):
        for interval_idx, (start_km, end_km) in enumerate(
            zip(ordered_boundaries, ordered_boundaries[1:]),
            start=1,
        ):
            matched_zones = [
                zone
                for zone in storage_zones
                if max(start_km, zone["start_km"]) < min(end_km, zone["end_km"])
            ]
            storage_ids = ";".join(str(zone["storage_section_id"]) for zone in matched_zones)
            section_id = f"VPA-{direction_code}-{interval_idx:03d}"
            power_arm_rows.append(
                {
                    "section_id": section_id,
                    "power_arm_id": section_id,
                    "road": "Shuohuang",
                    "direction": direction_name,
                    "start_km": f"{start_km:.6f}",
                    "end_km": f"{end_km:.6f}",
                    "max_traction_supply_kw": "1000000",
                    "max_regen_absorption_kw": "1000000",
                    "max_grid_feedback_kw": "1000000",
                    "up_down_feed_rule": "scenario_controlled",
                    "grid_feedback_rule": "not_credited_by_current_dispatch_model",
                    "electrical_limit_status": "virtual_non_binding_until_official_limits",
                    "electrical_limit_note": "Generated virtual template; replace with official power-arm limits.",
                    "storage_available": "true" if storage_ids else "false",
                    "storage_section_id": storage_ids,
                    "storage_start_km": "",
                    "storage_end_km": "",
                    "storage_status": (
                        "virtual_template_from_energy_transfer_zones"
                        if storage_ids
                        else "no_storage_in_current_section"
                    ),
                    "storage_note": (
                        "Derived from route.energy_transfer_ranges_km."
                        if storage_ids
                        else "No configured storage zone overlaps this interval."
                    ),
                }
            )
    _write_csv(
        output_dir / POWER_ARM_INTERVALS_FILE,
        [
            "section_id",
            "power_arm_id",
            "road",
            "direction",
            "start_km",
            "end_km",
            "max_traction_supply_kw",
            "max_regen_absorption_kw",
            "max_grid_feedback_kw",
            "up_down_feed_rule",
            "grid_feedback_rule",
            "electrical_limit_status",
            "electrical_limit_note",
            "storage_available",
            "storage_section_id",
            "storage_start_km",
            "storage_end_km",
            "storage_status",
            "storage_note",
        ],
        power_arm_rows,
    )

    block_rows = []
    cursor = 0.0
    block_idx = 1
    while cursor < route.total_length_km - 1e-9:
        end_km = min(route.total_length_km, cursor + block_length_km)
        block_rows.append(
            {
                "block_id": f"B{block_idx:04d}",
                "start_km": f"{cursor:.3f}",
                "end_km": f"{end_km:.3f}",
                "direction": "both",
                "block_type": "fixed",
                "is_single_line": "false",
            }
        )
        cursor = end_km
        block_idx += 1
    _write_csv(
        output_dir / SIGNAL_BLOCKS_FILE,
        ["block_id", "start_km", "end_km", "direction", "block_type", "is_single_line"],
        block_rows,
    )

    _write_csv(
        output_dir / STATION_RESOURCES_FILE,
        ["station_name", "track_capacity", "throat_capacity", "is_terminal"],
        [
            {
                "station_name": station.name,
                "track_capacity": 4 if idx in {0, len(route.stations) - 1} else 2,
                "throat_capacity": 1,
                "is_terminal": "true" if idx in {0, len(route.stations) - 1} else "false",
            }
            for idx, station in enumerate(route.stations)
        ],
    )

    _write_csv(
        output_dir / TRAINS_FILE,
        [
            "name",
            "mass_tons",
            "max_traction_kN",
            "max_brake_kN",
            "rotational_mass_factor",
            "davis_a",
            "davis_b",
            "davis_c",
            "length_km",
            "longitudinal_segments",
            "direction",
            "traction_adhesion_weight_fraction",
            "brake_adhesion_weight_fraction",
            "locomotive_type",
            "locomotive_count",
            "locomotive_consist",
            "freight_load_state",
        ],
        [
            {
                "name": train.name,
                "mass_tons": (
                    train.vehicle_mass_tons
                    if getattr(train, "vehicle_mass_tons", None) is not None
                    else train.mass_tons
                ),
                "max_traction_kN": train.max_traction_kN,
                "max_brake_kN": train.max_brake_kN,
                "rotational_mass_factor": train.rotational_mass_factor,
                "davis_a": train.davis.a,
                "davis_b": train.davis.b,
                "davis_c": train.davis.c,
                "length_km": train.length_km,
                "longitudinal_segments": train.longitudinal_segments,
                "direction": train.direction,
                "traction_adhesion_weight_fraction": train.traction_adhesion_weight_fraction,
                "brake_adhesion_weight_fraction": train.brake_adhesion_weight_fraction,
                "locomotive_type": train.locomotive_type,
                "locomotive_count": train.locomotive_count,
                "locomotive_consist": _serialise_locomotive_consist(
                    getattr(train, "locomotive_consist", ())
                ),
                "freight_load_state": train.freight_load_state,
            }
            for train in trains.values()
        ],
    )

    (output_dir / BATTERY_FILE).write_text(
        json.dumps(asdict(battery), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / OPERATING_CONDITIONS_FILE).write_text(
        json.dumps(asdict(route.operating_conditions), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / RESOURCE_CONFIG_FILE).write_text(
        json.dumps(asdict(ResourceConfig()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _print_report(report: DataValidationReport) -> None:
    """函数 _print_report：执行该模块中的相关处理逻辑。"""
    print("=== Real Data Validation ===")
    print(f"Source: {report.source_dir}")
    print(f"Valid: {report.is_valid}")
    print(f"Errors: {len(report.errors)}")
    print(f"Warnings: {len(report.warnings)}")
    for issue in report.issues[:20]:
        row = "" if issue.row is None else f":{issue.row}"
        print(f"[{issue.severity}] {issue.file}{row} {issue.field} {issue.message}")
    if len(report.issues) > 20:
        print(f"... {len(report.issues) - 20} more issues")


def main(argv: Optional[List[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Real-data ingestion and validation utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a real-data input directory.")
    validate_parser.add_argument("input_dir", type=Path)
    validate_parser.add_argument("--output-dir", type=Path)

    template_parser = subparsers.add_parser("export-template", help="Export CSV/JSON template from sandbox config.")
    template_parser.add_argument("--config", type=Path, default=Path("sandbox_config.json"))
    template_parser.add_argument("--output-dir", type=Path, required=True)
    template_parser.add_argument("--no-overwrite", action="store_true")

    export_parser = subparsers.add_parser("export-json", help="Convert a real-data input directory to sandbox JSON.")
    export_parser.add_argument("input_dir", type=Path)
    export_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "validate":
        report = validate_real_data_bundle(args.input_dir)
        _print_report(report)
        if args.output_dir is not None:
            write_validation_report(report, args.output_dir)
        return 0 if report.is_valid else 1

    if args.command == "export-template":
        write_real_data_template_from_config(
            args.config,
            args.output_dir,
            overwrite=not args.no_overwrite,
        )
        print(f"Template exported to {args.output_dir}")
        return 0

    if args.command == "export-json":
        bundle = load_real_data_bundle(args.input_dir)
        write_sandbox_config(bundle, args.output)
        print(f"Sandbox-compatible config written to {args.output}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
