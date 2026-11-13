"""以最小参数区间执行联合稳健性物理仿真端到端测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.joint_parameter_robustness_benchmark import run_benchmark


def main() -> None:
    with TemporaryDirectory(prefix="joint_robustness_") as temp_name:
        root = Path(temp_name)
        config_path = root / "ranges.json"
        config_path.write_text(json.dumps({
            "schema_version": "1.0",
            "evaluation_code": "integration_minimal",
            "data_status": "synthetic_test_interval",
            "ranges": {"storage_capacity": [0.99, 1.01]},
            "sampling": {"interior_sample_count": 0, "seed": 7},
        }), encoding="utf-8")
        output_dir = root / "output"
        summary = run_benchmark(
            data_dir=ROOT / "data" / "real_shuohuang",
            parameter_ranges=config_path,
            output_dir=output_dir,
            heavy_count=1,
            empty_count=1,
        )
        assert summary["coverage"]["parameter_scenario_count"] == 3
        assert summary["coverage"]["combination_count"] == 15
        assert summary["claim_scope"] == "tested_discrete_joint_scenarios_only"
        assert summary["continuous_interval_certified"] is False
        assert (output_dir / "joint_parameter_scenarios.csv").is_file()
        assert (output_dir / "joint_robustness_results.csv").is_file()
        assert (output_dir / "JOINT_PARAMETER_ROBUSTNESS_REPORT.md").is_file()
    print("joint parameter robustness end-to-end: PASS")


if __name__ == "__main__":
    main()
