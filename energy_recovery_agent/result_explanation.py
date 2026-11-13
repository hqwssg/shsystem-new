"""只读方案展示适配器：不重新评分，不改推荐决策，不生成生产下发许可。"""

from collections.abc import Mapping, Sequence
import math


ACTION_LABELS = {"optimize": "发现可供复核的改进方案", "keep_baseline": "保留原方案",
                 "no_feasible_solution": "本轮未得到可采用方案"}
REASON_LABELS = {
    "baseline_infeasible": "原运行图未通过发车间隔、站场资源或供电等硬约束检查。本轮没有给出可验收的节能方案。",
    "feasibility_restored_energy_comparison_unavailable": "选中方案通过了约束检查。基线能耗供诊断使用，暂不评价节能改善。",
    "material_energy_improvement_found": "候选通过可行性检查，在相同储能条件下能量指标有实质改善。",
    "no_material_energy_improvement": "已比较候选，但能量改善未达到门槛，或另一核心指标变差；保留原方案不表示算法没有运行。",
    "storage_preset_changed_requires_fixed_storage_recheck": "候选同时改变了储能配置，不能把差值都算作调度收益；需要固定储能配置重新比较。",
    "selected_candidate_failed_core_robust_gate": "返回候选未通过核心扰动场景检查，不能按较低能耗强行采用。",
}
BOTTLENECK_LABELS = {
    "section_without_storage": "该供电臂未接入储能",
    "storage_capacity_or_power_limit": "储能容量或充电功率不足",
    "storage_charge_power_or_capacity": "储能充电能力受限",
    "storage_discharge_power_or_soc": "储能放电功率或剩余电量受限",
    "resource_conflict": "站场、咽喉或区间占用冲突",
    "scenario_infeasibility": "核心扰动场景未通过",
    "stress_scenario_diagnostic": "非核心压力场景存在风险",
    "terminal_soc_deviation": "评价结束时储能电量偏离目标",
    "traction_supply_limit": "牵引供电能力受限",
    "flow_continuity": "重空车流衔接未通过",
}
CHECK_LABELS = {"official_data_acceptance": "正式输入数据验收", "model_calibration": "模型独立校准验证",
                "result_audit": "本次结果质量审计", "deployment_acceptance": "目标环境验收"}
REQUIRED_DATA = {"timetable": "正式运行图", "train_dynamics": "车辆牵引、制动与阻力参数",
                 "power_arm_limits": "供电臂电气能力", "storage_connection": "储能站址与接入供电臂",
                 "storage_discharge": "储能最大放电功率", "signaling_resources": "完整闭塞与站场资源",
                 "initial_inventory": "初始重空车流库存"}
QUALITY_LABELS = {"provided": "已提供（仍需验收）", "confirmed": "已确认", "assumed": "规划假设",
                  "missing": "缺失", "unverified": "未确认"}
SCOPE_LABELS = {"baseline": "原方案", "selected_candidate": "选中候选",
                "selected_candidate_core": "选中候选的核心场景",
                "selected_candidate_non_core_stress": "选中候选的非核心压力场景"}
LOCATION_LABELS = {"battery_charge_limited_kwh": "受限未充入量",
                   "battery_discharge_limited_kwh": "受限未放出量", "normal": "正常运行场景",
                   "heavy_delay_light": "重车轻度晚点场景", "empty_delay_light": "空车轻度晚点场景",
                   "heavy_delay": "重车晚点压力场景", "empty_delay": "空车晚点压力场景"}


def _finite(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def build_result_explanation(*, run_id: str, run_status: str, summary: Mapping,
                             attribution: Mapping, candidate_rows: Sequence[Mapping] = (),
                             metric_rows: Sequence[Mapping] = (), dimension_rows: Sequence[Mapping] = (),
                             data_evidence: Mapping | None = None) -> dict:
    evidence = dict(data_evidence or {})
    decision = attribution.get("decision") or summary.get("optimization_decision") or {}
    action = str(decision.get("action", "unknown"))
    reason = str(decision.get("reason", ""))
    selected_id = str(decision.get("selected_candidate_id", ""))
    selected = next((row for row in candidate_rows if str(row.get("candidate_id")) == selected_id), {})
    # CSV布尔值只认可明确的true，不把非空字符串false当真。
    feasible = selected.get("feasible") is True or str(selected.get("feasible", "")).lower() == "true"
    fixed_storage = (attribution.get("attribution_scope") or {}).get("dispatch_only_attribution_allowed") is True
    complete = (run_status == "succeeded" and bool(run_id.strip()) and
                ("valid" not in summary or summary.get("valid") is True))
    comparable = complete and feasible and fixed_storage
    recommendation = action == "optimize" and reason == "material_energy_improvement_found" and comparable
    if not complete:
        title = "结果尚未确认完成，请勿采用"
    elif action == "optimize" and not comparable:
        title = "推荐依据不完整，请先复核"
    else:
        title = ACTION_LABELS.get(action, "决策状态未知，请先复核")
    explanation = REASON_LABELS.get(reason, "未提供可识别的决策理由；请查看原始结果，不自动猜测采用原因。")
    if action == "no_feasible_solution":
        explanation += " 搜索未找到可行方案，不等于已证明当前模型无解。"
    quality_items = evidence.get("items") or {}
    items = []
    for key, label in REQUIRED_DATA.items():
        item = quality_items.get(key, {})
        status = str(item.get("status", "unverified"))
        if status not in QUALITY_LABELS:
            status = "unverified"
        items.append({"key": key, "label": label, "status": status,
                      "status_label": QUALITY_LABELS[status], "note": str(item.get("note", ""))})
    checks = [{"key": key, "label": label, "passed": evidence.get(key) is True,
               "status_label": "通过" if evidence.get(key) is True else "未确认通过"}
              for key, label in CHECK_LABELS.items()]
    formal = (complete and evidence.get("run_id") == run_id and evidence.get("data_status") == "official" and
              evidence.get("formal_engineering_conclusion_allowed") is True and
              all(row["status"] == "confirmed" for row in items) and all(row["passed"] for row in checks))
    improvements = []
    for row in metric_rows:
        # 只展示现有归因账本的收益项；充放电量、窗末SOC不伪装成节能。
        if row.get("benefit_direction") not in {"lower", "higher"}:
            continue
        before, after, gain = (_finite(row.get(key)) for key in ("baseline", "optimized", "improvement"))
        if before is None or after is None or gain is None:
            continue
        improvements.append({"label": str(row.get("metric_label", row.get("metric", ""))),
                             "baseline": before, "candidate": after, "improvement": gain,
                             "unit": {"kWh": "千瓦时", "CNY": "元", "ratio": "比例", "count": "次",
                                      "score": "评分", "constraint_score": "约束评分", "s": "秒"}.get(str(row.get("unit")), str(row.get("unit", ""))),
                             "dispatch_only_comparable": comparable})
    adjustments = []
    known_departure_changes = 0
    for row in dimension_rows:
        delta = _finite(row.get("optimized_minus_baseline"))
        departure_row = row.get("dimension_type") == "train" and row.get("metric") == "depart_time_s"
        if departure_row and delta is not None:
            known_departure_changes += 1
        if departure_row and delta:
            adjustments.append({"train_id": str(row.get("dimension_id", "")), "shift_s": delta,
                                "text": f"列车 {row.get('dimension_id', '')} 发车{'推迟' if delta > 0 else '提前'} {abs(delta):g} 秒"})
    bottlenecks = [{"label": BOTTLENECK_LABELS.get(str(row.get("bottleneck_type")), "其他瓶颈（详见原始结果）"),
                    "id": str(row.get("bottleneck_id", "")),
                    "location_label": LOCATION_LABELS.get(str(row.get("bottleneck_id", "")), str(row.get("bottleneck_id", ""))),
                    "scope": str(row.get("scope", "")),
                    "scope_label": SCOPE_LABELS.get(str(row.get("scope", "")), "作用范围未标明"),
                    "blocking": row.get("blocking") is True}
                   for row in (attribution.get("top_bottlenecks") or [])]
    warnings = ["本页是决策解释，不是调度指令；现场采用须由调度人员确认。",
                "资源可行性、能量收益和正式数据可信度是不同判断，不能用任务成功替代三者验收。",
                "共享储能收益不能直接按比例分摊为单列车节能贡献。"]
    if not formal:
        warnings.append("含假设、缺失参数或验收证据不全，仅用于当前模型下的方案比较；不得发布正式节能率、线路容量或投资收益。")
    if not fixed_storage:
        warnings.append("固定储能对照证据不足，差值不能标为纯调度节能收益。")
    return {"schema_version": "1.0", "display_only": True, "run_id": run_id, "run_status": run_status,
            "decision": {"action": action, "reason": reason, "title": title, "explanation": explanation,
                         "selected_candidate_id": selected_id, "candidate_review_recommended": recommendation},
            "data_confidence": {"label": "正式结论证据齐全（仍需人工复核）" if formal else "仅限模型比较，正式结论条件未满足",
                                "formal_engineering_conclusion_allowed": formal, "items": items, "checks": checks},
            "improvements": improvements, "adjustments": adjustments,
            "adjustment_summary": {"departure_attribution_available": known_departure_changes > 0,
                                   "text": "本次列车发车时刻未改变。" if known_departure_changes and not adjustments
                                   else "未提供逐列车发车调整明细。" if not known_departure_changes
                                   else f"有 {len(adjustments)} 列车调整发车时刻，详见上方。"},
            "bottlenecks": bottlenecks,
            "warnings": warnings, "production_dispatch_allowed": False}
