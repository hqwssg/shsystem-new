# 模块功能说明：验证稳健可行性修复能够发现粗粒度搜索遗漏的窄相位窗口。

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    ScheduleTemplate,
    TemplateSearchConfig,
    default_scenarios,
    generate_schedule,
    resource_feasibility_repair_templates,
    targeted_resource_feasibility_repair_templates,
    template_key,
)
from recovery_work_budget import RecoveryWorkBudget


def main() -> int:
    """构造仅2760秒相位可行的检查器，验证60秒修复扫描顺序。"""

    base = ScheduleTemplate(
        heavy_headway_s=3300,
        empty_headway_s=2700,
        heavy_empty_phase_s=2600,
        heavy_count=3,
        empty_count=3,
    )
    config = TemplateSearchConfig(
        population_size=4,
        generations=1,
        max_phase_s=5400,
        enable_storage_preset_search=False,
    )

    def fake_resource_check(schedule, *_args, **_kwargs):
        """仅把探针应命中的窄相位窗口判为资源可行。"""

        first_gap_s = schedule.empty_departures_s[0] - schedule.heavy_departures_s[0]
        feasible = first_gap_s in {2640, 2760, 2880}
        return SimpleNamespace(feasible=feasible)

    global_budget = RecoveryWorkBudget(full_limit=2, resource_limit=1000, candidate_limit=1000,
                                       wall_limit_s=30, solver_limit_s=2)
    with patch(
        "rolling_optimizer.check_schedule_resources",
        side_effect=fake_resource_check,
    ) as global_checks:
        seeds, diagnostics = resource_feasibility_repair_templates(
            base,
            config,
            default_scenarios(),
            resource_model=SimpleNamespace(),
            heavy_cache=SimpleNamespace(),
            empty_cache=SimpleNamespace(),
            schedule_factory=generate_schedule,
            required_heavy_count=3,
            required_empty_count=3,
            work_budget=global_budget,
        )
    assert global_budget.resource_count == global_checks.call_count

    assert len(seeds) == 1
    assert seeds[0].heavy_headway_s == 3300
    assert seeds[0].empty_headway_s == 3300
    assert seeds[0].heavy_empty_phase_s == 2760
    assert diagnostics["resource_feasible_seed_count"] == 1
    assert diagnostics["evaluated_template_count"] < 10
    assert diagnostics["targeted_local_repair"]["repair_level"] == "level_1_under_16"

    local_base = ScheduleTemplate(
        heavy_headway_s=2400,
        empty_headway_s=2400,
        heavy_empty_phase_s=840,
        heavy_count=6,
        empty_count=6,
    )

    def fake_local_resource_check(schedule, *_args, **_kwargs):
        """仅当第一列空车采用120秒局部错峰时消除构造冲突。"""

        adjustments = tuple(schedule.template.empty_departure_adjustments_s)
        feasible = bool(adjustments) and adjustments[0] == 120
        conflicts = [] if feasible else [SimpleNamespace(
            train_a="E001",
            train_b="H001",
            overlap_duration_s=35.0,
        )]
        return SimpleNamespace(
            feasible=feasible,
            conflicts=conflicts,
            conflict_count=len(conflicts),
            overlap_violation_s=0.0 if feasible else 35.0,
        )

    local_budget = RecoveryWorkBudget(full_limit=2, resource_limit=1000, candidate_limit=1000,
                                      wall_limit_s=30, solver_limit_s=2)
    with patch(
        "rolling_optimizer.check_schedule_resources",
        side_effect=fake_local_resource_check,
    ) as local_checks:
        local_seeds, local_diagnostics = targeted_resource_feasibility_repair_templates(
            [local_base],
            default_scenarios(),
            resource_model=SimpleNamespace(),
            heavy_cache=SimpleNamespace(),
            empty_cache=SimpleNamespace(),
            schedule_factory=generate_schedule,
            required_heavy_count=6,
            required_empty_count=6,
            work_budget=local_budget,
        )
    assert local_budget.resource_count == local_checks.call_count  # 含最终排名明细的额外复核

    assert len(local_seeds) == 1
    assert local_seeds[0].empty_departure_adjustments_s == (120, 0, 0, 0, 0, 0)
    assert local_diagnostics["resource_feasible_seed_count"] == 1
    assert local_diagnostics["best_ranked_templates"]
    assert local_diagnostics["best_ranked_templates"][0]["scenario_details"]
    assert local_diagnostics["repair_level"] == "level_1_under_16"
    assert template_key(local_seeds[0]) != template_key(local_base)
    assert generate_schedule(local_seeds[0]).empty_departures_s[0] == 960

    level2_base = ScheduleTemplate(
        heavy_headway_s=2400,
        empty_headway_s=2400,
        heavy_empty_phase_s=840,
        heavy_count=8,
        empty_count=8,
    )
    captured_level2 = {}

    def fake_level2_repair(*args, **kwargs):
        """记录16列车阈值选择，避免在阈值测试中重复执行完整束搜索。"""

        captured_level2.update(kwargs)
        return [], {
            "triggered": True,
            "repair_level": "level_2_16_plus",
            "total_train_count": 16,
            "resource_feasible_seed_count": 0,
        }

    def always_blocked_resource_check(*_args, **_kwargs):
        return SimpleNamespace(
            feasible=False,
            conflicts=[],
            conflict_count=1,
            overlap_violation_s=1.0,
        )

    with patch(
        "rolling_optimizer.check_schedule_resources",
        side_effect=always_blocked_resource_check,
    ), patch(
        "rolling_optimizer.targeted_resource_feasibility_repair_templates",
        side_effect=fake_level2_repair,
    ):
        _level2_seeds, level2_diagnostics = resource_feasibility_repair_templates(
            level2_base,
            config,
            default_scenarios(),
            resource_model=SimpleNamespace(),
            heavy_cache=SimpleNamespace(),
            empty_cache=SimpleNamespace(),
            schedule_factory=generate_schedule,
            required_heavy_count=8,
            required_empty_count=8,
        )

    assert level2_diagnostics["targeted_local_repair"]["repair_level"] == "level_2_16_plus"
    assert captured_level2["adjustment_step_s"] == 30
    assert captured_level2["max_absolute_adjustment_s"] == 600
    assert captured_level2["max_iterations"] == 16
    assert captured_level2["beam_width"] == 6
    print("dispatch feasibility repair smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
