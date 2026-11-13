"""清点工具的口径断言。

守的是三件事：
1. 电表台账 = 一台机车（3 节）——用单车台账交叉锁定，别再把单机读数当整列。
2. 里程口径——PDF 区间公里合计必须等于 stations.csv，且项目在用的 396.5 km 有明确差额。
3. 曲线阻力——量级已知，不足以解释历史偏差，避免下次又把它当主因。
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.audit_data_inventory import (  # noqa: E402
    read_ammeter_trips,
    read_curve_stats,
    read_distance_check,
    read_single_loco,
)

PASSED = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    tag = "PASS" if ok else "FAIL"
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    print(f"[{tag}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    print("数据清点口径：")

    # ---------------- 1. 计量对象 ----------------
    ledger = read_ammeter_trips(limit=4000)
    single = read_single_loco()

    check("趟级台账可读且趟数充足", len(ledger) >= 500, f"{len(ledger)} 趟")

    gross = statistics.median(x["gross_kwh"] for x in ledger)
    feed = statistics.median(x["feed_kwh"] for x in ledger)
    check("重车毛牵引落在 5,000–7,500 kWh", 5000 <= gross <= 7500, f"{gross:,.0f} kWh")
    check("重车反馈落在 12,000–18,000 kWh", 12000 <= feed <= 18000, f"{feed:,.0f} kWh")
    check("重车净值为负（净发电）", feed > gross, f"{gross - feed:,.0f} kWh")

    check("单车台账可读", bool(single), single.get("file", ""))
    check("单车台账的 A/B/C 三节之和等于总能耗", single.get("section_sum_matches_total") is True)
    check("单车台账恰为 3 节", single.get("section_count") == 3, str(single.get("section_count")))

    # 两条独立台账同量级 —— 这是「台账=单机」的核心判据
    if single:
        ratio = single["gross_median"] / gross if gross else 0
        check(
            "单车台账与趟级台账毛牵引同量级（比值 0.6–1.6）",
            0.6 <= ratio <= 1.6,
            f"{single['gross_median']:,.0f} / {gross:,.0f} = {ratio:.2f}",
        )
        fratio = single["feed_median"] / feed if feed else 0
        check(
            "单车台账与趟级台账反馈同量级（比值 0.6–1.6）",
            0.6 <= fratio <= 1.6,
            f"{single['feed_median']:,.0f} / {feed:,.0f} = {fratio:.2f}",
        )
        check(
            "单车台账单耗落在 5–12 kWh/万吨公里",
            5 <= single["unit_median"] <= 12,
            f"{single['unit_median']:.2f}",
        )

    three = sum(1 for x in ledger if x["meters"] == 3) / len(ledger)
    check("三块表车次占多数（≥70%）", three >= 0.70, f"{three:.0%}")

    # ---------------- 2. 假设表口径 ----------------
    assumptions = json.loads(
        (ROOT / "data" / "real_shuohuang" / "assumptions.json").read_text(encoding="utf-8")
    )
    by = {a["id"]: a for a in assumptions["assumptions"]}

    loco = by.get("two_wan_ton_locomotive_count", {})
    check("两万吨台数判定为 2 台", loco.get("value") == 2, str(loco.get("value")))
    check(
        "台数依据引用了编组模式文档或运行图技术资料",
        "编组模式" in loco.get("basis", "") or "运行图技术资料" in loco.get("basis", ""),
    )
    check(
        "台数假设记录了被撤回的 1 台与 3 台两种误判",
        any(str(a.get("value")) == "1" for a in loco.get("alternatives", []))
        and any(str(a.get("value")) == "3" for a in loco.get("alternatives", [])),
    )

    subject = by.get("meter_reading_subject", {})
    check("计量对象登记为「单台机车」", "单台机车" in subject.get("value", ""), subject.get("value", "")[:40])

    resistance = by.get("freight_basic_resistance", {})
    check("阻力系数已解除 contested", resistance.get("status") == "resolved", resistance.get("status", ""))

    # ---------------- 3. 里程口径 ----------------
    dist = read_distance_check()
    check(
        "PDF 区间公里合计等于 stations.csv 的肃宁北里程（±0.5 km）",
        abs(dist["pdf_section_km"] - (dist["stations_km"] or 0)) <= 0.5,
        f"{dist['pdf_section_km']} vs {dist['stations_km']}",
    )
    check(
        "项目在用的 396.5 km 与真实里程差 8–12 km",
        8 <= abs(dist["gap_km"]) <= 12,
        f"{dist['gap_km']:+.1f} km",
    )
    check(
        "上行通通时分合计落在 350–400 min",
        350 <= dist["up_transit_first"] <= 400,
        f"{dist['up_transit_first']} min",
    )
    check(
        "通时分组两端有序（首值 ≥ 末值）",
        dist["up_transit_first"] >= dist["up_transit_last"]
        and dist["down_transit_first"] >= dist["down_transit_last"],
        f"上行 {dist['up_transit_first']}/{dist['up_transit_last']}、"
        f"下行 {dist['down_transit_first']}/{dist['down_transit_last']}",
    )

    # ---------------- 4. 曲线阻力 ----------------
    curve = read_curve_stats()
    check("曲线段数 ≥ 300", curve.get("curves", 0) >= 300, str(curve.get("curves")))
    check(
        "曲线占全线 30%–45%",
        0.30 <= curve.get("curve_share", 0) <= 0.45,
        f"{curve.get('curve_share', 0):.0%}",
    )
    check(
        "曲线阻力折到全线 < 0.5 N/kN（不足以解释历史偏差）",
        curve.get("wr_line_average_n_per_kn", 9) < 0.5,
        f"{curve.get('wr_line_average_n_per_kn')} N/kN",
    )

    print()
    total = PASSED + FAILED
    verdict = "PASS" if FAILED == 0 else "FAIL"
    print(f"数据清点：{verdict}（{PASSED}/{total}）")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
