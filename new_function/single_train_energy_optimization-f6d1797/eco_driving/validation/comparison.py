"""baseline 与 optimized 的统一指标对比。"""

from __future__ import annotations

from typing import Mapping

from ..metrics.eco_driving_metrics import summarize


def compare(baseline, optimized) -> Mapping[str, object]:
    b = dict(summarize(baseline))
    o = dict(summarize(optimized))
    keys = sorted(set(b) | set(o))
    delta = {key: float(o.get(key, 0.0)) - float(b.get(key, 0.0)) for key in keys}
    delta_percent = {
        key: (
            100.0 * delta[key] / (
                abs(float(b.get(key, 0.0)))
                if abs(float(b.get(key, 0.0))) >= 1.0
                else 1.0
            )
            if abs(float(b.get(key, 0.0))) > 1e-12
            else None
        )
        for key in keys
    }
    baseline_net = float(b.get("net_energy_kwh", 0.0))
    optimized_net = float(o.get("net_energy_kwh", 0.0))
    baseline_feasible = bool(
        baseline.metadata.get("feasible_candidate", baseline.metadata.get("reached_end", True))
    )
    optimized_feasible = bool(
        optimized.metadata.get("feasible_candidate", optimized.metadata.get("reached_end", True))
    )
    comparison_feasible = baseline_feasible and optimized_feasible
    saving = baseline_net - optimized_net if comparison_feasible else None
    return {
        "baseline": b,
        "optimized": o,
        "delta": delta,
        "delta_percent": delta_percent,
        "baseline_feasible": baseline_feasible,
        "optimized_feasible": optimized_feasible,
        "comparison_feasible": comparison_feasible,
        "energy_saving_kwh": saving,
        "energy_saving_percent": (
            100.0 * saving / abs(baseline_net)
            if saving is not None and abs(baseline_net) > 1e-12
            else None
        ),
    }
