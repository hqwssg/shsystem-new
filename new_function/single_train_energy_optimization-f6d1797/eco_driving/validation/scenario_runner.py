"""运行 baseline/optimized 场景对比。"""

from __future__ import annotations

from ..io.data_loader import load_eco_driving_data
from ..optimizer.baseline import run_baseline
from ..optimizer.eco_driving_optimizer import EcoDrivingOptimizer
from .comparison import compare
from .scenarios import default_scenarios


def run_scenarios(scenarios=None, dt: float = 1.0, beam_width: int = 60):
    data = load_eco_driving_data()
    optimizer = EcoDrivingOptimizer(data.railway, data.train, data.traction_limit_n, beam_width=beam_width, dt=dt)
    rows = []
    for scenario in scenarios or default_scenarios():
        baseline = run_baseline(scenario, data.railway, data.train, dt=dt, traction_limit_n=data.traction_limit_n)
        optimized = optimizer.optimize(scenario)
        result = compare(baseline, optimized)
        result["scenario"] = scenario.description
        result["baseline_result"] = baseline
        result["optimized_result"] = optimized
        rows.append(result)
    return rows
