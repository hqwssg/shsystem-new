"""上传 Excel 时按工作表检查编号重复和区间重叠。"""

from __future__ import annotations

from typing import Sequence
import re

SINGLE_ROW_SHEETS = frozenset({"线路参数", "储能参数", "回放说明", "抽样"})
MAX_MESSAGES = 20
_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
Row = tuple[int, dict[str, str]]


def conflict_report(
    workbook: str,
    sheets: Sequence[tuple[str, Sequence[str], Sequence[Row]]],
) -> str | None:
    messages: list[str] = []
    for sheet_name, columns, rows in sheets:
        if sheet_name in SINGLE_ROW_SHEETS or not rows:
            continue
        for index, (excel_row, candidate) in enumerate(rows):
            reason = _check(sheet_name, rows[:index], candidate, columns)
            if reason:
                messages.append(f"{workbook} / {sheet_name} / 第{excel_row}行：{reason}")
    if not messages:
        return None
    lines = messages[:MAX_MESSAGES]
    extra = len(messages) - len(lines)
    if extra > 0:
        lines.append(f"还有 {extra} 处冲突，请先改上面这些。")
    lines.append("这一版没有发布。")
    return "\n".join(lines)


def _text(row: dict[str, str], key: str) -> str:
    return str(row.get(key) or "").strip()


def _number(row: dict[str, str], key: str) -> float | None:
    raw = _text(row, key).replace(",", "")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _time_seconds(row: dict[str, str], key: str) -> int | None:
    raw = _text(row, key)
    match = _TIME.match(raw) if raw else None
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3) or 0)


def _same(left: str, right: str) -> bool:
    return bool(left) and left == right


def _overlap(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start < other_end and other_start < end


def _require_text(row: dict[str, str], field: str) -> str | None:
    if not _text(row, field):
        return f"「{field}」不能为空"
    return None


def _require_number(row: dict[str, str], field: str) -> str | None:
    if not _text(row, field):
        return f"「{field}」不能为空"
    if _number(row, field) is None:
        return f"「{field}」不是数字"
    return None


def _require_time(row: dict[str, str], field: str) -> str | None:
    if not _text(row, field):
        return f"「{field}」不能为空"
    if _time_seconds(row, field) is None:
        return f"「{field}」要填 HH:MM:SS"
    return None


def _duplicate(previous: Sequence[Row], candidate: dict[str, str], field: str, label: str) -> str | None:
    value = _text(candidate, field)
    for excel_row, row in previous:
        if _same(value, _text(row, field)):
            return f"与第{excel_row}行的{label}重复"
    return None


def _duplicate_key(previous: Sequence[Row], candidate: dict[str, str], fields: Sequence[str], label: str) -> str | None:
    for excel_row, row in previous:
        if all(_same(_text(candidate, field), _text(row, field)) for field in fields):
            return f"与第{excel_row}行的{label}重复"
    return None


def _mileage_overlap(previous: Sequence[Row], candidate: dict[str, str], id_field: str) -> str | None:
    start_error = _require_number(candidate, "起点km")
    if start_error:
        return start_error
    end_error = _require_number(candidate, "终点km")
    if end_error:
        return end_error
    start = _number(candidate, "起点km")
    end = _number(candidate, "终点km")
    assert start is not None and end is not None
    if start >= end:
        return "起点km必须小于终点km"
    for excel_row, row in previous:
        other_start = _number(row, "起点km")
        other_end = _number(row, "终点km")
        if other_start is None or other_end is None:
            continue
        if _overlap(start, end, other_start, other_end):
            name = _text(row, id_field)
            who = f"（{name}）" if name else ""
            return f"里程与第{excel_row}行{who}重叠"
    return None


def _check(sheet_name: str, previous: Sequence[Row], candidate: dict[str, str], columns: Sequence[str]) -> str | None:
    planning_keys = {"候选站点": ("站点编码",), "储能技术": ("技术编码",), "站点技术配置": ("站点编码", "技术编码"), "规划场景": ("场景编码",), "场景集": ("场景集编码",), "规划策略": ("策略编码",)}
    if sheet_name in planning_keys:
        keys = planning_keys[sheet_name]
        for key in keys:
            error = _require_text(candidate, key)
            if error:
                return error
        return _duplicate_key(previous, candidate, keys, "规划编码")
    if sheet_name == "车站":
        return _check_stations(previous, candidate)
    if sheet_name == "区间":
        return (
            _require_text(candidate, "区间编号")
            or _duplicate(previous, candidate, "区间编号", "区间编号")
            or _mileage_overlap(previous, candidate, "区间编号")
        )
    if sheet_name == "列车" and "车型名称" in columns:
        return _require_text(candidate, "车型名称") or _duplicate(previous, candidate, "车型名称", "车型名称")
    if sheet_name == "列车" and "列车号" in columns:
        return _require_text(candidate, "列车号") or _duplicate(previous, candidate, "列车号", "列车号")
    if sheet_name == "储能区段":
        return _check_storage_zones(previous, candidate)
    if sheet_name == "时刻表":
        return _check_stops(previous, candidate)
    if sheet_name == "元数据":
        return _require_text(candidate, "键") or _duplicate(previous, candidate, "键", "键")
    if sheet_name == "追踪间隔":
        return (
            _require_text(candidate, "线路")
            or _require_text(candidate, "适用范围")
            or _duplicate_key(previous, candidate, ("线路", "适用范围"), "线路和适用范围")
        )
    if sheet_name == "技术作业时分":
        return (
            _require_text(candidate, "车站名称")
            or _require_text(candidate, "作业类型")
            or _require_text(candidate, "辆数")
            or _duplicate_key(previous, candidate, ("车站名称", "作业类型", "辆数"), "车站、作业类型和辆数")
        )
    if sheet_name == "作业适用范围":
        return (
            _require_text(candidate, "车站名称")
            or _require_text(candidate, "车型")
            or _require_text(candidate, "方向")
            or _duplicate_key(previous, candidate, ("车站名称", "车型", "方向"), "车站、车型和方向")
        )
    if sheet_name == "供电臂":
        return _check_power_arms(previous, candidate)
    if sheet_name == "周期":
        return _require_text(candidate, "周期序号") or _duplicate(previous, candidate, "周期序号", "周期序号")
    if sheet_name == "事件":
        return _check_events(previous, candidate)
    if sheet_name == "参数区间":
        return _check_ranges(previous, candidate)
    return None


def _check_storage_zones(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    def identity(row: dict[str, str]) -> str:
        return _text(row, "设施编号") or _text(row, "储能区段编号")

    def active(row: dict[str, str]) -> bool:
        flag = _text(row, "运行基线启用").lower()
        if flag:
            return flag not in {"false", "0", "no", "否"}
        return _text(row, "实施状态").lower() not in {"planned", "规划"}

    key = identity(candidate)
    if not key:
        return "「设施编号或储能区段编号」不能为空"
    for excel_row, row in previous:
        if identity(row) == key:
            return f"与第{excel_row}行的设施编号或储能区段编号重复"
    # Planned, inactive facilities may overlap the operational baseline.
    # Still validate every interval and reject overlap between active rows.
    operational = [(excel_row, row) for excel_row, row in previous if active(row)] if active(candidate) else []
    return _mileage_overlap(operational, candidate, "设施编号" if _text(candidate, "设施编号") else "储能区段编号")


def _check_stations(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    error = (
        _require_text(candidate, "车站编号")
        or _require_text(candidate, "车站名称")
        or _require_number(candidate, "里程km")
        or _duplicate(previous, candidate, "车站编号", "车站编号")
        or _duplicate(previous, candidate, "车站名称", "车站名称")
    )
    if error:
        return error
    km = _number(candidate, "里程km")
    for excel_row, row in previous:
        if _number(row, "里程km") == km:
            return f"与第{excel_row}行的里程重复"
    return None


def _check_power_arms(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    error = (
        _require_text(candidate, "供电臂编号")
        or _require_text(candidate, "方向")
        or _duplicate(previous, candidate, "供电臂编号", "供电臂编号")
        or _require_number(candidate, "起点km")
        or _require_number(candidate, "终点km")
    )
    if error:
        return error
    start = _number(candidate, "起点km")
    end = _number(candidate, "终点km")
    assert start is not None and end is not None
    if start >= end:
        return "起点km必须小于终点km"
    direction = _text(candidate, "方向")
    for excel_row, row in previous:
        if _text(row, "方向") != direction:
            continue
        other_start = _number(row, "起点km")
        other_end = _number(row, "终点km")
        if other_start is None or other_end is None:
            continue
        if _overlap(start, end, other_start, other_end):
            return f"与第{excel_row}行同一方向的里程重叠"
    return None


def _check_events(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    error = _require_text(candidate, "周期序号") or _require_text(candidate, "事件编号")
    if error:
        return error
    for excel_row, row in previous:
        if _same(_text(candidate, "周期序号"), _text(row, "周期序号")) and _same(
            _text(candidate, "事件编号"), _text(row, "事件编号")
        ):
            return f"与第{excel_row}行在同一周期的事件编号重复"
    event_type = _text(candidate, "事件类型")
    timed = event_type in {"临时限速", "temporary_speed_restriction"} or bool(
        _text(candidate, "开始秒") or _text(candidate, "结束秒")
    )
    if not timed:
        return None
    error = (
        _require_text(candidate, "对象编号")
        or _require_number(candidate, "开始秒")
        or _require_number(candidate, "结束秒")
    )
    if error:
        return error
    start = _number(candidate, "开始秒")
    end = _number(candidate, "结束秒")
    assert start is not None and end is not None
    if start >= end:
        return "开始秒必须小于结束秒"
    object_id = _text(candidate, "对象编号")
    for excel_row, row in previous:
        if _text(row, "对象编号") != object_id:
            continue
        other_start = _number(row, "开始秒")
        other_end = _number(row, "结束秒")
        if other_start is None or other_end is None:
            continue
        if _overlap(start, end, other_start, other_end):
            return f"与第{excel_row}行同一对象的时间重叠"
    return None


def _check_ranges(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    code = _text(candidate, "参数编码")
    name = _text(candidate, "中文名称")
    if not code and not name:
        return "「参数编码或中文名称」不能为空"
    error = _require_number(candidate, "下限") or _require_number(candidate, "上限")
    if error:
        return error
    lower = _number(candidate, "下限")
    upper = _number(candidate, "上限")
    assert lower is not None and upper is not None
    if lower > upper:
        return "下限不能大于上限"
    if code:
        duplicated = _duplicate(previous, candidate, "参数编码", "参数编码")
        if duplicated:
            return duplicated
    if name:
        return _duplicate(previous, candidate, "中文名称", "中文名称")
    return None


def _check_stops(previous: Sequence[Row], candidate: dict[str, str]) -> str | None:
    error = (
        _require_text(candidate, "列车号")
        or _require_number(candidate, "顺序")
        or _require_text(candidate, "车站名称")
        or _require_time(candidate, "到达时刻")
        or _require_time(candidate, "出发时刻")
    )
    if error:
        return error
    arrival = _time_seconds(candidate, "到达时刻")
    departure = _time_seconds(candidate, "出发时刻")
    assert arrival is not None and departure is not None
    if arrival > departure:
        return "到达时刻不能晚于出发时刻"
    for excel_row, row in previous:
        if _same(_text(candidate, "列车号"), _text(row, "列车号")) and _number(row, "顺序") == _number(candidate, "顺序"):
            return f"与第{excel_row}行是同一列车的同一顺序"
        if _same(_text(candidate, "列车号"), _text(row, "列车号")) and _same(
            _text(candidate, "车站名称"), _text(row, "车站名称")
        ):
            return f"与第{excel_row}行是同一列车的同一车站"
    ordered: list[Row] = [
        (excel_row, row)
        for excel_row, row in previous
        if _text(row, "列车号") == _text(candidate, "列车号")
    ]
    ordered.append((-1, candidate))
    ordered.sort(key=lambda item: _number(item[1], "顺序") or 0)
    for index in range(1, len(ordered)):
        prev_row_no, prev_row = ordered[index - 1]
        next_row_no, next_row = ordered[index]
        prev_departure = _time_seconds(prev_row, "出发时刻")
        next_arrival = _time_seconds(next_row, "到达时刻")
        if prev_departure is None or next_arrival is None or next_arrival >= prev_departure:
            continue
        if -1 not in (prev_row_no, next_row_no):
            continue
        other = prev_row_no if next_row_no == -1 else next_row_no
        if other < 0:
            return "同一列车后一站到达早于前一站出发"
        return f"与第{other}行相比，同一列车的到发时间重叠"
    station = _text(candidate, "车站名称")
    train_id = _text(candidate, "列车号")
    for excel_row, row in previous:
        if _text(row, "车站名称") != station or _text(row, "列车号") == train_id:
            continue
        other_arrival = _time_seconds(row, "到达时刻")
        other_departure = _time_seconds(row, "出发时刻")
        if other_arrival is None or other_departure is None:
            continue
        if _overlap(arrival, departure, other_arrival, other_departure):
            return f"与第{excel_row}行在同一车站的占用时间重叠"
    return None
