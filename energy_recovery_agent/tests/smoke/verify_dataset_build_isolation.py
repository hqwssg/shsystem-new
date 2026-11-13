# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from contextlib import ExitStack
from argparse import Namespace
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from unittest.mock import patch

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import run_project
from smoke_paths import smoke_output

DEFAULT_DATA_DIR = ROOT / "data" / "real_shuohuang"
OUTPUT_DIR = smoke_output("dataset_build_isolation_smoke")
CUSTOM_DATA_DIR = OUTPUT_DIR / "custom_data"
PRESERVED_FILE = "energy_calibration_factors.json"


def _write_workbook(path: Path, sheet_name: str, headers: list[str], row: list[object]) -> None:
    """写出构建隔离测试所需的最小来源工作簿。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.append(headers)
    worksheet.append(row)
    workbook.save(path)


def _build_source_fixture(source_dir: Path) -> None:
    _write_workbook(
        source_dir / "geometry" / "gradients.xlsx",
        "坡度表",
        ["source_image", "start_km", "end_km", "length(m)", "坡度(千分率)"],
        ["synthetic_fixture", 0, 583.003, 583003, 0],
    )
    _write_workbook(
        source_dir / "geometry" / "curves.xlsx",
        "线路曲线表 (2)",
        ["曲线起始位置(km)", "曲线结束位置(km)", "半径R(m)", "曲线长度L(m)", "曲线方向"],
        [0, 1, 1000, 1000, "左"],
    )
    _write_workbook(
        source_dir / "power_arm" / "power_arm_continuous_intervals.xlsx",
        "供电臂连续区间表",
        ["section_id", "road", "direction", "start_km", "end_km", "length_km"],
        ["P1", "朔黄", "上行", 0, 583.003, 583.003],
    )


def _hash_tree(path: Path) -> str:
    """函数 _hash_tree：执行该模块中的相关处理逻辑。"""
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    CUSTOM_DATA_DIR.mkdir(parents=True)
    source_dir = OUTPUT_DIR / "source_fixture"
    _build_source_fixture(source_dir)
    preserved_payload = {
        "global": {"traction_scale": 1.23, "sample_count": 10},
        "groups": {},
    }
    preserved_bytes = json.dumps(preserved_payload, ensure_ascii=False).encode("utf-8")
    (CUSTOM_DATA_DIR / PRESERVED_FILE).write_bytes(preserved_bytes)
    (CUSTOM_DATA_DIR / "stale_file.txt").write_text("remove me", encoding="utf-8")

    default_before = _hash_tree(DEFAULT_DATA_DIR)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run_project.py"),
            "build-data",
            "--data-dir",
            str(CUSTOM_DATA_DIR),
            "--source-dir",
            str(source_dir),
        ],
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"Custom dataset build failed with exit code {completed.returncode}")
    default_after = _hash_tree(DEFAULT_DATA_DIR)

    if default_before != default_after:
        raise AssertionError("Custom dataset build modified the default real_shuohuang directory.")
    if (CUSTOM_DATA_DIR / PRESERVED_FILE).read_bytes() != preserved_bytes:
        raise AssertionError("Dataset rebuild did not preserve the existing calibration factor file.")
    if (CUSTOM_DATA_DIR / "stale_file.txt").exists():
        raise AssertionError("Dataset rebuild retained an unmanaged stale file.")
    for required in ("gradients.csv", "curves.csv", "segments.csv", "power_arm_intervals.csv"):
        if not (CUSTOM_DATA_DIR / required).exists():
            raise AssertionError(f"Custom dataset is missing rebuilt file: {required}")
    with (CUSTOM_DATA_DIR / "power_arm_intervals.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        power_arm_fields = set((csv.DictReader(handle).fieldnames or ()))
    if not {"storage_start_km", "storage_end_km"}.issubset(power_arm_fields):
        raise AssertionError("Dataset build dropped explicit storage boundary columns.")

    summary = json.loads((CUSTOM_DATA_DIR / "build_summary.json").read_text(encoding="utf-8"))
    if Path(summary["source_dir"]).resolve() != source_dir.resolve():
        raise AssertionError("Dataset build summary did not record the selected source directory.")
    if PRESERVED_FILE not in summary["preserved_derived_files"]:
        raise AssertionError("Build summary did not report the preserved calibration file.")

    parsed = run_project.build_parser().parse_args(
        ["simulate", "--data-dir", str(CUSTOM_DATA_DIR)]
    )
    if parsed.data_dir != CUSTOM_DATA_DIR or parsed.rebuild_data:
        raise AssertionError("simulate must use the selected directory without rebuilding it by default.")

    workflow_args = Namespace(
        rebuild_data=False,
        data_dir=CUSTOM_DATA_DIR,
        source_dir=ROOT / "data" / "source",
        timetable=ROOT / "data_templates" / "running_diagram_template.xlsx",
        smart_meter_dir=ROOT / "data" / "source" / "smart_meter",
        output_root=OUTPUT_DIR / "workflow",
        max_per_normalized_trainid=1,
        max_realtime_rows_per_file=1,
        timetable_population_size=2,
        timetable_generations=1,
        max_shift_min=5,
        step_min=5,
        max_dwell_extension_min=0,
        max_candidates=2,
        crossover_rate=0.8,
        mutation_rate=0.1,
        seed=42,
        dispatch_population_size=2,
        dispatch_generations=1,
        heavy_count=1,
        empty_count=1,
        baseline_phase_s=2600,
        baseline_heavy_headway_s=3300,
        baseline_empty_headway_s=2700,
        min_depart_gap_s=300,
        settlement_step_s=10,
    )
    command_names = (
        "cmd_validate_data",
        "cmd_meter_samples",
        "cmd_audit_timetable",
        "cmd_optimize_timetable",
        "cmd_dispatch_case",
        "cmd_heavy_empty_plan",
    )
    with ExitStack() as stack:
        build_mock = stack.enter_context(patch.object(run_project, "cmd_build_data", return_value=0))
        command_mocks = {
            name: stack.enter_context(patch.object(run_project, name, return_value=0))
            for name in command_names
        }
        stack.enter_context(patch.object(run_project, "_load_step_summary", return_value={}))
        stack.enter_context(patch.object(run_project, "write_simulation_report"))
        if run_project.cmd_real_data_workflow(workflow_args) != 0:
            raise AssertionError("Mocked simulation workflow failed.")
    build_mock.assert_not_called()
    for name, command_mock in command_mocks.items():
        command_mock.assert_called_once()
        called_args = command_mock.call_args.args[0]
        selected_dir = getattr(called_args, "resource_data_dir", getattr(called_args, "data_dir", None))
        if selected_dir != CUSTOM_DATA_DIR:
            raise AssertionError(f"{name} did not receive the selected custom data directory.")

    print("custom dataset build isolation and derived-file preservation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
