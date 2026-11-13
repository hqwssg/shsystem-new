#!/usr/bin/env python3
"""Generate the canonical Shuohuang demo migration from zhongkong_data.

The generated migration is self-contained: it stores all 28 source files and
projects the data needed by the energy module into its relational tables.
Only Python's standard library is required, including for reading the XLSX.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree
from zipfile import ZipFile


PROJECT_CODE = "shuohuang_demo"
VERSION_CODE = "v1"
TIMETABLE_CODE = "TT-2026-DEMO"
SCENARIO_CODE = "BASELINE"
EXPECTED_COUNTS = {
    "files": 28,
    "stations": 33,
    "segments": 1390,
    "train_types": 2,
    "storage_devices": 2,
    "power_arms": 76,
    "station_resources": 33,
    "timetable_trains": 2,
    "timetable_stops": 22,
    "scenarios": 1,
}


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="生成朔黄重空完整示例数据 SQL")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_root / "zhongkong_data" / "data",
        help="原始数据目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "sql" / "carbon-energy" / "V5__shuohuang_full_dataset.sql",
        help="生成的 SQL 文件",
    )
    parser.add_argument("--check", action="store_true", help="只校验原始数据，不写文件")
    return parser.parse_args()


def read_csv(data_dir: Path, name: str) -> list[dict[str, str]]:
    with (data_dir / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(data_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((data_dir / name).read_text(encoding="utf-8-sig"))


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"无效的 XLSX 单元格引用：{reference}")
    value = 0
    for char in letters.group(0):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def read_xlsx(path: Path) -> dict[str, list[dict[str, Any]]]:
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns = {"m": main_ns, "r": office_ns, "p": package_ns}
    result: dict[str, list[dict[str, Any]]] = {}

    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(".//m:t", ns))
                for item in root.findall("m:si", ns)
            ]

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall("p:Relationship", ns)
        }

        for sheet in workbook.findall("m:sheets/m:sheet", ns):
            sheet_name = sheet.attrib["name"]
            relation_id = sheet.attrib[f"{{{office_ns}}}id"]
            raw_target = targets[relation_id]
            if raw_target.startswith("/"):
                target = raw_target.lstrip("/")
            elif raw_target.startswith("xl/"):
                target = raw_target
            else:
                target = f"xl/{raw_target}"
            root = ElementTree.fromstring(archive.read(target))
            grid: list[list[Any]] = []

            for row in root.findall(".//m:sheetData/m:row", ns):
                values: dict[int, Any] = {}
                for cell in row.findall("m:c", ns):
                    index = column_index(cell.attrib["r"])
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("m:v", ns)
                    inline_node = cell.find("m:is", ns)
                    raw_value: Any = "" if value_node is None else value_node.text or ""
                    if cell_type == "s" and raw_value != "":
                        raw_value = shared_strings[int(raw_value)]
                    elif cell_type == "inlineStr" and inline_node is not None:
                        raw_value = "".join(
                            node.text or "" for node in inline_node.findall(".//m:t", ns)
                        )
                    elif cell_type == "b":
                        raw_value = raw_value == "1"
                    values[index] = raw_value
                width = max(values, default=-1) + 1
                grid.append([values.get(index, "") for index in range(width)])

            if not grid:
                result[sheet_name] = []
                continue
            headers = [str(value).strip() for value in grid[0]]
            rows: list[dict[str, Any]] = []
            for values in grid[1:]:
                padded = values + [""] * (len(headers) - len(values))
                row = {headers[index]: padded[index] for index in range(len(headers)) if headers[index]}
                if any(value not in ("", None) for value in row.values()):
                    rows.append(row)
            result[sheet_name] = rows
    return result


def sql_text(value: Any) -> str:
    if value is None:
        return "NULL"
    raw = str(value).encode("utf-8")
    return f"CONVERT(X'{raw.hex()}' USING utf8mb4)"


def sql_key(value: Any) -> str:
    """Render a text key with binary semantics for mixed MySQL collations."""
    return f"BINARY {sql_text(value)}"


def sql_json(value: Any) -> str:
    return sql_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def sql_number(value: Any, *, nullable: bool = False) -> str:
    if value is None or str(value).strip() == "":
        if nullable:
            return "NULL"
        raise ValueError("必填数字为空")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"无效数字：{value}") from exc
    return format(number, "f")


def sql_bool(value: Any) -> str:
    return "1" if str(value).strip().lower() in {"1", "true", "yes", "是", "已有"} else "0"


def chunks(items: list[list[str]], size: int = 200) -> Iterable[list[list[str]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def insert_values(
    table: str,
    columns: list[str],
    rows: list[list[str]],
    update_columns: list[str],
    *,
    chunk_size: int = 200,
) -> str:
    statements: list[str] = []
    column_sql = ", ".join(f"`{column}`" for column in columns)
    update_sql = ", ".join(
        f"`{column}` = VALUES(`{column}`)" for column in update_columns
    )
    for group in chunks(rows, chunk_size):
        values_sql = ",\n    ".join("(" + ", ".join(row) + ")" for row in group)
        statements.append(
            f"INSERT INTO `{table}` ({column_sql}) VALUES\n    {values_sql}\n"
            f"ON DUPLICATE KEY UPDATE {update_sql};"
        )
    return "\n\n".join(statements)


def media_type(path: Path) -> str:
    return {
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[path.suffix.lower()]


def time_to_seconds(value: Any) -> int:
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        numeric = Decimal(text)
        if numeric < 1:
            return int(numeric * 86400)
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"无效时间：{value}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(Decimal(parts[2]))


def build_sql(data_dir: Path) -> tuple[str, dict[str, int]]:
    files = sorted(path for path in data_dir.rglob("*") if path.is_file())
    if len(files) != EXPECTED_COUNTS["files"]:
        raise ValueError(f"数据文件应为 28 个，实际为 {len(files)} 个")

    stations = read_csv(data_dir, "车站主数据.csv")
    station_capacity = {row["station_name"]: row for row in read_csv(data_dir, "车站能力.csv")}
    segments = read_csv(data_dir, "区间.csv")
    train_types = read_csv(data_dir, "列车参数.csv")
    storage_sections = read_csv(data_dir, "储能区段.csv")
    storage_parameters = read_json(data_dir, "储能参数.json")
    power_arms = read_csv(data_dir, "供电臂.csv")
    resource_rules = read_json(data_dir, "资源规则.json")
    workbook = read_xlsx(data_dir / "platform" / "运行图.xlsx")
    timetable_trains = workbook.get("trains", [])
    timetable_stops = workbook.get("timetable", [])
    scenarios = workbook.get("scenario", [])

    counts = {
        "files": len(files),
        "stations": len(stations),
        "segments": len(segments),
        "train_types": len(train_types),
        "storage_devices": len(storage_sections),
        "power_arms": len(power_arms),
        "station_resources": len(station_capacity),
        "timetable_trains": len(timetable_trains),
        "timetable_stops": len(timetable_stops),
        "scenarios": len(scenarios),
    }
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"数据数量不符合预期：{counts}")

    station_names = {row["station_name"] for row in stations}
    missing_capacity = station_names - station_capacity.keys()
    stop_names = {str(row["station_name"]).strip() for row in timetable_stops}
    train_station_names = {
        str(row[field]).strip()
        for row in timetable_trains
        for field in ("origin_station", "destination_station")
    }
    missing_stations = (stop_names | train_station_names) - station_names
    train_type_names = {row["name"] for row in train_types}
    missing_train_types = {str(row["train_type"]).strip() for row in timetable_trains} - train_type_names
    if missing_capacity or missing_stations or missing_train_types:
        raise ValueError(
            "数据关联不完整："
            f"缺少能力={sorted(missing_capacity)}，缺少站点={sorted(missing_stations)}，"
            f"缺少列车类型={sorted(missing_train_types)}"
        )

    digest = hashlib.sha256()
    for path in files:
        relative_path = path.relative_to(data_dir).as_posix()
        content = path.read_bytes()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    dataset_hash = digest.hexdigest()

    output: list[str] = [
        "-- Generated by tools/zhongkong/generate_dataset_sql.py. Do not edit manually.",
        "-- Canonical Shuohuang planning-placeholder dataset: 28 source files plus relational projections.",
        "SET NAMES utf8mb4;",
        "USE carbon_emissions;",
        "START TRANSACTION;",
        "",
        f"SET @project_id := (SELECT project_id FROM energy_project WHERE BINARY project_code = {sql_key(PROJECT_CODE)} LIMIT 1);",
        "SET @project_id := COALESCE(@project_id, UUID());",
        "INSERT INTO energy_project (project_id, project_code, project_name, route_name, timezone, status)",
        f"VALUES (@project_id, '{PROJECT_CODE}', {sql_text('朔黄演示')}, {sql_text('朔黄铁路')}, 'Asia/Shanghai', 'active')",
        "ON DUPLICATE KEY UPDATE project_name=VALUES(project_name), route_name=VALUES(route_name), timezone=VALUES(timezone), status=VALUES(status), updated_at=NOW();",
        "",
        f"SET @existing_version_id := (SELECT version_id FROM energy_project_version WHERE project_id=@project_id AND BINARY version_code = {sql_key(VERSION_CODE)} LIMIT 1);",
        "SET @existing_content_sha256 := (SELECT content_sha256 FROM energy_project_version WHERE version_id=@existing_version_id LIMIT 1);",
        "SET @legacy_content_sha256 := SHA2('shuohuang_demo/v1/local-fixture', 256);",
        f"SET @full_content_sha256 := '{dataset_hash}';",
        "-- A NULL version id deliberately aborts instead of overwriting an unrelated v1 dataset.",
        "SET @version_id := IF(@existing_version_id IS NULL, UUID(), IF(BINARY @existing_content_sha256 = BINARY @legacy_content_sha256 OR BINARY @existing_content_sha256 = BINARY @full_content_sha256, @existing_version_id, NULL));",
        "INSERT INTO energy_project_version",
        "    (version_id, project_id, version_code, version_name, data_status, lifecycle_status, effective_from, source_note, content_sha256, published_at)",
        f"VALUES (@version_id, @project_id, '{VERSION_CODE}', {sql_text('第1版（完整示例数据）')}, 'planning_placeholder', 'published',",
        f"        '2026-01-01 00:00:00', {sql_text('朔黄重空协调完整规划占位数据；含28个原始文件、实验性电表标定样本和虚拟运行图')}, @full_content_sha256, NOW())",
        "ON DUPLICATE KEY UPDATE version_name=VALUES(version_name), data_status=VALUES(data_status), lifecycle_status=VALUES(lifecycle_status),",
        "    effective_from=VALUES(effective_from), source_note=VALUES(source_note), content_sha256=VALUES(content_sha256), published_at=VALUES(published_at), updated_at=NOW();",
        "",
        "-- Rebuild only the canonical demo version. Timetable/scenario rows are retained because run history references them.",
        "DELETE s FROM energy_timetable_stop s JOIN energy_timetable_train t ON t.timetable_train_id=s.timetable_train_id JOIN energy_timetable tt ON tt.timetable_id=t.timetable_id WHERE tt.version_id=@version_id;",
        "DELETE t FROM energy_timetable_train t JOIN energy_timetable tt ON tt.timetable_id=t.timetable_id WHERE tt.version_id=@version_id;",
        "DELETE FROM energy_transport_task WHERE version_id=@version_id;",
        "DELETE FROM energy_od_demand WHERE version_id=@version_id;",
        "DELETE FROM energy_station_resource WHERE version_id=@version_id;",
        "DELETE FROM energy_route_segment WHERE version_id=@version_id;",
        "DELETE FROM energy_train_type_parameter WHERE version_id=@version_id;",
        "DELETE FROM energy_storage_device WHERE version_id=@version_id;",
        "DELETE FROM energy_power_arm WHERE version_id=@version_id;",
        "DELETE FROM energy_signaling_block WHERE version_id=@version_id;",
        "DELETE FROM energy_station WHERE version_id=@version_id;",
        "DELETE FROM energy_dataset_file WHERE version_id=@version_id;",
        "",
    ]

    dataset_rows: list[list[str]] = []
    for path in files:
        relative_path = path.relative_to(data_dir).as_posix()
        content = path.read_bytes()
        dataset_rows.append(
            [
                "@version_id",
                sql_text(relative_path),
                sql_text(media_type(path)),
                f"X'{content.hex()}'",
                str(len(content)),
                f"'{hashlib.sha256(content).hexdigest()}'",
            ]
        )
    output.append(
        insert_values(
            "energy_dataset_file",
            ["version_id", "relative_path", "media_type", "content", "content_size_bytes", "content_sha256"],
            dataset_rows,
            ["media_type", "content", "content_size_bytes", "content_sha256"],
            chunk_size=1,
        )
    )

    station_rows: list[list[str]] = []
    for row in stations:
        capacity = station_capacity[row["station_name"]]
        station_rows.append(
            [
                "UUID()",
                "@version_id",
                sql_text(row["station_id"]),
                sql_text(row["station_name"]),
                sql_number(row["position_km"]),
                sql_text(row["station_type"]),
                sql_number(capacity["track_capacity"]),
                sql_number(capacity["throat_capacity"]),
                sql_bool(capacity["is_terminal"]),
                sql_text(f"车站主数据.csv；来源页 {row['source_pages']}；状态 {row['algorithm_status'] or '未标注'}"),
            ]
        )
    output.append(
        insert_values(
            "energy_station",
            ["station_id", "version_id", "station_code", "station_name", "position_km", "station_type", "track_capacity", "throat_capacity", "is_terminal", "source_note"],
            station_rows,
            ["station_name", "position_km", "station_type", "track_capacity", "throat_capacity", "is_terminal", "source_note"],
        )
    )

    segment_rows = [
        [
            "UUID()",
            "@version_id",
            sql_text(row["segment_id"]),
            sql_number(row["start_km"]),
            sql_number(row["end_km"]),
            sql_number(row["gradient_per_mille"]),
            sql_number(row["curve_radius_m"], nullable=True),
            sql_number(row["speed_limit_kmh"], nullable=True),
            sql_text(row["terrain"]),
            "'both'",
            sql_text("区间.csv；真实线路纵断面/曲线合并投影"),
        ]
        for row in segments
    ]
    output.append(
        insert_values(
            "energy_route_segment",
            ["segment_id", "version_id", "segment_code", "start_km", "end_km", "gradient_permille", "curve_radius_m", "speed_limit_kmh", "terrain", "direction", "source_note"],
            segment_rows,
            ["start_km", "end_km", "gradient_permille", "curve_radius_m", "speed_limit_kmh", "terrain", "direction", "source_note"],
        )
    )

    train_type_rows: list[list[str]] = []
    for row in train_types:
        extra = {
            "tractionAdhesionWeightFraction": row["traction_adhesion_weight_fraction"],
            "brakeAdhesionWeightFraction": row["brake_adhesion_weight_fraction"],
            "massDataStatus": row["mass_data_status"],
            "massNote": row["mass_note"],
        }
        train_type_rows.append(
            [
                "UUID()", "@version_id", sql_text(row["name"]), sql_text(row["name"].lower()),
                sql_number(row["mass_tons"]), sql_number(row["mass_min_tons"], nullable=True), sql_number(row["mass_max_tons"], nullable=True),
                sql_number(row["length_km"]), sql_number(row["rotational_mass_factor"]), sql_number(row["max_traction_kN"]),
                sql_number(row["max_brake_kN"]), sql_number(row["max_power_kW"]), sql_number(row["davis_a"]), sql_number(row["davis_b"]),
                sql_number(row["davis_c"]), "NULL", "NULL", "NULL", "NULL", sql_text(row["direction"]),
                sql_number(row["longitudinal_segments"]), sql_json(extra), "'planning_placeholder'", sql_text("列车参数.csv；工程虚拟牵引参数，正式参数到位后替换"),
            ]
        )
    output.append(
        insert_values(
            "energy_train_type_parameter",
            ["train_type_id", "version_id", "train_type_code", "train_type", "mass_t", "mass_min_t", "mass_max_t", "length_km", "rotational_mass_factor", "max_traction_kn", "max_brake_kn", "max_power_kw", "davis_a", "davis_b", "davis_c", "traction_curve_json", "brake_curve_json", "regen_power_limit_kw", "regen_efficiency", "direction", "longitudinal_segments", "extra_parameters_json", "data_status", "source_note"],
            train_type_rows,
            ["train_type", "mass_t", "mass_min_t", "mass_max_t", "length_km", "rotational_mass_factor", "max_traction_kn", "max_brake_kn", "max_power_kw", "davis_a", "davis_b", "davis_c", "direction", "longitudinal_segments", "extra_parameters_json", "data_status", "source_note"],
        )
    )

    round_trip_efficiency = Decimal(str(storage_parameters["round_trip_efficiency"]))
    one_way_efficiency = round_trip_efficiency.sqrt()
    storage_rows: list[list[str]] = []
    for row in storage_sections:
        storage_rows.append(
            [
                "UUID()", "@version_id", sql_text(row["storage_section_id"]), sql_text(row["storage_section_id"]),
                sql_number(storage_parameters["capacity_kwh"]), sql_number(storage_parameters["max_charge_power_kW"]),
                sql_number(storage_parameters["max_discharge_power_kW"]), sql_number(one_way_efficiency), sql_number(one_way_efficiency),
                "0", "0", sql_number(storage_parameters["capacity_kwh"]), sql_number(row["start_km"]), sql_number(row["end_km"]),
                "'both'", "1", "'planning_placeholder'", sql_text(f"{row['note']}；{storage_parameters['note']}"),
            ]
        )
    output.append(
        insert_values(
            "energy_storage_device",
            ["storage_id", "version_id", "storage_code", "label", "capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw", "charge_efficiency", "discharge_efficiency", "initial_soc_kwh", "min_soc_kwh", "max_soc_kwh", "start_km", "end_km", "direction", "available", "data_status", "source_note"],
            storage_rows,
            ["label", "capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw", "charge_efficiency", "discharge_efficiency", "initial_soc_kwh", "min_soc_kwh", "max_soc_kwh", "start_km", "end_km", "direction", "available", "data_status", "source_note"],
        )
    )

    power_arm_rows: list[list[str]] = []
    direction_map = {"上行": "reverse", "下行": "forward"}
    for row in power_arms:
        review_value = str(row["needs_manual_review"]).strip()
        needs_review = "0" if review_value in {"否", "false", "0", "已有"} else "1"
        source_note = "；".join(
            part for part in [row["confidence"], row["review_note"], row["electrical_limit_note"], row["storage_note"]] if part
        )
        power_arm_rows.append(
            [
                "UUID()", "@version_id", sql_text(row["power_arm_id"]), sql_number(row["start_km"]), sql_number(row["end_km"]),
                sql_text(direction_map.get(row["direction"], "both")), sql_number(row["max_traction_supply_kw"], nullable=True),
                sql_number(row["max_regen_absorption_kw"], nullable=True), sql_number(row["max_grid_feedback_kw"], nullable=True),
                "0", needs_review, "'planning_placeholder'", sql_text(source_note),
            ]
        )
    output.append(
        insert_values(
            "energy_power_arm",
            ["power_arm_id", "version_id", "power_arm_code", "start_km", "end_km", "direction", "max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw", "direct_use_allowed", "needs_manual_review", "data_status", "source_note"],
            power_arm_rows,
            ["start_km", "end_km", "direction", "max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw", "direct_use_allowed", "needs_manual_review", "data_status", "source_note"],
        )
    )

    resource_rows: list[list[str]] = []
    for station in stations:
        capacity = station_capacity[station["station_name"]]
        resource_rows.append(
            [
                "UUID()", "@version_id",
                f"(SELECT station_id FROM energy_station WHERE version_id=@version_id AND BINARY station_code = {sql_key(station['station_id'])} LIMIT 1)",
                sql_number(capacity["track_capacity"]), sql_number(capacity["throat_capacity"]),
                sql_number(resource_rules["station_occupancy_s"]), sql_number(resource_rules["throat_occupancy_s"]),
                sql_json({"source": "车站能力.csv", "resourceRuleStatus": resource_rules["_metadata"]["data_status"]}),
                sql_text("车站能力.csv + 资源规则.json"),
            ]
        )
    output.append(
        insert_values(
            "energy_station_resource",
            ["station_resource_id", "version_id", "station_id", "track_capacity", "throat_capacity", "station_occupancy_s", "throat_occupancy_s", "extra_rules_json", "source_note"],
            resource_rows,
            ["track_capacity", "throat_capacity", "station_occupancy_s", "throat_occupancy_s", "extra_rules_json", "source_note"],
        )
    )

    output.extend(
        [
            "INSERT INTO energy_timetable (timetable_id, version_id, timetable_code, timetable_name, service_date, data_status, source_note)",
            f"VALUES (UUID(), @version_id, '{TIMETABLE_CODE}', {sql_text('朔黄重空协调虚拟运行图')}, '2026-01-01', 'planning_placeholder', {sql_text('platform/运行图.xlsx；真实站点上的流程验证虚拟运行图')})",
            "ON DUPLICATE KEY UPDATE timetable_name=VALUES(timetable_name), service_date=VALUES(service_date), data_status=VALUES(data_status), source_note=VALUES(source_note);",
            f"SET @timetable_id := (SELECT timetable_id FROM energy_timetable WHERE version_id=@version_id AND BINARY timetable_code = {sql_key(TIMETABLE_CODE)} LIMIT 1);",
            "",
        ]
    )
    for train in timetable_trains:
        output.extend(
            [
                "INSERT INTO energy_timetable_train (timetable_train_id, timetable_id, train_type_id, train_no, direction, origin_station_id, destination_station_id, service_type, evaluation_enabled)",
                "SELECT UUID(), @timetable_id,",
                f"    (SELECT train_type_id FROM energy_train_type_parameter WHERE version_id=@version_id AND BINARY train_type_code = {sql_key(train['train_type'])} LIMIT 1),",
                f"    {sql_text(train['train_id'])}, {sql_text(train['direction'])},",
                f"    (SELECT station_id FROM energy_station WHERE version_id=@version_id AND BINARY station_name = {sql_key(train['origin_station'])} LIMIT 1),",
                f"    (SELECT station_id FROM energy_station WHERE version_id=@version_id AND BINARY station_name = {sql_key(train['destination_station'])} LIMIT 1),",
                f"    {sql_text(train['load_state'])}, 1",
                "ON DUPLICATE KEY UPDATE train_type_id=VALUES(train_type_id), direction=VALUES(direction), origin_station_id=VALUES(origin_station_id), destination_station_id=VALUES(destination_station_id), service_type=VALUES(service_type), evaluation_enabled=VALUES(evaluation_enabled);",
                "",
            ]
        )

    service_date = date(2026, 1, 1)
    stop_rows: list[list[str]] = []
    previous_by_train: dict[str, int] = {}
    day_offset_by_train: dict[str, int] = {}
    for stop in timetable_stops:
        train_id = str(stop["train_id"]).strip()
        day_offset = day_offset_by_train.get(train_id, 0)
        arrival = time_to_seconds(stop["arrival_time"])
        previous = previous_by_train.get(train_id, -1)
        while arrival + day_offset < previous:
            day_offset += 86400
        arrival += day_offset
        departure = time_to_seconds(stop["departure_time"]) + day_offset
        while departure < arrival:
            departure += 86400
        day_offset_by_train[train_id] = day_offset
        previous_by_train[train_id] = departure
        arrival_at = datetime.combine(service_date, datetime.min.time()) + timedelta(seconds=arrival)
        departure_at = datetime.combine(service_date, datetime.min.time()) + timedelta(seconds=departure)
        stop_rows.append(
            [
                f"(SELECT timetable_train_id FROM energy_timetable_train WHERE timetable_id=@timetable_id AND BINARY train_no = {sql_key(train_id)} LIMIT 1)",
                sql_number(stop["seq"]),
                f"(SELECT station_id FROM energy_station WHERE version_id=@version_id AND BINARY station_name = {sql_key(stop['station_name'])} LIMIT 1)",
                f"'{arrival_at:%Y-%m-%d %H:%M:%S}'", f"'{departure_at:%Y-%m-%d %H:%M:%S}'", str(arrival), str(departure),
                sql_text(stop["stop_type"]), sql_text(stop.get("track") or None), sql_text(stop.get("operation_type") or None),
            ]
        )
    output.append(
        insert_values(
            "energy_timetable_stop",
            ["timetable_train_id", "seq", "station_id", "arrival_time", "departure_time", "arrival_offset_s", "departure_offset_s", "stop_type", "track", "operation_type"],
            stop_rows,
            ["station_id", "arrival_time", "departure_time", "arrival_offset_s", "departure_offset_s", "stop_type", "track", "operation_type"],
        )
    )

    scenario = scenarios[0]
    scenario_parameters = {
        "sourceScenarioId": scenario["scenario_id"],
        "storageCapacityKwh": scenario["storage_capacity_kwh"],
        "storagePowerKw": scenario["storage_power_kw"],
        "initialSocKwh": scenario["initial_soc_kwh"],
        "transferScope": scenario["transfer_scope"],
        "note": scenario["note"],
    }
    output.extend(
        [
            "INSERT INTO energy_scenario (scenario_id, version_id, scenario_code, allow_direct_use, allow_storage, settlement_step_s, parameters_json)",
            f"VALUES (UUID(), @version_id, '{SCENARIO_CODE}', {sql_bool(scenario['direct_use_enabled'])}, {sql_bool(scenario['storage_enabled'])}, {sql_number(scenario['settlement_time_step_s'])}, {sql_json(scenario_parameters)})",
            "ON DUPLICATE KEY UPDATE allow_direct_use=VALUES(allow_direct_use), allow_storage=VALUES(allow_storage), settlement_step_s=VALUES(settlement_step_s), parameters_json=VALUES(parameters_json);",
            "",
            "INSERT INTO energy_dept_project (dept_id, project_code, enabled, create_by, create_time)",
            "SELECT 3000, 'shuohuang_demo', '1', 'dataset-import', NOW() FROM sys_dept WHERE dept_id=3000",
            "ON DUPLICATE KEY UPDATE enabled='1', update_by='dataset-import', update_time=NOW();",
            "",
            "COMMIT;",
            "",
            "SELECT",
            "  (SELECT COUNT(*) FROM energy_dataset_file WHERE version_id=@version_id) AS dataset_files,",
            "  (SELECT COUNT(*) FROM energy_station WHERE version_id=@version_id) AS stations,",
            "  (SELECT COUNT(*) FROM energy_route_segment WHERE version_id=@version_id) AS route_segments,",
            "  (SELECT COUNT(*) FROM energy_power_arm WHERE version_id=@version_id) AS power_arms,",
            "  (SELECT COUNT(*) FROM energy_train_type_parameter WHERE version_id=@version_id) AS train_types,",
            "  (SELECT COUNT(*) FROM energy_storage_device WHERE version_id=@version_id) AS storage_devices,",
            "  (SELECT COUNT(*) FROM energy_timetable_train WHERE timetable_id=@timetable_id) AS timetable_trains;",
            "",
        ]
    )
    return "\n".join(output), counts


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"数据目录不存在：{data_dir}")
    sql, counts = build_sql(data_dir)
    if not args.check:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(sql, encoding="utf-8", newline="\n")
        print(f"已生成：{args.output.resolve()}")
    print("数据校验通过：" + "，".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
