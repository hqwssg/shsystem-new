"""把按主题的中文 Excel 转成算法现有 CSV/JSON，并生成用户模板。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import csv
import json
import re
import tempfile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from .excel_conflicts import conflict_report
from .file_names import records_to_algorithm_names, to_algorithm_path
from .mysql import SimulationRepository
from .snapshots import materialize_file_records, record_from_bytes, validate_relative_path

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "data_templates" / "user_excel"
HEADER_FILL = PatternFill("solid", fgColor="D9EAF7")
HEADER_FONT = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")


class ExcelConversionError(ValueError):
    """用户 Excel 无法转换成内部数据文件。"""


@dataclass(frozen=True)
class WorkbookSpec:
    code: str
    filename: str
    title: str
    hint: str
    aliases: tuple[str, ...]
    instruction: str
    sheets: tuple[tuple[str, tuple[str, ...], str], ...]
    convert: Callable[[Path, dict[str, bytes]], dict[str, bytes]]


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_maps(path: Path, sheet_name: str, workbook_name: str) -> list[tuple[int, dict[str, str]]]:
    book = load_workbook(path, data_only=True)
    if sheet_name not in book.sheetnames:
        return []
    sheet = book[sheet_name]
    headers = [_cell_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    if not any(headers):
        return []
    rows: list[tuple[int, dict[str, str]]] = []
    for row_idx, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        mapped = {headers[i]: _cell_text(values[i] if i < len(values) else "") for i in range(len(headers))}
        if not any(mapped.values()):
            continue
        rows.append((row_idx, mapped))
    return rows


def _require_number(raw: str, workbook: str, sheet: str, row: int, field: str) -> float:
    text = raw.replace(",", "").strip()
    if not text:
        raise ExcelConversionError(f"{workbook} / {sheet} / 第{row}行 / {field} 不能为空")
    try:
        return float(text)
    except ValueError as exc:
        raise ExcelConversionError(f"{workbook} / {sheet} / 第{row}行 / {field} 不是数字（不要把单位写进单元格）") from exc


def _optional_number(raw: str, workbook: str, sheet: str, row: int, field: str) -> float | None:
    if not raw:
        return None
    return _require_number(raw, workbook, sheet, row, field)


def _csv_bytes(fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})
    return buffer.getvalue().encode("utf-8")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _load_json(baseline: Mapping[str, bytes], relative_path: str) -> dict[str, Any]:
    raw = baseline.get(relative_path)
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _map_row(row: Mapping[str, str], mapping: Mapping[str, str]) -> dict[str, str]:
    return {english: row.get(chinese, "") for chinese, english in mapping.items()}


def _unmap_row(row: Mapping[str, Any], mapping: Mapping[str, str]) -> dict[str, str]:
    return {chinese: _format_cell(row.get(english, "")) for chinese, english in mapping.items()}


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ",".join(_format_cell(item) for item in value if item not in (None, ""))
    return str(value).strip()


def _csv_maps(content: bytes) -> list[dict[str, str]]:
    if not content:
        return []
    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    rows = []
    for row in reader:
        rows.append({str(key): _format_cell(value) for key, value in row.items() if key})
    return rows


def _display_direction(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"forward", "正向", "重车方向"}:
        return "正向"
    if lowered in {"reverse", "反向", "空车方向"}:
        return "反向"
    return str(value or "").strip()


def _display_train_type(value: str) -> str:
    text = str(value or "").strip()
    if text in {"Heavy", "重车"}:
        return "重车"
    if text in {"Empty", "空车"}:
        return "空车"
    return text


def convert_geometry(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    name = path.name
    overlays: dict[str, bytes] = {}
    route_rows = _sheet_maps(path, "线路参数", name)
    if route_rows:
        _row_idx, row = route_rows[0]
        payload = _load_json(baseline, "route_metadata.json")
        route = dict(payload.get("route") or {})
        if row.get("线路总长km"):
            route["total_length_km"] = _require_number(row["线路总长km"], name, "线路参数", _row_idx, "线路总长km")
        if row.get("最高速度kmh"):
            route["max_speed_kmh"] = _require_number(row["最高速度kmh"], name, "线路参数", _row_idx, "最高速度kmh")
        start = _optional_number(row.get("长大下坡起点km", ""), name, "线路参数", _row_idx, "长大下坡起点km")
        end = _optional_number(row.get("长大下坡终点km", ""), name, "线路参数", _row_idx, "长大下坡终点km")
        if start is not None or end is not None:
            current = list(route.get("long_downhill_range_km") or [0.0, 0.001])
            route["long_downhill_range_km"] = [
                start if start is not None else float(current[0]),
                end if end is not None else float(current[-1]),
            ]
        signaling = dict(route.get("signaling_system") or {})
        if row.get("信号模式"):
            signaling["mode"] = row["信号模式"]
        if signaling:
            route["signaling_system"] = signaling
        payload["route"] = route
        payload.setdefault("schema_version", "1.0")
        overlays["route_metadata.json"] = _json_bytes(payload)

    station_mapping = {"车站编号": "station_id", "车站名称": "name", "里程km": "position_km"}
    station_rows = _sheet_maps(path, "车站", name)
    if station_rows:
        converted = []
        for row_idx, row in station_rows:
            item = _map_row(row, station_mapping)
            if not item["name"]:
                raise ExcelConversionError(f"{name} / 车站 / 第{row_idx}行 / 车站名称 不能为空")
            item["position_km"] = str(_require_number(item["position_km"], name, "车站", row_idx, "里程km"))
            converted.append(item)
        overlays["stations.csv"] = _csv_bytes(("station_id", "name", "position_km"), converted)

    segment_mapping = {
        "区间编号": "segment_id",
        "起点km": "start_km",
        "终点km": "end_km",
        "坡度千分之一": "gradient_per_mille",
        "曲线半径m": "curve_radius_m",
        "地形": "terrain",
        "限速kmh": "speed_limit_kmh",
    }
    segment_rows = _sheet_maps(path, "区间", name)
    if segment_rows:
        converted = []
        for row_idx, row in segment_rows:
            item = _map_row(row, segment_mapping)
            item["start_km"] = str(_require_number(item["start_km"], name, "区间", row_idx, "起点km"))
            item["end_km"] = str(_require_number(item["end_km"], name, "区间", row_idx, "终点km"))
            converted.append(item)
        overlays["segments.csv"] = _csv_bytes(
            ("segment_id", "start_km", "end_km", "gradient_per_mille", "curve_radius_m", "terrain", "speed_limit_kmh"),
            converted,
        )
    return overlays


def convert_trains(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    del baseline
    name = path.name
    mapping = {
        "车型名称": "name",
        "质量吨": "mass_tons",
        "最大牵引力kN": "max_traction_kN",
        "最大制动力kN": "max_brake_kN",
        "回转质量系数": "rotational_mass_factor",
        "Davis_A": "davis_a",
        "Davis_B": "davis_b",
        "Davis_C": "davis_c",
        "列车长度km": "length_km",
        "纵向分段数": "longitudinal_segments",
        "方向": "direction",
        "牵引黏着质量比": "traction_adhesion_weight_fraction",
        "制动黏着质量比": "brake_adhesion_weight_fraction",
        "最大功率kW": "max_power_kW",
        "质量数据状态": "mass_data_status",
        "质量下限吨": "mass_min_tons",
        "质量上限吨": "mass_max_tons",
        "备注": "mass_note",
    }
    rows = _sheet_maps(path, "列车", name)
    if not rows:
        return {}
    converted = []
    for row_idx, row in rows:
        item = _map_row(row, mapping)
        if not item["name"]:
            raise ExcelConversionError(f"{name} / 列车 / 第{row_idx}行 / 车型名称 不能为空")
        direction = item["direction"].lower()
        if direction in {"正向", "重车方向", "forward"}:
            item["direction"] = "forward"
        elif direction in {"反向", "空车方向", "reverse"}:
            item["direction"] = "reverse"
        for field in ("mass_tons", "max_traction_kN", "max_brake_kN"):
            chinese = next(key for key, value in mapping.items() if value == field)
            item[field] = str(_require_number(item[field], name, "列车", row_idx, chinese))
        converted.append(item)
    return {
        "trains.csv": _csv_bytes(
            (
                "name", "mass_tons", "max_traction_kN", "max_brake_kN", "rotational_mass_factor",
                "davis_a", "davis_b", "davis_c", "length_km", "longitudinal_segments", "direction",
                "traction_adhesion_weight_fraction", "brake_adhesion_weight_fraction", "max_power_kW",
                "mass_data_status", "mass_min_tons", "mass_max_tons", "mass_note",
            ),
            converted,
        )
    }


def convert_storage(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    name = path.name
    overlays: dict[str, bytes] = {}
    battery_rows = _sheet_maps(path, "储能参数", name)
    if battery_rows:
        row_idx, row = battery_rows[0]
        payload = _load_json(baseline, "battery.json")
        mapping = {
            "容量kWh": "capacity_kwh", "往返效率": "round_trip_efficiency",
            "折旧成本每kWh": "depreciation_cost_per_kwh", "电价每kWh": "grid_price_per_kwh",
            "最大充电功率kW": "max_charge_power_kW", "最大放电功率kW": "max_discharge_power_kW",
        }
        for chinese, english in mapping.items():
            if row.get(chinese):
                payload[english] = _require_number(row[chinese], name, "储能参数", row_idx, chinese)
        basis = row.get("折旧计费口径", "").strip()
        if basis:
            basis = {"充放电总量": "total_throughput", "充电量": "charge_energy", "放电量": "discharge_energy"}.get(basis, basis)
            if basis not in {"total_throughput", "charge_energy", "discharge_energy"}:
                raise ExcelConversionError("折旧计费口径应为total_throughput、charge_energy或discharge_energy。")
            payload["depreciation_cost_basis"] = basis
        if row.get("备注"):
            payload["note"] = row["备注"]
        overlays["battery.json"] = _json_bytes(payload)

    zone_rows = _sheet_maps(path, "储能区段", name)
    if zone_rows:
        previous = _csv_maps(baseline.get("energy_transfer_zones.csv", b""))
        def identity(row):
            return str(row.get("zone_id") or row.get("storage_section_id") or "").strip()
        by_id = {identity(row): row for row in previous if identity(row)}
        mapping = dict(_ZONE_COLUMNS)
        converted = []
        for row_idx, row in zone_rows:
            submitted = _map_row(row, mapping)
            key = identity(submitted)
            original = by_id.get(key)
            if original is None and not key:
                matches = [old for old in previous if old.get("start_km") == submitted.get("start_km") and old.get("end_km") == submitted.get("end_km")]
                original = matches[0] if len(matches) == 1 else None
            merged = dict(original or {})
            # Old templates omit these columns. Retain their baseline values,
            # including provenance, rather than accidentally activating a planned facility.
            for chinese, english in mapping.items():
                if chinese in row and row[chinese] != "":
                    merged[english] = row[chinese]
            if merged.get("implementation_status"):
                status = {"已实施": "implemented", "规划": "planned"}.get(merged["implementation_status"], merged["implementation_status"])
                if status not in {"implemented", "planned"}:
                    raise ExcelConversionError(f"储能区段第{row_idx}行的实施状态应为implemented或planned。")
                merged["implementation_status"] = status
            if merged.get("active_in_operational_baseline"):
                raw = str(merged["active_in_operational_baseline"]).lower()
                if raw not in {"true", "false", "1", "0", "yes", "no", "是", "否"}:
                    raise ExcelConversionError(f"储能区段第{row_idx}行的运行基线启用应为是或否。")
                merged["active_in_operational_baseline"] = "true" if raw in {"true", "1", "yes", "是"} else "false"
            if merged.get("max_transfer_power_kW"):
                power = _require_number(str(merged["max_transfer_power_kW"]), name, "储能区段", row_idx, "最大传输功率kW")
                if not 0 < power < float("inf"):
                    raise ExcelConversionError("最大传输功率必须是正有限数值。")
                merged["max_transfer_power_kW"] = power
            converted.append(merged)
        fields = list(mapping.values())
        for row in previous + converted:
            fields.extend(key for key in row if key not in fields)
        overlays["energy_transfer_zones.csv"] = _csv_bytes(fields, converted)
    return overlays


def convert_timetable(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    del baseline
    name = path.name
    train_rows = _sheet_maps(path, "列车", name)
    stop_rows = _sheet_maps(path, "时刻表", name)
    if not train_rows and not stop_rows:
        return {}
    book = Workbook()
    trains = book.active
    trains.title = "trains"
    train_fields = (
        ("列车号", "train_id"),
        ("车型", "train_type"),
        ("方向", "direction"),
        ("始发站", "origin_station"),
        ("终到站", "destination_station"),
        ("质量吨", "mass_t"),
        ("编组", "formation"),
        ("牵引类型", "traction_type"),
        ("优先级", "priority"),
    )
    trains.append([english for _cn, english in train_fields])
    for row_idx, row in train_rows:
        values = []
        for chinese, english in train_fields:
            value = row.get(chinese, "")
            if english == "direction":
                lowered = value.lower()
                if lowered in {"正向", "重车方向", "forward"}:
                    value = "forward"
                elif lowered in {"反向", "空车方向", "reverse"}:
                    value = "reverse"
            if english == "train_type":
                if value in {"重车", "Heavy"}:
                    value = "Heavy"
                elif value in {"空车", "Empty"}:
                    value = "Empty"
            if english == "train_id" and not value:
                raise ExcelConversionError(f"{name} / 列车 / 第{row_idx}行 / 列车号 不能为空")
            values.append(value)
        trains.append(values)

    timetable = book.create_sheet("timetable")
    stop_fields = (
        ("列车号", "train_id"),
        ("顺序", "seq"),
        ("车站名称", "station_name"),
        ("里程km", "station_km"),
        ("到达时刻", "arrival_time"),
        ("出发时刻", "departure_time"),
        ("停站类型", "stop_type"),
        ("股道", "track"),
        ("作业类型", "operation_type"),
        ("备注", "note"),
    )
    timetable.append([english for _cn, english in stop_fields])
    for _row_idx, row in stop_rows:
        timetable.append([row.get(chinese, "") for chinese, _english in stop_fields])

    metadata = book.create_sheet("metadata")
    metadata.append(["key", "value"])
    for row_idx, row in _sheet_maps(path, "元数据", name):
        key = row.get("键") or row.get("key")
        if key:
            metadata.append([key, row.get("值") or row.get("value") or ""])
    if metadata.max_row == 1:
        metadata.append(["route_name", "shuohuang"])
        metadata.append(["time_zone", "Asia/Shanghai"])

    scenario = book.create_sheet("scenario")
    scenario.append(["scenario", "direct_use", "storage", "note"])
    scenario.append(["storage_no_direct", "FALSE", "TRUE", "朔黄默认无直发直用"])
    constraints = book.create_sheet("constraints")
    constraints.append(["constraint_type", "value", "note"])

    buffer = BytesIO()
    book.save(buffer)
    return {timetable_storage_path(path.name): buffer.getvalue()}


def convert_operations(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    del baseline
    name = path.name
    overlays: dict[str, bytes] = {}
    headway_mapping = {"线路": "line", "适用范围": "scope", "间隔分钟": "headway_min", "来源页": "source_pages"}
    headway_rows = _sheet_maps(path, "追踪间隔", name)
    if headway_rows:
        overlays["headway_constraints.csv"] = _csv_bytes(
            ("line", "scope", "headway_min", "source_pages"),
            [_map_row(row, headway_mapping) for _idx, row in headway_rows],
        )
    time_mapping = {
        "车站名称": "station_name",
        "来源站名": "source_station_name",
        "作业地点": "operation_location",
        "辆数": "cars",
        "作业类型": "operation_type",
        "对位分钟": "spotting_min",
        "装卸分钟": "loading_unloading_min",
        "取送分钟": "pickup_min",
        "合计分钟": "total_min",
        "来源页": "source_pages",
        "置信度": "confidence",
        "备注": "note",
    }
    time_rows = _sheet_maps(path, "技术作业时分", name)
    if time_rows:
        overlays["technical_operation_times.csv"] = _csv_bytes(tuple(time_mapping.values()), [_map_row(row, time_mapping) for _idx, row in time_rows])
    assign_mapping = {
        "车站名称": "station_name",
        "车型": "train_type",
        "方向": "direction",
        "适用位置": "applies_to",
        "最小占用分钟": "min_occupancy_min",
        "来源": "source",
        "备注": "note",
    }
    assign_rows = _sheet_maps(path, "作业适用范围", name)
    if assign_rows:
        converted = []
        for _idx, row in assign_rows:
            item = _map_row(row, assign_mapping)
            if item["train_type"] in {"重车", "Heavy"}:
                item["train_type"] = "Heavy"
            elif item["train_type"] in {"空车", "Empty"}:
                item["train_type"] = "Empty"
            converted.append(item)
        overlays["station_operation_assignments.csv"] = _csv_bytes(tuple(assign_mapping.values()), converted)
    return overlays


def convert_power_arm(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    del baseline
    name = path.name
    mapping = {
        "供电臂编号": "section_id",
        "线路": "road",
        "方向": "direction",
        "起点km": "start_km",
        "终点km": "end_km",
        "长度km": "length_km",
        "供电臂ID": "power_arm_id",
        "牵引变电所": "traction_substation_raw",
        "供电范围": "power_supply_range_raw",
        "可否储能": "storage_available",
        "储能区段编号": "storage_section_id",
        "储能起点km": "storage_start_km",
        "储能终点km": "storage_end_km",
        "备注": "review_note",
    }
    rows = _sheet_maps(path, "供电臂", name)
    if not rows:
        return {}
    converted = []
    for row_idx, row in rows:
        item = _map_row(row, mapping)
        if not item["section_id"]:
            raise ExcelConversionError(f"{name} / 供电臂 / 第{row_idx}行 / 供电臂编号 不能为空")
        item["start_km"] = str(_require_number(item["start_km"], name, "供电臂", row_idx, "起点km"))
        item["end_km"] = str(_require_number(item["end_km"], name, "供电臂", row_idx, "终点km"))
        converted.append(item)
    fieldnames = (
        "section_id", "road", "direction", "start_km", "end_km", "length_km", "power_arm_id",
        "traction_substation_raw", "power_supply_range_raw", "boundary_or_arm_raw", "confidence",
        "needs_manual_review", "review_note", "max_traction_supply_kw", "max_regen_absorption_kw",
        "max_grid_feedback_kw", "up_down_feed_rule", "grid_feedback_rule", "electrical_limit_status",
        "electrical_limit_note", "storage_available", "storage_section_id", "storage_start_km",
        "storage_end_km", "storage_status", "storage_note",
    )
    for item in converted:
        item.setdefault("max_traction_supply_kw", "1000000")
        item.setdefault("max_regen_absorption_kw", "1000000")
        item.setdefault("max_grid_feedback_kw", "1000000")
        item.setdefault("electrical_limit_status", "default_large_non_binding_until_official_limits")
    return {"power_arm_intervals.csv": _csv_bytes(fieldnames, converted)}


def convert_disturbance(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    name = path.name
    payload = _load_json(baseline, "platform/historical_disturbance_replay.json")
    meta_rows = _sheet_maps(path, "回放说明", name)
    if meta_rows:
        _idx, row = meta_rows[0]
        if row.get("回放编码"):
            payload["replay_code"] = row["回放编码"]
        if row.get("执行窗口秒"):
            payload["execute_window_s"] = int(_require_number(row["执行窗口秒"], name, "回放说明", _idx, "执行窗口秒"))
        if row.get("数据状态"):
            payload["data_status"] = row["数据状态"]
        if row.get("来源说明"):
            payload["source_note"] = row["来源说明"]
    payload.setdefault("schema_version", "1.3")
    payload.setdefault("cycles", [])

    cycles_by_index: dict[int, dict[str, Any]] = {}
    for existing in payload.get("cycles") or []:
        if isinstance(existing, dict) and existing.get("cycle_index") is not None:
            cycles_by_index[int(existing["cycle_index"])] = dict(existing)

    cycle_rows = _sheet_maps(path, "周期", name)
    if cycle_rows:
        cycles_by_index = {}
        for row_idx, row in cycle_rows:
            index = int(_require_number(row.get("周期序号", ""), name, "周期", row_idx, "周期序号"))
            cycles_by_index[index] = {
                "cycle_index": index,
                "current_time_s": int(_require_number(row.get("当前时刻秒", "0"), name, "周期", row_idx, "当前时刻秒")),
                "observed_at": row.get("观测时间") or None,
                "source_record_ids": [item for item in re.split(r"[，,;；\s]+", row.get("来源记录", "")) if item],
                "observed_heavy_delay_s": int(_optional_number(row.get("重车晚点秒", ""), name, "周期", row_idx, "重车晚点秒") or 0),
                "observed_empty_delay_s": int(_optional_number(row.get("空车晚点秒", ""), name, "周期", row_idx, "空车晚点秒") or 0),
                "events": [],
            }

    event_type_map = {
        "列车晚点": "train_delay",
        "train_delay": "train_delay",
        "储能状态": "storage_device_state",
        "storage_device_state": "storage_device_state",
        "临时限速": "temporary_speed_restriction",
        "temporary_speed_restriction": "temporary_speed_restriction",
    }
    if cycle_rows or _sheet_maps(path, "事件", name):
        for item in cycles_by_index.values():
            item["events"] = []
        for row_idx, row in _sheet_maps(path, "事件", name):
            index = int(_require_number(row.get("周期序号", ""), name, "事件", row_idx, "周期序号"))
            cycle = cycles_by_index.setdefault(index, {"cycle_index": index, "events": []})
            event_type = event_type_map.get(row.get("事件类型", ""), row.get("事件类型", ""))
            payload_body: dict[str, Any] = {}
            if event_type == "train_delay":
                payload_body["delay_s"] = int(_require_number(row.get("晚点秒", ""), name, "事件", row_idx, "晚点秒"))
            elif event_type == "storage_device_state":
                if row.get("储能kWh"):
                    payload_body["soc_kwh"] = _require_number(row["储能kWh"], name, "事件", row_idx, "储能kWh")
                available = row.get("是否可用", "")
                payload_body["available"] = available in {"是", "true", "True", "1", "可用"}
            elif event_type == "temporary_speed_restriction":
                payload_body = {
                    "start_km": _optional_number(row.get("起点km", ""), name, "事件", row_idx, "起点km"),
                    "end_km": _optional_number(row.get("终点km", ""), name, "事件", row_idx, "终点km"),
                    "speed_limit_kmh": _optional_number(row.get("限速kmh", ""), name, "事件", row_idx, "限速kmh"),
                    "start_time_s": int(_optional_number(row.get("开始秒", ""), name, "事件", row_idx, "开始秒") or 0),
                    "end_time_s": int(_optional_number(row.get("结束秒", ""), name, "事件", row_idx, "结束秒") or 0),
                    "direction": row.get("方向") or "down",
                    "reason": row.get("原因") or "",
                }
            cycle.setdefault("events", []).append({
                "event_id": row.get("事件编号") or f"event-{index}-{row_idx}",
                "event_type": event_type,
                "entity_id": row.get("对象编号") or "",
                "payload": payload_body,
            })
        payload["cycles"] = [cycles_by_index[key] for key in sorted(cycles_by_index)]
    if not meta_rows and not cycle_rows and not _sheet_maps(path, "事件", name):
        return {}
    return {"platform/historical_disturbance_replay.json": _json_bytes(payload)}


JOINT_PARAM_LABELS = {
    "重车质量": "heavy_mass",
    "空车质量": "empty_mass",
    "Davis_A": "davis_a",
    "Davis_B": "davis_b",
    "Davis_C": "davis_c",
    "最大牵引力": "max_traction",
    "最大制动力": "max_brake",
    "最大功率": "max_power",
    "储能容量": "storage_capacity",
    "储能充电功率": "storage_charge_power",
    "储能放电功率": "storage_discharge_power",
    "储能效率": "storage_efficiency",
    "牵引供电能力": "electrical_traction_supply",
    "再生吸收能力": "electrical_regen_absorption",
    "电网回馈能力": "electrical_grid_feedback",
}


def convert_joint_params(path: Path, baseline: Mapping[str, bytes]) -> dict[str, bytes]:
    name = path.name
    payload = _load_json(baseline, "platform/joint_parameter_ranges.json")
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("ranges", {})
    payload.setdefault("sampling", {})
    range_rows = _sheet_maps(path, "参数区间", name)
    if range_rows:
        ranges = dict(payload.get("ranges") or {})
        for row_idx, row in range_rows:
            code = row.get("参数编码") or JOINT_PARAM_LABELS.get(row.get("中文名称", ""), "")
            if not code:
                raise ExcelConversionError(f"{name} / 参数区间 / 第{row_idx}行 / 参数编码或中文名称 不能为空")
            low = _require_number(row.get("下限", ""), name, "参数区间", row_idx, "下限")
            high = _require_number(row.get("上限", ""), name, "参数区间", row_idx, "上限")
            ranges[code] = [low, high]
        payload["ranges"] = ranges
    sample_rows = _sheet_maps(path, "抽样", name)
    if sample_rows:
        row_idx, row = sample_rows[0]
        sampling = dict(payload.get("sampling") or {})
        if row.get("内部抽样次数"):
            sampling["interior_sample_count"] = int(_require_number(row["内部抽样次数"], name, "抽样", row_idx, "内部抽样次数"))
        if row.get("随机种子"):
            sampling["seed"] = int(_require_number(row["随机种子"], name, "抽样", row_idx, "随机种子"))
        payload["sampling"] = sampling
    if not range_rows and not sample_rows:
        return {}
    return {"platform/joint_parameter_ranges.json": _json_bytes(payload)}


WORKBOOKS: tuple[WorkbookSpec, ...] = (
    WorkbookSpec(
        code="geometry",
        filename="线路几何.xlsx",
        title="线路几何",
        hint="线路总长、车站、区间坡度限速",
        aliases=("线路几何", "geometry"),
        instruction="数字单元格只填数字，不要写 km。空表表示这一项沿用所选底稿版本。",
        sheets=(
            ("线路参数", ("线路总长km", "最高速度kmh", "长大下坡起点km", "长大下坡终点km", "信号模式"), "一般只填一行。信号模式可填 hybrid / fixed / moving。"),
            ("车站", ("车站编号", "车站名称", "里程km"), "至少两个车站，里程从起点递增。"),
            ("区间", ("区间编号", "起点km", "终点km", "坡度千分之一", "曲线半径m", "地形", "限速kmh"), "区间应尽量连续覆盖全线。"),
        ),
        convert=convert_geometry,
    ),
    WorkbookSpec(
        code="trains",
        filename="列车参数.xlsx",
        title="列车参数",
        hint="重车、空车质量与牵引制动",
        aliases=("列车参数", "trains"),
        instruction="通常两行：Heavy 重车、Empty 空车。方向填 正向 或 反向。",
        sheets=(
            ("列车", (
                "车型名称", "质量吨", "最大牵引力kN", "最大制动力kN", "回转质量系数",
                "Davis_A", "Davis_B", "Davis_C", "列车长度km", "纵向分段数", "方向",
                "牵引黏着质量比", "制动黏着质量比", "最大功率kW", "质量数据状态",
                "质量下限吨", "质量上限吨", "备注",
            ), "车型名称建议填 Heavy / Empty，与算法内部名称一致。"),
        ),
        convert=convert_trains,
    ),
    WorkbookSpec(
        code="storage",
        filename="储能设备.xlsx",
        title="储能设备",
        hint="容量功率电价和储能区段",
        aliases=("储能设备", "storage"),
        instruction="没有正式设备参数时不要改演示底稿。",
        sheets=(
            ("储能参数", ("容量kWh", "往返效率", "折旧成本每kWh", "电价每kWh", "最大充电功率kW", "最大放电功率kW", "备注", "折旧计费口径"), "只填一行。"),
            ("储能区段", ("起点km", "终点km", "效率", "储能区段编号", "数据状态", "备注", "设施编号", "最大传输功率kW", "实施状态", "运行基线启用", "来源文件", "来源SHA256"), "区段编号要和滚动任务里的储能设备对应。"),
        ),
        convert=convert_storage,
    ),
    WorkbookSpec(
        code="timetable",
        filename="运行图.xlsx",
        title="运行图",
        hint="列车时刻到发",
        aliases=("运行图", "timetable", "running_diagram"),
        instruction="时刻用 HH:MM:SS。车型填 重车/空车 或 Heavy/Empty。",
        sheets=(
            ("列车", ("列车号", "车型", "方向", "始发站", "终到站", "质量吨", "编组", "牵引类型", "优先级"), "每列车一行。"),
            ("时刻表", ("列车号", "顺序", "车站名称", "里程km", "到达时刻", "出发时刻", "停站类型", "股道", "作业类型", "备注"), "停站类型：origin / pass / stop / destination。"),
            ("元数据", ("键", "值"), "可填 route_name、time_zone。"),
        ),
        convert=convert_timetable,
    ),
    WorkbookSpec(
        code="operations",
        filename="追踪与作业.xlsx",
        title="追踪与作业",
        hint="追踪间隔和技术作业时分",
        aliases=("追踪与作业", "operations", "headway"),
        instruction="间隔用分钟。空表沿用底稿。",
        sheets=(
            ("追踪间隔", ("线路", "适用范围", "间隔分钟", "来源页"), ""),
            ("技术作业时分", ("车站名称", "来源站名", "作业地点", "辆数", "作业类型", "对位分钟", "装卸分钟", "取送分钟", "合计分钟", "来源页", "置信度", "备注"), ""),
            ("作业适用范围", ("车站名称", "车型", "方向", "适用位置", "最小占用分钟", "来源", "备注"), "适用位置可填 origin / destination / all。"),
        ),
        convert=convert_operations,
    ),
    WorkbookSpec(
        code="power_arm",
        filename="供电臂.xlsx",
        title="供电臂",
        hint="供电臂起终点和储能接入",
        aliases=("供电臂", "power_arm"),
        instruction="方向填 上行 或 下行。",
        sheets=(
            ("供电臂", ("供电臂编号", "线路", "方向", "起点km", "终点km", "长度km", "供电臂ID", "牵引变电所", "供电范围", "可否储能", "储能区段编号", "储能起点km", "储能终点km", "备注"), ""),
        ),
        convert=convert_power_arm,
    ),
    WorkbookSpec(
        code="disturbance",
        filename="滚动扰动.xlsx",
        title="滚动扰动",
        hint="历史晚点、限速、储能状态回放",
        aliases=("滚动扰动", "disturbance", "replay"),
        instruction="事件类型填 列车晚点 / 储能状态 / 临时限速。",
        sheets=(
            ("回放说明", ("回放编码", "执行窗口秒", "数据状态", "来源说明"), "只填一行。"),
            ("周期", ("周期序号", "当前时刻秒", "观测时间", "来源记录", "重车晚点秒", "空车晚点秒"), "周期序号从 0 开始。"),
            ("事件", ("周期序号", "事件编号", "事件类型", "对象编号", "晚点秒", "起点km", "终点km", "限速kmh", "开始秒", "结束秒", "方向", "储能kWh", "是否可用", "原因"), "按事件类型填写对应列，其余可空。"),
        ),
        convert=convert_disturbance,
    ),
    WorkbookSpec(
        code="joint_params",
        filename="联合参数.xlsx",
        title="联合参数",
        hint="稳健性参数上下限",
        aliases=("联合参数", "joint"),
        instruction="下限上限是相对倍率，例如 0.9 到 1.1。",
        sheets=(
            ("参数区间", ("参数编码", "中文名称", "下限", "上限"), "参数编码可空，系统按中文名称识别。"),
            ("抽样", ("内部抽样次数", "随机种子"), "只填一行。"),
        ),
        convert=convert_joint_params,
    ),
)


from .planning_excel import workbook_spec as _planning_spec, export_tables as _export_planning, TABLES as PLANNING_TABLES
WORKBOOKS += (_planning_spec(),)


def catalog() -> list[dict[str, str]]:
    return [
        {
            "code": item.code,
            "filename": item.filename,
            "title": item.title,
            "hint": item.hint,
        }
        for item in WORKBOOKS
    ]


def timetable_storage_path(filename: str) -> str:
    """运行图按用户上传的文件名保存在 platform/ 下，不再统一改成 running_diagram.xlsx。"""

    name = str(filename).replace("\\", "/").split("/")[-1]
    stem = Path(name).stem.strip() or "运行图"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .")
    cleaned = cleaned.replace("\\", "_").replace("/", "_")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "运行图"
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip(" .") or "运行图"
    return validate_relative_path(f"platform/{cleaned}.xlsx")


def is_timetable_relative_path(relative_path: str) -> bool:
    posix = str(relative_path).replace("\\", "/")
    lower = posix.lower()
    name = Path(posix).name.lower()
    if "running_diagram" in lower or "运行图" in posix or name in {"timetable.csv", "timetable.xlsx", "运行图.xlsx", "时刻表.csv", "时刻表.xlsx"}:
        return True
    parent = posix.rsplit("/", 1)[0] if "/" in posix else ""
    return parent == "platform" and name.endswith(".xlsx")


def identify_workbook(filename: str) -> WorkbookSpec:
    stem = Path(filename).stem
    for spec in WORKBOOKS:
        if Path(filename).name == spec.filename:
            return spec
        if any(alias and alias in stem for alias in spec.aliases):
            return spec
    raise ExcelConversionError(
        f"无法识别工作簿「{filename}」。请使用下载的模板文件名，例如 列车参数.xlsx。"
    )


def _spec_by_code(code: str) -> WorkbookSpec:
    for spec in WORKBOOKS:
        if spec.code == code:
            return spec
    raise ExcelConversionError(f"未知工作簿类型：{code}")


def identify_workbook_file(path: Path) -> WorkbookSpec:
    try:
        return identify_workbook(path.name)
    except ExcelConversionError:
        return _identify_workbook_by_sheets(path)


def _identify_workbook_by_sheets(path: Path) -> WorkbookSpec:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        names = set(book.sheetnames)
    finally:
        book.close()
    if "时刻表" in names:
        return _spec_by_code("timetable")
    if {"回放说明", "周期", "事件"} & names:
        return _spec_by_code("disturbance")
    if "参数区间" in names or "抽样" in names:
        return _spec_by_code("joint_params")
    if {"储能参数", "储能区段"} & names:
        return _spec_by_code("storage")
    if {"追踪间隔", "技术作业时分", "作业适用范围"} & names:
        return _spec_by_code("operations")
    if "供电臂" in names:
        return _spec_by_code("power_arm")
    if {"线路参数", "车站", "区间"} & names:
        return _spec_by_code("geometry")
    if "列车" in names:
        return _spec_by_code("trains")
    raise ExcelConversionError(
        f"无法识别工作簿「{path.name}」。请使用下载的模板，或保留模板中的工作表名称。"
    )


def convert_excel_files(paths: Sequence[Path], baseline: Mapping[str, bytes] | None = None) -> dict[str, bytes]:
    if not paths:
        raise ExcelConversionError("请至少上传一个 Excel 文件")
    overlays: dict[str, bytes] = {}
    seen: set[str] = set()
    base = dict(baseline or {})
    for path in paths:
        spec = identify_workbook_file(path)
        if spec.code in seen:
            raise ExcelConversionError(f"重复上传了同一类表格：{spec.title}")
        seen.add(spec.code)
        report = conflict_report(
            path.name,
            [
                (sheet_name, headers, _sheet_maps(path, sheet_name, path.name))
                for sheet_name, headers, _note in spec.sheets
            ],
        )
        if report:
            raise ExcelConversionError(report)
        converted = spec.convert(path, base)
        if not converted:
            raise ExcelConversionError(f"{path.name} 里没有有效数据行。空表请不要上传，系统会沿用底稿版本。")
        overlays.update(converted)
        base.update(converted)
    return overlays


def write_workbook_template(spec: WorkbookSpec, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    intro = book.active
    intro.title = "填写说明"
    intro["A1"] = spec.title
    intro["A1"].font = Font(bold=True, size=14)
    intro["A2"] = spec.instruction
    intro["A2"].alignment = WRAP
    intro["A3"] = "数字不要带单位。空工作表表示这一项沿用你选择的底稿版本。"
    intro["A3"].alignment = WRAP
    intro.column_dimensions["A"].width = 80
    intro.row_dimensions[2].height = 48
    for sheet_name, headers, note in spec.sheets:
        sheet = book.create_sheet(sheet_name)
        sheet.append(list(headers))
        for cell in sheet[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = max(12, min(22, len(header) + 4))
        if note:
            sheet.oddHeader.left.text = note
    book.save(destination)
    return destination


def write_templates(output_dir: Path | None = None) -> list[Path]:
    root = Path(output_dir or TEMPLATE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in WORKBOOKS:
        written.append(write_workbook_template(spec, root / spec.filename))
    (root / "README.md").write_text(
        "按主题填写中文 Excel，只上传改过的文件。发布时会叠在所选底稿版本上生成新版本。\n",
        encoding="utf-8",
    )
    (root / "catalog.json").write_text(
        json.dumps(catalog(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return written


def template_path(filename: str) -> Path:
    spec = identify_workbook(filename)
    path = TEMPLATE_DIR / spec.filename
    if not path.is_file():
        write_workbook_template(spec, path)
    return path


def import_excel_dataset(
    repository: SimulationRepository,
    excel_paths: Sequence[Path],
    *,
    base_project_code: str,
    base_version_code: str,
    project_code: str,
    project_name: str,
    route_name: str,
    version_code: str,
    data_status: str = "planning_placeholder",
    source_note: str = "",
) -> dict:
    _project_id, version_id = repository.resolve_version(base_project_code, base_version_code)
    baseline_records = repository.load_version_files(version_id)
    algorithm_records = records_to_algorithm_names(baseline_records)
    baseline = {record.relative_path: record.content for record in algorithm_records}
    overlays = convert_excel_files(excel_paths, baseline)
    with tempfile.TemporaryDirectory(prefix="energy-excel-") as temp_name:
        root = Path(temp_name)
        materialize_file_records(algorithm_records, root)
        if any(is_timetable_relative_path(path) for path in overlays):
            overlay_timetables = {
                path for path in overlays if is_timetable_relative_path(path)
            }
            overlay_timetables.update(to_algorithm_path(path) for path in overlay_timetables)
            for record in algorithm_records:
                if is_timetable_relative_path(record.relative_path) and record.relative_path not in overlay_timetables:
                    leftover = root / Path(*Path(record.relative_path).parts)
                    if leftover.is_file():
                        leftover.unlink()
        for relative_path, content in overlays.items():
            target = root / Path(*Path(relative_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        note = source_note or f"基于 {base_project_code}/{base_version_code}，覆盖 {', '.join(path.name for path in excel_paths)}"
        return repository.import_dataset(
            root,
            project_code=project_code,
            project_name=project_name,
            route_name=route_name,
            version_code=version_code,
            data_status=data_status,
            source_note=note,
        )


SINGLE_ROW_SHEETS = frozenset({"线路参数", "储能参数", "回放说明", "抽样", "场景集", "规划策略"})

_STATION_COLUMNS = (("车站编号", "station_id"), ("车站名称", "name"), ("里程km", "position_km"))
_SEGMENT_COLUMNS = (
    ("区间编号", "segment_id"),
    ("起点km", "start_km"),
    ("终点km", "end_km"),
    ("坡度千分之一", "gradient_per_mille"),
    ("曲线半径m", "curve_radius_m"),
    ("地形", "terrain"),
    ("限速kmh", "speed_limit_kmh"),
)
_TRAIN_COLUMNS = (
    ("车型名称", "name"),
    ("质量吨", "mass_tons"),
    ("最大牵引力kN", "max_traction_kN"),
    ("最大制动力kN", "max_brake_kN"),
    ("回转质量系数", "rotational_mass_factor"),
    ("Davis_A", "davis_a"),
    ("Davis_B", "davis_b"),
    ("Davis_C", "davis_c"),
    ("列车长度km", "length_km"),
    ("纵向分段数", "longitudinal_segments"),
    ("方向", "direction"),
    ("牵引黏着质量比", "traction_adhesion_weight_fraction"),
    ("制动黏着质量比", "brake_adhesion_weight_fraction"),
    ("最大功率kW", "max_power_kW"),
    ("质量数据状态", "mass_data_status"),
    ("质量下限吨", "mass_min_tons"),
    ("质量上限吨", "mass_max_tons"),
    ("备注", "mass_note"),
)
_ZONE_COLUMNS = (
    ("设施编号", "zone_id"),
    ("最大传输功率kW", "max_transfer_power_kW"),
    ("实施状态", "implementation_status"),
    ("运行基线启用", "active_in_operational_baseline"),
    ("来源文件", "source_document"),
    ("来源SHA256", "source_sha256"),
    ("起点km", "start_km"),
    ("终点km", "end_km"),
    ("效率", "efficiency"),
    ("储能区段编号", "storage_section_id"),
    ("数据状态", "data_status"),
    ("备注", "note"),
)
_TIMETABLE_TRAIN_COLUMNS = (
    ("列车号", "train_id"),
    ("车型", "train_type"),
    ("方向", "direction"),
    ("始发站", "origin_station"),
    ("终到站", "destination_station"),
    ("质量吨", "mass_t"),
    ("编组", "formation"),
    ("牵引类型", "traction_type"),
    ("优先级", "priority"),
)
_TIMETABLE_STOP_COLUMNS = (
    ("列车号", "train_id"),
    ("顺序", "seq"),
    ("车站名称", "station_name"),
    ("里程km", "station_km"),
    ("到达时刻", "arrival_time"),
    ("出发时刻", "departure_time"),
    ("停站类型", "stop_type"),
    ("股道", "track"),
    ("作业类型", "operation_type"),
    ("备注", "note"),
)
_HEADWAY_COLUMNS = (("线路", "line"), ("适用范围", "scope"), ("间隔分钟", "headway_min"), ("来源页", "source_pages"))
_OPERATION_TIME_COLUMNS = (
    ("车站名称", "station_name"),
    ("来源站名", "source_station_name"),
    ("作业地点", "operation_location"),
    ("辆数", "cars"),
    ("作业类型", "operation_type"),
    ("对位分钟", "spotting_min"),
    ("装卸分钟", "loading_unloading_min"),
    ("取送分钟", "pickup_min"),
    ("合计分钟", "total_min"),
    ("来源页", "source_pages"),
    ("置信度", "confidence"),
    ("备注", "note"),
)
_ASSIGNMENT_COLUMNS = (
    ("车站名称", "station_name"),
    ("车型", "train_type"),
    ("方向", "direction"),
    ("适用位置", "applies_to"),
    ("最小占用分钟", "min_occupancy_min"),
    ("来源", "source"),
    ("备注", "note"),
)
_POWER_ARM_COLUMNS = (
    ("供电臂编号", "section_id"),
    ("线路", "road"),
    ("方向", "direction"),
    ("起点km", "start_km"),
    ("终点km", "end_km"),
    ("长度km", "length_km"),
    ("供电臂ID", "power_arm_id"),
    ("牵引变电所", "traction_substation_raw"),
    ("供电范围", "power_supply_range_raw"),
    ("可否储能", "storage_available"),
    ("储能区段编号", "storage_section_id"),
    ("储能起点km", "storage_start_km"),
    ("储能终点km", "storage_end_km"),
    ("备注", "review_note"),
)
_POWER_ARM_FIELDS = (
    "section_id", "road", "direction", "start_km", "end_km", "length_km", "power_arm_id",
    "traction_substation_raw", "power_supply_range_raw", "boundary_or_arm_raw", "confidence",
    "needs_manual_review", "review_note", "max_traction_supply_kw", "max_regen_absorption_kw",
    "max_grid_feedback_kw", "up_down_feed_rule", "grid_feedback_rule", "electrical_limit_status",
    "electrical_limit_note", "storage_available", "storage_section_id", "storage_start_km",
    "storage_end_km", "storage_status", "storage_note",
)
_EVENT_TYPE_LABELS = {
    "train_delay": "列车晚点",
    "storage_device_state": "储能状态",
    "temporary_speed_restriction": "临时限速",
}


def _columns_of(pairs: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(chinese for chinese, _english in pairs)


def _mapping_of(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    return {chinese: english for chinese, english in pairs}


def _sheet_document(name: str, columns: Sequence[str], hint: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "columns": list(columns),
        "hint": hint,
        "singleRow": name in SINGLE_ROW_SHEETS,
        "rows": [dict(row) for row in rows],
    }


def _baseline_from_records(records: Sequence[Any]) -> dict[str, bytes]:
    algorithm_records = records_to_algorithm_names(records)
    return {record.relative_path: record.content for record in algorithm_records}


def _csv_sheet_rows(baseline: Mapping[str, bytes], relative_path: str, pairs: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    mapping = _mapping_of(pairs)
    return [_unmap_row(row, mapping) for row in _csv_maps(baseline.get(relative_path, b""))]


def _with_labels(rows: Sequence[Mapping[str, str]], *, direction: bool = False, train_type: bool = False) -> list[dict[str, str]]:
    labeled = []
    for source in rows:
        row = dict(source)
        if direction and "方向" in row:
            row["方向"] = _display_direction(row.get("方向", ""))
        if train_type and "车型" in row:
            row["车型"] = _display_train_type(row.get("车型", ""))
        labeled.append(row)
    return labeled


def _xlsx_tables(content: bytes) -> dict[str, list[dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix="energy-xlsx-read-") as temp_name:
        path = Path(temp_name) / "book.xlsx"
        path.write_bytes(content)
        book = load_workbook(path, data_only=True, read_only=True)
        try:
            tables: dict[str, list[dict[str, str]]] = {}
            for name in book.sheetnames:
                sheet = book[name]
                iterator = sheet.iter_rows(values_only=True)
                try:
                    header_row = next(iterator)
                except StopIteration:
                    tables[name] = []
                    continue
                headers = [_cell_text(cell) for cell in header_row]
                parsed: list[dict[str, str]] = []
                for values in iterator:
                    mapped = {
                        headers[index]: _cell_text(values[index] if index < len(values) else "")
                        for index in range(len(headers))
                        if headers[index]
                    }
                    if any(mapped.values()):
                        parsed.append(mapped)
                tables[name] = parsed
            return tables
        finally:
            book.close()


def _rename_english_rows(rows: Sequence[Mapping[str, str]], pairs: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    renamed = []
    for row in rows:
        item = {}
        for chinese, english in pairs:
            item[chinese] = _format_cell(row.get(english, row.get(chinese, "")))
        renamed.append(item)
    return renamed


def _first_timetable(baseline: Mapping[str, bytes]) -> tuple[str, bytes]:
    matches = [(path, content) for path, content in baseline.items() if is_timetable_relative_path(path)]
    if not matches:
        return "", b""
    for path, content in matches:
        if content[:2] == b"PK":
            return path, content
    path, content = matches[0]
    raise ExcelConversionError(f"运行图 {path} 不是 Excel，不能在线编辑")


def _export_geometry(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    payload = _load_json(baseline, "route_metadata.json")
    route = dict(payload.get("route") or {})
    downhill = list(route.get("long_downhill_range_km") or ["", ""])
    signaling = route.get("signaling_system") if isinstance(route.get("signaling_system"), dict) else {}
    route_row = {
        "线路总长km": _format_cell(route.get("total_length_km")),
        "最高速度kmh": _format_cell(route.get("max_speed_kmh")),
        "长大下坡起点km": _format_cell(downhill[0] if downhill else ""),
        "长大下坡终点km": _format_cell(downhill[-1] if len(downhill) > 1 else ""),
        "信号模式": _format_cell(signaling.get("mode")),
    }
    route_rows = [route_row] if any(route_row.values()) else []
    return [
        _sheet_document("线路参数", _columns_of((
            ("线路总长km", "total_length_km"),
            ("最高速度kmh", "max_speed_kmh"),
            ("长大下坡起点km", "start"),
            ("长大下坡终点km", "end"),
            ("信号模式", "mode"),
        )), "一般只填一行。信号模式可填 hybrid / fixed / moving。", route_rows),
        _sheet_document("车站", _columns_of(_STATION_COLUMNS), "至少两个车站，里程从起点递增。", _csv_sheet_rows(baseline, "stations.csv", _STATION_COLUMNS)),
        _sheet_document("区间", _columns_of(_SEGMENT_COLUMNS), "区间应尽量连续覆盖全线。", _csv_sheet_rows(baseline, "segments.csv", _SEGMENT_COLUMNS)),
    ]


def _export_trains(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    rows = _with_labels(_csv_sheet_rows(baseline, "trains.csv", _TRAIN_COLUMNS), direction=True)
    return [_sheet_document("列车", _columns_of(_TRAIN_COLUMNS), "车型名称建议填 Heavy / Empty。方向填 正向 或 反向。", rows)]


def _export_storage(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    payload = _load_json(baseline, "battery.json")
    battery_row = {
        "容量kWh": _format_cell(payload.get("capacity_kwh")),
        "往返效率": _format_cell(payload.get("round_trip_efficiency")),
        "折旧成本每kWh": _format_cell(payload.get("depreciation_cost_per_kwh")),
        "电价每kWh": _format_cell(payload.get("grid_price_per_kwh")),
        "最大充电功率kW": _format_cell(payload.get("max_charge_power_kW")),
        "最大放电功率kW": _format_cell(payload.get("max_discharge_power_kW")),
        "备注": _format_cell(payload.get("note")),
        "折旧计费口径": _format_cell(payload.get("depreciation_cost_basis", "total_throughput")),
    }
    battery_rows = [battery_row] if any(battery_row.values()) else []
    return [
        _sheet_document("储能参数", ("容量kWh", "往返效率", "折旧成本每kWh", "电价每kWh", "最大充电功率kW", "最大放电功率kW", "备注", "折旧计费口径"), "只填一行。", battery_rows),
        _sheet_document("储能区段", _columns_of(_ZONE_COLUMNS), "新版设施编号标识柔性传输设施；旧储能区段编号要与供电臂接入和储能设备对应。", _csv_sheet_rows(baseline, "energy_transfer_zones.csv", _ZONE_COLUMNS)),
    ]


def _export_timetable(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    _path, content = _first_timetable(baseline)
    tables = _xlsx_tables(content) if content else {}
    trains = _with_labels(_rename_english_rows(tables.get("trains") or [], _TIMETABLE_TRAIN_COLUMNS), direction=True, train_type=True)
    stops = _rename_english_rows(tables.get("timetable") or [], _TIMETABLE_STOP_COLUMNS)
    metadata = []
    for row in tables.get("metadata") or []:
        key = row.get("key") or row.get("键") or ""
        if not key:
            continue
        metadata.append({"键": _format_cell(key), "值": _format_cell(row.get("value") or row.get("值") or "")})
    return [
        _sheet_document("列车", _columns_of(_TIMETABLE_TRAIN_COLUMNS), "每列车一行。", trains),
        _sheet_document("时刻表", _columns_of(_TIMETABLE_STOP_COLUMNS), "停站类型：origin / pass / stop / destination。", stops),
        _sheet_document("元数据", ("键", "值"), "可填 route_name、time_zone。", metadata),
    ]


def _export_operations(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    assignments = _with_labels(_csv_sheet_rows(baseline, "station_operation_assignments.csv", _ASSIGNMENT_COLUMNS), train_type=True)
    return [
        _sheet_document("追踪间隔", _columns_of(_HEADWAY_COLUMNS), "", _csv_sheet_rows(baseline, "headway_constraints.csv", _HEADWAY_COLUMNS)),
        _sheet_document("技术作业时分", _columns_of(_OPERATION_TIME_COLUMNS), "", _csv_sheet_rows(baseline, "technical_operation_times.csv", _OPERATION_TIME_COLUMNS)),
        _sheet_document("作业适用范围", _columns_of(_ASSIGNMENT_COLUMNS), "适用位置可填 origin / destination / all。", assignments),
    ]


def _export_power_arm(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    return [_sheet_document("供电臂", _columns_of(_POWER_ARM_COLUMNS), "方向填 上行 或 下行。", _csv_sheet_rows(baseline, "power_arm_intervals.csv", _POWER_ARM_COLUMNS))]


def _export_disturbance(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    payload = _load_json(baseline, "platform/historical_disturbance_replay.json")
    meta = {
        "回放编码": _format_cell(payload.get("replay_code")),
        "执行窗口秒": _format_cell(payload.get("execute_window_s")),
        "数据状态": _format_cell(payload.get("data_status")),
        "来源说明": _format_cell(payload.get("source_note")),
    }
    cycles = []
    events = []
    for cycle in payload.get("cycles") or []:
        if not isinstance(cycle, dict):
            continue
        record_ids = cycle.get("source_record_ids") or []
        cycles.append({
            "周期序号": _format_cell(cycle.get("cycle_index")),
            "当前时刻秒": _format_cell(cycle.get("current_time_s")),
            "观测时间": _format_cell(cycle.get("observed_at")),
            "来源记录": _format_cell(record_ids),
            "重车晚点秒": _format_cell(cycle.get("observed_heavy_delay_s")),
            "空车晚点秒": _format_cell(cycle.get("observed_empty_delay_s")),
        })
        for event in cycle.get("events") or []:
            if not isinstance(event, dict):
                continue
            body = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            event_type = str(event.get("event_type") or "")
            events.append({
                "周期序号": _format_cell(cycle.get("cycle_index")),
                "事件编号": _format_cell(event.get("event_id")),
                "事件类型": _EVENT_TYPE_LABELS.get(event_type, event_type),
                "对象编号": _format_cell(event.get("entity_id")),
                "晚点秒": _format_cell(body.get("delay_s")),
                "起点km": _format_cell(body.get("start_km")),
                "终点km": _format_cell(body.get("end_km")),
                "限速kmh": _format_cell(body.get("speed_limit_kmh")),
                "开始秒": _format_cell(body.get("start_time_s")),
                "结束秒": _format_cell(body.get("end_time_s")),
                "方向": _format_cell(body.get("direction")),
                "储能kWh": _format_cell(body.get("soc_kwh")),
                "是否可用": _format_cell(body.get("available")) if "available" in body else "",
                "原因": _format_cell(body.get("reason")),
            })
    return [
        _sheet_document("回放说明", ("回放编码", "执行窗口秒", "数据状态", "来源说明"), "只填一行。", [meta] if any(meta.values()) else []),
        _sheet_document("周期", ("周期序号", "当前时刻秒", "观测时间", "来源记录", "重车晚点秒", "空车晚点秒"), "周期序号从 0 开始。", cycles),
        _sheet_document("事件", ("周期序号", "事件编号", "事件类型", "对象编号", "晚点秒", "起点km", "终点km", "限速kmh", "开始秒", "结束秒", "方向", "储能kWh", "是否可用", "原因"), "按事件类型填写对应列，其余可空。", events),
    ]


def _export_joint(baseline: Mapping[str, bytes]) -> list[dict[str, Any]]:
    payload = _load_json(baseline, "platform/joint_parameter_ranges.json")
    label_by_code = {english: chinese for chinese, english in JOINT_PARAM_LABELS.items()}
    ranges = []
    for code, bounds in (payload.get("ranges") or {}).items():
        pair = list(bounds) if isinstance(bounds, (list, tuple)) else ["", ""]
        ranges.append({
            "参数编码": _format_cell(code),
            "中文名称": label_by_code.get(str(code), ""),
            "下限": _format_cell(pair[0] if pair else ""),
            "上限": _format_cell(pair[1] if len(pair) > 1 else ""),
        })
    sampling = payload.get("sampling") if isinstance(payload.get("sampling"), dict) else {}
    sample_row = {
        "内部抽样次数": _format_cell(sampling.get("interior_sample_count")),
        "随机种子": _format_cell(sampling.get("seed")),
    }
    return [
        _sheet_document("参数区间", ("参数编码", "中文名称", "下限", "上限"), "参数编码可空，系统按中文名称识别。", ranges),
        _sheet_document("抽样", ("内部抽样次数", "随机种子"), "只填一行。", [sample_row] if any(sample_row.values()) else []),
    ]


_EXPORTERS = {
    "storage_planning": _export_planning,
    "geometry": _export_geometry,
    "trains": _export_trains,
    "storage": _export_storage,
    "timetable": _export_timetable,
    "operations": _export_operations,
    "power_arm": _export_power_arm,
    "disturbance": _export_disturbance,
    "joint_params": _export_joint,
}


def _export_topic(spec: WorkbookSpec, baseline: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "code": spec.code,
        "title": spec.title,
        "hint": spec.hint,
        "instruction": spec.instruction,
        "sheets": _EXPORTERS[spec.code](baseline),
    }


_SHEET_SOURCE_FILES = {
    **{("storage_planning", name): (file,) for name, _, file in PLANNING_TABLES},
    ("geometry", "线路参数"): ("route_metadata.json",),
    ("geometry", "车站"): ("stations.csv",),
    ("geometry", "区间"): ("segments.csv",),
    ("trains", "列车"): ("trains.csv",),
    ("storage", "储能参数"): ("battery.json",),
    ("storage", "储能区段"): ("energy_transfer_zones.csv",),
    ("operations", "追踪间隔"): ("headway_constraints.csv",),
    ("operations", "技术作业时分"): ("technical_operation_times.csv",),
    ("operations", "作业适用范围"): ("station_operation_assignments.csv",),
    ("power_arm", "供电臂"): ("power_arm_intervals.csv",),
    ("disturbance", "回放说明"): ("platform/historical_disturbance_replay.json",),
    ("disturbance", "周期"): ("platform/historical_disturbance_replay.json",),
    ("disturbance", "事件"): ("platform/historical_disturbance_replay.json",),
    ("joint_params", "参数区间"): ("platform/joint_parameter_ranges.json",),
    ("joint_params", "抽样"): ("platform/joint_parameter_ranges.json",),
}


def sheet_storage_paths(topic: str, sheet: str) -> tuple[str, ...] | None:
    """返回这一张表要读取的库内路径。运行图文件名不固定时返回 None。"""

    spec = _spec_by_code(topic)
    names = [name for name, _columns, _hint in spec.sheets]
    if sheet not in names:
        raise ExcelConversionError(f"{spec.title} 没有工作表「{sheet}」")
    if topic == "timetable":
        return None
    english_paths = _SHEET_SOURCE_FILES.get((topic, sheet))
    if not english_paths:
        raise ExcelConversionError(f"{spec.title} / {sheet} 没有对应的数据文件")
    from .file_names import to_storage_path
    return tuple(to_storage_path(path) for path in english_paths)


def load_sheet_records(repository: SimulationRepository, version_id: Any, topic: str, sheet: str) -> tuple[Any, ...]:
    """只加载一张表要用到的版本文件。"""

    paths = sheet_storage_paths(topic, sheet)
    if paths is None:
        records = []
        for record in repository.load_version_files_like(version_id, "platform/%"):
            if is_timetable_relative_path(record.relative_path):
                records.append(record)
        return tuple(records)
    return repository.load_version_files_by_paths(version_id, paths)


def export_version_tables(records: Sequence[Any], topic: str | None = None, sheet: str | None = None) -> dict[str, Any]:
    """把已发布版本文件反解成与 Excel 模板一致的中文表。"""

    baseline = _baseline_from_records(records)
    if topic:
        document = _export_topic(_spec_by_code(topic), baseline)
        if sheet:
            matched = [item for item in document["sheets"] if item["name"] == sheet]
            if not matched:
                raise ExcelConversionError(f"未知工作表：{sheet}")
            document["sheets"] = matched
        return document
    return {"topics": [_export_topic(spec, baseline) for spec in WORKBOOKS]}


def _normalize_submitted_sheets(sheets: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    by_name: dict[str, list[dict[str, str]]] = {}
    for sheet in sheets:
        name = str(sheet.get("name") or "").strip()
        if not name:
            continue
        rows = []
        for row in sheet.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            rows.append({str(key): _format_cell(value) for key, value in row.items()})
        by_name[name] = rows
    return by_name


def _write_topic_workbook(spec: WorkbookSpec, rows_by_sheet: Mapping[str, Sequence[Mapping[str, str]]], destination: Path) -> Path:
    book = Workbook()
    first = True
    for sheet_name, headers, _note in spec.sheets:
        sheet = book.active if first else book.create_sheet(sheet_name)
        first = False
        sheet.title = sheet_name
        sheet.append(list(headers))
        for row in rows_by_sheet.get(sheet_name) or []:
            if not any(_cell_text(row.get(header, "")) for header in headers):
                continue
            sheet.append([_cell_text(row.get(header, "")) for header in headers])
    destination.parent.mkdir(parents=True, exist_ok=True)
    book.save(destination)
    return destination


def _empty_timetable_bytes() -> bytes:
    book = Workbook()
    trains = book.active
    trains.title = "trains"
    trains.append([english for _chinese, english in _TIMETABLE_TRAIN_COLUMNS])
    timetable = book.create_sheet("timetable")
    timetable.append([english for _chinese, english in _TIMETABLE_STOP_COLUMNS])
    metadata = book.create_sheet("metadata")
    metadata.append(["key", "value"])
    metadata.append(["route_name", "shuohuang"])
    metadata.append(["time_zone", "Asia/Shanghai"])
    scenario = book.create_sheet("scenario")
    scenario.append(["scenario", "direct_use", "storage", "note"])
    scenario.append(["storage_no_direct", "FALSE", "TRUE", "朔黄默认无直发直用"])
    constraints = book.create_sheet("constraints")
    constraints.append(["constraint_type", "value", "note"])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _json_overlay(overlays: dict[str, bytes], baseline: Mapping[str, bytes], relative_path: str) -> dict[str, Any]:
    raw = overlays.get(relative_path) or baseline.get(relative_path) or b""
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _fill_explicit_empty_sheets(
    topic: str,
    rows_by_sheet: Mapping[str, Sequence[Mapping[str, str]]],
    overlays: dict[str, bytes],
    baseline: Mapping[str, bytes],
    timetable_path: str,
) -> dict[str, bytes]:
    """前端明确提交的空表要清掉对应文件，不能沿用底稿。"""

    def submitted_empty(name: str) -> bool:
        return name in rows_by_sheet and not rows_by_sheet[name]

    if topic == "geometry":
        if submitted_empty("车站"):
            overlays["stations.csv"] = _csv_bytes(("station_id", "name", "position_km"), [])
        if submitted_empty("区间"):
            overlays["segments.csv"] = _csv_bytes(tuple(english for _chinese, english in _SEGMENT_COLUMNS), [])
    elif topic == "trains" and submitted_empty("列车"):
        overlays["trains.csv"] = _csv_bytes(tuple(english for _chinese, english in _TRAIN_COLUMNS), [])
    elif topic == "storage" and submitted_empty("储能区段"):
        overlays["energy_transfer_zones.csv"] = _csv_bytes(tuple(english for _chinese, english in _ZONE_COLUMNS), [])
    elif topic == "operations":
        if submitted_empty("追踪间隔"):
            overlays["headway_constraints.csv"] = _csv_bytes(tuple(english for _chinese, english in _HEADWAY_COLUMNS), [])
        if submitted_empty("技术作业时分"):
            overlays["technical_operation_times.csv"] = _csv_bytes(tuple(english for _chinese, english in _OPERATION_TIME_COLUMNS), [])
        if submitted_empty("作业适用范围"):
            overlays["station_operation_assignments.csv"] = _csv_bytes(tuple(english for _chinese, english in _ASSIGNMENT_COLUMNS), [])
    elif topic == "power_arm" and submitted_empty("供电臂"):
        overlays["power_arm_intervals.csv"] = _csv_bytes(_POWER_ARM_FIELDS, [])
    elif topic == "timetable" and submitted_empty("列车") and submitted_empty("时刻表"):
        overlays[timetable_path] = _empty_timetable_bytes()
    elif topic == "disturbance" and (submitted_empty("周期") or submitted_empty("事件") or submitted_empty("回放说明")):
        key = "platform/historical_disturbance_replay.json"
        if submitted_empty("回放说明") and submitted_empty("周期") and submitted_empty("事件"):
            overlays[key] = _json_bytes({"schema_version": "1.3", "cycles": []})
        elif submitted_empty("周期"):
            payload = _json_overlay(overlays, baseline, key)
            payload["cycles"] = []
            payload.setdefault("schema_version", "1.3")
            overlays[key] = _json_bytes(payload)
    elif topic == "joint_params" and (submitted_empty("参数区间") or submitted_empty("抽样")):
        key = "platform/joint_parameter_ranges.json"
        if submitted_empty("参数区间") and submitted_empty("抽样"):
            overlays[key] = _json_bytes({"schema_version": "1.0", "ranges": {}, "sampling": {}})
        else:
            payload = _json_overlay(overlays, baseline, key)
            payload.setdefault("schema_version", "1.0")
            if submitted_empty("参数区间"):
                payload["ranges"] = {}
            if submitted_empty("抽样"):
                payload["sampling"] = {}
            overlays[key] = _json_bytes(payload)
    return overlays


def tables_to_overlays(
    topic: str,
    sheets: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, bytes] | None = None,
    *,
    timetable_path: str | None = None,
) -> dict[str, bytes]:
    """把在线编辑提交的中文表转回算法文件，并沿用现有 Excel 校验。"""

    spec = _spec_by_code(topic)
    rows_by_sheet = _normalize_submitted_sheets(sheets)
    base = dict(baseline or {})
    if topic == "storage_planning":
        from .planning_excel import convert_rows
        names = [sheet.get("name") for sheet in sheets]
        if len(names) != len(set(names)):
            raise ExcelConversionError("储能规划不能重复提交同一张工作表。")
        return convert_rows(rows_by_sheet, base, preserve_empty=False)
    stored_timetable = timetable_path or "platform/运行图.xlsx"
    filename = Path(stored_timetable).name if topic == "timetable" else spec.filename
    with tempfile.TemporaryDirectory(prefix="energy-tables-") as temp_name:
        path = _write_topic_workbook(spec, rows_by_sheet, Path(temp_name) / filename)
        overlays = dict(spec.convert(path, base) or {})
    return _fill_explicit_empty_sheets(topic, rows_by_sheet, overlays, base, stored_timetable)


def replace_version_topic(
    repository: SimulationRepository,
    *,
    project_code: str,
    version_code: str,
    topic: str,
    sheets: Sequence[Mapping[str, Any]],
    source_note: str = "",
) -> dict:
    """用一个主题的表格覆盖当前版本里对应文件，版本编码保持不变。"""

    if not isinstance(sheets, Sequence) or isinstance(sheets, (str, bytes)):
        raise ExcelConversionError("sheets 必须是数组")
    spec = _spec_by_code(topic)
    _project_id, version_id = repository.resolve_version(project_code, version_code)
    baseline_records = repository.load_version_files(version_id)
    algorithm_records = records_to_algorithm_names(baseline_records)
    baseline = {record.relative_path: record.content for record in algorithm_records}
    timetable_path = None
    if topic == "timetable":
        existing = [record.relative_path for record in algorithm_records if is_timetable_relative_path(record.relative_path)]
        timetable_path = existing[0] if existing else "platform/运行图.xlsx"
    overlays = tables_to_overlays(topic, sheets, baseline, timetable_path=timetable_path)
    if not overlays:
        raise ExcelConversionError(f"{spec.title} 没有可保存的内容")
    by_path = {record.relative_path: record for record in algorithm_records}
    for relative_path, content in overlays.items():
        by_path[relative_path] = record_from_bytes(relative_path, content)
    note = source_note.strip() if source_note else f"在线编辑 {spec.title}"
    return repository.replace_dataset(version_id, tuple(by_path[key] for key in sorted(by_path)), source_note=note)
