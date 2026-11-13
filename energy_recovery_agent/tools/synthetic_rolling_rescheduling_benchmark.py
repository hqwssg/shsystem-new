"""使用当前规划数据执行合成状态驱动的多轮滚动重调度实验。"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
import argparse
import csv
import json
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from matplotlib_chinese_font import configure_matplotlib_chinese_font
from energy_settlement import StorageDeviceRuntimeState, storage_section_ids_from_limits
from historical_disturbance_replay import HistoricalDisturbanceReplay
from historical_disturbance_replay import load_historical_disturbance_replay
from rolling_optimizer import (
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    RollingCycleObservation,
    RollingOptimizer,
    RollingSafetyPolicy,
    RollingWindowState,
    ScheduleTemplate,
    TemplateSearchConfig,
    default_scenarios,
    run_mpc_cycles,
)
from recovery_conflict_analysis import extract_recovery_conflict_analysis
from run_dispatch_case import (
    build_storage_eval_contexts,
    load_case_inputs,
    settle_schedule,
)
from storage_presets import default_storage_preset_library
from operating_conditions import TemporarySpeedRestriction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "real_shuohuang"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E15_synthetic_rolling_rescheduling"
DEFAULT_PRESET_ID = "virtual_two_section_base"
DEFAULT_DELAYS = ((0, 0), (180, 0), (60, 240), (0, 0))


# Configure explicitly in the module that creates rolling_state_timeline.png.
# This avoids relying on import side effects from the settlement modules.
configure_matplotlib_chinese_font()


def _write_csv(
    path: Path,
    rows: Sequence[dict[str, Any]],
    fieldnames: Sequence[str] | None = None,
) -> None:
    """写出带 BOM 的 CSV，方便直接用表格软件核验。"""

    resolved_fieldnames = list(
        fieldnames or dict.fromkeys(key for row in rows for key in row)
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _csv_value(value: Any) -> Any:
    """将嵌套值转换为稳定 JSON 文本，避免 CSV 中出现 Python 表示法。"""

    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _write_chart(rows: Sequence[dict[str, Any]], output_dir: Path) -> str:
    """绘制每轮晚点观测与 SOC 连续状态。"""

    selected_font = configure_matplotlib_chinese_font()
    if selected_font is None:
        raise RuntimeError(
            "Matplotlib 未找到覆盖中文字形的字体；请安装 fonts-noto-cjk "
            "并删除 Matplotlib 字体缓存后重试。"
        )
    cycles = [int(row["cycle_index"]) + 1 for row in rows]
    fig, left = plt.subplots(figsize=(9.5, 4.8))
    left.plot(cycles, [row["observed_heavy_delay_s"] for row in rows], marker="o", label="重车晚点")
    left.plot(cycles, [row["observed_empty_delay_s"] for row in rows], marker="s", label="空车晚点")
    left.set_xlabel("滚动轮次")
    left.set_ylabel("观测晚点（秒）")
    left.set_xticks(cycles)
    left.grid(alpha=0.25)
    right = left.twinx()
    right.plot(cycles, [row["initial_soc_kwh"] for row in rows], color="#2E8B57", marker="^", label="轮次初始SOC")
    right.plot(cycles, [row["executed_final_soc_kwh"] for row in rows], color="#7A3E9D", marker="v", linestyle="--", label="执行后SOC")
    right.set_ylabel("储能 SOC（kWh）")
    handles_left, labels_left = left.get_legend_handles_labels()
    handles_right, labels_right = right.get_legend_handles_labels()
    left.legend(handles_left + handles_right, labels_left + labels_right, loc="best")
    left.set_title("状态驱动的多轮滚动重调度")
    fig.tight_layout()
    path = output_dir / "rolling_state_timeline.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return str(path)


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    """生成实验目的、结果和适用边界说明。"""

    if summary["robust_infeasible_cycle_count"]:
        fallback_conclusion = (
            f"- 压力场景及恢复轮共出现 `{summary['robust_infeasible_cycle_count']}` 次回退，"
            f"提取到的核心场景冲突实例数为 `{summary['infeasible_extracted_conflict_counts']}`；"
            "不可行结果及其锁定边界已如实保留。"
        )
    else:
        fallback_conclusion = (
            "- 压力场景及恢复轮均未发生回退，未产生需要提取的核心场景冲突；"
            "当前合成扰动序列下各轮均通过完整稳健评价。"
        )

    replay_lines = []
    replay_manifest = summary.get("disturbance_replay")
    if isinstance(replay_manifest, dict):
        replay_lines = [
            f"- 回放编号为 `{replay_manifest['replay_code']}`，输入SHA-256为 `{replay_manifest['source_sha256']}`。",
            f"- 共读取 `{replay_manifest['event_count']}` 个事件，直接应用 `{replay_manifest['applied_event_count']}` 个，阻断 `{replay_manifest['blocking_event_count']}` 个。",
            f"- 直接应用的临时限速为 `{[item['name'] for item in summary['applied_temporary_speed_restrictions']]}`；逐车晚点和设备状态见逐轮结果文件。",
        ]

    lines = [
        (
            "# 历史扰动回放与多轮滚动重调度报告"
            if summary["input_mode"] == "historical_disturbance_replay"
            else "# E15 合成状态驱动的多轮滚动重调度测试"
        ),
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "## 结论",
        "",
        f"- 已连续执行 `{summary['cycle_count']}` 个滚动周期，综合验收结果为 `{summary['all_gates_passed']}`。",
        f"- 输入模式为 `{summary['input_mode']}`，状态序列为 `{summary['delay_sequence']}`。",
        *replay_lines,
        "- 每轮只提交执行窗口内的发车；已提交发车、储能区停车策略和储能预设在后续轮次保持锁定。",
        "- 本轮提交和执行期能量结算使用叠加已观测晚点后的实际运行图；名义计划时刻仅保留为优化基准。",
        f"- 提交状态统计为 `{summary['commit_status_counts']}`；生产默认扣留核心稳健不可行轮的新增决策，本次扣留 `{summary['withheld_cycle_count']}` 轮。",
        f"- 安全状态统计为 `{summary['safety_state_counts']}`；每轮最多自动重试 `{summary['safety_policy']['max_retries_per_cycle']}` 次。",
        "- 已执行时间片单独结算，所得终点 SOC 作为下一轮起点 SOC；预测评价只使用当前时刻之后的功率，不重复结算历史。",
        f"- 核心稳健可行轮次为 `{summary['robust_feasible_cycle_count']}/{summary['cycle_count']}`；该指标反映本次回放输入下的算法行为，不是正式线路容量结论。",
        fallback_conclusion,
        f"- 共形成 `{summary['total_conflict_chain_count']}` 条逐轮冲突链：完全可调 `{summary['total_repairable_chain_count']}` 条、受锁定历史部分阻断 `{summary['total_partially_blocked_chain_count']}` 条、完全阻断 `{summary['total_blocked_chain_count']}` 条。",
        f"- 第二阶段恢复修复触发 `{summary['recovery_repair_triggered_cycle_count']}` 轮，实际采用 `{summary['recovery_repair_adopted_cycle_count']}` 轮；未采用结果不会写入后续执行状态。",
        f"- 第三阶段精确恢复实际调用求解器 `{summary['exact_recovery_solver_triggered_cycle_count']}` 轮，因锁定历史预判阻断 `{summary['exact_recovery_locked_blocked_cycle_count']}` 轮，实际采用 `{summary['exact_recovery_adopted_cycle_count']}` 轮。",
        f"- 最强扰动位于第 `{summary['strongest_disturbance_cycle_index'] + 1}` 轮，该轮核心稳健可行为 `{summary['strongest_disturbance_cycle_robust_feasible']}`；最终恢复轮为 `{summary['final_recovery_cycle_robust_feasible']}`。",
        "",
        "## 逐轮结果",
        "",
        "| 轮次 | 当前时刻 | 重/空晚点 | 核心稳健可行 | 提交状态 | 安全状态/尝试数 | 局部恢复/采用 | 精确恢复/采用 | 冲突实例/链 | 初始SOC | 执行后SOC |",
        "| ---: | ---: | ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in summary["cycles"]:
        lines.append(
            f"| {row['cycle_index'] + 1} | {row['current_time_s']} | "
            f"{row['observed_heavy_delay_s']}/{row['observed_empty_delay_s']} | "
            f"{row['robust_feasible']} | "
            f"{row['commit_status']} | "
            f"{row['safety_state']}/{row['safety_attempt_count']} | "
            f"{row['recovery_repair_status']}/{row['recovery_repair_adopted']} | "
            f"{row['exact_recovery_status']}/{row['exact_recovery_adopted']} | "
            f"{row['recovery_conflict_count']}/{row['recovery_conflict_chain_count']} | "
            f"{row['initial_soc_kwh']:.3f} | {row['executed_final_soc_kwh']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 自动门禁",
            "",
        ]
    )
    lines.extend(
        f"- `{name}`：`{passed}`" for name, passed in summary["gates"].items()
    )
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            "- `benchmark_summary.json`：配置、逐轮状态、决策、能量和门禁；",
            "- `rolling_cycles.csv`：逐轮可复核明细；",
            "- `recovery_conflicts.csv`：逐场景冲突实例及其直接可调整列车；",
            "- `recovery_conflict_chains.csv`：按共享列车连接的冲突链；",
            "- `recovery_adjustable_trains.csv`：全体列车的锁定/可调整分类及是否与冲突相关；",
            "- `recovery_adjustment_candidates.csv`：可调整列车优先级、所属冲突链和冲突负担；",
            "- `recovery_conflict_analysis.json`：供第二阶段修复器直接消费的完整结构；",
            "- `recovery_repair_decisions.csv`：第二阶段逐列车修复量及采用情况；",
            "- `recovery_repair_scenarios.csv`：修复前后各核心场景的残余冲突；",
            "- `recovery_repair_results.json`：完整修复状态、搜索次数和诊断；",
            "- `exact_recovery_decisions.csv`：第三阶段精确恢复的逐列车调整；",
            "- `exact_recovery_results.json`：精确求解状态、证明、锁定边界和完整评价结果；",
            "- `rolling_state_timeline.png`：晚点与 SOC 状态时间线；",
            *(
                [
                    "- `disturbance_replay_manifest.json`：输入来源、摘要和事件受理统计；",
                    "- `disturbance_replay_cycles.csv`：源记录、逐车事件、设备状态和逐轮决策关联表；",
                ]
                if summary["input_mode"] == "historical_disturbance_replay" else []
            ),
            "- `verification.json`：独立结果核验。",
            "",
            "## 结论边界",
            "",
            "结果效力由输入数据状态决定。使用规划、工程占位或合成数据时，本测试只验证滚动状态传递、锁定、重调度和能量账本链路，不发布现场节能率。",
        ]
    )
    report_name = (
        "HISTORICAL_DISTURBANCE_REPLAY_REPORT.md"
        if summary["input_mode"] == "historical_disturbance_replay"
        else "SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md"
    )
    (output_dir / report_name).write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run_benchmark(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    delays: Sequence[tuple[int, int]] = DEFAULT_DELAYS,
    horizon_s: int = 7200,
    execute_window_s: int = 3300,
    settlement_step_s: int = 10,
    storage_preset_id: str = DEFAULT_PRESET_ID,
    population_size: int = 2,
    generations: int = 1,
    seed: int = 20260907,
    enable_recovery: bool = True,
    allow_infeasible_commit_for_experiment: bool = False,
    safety_policy: RollingSafetyPolicy | None = None,
    initial_storage_device_states: Sequence[StorageDeviceRuntimeState] | None = None,
    disturbance_replay: HistoricalDisturbanceReplay | None = None,
) -> dict[str, Any]:
    """执行合成状态测试或经过严格校验的历史扰动回放。"""

    replay_cycles = disturbance_replay.cycles if disturbance_replay is not None else ()
    if disturbance_replay is not None:
        if disturbance_replay.blocking_events:
            details = "; ".join(
                f"{event.event_id}/{event.event_type}: {event.blocking_reason}"
                for event in disturbance_replay.blocking_events
            )
            raise ValueError(f"历史回放包含当前不能安全执行的事件：{details}")
        if initial_storage_device_states is not None:
            raise ValueError("历史扰动回放不能与独立的初始storage_devices参数同时使用。")
        execute_window_s = disturbance_replay.execute_window_s
        delays = tuple(
            (cycle.observed_heavy_delay_s, cycle.observed_empty_delay_s)
            for cycle in replay_cycles
        )

    if len(delays) < 2:
        raise ValueError("多轮滚动测试至少需要两个状态周期。")
    output_dir.mkdir(parents=True, exist_ok=True)
    case_inputs = load_case_inputs(data_dir, output_dir / "input_check")
    applied_speed_restrictions = []
    library_by_id = {
        preset.scenario_id: preset
        for preset in default_storage_preset_library(case_inputs.battery)
    }
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
    context = contexts[storage_preset_id]
    optimizer = RollingOptimizer(
        context.route,
        context.heavy_cache,
        context.empty_cache,
        context.settlement_system,
        resource_model=case_inputs.resource_model,
        storage_sections=context.storage_sections,
        storage_contexts=contexts,
        default_storage_preset_id=storage_preset_id,
    )
    base_template = ScheduleTemplate(
        heavy_headway_s=3300,
        empty_headway_s=2700,
        heavy_empty_phase_s=2300,
        heavy_count=1,
        empty_count=1,
        storage_preset_id=storage_preset_id,
    )
    search_config = TemplateSearchConfig(
        method="nsga2",
        population_size=population_size,
        generations=generations,
        elite_count=min(population_size, 2),
        min_headway_s=2700,
        max_headway_s=3300,
        max_phase_s=2600,
        max_hold_s=180,
        max_storage_align_shift_s=300,
        parallel_workers=1,
        seed=seed,
        enable_storage_preset_search=False,
        storage_preset_ids=(storage_preset_id,),
        allowed_heavy_headways_s=(3000, 3300),
        allowed_empty_headways_s=(2700, 3000),
        allowed_phases_s=(2300, 2600),
        allowed_holds_s=(0, 180),
        allowed_storage_align_shifts_s=(0, 300),
    )
    storage_ids = storage_section_ids_from_limits(
        context.settlement_system.power_arm_limits
    )
    if not storage_ids:
        raise ValueError("滚动基准要求至少配置一台储能设备。")
    storage_count = len(storage_ids)
    specifications = {
        item.storage_section_id: item
        for item in context.settlement_system.storage_device_parameters
    }
    initial_soc_per_storage = context.settlement_system.capacity_kwh * 0.25 / storage_count
    current_storage_states = (
        tuple(initial_storage_device_states)
        if initial_storage_device_states is not None
        else tuple(
            StorageDeviceRuntimeState(
                storage_section_id=storage_id,
                soc_kwh=(
                    specifications[storage_id].min_soc_kwh
                    + 0.25 * (
                        float(specifications[storage_id].max_soc_kwh)
                        - specifications[storage_id].min_soc_kwh
                    )
                    if storage_id in specifications else initial_soc_per_storage
                ),
                available=(
                    specifications[storage_id].available
                    if storage_id in specifications else True
                ),
                max_charge_power_kw=(
                    specifications[storage_id].max_charge_power_kw
                    if storage_id in specifications
                    else context.settlement_system.max_charge_power_kW / storage_count
                ),
                max_discharge_power_kw=(
                    specifications[storage_id].max_discharge_power_kw
                    if storage_id in specifications
                    else context.settlement_system.max_discharge_power_kW / storage_count
                ),
            )
            for storage_id in storage_ids
        )
    )
    # 在进入搜索前触发设备集合、容量和额定功率的完整校验。
    context.settlement_system.with_storage_runtime_states(current_storage_states).settle([])
    observation_rows: list[dict[str, Any]] = []
    execution_settlements: list[Any] = []
    settled_schedule_rows: list[dict[str, list[int]]] = []
    cycle_resource_models: list[Any] = []
    cycle_contexts: list[Any] = []
    known_added_trains: dict[str, Any] = {}
    known_resource_outages: dict[str, Any] = {}
    known_power_limits: dict[str, Any] = {}

    def settle_previous(state, previous_result) -> None:
        nonlocal current_storage_states
        if previous_result is None:
            return
        start_s = state.current_time_s - execute_window_s
        executed_system = context.settlement_system.with_storage_runtime_states(
            current_storage_states,
            target_final_soc_kwh=None,
            preserve_target=False,
        )
        committed_schedule = previous_result.committed_execution_schedule
        settlement = settle_schedule(
            committed_schedule,
            context.heavy_cache,
            context.empty_cache,
            executed_system,
            case_inputs.resource_model,
            from_time_s=start_s,
            until_time_s=state.current_time_s,
        )
        execution_settlements.append(settlement)
        settled_schedule_rows.append(
            {
                "heavy_departures_s": list(committed_schedule.heavy_departures_s),
                "empty_departures_s": list(committed_schedule.empty_departures_s),
            }
        )
        current_storage_states = tuple(
            StorageDeviceRuntimeState(
                storage_section_id=item.storage_section_id,
                soc_kwh=settlement.final_soc_by_storage_kwh[item.storage_section_id],
                available=item.available,
                max_charge_power_kw=item.max_charge_power_kw,
                max_discharge_power_kw=item.max_discharge_power_kw,
            )
            for item in current_storage_states
        )

    def observation_provider(cycle_index, state, previous_result):
        nonlocal current_storage_states, case_inputs, contexts, context
        settle_previous(state, previous_result)
        heavy_delay_s, empty_delay_s = delays[cycle_index]
        replay_cycle = replay_cycles[cycle_index] if replay_cycles else None
        replay_observation = replay_cycle.to_observation() if replay_cycle is not None else RollingCycleObservation()
        new_speed_restrictions = []
        if replay_cycle is not None:
            known_names = {item.name for item in applied_speed_restrictions}
            for event in replay_cycle.events:
                if event.event_type != "temporary_speed_restriction" or not event.applicable or event.entity_id in known_names:
                    continue
                payload = event.payload
                new_speed_restrictions.append(TemporarySpeedRestriction(
                    name=event.entity_id,
                    start_km=payload["start_km"],
                    end_km=payload["end_km"],
                    speed_limit_kmh=payload["speed_limit_kmh"],
                    start_time_s=payload["start_time_s"],
                    end_time_s=payload["end_time_s"],
                    reason=str(payload.get("reason") or "历史扰动回放"),
                    direction=str(payload.get("direction") or "both"),
                ))
        if new_speed_restrictions:
            applied_speed_restrictions.extend(new_speed_restrictions)
            conditions = replace(
                case_inputs.route.operating_conditions,
                speed_restrictions=[
                    *case_inputs.route.operating_conditions.speed_restrictions,
                    *new_speed_restrictions,
                ],
            )
            case_inputs = replace(
                case_inputs,
                route=replace(case_inputs.route, operating_conditions=conditions),
            )
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
            context = contexts[storage_preset_id]
            optimizer.route = context.route
            optimizer.heavy_cache = context.heavy_cache
            optimizer.empty_cache = context.empty_cache
            optimizer.settlement_system = context.settlement_system
            optimizer.storage_sections = tuple(context.storage_sections)
            optimizer.storage_contexts = dict(contexts)
        # 加车和有时效的设备约束属于持续状态：首次收到后保留到发车/失效。
        # 取消事件仅在当前快照执行一次，避免滚动模板下一周期复用序号时误取消另一列车。
        for addition in replay_observation.added_trains:
            known_added_trains[addition.train_id] = addition
        for outage in replay_observation.resource_unavailabilities:
            known_resource_outages[outage.event_id] = outage
        for limit in replay_observation.dynamic_power_arm_limits:
            known_power_limits[limit.event_id] = limit
        active_additions = tuple(
            item for item in known_added_trains.values()
            if item.departure_s >= state.current_time_s
        )
        active_outages = tuple(
            item for item in known_resource_outages.values()
            if item.end_time_s > state.current_time_s
        )
        active_power_limits = tuple(
            item for item in known_power_limits.values()
            if item.end_time_s > state.current_time_s
        )
        known_arm_ids = set(context.settlement_system.power_arm_limits)
        unknown_arms = sorted(item.power_arm_id for item in active_power_limits if item.power_arm_id not in known_arm_ids)
        if unknown_arms:
            raise ValueError(f"动态供电限值引用了未知供电臂：{unknown_arms}")
        station_count = len(case_inputs.resource_model.stations)
        unknown_resources = []
        for item in active_outages:
            if item.resource_type == "station_track":
                known = item.resource_id in {f"station:{index}" for index in range(station_count)}
            elif item.resource_type == "station_throat":
                known = item.resource_id in {f"throat:{index}" for index in range(station_count)}
            else:
                known = any(
                    item.resource_id == f"section:{index}"
                    or item.resource_id.startswith(f"section:{index}:")
                    for index in range(max(0, station_count - 1))
                )
            if not known:
                unknown_resources.append(item.resource_id)
        if unknown_resources:
            raise ValueError(f"资源封锁引用了未知资源：{sorted(unknown_resources)}")
        cycle_resource_models.append(replace(
            case_inputs.resource_model,
            unavailabilities=active_outages,
        ))
        cycle_contexts.append(context)
        if replay_cycle is not None and replay_cycle.storage_states_provided:
            current_storage_states = replay_cycle.storage_device_states
            # 设备覆盖、SOC边界与临时功率上限使用正式结算模型校验。
            context.settlement_system.with_storage_runtime_states(
                current_storage_states
            ).settle([])
        current_soc = sum(item.soc_kwh for item in current_storage_states)
        observation_rows.append(
            {
                "cycle_index": cycle_index,
                "current_time_s": state.current_time_s,
                "observed_heavy_delay_s": heavy_delay_s,
                "observed_empty_delay_s": empty_delay_s,
                "observed_train_delays_s": (
                    dict(replay_observation.observed_train_delays_s)
                    if replay_cycle is not None else {}
                ),
                "cancelled_train_ids": list(replay_observation.cancelled_train_ids),
                "added_train_ids": [item.train_id for item in active_additions],
                "resource_unavailability_ids": [item.event_id for item in active_outages],
                "dynamic_power_limit_ids": [item.event_id for item in active_power_limits],
                "disturbance_events": (
                    [asdict(event) for event in replay_cycle.events]
                    if replay_cycle is not None else []
                ),
                "initial_soc_kwh": current_soc,
                "initial_soc_by_storage_kwh": {
                    item.storage_section_id: item.soc_kwh
                    for item in current_storage_states
                },
                "storage_device_states": [asdict(item) for item in current_storage_states],
                "storage_states_provided": bool(
                    replay_cycle is not None and replay_cycle.storage_states_provided
                ),
                "source_record_ids": (
                    list(replay_cycle.source_record_ids) if replay_cycle is not None else []
                ),
                "observed_at": replay_cycle.observed_at if replay_cycle is not None else "",
                "locked_heavy_before": list(state.locked_heavy_departures_s),
                "locked_empty_before": list(state.locked_empty_departures_s),
            }
        )
        return RollingCycleObservation(
            observed_heavy_delay_s=heavy_delay_s,
            observed_empty_delay_s=empty_delay_s,
            observed_train_delays_s=(
                replay_observation.observed_train_delays_s
                if replay_cycle is not None else ()
            ),
            storage_device_states=current_storage_states,
            cancelled_train_ids=replay_observation.cancelled_train_ids,
            added_trains=active_additions,
            resource_unavailabilities=active_outages,
            dynamic_power_arm_limits=active_power_limits,
        )

    started = time.perf_counter()
    effective_safety_policy = safety_policy or RollingSafetyPolicy()
    results = run_mpc_cycles(
        optimizer,
        RollingWindowState(0, [], [], storage_device_states=current_storage_states),
        base_template,
        cycles=len(delays),
        horizon_s=horizon_s,
        execute_window_s=execute_window_s,
        search_config=search_config,
        enable_recovery=enable_recovery,
        allow_infeasible_commit_for_experiment=(
            allow_infeasible_commit_for_experiment
        ),
        safety_policy=effective_safety_policy,
        observation_provider=observation_provider,
    )
    final_state = RollingWindowState(
        current_time_s=len(delays) * execute_window_s,
        locked_heavy_departures_s=[],
        locked_empty_departures_s=[],
    )
    settle_previous(final_state, results[-1])
    wall_time_s = time.perf_counter() - started

    cycle_rows: list[dict[str, Any]] = []
    recovery_analyses = []
    recovery_repair_payloads = []
    exact_recovery_payloads = []
    for cycle_index, (observation, result, settlement, settled_schedule) in enumerate(zip(
        observation_rows, results, execution_settlements, settled_schedule_rows
    )):
        cycle_resource_model = cycle_resource_models[cycle_index]
        cycle_context = cycle_contexts[cycle_index]
        template = result.schedule.template
        normal_scenario = next(
            (
                row
                for row in result.selected_scenario_diagnostics
                if row.get("scenario") == "normal"
            ),
            {},
        )
        core_scenario_rows = [
            row
            for row in result.selected_scenario_diagnostics
            if bool(row.get("core_for_feasibility"))
        ]
        core_robust_feasible = bool(core_scenario_rows) and all(
            bool(row.get("feasible")) for row in core_scenario_rows
        )
        analysis = extract_recovery_conflict_analysis(
            result.schedule,
            default_scenarios(
                observation["observed_heavy_delay_s"],
                observation["observed_empty_delay_s"],
            ),
            cycle_resource_model,
            cycle_context.heavy_cache,
            cycle_context.empty_cache,
            current_time_s=observation["current_time_s"],
            locked_heavy_departures_s=observation["locked_heavy_before"],
            locked_empty_departures_s=observation["locked_empty_before"],
        )
        recovery_analyses.append(analysis)
        repair_payload = dict(result.search_diagnostics.get("recovery_repair") or {})
        repair_payload["cycle_index"] = observation["cycle_index"]
        recovery_repair_payloads.append(repair_payload)
        exact_payload = dict(result.search_diagnostics.get("exact_recovery") or {})
        exact_payload["cycle_index"] = observation["cycle_index"]
        exact_recovery_payloads.append(exact_payload)
        repair_decisions = list(repair_payload.get("decisions") or [])
        repair_final_scenarios = list(repair_payload.get("final_scenarios") or [])
        execution_state = dict(result.search_diagnostics.get("execution_state") or {})
        cycle_rows.append(
            {
                **observation,
                "selected_score_feasible": result.score.feasible,
                "robust_feasible": core_robust_feasible,
                "constraint_violation": result.score.constraint_violation,
                "headway_violation_s": result.score.headway_violation_s,
                "signal_violation_count": result.score.signal_violation_count,
                "resource_conflict_count": result.score.resource_conflict_count,
                "resource_overlap_violation_s": result.score.resource_overlap_violation_s,
                "flow_continuity_violation_count": result.score.flow_continuity_violation_count,
                "electrical_constraint_violation_kwh": result.score.electrical_constraint_violation_kwh,
                "traction_supply_excess_kwh": result.score.traction_supply_excess_kwh,
                "regen_absorption_excess_kwh": result.score.regen_absorption_excess_kwh,
                "candidate_count": result.candidate_count,
                "feasible_candidate_count": result.feasible_candidate_count,
                "selected_heavy_headway_s": template.heavy_headway_s,
                "selected_empty_headway_s": template.empty_headway_s,
                "selected_phase_s": template.heavy_empty_phase_s,
                "selected_hold_s": template.flex_zone_hold_s,
                "selected_storage_shift_s": template.storage_align_shift_s,
                "executable_heavy_count": len(result.executable_heavy_departures_s),
                "executable_empty_count": len(result.executable_empty_departures_s),
                "executable_heavy_departures_s": list(result.executable_heavy_departures_s),
                "executable_empty_departures_s": list(result.executable_empty_departures_s),
                "planned_heavy_departures_s": list(result.schedule.heavy_departures_s),
                "planned_empty_departures_s": list(result.schedule.empty_departures_s),
                "planned_heavy_train_ids": list(result.schedule.heavy_train_ids),
                "planned_empty_train_ids": list(result.schedule.empty_train_ids),
                "realized_heavy_departures_s": list(result.execution_schedule.heavy_departures_s),
                "realized_empty_departures_s": list(result.execution_schedule.empty_departures_s),
                "execution_scenario": execution_state.get("scenario"),
                "core_robust_feasible": result.core_robust_feasible,
                "commit_status": result.commit_status,
                "operational_intervention_required": (
                    result.operational_intervention_required
                ),
                "safety_state": result.safety_state,
                "safety_action": result.safety_action,
                "safety_attempt_count": result.safety_attempt_count,
                "safety_transition": dict(
                    result.search_diagnostics.get("safety_state_machine") or {}
                ),
                "committed_heavy_departures_s": list(
                    result.committed_execution_schedule.heavy_departures_s
                ),
                "committed_empty_departures_s": list(
                    result.committed_execution_schedule.empty_departures_s
                ),
                "settled_heavy_departures_s": settled_schedule["heavy_departures_s"],
                "settled_empty_departures_s": settled_schedule["empty_departures_s"],
                "forecast_grid_kwh": result.score.grid_kwh,
                "forecast_wasted_kwh": result.score.wasted_kwh,
                "forecast_final_soc_kwh": result.score.final_soc_kwh,
                "executed_grid_kwh": settlement.grid_kwh,
                "executed_wasted_kwh": settlement.wasted_kwh,
                "executed_charge_kwh": settlement.battery_charge_kwh,
                "executed_discharge_kwh": settlement.battery_discharge_kwh,
                "executed_charge_by_storage_kwh": (
                    settlement.battery_charge_by_storage_kwh
                ),
                "executed_discharge_by_storage_kwh": (
                    settlement.battery_discharge_by_storage_kwh
                ),
                "executed_wasted_by_storage_kwh": settlement.wasted_by_storage_kwh,
                "storage_parameters_by_id": settlement.storage_parameters_by_id,
                "executed_final_soc_kwh": settlement.final_soc_kwh,
                "executed_final_soc_by_storage_kwh": (
                    settlement.final_soc_by_storage_kwh
                ),
                "energy_from_time_s": result.search_diagnostics["rolling_energy_state"]["energy_from_time_s"],
                "evaluated_normal_heavy_delay_s": normal_scenario.get("heavy_delay_s"),
                "evaluated_normal_empty_delay_s": normal_scenario.get("empty_delay_s"),
                "recovery_conflict_count": len(analysis.conflicts),
                "recovery_conflict_chain_count": len(analysis.chains),
                "all_adjustable_train_count": len(analysis.all_adjustable_train_ids),
                "conflict_related_adjustable_train_count": len(
                    analysis.conflict_related_adjustable_train_ids
                ),
                "conflict_related_adjustable_train_ids": list(
                    analysis.conflict_related_adjustable_train_ids
                ),
                "locked_only_conflict_count": analysis.locked_only_conflict_count,
                "repairable_chain_count": analysis.repairable_chain_count,
                "partially_blocked_chain_count": analysis.partially_blocked_chain_count,
                "blocked_chain_count": analysis.blocked_chain_count,
                "recovery_repair_triggered": bool(repair_payload.get("triggered")),
                "recovery_repair_status": repair_payload.get("status", "not_applicable"),
                "recovery_repair_adopted": bool(repair_payload.get("adopted")),
                "recovery_repair_decision_count": len(repair_decisions),
                "recovery_repair_max_single_adjustment_s": int(
                    repair_payload.get("max_single_adjustment_s") or 0
                ),
                "recovery_repair_total_adjustment_s": int(
                    repair_payload.get("total_adjustment_s") or 0
                ),
                "recovery_repair_final_adjustable_conflict_count": sum(
                    int(item.get("adjustable_conflict_count") or 0)
                    for item in repair_final_scenarios
                ),
                "recovery_repair_final_locked_only_conflict_count": sum(
                    int(item.get("locked_only_conflict_count") or 0)
                    for item in repair_final_scenarios
                ),
                "exact_recovery_status": exact_payload.get("status", "not_applicable"),
                "exact_recovery_triggered": bool(
                    (exact_payload.get("diagnostics") or {}).get("triggered")
                    or exact_payload.get("triggered")
                ),
                "exact_recovery_adopted": bool(exact_payload.get("adopted")),
                "exact_recovery_decision_count": len(exact_payload.get("decisions") or []),
                "exact_recovery_operational_intervention_required": bool(
                    exact_payload.get("operational_intervention_required")
                ),
                "diagnostic": result.diagnostic,
            }
        )

    soc_continuity = all(
        bool(cycle_rows[index]["storage_states_provided"])
        or abs(float(cycle_rows[index]["initial_soc_kwh"]) - float(cycle_rows[index - 1]["executed_final_soc_kwh"])) <= 1e-6
        for index in range(1, len(cycle_rows))
    )
    storage_device_soc_continuity = all(
        bool(cycle_rows[index]["storage_states_provided"])
        or all(
            abs(
                float(cycle_rows[index]["initial_soc_by_storage_kwh"].get(storage_id, -1.0))
                - float(cycle_rows[index - 1]["executed_final_soc_by_storage_kwh"].get(storage_id, -2.0))
            ) <= 1e-6
            for storage_id in storage_ids
        )
        for index in range(1, len(cycle_rows))
    )
    locks_monotonic = all(
        set(cycle_rows[index - 1]["locked_heavy_before"]).issubset(cycle_rows[index]["locked_heavy_before"])
        and set(cycle_rows[index - 1]["locked_empty_before"]).issubset(cycle_rows[index]["locked_empty_before"])
        for index in range(1, len(cycle_rows))
    )
    realized_departures_committed = all(
        set(cycle_rows[index - 1]["executable_heavy_departures_s"]).issubset(
            cycle_rows[index]["locked_heavy_before"]
        )
        and set(cycle_rows[index - 1]["executable_empty_departures_s"]).issubset(
            cycle_rows[index]["locked_empty_before"]
        )
        for index in range(1, len(cycle_rows))
    )

    def expected_realized_times(row: dict[str, Any], train_type: str) -> list[int]:
        """按正常场景语义重建本轮应提交的实际发车序列。"""

        planned = row[f"planned_{train_type}_departures_s"]
        locked = set(row[f"locked_{train_type}_before"])
        delay = int(row[f"observed_{train_type}_delay_s"])
        current_time = int(row["current_time_s"])
        return [
            int(value) if int(value) in locked or int(value) < current_time else int(value) + delay
            for value in planned
        ]

    execution_state_matches_observation = all(
        row["realized_heavy_departures_s"] == expected_realized_times(row, "heavy")
        and row["realized_empty_departures_s"] == expected_realized_times(row, "empty")
        and row["execution_scenario"] == "normal"
        for row in cycle_rows
    )
    train_delay_events_reach_execution = all(
        dict(row["observed_train_delays_s"])
        == dict((results[index].search_diagnostics.get("execution_state") or {}).get("observed_train_delays_s") or {})
        for index, row in enumerate(cycle_rows)
    )
    dynamic_events_reach_execution = all(
        row["cancelled_train_ids"] == list((results[index].search_diagnostics.get("execution_state") or {}).get("cancelled_train_ids") or [])
        and row["added_train_ids"] == list((results[index].search_diagnostics.get("execution_state") or {}).get("added_train_ids") or [])
        and row["resource_unavailability_ids"] == list((results[index].search_diagnostics.get("execution_state") or {}).get("resource_unavailability_ids") or [])
        and row["dynamic_power_limit_ids"] == list((results[index].search_diagnostics.get("execution_state") or {}).get("dynamic_power_limit_ids") or [])
        for index, row in enumerate(cycle_rows)
    )
    strongest_cycle_index = max(
        range(len(cycle_rows)),
        key=lambda index: (
            int(cycle_rows[index]["observed_heavy_delay_s"])
            + int(cycle_rows[index]["observed_empty_delay_s"]),
            index,
        ),
    )
    strong_or_subsequent_recovery_feasible = any(
        bool(row["robust_feasible"])
        for row in cycle_rows[strongest_cycle_index:]
    )
    replay_storage_observations_applied = all(
        not replay_cycle.storage_states_provided
        or cycle_rows[index]["initial_soc_by_storage_kwh"] == {
            item.storage_section_id: item.soc_kwh
            for item in replay_cycle.storage_device_states
        }
        for index, replay_cycle in enumerate(replay_cycles)
    )
    expected_speed_restriction_count = sum(
        event.event_type == "temporary_speed_restriction" and event.applicable
        for cycle in replay_cycles for event in cycle.events
    )
    applied_speed_restriction_ids = {
        item.name for item in applied_speed_restrictions
    }
    optimizer_speed_restriction_ids = {
        item.name for item in context.route.operating_conditions.speed_restrictions
    }
    gates = {
        "all_cycles_completed": len(results) == len(delays),
        "observation_sequence_applied": [
            (row["observed_heavy_delay_s"], row["observed_empty_delay_s"])
            for row in cycle_rows
        ] == list(delays),
        "replay_storage_observations_applied": replay_storage_observations_applied,
        "temporary_speed_restrictions_applied": (
            len(applied_speed_restrictions) == expected_speed_restriction_count
            and applied_speed_restriction_ids.issubset(optimizer_speed_restriction_ids)
        ),
        "observations_reach_scenario_evaluation": all(
            row["evaluated_normal_heavy_delay_s"] == row["observed_heavy_delay_s"]
            and row["evaluated_normal_empty_delay_s"] == row["observed_empty_delay_s"]
            for row in cycle_rows
        ),
        "soc_continuity": soc_continuity,
        "storage_device_soc_continuity": storage_device_soc_continuity,
        "locked_history_monotonic": locks_monotonic,
        "realized_departures_committed_to_next_cycle": realized_departures_committed,
        "execution_state_matches_observed_delays": execution_state_matches_observation,
        "train_delay_events_reach_execution": train_delay_events_reach_execution,
        "dynamic_events_reach_execution": dynamic_events_reach_execution,
        "energy_window_moves_with_cycle": [row["energy_from_time_s"] for row in cycle_rows]
        == [index * execute_window_s for index in range(len(delays))],
        "feasible_cycles_have_executable_service": all(
            not row["robust_feasible"]
            or row["executable_heavy_count"] + row["executable_empty_count"] > 0
            for row in cycle_rows
        ),
        "infeasible_new_decisions_withheld_unless_experimental": all(
            row["robust_feasible"]
            or allow_infeasible_commit_for_experiment
            or row["commit_status"] == "withheld_infeasible"
            for row in cycle_rows
        ),
        "settlement_uses_committed_schedule": all(
            row["settled_heavy_departures_s"] == row["committed_heavy_departures_s"]
            and row["settled_empty_departures_s"] == row["committed_empty_departures_s"]
            for row in cycle_rows
        ),
        "safety_states_valid": all(
            row["safety_state"] in {
                "normal",
                "recovered_automatically",
                "recovered_after_observation",
                "waiting_for_observation",
                "manual_intervention_required",
                "experiment_only",
            }
            for row in cycle_rows
        ),
        "withheld_cycles_have_safe_action": all(
            row["commit_status"] != "withheld_infeasible"
            or (
                row["safety_state"] in {
                    "waiting_for_observation",
                    "manual_intervention_required",
                }
                and str(row["safety_action"]).startswith("hold_new_departures")
            )
            for row in cycle_rows
        ),
        "automatic_retry_is_bounded": all(
            1 <= int(row["safety_attempt_count"])
            <= 1 + effective_safety_policy.max_retries_per_cycle
            for row in cycle_rows
        ),
        "soc_within_physical_bounds": all(
            -1e-9 <= row["executed_final_soc_kwh"] <= context.settlement_system.capacity_kwh + 1e-9
            for row in cycle_rows
        ),
        "conflict_chains_fully_classified": all(
            chain.repairability in {
                "repairable_by_future_departure_adjustment",
                "partially_blocked_by_locked_history",
                "blocked_by_locked_history",
            }
            and set(chain.locked_train_ids).isdisjoint(chain.adjustable_train_ids)
            for analysis in recovery_analyses
            for chain in analysis.chains
        ),
        "infeasible_cycles_have_extracted_conflicts": all(
            row["robust_feasible"] or row["recovery_conflict_count"] > 0
            for row in cycle_rows
        ),
        "recovery_repair_preserves_locked_history": all(
            not payload.get("triggered")
            or bool(payload.get("locked_departures_preserved"))
            for payload in recovery_repair_payloads
        ),
        "adopted_recovery_has_explicit_decisions": all(
            not payload.get("adopted") or bool(payload.get("decisions"))
            for payload in recovery_repair_payloads
        ),
        "exact_recovery_preserves_locked_history": all(
            payload.get("status") in {"not_applicable", "disabled"}
            or bool(payload.get("locked_departures_preserved"))
            for payload in exact_recovery_payloads
        ),
        "adopted_exact_recovery_is_fully_verified": all(
            not payload.get("adopted")
            or (
                bool(payload.get("exact_resource_feasible"))
                and bool(payload.get("full_robust_feasible"))
                and bool(payload.get("decisions"))
            )
            for payload in exact_recovery_payloads
        ),
        "strong_disturbance_or_subsequent_cycle_recovers_robust_feasibility": (
            strong_or_subsequent_recovery_feasible
        ),
    }
    summary = {
        "schema_version": "1.8",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "completed",
        "data_status": (
            disturbance_replay.data_status
            if disturbance_replay is not None
            else "planning_and_engineering_placeholder_inputs"
        ),
        "input_mode": (
            "historical_disturbance_replay"
            if disturbance_replay is not None else "synthetic_delay_sequence"
        ),
        "disturbance_replay": (
            disturbance_replay.manifest() if disturbance_replay is not None else None
        ),
        "applied_temporary_speed_restrictions": [
            asdict(item) for item in applied_speed_restrictions
        ],
        "optimizer_speed_restriction_ids": sorted(optimizer_speed_restriction_ids),
        "cycle_count": len(delays),
        "delay_sequence": [list(item) for item in delays],
        "horizon_s": horizon_s,
        "execute_window_s": execute_window_s,
        "wall_time_s": wall_time_s,
        "storage_preset_id": storage_preset_id,
        "recovery_enabled": enable_recovery,
        "allow_infeasible_commit_for_experiment": (
            allow_infeasible_commit_for_experiment
        ),
        "safety_policy": asdict(effective_safety_policy),
        "search_config": asdict(search_config),
        "robust_feasible_cycle_count": sum(bool(row["robust_feasible"]) for row in cycle_rows),
        "robust_infeasible_cycle_count": sum(not bool(row["robust_feasible"]) for row in cycle_rows),
        "infeasible_extracted_conflict_counts": [
            row["recovery_conflict_count"]
            for row in cycle_rows
            if not row["robust_feasible"]
        ],
        "selected_template_change_count": sum(
            cycle_rows[index]["selected_phase_s"] != cycle_rows[index - 1]["selected_phase_s"]
            or cycle_rows[index]["selected_storage_shift_s"] != cycle_rows[index - 1]["selected_storage_shift_s"]
            for index in range(1, len(cycle_rows))
        ),
        "total_conflict_chain_count": sum(
            row["recovery_conflict_chain_count"] for row in cycle_rows
        ),
        "total_repairable_chain_count": sum(
            row["repairable_chain_count"] for row in cycle_rows
        ),
        "total_partially_blocked_chain_count": sum(
            row["partially_blocked_chain_count"] for row in cycle_rows
        ),
        "total_blocked_chain_count": sum(
            row["blocked_chain_count"] for row in cycle_rows
        ),
        "recovery_repair_triggered_cycle_count": sum(
            bool(row["recovery_repair_triggered"]) for row in cycle_rows
        ),
        "recovery_repair_adopted_cycle_count": sum(
            bool(row["recovery_repair_adopted"]) for row in cycle_rows
        ),
        "exact_recovery_solver_triggered_cycle_count": sum(
            bool((payload.get("diagnostics") or {}).get("triggered"))
            for payload in exact_recovery_payloads
        ),
        "exact_recovery_locked_blocked_cycle_count": sum(
            payload.get("status") == "blocked_by_locked_history"
            for payload in exact_recovery_payloads
        ),
        "exact_recovery_adopted_cycle_count": sum(
            bool(payload.get("adopted")) for payload in exact_recovery_payloads
        ),
        "commit_status_counts": {
            status: sum(row["commit_status"] == status for row in cycle_rows)
            for status in sorted({row["commit_status"] for row in cycle_rows})
        },
        "withheld_cycle_count": sum(
            row["commit_status"] == "withheld_infeasible" for row in cycle_rows
        ),
        "safety_state_counts": {
            state: sum(row["safety_state"] == state for row in cycle_rows)
            for state in sorted({row["safety_state"] for row in cycle_rows})
        },
        "strongest_disturbance_cycle_index": strongest_cycle_index,
        "strongest_disturbance_cycle_robust_feasible": bool(
            cycle_rows[strongest_cycle_index]["robust_feasible"]
        ),
        "final_recovery_cycle_robust_feasible": bool(cycle_rows[-1]["robust_feasible"]),
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "cycles": cycle_rows,
        "limitations": (
            [
                "历史回放可执行逐车晚点和动态事件，但取消后的运输任务补偿、加车车底来源及人工授权仍由平台和调度规章负责。",
                "方向专用临时限速仍未进入分方向轨迹模型，遇到时会在求解前阻断。",
                "线路、车辆和储能参数的数据状态仍需与回放数据状态分别核验。",
                "单次历史回放不替代多案例、多随机种子统计。",
            ]
            if disturbance_replay is not None
            else [
                "车辆、线路和储能参数仍包含规划或工程占位值。",
                "合成晚点用于软件链路验证，不代表现场扰动分布。",
                "正式数据到位后仍需执行历史扰动回放和多随机种子统计。",
            ]
        ),
    }
    conflict_rows = []
    chain_rows = []
    train_rows = []
    adjustment_candidate_rows = []
    repair_decision_rows = []
    repair_scenario_rows = []
    exact_decision_rows = []
    analysis_payload = []
    for cycle_index, analysis in enumerate(recovery_analyses):
        payload = analysis.to_dict()
        payload["cycle_index"] = cycle_index
        analysis_payload.append(payload)
        for conflict_index, conflict in enumerate(analysis.conflicts, start=1):
            conflict_id = f"CF{conflict_index:03d}"
            chain_id = next(
                chain.chain_id
                for chain in analysis.chains
                if conflict_id in chain.conflict_ids
            )
            conflict_rows.append(
                {
                    "cycle_index": cycle_index,
                    "conflict_id": conflict_id,
                    "chain_id": chain_id,
                    **asdict(conflict),
                }
            )
        chain_rows.extend(
            {"cycle_index": cycle_index, **asdict(chain)}
            for chain in analysis.chains
        )
        adjustment_candidate_rows.extend(
            {"cycle_index": cycle_index, **asdict(candidate)}
            for candidate in analysis.adjustment_candidates
        )
        related = set(analysis.conflict_related_adjustable_train_ids)
        train_rows.extend(
            {
                "cycle_index": cycle_index,
                **asdict(train),
                "conflict_related": train.train_id in related,
            }
            for train in analysis.trains
        )
    for payload in recovery_repair_payloads:
        cycle_index = int(payload["cycle_index"])
        for decision in payload.get("decisions") or []:
            repair_decision_rows.append(
                {
                    "cycle_index": cycle_index,
                    "status": payload.get("status"),
                    "adopted": bool(payload.get("adopted")),
                    **decision,
                }
            )
        for phase_name in ("baseline_scenarios", "final_scenarios"):
            for scenario in payload.get(phase_name) or []:
                repair_scenario_rows.append(
                    {
                        "cycle_index": cycle_index,
                        "phase": "before" if phase_name == "baseline_scenarios" else "after",
                        "status": payload.get("status"),
                        "adopted": bool(payload.get("adopted")),
                        **scenario,
                    }
                )
    for payload in exact_recovery_payloads:
        cycle_index = int(payload["cycle_index"])
        for decision in payload.get("decisions") or []:
            exact_decision_rows.append(
                {
                    "cycle_index": cycle_index,
                    "status": payload.get("status"),
                    "proof": payload.get("proof"),
                    "adopted": bool(payload.get("adopted")),
                    **decision,
                }
            )
    _write_csv(
        output_dir / "rolling_cycles.csv",
        [{key: _csv_value(value) for key, value in row.items()} for row in cycle_rows],
    )
    _write_csv(
        output_dir / "recovery_conflicts.csv",
        [{key: _csv_value(value) for key, value in row.items()} for row in conflict_rows],
    )
    _write_csv(
        output_dir / "recovery_conflict_chains.csv",
        [{key: _csv_value(value) for key, value in row.items()} for row in chain_rows],
    )
    _write_csv(
        output_dir / "recovery_adjustable_trains.csv",
        [{key: _csv_value(value) for key, value in row.items()} for row in train_rows],
    )
    _write_csv(
        output_dir / "recovery_adjustment_candidates.csv",
        [
            {key: _csv_value(value) for key, value in row.items()}
            for row in adjustment_candidate_rows
        ],
    )
    (output_dir / "recovery_conflict_analysis.json").write_text(
        json.dumps(analysis_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(output_dir / "recovery_repair_decisions.csv", repair_decision_rows)
    _write_csv(output_dir / "recovery_repair_scenarios.csv", repair_scenario_rows)
    (output_dir / "recovery_repair_results.json").write_text(
        json.dumps(recovery_repair_payloads, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(
        output_dir / "exact_recovery_decisions.csv",
        exact_decision_rows,
        fieldnames=(
            "cycle_index",
            "status",
            "proof",
            "adopted",
            "train_id",
            "train_type",
            "departure_index",
            "original_departure_s",
            "repaired_departure_s",
            "adjustment_s",
        ),
    )
    (output_dir / "exact_recovery_results.json").write_text(
        json.dumps(exact_recovery_payloads, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["chart"] = _write_chart(cycle_rows, output_dir)
    (output_dir / "benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if disturbance_replay is not None:
        (output_dir / "disturbance_replay_manifest.json").write_text(
            json.dumps(disturbance_replay.manifest(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_csv(
            output_dir / "disturbance_replay_cycles.csv",
            [
                {
                    "cycle_index": row["cycle_index"],
                    "current_time_s": row["current_time_s"],
                    "observed_at": row["observed_at"],
                    "source_record_ids": _csv_value(row["source_record_ids"]),
                    "observed_heavy_delay_s": row["observed_heavy_delay_s"],
                    "observed_empty_delay_s": row["observed_empty_delay_s"],
                    "observed_train_delays_s": _csv_value(row["observed_train_delays_s"]),
                    "cancelled_train_ids": _csv_value(row["cancelled_train_ids"]),
                    "added_train_ids": _csv_value(row["added_train_ids"]),
                    "resource_unavailability_ids": _csv_value(row["resource_unavailability_ids"]),
                    "dynamic_power_limit_ids": _csv_value(row["dynamic_power_limit_ids"]),
                    "disturbance_events": _csv_value(row["disturbance_events"]),
                    "storage_states_provided": row["storage_states_provided"],
                    "storage_device_states": _csv_value(row["storage_device_states"]),
                    "commit_status": row["commit_status"],
                    "safety_state": row["safety_state"],
                    "core_robust_feasible": row["core_robust_feasible"],
                }
                for row in cycle_rows
            ],
        )
    _write_report(summary, output_dir)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--population-size", type=int, default=2)
    parser.add_argument("--generations", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--disable-recovery", action="store_true")
    parser.add_argument("--disable-safety-retry", action="store_true")
    parser.add_argument("--max-safety-retries", type=int, default=1)
    parser.add_argument("--manual-after-withheld", type=int, default=2)
    parser.add_argument("--storage-devices-json", default="")
    parser.add_argument("--disturbance-history", type=Path, default=None)
    parser.add_argument("--disturbance-history-label", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    initial_storage_device_states = None
    if args.storage_devices_json:
        rows = json.loads(args.storage_devices_json)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("--storage-devices-json 必须是JSON对象数组。")
        initial_storage_device_states = tuple(
            StorageDeviceRuntimeState(**row) for row in rows
        )
    summary = run_benchmark(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        population_size=args.population_size,
        generations=args.generations,
        seed=args.seed,
        enable_recovery=not args.disable_recovery,
        safety_policy=RollingSafetyPolicy(
            enable_automatic_retry=not args.disable_safety_retry,
            max_retries_per_cycle=args.max_safety_retries,
            manual_after_consecutive_withheld=args.manual_after_withheld,
        ),
        initial_storage_device_states=initial_storage_device_states,
        disturbance_replay=(
            load_historical_disturbance_replay(
                args.disturbance_history,
                source_label=args.disturbance_history_label,
            )
            if args.disturbance_history is not None else None
        ),
    )
    print(json.dumps({
        "status": summary["status"],
        "all_gates_passed": summary["all_gates_passed"],
        "cycle_count": summary["cycle_count"],
        "wall_time_s": summary["wall_time_s"],
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
