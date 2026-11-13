#!/usr/bin/env python
"""阻力缩放扫描的断言：锁住单调性，也锁住那条容易被读错的告诫。

这个脚本防的是两件相反的事：

1. **单调性**——阻力越小牵引越小。这条若破，说明有别的项在主导，扫描就没意义。
2. **别把最优缩放当校准值**——报告必须写明「阻力缩放与控制律改进不可分辨」。

第 2 条看起来像文字工作，但它是这个工具唯一的价值所在：
一个能同时命中三项指标的缩放因子太容易被当成「找到了真阻力」，
而它其实只是把控制律的缺陷折算进了阻力。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "outputs" / "resistance_scale"
PAYLOAD = OUT_DIR / "resistance_scale.json"
CSV = OUT_DIR / "resistance_scale.csv"
REPORT = OUT_DIR / "阻力缩放扫描.md"

FAILED = 0


def check(label: str, passed: bool, detail: str = "") -> None:
    global FAILED
    if passed:
        print(f"[PASS] {label}" + (f"  — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"[FAIL] {label}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    for path in (PAYLOAD, CSV, REPORT):
        check(f"{path.name} 存在", path.exists(), str(path.relative_to(ROOT)))
    if not PAYLOAD.exists():
        print(f"\n阻力缩放扫描：FAIL（{FAILED} 项）")
        return 1

    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    samples = sorted(payload["samples"], key=lambda row: row["resistance_scale"])
    check("扫描档数 ≥ 4", len(samples) >= 4, f"{len(samples)} 档")
    check("口径为单台（trains.csv）", "locomotive_count=1" in payload["consist_note"],
          payload["consist_note"])

    base = next((row for row in samples if abs(row["resistance_scale"] - 1.0) < 1e-9), None)
    check("包含基准档 ×1.00", base is not None)
    if base:
        check("基准档牵引落在 15,000–18,500 kWh",
              15000.0 <= base["traction_kwh"] <= 18500.0, f"{base['traction_kwh']:,.0f} kWh")
        check("基准档再生落在 13,000–15,500 kWh",
              13000.0 <= base["regen_kwh"] <= 15500.0, f"{base['regen_kwh']:,.0f} kWh")

    # samples 已按缩放因子升序（阻力由小到大），所以牵引应递增、再生应递减。
    tractions = [row["traction_kwh"] for row in samples]
    check("阻力越大 → 牵引单调不减",
          all(b >= a - 1e-6 for a, b in zip(tractions, tractions[1:])),
          " → ".join(f"{v:,.0f}" for v in tractions))

    regens = [row["regen_kwh"] for row in samples]
    check("阻力越大 → 再生单调不增",
          all(b <= a + 1e-6 for a, b in zip(regens, regens[1:])),
          " → ".join(f"{v:,.0f}" for v in regens))

    best = payload["best_fit"]
    check("最优缩放落在 0.2–0.5（不是 1.0，说明基准确有偏差）",
          0.2 <= best["resistance_scale"] <= 0.5, f"×{best['resistance_scale']:.2f}")
    check("最优档三项指标都在 ±25% 内",
          abs(best["traction_ratio"] - 1.0) <= 0.25
          and abs(best["regen_ratio"] - 1.0) <= 0.25
          and abs(best["minutes_gap"]) <= 25.0,
          f"牵引 {best['traction_ratio']:.2f}× / 再生 {best['regen_ratio']:.2f}× / "
          f"时分 {best['minutes_gap']:+.1f} min")

    # ---- 告诫必须写进报告，否则这个工具只会误导人 ----
    text = REPORT.read_text(encoding="utf-8")
    check("报告写明「不可分辨」", "不可分辨" in text)
    check("报告写明不能读成「阻力只该是 35%」", "不能" in text and "35%" in text)
    check("报告引用功率可达性作为独立证据", "功率可达性" in text)
    check("报告引用了图定不可行（23,524）", "23,524" in text)
    check("payload 带 caveat 字段", "不可分辨" in payload.get("caveat", ""))

    print(f"\n阻力缩放扫描：{'PASS' if FAILED == 0 else 'FAIL'}（{FAILED} 项失败）")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
