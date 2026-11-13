"""验证异常与极端输入总套件的聚合门禁。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.abnormal_extreme_input_suite import run_suite


def main() -> int:
    output_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    output_dir = output_root / "abnormal_extreme_input_suite_smoke"
    summary = run_suite(
        output_dir,
        seeds=[707],
        energy_cases=20,
        time_slicing_cases=15,
        resource_cases=20,
        pareto_cases=15,
    )
    assert summary["passed"] is True, summary
    assert summary["component_count"] == 6
    assert summary["failed_component_count"] == 0
    assert summary["enumerated_case_count"] == 204
    assert all(item["passed"] for item in summary["deep_guard_results"])
    persisted = json.loads((output_dir / "abnormal_extreme_input_summary.json").read_text(encoding="utf-8"))
    assert persisted["passed_component_count"] == 6
    print("abnormal and extreme input suite: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
