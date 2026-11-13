# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import csv
import json
import shutil
import tempfile

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "source"
SOURCE_DIR = DEFAULT_SOURCE_DIR
TEMPLATE_DIR = ROOT / "data" / "real_partial"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "real_shuohuang"
OUTPUT_DIR = DEFAULT_OUTPUT_DIR
PRESERVED_DERIVED_FILES = (
    "smart_meter_calibration_samples.csv",
    "smart_meter_calibration_samples_summary.json",
    "smart_meter_representative_interval_samples.csv",
    "energy_calibration_factors.json",
)
ROUTE_END_KM = 583.003
MAX_SPEED_KMH = 120.0


def clean(value: Any) -> str:
    """函数 clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def as_float(value: Any, default: float | None = None) -> float | None:
    """函数 as_float：执行该模块中的相关处理逻辑。"""
    text = clean(value)
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def read_sheet_rows(path: Path, sheet_name: str | None = None) -> list[dict[str, Any]]:
    """函数 read_sheet_rows：执行该模块中的相关处理逻辑。"""
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [clean(item) for item in rows[0]]
    result: list[dict[str, Any]] = []
    for values in rows[1:]:
        row = {headers[idx]: value for idx, value in enumerate(values) if idx < len(headers) and headers[idx]}
        if any(clean(value) for value in row.values()):
            result.append(row)
    return result


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    """函数 write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(fieldnames)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """函数 write_json：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_if_exists(name: str) -> None:
    """函数 copy_if_exists：执行该模块中的相关处理逻辑。"""
    source = TEMPLATE_DIR / name
    if source.exists():
        shutil.copy2(source, OUTPUT_DIR / name)


def formation_note(row: dict[str, str]) -> str:
    """函数 formation_note：执行该模块中的相关处理逻辑。"""
    load_state = clean(row.get("load_state"))
    mode = clean(row.get("formation_mode"))
    wagon_count = clean(row.get("wagon_count"))
    mass_tons = clean(row.get("mass_tons"))
    category = clean(row.get("category"))

    mass_note = f"{mass_tons}吨{'空车' if load_state == 'empty' else '重车'}对应{wagon_count}辆整列总重" if mass_tons and wagon_count else ""
    if mode == "1+1":
        mode_note = "1+1为两台机车分布式重载编组模式"
    elif mode == "2+0":
        mode_note = "2+0为两台机车集中在头部的重联编组模式"
    elif mode == "单牵":
        mode_note = "单牵为单机牵引方式"
    elif mode == "单牵(2+0)":
        mode_note = "单牵为牵引方式，括号内2+0为对应编组模式，二者不冲突"
    else:
        mode_note = f"{mode}为编组/牵引模式" if mode else ""

    extra: list[str] = []
    if category == "combined_10000_ton":
        extra.append("组合万吨是否涉及组合/拆解作业由正式运行图确认")
    if category == "ordinary":
        extra.append("普列是否纳入当前算法由正式运行图确认")

    parts = [part for part in (mass_note, mode_note, *extra) if part]
    return "；".join(parts)


def build_train_formation_modes() -> None:
    """函数 build_train_formation_modes：执行该模块中的相关处理逻辑。"""
    source = TEMPLATE_DIR / "train_formation_modes_2025.csv"
    if not source.exists():
        return
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = [
        "category",
        "load_state",
        "formation_mode",
        "traction_config_raw",
        "wagon_count",
        "mass_tons",
        "notes",
    ]
    output_rows = []
    for row in rows:
        item = {field: row.get(field, "") for field in fields}
        item["notes"] = formation_note(row)
        output_rows.append(item)
    write_csv(OUTPUT_DIR / "train_formation_modes_2025.csv", fields, output_rows)


def load_gradients() -> list[dict[str, Any]]:
    """函数 load_gradients：执行该模块中的相关处理逻辑。"""
    rows = read_sheet_rows(SOURCE_DIR / "geometry" / "gradients.xlsx", "坡度表")
    gradients: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        start = as_float(row.get("start_km"))
        end = as_float(row.get("end_km"))
        length_m = as_float(row.get("length(m)"))
        grade = as_float(row.get("坡度(千分率)"))
        if start is None or end is None or grade is None:
            continue
        if end <= start:
            continue
        clipped_end = min(end, ROUTE_END_KM)
        if clipped_end <= start:
            continue
        if length_m is None or clipped_end < end - 1e-9:
            length_m = (clipped_end - start) * 1000.0
        gradients.append(
            {
                "gradient_id": f"G{idx:04d}",
                "source_image": clean(row.get("source_image")),
                "start_km": round(start, 6),
                "end_km": round(clipped_end, 6),
                "length_m": round(length_m, 3),
                "gradient_per_mille": round(grade, 6),
            }
        )
    return [item for item in gradients if item["start_km"] < ROUTE_END_KM and item["end_km"] > 0]


def load_curves() -> list[dict[str, Any]]:
    """函数 load_curves：执行该模块中的相关处理逻辑。"""
    rows = read_sheet_rows(SOURCE_DIR / "geometry" / "curves.xlsx", "线路曲线表 (2)")
    curves: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        start = as_float(row.get("曲线起始位置(km)"))
        end = as_float(row.get("曲线结束位置(km)"))
        radius = as_float(row.get("半径R(m)"))
        length_m = as_float(row.get("曲线长度L(m)"))
        if start is None or end is None or radius is None:
            continue
        if end <= start or radius <= 0:
            continue
        clipped_end = min(end, ROUTE_END_KM)
        if clipped_end <= start:
            continue
        if length_m is None or clipped_end < end - 1e-9:
            length_m = (clipped_end - start) * 1000.0
        curves.append(
            {
                "curve_id": f"C{idx:04d}",
                "start_km": round(start, 6),
                "end_km": round(clipped_end, 6),
                "radius_m": round(radius, 3),
                "length_m": round(length_m, 3),
                "direction": clean(row.get("曲线方向")),
                "source_sheet": "线路曲线表 (2)",
            }
        )
    return [item for item in curves if item["start_km"] < ROUTE_END_KM and item["end_km"] > 0]


def find_gradient(gradients: list[dict[str, Any]], midpoint: float) -> float:
    """函数 find_gradient：执行该模块中的相关处理逻辑。"""
    for item in gradients:
        if float(item["start_km"]) <= midpoint < float(item["end_km"]):
            return float(item["gradient_per_mille"])
    return 0.0


def find_curve_radius(curves: list[dict[str, Any]], midpoint: float) -> float | None:
    """函数 find_curve_radius：执行该模块中的相关处理逻辑。"""
    candidates = [
        float(item["radius_m"])
        for item in curves
        if float(item["start_km"]) <= midpoint < float(item["end_km"])
    ]
    if not candidates:
        return None
    return min(candidates)


def build_segments(gradients: list[dict[str, Any]], curves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """函数 build_segments：执行该模块中的相关处理逻辑。"""
    breakpoints = {0.0, ROUTE_END_KM}
    for item in gradients:
        breakpoints.add(max(0.0, min(ROUTE_END_KM, float(item["start_km"]))))
        breakpoints.add(max(0.0, min(ROUTE_END_KM, float(item["end_km"]))))
    for item in curves:
        breakpoints.add(max(0.0, min(ROUTE_END_KM, float(item["start_km"]))))
        breakpoints.add(max(0.0, min(ROUTE_END_KM, float(item["end_km"]))))

    points = sorted(point for point in breakpoints if 0.0 <= point <= ROUTE_END_KM)
    segments: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(zip(points, points[1:]), start=1):
        if end - start <= 1e-9:
            continue
        midpoint = (start + end) / 2.0
        radius = find_curve_radius(curves, midpoint)
        speed_limit = 75.0 if start < 76.293 else MAX_SPEED_KMH
        segments.append(
            {
                "segment_id": f"RS{idx:04d}",
                "start_km": f"{start:.6f}",
                "end_km": f"{end:.6f}",
                "gradient_per_mille": f"{find_gradient(gradients, midpoint):.6f}",
                "curve_radius_m": "" if radius is None else f"{radius:.3f}",
                "terrain": "real_profile",
                "speed_limit_kmh": f"{speed_limit:.1f}",
            }
        )
    return segments


def export_power_arm_intervals() -> None:
    """函数 export_power_arm_intervals：执行该模块中的相关处理逻辑。"""
    rows = read_sheet_rows(SOURCE_DIR / "power_arm" / "power_arm_continuous_intervals.xlsx", "供电臂连续区间表")
    fields = [
        "section_id",
        "road",
        "direction",
        "start_km",
        "end_km",
        "length_km",
        "power_arm_id",
        "traction_substation_raw",
        "power_supply_range_raw",
        "boundary_or_arm_raw",
        "confidence",
        "needs_manual_review",
        "review_note",
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
    ]
    output_rows = []
    for row in rows:
        item = {field: row.get(field, "") for field in fields}
        # The legacy K145-K200.7 markers are Shuohuang-only planning assumptions.
        # Applying them by chainage to other lines creates false storage availability.
        if clean(item.get("road")) != "朔黄线":
            item.update(
                {
                    "storage_available": "否",
                    "storage_section_id": "",
                    "storage_start_km": "",
                    "storage_end_km": "",
                    "storage_status": "no_storage_outside_shuohuang_scope",
                    "storage_note": "当前储能规划标记仅适用于朔黄线；其他线路不按同公里标映射。",
                }
            )
        output_rows.append(item)
    write_csv(OUTPUT_DIR / "power_arm_intervals.csv", fields, output_rows)


def build_route_metadata() -> None:
    """函数 build_route_metadata：执行该模块中的相关处理逻辑。"""
    payload = {
        "schema_version": "1.0",
        "line_name": "shuohuang_real",
        "data_status": "real_mainline_stations_from_line_diagrams_1_2_3",
        "route": {
            "total_length_km": ROUTE_END_KM,
            "max_speed_kmh": MAX_SPEED_KMH,
            "long_downhill_range_km": [0.0, 0.001],
            "signaling_system": {
                "mode": "hybrid",
                "check_step_s": 5,
            },
        },
        "source_metadata": {
            "description": "Shuohuang real-data bundle generated from reviewed project data. Virtual route geometry and virtual energy-transfer zones are not copied.",
            "real_sources": [
                "stations.csv: real mainline stations from line diagrams 1/2/3 and PDF station table (terminal 黄骅港 K583+003)",
                "data/source/geometry/gradients.xlsx -> gradients.csv and segments.csv gradient_per_mille",
                "data/source/geometry/curves.xlsx -> curves.csv and segments.csv curve_radius_m",
                "data/source/power_arm/power_arm_continuous_intervals.xlsx -> power_arm_intervals.csv",
                "previously structured station/headway/technical-operation/train-formation files extracted from provided PDF or user files",
            ],
            "explicit_assumptions": [
                "stations.csv contains only real Shuohuang mainline stations covered by line diagrams 1/2/3; terminal is 黄骅港 at K583+003.",
                "Storage capacity, efficiency, charge power and economic parameters are sourced from shuohuang_data/5.储能系统参数.doc; discharge power and connection topology remain unprovided.",
                "No official signaling block boundaries are available; signaling_blocks.csv is intentionally omitted.",
                "route.signaling_system.mode keeps the loader-compatible value 'hybrid'; real signaling details are not confirmed.",
                "route.long_downhill_range_km keeps a minimal loader-compatible range; the optimizer uses the reviewed gradient table instead.",
                "energy_transfer_zones.csv contains the provided implemented and planned flexible energy-coordination ranges; only the implemented row enters the operational baseline.",
                "Train traction/brake/Davis/max_power use engineering virtual presets in trains.csv; replace when official traction data arrives.",
                "Power-arm electrical traction/absorption/feed-back limits use large non-binding defaults until official limits are available.",
                "Direct up/down regenerative energy use is disabled for Shuohuang; storage reuse remains governed by the provided active flexible-zone data and explicit storage parameters.",
            ],
            "needs_confirmation": [
                "Bare K / 黄K / 朔黄K chainage equivalence in the current Shuohuang K0-K583.003 model.",
                "SK/准池K connection-line chainage conversion only if future cross-line modeling is required.",
                "Official running diagram format and real timetable.",
                "Smart meter units, multipliers, phase aggregation and direction code sxx=0.",
                "Official traction/brake/resistance parameters if dispatch energy numbers need calibration.",
            ],
        },
    }
    write_json(OUTPUT_DIR / "route_metadata.json", payload)


def build_battery() -> None:
    """函数 build_battery：执行该模块中的相关处理逻辑。"""
    write_json(
        OUTPUT_DIR / "battery.json",
        {
            "capacity_kwh": 145.0,
            "round_trip_efficiency": 0.90,
            "depreciation_cost_per_kwh": 0.326,
            "depreciation_cost_basis": "total_throughput",
            "grid_price_per_kwh": 0.6818,
            "max_charge_power_kW": 2000.0,
            "max_discharge_power_kW": 0.0,
            "planning_max_discharge_power_assumption_kW": 2000.0,
            "data_status": "provided_document_partial_real_parameters",
            "scenario_name": "provided_storage_system_parameters_20260918",
            "planning_assumption": False,
            "field_data_status": {
                "capacity_kwh": "provided_45kwh_flywheel_plus_100kwh_lto",
                "round_trip_efficiency": "provided",
                "depreciation_cost_per_kwh": "provided",
                "grid_price_per_kwh": "provided",
                "max_charge_power_kW": "provided",
                "max_discharge_power_kW": "missing_conservative_zero",
            },
            "source_document": "shuohuang_data/5.储能系统参数.doc",
            "source_sha256": "59df2cf3fadba1e4ae8a6979a9e05cd290f1211dedd7cbd0eb66ac041c981357",
            "note": "飞轮45kWh与钛酸锂100kWh合计145kWh；最大放电功率、站址和接入供电臂未提供，运行基线按0kW放电保守处理。",
        },
    )


def build_energy_transfer_zones() -> None:
    """函数 build_energy_transfer_zones：执行该模块中的相关处理逻辑。"""
    write_csv(
        OUTPUT_DIR / "energy_transfer_zones.csv",
        (
            "zone_id",
            "start_km",
            "end_km",
            "max_transfer_power_kW",
            "efficiency",
            "implementation_status",
            "active_in_operational_baseline",
            "data_status",
            "source_document",
            "source_sha256",
            "note",
        ),
        [
            {
                "zone_id": "FLEX-IMPLEMENTED-001",
                "start_km": 108.0,
                "end_km": 219.0,
                "max_transfer_power_kW": 12000.0,
                "efficiency": 0.95,
                "implementation_status": "implemented",
                "active_in_operational_baseline": "true",
            "data_status": "provided_document",
            "source_document": "shuohuang_data/6.柔性供电能量协同区间.doc",
            "source_sha256": "b23dba45cd1950b3fccf84ba4b10d7767a1c3d57087f841c02c6c00b8b11bef8",
            "note": "已实施区间，进入当前运行基线。",
            },
            {
                "zone_id": "FLEX-PLANNED-001",
                "start_km": 16.0,
                "end_km": 139.0,
                "max_transfer_power_kW": 12000.0,
                "efficiency": 0.95,
                "implementation_status": "planned",
                "active_in_operational_baseline": "false",
            "data_status": "provided_document",
            "source_document": "shuohuang_data/6.柔性供电能量协同区间.doc",
            "source_sha256": "b23dba45cd1950b3fccf84ba4b10d7767a1c3d57087f841c02c6c00b8b11bef8",
            "note": "规划区间，仅用于规划情景。",
            },
        ],
    )


def main(output_dir: Path | None = None, source_dir: Path | None = None) -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    global OUTPUT_DIR, SOURCE_DIR
    target_dir = (output_dir or DEFAULT_OUTPUT_DIR).resolve()
    SOURCE_DIR = (source_dir or DEFAULT_SOURCE_DIR).resolve()
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shuohuang-build-", dir=target_dir.parent) as temp_name:
        staging_dir = Path(temp_name) / "dataset"
        staging_dir.mkdir()
        OUTPUT_DIR = staging_dir

        for name in (
            "stations.csv",
            "station_resources.csv",
            "headway_constraints.csv",
            "technical_operation_times.csv",
            "technical_operation_times_out_of_scope.csv",
            "station_operation_assignments.csv",
            "pdf_station_master.csv",
            "pdf_station_out_of_scope.csv",
            "operating_conditions.json",
            "resource_config.json",
        ):
            copy_if_exists(name)
        build_train_formation_modes()

        gradients = load_gradients()
        curves = load_curves()
        segments = build_segments(gradients, curves)

        write_csv(
            OUTPUT_DIR / "gradients.csv",
            ("gradient_id", "source_image", "start_km", "end_km", "length_m", "gradient_per_mille"),
            gradients,
        )
        write_csv(
            OUTPUT_DIR / "curves.csv",
            ("curve_id", "start_km", "end_km", "radius_m", "length_m", "direction", "source_sheet"),
            curves,
        )
        write_csv(
            OUTPUT_DIR / "segments.csv",
            ("segment_id", "start_km", "end_km", "gradient_per_mille", "curve_radius_m", "terrain", "speed_limit_kmh"),
            segments,
        )

    # 保留 Heavy/Empty 接口行以兼容当前优化器，但不能据此声称已经完成物理标定。
        copy_if_exists("trains.csv")
        build_battery()
        build_energy_transfer_zones()
        build_route_metadata()
        export_power_arm_intervals()

        for name in PRESERVED_DERIVED_FILES:
            source = target_dir / name
            if source.exists():
                shutil.copy2(source, OUTPUT_DIR / name)

        try:
            output_label = str(target_dir.relative_to(ROOT))
        except ValueError:
            output_label = str(target_dir)
        try:
            source_label = str(SOURCE_DIR.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            source_label = str(SOURCE_DIR)
        summary = {
            "output_dir": output_label,
            "source_dir": source_label,
            "gradient_count": len(gradients),
            "curve_count": len(curves),
            "segment_count": len(segments),
            "copied_structured_real_extracts": "only files whose source metadata says PDF/user-provided real data or explicit assumptions",
            "omitted_virtual_files": ["signaling_blocks.csv"],
            "preserved_derived_files": [
                name for name in PRESERVED_DERIVED_FILES if (OUTPUT_DIR / name).exists()
            ],
        }
        write_json(OUTPUT_DIR / "build_summary.json", summary)
        (OUTPUT_DIR / "DATASET_README.md").write_text(
        "\n".join(
            [
                "# 朔黄线真实数据集",
                "",
                "本目录由 `tools/build_real_shuohuang_dataset.py` 生成，作为当前算法主线默认输入。",
                "",
                "## 已导入的真实数据",
                "",
                "- `stations.csv`：仅含线路图1/2/3覆盖的朔黄主线真实站点，终点为黄骅港 K583+003。",
                f"- `gradients.csv`：来自 `{source_label}/geometry/gradients.xlsx`。",
                f"- `curves.csv`：来自 `{source_label}/geometry/curves.xlsx`。",
                "- `segments.csv`：由真实坡度、平曲线和限速信息合成，替代旧虚拟线路几何。",
                f"- `power_arm_intervals.csv`：来自 `{source_label}/power_arm/power_arm_continuous_intervals.xlsx`。",
                "- `stations.csv`、`headway_constraints.csv`、`technical_operation_times.csv`：来自此前 PDF 真实资料整理结果。",
                "- `train_formation_modes_2025.csv`：来自 2025 朔黄铁路编组模式资料。",
                "- `smart_meter_calibration_samples.csv`：由 `smart_meter_calibration_builder.py` 生成；如重建本目录后需要重新运行该脚本。",
                "- `energy_calibration_factors.json`：由 `energy_calibration_factor_builder.py` 生成；如重建本目录后需要重新运行该脚本。",
                "",
                "## 已接入的储能与柔性供电资料",
                "",
                "- `battery.json`：储能容量 145 kWh、往返效率 0.90、最大充电功率 2 MW、电价 0.6818 元/kWh、折旧成本 0.326 元/kWh来自已提供资料；最大放电功率、站址和接入供电臂仍缺失。",
                "- `energy_transfer_zones.csv`：K108-K219 为已实施柔性供电协同区间并进入运行基线；K16-K139 为规划区间，不进入当前运行基线；两者最大传输功率均为 12 MW、效率为 0.95。",
                "- `power_arm_intervals.csv`：K145-K164、K164-K200.7 储能可用标记仍是朔黄线规划假设，不代表已确认储能站址；该标记不会再按相同公里标映射到其他线路。",
                "",
                "## 仍使用的工程预设",
                "",
                "- `trains.csv`：质量来自编组资料；牵引/制动/Davis/功率为工程虚拟预设。",
                "- `data_templates/running_diagram_template.xlsx`：基于真实主线站点的虚拟运行图（时刻/停点为预设）。",
                "",
                "## 明确未使用",
                "",
                "- 未复制 `signaling_blocks.csv`：暂无真实闭塞分区数据。",
                "",
                "## 仍为假设或待确认",
                "",
                "- `battery.json` 仅部分字段为真实参数；最大放电功率、站址和接入供电臂仍待正式资料。`trains.csv` 的动力学参数和运行图模板仍含工程预设。",
                "- `power_arm_intervals.csv` 中供电臂最大牵引供电能力、最大再生吸收能力、回馈限制暂采用较大默认值，不作为当前原型瓶颈；后续有真实资料后替换。",
                "- 朔黄上下行供电相互隔离，当前算法默认不计算直发直用；再生能量仅可在标记为储能可用的区段进入储能后利用。",
                "- 当前储能可用区段仅在朔黄线按 K145-K164、K164-K200.7 两段规划假设标记；其他线路明确不继承该公里标假设，后续统一按正式储能站址和接入供电臂资料替换。",
                "- 当前只建模朔黄线 K0-K583.003；神朔 SK、准池K 等接入线边界暂作为模型边界外记录，不参与运行模拟区间生成。",
                "- 未标明线路名的 K、黄K/朔黄K 是否属于同一朔黄线连续里程体系仍需确认。",
                "- `smart_meter_calibration_samples.csv` 的电量单位已按供应商答复按 kWh 理解；当前样本覆盖有限，仅用于原型对比，不作为最终工程校准。",
                "- `energy_calibration_factors.json` 只用于对比和敏感性测试，不应作为最终工程 kWh 校准结论。",
                "- 正式运行图仍需确认后才能做正式业务验证。",
                "",
            ]
        ),
        encoding="utf-8",
    )
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(staging_dir), target_dir)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        OUTPUT_DIR = DEFAULT_OUTPUT_DIR
        SOURCE_DIR = DEFAULT_SOURCE_DIR


if __name__ == "__main__":
    main()
