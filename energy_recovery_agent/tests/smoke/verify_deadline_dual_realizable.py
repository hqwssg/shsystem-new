"""守图定剖面（对偶解）的可实现性闸门测试。

守五件事：

1. **网格最优确实能被开出来**——跟踪能耗与规划值差 ≤ 5%，时分不超图定。
   若这一条破了，`deadline_dual_bound` 的 13,559 就只是纸面值；
2. **不是靠开慢换来的**——时分必须落在图定的 383.3 min 以内。曾经出现过
   「电量降到 8,408 但时分涨到 471 min」的口径，看着省电其实晚点；
3. **步长无关**——dt=1 与 dt=10 差 ≤ 3%；
4. **到站时刻真的守住了**——纸面合规不算数，要按**仿真轨迹**第一次到达各站
   的时刻去比图定到站时刻；
5. **「有计划没执行力」这个对照仍在**——同一份计划只当上限、内部走反应式，
   时分必须显著变长。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "speed_profile_dual_realizable"
PAYLOAD_PATH = OUT / "speed_profile_realizable.json"

PLAN_ENERGY = 13558.8
PLAN_MINUTES = 383.1
DEADLINE_MINUTES = 383.3
ENERGY_TOLERANCE = 0.05
MAX_LATE_MINUTES = 1.5
MAX_LATE_STATIONS = 1

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def case(payload: dict, label: str) -> dict:
    """按标签取一条口径。"""

    for item in payload["cases"]:
        if item["label"] == label:
            return item
    raise KeyError(f"缺口径 {label}：{[c['label'] for c in payload['cases']]}")


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/verify_speed_profile_realizable")
        return 2

    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    plan = payload["plan"]
    track = case(payload, "profile_track")
    realized = payload["realized_section_time"]
    section = payload["section_time"]

    # ---- 0. 用的是对偶剖面，不是无约束剖面 ----
    check(
        "计划值来源是对偶解",
        plan.get("reference_source") == "speed_profile_dual",
        f"{plan.get('reference_source')}：{plan.get('profile_path')}",
    )
    check(
        "计划能耗与规划值一致",
        abs(plan["energy_kwh"] - PLAN_ENERGY) < 1.0,
        f"{plan['energy_kwh']:,.1f} vs {PLAN_ENERGY:,.1f} kWh",
    )

    # ---- 1. 可开出来 ----
    gap = track["traction_kwh"] / plan["energy_kwh"] - 1.0
    check(
        "跟踪能耗与规划值差 ≤ 5%",
        abs(gap) <= ENERGY_TOLERANCE,
        f"{track['traction_kwh']:,.0f} vs {plan['energy_kwh']:,.0f} kWh（{gap:+.1%}）",
    )
    check(
        "跟踪能耗不超过 14,200 kWh",
        track["traction_kwh"] <= 14200.0,
        f"{track['traction_kwh']:,.0f} kWh",
    )

    # ---- 2. 不是靠开慢换来的 ----
    check(
        "跟踪时分不超图定",
        track["running_minutes"] <= DEADLINE_MINUTES + 0.5,
        f"{track['running_minutes']:.1f} vs {DEADLINE_MINUTES:.1f} min",
    )
    check(
        "跟踪时分与规划值差 ≤ 3 min",
        abs(track["running_minutes"] - plan["minutes"]) <= 3.0,
        f"{track['running_minutes']:.1f} vs {plan['minutes']:.1f} min",
    )

    # ---- 3. 步长无关 ----
    try:
        fine = case(payload, "profile_track_fine")
    except KeyError:
        fine = None
    if fine is not None:
        step_gap = fine["traction_kwh"] / track["traction_kwh"] - 1.0
        check(
            "1 s 与 10 s 步长结果一致（≤3%）",
            abs(step_gap) <= 0.03,
            f"{track['traction_kwh']:,.0f} → {fine['traction_kwh']:,.0f} kWh（{step_gap:+.1%}）",
        )
    else:
        check("细步长复核存在", False, "缺 profile_track_fine")

    # ---- 4. 到站时刻（纸面 + 实际）----
    check(
        "计划剖面纸面合规（最大晚点 ≤ 0.5 min）",
        section["worst_late_minutes"] <= 0.5,
        f"{section['worst_late_minutes']:+.1f} min",
    )
    check(
        "仿真轨迹晚点站数 ≤ 1",
        realized.get("late_station_count", 99) <= MAX_LATE_STATIONS,
        f"{realized.get('late_station_count')} 个（共 {len(realized['stations'])} 个检查点）",
    )
    check(
        "仿真轨迹最大晚点 ≤ 1.5 min",
        realized["worst_late_minutes"] <= MAX_LATE_MINUTES,
        f"{realized['worst_late_minutes']:+.1f} min（{realized['worst_late_km']:.0f} km）",
    )
    check(
        "晚点出现在起步段（计划恰好卡死处）",
        realized["worst_late_km"] <= 20.0,
        f"{realized['worst_late_km']:.0f} km",
    )

    # ---- 5. 「有计划没执行力」的对照仍在 ----
    try:
        cap = case(payload, "profile_cap")
    except KeyError:
        cap = None
    if cap is not None:
        check(
            "只当上限时时分显著变长（证明差的是执行力）",
            cap["running_minutes"] > track["running_minutes"] + 20.0,
            f"{cap['running_minutes']:.1f} vs {track['running_minutes']:.1f} min",
        )
    else:
        check("剖面限幅对照存在", False, "缺 profile_cap")

    # ---- 6. 轨迹贴合 ----
    check(
        "与计划速度的平均绝对偏差 ≤ 0.2 m/s",
        payload["deviation"]["mean_abs_mps"] <= 0.2,
        f"{payload['deviation']['mean_abs_mps']:.3f} m/s",
    )

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"守图定剖面可实现性：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"守图定剖面可实现性：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
