"""电表计量口径的闸门测试。

守四件事：

1. **读数就是全列**——`use_ygdn` 必须等于 a+b+c。这一条是「不需要 ×2」的全部
   依据；一旦它被改坏，目标电量又会回到 12,644，后面所有结论跟着翻。
2. **重车净发电、空车净耗电**——方向不能反。这是「重空协同 + 储能」的物理前提，
   反了整套方案就没有意义。
3. **单表读数远小于趟级读数**——用来钉死「读数只是一台机车」这个已被否决的说法：
   表里根本没有「一台 6,322」这种数据。
4. **势能下界不能当判据**——动能缓冲的复用比必须远大于 1。若它退化成 ≈1，
   说明坡度被抹平了，那时单块缓冲下界才会重新变得有效（而实测已经否决了它）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "meter_scope"
PAYLOAD_PATH = OUT / "meter_scope.json"

_results: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/analyze_meter_scope.py")
        return 2
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))

    audit = payload["scope_audit_two_wan"]
    heavy = payload["heavy_two_wan"]
    empty = payload["empty_all"]
    gradient = payload["gradient"]

    # ---- 1. 口径：读数 = 三表之和 ----
    check(
        "审计覆盖足够多车次",
        audit["checked"] >= 1000,
        f"{audit['checked']:,} 趟",
    )
    check(
        "a+b+c = use_ygdn 的吻合率 ≥ 99%",
        audit["match_rate"] >= 0.99,
        f"{audit['match_rate']:.1%}（{audit['matched']:,}/{audit['checked']:,}）",
    )
    check(
        "中位偏差 ≤ 1 kWh（只有取整误差）",
        audit["median_abs_diff"] <= 1.0,
        f"{audit['median_abs_diff']:.1f} kWh",
    )
    counts = audit["by_meter_count"]
    three = counts.get(3) or counts.get("3")
    two = counts.get(2) or counts.get("2")
    check("存在三表车次且占多数", bool(three) and bool(two) and three["n"] > two["n"],
          f"3 表 {three['n']:,} 趟 vs 2 表 {two['n']:,} 趟" if three and two else "缺分组")
    check(
        "电表块数越多、趟级电量越高（汇总而非单表）",
        bool(three) and bool(two) and three["median"] > two["median"],
        f"{three['median']:,.0f} vs {two['median']:,.0f} kWh" if three and two else "",
    )

    check(
        "三表车次的三个 ammeterid 互不相同（≥70%）",
        audit["distinct_id_three_share"] >= 0.70,
        f"{audit['distinct_id_three_share']:.1%}",
    )

    # 决定性交叉检验：表数跟的是「节数」，不是「台数」。
    # 神华 12 轴的 axle_arrangement 是 3(B0-B0)（3 节 × 4 轴），一表一节，
    # 所以单机 233 有三块表；带补机的双机 231 反而只有两块。
    # 若这条断言反转（231 三表、233 两表），「三表 = 三台」才可能成立。
    by_type = audit["by_train_type"]
    single = by_type.get("233", {})
    double = by_type.get("231", {})
    check(
        "12 轴 233 三表占多数、8 轴 231 无三表（表数对应节数而非台数）",
        int(single.get("3", 0)) > int(single.get("2", 0)) and int(double.get("3", 0)) == 0,
        f"233: 三表 {single.get('3', 0):,} / 两表 {single.get('2', 0):,}；"
        f"231: 三表 {double.get('3', 0):,} / 两表 {double.get('2', 0):,}",
    )

    # ---- 2. 三个口径的量级 ----
    gross = heavy["gross_kwh"]["median"]
    feed = heavy["feed_kwh"]["median"]
    net = heavy["net_kwh"]["median"]
    check(
        "重车毛牵引落在 5,500–7,000 kWh",
        5500.0 <= gross <= 7000.0,
        f"{gross:,.0f} kWh",
    )
    check(
        "重车毛牵引不是 12,644（翻倍口径已作废）",
        abs(gross - 12644.0) > 3000.0,
        f"{gross:,.0f} 距 12,644 有 6,000 以上",
    )
    check(
        "重车反馈落在 12,000–17,000 kWh",
        12000.0 <= feed <= 17000.0,
        f"{feed:,.0f} kWh",
    )
    check("重车净值为负（净发电）", net < 0.0, f"{net:,.0f} kWh")
    check(
        "重车反馈大于毛牵引（净发电的直接证据）",
        feed > gross,
        f"反馈 {feed:,.0f} > 牵引 {gross:,.0f}",
    )

    # ---- 3. 空车方向必须反向 ----
    empty_net = empty["net_kwh"]["median"]
    empty_feed = empty["feed_kwh"]["median"]
    check("空车净值为正（净耗电）", empty_net > 0.0, f"{empty_net:,.0f} kWh")
    check("空车反馈接近零（无制动工况）", empty_feed < 200.0, f"{empty_feed:,.0f} kWh")
    check(
        "空车耗电大于重车发电（一对车仍净耗）",
        empty_net > abs(net),
        f"{empty_net:,.0f} vs {abs(net):,.0f}",
    )
    pair = payload.get("round_trip") or {}
    check(
        "一对重空车净耗落在 15,000–19,000 kWh",
        15000.0 <= (pair.get("round_trip_kwh") or 0.0) <= 19000.0,
        f"{pair.get('round_trip_kwh', 0):,.0f} kWh",
    )

    # ---- 4. 势能下界的适用性 ----
    check(
        "累计爬升与既有口径一致（150–180 m）",
        150.0 <= gradient["cumulative_climb_m"] <= 180.0,
        f"{gradient['cumulative_climb_m']:.1f} m",
    )
    check(
        "坡度确实起伏（变号次数 ≥ 50）",
        gradient["sign_flips"] >= 50,
        f"{gradient['sign_flips']} 次",
    )
    check(
        "动能缓冲复用比远大于 1（单块缓冲下界不适用）",
        gradient["buffer_reuse_ratio"] >= 5.0,
        f"缓冲 {gradient['ke_buffer_kwh']:,.0f} kWh ÷ 每段 {gradient['per_dip_kwh']:,.0f} kWh "
        f"= {gradient['buffer_reuse_ratio']:.0f}×",
    )

    # ---- 5. 取证 ----
    references = payload.get("reference_trips") or []
    check("取证车次不少于 3 趟", len(references) >= 3, f"{len(references)} 趟")
    check(
        "取证车次全部是三表",
        all(row["meter_count"] == 3 for row in references),
        "、".join(str(row["meter_count"]) for row in references),
    )
    check(
        "取证车次的单表读数都远小于趟级读数",
        all(max(row["meter_values"]) < 0.6 * row["gross_kwh"] for row in references),
        f"单表最大 {max(max(row['meter_values']) for row in references):,.0f} "
        f"vs 趟级 {references[0]['gross_kwh']:,.0f}",
    )

    # ---- 6. 产物 ----
    check("报告存在", (OUT / "计量口径判定与重空基准.md").exists(), "")
    check("图存在", (OUT / "重空实测电量.png").exists(), "")

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"计量口径：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"计量口径：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
