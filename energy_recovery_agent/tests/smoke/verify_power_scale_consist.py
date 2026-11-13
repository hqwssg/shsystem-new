"""场景功率倍率回归测试：配置 consist 后倍率必须仍然生效。

背景
----
两万吨列车改为「12 轴 + 8 轴」双机型重联后，功率上限改由
``locomotive_curves.json`` 各机型持续功率逐台累加（14 400 + 9 600 = 24 000 kW），
不再读 CSV 的 ``max_power_kW``。

副作用：储能规划 ``_apply_train_overrides`` 与联合参数稳健性 ``apply_train_factors``
原先只缩放 ``max_power_kW``。consist 一生效，这两处的功率倍率就被静默忽略
（实测：``traction_power_factor=0.5`` 时上限仍是 24 000 kW），
于是「牵引功率下降 10%」这类情景实际什么都没变，结论会被误读成「功率不敏感」。

修法：``TrainParameters.power_scale``（默认 1.0）参与两种功率上限计算路径，
场景构造时把倍率同时写进 ``power_scale``。

判据
----
1. 默认 ``power_scale=1.0`` 时，功率上限与不设该字段完全一致；
2. 储能规划情景倍率 0.5 → 上限减半，且仿真牵引能耗确实下降；
3. 联合稳健性 ``max_power`` 倍率 0.5 → 上限减半。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joint_parameter_robustness import apply_train_factors  # noqa: E402
from run_dispatch_case import load_case_inputs  # noqa: E402
from storage_planning_mvp import _apply_train_overrides  # noqa: E402
from train_simulator import TrainSimulator  # noqa: E402

DELTA_T_S = 10


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} 失败：{detail}")


def _traction_kwh(simulator: TrainSimulator) -> float:
    return sum(max(0.0, r.power_kW) * DELTA_T_S / 3600.0 for r in simulator.run())


def main() -> int:
    inputs = load_case_inputs(
        ROOT / "data" / "real_shuohuang",
        ROOT / "outputs" / "_smoke_power_scale",
    )
    train = inputs.trains["Heavy"]

    baseline_sim = TrainSimulator(inputs.route, train, delta_t_s=DELTA_T_S)
    baseline_cap = baseline_sim.power_cap_kW()
    baseline_kwh = _traction_kwh(baseline_sim)
    check("默认倍率不改行为", abs(train.power_scale - 1.0) < 1e-12, f"默认值 {train.power_scale}")
    check("基线功率上限为正", baseline_cap > 0.0, f"{baseline_cap}")

    # --- 储能规划情景：traction_power_factor ---
    half = _apply_train_overrides(inputs.trains, {"traction_power_factor": 0.5})["Heavy"]
    half_sim = TrainSimulator(inputs.route, half, delta_t_s=DELTA_T_S)
    check(
        "储能情景功率倍率生效",
        abs(half_sim.power_cap_kW() - baseline_cap * 0.5) < 1.0,
        f"期望 {baseline_cap * 0.5:.0f} kW，实际 {half_sim.power_cap_kW():.0f} kW；"
        "倍率仍只作用于 CSV 的 max_power_kW，被 consist 覆盖",
    )
    half_kwh = _traction_kwh(half_sim)
    check(
        "储能情景能耗随之变化",
        half_kwh < baseline_kwh - 1.0,
        f"半功率 {half_kwh:.0f} kWh 未低于基线 {baseline_kwh:.0f} kWh",
    )

    # --- 联合参数稳健性：max_power ---
    robust = apply_train_factors(inputs.trains, {"max_power": 0.5})["Heavy"]
    robust_sim = TrainSimulator(inputs.route, robust, delta_t_s=DELTA_T_S)
    check(
        "稳健性功率倍率生效",
        abs(robust_sim.power_cap_kW() - baseline_cap * 0.5) < 1.0,
        f"期望 {baseline_cap * 0.5:.0f} kW，实际 {robust_sim.power_cap_kW():.0f} kW",
    )

    print(
        f"场景功率倍率回归：PASS（基线 {baseline_cap:.0f} kW / {baseline_kwh:.0f} kWh，"
        f"半功率 {half_kwh:.0f} kWh）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
