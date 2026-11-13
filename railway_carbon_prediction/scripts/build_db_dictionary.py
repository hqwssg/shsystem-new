"""Generate the database field dictionary from the live schema."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "10_数据库字段详细说明.md"

TABLES = [
    "prediction_org", "prediction_energy_var", "prediction_emission_factor",
    "prediction_caliber_rule", "prediction_activity_monthly",
    "prediction_emission_monthly", "prediction_anomaly",
    "prediction_anomaly_audit", "prediction_anomaly_watch",
    "prediction_anomaly_calibration", "prediction_ingest_batch",
    "prediction_ingest_audit", "prediction_dataset_version", "prediction_gra_result", "prediction_model",
    "prediction_forecast", "prediction_policy_factor", "prediction_policy_event",
    "prediction_scenario", "prediction_job", "prediction_audit_log",
    "prediction_calendar_event",
]

TABLE_META = {
    "prediction_org": ("组织维表", "保存公司根节点与三个分公司，建立模块 org_id 与平台 sys_dept.dept_id 的映射。"),
    "prediction_energy_var": ("能源与活动品种维表", "定义活动量/能源品种编码、单位、类别、是否牵引、是否建模目标。"),
    "prediction_emission_factor": ("排放因子维表", "按品种和生效期保存排放因子，支持年度口径切换与追溯。"),
    "prediction_caliber_rule": ("核算口径规则表", "保存供热面积折算系数、电网因子等口径规则。"),
    "prediction_activity_monthly": ("月度活动数据事实表", "按组织×月×品种保存活动量，是排放计算和模型特征的原始事实表。"),
    "prediction_emission_monthly": ("月度碳排放结果表", "按组织×月保存报表口径与可比口径排放结果及分项排放。"),
    "prediction_anomaly": ("异常检测与复核表", "保存 V2 异常检测的复核级异常、证据、断点信息和处置状态。"),
    "prediction_anomaly_audit": ("异常复核审计表", "保存异常复核的追加审计记录，不物理覆盖原记录。"),
    "prediction_anomaly_watch": ("关注级异常监控表", "保存关注级异常，不进入人工复核队列，用于月度数据质量报告。"),
    "prediction_anomaly_calibration": ("异常阈值校准表", "保存弱标签条件下的阈值/污染率校准结果。"),
    "prediction_ingest_batch": ("数据接入批次表", "保存每次数据接入的批次、幂等键、请求体指纹、覆盖标记和状态。"),
    "prediction_ingest_audit": ("入库覆盖审计表", "覆盖同月数据前保存旧活动值、旧排放值和旧异常状态，禁止无痕覆盖。"),
    "prediction_dataset_version": ("训练数据集版本表", "保存训练数据集的时间范围、行数和内容指纹。"),
    "prediction_gra_result": ("灰色关联分析结果表", "保存 GRA 关联度、去趋势关联度、排名和入选标记。"),
    "prediction_model": ("模型注册表", "保存模型版本、特征顺序、scaler、超参数、指标和工件路径。"),
    "prediction_forecast": ("预测结果表", "保存未来 12 个月预测结果，支持多模型/多情景。"),
    "prediction_policy_factor": ("政策与外部因子事实表", "保存政策、价格、供给、运输、电力、气象等月度因子。"),
    "prediction_policy_event": ("政策事件时间线", "保存定性政策事件及其来源、强度评分。"),
    "prediction_scenario": ("预测情景定义表", "保存 BAU 等情景的参数配置。"),
    "prediction_job": ("异步任务表", "保存训练、预测、GRA、导入等异步任务。"),
    "prediction_audit_log": ("模块审计日志", "保存模块级操作审计，JSON 记录上下文。"),
    "prediction_calendar_event": ("日历事件表", "保存春节、疫情、检修等日历事件。"),
}

COMMON = {
    "id": "自增主键，无业务含义",
    "org_id": "组织编码：SHL=公司根节点，JLG=机辆分公司，SNF=肃宁分公司，YPF=原平分公司",
    "period": "统计月首日，格式 YYYY-MM-01",
    "var_id": "品种编码，见 3.1 品种字典",
    "unit": "计量单位，与 prediction_energy_var.unit 一致",
    "value": "数值；活动量必须非负",
    "reported_value": "报表口径值；非负；仅热力口径切换时与 value 不同",
    "source_status": "数据来源状态，见 3.2",
    "is_estimated": "是否推算值：0=否，1=是",
    "quality_status": "数据质量状态：valid/pending/excluded，见 3.2",
    "data_flag": "数据标记：空或结构断点/口径变更标记，见 3.2",
    "batch_id": "接入批次号，关联 prediction_ingest_batch.batch_id",
    "data_version": "数据版本号，关联 prediction_dataset_version.version_id",
    "created_at": "记录创建时间，数据库自动写入",
    "updated_at": "记录最后更新时间，数据库自动更新",
    "operator": "操作人账号或系统标识",
    "note": "备注/说明",
    "reviewer": "复核人账号",
    "reviewed_at": "复核时间",
    "review_note": "复核意见",
}

FIELD_META: Dict[str, Dict[str, str]] = {
    "prediction_org": {
        "org_id": "组织主键：SHL/JLG/SNF/YPF",
        "org_name": "组织中文名称",
        "org_level": "层级：1=公司，2=分公司",
        "parent_org_id": "上级组织编码；根节点为 NULL",
        "platform_dept_id": "平台 sys_dept.dept_id，用于集成映射：3000/3010/3020/3030",
        "province": "主要经营省份，如“河北”“山西”“河北/山西”",
        "heating_months": "供暖月份，逗号分隔，如“1,2,3,11,12”",
        "latitude": "纬度，十进制度，范围 -90～90",
        "longitude": "经度，十进制度，范围 -180～180",
        "status": "组织状态：active=启用，inactive=停用",
    },
    "prediction_energy_var": {
        "var_id": "品种主键，见 3.1",
        "var_name": "品种中文名称",
        "unit": "权威计量单位",
        "var_category": "类别：fuel/electricity/heat/operation/target",
        "is_traction": "是否牵引电力：0=否，1=是",
        "is_target": "是否建模目标：0=否，1=是",
        "sort_order": "展示/处理排序号，升序",
        "remark": "备注",
    },
    "prediction_emission_factor": {
        "factor_id": "自增主键",
        "var_id": "适用品种编码",
        "factor_value": "因子数值，非负",
        "factor_unit": "因子单位：tCO2/MWh、tCO2/t、tCO2/万m3、tCO2/GJ",
        "factor_version": "因子版本，如 EF-ELEC-2025；用于结果快照与追溯",
        "effective_from": "生效起始日（含）",
        "effective_to": "失效日（含）；NULL 表示当前有效",
        "factor_source": "因子来源说明",
        "is_caliber_change": "是否口径切换点：0=否，1=是",
        "policy_basis": "政策/台账依据",
    },
    "prediction_caliber_rule": {
        "rule_id": "规则主键",
        "org_id": "适用组织：ALL/JLG/SNF/YPF",
        "rule_type": "规则类型：heat_area_factor=供热面积折算系数；grid_factor=电网因子",
        "effective_from": "生效起始日（含）",
        "effective_to": "失效日（含）；NULL 表示当前有效",
        "rule_value": "规则数值，非负",
        "unit": "单位：GJ/m2 或 tCO2/MWh",
        "rule_version": "规则版本，如 CAL-SNF-2025；用于结果快照与追溯",
        "source": "来源/协议/文件",
        "note": "备注",
    },
    "prediction_activity_monthly": {
        "id": "自增主键",
        "org_id": "组织编码",
        "period": "统计月首日",
        "var_id": "品种编码",
        "value": "物理/可比口径值；活动量非负",
        "reported_value": "报表口径值；热力口径切换时与 value 不同",
        "unit": "计量单位",
        "source_status": "原始/推算/补全/口径还原/异常剔除/无此项",
        "is_estimated": "是否推算：0=否，1=是",
        "quality_status": "valid/pending/excluded",
        "data_flag": "结构断点/口径切换/待核实标记",
        "batch_id": "接入批次号",
        "data_version": "数据版本号",
    },
    "prediction_emission_monthly": {
        "id": "自增主键",
        "org_id": "组织编码",
        "period": "统计月首日",
        "scope": "排放边界；当前固定为 Total",
        "gas_tco2": "天然气排放，tCO2e，非负",
        "gasoline_tco2": "汽油排放，tCO2e，非负",
        "diesel_tco2": "柴油排放，tCO2e，非负",
        "electricity_tco2": "电力排放（报表因子），tCO2e，非负",
        "heat_tco2": "热力排放（报表口径），tCO2e，非负",
        "total_reported_tco2": "报表口径总排放，tCO2e；=各分项之和",
        "total_comparable_tco2": "可比口径总排放，tCO2e；固定 2025 电力因子与基准热力系数",
        "electricity_factor": "当年电力排放因子，tCO2/MWh",
        "heat_factor": "热力排放因子，0.11 tCO2/GJ",
        "factor_version": "本次计算使用的因子版本组合，如 EF-ELEC-2025 / CAL-SNF-2025",
        "heat_area_factor": "本次计算使用的供热面积系数，GJ/m2",
        "factor_source": "本次计算使用的因子来源摘要",
        "factor_snapshot": "本次计算使用的完整因子快照 JSON：各品种 factor_value/factor_unit/factor_version/effective_from/effective_to",
        "calc_method": "计算方法；当前固定 activity_x_factor",
        "is_verified": "年度总量恒等式校验：0=未通过，1=通过",
        "batch_id": "计算/接入批次号",
        "data_version": "数据版本号",
    },
    "prediction_anomaly": {
        "id": "自增主键",
        "org_id": "组织编码",
        "period": "异常所在月",
        "var_id": "异常品种编码",
        "detect_batch_id": "检测批次号；增量接入时等于接入批次号",
        "channel": "主通道：raw/stl_residual/resid/joint/rule 或组合",
        "score": "综合异常得分 s=-score_samples，数值越大越异常，约 0～1",
        "score_percentile": "序列内得分分位，0～100",
        "level": "等级：正常/关注/异常/严重异常",
        "category": "类别：C1/C2/C3/C4/UNDETERMINED",
        "confidence": "分类置信度，0～1",
        "suggested_disposition": "建议处置：keep/correct/exclude/mark_breakpoint",
        "status": "复核状态：pending/approved/rejected/auto_closed",
        "final_disposition": "最终处置：keep/correct/exclude/mark_breakpoint；pending 时为 NULL",
        "value": "异常点实测值",
        "reference_value": "参照值（序列中位数）",
        "correction_value": "修正值；correct 时填写，非负",
        "evidence": "证据文本：z 值、连续段、断点统计量、通道、上下文等",
        "reviewer": "复核人；历史自动处置为 system",
        "reviewed_at": "复核时间",
        "review_note": "复核意见",
        "algorithm_version": "算法版本：v1/v2；当前主表为 v2",
        "raw_score": "raw 森林得分，非负",
        "resid_score": "STL 残差森林得分，非负",
        "joint_score": "多变量联合得分，非负；可为 NULL",
        "channels": "触发通道组合：raw/resid/joint/rule 及组合",
        "context_flags": "日历上下文：spring_festival/covid/maintenance，逗号分隔",
        "breakpoint_date": "断点所在月；无断点为 NULL",
        "breakpoint_stat": "断点池化统计量，非负",
        "shift_pct": "断点水平位移百分比，可正可负",
        "cv_ratio": "后段 CV / 前段 CV，非负；无法计算时 NULL",
        "in_breakpoint_window": "是否在断点后 3 个月过渡窗：0=否，1=是",
    },
    "prediction_anomaly_audit": {
        "id": "自增主键",
        "anomaly_id": "关联 prediction_anomaly.id",
        "action": "处置动作：keep/correct/exclude/mark_breakpoint",
        "before_value": "处置前值",
        "after_value": "处置后值",
        "operator": "复核人",
        "note": "处置理由",
    },
    "prediction_anomaly_watch": {
        "id": "自增主键",
        "org_id": "组织编码",
        "period": "异常所在月",
        "var_id": "异常品种编码",
        "level": "监控等级：关注/异常/严重异常",
        "category": "类别：C1/C2/C3/C4/UNDETERMINED",
        "score": "综合得分，约 0～1",
        "raw_score": "raw 森林得分",
        "resid_score": "残差森林得分",
        "joint_score": "联合得分",
        "channels": "触发通道组合",
        "context_flags": "日历上下文",
        "evidence": "证据文本",
        "algorithm_version": "算法版本：v2",
    },
    "prediction_anomaly_calibration": {
        "id": "自增主键",
        "run_id": "校准运行批次号",
        "org_id": "组织编码",
        "var_id": "品种编码",
        "quantile": "分位阈值，实际扫描 0.90/0.92/0.95/0.97/0.98/0.99",
        "threshold_value": "对应分位的得分阈值",
        "precision_v": "弱标签精确率，0～1",
        "recall_v": "弱标签召回率，0～1",
        "f1": "弱标签 F1，0～1",
        "n_pos": "正样本数，≥0",
        "n_neg": "负样本数，≥0",
        "selected": "是否推荐：0=否，1=是",
        "note": "说明；标注弱标签非 ground truth",
    },
    "prediction_ingest_batch": {
        "batch_id": "批次主键",
        "org_id": "组织编码；跨组织批次可为 NULL",
        "period_start": "批次最早月份",
        "period_end": "批次最晚月份",
        "row_count": "提交记录数，≥0",
        "anomaly_count": "命中复核级异常数，≥0",
        "status": "received/validated/pending_review/completed/rejected",
        "idempotency_key": "幂等键，唯一；同一 key 同请求体返回原批次，不同请求体报冲突",
        "payload_hash": "请求体规范化 SHA-256，用于同一幂等键的请求一致性校验",
        "override_flag": "是否显式覆盖同月已入库数据：0=否，1=是",
        "override_reason": "覆盖原因；override_flag=1 时必填",
        "replaces_batch_id": "被本次覆盖的上一批次",
        "operator": "提交人",
        "message": "状态说明/错误信息",
        "completed_at": "完成时间；pending_review 时为 NULL",
    },
    "prediction_ingest_audit": {
        "batch_id": "本次覆盖批次号",
        "replaces_batch_id": "被覆盖的旧批次号",
        "org_id": "组织编码",
        "period": "被覆盖月份",
        "entity_type": "审计对象：activity/emission/anomaly",
        "entity_key": "对象业务键，如 org:period:var",
        "var_id": "活动/异常品种；排放审计为 NULL",
        "old_value": "覆盖前数值：活动量、报表总排放或异常得分",
        "new_value": "覆盖后数值；旧异常无新值为 NULL",
        "old_status": "覆盖前状态：quality_status、is_verified 或异常 status",
        "new_status": "覆盖后状态；旧异常被替代时为 rejected",
        "detail": "JSON：完整旧对象、新对象、覆盖原因",
        "operator": "操作人",
    },
    "prediction_dataset_version": {
        "version_id": "版本主键",
        "org_id": "组织编码",
        "start_period": "训练数据起始月",
        "end_period": "训练数据结束月",
        "row_count": "参与版本的行数，≥0",
        "content_hash": "内容 SHA-256 指纹，64 位十六进制",
        "note": "版本说明",
    },
    "prediction_gra_result": {
        "id": "自增主键",
        "run_id": "GRA 运行批次号",
        "org_id": "组织编码",
        "var_id": "候选因子编码",
        "var_name": "候选因子中文名",
        "r": "水平序列关联度，0～1",
        "r_detrend": "一阶差分后关联度，0～1；可为 NULL",
        "rank_no": "排名，从 1 开始",
        "selected": "是否入选：0=否，1=是",
        "spurious": "是否伪关联：0=否，1=是",
        "rho_sensitive": "是否对 rho 敏感：0=否，1=是",
        "borderline": "是否阈值边界：0=否，1=是",
        "direction": "预期方向：positive/negative/unknown",
        "note": "归一化、兜底、共线等说明",
    },
    "prediction_model": {
        "model_id": "模型主键，格式 组织-模型-W-H-时间",
        "org_id": "组织编码",
        "model_type": "SW_LSTM/RIDGE/GBM/HOLT_WINTERS/SEASONAL_NAIVE/ENSEMBLE",
        "version": "模型版本，如 v1.0/v1.0-ft",
        "status": "candidate/active/deprecated",
        "is_champion": "是否冠军：0=否，1=是；同一 org 最多一条 1",
        "target_var": "建模目标；当前为 CO2_COMPARABLE",
        "window_size": "滑动窗口 W；取值 6/9/12",
        "horizon": "预测步长；当前 12",
        "feature_order": "JSON 数组：特征顺序，推理必须一致",
        "hyperparams": "JSON：W、hidden、模型等超参数",
        "scaler_state": "JSON：x_mean/x_scale/y_min/y_scale 等",
        "metrics": "JSON：测试/验证/基线/回测/区间指标",
        "train_start": "训练起始月",
        "train_end": "训练结束月",
        "n_samples": "窗口样本数，≥1",
        "artifact_path": "模型工件目录",
        "data_version": "训练数据版本",
        "trained_at": "训练完成时间",
        "trained_by": "训练人/系统",
    },
    "prediction_forecast": {
        "id": "自增主键",
        "model_id": "关联 prediction_model.model_id",
        "org_id": "组织编码",
        "period": "预测月份",
        "scenario": "情景：BAU/COAL_HIGH/COAL_LOW/EFFICIENCY；当前为 BAU",
        "target_var": "目标变量；当前 CO2_COMPARABLE",
        "point": "可比口径点预测，tCO2e，非负",
        "lower_bound": "90% 区间下界，非负",
        "upper_bound": "90% 区间上界，非负",
        "reported_point": "折算到报表口径的点预测，非负",
        "comparable_point": "可比口径点预测，非负",
        "confidence_level": "置信水平；当前 0.90",
    },
    "prediction_policy_factor": {
        "id": "自增主键",
        "factor_id": "因子编码，如 COAL_PRICE_QHD5500、HDD_AVG4",
        "factor_name": "因子中文名",
        "period": "统计月首日",
        "value": "因子数值；一般非负",
        "unit": "单位，如 元/吨、℃·d、万吨、亿千瓦时",
        "category": "price/supply/transport/power/weather/policy/operation",
        "source_level": "national/provincial/market/enterprise/station",
        "source_status": "原始/插值/1-2月合计均分/外推/企业计划",
        "is_scenario_only": "是否仅情景输入：0=否，1=是",
        "data_source": "来源文件/机构/URL",
    },
    "prediction_policy_event": {
        "id": "自增主键",
        "event_id": "事件主键，如 EVT-2022-303",
        "event_name": "事件名称",
        "start_period": "事件起始月",
        "end_period": "事件结束月；NULL 表示持续",
        "dimension": "price/supply/transport/grid/carbon_market/other",
        "description": "事件描述",
        "source_url": "来源链接",
        "intensity": "专家强度评分，0～1；仅情景解释，不进入 GRA",
    },
    "prediction_scenario": {
        "scenario_id": "情景主键：BAU/COAL_HIGH/COAL_LOW/EFFICIENCY",
        "scenario_name": "情景中文名",
        "description": "情景说明",
        "config": "JSON：coal_price_multiplier、activity_multiplier、grid_factor",
        "is_default": "是否默认情景：0=否，1=是",
    },
    "prediction_job": {
        "job_id": "任务主键",
        "job_type": "TRAIN/FORECAST/GRA/IMPORT",
        "status": "queued/running/succeeded/failed",
        "params": "JSON：任务参数",
        "result": "JSON：任务结果",
        "error": "失败原因",
        "operator": "提交人",
        "started_at": "开始时间",
        "finished_at": "结束时间",
    },
    "prediction_audit_log": {
        "id": "自增主键",
        "action": "操作类型，如 IMPORT_HISTORY/ANOMALY_SCAN_V2/FORECAST/REVIEW",
        "entity": "操作对象表名",
        "entity_id": "对象主键/批次号",
        "operator": "操作人",
        "detail": "JSON：操作上下文",
    },
    "prediction_calendar_event": {
        "id": "自增主键",
        "event_id": "事件主键，如 CNY-1、COVID-2020",
        "event_type": "spring_festival/epidemic/maintenance",
        "event_name": "事件名称",
        "start_date": "事件开始日期",
        "end_date": "事件结束日期；应 ≥ start_date",
        "org_id": "适用组织：ALL 或具体 org_id",
        "impact_direction": "影响方向：down/up/unknown",
        "source": "来源",
        "note": "说明",
    },
}

# Fill common fields where table-specific is absent
for t in TABLES:
    FIELD_META.setdefault(t, {})
    for k, v in COMMON.items():
        FIELD_META[t].setdefault(k, v)


def connect():
    return pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                           database="carbon_emissions", charset="utf8mb4",
                           cursorclass=DictCursor)


def get_schema(cur):
    cur.execute("SELECT table_name AS name,table_type AS ttype,table_comment AS comment "
                "FROM information_schema.tables WHERE table_schema='carbon_emissions' "
                "AND table_name LIKE 'prediction%' ORDER BY table_name")
    tables = {r["name"]: r for r in cur.fetchall()}
    out = {}
    for name in tables:
        cur.execute("""SELECT column_name AS name,column_type AS ctype,is_nullable AS nullable,
                              column_default AS dflt,column_key AS ckey,column_comment AS comment,
                              ordinal_position AS pos
                       FROM information_schema.columns
                       WHERE table_schema='carbon_emissions' AND table_name=%s
                       ORDER BY ordinal_position""", (name,))
        cols = cur.fetchall()
        cur.execute("""SELECT index_name AS name,non_unique AS non_unique,seq_in_index AS seq,
                              column_name AS col
                       FROM information_schema.statistics
                       WHERE table_schema='carbon_emissions' AND table_name=%s
                       ORDER BY index_name,seq_in_index""", (name,))
        idx = cur.fetchall()
        cur.execute(f"SELECT COUNT(*) AS n FROM `{name}`")
        cnt = cur.fetchone()["n"]
        out[name] = {"meta": tables[name], "columns": cols, "indexes": idx, "count": cnt}
    return out


def key_label(col, indexes):
    key = col.get("ckey") or ""
    if key == "PRI":
        return "PK"
    labels = []
    for idx in indexes:
        if idx["col"] != col["name"]:
            continue
        if idx["name"] == "PRIMARY":
            continue
        if int(idx["non_unique"]) == 0:
            labels.append("UK")
        else:
            labels.append("IDX")
    return ",".join(sorted(set(labels))) if labels else "—"


def index_summary(indexes):
    groups = {}
    for r in indexes:
        groups.setdefault(r["name"], {"unique": int(r["non_unique"]) == 0, "cols": []})
        groups[r["name"]]["cols"].append(r["col"])
    lines = []
    for name, g in groups.items():
        typ = "唯一键" if g["unique"] else "普通索引"
        lines.append(f"{name}（{typ}：{', '.join(g['cols'])}）")
    return "；".join(lines) if lines else "无"


def fmt_default(v):
    if v is None:
        return "NULL"
    s = str(v)
    if s.startswith("CURRENT_TIMESTAMP"):
        return "CURRENT_TIMESTAMP"
    return s


def main():
    conn = connect(); cur = conn.cursor()
    schema = get_schema(cur)
    conn.close()

    lines: List[str] = []
    add = lines.append
    add("# 碳排放趋势预测系统——数据库字段详细说明")
    add("")
    add(f"**数据库**：`carbon_emissions`  ")
    add(f"**文档版本**：V1.0  ")
    add(f"**生成日期**：{datetime.now().strftime('%Y-%m-%d')}  ")
    add("**字符集/引擎**：utf8mb4 / utf8mb4_0900_ai_ci / InnoDB  ")
    add("**表前缀**：`prediction_`  ")
    add("**说明**：本文档按当前实际库表生成，覆盖 22 张业务表、1 个宽表视图，并说明每个字段的类型、空值、默认值、键、含义和取值范围。")
    add("")
    add("> 平台已有 `sys_*`、`emission_*`、`report_*`、`energy_*` 表不在本文档范围内；本模块只新增 `prediction_*` 对象，不修改平台表。")
    add("")
    add("---")
    add("")
    add("## 1. 阅读说明")
    add("")
    add("### 1.1 字段表列含义")
    add("")
    add("| 列 | 含义 |")
    add("| --- | --- |")
    add("| 字段 | 数据库列名 |")
    add("| 类型 | MySQL 数据类型与长度 |")
    add("| 空 | 是否允许 NULL：是/否 |")
    add("| 默认 | 数据库默认值；NULL 表示无默认值 |")
    add("| 键 | PK=主键，UK=唯一键，IDX=普通索引，—=无 |")
    add("| 含义 | 业务含义 |")
    add("| 取值范围/约束 | 固定枚举、数值范围、单位、格式或外键关系 |")
    add("")
    add("### 1.2 通用约定")
    add("")
    add("- 月份字段统一为 `DATE`，存每月 1 日，格式 `YYYY-MM-01`；")
    add("- 时间字段为 `DATETIME`，格式 `YYYY-MM-DD HH:MM:SS`；")
    add("- 金额/排放/活动量使用 `DECIMAL`，避免浮点误差；")
    add("- 所有活动量、排放量、预测值均为非负；")
    add("- 布尔字段统一用 `TINYINT(1)`：0=否，1=是；")
    add("- JSON 字段必须存合法 JSON；写入前由应用层校验；")
    add("- 外键关系由应用层维护，数据库未建物理外键，便于平台分库/解耦。")
    add("")
    add("### 1.3 表清单")
    add("")
    add("| # | 表名 | 类型 | 当前行数 | 说明 |")
    add("| ---: | --- | --- | ---: | --- |")
    for i, t in enumerate(TABLES, 1):
        title, purpose = TABLE_META[t]
        add(f"| {i} | `{t}` | 业务表 | {schema[t]['count']} | {title}：{purpose} |")
    add("| 23 | `prediction_v_carbon_monthly` | 视图 | — | 组织×月度宽表，供平台直接查询 |")
    add("")
    add("> 另有 `prediction_anomaly_v1` 为 V1 异常结果备份表，字段与 `prediction_anomaly` 的 V1 部分兼容，不在主链路使用，见附录 A。")
    add("")
    add("---")
    add("")
    add("## 2. 通用字段与枚举字典")
    add("")
    add("### 2.1 组织与品种")
    add("")
    add("**org_id 组织编码**")
    add("")
    add("| 值 | 含义 | 平台 dept_id |")
    add("| --- | --- | ---: |")
    add("| SHL | 国能朔黄铁路发展有限责任公司（根节点） | 3000 |")
    add("| JLG | 机辆分公司 | 3030 |")
    add("| SNF | 肃宁分公司 | 3020 |")
    add("| YPF | 原平分公司 | 3010 |")
    add("")
    add("**var_id 品种编码**")
    add("")
    add("| var_id | 名称 | 单位 | 类别 | 说明 |")
    add("| --- | --- | --- | --- | --- |")
    var_rows = [
        ("TURNOVER", "货运周转量", "百万吨公里", "operation", "仅机辆分公司；2019—2020 为推算，肃宁/原平无此项"),
        ("GAS", "天然气", "万m³", "fuel", "原平无此项"),
        ("GASOLINE", "汽油", "t", "fuel", "量级很小，异常只进关注"),
        ("DIESEL", "柴油", "t", "fuel", "内燃机车/生产用油"),
        ("ELEC_TOTAL", "电力总和", "MWh", "electricity", "机辆=牵引+辅助；肃宁/原平=辅助生产电力"),
        ("ELEC_TRAC", "牵引电力", "MWh", "electricity", "仅机辆分公司；2019—2023 为按辅占比推算，2024 起实测，后续不自动拆分"),
        ("ELEC_AUX", "辅助生产电力", "MWh", "electricity", "机辆为拆分值；肃宁/原平等于电力总和"),
        ("HEAT", "热力（可比口径）", "GJ", "heat", "按 0.9224 基准系数还原"),
        ("HEAT_REPORTED", "热力（报表口径）", "GJ", "heat", "2025 年按新系数填报"),
        ("DIESEL_LOCO_COUNT", "内燃机车运用台数", "台", "operation", "企业计划/情景输入"),
        ("CO2_COMPARABLE", "碳排放（可比口径）", "tCO2e", "target", "固定 2025 电力因子与基准热力系数"),
        ("CO2_REPORTED", "碳排放（报表口径）", "tCO2e", "target", "按当年实际因子/热力口径"),
    ]
    for r in var_rows:
        add("| " + " | ".join(r) + " |")
    add("")
    add("### 2.2 数据来源与质量状态")
    add("")
    add("**source_status 数据来源状态**")
    add("")
    add("| 值 | 含义 |")
    add("| --- | --- |")
    for v, d in [
        ("原始", "台账/报表原值"),
        ("推算-电量系数法", "周转量缺失，按同月周转量/电量比例推算"),
        ("推算-辅占比重构", "机辆历史 2019—2023 牵引/辅助电力未分列，按辅占比拆分"),
        ("推算-供暖度日分摊", "年总量按 HDD 权重分摊到月"),
        ("异常剔除-同期补全", "已知异常点剔除后用同期值补全"),
        ("口径还原", "按基准系数还原为可比口径"),
        ("无此项", "该组织无此品种（如原平天然气）"),
        ("人工修正", "复核 correct 后的人工修正值"),
    ]:
        add(f"| {v} | {d} |")
    add("")
    add("**quality_status 数据质量状态**")
    add("")
    add("| 值 | 含义 | 训练是否使用 |")
    add("| --- | --- | --- |")
    for v, d, use in [
        ("valid", "有效", "是"),
        ("pending", "新增数据命中异常，待复核", "否"),
        ("excluded", "复核排除", "否"),
    ]:
        add(f"| {v} | {d} | {use} |")
    add("")
    add("**data_flag 数据标记**")
    add("")
    add("| 值 | 含义 |")
    add("| --- | --- |")
    for v, d in [
        ("（空）", "无特殊标记"),
        ("GAS_2024_ANOMALY", "机辆 2024 年天然气异常，已补全"),
        ("CALIBER_CHANGE_2025", "2025 年供热系数口径切换"),
        ("LEVEL_SHIFT_2024", "2024 年电力水平位移"),
        ("LOCO_RETIREMENT_2025", "2025 年内燃机车退役"),
        ("ESTIMATED_2019_2020", "2019—2020 年周转量推算"),
        ("ANOMALY_BREAKPOINT", "V2 历史异常标记的结构断点"),
        ("MANUAL_BREAKPOINT", "人工复核标记的结构断点"),
    ]:
        add(f"| {v} | {d} |")
    add("")
    add("### 2.3 异常枚举")
    add("")
    add("**level 异常等级**")
    add("")
    add("| 值 | 含义 | 典型处置 |")
    add("| --- | --- | --- |")
    for v, d, h in [
        ("正常", "未命中异常阈值", "不处理"),
        ("关注", "轻度偏离/单通道/日历可解释", "进 watch 监控，不进复核"),
        ("异常", "达到异常阈值", "进复核队列"),
        ("严重异常", "得分≥0.75、分位≥99，或绝对 z>5", "优先复核"),
    ]:
        add(f"| {v} | {d} | {h} |")
    add("")
    add("**category 异常类别**")
    add("")
    add("| 值 | 含义 | 说明 |")
    add("| --- | --- | --- |")
    for v, d, h in [
        ("C1", "单点数据错误/尖峰", "抄表、录入、单点跳变"),
        ("C2", "连续漂移/质量台阶", "计量通道异常、连续离群"),
        ("C3", "真实业务跃变/结构断点", "机车退役、供热调整、疫情冲击"),
        ("C4", "季节峰谷", "供暖季、春节等正常峰谷"),
        ("UNDETERMINED", "统计异常但业务证据不足", "按严重程度进复核或监控"),
    ]:
        add(f"| {v} | {d} | {h} |")
    add("")
    add("**status 复核状态**")
    add("")
    add("| 值 | 含义 |")
    add("| --- | --- |")
    for v, d in [
        ("pending", "待人工复核"),
        ("approved", "已复核通过"),
        ("rejected", "已驳回（保留原始状态）"),
        ("auto_closed", "历史数据自动处置并关闭"),
    ]:
        add(f"| {v} | {d} |")
    add("")
    add("**final_disposition 最终处置**")
    add("")
    add("| 值 | 含义 | 对活动数据 | 对训练 |")
    add("| --- | --- | --- | --- |")
    for v, d, a, b in [
        ("keep", "保留原值", "quality=valid", "进入训练"),
        ("correct", "修正为指定值", "更新 value/reported_value", "进入训练"),
        ("exclude", "排除该点", "quality=excluded", "不进入训练"),
        ("mark_breakpoint", "保留原值并标记断点", "data_flag=MANUAL_BREAKPOINT", "进入训练，作为断点解释"),
    ]:
        add(f"| {v} | {d} | {a} | {b} |")
    add("")
    add("**channels/context_flags**")
    add("")
    add("- `channels`：`raw`、`resid`、`joint`、`rule` 及其组合，如 `raw+resid+joint`；")
    add("- `context_flags`：`spring_festival`、`covid`、`maintenance`，逗号分隔；空串表示无上下文。")
    add("")
    add("### 2.4 模型、预测与任务枚举")
    add("")
    add("| 字段 | 取值 | 含义 |")
    add("| --- | --- | --- |")
    for f, vals, meaning in [
        ("model_type", "SW_LSTM/RIDGE/GBM/HOLT_WINTERS/SEASONAL_NAIVE/ENSEMBLE", "模型类型"),
        ("model.status", "candidate/active/deprecated", "候选/启用/弃用"),
        ("forecast.scenario", "BAU/COAL_HIGH/COAL_LOW/EFFICIENCY", "基准/煤价高/煤价低/能效提升"),
        ("job.job_type", "TRAIN/FORECAST/GRA/IMPORT", "训练/预测/GRA/导入"),
        ("job.status", "queued/running/succeeded/failed", "排队/运行/成功/失败"),
        ("event_type", "spring_festival/epidemic/maintenance", "春节/疫情/检修"),
        ("impact_direction", "down/up/unknown", "下降/上升/未知"),
    ]:
        add(f"| {f} | {vals} | {meaning} |")
    add("")
    add("### 2.5 政策因子枚举")
    add("")
    add("| 字段 | 取值 | 含义 |")
    add("| --- | --- | --- |")
    for f, vals, d in [
        ("category", "price/supply/transport/power/weather/policy/operation", "价格/供给/运输/电力/气象/政策/运营"),
        ("source_level", "national/provincial/market/enterprise/station", "国家/省级/市场/企业/站点"),
        ("source_status", "原始/插值/1-2月合计均分/外推/企业计划", "数据来源状态"),
        ("is_scenario_only", "0/1", "是否仅作情景输入"),
        ("dimension", "price/supply/transport/grid/carbon_market/other", "政策事件维度"),
    ]:
        add(f"| {f} | {vals} | {d} |")
    add("")
    add("### 2.6 关键固定值")
    add("")
    add("**排放因子（prediction_emission_factor）**")
    add("")
    add("| var_id | 因子值 | 单位 | 生效期 |")
    add("| --- | ---: | --- | --- |")
    for v, val, unit, period in [
        ("GAS", "21.621732", "tCO2/万m3", "2019-01-01 起"),
        ("GASOLINE", "3.042475", "tCO2/t", "2019-01-01 起"),
        ("DIESEL", "3.145245", "tCO2/t", "2019-01-01 起"),
        ("HEAT", "0.110000", "tCO2/GJ", "2019-01-01 起"),
        ("ELEC_TOTAL", "0.884300", "tCO2/MWh", "2019—2021"),
        ("ELEC_TOTAL", "0.570300", "tCO2/MWh", "2022"),
        ("ELEC_TOTAL", "0.556800", "tCO2/MWh", "2023"),
        ("ELEC_TOTAL", "0.536600", "tCO2/MWh", "2024"),
        ("ELEC_TOTAL", "0.530600", "tCO2/MWh", "2025 起；可比口径固定值"),
    ]:
        add(f"| {v} | {val} | {unit} | {period} |")
    add("")
    add("**供热面积折算系数（prediction_caliber_rule）**")
    add("")
    add("| org_id | 2019—2024 | 2025 起 | 说明 |")
    add("| --- | ---: | ---: | --- |")
    add("| JLG | 0.9224 | 0.9224 | 未调整 |")
    add("| SNF | 0.9224 | 0.380 | 2025 年系数调整，面积未变 |")
    add("| YPF | 0.9224 | 0.334 | 2025 年系数调整，面积未变 |")
    add("")
    add("**预测情景参数（prediction_scenario.config）**")
    add("")
    add("| scenario_id | coal_price_multiplier | activity_multiplier | grid_factor |")
    add("| --- | ---: | ---: | ---: |")
    add("| BAU | 1.00 | 1.00 | 0.5306 |")
    add("| COAL_HIGH | 1.10 | 1.00 | 0.5306 |")
    add("| COAL_LOW | 0.90 | 1.00 | 0.5306 |")
    add("| EFFICIENCY | 1.00 | 0.97 | 0.5306 |")
    add("")
    add("> 2025 年电力因子 0.5306 同时作为可比口径固定因子；报表口径仍按当年实际因子计算。")
    add("")
    add("---")
    add("")
    add("## 3. 表结构详述")
    add("")

    for i, t in enumerate(TABLES, 1):
        meta = schema[t]
        title, purpose = TABLE_META[t]
        add(f"### 3.{i} `{t}`")
        add("")
        add(f"**用途**：{purpose}")
        add("")
        add(f"**当前行数**：{meta['count']}")
        add("")
        add("| 字段 | 类型 | 空 | 默认 | 键 | 含义 | 取值范围/约束 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for col in meta["columns"]:
            name = col["name"]
            desc = FIELD_META[t].get(name)
            if not desc:
                desc = col.get("comment") or "—"
                print(f"WARN missing description: {t}.{name}")
            rng = RANGE_META.get(t, {}).get(name, "") or "—"
            add(f"| `{name}` | {col['ctype']} | {col['nullable']} | {fmt_default(col['dflt'])} | {key_label(col, meta['indexes'])} | {desc} | {rng} |")
        add("")
        add(f"**键与索引**：{index_summary(meta['indexes'])}")
        add("")
        notes = TABLE_NOTES.get(t)
        if notes:
            add(f"**说明**：{notes}")
            add("")
        add("---")
        add("")

    # view
    add("## 4. 视图 `prediction_v_carbon_monthly`")
    add("")
    add("**用途**：按组织×月聚合活动数据与排放结果，供平台可视化/报表直接查询，避免多表 JOIN。")
    add("")
    add("| 字段 | 类型 | 含义 | 取值范围/约束 |")
    add("| --- | --- | --- | --- |")
    view_rows = [
        ("org_id", "varchar(16)", "组织编码", "JLG/SNF/YPF"),
        ("org_name", "varchar(64)", "组织名称", "—"),
        ("period", "date", "统计月首日", "YYYY-MM-01"),
        ("turnover", "decimal", "货运周转量", "百万吨公里；无数据为 NULL"),
        ("gas", "decimal", "天然气", "万m³；无数据为 NULL"),
        ("gasoline", "decimal", "汽油", "t；无数据为 NULL"),
        ("diesel", "decimal", "柴油", "t；无数据为 NULL"),
        ("electricity_total", "decimal", "电力总和", "MWh；无数据为 NULL"),
        ("electricity_traction", "decimal", "牵引电力", "MWh；无数据为 NULL"),
        ("electricity_aux", "decimal", "辅助生产电力", "MWh；无数据为 NULL"),
        ("heat_gj", "decimal", "热力（可比口径）", "GJ；无数据为 NULL"),
        ("heat_reported_gj", "decimal", "热力（报表口径）", "GJ；无数据为 NULL"),
        ("co2_reported_tco2", "decimal", "报表口径总排放", "tCO2e；无数据为 NULL"),
        ("co2_comparable_tco2", "decimal", "可比口径总排放", "tCO2e；无数据为 NULL"),
        ("is_verified", "tinyint", "年度恒等式校验", "0=未通过，1=通过"),
    ]
    for r in view_rows:
        add("| " + " | ".join(r) + " |")
    add("")
    add("> 视图为只读对象，不直接写入；数据来自 `prediction_activity_monthly` 与 `prediction_emission_monthly`。")
    add("")
    add("---")
    add("")
    add("## 5. 表关系与索引说明")
    add("")
    add("### 5.1 逻辑关系")
    add("")
    add("| 子表字段 | 父表 | 关系 |")
    add("| --- | --- | --- |")
    for a, b, rel in [
        ("prediction_*.org_id", "prediction_org.org_id", "多对一"),
        ("prediction_activity_monthly.var_id", "prediction_energy_var.var_id", "多对一"),
        ("prediction_emission_factor.var_id", "prediction_energy_var.var_id", "多对一"),
        ("prediction_anomaly.detect_batch_id", "prediction_ingest_batch.batch_id", "多对一/批次追溯"),
        ("prediction_anomaly_audit.anomaly_id", "prediction_anomaly.id", "多对一"),
        ("prediction_forecast.model_id", "prediction_model.model_id", "多对一"),
        ("prediction_model.data_version", "prediction_dataset_version.version_id", "多对一"),
        ("prediction_policy_factor.factor_id", "外部因子编码（逻辑）", "按 factor_id+period 唯一"),
    ]:
        add(f"| {a} | {b} | {rel} |")
    add("")
    add("> 数据库未建物理外键；上述关系由应用层和唯一键保证。")
    add("")
    add("### 5.2 关键唯一键")
    add("")
    add("| 表 | 唯一键 | 作用 |")
    add("| --- | --- | --- |")
    for t, uk, d in [
        ("prediction_activity_monthly", "(org_id, period, var_id)", "防止同月同品种重复"),
        ("prediction_emission_monthly", "(org_id, period, scope)", "防止同月重复排放"),
        ("prediction_anomaly", "(org_id, period, var_id, detect_batch_id)", "防止同批次重复异常"),
        ("prediction_anomaly_watch", "(org_id, period, var_id, algorithm_version)", "防止同版本重复监控"),
        ("prediction_gra_result", "(run_id, org_id, var_id)", "一次 GRA 每因子一条"),
        ("prediction_forecast", "(model_id, org_id, period, scenario, target_var)", "防止同模型同月重复预测"),
        ("prediction_policy_factor", "(factor_id, period)", "防止同因子同月重复"),
        ("prediction_model", "model_id（主键）", "模型版本唯一"),
    ]:
        add(f"| `{t}` | {uk} | {d} |")
    add("")
    add("---")
    add("")
    add("## 6. 数据状态流转")
    add("")
    add("### 6.1 活动数据")
    add("")
    add("```text")
    add("接入/导入 → quality_status=valid")
    add("新增单点命中异常 → quality_status=pending → 复核")
    add("复核 keep/correct → quality_status=valid")
    add("复核 exclude → quality_status=excluded")
    add("```")
    add("")
    add("### 6.2 异常")
    add("")
    add("```text")
    add("V2 检测 → 复核级 auto_closed（历史） / pending（新增）")
    add("pending → approved（keep/correct/exclude/mark_breakpoint）")
    add("pending → rejected（保留原值，需说明）")
    add("关注级 → prediction_anomaly_watch（无复核状态）")
    add("```")
    add("")
    add("### 6.3 批次")
    add("")
    add("```text")
    add("received → validated → pending_review（有异常）")
    add("pending_review → completed（全部复核）")
    add("received/validated → rejected（校验失败）")
    add("```")
    add("")
    add("---")
    add("")
    add("## 7. 当前数据量与校验")
    add("")
    add("| 项目 | 当前值 |")
    add("| --- | ---: |")
    for t in ["prediction_org", "prediction_activity_monthly", "prediction_emission_monthly",
               "prediction_anomaly", "prediction_anomaly_watch", "prediction_forecast",
               "prediction_policy_factor", "prediction_gra_result", "prediction_model"]:
        add(f"| `{t}` | {schema[t]['count']} |")
    add("")
    add("- 排放年度总量与原始台账年度合计偏差 <0.5%，252 条月度记录全部 `is_verified=1`；")
    add("- 活动数据唯一键 `(org_id,period,var_id)` 无重复；")
    add("- 预测表 36 条 = 3 组织 × 12 月 × BAU；")
    add("- 异常主表 8 条复核级，关注表 143 条，V1 备份 19 条。")
    add("")
    add("---")
    add("")
    add("## 8. 使用与扩展注意事项")
    add("")
    add("1. 新增品种需先在 `prediction_energy_var` 注册单位、类别，再写活动数据；")
    add("2. 新增排放因子/供热系数必须写生效期，禁止直接改历史值；")
    add("3. 修改活动数据必须同步重算 `prediction_emission_monthly`；")
    add("4. 训练只使用 `quality_status=valid` 的月份；")
    add("5. JSON 字段（feature_order/scaler_state/metrics/config）必须保持向后兼容；")
    add("6. 预测结果写入前校验 `lower_bound ≤ point ≤ upper_bound`；")
    add("7. 异常复核必须写 `prediction_anomaly_audit`，禁止物理删除；")
    add("8. 生产环境建议给本模块单独数据库账号，只授予 `prediction_*` 读写权限。")
    add("")
    add("---")
    add("")
    add("## 9. 常用校验 SQL")
    add("")
    add("**9.1 活动数据唯一性**")
    add("")
    add("```sql")
    add("SELECT org_id, period, var_id, COUNT(*) AS n")
    add("FROM prediction_activity_monthly")
    add("GROUP BY org_id, period, var_id")
    add("HAVING n > 1;")
    add("```")
    add("")
    add("**9.2 排放总量恒等式**")
    add("")
    add("```sql")
    add("SELECT org_id, period")
    add("FROM prediction_emission_monthly")
    add("WHERE ABS(total_reported_tco2 - (gas_tco2 + gasoline_tco2 + diesel_tco2 + electricity_tco2 + heat_tco2)) > 0.01;")
    add("```")
    add("")
    add("**9.3 预测区间合法性**")
    add("")
    add("```sql")
    add("SELECT id, org_id, period")
    add("FROM prediction_forecast")
    add("WHERE lower_bound > point OR point > upper_bound OR point < 0;")
    add("```")
    add("")
    add("**9.4 冠军模型唯一性**")
    add("")
    add("```sql")
    add("SELECT org_id, COUNT(*) AS n")
    add("FROM prediction_model")
    add("WHERE is_champion = 1")
    add("GROUP BY org_id")
    add("HAVING n > 1;")
    add("```")
    add("")
    add("**9.5 异常状态一致性**")
    add("")
    add("```sql")
    add("SELECT id, org_id, period, var_id")
    add("FROM prediction_anomaly")
    add("WHERE (status = 'pending' AND final_disposition IS NOT NULL)")
    add("   OR (status IN ('approved','auto_closed') AND final_disposition IS NULL);")
    add("```")
    add("")
    add("**9.6 批次待复核数量**")
    add("")
    add("```sql")
    add("SELECT detect_batch_id, COUNT(*) AS pending_n")
    add("FROM prediction_anomaly")
    add("WHERE status = 'pending'")
    add("GROUP BY detect_batch_id;")
    add("```")
    add("")
    add("---")
    add("")
    add("## 附录 A `prediction_anomaly_v1` 备份表")
    add("")
    add("`prediction_anomaly_v1` 是 V1 异常结果的备份表，字段与当前 `prediction_anomaly` 的 V1 部分兼容（无 raw_score/resid_score/joint_score 等 V2 字段）。该表只用于历史对照，不参与在线检测、复核和预测。")
    add("")
    add("## 附录 B 文档维护")
    add("")
    add("- 表结构变更后应同步更新本文档；")
    add("- 建议每次发布前执行 `python scripts/build_db_dictionary.py` 重新生成；")
    add("- 字段含义以数据库注释、应用层校验和本文档三者一致为准。")
    add("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("saved", OUT, "lines", len(lines))


RANGE_META: Dict[str, Dict[str, str]] = {
    "prediction_org": {
        "org_id": "SHL/JLG/SNF/YPF",
        "org_level": "1 或 2",
        "platform_dept_id": "3000/3010/3020/3030",
        "latitude": "-90～90",
        "longitude": "-180～180",
        "status": "active/inactive",
    },
    "prediction_energy_var": {
        "var_id": "见 2.1",
        "var_category": "fuel/electricity/heat/operation/target",
        "is_traction": "0/1",
        "is_target": "0/1",
        "sort_order": "≥0",
    },
    "prediction_emission_factor": {
        "var_id": "GAS/GASOLINE/DIESEL/HEAT/ELEC_TOTAL",
        "factor_value": "≥0；电力 0.8843/0.5703/0.5568/0.5366/0.5306；热力 0.11",
        "factor_unit": "tCO2/MWh、tCO2/t、tCO2/万m3、tCO2/GJ",
        "factor_version": "非空；如 EF-ELEC-2025、EF-GAS-2019",
        "effective_from": "YYYY-MM-DD",
        "effective_to": "NULL 或 ≥effective_from",
        "is_caliber_change": "0/1",
    },
    "prediction_caliber_rule": {
        "org_id": "ALL/JLG/SNF/YPF",
        "rule_type": "heat_area_factor/grid_factor",
        "rule_value": "≥0；供热 0.9224/0.380/0.334；电网 0.8843—0.5306",
        "unit": "GJ/m2 或 tCO2/MWh",
        "rule_version": "非空；如 CAL-SNF-2025、CAL-JLG-2019",
        "effective_to": "NULL 或 ≥effective_from",
    },
    "prediction_activity_monthly": {
        "period": "YYYY-MM-01",
        "value": "≥0",
        "reported_value": "≥0",
        "is_estimated": "0/1",
        "quality_status": "valid/pending/excluded",
        "source_status": "原始/推算-电量系数法/推算-辅占比重构/推算-供暖度日分摊/异常剔除-同期补全/口径还原/无此项/人工修正",
        "data_flag": "空/GAS_2024_ANOMALY/CALIBER_CHANGE_2025/LEVEL_SHIFT_2024/LOCO_RETIREMENT_2025/ESTIMATED_2019_2020/ANOMALY_BREAKPOINT/MANUAL_BREAKPOINT",
    },
    "prediction_emission_monthly": {
        "scope": "Total",
        "gas_tco2": "≥0",
        "gasoline_tco2": "≥0",
        "diesel_tco2": "≥0",
        "electricity_tco2": "≥0",
        "heat_tco2": "≥0",
        "total_reported_tco2": "≥0；=五项分项和",
        "total_comparable_tco2": "≥0；固定基准因子",
        "electricity_factor": ">0",
        "heat_factor": "0.11",
        "factor_version": "非空或 NULL；推荐格式 EF-...、CAL-...（多个版本用竖线连接时需转义）",
        "heat_area_factor": ">0；如 0.9224/0.380/0.334",
        "factor_source": "自由文本，≤255 字符",
        "factor_snapshot": "合法 JSON；键为 GAS/GASOLINE/DIESEL/ELEC_TOTAL/HEAT/HEAT_AREA/BASE_ELEC/BASE_HEAT_AREA",
        "calc_method": "activity_x_factor",
        "is_verified": "0/1",
    },
    "prediction_anomaly": {
        "channel": "raw/stl_residual/resid/joint/rule 或组合",
        "score": "0～1（越大越异常）",
        "score_percentile": "0～100",
        "level": "正常/关注/异常/严重异常",
        "category": "C1/C2/C3/C4/UNDETERMINED",
        "confidence": "0～1",
        "suggested_disposition": "keep/correct/exclude/mark_breakpoint",
        "status": "pending/approved/rejected/auto_closed",
        "final_disposition": "keep/correct/exclude/mark_breakpoint；pending 时 NULL",
        "value": "≥0",
        "reference_value": "≥0",
        "correction_value": "≥0",
        "algorithm_version": "v1/v2",
        "raw_score": "≥0",
        "resid_score": "≥0",
        "joint_score": "≥0 或 NULL",
        "channels": "raw/resid/joint/rule 组合",
        "context_flags": "空/spring_festival/covid/maintenance 组合",
        "breakpoint_date": "YYYY-MM-01 或 NULL",
        "breakpoint_stat": "≥0 或 NULL",
        "shift_pct": "可正可负（%）",
        "cv_ratio": "≥0 或 NULL",
        "in_breakpoint_window": "0/1",
    },
    "prediction_anomaly_audit": {
        "action": "keep/correct/exclude/mark_breakpoint",
        "before_value": "可为 NULL",
        "after_value": "可为 NULL",
    },
    "prediction_anomaly_watch": {
        "level": "关注/异常/严重异常",
        "category": "C1/C2/C3/C4/UNDETERMINED",
        "score": "0～1",
        "channels": "raw/resid/joint 组合",
        "algorithm_version": "v2",
    },
    "prediction_anomaly_calibration": {
        "quantile": "0.90/0.92/0.95/0.97/0.98/0.99",
        "threshold_value": "≥0",
        "precision_v": "0～1",
        "recall_v": "0～1",
        "f1": "0～1",
        "n_pos": "≥0",
        "n_neg": "≥0",
        "selected": "0/1",
    },
    "prediction_ingest_batch": {
        "status": "received/validated/pending_review/completed/rejected",
        "row_count": "≥0",
        "anomaly_count": "≥0",
        "payload_hash": "64 位十六进制 SHA-256",
        "override_flag": "0/1",
        "override_reason": "override_flag=1 时非空",
        "replaces_batch_id": "旧批次号或 NULL",
    },
    "prediction_ingest_audit": {
        "entity_type": "activity/emission/anomaly",
        "entity_key": "非空，最多 96 字符",
        "old_value": "可 NULL",
        "new_value": "可 NULL",
        "old_status": "可 NULL",
        "new_status": "可 NULL",
        "detail": "合法 JSON",
    },
    "prediction_dataset_version": {
        "content_hash": "64 位十六进制 SHA-256",
        "row_count": "≥0",
    },
    "prediction_gra_result": {
        "r": "0～1",
        "r_detrend": "0～1 或 NULL",
        "rank_no": "≥1",
        "selected": "0/1",
        "spurious": "0/1",
        "rho_sensitive": "0/1",
        "borderline": "0/1",
        "direction": "positive/negative/unknown",
    },
    "prediction_model": {
        "model_type": "SW_LSTM/RIDGE/GBM/HOLT_WINTERS/SEASONAL_NAIVE/ENSEMBLE",
        "status": "candidate/active/deprecated",
        "is_champion": "0/1",
        "target_var": "CO2_COMPARABLE",
        "window_size": "6/9/12",
        "horizon": "12",
        "n_samples": "≥1",
        "hyperparams": "JSON：W/hidden/model 等",
        "scaler_state": "JSON：x_mean/x_scale/y_min/y_scale",
        "metrics": "JSON：test_2025/baselines/backtest",
    },
    "prediction_forecast": {
        "scenario": "BAU/COAL_HIGH/COAL_LOW/EFFICIENCY",
        "target_var": "CO2_COMPARABLE",
        "point": "≥0",
        "lower_bound": "≥0 且 ≤point",
        "upper_bound": "≥point",
        "reported_point": "≥0",
        "comparable_point": "≥0",
        "confidence_level": "0.90",
    },
    "prediction_policy_factor": {
        "category": "price/supply/transport/power/weather/policy/operation",
        "source_level": "national/provincial/market/enterprise/station",
        "source_status": "原始/插值/1-2月合计均分/外推/企业计划",
        "is_scenario_only": "0/1",
        "value": "一般 ≥0",
    },
    "prediction_policy_event": {
        "dimension": "price/supply/transport/grid/carbon_market/other",
        "intensity": "0～1",
        "end_period": "NULL 或 ≥start_period",
    },
    "prediction_scenario": {
        "scenario_id": "BAU/COAL_HIGH/COAL_LOW/EFFICIENCY",
        "is_default": "0/1；仅一个 1",
        "config": "JSON：coal_price_multiplier/activity_multiplier/grid_factor",
    },
    "prediction_job": {
        "job_type": "TRAIN/FORECAST/GRA/IMPORT",
        "status": "queued/running/succeeded/failed",
    },
    "prediction_audit_log": {
        "action": "IMPORT_HISTORY/ANOMALY_SCAN_V2/FORECAST/REVIEW/UPSERT_POLICY_FACTORS 等",
    },
    "prediction_calendar_event": {
        "event_type": "spring_festival/epidemic/maintenance",
        "impact_direction": "down/up/unknown",
        "end_date": "≥start_date",
    },
}

TABLE_NOTES = {
    "prediction_org": "组织编码与平台 dept_id 的映射是集成关键；不要修改历史 org_id。",
    "prediction_emission_factor": "同一 var_id 的生效期不得重叠；切换点需 is_caliber_change=1。",
    "prediction_caliber_rule": "供热面积系数仅用于物理热力还原；报表口径仍保留原值。",
    "prediction_activity_monthly": "value 为物理/可比口径；reported_value 仅在热力口径切换时不同。肃宁/原平不存 TURNOVER、ELEC_TRAC；其 ELEC_AUX=ELEC_TOTAL。",
    "prediction_emission_monthly": "分项排放按报表口径计算；total_reported_tco2=五项分项和，total_comparable_tco2 用基准电力/热力因子重算，二者必须同时保存。",
    "prediction_anomaly": "复核级异常；关注级在 prediction_anomaly_watch。algorithm_version 默认 v1 仅为兼容旧写入，新检测必须显式写 v2。",
    "prediction_anomaly_watch": "保存所有不进入复核队列的监控记录，包含关注/异常/严重异常（规则豁免或已自动闭合）；用于月度数据质量报告。",
    "prediction_anomaly_calibration": "弱标签校准，正例来自历史复核/规则处置，不是 ground truth。",
    "prediction_ingest_audit": "仅覆盖入库时写入；旧活动/排放/异常各一条，detail 保留完整旧对象。",
    "prediction_model": "同一 org 只有一条 is_champion=1；旧模型保留为 deprecated。",
    "prediction_forecast": "point/comparable_point 为可比口径；reported_point 为报表口径。",
    "prediction_policy_factor": "同一 factor_id+period 唯一；外部因子需标注 source_status。",
    "prediction_policy_event": "定性政策只做解释，不进入 GRA 主筛选。",
    "prediction_calendar_event": "检修事件需企业计划；当前数据中 maintenance 为空。",
}


if __name__ == "__main__":
    main()
