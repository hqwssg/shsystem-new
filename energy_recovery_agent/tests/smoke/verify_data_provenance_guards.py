"""Regression for provenance gating of virtual versus official data."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from pathlib import Path

import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_quality_validator import validate_all


ROOT = Path(__file__).resolve().parents[2]


def _write_source_workbook(path: Path, sheet_name: str, headers: list[str], row: list[object]) -> None:
    """创建来源校验所需的最小合法工作簿，避免依赖未发布的原始数据。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.append(headers)
    worksheet.append(row)
    workbook.save(path)


def _mark_trains_virtual(path: Path) -> None:
    """把列车质量状态标记为虚拟，用于回归溯源门禁本身。

    2026-11-04 起 `trains.csv` 的 `mass_data_status` 已改为
    `verified_by_smart_meter_train_weight`（5 万趟实绩核对），真实数据集不再
    天然触发「参数未确认」。与 battery / energy zone 一致，这里显式构造标记，
    让本用例继续校验「门禁能拦住虚拟数据」这一机制，而不是依赖数据集当前状态。
    """

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        row["mass_data_status"] = "virtual_placeholder"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _mark_battery_virtual(path: Path) -> None:
    """把储能参数标记为规划假设，用于回归溯源门禁本身。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["planning_assumption"] = True
    payload["data_status"] = "planning_virtual_preset"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _mark_energy_zones_virtual(path: Path) -> None:
    """把柔性供电协同区间标记为规划虚拟，用于回归溯源门禁本身。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        row["data_status"] = "planning_virtual_preset"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory(prefix="provenance_guard_smoke_") as temp_name:
        root = Path(temp_name)
        data_dir = root / "data"
        source_dir = root / "source"
        shutil.copytree(ROOT / "data" / "real_shuohuang", data_dir)
        # 本用例回归的是"虚拟数据必须被溯源门禁标记"这一机制本身。
        # 2026-09-18 起 data/real_shuohuang 的 battery.json 与 energy_transfer_zones.csv
        # 已换为已提供的文档值（见 docs/new_real_data_integration_20260918.md），
        # 因此这里显式构造虚拟溯源标记，不再依赖运行数据集当前的溯源状态。
        _mark_battery_virtual(data_dir / "battery.json")
        _mark_energy_zones_virtual(data_dir / "energy_transfer_zones.csv")
        _mark_trains_virtual(data_dir / "trains.csv")
        _write_source_workbook(
            source_dir / "power_arm" / "power_arm_continuous_intervals.xlsx",
            "供电臂连续区间表",
            ["section_id", "direction", "start_km", "end_km", "length_km"],
            ["P1", "上行", 0, 1, 1],
        )
        _write_source_workbook(
            source_dir / "geometry" / "gradients.xlsx",
            "坡度表",
            ["source_image", "start_km", "end_km", "length(m)", "坡度(千分率)"],
            ["synthetic_fixture", 0, 1, 1000, 0],
        )
        timetable = ROOT / "data_templates" / "running_diagram_template.xlsx"

        normal = validate_all(data_dir, source_dir, timetable)
        provenance_codes = {issue.code for issue in normal.warnings + normal.errors}
        if "provenance_battery_placeholder" not in provenance_codes:
            raise AssertionError("Normal validation must report the virtual battery provenance.")
        if not normal.is_valid:
            raise AssertionError("Virtual data should remain usable for the normal simulation workflow.")

        strict = validate_all(data_dir, source_dir, timetable, require_official_data=True)
        if strict.is_valid:
            raise AssertionError("Strict official-data validation must reject the current virtual dataset.")
        strict_codes = {issue.code for issue in strict.errors}
        expected = {
            "provenance_battery_placeholder",
            "provenance_resource_config_placeholder",
            "provenance_train_parameter_unconfirmed",
            "provenance_energy_zone_placeholder",
        }
        if not expected.issubset(strict_codes):
            raise AssertionError(f"Strict provenance errors missing: {expected - strict_codes}")

        route_path = data_dir / "route_metadata.json"
        route = json.loads(route_path.read_text(encoding="utf-8"))
        route["source_metadata"]["explicit_assumptions"] = []
        route["source_metadata"]["needs_confirmation"] = []
        route_path.write_text(json.dumps(route, ensure_ascii=False), encoding="utf-8")
        # 严格模式失败仍必须来自实际未确认的运行时数值，不能仅因线路元数据列表缺失。
        strict_after = validate_all(data_dir, source_dir, timetable, require_official_data=True)
        if strict_after.is_valid:
            raise AssertionError("Strict validation must remain blocked by unconfirmed runtime inputs.")

    print("data provenance guard verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
