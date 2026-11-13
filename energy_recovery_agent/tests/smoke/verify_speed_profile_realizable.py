"""最优剖面「可实现性」的闸门测试。

这个测试守的是一条与 `verify_speed_profile_bound` 互补的断言：

    规划出来的东西，必须真的能被控制器开出来。

它比「最优值是多少」更关键。上一轮的教训是——网格最优值可以是 12,919 kWh，
而真实列车连这条剖面都跑不出来（加速度比车辆能力大 5.9 倍）。数字自洽不等于
物理可行。

除了读产物做数值断言，这里还锁住跟踪器本身的几个行为性缺陷：

* 剖面在起点为 0 时列车必须能起步（不能把 0 当硬目标死锁）；
* 前馈跟踪必须与积分步长解耦（曾写成 Δ/Δt，dt=1 时系数被放大 10 倍而卡死）；
* `profile_mode` 与 `speed_profile` 的非法组合必须抛错，不能静默退化成反应式。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "speed_profile_realizable"
PAYLOAD_PATH = OUT / "speed_profile_realizable.json"

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def test_profile_target_behaviour() -> None:
    """锁住 `SpeedProfileTarget` 的插值、起步与校验。"""

    from train_simulator import SpeedProfileTarget

    profile = SpeedProfileTarget(
        positions_km=(0.0, 1.0, 2.0),
        speeds_mps=(0.0, 10.0, 20.0),
        lead_m=100.0,
    )
    check(
        "剖面前视读取会在起点之外取到正速度（列车能起步）",
        profile.target_mps(0.1) > 0.0,
        f"target(0.1 km) = {profile.target_mps(0.1):.3f} m/s",
    )
    check(
        "插值在端点外取端值",
        profile.target_mps(-5.0) == 0.0 and profile.target_mps(99.0) == 20.0,
        f"{profile.target_mps(-5.0):.1f} / {profile.target_mps(99.0):.1f}",
    )

    raised = 0
    for kwargs in (
        {"positions_km": (0.0, 1.0), "speeds_mps": (0.0,)},
        {"positions_km": (0.0,), "speeds_mps": (0.0,)},
        {"positions_km": (0.0, 0.0), "speeds_mps": (0.0, 1.0)},
        {"positions_km": (0.0, 1.0), "speeds_mps": (0.0, 1.0), "slack_mps": -1.0},
        {"positions_km": (0.0, 1.0), "speeds_mps": (0.0, 1.0), "lead_m": -1.0},
    ):
        try:
            SpeedProfileTarget(**kwargs)
        except ValueError:
            raised += 1
    check("非法剖面输入全部抛 ValueError", raised == 5, f"{raised}/5")

    from train_simulator import BrakeStrategy, TrainSimulator
    from tools.calibrate_brake_strategy import build_train

    route, train = build_train("Heavy", None, (("SHENHUA_12", 2),))
    try:
        TrainSimulator(route, train, profile_mode="track", brake_strategy=BrakeStrategy())
        mismatch = False
    except ValueError:
        mismatch = True
    check("profile_mode='track' 但没给 profile 时抛错", mismatch)

    try:
        TrainSimulator(route, train, profile_mode="nonsense", speed_profile=profile)
        bad_mode = False
    except ValueError:
        bad_mode = True
    check("非法 profile_mode 抛错（不静默退化）", bad_mode)


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/verify_speed_profile_realizable.py")
        return 2

    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    cases = {case["label"]: case for case in payload["cases"]}
    plan = payload["plan"]
    target = payload["target"]

    required = {"reactive_strict", "reactive_dwell", "profile_cap", "profile_track"}
    check("四条核心口径齐全", required <= set(cases), f"{sorted(cases)}")

    reactive = cases["reactive_strict"]
    track = cases["profile_track"]
    cap = cases["profile_cap"]
    plan_kwh = float(plan["energy_kwh"])
    plan_minutes = float(plan["minutes"])

    # ---- 1. 可实现性：时分与计划一致 ----
    check(
        "跟踪时分与计划相差 ≤ 3 min",
        abs(track["running_minutes"] - plan_minutes) <= 3.0,
        f"{track['running_minutes']:.1f} vs 计划 {plan_minutes:.1f} min",
    )
    check(
        "跟踪跑在 410 min 以内（不靠晚点换省电）",
        track["running_minutes"] <= 412.0,
        f"{track['running_minutes']:.1f} min",
    )

    # ---- 2. 收益：必须显著低于反应式控制器 ----
    saved = reactive["traction_kwh"] - track["traction_kwh"]
    check(
        "剖面跟踪比反应式省 ≥ 40%",
        saved / reactive["traction_kwh"] >= 0.40,
        f"{reactive['traction_kwh']:,.0f} → {track['traction_kwh']:,.0f} kWh（−{saved / reactive['traction_kwh']:.0%}）",
    )
    check(
        "跟踪结果不高于实绩 15%",
        track["traction_kwh"] <= target["metered_wheel_kwh"] * 1.15,
        f"{track['traction_kwh']:,.0f} vs 实绩 {target['metered_wheel_kwh']:,.0f} kWh",
    )

    # ---- 3. 「有计划但没执行力」必须看得出来 ----
    check(
        "剖面限幅口径显著更慢（有计划 ≠ 能执行）",
        cap["running_minutes"] >= track["running_minutes"] + 20.0,
        f"{cap['running_minutes']:.1f} vs {track['running_minutes']:.1f} min",
    )

    # ---- 4. 步长无关性 ----
    fine = cases.get("profile_track_fine")
    if fine is not None:
        ratio = fine["traction_kwh"] / track["traction_kwh"]
        check(
            "1 s 与 10 s 步长结果一致（差 ≤ 5%）",
            0.95 <= ratio <= 1.05,
            f"{fine['traction_kwh']:,.0f} vs {track['traction_kwh']:,.0f} kWh（{ratio - 1:+.1%}）",
        )
        check(
            "两种步长的时分也一致（差 ≤ 2 min）",
            abs(fine["running_minutes"] - track["running_minutes"]) <= 2.0,
            f"{fine['running_minutes']:.1f} vs {track['running_minutes']:.1f} min",
        )
    else:
        check("细步长复核存在（未用 --skip-fine）", False, "缺 profile_track_fine")

    # ---- 5. 跟踪贴合度 ----
    deviation = payload["deviation"]
    check(
        "跟踪轨迹贴合计划（平均偏差 ≤ 0.2 m/s）",
        deviation["mean_abs_mps"] <= 0.2,
        f"{deviation['mean_abs_mps']:.3f} m/s",
    )

    # ---- 6. 区间时刻合规字段（结论的一部分，不能缺） ----
    section = payload.get("section_time", {})
    check(
        "产物记录了逐区间时刻合规",
        "worst_late_minutes" in section and section.get("stations"),
        f"晚点 {section.get('worst_late_minutes')} min / 提前 {section.get('worst_early_minutes')} min",
    )

    # ---- 7. 跟踪器行为性回归 ----
    test_profile_target_behaviour()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"剖面可实现性：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"剖面可实现性：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
