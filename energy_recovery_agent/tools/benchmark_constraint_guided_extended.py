"""生产接入前的离线扩展试验；不接数据库、不改变生产求解开关或正式输入。"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import argparse
import json
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
from energy_settlement import StorageDeviceRuntimeState, storage_section_ids_from_limits
from power_arm_electrical_limits import DynamicPowerArmLimit
from rolling_optimizer import (
    RollingOptimizer, RollingWindowState, ScheduleTemplate, apply_scenario,
    apply_dynamic_train_services, apply_train_delay_observations,
    candidate_selection_key, default_scenarios, generate_schedule, robust_evaluate_schedule,
    template_key,
)
from run_dispatch_case import build_storage_eval_contexts, load_case_inputs, settle_schedule
from storage_presets import default_storage_preset_library
from tools.benchmark_constraint_guided_search import ARMS, ARM_LABELS, key_text, make_config, write_json
from tools.benchmark_provenance import capture_provenance, verify_provenance
from tools.small_scale_optimality_gap_benchmark import build_discrete_domain, _truncate_schedule

PRESET = "virtual_two_section_base"
DOMAIN = dict(heavy_headways_s=[2700, 3300], empty_headways_s=[2700, 3300],
              phases_s=[2000, 2600, 2760, 3000], holds_s=[0, 180],
              storage_shifts_s=[0, 300], storage_preset_id=PRESET)
PROFILES = {
    "positive_discharge": {"label": "合成正放电", "max_discharge_kw": 2000.0, "supply_limit_kw": None},
    "supply_limited": {"label": "合成供电受限", "max_discharge_kw": 2000.0, "supply_limit_kw": 10000.0},
}


def case_id(spec):
    return f"{spec['profile']}_n{spec['scale'] * 2}"


def make_domain(spec):
    base = ScheduleTemplate(3300, 2700, 2600, spec["scale"], spec["scale"], storage_preset_id=PRESET)
    return base, build_discrete_domain(base, **DOMAIN)


def config_for(seed):
    return replace(make_config(DOMAIN, seed), population_size=12, generations=10, elite_count=4)


def build_context(spec, output):
    """显式、只读覆盖；不能把假设回写 battery.json 或供电臂文件。"""
    case = load_case_inputs(Path(spec["data_dir"]), output / "input_check")
    profile = PROFILES[spec["profile"]]
    if case.battery.storage_devices:
        raise ValueError("此合成试验针对当前虚拟预设，不能覆盖正式逐设备配置")
    battery = replace(case.battery, max_discharge_power_kW=profile["max_discharge_kw"],
                      planning_assumption=True, data_status="synthetic_preproduction_validation",
                      note="仅供离线扩展验证的2000kW正放电假设，不是正式设备参数。")
    library = {item.scenario_id: item for item in default_storage_preset_library(battery)}
    context = build_storage_eval_contexts(
        case_inputs=case, trains=case.trains, base_battery=battery, preset_ids=[PRESET],
        library_by_id=library, settlement_step_s=10, initial_soc_kwh=0.0,
        target_final_soc_kwh=0.0, final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.05, wasted_energy_penalty_per_kwh=0.05,
        energy_scenario="storage_no_direct")[PRESET]
    if profile["supply_limit_kw"] is not None:
        events = tuple(DynamicPowerArmLimit(
            f"synthetic_supply_{arm}", arm, 0, 1000000,
            max_traction_supply_kw=profile["supply_limit_kw"],
            reason="离线供电受限压力工况，不是正式供电能力")
            for arm in sorted(context.power_arm_limits))
        context = replace(context, settlement_system=context.settlement_system.with_dynamic_power_arm_limits(events))
    return case, context


def scorer(spec, case, context):
    base, _ = make_domain(spec)
    horizon = spec["horizon_s"]

    def screen(template):
        return screen_schedule(_truncate_schedule(template, horizon), scenarios=default_scenarios(),
                               resource_model=case.resource_model, heavy_cache=context.heavy_cache,
                               empty_cache=context.empty_cache, required_heavy_count=spec["scale"],
                               required_empty_count=spec["scale"],
                               min_depart_gap_s=case.resource_model.config.min_depart_headway_s)

    def full(template):
        schedule = _truncate_schedule(template, horizon)
        if len(schedule.heavy_departures_s) != spec["scale"] or len(schedule.empty_departures_s) != spec["scale"]:
            raise AssertionError("不能通过截断列车数量伪造扩大规模或降低能耗")
        per_scenario = []
        score = robust_evaluate_schedule(
            schedule, default_scenarios(), context.heavy_cache, context.empty_cache,
            context.settlement_system, context.route.signaling_system,
            resource_model=case.resource_model, storage_sections=context.storage_sections,
            min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
            target_gap_s=round((base.heavy_headway_s + base.empty_headway_s) / 2),
            objective_mode="balanced", energy_scenario="storage_no_direct", objective_priority="energy_first",
            scenario_score_sink=per_scenario)
        record = {"template_key": list(template_key(template)), "score": asdict(score),
                  "scenario_scores": [{"name": s.name, "core": s.core_for_feasibility, "score": asdict(v)}
                                      for s, v in per_scenario]}
        return score, record

    return screen, full


def search_worker(spec):
    started = time.perf_counter()
    output = Path(spec["output"])
    base, domain = make_domain(spec)
    case, context = build_context(spec, output)
    screen, full = scorer(spec, case, context)
    records = []

    def evaluate(template):
        value, record = full(template)
        records.append(record)
        return value

    setup_s = time.perf_counter() - started
    guided, layered = ARMS[spec["arm"]]
    evaluator = BudgetedEvaluator(domain, evaluate, screen, layered=layered,
                                  full_evaluation_budget=spec["full_budget"], proposal_budget=len(domain),
                                  deadline=started + spec["wall_limit_s"])
    result = run_search(base, config_for(spec["seed"]), evaluator, guided=guided,
                        guide_probe_budget=len(domain), guide_seed_count=2)
    selected = result.pop("selected")
    result.update(schema_version="1.0", spec=spec, setup_wall_time_s=setup_s,
                  heuristic_found_feasible=selected is not None,
                  selected_template_key=list(template_key(selected[0])) if selected else None,
                  selected_score=asdict(selected[1]) if selected else None,
                  selected_selection_key=list(candidate_selection_key(selected[1])) if selected else None,
                  full_candidate_records=records, trace=evaluator.trace,
                  production_enabled=False, synthetic_profile=PROFILES[spec["profile"]])
    write_json(output / "result.json", result)


def replay_worker(spec):
    output = Path(spec["output"])
    case, context = build_context(spec, output)
    screen, full = scorer(spec, case, context)
    _, domain = make_domain(spec)
    lookup = {key_text(template_key(t)): t for t in domain}
    rows = []
    for key in spec["replay_keys"]:
        _, record = full(lookup[key_text(key)])
        rows.append(record)
    # 全域廉价结构审计，不作全域完整电气可行性/最优性声明。
    audit = [{"template_key": list(template_key(t)), **asdict(screen(t))} for t in domain]
    write_json(output / "result.json", {"spec": spec, "full_candidate_records": rows, "screen_audit": audit})


def storage_summary(result):
    fields = ("initial_soc_kwh", "final_soc_kwh", "initial_soc_by_storage_kwh", "final_soc_by_storage_kwh",
              "battery_charge_kwh", "battery_discharge_kwh", "battery_charge_by_storage_kwh",
              "battery_discharge_by_storage_kwh", "self_discharge_loss_kwh", "total_gen_kwh", "total_con_kwh",
              "grid_kwh", "wasted_kwh", "traction_supply_excess_kwh")
    return {name: getattr(result, name) for name in fields}


def rolling_worker(spec):
    """真实生产优化器锁定门禁＋真实轨迹结算器逐设备连续性；不使用伪评分。"""
    output = Path(spec["output"])
    case, context = build_context(spec, output)
    system = context.settlement_system
    storage_ids = storage_section_ids_from_limits(system.power_arm_limits)
    initial_states = tuple(StorageDeviceRuntimeState(s, system.capacity_kwh * .25 / len(storage_ids))
                           for s in storage_ids)
    initial_system = system.with_storage_runtime_states(initial_states, preserve_target=False)
    schedule = generate_schedule(ScheduleTemplate(3300, 3300, 2760, 6, 6, storage_preset_id=PRESET))
    # 对齐10秒结算桶；十个相邻、无重叠窗口覆盖完整回放区间。
    edges = list(range(0, 45001, 4500))
    whole = settle_schedule(schedule, context.heavy_cache, context.empty_cache, initial_system,
                            case.resource_model, from_time_s=0, until_time_s=edges[-1])
    states = initial_states
    windows = []
    for start, end in zip(edges, edges[1:]):
        active = system.with_storage_runtime_states(states, preserve_target=False)
        settled = settle_schedule(schedule, context.heavy_cache, context.empty_cache, active,
                                  case.resource_model, from_time_s=start, until_time_s=end)
        windows.append({"from_time_s": start, "until_time_s": end, **storage_summary(settled)})
        states = tuple(replace(item, soc_kwh=settled.final_soc_by_storage_kwh[item.storage_section_id])
                       for item in states)

    # 有意重置SOC的负例：证明当前用例能识别“每窗重新初始化”这个错误。
    reset_windows = [settle_schedule(schedule, context.heavy_cache, context.empty_cache, initial_system,
                                     case.resource_model, from_time_s=start, until_time_s=end)
                     for start, end in zip(edges, edges[1:])]
    missing_rejected = overflow_rejected = False
    try:
        system.with_storage_runtime_states(initial_states[:-1]).settle([])
    except ValueError:
        missing_rejected = True
    try:
        system.with_storage_runtime_states((replace(initial_states[0], soc_kwh=system.capacity_kwh + 1),
                                            *initial_states[1:])).settle([])
    except ValueError:
        overflow_rejected = True

    locked_h, locked_e = [0, 3300], [2760, 6060]
    # counts=0只重评已下发的四列；禁止借重新生成时刻改变既有承诺。
    base = ScheduleTemplate(3300, 3300, 3000, 0, 0, flex_zone_hold_s=180, storage_preset_id=PRESET)
    config = replace(config_for(11), population_size=2, generations=1, elite_count=1,
                     allowed_heavy_headways_s=(3300,), allowed_empty_headways_s=(3300,),
                     allowed_phases_s=(3000,), allowed_holds_s=(180,), allowed_storage_align_shifts_s=(0,))
    state = RollingWindowState(1800, locked_h, locked_e, locked_empty_storage_hold_s=0,
                               locked_storage_preset_id=PRESET, storage_device_states=initial_states)
    optimizer = RollingOptimizer(context.route, context.heavy_cache, context.empty_cache, system,
                                 case.resource_model, context.storage_sections,
                                 storage_contexts={PRESET: context}, default_storage_preset_id=PRESET)
    result = optimizer.optimize_once(state, base, horizon_s=10000, execute_window_s=3300,
                                     search_config=config, enable_recovery=False)
    candidate = result.schedule
    locks = []
    for scenario in default_scenarios():
        disturbed = apply_scenario(candidate, scenario, disturbance_from_time_s=1800,
                                   locked_heavy_departures_s=iter(locked_h), locked_empty_departures_s=iter(locked_e))
        locks.append({"scenario": scenario.name, "heavy": disturbed.heavy_departures_s,
                      "empty": disturbed.empty_departures_s})
    cancellation_rejected = False
    try:
        apply_dynamic_train_services(candidate, [candidate.heavy_train_ids[1]], (), current_time_s=1800,
                                     locked_heavy_departures_s=locked_h, locked_empty_departures_s=locked_e)
    except ValueError:
        cancellation_rejected = True
    observed_delay_rejected = False
    try:
        apply_train_delay_observations(candidate, [(candidate.empty_train_ids[0], 600)],
                                       current_time_s=1800, locked_empty_departures_s=locked_e)
    except ValueError:
        observed_delay_rejected = True
    # 同一已下发历史叠加零供电＋新增请求；必须扣留新增，不得释放历史。
    zero_events = tuple(DynamicPowerArmLimit(f"zero_{arm}", arm, 0, 1000000, max_traction_supply_kw=0.0)
                        for arm in sorted(context.power_arm_limits))
    blocked = optimizer.optimize_once(replace(state, dynamic_power_arm_limits=zero_events),
                                       replace(base, heavy_count=1, empty_count=1), horizon_s=10000,
                                       execute_window_s=3300, search_config=config, enable_recovery=False)
    locked_only = generate_schedule(ScheduleTemplate(3300, 3300, 2760, 2, 2, storage_preset_id=PRESET))
    # 多场景迭代器输入必须在预筛内部固化；与完整评价采用相同锁定和扰动起点。
    screened = screen_schedule(locked_only, scenarios=default_scenarios(), resource_model=case.resource_model,
                               heavy_cache=context.heavy_cache, empty_cache=context.empty_cache,
                               required_heavy_count=2, required_empty_count=2,
                               min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
                               disturbance_from_time_s=1800, locked_heavy_departures_s=iter(locked_h),
                               locked_empty_departures_s=iter(locked_e))
    write_json(output / "result.json", {
        "spec": spec, "storage_ids": storage_ids, "initial_states": [asdict(x) for x in initial_states],
        "whole": storage_summary(whole), "windows": windows,
        "reset_grid_kwh": sum(x.grid_kwh for x in reset_windows),
        "reset_final_soc_by_storage_kwh": reset_windows[-1].final_soc_by_storage_kwh,
        "missing_device_rejected": missing_rejected, "overflow_soc_rejected": overflow_rejected,
        "lock_success": {"commit_status": result.commit_status, "heavy": candidate.heavy_departures_s,
                         "empty": candidate.empty_departures_s, "hold_s": candidate.template.flex_zone_hold_s,
                         "preset": candidate.template.storage_preset_id, "disturbances": locks,
                         "screen": asdict(screened), "cancellation_rejected": cancellation_rejected,
                         "observed_delay_rejected": observed_delay_rejected},
        "lock_failure": {"commit_status": blocked.commit_status,
                         "heavy": blocked.committed_execution_schedule.heavy_departures_s,
                         "empty": blocked.committed_execution_schedule.empty_departures_s,
                         "executable_heavy": blocked.executable_heavy_departures_s,
                         "executable_empty": blocked.executable_empty_departures_s},
        "efficiency": system.round_trip_efficiency, "capacity_kwh": system.capacity_kwh,
        "note": "锁定为真实优化器集成校验；SOC为12列固定执行轨迹的10窗回放，不冒称已验证完整闭环调度。"})


def summarize(rows):
    groups = []
    for profile, scale, budget in sorted({(r["profile"], r["scale"], r["full_budget"]) for r in rows}):
        for arm in ("baseline", "combined"):
            group = [r for r in rows if (r["profile"], r["scale"], r["full_budget"], r["arm"])
                     == (profile, scale, budget, arm)]
            groups.append(dict(profile=profile, train_count=scale * 2, full_budget=budget, arm=arm,
                               run_count=len(group), hits=sum(r["heuristic_found_feasible"] for r in group),
                               mean_full_evaluations=statistics.fmean(r["full_evaluation_count"] for r in group),
                               mean_screens=statistics.fmean(r["screen_count"] for r in group),
                               median_e2e_s=statistics.median(r["e2e_wall_time_s"] for r in group)))
    pairs = []
    for base in (r for r in rows if r["arm"] == "baseline"):
        other = next(r for r in rows if r["arm"] == "combined" and
                     all(r[k] == base[k] for k in ("profile", "scale", "full_budget", "seed")))
        both = base["heuristic_found_feasible"] and other["heuristic_found_feasible"]
        pairs.append({"case_id": case_id(base), "seed": base["seed"], "full_budget": base["full_budget"],
                      "baseline_hit": base["heuristic_found_feasible"], "combined_hit": other["heuristic_found_feasible"],
                      "lost_feasible": base["heuristic_found_feasible"] and not other["heuristic_found_feasible"],
                      "quality_worse": bool(both and other["selected_selection_key"] > base["selected_selection_key"]),
                      "e2e_ratio": other["e2e_wall_time_s"] / base["e2e_wall_time_s"],
                      "baseline_full": base["full_evaluation_count"], "combined_full": other["full_evaluation_count"]})
    # 双方都未命中的压力工况仅作安全/可搜索性诊断，不能计入有效提速。
    useful = [p for p in pairs if p["baseline_hit"] or p["combined_hit"]]
    count = sum(p["baseline_full"] for p in useful)
    return {"groups": groups, "pairs": pairs, "effectiveness": {
        "comparable_pair_count": len(useful),
        "full_evaluation_reduction": 1 - sum(p["combined_full"] for p in useful) / count if count else None,
        "median_paired_e2e_ratio": statistics.median(p["e2e_ratio"] for p in useful) if useful else None,
        "no_paired_feasible_loss": not any(p["lost_feasible"] for p in pairs),
        "no_paired_quality_loss": not any(p["quality_worse"] for p in pairs)}}


def plan(data_dir, output):
    cases = [("positive_discharge", n, b, seed) for n in (4, 6) for b in (24, 48) for seed in (11, 23)]
    cases += [("supply_limited", n, 48, seed) for n in (4, 6) for seed in (11, 23)]
    cases += [("positive_discharge", 8, 48, 11)]
    specs = []
    for profile, scale, budget, seed in cases:
        arms = ["baseline", "combined"]
        random.Random(seed + scale + budget).shuffle(arms)
        for arm in arms:
            run_id = f"{profile}_n{scale * 2}_b{budget}_s{seed}_{arm}"
            specs.append(dict(mode="search", run_id=run_id, profile=profile, scale=scale,
                              horizon_s=scale * 3300, full_budget=budget, seed=seed, arm=arm,
                              wall_limit_s=600, proposal_budget=64, data_dir=str(data_dir),
                              output=str(output / "runs" / run_id)))
    return specs


def invoke(spec, output):
    work = Path(spec["output"])
    work.mkdir(parents=True, exist_ok=True)
    spec_path = work / "spec.json"
    write_json(spec_path, spec)
    start = time.perf_counter()
    with (work / "stdout.log").open("w", encoding="utf-8") as stdout, (work / "stderr.log").open("w", encoding="utf-8") as stderr:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker-spec", str(spec_path)],
                              cwd=ROOT, stdout=stdout, stderr=stderr, timeout=spec.get("wall_limit_s", 900) + 60)
    elapsed = time.perf_counter() - start
    if proc.returncode:
        raise RuntimeError(f"子进程失败，已保留证据：{work / 'stderr.log'}")
    result = json.loads((work / "result.json").read_text(encoding="utf-8"))
    write_json(work / "process_timing.json", {"e2e_wall_time_s": elapsed, "exit_code": proc.returncode})
    return result, elapsed


def run(args):
    output, data_dir = args.output_dir.resolve(), args.data_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        raise ValueError("必须使用新输出目录，保留既有试验记录")
    provenance = capture_provenance(data_dir)
    specs = plan(data_dir, output)
    manifest = {"schema_version": "1.0", "created_at": datetime.now().astimezone().isoformat(),
                "provenance": provenance, "domain": DOMAIN, "profiles": PROFILES, "specs": specs,
                "preregistered_gates": {"no_false_rejection_among_full_records": True,
                    "selected_independent_replay": True, "no_budget_overrun": True, "no_timeout": True,
                    "positive_discharge_exercised": True, "supply_limit_exercised": True,
                    "commit_lock_and_failure_gate": True, "device_soc_continuity": True,
                    "whole_split_energy_conservation_tolerance_kwh": 1e-6,
                    "no_paired_hit_or_quality_loss": True, "min_full_reduction_useful_pairs": .25,
                    "max_paired_median_e2e_ratio_useful_pairs": .8},
                "boundaries": ["64候选有限域，不证明全局最优或全局无解", "两个种子只作扩展筛查，不是上线成功率估计",
                               "16列单种子压力项", "实际子进程搜索链耗时，不含数据库/完整生产工件",
                               "SOC固定执行轨迹回放与锁定集成分别校验，不冒充完整闭环联调"],
                "production_enabled": False}
    write_json(output / "manifest.json", manifest)
    rows = []
    for index, spec in enumerate(specs):
        result, elapsed = invoke(spec, output)
        row = {k: spec[k] for k in ("run_id", "profile", "scale", "full_budget", "seed", "arm")}
        row.update({k: result[k] for k in ("full_evaluation_count", "screen_count", "proposal_count",
                                          "heuristic_found_feasible", "selected_selection_key", "stop_reason")})
        row["e2e_wall_time_s"] = elapsed
        rows.append(row)
        write_json(output / "progress.json", {"completed": len(rows), "total": len(specs), "rows": rows})
        print(f"[{index + 1}/{len(specs)}] {spec['run_id']} hit={row['heuristic_found_feasible']} "
              f"full={row['full_evaluation_count']} e2e={elapsed:.3f}s", flush=True)

    # 搜索全部完成后，独立新进程回放选中方案和每工况两个被拒样本；不向搜索提供答案。
    audits = []
    for profile, scale in sorted({(r["profile"], r["scale"]) for r in rows}):
        group_specs = [s for s in specs if s["profile"] == profile and s["scale"] == scale]
        records, chosen = {}, set()
        for spec in group_specs:
            result = json.loads((Path(spec["output"]) / "result.json").read_text(encoding="utf-8"))
            for record in result["full_candidate_records"]:
                records[key_text(record["template_key"])] = record
            if result["selected_template_key"]:
                chosen.add(key_text(result["selected_template_key"]))
        chosen.update(sorted(k for k, r in records.items() if not r["score"]["feasible"])[:2])
        if not chosen and records:
            chosen.add(min(records))
        spec = {**group_specs[0], "mode": "replay", "replay_keys": [json.loads(k) for k in sorted(chosen)],
                "output": str(output / "audits" / f"{profile}_n{scale * 2}"), "wall_limit_s": 600}
        _, elapsed = invoke(spec, output)
        audits.append({"case_id": case_id(spec), "output": spec["output"], "e2e_wall_time_s": elapsed})
        print(f"independent replay {case_id(spec)}: {len(chosen)} candidates", flush=True)
    rolling_spec = {**specs[0], "mode": "rolling", "profile": "positive_discharge",
                    "output": str(output / "rolling_safety"), "wall_limit_s": 900}
    invoke(rolling_spec, output)
    summary = {"schema_version": "1.0", "benchmark_completed": True, "rows": rows, "audits": audits,
               **summarize(rows), "provenance": verify_provenance(provenance, data_dir), "production_enabled": False}
    write_json(output / "benchmark_summary.json", summary)
    from tools.verify_constraint_guided_extended import verify, write_report
    verification = verify(output)
    write_json(output / "verification.json", verification)
    write_report(output, summary, verification)
    print(json.dumps(verification, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/constraint_guided_extended_20261015")
    parser.add_argument("--worker-spec", type=Path)
    args = parser.parse_args()
    if args.worker_spec:
        spec = json.loads(args.worker_spec.read_text(encoding="utf-8"))
        {"search": search_worker, "replay": replay_worker, "rolling": rolling_worker}[spec["mode"]](spec)
    else:
        run(args)


if __name__ == "__main__":
    main()
