"""质量口径回归测试：确保「整列车总重 = 车辆总重 + 机车自重」不被破坏。

背景
----
编组资料（《2025朔黄铁路编组模式》）给的是**车辆总重**：216 辆 C80 重车
21600 t = 216×100 t，空车 4320 t = 216×20 t，均不含机车。

代码曾把该值当作「整列车总重」，又在算货车阻力时减掉一次机车自重，
导致 Heavy 能耗低估 3.0%、Empty 低估 8.0%。本测试锁死正确口径：

1. 构造时 `mass_tons` 自动归一化为车辆 + 机车；
2. `dataclasses.replace()` 不得重复叠加机车质量（幂等）；
3. `mass_min_tons` / `mass_max_tons` 随同一偏移同步平移；
4. 货车质量必须等于车辆总重，不能被二次扣减；
5. 未配置机车时行为不变；
6. CLI `--empty-mass-tons` 按车辆口径输入并自动加机车。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from train_simulator import (  # noqa: E402
    DavisCoefficients,
    TrainParameters,
    _basic_resistance_kN,
    locomotive_mass_tons,
)

LOCO = "HXD1_23t"
UNIT_MASS = 184.0
DAVIS = DavisCoefficients(0.92, 0.0048, 0.000125)


def _train(name: str, vehicle_mass: float, count: int, **kwargs) -> TrainParameters:
    return TrainParameters(
        name=name,
        mass_tons=vehicle_mass,
        max_traction_kN=5600.0,
        max_brake_kN=6200.0,
        rotational_mass_factor=1.06,
        davis=DAVIS,
        locomotive_type=LOCO,
        locomotive_count=count,
        **kwargs,
    )


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} 失败：{detail}")


def main() -> int:
    # --- 1. 归一化：重车 ---
    heavy = _train("Heavy", 21600.0, 4)
    loco_mass = locomotive_mass_tons(LOCO, 4)
    check(
        "重车总重归一化",
        abs(heavy.mass_tons - (21600.0 + loco_mass)) < 1e-9,
        f"期望 {21600.0 + loco_mass}，实际 {heavy.mass_tons}",
    )
    check(
        "重车车辆质量保留",
        heavy.vehicle_mass_tons == 21600.0,
        f"实际 {heavy.vehicle_mass_tons}",
    )
    check("机车质量取值", abs(loco_mass - 736.0) < 1e-9, f"实际 {loco_mass}")

    # --- 2. 幂等：replace 不得重复叠加 ---
    scaled = replace(heavy, mass_tons=heavy.mass_tons * 1.1)
    check(
        "replace 不重复加机车",
        abs(scaled.mass_tons - heavy.mass_tons * 1.1) < 1e-9,
        f"实际 {scaled.mass_tons}",
    )
    rescale = replace(scaled, mass_tons=scaled.mass_tons * 1.1)
    check(
        "连续 replace 仍不叠加",
        abs(rescale.mass_tons - heavy.mass_tons * 1.21) < 1e-6,
        f"实际 {rescale.mass_tons}",
    )

    # --- 3. 边界同步平移 ---
    empty = _train("Empty", 4320.0, 2, mass_min_tons=2160.0, mass_max_tons=4320.0)
    empty_loco = locomotive_mass_tons(LOCO, 2)
    check("空车上界平移", abs(empty.mass_max_tons - (4320.0 + empty_loco)) < 1e-9, f"实际 {empty.mass_max_tons}")
    check("空车下界平移", abs(empty.mass_min_tons - (2160.0 + empty_loco)) < 1e-9, f"实际 {empty.mass_min_tons}")
    check("空车总重", abs(empty.mass_tons - 4688.0) < 1e-9, f"实际 {empty.mass_tons}")

    # --- 4. 货车质量不得被二次扣减 ---
    wagon_mass = heavy.mass_tons - locomotive_mass_tons(LOCO, heavy.locomotive_count)
    check("重车货车质量", abs(wagon_mass - 21600.0) < 1e-9, f"实际 {wagon_mass}")
    empty_wagon = empty.mass_tons - locomotive_mass_tons(LOCO, empty.locomotive_count)
    check("空车货车质量", abs(empty_wagon - 4320.0) < 1e-9, f"实际 {empty_wagon}")

    # 阻力必须与「车辆 21600 + 机车 736」的应然值一致（修复前为 282.30 kN）
    resistance_40 = _basic_resistance_kN(heavy, 40.0, 1.0, 1.0)
    check(
        "重车 40km/h 阻力",
        abs(resistance_40 - 291.77) < 0.5,
        f"期望约 291.77 kN，实际 {resistance_40:.2f}",
    )

    # --- 5. 未配置机车时行为不变 ---
    plain = TrainParameters(
        name="Plain",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DAVIS,
    )
    check("无机车不改质量", plain.mass_tons == 1000.0, f"实际 {plain.mass_tons}")
    check("无机车无车辆质量标记", plain.vehicle_mass_tons is None, f"实际 {plain.vehicle_mass_tons}")

    # --- 6. CLI 覆盖按车辆口径输入 ---
    from run_dispatch_case import apply_train_mass_scenario  # noqa: E402

    overridden = apply_train_mass_scenario({"Empty": empty}, 2160.0)["Empty"]
    check(
        "CLI 覆盖加机车",
        abs(overridden.mass_tons - (2160.0 + empty_loco)) < 1e-9,
        f"实际 {overridden.mass_tons}",
    )
    check("CLI 覆盖记录车辆值", overridden.vehicle_mass_tons == 2160.0, f"实际 {overridden.vehicle_mass_tons}")

    # --- 7. 实际数据配置自洽（trains.csv 的机型 / 台数必须能被解析） ---
    from locomotive_curves import default_curve_bank  # noqa: E402

    bank = default_curve_bank()
    for code in ("SHENHUA_12", "HXD1_23t", "HXD1_25t"):
        params = bank.locomotive_params(code)
        check(f"{code} 机型存在", params is not None, "locomotive_curves.json 缺少条目")
        check(
            f"{code} 有持续功率",
            (bank.locomotive_power_kW(code) or 0.0) > 0.0,
            "持续牵引力/速度缺失，功率上限会静默回退到 CSV",
        )
        check(
            f"{code} 有电制动曲线",
            bank.brake_force_kN(code, 50.0) is not None,
            "缺 brake_curve 会使电制动力与再生电量恒为 0",
        )
    check(
        "神12 整备质量",
        abs((bank.locomotive_params("SHENHUA_12") or {}).get("computed_mass_t", 0.0) - 300.0) < 1e-9,
        "实测单机行 辆数=3 × 100 t/节",
    )
    check(
        "神12 持续功率",
        abs((bank.locomotive_power_kW("SHENHUA_12") or 0.0) - 14400.0) < 5.0,
        "技术方案：十二轴交流 14400 kW",
    )

    # --- 8. 真实数据文件加载后的总重口径 ---
    import csv as _csv  # noqa: E402

    rows = list(_csv.DictReader(open(ROOT / "data" / "real_shuohuang" / "trains.csv", encoding="utf-8-sig")))
    for row in rows:
        name = row["name"]
        vehicle = float(row["mass_tons"])
        count = int(row["locomotive_count"])
        loco_type = row["locomotive_type"]
        built = TrainParameters(
            name=name,
            mass_tons=vehicle,
            max_traction_kN=float(row["max_traction_kN"]),
            max_brake_kN=float(row["max_brake_kN"]),
            rotational_mass_factor=float(row["rotational_mass_factor"]),
            davis=DavisCoefficients(
                float(row["davis_a"]), float(row["davis_b"]), float(row["davis_c"])
            ),
            locomotive_type=loco_type,
            locomotive_count=count,
        )
        expected = vehicle + locomotive_mass_tons(loco_type, count)
        check(f"{name} 总重 = 车辆 + 机车", abs(built.mass_tons - expected) < 1e-9,
              f"期望 {expected}，实际 {built.mass_tons}")

    print("质量口径回归：PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
