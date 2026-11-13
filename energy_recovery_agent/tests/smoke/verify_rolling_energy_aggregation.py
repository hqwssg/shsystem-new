# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    ScheduleScore,
    ScheduleTemplate,
    energy_scenario_objective,
    robust_evaluate_schedule,
)


def _score(charge_kwh: float, discharge_kwh: float) -> ScheduleScore:
    """函数 _score：执行该模块中的相关处理逻辑。"""
    return ScheduleScore(
        feasible=True,
        total_cost=0.0,
        headway_deviation=0.0,
        worst_case_cost=0.0,
        worst_case_headway_deviation=0.0,
        scenario_count=1,
        energy_scenario="storage_no_direct",
        battery_charge_kwh=charge_kwh,
        battery_discharge_kwh=discharge_kwh,
        storage_efficiency=0.9,
    )


def test_robust_energy_loss_is_aggregated_per_scenario() -> None:
    """函数 test_robust_energy_loss_is_aggregated_per_scenario：执行该模块中的相关处理逻辑。"""
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(900, 900, 0, 1, 0),
    )
    scenarios = [DisturbanceScenario("charge_only"), DisturbanceScenario("discharge_only")]
    # 两个场景的损失分别为 10 和 0 kWh。若先平均能量流，会得到充电 5、放电 5，
    # 并错误地报告有效损失为零。
    with patch(
        "rolling_optimizer.evaluate_schedule",
        side_effect=[_score(10.0, 0.0), _score(0.0, 10.0)],
    ):
        aggregate = robust_evaluate_schedule(
            schedule,
            scenarios,
            heavy_cache=None,
            empty_cache=None,
            settlement_system=None,
            signaling_system={},
        )
    assert abs(aggregate.effective_regen_loss_kwh - 5.0) < 1e-9
    assert abs(energy_scenario_objective(aggregate) - 5.0) < 1e-9


if __name__ == "__main__":
    test_robust_energy_loss_is_aggregated_per_scenario()
    print("rolling robust energy aggregation verification passed")
