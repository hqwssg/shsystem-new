# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from argparse import Namespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import timetable_energy_audit as audit_module
import run_simulation_experiment_suite as experiment_suite
import run_project
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "running_diagram_template.xlsx"
DATA_DIR = Path("data") / "real_shuohuang"
OUTPUT_DIR = smoke_output("data_directory_propagation_smoke")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    profile = audit_module.load_infrastructure_profile(DATA_DIR)
    with patch.object(
        audit_module,
        "load_infrastructure_profile",
        return_value=profile,
    ) as profile_loader:
        summary = audit_module.audit_timetable(
            TEMPLATE,
            OUTPUT_DIR,
            DATA_DIR / "power_arm_intervals.csv",
            infrastructure_data_dir=DATA_DIR,
        )
    profile_loader.assert_called_once_with(DATA_DIR)
    assert summary["valid"]
    assert summary["infrastructure_data_dir"] == str(DATA_DIR)
    report_text = (OUTPUT_DIR / "TIMETABLE_ENERGY_AUDIT_REPORT.md").read_text(encoding="utf-8")
    assert "# 运行图能量审查报告" in report_text
    assert "## 输入摘要" in report_text
    assert "储能（无直接利用）" in report_text
    assert "Timetable Energy Audit Report" not in report_text
    with TemporaryDirectory() as temp_name:
        isolated_dir = Path(temp_name)
        try:
            audit_module.load_infrastructure_profile(isolated_dir)
        except FileNotFoundError as exc:
            if str(isolated_dir) not in str(exc):
                raise AssertionError("Missing-infrastructure error did not identify the selected data directory.")
        else:
            raise AssertionError("Infrastructure loader silently fell back outside the selected data directory.")
    custom_dir = Path("data") / "experiment_suite_custom"
    case_args = experiment_suite.parse_case_args(
        experiment_suite.CASE_DEFINITIONS[0],
        OUTPUT_DIR / "experiment_case",
        custom_dir,
    )
    if Path(case_args.input) != custom_dir:
        raise AssertionError("Experiment case parser did not receive the selected data directory.")
    project_args = run_project.build_parser().parse_args(
        ["experiment-suite", "--data-dir", str(custom_dir)]
    )
    if project_args.data_dir != custom_dir:
        raise AssertionError("Unified experiment-suite entry did not retain --data-dir.")
    experiment_output = OUTPUT_DIR / "experiment_suite"
    with patch.object(experiment_suite, "main", return_value=0) as suite_main:
        result = run_project.cmd_experiment_suite(
            Namespace(data_dir=custom_dir, output_root=experiment_output)
        )
    if result != 0:
        raise AssertionError("Unified experiment-suite command returned a failure code.")
    suite_main.assert_called_once_with(
        ["--data-dir", str(custom_dir), "--output-root", str(experiment_output)]
    )

    audit_args = run_project.build_parser().parse_args(
        ["audit-timetable", "--data-dir", str(custom_dir)]
    )
    with patch("timetable_energy_audit.audit_timetable", return_value={"valid": True}) as audit_entry:
        assert run_project.cmd_audit_timetable(audit_args) == 0
    assert audit_entry.call_args.args[2] == custom_dir / "power_arm_intervals.csv"

    optimize_args = run_project.build_parser().parse_args(
        ["optimize-timetable", "--data-dir", str(custom_dir)]
    )
    with patch("timetable_optimizer.optimize_timetable", return_value={"valid": True}) as optimize_entry:
        assert run_project.cmd_optimize_timetable(optimize_args) == 0
    assert optimize_entry.call_args.kwargs["power_arm_path"] == custom_dir / "power_arm_intervals.csv"
    assert optimize_entry.call_args.kwargs["resource_data_dir"] == custom_dir

    meter_args = run_project.build_parser().parse_args(
        ["meter-samples", "--data-dir", str(custom_dir)]
    )
    sample_summary = {
        "sample_count": 0,
        "sample_counts_by_normalized_trainid": {},
        "sample_counts_by_source_table": {},
    }
    alignment_summary = {
        "alignment_status_counts": {"aligned": 0, "zero_distance": 0, "station_unmapped": 0},
    }
    with patch(
        "smart_meter_representative_sampler.build_representative_samples",
        return_value=sample_summary,
    ), patch(
        "energy_calibration_alignment.build_alignment",
        return_value=alignment_summary,
    ) as alignment_entry:
        assert run_project.cmd_meter_samples(meter_args) == 0
    assert alignment_entry.call_args.args[1] == custom_dir / "stations.csv"
    assert alignment_entry.call_args.kwargs["factor_json"] == custom_dir / "energy_calibration_factors.json"
    assert alignment_entry.call_args.kwargs["infrastructure_data_dir"] == custom_dir

    explicit_power_arm = Path("explicit") / "power_arms.csv"
    explicit_args = run_project.build_parser().parse_args(
        [
            "audit-timetable",
            "--data-dir",
            str(custom_dir),
            "--power-arm-path",
            str(explicit_power_arm),
        ]
    )
    with patch("timetable_energy_audit.audit_timetable", return_value={"valid": True}) as explicit_entry:
        assert run_project.cmd_audit_timetable(explicit_args) == 0
    assert explicit_entry.call_args.args[2] == explicit_power_arm
    print("audit infrastructure data-directory propagation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
