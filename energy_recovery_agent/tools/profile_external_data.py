"""Profile provider files and produce candidate field mappings without changing input files.

The profiler is deliberately schema-on-read.  It accepts common CSV/TSV, JSON and
XLSX exports, reports unsupported formats, and never promotes a guessed mapping to
an algorithm input.  A human or an explicit mapping profile must confirm ambiguous
fields before a later conversion step consumes the data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

try:  # openpyxl is already used by the repository for XLSX inputs.
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - the report records XLSX as unavailable.
    load_workbook = None


CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "train_id": ("trainid", "trainno", "trainnumber", "train", "车号", "车次", "列车号", "列车编号"),
    "sensor_id": ("sensorid", "sensorno", "deviceid", "设备号", "设备编号", "传感器号", "传感器编号"),
    "meter_id": ("meterid", "ammeterid", "electricmeterid", "电表号", "电表编号", "电能表编号"),
    "event_time": ("timestamp", "datetime", "eventtime", "recordtime", "采集时间", "记录时间", "时间", "时刻"),
    "longitude": ("longitude", "lon", "gpsx", "经度"),
    "latitude": ("latitude", "lat", "gpsy", "纬度"),
    "position_km": ("positionkm", "kilometer", "kilometermarker", "mileage", "里程", "公里标", "位置公里"),
    "speed": ("speed", "speedkmh", "speedmps", "速度", "运行速度"),
    "acceleration": ("acceleration", "acc", "longitudinalacceleration", "加速度", "纵向加速度"),
    "inclination": ("inclination", "pitch", "gradient", "slope", "倾角", "俯仰角", "坡度"),
    "traction_energy": ("tractionenergy", "positiveenergy", "useygdn", "tractionmeter", "牵引电量", "牵引能量", "正向电量", "用电量"),
    "regen_energy": ("regenenergy", "feedbackenergy", "usefkdn", "regenerationmeter", "再生电量", "再生能量", "回馈电量", "制动电量"),
    "power": ("power", "powerkw", "瞬时功率", "功率"),
    "voltage": ("voltage", "电压"),
    "current": ("current", "ampere", "电流"),
    "direction": ("direction", "directioncode", "sxx", "方向", "行别"),
    "station": ("station", "stationname", "车站", "站名"),
    "line": ("line", "railway", "线路", "线别"),
    "power_arm_id": ("powerarmid", "powerarm", "供电臂", "供电臂编号"),
}

UNIT_HINTS: dict[str, tuple[str, ...]] = {
    "speed": ("kmh", "km/h", "mps", "m/s", "速度"),
    "acceleration": ("mps2", "m/s2", "加速度"),
    "inclination": ("deg", "degree", "度", "permille", "千分率", "坡度"),
    "traction_energy": ("kwh", "mwh", "wh", "电量", "电能"),
    "regen_energy": ("kwh", "mwh", "wh", "电量", "电能"),
    "power": ("kw", "mw", "w", "功率"),
    "voltage": ("v", "kv", "电压"),
    "current": ("a", "ka", "电流"),
}

FILE_SUFFIXES = {".csv", ".tsv", ".json", ".xlsx", ".xls"}


def _norm(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = _text(value).replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "utf-8", "cp936"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replaced"


def _csv_rows(path: Path, max_rows: int) -> tuple[list[str], Iterator[dict[str, Any]], str, str]:
    text, encoding = _read_text(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    reader = csv.DictReader(lines[start:], delimiter=delimiter)
    headers = [str(value or "").strip() for value in (reader.fieldnames or [])]

    def limited() -> Iterator[dict[str, Any]]:
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            yield {header: row.get(header, "") for header in headers}

    return headers, limited(), encoding, delimiter


def _json_rows(path: Path, max_rows: int) -> tuple[list[str], Iterator[dict[str, Any]], str]:
    text, encoding = _read_text(path)
    payload = json.loads(text)
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        for key in ("rows", "data", "records", "items", "observations"):
            if isinstance(payload.get(key), list):
                raw_rows = payload[key]
                break
        else:
            raw_rows = [payload]
    else:
        raise ValueError("JSON root must be an object or an array")
    rows = [row for row in raw_rows[:max_rows] if isinstance(row, Mapping)]
    headers: list[str] = []
    for row in rows:
        for key in row:
            key_text = str(key)
            if key_text not in headers:
                headers.append(key_text)

    def limited() -> Iterator[dict[str, Any]]:
        for row in rows:
            yield {header: row.get(header, "") for header in headers}

    return headers, limited(), encoding


def _xlsx_rows(path: Path, max_rows: int) -> list[dict[str, Any]]:
    if load_workbook is None:
        raise RuntimeError("openpyxl is unavailable; XLSX cannot be profiled")
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheets: list[dict[str, Any]] = []
    for worksheet in workbook.worksheets:
        values = worksheet.iter_rows(values_only=True)
        header_row: list[str] | None = None
        rows: list[dict[str, Any]] = []
        for raw in values:
            cells = list(raw)
            if header_row is None:
                candidate = [str(value).strip() if value is not None else "" for value in cells]
                if any(candidate):
                    header_row = candidate
                continue
            if not any(value is not None and str(value).strip() for value in cells):
                continue
            row = {header_row[i]: cells[i] if i < len(cells) else "" for i in range(len(header_row)) if header_row[i]}
            rows.append(row)
            if len(rows) >= max_rows:
                break
        sheets.append({"sheet_name": worksheet.title, "headers": header_row or [], "rows": rows})
    workbook.close()
    return sheets


def _field_mapping(header: str, values: Sequence[Any]) -> dict[str, Any]:
    normalized = _norm(header)
    scored: list[tuple[int, str, str]] = []
    for canonical, aliases in CANONICAL_FIELDS.items():
        alias_norms = {_norm(alias) for alias in aliases}
        score = 0
        if normalized in alias_norms:
            score = 100
        elif any(len(alias) >= 3 and alias in normalized for alias in alias_norms):
            score = 70
        elif any(len(normalized) >= 3 and normalized in alias for alias in alias_norms):
            score = 55
        if score:
            scored.append((score, canonical, "exact" if score == 100 else "token"))
    scored.sort(reverse=True)
    best = scored[0] if scored else None
    ambiguous = bool(best and len(scored) > 1 and scored[1][0] >= best[0] - 10)
    numeric = [_parse_number(value) for value in values]
    numeric_values = [value for value in numeric if value is not None]
    nonempty = [_text(value) for value in values if _text(value)]
    unit_hints = [
        canonical
        for canonical, hints in UNIT_HINTS.items()
        if any(len(_norm(hint)) >= 2 and _norm(hint) in normalized for hint in hints)
    ]
    confidence = (best[0] / 100.0) if best else 0.0
    if ambiguous:
        confidence = min(confidence, 0.69)
    return {
        "source_field": header,
        "normalized_field": normalized,
        "candidate_canonical_field": best[1] if best else None,
        "candidate_match_type": best[2] if best else None,
        "candidate_confidence": round(confidence, 3),
        "ambiguous": ambiguous,
        "requires_confirmation": bool(best and (ambiguous or confidence < 0.95)),
        "unit_hints": sorted(set(unit_hints)),
        "observed_type": "numeric" if numeric_values and len(numeric_values) >= max(1, len(nonempty) * 0.8) else "text",
        "nonempty_count": len(nonempty),
        "unique_count": len(set(nonempty)),
        "numeric_min": min(numeric_values) if numeric_values else None,
        "numeric_max": max(numeric_values) if numeric_values else None,
        "examples": nonempty[:3],
    }


def _profile_rows(headers: Sequence[str], rows: Iterable[Mapping[str, Any]], max_rows: int) -> dict[str, Any]:
    samples: dict[str, list[Any]] = {header: [] for header in headers}
    row_count = 0
    for row in rows:
        row_count += 1
        for header in headers:
            if len(samples[header]) < 100:
                samples[header].append(row.get(header, ""))
    mappings = [_field_mapping(header, samples[header]) for header in headers]
    candidates = [item for item in mappings if item["candidate_canonical_field"]]
    canonical_counts = Counter(item["candidate_canonical_field"] for item in candidates)
    duplicate_canonical_fields = sorted(field_name for field_name, count in canonical_counts.items() if count > 1)
    return {
        "sampled_row_count": row_count,
        "field_count": len(headers),
        "fields": mappings,
        "duplicate_canonical_field_candidates": duplicate_canonical_fields,
        "truncated": row_count >= max_rows,
    }


def _classify(path: Path, fields: Sequence[Mapping[str, Any]]) -> list[str]:
    found = {item["candidate_canonical_field"] for item in fields if item.get("candidate_canonical_field")}
    classes: list[str] = []
    if {"longitude", "latitude"} <= found or "position_km" in found:
        classes.append("train_position")
    if {"acceleration", "inclination"} & found:
        classes.append("train_motion")
    if {"traction_energy", "regen_energy", "meter_id"} & found:
        classes.append("onboard_meter")
    if "event_time" in found:
        classes.append("time_series")
    return classes or ["unknown"]


def profile_file(path: Path, max_rows: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "file_name": path.name,
        "suffix": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "status": "ok",
        "errors": [],
        "sheets": [],
    }
    try:
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            headers, rows, encoding, delimiter = _csv_rows(path, max_rows)
            sheet = {"sheet_name": None, "encoding": encoding, "delimiter": delimiter, "headers": headers}
            sheet.update(_profile_rows(headers, rows, max_rows))
            sheet["inferred_data_classes"] = _classify(path, sheet["fields"])
            result["sheets"].append(sheet)
        elif suffix == ".json":
            headers, rows, encoding = _json_rows(path, max_rows)
            sheet = {"sheet_name": None, "encoding": encoding, "headers": headers}
            sheet.update(_profile_rows(headers, rows, max_rows))
            sheet["inferred_data_classes"] = _classify(path, sheet["fields"])
            result["sheets"].append(sheet)
        elif suffix == ".xlsx":
            for sheet_source in _xlsx_rows(path, max_rows):
                sheet = {"sheet_name": sheet_source["sheet_name"], "headers": sheet_source["headers"]}
                sheet.update(_profile_rows(sheet_source["headers"], sheet_source["rows"], max_rows))
                sheet["inferred_data_classes"] = _classify(path, sheet["fields"])
                result["sheets"].append(sheet)
        elif suffix == ".xls":
            result["status"] = "unsupported"
            result["errors"].append({"code": "legacy_xls_requires_conversion", "message": "Legacy XLS is preserved but needs a trusted reader or conversion before profiling."})
        else:
            result["status"] = "ignored"
            result["errors"].append({"code": "unsupported_extension", "message": "File type is outside the profiler's safe read set."})
    except Exception as exc:  # Report one bad provider file while continuing the package.
        result["status"] = "error"
        result["errors"].append({"code": "profile_failed", "message": f"{type(exc).__name__}: {exc}"})
    return result


def profile_directory(input_path: Path, output_dir: Path, max_rows: int = 5000) -> dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    files = [input_path] if input_path.is_file() else sorted(
        path for path in input_path.rglob("*") if path.is_file() and path.suffix.lower() in FILE_SUFFIXES
    )
    reports = [profile_file(path, max_rows) for path in files]
    all_fields = [field for report in reports for sheet in report["sheets"] for field in sheet["fields"]]
    confirmations = [field for field in all_fields if field.get("requires_confirmation")]
    return {
        "schema_version": "1.0",
        "tool": "external_data_profiler",
        "input_path": str(input_path),
        "max_rows_per_sheet": max_rows,
        "file_count": len(reports),
        "ok_file_count": sum(report["status"] == "ok" for report in reports),
        "error_file_count": sum(report["status"] == "error" for report in reports),
        "unsupported_file_count": sum(report["status"] == "unsupported" for report in reports),
        "confirmation_count": len(confirmations),
        "reports": reports,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    lines = ["# 外部数据自动剖析和字段映射报告", "", f"输入路径：`{report['input_path']}`", "", "本报告只提供候选映射，不代表字段已获得人工确认，也不会直接形成算法输入。", "", "## 总览", "", "| 项目 | 数量 |", "| --- | ---: |", f"| 文件数 | {report['file_count']} |", f"| 成功解析 | {report['ok_file_count']} |", f"| 解析失败 | {report['error_file_count']} |", f"| 暂不支持 | {report['unsupported_file_count']} |", f"| 需要确认的字段 | {report['confirmation_count']} |", ""]
    for file_report in report["reports"]:
        lines.extend([f"## {file_report['file_name']}", "", f"状态：`{file_report['status']}`；SHA-256：`{file_report['sha256']}`", ""])
        for sheet in file_report["sheets"]:
            title = sheet.get("sheet_name") or "默认数据表"
            lines.extend([f"### {title}", "", f"采样行数：{sheet['sampled_row_count']}；字段数：{sheet['field_count']}；数据类型：{', '.join(sheet['inferred_data_classes'])}", "", "| 原字段 | 候选标准字段 | 置信度 | 单位提示 | 是否需确认 |", "| --- | --- | ---: | --- | --- |"])
            for item in sheet["fields"]:
                lines.append(f"| {item['source_field']} | {item['candidate_canonical_field'] or '未识别'} | {item['candidate_confidence']:.3f} | {', '.join(item['unit_hints']) or '未识别'} | {'是' if item['requires_confirmation'] else '否'} |")
            lines.append("")
        for error in file_report["errors"]:
            lines.append(f"- `{error['code']}`：{error['message']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="原始文件或目录；不会被修改")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "external_data_profile")
    parser.add_argument("--max-rows", type=int, default=5000)
    args = parser.parse_args()
    if args.max_rows < 1:
        raise SystemExit("--max-rows must be positive")
    report = profile_directory(args.input, args.output_dir, args.max_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "external_data_profile.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "EXTERNAL_DATA_PROFILE.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("file_count", "ok_file_count", "error_file_count", "unsupported_file_count", "confirmation_count")}, ensure_ascii=False))
    return 0 if report["error_file_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
