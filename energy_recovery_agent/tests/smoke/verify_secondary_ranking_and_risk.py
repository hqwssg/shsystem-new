"""验证技术方案解释性指标与二级择优。

覆盖：
1. 单位运量能耗 ``energy_per_transport``（kWh/(千吨·km)、kWh/(吨·km)）换算正确，零周转量安全归零；
2. ``candidate_rows`` 含单位运量能耗列且与辅助函数一致；
3. 二级择优三项子指标（时刻平滑度/作业均衡度/换班友好性）取值在 [0,1]，且能区分优劣方案；
4. ``secondary_ranking_rows`` 按主目标并列分组、组内按二级分降序择优，每组恰有一个 ``secondary_selected``；
5. 拥堵风险指数映射正确（利用率 ≤ 阈值 → 0，≥ 容量 → 1），明细可按区段/车站/时段定位；
6. 产物齐全、表头一致、``summary.json`` 含新增指标。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import (
    CONGESTION_RISK_FREE_UTILIZATION,
    HeArc,
    _coefficient_of_variation,
    _congestion_risk_index,
    _operation_balance,
    _shift_friendliness,
    _shift_boundaries,
    _timetable_smoothness,
    candidate_rows,
    congestion_risk_rows,
    energy_per_transport,
    load_he_input_template,
    optimize_heavy_empty_network,
    secondary_ranking_metrics,
    secondary_ranking_rows,
    write_optimization_outputs,
)
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("secondary_ranking_and_risk")
SCENARIO_ID = "capacity_surplus_demo"


def _small_bundle(bundle):
    """缩小搜索规模，保持结构不变。"""
    return replace(
        bundle,
        scenarios={
            name: replace(scenario, population_size=4, generations=2)
            for name, scenario in bundle.scenarios.items()
        },
    )


def _arc(**overrides) -> HeArc:
    """构造一个最小可用的运行/作业弧，便于合成候选。"""
    defaults = dict(
        arc_id="A",
        layer="train",
        demand_id="OD",
        train_id="T",
        train_type="heavy",
        from_node_id="n1",
        to_node_id="n2",
        arc_type="heavy_running",
        start_station="S1",
        end_station="S2",
        start_time_s=0,
        end_time_s=100,
        start_km=0.0,
        end_km=10.0,
        distance_km=10.0,
        energy_kwh=0.0,
        base_energy_kwh=0.0,
        avg_gradient_promille=0.0,
        curve_equivalent=0.0,
        power_arm_ids=(),
        power_arm_review_required=False,
        cost=0.0,
        capacity_resource_id="sec:S1-S2",
        source="synthetic",
    )
    defaults.update(overrides)
    return HeArc(**defaults)


def test_energy_per_transport_math(bundle) -> None:
    """单位运量能耗换算正确，零周转量安全归零。"""

    result = optimize_heavy_empty_network(_small_bundle(bundle), SCENARIO_ID)
    candidate = result.best_candidate
    metrics = energy_per_transport(candidate)
    if candidate.throughput_ton_km > 0:
        expected = candidate.energy_kwh / (candidate.throughput_ton_km / 1000.0)
        if abs(metrics["energy_per_1000_ton_km"] - expected) > 1e-3:
            raise AssertionError(f"单位运量能耗换算不一致：{metrics} vs {expected}")
        if abs(metrics["energy_per_ton_km"] * 1000.0 - metrics["energy_per_1000_ton_km"]) > 1e-3:
            raise AssertionError("两种口径不一致")
    zero = replace(candidate, throughput_ton_km=0.0)
    if energy_per_transport(zero) != {"energy_per_1000_ton_km": 0.0, "energy_per_ton_km": 0.0}:
        raise AssertionError("零周转量应安全归零")

    rows = candidate_rows([candidate], "check")
    if "energy_per_1000_ton_km" not in rows[0] or "energy_per_ton_km" not in rows[0]:
        raise AssertionError("candidate_rows 缺少单位运量能耗列")
    if abs(float(rows[0]["energy_per_1000_ton_km"]) - metrics["energy_per_1000_ton_km"]) > 1e-6:
        raise AssertionError("candidate_rows 单位运量能耗与辅助函数不一致")


def test_secondary_sub_metrics_discriminate(bundle) -> None:
    """三项子指标取值在 [0,1]，且能区分规整/不规整方案。"""

    result = optimize_heavy_empty_network(_small_bundle(bundle), SCENARIO_ID)
    base = result.best_candidate

    even = replace(
        base,
        arcs=(
            _arc(arc_id="e1", train_id="T1", start_time_s=0, end_time_s=100),
            _arc(arc_id="e2", train_id="T2", start_time_s=600, end_time_s=700),
            _arc(arc_id="e3", train_id="T3", start_time_s=1200, end_time_s=1300),
        ),
    )
    uneven = replace(
        base,
        arcs=(
            _arc(arc_id="u1", train_id="T1", start_time_s=0, end_time_s=100),
            _arc(arc_id="u2", train_id="T2", start_time_s=600, end_time_s=700),
            _arc(arc_id="u3", train_id="T3", start_time_s=5000, end_time_s=5100),
        ),
    )
    if not (_timetable_smoothness(even) > _timetable_smoothness(uneven)):
        raise AssertionError("时刻平滑度未能区分规整与不规整发车")
    if abs(_timetable_smoothness(even) - 1.0) > 1e-9:
        raise AssertionError("完全等间隔发车平滑度应为 1")

    crossing = replace(base, arcs=(_arc(arc_id="c1", start_time_s=28700, end_time_s=28900),))
    no_crossing = replace(base, arcs=(_arc(arc_id="n1", start_time_s=100, end_time_s=200),))
    if abs(_shift_friendliness(no_crossing) - 1.0) > 1e-9:
        raise AssertionError("不跨换班边界应为 1")
    if not (_shift_friendliness(crossing) < _shift_friendliness(no_crossing)):
        raise AssertionError("换班友好性未能识别跨界作业")

    balanced = replace(
        base,
        arcs=(
            _arc(arc_id="b1", arc_type="loading", start_station="A"),
            _arc(arc_id="b2", arc_type="loading", start_station="A"),
            _arc(arc_id="b3", arc_type="loading", start_station="B"),
            _arc(arc_id="b4", arc_type="loading", start_station="B"),
        ),
    )
    skewed = replace(
        base,
        arcs=(
            _arc(arc_id="s1", arc_type="loading", start_station="A"),
            _arc(arc_id="s2", arc_type="loading", start_station="A"),
            _arc(arc_id="s3", arc_type="loading", start_station="A"),
            _arc(arc_id="s4", arc_type="loading", start_station="B"),
        ),
    )
    if not (_operation_balance(balanced, bundle) > _operation_balance(skewed, bundle)):
        raise AssertionError("作业均衡度未能区分均衡与偏斜方案")

    metrics = secondary_ranking_metrics(base, bundle)
    for key in ("timetable_smoothness", "operation_balance", "shift_friendliness", "secondary_ranking_score"):
        if not (0.0 <= metrics[key] <= 1.0):
            raise AssertionError(f"二级择优指标越界：{key}={metrics[key]}")
    if abs(_coefficient_of_variation([5.0, 5.0, 5.0])) > 1e-12:
        raise AssertionError("等值序列变异系数应为 0")
    if _shift_boundaries(0) != [0]:
        raise AssertionError("边界生成异常")


def test_secondary_ranking_tie_grouping(bundle) -> None:
    """主目标并列分组、组内按二级分择优，每组恰有一个 secondary_selected。"""

    result = optimize_heavy_empty_network(_small_bundle(bundle), SCENARIO_ID)
    base = result.best_candidate
    regular = replace(
        base,
        candidate_id="TIE_REGULAR",
        score=1.0,
        arcs=(
            _arc(arc_id="r1", train_id="T1", start_time_s=0, end_time_s=100),
            _arc(arc_id="r2", train_id="T2", start_time_s=600, end_time_s=700),
            _arc(arc_id="r3", train_id="T3", start_time_s=1200, end_time_s=1300),
        ),
    )
    irregular = replace(
        base,
        candidate_id="TIE_IRREGULAR",
        score=1.0,
        arcs=(
            _arc(arc_id="i1", train_id="T1", start_time_s=0, end_time_s=100),
            _arc(arc_id="i2", train_id="T2", start_time_s=100, end_time_s=200),
            _arc(arc_id="i3", train_id="T3", start_time_s=9000, end_time_s=9100),
        ),
    )
    distinct = replace(base, candidate_id="DISTINCT", score=2.0, arcs=base.arcs)
    fake = replace(result, candidates=(regular, irregular, distinct))
    rows = secondary_ranking_rows(fake, bundle)
    if len(rows) != 3:
        raise AssertionError("二级择优行数应等于候选数")
    regular_row = next(row for row in rows if row["candidate_id"] == "TIE_REGULAR")
    irregular_row = next(row for row in rows if row["candidate_id"] == "TIE_IRREGULAR")
    if regular_row["tie_group_id"] != irregular_row["tie_group_id"]:
        raise AssertionError("同分候选应归入同一并列组")
    if regular_row["tie_group_size"] != 2:
        raise AssertionError("并列组大小应为 2")
    if regular_row["rank_within_tie"] != 1 or not regular_row["secondary_selected"]:
        raise AssertionError("规整方案应成为并列组内二级择优结果")
    if irregular_row["secondary_selected"]:
        raise AssertionError("并列组内只应有一个二级择优结果")
    if sum(1 for row in rows if row["secondary_selected"]) != 2:
        raise AssertionError("两组各应有一个二级择优结果")


def test_congestion_risk_mapping_and_locatability(bundle) -> None:
    """拥堵风险映射正确，明细可按区段/车站/时段定位。"""

    free = CONGESTION_RISK_FREE_UTILIZATION
    if _congestion_risk_index(0.0) != 0.0 or _congestion_risk_index(free) != 0.0:
        raise AssertionError("阈值以下风险应为 0")
    if abs(_congestion_risk_index(1.0) - 1.0) > 1e-9:
        raise AssertionError("达到容量风险应为 1")
    if abs(_congestion_risk_index(1.5) - 1.0) > 1e-9:
        raise AssertionError("超容量风险应封顶为 1")
    if not (0.0 < _congestion_risk_index((free + 1.0) / 2.0) < 1.0):
        raise AssertionError("阈值与容量之间应线性过渡")

    result = optimize_heavy_empty_network(_small_bundle(bundle), SCENARIO_ID)
    rows = congestion_risk_rows(result, bundle)
    if not rows:
        raise AssertionError("拥堵风险明细不应为空")
    for row in rows:
        for key in (
            "resource_type",
            "resource_id",
            "period_start_s",
            "period_end_s",
            "utilization_ratio",
            "congestion_risk_index",
        ):
            if key not in row:
                raise AssertionError(f"拥堵风险明细缺少定位字段：{key}")
        if not (0.0 <= float(row["congestion_risk_index"]) <= 1.0):
            raise AssertionError("拥堵风险指数越界")
        over = float(row["utilization_ratio"]) > 1.0
        if bool(row["over_capacity"]) != over:
            raise AssertionError("over_capacity 与利用率不一致")


def test_outputs_written_and_consistent(bundle) -> None:
    """产物齐全、表头一致、summary.json 含新增指标。"""

    small = _small_bundle(bundle)
    result = optimize_heavy_empty_network(small, SCENARIO_ID)
    write_optimization_outputs(result, OUTPUT_ROOT, bundle=small)

    for name in ("secondary_ranking.csv", "congestion_risk.csv"):
        path = OUTPUT_ROOT / name
        if not path.exists():
            raise AssertionError(f"缺少产物：{name}")

    with (OUTPUT_ROOT / "secondary_ranking.csv").open(encoding="utf-8-sig", newline="") as handle:
        rank_rows = list(csv.DictReader(handle))
    expected_rank_header = {
        "candidate_id",
        "primary_rank",
        "tie_group_id",
        "tie_group_size",
        "secondary_ranking_score",
        "rank_within_tie",
        "secondary_selected",
    }
    if not expected_rank_header.issubset(set(rank_rows[0])):
        raise AssertionError(f"secondary_ranking.csv 表头不一致：{sorted(set(rank_rows[0]))}")
    selected = [row for row in rank_rows if row["secondary_selected"] in {"True", "true", "1"}]
    groups = {row["tie_group_id"] for row in rank_rows}
    if len(selected) != len(groups):
        raise AssertionError("每个并列组应恰有一个二级择优结果")

    with (OUTPUT_ROOT / "congestion_risk.csv").open(encoding="utf-8-sig", newline="") as handle:
        risk_rows = list(csv.DictReader(handle))
    if not risk_rows:
        raise AssertionError("congestion_risk.csv 不应为空")

    summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    for key in (
        "best_energy_per_1000_ton_km",
        "best_energy_per_ton_km",
        "energy_per_transport_unit",
        "best_secondary_ranking",
        "secondary_ranking_output",
        "congestion_risk_output",
        "max_congestion_risk_index",
        "mean_congestion_risk_index",
        "over_capacity_period_count",
    ):
        if key not in summary:
            raise AssertionError(f"summary.json 缺少指标：{key}")
    if not (0.0 <= float(summary["max_congestion_risk_index"]) <= 1.0):
        raise AssertionError("summary 拥堵风险越界")

    report = (OUTPUT_ROOT / "HEAVY_EMPTY_NETWORK_REPORT.md").read_text(encoding="utf-8")
    for token in ("单位运量能耗", "二级择优综合分", "拥堵风险指数"):
        if token not in report:
            raise AssertionError(f"报告缺少内容：{token}")


def main() -> int:
    bundle = load_he_input_template(TEMPLATE)
    test_energy_per_transport_math(bundle)
    test_secondary_sub_metrics_discriminate(bundle)
    test_secondary_ranking_tie_grouping(bundle)
    test_congestion_risk_mapping_and_locatability(bundle)
    test_outputs_written_and_consistent(bundle)
    print("secondary ranking and congestion risk verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
