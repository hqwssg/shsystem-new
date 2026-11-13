"""轨迹级指标摘要。"""

from __future__ import annotations

from typing import Mapping

from ..models import EcoDrivingResult


def summarize(result: EcoDrivingResult) -> Mapping[str, float]:
    if not result.samples:
        return {"runtime_s": 0.0, "final_speed_mps": 0.0, "average_speed_mps": 0.0}
    duration = max(result.runtime_s, 1e-9)
    distance = result.samples[-1].position_m
    energy = result.metadata.get("energy", {})
    return {
        "runtime_s": result.runtime_s,
        "final_speed_mps": result.final_speed_mps,
        "average_speed_mps": distance / duration,
        "distance_m": distance,
        **{str(k): float(v) for k, v in energy.items()},
    }
