# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence
import argparse
import sys

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from power_arm_electrical_limits import electrical_limit_fields, storage_fields_for_interval


SOURCE = Path("data") / "source" / "power_arm" / "power_arm_boundaries.xlsx"
OUTPUT = Path("outputs") / "power_arm_generation" / "power_arm_continuous_intervals.xlsx"
MODEL_ROUTE_END_KM = {"朔黄线": 583.003}
IN_MODEL_MARKER_PREFIXES = {"K", "朔黄", "黄K"}
OUT_OF_MODEL_MARKER_PREFIXES = {"神朔", "准池"}


def optional_float(value):
    """函数 optional_float：执行该模块中的相关处理逻辑。"""
    if value is None or value == "":
        return None
    return float(value)


def clean(value) -> str:
    """函数 clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def marker_prefix(marker: str) -> str:
    """函数 marker_prefix：执行该模块中的相关处理逻辑。"""
    text = clean(marker)
    upper_text = text.upper()
    for prefix in ("神朔", "准池", "朔黄"):
        if prefix in text:
            return prefix
    if upper_text.startswith("SK"):
        return "神朔"
    if "黄" in text and "K" in upper_text:
        return "黄K"
    if "K" in upper_text:
        return "K"
    return "K"


def marker_scope(prefix: str) -> str:
    """函数 marker_scope：执行该模块中的相关处理逻辑。"""
    if prefix in OUT_OF_MODEL_MARKER_PREFIXES:
        return "model_out_of_scope_connection_line"
    if prefix in IN_MODEL_MARKER_PREFIXES:
        return "current_shuohuang_model"
    return "unknown"


def forward_fill_records():
    """函数 forward_fill_records：执行该模块中的相关处理逻辑。"""
    wb = openpyxl.load_workbook(SOURCE, data_only=True)
    ws = wb.active
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    rows = []
    carry = {
        "road": "",
        "traction_substation_raw": "",
        "power_supply_range_raw": "",
        "neutral_section_or_arm_raw": "",
    }
    for r in range(2, ws.max_row + 1):
        raw = {headers[col - 1]: ws.cell(r, col).value for col in range(1, ws.max_column + 1)}
        if not raw.get("record_id"):
            continue
        for key in carry:
            if raw.get(key) not in (None, ""):
                carry[key] = clean(raw.get(key))
            raw[key] = carry[key]
        raw["center_km"] = optional_float(raw.get("center_km"))
        raw["start_km"] = optional_float(raw.get("start_km"))
        raw["end_km"] = optional_float(raw.get("end_km"))
        raw["min_km"] = optional_float(raw.get("min_km"))
        raw["max_km"] = optional_float(raw.get("max_km"))
        raw["source_row"] = r
        raw["marker_prefix"] = marker_prefix(raw.get("center_phase_marker_raw"))
        raw["marker_scope"] = marker_scope(raw["marker_prefix"])
        rows.append(raw)
    return rows


def join_unique(values):
    """函数 join_unique：执行该模块中的相关处理逻辑。"""
    seen = []
    for value in values:
        text = clean(value)
        if text and text not in seen:
            seen.append(text)
    return " / ".join(seen)


def interval_row(section_no, road, direction, start, end, left, right, confidence, review_flag, note):
    """函数 interval_row：执行该模块中的相关处理逻辑。"""
    start_km = round(float(start), 6)
    end_km = round(float(end), 6)
    length_km = round(abs(end_km - start_km), 6)
    section_id = f"PAI-{section_no:03d}"
    left_id = clean(left.get("record_id")) if left else ""
    right_id = clean(right.get("record_id")) if right else ""
    left_name = clean(left.get("neutral_section_or_arm_raw")) if left else "线路起点"
    right_name = clean(right.get("neutral_section_or_arm_raw")) if right else "线路终点"
    power_arm_id = f"{road}:{direction}:{left_id or 'START'}-{right_id or 'END'}"
    return {
        "section_id": section_id,
        "road": road,
        "direction": direction,
        "start_km": start_km,
        "end_km": end_km,
        "length_km": length_km,
        "power_arm_id": power_arm_id,
        "traction_substation_raw": join_unique(
            [left.get("traction_substation_raw") if left else "", right.get("traction_substation_raw") if right else ""]
        ),
        "power_supply_range_raw": join_unique(
            [left.get("power_supply_range_raw") if left else "", right.get("power_supply_range_raw") if right else ""]
        ),
        "boundary_or_arm_raw": join_unique([left_name, right_name]),
        "source_record_ids": ";".join([v for v in [left_id, right_id] if v]),
        "left_boundary_record_id": left_id,
        "right_boundary_record_id": right_id,
        "left_center_marker_raw": clean(left.get("center_phase_marker_raw")) if left else "",
        "right_center_marker_raw": clean(right.get("center_phase_marker_raw")) if right else "",
        "left_center_km": left.get("center_km") if left else None,
        "right_center_km": right.get("center_km") if right else None,
        "confidence": confidence,
        "needs_manual_review": review_flag,
        "review_note": note,
        **electrical_limit_fields(),
        **storage_fields_for_interval(start_km, end_km),
    }


def build_intervals(records):
    """函数 build_intervals：执行该模块中的相关处理逻辑。"""
    grouped = defaultdict(list)
    for rec in records:
        center = rec.get("center_km")
        road = clean(rec.get("road"))
        direction = clean(rec.get("direction"))
        if center is None or not road or not direction:
            continue
        grouped[(road, direction)].append(rec)

    intervals = []
    section_no = 1
    for (road, direction), items in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        items = sorted(
            [rec for rec in items if rec.get("marker_scope") == "current_shuohuang_model"],
            key=lambda rec: (rec["center_km"], clean(rec["record_id"])),
        )
        if not items:
            continue

        if road in MODEL_ROUTE_END_KM and direction in ("上行", "下行"):
            first = items[0]
            intervals.append(
                interval_row(
                    section_no,
                    road,
                    direction,
                    0.0,
                    first["center_km"],
                    None,
                    first,
                    "model_edge_inferred",
                    "缺失",
                    "线路起点到首个电分相中心由模型边界外推，需确认供电臂归属。",
                )
            )
            section_no += 1

        for left, right in zip(items, items[1:]):
            length = abs(right["center_km"] - left["center_km"])
            review = "已有"
            note = "由已复核电分相中心公里标相邻生成。"
            confidence = "inferred_from_verified_boundaries"
            if left.get("marker_prefix") != right.get("marker_prefix"):
                review = "缺失"
                note += (
                    f" 相邻边界里程体系不同：{left.get('marker_prefix')} -> {right.get('marker_prefix')}，"
                    "当前纳入朔黄线模型，但需确认未标明线路名的K/黄K/朔黄K是否属于同一朔黄里程体系。"
                )
            if length > 50:
                review = "缺失"
                note += " 相邻中心间距超过50km，需重点确认是否跨线路或缺少中间边界。"
            intervals.append(interval_row(section_no, road, direction, left["center_km"], right["center_km"], left, right, confidence, review, note))
            section_no += 1

        if road in MODEL_ROUTE_END_KM and direction in ("上行", "下行"):
            last = items[-1]
            intervals.append(
                interval_row(
                    section_no,
                    road,
                    direction,
                    last["center_km"],
                    MODEL_ROUTE_END_KM[road],
                    last,
                    None,
                    "model_edge_inferred",
                    "缺失",
                    f"末个电分相中心到模型终点 {MODEL_ROUTE_END_KM[road]} km 由模型边界外推，需确认供电臂归属。",
                )
            )
            section_no += 1
    return intervals


def style_sheet(ws):
    """函数 style_sheet：执行该模块中的相关处理逻辑。"""
    header_fill = PatternFill("solid", fgColor="4F81BD")
    thin = Side(style="thin", color="D9E2F3")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows():
        for cell in row:
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        width = 10
        for cell in ws[letter]:
            width = max(width, min(len(clean(cell.value)) + 2, 42))
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"


def write_workbook(intervals, records):
    """函数 write_workbook：执行该模块中的相关处理逻辑。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "说明与统计"
    ws.append(["项目", "值"])
    ws.append(["来源文件", str(SOURCE)])
    ws.append(["输出文件", str(OUTPUT)])
    ws.append(["源边界记录数", len(records)])
    ws.append(["连续区间数", len(intervals)])
    out_of_scope_count = sum(1 for row in records if row.get("marker_scope") == "model_out_of_scope_connection_line")
    ws.append(["当前模型外接入线边界记录数", out_of_scope_count])
    ws.append(["朔黄线模型终点km", MODEL_ROUTE_END_KM["朔黄线"]])
    ws.append(
        [
            "生成规则",
            "当前只建模朔黄线K0至K583.003；K、朔黄K、黄K按当前朔黄模型内边界生成连续区间；神朔SK、准池K等接入线边界保留在源记录中，但暂不参与运行模拟区间生成。",
        ]
    )
    ws.append(["复核优先级", "先复核未标明线路名的K、黄K/朔黄K是否属于朔黄连续里程体系；神朔SK、准池K待后续扩展跨线建模时再换算。"])
    style_sheet(ws)

    headers = [
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
        "source_record_ids",
        "left_boundary_record_id",
        "right_boundary_record_id",
        "left_center_marker_raw",
        "right_center_marker_raw",
        "left_center_km",
        "right_center_km",
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
    ws2 = wb.create_sheet("供电臂连续区间表")
    ws2.append(headers)
    for rec in intervals:
        ws2.append([rec.get(header) for header in headers])
    style_sheet(ws2)

    source_headers = [
        "record_id",
        "road",
        "source_row",
        "traction_substation_raw",
        "power_supply_range_raw",
        "neutral_section_or_arm_raw",
        "direction",
        "start_phase_marker_raw",
        "center_phase_marker_raw",
        "end_phase_marker_raw",
        "start_km",
        "center_km",
        "end_km",
        "min_km",
        "max_km",
        "marker_prefix",
        "marker_scope",
    ]
    ws3 = wb.create_sheet("源边界记录")
    ws3.append(source_headers)
    for rec in records:
        ws3.append([rec.get(header) for header in source_headers])
    style_sheet(ws3)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT)


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(
        description="Generate reviewable continuous power-arm intervals from boundary records."
    )
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    global SOURCE, OUTPUT
    args = build_parser().parse_args(argv)
    SOURCE = args.source
    OUTPUT = args.output
    records = forward_fill_records()
    intervals = build_intervals(records)
    write_workbook(intervals, records)
    print(f"source_records={len(records)}")
    print(f"intervals={len(intervals)}")
    print(f"output={OUTPUT}")
    return 0


if __name__ == "__main__":
    main()
