# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence
import argparse
import bisect
import csv
import json
import math
import re
from datetime import datetime

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None


DEFAULT_SMART_METER_DIR = Path("data") / "source" / "smart_meter"
DEFAULT_OUTPUT_DIR = Path("outputs") / "smart_meter_time_matching"
INTERVAL_PATTERNS = ("nhtj_jkfile_station_*.csv", "nhtj_jkfile_ammeter_info_*.csv")
REALTIME_PATTERNS = ("SS4-*.xlsx",)


@dataclass(frozen=True)
class IntervalRecord:
    """类 IntervalRecord：执行该模块中的相关处理逻辑。"""
    source_file: str
    source_row: int
    source_table: str
    guid: str
    trainid: str
    normalized_trainid: str
    starttime: datetime
    endtime: datetime
    start_station: str
    end_station: str
    use_ygdn: Optional[float]
    use_fkdn: Optional[float]
    start_ygdn: Optional[float]
    end_ygdn: Optional[float]
    start_fkdn: Optional[float]
    end_fkdn: Optional[float]


@dataclass(frozen=True)
class IntervalOverlap:
    """类 IntervalOverlap：执行该模块中的相关处理逻辑。"""
    trainid: str
    normalized_trainid: str
    left_source_file: str
    left_source_row: int
    left_starttime: datetime
    left_endtime: datetime
    right_source_file: str
    right_source_row: int
    right_starttime: datetime
    right_endtime: datetime


class IntervalOverlapError(RuntimeError):
    """Raised when station interval tasks overlap and must be excluded from calibration."""

    def __init__(self, overlaps: Sequence[IntervalOverlap]) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        self.overlaps = list(overlaps)
        examples = "; ".join(
            (
                f"trainid={item.trainid}, "
                f"{item.left_source_file}:{item.left_source_row} "
                f"{_fmt_time(item.left_starttime)}-{_fmt_time(item.left_endtime)} overlaps "
                f"{item.right_source_file}:{item.right_source_row} "
                f"{_fmt_time(item.right_starttime)}-{_fmt_time(item.right_endtime)}"
            )
            for item in self.overlaps[:5]
        )
        suffix = "" if len(self.overlaps) <= 5 else f"; ... total={len(self.overlaps)}"
        super().__init__(
            "nhtj_jkfile_station 中同一 trainid 存在重叠任务。"
            "按当前数据规则，相关的智能电表匹配与校准数据全部不得使用。 "
            + examples
            + suffix
        )


@dataclass(frozen=True)
class RealtimePoint:
    """类 RealtimePoint：执行该模块中的相关处理逻辑。"""
    source_file: str
    source_row: int
    trainid: str
    normalized_trainid: str
    recordtime: datetime
    ygdn: Optional[float]
    fk_dn: Optional[float]
    ammeterid: str


@dataclass(frozen=True)
class MatchRow:
    """类 MatchRow：执行该模块中的相关处理逻辑。"""
    interval_source_file: str
    interval_source_row: int
    interval_source_table: str
    guid: str
    station_trainid: str
    normalized_trainid: str
    station_starttime: str
    station_endtime: str
    start_station: str
    end_station: str
    station_use_ygdn: Optional[float]
    station_use_fkdn: Optional[float]
    station_delta_ygdn: Optional[float]
    station_delta_fkdn: Optional[float]
    realtime_source_file: str
    realtime_trainid: str
    start_realtime_row: str
    end_realtime_row: str
    start_recordtime: str
    end_recordtime: str
    start_ygdn: Optional[float]
    end_ygdn: Optional[float]
    start_fk_dn: Optional[float]
    end_fk_dn: Optional[float]
    matched_use_ygdn: Optional[float]
    matched_use_fkdn: Optional[float]
    ygdn_diff: Optional[float]
    fkdn_diff: Optional[float]
    start_time_gap_s: Optional[float]
    end_time_gap_s: Optional[float]
    point_count_in_window: int
    candidate_exact_trainid_count: int
    match_status: str
    match_quality: str
    notes: str


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
    return value_float if math.isfinite(value_float) else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    """函数 _parse_datetime：执行该模块中的相关处理逻辑。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = _clean(value)
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _fmt_time(value: Optional[datetime]) -> str:
    """函数 _fmt_time：执行该模块中的相关处理逻辑。"""
    return "" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def normalize_trainid(value: Any) -> str:
    """函数 normalize_trainid：执行该模块中的相关处理逻辑。"""
    text = _clean(value).upper()
    match = re.match(r"(\d+)", text)
    return match.group(1) if match else text


def _read_csv_rows(path: Path, max_rows: Optional[int] = None) -> Iterable[tuple[int, Dict[str, str]]]:
    """函数 _read_csv_rows：执行该模块中的相关处理逻辑。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for idx, (row_number, row) in enumerate(enumerate(csv.DictReader(handle), start=2)):
            if max_rows is not None and idx >= max_rows:
                break
            yield row_number, row


def _read_xlsx_rows(path: Path, max_rows: Optional[int] = None) -> Iterable[tuple[int, Dict[str, Any]]]:
    """函数 _read_xlsx_rows：执行该模块中的相关处理逻辑。"""
    if load_workbook is None:
        raise RuntimeError("openpyxl is required to read SS4 realtime xlsx files.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        headers = [_clean(cell.value).lower() for cell in sheet[1]]
        count = 0
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if max_rows is not None and count >= max_rows:
                break
            row = {headers[idx]: value for idx, value in enumerate(values) if idx < len(headers)}
            if any(_clean(value) for value in row.values()):
                count += 1
                yield row_number, row
    finally:
        workbook.close()


def source_table_name(path: Path) -> str:
    """函数 source_table_name：执行该模块中的相关处理逻辑。"""
    name = path.name.lower()
    if "station" in name:
        return "nhtj_jkfile_station"
    if "ammeter_info" in name:
        return "nhtj_jkfile_ammeter_info"
    return path.stem


def load_interval_records(
    source_dir: Path,
    max_rows_per_file: Optional[int] = None,
    normalized_trainid_filter: Optional[set[str]] = None,
    source_table_filter: Optional[set[str]] = None,
) -> list[IntervalRecord]:
    """函数 load_interval_records：执行该模块中的相关处理逻辑。"""
    records: list[IntervalRecord] = []
    files: list[Path] = []
    for pattern in INTERVAL_PATTERNS:
        files.extend(source_dir.glob(pattern))
    for path in sorted(files):
        table = source_table_name(path)
        if source_table_filter is not None and table not in source_table_filter:
            continue
        for row_number, row in _read_csv_rows(path, max_rows=max_rows_per_file):
            starttime = _parse_datetime(row.get("starttime"))
            endtime = _parse_datetime(row.get("endtime"))
            trainid = _clean(row.get("trainid"))
            if starttime is None or endtime is None or not trainid:
                continue
            normalized_trainid = normalize_trainid(trainid)
            if normalized_trainid_filter is not None and normalized_trainid not in normalized_trainid_filter:
                continue
            records.append(
                IntervalRecord(
                    source_file=path.name,
                    source_row=row_number,
                    source_table=table,
                    guid=_clean(row.get("guid")),
                    trainid=trainid,
                    normalized_trainid=normalized_trainid,
                    starttime=starttime,
                    endtime=endtime,
                    start_station=_clean(row.get("start_station")),
                    end_station=_clean(row.get("end_station")),
                    use_ygdn=_optional_float(row.get("use_ygdn")),
                    use_fkdn=_optional_float(row.get("use_fkdn")),
                    start_ygdn=_optional_float(row.get("start_ygdn")),
                    end_ygdn=_optional_float(row.get("end_ygdn")),
                    start_fkdn=_optional_float(row.get("start_fkdn")),
                    end_fkdn=_optional_float(row.get("end_fkdn")),
                )
            )
    return records



def find_station_interval_overlaps_from_dir(
    source_dir: Path,
    *,
    max_rows_per_file: Optional[int] = None,
) -> list[IntervalOverlap]:
    """Stream station-interval CSVs and detect same-trainid time overlaps.

    This avoids loading ammeter_info and avoids materializing full IntervalRecord
    objects for every station row, which previously made validate-data look hung
    on the ~200MB station meter export.
    """
    files: list[Path] = []
    for pattern in ("nhtj_jkfile_station_*.csv",):
        files.extend(Path(source_dir).glob(pattern))
    by_trainid: dict[str, list[tuple[datetime, datetime, str, int, str]]] = {}
    for path in sorted(files):
        for row_number, row in _read_csv_rows(path, max_rows=max_rows_per_file):
            starttime = _parse_datetime(row.get("starttime"))
            endtime = _parse_datetime(row.get("endtime"))
            trainid = _clean(row.get("trainid"))
            if starttime is None or endtime is None or not trainid:
                continue
            if endtime <= starttime:
                continue
            normalized = normalize_trainid(trainid)
            by_trainid.setdefault(normalized, []).append(
                (starttime, endtime, path.name, row_number, trainid)
            )

    overlaps: list[IntervalOverlap] = []
    for normalized_trainid, items in by_trainid.items():
        ordered = sorted(items, key=lambda item: (item[0], item[1], item[2], item[3]))
        previous = None
        for current in ordered:
            if previous is not None and current[0] < previous[1]:
                overlaps.append(
                    IntervalOverlap(
                        trainid=current[4],
                        normalized_trainid=normalized_trainid,
                        left_source_file=previous[2],
                        left_source_row=previous[3],
                        left_starttime=previous[0],
                        left_endtime=previous[1],
                        right_source_file=current[2],
                        right_source_row=current[3],
                        right_starttime=current[0],
                        right_endtime=current[1],
                    )
                )
                if current[1] <= previous[1]:
                    continue
            previous = current
    return overlaps


def find_station_interval_overlaps(intervals: Sequence[IntervalRecord]) -> list[IntervalOverlap]:
    """函数 find_station_interval_overlaps：执行该模块中的相关处理逻辑。"""
    by_trainid: dict[str, list[IntervalRecord]] = {}
    for interval in intervals:
        if interval.source_table != "nhtj_jkfile_station":
            continue
        by_trainid.setdefault(interval.normalized_trainid, []).append(interval)

    overlaps: list[IntervalOverlap] = []
    for normalized_trainid, items in by_trainid.items():
        ordered = sorted(items, key=lambda item: (item.starttime, item.endtime, item.source_file, item.source_row))
        previous: Optional[IntervalRecord] = None
        for current in ordered:
            if previous is not None and current.starttime < previous.endtime:
                overlaps.append(
                    IntervalOverlap(
                        trainid=current.trainid,
                        normalized_trainid=normalized_trainid,
                        left_source_file=previous.source_file,
                        left_source_row=previous.source_row,
                        left_starttime=previous.starttime,
                        left_endtime=previous.endtime,
                        right_source_file=current.source_file,
                        right_source_row=current.source_row,
                        right_starttime=current.starttime,
                        right_endtime=current.endtime,
                    )
                )
                if current.endtime <= previous.endtime:
                    continue
            previous = current
    return overlaps


def ensure_no_station_interval_overlaps(intervals: Sequence[IntervalRecord]) -> None:
    """函数 ensure_no_station_interval_overlaps：执行该模块中的相关处理逻辑。"""
    overlaps = find_station_interval_overlaps(intervals)
    if overlaps:
        raise IntervalOverlapError(overlaps)


def overlap_interval_keys(overlaps: Sequence[IntervalOverlap]) -> set[tuple[str, int]]:
    """函数 overlap_interval_keys：执行该模块中的相关处理逻辑。"""
    keys: set[tuple[str, int]] = set()
    for overlap in overlaps:
        keys.add((overlap.left_source_file, overlap.left_source_row))
        keys.add((overlap.right_source_file, overlap.right_source_row))
    return keys


def exclude_overlapping_station_intervals(intervals: Sequence[IntervalRecord]) -> tuple[list[IntervalRecord], list[IntervalOverlap]]:
    """函数 exclude_overlapping_station_intervals：执行该模块中的相关处理逻辑。"""
    overlaps = find_station_interval_overlaps(intervals)
    if not overlaps:
        return list(intervals), []
    excluded = overlap_interval_keys(overlaps)
    filtered = [
        interval
        for interval in intervals
        if interval.source_table != "nhtj_jkfile_station" or (interval.source_file, interval.source_row) not in excluded
    ]
    return filtered, overlaps


def load_realtime_points(source_dir: Path, max_rows_per_file: Optional[int] = None) -> list[RealtimePoint]:
    """函数 load_realtime_points：执行该模块中的相关处理逻辑。"""
    points: list[RealtimePoint] = []
    files: list[Path] = []
    for pattern in REALTIME_PATTERNS:
        files.extend(source_dir.glob(pattern))
    for path in sorted(files):
        for row_number, row in _read_xlsx_rows(path, max_rows=max_rows_per_file):
            trainid = _clean(row.get("trainid"))
            recordtime = _parse_datetime(row.get("recordtime"))
            if not trainid or recordtime is None:
                continue
            points.append(
                RealtimePoint(
                    source_file=path.name,
                    source_row=row_number,
                    trainid=trainid,
                    normalized_trainid=normalize_trainid(trainid),
                    recordtime=recordtime,
                    ygdn=_optional_float(row.get("ygdn")),
                    fk_dn=_optional_float(row.get("fk_dn")),
                    ammeterid=_clean(row.get("ammeterid")),
                )
            )
    return points


def build_realtime_index(points: Sequence[RealtimePoint]) -> dict[str, dict[str, list[RealtimePoint]]]:
    """函数 build_realtime_index：执行该模块中的相关处理逻辑。"""
    index: dict[str, dict[str, list[RealtimePoint]]] = {}
    for point in points:
        exact_bucket = index.setdefault(point.normalized_trainid, {}).setdefault(point.trainid, [])
        exact_bucket.append(point)
    for exact_groups in index.values():
        for items in exact_groups.values():
            items.sort(key=lambda item: item.recordtime)
    return index


def nearest_point(points: Sequence[RealtimePoint], target: datetime) -> Optional[RealtimePoint]:
    """函数 nearest_point：执行该模块中的相关处理逻辑。"""
    if not points:
        return None
    times = [point.recordtime for point in points]
    idx = bisect.bisect_left(times, target)
    candidates = []
    if idx < len(points):
        candidates.append(points[idx])
    if idx > 0:
        candidates.append(points[idx - 1])
    return min(candidates, key=lambda point: abs((point.recordtime - target).total_seconds())) if candidates else None


def count_points_in_window(points: Sequence[RealtimePoint], start: datetime, end: datetime) -> int:
    """函数 count_points_in_window：执行该模块中的相关处理逻辑。"""
    times = [point.recordtime for point in points]
    left = bisect.bisect_left(times, start)
    right = bisect.bisect_right(times, end)
    return max(0, right - left)


def _delta(end_value: Optional[float], start_value: Optional[float]) -> Optional[float]:
    """函数 _delta：执行该模块中的相关处理逻辑。"""
    return None if end_value is None or start_value is None else end_value - start_value


def _abs_diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
    """函数 _abs_diff：执行该模块中的相关处理逻辑。"""
    return None if left is None or right is None else abs(left - right)


def match_interval(
    interval: IntervalRecord,
    realtime_index: dict[str, dict[str, list[RealtimePoint]]],
    *,
    boundary_tolerance_s: float,
    energy_tolerance: float,
) -> MatchRow:
    """函数 match_interval：执行该模块中的相关处理逻辑。"""
    exact_groups = realtime_index.get(interval.normalized_trainid, {})
    station_delta_ygdn = _delta(interval.end_ygdn, interval.start_ygdn)
    station_delta_fkdn = _delta(interval.end_fkdn, interval.start_fkdn)
    if not exact_groups:
        return _empty_match(interval, "no_realtime_points", "none", "No SS4 realtime points with matching normalized trainid.")

    candidates: list[tuple[tuple[float, float, float], MatchRow]] = []
    for exact_trainid, points in exact_groups.items():
        start_point = nearest_point(points, interval.starttime)
        end_point = nearest_point(points, interval.endtime)
        if start_point is None or end_point is None:
            continue
        matched_ygdn = _delta(end_point.ygdn, start_point.ygdn)
        matched_fkdn = _delta(end_point.fk_dn, start_point.fk_dn)
        ygdn_diff = _abs_diff(matched_ygdn, interval.use_ygdn)
        fkdn_diff = _abs_diff(matched_fkdn, interval.use_fkdn)
        start_gap = abs((start_point.recordtime - interval.starttime).total_seconds())
        end_gap = abs((end_point.recordtime - interval.endtime).total_seconds())
        point_count = count_points_in_window(points, interval.starttime, interval.endtime)
        energy_diff_score = (ygdn_diff if ygdn_diff is not None else 1e18) + (fkdn_diff if fkdn_diff is not None else 1e18)
        time_gap_score = start_gap + end_gap
        window_penalty = 0.0 if point_count > 0 else 1.0
        status, quality, notes = classify_match(
            point_count,
            start_gap,
            end_gap,
            ygdn_diff,
            fkdn_diff,
            boundary_tolerance_s,
            energy_tolerance,
        )
        row = MatchRow(
            interval_source_file=interval.source_file,
            interval_source_row=interval.source_row,
            interval_source_table=interval.source_table,
            guid=interval.guid,
            station_trainid=interval.trainid,
            normalized_trainid=interval.normalized_trainid,
            station_starttime=_fmt_time(interval.starttime),
            station_endtime=_fmt_time(interval.endtime),
            start_station=interval.start_station,
            end_station=interval.end_station,
            station_use_ygdn=interval.use_ygdn,
            station_use_fkdn=interval.use_fkdn,
            station_delta_ygdn=station_delta_ygdn,
            station_delta_fkdn=station_delta_fkdn,
            realtime_source_file=start_point.source_file if start_point.source_file == end_point.source_file else f"{start_point.source_file};{end_point.source_file}",
            realtime_trainid=exact_trainid,
            start_realtime_row=str(start_point.source_row),
            end_realtime_row=str(end_point.source_row),
            start_recordtime=_fmt_time(start_point.recordtime),
            end_recordtime=_fmt_time(end_point.recordtime),
            start_ygdn=start_point.ygdn,
            end_ygdn=end_point.ygdn,
            start_fk_dn=start_point.fk_dn,
            end_fk_dn=end_point.fk_dn,
            matched_use_ygdn=matched_ygdn,
            matched_use_fkdn=matched_fkdn,
            ygdn_diff=ygdn_diff,
            fkdn_diff=fkdn_diff,
            start_time_gap_s=start_gap,
            end_time_gap_s=end_gap,
            point_count_in_window=point_count,
            candidate_exact_trainid_count=len(exact_groups),
            match_status=status,
            match_quality=quality,
            notes=notes,
        )
        candidates.append(((window_penalty, energy_diff_score, time_gap_score), row))

    aggregate_candidate = build_aggregate_candidate(
        interval,
        exact_groups,
        station_delta_ygdn,
        station_delta_fkdn,
        boundary_tolerance_s,
        energy_tolerance,
    )
    if aggregate_candidate is not None:
        sort_key, row = aggregate_candidate
        candidates.append((sort_key, row))

    if not candidates:
        return _empty_match(interval, "no_boundary_candidate", "none", "Realtime trainid exists, but no boundary candidate was available.")
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def build_aggregate_candidate(
    interval: IntervalRecord,
    exact_groups: dict[str, list[RealtimePoint]],
    station_delta_ygdn: Optional[float],
    station_delta_fkdn: Optional[float],
    boundary_tolerance_s: float,
    energy_tolerance: float,
) -> Optional[tuple[tuple[float, float, float], MatchRow]]:
    """函数 build_aggregate_candidate：执行该模块中的相关处理逻辑。"""
    if len(exact_groups) <= 1:
        return None
    start_points: list[RealtimePoint] = []
    end_points: list[RealtimePoint] = []
    point_count = 0
    for points in exact_groups.values():
        start_point = nearest_point(points, interval.starttime)
        end_point = nearest_point(points, interval.endtime)
        if start_point is None or end_point is None:
            return None
        start_points.append(start_point)
        end_points.append(end_point)
        point_count += count_points_in_window(points, interval.starttime, interval.endtime)

    start_ygdn = _sum_values(point.ygdn for point in start_points)
    end_ygdn = _sum_values(point.ygdn for point in end_points)
    start_fk_dn = _sum_values(point.fk_dn for point in start_points)
    end_fk_dn = _sum_values(point.fk_dn for point in end_points)
    matched_ygdn = _delta(end_ygdn, start_ygdn)
    matched_fkdn = _delta(end_fk_dn, start_fk_dn)
    ygdn_diff = _abs_diff(matched_ygdn, interval.use_ygdn)
    fkdn_diff = _abs_diff(matched_fkdn, interval.use_fkdn)
    start_gap = max(abs((point.recordtime - interval.starttime).total_seconds()) for point in start_points)
    end_gap = max(abs((point.recordtime - interval.endtime).total_seconds()) for point in end_points)
    energy_diff_score = (ygdn_diff if ygdn_diff is not None else 1e18) + (fkdn_diff if fkdn_diff is not None else 1e18)
    time_gap_score = start_gap + end_gap
    window_penalty = 0.0 if point_count > 0 else 1.0
    status, quality, notes = classify_match(
        point_count,
        start_gap,
        end_gap,
        ygdn_diff,
        fkdn_diff,
        boundary_tolerance_s,
        energy_tolerance,
    )
    aggregate_trainid = "+".join(sorted(exact_groups))
    source_files = sorted({point.source_file for point in start_points + end_points})
    row = MatchRow(
        interval_source_file=interval.source_file,
        interval_source_row=interval.source_row,
        interval_source_table=interval.source_table,
        guid=interval.guid,
        station_trainid=interval.trainid,
        normalized_trainid=interval.normalized_trainid,
        station_starttime=_fmt_time(interval.starttime),
        station_endtime=_fmt_time(interval.endtime),
        start_station=interval.start_station,
        end_station=interval.end_station,
        station_use_ygdn=interval.use_ygdn,
        station_use_fkdn=interval.use_fkdn,
        station_delta_ygdn=station_delta_ygdn,
        station_delta_fkdn=station_delta_fkdn,
        realtime_source_file=";".join(source_files),
        realtime_trainid=aggregate_trainid,
        start_realtime_row="+".join(str(point.source_row) for point in start_points),
        end_realtime_row="+".join(str(point.source_row) for point in end_points),
        start_recordtime=";".join(_fmt_time(point.recordtime) for point in start_points),
        end_recordtime=";".join(_fmt_time(point.recordtime) for point in end_points),
        start_ygdn=start_ygdn,
        end_ygdn=end_ygdn,
        start_fk_dn=start_fk_dn,
        end_fk_dn=end_fk_dn,
        matched_use_ygdn=matched_ygdn,
        matched_use_fkdn=matched_fkdn,
        ygdn_diff=ygdn_diff,
        fkdn_diff=fkdn_diff,
        start_time_gap_s=start_gap,
        end_time_gap_s=end_gap,
        point_count_in_window=point_count,
        candidate_exact_trainid_count=len(exact_groups),
        match_status=status,
        match_quality=quality,
        notes=f"{notes} Aggregated realtime trainids: {aggregate_trainid}.",
    )
    return (window_penalty, energy_diff_score, time_gap_score), row


def _sum_values(values: Iterable[Optional[float]]) -> Optional[float]:
    """函数 _sum_values：执行该模块中的相关处理逻辑。"""
    items = list(values)
    if any(value is None for value in items):
        return None
    return sum(float(value) for value in items)


def classify_match(
    point_count: int,
    start_gap: float,
    end_gap: float,
    ygdn_diff: Optional[float],
    fkdn_diff: Optional[float],
    boundary_tolerance_s: float,
    energy_tolerance: float,
) -> tuple[str, str, str]:
    """函数 classify_match：执行该模块中的相关处理逻辑。"""
    boundary_ok = start_gap <= boundary_tolerance_s and end_gap <= boundary_tolerance_s
    energy_values_available = ygdn_diff is not None and fkdn_diff is not None
    energy_ok = energy_values_available and ygdn_diff <= energy_tolerance and fkdn_diff <= energy_tolerance
    if point_count <= 0:
        return "matched_nearest_boundary_no_points_inside_window", "low", "Boundary points were selected by nearest time, but no realtime point falls inside interval."
    if boundary_ok and energy_ok:
        return "matched_energy_consistent", "high", "Realtime boundary delta matches station use energy within tolerance."
    if boundary_ok and not energy_ok:
        return "matched_energy_mismatch", "medium", "Boundary times are close, but realtime delta differs from station use energy."
    if energy_ok:
        return "matched_energy_consistent_boundary_gap_large", "medium", "Energy delta matches, but one or both boundary time gaps exceed tolerance."
    return "matched_nearest_boundary", "low", "Nearest boundary points found; energy and/or boundary tolerance not fully satisfied."


def _empty_match(interval: IntervalRecord, status: str, quality: str, notes: str) -> MatchRow:
    """函数 _empty_match：执行该模块中的相关处理逻辑。"""
    station_delta_ygdn = _delta(interval.end_ygdn, interval.start_ygdn)
    station_delta_fkdn = _delta(interval.end_fkdn, interval.start_fkdn)
    return MatchRow(
        interval_source_file=interval.source_file,
        interval_source_row=interval.source_row,
        interval_source_table=interval.source_table,
        guid=interval.guid,
        station_trainid=interval.trainid,
        normalized_trainid=interval.normalized_trainid,
        station_starttime=_fmt_time(interval.starttime),
        station_endtime=_fmt_time(interval.endtime),
        start_station=interval.start_station,
        end_station=interval.end_station,
        station_use_ygdn=interval.use_ygdn,
        station_use_fkdn=interval.use_fkdn,
        station_delta_ygdn=station_delta_ygdn,
        station_delta_fkdn=station_delta_fkdn,
        realtime_source_file="",
        realtime_trainid="",
        start_realtime_row="",
        end_realtime_row="",
        start_recordtime="",
        end_recordtime="",
        start_ygdn=None,
        end_ygdn=None,
        start_fk_dn=None,
        end_fk_dn=None,
        matched_use_ygdn=None,
        matched_use_fkdn=None,
        ygdn_diff=None,
        fkdn_diff=None,
        start_time_gap_s=None,
        end_time_gap_s=None,
        point_count_in_window=0,
        candidate_exact_trainid_count=0,
        match_status=status,
        match_quality=quality,
        notes=notes,
    )


def realtime_coverage_by_trainid(
    realtime_index: dict[str, dict[str, list[RealtimePoint]]],
) -> dict[str, tuple[datetime, datetime]]:
    """函数 realtime_coverage_by_trainid：执行该模块中的相关处理逻辑。"""
    coverage: dict[str, tuple[datetime, datetime]] = {}
    for normalized_trainid, exact_groups in realtime_index.items():
        times: list[datetime] = []
        for points in exact_groups.values():
            times.extend(point.recordtime for point in points)
        if times:
            coverage[normalized_trainid] = (min(times), max(times))
    return coverage


def filter_intervals_overlapping_realtime_coverage(
    intervals: Sequence[IntervalRecord],
    coverage: dict[str, tuple[datetime, datetime]],
) -> list[IntervalRecord]:
    """函数 filter_intervals_overlapping_realtime_coverage：执行该模块中的相关处理逻辑。"""
    filtered: list[IntervalRecord] = []
    for interval in intervals:
        window = coverage.get(interval.normalized_trainid)
        if window is None:
            continue
        start, end = window
        if interval.endtime < start or interval.starttime > end:
            continue
        filtered.append(interval)
    return filtered


def match_smart_meter_time_windows(
    source_dir: Path,
    *,
    boundary_tolerance_s: float = 120.0,
    energy_tolerance: float = 1.0,
    max_interval_rows_per_file: Optional[int] = None,
    max_realtime_rows_per_file: Optional[int] = None,
    overlap_policy: str = "exclude",
    restrict_to_realtime_coverage: bool = True,
) -> list[MatchRow]:
    """函数 match_smart_meter_time_windows：执行该模块中的相关处理逻辑。"""
    realtime_points = load_realtime_points(source_dir, max_rows_per_file=max_realtime_rows_per_file)
    realtime_index = build_realtime_index(realtime_points)
    realtime_trainids = set(realtime_index)
    intervals = load_interval_records(
        source_dir,
        max_rows_per_file=max_interval_rows_per_file,
        normalized_trainid_filter=realtime_trainids,
    )
    if restrict_to_realtime_coverage:
        coverage = realtime_coverage_by_trainid(realtime_index)
        intervals = filter_intervals_overlapping_realtime_coverage(intervals, coverage)
    if overlap_policy == "strict":
        ensure_no_station_interval_overlaps(intervals)
    elif overlap_policy == "exclude":
        intervals, _overlaps = exclude_overlapping_station_intervals(intervals)
    else:
        raise ValueError("overlap_policy must be 'strict' or 'exclude'.")
    return [
        match_interval(
            interval,
            realtime_index,
            boundary_tolerance_s=boundary_tolerance_s,
            energy_tolerance=energy_tolerance,
        )
        for interval in intervals
    ]


def write_match_outputs(rows: Sequence[MatchRow], output_dir: Path) -> None:
    """函数 write_match_outputs：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "smart_meter_time_window_matches.csv"
    fieldnames = list(MatchRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    by_status: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    for row in rows:
        by_status[row.match_status] = by_status.get(row.match_status, 0) + 1
        by_quality[row.match_quality] = by_quality.get(row.match_quality, 0) + 1
    summary = {
        "match_count": len(rows),
        "status_counts": dict(sorted(by_status.items())),
        "quality_counts": dict(sorted(by_quality.items())),
        "output_csv": str(csv_path),
    }
    (output_dir / "smart_meter_time_window_matching_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Match station/ammeter interval records to SS4 realtime meter points by trainid and time window.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_SMART_METER_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--boundary-tolerance-s", type=float, default=120.0)
    parser.add_argument("--energy-tolerance", type=float, default=1.0)
    parser.add_argument("--max-interval-rows-per-file", type=int)
    parser.add_argument("--max-realtime-rows-per-file", type=int)
    parser.add_argument(
        "--overlap-policy",
        choices=("strict", "exclude"),
        default="exclude",
        help="strict rejects overlapping station intervals; exclude drops overlapped station rows and matches the remaining clean intervals.",
    )
    parser.add_argument(
        "--no-restrict-to-realtime-coverage",
        action="store_true",
        help="Match all intervals for realtime trainids, including those outside SS4 coverage windows.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    rows = match_smart_meter_time_windows(
        args.input_dir,
        boundary_tolerance_s=args.boundary_tolerance_s,
        energy_tolerance=args.energy_tolerance,
        max_interval_rows_per_file=args.max_interval_rows_per_file,
        max_realtime_rows_per_file=args.max_realtime_rows_per_file,
        overlap_policy=args.overlap_policy,
        restrict_to_realtime_coverage=not args.no_restrict_to_realtime_coverage,
    )
    write_match_outputs(rows, args.output_dir)
    print(f"Matched interval records: {len(rows)}")
    print(f"Output directory: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
