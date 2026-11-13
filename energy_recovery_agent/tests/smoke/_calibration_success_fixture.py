# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv


FIELDS = [
    "sample_id",
    "trainid",
    "realtime_trainid",
    "travel_direction",
    "start_station",
    "end_station",
    "distance_km",
    "duration_s",
    "avg_speed_kmh",
    "meter_traction_energy_raw",
    "prototype_traction_energy_raw",
    "alignment_status",
    "estimate_status",
    "calibration_status",
]


def write_nonzero_alignment_fixture(path: Path) -> Path:
    """Deterministic non-zero alignment rows for smoke tests.

    Geometry/time fields are chosen so aggregated A/B rows land in fit_core under the
    production fit policy (non-short-stop, non-low-intensity, aggregated_ab).
    """
    rows: list[dict[str, str]] = []
    definitions = (
        ("down", "58A+58B", 1.20),
        ("up", "151A+151B", 0.80),
        ("down", "58", 1.10),
        ("up", "151", 0.90),
    )
    # distance=15km、duration=1200s，因此速度为 45km/h；按测试夹具比例，强度保持 >=5。
    distance_km = 15.0
    duration_s = 1200.0
    avg_speed_kmh = distance_km / duration_s * 3600.0
    for direction, realtime_trainid, ratio in definitions:
        for index in range(30):
            prototype = 100.0 + index
            rows.append(
                {
                    "sample_id": f"{direction}-{realtime_trainid}-{index:02d}",
                    "trainid": realtime_trainid.split("A", 1)[0],
                    "realtime_trainid": realtime_trainid,
                    "travel_direction": direction,
                    "start_station": "A" if direction == "down" else "B",
                    "end_station": "B" if direction == "down" else "A",
                    "distance_km": f"{distance_km:.6f}".rstrip("0").rstrip("."),
                    "duration_s": f"{duration_s:.6f}".rstrip("0").rstrip("."),
                    "avg_speed_kmh": f"{avg_speed_kmh:.6f}".rstrip("0").rstrip("."),
                    "meter_traction_energy_raw": f"{prototype * ratio:.6f}",
                    "prototype_traction_energy_raw": f"{prototype:.6f}",
                    "alignment_status": "aligned",
                    "estimate_status": "prototype_estimate_not_calibrated",
                    "calibration_status": "usable_high_confidence",
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path
