"""动能飞行参数扫描的口径断言。

守三件事：
1. 掉速容差确实单调地「省电但费时」——两个方向都要有序，否则说明控制器有反直觉分支。
2. droop=4 能把牵引压到实测水平，但同时超图定——这条是本轮的核心结论，必须可复算。
3. 惰行带放宽时，制动功几乎不变而再生塌掉——这是「不能靠放宽 band 省电」的判据。

依赖 ``outputs/flight_strategy/``；缺文件时跳过（发布包不含 outputs/）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "outputs" / "flight_strategy" / "flight_strategy.json"
MD_PATH = ROOT / "outputs" / "flight_strategy" / "动能飞行参数扫描.md"

PASSED = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    if not JSON_PATH.exists():
        print(f"跳过：缺少 {JSON_PATH}")
        return 0

    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    target = payload["target"]
    droop = payload["droop_sweep"]
    band = payload["band_sweep"]

    print("动能飞行参数扫描：")

    # ---- 1. 单调性 ----
    tractions = [r["traction_kwh"] for r in droop]
    minutes = [r["minutes"] for r in droop]
    check(
        "掉速容差越大 → 牵引单调不增",
        all(b <= a + 1e-6 for a, b in zip(tractions, tractions[1:])),
        " → ".join(f"{v:,.0f}" for v in tractions[:4]),
    )
    check(
        "掉速容差越大 → 时分单调不减",
        all(b >= a - 1e-6 for a, b in zip(minutes, minutes[1:])),
        " → ".join(f"{v:.0f}" for v in minutes[:4]),
    )

    # ---- 2. 能耗—时分冲突 ----
    base = droop[0]
    check(
        f"基线牵引在 18,000–20,000 kWh（接入 1+1 后的反应式基线）",
        18000 <= base["traction_kwh"] <= 20000,
        f"{base['traction_kwh']:,.0f}",
    )
    best = min(droop, key=lambda r: abs(r["traction_kwh"] - target["traction_kwh"]))
    check(
        "存在掉速容差档位把牵引压到实测 ±10%",
        abs(best["traction_kwh"] / target["traction_kwh"] - 1) <= 0.10,
        f"droop={best['droop_mps']} → {best['traction_kwh']:,.0f} kWh",
    )
    check(
        "该档位的时分超出图定（能耗与时分硬冲突）",
        best["minutes"] > target["schedule_minutes"] + 10,
        f"{best['minutes']:.0f} vs 图定 {target['schedule_minutes']:.0f} min",
    )
    check(
        "基线时分本身已不优于实测（慢却更费电）",
        base["minutes"] >= target["measured_minutes"],
        f"{base['minutes']:.0f} vs 实测 {target['measured_minutes']:.0f} min",
    )

    # ---- 3. 惰行带的副作用 ----
    first, last = band[0], band[-1]
    brake_change = abs(last["brake_work_kwh"] / first["brake_work_kwh"] - 1)
    check(
        "放宽惰行带后制动功几乎不变（<5%）",
        brake_change < 0.05,
        f"{first['brake_work_kwh']:,.0f} → {last['brake_work_kwh']:,.0f}",
    )
    regen_drop = 1 - last["regen_kwh"] / first["regen_kwh"]
    check(
        "但再生塌掉一半以上（不能靠放宽 band 省电）",
        regen_drop > 0.5,
        f"{first['regen_kwh']:,.0f} → {last['regen_kwh']:,.0f}（−{regen_drop:.0%}）",
    )
    check(
        "净值由负转正（放宽 band 会把净发电算成净耗电）",
        first["net_kwh"] < 0 < last["net_kwh"],
        f"{first['net_kwh']:,.0f} → {last['net_kwh']:,.0f}",
    )

    # ---- 4. 报告 ----
    text = MD_PATH.read_text(encoding="utf-8") if MD_PATH.exists() else ""
    check("报告存在且写明「不能靠调参补上」", "不能" in text or "硬冲突" in text)
    check("报告写明了惰行带的机制（电制动按受力上限吃不下）", "电制动" in text and ("上限" in text or "硬刹" in text))
    check("报告给出了下一步（前瞻式剖面）", "前瞻" in text)

    print()
    print(f"动能飞行扫描：{'PASS' if FAILED == 0 else 'FAIL'}（{PASSED}/{PASSED + FAILED}）")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
