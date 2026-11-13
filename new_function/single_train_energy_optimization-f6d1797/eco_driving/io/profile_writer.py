"""速度曲线 CSV 输出。"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import EcoDrivingResult


FIELDS = (
    "position_m", "time_s", "speed_mps", "speed_kmh", "gradient", "curve_radius",
    "speed_limit", "acceleration", "mode", "traction_force", "braking_force",
    "traction_power", "braking_power", "cumulative_traction_energy",
    "cumulative_regenerative_energy", "cumulative_net_energy",
)


def write_profile_csv(result: EcoDrivingResult, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for sample in result.samples:
            writer.writerow({
                "position_m": sample.position_m,
                "time_s": sample.time_s,
                "speed_mps": sample.speed_mps,
                "speed_kmh": sample.speed_kmh,
                "gradient": sample.gradient_per_mille,
                "curve_radius": sample.curve_radius_m,
                "speed_limit": sample.speed_limit_mps,
                "acceleration": sample.acceleration_mps2,
                "mode": sample.mode.value,
                "traction_force": sample.traction_force_n,
                "braking_force": sample.braking_force_n,
                "traction_power": sample.traction_power_w,
                "braking_power": sample.braking_power_w,
                "cumulative_traction_energy": sample.cumulative_traction_energy_j,
                "cumulative_regenerative_energy": sample.cumulative_regenerative_energy_j,
                "cumulative_net_energy": sample.cumulative_net_energy_j,
            })
    return path
