"""在显式有限候选域内比较穷举全局最优解与离散域 NSGA-II。"""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import product
from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math
import platform
import statistics
import sys
import time

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rolling_optimizer import (
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    OBJECTIVE_MODE_BALANCED,
    OBJECTIVE_PRIORITY_ENERGY_FIRST,
    SEARCH_PROFILE_PRESETS,
    GeneratedSchedule,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    candidate_selection_key,
    default_scenarios,
    effective_objective_tuple,
    energy_scenario_objective,
    generate_schedule,
    nsga2_template_search,
    pareto_template_front,
    resolve_storage_eval_context,
    robust_evaluate_schedule,
    score_rank_value,
    template_key,
)
from run_dispatch_case import build_storage_eval_contexts, load_case_inputs
from storage_presets import default_storage_preset_library
from tools.benchmark_provenance import capture_provenance, verify_provenance


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "real_shuohuang"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E12_small_scale_optimality_gap"
DEFAULT_PRESET_ID = "virtual_two_section_base"


def _configure_matplotlib_fonts() -> None:
    """选择可用中文字体。"""

    available = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in ("Microsoft YaHei", "SimHei", "Arial Unicode MS"):
        if font_name in available:
            matplotlib.rcParams["font.sans-serif"] = [font_name]
            matplotlib.rcParams["font.family"] = "sans-serif"
            matplotlib.rcParams["axes.unicode_minus"] = False
            return


_configure_matplotlib_fonts()


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """写出 UTF-8 BOM CSV，便于直接使用表格软件复核。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_discrete_domain(
    base_template: ScheduleTemplate,
    *,
    heavy_headways_s: Sequence[int],
    empty_headways_s: Sequence[int],
    phases_s: Sequence[int],
    holds_s: Sequence[int],
    storage_shifts_s: Sequence[int],
    storage_preset_id: str,
) -> list[ScheduleTemplate]:
    """构造笛卡尔积候选域；该列表就是精确最优声明的完整边界。"""

    values = (
        tuple(sorted(set(heavy_headways_s))),
        tuple(sorted(set(empty_headways_s))),
        tuple(sorted(set(phases_s))),
        tuple(sorted(set(holds_s))),
        tuple(sorted(set(storage_shifts_s))),
    )
    if any(not value for value in values):
        raise ValueError("每个离散决策变量至少需要一个候选值。")
    return [
        replace(
            base_template,
            heavy_headway_s=heavy_headway,
            empty_headway_s=empty_headway,
            heavy_empty_phase_s=phase,
            flex_zone_hold_s=hold,
            storage_align_shift_s=storage_shift,
            storage_preset_id=storage_preset_id,
        )
        for heavy_headway, empty_headway, phase, hold, storage_shift in product(*values)
    ]


def _truncate_schedule(template: ScheduleTemplate, horizon_s: int) -> GeneratedSchedule:
    """按生产优化器相同的预测时域截断规则展开运行图。"""

    schedule = generate_schedule(template)
    return GeneratedSchedule(
        heavy_departures_s=[value for value in schedule.heavy_departures_s if value <= horizon_s],
        empty_departures_s=[value for value in schedule.empty_departures_s if value <= horizon_s],
        template=schedule.template,
    )


def _with_service_population_constraint(
    score: ScheduleScore,
    schedule: GeneratedSchedule,
    heavy_count: int,
    empty_count: int,
) -> ScheduleScore:
    """禁止通过把列车推出预测时域获得虚假能源优势。"""

    violation = abs(len(schedule.heavy_departures_s) - heavy_count) + abs(
        len(schedule.empty_departures_s) - empty_count
    )
    if violation == 0:
        return score
    return replace(
        score,
        feasible=False,
        constraint_violation=score.constraint_violation + float(violation),
    )


def _relative_gap_pct(candidate: float, optimum: float) -> Optional[float]:
    """返回最小化目标的非负相对差距；零最优值仅在同为零时定义为0。"""

    if math.isclose(candidate, optimum, rel_tol=1e-12, abs_tol=1e-9):
        return 0.0
    if abs(optimum) <= 1e-12:
        return 0.0 if abs(candidate) <= 1e-12 else None
    return max(0.0, (candidate - optimum) / abs(optimum) * 100.0)


def _gap_statistics(gaps: Sequence[float]) -> dict[str, Any]:
    """全体搜索失败时，差距未定义，不能崩溃或伪记为零。"""
    return {"defined_gap_run_count": len(gaps),
            "mean_primary_energy_gap_pct": statistics.fmean(gaps) if gaps else None,
            "max_primary_energy_gap_pct": max(gaps) if gaps else None}


def _gap_label(value: Optional[float]) -> str:
    return "未定义（未取得可比较差距）" if value is None else f"{value:.6f}%"


def compare_exact_and_heuristic(
    domain: Sequence[ScheduleTemplate],
    scores: dict[tuple[Any, ...], ScheduleScore],
    *,
    base_template: ScheduleTemplate,
    search_config: TemplateSearchConfig,
    seed: int,
    evaluation_times: Optional[dict[tuple[Any, ...], float]] = None,
) -> dict[str, Any]:
    """在同一离散域和同一评分表上执行一次 NSGA-II 并计算最优性差距。"""

    feasible_domain = [
        (template, scores[template_key(template)])
        for template in domain
        if scores[template_key(template)].feasible
    ]
    if not feasible_domain:
        raise ValueError("离散候选域没有核心稳健可行方案，无法计算最优性差距。")
    exact_best_template, exact_best_score = min(
        feasible_domain, key=lambda item: candidate_selection_key(item[1])
    )
    visited: set[tuple[Any, ...]] = set()

    def lookup(template: ScheduleTemplate) -> ScheduleScore:
        key = template_key(template)
        if key not in scores:
            raise AssertionError(f"启发式生成了离散候选域之外的模板: {key!r}")
        visited.add(key)
        return scores[key]

    configured = replace(search_config, seed=seed)
    started = time.perf_counter()
    ranked = nsga2_template_search(base_template, configured, lookup)
    search_time_s = time.perf_counter() - started
    feasible_ranked = [(template, score) for template, score in ranked if score.feasible]
    heuristic_best = (
        min(feasible_ranked, key=lambda item: candidate_selection_key(item[1]))
        if feasible_ranked
        else None
    )
    exact_front = pareto_template_front(feasible_domain)
    visited_feasible = [
        (template, scores[template_key(template)])
        for template in domain
        if template_key(template) in visited and scores[template_key(template)].feasible
    ]
    heuristic_front = pareto_template_front(visited_feasible)
    exact_front_objectives = {effective_objective_tuple(score) for _template, score in exact_front}
    heuristic_front_objectives = {
        effective_objective_tuple(score) for _template, score in heuristic_front
    }
    coverage = (
        len(exact_front_objectives & heuristic_front_objectives) / len(exact_front_objectives)
        if exact_front_objectives
        else 1.0
    )
    result: dict[str, Any] = {
        "seed": seed,
        "heuristic_found_feasible": heuristic_best is not None,
        "visited_candidate_count": len(visited),
        "domain_coverage_rate": len(visited) / len(domain),
        "heuristic_search_overhead_s": search_time_s,
        "visited_full_evaluation_time_s": sum((evaluation_times or {}).get(key, 0.0) for key in visited)
        if evaluation_times is not None else None,
        "exact_pareto_objective_count": len(exact_front_objectives),
        "heuristic_pareto_objective_count": len(heuristic_front_objectives),
        "exact_pareto_coverage_rate": coverage,
        "exact_best_template_key": list(template_key(exact_best_template)),
        "exact_primary_energy_objective": energy_scenario_objective(exact_best_score),
        "exact_grid_kwh": exact_best_score.grid_kwh,
        "exact_wasted_kwh": exact_best_score.wasted_kwh,
        "exact_total_cost": exact_best_score.total_cost,
    }
    if heuristic_best is None:
        result.update(
            {
                "heuristic_best_template_key": None,
                "heuristic_primary_energy_objective": None,
                "primary_energy_optimality_gap_pct": None,
                "heuristic_exact_lexicographic_match": False,
            }
        )
        return result

    heuristic_template, heuristic_score = heuristic_best
    result.update(
        {
            "heuristic_best_template_key": list(template_key(heuristic_template)),
            "heuristic_primary_energy_objective": energy_scenario_objective(heuristic_score),
            "heuristic_grid_kwh": heuristic_score.grid_kwh,
            "heuristic_wasted_kwh": heuristic_score.wasted_kwh,
            "heuristic_total_cost": heuristic_score.total_cost,
            "primary_energy_optimality_gap_pct": _relative_gap_pct(
                energy_scenario_objective(heuristic_score),
                energy_scenario_objective(exact_best_score),
            ),
            "grid_gap_pct": _relative_gap_pct(heuristic_score.grid_kwh, exact_best_score.grid_kwh),
            "wasted_gap_pct": _relative_gap_pct(
                heuristic_score.wasted_kwh, exact_best_score.wasted_kwh
            ),
            "cost_gap_pct": _relative_gap_pct(
                heuristic_score.total_cost, exact_best_score.total_cost
            ),
            "heuristic_exact_lexicographic_match": (
                candidate_selection_key(heuristic_score)
                == candidate_selection_key(exact_best_score)
            ),
        }
    )
    return result


def _candidate_row(scale: int, template: ScheduleTemplate, score: ScheduleScore) -> dict[str, Any]:
    """将一个穷举候选转换为可审计明细。"""

    objectives = effective_objective_tuple(score)
    selection_key = candidate_selection_key(score)
    return {
        "scale": scale,
        "train_count": scale * 2,
        "heavy_headway_s": template.heavy_headway_s,
        "empty_headway_s": template.empty_headway_s,
        "phase_s": template.heavy_empty_phase_s,
        "hold_s": template.flex_zone_hold_s,
        "storage_align_shift_s": template.storage_align_shift_s,
        "storage_preset_id": template.storage_preset_id,
        "feasible": score.feasible,
        "constraint_violation": score.constraint_violation,
        "effective_regen_loss_kwh": score.effective_regen_loss_kwh,
        "primary_energy_objective": energy_scenario_objective(score),
        "grid_kwh": score.grid_kwh,
        "wasted_kwh": score.wasted_kwh,
        "total_cost": score.total_cost,
        "headway_deviation": score.headway_deviation,
        "objective_1_quantized": objectives[0],
        "objective_2_quantized": objectives[1],
        "objective_3_quantized": objectives[2],
        "score_rank_value": score_rank_value(score),
        **{
            f"selection_key_{index}": value
            for index, value in enumerate(selection_key)
        },
    }


def _write_chart(rows: Sequence[dict[str, Any]], output_dir: Path) -> str:
    """同时展示可行命中率和成功运行的条件最优性差距。"""

    fig, (left, right) = plt.subplots(1, 2, figsize=(11.2, 4.5))
    train_counts = sorted({int(row["train_count"]) for row in rows})
    profiles = [
        name
        for name in ("quick", "standard", "large")
        if any(row.get("profile") == name for row in rows)
    ]
    colors = {"quick": "#176B87", "standard": "#E07A1F", "large": "#2E8B57"}
    width = 0.22
    center = (len(profiles) - 1) / 2
    for index, profile in enumerate(profiles):
        rates = []
        gaps = []
        for train_count in train_counts:
            selected = [
                row
                for row in rows
                if int(row["train_count"]) == train_count and row.get("profile") == profile
            ]
            rates.append(
                statistics.fmean(float(row["heuristic_found_feasible"]) for row in selected)
            )
            valid_gaps = [
                float(row["primary_energy_optimality_gap_pct"])
                for row in selected
                if row.get("primary_energy_optimality_gap_pct") is not None
            ]
            gaps.append(statistics.fmean(valid_gaps) if valid_gaps else math.nan)
        positions = [value + (index - center) * width for value in train_counts]
        left.bar(
            positions,
            rates,
            width=width,
            color=colors[profile],
            label=profile,
        )
        right.plot(
            train_counts,
            gaps,
            marker="o",
            color=colors[profile],
            label=profile,
        )
    left.set_xlabel("列车总数")
    left.set_ylabel("可行解命中率")
    left.set_title("启发式可行解命中率")
    left.set_xticks(train_counts)
    left.set_ylim(0.0, 1.08)
    left.grid(axis="y", alpha=0.25)
    left.legend()
    right.axhline(0.0, color="#333333", linewidth=1, linestyle="--")
    right.set_xlabel("列车总数")
    right.set_ylabel("条件最优性差距（%）")
    right.set_title("找到可行解后的主能源目标差距")
    right.set_xticks(train_counts)
    right.grid(alpha=0.25)
    right.legend()
    fig.suptitle("小规模精确解与启发式解对比")
    fig.tight_layout()
    path = output_dir / "optimality_gap_by_scale.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return str(path)


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    """生成可直接纳入论文实验记录的中文说明。"""

    lines = [
        "# E12 小规模最优解与启发式最优差距测试",
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "## 结论",
        "",
        f"- 已完整穷举每个规模的 `{summary['domain']['candidate_count_per_scale']}` 个候选，精确性范围严格限定为下述离散域。",
        f"- 共执行 `{len(summary['heuristic_runs'])}` 次 NSGA-II。结果同时报告可行解命中率，未找到可行解的运行不把差距伪记为0。",
        f"- 在找到可行解且差距有定义的运行中，主能源目标条件最优性差距最大值为 `{_gap_label(summary['aggregate']['max_primary_energy_gap_pct'])}`，均值为 `{_gap_label(summary['aggregate']['mean_primary_energy_gap_pct'])}`。",
        "- 三档预算的总体可行命中率分别为："
        + "；".join(
            f"`{row['profile']}` {row['heuristic_feasible_rate']:.1%}"
            for row in summary["profile_summaries"]
        )
        + "。",
        "- 搜索预算增加不保证每个固定随机种子的候选集合嵌套；本实验应优先解释可行命中率和多种子统计，不能把单个种子的非单调结果当成目标函数退化。",
        "- 当前参数仍含规划/占位值；本测试证明算法在声明候选域内的相对求解质量，不代表现场节能率。",
        "- 本对照只测纯 NSGA-II，不包含生产流程的局部修复和精确兜底；查表搜索耗时不是实际优化耗时。访问候选的完整评价耗时为本轮实测候选耗时之和，不包含并行加速、初始化或输出。",
        "",
        "## 精确性边界",
        "",
        "精确基线采用有限域完全穷举。所有候选使用与生产调度相同的五场景评价、核心场景可行性、资源、信号、电气、能量结算、SOC和服务数量规则。主比较按生产 `energy_first` 词典序选择键进行；`optimality gap` 单独针对其中首要的 `grid_kwh + effective_regen_loss_kwh` 指标计算。",
        "",
        "| 决策变量 | 候选值 |",
        "| --- | --- |",
        f"| 重车追踪间隔 | `{summary['domain']['heavy_headways_s']}` |",
        f"| 空车追踪间隔 | `{summary['domain']['empty_headways_s']}` |",
        f"| 重空相位 | `{summary['domain']['phases_s']}` |",
        f"| 储能区停车 | `{summary['domain']['holds_s']}` |",
        f"| 储能对齐偏移 | `{summary['domain']['storage_shifts_s']}` |",
        f"| 储能预设 | `{summary['domain']['storage_preset_id']}`（固定，隔离运行图搜索质量） |",
        "",
        "因此“全局最优”只指上述笛卡尔积离散域，不外推到连续时间、逐列车任意调整或其他储能设备参数。",
        "",
        "## 分规模结果",
        "",
        "| 列车数 | 搜索档位 | 可行候选/总候选 | 可行命中率 | 条件差距均值 | 条件差距最大值 | 精确命中率 | Pareto覆盖均值 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    exact_by_scale = {row["scale"]: row for row in summary["scale_summaries"]}
    for row in summary["profile_scale_summaries"]:
        exact_row = exact_by_scale[row["scale"]]
        lines.append(
            f"| {row['train_count']} | {row['profile']} | "
            f"{exact_row['feasible_candidate_count']}/{exact_row['domain_candidate_count']} | "
            f"{row['heuristic_feasible_rate']:.1%} | {_gap_label(row['mean_primary_energy_gap_pct'])} | "
            f"{_gap_label(row['max_primary_energy_gap_pct'])} | {row['exact_match_rate']:.1%} | "
            f"{row['mean_exact_pareto_coverage_rate']:.1%} |"
        )
    lines.extend(["", "## 可行域的能源目标区分度", "",
                  "目标差距为零不一定代表搜索充分；若目标在可行域中近乎相同，应优先看可行命中率、词典序命中和覆盖率。"])
    for row in summary["scale_summaries"]:
        lines.append(f"- {row['train_count']} 列车：可行目标极差 {row.get('feasible_energy_objective_spread_kwh', 0):.9f} 千瓦时，按0.01千瓦时区分的目标数 {row.get('distinct_feasible_energy_objectives', '未记录')}。")
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            "- `benchmark_summary.json`：完整实验配置、精确性声明、分规模和汇总结果；",
            "- `exact_candidates.csv`：每个规模全部穷举候选及评价指标；",
            "- `heuristic_runs.csv`：每个随机种子的最好解、差距、候选覆盖和Pareto覆盖；",
            "- `optimality_gap_by_scale.png`：各规模、各随机种子的主目标差距图。",
        ]
    )
    (output_dir / "SMALL_SCALE_OPTIMALITY_GAP_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run_benchmark(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    scales: Sequence[int] = (1, 2, 3),
    seeds: Sequence[int] = (11, 23, 37, 53, 71),
    heavy_headways_s: Sequence[int] = (3000, 3300),
    empty_headways_s: Sequence[int] = (2700, 3300),
    phases_s: Sequence[int] = (2300, 2600, 2760),
    holds_s: Sequence[int] = (0, 180),
    storage_shifts_s: Sequence[int] = (0, 300),
    storage_preset_id: str = DEFAULT_PRESET_ID,
    profiles: Sequence[str] = ("quick", "standard", "large"),
    horizon_s: int = 14400,
    settlement_step_s: int = 10,
) -> dict[str, Any]:
    """执行小规模有限域穷举与多种子 NSGA-II 对比。"""

    if not scales or any(scale <= 0 for scale in scales):
        raise ValueError("scales必须包含正整数。")
    if not seeds:
        raise ValueError("至少需要一个随机种子。")
    normalized_profiles = tuple(dict.fromkeys(str(value).strip().lower() for value in profiles))
    unknown_profiles = [value for value in normalized_profiles if value not in SEARCH_PROFILE_PRESETS]
    if not normalized_profiles or unknown_profiles:
        raise ValueError(f"搜索档位必须来自{sorted(SEARCH_PROFILE_PRESETS)}，未知值={unknown_profiles}")
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = capture_provenance(data_dir)
    case_inputs = load_case_inputs(data_dir, output_dir / "input_check")
    library = default_storage_preset_library(case_inputs.battery)
    library_by_id = {preset.scenario_id: preset for preset in library}
    if storage_preset_id not in library_by_id:
        raise ValueError(f"未知储能预设: {storage_preset_id!r}")
    contexts = build_storage_eval_contexts(
        case_inputs=case_inputs,
        trains=case_inputs.trains,
        base_battery=case_inputs.battery,
        preset_ids=[storage_preset_id],
        library_by_id=library_by_id,
        settlement_step_s=settlement_step_s,
        initial_soc_kwh=0.0,
        target_final_soc_kwh=0.0,
        final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.05,
        wasted_energy_penalty_per_kwh=0.05,
        energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    )
    context = resolve_storage_eval_context(contexts, storage_preset_id, storage_preset_id)
    scenarios = default_scenarios()
    all_candidate_rows: list[dict[str, Any]] = []
    heuristic_rows: list[dict[str, Any]] = []
    scale_summaries: list[dict[str, Any]] = []
    progress_path = output_dir / "benchmark_progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "completed_scales": [],
                "requested_scales": list(scales),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for scale in scales:
        base_template = ScheduleTemplate(
            heavy_headway_s=3300,
            empty_headway_s=2700,
            heavy_empty_phase_s=2600,
            heavy_count=int(scale),
            empty_count=int(scale),
            storage_preset_id=storage_preset_id,
        )
        domain = build_discrete_domain(
            base_template,
            heavy_headways_s=heavy_headways_s,
            empty_headways_s=empty_headways_s,
            phases_s=phases_s,
            holds_s=holds_s,
            storage_shifts_s=storage_shifts_s,
            storage_preset_id=storage_preset_id,
        )
        target_gap_s = int(round((base_template.heavy_headway_s + base_template.empty_headway_s) / 2))
        scores: dict[tuple[Any, ...], ScheduleScore] = {}
        evaluation_times: dict[tuple[Any, ...], float] = {}
        started = time.perf_counter()
        for template in domain:
            evaluation_started = time.perf_counter()
            schedule = _truncate_schedule(template, horizon_s)
            score = robust_evaluate_schedule(
                schedule,
                scenarios,
                context.heavy_cache,
                context.empty_cache,
                context.settlement_system,
                context.route.signaling_system,
                resource_model=case_inputs.resource_model,
                storage_sections=context.storage_sections,
                min_depart_gap_s=case_inputs.resource_model.config.min_depart_headway_s,
                target_gap_s=target_gap_s,
                objective_mode=OBJECTIVE_MODE_BALANCED,
                energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
                objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST,
            )
            score = _with_service_population_constraint(score, schedule, scale, scale)
            scores[template_key(template)] = score
            evaluation_times[template_key(template)] = time.perf_counter() - evaluation_started
            all_candidate_rows.append(_candidate_row(scale, template, score))
        exhaustive_time_s = time.perf_counter() - started
        feasible_items = [
            (template, scores[template_key(template)])
            for template in domain
            if scores[template_key(template)].feasible
        ]
        if not feasible_items:
            raise RuntimeError(f"规模{scale * 2}列车的离散域没有核心稳健可行候选。")
        exact_template, exact_score = min(
            feasible_items, key=lambda item: candidate_selection_key(item[1])
        )
        current_rows = []
        for profile_name in normalized_profiles:
            profile = SEARCH_PROFILE_PRESETS[profile_name]
            config = TemplateSearchConfig(
                method="nsga2",
                population_size=int(profile["population_size"]),
                generations=int(profile["generations"]),
                elite_count=int(profile["elite_count"]),
                mutation_probability=0.45,
                headway_mutation_s=300,
                phase_mutation_s=300,
                hold_mutation_s=180,
                storage_shift_mutation_s=300,
                min_headway_s=min(min(heavy_headways_s), min(empty_headways_s)),
                max_headway_s=max(max(heavy_headways_s), max(empty_headways_s)),
                max_phase_s=max(phases_s),
                max_hold_s=max(holds_s),
                max_storage_align_shift_s=max(abs(value) for value in storage_shifts_s),
                parallel_workers=1,
                seed=int(seeds[0]),
                enable_storage_preset_search=False,
                storage_preset_ids=(storage_preset_id,),
                allowed_heavy_headways_s=tuple(heavy_headways_s),
                allowed_empty_headways_s=tuple(empty_headways_s),
                allowed_phases_s=tuple(phases_s),
                allowed_holds_s=tuple(holds_s),
                allowed_storage_align_shifts_s=tuple(storage_shifts_s),
            )
            for seed in seeds:
                row = compare_exact_and_heuristic(
                    domain,
                    scores,
                    base_template=base_template,
                    search_config=config,
                    seed=int(seed),
                    evaluation_times=evaluation_times,
                )
                row.update(
                    {
                        "scale": scale,
                        "train_count": scale * 2,
                        "profile": profile_name,
                        "population_size": config.population_size,
                        "generations": config.generations,
                    }
                )
                current_rows.append(row)
                heuristic_rows.append(row)
        scale_summaries.append(
            {
                "scale": scale,
                "train_count": scale * 2,
                "domain_candidate_count": len(domain),
                "feasible_candidate_count": len(feasible_items),
                "exhaustive_evaluation_time_s": exhaustive_time_s,
                "exact_best_template": asdict(exact_template),
                "exact_primary_energy_objective": energy_scenario_objective(exact_score),
                "exact_grid_kwh": exact_score.grid_kwh,
                "exact_wasted_kwh": exact_score.wasted_kwh,
                "exact_total_cost": exact_score.total_cost,
                "feasible_energy_objective_spread_kwh": max(energy_scenario_objective(score)
                    for _template, score in feasible_items) - min(energy_scenario_objective(score)
                    for _template, score in feasible_items),
                "distinct_feasible_energy_objectives": len({round(energy_scenario_objective(score), 2)
                    for _template, score in feasible_items}),
            }
        )
        # 每个规模完成后立即保存证据，长测中断时不丢失已完成结果。
        _write_csv(output_dir / "exact_candidates.csv", all_candidate_rows)
        _write_csv(output_dir / "heuristic_runs.csv", heuristic_rows)
        progress_path.write_text(
            json.dumps(
                {
                    "status": "running",
                    "completed_scales": [row["scale"] for row in scale_summaries],
                    "requested_scales": list(scales),
                    "scale_summaries": scale_summaries,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    all_gaps = [
        float(row["primary_energy_optimality_gap_pct"])
        for row in heuristic_rows
        if row.get("primary_energy_optimality_gap_pct") is not None
    ]
    profile_scale_summaries = []
    for scale in scales:
        for profile_name in normalized_profiles:
            grouped = [
                row
                for row in heuristic_rows
                if row["scale"] == scale and row["profile"] == profile_name
            ]
            gaps = [
                float(row["primary_energy_optimality_gap_pct"])
                for row in grouped
                if row.get("primary_energy_optimality_gap_pct") is not None
            ]
            profile_scale_summaries.append(
                {
                    "scale": scale,
                    "train_count": scale * 2,
                    "profile": profile_name,
                    "population_size": grouped[0]["population_size"],
                    "generations": grouped[0]["generations"],
                    "heuristic_feasible_rate": statistics.fmean(
                        float(row["heuristic_found_feasible"]) for row in grouped
                    ),
                    "exact_match_rate": statistics.fmean(
                        float(row["heuristic_exact_lexicographic_match"]) for row in grouped
                    ),
                    **_gap_statistics(gaps),
                    "mean_exact_pareto_coverage_rate": statistics.fmean(
                        float(row["exact_pareto_coverage_rate"]) for row in grouped
                    ),
                }
            )
    profile_summaries = []
    for profile_name in normalized_profiles:
        grouped = [row for row in heuristic_rows if row["profile"] == profile_name]
        gaps = [
            float(row["primary_energy_optimality_gap_pct"])
            for row in grouped
            if row.get("primary_energy_optimality_gap_pct") is not None
        ]
        profile_summaries.append(
            {
                "profile": profile_name,
                "population_size": grouped[0]["population_size"],
                "generations": grouped[0]["generations"],
                "run_count": len(grouped),
                "feasible_run_count": sum(
                    bool(row["heuristic_found_feasible"]) for row in grouped
                ),
                "heuristic_feasible_rate": statistics.fmean(
                    float(row["heuristic_found_feasible"]) for row in grouped
                ),
                "exact_match_rate": statistics.fmean(
                    float(row["heuristic_exact_lexicographic_match"]) for row in grouped
                ),
                **_gap_statistics(gaps),
            }
        )
    summary = {
        "benchmark_completed": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "data_boundary": (
            "当前规划/工程占位参数，仅用于算法验证；正式数据到位后必须按同一冻结域重跑。"
        ),
        "optimality_claim": (
            "穷举结果仅对记录的有限笛卡尔积候选域全局最优；不代表连续时间、逐列车任意调整或其他储能预设下全局最优。"
        ),
        "comparison_contract": {
            "feasibility": "与生产调度相同的五场景评价，前三个核心场景必须全部可行",
            "selection": "energy_first生产词典序候选选择键",
            "reported_gap_objective": "grid_kwh + effective_regen_loss_kwh",
            "storage_scope": "固定储能预设，隔离运行图启发式搜索质量",
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "provenance": verify_provenance(provenance, data_dir),
        "settings": {
            "scales": list(scales),
            "seeds": list(seeds),
            "profiles": list(normalized_profiles),
            "profile_budgets": {
                name: {
                    "population_size": SEARCH_PROFILE_PRESETS[name]["population_size"],
                    "generations": SEARCH_PROFILE_PRESETS[name]["generations"],
                    "elite_count": SEARCH_PROFILE_PRESETS[name]["elite_count"],
                }
                for name in normalized_profiles
            },
            "horizon_s": horizon_s,
            "settlement_step_s": settlement_step_s,
        },
        "domain": {
            "heavy_headways_s": list(heavy_headways_s),
            "empty_headways_s": list(empty_headways_s),
            "phases_s": list(phases_s),
            "holds_s": list(holds_s),
            "storage_shifts_s": list(storage_shifts_s),
            "storage_preset_id": storage_preset_id,
            "candidate_count_per_scale": math.prod(
                len(set(values))
                for values in (
                    heavy_headways_s,
                    empty_headways_s,
                    phases_s,
                    holds_s,
                    storage_shifts_s,
                )
            ),
        },
        "scale_summaries": scale_summaries,
        "profile_scale_summaries": profile_scale_summaries,
        "profile_summaries": profile_summaries,
        "heuristic_runs": heuristic_rows,
        "aggregate": {
            "heuristic_run_count": len(heuristic_rows),
            "heuristic_feasible_run_count": sum(
                bool(row["heuristic_found_feasible"]) for row in heuristic_rows
            ),
            "heuristic_infeasible_run_count": sum(
                not bool(row["heuristic_found_feasible"]) for row in heuristic_rows
            ),
            "heuristic_feasible_rate": statistics.fmean(
                float(row["heuristic_found_feasible"]) for row in heuristic_rows
            ),
            "exact_match_rate": statistics.fmean(
                float(row["heuristic_exact_lexicographic_match"]) for row in heuristic_rows
            ),
            **_gap_statistics(all_gaps),
        },
    }
    _write_csv(output_dir / "exact_candidates.csv", all_candidate_rows)
    _write_csv(output_dir / "heuristic_runs.csv", heuristic_rows)
    summary["outputs"] = {
        "summary": str(output_dir / "benchmark_summary.json"),
        "exact_candidates": str(output_dir / "exact_candidates.csv"),
        "heuristic_runs": str(output_dir / "heuristic_runs.csv"),
        "chart": _write_chart(heuristic_rows, output_dir),
        "report": str(output_dir / "SMALL_SCALE_OPTIMALITY_GAP_REPORT.md"),
    }
    (output_dir / "benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    progress_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "completed_scales": [row["scale"] for row in scale_summaries],
                "requested_scales": list(scales),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_report(summary, output_dir)
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立复现实验命令。"""

    parser = argparse.ArgumentParser(description="小规模精确最优与启发式最优差距测试")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71])
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=sorted(SEARCH_PROFILE_PRESETS),
        default=["quick", "standard", "large"],
    )
    parser.add_argument("--horizon-s", type=int, default=14400)
    parser.add_argument("--settlement-step-s", type=int, default=10)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行基准并输出关键结论。"""

    args = build_parser().parse_args(argv)
    summary = run_benchmark(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        scales=args.scales,
        seeds=args.seeds,
        profiles=args.profiles,
        horizon_s=args.horizon_s,
        settlement_step_s=args.settlement_step_s,
    )
    print(json.dumps({"benchmark_completed": summary["benchmark_completed"], **summary["aggregate"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
