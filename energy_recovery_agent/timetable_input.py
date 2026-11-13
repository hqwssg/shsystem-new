# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import argparse
import csv
import json
import math
import re

from formation_modes import (
    DEFAULT_FORMATION_MODE_PATH,
    formation_source_note,
    infer_load_state,
    load_formation_modes,
    resolve_formation_mode,
)

try:
    import openpyxl
except ImportError:  # pragma: no cover - 仅使用 CSV 时仍可正常工作。
    openpyxl = None


TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")

REQUIRED_TRAIN_FIELDS = (
    "train_id",
    "train_type",
    "direction",
    "origin_station",
    "destination_station",
)
REQUIRED_TIMETABLE_FIELDS = (
    "train_id",
    "seq",
    "station_name",
    "station_km",
    "arrival_time",
    "departure_time",
)


@dataclass(frozen=True)
class TimetableIssue:
    """类 TimetableIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    code: str
    sheet: str
    row: Optional[int]
    field: str
    message: str


@dataclass
class TimetableValidationReport:
    """类 TimetableValidationReport：执行该模块中的相关处理逻辑。"""
    source_path: str
    issues: List[TimetableIssue] = field(default_factory=list)

    def add(
        self,
        severity: str,
        code: str,
        sheet: str,
        row: Optional[int],
        field: str,
        message: str,
    ) -> None:
        """函数 add：执行该模块中的相关处理逻辑。"""
        self.issues.append(
            TimetableIssue(
                severity=severity,
                code=code,
                sheet=sheet,
                row=row,
                field=field,
                message=message,
            )
        )

    def error(self, code: str, sheet: str, row: Optional[int], field: str, message: str) -> None:
        """函数 error：执行该模块中的相关处理逻辑。"""
        self.add("error", code, sheet, row, field, message)

    def warning(self, code: str, sheet: str, row: Optional[int], field: str, message: str) -> None:
        """函数 warning：执行该模块中的相关处理逻辑。"""
        self.add("warning", code, sheet, row, field, message)

    @property
    def errors(self) -> List[TimetableIssue]:
        """函数 errors：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[TimetableIssue]:
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
                "sheet": issue.sheet,
                "row": "" if issue.row is None else issue.row,
                "field": issue.field,
                "message": issue.message,
            }
            for issue in self.issues
        ]

    def summary(self) -> Dict[str, object]:
        """函数 summary：执行该模块中的相关处理逻辑。"""
        return {
            "source_path": self.source_path,
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": self.to_rows(),
        }


@dataclass(frozen=True)
class TimetableTrain:
    """类 TimetableTrain：执行该模块中的相关处理逻辑。"""
    train_id: str
    train_type: str
    direction: str
    origin_station: str
    destination_station: str
    mass_t: Optional[float]
    formation: str
    traction_type: str
    priority: Optional[int]
    formation_category: str = ""
    formation_mode: str = ""
    wagon_count: Optional[int] = None
    mass_source: str = ""


@dataclass(frozen=True)
class TimetableStop:
    """类 TimetableStop：执行该模块中的相关处理逻辑。"""
    train_id: str
    seq: int
    station_name: str
    station_km: float
    arrival_time_s: int
    departure_time_s: int
    stop_type: str
    track: str
    operation_type: str
    note: str


@dataclass(frozen=True)
class TimetableScenario:
    """类 TimetableScenario：执行该模块中的相关处理逻辑。"""
    scenario_id: str
    direct_use_enabled: bool
    storage_enabled: bool
    storage_capacity_kwh: Optional[float]
    storage_power_kw: Optional[float]
    initial_soc_kwh: Optional[float]
    settlement_time_step_s: int
    transfer_scope: str
    storage_charge_power_kw: Optional[float] = None
    storage_discharge_power_kw: Optional[float] = None
    storage_efficiency: Optional[float] = None

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.scenario_id).strip():
            raise ValueError("scenario_id must not be blank")
        if type(self.direct_use_enabled) is not bool:
            raise ValueError("direct_use_enabled must be a boolean")
        if type(self.storage_enabled) is not bool:
            raise ValueError("storage_enabled must be a boolean")
        if (
            isinstance(self.settlement_time_step_s, bool)
            or not isinstance(self.settlement_time_step_s, int)
            or self.settlement_time_step_s <= 0
        ):
            raise ValueError("settlement_time_step_s must be a positive integer")
        if not str(self.transfer_scope).strip():
            raise ValueError("transfer_scope must not be blank")

        nonnegative_fields = (
            "storage_capacity_kwh",
            "storage_power_kw",
            "initial_soc_kwh",
            "storage_charge_power_kw",
            "storage_discharge_power_kw",
        )
        for field_name in nonnegative_fields:
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be a finite non-negative number")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{field_name} must be a finite non-negative number")

        if self.storage_efficiency is not None:
            efficiency = self.storage_efficiency
            if isinstance(efficiency, bool) or not isinstance(efficiency, (int, float)):
                raise ValueError("storage_efficiency must be finite and in (0, 1]")
            if not math.isfinite(float(efficiency)) or not 0.0 < float(efficiency) <= 1.0:
                raise ValueError("storage_efficiency must be finite and in (0, 1]")

        capacity = self.storage_capacity_kwh
        initial_soc = self.initial_soc_kwh or 0.0
        if initial_soc > 0.0 and capacity is None:
            raise ValueError("initial_soc_kwh requires storage_capacity_kwh")
        if capacity is not None and initial_soc > capacity:
            raise ValueError("initial_soc_kwh cannot exceed storage_capacity_kwh")
        if self.storage_enabled:
            if capacity is None or capacity <= 0.0:
                raise ValueError("storage_capacity_kwh must be positive when storage is enabled")
            charge_power = self.storage_charge_power_kw
            if charge_power is None:
                charge_power = self.storage_power_kw
            discharge_power = self.storage_discharge_power_kw
            if discharge_power is None:
                discharge_power = self.storage_power_kw
            if charge_power is None or charge_power <= 0.0:
                raise ValueError("storage charge power must be positive when storage is enabled")
            # Charge-only operation is a valid conservative mode when the
            # received equipment data does not provide a discharge rating.
            if discharge_power is None:
                raise ValueError("storage discharge power must be provided when storage is enabled")


@dataclass(frozen=True)
class CanonicalTimetable:
    """类 CanonicalTimetable：执行该模块中的相关处理逻辑。"""
    trains: Tuple[TimetableTrain, ...]
    stops: Tuple[TimetableStop, ...]
    scenarios: Tuple[TimetableScenario, ...]
    constraints: Tuple[Dict[str, Any], ...]
    metadata: Dict[str, Any]
    validation_report: TimetableValidationReport


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
        raise ValueError(f"Expected a finite number, got {value!r}")
    return number


def _optional_int(value: Any) -> Optional[int]:
    """函数 _optional_int：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text:
        return None
    number = float(text)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"Expected a finite integer, got {value!r}")
    return int(number)


def _bool(value: Any) -> bool:
    """函数 _bool：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if not text:
        return False
    if text in {"1", "true", "yes", "y", "enabled", "on"}:
        return True
    if text in {"0", "false", "no", "n", "disabled", "off"}:
        return False
    raise ValueError(f"Expected a boolean value, got {value!r}")


def _read_optional_float(
    row: Dict[str, Any],
    field_name: str,
    report: TimetableValidationReport,
    sheet: str,
    row_idx: int,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    minimum_exclusive: bool = False,
) -> Optional[float]:
    """函数 _read_optional_float：执行该模块中的相关处理逻辑。"""
    raw = row.get(field_name)
    if not _clean(raw):
        return None
    try:
        value = _optional_float(raw)
    except (TypeError, ValueError, OverflowError):
        report.error("invalid_number", sheet, row_idx, field_name, f"{field_name} must be a finite number.")
        return None
    assert value is not None
    below_minimum = minimum is not None and (
        value <= minimum if minimum_exclusive else value < minimum
    )
    if below_minimum or (maximum is not None and value > maximum):
        if minimum_exclusive and minimum is not None:
            range_text = f"greater than {minimum}"
        elif minimum is not None and maximum is not None:
            range_text = f"between {minimum} and {maximum}"
        elif minimum is not None:
            range_text = f"greater than or equal to {minimum}"
        else:
            range_text = f"less than or equal to {maximum}"
        report.error("out_of_range", sheet, row_idx, field_name, f"{field_name} must be {range_text}.")
        return None
    return value


def _read_optional_int(
    row: Dict[str, Any],
    field_name: str,
    report: TimetableValidationReport,
    sheet: str,
    row_idx: int,
    *,
    minimum: Optional[int] = None,
) -> Optional[int]:
    """函数 _read_optional_int：执行该模块中的相关处理逻辑。"""
    raw = row.get(field_name)
    if not _clean(raw):
        return None
    try:
        value = _optional_int(raw)
    except (TypeError, ValueError, OverflowError):
        report.error("invalid_integer", sheet, row_idx, field_name, f"{field_name} must be a finite integer.")
        return None
    assert value is not None
    if minimum is not None and value < minimum:
        report.error(
            "out_of_range",
            sheet,
            row_idx,
            field_name,
            f"{field_name} must be greater than or equal to {minimum}.",
        )
        return None
    return value


def _read_bool(
    row: Dict[str, Any],
    field_name: str,
    report: TimetableValidationReport,
    sheet: str,
    row_idx: int,
) -> bool:
    """函数 _read_bool：执行该模块中的相关处理逻辑。"""
    try:
        return _bool(row.get(field_name))
    except ValueError:
        report.error(
            "invalid_boolean",
            sheet,
            row_idx,
            field_name,
            f"{field_name} must be a recognized true/false value.",
        )
        return False


def parse_time_to_s(value: Any) -> Optional[int]:
    """函数 parse_time_to_s：执行该模块中的相关处理逻辑。"""
    if value is None:
        return None
    if hasattr(value, "hour") and hasattr(value, "minute") and hasattr(value, "second"):
        if int(getattr(value, "microsecond", 0)) != 0:
            return None
        return int(value.hour) * 3600 + int(value.minute) * 60 + int(value.second)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            return None
        if number < 1.0:
            seconds = number * 86400.0
            rounded = round(seconds)
            if not math.isclose(seconds, rounded, rel_tol=0.0, abs_tol=1e-6):
                return None
            return int(rounded)
        if not number.is_integer():
            return None
        return int(number)
    text = _clean(value)
    if not text:
        return None
    if re.fullmatch(r"[0-9]+", text):
        return int(text)
    match = TIME_RE.match(text)
    if not match:
        return None
    hour_text, minute_text, second_text = match.groups()
    hours = int(hour_text or 0)
    minutes = int(minute_text)
    seconds = int(second_text)
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def format_s_as_hhmmss(seconds: int) -> str:
    """函数 format_s_as_hhmmss：执行该模块中的相关处理逻辑。"""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _rows_from_csv(path: Path) -> List[Dict[str, Any]]:
    """函数 _rows_from_csv：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _rows_from_xlsx(path: Path, sheet_name: str) -> List[Dict[str, Any]]:
    """函数 _rows_from_xlsx：执行该模块中的相关处理逻辑。"""
    if openpyxl is None:
        raise RuntimeError("openpyxl is required to read xlsx timetable templates.")
    workbook = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in workbook.sheetnames:
        return []
    sheet = workbook[sheet_name]
    header: List[str] = []
    for cell in sheet[1]:
        value = _clean(cell.value)
        if value:
            header.append(value)
    rows: List[Dict[str, Any]] = []
    for row_idx in range(2, sheet.max_row + 1):
        values = [sheet.cell(row_idx, col_idx + 1).value for col_idx in range(len(header))]
        if not any(_clean(value) for value in values):
            continue
        rows.append({header[col_idx]: values[col_idx] for col_idx in range(len(header))})
    return rows


def _metadata_from_xlsx(path: Path) -> Dict[str, Any]:
    """函数 _metadata_from_xlsx：执行该模块中的相关处理逻辑。"""
    if openpyxl is None:
        return {}
    workbook = openpyxl.load_workbook(path, data_only=True)
    if "metadata" not in workbook.sheetnames:
        return {}
    sheet = workbook["metadata"]
    metadata: Dict[str, Any] = {}
    for row_idx in range(2, sheet.max_row + 1):
        key = _clean(sheet.cell(row_idx, 1).value)
        if key:
            metadata[key] = sheet.cell(row_idx, 2).value
    return metadata


def _load_sheet_rows(path: Path, sheet_name: str) -> List[Dict[str, Any]]:
    """函数 _load_sheet_rows：执行该模块中的相关处理逻辑。"""
    if path.suffix.lower() == ".xlsx":
        return _rows_from_xlsx(path, sheet_name)
    if path.is_dir():
        csv_path = path / f"{sheet_name}.csv"
        return _rows_from_csv(csv_path) if csv_path.exists() else []
    raise ValueError(f"Unsupported timetable input path: {path}")


def _missing_fields(row: Dict[str, Any], fields: Sequence[str]) -> List[str]:
    """函数 _missing_fields：执行该模块中的相关处理逻辑。"""
    return [field for field in fields if not _clean(row.get(field))]


def load_canonical_timetable(path: Path) -> CanonicalTimetable:
    """函数 load_canonical_timetable：执行该模块中的相关处理逻辑。"""
    report = TimetableValidationReport(str(path))
    train_rows = _load_sheet_rows(path, "trains")
    stop_rows = _load_sheet_rows(path, "timetable")
    scenario_rows = _load_sheet_rows(path, "scenario")
    constraint_rows = _load_sheet_rows(path, "constraints")
    metadata = _metadata_from_xlsx(path) if path.suffix.lower() == ".xlsx" else {}
    formation_modes_path_text = _clean(metadata.get("formation_modes_path"))
    formation_modes = load_formation_modes(Path(formation_modes_path_text) if formation_modes_path_text else DEFAULT_FORMATION_MODE_PATH)

    trains: List[TimetableTrain] = []
    train_ids: set[str] = set()
    for idx, row in enumerate(train_rows, start=2):
        missing = _missing_fields(row, REQUIRED_TRAIN_FIELDS)
        for field_name in missing:
            report.error("missing_required", "trains", idx, field_name, "Required train field is blank.")
        train_id = _clean(row.get("train_id"))
        if not train_id:
            continue
        if train_id in train_ids:
            report.error("duplicate_train_id", "trains", idx, "train_id", f"Duplicate train_id {train_id}.")
        train_ids.add(train_id)
        direction = _clean(row.get("direction"))
        if direction not in {"forward", "reverse"}:
            report.error("invalid_direction", "trains", idx, "direction", "Use forward or reverse.")
        formation_category = _clean(row.get("formation_category"))
        formation_mode = _clean(row.get("formation_mode"))
        wagon_count = _read_optional_int(row, "wagon_count", report, "trains", idx, minimum=1)
        mass_t = _read_optional_float(
            row,
            "mass_t",
            report,
            "trains",
            idx,
            minimum=0.0,
            minimum_exclusive=True,
        )
        priority = _read_optional_int(row, "priority", report, "trains", idx, minimum=0)
        resolved_mode = resolve_formation_mode(
            formation_modes,
            category=formation_category,
            load_state=_clean(row.get("load_state")) or infer_load_state(_clean(row.get("train_type"))),
            formation_mode=formation_mode,
            wagon_count=wagon_count,
            free_text=_clean(row.get("formation")),
        )
        mass_source = "input_mass_t" if mass_t is not None else ""
        if resolved_mode and mass_t is None:
            mass_t = resolved_mode.mass_tons
            mass_source = "formation_modes_2025"
        elif resolved_mode and mass_t is not None and abs(mass_t - resolved_mode.mass_tons) > 1e-6:
            report.warning(
                "formation_mass_mismatch",
                "trains",
                idx,
                "mass_t",
                f"Input mass_t {mass_t} differs from formation catalog mass {resolved_mode.mass_tons}; input mass_t is kept.",
            )
        trains.append(
            TimetableTrain(
                train_id=train_id,
                train_type=_clean(row.get("train_type")),
                direction=direction,
                origin_station=_clean(row.get("origin_station")),
                destination_station=_clean(row.get("destination_station")),
                mass_t=mass_t,
                formation=_clean(row.get("formation")),
                traction_type=_clean(row.get("traction_type")),
                priority=priority,
                formation_category=formation_category or (resolved_mode.category if resolved_mode else ""),
                formation_mode=formation_mode or (resolved_mode.formation_mode if resolved_mode else ""),
                wagon_count=wagon_count or (resolved_mode.wagon_count if resolved_mode else None),
                mass_source=mass_source or (formation_source_note(resolved_mode) if resolved_mode else ""),
            )
        )

    stops: List[TimetableStop] = []
    stops_by_train: Dict[str, List[TimetableStop]] = {}
    for idx, row in enumerate(stop_rows, start=2):
        missing = _missing_fields(row, REQUIRED_TIMETABLE_FIELDS)
        for field_name in missing:
            report.error("missing_required", "timetable", idx, field_name, "Required timetable field is blank.")
        train_id = _clean(row.get("train_id"))
        if train_id and train_id not in train_ids:
            report.error("unknown_train", "timetable", idx, "train_id", f"Train {train_id} is not defined in trains.")
        arrival_time_s = parse_time_to_s(row.get("arrival_time"))
        departure_time_s = parse_time_to_s(row.get("departure_time"))
        if arrival_time_s is None:
            report.error("invalid_time", "timetable", idx, "arrival_time", "Use HH:MM:SS or seconds.")
            arrival_time_s = 0
        if departure_time_s is None:
            report.error("invalid_time", "timetable", idx, "departure_time", "Use HH:MM:SS or seconds.")
            departure_time_s = arrival_time_s
        if departure_time_s < arrival_time_s:
            report.error("negative_stop_time", "timetable", idx, "departure_time", "Departure cannot be before arrival.")
        seq_value = _read_optional_int(row, "seq", report, "timetable", idx, minimum=1)
        seq = seq_value if seq_value is not None else 0
        station_km_value = _read_optional_float(
            row,
            "station_km",
            report,
            "timetable",
            idx,
            minimum=0.0,
        )
        station_km = station_km_value if station_km_value is not None else math.nan
        stop = TimetableStop(
            train_id=train_id,
            seq=seq,
            station_name=_clean(row.get("station_name")),
            station_km=station_km,
            arrival_time_s=arrival_time_s,
            departure_time_s=departure_time_s,
            stop_type=_clean(row.get("stop_type")) or "pass",
            track=_clean(row.get("track")),
            operation_type=_clean(row.get("operation_type")),
            note=_clean(row.get("note")),
        )
        stops.append(stop)
        stops_by_train.setdefault(train_id, []).append(stop)

    trains_by_id = {train.train_id: train for train in trains}
    for train_id, train_stops in stops_by_train.items():
        ordered = sorted(train_stops, key=lambda item: item.seq)
        seen_seq: set[int] = set()
        previous_departure: Optional[int] = None
        previous_km: Optional[float] = None
        direction = trains_by_id.get(train_id).direction if train_id in trains_by_id else ""
        for stop in ordered:
            if stop.seq in seen_seq:
                report.error("duplicate_seq", "timetable", None, "seq", f"Train {train_id} has duplicate seq {stop.seq}.")
            seen_seq.add(stop.seq)
            if previous_departure is not None and stop.arrival_time_s < previous_departure:
                report.error(
                    "non_monotonic_time",
                    "timetable",
                    None,
                    "arrival_time",
                    f"Train {train_id} arrival time goes backwards at seq {stop.seq}.",
                )
            if previous_km is not None and math.isfinite(stop.station_km) and math.isfinite(previous_km):
                if stop.station_km != previous_km and stop.arrival_time_s == previous_departure:
                    report.error(
                        "zero_duration_running_section", "timetable", None, "arrival_time",
                        f"列车 {train_id} 第 {stop.seq} 站与前站里程不同，跨站运行时长必须大于零。",
                    )
                if direction == "forward" and stop.station_km < previous_km:
                    report.error("non_monotonic_km", "timetable", None, "station_km", f"Train {train_id} forward km decreases.")
                if direction == "reverse" and stop.station_km > previous_km:
                    report.error("non_monotonic_km", "timetable", None, "station_km", f"Train {train_id} reverse km increases.")
            previous_departure = stop.departure_time_s
            previous_km = stop.station_km

    scenarios: List[TimetableScenario] = []
    scenario_ids: set[str] = set()
    for idx, row in enumerate(scenario_rows, start=2):
        row_error_count = len(report.errors)
        scenario_id = _clean(row.get("scenario_id"))
        if not scenario_id:
            report.error("missing_required", "scenario", idx, "scenario_id", "scenario_id is required.")
            continue
        if scenario_id in scenario_ids:
            report.error("duplicate_scenario_id", "scenario", idx, "scenario_id", f"Duplicate scenario_id {scenario_id}.")
        scenario_ids.add(scenario_id)
        direct_use_enabled = _read_bool(row, "direct_use_enabled", report, "scenario", idx)
        storage_enabled = _read_bool(row, "storage_enabled", report, "scenario", idx)
        storage_capacity = _read_optional_float(
            row, "storage_capacity_kwh", report, "scenario", idx, minimum=0.0
        )
        storage_power = _read_optional_float(
            row, "storage_power_kw", report, "scenario", idx, minimum=0.0
        )
        initial_soc = _read_optional_float(
            row, "initial_soc_kwh", report, "scenario", idx, minimum=0.0
        )
        storage_charge_power = _read_optional_float(
            row, "storage_charge_power_kw", report, "scenario", idx, minimum=0.0
        )
        storage_discharge_power = _read_optional_float(
            row, "storage_discharge_power_kw", report, "scenario", idx, minimum=0.0
        )
        storage_efficiency = _read_optional_float(
            row,
            "storage_efficiency",
            report,
            "scenario",
            idx,
            minimum=0.0,
            maximum=1.0,
            minimum_exclusive=True,
        )
        step = _read_optional_int(
            row, "settlement_time_step_s", report, "scenario", idx, minimum=1
        )
        if step is None and not _clean(row.get("settlement_time_step_s")):
            report.error(
                "missing_required",
                "scenario",
                idx,
                "settlement_time_step_s",
                "settlement_time_step_s is required; formal running-graph evaluation uses an explicit approved time bucket.",
            )

        if initial_soc is not None and initial_soc > 0.0 and storage_capacity is None:
            report.error(
                "invalid_storage_soc",
                "scenario",
                idx,
                "initial_soc_kwh",
                "initial_soc_kwh requires storage_capacity_kwh.",
            )
        if initial_soc is not None and storage_capacity is not None and initial_soc > storage_capacity:
            report.error(
                "invalid_storage_soc",
                "scenario",
                idx,
                "initial_soc_kwh",
                "initial_soc_kwh cannot exceed storage_capacity_kwh.",
            )
        if storage_enabled:
            if storage_capacity is None or storage_capacity <= 0.0:
                report.error(
                    "invalid_storage_capacity",
                    "scenario",
                    idx,
                    "storage_capacity_kwh",
                    "storage_capacity_kwh must be positive when storage is enabled.",
                )
            charge_power = storage_charge_power if storage_charge_power is not None else storage_power
            discharge_power = storage_discharge_power if storage_discharge_power is not None else storage_power
            if charge_power is None or charge_power <= 0.0:
                report.error(
                    "invalid_storage_power",
                    "scenario",
                    idx,
                    "storage_charge_power_kw",
                    "Storage charge power must be positive when storage is enabled.",
                )
            if discharge_power is None or discharge_power <= 0.0:
                report.error(
                    "invalid_storage_power",
                    "scenario",
                    idx,
                    "storage_discharge_power_kw",
                    "Storage discharge power must be positive when storage is enabled.",
                )
        if len(report.errors) > row_error_count:
            continue
        assert step is not None
        scenarios.append(
            TimetableScenario(
                scenario_id=scenario_id,
                direct_use_enabled=direct_use_enabled,
                storage_enabled=storage_enabled,
                storage_capacity_kwh=storage_capacity,
                storage_power_kw=storage_power,
                initial_soc_kwh=initial_soc,
                settlement_time_step_s=step,
                transfer_scope=_clean(row.get("transfer_scope")) or "same_power_arm",
                storage_charge_power_kw=storage_charge_power,
                storage_discharge_power_kw=storage_discharge_power,
                storage_efficiency=storage_efficiency,
            )
        )

    for idx, row in enumerate(constraint_rows, start=2):
        constraint_type = _clean(
            row.get("constraint_type") or row.get("type") or row.get("name")
        ).lower()
        is_headway = (
            "headway" in constraint_type
            or "追踪" in constraint_type
            or "间隔" in constraint_type
        )
        if is_headway:
            value = _read_optional_int(row, "value", report, "constraints", idx, minimum=1)
            if value is None and not _clean(row.get("value")):
                report.error(
                    "missing_constraint_value",
                    "constraints",
                    idx,
                    "value",
                    "Headway constraint value is required.",
                )
            unit = _clean(row.get("unit")).lower()
            if unit and unit not in {"min", "minute", "minutes", "分钟"}:
                report.error(
                    "invalid_constraint_unit",
                    "constraints",
                    idx,
                    "unit",
                    "Headway constraints must use minutes.",
                )
            continue
        unit = _clean(row.get("unit")).lower()
        numeric_units = {
            "s", "sec", "second", "seconds", "秒",
            "min", "minute", "minutes", "分钟",
            "h", "hour", "hours", "小时",
            "km", "m", "kw", "kwh", "mw", "mwh",
        }
        if unit in numeric_units and _clean(row.get("value")):
            _read_optional_float(row, "value", report, "constraints", idx, minimum=0.0)

    if not train_rows:
        report.error("missing_sheet_or_rows", "trains", None, "", "No rows found in trains.")
    if not stop_rows:
        report.error("missing_sheet_or_rows", "timetable", None, "", "No rows found in timetable.")
    if not scenarios:
        report.warning("missing_scenario", "scenario", None, "", "No scenario rows found; default algorithm settings will be needed.")

    return CanonicalTimetable(
        trains=tuple(trains),
        stops=tuple(stops),
        scenarios=tuple(scenarios),
        constraints=tuple(dict(row) for row in constraint_rows),
        metadata=metadata,
        validation_report=report,
    )


def timetable_node_rows(timetable: CanonicalTimetable) -> List[Dict[str, object]]:
    """函数 timetable_node_rows：执行该模块中的相关处理逻辑。"""
    trains_by_id = {train.train_id: train for train in timetable.trains}
    rows: List[Dict[str, object]] = []
    for stop in sorted(timetable.stops, key=lambda item: (item.train_id, item.seq)):
        train = trains_by_id.get(stop.train_id)
        train_type = train.train_type if train else ""
        direction = train.direction if train else ""
        state = "pass" if stop.arrival_time_s == stop.departure_time_s else "arrive"
        rows.append(
            {
                "node_id": f"{stop.train_id}:n{stop.seq:03d}:arrive",
                "train_id": stop.train_id,
                "train_type": train_type,
                "direction": direction,
                "station_name": stop.station_name,
                "position_km": stop.station_km,
                "time_s": stop.arrival_time_s,
                "time_hhmmss": format_s_as_hhmmss(stop.arrival_time_s),
                "state": state,
            }
        )
        if stop.departure_time_s > stop.arrival_time_s:
            rows.append(
                {
                    "node_id": f"{stop.train_id}:n{stop.seq:03d}:depart",
                    "train_id": stop.train_id,
                    "train_type": train_type,
                    "direction": direction,
                    "station_name": stop.station_name,
                    "position_km": stop.station_km,
                    "time_s": stop.departure_time_s,
                    "time_hhmmss": format_s_as_hhmmss(stop.departure_time_s),
                    "state": stop.operation_type or "waiting",
                }
            )
    return rows


def timetable_arc_rows(timetable: CanonicalTimetable) -> List[Dict[str, object]]:
    """函数 timetable_arc_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    stops_by_train: Dict[str, List[TimetableStop]] = {}
    trains_by_id = {train.train_id: train for train in timetable.trains}
    for stop in timetable.stops:
        stops_by_train.setdefault(stop.train_id, []).append(stop)
    for train_id, train_stops in sorted(stops_by_train.items()):
        train = trains_by_id.get(train_id)
        ordered = sorted(train_stops, key=lambda item: item.seq)
        for idx, stop in enumerate(ordered):
            if stop.departure_time_s > stop.arrival_time_s:
                rows.append(
                    {
                        "arc_id": f"{train_id}:a{len(rows):04d}:waiting",
                        "train_id": train_id,
                        "train_type": train.train_type if train else "",
                        "direction": train.direction if train else "",
                        "arc_type": stop.operation_type or "waiting",
                        "start_time_s": stop.arrival_time_s,
                        "end_time_s": stop.departure_time_s,
                        "duration_s": stop.departure_time_s - stop.arrival_time_s,
                        "start_km": stop.station_km,
                        "end_km": stop.station_km,
                        "distance_km": 0.0,
                        "energy_kwh": "",
                        "capacity_resource_id": f"station:{stop.station_name}",
                        "source": "user_timetable_template",
                    }
                )
            if idx + 1 >= len(ordered):
                continue
            next_stop = ordered[idx + 1]
            rows.append(
                {
                    "arc_id": f"{train_id}:a{len(rows):04d}:running",
                    "train_id": train_id,
                    "train_type": train.train_type if train else "",
                    "direction": train.direction if train else "",
                    "arc_type": "running",
                    "start_time_s": stop.departure_time_s,
                    "end_time_s": next_stop.arrival_time_s,
                    "duration_s": next_stop.arrival_time_s - stop.departure_time_s,
                    "start_km": stop.station_km,
                    "end_km": next_stop.station_km,
                    "distance_km": abs(next_stop.station_km - stop.station_km),
                    "energy_kwh": "",
                    "capacity_resource_id": f"section:{stop.station_name}->{next_stop.station_name}",
                    "source": "user_timetable_template",
                }
            )
    return rows


def _write_csv(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_bytes(b"\xef\xbb\xbf")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_timetable_parse_outputs(timetable: CanonicalTimetable, output_dir: Path) -> None:
    """函数 write_timetable_parse_outputs：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report = timetable.validation_report
    _write_csv(output_dir / "validation_issues.csv", report.to_rows())
    _write_csv(output_dir / "timetable_nodes_draft.csv", timetable_node_rows(timetable))
    _write_csv(output_dir / "timetable_arcs_draft.csv", timetable_arc_rows(timetable))
    (output_dir / "validation_summary.json").write_text(
        json.dumps(report.summary(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Validate canonical user timetable input.")
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "timetable_input_validation")
    args = parser.parse_args()

    timetable = load_canonical_timetable(args.input_path)
    write_timetable_parse_outputs(timetable, args.output_dir)
    print(json.dumps(timetable.validation_report.summary(), ensure_ascii=False, indent=2))
    if not timetable.validation_report.is_valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
