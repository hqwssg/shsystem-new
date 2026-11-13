# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json

from smart_meter_time_matcher import (
    DEFAULT_SMART_METER_DIR,
    IntervalRecord,
    exclude_overlapping_station_intervals,
    load_interval_records,
    load_realtime_points,
)


DEFAULT_OUTPUT_CSV = Path("data") / "real_shuohuang" / "smart_meter_representative_interval_samples.csv"


@dataclass(frozen=True)
class RepresentativeIntervalSample:
    """类 RepresentativeIntervalSample：执行该模块中的相关处理逻辑。"""
    sample_id: str
    selection_policy: str
    interval_source_file: str
    interval_source_row: int
    interval_source_table: str
    guid: str
    trainid: str
    normalized_trainid: str
    realtime_trainid_coverage_key: str
    starttime: str
    endtime: str
    start_station: str
    end_station: str
    use_ygdn_kwh: Optional[float]
    use_fkdn_kwh: Optional[float]
    start_ygdn: Optional[float]
    end_ygdn: Optional[float]
    start_fkdn: Optional[float]
    end_fkdn: Optional[float]
    duplicate_overlap_policy: str
    calibration_role: str
    data_status: str
    notes: str


def _fmt_time(value: Any) -> str:
    """函数 _fmt_time：执行该模块中的相关处理逻辑。"""
    return "" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _interval_sort_key(interval: IntervalRecord) -> tuple[str, str, str, int]:
    """函数 _interval_sort_key：执行该模块中的相关处理逻辑。"""
    return (
        interval.normalized_trainid,
        interval.source_table,
        _fmt_time(interval.starttime),
        interval.source_row,
    )


def realtime_coverage_keys(source_dir: Path, max_realtime_rows_per_file: Optional[int]) -> tuple[set[str], dict[str, list[str]]]:
    """函数 realtime_coverage_keys：执行该模块中的相关处理逻辑。"""
    points = load_realtime_points(source_dir, max_rows_per_file=max_realtime_rows_per_file)
    exact_by_normalized: dict[str, set[str]] = {}
    for point in points:
        exact_by_normalized.setdefault(point.normalized_trainid, set()).add(point.trainid)
    return set(exact_by_normalized), {key: sorted(values) for key, values in exact_by_normalized.items()}


def select_representative_intervals(
    intervals: Sequence[IntervalRecord],
    exact_realtime_by_normalized: dict[str, list[str]],
    *,
    max_per_normalized_trainid: int,
) -> list[RepresentativeIntervalSample]:
    """函数 select_representative_intervals：执行该模块中的相关处理逻辑。"""
    selected: list[RepresentativeIntervalSample] = []
    by_trainid: dict[str, list[IntervalRecord]] = {}
    for interval in intervals:
        by_trainid.setdefault(interval.normalized_trainid, []).append(interval)

    for normalized_trainid in sorted(by_trainid):
        exact_keys = exact_realtime_by_normalized.get(normalized_trainid, [normalized_trainid])
        candidates_by_table: dict[str, list[IntervalRecord]] = {}
        for interval in by_trainid[normalized_trainid]:
            candidates_by_table.setdefault(interval.source_table, []).append(interval)
        for table_name in candidates_by_table:
            candidates_by_table[table_name] = sorted(candidates_by_table[table_name], key=_interval_sort_key)

        candidates: list[IntervalRecord] = []
        table_names = sorted(candidates_by_table)
        while len(candidates) < max_per_normalized_trainid and any(candidates_by_table.values()):
            for table_name in table_names:
                if candidates_by_table[table_name]:
                    candidates.append(candidates_by_table[table_name].pop(0))
                    if len(candidates) >= max_per_normalized_trainid:
                        break

        for interval in candidates:
            sample_index = len(selected) + 1
            selected.append(
                RepresentativeIntervalSample(
                    sample_id=f"SMR-{sample_index:06d}",
                    selection_policy="representative_by_trainid_after_excluding_overlaps",
                    interval_source_file=interval.source_file,
                    interval_source_row=interval.source_row,
                    interval_source_table=interval.source_table,
                    guid=interval.guid,
                    trainid=interval.trainid,
                    normalized_trainid=interval.normalized_trainid,
                    realtime_trainid_coverage_key="+".join(exact_keys),
                    starttime=_fmt_time(interval.starttime),
                    endtime=_fmt_time(interval.endtime),
                    start_station=interval.start_station,
                    end_station=interval.end_station,
                    use_ygdn_kwh=interval.use_ygdn,
                    use_fkdn_kwh=interval.use_fkdn,
                    start_ygdn=interval.start_ygdn,
                    end_ygdn=interval.end_ygdn,
                    start_fkdn=interval.start_fkdn,
                    end_fkdn=interval.end_fkdn,
                    duplicate_overlap_policy="overlapped_station_intervals_excluded",
                    calibration_role="algorithm_validation_representative_sample",
                    data_status="real_meter_interval_extracted_not_full_population",
                    notes="Representative sample for algorithm validation coverage; duplicate/overlapped station intervals are ignored.",
                )
            )
    return selected


def write_samples(path: Path, samples: Sequence[RepresentativeIntervalSample]) -> None:
    """函数 write_samples：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(RepresentativeIntervalSample.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            writer.writerow(asdict(sample))


def _display_path(path: Path) -> str:
    """函数 _display_path：执行该模块中的相关处理逻辑。"""
    try:
        resolved = path.resolve()
    except OSError:
        return str(path)
    try:
        if resolved.exists():
            return str(resolved)
        parent = resolved.parent
        for candidate in parent.iterdir():
            if candidate.name == resolved.name:
                return str(candidate)
    except OSError:
        pass
    return str(resolved)


def build_representative_samples(
    source_dir: Path,
    output_csv: Path,
    *,
    max_per_normalized_trainid: int = 50,
    max_realtime_rows_per_file: Optional[int] = 10000,
) -> dict[str, Any]:
    """函数 build_representative_samples：执行该模块中的相关处理逻辑。"""
    normalized_realtime_trainids, exact_by_normalized = realtime_coverage_keys(source_dir, max_realtime_rows_per_file)
    intervals = load_interval_records(source_dir, normalized_trainid_filter=normalized_realtime_trainids)
    clean_intervals, overlaps = exclude_overlapping_station_intervals(intervals)
    selected = select_representative_intervals(
        clean_intervals,
        exact_by_normalized,
        max_per_normalized_trainid=max_per_normalized_trainid,
    )
    write_samples(output_csv, selected)

    by_trainid: dict[str, int] = {}
    by_table: dict[str, int] = {}
    for sample in selected:
        by_trainid[sample.normalized_trainid] = by_trainid.get(sample.normalized_trainid, 0) + 1
        by_table[sample.interval_source_table] = by_table.get(sample.interval_source_table, 0) + 1
    summary = {
        "source_dir": _display_path(source_dir),
        "output_csv": str(output_csv),
        "selection_policy": "representative_by_trainid_after_excluding_overlaps",
        "realtime_normalized_trainid_count": len(normalized_realtime_trainids),
        "realtime_normalized_trainids": sorted(normalized_realtime_trainids),
        "exact_realtime_trainids_by_normalized": exact_by_normalized,
        "input_interval_count_for_realtime_trainids": len(intervals),
        "overlap_pair_count_for_realtime_trainids": len(overlaps),
        "clean_interval_count": len(clean_intervals),
        "sample_count": len(selected),
        "max_per_normalized_trainid": max_per_normalized_trainid,
        "sample_counts_by_normalized_trainid": dict(sorted(by_trainid.items())),
        "sample_counts_by_source_table": dict(sorted(by_table.items())),
        "note": "This table is for validation coverage, not full-population statistics. Overlapped station intervals are excluded.",
    }
    output_csv.with_name(output_csv.stem + "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Build representative smart-meter interval samples for algorithm validation coverage.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_SMART_METER_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--max-per-normalized-trainid", type=int, default=50)
    parser.add_argument("--max-realtime-rows-per-file", type=int, default=10000)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = build_representative_samples(
        args.input_dir,
        args.output_csv,
        max_per_normalized_trainid=args.max_per_normalized_trainid,
        max_realtime_rows_per_file=args.max_realtime_rows_per_file,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
