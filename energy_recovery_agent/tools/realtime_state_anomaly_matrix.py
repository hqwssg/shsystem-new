"""执行实时状态异常注入、状态保护和滚动恢复测试矩阵。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import StorageDeviceRuntimeState
from realtime_state_guard import RealtimeGuardPolicy, RealtimeStateGuard
from rolling_optimizer import (
    GeneratedSchedule,
    RollingOptimizationResult,
    RollingSafetyController,
    RollingSafetyPolicy,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    gate_rolling_execution_commit,
)


SCHEMA_VERSION = "1.0"
BASE_TEMPLATE = ScheduleTemplate(900, 900, 300, 1, 1)


def _record(**overrides: Any) -> dict[str, Any]:
    """构造一条默认有效的正向列车状态。"""

    row = {
        "timestamp_s": 100,
        "train_id": "T001",
        "direction": "forward",
        "position_km": 10.0,
        "speed_mps": 12.0,
        "power_kW": 1800.0,
        "soc_kwh": 50.0,
    }
    row.update(overrides)
    return row


def _matrix_row(
    case_id: str,
    category: str,
    injection: str,
    expected: str,
    actual: str,
    passed: bool,
    evidence: Any,
) -> dict[str, Any]:
    """形成统一的测试矩阵行。"""

    return {
        "case_id": case_id,
        "category": category,
        "injection": injection,
        "expected_behavior": expected,
        "actual_behavior": actual,
        "passed": bool(passed),
        "evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
    }


def _isolated_ingest(row: dict[str, Any], *, received_at_s: int = 100) -> dict[str, Any]:
    guard = RealtimeStateGuard(capacity_kwh=100.0)
    return guard.ingest_batch([row], received_at_s=received_at_s)


def _field_and_freshness_cases() -> list[dict[str, Any]]:
    """覆盖字段、数值范围、消息新鲜度和时钟偏差。"""

    rows: list[dict[str, Any]] = []

    def check(
        case_id: str,
        injection: str,
        row: dict[str, Any],
        *,
        accepted: bool,
        error_contains: str = "",
        received_at_s: int = 100,
    ) -> None:
        result = _isolated_ingest(row, received_at_s=received_at_s)
        error_text = " | ".join(item["error"] for item in result["errors"])
        passed = (
            result["accepted_count"] == (1 if accepted else 0)
            and result["rejected_count"] == (0 if accepted else 1)
            and (not error_contains or error_contains in error_text)
        )
        rows.append(_matrix_row(
            case_id,
            "字段与时钟",
            injection,
            "接受并使用快照" if accepted else f"拒绝；错误包含“{error_contains}”",
            result["action"] if accepted else error_text,
            passed,
            result,
        ))

    check("RT-F01", "有效基线", _record(), accepted=True)
    missing = _record()
    del missing["power_kW"]
    check("RT-F02", "缺少必填字段", missing, accepted=False, error_contains="缺少实时字段")
    check("RT-F03", "布尔时间戳", _record(timestamp_s=True), accepted=False, error_contains="有限数值")
    check("RT-F04", "非有限功率", _record(power_kW=float("nan")), accepted=False, error_contains="有限数值")
    check("RT-F05", "负时间戳", _record(timestamp_s=-1), accepted=False, error_contains="非负整数")
    check("RT-F06", "小数时间戳", _record(timestamp_s=99.5), accepted=False, error_contains="非负整数")
    check("RT-F07", "空列车ID", _record(train_id="  "), accepted=False, error_contains="不能为空")
    check("RT-F08", "非法方向", _record(direction="sideways"), accepted=False, error_contains="direction")
    check("RT-F09", "负位置", _record(position_km=-0.1), accepted=False, error_contains="不能为负数")
    check("RT-F10", "负速度", _record(speed_mps=-0.1), accepted=False, error_contains="不能为负数")
    check("RT-F11", "负SOC", _record(soc_kwh=-0.1), accepted=False, error_contains="不能为负数")
    check("RT-F12", "SOC超过容量", _record(soc_kwh=100.1), accepted=False, error_contains="容量上限")
    check("RT-C01", "新鲜度边界", _record(timestamp_s=70), accepted=True, received_at_s=100)
    check("RT-C02", "过期消息", _record(timestamp_s=69), accepted=False, error_contains="最大新鲜度", received_at_s=100)
    check("RT-C03", "未来偏差边界", _record(timestamp_s=105), accepted=True, received_at_s=100)
    check("RT-C04", "未来时钟漂移", _record(timestamp_s=106), accepted=False, error_contains="未来时钟偏差", received_at_s=100)
    return rows


def _sequence_and_outage_cases() -> list[dict[str, Any]]:
    """覆盖重复、乱序、位置异常、坏消息隔离、断流和恢复。"""

    rows: list[dict[str, Any]] = []
    policy = RealtimeGuardPolicy(max_staleness_s=30, max_future_skew_s=5, outage_timeout_s=30)
    guard = RealtimeStateGuard(policy, capacity_kwh=100.0)
    baseline = _record()
    guard.ingest_batch([baseline], received_at_s=100)

    checks = (
        ("RT-S01", "完全重复消息", dict(baseline), 100, "重复消息"),
        ("RT-S02", "同车消息乱序", _record(timestamp_s=99, position_km=9.9), 100, "消息乱序"),
        ("RT-S03", "正向位置倒退", _record(timestamp_s=110, position_km=9.9), 110, "位置倒退"),
        ("RT-S04", "列车方向突变", _record(timestamp_s=110, direction="reverse"), 110, "方向发生变化"),
    )
    for case_id, injection, row, received_at, expected_error in checks:
        before = guard.cursor_snapshot()
        result = guard.ingest_batch([row], received_at_s=received_at)
        cursor_preserved = result["cursor"] == before
        error_text = " | ".join(item["error"] for item in result["errors"])
        rows.append(_matrix_row(
            case_id,
            "顺序与位置",
            injection,
            "拒绝且不推进可信游标",
            error_text,
            result["rejected_count"] == 1 and cursor_preserved and expected_error in error_text,
            {"cursor_before": before, "result": result},
        ))

    recovered = guard.ingest_batch([_record(timestamp_s=110, position_km=11.0)], received_at_s=110)
    rows.append(_matrix_row(
        "RT-S05",
        "顺序与位置",
        "多条坏消息后的有效消息",
        "接受有效消息，游标从100推进到110",
        recovered["state"],
        recovered["accepted_count"] == 1
        and recovered["cursor"]["T001"]["timestamp_s"] == 110,
        recovered,
    ))

    reverse_guard = RealtimeStateGuard(policy)
    reverse_guard.ingest_batch([_record(train_id="R001", direction="reverse", position_km=20.0)], received_at_s=100)
    reverse_before = reverse_guard.cursor_snapshot()
    reverse_bad = reverse_guard.ingest_batch(
        [_record(timestamp_s=110, train_id="R001", direction="reverse", position_km=20.1)],
        received_at_s=110,
    )
    rows.append(_matrix_row(
        "RT-S06",
        "顺序与位置",
        "反向列车位置反向异常",
        "拒绝且不推进可信游标",
        " | ".join(item["error"] for item in reverse_bad["errors"]),
        reverse_bad["rejected_count"] == 1 and reverse_bad["cursor"] == reverse_before,
        reverse_bad,
    ))

    outage_guard = RealtimeStateGuard(policy)
    no_data = outage_guard.evaluate(100)
    rows.append(_matrix_row(
        "RT-O01", "断流与恢复", "启动后没有任何状态", "no_data_hold并等待快照",
        no_data["state"], no_data["state"] == "no_data_hold", no_data,
    ))
    healthy = outage_guard.ingest_batch([_record()], received_at_s=100)
    rows.append(_matrix_row(
        "RT-O02", "断流与恢复", "收到首个有效状态", "进入healthy",
        healthy["state"], healthy["state"] == "healthy" and not healthy["recovered"], healthy,
    ))
    outage = outage_guard.evaluate(131)
    rows.append(_matrix_row(
        "RT-O03", "断流与恢复", "超过30秒未收到有效消息", "扣留新决策并保留最后可信状态",
        outage["state"],
        outage["state"] == "stream_outage_hold"
        and outage["action"] == "hold_new_decisions_and_keep_last_trusted_state",
        outage,
    ))
    restored = outage_guard.ingest_batch([_record(timestamp_s=132, position_km=11.0)], received_at_s=132)
    rows.append(_matrix_row(
        "RT-O04", "断流与恢复", "断流后收到新鲜有效消息", "标记recovered并恢复使用",
        restored["state"], restored["state"] == "recovered" and restored["recovered"], restored,
    ))

    drift_guard = RealtimeStateGuard(policy)
    drift_guard.ingest_batch([_record()], received_at_s=100)
    drift_before = drift_guard.cursor_snapshot()
    drift = drift_guard.ingest_batch([_record(timestamp_s=116, position_km=11.0)], received_at_s=110)
    corrected = drift_guard.ingest_batch([_record(timestamp_s=110, position_km=11.0)], received_at_s=110)
    rows.append(_matrix_row(
        "RT-O05", "断流与恢复", "未来时钟漂移后校正重发", "漂移消息拒绝，校正消息接受",
        f"rejected={drift['rejected_count']}, corrected={corrected['accepted_count']}",
        drift["rejected_count"] == 1
        and drift["cursor"] == drift_before
        and corrected["accepted_count"] == 1,
        {"drift": drift, "corrected": corrected},
    ))

    multi_guard = RealtimeStateGuard(policy, expected_train_ids=("T001", "T002"))
    partial = multi_guard.ingest_batch([_record(train_id="T001")], received_at_s=100)
    rows.append(_matrix_row(
        "RT-O06", "断流与恢复", "期望两列车但只收到一列车", "识别不完整流并扣留新决策",
        partial["state"],
        partial["state"] == "incomplete_stream_hold"
        and partial["missing_train_ids"] == ["T002"],
        partial,
    ))
    complete = multi_guard.ingest_batch(
        [_record(train_id="T002", position_km=20.0)], received_at_s=100
    )
    rows.append(_matrix_row(
        "RT-O07", "断流与恢复", "缺失列车补齐", "完整快照恢复为healthy",
        complete["state"], complete["state"] == "healthy", complete,
    ))
    multi_guard.ingest_batch(
        [_record(timestamp_s=131, train_id="T001", position_km=11.0)], received_at_s=131
    )
    one_stream_stale = multi_guard.evaluate(131)
    rows.append(_matrix_row(
        "RT-O08", "断流与恢复", "一列车持续更新、另一列车断流", "定位T002并扣留新决策",
        one_stream_stale["state"],
        one_stream_stale["state"] == "stream_outage_hold"
        and one_stream_stale["stale_train_ids"] == ["T002"],
        one_stream_stale,
    ))
    unknown_before = multi_guard.cursor_snapshot()
    unknown = multi_guard.ingest_batch(
        [_record(timestamp_s=131, train_id="T999", position_km=99.0)], received_at_s=131
    )
    rows.append(_matrix_row(
        "RT-O09", "断流与恢复", "期望集合之外的列车ID", "拒绝且不改变可信游标",
        " | ".join(item["error"] for item in unknown["errors"]),
        unknown["rejected_count"] == 1
        and unknown["cursor"] == unknown_before
        and "不在期望状态集合" in unknown["errors"][0]["error"],
        unknown,
    ))
    return rows


def _expect_exception(
    case_id: str,
    injection: str,
    callback: Callable[[], Any],
    expected_text: str,
) -> dict[str, Any]:
    """执行预期拒绝的设备状态构造。"""

    try:
        callback()
    except (TypeError, ValueError) as exc:
        error = str(exc)
        return _matrix_row(
            case_id, "设备状态", injection, "输入启动求解前被拒绝", error,
            expected_text in error, {"error_type": type(exc).__name__, "error": error},
        )
    return _matrix_row(case_id, "设备状态", injection, "输入启动求解前被拒绝", "未拒绝", False, {})


def _rolling_result(state: RollingWindowState, feasible: bool) -> RollingOptimizationResult:
    """构造只关注提交门禁状态的轻量滚动结果。"""

    schedule = GeneratedSchedule(
        heavy_departures_s=[state.current_time_s],
        empty_departures_s=[state.current_time_s + 100],
        template=BASE_TEMPLATE,
    )
    scenario_rows = ({
        "scenario": "normal",
        "core_for_feasibility": True,
        "feasible": feasible,
        "constraint_violation": 0.0 if feasible else 1.0,
        "resource_conflict_count": 0 if feasible else 1,
        "resource_overlap_violation_s": 0.0 if feasible else 60.0,
    },)
    decision = gate_rolling_execution_commit(
        schedule,
        scenario_rows,
        current_time_s=state.current_time_s,
        execute_window_s=600,
        locked_heavy_departures_s=state.locked_heavy_departures_s,
        locked_empty_departures_s=state.locked_empty_departures_s,
    )
    return RollingOptimizationResult(
        schedule=schedule,
        execution_schedule=schedule,
        committed_execution_schedule=decision.committed_execution_schedule,
        score=ScheduleScore(feasible, 1.0, 0.0, 1.0, 0.0, 1),
        executable_heavy_departures_s=decision.executable_heavy_departures_s,
        executable_empty_departures_s=decision.executable_empty_departures_s,
        core_robust_feasible=decision.core_robust_feasible,
        commit_status=decision.commit_status,
        operational_intervention_required=decision.operational_intervention_required,
        selected_scenario_diagnostics=scenario_rows,
    )


class _SequenceOptimizer:
    """按序列返回结果并记录求解次数。"""

    default_storage_preset_id = ""

    def __init__(self, feasibility: list[bool]) -> None:
        self.feasibility = feasibility
        self.calls: list[RollingWindowState] = []

    def optimize_once(self, state: RollingWindowState, _base_template: ScheduleTemplate, **_kwargs: Any) -> RollingOptimizationResult:
        self.calls.append(state)
        index = min(len(self.calls) - 1, len(self.feasibility) - 1)
        return _rolling_result(state, self.feasibility[index])


def _device_and_rolling_cases() -> list[dict[str, Any]]:
    """覆盖设备状态拒绝、求解幂等、自动恢复和人工升级。"""

    rows = [
        _expect_exception(
            "RT-D01", "重复储能设备ID",
            lambda: RollingWindowState(
                0, [], [],
                storage_device_states=(
                    StorageDeviceRuntimeState("S1", 10.0),
                    StorageDeviceRuntimeState("S1", 20.0),
                ),
            ),
            "Duplicate",
        ),
        _expect_exception(
            "RT-D02", "汇总SOC与设备SOC同时提供",
            lambda: RollingWindowState(
                0, [], [], storage_soc_kwh=10.0,
                storage_device_states=(StorageDeviceRuntimeState("S1", 10.0),),
            ),
            "cannot be supplied together",
        ),
        _expect_exception(
            "RT-D03", "设备SOC为负数",
            lambda: StorageDeviceRuntimeState("S1", -1.0),
            "non-negative",
        ),
        _expect_exception(
            "RT-D04", "设备在线状态不是布尔值",
            lambda: StorageDeviceRuntimeState("S1", 1.0, available=1),
            "boolean",
        ),
    ]

    config = TemplateSearchConfig(population_size=2, generations=1, elite_count=1)
    common = {
        "horizon_s": 1200,
        "execute_window_s": 600,
        "search_config": config,
        "enable_recovery": False,
        "allow_infeasible_commit_for_experiment": False,
    }

    idempotent_optimizer = _SequenceOptimizer([True])
    idempotent_controller = RollingSafetyController(RollingSafetyPolicy(enable_automatic_retry=False))
    state = RollingWindowState(0, [], [], observed_heavy_delay_s=30)
    first = idempotent_controller.optimize_cycle(idempotent_optimizer, state, BASE_TEMPLATE, **common)
    second = idempotent_controller.optimize_cycle(idempotent_optimizer, state, BASE_TEMPLATE, **common)
    rows.append(_matrix_row(
        "RT-R01", "滚动恢复", "完全相同状态重复提交", "复用结果且不重复求解",
        f"calls={len(idempotent_optimizer.calls)}",
        first is second and len(idempotent_optimizer.calls) == 1,
        first.search_diagnostics.get("safety_state_machine", {}),
    ))

    changed_optimizer = _SequenceOptimizer([False, True])
    changed_controller = RollingSafetyController(RollingSafetyPolicy(enable_automatic_retry=False))
    failed = changed_controller.optimize_cycle(
        changed_optimizer,
        RollingWindowState(0, [], [], observed_heavy_delay_s=120),
        BASE_TEMPLATE,
        **common,
    )
    recovered = changed_controller.optimize_cycle(
        changed_optimizer,
        RollingWindowState(600, [], [], observed_heavy_delay_s=0),
        BASE_TEMPLATE,
        **common,
    )
    rows.append(_matrix_row(
        "RT-R02", "滚动恢复", "不可行扣留后观测变化", "不锁定坏方案并在新观测后恢复",
        f"{failed.safety_state}->{recovered.safety_state}",
        failed.safety_state == "waiting_for_observation"
        and failed.committed_execution_schedule.heavy_departures_s == []
        and recovered.safety_state == "recovered_after_observation"
        and len(changed_optimizer.calls) == 2,
        {
            "failed": failed.search_diagnostics["safety_state_machine"],
            "recovered": recovered.search_diagnostics["safety_state_machine"],
        },
    ))

    retry_optimizer = _SequenceOptimizer([False, True])
    retry_controller = RollingSafetyController(RollingSafetyPolicy(max_retries_per_cycle=1))
    retried = retry_controller.optimize_cycle(
        retry_optimizer, RollingWindowState(0, [], []), BASE_TEMPLATE, **common
    )
    rows.append(_matrix_row(
        "RT-R03", "滚动恢复", "首次求解不可行", "一次有界增强重试后自动恢复",
        retried.safety_state,
        retried.safety_state == "recovered_automatically"
        and retried.safety_attempt_count == 2
        and len(retry_optimizer.calls) == 2,
        retried.search_diagnostics["safety_state_machine"],
    ))

    manual_optimizer = _SequenceOptimizer([False, False])
    manual_controller = RollingSafetyController(RollingSafetyPolicy(enable_automatic_retry=False))
    waiting = manual_controller.optimize_cycle(
        manual_optimizer, RollingWindowState(0, [], []), BASE_TEMPLATE, **common
    )
    manual = manual_controller.optimize_cycle(
        manual_optimizer,
        RollingWindowState(600, [], [], observed_empty_delay_s=60),
        BASE_TEMPLATE,
        **common,
    )
    rows.append(_matrix_row(
        "RT-R04", "滚动恢复", "连续两轮不可行", "从等待升级到人工处置，均扣留新发车",
        f"{waiting.safety_state}->{manual.safety_state}",
        waiting.safety_state == "waiting_for_observation"
        and manual.safety_state == "manual_intervention_required"
        and manual.operational_intervention_required
        and not manual.committed_execution_schedule.heavy_departures_s,
        manual.search_diagnostics["safety_state_machine"],
    ))

    device_optimizer = _SequenceOptimizer([True, True])
    device_controller = RollingSafetyController(RollingSafetyPolicy(enable_automatic_retry=False))
    online = RollingWindowState(
        0, [], [],
        storage_device_states=(StorageDeviceRuntimeState("S1", 10.0, True, 5.0, 5.0),),
    )
    offline = RollingWindowState(
        0, [], [],
        storage_device_states=(StorageDeviceRuntimeState("S1", 10.0, False, 0.0, 0.0),),
    )
    device_controller.optimize_cycle(device_optimizer, online, BASE_TEMPLATE, **common)
    offline_result = device_controller.optimize_cycle(device_optimizer, offline, BASE_TEMPLATE, **common)
    transition = offline_result.search_diagnostics["safety_state_machine"]
    rows.append(_matrix_row(
        "RT-R05", "滚动恢复", "储能设备在线转停运", "状态指纹变化并重新求解",
        f"calls={len(device_optimizer.calls)}, changed={transition['observation_changed']}",
        len(device_optimizer.calls) == 2 and transition["observation_changed"] is True,
        transition,
    ))
    return rows


def run_matrix(output_dir: Path) -> dict[str, Any]:
    """运行完整矩阵并写出机器和人员可读工件。"""

    rows = _field_and_freshness_cases() + _sequence_and_outage_cases() + _device_and_rolling_cases()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    category_summary: dict[str, dict[str, int]] = {}
    for row in rows:
        item = category_summary.setdefault(row["category"], {"case_count": 0, "passed_count": 0, "failed_count": 0})
        item["case_count"] += 1
        item["passed_count" if row["passed"] else "failed_count"] += 1
    failures = [row for row in rows if not row["passed"]]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "passed": not failures,
        "case_count": len(rows),
        "passed_count": len(rows) - len(failures),
        "failed_count": len(failures),
        "categories": category_summary,
        "production_actions": {
            "invalid_or_stale_message": "reject_and_preserve_trusted_cursor",
            "stream_outage": "hold_new_decisions_and_keep_last_trusted_state",
            "fresh_message_after_outage": "recover_and_use_accepted_snapshot",
            "infeasible_schedule": "withhold_new_departures",
            "repeated_infeasibility": "manual_intervention_required",
        },
        "limitations": [
            "当前阈值是离线测试策略，不代表现场调度规章。",
            "本矩阵不连接消息中间件、现场时钟或真实设备。",
            "通过矩阵不代表正式数据已验收或可下发控制指令。",
        ],
        "outputs": {
            "report": "REALTIME_STATE_ANOMALY_MATRIX_REPORT.md",
            "summary": "realtime_state_anomaly_matrix_summary.json",
            "cases": "realtime_state_anomaly_matrix_cases.csv",
            "failures": "realtime_state_anomaly_matrix_failures.json",
        },
    }
    with (output_dir / summary["outputs"]["cases"]).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / summary["outputs"]["summary"]).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / summary["outputs"]["failures"]).write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "failures": failures}, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 实时状态异常注入与恢复测试矩阵",
        "",
        f"结论：`{'PASS' if summary['passed'] else 'FAIL'}`；共 {summary['case_count']} 项，通过 {summary['passed_count']} 项，失败 {summary['failed_count']} 项。",
        "",
        "| 类别 | 案例 | 通过 | 失败 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, item in category_summary.items():
        lines.append(f"| {category} | {item['case_count']} | {item['passed_count']} | {item['failed_count']} |")
    lines.extend([
        "",
        "## 逐项矩阵",
        "",
        "| 编号 | 类别 | 异常注入 | 预期行为 | 实际行为 | 结果 |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in rows:
        values = [
            str(row["case_id"]),
            str(row["category"]),
            str(row["injection"]),
            str(row["expected_behavior"]),
            str(row["actual_behavior"]),
            "PASS" if row["passed"] else "FAIL",
        ]
        escaped = [value.replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    lines.extend([
        "",
        "## 生产动作边界",
        "",
        "- 非法、过期、未来漂移、重复或乱序消息：拒绝该消息，保持最后可信游标。",
        "- 数据断流：停止形成新的自动决策，保留最后可信状态等待新快照。",
        "- 断流后新鲜有效消息：明确标记恢复，再允许状态进入求解。",
        "- 核心稳健不可行方案：扣留新增发车；连续失败升级人工处置。",
        "- 相同状态重复提交：幂等复用；观测或设备状态变化：重新求解。",
        "",
        "## 边界",
        "",
        *[f"- {item}" for item in summary["limitations"]],
    ])
    (output_dir / summary["outputs"]["report"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper") / "experiments" / "realtime_state_anomaly_matrix_current",
    )
    args = parser.parse_args()
    summary = run_matrix(args.output_dir)
    print(json.dumps({
        "passed": summary["passed"],
        "case_count": summary["case_count"],
        "failed_count": summary["failed_count"],
        "report": str(args.output_dir / summary["outputs"]["report"]),
    }, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
