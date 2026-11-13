"""对合成数据包注入确定性异常，并验证正式数据校验入口能够拦截。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_ingestion import validate_real_data_bundle


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class AnomalyCase:
    """描述一个互相隔离的数据异常及其预期校验结果。"""

    case_id: str
    category: str
    name: str
    target_file: str
    expected_code: str
    mutate: Callable[[Path], None]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _edit_json(file_name: str, edit: Callable[[dict[str, Any]], None]) -> Callable[[Path], None]:
    def mutate(case_dir: Path) -> None:
        path = case_dir / file_name
        payload = _read_json(path)
        edit(payload)
        _write_json(path, payload)

    return mutate


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _edit_csv(
    file_name: str,
    edit: Callable[[list[str], list[dict[str, str]]], None],
) -> Callable[[Path], None]:
    def mutate(case_dir: Path) -> None:
        path = case_dir / file_name
        fields, rows = _read_csv(path)
        edit(fields, rows)
        _write_csv(path, fields, rows)

    return mutate


def _set_csv_value(file_name: str, row_index: int, field: str, value: str) -> Callable[[Path], None]:
    return _edit_csv(file_name, lambda _fields, rows: rows[row_index].__setitem__(field, value))


def _remove_csv_column(file_name: str, field: str) -> Callable[[Path], None]:
    def edit(fields: list[str], rows: list[dict[str, str]]) -> None:
        fields.remove(field)
        for row in rows:
            row.pop(field, None)

    return _edit_csv(file_name, edit)


def _duplicate_csv_row(file_name: str, row_index: int) -> Callable[[Path], None]:
    return _edit_csv(file_name, lambda _fields, rows: rows.append(dict(rows[row_index])))


def _remove_file(file_name: str) -> Callable[[Path], None]:
    return lambda case_dir: (case_dir / file_name).unlink()


def _malformed_json(file_name: str) -> Callable[[Path], None]:
    return lambda case_dir: (case_dir / file_name).write_text('{"broken": ', encoding="utf-8")


def _create_invalid_blocks(case_dir: Path) -> None:
    _write_csv(
        case_dir / "signaling_blocks.csv",
        ["block_id", "start_km", "end_km", "direction", "is_single_line"],
        [{"block_id": "B001", "start_km": "0", "end_km": "10", "direction": "sideways", "is_single_line": "false"}],
    )


def _cases() -> tuple[AnomalyCase, ...]:
    """返回覆盖文件、拓扑、车辆、储能和资源约束的固定案例集。"""

    return (
        AnomalyCase("SD-F01", "文件与模式", "缺少必需文件", "route_metadata.json", "missing_file", _remove_file("route_metadata.json")),
        AnomalyCase("SD-F02", "文件与模式", "JSON语法损坏", "battery.json", "invalid_json", _malformed_json("battery.json")),
        AnomalyCase("SD-F03", "文件与模式", "CSV缺少必需列", "trains.csv", "missing_column", _remove_csv_column("trains.csv", "mass_tons")),
        AnomalyCase("SD-F04", "文件与模式", "非法信号制式", "route_metadata.json", "invalid_signaling_mode", _edit_json("route_metadata.json", lambda p: p["route"]["signaling_system"].__setitem__("mode", "unknown"))),
        AnomalyCase("SD-R01", "线路与拓扑", "线路总长为零", "route_metadata.json", "number_too_small", _edit_json("route_metadata.json", lambda p: p["route"].__setitem__("total_length_km", 0))),
        AnomalyCase("SD-R02", "线路与拓扑", "车站名称重复", "stations.csv", "duplicate_station", _set_csv_value("stations.csv", 1, "name", "神池南")),
        AnomalyCase("SD-R03", "线路与拓扑", "车站超出线路", "stations.csv", "station_outside_route", _set_csv_value("stations.csv", 1, "position_km", "9999")),
        AnomalyCase("SD-R04", "线路与拓扑", "区段起点留有空隙", "segments.csv", "segment_coverage_gap", _set_csv_value("segments.csv", 0, "start_km", "0.1")),
        AnomalyCase("SD-R05", "线路与拓扑", "相邻区段重叠", "segments.csv", "segment_overlap", _set_csv_value("segments.csv", 1, "start_km", "1.0")),
        AnomalyCase("SD-R06", "线路与拓扑", "区段终点不大于起点", "segments.csv", "invalid_range", _set_csv_value("segments.csv", 0, "end_km", "0")),
        AnomalyCase("SD-R07", "线路与拓扑", "坡度为非有限数", "segments.csv", "invalid_number", _set_csv_value("segments.csv", 0, "gradient_per_mille", "NaN")),
        AnomalyCase("SD-R08", "线路与拓扑", "能量区效率越界", "energy_transfer_zones.csv", "invalid_efficiency", _set_csv_value("energy_transfer_zones.csv", 0, "efficiency", "1.1")),
        AnomalyCase("SD-R09", "线路与拓扑", "能量区超出线路", "energy_transfer_zones.csv", "range_outside_route", _set_csv_value("energy_transfer_zones.csv", 0, "end_km", "9999")),
        AnomalyCase("SD-R10", "线路与拓扑", "闭塞方向非法", "signaling_blocks.csv", "invalid_direction", _create_invalid_blocks),
        AnomalyCase("SD-T01", "车辆物理", "列车名称重复", "trains.csv", "duplicate_train", _duplicate_csv_row("trains.csv", 0)),
        AnomalyCase("SD-T02", "车辆物理", "牵引力为零", "trains.csv", "number_too_small", _set_csv_value("trains.csv", 0, "max_traction_kN", "0")),
        AnomalyCase("SD-T03", "车辆物理", "制动力为负", "trains.csv", "number_too_small", _set_csv_value("trains.csv", 0, "max_brake_kN", "-1")),
        AnomalyCase("SD-T04", "车辆物理", "列车方向非法", "trains.csv", "invalid_direction", _set_csv_value("trains.csv", 0, "direction", "sideways")),
        AnomalyCase("SD-T05", "车辆物理", "黏着质量比例越界", "trains.csv", "number_too_large", _set_csv_value("trains.csv", 0, "traction_adhesion_weight_fraction", "1.1")),
        AnomalyCase("SD-E01", "储能与电气", "储能容量为负", "battery.json", "number_too_small", _edit_json("battery.json", lambda p: p.__setitem__("capacity_kwh", -1))),
        AnomalyCase("SD-E02", "储能与电气", "往返效率大于一", "battery.json", "number_too_large", _edit_json("battery.json", lambda p: p.__setitem__("round_trip_efficiency", 1.1))),
        AnomalyCase("SD-E03", "储能与电气", "充电功率为负", "battery.json", "number_too_small", _edit_json("battery.json", lambda p: p.__setitem__("max_charge_power_kW", -1))),
        AnomalyCase("SD-E04", "储能与电气", "规划标记不是布尔值", "battery.json", "invalid_boolean", _edit_json("battery.json", lambda p: p.__setitem__("planning_assumption", "perhaps"))),
        AnomalyCase("SD-E05", "储能与电气", "运行条件列表类型错误", "operating_conditions.json", "invalid_list", _edit_json("operating_conditions.json", lambda p: p.__setitem__("speed_restrictions", {}))),
        AnomalyCase("SD-C01", "资源与跨表", "站场资源引用未知车站", "station_resources.csv", "unknown_station", _set_csv_value("station_resources.csv", 0, "station_name", "不存在站")),
        AnomalyCase("SD-C02", "资源与跨表", "站场股道容量为零", "station_resources.csv", "number_too_small", _set_csv_value("station_resources.csv", 0, "track_capacity", "0")),
        AnomalyCase("SD-C03", "资源与跨表", "追踪间隔为负", "headway_constraints.csv", "number_too_small", _set_csv_value("headway_constraints.csv", 0, "headway_min", "-1")),
        AnomalyCase("SD-C04", "资源与跨表", "作业分配引用未知车站", "station_operation_assignments.csv", "unknown_station", _set_csv_value("station_operation_assignments.csv", 0, "station_name", "不存在站")),
        AnomalyCase("SD-C05", "资源与跨表", "作业分配列车类型非法", "station_operation_assignments.csv", "invalid_train_type", _set_csv_value("station_operation_assignments.csv", 0, "train_type", "Passenger")),
    )


def _tree_hash(source_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in source_dir.rglob("*") if item.is_file()):
        digest.update(path.relative_to(source_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_outputs(output_dir: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "synthetic_data_anomaly_summary.json"
    cases_path = output_dir / "synthetic_data_anomaly_cases.csv"
    failures_path = output_dir / "synthetic_data_anomaly_failures.json"
    report_path = output_dir / "SYNTHETIC_DATA_ANOMALY_REPORT.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with cases_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if not row["passed"]]
    failures_path.write_text(json.dumps({"failures": failures}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 合成输入数据异常覆盖报告",
        "",
        "本报告验证异常数据在进入仿真、优化和数据库任务执行前能够被统一数据校验入口识别。",
        "",
        f"- 有效母本：{'通过' if summary['baseline_valid'] else '失败'}",
        f"- 异常案例：{summary['case_count']}",
        f"- 通过：{summary['passed_count']}",
        f"- 失败：{summary['failed_count']}",
        f"- 母本完整性：{'未改变' if summary['baseline_unchanged'] else '已改变'}",
        f"- 案例集合指纹：`{summary['case_set_sha256']}`",
        "",
        "| 案例 | 类别 | 注入异常 | 目标文件 | 预期错误码 | 实际错误码 | 结果 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | {row['category']} | {row['name']} | `{row['target_file']}` | "
            f"`{row['expected_code']}` | `{row['actual_codes']}` | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## 结论边界",
        "",
        "通过表示当前校验器能拒绝这些已枚举的数据异常，不表示工程参数已正式标定，也不替代数据库约束、接口并发和现场系统联调。",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_matrix(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    """运行相互隔离的异常案例并生成机器可读与人员可读结果。"""

    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    baseline_before = _tree_hash(source_dir)
    baseline_report = validate_real_data_bundle(source_dir)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="heavy_empty_train_coordination_data_anomaly_") as temp_root:
        temp_path = Path(temp_root)
        for case in _cases():
            case_dir = temp_path / case.case_id
            shutil.copytree(source_dir, case_dir)
            case.mutate(case_dir)
            report = validate_real_data_bundle(case_dir)
            matching = [
                issue for issue in report.errors
                if issue.code == case.expected_code and issue.file == case.target_file
            ]
            codes = sorted({issue.code for issue in report.errors})
            rows.append({
                "case_id": case.case_id,
                "category": case.category,
                "name": case.name,
                "target_file": case.target_file,
                "expected_code": case.expected_code,
                "actual_codes": ",".join(codes),
                "error_count": len(report.errors),
                "passed": bool(not report.is_valid and matching),
            })

    baseline_after = _tree_hash(source_dir)
    stable_cases = [
        {key: row[key] for key in ("case_id", "category", "target_file", "expected_code", "passed")}
        for row in rows
    ]
    case_hash = hashlib.sha256(
        json.dumps(stable_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    categories: dict[str, dict[str, int]] = {}
    for row in rows:
        group = categories.setdefault(row["category"], {"case_count": 0, "passed_count": 0, "failed_count": 0})
        group["case_count"] += 1
        group["passed_count" if row["passed"] else "failed_count"] += 1
    failed_count = sum(1 for row in rows if not row["passed"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "passed": baseline_report.is_valid and baseline_before == baseline_after and failed_count == 0,
        "source_dir": str(source_dir),
        "baseline_valid": baseline_report.is_valid,
        "baseline_error_count": len(baseline_report.errors),
        "baseline_warning_count": len(baseline_report.warnings),
        "baseline_unchanged": baseline_before == baseline_after,
        "case_count": len(rows),
        "passed_count": len(rows) - failed_count,
        "failed_count": failed_count,
        "categories": categories,
        "case_set_sha256": case_hash,
        "outputs": {
            "report": "SYNTHETIC_DATA_ANOMALY_REPORT.md",
            "summary": "synthetic_data_anomaly_summary.json",
            "cases": "synthetic_data_anomaly_cases.csv",
            "failures": "synthetic_data_anomaly_failures.json",
        },
    }
    _write_outputs(output_dir, summary, rows)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data" / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper" / "experiments" / "synthetic_data_anomaly_matrix_current")
    args = parser.parse_args()
    summary = run_matrix(args.source_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
