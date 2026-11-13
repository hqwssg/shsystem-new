#!/usr/bin/env python
"""逐区间电量对照的口径与量级断言。

这里锁的不是「模型对不对」，而是三件更容易悄悄坏掉的事：

1. **对照的两侧口径一致**。实测是电网侧、模型是轮周侧，混起来会算出 3.6 这种量级错。
2. **首段不是纯运行**。神池南→宁武西 15.9 km 实测 114 min，那是装车调车作业；
   不剔除就会被当成「爬行」，把速度统计整体拖垮。
3. **级位只改分摊、不改轨迹**。这条不变量一旦破，级位校准就会偷偷改能量总额。

跑法：``python tests/smoke/verify_section_energy.py``
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "outputs" / "section_energy"
PAYLOAD = OUT_DIR / "section_compare.json"
SWEEP = OUT_DIR / "calibration_sweep.csv"
REPORT = OUT_DIR / "逐区间电量对照.md"
FIGURE = OUT_DIR / "逐区间对照.png"

FAILED = 0


def check(label: str, passed: bool, detail: str = "") -> None:
    global FAILED
    if passed:
        print(f"[PASS] {label}" + (f"  — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"[FAIL] {label}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    for path in (PAYLOAD, SWEEP, REPORT, FIGURE):
        check(f"{path.name} 存在", path.exists(), str(path.relative_to(ROOT)))
    if not PAYLOAD.exists():
        print(f"\n逐区间对照：FAIL（{FAILED} 项）")
        return 1

    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    stats = payload["summary"]
    sections = payload["sections"]
    calibration = payload["calibration"]

    check("对照区间数 = 23", len(sections) == 23, f"{len(sections)} 段")
    check("实测行程数 ≥ 1,500", payload["observed_trips"] >= 1500,
          f"{payload['observed_trips']:,} 趟")

    # ---- 口径：实测电网侧 vs 模型轮周侧 ----
    gross_obs = stats["observed_traction_kwh"]
    # 2026-11-07：实测已换算到整列口径（电表台账 = 一台机车，两万吨 = 1+1 两台，×2）。
    check("实测毛牵引（整列）落在 10,000–13,000 kWh", 10000.0 <= gross_obs <= 13000.0,
          f"{gross_obs:,.0f} kWh")
    feed_obs = stats["observed_feed_kwh"]
    check("实测反馈（整列）落在 24,000–30,000 kWh", 24000.0 <= feed_obs <= 30000.0,
          f"{feed_obs:,.0f} kWh")

    # ---- 再生已对上 ----
    ratio_regen = stats["regen_ratio"]
    # 整列口径下模型再生偏少（实测两台各回收一份），区间放宽并记录方向。
    check("模型再生 / 实测反馈 落在 0.7–0.95（整列口径下模型偏少）",
          0.70 <= ratio_regen <= 0.95, f"{ratio_regen:.2f}×")

    # ---- 牵引仍是缺口，但量级必须守住 ----
    ratio_traction = stats["traction_ratio"]
    check("模型牵引 / 实测 落在 1.4–2.0（整列口径下的真实缺口）",
          1.4 <= ratio_traction <= 2.0, f"{ratio_traction:.2f}×")

    # ---- 时分：剔除首段作业后应基本持平 ----
    pure_obs = stats["tail_observed_minutes"]
    pure_mdl = stats["model_pure_minutes"]
    check("纯运行时分差 ≤ 15 min", abs(pure_mdl - pure_obs) <= 15.0,
          f"实测 {pure_obs:.0f} / 模型 {pure_mdl:.0f} min")
    check("模型站停 > 0（图定时分需在站内吸收）", stats["model_dwell_minutes"] > 0.0,
          f"{stats['model_dwell_minutes']:.0f} min")

    # ---- 首段是作业，不是运行 ----
    head = sections[0]
    check("首段实测速度 < 15 km/h（装车调车作业特征）",
          head["observed_speed_kmh"] < 15.0,
          f"{head['observed_speed_kmh']:.1f} km/h / {head['observed_minutes']:.0f} min")

    # ---- 两类偏差的方向 ----
    check("下坡段再生倍数 < 1.5（下坡不多回收）",
          stats["downhill_model_regen_kwh"] / max(stats["downhill_observed_feed_kwh"], 1.0) < 1.5,
          f"{stats['downhill_model_regen_kwh']:,.0f} / "
          f"{stats['downhill_observed_feed_kwh']:,.0f} kWh")
    check("平缓段牵引倍数 > 1.4（偏差仍集中在牵引）",
          stats["flat_model_traction_kwh"] / max(stats["flat_observed_traction_kwh"], 1.0) > 1.4,
          f"{stats['flat_model_traction_kwh']:,.0f} / "
          f"{stats['flat_observed_traction_kwh']:,.0f} kWh")

    # ---- 总量吻合不等于分布吻合 ----
    fed = [row for row in sections if row["observed_feed_kwh"] >= 100.0]
    high = [
        row
        for row in fed
        if row["model_regen_kwh"] / row["observed_feed_kwh"] >= 1.5
    ]
    zero = [row for row in fed if row["model_regen_kwh"] < 1.0]
    check(
        "再生总量吻合但分布不对（同时存在 ≥1.5 倍的段与再生为零的段）",
        len(high) >= 1 and len(zero) >= 1,
        f"偏高 {len(high)} 段（"
        + "、".join(str(row["index"]) for row in high)
        + f"）、为零 {len(zero)} 段（"
        + "、".join(str(row["index"]) for row in zero)
        + "）",
    )
    check(
        "报告写明了「总量吻合不等于逐段吻合」",
        "总量吻合不等于逐段吻合" in REPORT.read_text(encoding="utf-8"),
    )

    # ---- 不变量：级位只改分摊，不改轨迹 ----
    samples = calibration["samples"]
    # --no-sweep 生成的结果没有扫描样本；有样本时再校验分摊不变性。
    check("级位扫描样本 ≥ 5 档（--no-sweep 时跳过）", len(samples) >= 5 or not samples,
          f"{len(samples)} 档")
    if samples:
        tractions = {round(row["traction_kwh"], 3) for row in samples}
        brakes = {round(row["brake_work_kwh"], 3) for row in samples}
        check("级位改变时牵引恒定（分摊不改轨迹）", len(tractions) == 1,
              f"{sorted(tractions)}")
        check("级位改变时制动功恒定（分摊不改轨迹）", len(brakes) == 1,
              f"{sorted(brakes)}")
        regens = [row["regen_kwh"] for row in samples]
        check("级位增大时再生单调不减", all(b >= a for a, b in zip(regens, regens[1:])),
              f"{regens[0]:,.0f} → {regens[-1]:,.0f} kWh")

    # ---- 校准值落在标定值附近 ----
    level = calibration.get("interpolated_level")
    if level is not None:
        check("配平反馈所需级位落在 0.40–0.55（与 0.48 的标定一致）",
              0.40 <= level <= 0.55, f"{level:.3f}")

    # ---- 站停被识别（西柏坡） ----
    holds = [row for row in sections if row["hold_steps"] > 0]
    check("至少识别出一处模型站停", len(holds) >= 1,
          "、".join(f"段{row['index']}" for row in holds) or "无")

    # ---- 报告里必须写明首段口径 ----
    text = REPORT.read_text(encoding="utf-8")
    check("报告说明了首段是装车调车作业", "装车" in text and "段 0" in text)
    if samples:
        check("报告说明了级位只配平再生", "只改分摊" in text or "配平" in text)
    else:
        check("报告在无扫描时跳过级位节（不输出半截结论）", "级位校准" not in text)

    print(f"\n逐区间对照：{'PASS' if FAILED == 0 else 'FAIL'}（{FAILED} 项失败）")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
