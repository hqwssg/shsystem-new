# 模块功能说明：验证调度容量基准的指标提取、建议生成和图表输出。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.dispatch_capacity_quality_benchmark import (
    _extra_dispatch_metrics,
    _recommend_profiles,
    _write_charts,
)


def main() -> int:
    """用最小结果夹具覆盖新增基准的纯后处理逻辑。"""

    with TemporaryDirectory(prefix="dispatch_capacity_") as temp_name:
        root = Path(temp_name)
        algorithm_dir = root / "algorithm"
        algorithm_dir.mkdir()
        (algorithm_dir / "summary.json").write_text(
            json.dumps({
                "optimizer_diagnostics": {
                    "returned_candidate_core_robust_feasible": True,
                    "all_core_robust_candidates_infeasible": False,
                    "search_diagnostics": {
                        "candidate_evaluation_cache": {
                            "requests": 10,
                            "actual_robust_evaluations": 8,
                            "cache_hits": 2,
                            "unique_cached_templates": 8,
                        },
                        "energy_flat": False,
                        "recommended_search_profile": "standard",
                    }
                }
            }),
            encoding="utf-8",
        )
        metrics = _extra_dispatch_metrics(algorithm_dir)
        assert metrics["evaluation_cache_hits"] == 2
        assert metrics["core_robust_feasible"]
        rows = [
            {
                "case_type": "capacity", "profile": "capacity_quick", "train_count": 2,
                "scale": 1, "passed": True, "feasible": True, "wall_time_s": 5.0,
                "timeout_limit_s": 60, "peak_rss_mb": 100.0, "candidate_count": 8,
                "population_size": 4, "generations": 1, "evaluation_budget_upper": 8,
            },
            {
                "case_type": "budget", "profile": "quick", "train_count": 4,
                "scale": 2, "passed": True, "feasible": True, "wall_time_s": 8.0,
                "timeout_limit_s": 60, "peak_rss_mb": 110.0, "candidate_count": 12,
                "population_size": 4, "generations": 1, "evaluation_budget_upper": 8,
                "effective_regen_loss_kwh": 20.0, "grid_kwh": 10.0,
            },
        ]
        rows[1]["core_robust_feasible"] = True
        recommendations = _recommend_profiles(rows)
        assert recommendations["current_default"] == "quick"
        assert not recommendations["larger_budget_tested"]
        assert recommendations["profiles"]["quick"]["core_robust_feasible"]
        chart_paths = _write_charts(rows, root)
        assert len(chart_paths) == 2
        assert all(Path(path).is_file() for path in chart_paths)
    print("dispatch capacity and quality benchmark smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
