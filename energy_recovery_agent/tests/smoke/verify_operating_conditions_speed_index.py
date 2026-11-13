# 模块功能说明：验证限速空间索引与原始全表扫描在边界、时间窗和随机点上完全等价。

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operating_conditions import (
    OPEN_ENDED_TIME_S,
    OperatingConditions,
    TemporarySpeedRestriction,
    WeatherCondition,
    active_in_time,
    active_weather_at,
    position_in_range,
    speed_limit_kmh_at,
)


def brute_force_speed_limit_kmh_at(
    profile: OperatingConditions,
    route_max_speed_kmh: float,
    position_km: float,
    time_s: int,
    direction: str | None = None,
) -> float:
    """按优化前的全表扫描口径计算参考限速。"""

    speed_limit = route_max_speed_kmh
    for weather in active_weather_at(profile, position_km, time_s):
        if weather.speed_limit_kmh is not None:
            speed_limit = min(speed_limit, float(weather.speed_limit_kmh))
    for restriction in profile.speed_restrictions:
        direction_matches = (
            direction is None
            or restriction.direction == "both"
            or restriction.direction == direction
        )
        if direction_matches and active_in_time(restriction.start_time_s, restriction.end_time_s, time_s) and position_in_range(
            position_km,
            restriction.start_km,
            restriction.end_km,
        ):
            speed_limit = min(speed_limit, float(restriction.speed_limit_kmh))
    return max(5.0, speed_limit)


def main() -> None:
    """覆盖重叠区段、整数边界、动态时间窗和无规则位置。"""

    restrictions = [
        TemporarySpeedRestriction("segment_a", 0.0, 1.0, 75.0),
        TemporarySpeedRestriction("segment_b", 1.0, 2.75, 65.0),
        TemporarySpeedRestriction("overlap", 0.5, 1.5, 55.0, 100, 200),
        TemporarySpeedRestriction("long_range", 0.0, 76.293, 80.0),
        TemporarySpeedRestriction("late", 75.8, 90.2, 45.0, 500, 900),
        TemporarySpeedRestriction("forward_only", 15.0, 25.0, 35.0, direction="forward"),
        TemporarySpeedRestriction("reverse_only", 20.0, 30.0, 40.0, direction="reverse"),
    ]
    profile = OperatingConditions(
        weather_conditions=[
            WeatherCondition(
                "weather",
                start_time_s=250,
                end_time_s=750,
                affected_ranges_km=[(10.0, 20.0)],
                speed_limit_kmh=50.0,
            )
        ],
        speed_restrictions=restrictions,
    )

    points = [
        (0.0, 0), (0.999999, 0), (1.0, 0), (1.5, 99), (1.5, 100),
        (1.5, 200), (1.5, 201), (2.75, 0), (2.750001, 0),
        (10.0, 250), (20.0, 750), (20.000001, 750),
        (75.8, 499), (75.8, 500), (76.293, 900), (90.2, 900),
        (90.200001, OPEN_ENDED_TIME_S), (583.003, 0),
    ]
    rng = random.Random(20260905)
    points.extend((rng.uniform(0.0, 100.0), rng.randint(0, 1200)) for _ in range(2000))

    for direction in (None, "forward", "reverse"):
        for position_km, time_s in points:
            indexed = speed_limit_kmh_at(profile, 120.0, position_km, time_s, direction)
            reference = brute_force_speed_limit_kmh_at(profile, 120.0, position_km, time_s, direction)
            if indexed != reference:
                raise AssertionError(
                    f"限速索引结果不等价: position={position_km}, time={time_s}, "
                    f"direction={direction}, indexed={indexed}, reference={reference}"
                )

    print("operating conditions speed index: PASS")


if __name__ == "__main__":
    main()
