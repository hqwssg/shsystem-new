"""验证随机合成差分测试的结果、复现性和工件合同。"""

from __future__ import annotations

from pathlib import Path
import json
import os
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.random_synthetic_differential import run_differential_tests


def main() -> int:
    smoke_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    first_dir = smoke_root / "random_synthetic_differential_smoke" / "first"
    second_dir = smoke_root / "random_synthetic_differential_smoke" / "second"
    arguments = {
        "seeds": [101, 202],
        "energy_cases": 60,
        "time_slicing_cases": 50,
        "resource_cases": 60,
        "pareto_cases": 40,
    }
    first = run_differential_tests(first_dir, **arguments)
    second = run_differential_tests(second_dir, **arguments)
    assert first["passed"] and second["passed"]
    assert first["total_case_count"] == 420
    assert first["failed_count"] == 0
    assert first["case_set_sha256"] == second["case_set_sha256"]
    assert first["suites"] == second["suites"]
    assert all(item["case_count"] > 0 for item in first["suites"].values())
    assert all(item["failed_count"] == 0 for item in first["suites"].values())
    for relative_path in first["outputs"].values():
        assert (first_dir / relative_path).is_file(), relative_path
    failures = json.loads(
        (first_dir / "random_synthetic_differential_failures.json").read_text(encoding="utf-8")
    )
    assert failures["failures"] == []
    with patch(
        "tools.random_synthetic_differential._run_energy_case",
        side_effect=RuntimeError("injected differential failure"),
    ):
        failed = run_differential_tests(
            smoke_root / "random_synthetic_differential_smoke" / "injected_failure",
            seeds=[303],
            energy_cases=1,
            time_slicing_cases=1,
            resource_cases=1,
            pareto_cases=1,
        )
    assert failed["passed"] is False and failed["failed_count"] == 1
    replay = json.loads(
        (
            smoke_root
            / "random_synthetic_differential_smoke"
            / "injected_failure"
            / "random_synthetic_differential_failures.json"
        ).read_text(encoding="utf-8")
    )
    assert replay["failures"][0]["max_absolute_error"] is None
    assert "injected differential failure" in replay["failures"][0]["error"]
    print("random synthetic differential smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
