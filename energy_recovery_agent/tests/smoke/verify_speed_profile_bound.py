"""最优剖面（网格最优参考）的闸门测试。

这组断言在 2026-11-06 全面重写过，原因值得记下来：**上一版测试锁住的是
一个由 bug 得出的结论**。它断言「最优值仍比实绩高 10% 以上，所以物理量偏大」，
而那个 10% 来自三处实现错误（加速度上限凭经验取大 5.9 倍、加减速窗口方向
写反、阻力固定在 15 m/s）。测试通过得越理直气壮，错误结论就越难被推翻。

所以现在断言分两类：

1. **方法学不变量**——不管结论怎么变都必须成立（前沿单调、剖面不超限速、
   最优值必须显著低于反应式控制器）。
2. **针对具体 bug 的回归**——每一条都对应一次真实踩坑，改回去立刻红：
   * 加速度上限必须从列车模型反算（不再是 0.35 那种经验值）；
   * 剖面隐含的加速度/减速度不得越界（锁住 a_acc/a_brk 用反）；
   * 网格分辨率不足时必须抛错，而不是静默假死在某个速度上；
   * 阻力必须随速度变化（剖面里 basic_resistance_kN 不能是常数）。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "speed_profile_bound"
BOUND_PATH = OUT / "speed_profile_bound.json"
FRONTIER_PATH = OUT / "frontier.csv"
PROFILE_PATH = OUT / "optimal_speed_profile.csv"

METERED_WHEEL_KWH = 10874.0
METERED_MINUTES = 410.0

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def test_grid_resolution_guard() -> None:
    """锁住「网格分辨率不足会静默假死」这个坑。"""

    from tools.plan_speed_profile import Grid, check_grid_resolution

    coarse = Grid(
        xs_km=np.linspace(0.0, 1.0, 10),
        v_grid=np.arange(0.0, 22.0 + 0.25, 0.5),
        v_limit=np.full(10, 22.0),
        rb_coeffs=np.zeros((3, 10)),
        rg_kN=np.zeros(10),
        m_eff_kg=1.0,
        ds_m=100.0,
    )
    try:
        # dv=0.5 m/s、a=0.005 m/s² 时 2·v·dv−dv² 远大于 2·a·ds，
        # 高速度段任何向上转移都不合法，DP 会假死在 43.2 km/h。
        check_grid_resolution(coarse, 0.005)
        raised = False
    except ValueError:
        raised = True
    check("网格分辨率不足时抛错（不静默假死）", raised)

    fine = Grid(
        xs_km=np.linspace(0.0, 1.0, 10),
        v_grid=np.arange(0.0, 22.0 + 0.125, 0.25),
        v_limit=np.full(10, 22.0),
        rb_coeffs=np.zeros((3, 10)),
        rg_kN=np.zeros(10),
        m_eff_kg=1.0,
        ds_m=100.0,
    )
    try:
        check_grid_resolution(fine, 0.0595)
        ok = True
    except ValueError:
        ok = False
    check("分辨率足够时不误报", ok)


def test_resistance_varies_with_speed() -> None:
    """锁住「阻力固定在参考速度」这个坑。"""

    from tools.calibrate_brake_strategy import build_train
    from tools.plan_speed_profile import build_grid

    route, train = build_train("Heavy", None, (("SHENHUA_12", 2),))
    grid = build_grid(route, train, 100.0, 0.25)
    index = len(grid.xs_km) // 2
    low = float(grid.resistance_kN(index, 5.0))
    high = float(grid.resistance_kN(index, 20.0))
    check(
        "基本阻力随速度上升（w0 = a + b·v + c·v²）",
        high > low * 1.05,
        f"5 m/s {low:.1f} kN → 20 m/s {high:.1f} kN",
    )
    from train_simulator import calculate_forces

    reference = calculate_forces(train, route, float(grid.xs_km[index]), 17.0, 0)[0]
    fitted = float(grid.resistance_kN(index, 17.0))
    check(
        "二次拟合与模型逐点一致（误差 < 0.5%）",
        abs(fitted - reference) <= max(0.005 * abs(reference), 0.5),
        f"拟合 {fitted:.2f} vs 模型 {reference:.2f} kN",
    )


def main() -> int:
    """跑全部断言。"""

    if not BOUND_PATH.exists():
        print(f"缺少 {BOUND_PATH}，先跑 tools/plan_speed_profile.py")
        return 2

    payload = json.loads(BOUND_PATH.read_text(encoding="utf-8"))
    at_target = payload["at_target"]
    simulated = payload["simulator_reference"]
    grid = payload.get("grid", {})
    optimal = at_target["energy_kwh"]
    sim_kwh = simulated["traction_kwh"]

    # ---- 1. 方法学不变量 ----
    check(
        "最优值显著低于反应式控制器",
        optimal < sim_kwh * 0.8,
        f"{optimal:,.0f} vs {sim_kwh:,.0f} kWh（{optimal / sim_kwh:.0%}）",
    )
    check(
        "最优时分贴近图定 410 min（±8）",
        abs(at_target["minutes"] - METERED_MINUTES) <= 8.0,
        f"{at_target['minutes']:.1f} min",
    )

    # ---- 2. 物理一致性：最优值必须落在实绩附近 ----
    ratio = optimal / METERED_WHEEL_KWH
    check(
        "最优值与实绩相差 ≤ 12%（物理量没有系统性偏差）",
        abs(ratio - 1.0) <= 0.12,
        f"{optimal:,.0f} vs {METERED_WHEEL_KWH:,.0f} kWh（{ratio - 1:+.1%}）",
    )
    excess = sim_kwh - METERED_WHEEL_KWH
    control_share = (sim_kwh - optimal) / excess if excess > 0 else 0.0
    check(
        "超额主要由控制律解释（≥ 90%）",
        control_share >= 0.90,
        f"{(sim_kwh - optimal):,.0f} / {excess:,.0f} = {control_share:.0%}",
    )

    # ---- 3. 加减速度必须取自模型，不能是经验值 ----
    a_acc = float(grid.get("a_acc_mps2", 0.0))
    check(
        "产物记录了加速度来源",
        grid.get("a_acc_source") in {"auto", "override"},
        f"source={grid.get('a_acc_source')!r}",
    )
    check(
        "默认加速度来自模型（0.04–0.10 m/s² 量级，不是 0.35 那种经验值）",
        0.04 <= a_acc <= 0.10,
        f"a_acc={a_acc:.4f} m/s²",
    )
    traction_kN = float(grid.get("traction_limit_kN", 0.0))
    mass_kg = float(grid.get("effective_mass_kg", 0.0))
    if traction_kN > 0.0 and mass_kg > 0.0:
        computed = traction_kN * 1000.0 / mass_kg
        check(
            "a_acc 与「牵引力 ÷ 有效质量」自洽（误差 ≤ 1%）",
            abs(a_acc - computed) <= 0.01 * computed,
            f"{a_acc:.5f} vs {computed:.5f} m/s²",
        )
    else:
        check("产物记录了牵引力与有效质量", False, "缺 traction_limit_kN / effective_mass_kg")

    # ---- 4. 前沿单调性 ----
    if FRONTIER_PATH.exists():
        with FRONTIER_PATH.open("r", encoding="utf-8-sig") as handle:
            frontier = [
                (float(row["lambda"]), float(row["energy_kwh"]), float(row["minutes"]))
                for row in csv.DictReader(handle)
            ]
        frontier.sort()
        check(
            "λ 增大时运行时分单调下降",
            all(b[2] <= a[2] + 1e-6 for a, b in zip(frontier, frontier[1:])),
            " > ".join(f"{row[2]:.0f}" for row in frontier),
        )
        check(
            "λ 增大时能耗单调上升（赶时间要付电费）",
            all(b[1] >= a[1] - 1e-6 for a, b in zip(frontier, frontier[1:])),
            " < ".join(f"{row[1]:,.0f}" for row in frontier),
        )
    else:
        check("前沿产物存在", False, "缺 frontier.csv")

    # ---- 5. 剖面本身合规 + 加速度不越界 ----
    if PROFILE_PATH.exists():
        with PROFILE_PATH.open("r", encoding="utf-8-sig") as handle:
            profile = list(csv.DictReader(handle))
        over = [
            row for row in profile
            if float(row["speed_kmh"]) > float(row["speed_limit_kmh"]) + 1e-6
        ]
        check("剖面全程不超限速", not over, f"越限 {len(over)} 点")
        check(
            "剖面覆盖完整里程（末点 > 395 km）",
            float(profile[-1]["position_km"]) > 395.0,
            f"{profile[-1]['position_km']} km",
        )
        accelerations = [float(row["accel_mps2"]) for row in profile if row.get("accel_mps2")]
        a_brk = float(grid.get("a_brk_mps2", 0.0))
        if accelerations:
            check(
                "剖面加速度不超过 a_acc（锁住方向写反）",
                max(accelerations) <= a_acc + 1e-6,
                f"max {max(accelerations):.4f} ≤ {a_acc:.4f} m/s²",
            )
            check(
                "剖面减速度不超过 a_brk（锁住方向写反）",
                min(accelerations) >= -a_brk - 1e-6,
                f"min {min(accelerations):.4f} ≥ {-a_brk:.4f} m/s²",
            )
        else:
            check("剖面记录了逐步加速度", False, "缺 accel_mps2 列")

        resistances = [
            float(row["basic_resistance_kN"]) for row in profile if row.get("basic_resistance_kN")
        ]
        if resistances:
            check(
                "剖面基本阻力不是常数（随速度变化）",
                max(resistances) - min(resistances) > 1.0,
                f"{min(resistances):.0f}–{max(resistances):.0f} kN",
            )
    else:
        check("剖面产物存在", False, "缺 optimal_speed_profile.csv")

    # ---- 6. 内置的 bug 回归 ----
    test_grid_resolution_guard()
    test_resistance_varies_with_speed()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"最优剖面：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"最优剖面：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
