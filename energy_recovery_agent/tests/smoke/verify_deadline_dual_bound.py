"""守图定代价（对偶下界）的闸门测试。

守五件事：

1. **上下界夹住了**——下界 ≤ 可行解，且间隙要小（本例 < 5%）。只有一个数
   而没有界，就分不清「最优」与「某个策略」；
2. **可行解真的可行**——全部检查点不晚点，最小余量不能是负的；
3. **价格是个小量**——「不晚点」相对「只限总时分」的代价必须是百分之几，
   不是上一轮算出的 +40%。这一条直接锁住本轮的核心结论；
4. **顺序分解的数字不能再被引用为最优**——它必须显著高于本工具的可行解，
   否则说明这轮改进没有真正生效；
5. **站停没有被漏扣**——241.77 km 之后所有检查点的截止时刻必须比到站时刻
   早 25 min。写错一次，整个下界都会偏松。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs" / "speed_profile_dual"
PAYLOAD_PATH = OUT / "speed_profile_dual.json"
PROFILE_PATH = OUT / "dual_speed_profile.csv"
CP_PATH = OUT / "cp_bounds.csv"

MAX_GAP_RATIO = 0.05        # 对偶间隙上限
MAX_PRICE_RATIO = 0.05      # 「守图定」价格上限
SECTIONED_KWH = 16782.0

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言。"""

    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def test_deadline_mapping() -> None:
    """站停必须从截止时刻里扣掉，且只扣一次。"""

    from tools.plan_speed_profile_dual import build_context
    from tools.plan_speed_profile_sectioned import diagram_checkpoints

    context = build_context(200.0, 0.5)
    rows = context["deadlines"]
    raw, _stops = diagram_checkpoints(context["window_end_km"])

    stop = next(row for row in rows if row["dwell_minutes"] > 1e-9)
    after = rows[rows.index(stop) + 1]
    raw_after = raw[after["index"]]

    check(
        "站停位置 241.77 km 被识别",
        abs(stop["position_km"] - 241.77) < 0.05,
        f"{stop['position_km']:.2f} km，{stop['dwell_minutes']:.0f} min",
    )
    check(
        "站停之后的截止时刻 = 到站时刻 − 25 min",
        abs(after["deadline_minutes"] - (raw_after["target_minutes"] - 25.0)) < 1e-6,
        f"{after['name']}：{after['deadline_minutes']:.1f} vs "
        f"{raw_after['target_minutes']:.1f} − 25",
    )
    check(
        "站停之前的截止时刻不扣（只扣一次）",
        abs(stop["deadline_minutes"] - raw[stop["index"]]["target_minutes"]) < 1e-6
        and abs(stop["dwell_before_minutes"]) < 1e-9,
        f"{stop['name']}：{stop['deadline_minutes']:.1f} = 到站 {raw[stop['index']]['target_minutes']:.1f}",
    )
    check(
        "截止时刻严格递增",
        all(b["deadline_minutes"] > a["deadline_minutes"] for a, b in zip(rows, rows[1:])),
        f"{rows[0]['deadline_minutes']:.1f}→{rows[-1]['deadline_minutes']:.1f} min",
    )


def test_edge_lambda_shape() -> None:
    """λ 必须是位置的非增阶梯，且最左端等于 μ 之和。"""

    import numpy as np

    from tools.plan_speed_profile_dual import edge_lambdas

    edges = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    mu = [0.0, 3.0, 0.0, 7.0]
    positions = [0.0, 0.2, 0.4, 0.5]
    lambdas = edge_lambdas(mu, positions, edges)
    check(
        "λ 最左端 = 全部乘子之和",
        abs(lambdas[0] - 10.0) < 1e-9,
        f"{lambdas.tolist()}",
    )
    check(
        "λ 是非增阶梯",
        all(b <= a + 1e-12 for a, b in zip(lambdas, lambdas[1:])),
        f"{lambdas.tolist()}",
    )
    check(
        "λ 末段只被最后一个检查点罚到",
        abs(lambdas[-1] - 7.0) < 1e-9,
        f"{lambdas[-1]:.2f}",
    )


def main() -> int:
    """跑全部断言。"""

    if not PAYLOAD_PATH.exists():
        print(f"缺少 {PAYLOAD_PATH}，先跑 tools/plan_speed_profile_dual.py")
        return 2

    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    lower = float(payload["lower_bound_kwh"])
    primal = float(payload["primal_kwh"])
    reference = payload.get("reference_kwh")
    checkpoints = payload["checkpoints"]

    # ---- 1. 上下界 ----
    check(
        "下界 ≤ 可行解",
        lower <= primal + 1e-6,
        f"{lower:,.0f} ≤ {primal:,.0f} kWh",
    )
    gap_ratio = primal / lower - 1.0
    check(
        "对偶间隙 < 5%",
        gap_ratio < MAX_GAP_RATIO,
        f"{gap_ratio:.2%}",
    )
    check(
        "下界高于顺序分解的一半（没退化成平凡界）",
        lower > SECTIONED_KWH * 0.5,
        f"{lower:,.0f} kWh",
    )

    # ---- 2. 可行解真的可行 ----
    min_slack = min(row["slack_minutes"] for row in checkpoints[1:])
    check(
        "全部检查点不晚点",
        min_slack >= -0.05,
        f"最小余量 {min_slack:+.2f} min",
    )
    check(
        "可行解标记为 feasible",
        bool(payload["primal_feasible"]),
        f"{payload['primal_minutes']:.1f} min",
    )
    check(
        "运行时分不超过图定",
        payload["primal_minutes"] <= payload["deadline_last_minutes"] + 0.5,
        f"{payload['primal_minutes']:.1f} vs {payload['deadline_last_minutes']:.1f} min",
    )

    # ---- 3. 价格是个小量 ----
    if isinstance(reference, (int, float)):
        price_ratio = primal / float(reference) - 1.0
        check(
            "「守图定」价格 < 5%（不是上一轮的 +40%）",
            price_ratio < MAX_PRICE_RATIO,
            f"{primal:,.0f} vs 无约束 {reference:,.0f} → {price_ratio:+.2%}",
        )
        check(
            "可行解高于无区间约束（方向不能反）",
            primal >= float(reference) - 1.0,
            f"{primal:,.0f} ≥ {reference:,.0f}",
        )
    else:
        check("无区间约束基准存在", False, "缺 reference_kwh")

    # ---- 4. 顺序分解不能再被当作最优 ----
    if isinstance(payload.get("punctual_kwh"), (int, float)):
        check(
            "顺序分解显著高于本工具可行解",
            float(payload["punctual_kwh"]) > primal * 1.05,
            f"{payload['punctual_kwh']:,.0f} vs {primal:,.0f} kWh"
            f"（{payload['punctual_kwh'] / primal - 1:+.0%}）",
        )
    else:
        check("顺序分解对照存在", False, "缺 punctual_kwh")

    # ---- 5. 乘子结构 ----
    mus = payload["mu"]
    check(
        "乘子全部非负",
        all(value >= 0.0 for value in mus),
        f"max {max(mus):.1f}",
    )
    check(
        "最后一个检查点乘子为正（总时分一定在用）",
        mus[-1] > 0.0,
        f"{mus[-1]:.1f}",
    )
    active = [index for index, value in enumerate(mus) if value > 1.0]
    check(
        "活跃乘子数量很少（图定区间时分普遍宽裕）",
        len(active) <= 6,
        f"{len(active)} 个活跃：{active}",
    )

    # ---- 6. 产物可读 ----
    if PROFILE_PATH.exists():
        import csv

        with PROFILE_PATH.open("r", encoding="utf-8-sig") as handle:
            profile = list(csv.DictReader(handle))
        over = [
            row for row in profile
            if float(row["speed_kmh"]) > float(row["speed_limit_kmh"]) + 1e-6
        ]
        check("剖面不超限速", not over, f"{len(profile)} 点，越限 {len(over)}")
        check(
            "剖面覆盖到窗口端点",
            float(profile[-1]["position_km"]) > 395.0,
            f"{profile[-1]['position_km']} km",
        )
    else:
        check("剖面产物存在", False, "缺 dual_speed_profile.csv")

    if CP_PATH.exists():
        check("逐检查点表存在", True, "cp_bounds.csv")
    else:
        check("逐检查点表存在", False, "缺 cp_bounds.csv")

    # ---- 7. 内置回归 ----
    test_deadline_mapping()
    test_edge_lambda_shape()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"守图定代价（对偶）：FAIL（{len(failed)}/{len(_results)} 项未通过）")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"守图定代价（对偶）：PASS（{len(_results)}/{len(_results)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
