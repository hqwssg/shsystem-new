"""Verify scenario overrides do not silently reuse the default dispatch output path."""

from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from run_project import DEFAULT_OUTPUT_ROOT, _dispatch_output_dir, write_simulation_report


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    default = Namespace(
        output_dir=DEFAULT_OUTPUT_ROOT / "dispatch_storage_no_direct_phase2600",
        baseline_phase_s=2600,
    )
    assert _dispatch_output_dir(default) == default.output_dir

    overridden = Namespace(
        output_dir=DEFAULT_OUTPUT_ROOT / "dispatch_storage_no_direct_phase2600",
        baseline_phase_s=3000,
    )
    assert _dispatch_output_dir(overridden) == Path("outputs") / "dispatch_storage_no_direct_phase3000"

    explicit = Namespace(
        output_dir=Path("outputs") / "my_custom_dispatch",
        baseline_phase_s=3000,
    )
    assert _dispatch_output_dir(explicit) == explicit.output_dir

    with TemporaryDirectory() as temp_name:
        output_root = Path(temp_name)
        write_simulation_report(
            output_root,
            {
                "validate-data": {},
                "meter-samples": {},
                "audit-timetable": {},
                "optimize-timetable": {},
                "dispatch-case": {},
            },
            dispatch_output_dir=output_root / "dispatch_storage_no_direct_phase3000",
        )
        report = (output_root / "SIMULATION_TEST_REPORT.md").read_text(encoding="utf-8")
        assert str(output_root / "dispatch_storage_no_direct_phase3000") in report
        assert "outputs/dispatch_storage_no_direct_phase2600" not in report
    print("dispatch output path override isolation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
