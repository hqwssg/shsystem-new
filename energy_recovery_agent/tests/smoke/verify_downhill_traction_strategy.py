"""下坡牵引策略（``downhill_traction_fraction``）回归测试。

锁住四件事：

1. 输入契约：默认 1.0 表示「不区分坡向」，边界 0/1 必须接受，越界必须报错；
2. 默认值不改行为：显式传 1.0 与不传 ``brake_strategy`` 必须逐位一致
   —— 这是新参数最容易犯的错（悄悄改了基线，而所有历史结论都不知道）；
3. ``0`` 的物理含义：剩余力为正（重力净驱动、惰行会加速）的步，牵引必须恒为 0；
4. 单调性：份额越小，牵引电量越小、耗时不减。反过来就说明注入点写错了方向。

第 3 条是本参数唯一实质性的断言。判据必须用 ``calculate_forces`` 算剩余力，
不能用「车头所在坡段的坡度」：列车长 2.6 km，控制律用的是沿全列车长的平均坡度，
车头在陡下坡上时车尾可能还在爬坡——按车头坡度判会得到一堆假违规。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "real_shuohuang"
MAIN_OD_KM = 396.0

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def test_contract() -> None:
    from train_simulator import BrakeStrategy

    check(
        "默认下坡牵引份额为 1.0（不区分坡向）",
        abs(BrakeStrategy().downhill_traction_fraction - 1.0) < 1e-12,
        f"实际 {BrakeStrategy().downhill_traction_fraction}",
    )
    for level in (0.0, 1.0):
        try:
            BrakeStrategy(downhill_traction_fraction=level)
        except ValueError as exc:  # pragma: no cover - 边界值必须接受
            check(f"接受边界份额 {level}", False, str(exc))
        else:
            check(f"接受边界份额 {level}", True)
    for label, bad in (
        ("拒绝负份额", -0.01),
        ("拒绝超过 1 的份额", 1.01),
        ("拒绝 NaN", math.nan),
        ("拒绝 inf", math.inf),
    ):
        try:
            BrakeStrategy(downhill_traction_fraction=bad)
        except ValueError:
            check(label, True)
        else:
            check(label, False, "未抛出 ValueError")


def _run(fraction: Optional[float], delta_t: int = 10):
    """跑 396 km 工况，返回 (route, train, records)。``fraction=None`` 表示不传策略。"""

    from run_dispatch_case import load_case_inputs
    from train_simulator import BrakeStrategy, TrainSimulator
    from tools.validate_section_times import (
        TIER_2W, _sections, _stations, build_schedule, load_dwell_plan,
    )

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_strategy_smoke")
    schedule = build_schedule(
        _stations(), _sections(), "forward", TIER_2W,
        dwell_plan=load_dwell_plan("all"), label="Heavy",
    )
    strategy = None if fraction is None else BrakeStrategy(
        electrical_level=0.48, downhill_traction_fraction=fraction
    )
    simulator = TrainSimulator(
        inputs.route, inputs.trains["Heavy"], delta_t_s=delta_t,
        schedule=schedule, brake_strategy=strategy,
    )
    return inputs.route, inputs.trains["Heavy"], simulator.run()


def _totals(records, delta_t: int = 10) -> Dict[str, float]:
    run = [r for r in records if r.position_km <= MAIN_OD_KM]
    traction = sum(max(0.0, r.power_kW) * delta_t / 3600.0 for r in run)
    regen = sum(max(0.0, -r.power_kW) * delta_t / 3600.0 for r in run)
    return {
        "traction_kwh": round(traction, 3),
        "regen_kwh": round(regen, 3),
        "minutes": round(run[-1].time_s / 60.0, 3),
    }


def test_default_is_identity() -> None:
    """显式 1.0 必须与「不传策略」逐位一致。"""

    baseline = _totals(_run(None)[2])
    explicit = _totals(_run(1.0)[2])
    for key, label in (
        ("traction_kwh", "牵引电量"),
        ("regen_kwh", "再生电量"),
        ("minutes", "运行时分"),
    ):
        check(
            f"显式 1.0 与默认的{label}逐位一致",
            baseline[key] == explicit[key],
            f"{baseline[key]} vs {explicit[key]}",
        )


def test_zero_forbids_traction_on_downhill() -> None:
    """份额为 0 时，剩余力为正（重力净驱动）的步不得出现牵引。"""

    from train_simulator import calculate_forces

    route, train, records = _run(0.0)
    violations: List[str] = []
    checked_steps = 0
    for record in records:
        if record.position_km > MAIN_OD_KM:
            break
        rolling_kN, gradient_kN, _ = calculate_forces(
            train, route, record.position_km, record.speed_mps
        )
        residual = -(rolling_kN + gradient_kN)
        if residual <= 0.0:
            continue
        checked_steps += 1
        if record.traction_kN > 1e-9:
            violations.append(
                f"km {record.position_km:.2f} 剩余力 {residual:+.0f} kN "
                f"牵引 {record.traction_kN:.1f} kN"
            )
    check(
        "0 份额下重力净驱动时牵引恒为 0",
        checked_steps > 100 and not violations,
        f"检查 {checked_steps} 步，违规 {len(violations)} 处：{violations[:3]}",
    )


def test_monotonicity() -> None:
    """份额越小，牵引越小、耗时不减。"""

    full = _totals(_run(1.0)[2])
    half = _totals(_run(0.5)[2])
    zero = _totals(_run(0.0)[2])

    check(
        "牵引电量随份额单调下降",
        full["traction_kwh"] > half["traction_kwh"] > zero["traction_kwh"],
        f"1.0={full['traction_kwh']:,.0f} 0.5={half['traction_kwh']:,.0f} "
        f"0.0={zero['traction_kwh']:,.0f}",
    )
    check(
        "运行时分随份额单调不减",
        full["minutes"] <= half["minutes"] <= zero["minutes"],
        f"1.0={full['minutes']:.0f} 0.5={half['minutes']:.0f} 0.0={zero['minutes']:.0f}",
    )
    # 份额只收缩牵引上限，不应把车卡死——否则说明注入点影响了别的分支。
    check(
        "0 份额仍能跑完全程",
        zero["minutes"] < 900.0,
        f"{zero['minutes']:.0f} min",
    )
    check(
        "0 份额仍需要牵引（上坡未受影响）",
        zero["traction_kwh"] > 1000.0,
        f"{zero['traction_kwh']:,.0f} kWh",
    )


def main() -> int:
    print("下坡牵引策略回归")
    test_contract()
    test_default_is_identity()
    test_zero_forbids_traction_on_downhill()
    test_monotonicity()
    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
