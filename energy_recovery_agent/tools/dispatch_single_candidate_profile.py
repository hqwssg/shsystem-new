# 模块功能说明：隔离并剖析一个重空调度候选的完整稳健评价，不把数据加载和缓存构建计入候选耗时。

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, Sequence
import argparse
import cProfile
import json
import pstats
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    ScheduleTemplate,
    default_scenarios,
    generate_schedule,
    robust_evaluate_schedule,
)
from run_dispatch_case import (
    apply_battery_scenario,
    apply_train_mass_scenario,
    build_parser as build_dispatch_parser,
    build_storage_eval_contexts,
    effective_min_depart_gap_s,
    load_case_inputs,
    recommended_energy_observability,
    resolve_storage_preset_search,
)
from tools.benchmark_provenance import capture_provenance, verify_provenance


DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "dispatch_single_candidate_profile"


def _semantic_payload(score: Any, scenario_scores: Sequence[Any]) -> dict[str, Any]:
    """提取不含耗时和路径的评价结果，用于验证重复运行的业务语义一致性。"""

    return {
        "robust_score": asdict(score),
        "scenario_scores": [
            {"scenario": scenario.name, "score": asdict(scenario_score)}
            for scenario, scenario_score in scenario_scores
        ],
    }


def _semantic_sha256(score: Any, scenario_scores: Sequence[Any]) -> str:
    """计算单候选稳健评价的确定性语义摘要。"""

    encoded = json.dumps(
        _semantic_payload(score, scenario_scores),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _profile_rows(profile_path: Path, top: int) -> list[dict[str, Any]]:
    """读取累计耗时最高的函数，同时保留函数自身耗时。"""

    stats = pstats.Stats(str(profile_path)).strip_dirs()
    rows: list[dict[str, Any]] = []
    ordered = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)
    for (filename, line, function), values in ordered[:top]:
        primitive_calls, total_calls, own_s, cumulative_s, _callers = values
        rows.append(
            {
                "function": f"{Path(filename).as_posix()}:{line}::{function}",
                "calls": total_calls,
                "primitive_calls": primitive_calls,
                "own_s": round(own_s, 6),
                "cumulative_s": round(cumulative_s, 6),
            }
        )
    return rows


def _write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    """生成便于评审的中文单候选剖析报告。"""

    settings = summary["candidate"]
    benchmark = summary["benchmark"]
    lines = [
        "# 重空协同调度单候选性能剖析",
        "",
        "## 测试边界",
        "",
        "本报告只剖析一个固定候选的完整稳健评价。数据加载、列车基础轨迹计算、储能上下文构建和结果写盘均不计入候选耗时。",
        "",
        f"- 列车：{settings['heavy_count']} 重 + {settings['empty_count']} 空，共 {settings['heavy_count'] + settings['empty_count']} 列；",
        f"- 重/空间隔：`{settings['heavy_headway_s']}/{settings['empty_headway_s']} s`；有效空车相位：`{settings['phase_s']} s`；",
        f"- 储能预设：`{settings['storage_preset_id']}`；结算步长：`{settings['settlement_step_s']} s`；",
        f"- 扰动场景：`{benchmark['scenario_count']}` 个；重复计时：`{benchmark['repeat_count']}` 次。",
        "",
        "## 结果",
        "",
        f"- 非剖析计时中位数：`{benchmark['median_wall_time_s']:.6f} s/候选`；",
        f"- 最小/最大耗时：`{benchmark['min_wall_time_s']:.6f}/{benchmark['max_wall_time_s']:.6f} s`；",
        f"- cProfile 单次耗时：`{benchmark['profiled_wall_time_s']:.6f} s`；",
        f"- 稳健可行：`{str(benchmark['core_robust_feasible']).lower()}`；约束违反量：`{benchmark['constraint_violation']}`；",
        f"- 重复运行语义摘要唯一：`{str(benchmark['semantic_stable']).lower()}`；SHA-256：`{benchmark['semantic_sha256']}`。",
        "",
        "## 累计耗时最高函数",
        "",
        "| 函数 | 调用次数 | 自身耗时/s | 累计耗时/s |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in summary["top_functions"]:
        lines.append(
            f"| `{row['function']}` | {row['calls']} | {row['own_s']:.6f} | {row['cumulative_s']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 解读原则",
            "",
            "累计耗时包含被调用函数，多个条目不能直接相加。只有热点属于重复计算或可建立等价索引，且优化前后语义 SHA-256 完全一致时，才实施算法代码优化。",
            "当前数据包含规划和工程占位参数，本报告用于软件性能判断，不代表正式线路运行耗时承诺。",
        ]
    )
    (output_dir / "DISPATCH_SINGLE_CANDIDATE_PROFILE.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_profile(
    *,
    data_dir: Path,
    output_dir: Path,
    heavy_count: int = 4,
    empty_count: int = 4,
    heavy_headway_s: int = 3300,
    empty_headway_s: int = 3300,
    phase_s: int = 840,
    storage_preset_id: str = "virtual_two_section_base",
    settlement_step_s: int = 10,
    repeat_count: int = 3,
    top: int = 40,
) -> dict[str, Any]:
    """构建固定上下文，剖析并重复计时一个完整稳健候选。"""

    if heavy_count <= 0 or empty_count <= 0 or repeat_count <= 0 or top <= 0:
        raise ValueError("列车数量、重复次数和热点函数数量必须为正整数。")
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = capture_provenance(data_dir)

    dispatch_args = build_dispatch_parser().parse_args([])
    dispatch_args.input = str(data_dir)
    dispatch_args.output_dir = str(output_dir / "setup")
    dispatch_args.settlement_step_s = settlement_step_s
    dispatch_args.storage_preset_ids = storage_preset_id
    dispatch_args.enable_storage_preset_search = True
    dispatch_args.disable_storage_preset_search = False

    setup_started = time.perf_counter()
    case_inputs = load_case_inputs(data_dir, output_dir / "setup")
    trains = apply_train_mass_scenario(case_inputs.trains, None)
    battery = apply_battery_scenario(
        case_inputs.battery,
        capacity_kwh=None,
        max_charge_power_kW=None,
        max_discharge_power_kW=None,
        round_trip_efficiency=None,
    )
    observability = recommended_energy_observability(dispatch_args)
    storage_search = resolve_storage_preset_search(dispatch_args, battery)
    if storage_preset_id not in storage_search["library_by_id"]:
        raise ValueError(f"未知储能预设：{storage_preset_id}")
    contexts = build_storage_eval_contexts(
        case_inputs=case_inputs,
        trains=trains,
        base_battery=battery,
        preset_ids=[storage_preset_id],
        library_by_id=storage_search["library_by_id"],
        settlement_step_s=settlement_step_s,
        initial_soc_kwh=dispatch_args.initial_soc_kwh,
        target_final_soc_kwh=dispatch_args.target_final_soc_kwh,
        final_soc_tolerance_kwh=dispatch_args.final_soc_tolerance_kwh,
        final_soc_penalty_per_kwh=dispatch_args.final_soc_penalty_per_kwh,
        wasted_energy_penalty_per_kwh=float(observability["applied_wasted_energy_penalty_per_kwh"]),
        energy_scenario=dispatch_args.energy_scenario,
    )
    context = contexts[storage_preset_id]
    min_depart_gap_s = effective_min_depart_gap_s(
        dispatch_args.min_depart_gap_s, case_inputs.resource_model
    )
    template = ScheduleTemplate(
        heavy_headway_s=heavy_headway_s,
        empty_headway_s=empty_headway_s,
        heavy_empty_phase_s=phase_s,
        heavy_count=heavy_count,
        empty_count=empty_count,
        storage_preset_id=storage_preset_id,
    )
    schedule = generate_schedule(template)
    scenarios = list(default_scenarios())
    setup_wall_time_s = time.perf_counter() - setup_started

    def evaluate_once() -> tuple[Any, list[Any]]:
        scenario_scores: list[Any] = []
        score = robust_evaluate_schedule(
            schedule,
            scenarios,
            context.heavy_cache,
            context.empty_cache,
            context.settlement_system,
            context.route.signaling_system,
            resource_model=case_inputs.resource_model,
            storage_sections=context.storage_sections,
            min_depart_gap_s=min_depart_gap_s,
            target_gap_s=int(round((heavy_headway_s + empty_headway_s) / 2.0)),
            objective_mode=dispatch_args.objective_mode,
            energy_scenario=dispatch_args.energy_scenario,
            objective_priority=dispatch_args.objective_priority,
            scenario_score_sink=scenario_scores,
        )
        return score, scenario_scores

    # 预热用于排除首次导入和惰性初始化，不进入正式计时。
    warm_score, warm_scenarios = evaluate_once()
    hashes = [_semantic_sha256(warm_score, warm_scenarios)]

    profile_path = output_dir / "single_candidate.prof"
    profiler = cProfile.Profile()
    profiled_started = time.perf_counter()
    profiler.enable()
    profiled_score, profiled_scenarios = evaluate_once()
    profiler.disable()
    profiled_wall_time_s = time.perf_counter() - profiled_started
    profiler.dump_stats(str(profile_path))
    hashes.append(_semantic_sha256(profiled_score, profiled_scenarios))

    timings: list[float] = []
    last_score = profiled_score
    last_scenarios = profiled_scenarios
    for _ in range(repeat_count):
        started = time.perf_counter()
        last_score, last_scenarios = evaluate_once()
        timings.append(time.perf_counter() - started)
        hashes.append(_semantic_sha256(last_score, last_scenarios))

    summary = {
        "schema_version": "1.0",
        "data_status": "planning_and_placeholder_inputs",
        "scope": "single_candidate_full_robust_evaluation_only",
        "candidate": {
            "heavy_count": heavy_count,
            "empty_count": empty_count,
            "heavy_headway_s": heavy_headway_s,
            "empty_headway_s": empty_headway_s,
            "phase_s": phase_s,
            "storage_preset_id": storage_preset_id,
            "settlement_step_s": settlement_step_s,
        },
        "benchmark": {
            "setup_wall_time_s": round(setup_wall_time_s, 6),
            "setup_excluded_from_candidate_timing": True,
            "scenario_count": len(scenarios),
            "repeat_count": repeat_count,
            "wall_times_s": [round(value, 6) for value in timings],
            "median_wall_time_s": round(median(timings), 6),
            "min_wall_time_s": round(min(timings), 6),
            "max_wall_time_s": round(max(timings), 6),
            "profiled_wall_time_s": round(profiled_wall_time_s, 6),
            "core_robust_feasible": bool(last_score.feasible),
            "constraint_violation": round(float(last_score.constraint_violation), 9),
            "semantic_stable": len(set(hashes)) == 1,
            "semantic_sha256": hashes[-1],
            "all_semantic_sha256": hashes,
        },
        "top_functions": _profile_rows(profile_path, top),
        "provenance": verify_provenance(provenance, data_dir),
        "outputs": {
            "profile": str(profile_path),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "DISPATCH_SINGLE_CANDIDATE_PROFILE.md"),
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(output_dir, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立命令行入口。"""

    parser = argparse.ArgumentParser(description="剖析重空协同调度的单候选完整稳健评价。")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--heavy-count", type=int, default=4)
    parser.add_argument("--empty-count", type=int, default=4)
    parser.add_argument("--heavy-headway-s", type=int, default=3300)
    parser.add_argument("--empty-headway-s", type=int, default=3300)
    parser.add_argument("--phase-s", type=int, default=840)
    parser.add_argument("--storage-preset-id", default="virtual_two_section_base")
    parser.add_argument("--settlement-step-s", type=int, default=10)
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument("--top", type=int, default=40)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行命令并打印关键计时和产物位置。"""

    args = build_parser().parse_args(argv)
    summary = run_profile(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
        heavy_headway_s=args.heavy_headway_s,
        empty_headway_s=args.empty_headway_s,
        phase_s=args.phase_s,
        storage_preset_id=args.storage_preset_id,
        settlement_step_s=args.settlement_step_s,
        repeat_count=args.repeat_count,
        top=args.top,
    )
    print(json.dumps({
        "median_wall_time_s": summary["benchmark"]["median_wall_time_s"],
        "semantic_stable": summary["benchmark"]["semantic_stable"],
        "report": summary["outputs"]["report"],
    }, ensure_ascii=False, indent=2))
    return 0 if summary["benchmark"]["semantic_stable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
