"""逐区间图定时刻硬约束的闸门测试。

守三件事：

1. **约束真的被满足**——所有检查点的累计时刻不晚于图定（允许两处已识别的
   图定不可达段，但缺口必须 ≤ 4 min 且被如实标注）；
2. **口径没退回去**——约束必须写在累计时刻上。曾经写成「逐区间时分 ≤ 图定」，
   结果把前段合法挪用的余量判成违规，一半区间报假阳性；
3. **站停没被重复扣**——241.77 km 的 25 min 站停既不在区间运行时分里，
   又要计入总时分。写错过一次，全列凭空晚点 24 min。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "speed_profile_sectioned"
PAYLOAD_PATH = OUT / "speed_profile_sectioned.json"
PROFILE_PATH = OUT / "sectioned_speed_profile.csv"

METERED_WHEEL_KWH = 10874.0
METERED_MINUTES = 410.0
MAX_ALLOWED_LATE = 4.0

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def test_checkpoints() -> None:
    """锁住检查点的构造：单调、最后一个在窗口端点、停站被识别出来。"""

    from tools.plan_speed_profile_sectioned import diagram_checkpoints

    checkpoints, stops = diagram_checkpoints(395.9)
    positions = [row["position_km"] for row in checkpoints]
    targets = [row["target_minutes"] for row in checkpoints]
    check(
        "检查点位置严格递增",
        all(b > a for a, b in zip(positions, positions[1:])),
        f"{len(positions)} 个点，{positions[0]:.2f}→{positions[-1]:.2f} km",
    )
    check(
        "检查点目标时刻严格递增",
        all(b > a for a, b in zip(targets, targets[1:])),
        f"{targets[0]:.1f}→{targets[-1]:.1f} min",
    )
    check(
        "窗口端点被补成检查点",
        abs(positions[-1] - 395.9) < 1e-6,
        f"{positions[-1]:.2f} km",
    )
    check(
        "识别出唯一的停站作业位置",
        len(stops) == 1 and abs(stops[0] - 241.77) < 0.01,
        f"{stops}",
    )
    dwell_total = sum(row["dwell_minutes"] for row in checkpoints)
    check(
        "停站时分被单独记录（25 min）",
        abs(dwell_total - 25.0) < 0.5,
        f"{dwell_total:.1f} min",
    )


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/plan_speed_profile_sectioned.py")
        return 2

    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    rows = payload["sections"]
    energy = float(payload["total_energy_kwh"])
    running = float(payload["total_running_minutes"])
    dwell = float(payload["total_dwell_minutes"])
    total = float(payload["total_minutes"])
    diagram_total = float(payload["diagram_total_minutes"])

    # ---- 1. 结构 ----
    check("区间数完整（22 段）", len(rows) == 22, f"{len(rows)} 段")
    check(
        "总时分 = 区间运行 + 站停",
        abs(total - (running + dwell)) < 0.2,
        f"{running:.1f} + {dwell:.0f} = {total:.1f} min",
    )
    check(
        "站停 25 min 只计一次（没被塞进区间运行）",
        abs(dwell - 25.0) < 0.5 and total < diagram_total + 5.0,
        f"dwell={dwell:.0f} min，总 {total:.1f} vs 图定 {diagram_total:.1f}",
    )

    # ---- 2. 约束真的满足 ----
    late_rows = [row for row in rows if not row["feasible"]]
    worst_late = max(row["lateness_minutes"] for row in rows)
    check(
        "总时分不超过图定",
        total <= diagram_total + 1.0,
        f"{total:.1f} vs {diagram_total:.1f} min",
    )
    check(
        "晚点段数量 ≤ 2（已识别的图定不可达处）",
        len(late_rows) <= 2,
        f"{len(late_rows)} 段：" + ", ".join(
            f"{row['from_km']:.0f}–{row['to_km']:.0f} km {row['lateness_minutes']:+.2f}"
            for row in late_rows
        ),
    )
    check(
        "最大晚点 ≤ 4 min",
        worst_late <= MAX_ALLOWED_LATE,
        f"{worst_late:+.2f} min",
    )
    check(
        "累计时刻单调递增",
        all(
            b["cumulative_plan_minutes"] >= a["cumulative_plan_minutes"] - 1e-6
            for a, b in zip(rows, rows[1:])
            if a["segment"] == b["segment"]
        ),
        "同一段内严格不减",
    )
    check(
        "每段运行时分都为正",
        all(row["plan_section_minutes"] > 0.0 for row in rows),
    )

    # ---- 3. 与其他口径的关系 ----
    check(
        "本工具优于现网反应式控制器（18,716 kWh）",
        energy < 18716.0,
        f"{energy:,.0f} kWh（−{1 - energy / 18716.0:.1%}）",
    )
    comparable = payload.get("unconstrained_same_running_kwh")
    check(
        "无约束对照存在且更低（守图定要付代价）",
        isinstance(comparable, (int, float)) and comparable < energy,
        f"无约束 {comparable:,.0f} → 约束 {energy:,.0f} kWh"
        if isinstance(comparable, (int, float))
        else "缺对照",
    )
    check(
        "λ 全部为有限非负值",
        all(0.0 <= row["lambda"] < 1e9 for row in rows),
        f"max λ = {max(row['lambda'] for row in rows):.1f}",
    )

    # ---- 4. 剖面产物可读 ----
    if PROFILE_PATH.exists():
        import csv

        with PROFILE_PATH.open("r", encoding="utf-8-sig") as handle:
            profile = list(csv.DictReader(handle))
        over = [
            row for row in profile
            if float(row["speed_kmh"]) > float(row["speed_limit_kmh"]) + 1e-6
        ]
        check(
            "剖面不超限速",
            not over,
            f"{len(profile)} 点，越限 {len(over)}",
        )
        check(
            "剖面覆盖到窗口端点",
            float(profile[-1]["position_km"]) > 395.0,
            f"{profile[-1]['position_km']} km",
        )
    else:
        check("剖面产物存在", False, "缺 sectioned_speed_profile.csv")

    # ---- 5. 内置回归 ----
    test_checkpoints()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"逐区间硬约束：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"逐区间硬约束：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
