# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
import argparse
import csv
import json
import math

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None


DEFAULT_SMART_METER_DIR = Path("data") / "source" / "smart_meter"
DEFAULT_OUTPUT_CSV = Path("outputs") / "smart_meter_calibration" / "smart_meter_calibration_records.csv"

AMMETER_INFO_PATTERN = "nhtj_jkfile_ammeter_info_*.csv"
STATION_PATTERN = "nhtj_jkfile_station_*.csv"
REALTIME_METER_PATTERN = "SS4-*.xlsx"

REQUIRED_COLUMNS = (
    "guid",
    "unitid",
    "traintypeid",
    "trainid",
    "sxx",
    "trainorder",
    "starttime",
    "endtime",
    "start_station",
    "end_station",
    "use_ygdn",
    "use_fkdn",
    "train_weight",
    "train_load",
)

ABC_ENERGY_COLUMNS = (
    "a_use_ygdn",
    "b_use_ygdn",
    "c_use_ygdn",
    "a_use_fkdn",
    "b_use_fkdn",
    "c_use_fkdn",
)

OUTPUT_COLUMNS = (
    "source_table",
    "source_file",
    "source_row",
    "guid",
    "unitid",
    "traintypeid",
    "train_type_label",
    "train_type_mapping_status",
    "trainid",
    "trainorder",
    "direction_code",
    "direction_label",
    "direction_mapping_status",
    "starttime",
    "endtime",
    "recordtime",
    "start_station",
    "end_station",
    "association_policy",
    "association_key_trainid",
    "association_time_start",
    "association_time_end",
    "association_status",
    "train_weight",
    "train_load",
    "train_length",
    "train_num",
    "start_positive_energy_raw",
    "end_positive_energy_raw",
    "start_feedback_energy_raw",
    "end_feedback_energy_raw",
    "positive_energy_raw",
    "feedback_energy_raw",
    "positive_energy_kwh_assuming_scale",
    "feedback_energy_kwh_assuming_scale",
    "net_energy_kwh_assuming_scale",
    "abc_positive_energy_raw_sum",
    "abc_feedback_energy_raw_sum",
    "abc_sum_status",
    "delta_positive_energy_raw",
    "delta_feedback_energy_raw",
    "delta_sum_status",
    "realtime_positive_cumulative_raw",
    "realtime_feedback_cumulative_raw",
    "energy_unit_status",
    "mass_mapping_status",
    "record_warnings",
)

TRAIN_TYPE_MAP = {
    "225": ("SS4", "confirmed_by_provider_reply"),
    "231": ("神8", "provisional_provider_reply_code_may_change"),
    "232": ("神8", "provisional_provider_reply_code_may_change"),
    "234": ("神8", "provisional_provider_reply_code_may_change"),
    "233": ("神12", "provisional_provider_reply_code_may_change"),
}

CONFIRMED_ENERGY_UNIT_STATUS = "confirmed_kwh_from_provider_reply"
INTERVAL_MASS_STATUS = "realtime_reported_total_weight_and_load_often_unavailable"
REALTIME_MASS_STATUS = "zz_corresponds_to_train_weight_confirmed_train_load_not_available"


@dataclass(frozen=True)
class SmartMeterAdapterConfig:
    """Mapping assumptions for smart-meter records."""

    energy_scale_to_kwh: float = 1.0
    allow_negative_energy: bool = True
    direction_map: Dict[str, str] = field(default_factory=lambda: {"1": "down", "2": "up"})


@dataclass(frozen=True)
class SmartMeterIssue:
    """类 SmartMeterIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    code: str
    source: str
    row: str
    field: str
    message: str
    suggestion: str = ""


@dataclass(frozen=True)
class SmartMeterCalibrationRecord:
    """类 SmartMeterCalibrationRecord：执行该模块中的相关处理逻辑。"""
    source_table: str
    source_file: str
    source_row: int
    guid: str
    unitid: str
    traintypeid: str
    train_type_label: str
    train_type_mapping_status: str
    trainid: str
    trainorder: str
    direction_code: str
    direction_label: str
    direction_mapping_status: str
    starttime: str
    endtime: str
    recordtime: str
    start_station: str
    end_station: str
    association_policy: str
    association_key_trainid: str
    association_time_start: str
    association_time_end: str
    association_status: str
    train_weight: Optional[float]
    train_load: Optional[float]
    train_length: Optional[float]
    train_num: Optional[float]
    start_positive_energy_raw: Optional[float]
    end_positive_energy_raw: Optional[float]
    start_feedback_energy_raw: Optional[float]
    end_feedback_energy_raw: Optional[float]
    positive_energy_raw: Optional[float]
    feedback_energy_raw: Optional[float]
    positive_energy_kwh_assuming_scale: Optional[float]
    feedback_energy_kwh_assuming_scale: Optional[float]
    net_energy_kwh_assuming_scale: Optional[float]
    abc_positive_energy_raw_sum: Optional[float]
    abc_feedback_energy_raw_sum: Optional[float]
    abc_sum_status: str
    delta_positive_energy_raw: Optional[float]
    delta_feedback_energy_raw: Optional[float]
    delta_sum_status: str
    realtime_positive_cumulative_raw: Optional[float]
    realtime_feedback_cumulative_raw: Optional[float]
    energy_unit_status: str
    mass_mapping_status: str
    record_warnings: str


@dataclass
class SmartMeterAdapterResult:
    """类 SmartMeterAdapterResult：执行该模块中的相关处理逻辑。"""
    records: List[SmartMeterCalibrationRecord] = field(default_factory=list)
    issues: List[SmartMeterIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[SmartMeterIssue]:
        """函数 errors：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[SmartMeterIssue]:
        """函数 warnings：执行该模块中的相关处理逻辑。"""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """函数 is_valid：执行该模块中的相关处理逻辑。"""
        return not self.errors

    def summary(self) -> Dict[str, object]:
        """函数 summary：执行该模块中的相关处理逻辑。"""
        return {
            "valid": self.is_valid,
            "record_count": len(self.records),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [asdict(issue) for issue in self.issues],
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
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _sum_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    """函数 _sum_optional：执行该模块中的相关处理逻辑。"""
    items = list(values)
    if any(value is None for value in items):
        return None
    return sum(float(value) for value in items)


def _nearly_equal(left: Optional[float], right: Optional[float], tolerance: float = 1e-6) -> bool:
    """函数 _nearly_equal：执行该模块中的相关处理逻辑。"""
    return left is not None and right is not None and abs(float(left) - float(right)) <= tolerance


def _excel_rows(path: Path, max_rows: Optional[int]) -> tuple[list[str], list[tuple[int, Dict[str, Any]]]]:
    """函数 _excel_rows：执行该模块中的相关处理逻辑。"""
    if load_workbook is None:
        raise RuntimeError("openpyxl is required to read realtime smart-meter xlsx files.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        headers = [_clean(cell.value).lower() for cell in sheet[1]]
        rows: list[tuple[int, Dict[str, Any]]] = []
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if max_rows is not None and len(rows) >= max_rows:
                break
            item = {headers[idx]: value for idx, value in enumerate(values) if idx < len(headers)}
            if any(_clean(value) for value in item.values()):
                rows.append((row_number, item))
        return headers, rows
    finally:
        workbook.close()


def discover_smart_meter_csvs(path: Path | str) -> List[Path]:
    """函数 discover_smart_meter_csvs：执行该模块中的相关处理逻辑。"""
    source = Path(path)
    if source.is_file():
        return [source]
    if not source.exists():
        return []
    candidates = list(source.glob(AMMETER_INFO_PATTERN)) + list(source.glob(STATION_PATTERN)) + list(source.glob(REALTIME_METER_PATTERN))
    return sorted({candidate.resolve() for candidate in candidates})


def _source_table(path: Path) -> str:
    """函数 _source_table：执行该模块中的相关处理逻辑。"""
    name = path.name.lower()
    if "ammeter_info" in name:
        return "nhtj_jkfile_ammeter_info"
    if "station" in name:
        return "nhtj_jkfile_station"
    if name.startswith("ss4-") and name.endswith(".xlsx"):
        return "realtime_meter_monitor"
    return path.stem


def _map_train_type(traintypeid: str) -> tuple[str, str]:
    """函数 _map_train_type：执行该模块中的相关处理逻辑。"""
    if not traintypeid:
        return "", "missing_traintypeid"
    return TRAIN_TYPE_MAP.get(traintypeid, ("", "unknown_traintypeid"))


def _append_warning(warnings: List[str], message: str) -> None:
    """函数 _append_warning：执行该模块中的相关处理逻辑。"""
    if message not in warnings:
        warnings.append(message)


def _issue(
    result: SmartMeterAdapterResult,
    severity: str,
    code: str,
    source: Path,
    row: object = "",
    field: str = "",
    message: str = "",
    suggestion: str = "",
) -> None:
    """函数 _issue：执行该模块中的相关处理逻辑。"""
    result.issues.append(
        SmartMeterIssue(
            severity=severity,
            code=code,
            source=str(source),
            row="" if row is None else str(row),
            field=field,
            message=message,
            suggestion=suggestion,
        )
    )


def _map_record(
    row: Dict[str, str],
    source: Path,
    source_table: str,
    source_row: int,
    config: SmartMeterAdapterConfig,
    result: SmartMeterAdapterResult,
) -> Optional[SmartMeterCalibrationRecord]:
    """函数 _map_record：执行该模块中的相关处理逻辑。"""
    row_warnings: List[str] = []
    traintypeid = _clean(row.get("traintypeid"))
    train_type_label, train_type_status = _map_train_type(traintypeid)
    if train_type_status == "unknown_traintypeid":
        _append_warning(row_warnings, f"unknown traintypeid={traintypeid}")
    direction_code = _clean(row.get("sxx"))
    direction_label = config.direction_map.get(direction_code, "unknown")
    direction_status = "mapped_from_field_description" if direction_label != "unknown" else "unknown_direction_code"
    if direction_label == "unknown":
        row_warnings.append(f"sxx={direction_code or '<blank>'} not in confirmed direction map")
        _issue(
            result,
            "warning",
            "smart_meter_unknown_direction_code",
            source,
            source_row,
            "sxx",
            f"sxx={direction_code or '<blank>'} is not in the confirmed map 1=down, 2=up.",
            "Ask data provider whether 0 is valid and what it means.",
        )

    use_ygdn = _optional_float(row.get("use_ygdn"))
    use_fkdn = _optional_float(row.get("use_fkdn"))
    if use_ygdn is None:
        _issue(result, "error", "smart_meter_invalid_number", source, source_row, "use_ygdn", "use_ygdn must be numeric.")
    if use_fkdn is None:
        _issue(result, "error", "smart_meter_invalid_number", source, source_row, "use_fkdn", "use_fkdn must be numeric.")
    if use_ygdn is None or use_fkdn is None:
        return None

    if not config.allow_negative_energy and (use_ygdn < 0 or use_fkdn < 0):
        _issue(result, "error", "smart_meter_negative_energy", source, source_row, "use_ygdn/use_fkdn", "Negative energy is not allowed by config.")
        return None
    if use_ygdn < 0 or use_fkdn < 0:
        row_warnings.append("negative energy value preserved")
    if use_ygdn == 0:
        _append_warning(row_warnings, "use_ygdn=0 may be shunting/no-pantograph or a statistics issue")

    abc_positive = _sum_optional(
        [_optional_float(row.get("a_use_ygdn")), _optional_float(row.get("b_use_ygdn")), _optional_float(row.get("c_use_ygdn"))]
    )
    abc_feedback = _sum_optional(
        [_optional_float(row.get("a_use_fkdn")), _optional_float(row.get("b_use_fkdn")), _optional_float(row.get("c_use_fkdn"))]
    )
    start_ygdn = _optional_float(row.get("start_ygdn"))
    end_ygdn = _optional_float(row.get("end_ygdn"))
    start_fkdn = _optional_float(row.get("start_fkdn"))
    end_fkdn = _optional_float(row.get("end_fkdn"))
    delta_positive = None if start_ygdn is None or end_ygdn is None else end_ygdn - start_ygdn
    delta_feedback = None if start_fkdn is None or end_fkdn is None else end_fkdn - start_fkdn

    positive_delta_ok = _nearly_equal(use_ygdn, delta_positive)
    feedback_delta_ok = _nearly_equal(use_fkdn, delta_feedback)
    positive_abc_ok = _nearly_equal(use_ygdn, abc_positive)
    feedback_abc_ok = _nearly_equal(use_fkdn, abc_feedback)
    if abc_positive is not None and abc_feedback is not None and positive_abc_ok and feedback_abc_ok:
        abc_status = "confirmed_use_equals_a_b_c_sum"
    elif abc_positive is not None and abc_feedback is not None:
        abc_status = "abc_sum_mismatch"
        row_warnings.append("A/B/C energy sum does not match use_ygdn/use_fkdn")
    else:
        abc_status = "abc_sum_incomplete"
    if abc_status == "abc_sum_incomplete" and any(_clean(row.get(column)) for column in ABC_ENERGY_COLUMNS):
        row_warnings.append("A/B/C energy fields are partially populated")
    if positive_delta_ok and feedback_delta_ok:
        delta_status = "confirmed_use_equals_end_minus_start"
    elif delta_positive is None and delta_feedback is None:
        delta_status = "delta_fields_missing"
    else:
        delta_status = "delta_mismatch"
        row_warnings.append("end-start energy delta does not match use_ygdn/use_fkdn")

    positive_kwh = use_ygdn * config.energy_scale_to_kwh
    feedback_kwh = use_fkdn * config.energy_scale_to_kwh
    return SmartMeterCalibrationRecord(
        source_table=source_table,
        source_file=source.name,
        source_row=source_row,
        guid=_clean(row.get("guid")),
        unitid=_clean(row.get("unitid")),
        traintypeid=traintypeid,
        train_type_label=train_type_label,
        train_type_mapping_status=train_type_status,
        trainid=_clean(row.get("trainid")),
        trainorder=_clean(row.get("trainorder") or row.get("cc")),
        direction_code=direction_code,
        direction_label=direction_label,
        direction_mapping_status=direction_status,
        starttime=_clean(row.get("starttime")),
        endtime=_clean(row.get("endtime")),
        recordtime="",
        start_station=_clean(row.get("start_station")),
        end_station=_clean(row.get("end_station")),
        association_policy="trainid_time_window_match",
        association_key_trainid=_clean(row.get("trainid")),
        association_time_start=_clean(row.get("starttime")),
        association_time_end=_clean(row.get("endtime")),
        association_status="station_and_ammeter_info_related_by_guid_to_nhtj_guid; realtime_requires_trainid_time_window",
        train_weight=_optional_float(row.get("train_weight")),
        train_load=_optional_float(row.get("train_load")),
        train_length=_optional_float(row.get("train_lenght")),
        train_num=_optional_float(row.get("train_num")),
        start_positive_energy_raw=start_ygdn,
        end_positive_energy_raw=end_ygdn,
        start_feedback_energy_raw=start_fkdn,
        end_feedback_energy_raw=end_fkdn,
        positive_energy_raw=use_ygdn,
        feedback_energy_raw=use_fkdn,
        positive_energy_kwh_assuming_scale=positive_kwh,
        feedback_energy_kwh_assuming_scale=feedback_kwh,
        net_energy_kwh_assuming_scale=positive_kwh - feedback_kwh,
        abc_positive_energy_raw_sum=abc_positive,
        abc_feedback_energy_raw_sum=abc_feedback,
        abc_sum_status=abc_status,
        delta_positive_energy_raw=delta_positive,
        delta_feedback_energy_raw=delta_feedback,
        delta_sum_status=delta_status,
        realtime_positive_cumulative_raw=None,
        realtime_feedback_cumulative_raw=None,
        energy_unit_status=CONFIRMED_ENERGY_UNIT_STATUS,
        mass_mapping_status=INTERVAL_MASS_STATUS,
        record_warnings="; ".join(row_warnings),
    )


def _map_realtime_record(
    row: Dict[str, Any],
    source: Path,
    source_table: str,
    source_row: int,
    config: SmartMeterAdapterConfig,
    result: SmartMeterAdapterResult,
) -> Optional[SmartMeterCalibrationRecord]:
    """函数 _map_realtime_record：执行该模块中的相关处理逻辑。"""
    trainid = _clean(row.get("trainid"))
    traintypeid = _clean(row.get("traintypeid"))
    train_type_label, train_type_status = _map_train_type(traintypeid)
    recordtime = _clean(row.get("recordtime"))
    ygdn = _optional_float(row.get("ygdn"))
    fk_dn = _optional_float(row.get("fk_dn"))
    if not trainid:
        _issue(result, "warning", "smart_meter_realtime_missing_trainid", source, source_row, "trainid", "Realtime meter row has no trainid.")
    if not recordtime:
        _issue(result, "warning", "smart_meter_realtime_missing_recordtime", source, source_row, "recordtime", "Realtime meter row has no recordtime.")
    return SmartMeterCalibrationRecord(
        source_table=source_table,
        source_file=source.name,
        source_row=source_row,
        guid="",
        unitid=_clean(row.get("unitid")),
        traintypeid=traintypeid,
        train_type_label=train_type_label,
        train_type_mapping_status=train_type_status,
        trainid=trainid,
        trainorder="",
        direction_code="",
        direction_label="unknown",
        direction_mapping_status="not_available_in_realtime_meter_table",
        starttime="",
        endtime="",
        recordtime=recordtime,
        start_station="",
        end_station="",
        association_policy="trainid_recordtime_match",
        association_key_trainid=trainid,
        association_time_start=recordtime,
        association_time_end=recordtime,
        association_status="realtime_to_interval_requires_trainid_time_window; interval_info_guid_maps_to_station_nhtj_guid",
        train_weight=_optional_float(row.get("zz")),
        train_load=None,
        train_length=None,
        train_num=None,
        start_positive_energy_raw=None,
        end_positive_energy_raw=None,
        start_feedback_energy_raw=None,
        end_feedback_energy_raw=None,
        positive_energy_raw=None,
        feedback_energy_raw=None,
        positive_energy_kwh_assuming_scale=None,
        feedback_energy_kwh_assuming_scale=None,
        net_energy_kwh_assuming_scale=None,
        abc_positive_energy_raw_sum=None,
        abc_feedback_energy_raw_sum=None,
        abc_sum_status="not_applicable_realtime_cumulative_record",
        delta_positive_energy_raw=None,
        delta_feedback_energy_raw=None,
        delta_sum_status="not_applicable_realtime_cumulative_record",
        realtime_positive_cumulative_raw=ygdn,
        realtime_feedback_cumulative_raw=fk_dn,
        energy_unit_status=CONFIRMED_ENERGY_UNIT_STATUS,
        mass_mapping_status=REALTIME_MASS_STATUS,
        record_warnings="",
    )


def load_smart_meter_file(
    path: Path | str,
    config: SmartMeterAdapterConfig | None = None,
    max_rows: Optional[int] = None,
) -> SmartMeterAdapterResult:
    """函数 load_smart_meter_file：执行该模块中的相关处理逻辑。"""
    source = Path(path)
    config = config or SmartMeterAdapterConfig()
    result = SmartMeterAdapterResult()
    if not source.exists():
        _issue(result, "error", "smart_meter_missing_file", source, "", "", "Smart meter CSV file is missing.")
        return result

    try:
        source_table = _source_table(source)
        if source.suffix.lower() == ".xlsx":
            required = ("id", "unitid", "traintypeid", "trainid", "recordtime", "ygdn", "fk_dn", "ammeterid")
            fieldnames, rows = _excel_rows(source, max_rows)
            for column in required:
                if column not in fieldnames:
                    _issue(result, "error", "smart_meter_missing_column", source, 1, column, f"Required column {column} is missing.")
            if result.errors:
                return result
            for row_number, row in rows:
                record = _map_realtime_record(row, source, source_table, row_number, config, result)
                if record is not None:
                    result.records.append(record)
            return result

        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            for column in REQUIRED_COLUMNS:
                if column not in fieldnames:
                    _issue(result, "error", "smart_meter_missing_column", source, 1, column, f"Required column {column} is missing.")
            for column in ABC_ENERGY_COLUMNS:
                if column not in fieldnames:
                    _issue(
                        result,
                        "warning",
                        "smart_meter_missing_abc_column",
                        source,
                        1,
                        column,
                        f"Optional A/B/C energy column {column} is missing.",
                    )
            if result.errors:
                return result
            for row_number, row in enumerate(reader, start=2):
                if max_rows is not None and len(result.records) >= max_rows:
                    break
                record = _map_record(row, source, source_table, row_number, config, result)
                if record is not None:
                    result.records.append(record)
    except OSError as exc:
        _issue(result, "error", "smart_meter_read_error", source, "", "", str(exc))
    return result


def load_smart_meter_directory(
    path: Path | str = DEFAULT_SMART_METER_DIR,
    config: SmartMeterAdapterConfig | None = None,
    max_rows_per_file: Optional[int] = None,
) -> SmartMeterAdapterResult:
    """函数 load_smart_meter_directory：执行该模块中的相关处理逻辑。"""
    source = Path(path)
    result = SmartMeterAdapterResult()
    files = discover_smart_meter_csvs(source)
    if not files:
        _issue(
            result,
            "warning",
            "smart_meter_no_csv_files",
            source,
            "",
            "",
            "No smart meter CSV files were found. Calibration export will be empty.",
        )
        return result
    for file_path in files:
        child = load_smart_meter_file(file_path, config=config, max_rows=max_rows_per_file)
        result.records.extend(child.records)
        result.issues.extend(child.issues)
    return result


def write_calibration_csv(records: Sequence[SmartMeterCalibrationRecord], output_csv: Path | str) -> None:
    """函数 write_calibration_csv：执行该模块中的相关处理逻辑。"""
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_COLUMNS))
        writer.writeheader()
        for record in records:
            row = asdict(record)
            writer.writerow(row)


def write_adapter_outputs(result: SmartMeterAdapterResult, output_csv: Path | str) -> None:
    """函数 write_adapter_outputs：执行该模块中的相关处理逻辑。"""
    output_path = Path(output_csv)
    write_calibration_csv(result.records, output_path)
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(result.summary(), ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Map smart meter tables to calibration records for the dispatch algorithm.")
    parser.add_argument("--input", type=Path, default=DEFAULT_SMART_METER_DIR, help="Smart meter CSV file or directory.")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--energy-scale-to-kwh", type=float, default=1.0)
    parser.add_argument("--max-rows-per-file", type=int)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    config = SmartMeterAdapterConfig(energy_scale_to_kwh=args.energy_scale_to_kwh)
    result = load_smart_meter_directory(args.input, config=config, max_rows_per_file=args.max_rows_per_file)
    write_adapter_outputs(result, args.output_csv)
    print(f"Smart meter calibration records: {len(result.records)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Warnings: {len(result.warnings)}")
    print(f"Output CSV: {args.output_csv}")
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
