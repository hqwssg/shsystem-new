"""使用真实物理轨迹执行历史扰动四轮回放；本脚本属于独立长耗时测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import csv
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.result_projection import project_result_directory
from historical_disturbance_replay import load_historical_disturbance_replay
from tools.synthetic_rolling_rescheduling_benchmark import run_benchmark


def main() -> int:
    replay = load_historical_disturbance_replay(
        ROOT / "data_templates" / "historical_disturbance_replay_template.json"
    )
    with TemporaryDirectory(prefix="historical_replay_output_") as temp_name:
        output_dir = Path(temp_name)
        summary = run_benchmark(
            data_dir=ROOT / "data" / "real_shuohuang",
            output_dir=output_dir,
            population_size=2,
            generations=1,
            seed=20260908,
            disturbance_replay=replay,
        )
        assert summary["input_mode"] == "historical_disturbance_replay"
        assert summary["disturbance_replay"]["source_sha256"] == replay.source_sha256
        assert summary["cycle_count"] == 4
        assert summary["all_gates_passed"] is True
        assert summary["gates"]["replay_storage_observations_applied"] is True
        assert summary["gates"]["train_delay_events_reach_execution"] is True
        assert summary["gates"]["temporary_speed_restrictions_applied"] is True
        assert len(summary["applied_temporary_speed_restrictions"]) == 1
        assert summary["applied_temporary_speed_restrictions"][0]["direction"] == "forward"
        assert summary["cycles"][0]["observed_train_delays_s"] == {"H001": 30}
        assert summary["cycles"][0]["planned_heavy_departures_s"][0] == 30
        assert summary["cycles"][0]["realized_heavy_departures_s"][0] == 30
        assert 30 in summary["cycles"][1]["locked_heavy_before"]
        for name in (
            "disturbance_replay_manifest.json",
            "disturbance_replay_cycles.csv",
            "HISTORICAL_DISTURBANCE_REPLAY_REPORT.md",
        ):
            assert (output_dir / name).is_file(), name
        with (output_dir / "disturbance_replay_cycles.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 4
        assert json.loads(rows[2]["source_record_ids"]) == [
            "example-record-0003", "example-record-0004"
        ]
        projection = project_result_directory(uuid4(), output_dir)
        observation = projection["rolling_control_events"][0]["event"]["observation"]
        assert observation["observed_train_delays_s"] == {"H001": 30}
        assert len(observation["disturbance_events"]) == 3

    dynamic_replay = load_historical_disturbance_replay(
        ROOT / "tests" / "fixtures" / "historical_dynamic_disturbance_events.json"
    )
    with TemporaryDirectory(prefix="historical_dynamic_replay_output_") as temp_name:
        dynamic_summary = run_benchmark(
            data_dir=ROOT / "data" / "real_shuohuang",
            output_dir=Path(temp_name),
            population_size=2,
            generations=1,
            seed=20260909,
            disturbance_replay=dynamic_replay,
            allow_infeasible_commit_for_experiment=True,
        )
        assert dynamic_summary["gates"]["dynamic_events_reach_execution"] is True
        first, second = dynamic_summary["cycles"]
        assert first["cancelled_train_ids"] == ["E001"]
        assert first["added_train_ids"] == ["E003"]
        assert "E001" not in first["planned_empty_train_ids"]
        assert "E003" in first["planned_empty_train_ids"]
        assert second["cancelled_train_ids"] == []
        assert second["added_train_ids"] == ["E003"]
        assert second["resource_unavailability_ids"] == ["dynamic-resource-0001"]
        assert second["dynamic_power_limit_ids"] == ["dynamic-power-0001"]
    print("historical disturbance replay end-to-end verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
