"""制动分配策略（电制动投入级位）回归测试。

锁住四件事：

1. ``BrakeStrategy`` 的输入契约：默认值来自实绩标定，越界必须拒绝；
2. ``electrical_level`` 只改电制动与空气制动的**分摊**，不改总制动力
   —— 因此牵引电量、耗时、均速必须逐位不变，只有再生电量随级位变化；
3. 级位单调：级位越大，再生电量越大，且不超过「满级位」的上界；
4. 标定结果可复现：按 ``outputs/brake_calibration/calibration.json``
   记录的级位跑 396 km，再生电量与实绩中位数的偏差在 15% 以内。

第 2 条是这次改动的核心不变量：如果哪天有人把 level 也乘进制动力，
列车会跑得更慢，能耗与时刻全部失效，但不会有任何报错——所以必须测。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "real_shuohuang"
CALIBRATION_JSON = ROOT / "outputs" / "brake_calibration" / "calibration.json"
# 主 OD 神池南→肃宁北的实际里程，取自 stations.csv（此前项目长期写死 396.0）。
MAIN_OD_KM = 406.571

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def test_strategy_contract() -> None:
    from train_simulator import BrakeStrategy

    default = BrakeStrategy()
    check(
        "默认级位来自实绩标定（0.48）",
        abs(default.electrical_level - 0.48) < 1e-9,
        f"实际 {default.electrical_level}",
    )
    for label, bad in (
        ("拒绝负级位", -0.01),
        ("拒绝超过 1 的级位", 1.01),
        ("拒绝 NaN", math.nan),
        ("拒绝 inf", math.inf),
    ):
        try:
            BrakeStrategy(electrical_level=bad)
        except ValueError:
            check(label, True)
        else:
            check(label, False, "未抛出 ValueError")

    for level in (0.0, 1.0):
        try:
            BrakeStrategy(electrical_level=level)
        except ValueError as exc:  # pragma: no cover - 边界值必须接受
            check(f"接受边界级位 {level}", False, str(exc))
        else:
            check(f"接受边界级位 {level}", True)


def _run(level: float, delta_t: int = 10, with_schedule: bool = False):
    from run_dispatch_case import load_case_inputs
    from train_simulator import BrakeStrategy, TrainSimulator

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_brake_smoke")
    train = inputs.trains["Heavy"]
    schedule = None
    if with_schedule:
        from tools.validate_section_times import (
            TIER_2W, _sections, _stations, build_schedule, load_dwell_plan,
        )

        schedule = build_schedule(
            _stations(), _sections(), "forward", TIER_2W,
            dwell_plan=load_dwell_plan("all"), label="Heavy",
        )
    simulator = TrainSimulator(
        inputs.route,
        train,
        delta_t_s=delta_t,
        schedule=schedule,
        brake_strategy=BrakeStrategy(electrical_level=level),
    )
    return simulator.run()


def _totals(records, delta_t: int = 10, limit_km: float | None = None) -> dict:
    """汇总一次全程仿真的牵引 / 再生 / 里程。

    ``limit_km`` 缺省为 ``None``＝不截断：主 OD（神池南→肃宁北）本身就是
    406.571 km，早前写死 396.0 会把最后 10.6 km 的再生漏掉约 8%。
    """
    traction = 0.0
    regen = 0.0
    travelled = 0.0
    end_time = 0.0
    previous = records[0] if records else None
    for record in records:
        if previous is not None and record is not previous:
            travelled += abs(record.position_km - previous.position_km)
            if limit_km is not None and travelled > limit_km:
                break
        if record.power_kW > 0:
            traction += record.power_kW * delta_t / 3600.0
        else:
            regen += -record.power_kW * delta_t / 3600.0
        end_time = record.time_s
        previous = record
    return {
        "traction_kwh": round(traction, 3),
        "regen_kwh": round(regen, 3),
        "hours": round(end_time / 3600.0, 4),
        "distance_km": round(travelled, 2),
    }


def test_allocation_only() -> None:
    """级位不得改变动力学：牵引、耗时、里程逐位相同，只有再生变。"""

    low = _totals(_run(0.20))
    high = _totals(_run(0.90))

    check(
        "级位不改变牵引电量",
        low["traction_kwh"] == high["traction_kwh"],
        f"0.20 -> {low['traction_kwh']:,.1f} kWh vs 0.90 -> {high['traction_kwh']:,.1f} kWh",
    )
    check(
        "级位不改变耗时",
        low["hours"] == high["hours"],
        f"{low['hours']:.3f} h vs {high['hours']:.3f} h",
    )
    check(
        "级位不改变走行距离",
        low["distance_km"] == high["distance_km"],
        f"{low['distance_km']} km vs {high['distance_km']} km",
    )
    check(
        "级位增大则再生电量增大",
        high["regen_kwh"] > low["regen_kwh"] + 1.0,
        f"0.20 -> {low['regen_kwh']:,.0f} vs 0.90 -> {high['regen_kwh']:,.0f}",
    )


def test_level_scaling() -> None:
    """再生电量随级位呈「先线性、后饱和」：低档线性增长，高档被需求制动力截断。

    饱和点是有物理意义的：当「级位 × 电制动曲线能力」超过当时的**需求制动力**时，
    ``min(brake_kN, 实际电制动上限)`` 开始截断，再多给级位也不产生更多再生。
    实测 0.50 → 0.75 的比值已降到 1.45，说明饱和拐点就在 0.5 附近。
    """

    values = {level: _totals(_run(level))["regen_kwh"] for level in (0.25, 0.50, 0.75)}
    ratio_low = values[0.50] / max(values[0.25], 1e-9)
    ratio_high = values[0.75] / max(values[0.50], 1e-9)
    check(
        "低档再生电量随级位近似线性（比值 1.7—2.3）",
        1.7 <= ratio_low <= 2.3,
        f"0.25→0.50 = {ratio_low:.2f}",
    )
    check(
        "高档出现饱和（0.50→0.75 比值 < 1.8，但仍递增）",
        1.0 < ratio_high < 1.8,
        f"0.50→0.75 = {ratio_high:.2f}",
    )
    zero = _totals(_run(0.0))["regen_kwh"]
    check("级位为 0 时无再生", zero < 1e-6, f"实际 {zero}")


def test_calibration_reproduction() -> None:
    """按标定级位跑，再生电量应与实绩中位数接近。"""

    if not CALIBRATION_JSON.exists():
        print(f"[SKIP] 缺少 {CALIBRATION_JSON.name}，跳标定复现")
        return
    payload = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    consensus = payload.get("consensus") or {}
    level = consensus.get("median")
    cases = payload.get("cases") or []
    if level is None or not cases:
        print("[SKIP] 标定 JSON 缺少 consensus/cases")
        return

    target = cases[0]["target_regen_kwh"]
    # 标定产物必须与当前编组/里程同口径，否则比较的是两个不同的东西。
    # 旧产物是「396.0 km + 12 轴单机」下标出来的；两万吨改成 1+1 两台、
    # 主 OD 改成 406.571 km 之后，它既少了 10.6 km 的再生，又只算了半列车，
    # 直接比对会得到「+56%」这种假失败。
    from run_dispatch_case import load_case_inputs

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_brake_smoke")
    heavy = inputs.trains["Heavy"]
    stale = []
    artifact_km = payload.get("od_km")
    if artifact_km is not None and abs(float(artifact_km) - MAIN_OD_KM) > 1.0:
        stale.append(f"里程 {artifact_km} km ≠ 当前 {MAIN_OD_KM} km")
    case_label = str(cases[0].get("label") or "")
    if "单机" in case_label and heavy.locomotive_count != 1:
        stale.append(f"标定按「{case_label}」，当前编组为 {heavy.locomotive_consist}")
    if stale:
        print(
            "[SKIP] 标定产物口径已过期（" + "；".join(stale) + "），"
            "需重跑 tools/calibrate_brake_strategy.py 后再比对"
        )
        return

    actual = _totals(_run(level))["regen_kwh"]
    deviation = (actual - target) / target
    check(
        "标定级位复现实绩再生电量（±15%）",
        abs(deviation) <= 0.15,
        f"级位 {level}：仿真 {actual:,.0f} vs 实绩 {target:,.0f}（{deviation:+.1%}）",
    )
    check(
        "标定级位在合理区间（0.3—0.7）",
        0.3 <= level <= 0.7,
        f"实际 {level}",
    )
    check(
        "两个吨位工况的标定极差不超过 0.10",
        consensus.get("spread", 1.0) <= 0.10,
        f"实际 {consensus.get('spread')}",
    )


def test_consist_support() -> None:
    """混合编组：质量、牵引力、功率、电制动能力都按机型清单累加。"""

    from dataclasses import replace

    from run_dispatch_case import load_case_inputs
    from train_simulator import TrainSimulator, normalise_locomotive_consist

    check(
        "consist 合并同机型台数",
        normalise_locomotive_consist([("A", 1), ("B", 2), ("A", 1)]) == (("A", 2), ("B", 2)),
    )
    check("空 consist 归一化为空元组", normalise_locomotive_consist(None) == ())

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_brake_smoke")
    base = inputs.trains["Heavy"]
    vehicle_mass = base.vehicle_mass_tons

    single = replace(
        base,
        locomotive_consist=(("SHENHUA_12", 1),),
        locomotive_type=None,
        locomotive_count=0,
        vehicle_mass_tons=None,
        mass_tons=vehicle_mass,
    )
    mixed = replace(
        base,
        locomotive_consist=(("SHENHUA_12", 1), ("HXD1_25t", 1)),
        locomotive_type=None,
        locomotive_count=0,
        vehicle_mass_tons=None,
        mass_tons=vehicle_mass,
    )
    check(
        "consist 质量 = 车辆总重 + 各机车自重",
        abs(mixed.mass_tons - (vehicle_mass + 300.0 + 200.0)) < 1e-6,
        f"{mixed.mass_tons} vs {vehicle_mass + 500.0}",
    )
    check(
        "consist 同步主控机型与总台数",
        mixed.locomotive_type == "SHENHUA_12" and mixed.locomotive_count == 2,
        f"{mixed.locomotive_type} × {mixed.locomotive_count}",
    )

    sim_single = TrainSimulator(inputs.route, single, delta_t_s=10)
    sim_mixed = TrainSimulator(inputs.route, mixed, delta_t_s=10)
    v = 12.0
    brake_single = sim_single.electrical_brake_force_limit_kN(v)
    brake_mixed = sim_mixed.electrical_brake_force_limit_kN(v)
    check(
        "consist 电制动能力逐机型累加",
        abs(brake_mixed - (brake_single + 461.0)) < 1e-6,
        f"单机 {brake_single} -> 双机 {brake_mixed}",
    )
    check(
        "consist 牵引功率逐机型累加",
        abs(sim_mixed.power_cap_kW() - (sim_single.power_cap_kW() + 9600.0)) < 5.0,
        f"{sim_single.power_cap_kW():,.0f} -> {sim_mixed.power_cap_kW():,.0f} kW",
    )


def test_single_locomotive_baseline() -> None:
    """两万吨是 12 轴 + 8 轴「1+1」两台，配置不该退回单机。"""

    from run_dispatch_case import load_case_inputs

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_brake_smoke")
    heavy = inputs.trains["Heavy"]
    check(
        "Heavy 为 12 轴 + 8 轴 1+1 编组",
        heavy.locomotive_consist == (("SHENHUA_12", 1), ("SHENHUA_8", 1)),
        f"{heavy.locomotive_consist}",
    )
    check(
        "Heavy 台数由编组归一为 2",
        heavy.locomotive_count == 2,
        f"实际 {heavy.locomotive_count}",
    )
    check(
        "Heavy 整备质量 = 21600 车辆 + 300 + 200 机车",
        abs(heavy.mass_tons - 22100.0) < 1e-6,
        f"实际 {heavy.mass_tons}",
    )


def main() -> int:
    test_strategy_contract()
    test_allocation_only()
    test_level_scaling()
    test_calibration_reproduction()
    test_consist_support()
    test_single_locomotive_baseline()
    if failures:
        print(f"\n制动策略回归：FAIL（{len(failures)} 项）")
        return 1
    print("\n制动策略回归：PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
