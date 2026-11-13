"""牵引归因分解的闸门测试。

守住的不是"某个数值等于多少"，而是**拆法本身必须成立**：

1. 能量恒等式在非限速步上逐位闭合（残差 → 0）；
2. 有限残差全部落在可命名的限速夹紧步上；
3. 上坡牵引 ≈ 上坡坡道功 + 上坡阻力功（物理侧自洽）；
4. 动能用等效质量乘数 1.06，不是 2.06（曾踩过：把已含 1.0 的乘数又加了一次）；
5. 下坡牵引能解释超额；
6. 拉开惰行死区，牵引几乎不变（否证"抖动"假设）；
7. 与本项目另一套审计工具的牵引总量一致（防两处各自演化）。
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "traction_attribution"
JSON_PATH = OUT / "traction_attribution.json"
STEPS_PATH = OUT / "step_attribution.csv"
SWEEP_PATH = OUT / "coast_band_sweep.csv"
DROOP_PATH = OUT / "droop_sweep.csv"
POLICY_PATH = OUT / "policy_sweep.csv"
CLOSURE_PATH = ROOT / "outputs" / "energy_closure" / "closure_matrix.json"

TRACTION_EFFICIENCY = 0.86
MASS_T = 22200.0
MASS_FACTOR = 1.06

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def _raises(call) -> bool:
    """``call()`` 是否抛异常（用于契约断言）。"""

    try:
        call()
    except Exception:
        return True
    return False


def main() -> int:
    """跑全部断言。"""

    if not JSON_PATH.exists():
        print(f"缺少 {JSON_PATH}，先跑 tools/attribute_traction_energy.py")
        return 2

    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    runs = payload["runs"]
    verdict = payload["judgement"]
    primary = runs["loco_2"]

    check("两个台数分支都在结果里", set(runs) == {"loco_1", "loco_2"}, str(sorted(runs)))
    check("双机分支质量为 22,200 t", abs(primary["mass_t"] - MASS_T) < 1.0, f"{primary['mass_t']}")

    # ---- 1/2. 恒等式闭合 ----
    residual = primary["identity_residual_kwh"]
    other = primary["residual_excluding_limit_kwh"]
    check(
        "非限速步的能量恒等式逐位闭合（残差 < 0.1 kWh）",
        abs(other) < 0.1,
        f"残差 {other:.4f} kWh",
    )
    check(
        "全部残差都落在限速夹紧步上（占比 > 99%）",
        residual != 0 and abs(other) / abs(residual) < 0.01,
        f"总 {residual:.1f} / 限速外 {other:.4f}",
    )
    check("限速夹紧步数量有限（< 60）", 0 < primary["clamped_steps"] < 60, f"{primary['clamped_steps']} 步")

    # ---- 3. 上坡物理自洽 ----
    up = primary["by_gradient"]["up"]
    expected = up["grade_kwh"] + up["basic_kwh"]
    error = up["traction_kwh"] - expected
    check(
        "上坡牵引 ≈ 上坡坡道功 + 上坡阻力功（误差 < 5%）",
        abs(error) / up["traction_kwh"] < 0.05,
        f"实测 {up['traction_kwh']:,.0f} vs 物理 {expected:,.0f}（{error:+,.0f}）",
    )
    check(
        "上坡段坡道功为正",
        up["grade_kwh"] > 0,
        f"{up['grade_kwh']:,.0f} kWh",
    )
    check(
        "下坡段坡道功为负",
        primary["by_gradient"]["down"]["grade_kwh"] < 0,
        f"{primary['by_gradient']['down']['grade_kwh']:,.0f} kWh",
    )

    # ---- 4. 等效质量口径（防 2.06 倍） ----
    with STEPS_PATH.open("r", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if r["branch"] == "loco_2"]
    worst = 0.0
    for current, nxt in zip(rows, rows[1:]):
        v0 = float(current["speed_kmh"]) / 3.6
        v1 = float(nxt["speed_kmh"]) / 3.6
        expected_ke = 0.5 * MASS_T * 1000.0 * MASS_FACTOR * (
            nxt_speed := (v1**2 - v0**2)
        ) / 1000.0 / 3600.0
        actual = float(current["delta_ke_kwh"])
        worst = max(worst, abs(actual - expected_ke))
    # 阈值 0.6 kWh 而不是 0.02：CSV 里的速度保留 2 位小数（0.01 km/h），
    # 反推 Δ(v²) 时这点舍入在 22,200 t 上就放大成 ~0.36 kWh。要抓的是
    # "整倍"级别的错误（2.06 会让总量翻倍），不是打印精度。
    check(
        "动能按等效质量乘数 1.06 计算（不是 2.06）",
        worst < 0.6,
        f"最大单步偏差 {worst:.4f} kWh（CSV 速度舍入量级）",
    )
    doubled = 0.0
    for current, nxt in zip(rows[:200], rows[1:201]):
        v0 = float(current["speed_kmh"]) / 3.6
        v1 = float(nxt["speed_kmh"]) / 3.6
        doubled += 0.5 * MASS_T * 1000.0 * 2.06 * (v1**2 - v0**2) / 3600.0 / 1000.0
    actual_head = sum(float(r["delta_ke_kwh"]) for r in rows[:200])
    check(
        "若误用 2.06 会明显偏离（说明断言有分辨力）",
        abs(doubled - actual_head) > 1.0,
        f"2.06 口径 {doubled:,.1f} vs 实际 {actual_head:,.1f}",
    )

    # ---- 5. 判据 ----
    excess = verdict["excess_wheel_kwh"]
    check("超额为正（模型高于目标）", excess > 0, f"{excess:,.1f} kWh")
    check(
        "上坡牵引已接近目标（偏差在 ±10% 内）",
        abs(verdict["uphill_vs_target"]) <= 0.10,
        f"{verdict['uphill_vs_target']:+.1%}",
    )
    check(
        "下坡牵引解释超额的 80%–130%",
        0.8 <= verdict["downhill_share_of_excess"] <= 1.3,
        f"{verdict['downhill_share_of_excess']:.1%}",
    )
    check(
        "判定为「超额落在下坡段」",
        verdict["verdict"] == "explained_by_downhill_traction",
        verdict["verdict"],
    )

    # ---- 6. 否证抖动假设 ----
    if SWEEP_PATH.exists():
        with SWEEP_PATH.open("r", encoding="utf-8-sig") as handle:
            sweep = [row for row in csv.DictReader(handle)]
        first = float(sweep[0]["traction_kwh"])
        last = float(sweep[-1]["traction_kwh"])
        check(
            "死区放大 100 倍后牵引变化 < 10%（抖动不是原因）",
            abs(last / first - 1.0) < 0.10,
            f"{first:,.0f} → {last:,.0f}（{last / first - 1:+.1%}）",
        )
        brake_first = float(sweep[0]["brake_work_kwh"])
        brake_last = float(sweep[-1]["brake_work_kwh"])
        check(
            "死区放大后制动功变化 < 5%",
            abs(brake_last / brake_first - 1.0) < 0.05,
            f"{brake_first:,.0f} → {brake_last:,.0f}",
        )
    else:
        check("死区扫描产物存在", False, "缺 coast_band_sweep.csv")

    # ---- 6b. 死区扫描：能耗与时分的权衡 ----
    if DROOP_PATH.exists():
        with DROOP_PATH.open("r", encoding="utf-8-sig") as handle:
            droop = [row for row in csv.DictReader(handle)]
        energies = [float(row["traction_kwh"]) for row in droop]
        minutes = [float(row["running_minutes"]) for row in droop]
        check(
            "死区放大时牵引单调下降",
            all(a > b for a, b in zip(energies, energies[1:])),
            " > ".join(f"{v:,.0f}" for v in energies),
        )
        check(
            "死区放大时时分单调上升（说明不是免费）",
            all(a < b for a, b in zip(minutes, minutes[1:])),
            " < ".join(f"{v:.1f}" for v in minutes),
        )
        target_wheel = verdict["target_wheel_kwh"]
        hit = None
        for left, right in zip(droop, droop[1:]):
            e0, e1 = float(left["traction_kwh"]), float(right["traction_kwh"])
            if (e0 - target_wheel) * (e1 - target_wheel) <= 0 and e0 > e1:
                ratio = (e0 - target_wheel) / (e0 - e1)
                hit = float(left["running_minutes"]) + ratio * (
                    float(right["running_minutes"]) - float(left["running_minutes"])
                )
                break
        check(
            "能耗打到目标时必然晚点（> 425 min），二者不可同时满足",
            hit is not None and hit > 425.0,
            f"插值时分 {hit:.0f} min vs 图定 410" if hit else "未穿过目标线",
        )
    else:
        check("牵引死区扫描产物存在", False, "缺 droop_sweep.csv")

    # ---- 6c. 可达前沿：目标点在线外 ----
    if POLICY_PATH.exists():
        with POLICY_PATH.open("r", encoding="utf-8-sig") as handle:
            policy = [row for row in csv.DictReader(handle)]
        modes = {row["schedule_speed_cap"] for row in policy}
        check("前沿扫描覆盖两种按图定时口径", modes == {"strict", "dwell"}, str(sorted(modes)))
        at_time = [row for row in policy if abs(float(row["running_minutes"]) - 410.0) <= 3.0]
        best = min((float(row["traction_kwh"]) for row in at_time), default=None)
        check(
            "410 min 处可达的最低牵引远高于目标（> 1.5×）",
            best is not None and best > verdict["target_wheel_kwh"] * 1.5,
            f"{best:,.0f} kWh vs 目标 {verdict['target_wheel_kwh']:,.0f}" if best else "无该时点",
        )
        # 逐口径插值出「打到目标电量」所需时分
        needed = []
        for mode in ("strict", "dwell"):
            subset = [row for row in policy if row["schedule_speed_cap"] == mode]
            for left, right in zip(subset, subset[1:]):
                e0, e1 = float(left["traction_kwh"]), float(right["traction_kwh"])
                if (e0 - verdict["target_wheel_kwh"]) * (e1 - verdict["target_wheel_kwh"]) <= 0 and e0 > e1:
                    ratio = (e0 - verdict["target_wheel_kwh"]) / (e0 - e1)
                    needed.append(
                        float(left["running_minutes"])
                        + ratio * (float(right["running_minutes"]) - float(left["running_minutes"]))
                    )
                    break
        check(
            "打到目标电量需晚点 ≥ 25 min（目标点在前沿之外）",
            bool(needed) and min(needed) - 410.0 >= 25.0,
            f"最短 {min(needed):.0f} min" if needed else "未穿过目标线",
        )
        dwell_zero = next(
            (row for row in policy
             if row["schedule_speed_cap"] == "dwell" and float(row["traction_droop_mps"]) == 0.0),
            None,
        )
        check(
            "站停吸收口径本身就使牵引低于严格压速（口径差异真实存在）",
            dwell_zero is not None and float(dwell_zero["traction_kwh"]) < primary["total_traction_kwh"],
            f"{float(dwell_zero['traction_kwh']):,.0f} vs {primary['total_traction_kwh']:,.0f}"
            if dwell_zero else "缺 dwell/0 行",
        )
    else:
        check("前沿扫描产物存在", False, "缺 policy_sweep.csv")

    # ---- 6d. 按图定时口径的参数契约 ----
    import inspect

    from train_simulator import BrakeStrategy, TrainSimulator

    params = inspect.signature(TrainSimulator.__init__).parameters
    cap_param = params.get("schedule_speed_cap")
    check(
        "TrainSimulator 暴露 schedule_speed_cap 且默认 strict（不改变既有行为）",
        cap_param is not None and cap_param.default == "strict",
        str(cap_param),
    )
    check(
        "无效口径被拒绝（拼写错误不会静默退化成 strict）",
        _raises(lambda: TrainSimulator(
            None, None, schedule_speed_cap="dwel"  # type: ignore[arg-type]
        )),
        "ValueError",
    )
    check(
        "下坡提速参数已移除（实测无效，不留死旋钮）",
        not hasattr(BrakeStrategy(), "descent_speed_boost_mps"),
        "absent",
    )

    # ---- 7. 与闭合审计一致 ----
    if CLOSURE_PATH.exists():
        closure = json.loads(CLOSURE_PATH.read_text(encoding="utf-8"))
        raw = [
            row for row in closure["matrix"]
            if row.get("variant") == "raw" and row.get("branch") == "loco_2"
        ]
        if raw:
            audit_value = raw[0]["traction_kwh"]
            check(
                "与闭合审计的牵引总量一致（差 < 1 kWh）",
                abs(audit_value - primary["total_traction_kwh"]) < 1.0,
                f"审计 {audit_value:,.1f} vs 归因 {primary['total_traction_kwh']:,.1f}",
            )
            check(
                "审计已改用轮周下界比较（不再混用电网侧）",
                "bound_wheel_kwh" in raw[0] and abs(
                    raw[0]["simulated_vs_bound"]
                    - (raw[0]["traction_kwh"] / raw[0]["bound_wheel_kwh"] - 1.0)
                ) < 1e-4,
                f"simulated_vs_bound = {raw[0]['simulated_vs_bound']:+.3f}",
            )
        else:
            check("闭合审计里有 raw/loco_2 记录", False)
    else:
        check("闭合审计产物存在", False, "缺 closure_matrix.json")

    # ---- 8. 口径换算 ----
    check(
        "电网侧 = 轮周 ÷ 0.86",
        abs(verdict["model_grid_kwh"] - verdict["model_wheel_kwh"] / TRACTION_EFFICIENCY) < 0.5,
        f"{verdict['model_grid_kwh']:,.0f} vs {verdict['model_wheel_kwh'] / TRACTION_EFFICIENCY:,.0f}",
    )
    check(
        "目标 = 单台电表 6,322 × 2 = 12,644 kWh（电网侧）",
        abs(verdict["target_grid_kwh"] - 12644.0) < 0.5,
        f"{verdict['target_grid_kwh']:,.0f}",
    )
    check(
        "目标轮周 = 12,644 × 0.86",
        abs(verdict["target_wheel_kwh"] - 12644.0 * TRACTION_EFFICIENCY) < 0.5,
        f"{verdict['target_wheel_kwh']:,.0f}",
    )

    # ---- 9. 时分不被打乱 ----
    check(
        "双机分支时分在 405–420 min（未偏离运行图）",
        405.0 <= primary["running_minutes"] <= 420.0,
        f"{primary['running_minutes']:.1f} min",
    )

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"牵引归因：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"牵引归因：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
