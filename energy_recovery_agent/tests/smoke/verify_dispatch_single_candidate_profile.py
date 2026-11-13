# 模块功能说明：验证单候选性能剖析工具的语义摘要和报告输出契约。

from pathlib import Path
from tempfile import TemporaryDirectory
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rolling_optimizer import DisturbanceScenario, ScheduleScore
from tools.dispatch_single_candidate_profile import _semantic_sha256, _write_report


def main() -> int:
    """执行不依赖真实轨迹计算的剖析工具轻量回归。"""

    scenario = DisturbanceScenario("normal")
    score = ScheduleScore(True, 10.0, 20.0, 10.0, 20.0, 1)
    first = _semantic_sha256(score, [(scenario, score)])
    second = _semantic_sha256(score, [(scenario, score)])
    changed_score = ScheduleScore(True, 11.0, 20.0, 11.0, 20.0, 1)
    changed = _semantic_sha256(changed_score, [(scenario, changed_score)])
    assert first == second
    assert first != changed

    summary = {
        "candidate": {
            "heavy_count": 1,
            "empty_count": 1,
            "heavy_headway_s": 3300,
            "empty_headway_s": 3300,
            "phase_s": 840,
            "storage_preset_id": "test",
            "settlement_step_s": 10,
        },
        "benchmark": {
            "scenario_count": 1,
            "repeat_count": 2,
            "median_wall_time_s": 1.0,
            "min_wall_time_s": 0.9,
            "max_wall_time_s": 1.1,
            "profiled_wall_time_s": 2.0,
            "core_robust_feasible": True,
            "constraint_violation": 0.0,
            "semantic_stable": True,
            "semantic_sha256": first,
        },
        "top_functions": [
            {"function": "module.py:1::work", "calls": 2, "own_s": 0.5, "cumulative_s": 1.0}
        ],
    }
    with TemporaryDirectory() as temp:
        output_dir = Path(temp)
        _write_report(output_dir, summary)
        report = (output_dir / "DISPATCH_SINGLE_CANDIDATE_PROFILE.md").read_text(encoding="utf-8")
        assert "单候选性能剖析" in report
        assert first in report
        assert "module.py:1::work" in report

    print("dispatch single-candidate profiler smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
