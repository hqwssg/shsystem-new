"""真实子进程四组消融：同预算命中、完整评价次数、含初始化/写出的端到端耗时。"""

from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import argparse
import csv
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constraint_guided_search import BudgetedEvaluator, run_search, screen_schedule
from rolling_optimizer import (
    OBJECTIVE_MODE_BALANCED, OBJECTIVE_PRIORITY_ENERGY_FIRST, ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    ScheduleScore, ScheduleTemplate, TemplateSearchConfig, candidate_selection_key, default_scenarios,
    energy_scenario_objective, robust_evaluate_schedule, template_key,
)
from run_dispatch_case import build_storage_eval_contexts, load_case_inputs
from storage_presets import default_storage_preset_library
from tools.benchmark_provenance import capture_provenance, verify_provenance
from tools.small_scale_optimality_gap_benchmark import (
    build_discrete_domain, _truncate_schedule, _with_service_population_constraint,
)

ARMS = {"baseline": (False, False), "guided": (True, False),
        "layered": (False, True), "combined": (True, True)}
ARM_LABELS = {"baseline": "现有搜索", "guided": "约束引导", "layered": "分层评价", "combined": "引导＋分层"}
DEFAULT_REFERENCE = ROOT / "outputs/search_quality_20261014/current_verified"


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def key_text(key):
    return json.dumps(key, ensure_ascii=False, separators=(",", ":"))


def make_domain(scale: int, settings: dict):
    base = ScheduleTemplate(3300, 2700, 2600, scale, scale,
                            storage_preset_id=settings["storage_preset_id"])
    domain = build_discrete_domain(base, **settings)
    return base, domain


def make_config(settings: dict, seed: int):
    return TemplateSearchConfig(
        method="nsga2", population_size=8, generations=3, elite_count=3,
        mutation_probability=0.45, headway_mutation_s=300, phase_mutation_s=300,
        hold_mutation_s=180, storage_shift_mutation_s=300,
        min_headway_s=min(*settings["heavy_headways_s"], *settings["empty_headways_s"]),
        max_headway_s=max(*settings["heavy_headways_s"], *settings["empty_headways_s"]),
        max_phase_s=max(settings["phases_s"]), max_hold_s=max(settings["holds_s"]),
        max_storage_align_shift_s=max(abs(value) for value in settings["storage_shifts_s"]),
        parallel_workers=1, seed=seed, enable_storage_preset_search=False,
        storage_preset_ids=(settings["storage_preset_id"],),
        allowed_heavy_headways_s=tuple(settings["heavy_headways_s"]),
        allowed_empty_headways_s=tuple(settings["empty_headways_s"]),
        allowed_phases_s=tuple(settings["phases_s"]), allowed_holds_s=tuple(settings["holds_s"]),
        allowed_storage_align_shifts_s=tuple(settings["storage_shifts_s"]))


def build_case(data_dir: Path, output: Path, preset: str, step: int):
    case = load_case_inputs(data_dir, output / "input_check")
    library = {item.scenario_id: item for item in default_storage_preset_library(case.battery)}
    contexts = build_storage_eval_contexts(
        case_inputs=case, trains=case.trains, base_battery=case.battery,
        preset_ids=[preset], library_by_id=library, settlement_step_s=step,
        initial_soc_kwh=0.0, target_final_soc_kwh=0.0, final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.05, wasted_energy_penalty_per_kwh=0.05,
        energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT)
    return case, contexts[preset]


def worker(spec: dict):
    started = time.perf_counter()
    output = Path(spec["output"])
    base, domain = make_domain(spec["scale"], spec["domain"])
    case, context = build_case(Path(spec["data_dir"]), output, base.storage_preset_id, spec["step_s"])
    scenarios = default_scenarios()
    horizon = spec["horizon_s"]

    def screen(template):
        return screen_schedule(_truncate_schedule(template, horizon), scenarios=scenarios,
                               resource_model=case.resource_model, heavy_cache=context.heavy_cache,
                               empty_cache=context.empty_cache, required_heavy_count=spec["scale"],
                               required_empty_count=spec["scale"],
                               min_depart_gap_s=case.resource_model.config.min_depart_headway_s)

    if spec.get("audit_only"):
        # 独立预筛验证，不向搜索进程提供穷举结果或全域筛查缓存。
        rows = [{"template_key": list(template_key(template)), **asdict(screen(template))} for template in domain]
        write_json(output / "screen_audit.json", rows)
        return

    full_records = []

    def full(template):
        schedule = _truncate_schedule(template, horizon)
        scenario_scores = []
        score = robust_evaluate_schedule(
            schedule, scenarios, context.heavy_cache, context.empty_cache,
            context.settlement_system, context.route.signaling_system,
            resource_model=case.resource_model, storage_sections=context.storage_sections,
            min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
            target_gap_s=int(round((base.heavy_headway_s + base.empty_headway_s) / 2)),
            objective_mode=OBJECTIVE_MODE_BALANCED,
            energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
            objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST, scenario_score_sink=scenario_scores)
        score = _with_service_population_constraint(score, schedule, spec["scale"], spec["scale"])
        full_records.append({"template_key": list(template_key(template)), "score": asdict(score),
                             "scenario_scores": [{"name": scenario.name, "core": scenario.core_for_feasibility,
                                                  "score": asdict(value)} for scenario, value in scenario_scores]})
        return score

    setup = time.perf_counter() - started
    guided, layered = ARMS[spec["arm"]]
    evaluator = BudgetedEvaluator(domain, full, screen, layered=layered,
                                  full_evaluation_budget=spec["full_budget"],
                                  proposal_budget=spec["proposal_budget"],
                                  deadline=started + spec["wall_limit_s"])
    result = run_search(base, make_config(spec["domain"], spec["seed"]), evaluator,
                        guided=guided, guide_probe_budget=spec["guide_probes"], guide_seed_count=2)
    selected = result.pop("selected")
    result.update({"schema_version": "1.0", "spec": spec, "setup_wall_time_s": setup,
                   "heuristic_found_feasible": selected is not None,
                   "selected_template_key": list(template_key(selected[0])) if selected else None,
                   "selected_score": asdict(selected[1]) if selected else None,
                   "selected_selection_key": list(candidate_selection_key(selected[1])) if selected else None,
                   "selected_is_full_evaluated": selected is not None,
                   "full_candidate_records": full_records, "trace": evaluator.trace,
                   "unscored_candidate_energy_values_exported": False,
                   "worker_to_prewrite_s": time.perf_counter() - started})
    write_json(output / "result.json", result)


def load_reference(path: Path, data_dir: Path, scales):
    summary = json.loads((path / "benchmark_summary.json").read_text(encoding="utf-8"))
    verification = json.loads((path / "verification.json").read_text(encoding="utf-8"))
    current = capture_provenance(data_dir)
    if not summary.get("benchmark_completed") or verification.get("passed") is not True:
        raise ValueError("精确判分基准尚未完整验收")
    if current["input_sha256"] != summary["provenance"]["input_sha256"]:
        raise ValueError("判分基准的数据指纹不匹配，必须先重跑穷举")
    # 旧快照只读展示适配器已升级，不参与生产完整评价；其余旧根模块逐个确认。
    changed = [name for name, digest in summary["provenance"]["evaluation_code_files"].items()
               if name != "result_explanation.py" and
               (not (ROOT / name).is_file() or sha256((ROOT / name).read_bytes()).hexdigest() != digest)]
    if changed:
        raise ValueError(f"判分基准的评价依赖发生变化，须重跑穷举：{changed}")
    if not set(scales) <= set(summary["settings"]["scales"]):
        raise ValueError("判分基准没有覆盖请求规模")
    settings = {key: summary["domain"][key] for key in
                ("heavy_headways_s", "empty_headways_s", "phases_s", "holds_s", "storage_shifts_s", "storage_preset_id")}
    with (path / "exact_candidates.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_key = {}
    for scale in scales:
        base, domain = make_domain(scale, settings)
        for template in domain:
            matches = [row for row in rows if int(row["scale"]) == scale
                       and int(row["heavy_headway_s"]) == template.heavy_headway_s
                       and int(row["empty_headway_s"]) == template.empty_headway_s
                       and int(row["phase_s"]) == template.heavy_empty_phase_s
                       and int(row["hold_s"]) == template.flex_zone_hold_s
                       and int(row["storage_align_shift_s"]) == template.storage_align_shift_s
                       and row["storage_preset_id"] == template.storage_preset_id]
            if len(matches) != 1:
                raise ValueError("精确判分候选缺失或重复")
            by_key[key_text(template_key(template))] = matches[0]
    return summary, settings, by_key


def aggregate(rows: list[dict]):
    output = []
    for scale in sorted({row["scale"] for row in rows}):
        for budget in sorted({row["full_budget"] for row in rows}):
            for arm in ARMS:
                group = [row for row in rows if row["scale"] == scale and row["full_budget"] == budget and row["arm"] == arm]
                if group:
                    output.append({"scale": scale, "train_count": scale * 2, "full_budget": budget, "arm": arm,
                                   "run_count": len(group), "feasible_count": sum(row["heuristic_found_feasible"] for row in group),
                                   "feasible_rate": statistics.fmean(row["heuristic_found_feasible"] for row in group),
                                   "mean_full_evaluations": statistics.fmean(row["full_evaluation_count"] for row in group),
                                   "mean_screen_count": statistics.fmean(row["screen_count"] for row in group),
                                   "median_e2e_s": statistics.median(row["e2e_wall_time_s"] for row in group)})
    return output


def acceptance(rows: list[dict], audit: list[dict]):
    paired = []
    for baseline in (row for row in rows if row["arm"] == "baseline"):
        other = next(row for row in rows if row["arm"] == "combined" and
                     all(row[field] == baseline[field] for field in ("scale", "seed", "repeat", "full_budget")))
        paired.append({"train_count": baseline["scale"] * 2, "seed": baseline["seed"], "repeat": baseline["repeat"],
                       "full_budget": baseline["full_budget"],
                       "lost_feasible": baseline["heuristic_found_feasible"] and not other["heuristic_found_feasible"],
                       "worse_selected_key": bool(baseline["selected_selection_key"] and other["selected_selection_key"] and
                                                   other["selected_selection_key"] > baseline["selected_selection_key"]),
                       "e2e_ratio": other["e2e_wall_time_s"] / baseline["e2e_wall_time_s"],
                       "baseline_full": baseline["full_evaluation_count"], "combined_full": other["full_evaluation_count"]})
    count_base = sum(row["baseline_full"] for row in paired)
    reduction = 1 - sum(row["combined_full"] for row in paired) / count_base if count_base else 0.0
    ratio = statistics.median(row["e2e_ratio"] for row in paired)
    checks = {
        "no_false_rejection": not any(item["false_rejection_count"] for item in audit),
        "all_full_scores_match_reference": all(row["reference_scores_match"] for row in rows),
        "no_budget_overrun": all(row["full_evaluation_count"] <= row["full_budget"] and
                                 row["proposal_count"] <= row["proposal_budget"] for row in rows),
        "no_timeout": all(row["stop_reason"] != "wall_time_budget" for row in rows),
        "no_paired_feasible_loss": not any(row["lost_feasible"] for row in paired),
        "no_paired_selected_quality_loss": not any(row["worse_selected_key"] for row in paired),
        "combined_finite_domain_hit_rate_at_least_90pct": statistics.fmean(
            row["heuristic_found_feasible"] for row in rows if row["arm"] == "combined") >= 0.9,
        "full_evaluation_reduction_at_least_25pct": reduction >= 0.25,
        "paired_median_e2e_reduction_at_least_20pct": ratio <= 0.8,
    }
    return {"passed": all(checks.values()), "checks": checks, "paired_results": paired,
            "full_evaluation_reduction_rate": reduction, "median_paired_e2e_ratio": ratio,
            "scope": "local_finite_domain_experiment_only", "production_enabled": False}


def compare_full_records(records, reference):
    checked = []
    metrics = ("grid_kwh", "wasted_kwh", "total_cost", "headway_deviation",
               "constraint_violation", "effective_regen_loss_kwh")
    for record in records:
        source = reference.get(key_text(record["template_key"]))
        if source is None:
            return False
        score = record["score"]
        checked.append(score["feasible"] == (source["feasible"].lower() == "true") and
                       all(abs(score[key] - float(source[key])) <= 1e-6 for key in metrics) and
                       all(abs(actual - float(source[f"selection_key_{index}"])) <= 1e-6
                           for index, actual in enumerate(candidate_selection_key(
                               ScheduleScore(**score)))))
    return all(checked)


def write_report(summary, output):
    result = summary["acceptance"]
    lines = ["# 约束引导搜索＋分层评价：真实端到端四组消融", "",
             f"本地有限域验收：{'通过' if result['passed'] else '未通过'}；生产默认开关未改变。", "",
             "## 公平口径", "",
             "四组使用相同输入、离散域、NSGA-II规模、随机种子、完整评价次数上限、候选数上限和墙钟上限。引导扫描记入预筛次数与候选数；初始化、扫描、完整五场景评价、写盘、子进程启动/导入均计入实测端到端耗时。各组独立新进程，不共享候选评分缓存。这里是搜索试验链端到端，不包含数据库排队、生产整套图表工件或事后修复。",
             "",
             "约束引导只用必要约束分数选择两个起点，并把其完整评价计入预算；分层预筛只拒绝核心结构约束已明确失败的候选。通过预筛仍必须完成信号、电气、能量和SOC评价。内部约束代理只引导不可行区搜索，不作为完整评分或可采用结果输出；因此不是对旧搜索轨迹的等价加速声明。",
             "",
             "穷举基准只在子进程完成后独立判分，搜索进程不读穷举分数。此实验是限预算纯搜索及两个试验开关，不包含生产流程已有的事后修复/精确兜底，不代表生产任务成功率。", "",
             "## 分组结果", "",
             "| 列车数 | 完整评价上限 | 方法 | 可行命中 | 平均完整评价数 | 平均预筛数 | 端到端中位数/秒 |",
             "| ---: | ---: | --- | ---: | ---: | ---: | ---: |"]
    for row in summary["groups"]:
        lines.append(f"| {row['train_count']} | {row['full_budget']} | {ARM_LABELS[row['arm']]} | "
                     f"{row['feasible_count']}/{row['run_count']} | {row['mean_full_evaluations']:.2f} | "
                     f"{row['mean_screen_count']:.2f} | {row['median_e2e_s']:.3f} |")
    lines += ["", "## 预先声明的验收门槛", "",
              "不误删穷举可行解；全部真实完整评分与独立基准一致；不超完整评价/候选预算、不发生墙钟超时；组合组不丢失基线已命中的可行解、不降低两组均命中时的选中方案质量，有限域命中率至少90%；完整评价总次数至少降低25%，配对端到端耗时比中位数不高于0.8。", ""]
    lines += [f"- {name}：{'通过' if passed else '未通过'}" for name, passed in result["checks"].items()]
    lines += ["", f"- 组合组完整评价次数降幅：{result['full_evaluation_reduction_rate']:.1%}。",
              f"- 配对端到端耗时比中位数：{result['median_paired_e2e_ratio']:.3f}。", "",
              "## 结论边界", "",
              "输入仍含正式数据缺口；该有限域的能源目标缺乏区分度，不能把命中率/耗时改善称为额外节能收益，不能外推任意逐车调整或正式运行图。扩大规模、引入正放电/电气约束合成工况、验证完整生产链后，才能决定是否默认启用。",
              "",
              "完整原始记录在runs/各独立进程目录；screen_audit/为全域必要约束验证；benchmark_summary.json记录指纹、预算、顺序、逐次指标及配对验收。墙钟预算按检查点停止，已开始的单候选评价允许安全完成，不能把它写成硬实时SLA。"]
    (output / "CONSTRAINT_GUIDED_SEARCH_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(args):
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "benchmark_summary.json").exists() or (output / "benchmark_progress.json").exists():
        raise ValueError("请使用新的输出目录，避免覆盖之前的实验记录")
    if not args.scales or any(value <= 0 for value in args.scales) or len(set(args.scales)) != len(args.scales):
        raise ValueError("规模须为不重复的正整数")
    if not args.seeds or len(set(args.seeds)) != len(args.seeds) or args.repeats <= 0:
        raise ValueError("种子不应重复，重复次数应为正")
    if any(value <= 0 for value in args.full_budgets) or len(set(args.full_budgets)) != len(args.full_budgets):
        raise ValueError("完整评价预算须为不重复的正整数")
    provenance = capture_provenance(args.data_dir)
    reference_summary, domain, reference = load_reference(args.reference_dir, args.data_dir, args.scales)
    domain_count = reference_summary["domain"]["candidate_count_per_scale"]
    if args.proposal_budget <= 0 or args.guide_probes <= 0 or not math.isfinite(args.wall_limit_s) or args.wall_limit_s <= 0:
        raise ValueError("候选、预筛和墙钟预算必须为正")
    rows, audit, order = [], [], []
    common = {"data_dir": str(args.data_dir.resolve()), "domain": domain,
              "step_s": reference_summary["settings"]["settlement_step_s"],
              "horizon_s": reference_summary["settings"]["horizon_s"],
              "proposal_budget": min(args.proposal_budget, domain_count), "guide_probes": args.guide_probes,
              "wall_limit_s": args.wall_limit_s}

    def execute(spec, directory):
        spec["output"] = str(directory)
        write_json(directory / "spec.json", spec)
        started = time.perf_counter()
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker-spec", str(directory / "spec.json")],
                                 cwd=ROOT, capture_output=True, timeout=args.wall_limit_s + 45)
        elapsed = time.perf_counter() - started
        (directory / "worker.stdout.txt").write_bytes(process.stdout)
        (directory / "worker.stderr.txt").write_bytes(process.stderr)
        if process.returncode:
            raise RuntimeError(f"子进程失败：{directory}，查看worker.stderr.txt")
        return elapsed

    total = len(args.scales) * len(args.seeds) * len(args.full_budgets) * args.repeats * len(ARMS)
    for scale in args.scales:
        for budget in args.full_budgets:
            for repeat in range(args.repeats):
                for seed in args.seeds:
                    arms = list(ARMS)
                    random.Random(scale * 100000 + seed * 100 + repeat + budget).shuffle(arms)
                    for arm in arms:
                        directory = output / "runs" / f"n{scale * 2}_b{budget}_s{seed}_r{repeat}_{arm}"
                        spec = {**common, "scale": scale, "seed": seed, "repeat": repeat, "arm": arm, "full_budget": budget}
                        elapsed = execute(spec, directory)
                        measured = json.loads((directory / "result.json").read_text(encoding="utf-8"))
                        row = {key: measured[key] for key in (
                            "heuristic_found_feasible", "selected_template_key", "selected_selection_key", "stop_reason",
                            "full_evaluation_count", "screen_count", "screen_rejection_count", "proposal_count",
                            "setup_wall_time_s", "search_wall_time_s", "screen_time_s", "full_evaluation_time_s")}
                        row.update({"scale": scale, "seed": seed, "repeat": repeat, "full_budget": budget, "arm": arm,
                                    "proposal_budget": common["proposal_budget"], "e2e_wall_time_s": elapsed,
                                    "reference_scores_match": compare_full_records(measured["full_candidate_records"], reference),
                                    "result_file": str(directory / "result.json")})
                        rows.append(row)
                        order.append(directory.name)
                        write_json(output / "benchmark_progress.json", {"status": "running", "completed": len(rows),
                                                                        "total": total, "rows": rows})
                        print(f"[{len(rows)}/{total}] n={scale * 2} seed={seed} {arm}: "
                              f"hit={row['heuristic_found_feasible']} full={row['full_evaluation_count']} "
                              f"screen={row['screen_count']} e2e={elapsed:.3f}s", flush=True)
        directory = output / "screen_audit" / f"n{scale * 2}"
        execute({**common, "scale": scale, "audit_only": True}, directory)
        screen_rows = json.loads((directory / "screen_audit.json").read_text(encoding="utf-8"))
        false_rejections = [row for row in screen_rows if row["rejected"] and
                            reference[key_text(row["template_key"])]["feasible"].lower() == "true"]
        audit.append({"scale": scale, "candidate_count": len(screen_rows),
                      "rejected_count": sum(row["rejected"] for row in screen_rows),
                      "false_rejection_count": len(false_rejections)})
    summary = {"schema_version": "1.0", "completed": True, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
               "provenance": verify_provenance(provenance, args.data_dir), "reference_dir": str(args.reference_dir.resolve()),
               "reference_summary_sha256": sha256((args.reference_dir / "benchmark_summary.json").read_bytes()).hexdigest(),
               "reference_candidates_sha256": sha256((args.reference_dir / "exact_candidates.csv").read_bytes()).hexdigest(),
               "settings": {**common, "scales": args.scales, "seeds": args.seeds, "repeats": args.repeats,
                            "full_budgets": args.full_budgets, "nsga2_population": 8, "nsga2_generations": 3},
               "execution_order": order, "rows": rows, "groups": aggregate(rows), "screen_audit": audit,
               "acceptance": acceptance(rows, audit)}
    write_report(summary, output)
    write_json(output / "benchmark_summary.json", summary)
    write_json(output / "benchmark_progress.json", {"status": "completed", "completed": len(rows), "total": total})
    print(json.dumps({"output": str(output), "acceptance": summary["acceptance"]["checks"],
                      "passed": summary["acceptance"]["passed"]}, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/constraint_guided_search_20261015")
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--scales", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37, 53, 71])
    parser.add_argument("--full-budgets", type=int, nargs="+", default=[12])
    parser.add_argument("--proposal-budget", type=int, default=48)
    parser.add_argument("--guide-probes", type=int, default=48)
    parser.add_argument("--wall-limit-s", type=float, default=120.0)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.worker_spec:
        worker(json.loads(args.worker_spec.read_text(encoding="utf-8")))
    else:
        run_benchmark(args)


if __name__ == "__main__":
    main()
