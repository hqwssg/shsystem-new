"""串行同预算重测12/16列和滚动新增服务；所有失败原样留档，不开启生产开关。"""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import json
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from budgeted_recovery_search import optimize_budgeted
from energy_settlement import StorageDeviceRuntimeState, storage_section_ids_from_limits
from recovery_work_budget import RecoveryWorkBudget
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate, gate_rolling_execution_commit
from run_dispatch_case import settle_schedule
from tools.benchmark_constraint_guided_extended import (PRESET, build_context, config_for, make_domain, storage_summary)
from tools.benchmark_constraint_guided_search import write_json
from tools.benchmark_provenance import capture_provenance, verify_provenance

LIMITS = dict(full_limit=48, resource_limit=1800, candidate_limit=2048, wall_limit_s=600, solver_limit_s=60)
POLICY = dict(regular_full_limit=12, repair_resource_limit=900, exact_adjustment_bound_s=600)


def serializable(result):
    result = dict(result)
    selected = result.pop("selected")
    result["diagnostic_schedule"] = asdict(result["diagnostic_schedule"])
    result.update(found_feasible=selected is not None,
                  selected_schedule=asdict(selected[0]) if selected else None,
                  selected_score=asdict(selected[1]) if selected else None,
                  selected_stage=selected[2]["stage"] if selected else None)
    return result


def static_worker(spec):
    started = time.perf_counter()
    budget = RecoveryWorkBudget(**spec["limits"])
    output = Path(spec["output"])
    case, context = build_context(spec, output)
    base, domain = make_domain(spec)
    result = optimize_budgeted(base, domain, config_for(spec["seed"]), case, context, budget,
        combined=spec["arm"] == "combined", departure_end_s=spec["horizon_s"], **spec["policy"])
    write_json(output / "result.json", dict(spec=spec, **serializable(result),
        worker_wall_time_s=time.perf_counter() - started, production_enabled=False))


def rolling_worker(spec):
    started = time.perf_counter()
    output = Path(spec["output"])
    case, context = build_context(spec, output)
    system = context.settlement_system
    ids = storage_section_ids_from_limits(system.power_arm_limits)
    initial = tuple(StorageDeviceRuntimeState(s, system.capacity_kwh * .25 / len(ids)) for s in ids)
    states, history, rows, windows = initial, None, [], []
    for index in range(8):
        cycle_started = time.perf_counter()
        now = index * 3300
        base = ScheduleTemplate(3300, 3300, 2760, int(index < 4), int(index < 4), storage_preset_id=PRESET,
                                start_time_s=now)
        # 只扫描执行窗内相位，不用把空车推到下窗的方式伪造本窗新增服务成功。
        domain = [replace(base, heavy_empty_phase_s=phase) for phase in (2000, 2600, 2760, 3000)]
        config = replace(config_for(spec["seed"]), allowed_heavy_headways_s=(3300,), allowed_empty_headways_s=(3300,),
                         allowed_phases_s=(2000, 2600, 2760, 3000), allowed_holds_s=(0,), allowed_storage_align_shifts_s=(0,))
        active = replace(context, settlement_system=system.with_storage_runtime_states(states, preserve_target=False))
        budget = RecoveryWorkBudget(**spec["limits"])
        result = optimize_budgeted(base, domain, config, case, active, budget,
            combined=spec["arm"] == "combined", departure_end_s=now + 3299, current_time_s=now,
            history=history, **spec["policy"])
        chosen = result["selected"]
        display = chosen[0] if chosen else result["diagnostic_schedule"]
        decision = gate_rolling_execution_commit(display, chosen[2]["scenario_scores"] if chosen else [],
            current_time_s=now, execute_window_s=3300, candidate_feasible=chosen is not None,
            locked_heavy_departures_s=history.heavy_departures_s if history else (),
            locked_empty_departures_s=history.empty_departures_s if history else ())
        before = {s.storage_section_id: s.soc_kwh for s in states}
        history = decision.committed_execution_schedule
        settled = settle_schedule(history, context.heavy_cache, context.empty_cache,
            active.settlement_system, case.resource_model, from_time_s=now, until_time_s=now + 3300)
        windows.append(dict(from_time_s=now, until_time_s=now + 3300, **storage_summary(settled)))
        states = tuple(replace(s, soc_kwh=settled.final_soc_by_storage_kwh[s.storage_section_id]) for s in states)
        rows.append(dict(cycle=index, current_time_s=now, initial_soc_by_storage_kwh=before,
            committed_schedule=asdict(history), executable_heavy=decision.executable_heavy_departures_s,
            executable_empty=decision.executable_empty_departures_s, commit_status=decision.commit_status,
            **serializable(result), cycle_wall_time_s=time.perf_counter() - cycle_started))
        write_json(output / "checkpoint.json", dict(cycles=rows, windows=windows))
    whole = settle_schedule(history, context.heavy_cache, context.empty_cache,
        system.with_storage_runtime_states(initial, preserve_target=False), case.resource_model,
        from_time_s=0, until_time_s=26400)
    energy_fields = ("total_gen_kwh", "total_con_kwh", "grid_kwh", "wasted_kwh", "battery_charge_kwh", "battery_discharge_kwh")
    errors = {k: abs(sum(w[k] for w in windows) - getattr(whole, k)) for k in energy_fields}
    write_json(output / "result.json", dict(spec=spec, cycles=rows, windows=windows, whole=storage_summary(whole),
        whole_split_errors_kwh=errors, worker_wall_time_s=time.perf_counter() - started, production_enabled=False))


def run(args):
    output, data = args.output_dir.resolve(), args.data_dir.resolve()
    if (output / "manifest.json").exists():
        raise ValueError("使用新目录，禁止覆盖先前试验")
    provenance = capture_provenance(data)
    specs = []
    for profile, seeds in (("positive_discharge", (11, 23)), ("supply_limited", (11,))):
        for scale in (6, 8):
            for seed in seeds:
                for arm in ("baseline", "combined"):
                    name = f"{profile}_n{scale*2}_s{seed}_{arm}"
                    specs.append(dict(mode="static", scale=scale, profile=profile, seed=seed, arm=arm,
                        horizon_s=scale*3300, limits=LIMITS, policy=POLICY,
                        data_dir=str(data), output=str(output / name)))
    for arm in ("baseline", "combined"):
        specs.append(dict(mode="rolling", scale=1, profile="positive_discharge", seed=11, arm=arm,
            limits=LIMITS, policy=POLICY, data_dir=str(data), output=str(output / f"rolling_{arm}")))
    if args.pilot:
        specs = specs[:1]
    if args.pilot_rolling:
        specs = specs[-1:]
    write_json(output / "manifest.json", dict(specs=specs, provenance=provenance, serial=True,
        note="12次静态独立运行+两条8窗滚动轨迹；两臂各自均含相同修复和精确补解，不给任一组免费兜底；非全域最优性声明。"))
    rows = []
    for spec in specs:
        target = Path(spec["output"])
        write_json(target / "spec.json", spec)
        start = time.perf_counter()
        with (target / "stdout.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run([sys.executable, str(Path(__file__)), "--worker-spec", str(target / "spec.json")],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=5400 if spec["mode"] == "rolling" else 720)
        elapsed = time.perf_counter() - start
        if completed.returncode:
            raise RuntimeError(f"worker失败，请检查{target / 'stdout.log'}")
        result = json.loads((target / "result.json").read_text(encoding="utf-8"))
        rows.append(dict(spec=spec, e2e_wall_time_s=elapsed,
                         found_feasible=result.get("found_feasible"), selected_stage=result.get("selected_stage"),
                         budget=result.get("budget")))
        write_json(output / "progress.json", dict(rows=rows))
        print(f"{target.name}: feasible={result.get('found_feasible')} e2e={elapsed:.3f}s", flush=True)
    write_json(output / "summary.json", dict(rows=rows, provenance=verify_provenance(provenance, data), production_enabled=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=ROOT / "data/real_shuohuang")
    p.add_argument("--output-dir", type=Path, required=False)
    p.add_argument("--worker-spec", type=Path)
    p.add_argument("--pilot", action="store_true")
    p.add_argument("--pilot-rolling", action="store_true")
    args = p.parse_args()
    if args.worker_spec:
        spec = json.loads(args.worker_spec.read_text(encoding="utf-8"))
        {"static": static_worker, "rolling": rolling_worker}[spec["mode"]](spec)
    else:
        if args.output_dir is None:
            p.error("需要--output-dir")
        run(args)

if __name__ == "__main__":
    main()
