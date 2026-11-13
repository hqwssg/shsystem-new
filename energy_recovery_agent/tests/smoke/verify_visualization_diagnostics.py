# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from unittest.mock import patch
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import timetable_energy_audit as audit_module
import timetable_optimizer as optimizer_module
from smoke_paths import smoke_output


OUTPUT_DIR = smoke_output("visualization_diagnostics_smoke")


def _raise_plot_error(*_args, **_kwargs):
    """函数 _raise_plot_error：执行该模块中的相关处理逻辑。"""
    raise ValueError("injected chart failure")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    candidate_rows = [
        {
            "candidate_id": "C0000",
            "total_adjustment_min": 0.0,
            "max_shift_min": 0.0,
            "delay_min": 0.0,
        }
    ]
    scenario_rows = [
        {
            "candidate_id": "C0000",
            "scenario_id": "storage_no_direct",
            "total_adjustment_min": 0.0,
            "wasted_kwh_est": 1.0,
            "direct_used_kwh_est": 0.0,
            "storage_absorbed_kwh_est": 0.0,
            "grid_kwh_est": 1.0,
            "issue_count": 1,
        }
    ]

    with patch.object(optimizer_module, "_plot_pareto_front", side_effect=_raise_plot_error):
        with warnings.catch_warnings(record=True) as caught:
            figures, errors = optimizer_module.write_optimizer_visualizations(
                OUTPUT_DIR / "optimizer",
                candidate_rows,
                scenario_rows,
                [],
            )
    assert errors == [
        {
            "figure": "pareto_front",
            "error_type": "ValueError",
            "message": "injected chart failure",
        }
    ]
    assert "pareto_front" not in figures
    assert any("injected chart failure" in str(item.message) for item in caught)

    with patch.object(optimizer_module, "_plot_pareto_front", side_effect=_raise_plot_error):
        try:
            optimizer_module.write_optimizer_visualizations(
                OUTPUT_DIR / "optimizer_strict",
                candidate_rows,
                scenario_rows,
                [],
                strict=True,
            )
        except RuntimeError as exc:
            assert "injected chart failure" in str(exc)
        else:
            raise AssertionError("strict optimizer visualization mode did not fail")

    with patch.object(audit_module, "_plot_timetable_profile", side_effect=_raise_plot_error):
        with warnings.catch_warnings(record=True) as caught:
            figures, errors = audit_module.write_audit_visualizations(
                OUTPUT_DIR / "audit",
                [],
                [],
                [],
            )
    assert errors == [
        {
            "figure": "timetable_profile",
            "error_type": "ValueError",
            "message": "injected chart failure",
        }
    ]
    assert "timetable_profile" not in figures
    assert any("injected chart failure" in str(item.message) for item in caught)

    with patch.object(audit_module, "_plot_timetable_profile", side_effect=_raise_plot_error):
        try:
            audit_module.write_audit_visualizations(
                OUTPUT_DIR / "audit_strict",
                [],
                [],
                [],
                strict=True,
            )
        except RuntimeError as exc:
            assert "injected chart failure" in str(exc)
        else:
            raise AssertionError("strict audit visualization mode did not fail")

    print("visualization diagnostics and strict failure mode passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
