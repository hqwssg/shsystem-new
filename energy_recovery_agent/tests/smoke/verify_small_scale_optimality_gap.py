"""验证小规模精确解与离散域启发式差距计算。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    clamp_template,
    energy_scenario_objective,
    template_key,
)
from tools.small_scale_optimality_gap_benchmark import (
    _gap_statistics,
    _gap_label,
    _write_report,
    build_discrete_domain,
    compare_exact_and_heuristic,
)


def _score(template: ScheduleTemplate) -> ScheduleScore:
    """构造具有唯一已知最优点的轻量评分表。"""

    penalty = (
        abs(template.heavy_headway_s - 3300) / 300
        + abs(template.empty_headway_s - 3000) / 300
        + abs(template.heavy_empty_phase_s - 2300) / 300
        + abs(template.flex_zone_hold_s - 180) / 180
        + abs(template.storage_align_shift_s - 300) / 300
    )
    return ScheduleScore(
        feasible=True,
        total_cost=1000.0 + penalty,
        headway_deviation=penalty,
        worst_case_cost=1000.0 + penalty,
        worst_case_headway_deviation=penalty,
        scenario_count=3,
        grid_kwh=100.0,
        wasted_kwh=20.0 + penalty,
        effective_regen_loss_kwh=20.0 + penalty,
    )


def main() -> int:
    assert _gap_statistics([]) == {"defined_gap_run_count": 0,
                                   "mean_primary_energy_gap_pct": None, "max_primary_energy_gap_pct": None}
    assert "未定义" in _gap_label(None)
    assert _gap_statistics([0.0])["mean_primary_energy_gap_pct"] == 0.0
    base = ScheduleTemplate(3300, 2700, 2600, 2, 2, storage_preset_id="fixed")
    domain = build_discrete_domain(
        base,
        heavy_headways_s=(3000, 3300),
        empty_headways_s=(2700, 3000),
        phases_s=(2300, 2600),
        holds_s=(0, 180),
        storage_shifts_s=(0, 300),
        storage_preset_id="fixed",
    )
    assert len(domain) == 32
    scores = {template_key(template): _score(template) for template in domain}
    config = TemplateSearchConfig(
        population_size=12,
        generations=3,
        elite_count=3,
        min_headway_s=2700,
        max_headway_s=3300,
        max_phase_s=2600,
        max_hold_s=180,
        max_storage_align_shift_s=300,
        storage_preset_ids=("fixed",),
        enable_storage_preset_search=False,
        allowed_heavy_headways_s=(3000, 3300),
        allowed_empty_headways_s=(2700, 3000),
        allowed_phases_s=(2300, 2600),
        allowed_holds_s=(0, 180),
        allowed_storage_align_shifts_s=(0, 300),
        seed=11,
    )
    snapped = clamp_template(
        ScheduleTemplate(3199, 2810, 2470, 2, 2, flex_zone_hold_s=100, storage_align_shift_s=170),
        config,
    )
    assert snapped.heavy_headway_s == 3300
    assert snapped.empty_headway_s == 2700
    assert snapped.heavy_empty_phase_s == 2600
    assert snapped.flex_zone_hold_s == 180
    assert snapped.storage_align_shift_s == 300

    result = compare_exact_and_heuristic(
        domain,
        scores,
        base_template=base,
        search_config=config,
        seed=11,
    )
    assert result["heuristic_found_feasible"]
    assert result["visited_candidate_count"] <= len(domain)
    assert 0.0 <= result["domain_coverage_rate"] <= 1.0
    assert result["primary_energy_optimality_gap_pct"] is not None
    assert result["primary_energy_optimality_gap_pct"] >= 0.0
    assert result["exact_primary_energy_objective"] == 120.0
    assert energy_scenario_objective(scores[tuple(result["exact_best_template_key"])]) == 120.0
    # 域内存在可行点，但一次启发式完全未命中时，不能输出假零差距。
    with patch("tools.small_scale_optimality_gap_benchmark.nsga2_template_search", return_value=[]):
        missed = compare_exact_and_heuristic(domain, scores, base_template=base,
                                             search_config=config, seed=11)
    assert not missed["heuristic_found_feasible"]
    assert missed["primary_energy_optimality_gap_pct"] is None
    report_summary = {
        "generated_at": "test", "heuristic_runs": [missed], "aggregate": _gap_statistics([]),
        "domain": {"candidate_count_per_scale": 32, "heavy_headways_s": [3000, 3300],
                   "empty_headways_s": [2700, 3000], "phases_s": [2300, 2600],
                   "holds_s": [0, 180], "storage_shifts_s": [0, 300], "storage_preset_id": "fixed"},
        "profile_summaries": [{"profile": "quick", "heuristic_feasible_rate": 0.0}],
        "scale_summaries": [{"scale": 2, "train_count": 4, "feasible_candidate_count": 32,
                              "domain_candidate_count": 32}],
        "profile_scale_summaries": [{"scale": 2, "train_count": 4, "profile": "quick",
                                      "heuristic_feasible_rate": 0.0, "exact_match_rate": 0.0,
                                      "mean_exact_pareto_coverage_rate": 0.0, **_gap_statistics([])}],
    }
    with TemporaryDirectory() as directory:
        _write_report(report_summary, Path(directory))
        report = (Path(directory) / "SMALL_SCALE_OPTIMALITY_GAP_REPORT.md").read_text(encoding="utf-8")
        assert "未定义" in report and "0.000000%" not in report
    print("small-scale optimality-gap smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
