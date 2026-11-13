"""混合数据储能规划输入生成、运行图文件适配和端到端回归。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storage_planning_contract import CONTRACT_FILE_NAMES, load_storage_planning_bundle
from storage_planning_mixed import build_storage_planning_mixed_inputs
from storage_planning_mvp import run_storage_planning_mvp


def main() -> None:
    with TemporaryDirectory(prefix="storage_planning_mixed_") as name:
        root = Path(name)
        inputs = root / "inputs"
        outputs = root / "outputs"
        summary = build_storage_planning_mixed_inputs(
            ROOT / "data" / "real_shuohuang",
            ROOT / "data_templates" / "running_diagram_template.xlsx",
            inputs,
        )
        assert summary["valid"] is True
        assert summary["recommendation_level"] == "planning_sensitivity"
        assert summary["site_count"] == 2
        assert all((inputs / filename).is_file() for filename in CONTRACT_FILE_NAMES)
        assert (inputs / "mixed_running_diagram.xlsx").is_file()

        bundle = load_storage_planning_bundle(inputs)
        assert all("朔黄线:" in item.power_arm_code for item in bundle.sites)
        assert all(item.timetable_relative_path == "mixed_running_diagram.xlsx" for item in bundle.scenarios)
        # 缩小回归域只影响测试耗时；生产命令仍使用生成策略中的双站域。
        policy_path = inputs / "storage_planning_policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["max_site_count"] = 1
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

        result = run_storage_planning_mvp(
            inputs,
            ROOT / "data" / "real_shuohuang",
            outputs,
            max_levels_per_dimension=2,
            settlement_step_s=300,
        )
        assert result["recommendation_level"] == "planning_sensitivity"
        assert result["declared_search_domain"]["complete_for_declared_domain"] is True
        assert result["scenario_schedule_sources"] == {
            "mixed_current_timetable": "mixed_running_diagram.xlsx",
            "mixed_single_site_outage": "mixed_running_diagram.xlsx",
            "mixed_storage_power_derating": "mixed_running_diagram.xlsx",
        }
        assert result["best_feasible_build_alternative"] is not None
        with (outputs / "storage_device_scenario_results.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            device_scenarios = list(csv.DictReader(handle))
        outage_rows = [
            row for row in device_scenarios
            if row["scenario_code"] == "mixed_single_site_outage"
            and row["site_code"] == "MIXED-STORAGE_SECTION_1"
        ]
        assert outage_rows
        assert all(float(row["charge_kwh"]) == 0.0 for row in outage_rows)
        assert all(float(row["discharge_kwh"]) == 0.0 for row in outage_rows)
        derated_rows = [
            row for row in device_scenarios
            if row["scenario_code"] == "mixed_storage_power_derating"
        ]
        assert derated_rows and all(float(row["rated_power_factor"]) == 0.5 for row in derated_rows)
        assert any(float(row["self_discharge_loss_kwh"]) > 0.0 for row in device_scenarios)
        for filename in (
            "storage_planning_summary.json", "storage_planning_report.md", "energy_hotspots.csv",
            "storage_plan_candidates.csv", "storage_plan_scenario_results.csv",
        ):
            assert (outputs / filename).is_file(), filename
    print("storage planning mixed-data closure smoke: PASS")


if __name__ == "__main__":
    main()
