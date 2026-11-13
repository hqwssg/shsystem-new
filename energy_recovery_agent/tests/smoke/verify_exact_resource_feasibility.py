"""验证精确资源层能区分可行方案与经证明不可行模型。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exact_resource_feasibility import (
    solve_exact_resource_feasibility,
    solve_quality_optimized_resource_feasibility,
)
from rolling_optimizer import ScheduleTemplate, default_scenarios
from run_dispatch_case import load_case_inputs
from scheduler_nsga2 import build_power_cache
from recovery_work_budget import RecoveryWorkBudget


def main() -> int:
    with TemporaryDirectory(prefix="exact_resource_smoke_") as temp_name:
        case_inputs = load_case_inputs(ROOT / "data" / "real_shuohuang", Path(temp_name))
        heavy_cache = build_power_cache(
            case_inputs.trains["Heavy"], case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        empty_cache = build_power_cache(
            case_inputs.trains["Empty"], case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        # 不依赖求解器恰好选在边界哪侧：直接检查实际传给MILP的变量下界。
        for locked in ((), (1120,)):
            budget = RecoveryWorkBudget(full_limit=1, resource_limit=10, candidate_limit=10,
                                        wall_limit_s=30, solver_limit_s=2)
            with patch("exact_resource_feasibility.milp", return_value=SimpleNamespace(
                    status=1, x=None, message="test_limit", success=False)) as mocked:
                result = solve_exact_resource_feasibility(
                    ScheduleTemplate(3300, 3300, 0, 1, 0, start_time_s=1120), default_scenarios(),
                    case_inputs.resource_model, heavy_cache, empty_cache,
                    horizon_s=5000, max_adjustment_s=600, disturbance_from_time_s=1000,
                    locked_heavy_departures_s=locked, time_limit_s=30, work_budget=budget)
            bounds = mocked.call_args.kwargs["bounds"]
            assert bounds.lb[0] == (1120 if locked else 1000)
            assert mocked.call_args.kwargs["options"]["time_limit"] <= 2
            assert budget.solver_calls == 1 and budget.solver_time_s >= 0
            assert result.status == "solver_limit_no_solution" and result.proof == "none"
        template = ScheduleTemplate(3300, 2700, 2600, 2, 2)
        feasible = solve_exact_resource_feasibility(
            template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache, horizon_s=7200, time_limit_s=30,
        )
        assert feasible.status == "feasible_verified"
        assert feasible.proof != "none"
        assert all(
            row["feasible"]
            for row in feasible.diagnostics["authoritative_verification"]
        )

        fixed_verification = solve_exact_resource_feasibility(
            feasible.schedule_template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache, horizon_s=7200, max_adjustment_s=0, time_limit_s=30,
        )
        assert fixed_verification.status == "feasible_verified"
        assert fixed_verification.diagnostics["max_adjustment_s"] == 0

        rolling_verification = solve_exact_resource_feasibility(
            feasible.schedule_template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache,
            horizon_s=7200,
            max_adjustment_s=0,
            time_limit_s=30,
            disturbance_from_time_s=feasible.schedule_template.heavy_headway_s,
        )
        assert rolling_verification.status == "feasible_verified"

        quality = solve_quality_optimized_resource_feasibility(
            template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache,
            horizon_s=7200,
            initial_adjustment_bound_s=600,
            time_limit_s=30,
        )
        assert quality.status == "feasible_verified"
        quality_diagnostics = quality.diagnostics["quality_optimization"]
        assert quality_diagnostics["minimum_maximum_adjustment_proven"] is True
        minimum_bound = quality_diagnostics["minimum_maximum_adjustment_s"]
        assert quality_diagnostics["lower_infeasible_adjustment_bound_s"] == minimum_bound - 1
        assert quality_diagnostics["total_absolute_adjustment_optimal"] is True
        adjustments = (
            tuple(quality.schedule_template.heavy_departure_adjustments_s)
            + tuple(quality.schedule_template.empty_departure_adjustments_s)
        )
        assert max(abs(value) for value in adjustments) == minimum_bound
        assert sum(abs(value) for value in adjustments) == quality_diagnostics["total_absolute_adjustment_s"]

        quality_infeasible = solve_quality_optimized_resource_feasibility(
            template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache,
            horizon_s=500,
            initial_adjustment_bound_s=100,
            time_limit_s=30,
        )
        assert quality_infeasible.status == "model_infeasible"
        assert quality_infeasible.diagnostics["quality_optimization"]["reason"] == (
            "full_departure_domain_proven_infeasible"
        )

        infeasible = solve_exact_resource_feasibility(
            template, default_scenarios(), case_inputs.resource_model,
            heavy_cache, empty_cache, horizon_s=500, time_limit_s=30,
        )
        assert infeasible.status == "model_infeasible"
        assert "infeasible" in infeasible.proof
        assert infeasible.schedule_template is None

    print("exact resource feasibility smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
