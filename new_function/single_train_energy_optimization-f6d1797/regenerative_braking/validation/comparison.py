"""阶段 9 对比表：``baseline / optimized / delta / delta_percent``。

符号约定（必须写清，否则表会被读错）：

    delta         = optimized_value − baseline_value
    delta_percent = 100 × delta / |baseline_value|

因此 ``delta > 0`` 表示**主算法的数值比 baseline 大**，
但"大"是好是坏取决于指标方向（见 :data:`COMPARISON_METRICS` 的 ``prefer``）。
``improved`` 列把方向与符号合并成一个布尔值，避免读表的人自己心算符号。

``delta_percent`` 在 ``|baseline_value|`` 小于 :data:`PERCENT_FLOOR` 时为 ``None``：
baseline 本身接近 0 时百分比会放大成无意义的巨数（例如"不控"的回收能量恒为 0），
这时**只能看绝对差**，不能看百分比。这一点在 CSV 里表现为空单元格。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: |baseline| 低于该值时 delta_percent 记为 None
PERCENT_FLOOR = 1.0e-9


@dataclass(frozen=True)
class ComparisonMetric:
    """对比表里的一个指标。"""

    key: str
    label: str
    unit: str
    #: "higher" = 越大越好；"lower" = 越小越好；"context" = 无优劣，仅记录
    prefer: str

    def is_improvement(self, delta: float) -> Optional[bool]:
        if self.prefer == "higher":
            return delta > 0.0
        if self.prefer == "lower":
            return delta < 0.0
        return None


#: 对比表指标清单（键名与 ``ScenarioMetrics.to_flat_dict()`` 一致）
COMPARISON_METRICS: Tuple[ComparisonMetric, ...] = (
    ComparisonMetric("captured_energy_kWh", "回收能量", "kWh", "higher"),
    ComparisonMetric("storage_energy_kWh", "储能净存入能量", "kWh", "higher"),
    ComparisonMetric("storage_net_of_grid_import_energy_kWh", "扣除电网回吸的储能收益", "kWh", "higher"),
    ComparisonMetric("physical_dissipation_energy_kWh", "模型显式耗散", "kWh", "lower"),
    ComparisonMetric("regenerative_chain_loss_energy_kWh", "再生链损耗（不含摩擦制动）", "kWh", "lower"),
    ComparisonMetric("grid_import_energy_kWh", "电网回吸能量", "kWh", "lower"),
    ComparisonMetric("stored_plus_net_grid_export_energy_kWh", "净存入加净回网", "kWh", "context"),
    ComparisonMetric("capture_ratio", "捕获比例", "-", "higher"),
    ComparisonMetric("regenerative_efficiency", "再生效率", "-", "higher"),
    ComparisonMetric("grid_net_export_energy_kWh", "净回网能量", "kWh", "context"),
    ComparisonMetric("curtailed_energy_kWh", "弃能", "kWh", "lower"),
    ComparisonMetric("loss_energy_kWh", "未存入储能能量（旧总损耗）", "kWh", "lower"),
    ComparisonMetric("soc_end", "末态 SOC", "-", "context"),
    ComparisonMetric("control_effort_tv", "占空比总变差（抖振）", "-", "lower"),
    ComparisonMetric("duty_saturation_ratio", "占空比饱和比例", "-", "lower"),
    ComparisonMetric("tracking_rmse", "功率跟踪 RMSE", "W", "lower"),
    ComparisonMetric("closure_residual_kWh", "能量闭合残差", "kWh", "context"),
)

#: 用于"一行一场景"摘要的领头指标
HEADLINE_METRIC = "captured_energy_kWh"


def _value(metrics: Mapping[str, Any], key: str) -> Optional[float]:
    raw = metrics.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return value


def build_comparison_rows(
    records: Iterable[Any],
    *,
    optimized_labels: Sequence[str],
    metrics: Sequence[ComparisonMetric] = COMPARISON_METRICS,
) -> List[Dict[str, Any]]:
    """把套件运行记录展开成 ``baseline / optimized / delta / delta_percent`` 长表。

    ``records`` 里每一项需带 ``scenario_label`` / ``baseline_label`` / ``metrics``
    三个属性（:class:`regenerative_braking.validation.suite.SuiteRunRecord` 满足）。
    ``optimized_labels`` 给出哪些 label 作为 optimized 侧；同一场景下若有多项
    （如族 7 的固定 EKF / 固定 UKF），会分别与每个 baseline 配对。
    """

    # {(scenario, label): metrics}
    table: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    scenario_order: List[str] = []
    for record in records:
        key = (record.scenario_label, record.baseline_label)
        table[key] = record.metrics
        if record.scenario_label not in scenario_order:
            scenario_order.append(record.scenario_label)

    rows: List[Dict[str, Any]] = []
    for scenario_label in scenario_order:
        labels = [label for (scen, label) in table if scen == scenario_label]
        optimized_present = [label for label in optimized_labels if label in labels]
        baselines = [label for label in labels if label not in optimized_labels]

        for optimized_label in optimized_present:
            optimized_metrics = table[(scenario_label, optimized_label)]
            for baseline_label in baselines:
                baseline_metrics = table[(scenario_label, baseline_label)]
                for metric in metrics:
                    baseline_value = _value(baseline_metrics, metric.key)
                    optimized_value = _value(optimized_metrics, metric.key)
                    if baseline_value is None or optimized_value is None:
                        rows.append(
                            {
                                "scenario": scenario_label,
                                "baseline": baseline_label,
                                "optimized": optimized_label,
                                "metric": metric.key,
                                "metric_label": metric.label,
                                "unit": metric.unit,
                                "prefer": metric.prefer,
                                "baseline_value": baseline_value,
                                "optimized_value": optimized_value,
                                "delta": None,
                                "delta_percent": None,
                                "improved": None,
                            }
                        )
                        continue
                    delta = optimized_value - baseline_value
                    if abs(baseline_value) > PERCENT_FLOOR:
                        delta_percent: Optional[float] = 100.0 * delta / abs(baseline_value)
                    else:
                        delta_percent = None
                    rows.append(
                        {
                            "scenario": scenario_label,
                            "baseline": baseline_label,
                            "optimized": optimized_label,
                            "metric": metric.key,
                            "metric_label": metric.label,
                            "unit": metric.unit,
                            "prefer": metric.prefer,
                            "baseline_value": baseline_value,
                            "optimized_value": optimized_value,
                            "delta": delta,
                            "delta_percent": delta_percent,
                            "improved": metric.is_improvement(delta),
                        }
                    )
    return rows


def build_headline_rows(
    records: Iterable[Any],
    *,
    optimized_labels: Sequence[str],
    headline: str = HEADLINE_METRIC,
) -> List[Dict[str, Any]]:
    """只保留领头指标的一行一 (场景, baseline, optimized) 摘要，便于速览。"""

    return [
        row
        for row in build_comparison_rows(records, optimized_labels=optimized_labels)
        if row["metric"] == headline
    ]


def format_delta_percent(value: Optional[float]) -> str:
    """百分比列的可读格式（None → 空串，见模块 docstring）。"""

    if value is None:
        return ""
    return f"{value:+.2f}%"


def summarize_improvements(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """统计"主算法在多少个 (场景, baseline, 指标) 上更优 / 更差 / 持平"。"""

    better = worse = equal = unknown = 0
    for row in rows:
        improved = row.get("improved")
        if improved is None:
            unknown += 1
        elif improved:
            better += 1
        elif row.get("delta") == 0.0:
            equal += 1
        else:
            worse += 1
    return {
        "better": better,
        "worse": worse,
        "equal": equal,
        "no_verdict": unknown,
        "total": len(rows),
    }
