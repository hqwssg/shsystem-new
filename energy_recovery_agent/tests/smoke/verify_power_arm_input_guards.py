# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from run_dispatch_case import load_case_inputs
from data_ingestion import write_real_data_template_from_config
from timetable_energy_audit import audit_timetable
from timetable_optimizer import optimize_timetable


ROOT = Path(__file__).resolve().parents[2]
TIMETABLE = ROOT / "data_templates" / "running_diagram_template.xlsx"
DATA_DIR = ROOT / "data" / "real_shuohuang"


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with TemporaryDirectory() as temp_name:
        output_dir = Path(temp_name)
        missing_power_arm = output_dir / "missing_power_arm_intervals.csv"

        audit = audit_timetable(
            TIMETABLE,
            output_dir / "audit",
            missing_power_arm,
            infrastructure_data_dir=DATA_DIR,
        )
        assert not audit["valid"]
        assert audit["error_code"] == "missing_or_empty_power_arm_data"

        optimization = optimize_timetable(
            TIMETABLE,
            output_dir / "optimizer",
            power_arm_path=missing_power_arm,
            resource_data_dir=DATA_DIR,
            max_candidates=1,
        )
        assert not optimization["valid"]
        assert optimization["error_code"] == "missing_or_empty_power_arm_data"

        generated_bundle = output_dir / "generated_bundle"
        write_real_data_template_from_config(ROOT / "sandbox_config.json", generated_bundle)
        generated_power_arm = generated_bundle / "power_arm_intervals.csv"
        assert generated_power_arm.is_file() and generated_power_arm.stat().st_size > 0
        generated_inputs = load_case_inputs(generated_bundle, output_dir / "generated_dispatch")
        assert len(generated_inputs.power_arm_limits) == 8
        assert len(generated_inputs.storage_sections) == 4
        generated_power_arm.unlink()

        try:
            load_case_inputs(
                generated_bundle,
                output_dir / "dispatch",
            )
        except FileNotFoundError as exc:
            assert "power_arm_intervals.csv" in str(exc)
        else:
            raise AssertionError("Dispatch accepted a data directory without power-arm intervals.")

        with patch(
            "run_dispatch_case.DEFAULT_POWER_ARM_INTERVAL_PATH",
            output_dir / "missing_default_power_arm_intervals.csv",
        ):
            try:
                load_case_inputs(ROOT / "sandbox_config.json", output_dir / "sandbox_dispatch")
            except FileNotFoundError as exc:
                assert "power_arm" in str(exc)
            else:
                raise AssertionError("Legacy dispatch accepted a missing default power-arm file.")

    print("power-arm input guards passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
