# 模块功能说明：本脚本验证正式实验总控的阻断机制、方案编排和统一汇总输出。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.formal_experiment_controller as controller


def _accepted_readiness(data_dir: Path, source_dir: Path, timetable: Path, output_dir: Path, **_: object) -> dict:
    """为编排回归提供已验收桩；真实门禁阻断由统一入口单独覆盖。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    acceptance = {
        "accepted": True,
        "data_dir": str(data_dir),
        "source_dir": str(source_dir),
        "timetable": str(timetable),
        "error_count": 0,
        "warning_count": 0,
        "issues": [],
    }
    (output_dir / "readiness_summary.json").write_text(json.dumps({"accepted": True}), encoding="utf-8")
    return {"accepted": True, "acceptance": acceptance, "simulation": None, "comparison": None}


def main() -> int:
    """用当前可运行数据验证总控编排，不将其伪装为正式数据实验。"""
    original_runner = controller.run_pipeline
    controller.run_pipeline = _accepted_readiness
    data_dir = ROOT / "data" / "real_shuohuang"
    before = sorted(path.name for path in data_dir.iterdir())
    try:
        with TemporaryDirectory(prefix="formal_experiment_controller_") as temp_name:
            output_root = Path(temp_name) / "suite"
            summary = controller.run_formal_experiment_suite(
                data_dir=data_dir,
                source_dir=ROOT / "data" / "source",
                timetable=ROOT / "data_templates" / "running_diagram_template.xlsx",
                output_root=output_root,
                window_id="controller_regression",
                seeds=(101, 202),
                max_shift_min=10,
                step_min=5,
                max_dwell_extension_min=5,
                max_candidates=20,
                population_size=6,
                generations=2,
            )
            assert summary["status"] == "completed", summary
            assert len(summary["scenarios"]) == 5, summary["scenarios"]
            assert all(row["status"] == "completed" for row in summary["scenarios"])
            assert all(float(row["runtime_s"]) >= 0.0 for row in summary["scenarios"])
            assert (output_root / "formal_experiment_summary.json").is_file()
            assert (output_root / "formal_experiment_kpi.csv").is_file()
            assert (output_root / "formal_timestep_sensitivity.csv").is_file()
            assert (output_root / "FORMAL_EXPERIMENT_REPORT.md").is_file()
            assert (output_root / "derived_configs" / "F02_no_storage_runtime" / "DERIVED_NO_STORAGE_MANIFEST.json").is_file()
            baseline = next(row for row in summary["scenarios"] if row["scenario_code"] == "F01_B0_baseline")
            no_storage = next(row for row in summary["scenarios"] if row["scenario_code"] == "F02_B1_no_storage")
            assert baseline["battery_charge_kwh"] is not None
            assert no_storage["battery_charge_kwh"] == 0.0
            assert no_storage["grid_saving_vs_baseline_kwh"] is not None
            assert [row["time_step_s"] for row in summary["timestep_sensitivity"]] == [1, 5, 10]
            assert all(row["status"] == "completed" for row in summary["timestep_sensitivity"])

            failed_calibration = Path(temp_name) / "failed_calibration.json"
            failed_calibration.write_text(
                json.dumps({"publication_ready": False, "failed_checks": ["minimum_validation_samples"]}),
                encoding="utf-8",
            )
            blocked = controller.run_formal_experiment_suite(
                data_dir=data_dir,
                source_dir=ROOT / "data" / "source",
                timetable=ROOT / "data_templates" / "running_diagram_template.xlsx",
                output_root=Path(temp_name) / "calibration_blocked",
                window_id="calibration_blocked",
                seeds=(101,),
                calibration_summary=failed_calibration,
                require_calibration=True,
            )
            assert blocked["status"] == "blocked"
            assert blocked["readiness"]["accepted"] is True
            assert blocked["calibration"]["accepted"] is False
            assert blocked["scenarios"] == []
    finally:
        controller.run_pipeline = original_runner
    assert sorted(path.name for path in data_dir.iterdir()) == before, "总控不得修改正式输入目录"
    print("formal experiment controller smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
