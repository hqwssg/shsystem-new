"""预算化滚动影子运行：只产生审计工件，绝不产生现场控制事件。

所有请求、服务身份和逐设备初始状态必须来自冻结输入；不补造正式数据。
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
import math
from pathlib import Path
import time

from budgeted_recovery_search import optimize_budgeted
from energy_settlement import StorageDeviceRuntimeState
from power_arm_electrical_limits import DynamicPowerArmLimit
from recovery_work_budget import RecoveryWorkBudget
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate, TemplateSearchConfig, gate_rolling_execution_commit
from run_dispatch_case import load_case_inputs, build_storage_eval_contexts, settle_schedule
from storage_presets import default_storage_preset_library
from database.snapshots import collect_file_records, snapshot_manifest

MAX_LIMITS = dict(full_limit=48, resource_limit=1800, candidate_limit=2048, wall_limit_s=60, solver_limit_s=10)
SHADOW_REASON = "experimental_shadow_only_no_dispatch"


def _fields(row, allowed, label):
    if not isinstance(row, dict) or set(row) - set(allowed):
        raise ValueError(f"{label}必须为只含批准字段的对象")


def _integer(v, label, low=0, high=1000000):
    if type(v) is not int or not low <= v <= high:
        raise ValueError(f"{label}必须为{low}至{high}的整数")
    return v


def _id(v):
    if not isinstance(v, str) or len(v) != 4 or v[0] not in "HE" or not v[1:].isdigit() or int(v[1:]) == 0:
        raise ValueError("服务ID必须为H001/E001格式")
    return v


def load_shadow_request(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("影子请求文件过大")
    p = json.loads(raw)
    _fields(p, {"schema_version", "mode", "execute_window_s", "storage_preset_id", "initial_storage_device_states", "budget", "cycles"}, "影子请求")
    if p.get("schema_version") != "1.0" or p.get("mode") != "shadow_only":
        raise ValueError("影子请求必须显式声明schema_version=1.0及mode=shadow_only")
    step = _integer(p.get("execute_window_s"), "execute_window_s", 600, 7200)
    if step % 10:
        raise ValueError("执行窗须对齐10秒结算桶")
    states = p.get("initial_storage_device_states")
    if not isinstance(states, list) or not states:
        raise ValueError("必须显式提供全部设备的初始状态，不能默认初始化SOC")
    for state in states:
        _fields(state, {"storage_section_id", "soc_kwh", "available", "max_charge_power_kw", "max_discharge_power_kw"}, "储能状态")
        StorageDeviceRuntimeState(**state)
    supplied = p.get("budget", {})
    _fields(supplied, MAX_LIMITS, "预算")
    limits = {**MAX_LIMITS, **supplied}
    for name, v in limits.items():
        if name.endswith("limit_s"):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= MAX_LIMITS[name]:
                raise ValueError(f"{name}超出实验限额")
        else:
            _integer(v, name, 1, MAX_LIMITS[name])
    cycles = p.get("cycles")
    if not isinstance(cycles, list) or not 2 <= len(cycles) <= 16:
        raise ValueError("影子联调要求2至16个连续窗口")
    registered, pending = set(), {}
    source_ids = set()
    event_payloads = {}
    for i, cycle in enumerate(cycles):
        _fields(cycle, {"cycle_index", "current_time_s", "source_record_ids", "new_services", "cancelled_train_ids", "power_arm_limits", "storage_device_states"}, "窗口")
        if type(cycle.get("cycle_index")) is not int or cycle["cycle_index"] != i or type(cycle.get("current_time_s")) is not int or cycle["current_time_s"] != i*step:
            raise ValueError("影子窗口必须从0开始连续且严格对齐")
        refs = cycle.get("source_record_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or not s.strip() or s in source_ids for s in refs) or len(set(refs)) != len(refs):
            raise ValueError("窗口须提供非空、唯一的来源记录ID")
        source_ids.update(refs)
        new = cycle.get("new_services", [])
        cancel = cycle.get("cancelled_train_ids", [])
        if not isinstance(new, list) or not isinstance(cancel, list) or len(set(cancel)) != len(cancel):
            raise ValueError("服务/取消请求必须为数组且取消ID不得重复")
        for service in new:
            _fields(service, {"train_id", "train_type", "departure_s"}, "新增服务")
            tid = _id(service.get("train_id"))
            if service.get("train_type") != ("Heavy" if tid[0] == "H" else "Empty") or tid in registered:
                raise ValueError("服务类型不符或服务身份已使用（取消后也不能复用）")
            _integer(service.get("departure_s"), "departure_s", i*step, len(cycles)*step-1)
            registered.add(tid); pending[tid] = service
        for tid in cancel:
            _id(tid)
            if tid not in pending or pending[tid]["departure_s"] < i*step:
                raise ValueError("只能取消尚未执行的待办服务，不得取消历史或未知ID")
            if any(s["train_id"] == tid for s in new):
                raise ValueError("同一窗口不能同时新增和取消同一服务")
            pending.pop(tid)
        active = [s for s in pending.values() if i*step <= s["departure_s"] < (i+1)*step]
        if len(active) > 16:
            raise ValueError("单窗最多16列，扩大规模须另行验证")
        for prefix in "HE":
            times = [s["departure_s"] for s in active if s["train_id"].startswith(prefix)]
            if len(set(times)) != len(times):
                raise ValueError("同类服务请求发车时刻不能重复")
        for s in active:
            pending.pop(s["train_id"])
        limits_rows = cycle.get("power_arm_limits", [])
        if not isinstance(limits_rows, list):
            raise ValueError("power_arm_limits必须为数组")
        for event in limits_rows:
            _fields(event, {"event_id", "power_arm_id", "start_time_s", "end_time_s", "max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw", "reason"}, "供电观测")
            DynamicPowerArmLimit(**event)
            if event["event_id"] in event_payloads and event_payloads[event["event_id"]] != event:
                raise ValueError("同一供电事件ID不能覆盖为不同内容")
            event_payloads[event["event_id"]] = event
        if "storage_device_states" in cycle:
            if not isinstance(cycle["storage_device_states"], list) or not cycle["storage_device_states"]:
                raise ValueError("设备观测必须是非空数组")
            for state in cycle["storage_device_states"]:
                _fields(state, {"storage_section_id", "soc_kwh", "available", "max_charge_power_kw", "max_discharge_power_kw"}, "设备观测")
                StorageDeviceRuntimeState(**state)
    return p, limits, sha256(raw).hexdigest()


def _write(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run_shadow(*, data_dir, request_path, output_dir, experimental_budgeted_shadow=False,
               population_size=12, generations=10, seed=11, job_wall_limit_s=240):
    if experimental_budgeted_shadow is not True:
        raise ValueError("必须显式开启预算化影子实验开关")
    _integer(population_size, "population_size", 2, 24)
    _integer(generations, "generations", 1, 12)
    _integer(seed, "seed", 0)
    if isinstance(job_wall_limit_s, bool) or not isinstance(job_wall_limit_s, (int, float)) or not math.isfinite(job_wall_limit_s) or not 0 < job_wall_limit_s <= 870:
        raise ValueError("影子任务总墙钟预算无效")
    started = time.perf_counter()
    deadline = started + job_wall_limit_s
    p, limits, request_hash = load_shadow_request(request_path)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("影子运行须使用新输出目录")
    output.mkdir(parents=True, exist_ok=True)
    case = load_case_inputs(Path(data_dir), output / "input_check")
    input_hash = snapshot_manifest(collect_file_records(Path(data_dir)))["snapshot_sha256"]
    preset = p.get("storage_preset_id", "virtual_two_section_base")
    library = {s.scenario_id: s for s in default_storage_preset_library(case.battery)}
    if preset not in library:
        raise ValueError("未知储能配置")
    context = build_storage_eval_contexts(case_inputs=case, trains=case.trains, base_battery=case.battery,
        preset_ids=[preset], library_by_id=library, settlement_step_s=10, initial_soc_kwh=0.,
        target_final_soc_kwh=0., final_soc_tolerance_kwh=0., final_soc_penalty_per_kwh=.05,
        wasted_energy_penalty_per_kwh=.05, energy_scenario="storage_no_direct")[preset]
    system = context.settlement_system
    states = tuple(StorageDeviceRuntimeState(**s) for s in p["initial_storage_device_states"])
    system.with_storage_runtime_states(states, preserve_target=False).settle([])
    history, pending, power_events, rows = None, {}, {}, []
    delta = p["execute_window_s"]
    for cycle in p["cycles"]:
        cycle_started = time.perf_counter()
        now = cycle["current_time_s"]
        for s in cycle.get("new_services", []):
            pending[s["train_id"]] = s
        for tid in cycle.get("cancelled_train_ids", []):
            pending.pop(tid)
        due = sorted((s for s in pending.values() if now <= s["departure_s"] < now+delta), key=lambda s:(s["departure_s"],s["train_id"]))
        h, e = ([s for s in due if s["train_type"] == kind] for kind in ("Heavy", "Empty"))
        phase = e[0]["departure_s"] - now if e else 0
        base = ScheduleTemplate(3300, 3300, phase, len(h), len(e), start_time_s=now, storage_preset_id=preset,
            heavy_departure_adjustments_s=tuple(s["departure_s"]-now-i*3300 for i,s in enumerate(h)),
            empty_departure_adjustments_s=tuple(s["departure_s"]-now-phase-i*3300 for i,s in enumerate(e)))
        phases = tuple(sorted({phase, *[v for v in (2000,2600,2760,3000) if v < delta]}))
        domain = [replace(base, heavy_empty_phase_s=v) for v in phases]
        config = TemplateSearchConfig(population_size=population_size, generations=generations, elite_count=min(4,population_size),
            min_headway_s=3300, max_headway_s=3300, max_phase_s=max(phases), max_hold_s=0, max_storage_align_shift_s=0,
            allowed_heavy_headways_s=(3300,), allowed_empty_headways_s=(3300,), allowed_phases_s=phases,
            allowed_holds_s=(0,), allowed_storage_align_shifts_s=(0,), enable_storage_preset_search=False,
            storage_preset_ids=(preset,), seed=seed)
        previous_soc = {s.storage_section_id:s.soc_kwh for s in states}
        if "storage_device_states" in cycle:
            states = tuple(StorageDeviceRuntimeState(**s) for s in cycle["storage_device_states"])
        for event in cycle.get("power_arm_limits", []):
            power_events[event["event_id"]] = DynamicPowerArmLimit(**event)
        active_events = tuple(v for v in power_events.values() if v.end_time_s > now)
        if any(v.power_arm_id not in system.power_arm_limits for v in active_events):
            raise ValueError("供电观测引用未知供电臂")
        active_system = system.with_storage_runtime_states(states, preserve_target=False)
        if active_events:
            active_system = active_system.with_dynamic_power_arm_limits(active_events)
        active_system.settle([])
        active_context = replace(context, settlement_system=active_system)
        before = asdict(history) if history else None
        remaining = deadline-time.perf_counter()
        if remaining > .05:
            budget = RecoveryWorkBudget(**{**limits, "wall_limit_s":min(limits["wall_limit_s"], remaining)})
            result = optimize_budgeted(base, domain, config, case, active_context, budget, combined=True,
                departure_end_s=now+delta-1, current_time_s=now, history=history,
                new_train_ids=(tuple(s["train_id"] for s in h),tuple(s["train_id"] for s in e)))
            chosen = result.pop("selected")
            display = chosen[0] if chosen else result.pop("diagnostic_schedule")
            result.pop("diagnostic_schedule", None)
            decision = gate_rolling_execution_commit(display, chosen[2]["scenario_scores"] if chosen else [],
                current_time_s=now, execute_window_s=delta, candidate_feasible=chosen is not None,
                locked_heavy_departures_s=history.heavy_departures_s if history else (),
                locked_empty_departures_s=history.empty_departures_s if history else ())
            history = decision.committed_execution_schedule
            status = "shadow_feasible" if chosen else "shadow_withheld"
        else:
            result, chosen, status = {"budget":None, "stages":[{"stop_reason":"job_wall_time_budget"}]}, None, "shadow_not_evaluated_budget"
            history = history or GeneratedSchedule([], [], base)
        settled = settle_schedule(history, context.heavy_cache, context.empty_cache, active_system,
            case.resource_model, from_time_s=now, until_time_s=now+delta)
        initial_soc = {s.storage_section_id:s.soc_kwh for s in states}
        final_soc = settled.final_soc_by_storage_kwh
        states = tuple(replace(s, soc_kwh=final_soc[s.storage_section_id]) for s in states)
        for s in due:
            pending.pop(s["train_id"])
        fingerprint_payload = dict(request_sha256=request_hash, cycle=cycle, prior_shadow_history=before,
                                   input_sha256=input_hash, storage_device_states=[asdict(s) for s in active_system.storage_runtime_states],
                                   limits=limits, seed=seed, population_size=population_size, generations=generations)
        fingerprint = sha256(json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        rows.append(dict(cycle_index=cycle["cycle_index"], current_time_s=now, source_record_ids=cycle["source_record_ids"],
            request_fingerprint=fingerprint, shadow_status=status, shadow_only=True, execution_allowed=False,
            cancelled_train_ids=cycle.get("cancelled_train_ids", []), requested_train_ids=[s["train_id"] for s in due],
            pending_train_ids=sorted(pending), shadow_history_before=before, shadow_committed_schedule=asdict(history),
            shadow_selected_score=asdict(chosen[1]) if chosen else None,
            shadow_selected_schedule=asdict(chosen[0]) if chosen else None,
            shadow_selected_scenario_scores=chosen[2]["scenario_scores"] if chosen else [],
            carried_soc_by_storage_kwh=previous_soc, initial_soc_by_storage_kwh=initial_soc,
            observed_soc_reset="storage_device_states" in cycle, executed_final_soc_by_storage_kwh=final_soc,
            storage_device_states=[asdict(s) for s in active_system.storage_runtime_states],
            active_power_arm_limits=[asdict(e) for e in active_events],
            executed_charge_by_storage_kwh=settled.battery_charge_by_storage_kwh,
            executed_discharge_by_storage_kwh=settled.battery_discharge_by_storage_kwh,
            simulated_grid_kwh=settled.grid_kwh, cycle_wall_time_s=time.perf_counter()-cycle_started, **result))
        _write(output / "shadow_cycles.json", rows)
    summary = dict(schema_version="1.0", mode="budgeted_shadow", shadow_only=True,
        experimental_budgeted_shadow=True, execution_allowed=False, dispatch_allowed=False,
        production_accepted=False, formal_conclusions_allowed=False, request_sha256=request_hash,
        input_sha256=input_hash,
        storage_context_data_status=context.data_status,
        static_storage_devices=[asdict(s) for s in system.storage_device_parameters],
        cycle_count=len(rows), shadow_feasible_cycles=sum(r["shadow_status"]=="shadow_feasible" for r in rows),
        job_wall_limit_s=job_wall_limit_s, wall_time_s=time.perf_counter()-started,
        optimization_decision=dict(action="keep_baseline", reason=SHADOW_REASON, execution_allowed=False, shadow_only=True),
        note="仅影子仿真；shadow_committed_schedule不是现场承诺，执行窗结算也不是实测电表结果。")
    _write(output / "shadow_summary.json", summary)
    validate_shadow_output(output)
    return summary


def validate_shadow_output(output_dir):
    root = Path(output_dir)
    p = json.loads((root / "shadow_summary.json").read_text(encoding="utf-8"))
    if p.get("mode") != "budgeted_shadow" or p.get("shadow_only") is not True or p.get("experimental_budgeted_shadow") is not True or p.get("execution_allowed") is not False or p.get("dispatch_allowed") is not False:
        raise ValueError("影子结果缺少强制的禁止执行标志")
    if p.get("production_accepted") is not False or p.get("formal_conclusions_allowed") is not False:
        raise ValueError("影子结果不能发布正式工程或生产验收结论")
    decision = p.get("optimization_decision", {})
    if decision.get("action") != "keep_baseline" or decision.get("reason") != SHADOW_REASON or decision.get("execution_allowed") is not False or decision.get("selected_candidate_id") is not None:
        raise ValueError("影子结果不能生成普通优化或可下发决策")
    if any((root / name).exists() for name in ("rolling_cycles.csv", "ranked_candidates.csv", "summary.json", "optimizer_summary.json", "benchmark_summary.json")):
        raise ValueError("影子结果不能混入普通调度结果文件")
    rows = json.loads((root / "shadow_cycles.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != p.get("cycle_count") or not rows:
        raise ValueError("影子窗口工件不完整")
    if any(r.get("shadow_only") is not True or r.get("execution_allowed") is not False for r in rows):
        raise ValueError("影子窗口不能允许现场执行")
    return p
