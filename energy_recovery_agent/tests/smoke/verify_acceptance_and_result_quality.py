# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from formal_data_acceptance import run_acceptance
from result_quality_audit import ResultIssue, _check_dispatch, audit_output_root


ROOT = Path(__file__).resolve().parents[2]

acceptance = run_acceptance(
    ROOT / "data" / "real_shuohuang",
    ROOT / "data" / "source",
    ROOT / "data_templates" / "running_diagram_template.xlsx",
)
assert acceptance["accepted"] is False
assert acceptance["error_count"] > 0

with TemporaryDirectory(prefix="valid_result_quality_smoke_") as temp_name:
    output_root = Path(temp_name)
    dispatch_dir = output_root / "dispatch_minimal"
    dispatch_dir.mkdir(parents=True)
    valid_case = {
        "total_gen_kwh": 10,
        "total_con_kwh": 5,
        "direct_used_kwh": 0,
        "battery_charge_kwh": 6,
        "battery_discharge_kwh": 2,
        "wasted_kwh": 4,
        "grid_kwh": 3,
        "final_soc_kwh": 5,
        "final_soc_by_storage_kwh": {"S1": 5},
        "accepted_by_power_arm_kwh": 6,
        "recovered_energy_kwh": 6,
        "storage_efficiency": 1,
        "recovery_rate": 0.6,
    }
    (dispatch_dir / "summary.json").write_text(
        json.dumps(
            {
                "battery": {"capacity_kwh": 10},
                "baseline": valid_case,
                "optimized": valid_case,
            }
        ),
        encoding="utf-8",
    )
    result = audit_output_root(output_root)
    assert result["accepted"] is True, result

with TemporaryDirectory(prefix="result_quality_smoke_") as temp_name:
    output_root = Path(temp_name)
    dispatch_dir = output_root / "dispatch_storage_no_direct_phase2600"
    dispatch_dir.mkdir(parents=True)
    malformed = {
        "battery": {"capacity_kwh": 10},
        "baseline": {
            "total_gen_kwh": 10, "total_con_kwh": 5, "direct_used_kwh": 0,
            "battery_charge_kwh": 2, "battery_discharge_kwh": 0,
            "wasted_kwh": 1, "grid_kwh": 4,
            "final_soc_kwh": 11,
            "final_soc_by_storage_kwh": {"S1": 11},
        },
    }
    (dispatch_dir / "summary.json").write_text(json.dumps(malformed), encoding="utf-8")
    broken = audit_output_root(output_root)
    assert broken["accepted"] is False
    codes = {item["code"] for item in broken["issues"]}
    assert {"generation_not_conserved", "traction_not_conserved", "soc_out_of_bounds"} <= codes

with TemporaryDirectory(prefix="rolling_quality_smoke_") as temp_name:
    output_root = Path(temp_name)
    malformed_rolling = {
        "status": "completed",
        "cycle_count": 1,
        "all_gates_passed": True,
        "gates": {"storage_device_soc_continuity": True},
        "cycles": [{
            "initial_soc_kwh": 5,
            "executed_final_soc_kwh": 4,
            "storage_device_states": [{
                "storage_section_id": "S1",
                "soc_kwh": 5,
                "available": False,
            }],
            "storage_parameters_by_id": {"S1": {
                "capacity_kwh": 10,
                "max_charge_power_kw": 10,
                "max_discharge_power_kw": 10,
                "charge_efficiency": 1,
                "discharge_efficiency": 1,
                "initial_soc_kwh": 5,
                "min_soc_kwh": 0,
                "max_soc_kwh": 10,
                "available": True,
                "data_status": "synthetic",
                "source_note": "反例",
            }},
            "initial_soc_by_storage_kwh": {"S1": 5},
            "executed_final_soc_by_storage_kwh": {"S1": 4},
            "executed_charge_by_storage_kwh": {"S1": 0},
            "executed_discharge_by_storage_kwh": {"S1": 1},
            "executed_wasted_by_storage_kwh": {"S1": 0},
        }],
    }
    (output_root / "benchmark_summary.json").write_text(
        json.dumps(malformed_rolling), encoding="utf-8"
    )
    broken = audit_output_root(output_root)
    assert broken["accepted"] is False
    codes = {item["code"] for item in broken["issues"]}
    assert "offline_storage_has_flow" in codes


print("formal data acceptance and result quality audit passed")
