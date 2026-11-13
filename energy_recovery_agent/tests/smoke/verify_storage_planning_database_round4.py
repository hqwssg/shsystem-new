"""第四轮：储能规划第六类数据库任务、关系投影和结果投影验收。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import sys
import shutil

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.dataset_projection import project_dataset
from database.parameters import validate_run_parameters
from database.result_projection import project_result_directory
from database.worker import build_algorithm_command
from storage_planning_mvp import run_storage_planning_mvp


def main() -> None:
    sql = (ROOT / "database/migrations/008_storage_planning.sql").read_text(encoding="utf-8")
    for name in (
        "simulation_storage_candidate_site", "simulation_storage_technology",
        "simulation_storage_planning_scenario", "simulation_storage_planning_policy",
        "simulation_storage_plan", "simulation_storage_plan_device",
        "simulation_storage_plan_scenario_result", "simulation_storage_plan_decision",
    ):
        assert name in sql
    assert "'storage_planning'" in sql

    parameters = {
        "planning_policy_code": "SYNTHETIC-BASE",
        "scenario_set_code": "SYNTHETIC-TYPICAL-DAYS",
        "search_mode": "coarse",
        "max_levels_per_dimension": 2,
        "settlement_step_s": 300,
        "refinement_shortlist_size": 2,
    }
    validate_run_parameters("storage_planning", parameters)
    command = build_algorithm_command(
        "storage_planning", parameters,
        data_dir=ROOT / "data_templates/storage_planning_synthetic",
        output_dir=ROOT / "outputs/test-storage-planning-database-command",
    )
    assert "plan-storage" in command
    assert "--input-dir" in command and "--data-dir" in command

    with TemporaryDirectory(prefix="storage_planning_database_round4_") as name:
        temp_root = Path(name)
        merged = temp_root / "merged"
        shutil.copytree(ROOT / "data/real_shuohuang", merged)
        for source in (ROOT / "data_templates/storage_planning_synthetic").iterdir():
            if source.is_file():
                shutil.copy2(source, merged / source.name)
        projection = project_dataset(uuid4(), merged)
        assert projection["storage_candidate_sites"]
        assert projection["storage_technologies"]
        assert projection["storage_planning_scenarios"]
        assert len(projection["storage_planning_policies"]) == 1

        output = temp_root / "output"
        summary = run_storage_planning_mvp(
            ROOT / "data_templates/storage_planning_synthetic",
            ROOT / "data/real_shuohuang",
            output, max_levels_per_dimension=2, settlement_step_s=300,
            search_mode="coarse", refinement_shortlist_size=2,
        )
        projected = project_result_directory(uuid4(), output, 300)
        assert projected["storage_plans"]
        assert projected["storage_plan_devices"]
        assert projected["storage_plan_scenario_results"]
        decision = projected["storage_plan_decision"]
        assert decision is not None
        assert decision["decision"] == summary["decision"]
        assert any(item["selected"] for item in projected["storage_plans"])
        assert all(item["storage_plan_id"] for item in projected["storage_plan_devices"])

    print("storage planning database engineering round4: PASS")


if __name__ == "__main__":
    main()
