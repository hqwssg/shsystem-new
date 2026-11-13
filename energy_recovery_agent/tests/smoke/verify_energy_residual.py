"""牵引残差归因的闸门测试。

守四件事：

1. **能量账是平的**——恒等式残差必须 < 牵引的 1%。账不平的话，后面所有
   杠杆反解都是在错误的基数上做除法；
2. **牵引确实是个小残差**——必须只占输入侧毛吞吐的一小部分。这一条是
   「20.8% 不等于模型误差 20.8%」这个结论的全部依据，被改坏就全盘失效；
3. **杠杆的定性结论不能翻**——效率反解必须 >1（排除效率方向）、质量必须
   需要 >10% 的改动（排除吨位方向）、坡道必须在 3% 以内（保留高程方向）；
4. **再生不能当解释**——全额计入后净值必须为负，且与电表消耗符号相反。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "energy_residual"
PAYLOAD_PATH = OUT / "energy_residual.json"
LEVERS_PATH = OUT / "levers.csv"


_results: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def lever(payload: dict, key: str) -> dict:
    """按杠杆名取一项。"""

    for item in payload["levers"]:
        if item["lever"].startswith(key):
            return item
    raise KeyError(f"缺杠杆 {key}：{[x['lever'] for x in payload['levers']]}")


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/attribute_energy_residual.py")
        return 2

    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    totals = payload["totals"]
    traction = totals["traction_kwh"]
    brake = totals["brake_kwh"]
    grade = -totals["grade_kwh"]
    basic = totals["basic_kwh"]
    residual = totals["residual_kwh"]

    # ---- 1. 账是平的 ----
    check(
        "恒等式残差 < 牵引的 1%",
        abs(residual) / traction < 0.01,
        f"{residual:+.1f} kWh（{abs(residual) / traction:.3%}）",
    )
    check(
        "坡道放能量级正确（90,000–93,000 kWh）",
        90000.0 <= grade <= 93000.0,
        f"{grade:,.0f} kWh（降 {payload['drop_m']:,.0f} m）",
    )
    check(
        "制动耗散大于牵引（说明是「加速又刹掉」的往复）",
        brake > traction,
        f"{brake:,.0f} vs {traction:,.0f} kWh",
    )

    # ---- 2. 牵引是小残差 ----
    gross = traction + grade
    share = traction / gross
    check(
        "牵引只占输入侧毛吞吐 < 25%",
        share < 0.25,
        f"{share:.1%}（坡道放能 / 牵引 = {grade / traction:.1f}×）",
    )
    check(
        "缺口相对于坡道功 < 5%",
        (traction - payload["target_wheel_kwh"]) / grade < 0.05,
        f"{(traction - payload['target_wheel_kwh']) / grade:.2%}",
    )

    # ---- 3. 杠杆定性结论 ----
    eta = lever(payload, "牵引效率")
    eta_required = float(eta["required"])
    check(
        "效率反解出 η>1（排除效率方向）",
        eta_required > 1.0,
        f"需要 η={eta_required:.3f}",
    )
    mass = lever(payload, "列车总质量")
    mass_change = abs(float(mass["change"].rstrip("%")))
    check(
        "质量需要 >10% 的改动（排除吨位方向）",
        mass_change > 10.0,
        f"{mass['change']}",
    )
    grade_lever = lever(payload, "坡道功")
    grade_change = abs(float(grade_lever["change"].rstrip("%")))
    check(
        "坡道只需 ≤3% 的改动（保留高程方向）",
        grade_change <= 3.0 and grade_lever["plausible"],
        f"{grade_lever['change']}",
    )
    resistance = lever(payload, "基本阻力")
    check(
        "阻力需要 >4%（超出既有 2–4% 标定带）",
        abs(float(resistance["change"].rstrip("%"))) > 4.0 and not resistance["plausible"],
        f"{resistance['change']}",
    )
    check(
        "恰好两个杠杆被判可信",
        sum(1 for item in payload["levers"] if item["plausible"]) == 2,
        ", ".join(item["lever"] for item in payload["levers"] if item["plausible"]),
    )

    # ---- 4. 再生不能当解释 ----
    regen = payload["regen"]
    check(
        "再生全额计入后净值为负（与电表消耗符号相反）",
        regen["net_if_all_recovered_kwh"] < 0.0,
        f"{regen['net_if_all_recovered_kwh']:,.0f} kWh vs 电表 {payload['meter_grid_kwh']:,.0f}",
    )
    check(
        "再生大于牵引（量级上不可能是小修正）",
        regen["regen_over_traction"] > 1.0,
        f"{regen['regen_over_traction']:.1f}× 牵引",
    )

    # ---- 5. 产物可读 ----
    check("杠杆表存在", LEVERS_PATH.exists(), "levers.csv")

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"牵引残差归因：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"牵引残差归因：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
