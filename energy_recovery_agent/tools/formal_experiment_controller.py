# 模块功能说明：本模块串联正式数据验收、基线审查、储能消融、运行图优化、结果审计和结果汇总。

from __future__ import annotations

"""正式数据到位后的可复现对比实验总控。

本模块不替换默认数据目录，也不修改甲方原始资料。只有通过严格正式
数据验收后，才会启动基线、储能消融和运行图优化；储能消融使用输出目录
中的派生数据副本，并记录其差异，避免污染正式基线输入。
"""

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# 支持从项目根目录和 tools 目录两种方式启动。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from formal_data_acceptance import write_report as write_acceptance_report
from result_quality_audit import audit_output_root, write_report as write_quality_report
from timetable_energy_audit import audit_timetable
from timetable_optimizer import optimize_timetable
from tools.official_data_readiness_pipeline import run_pipeline


DEFAULT_SEEDS = (11, 23, 37, 53, 71)
KPI_FIELDS = (
    "total_traction_kwh",
    "total_regen_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "wasted_kwh",
    "grid_kwh",
    "effective_regen_loss_kwh",
    "recovery_rate",
    "issue_count",
    "max_shift_min",
    "total_adjustment_min",
    "delay_min",
    "constraint_violation",
    "runtime_s",
)
RESULT_FIELDS = (
    "scenario_code",
    "algorithm",
    "seed",
    "status",
    "quality_accepted",
    "decision_action",
    "decision_reason",
    "selected_candidate_id",
    *KPI_FIELDS,
    "grid_saving_vs_baseline_kwh",
    "waste_reduction_vs_baseline_kwh",
    "effective_loss_reduction_vs_baseline_kwh",
    "output_dir",
    "error",
)
TIMESTEP_RESULT_FIELDS = (
    "time_step_s",
    "status",
    "quality_accepted",
    "runtime_s",
    "grid_kwh",
    "wasted_kwh",
    "effective_regen_loss_kwh",
    "recovery_rate",
    "grid_difference_vs_1s",
    "grid_error_pct_vs_1s",
    "wasted_difference_vs_1s",
    "wasted_error_pct_vs_1s",
    "effective_loss_difference_vs_1s",
    "effective_loss_error_pct_vs_1s",
    "recovery_rate_difference_vs_1s",
    "error",
    "output_dir",
)


def _json_load(path: Path) -> Dict[str, Any]:
    """读取一个 JSON 对象；缺失或格式错误时给出可定位错误。"""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"无法读取 JSON 汇总 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 汇总必须是对象：{path}")
    return payload


def _number(value: Any) -> Optional[float]:
    """将可用指标转换为浮点数，空值保持为空。"""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_kpis() -> Dict[str, Optional[float]]:
    """构造统一指标字段，避免不同方案的汇总列不一致。"""
    return {field: None for field in KPI_FIELDS}


def _audit_kpis(output_dir: Path) -> Dict[str, Optional[float]]:
    """从运行图审查的场景汇总中读取工程能量指标。"""
    rows: List[Dict[str, str]] = []
    scenario_path = output_dir / "scenario_summary.csv"
    if not scenario_path.is_file():
        raise ValueError(f"基线审查缺少场景汇总：{scenario_path}")
    with scenario_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"基线审查场景汇总为空：{scenario_path}")
    row = next((item for item in rows if item.get("scenario_id") == "storage_no_direct"), rows[0])
    values = _empty_kpis()
    mapping = {
        "total_traction_kwh": "total_traction_kwh",
        "total_regen_kwh": "total_regen_kwh",
        "battery_charge_kwh": "storage_absorbed_kwh",
        "battery_discharge_kwh": "storage_discharged_kwh",
        "wasted_kwh": "wasted_kwh",
        "grid_kwh": "grid_kwh",
        "effective_regen_loss_kwh": "effective_regen_loss_kwh",
        "recovery_rate": "recovery_rate",
        "issue_count": "issue_count",
    }
    for target, source in mapping.items():
        values[target] = _number(row.get(source))
    values["max_shift_min"] = 0.0
    values["total_adjustment_min"] = 0.0
    values["delay_min"] = 0.0
    values["constraint_violation"] = 0.0
    return values


def _optimizer_kpis(output_dir: Path) -> tuple[Dict[str, Optional[float]], Dict[str, Any]]:
    """读取优化决策所选候选的指标；保留门控理由以供论文解释。"""
    summary = _json_load(output_dir / "optimizer_summary.json")
    decision = summary.get("optimization_decision")
    if not isinstance(decision, dict):
        raise ValueError("优化汇总缺少 optimization_decision。")
    selected_id = str(decision.get("selected_candidate_id") or "")
    scores_path = output_dir / "candidate_scenario_scores.csv"
    if not scores_path.is_file():
        raise ValueError(f"优化输出缺少候选场景评分：{scores_path}")
    with scores_path.open("r", encoding="utf-8-sig", newline="") as handle:
        scores = list(csv.DictReader(handle))
    selected = next((row for row in scores if str(row.get("candidate_id", "")) == selected_id), None)
    if selected is None:
        raise ValueError(f"优化决策引用的候选不存在：{selected_id or '<空>'}")
    values = _empty_kpis()
    mapping = {
        "total_regen_kwh": "total_regen_kwh_est",
        "battery_charge_kwh": "storage_absorbed_kwh_est",
        "battery_discharge_kwh": "storage_discharged_kwh_est",
        "wasted_kwh": "wasted_kwh_est",
        "grid_kwh": "grid_kwh_est",
        "effective_regen_loss_kwh": "effective_regen_loss_kwh_est",
        "recovery_rate": "recovery_rate_est",
        "issue_count": "issue_count",
        "max_shift_min": "max_shift_min",
        "total_adjustment_min": "total_adjustment_min",
        "delay_min": "delay_min",
        "constraint_violation": "constraint_violation",
    }
    for target, source in mapping.items():
        values[target] = _number(selected.get(source))
    metadata = {
        "decision_action": decision.get("action", ""),
        "decision_reason": decision.get("reason", ""),
        "selected_candidate_id": selected_id,
    }
    return values, metadata


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """以统一编码输出机器可读结果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _calibration_evidence(summary_path: Optional[Path]) -> Dict[str, Any]:
    """读取校准质量证据；只记录和门禁，不隐式改变车辆动力学。"""
    if summary_path is None:
        return {
            "provided": False,
            "accepted": False,
            "summary_path": "",
            "sha256": "",
            "status": "not_provided",
            "failed_checks": [],
        }
    path = Path(summary_path)
    if not path.is_file():
        return {
            "provided": True,
            "accepted": False,
            "summary_path": str(path),
            "sha256": "",
            "status": "missing_summary",
            "failed_checks": ["missing_calibration_summary"],
        }
    payload = _json_load(path)
    quality = payload.get("quality_audit") if isinstance(payload.get("quality_audit"), dict) else payload
    accepted = bool(payload.get("publication_ready", quality.get("publication_ready", quality.get("accepted", False))))
    return {
        "provided": True,
        "accepted": accepted,
        "summary_path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": payload.get("status", "quality_summary"),
        "failed_checks": quality.get("failed_checks", []),
        "validation_metrics": quality.get("validation_metrics", {}),
        "note": "校准证据用于验证模型误差，不会在总控中隐式缩放牵引/再生功率。",
    }


def _write_kpi_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    """输出跨方案的单行 KPI 表。"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_timestep_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    """写出 F08 时间步长敏感性结果。"""

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIMESTEP_RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, summary: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> None:
    """生成供研究人员快速阅读的正式实验总控报告。"""
    readiness = summary["readiness"]
    lines = [
        "# 正式数据对比实验总控报告",
        "",
        f"- 总体状态：`{summary['status']}`",
        f"- 数据目录：`{summary['data_dir']}`",
        f"- 运行图：`{summary['timetable']}`",
        f"- 正式数据验收：`{readiness['accepted']}`",
        f"- 校准证据提供：`{summary['calibration']['provided']}`",
        f"- 校准质量通过：`{summary['calibration']['accepted']}`",
        f"- 评价窗口：`{summary['window_id']}`",
        f"- NSGA-II 固定种子：`{', '.join(str(seed) for seed in summary['seeds'])}`",
        "",
    ]
    if summary["status"] == "blocked":
        reasons = []
        if not readiness["accepted"]:
            reasons.append("正式数据验收未通过，请处理 `F00_readiness/FORMAL_DATA_ACCEPTANCE_REPORT.md`。")
        if summary["require_calibration"] and not summary["calibration"]["accepted"]:
            reasons.append("本次运行要求校准证据，但校准质量门禁未通过或未提供摘要。")
        lines.extend([
            "## 阻断原因",
            "",
            " ".join(reasons) + " 因此没有运行基线、储能消融或优化步骤。",
            "",
        ])
    else:
        lines.extend([
            "## 方案结果",
            "",
            "| 方案 | 状态 | 质量审计 | 门控结论 | 购电 kWh | 弃能 kWh | 有效再生损失 kWh | 相对基线购电节省 kWh | 输出目录 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ])
        for row in rows:
            lines.append(
                "| {scenario_code} | {status} | {quality_accepted} | {decision_action} {decision_reason} | {grid_kwh} | {wasted_kwh} | {effective_regen_loss_kwh} | {grid_saving_vs_baseline_kwh} | `{output_dir}` |".format(
                    **{key: "" if value is None else value for key, value in row.items()}
                )
            )
        timestep_rows = summary.get("timestep_sensitivity", [])
        if timestep_rows:
            lines.extend(
                [
                    "",
                    "## F08 时间步长敏感性",
                    "",
                    "| 时间步长 s | 状态 | 质量审计 | 购电 kWh | 相对1秒误差 % | 弃能 kWh | 相对1秒误差 % | 耗时 s |",
                    "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for row in timestep_rows:
                lines.append(
                    f"| {row['time_step_s']} | {row['status']} | {row['quality_accepted']} | {row.get('grid_kwh', '')} | "
                    f"{row.get('grid_error_pct_vs_1s', '')} | {row.get('wasted_kwh', '')} | "
                    f"{row.get('wasted_error_pct_vs_1s', '')} | {row.get('runtime_s', '')} |"
                )
        lines.extend([
            "",
            "## 解释边界",
            "",
            "只有状态为 completed、质量审计为 True 且候选满足硬约束的行可以进入论文比较。优化行出现 keep_baseline 表示在当前评价窗口和批准调整范围内没有足以替代现行运行图的净收益，不是执行失败。",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _disable_storage_variant(source_data_dir: Path, target_dir: Path) -> Dict[str, Any]:
    """创建无储能派生数据集，仅用于 F02 消融，不触碰正式输入。"""
    if target_dir.exists():
        raise FileExistsError(f"无储能派生目录已存在，拒绝混用旧结果：{target_dir}")
    shutil.copytree(source_data_dir, target_dir)
    battery_path = target_dir / "battery.json"
    power_arm_path = target_dir / "power_arm_intervals.csv"
    if not battery_path.is_file() or not power_arm_path.is_file():
        raise ValueError("无法构造无储能对照：缺少 battery.json 或 power_arm_intervals.csv。")
    battery = _json_load(battery_path)
    for key in ("capacity_kwh", "max_charge_power_kW", "max_discharge_power_kW"):
        battery[key] = 0.0
    battery["data_status"] = "derived_from_official_no_storage_ablation"
    battery["scenario_name"] = "formal_no_storage_ablation"
    battery["planning_assumption"] = False
    battery["note"] = "由冻结正式数据派生，仅用于无储能消融对照；正式原始数据未被修改。"
    _write_json(battery_path, battery)

    with power_arm_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if "storage_available" not in fieldnames:
        raise ValueError("无法构造无储能对照：power_arm_intervals.csv 缺少 storage_available。")
    for row in rows:
        row["storage_available"] = "否"
        for key in ("storage_section_id", "storage_start_km", "storage_end_km"):
            if key in fieldnames:
                row[key] = ""
        if "storage_status" in fieldnames:
            row["storage_status"] = "derived_no_storage_ablation"
        if "storage_note" in fieldnames:
            row["storage_note"] = "由冻结正式数据派生，仅用于无储能消融对照。"
    with power_arm_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "source_data_dir": str(source_data_dir),
        "derived_data_dir": str(target_dir),
        "purpose": "F02 无储能消融",
        "changes": {
            "battery.capacity_kwh": 0.0,
            "battery.max_charge_power_kW": 0.0,
            "battery.max_discharge_power_kW": 0.0,
            "power_arm_intervals.storage_available": "否（全部供电臂）",
        },
    }
    _write_json(target_dir / "DERIVED_NO_STORAGE_MANIFEST.json", manifest)
    return manifest


def _quality_check(output_dir: Path) -> Dict[str, Any]:
    """对一个方案目录执行输出质量审计并保存报告。"""
    report_dir = output_dir / "F99_quality_audit"
    quality = audit_output_root(output_dir)
    write_quality_report(quality, report_dir)
    return quality


def _new_record(scenario_code: str, algorithm: str, output_dir: Path, seed: Optional[int] = None) -> Dict[str, Any]:
    """创建统一方案记录。"""
    return {
        "scenario_code": scenario_code,
        "algorithm": algorithm,
        "seed": seed,
        "status": "pending",
        "quality_accepted": None,
        "decision_action": "",
        "decision_reason": "",
        "selected_candidate_id": "",
        **_empty_kpis(),
        "grid_saving_vs_baseline_kwh": None,
        "waste_reduction_vs_baseline_kwh": None,
        "effective_loss_reduction_vs_baseline_kwh": None,
        "output_dir": str(output_dir),
        "error": "",
    }


def _apply_deltas(rows: Sequence[Dict[str, Any]]) -> None:
    """将所有成功方案转换为相对 B0 的同窗口差值。"""
    baseline = next((row for row in rows if row["scenario_code"] == "F01_B0_baseline" and row["status"] == "completed"), None)
    if baseline is None:
        return
    for row in rows:
        if row["status"] != "completed":
            continue
        for source, target in (
            ("grid_kwh", "grid_saving_vs_baseline_kwh"),
            ("wasted_kwh", "waste_reduction_vs_baseline_kwh"),
            ("effective_regen_loss_kwh", "effective_loss_reduction_vs_baseline_kwh"),
        ):
            base_value, current_value = _number(baseline.get(source)), _number(row.get(source))
            if base_value is not None and current_value is not None:
                row[target] = round(base_value - current_value, 6)


def _run_audit_record(record: Dict[str, Any], timetable: Path, data_dir: Path, strict_visualizations: bool) -> None:
    """执行一个运行图审查方案并填充记录。"""
    output_dir = Path(record["output_dir"])
    started_at = time.perf_counter()
    try:
        summary = audit_timetable(
            timetable,
            output_dir,
            data_dir / "power_arm_intervals.csv",
            strict_visualizations=strict_visualizations,
            infrastructure_data_dir=data_dir,
        )
        if not summary.get("valid", False):
            raise ValueError("运行图审查返回 valid=false。")
        record.update(_audit_kpis(output_dir))
        record["decision_action"] = "baseline" if record["scenario_code"] == "F01_B0_baseline" else "ablation"
        quality = _quality_check(output_dir)
        record["quality_accepted"] = quality["accepted"]
        if not quality["accepted"]:
            raise ValueError(f"结果质量审计失败，错误数：{quality['error_count']}")
        record["status"] = "completed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    finally:
        record["runtime_s"] = round(time.perf_counter() - started_at, 6)


def _run_optimizer_record(
    record: Dict[str, Any],
    *,
    timetable: Path,
    data_dir: Path,
    mode: str,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
    max_candidates: int,
    population_size: int,
    generations: int,
    crossover_rate: float,
    mutation_rate: float,
    strict_visualizations: bool,
) -> None:
    """执行规则或 NSGA-II 优化方案并读取所选候选的指标。"""
    output_dir = Path(record["output_dir"])
    started_at = time.perf_counter()
    try:
        summary = optimize_timetable(
            timetable,
            output_dir,
            power_arm_path=data_dir / "power_arm_intervals.csv",
            max_shift_min=max_shift_min,
            step_min=step_min,
            max_dwell_extension_min=max_dwell_extension_min,
            max_candidates=max_candidates,
            mode=mode,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            seed=record["seed"],
            resource_data_dir=data_dir,
            strict_visualizations=strict_visualizations,
        )
        if not summary.get("valid", False):
            raise ValueError("运行图优化返回 valid=false。")
        values, metadata = _optimizer_kpis(output_dir)
        record.update(values)
        record.update(metadata)
        quality = _quality_check(output_dir)
        record["quality_accepted"] = quality["accepted"]
        if not quality["accepted"]:
            raise ValueError(f"结果质量审计失败，错误数：{quality['error_count']}")
        record["status"] = "completed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    finally:
        record["runtime_s"] = round(time.perf_counter() - started_at, 6)


def _run_timestep_sensitivity(
    *,
    timetable: Path,
    data_dir: Path,
    output_root: Path,
    steps_s: Sequence[int],
    strict_visualizations: bool,
) -> List[Dict[str, Any]]:
    """使用相同运行图和设备参数执行 F08 结算时间步长对照。"""

    rows: List[Dict[str, Any]] = []
    for step_s in steps_s:
        output_dir = output_root / f"F08_timestep_{step_s}s"
        row: Dict[str, Any] = {
            "time_step_s": step_s,
            "status": "pending",
            "quality_accepted": None,
            "runtime_s": None,
            "grid_kwh": None,
            "wasted_kwh": None,
            "effective_regen_loss_kwh": None,
            "recovery_rate": None,
            "grid_difference_vs_1s": None,
            "grid_error_pct_vs_1s": None,
            "wasted_difference_vs_1s": None,
            "wasted_error_pct_vs_1s": None,
            "effective_loss_difference_vs_1s": None,
            "effective_loss_error_pct_vs_1s": None,
            "recovery_rate_difference_vs_1s": None,
            "error": "",
            "output_dir": str(output_dir),
        }
        started_at = time.perf_counter()
        try:
            summary = audit_timetable(
                timetable,
                output_dir,
                data_dir / "power_arm_intervals.csv",
                strict_visualizations=strict_visualizations,
                infrastructure_data_dir=data_dir,
                settlement_time_step_s_override=step_s,
            )
            if not summary.get("valid", False):
                raise ValueError("时间步长审查返回 valid=false。")
            kpis = _audit_kpis(output_dir)
            for name in ("grid_kwh", "wasted_kwh", "effective_regen_loss_kwh", "recovery_rate"):
                row[name] = kpis[name]
            quality = _quality_check(output_dir)
            row["quality_accepted"] = quality["accepted"]
            if not quality["accepted"]:
                raise ValueError(f"时间步长结果质量审计失败，错误数：{quality['error_count']}")
            row["status"] = "completed"
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
        finally:
            row["runtime_s"] = round(time.perf_counter() - started_at, 6)
        rows.append(row)

    reference = next((row for row in rows if row["time_step_s"] == 1 and row["status"] == "completed"), None)
    if reference is None:
        return rows
    for row in rows:
        if row["status"] != "completed":
            continue
        for metric, difference_field, error_field in (
            ("grid_kwh", "grid_difference_vs_1s", "grid_error_pct_vs_1s"),
            ("wasted_kwh", "wasted_difference_vs_1s", "wasted_error_pct_vs_1s"),
            ("effective_regen_loss_kwh", "effective_loss_difference_vs_1s", "effective_loss_error_pct_vs_1s"),
        ):
            current, base = _number(row[metric]), _number(reference[metric])
            if current is not None and base is not None:
                difference = current - base
                row[difference_field] = round(difference, 9)
                row[error_field] = round(difference / abs(base) * 100.0, 9) if abs(base) > 1e-12 else None
        current_recovery, base_recovery = _number(row["recovery_rate"]), _number(reference["recovery_rate"])
        if current_recovery is not None and base_recovery is not None:
            row["recovery_rate_difference_vs_1s"] = round(current_recovery - base_recovery, 12)
    return rows


def run_formal_experiment_suite(
    *,
    data_dir: Path,
    source_dir: Path,
    timetable: Path,
    output_root: Path,
    window_id: str,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    max_shift_min: int = 10,
    step_min: int = 5,
    max_dwell_extension_min: int = 5,
    max_candidates: int = 50,
    population_size: int = 20,
    generations: int = 20,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.2,
    strict_visualizations: bool = True,
    calibration_summary: Optional[Path] = None,
    require_calibration: bool = False,
    settlement_steps_s: Sequence[int] = (1, 5, 10),
) -> Dict[str, Any]:
    """执行一个冻结数据版本、一个评价窗口的全部正式对比实验。

    返回的 `status` 为 `blocked`、`completed` 或 `failed`。`blocked` 只表示
    正式数据门禁未通过；该情况下不会运行任何算法步骤。
    """
    data_dir, source_dir, timetable, output_root = map(Path, (data_dir, source_dir, timetable, output_root))
    normalized_seeds = tuple(int(seed) for seed in seeds)
    normalized_steps = tuple(int(step) for step in settlement_steps_s)
    if not str(window_id).strip():
        raise ValueError("window_id 不能为空。")
    if not normalized_seeds or len(set(normalized_seeds)) != len(normalized_seeds):
        raise ValueError("seeds 必须为非空且互不重复的整数列表。")
    if 1 not in normalized_steps or len(set(normalized_steps)) != len(normalized_steps) or any(step <= 0 for step in normalized_steps):
        raise ValueError("settlement_steps_s 必须是包含1且互不重复的正整数列表。")
    if min(max_shift_min, step_min, max_dwell_extension_min, max_candidates, population_size, generations) <= 0:
        raise ValueError("调整范围、候选数、种群和代数必须为正数。")
    # 统一入口会在调用业务函数前自动写入 run_manifests；它属于运行追溯信息，
    # 不应被误判为旧实验结果。除此之外，目录必须为空，避免不同数据版本混用。
    existing_artifacts = []
    if output_root.exists():
        existing_artifacts = [path for path in output_root.iterdir() if path.name != "run_manifests"]
    if existing_artifacts:
        raise FileExistsError(f"实验输出目录已含业务结果，拒绝混入旧结果：{output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    readiness_dir = output_root / "F00_readiness"
    readiness = run_pipeline(data_dir, source_dir, timetable, readiness_dir, run_simulation=False)
    write_acceptance_report(readiness["acceptance"], readiness_dir)
    calibration = _calibration_evidence(calibration_summary)
    blocked_by_calibration = require_calibration and not calibration["accepted"]
    summary: Dict[str, Any] = {
        "schema_version": "1.0",
        "status": "blocked" if not readiness.get("accepted", False) or blocked_by_calibration else "running",
        "data_dir": str(data_dir),
        "source_dir": str(source_dir),
        "timetable": str(timetable),
        "output_root": str(output_root),
        "window_id": str(window_id),
        "seeds": list(normalized_seeds),
        "parameters": {
            "max_shift_min": max_shift_min,
            "step_min": step_min,
            "max_dwell_extension_min": max_dwell_extension_min,
            "max_candidates": max_candidates,
            "population_size": population_size,
            "generations": generations,
            "crossover_rate": crossover_rate,
            "mutation_rate": mutation_rate,
            "strict_visualizations": strict_visualizations,
            "settlement_steps_s": list(normalized_steps),
        },
        "readiness": {
            "accepted": bool(readiness.get("accepted", False)),
            "error_count": readiness.get("acceptance", {}).get("error_count"),
            "warning_count": readiness.get("acceptance", {}).get("warning_count"),
            "output_dir": str(readiness_dir),
        },
        "calibration": calibration,
        "require_calibration": require_calibration,
        "derived_configs": [],
        "scenarios": [],
        "timestep_sensitivity": [],
    }
    result_rows: List[Dict[str, Any]] = []
    if not readiness.get("accepted", False) or blocked_by_calibration:
        _write_json(output_root / "formal_experiment_summary.json", summary)
        _write_kpi_csv(output_root / "formal_experiment_kpi.csv", result_rows)
        _write_timestep_csv(output_root / "formal_timestep_sensitivity.csv", [])
        _write_report(output_root / "FORMAL_EXPERIMENT_REPORT.md", summary, result_rows)
        return summary

    baseline = _new_record("F01_B0_baseline", "baseline_audit", output_root / "F01_B0_baseline")
    _run_audit_record(baseline, timetable, data_dir, strict_visualizations)
    result_rows.append(baseline)

    no_storage_dir = output_root / "derived_configs" / "F02_no_storage_runtime"
    try:
        summary["derived_configs"].append(_disable_storage_variant(data_dir, no_storage_dir))
        no_storage = _new_record("F02_B1_no_storage", "no_storage_ablation", output_root / "F02_B1_no_storage")
        _run_audit_record(no_storage, timetable, no_storage_dir, strict_visualizations)
    except Exception as exc:
        no_storage = _new_record("F02_B1_no_storage", "no_storage_ablation", output_root / "F02_B1_no_storage")
        no_storage["status"] = "failed"
        no_storage["error"] = str(exc)
    result_rows.append(no_storage)

    rule = _new_record("F03_R1_rule", "rule", output_root / "F03_R1_rule")
    _run_optimizer_record(
        rule,
        timetable=timetable,
        data_dir=data_dir,
        mode="rule",
        max_shift_min=max_shift_min,
        step_min=step_min,
        max_dwell_extension_min=max_dwell_extension_min,
        max_candidates=max_candidates,
        population_size=population_size,
        generations=generations,
        crossover_rate=crossover_rate,
        mutation_rate=mutation_rate,
        strict_visualizations=strict_visualizations,
    )
    result_rows.append(rule)

    for seed in normalized_seeds:
        nsga = _new_record(f"F04_NSGA_seed_{seed}", "nsga2", output_root / f"F04_NSGA_seed_{seed}", seed=seed)
        _run_optimizer_record(
            nsga,
            timetable=timetable,
            data_dir=data_dir,
            mode="nsga2",
            max_shift_min=max_shift_min,
            step_min=step_min,
            max_dwell_extension_min=max_dwell_extension_min,
            max_candidates=max_candidates,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            strict_visualizations=strict_visualizations,
        )
        result_rows.append(nsga)

    timestep_rows = _run_timestep_sensitivity(
        timetable=timetable,
        data_dir=data_dir,
        output_root=output_root,
        steps_s=normalized_steps,
        strict_visualizations=strict_visualizations,
    )

    _apply_deltas(result_rows)
    summary["scenarios"] = result_rows
    summary["timestep_sensitivity"] = timestep_rows
    summary["status"] = "completed" if all(row["status"] == "completed" for row in [*result_rows, *timestep_rows]) else "failed"
    _write_json(output_root / "formal_experiment_summary.json", summary)
    _write_kpi_csv(output_root / "formal_experiment_kpi.csv", result_rows)
    _write_timestep_csv(output_root / "formal_timestep_sensitivity.csv", timestep_rows)
    _write_report(output_root / "FORMAL_EXPERIMENT_REPORT.md", summary, result_rows)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """提供独立脚本入口，统一入口会复用同一实现。"""
    parser = argparse.ArgumentParser(description="执行正式数据验收后的自动化对比实验总控。")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--timetable", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument("--settlement-steps-s", nargs="+", type=int, default=[1, 5, 10])
    parser.add_argument("--max-shift-min", type=int, default=10)
    parser.add_argument("--step-min", type=int, default=5)
    parser.add_argument("--max-dwell-extension-min", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--population-size", type=int, default=20)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--crossover-rate", type=float, default=0.9)
    parser.add_argument("--mutation-rate", type=float, default=0.2)
    parser.add_argument("--no-strict-visualizations", action="store_true")
    parser.add_argument("--calibration-summary", type=Path)
    parser.add_argument("--require-calibration", action="store_true")
    args = parser.parse_args(argv)
    summary = run_formal_experiment_suite(
        data_dir=args.data_dir,
        source_dir=args.source_dir,
        timetable=args.timetable,
        output_root=args.output_root,
        window_id=args.window_id,
        seeds=args.seeds,
        max_shift_min=args.max_shift_min,
        step_min=args.step_min,
        max_dwell_extension_min=args.max_dwell_extension_min,
        max_candidates=args.max_candidates,
        population_size=args.population_size,
        generations=args.generations,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        strict_visualizations=not args.no_strict_visualizations,
        calibration_summary=args.calibration_summary,
        require_calibration=args.require_calibration,
        settlement_steps_s=args.settlement_steps_s,
    )
    print(json.dumps({
        "status": summary["status"],
        "accepted": summary["readiness"]["accepted"],
        "scenario_count": len(summary["scenarios"]),
        "output_root": summary["output_root"],
    }, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
