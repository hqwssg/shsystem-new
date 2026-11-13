"""按图定时（TrainSchedule）回归测试。

锁住三件事：

1. ``TrainSchedule`` 的输入校验（单调性、时长必须为正）；
2. 启用约束后，全线区间运行时分与图定值的偏差在可接受范围内；
3. 不传 ``schedule`` 时行为与原先一致（约束默认关闭，不影响既有基线）。

依赖 ``outputs/running_diagram_data/section_times.json``
（由 ``tools/extract_section_times.py`` 生成）。若该文件不存在，
本测试自动跳过逐区间比对，只做接口契约检查。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION_JSON = ROOT / "outputs" / "running_diagram_data" / "section_times.json"
DATA_DIR = ROOT / "data" / "real_shuohuang"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def test_schedule_contract() -> None:
    from train_simulator import TrainSchedule

    schedule = TrainSchedule.from_sections(
        [(0.0, 100.0, 10.0), (100.0, 250.0, 15.0)], label="unit"
    )
    check("from_sections 累计时间", abs(schedule.total_minutes() - 25.0) < 1e-9,
          f"实际 {schedule.total_minutes()}")
    check("方向判定为正向", schedule.forward is True)

    # 起点处剩余 100 km / 600 s -> 166.7 m/s
    cap = schedule.speed_cap_mps(0.0, 0.0)
    check("起点速度上限按剩余距离/时间", cap is not None and abs(cap - 100000.0 / 600.0) < 1e-6,
          f"实际 {cap}")

    # 逼近下一站（剩余 < 120 m 缓冲）时不再压制
    near = schedule.speed_cap_mps(99.95, 590.0)
    check("贴近下一站时释放约束", near is None, f"实际 {near}")

    # 已晚点时不再压制
    late = schedule.speed_cap_mps(50.0, 700.0)
    check("晚点后释放约束", late is None, f"实际 {late}")

    # 反向 schedule
    reverse = TrainSchedule.from_sections([(250.0, 100.0, 15.0), (100.0, 0.0, 10.0)])
    check("反向方向判定", reverse.forward is False)
    rev_cap = reverse.speed_cap_mps(200.0, 0.0)
    check("反向速度上限可用", rev_cap is not None and rev_cap > 0, f"实际 {rev_cap}")

    for label, bad in (
        ("拒绝非单调里程", [(0.0, 100.0, 5.0), (120.0, 80.0, 5.0)]),
        ("拒绝非正时长", [(0.0, 100.0, 0.0)]),
    ):
        try:
            TrainSchedule.from_sections(bad)
        except ValueError:
            check(label, True)
        else:
            check(label, False, "未抛出 ValueError")


def test_simulation_timing(delta_t: int = 10) -> None:
    if not SECTION_JSON.exists():
        print(f"[SKIP] 缺少 {SECTION_JSON.name}，跳过逐区间比对")
        return

    from run_dispatch_case import load_case_inputs
    from train_simulator import TrainSimulator
    from tools.validate_section_times import TIER_2W, _sections, _stations, build_schedule

    inputs = load_case_inputs(DATA_DIR, ROOT / "outputs" / "_schedule_smoke")
    stations = _stations()
    sections = _sections()
    train = inputs.trains["Heavy"]
    direction = "forward" if train.direction == "forward" else "reverse"
    schedule = build_schedule(stations, sections, direction, TIER_2W, label="Heavy")

    baseline = TrainSimulator(inputs.route, train, delta_t_s=delta_t).run()
    timed = TrainSimulator(inputs.route, train, delta_t_s=delta_t, schedule=schedule).run()

    baseline_h = baseline[-1].time_s / 3600.0
    timed_h = timed[-1].time_s / 3600.0
    scheduled_h = schedule.total_minutes() / 60.0

    check("按图定时后总时长不小于自由运行", timed_h >= baseline_h - 1e-9,
          f"自由 {baseline_h:.2f} h vs 定时 {timed_h:.2f} h")
    deviation = (timed_h - scheduled_h) / scheduled_h
    check("总时长与图定偏差在 5% 内", abs(deviation) <= 0.05,
          f"仿真 {timed_h:.2f} h vs 图定 {scheduled_h:.2f} h，偏差 {deviation:+.1%}")

    # 速度被压制时，牵引能耗不应显著上升（约束只减不增）
    def traction(records) -> float:
        return sum(max(0.0, r.power_kW) * delta_t / 3600.0 for r in records)

    base_kwh = traction(baseline)
    timed_kwh = traction(timed)
    check("定时后牵引能耗变化在 ±15% 内", abs(timed_kwh - base_kwh) / max(1.0, base_kwh) <= 0.15,
          f"{base_kwh:,.0f} -> {timed_kwh:,.0f} kWh")


def test_dwell_contract() -> None:
    """站停作业时分：到发时刻、纯运行时长、停站窗口的速度上限。"""

    from train_simulator import TrainSchedule

    schedule = TrainSchedule.from_sections(
        [(0.0, 100.0, 10.0), (100.0, 250.0, 15.0)],
        dwell_minutes=[8.0, 0.0],
        label="dwell",
    )
    _, arr1, dep1 = schedule.stops[1]
    check("停站记入到发时刻差", abs((dep1 - arr1) / 60.0 - 8.0) < 1e-9,
          f"实际 {(dep1 - arr1)/60.0} min")
    check("总时长 = 通通 + 停站", abs(schedule.total_minutes() - 33.0) < 1e-9,
          f"实际 {schedule.total_minutes()} min")
    check("纯运行时长剔除停站", abs(schedule.running_minutes() / 60.0 - 25.0) < 1e-9,
          f"实际 {schedule.running_minutes()/60.0} min")
    check("停站时长统计", abs(schedule.dwell_minutes() / 60.0 - 8.0) < 1e-9,
          f"实际 {schedule.dwell_minutes()/60.0} min")

    # 已到站但未到发车时刻 -> 速度上限必须是 0（而不是 None）
    cap_dwell = schedule.speed_cap_mps(101.0, arr1 + 60.0)
    check("停站窗口速度上限为 0", cap_dwell == 0.0, f"实际 {cap_dwell}")

    # 发车后恢复正常约束
    cap_run = schedule.speed_cap_mps(120.0, dep1 + 60.0)
    check("发车后恢复剩余时间约束", cap_run is not None and cap_run > 0.0, f"实际 {cap_run}")

    # 停站为正但发车早于到站 -> 拒绝
    try:
        TrainSchedule(stops=((0.0, 0.0, 0.0), (10.0, 600.0, 300.0)))
    except ValueError:
        check("发车早于到站被拒绝", True)
    else:
        check("发车早于到站被拒绝", False, "未抛出 ValueError")


def main() -> int:
    test_schedule_contract()
    test_dwell_contract()
    test_simulation_timing()
    if failures:
        print(f"\n按图定时回归：FAIL（{len(failures)} 项）")
        return 1
    print("\n按图定时回归：PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
