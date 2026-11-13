"""功率上限口径回归测试：控制逻辑与能耗结算必须用同一个功率上限。

背景
----
`control_traction_brake` 原先用「表 10 持续牵引力 × 持续速度 × 台数」反推功率上限，
而主循环里算电能的地方又用 CSV 的 `max_power_kW` 重算了一遍。两者不等时
（例如 4×HXD1 反推 38 400 kW、CSV 写 28 800 kW），牵引力按高值给、电量按低值记，
牵引能耗被系统性低估约 24%。本测试锁死「单一来源」这一不变量。

判据
----
1. `power_cap_kW()` 在配置机车时等于「单台持续功率 × 台数」；
2. 未配置机车时等于 CSV 的 `max_power_kW`；
3. 把 CSV 的 `max_power_kW` 改成荒谬值（1 kW），配置机车时的仿真结果必须完全不变
   —— 若结果变化，说明电能计算又去读了 CSV。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from locomotive_curves import default_curve_bank  # noqa: E402
from run_dispatch_case import load_case_inputs  # noqa: E402
from train_simulator import TrainSimulator  # noqa: E402

DELTA_T_S = 10


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} 失败：{detail}")


def _energy_kwh(simulator: TrainSimulator) -> tuple[float, int]:
    records = simulator.run()
    traction = sum(max(0.0, r.power_kW) * DELTA_T_S / 3600.0 for r in records)
    peak = max((r.power_kW for r in records), default=0.0)
    return traction, peak


def main() -> int:
    inputs = load_case_inputs(
        ROOT / "data" / "real_shuohuang",
        ROOT / "outputs" / "_smoke_power_cap",
    )
    train = inputs.trains["Heavy"]
    bank = default_curve_bank()

    # --- 1. 配置机车时，上限 = Σ(单台持续功率 × 台数) ---
    # 两万吨为 12 轴 + 8 轴双机型重联，单一 locomotive_type × locomotive_count
    # 的写法（14 400 × 2 = 28 800）会算错，必须按编组清单逐机型累加。
    units = train.locomotive_consist or ((train.locomotive_type, train.locomotive_count),)
    expected = 0.0
    for loco_type, count in units:
        per_loco = bank.locomotive_power_kW(loco_type)
        check("单台持续功率可推导", bool(per_loco), f"{loco_type} 缺少持续工况参数")
        expected += float(per_loco) * count
    simulator = TrainSimulator(inputs.route, train, delta_t_s=DELTA_T_S)
    check(
        "配置机车时功率上限",
        abs(simulator.power_cap_kW() - expected) < 1.0,
        f"期望 {expected:.0f} kW，实际 {simulator.power_cap_kW():.0f} kW",
    )

    baseline_kwh, baseline_peak = _energy_kwh(simulator)
    check(
        "实际功率不超过上限",
        baseline_peak <= expected * 1.001,
        f"峰值 {baseline_peak:.0f} kW > 上限 {expected:.0f} kW",
    )

    # --- 2. 未配置机车时回退到 CSV ---
    plain = replace(
        train,
        locomotive_type=None,
        locomotive_count=0,
        # consist 优先级高于 locomotive_type/count，退化为「无机车」时必须一并清空，
        # 否则仍会走特性表累加，测不到 CSV 回退分支。
        locomotive_consist=None,
        mass_tons=float(train.vehicle_mass_tons or train.mass_tons),
        vehicle_mass_tons=None,
        max_power_kW=20000.0,
    )
    plain_sim = TrainSimulator(inputs.route, plain, delta_t_s=DELTA_T_S)
    check(
        "无机车回退 CSV 功率",
        abs(plain_sim.power_cap_kW() - 20000.0) < 1e-6,
        f"实际 {plain_sim.power_cap_kW():.0f} kW",
    )

    # --- 3. 关键不变量：配置机车时 CSV 功率不得影响结果 ---
    poisoned = replace(train, max_power_kW=1.0)
    poisoned_sim = TrainSimulator(inputs.route, poisoned, delta_t_s=DELTA_T_S)
    poisoned_kwh, _peak = _energy_kwh(poisoned_sim)
    check(
        "CSV 功率不干扰能耗结算",
        abs(poisoned_kwh - baseline_kwh) < 1e-6,
        f"基准 {baseline_kwh:.1f} kWh，篡改 CSV 后 {poisoned_kwh:.1f} kWh；"
        "能耗计算仍在读 CSV 的 max_power_kW",
    )

    print(
        f"功率口径回归：PASS（{train.name} 上限 {expected:.0f} kW，"
        f"牵引能耗 {baseline_kwh:.0f} kWh，峰值 {baseline_peak:.0f} kW）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
