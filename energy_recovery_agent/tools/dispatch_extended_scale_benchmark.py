# 模块功能说明：按冻结的固定时域和扩展时域口径受监控执行12/16列车规模测试。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "paper" / "experiments" / "dispatch_extended_scale_test_plan.json"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "dispatch_extended_scale_benchmark"

from tools.algorithm_scale_stability_benchmark import (
    _extract_dispatch_result,
    _run_monitored,
)
from tools.dispatch_capacity_quality_benchmark import _extra_dispatch_metrics


def load_plan(path: Path) -> dict[str, Any]:
    """读取并验证扩展规模测试计划的基本结构。"""

    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = plan.get("planned_cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("扩展规模计划必须包含非空 planned_cases。")
    case_ids = [str(case.get("case_id", "")) for case in cases]
    if not all(case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("扩展规模案例 ID 必须非空且唯一。")
    return plan


def command_for_case(case: dict[str, Any], common: dict[str, Any], output_dir: Path) -> list[str]:
    """将冻结案例转换为统一项目入口命令。"""

    required = (
        "case_id", "heavy_count", "empty_count", "horizon_s",
        "heavy_headway_s", "empty_headway_s", "phase_s",
        "search_min_headway_s", "search_max_headway_s", "search_max_phase_s",
    )
    missing = [field for field in required if field not in case]
    if missing:
        raise ValueError(f"扩展规模案例缺少字段：{missing}")
    return [
        sys.executable,
        "run_project.py",
        "dispatch-case",
        "--output-dir", str(output_dir),
        "--heavy-count", str(case["heavy_count"]),
        "--empty-count", str(case["empty_count"]),
        "--horizon-s", str(case["horizon_s"]),
        "--baseline-heavy-headway-s", str(case["heavy_headway_s"]),
        "--baseline-empty-headway-s", str(case["empty_headway_s"]),
        "--baseline-phase-s", str(case["phase_s"]),
        "--search-min-headway-s", str(case["search_min_headway_s"]),
        "--search-max-headway-s", str(case["search_max_headway_s"]),
        "--search-max-phase-s", str(case["search_max_phase_s"]),
        "--population-size", str(common["population_size"]),
        "--generations", str(common["generations"]),
        "--seed", str(common["seed"]),
        "--settlement-step-s", str(common["settlement_step_s"]),
    ]


def _service_population(output_dir: Path, case: dict[str, Any]) -> dict[str, Any]:
    """核对算法输出是否保留请求的重空服务数量。"""

    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        return {
            "selected_heavy_count": None,
            "selected_empty_count": None,
            "service_population_complete": False,
        }
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    departures = summary.get("optimized_departures", {})
    heavy_count = len(departures.get("heavy_departures_s", []))
    empty_count = len(departures.get("empty_departures_s", []))
    return {
        "selected_heavy_count": heavy_count,
        "selected_empty_count": empty_count,
        "service_population_complete": (
            heavy_count == int(case["heavy_count"])
            and empty_count == int(case["empty_count"])
        ),
    }


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """写出扁平化运行记录。"""

    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            }
            for row in rows
        )


def _read_quality_comparison(output_dir: Path) -> dict[str, Any]:
    """读取基线与选中候选的关键质量指标，供跨案例报告比较。"""

    path = Path(output_dir) / "kpi_summary.csv"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        by_case = {row["case"]: row for row in csv.DictReader(handle)}
    if "baseline" not in by_case or "optimized" not in by_case:
        return {}

    baseline = by_case["baseline"]
    selected = by_case["optimized"]

    def number(row: dict[str, str], field: str) -> float:
        return float(row[field])

    def integer(row: dict[str, str], field: str) -> int:
        return int(float(row[field]))

    def percent_change(before: float, after: float) -> Optional[float]:
        if before == 0.0:
            return None
        return round((after - before) / before * 100.0, 6)

    baseline_grid = number(baseline, "grid_kwh")
    selected_grid = number(selected, "grid_kwh")
    baseline_wasted = number(baseline, "wasted_kwh")
    selected_wasted = number(selected, "wasted_kwh")
    baseline_cost = number(baseline, "total_cost")
    selected_cost = number(selected, "total_cost")
    return {
        "baseline_resource_conflict_count": integer(baseline, "resource_conflict_count"),
        "selected_resource_conflict_count": integer(selected, "resource_conflict_count"),
        "baseline_constraint_violation": number(baseline, "constraint_violation"),
        "selected_constraint_violation": number(selected, "constraint_violation"),
        "baseline_grid_kwh": baseline_grid,
        "selected_grid_kwh": selected_grid,
        "grid_change_pct": percent_change(baseline_grid, selected_grid),
        "baseline_wasted_kwh": baseline_wasted,
        "selected_wasted_kwh": selected_wasted,
        "wasted_change_pct": percent_change(baseline_wasted, selected_wasted),
        "baseline_recovery_rate": number(baseline, "recovery_rate"),
        "selected_recovery_rate": number(selected, "recovery_rate"),
        "baseline_total_cost": baseline_cost,
        "selected_total_cost": selected_cost,
        "cost_change_pct": percent_change(baseline_cost, selected_cost),
    }


def _write_report(output_dir: Path, rows: Sequence[dict[str, Any]]) -> None:
    """生成固定时域和扩展时域分组报告。"""

    lines = [
        "# 重空协同调度12/16列车扩展规模基准",
        "",
        "固定时域案例评价运输任务密度和资源压力；扩展时域案例评价软件计算规模。两组结果不得合并拟合。",
    ]
    for scope, title in (
        ("fixed_horizon_transport_density", "固定时域口径"),
        ("expanded_horizon_computational_scaling", "扩展时域口径"),
    ):
        lines.extend([
            "",
            f"## {title}",
            "",
            "| 案例 | 列车数 | 时域/s | 耗时/s | 峰值内存/MB | 完成 | 服务完整 | 核心稳健可行 | 标称回退 |",
            "| --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |",
        ])
        selected = [row for row in rows if row["scope"] == scope]
        if not selected:
            lines.append("| 尚未执行 | - | - | - | - | - | - | - | - |")
        for row in selected:
            lines.append(
                f"| {row['case_id']} | {row['train_count']} | {row['horizon_s']} | "
                f"{row['wall_time_s']} | {row['peak_rss_mb']} | "
                f"{'是' if row['passed'] else '否'} | "
                f"{'是' if row['service_population_complete'] else '否'} | "
                f"{'是' if row.get('core_robust_feasible') else '否'} | "
                f"{'是' if row.get('nominal_fallback_used') else '否'} |"
            )
    lines.extend([
        "",
        "## 解质量诊断",
        "",
        "| 案例 | 基线/候选资源冲突 | 基线/候选约束违反度 | 电网购电变化 | 弃能变化 | 回收率（基线→候选） | 总成本变化 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in rows:
        if "baseline_constraint_violation" not in row:
            continue
        lines.append(
            f"| {row['case_id']} | {row['baseline_resource_conflict_count']}→{row['selected_resource_conflict_count']} | "
            f"{row['baseline_constraint_violation']:.6f}→{row['selected_constraint_violation']:.6f} | "
            f"{row['grid_change_pct']:+.3f}% | {row['wasted_change_pct']:+.3f}% | "
            f"{row['baseline_recovery_rate']:.4f}→{row['selected_recovery_rate']:.4f} | "
            f"{row['cost_change_pct']:+.3f}% |"
        )
    feasible_rows = [row for row in rows if row.get("core_robust_feasible")]
    infeasible_rows = [row for row in rows if not row.get("core_robust_feasible")]
    lines.append("")
    if feasible_rows:
        lines.append(
            "核心稳健可行案例的能耗和成本变化已经通过当前规划/占位参数下的完整约束评价；正式数据到位后仍须重新校准和复验。"
        )
    if infeasible_rows:
        case_names = "、".join(str(row["case_id"]) for row in infeasible_rows)
        lines.append(
            f"{case_names} 未通过核心稳健可行性约束，其能耗和成本变化只用于诊断搜索方向，不能作为可实施优化收益。"
        )
    lines.extend(["", "## 本轮结论", ""])
    completed = [row for row in rows if row.get("passed")]
    if completed:
        max_timeout_ratio = max(
            float(row["wall_time_s"]) / float(row["timeout_limit_s"])
            for row in completed
        )
        peak_memory = max(float(row["peak_rss_mb"]) for row in completed)
        robust_count = sum(bool(row.get("core_robust_feasible")) for row in completed)
        phase5_triggered = max_timeout_ratio >= 0.8
        lines.extend([
            f"- {len(completed)} 个案例均在监控门限内完成；最大耗时占门限 {max_timeout_ratio * 100:.1f}%，峰值内存 {peak_memory:.3f} MB。",
            f"- 找到核心稳健可行解的案例数为 {robust_count}/{len(completed)}；资源可行性与程序是否超时分开判定。",
            (
                "- 已达到“成功运行耗时不低于门限80%”的第五阶段触发条件；下一步应剖析并降低扩展时域案例的定向修复成本。"
                if phase5_triggered
                else "- 当前未达到第五阶段架构优化的触发条件。"
            ),
        ])
    lines.extend([
        "",
        "## 解释边界",
        "",
        "超时只表示在给定门槛内没有完成；核心稳健不可行与计算超时必须分开报告。当前输入含规划和工程占位参数，结果不代表正式线路容量。",
    ])
    (output_dir / "DISPATCH_EXTENDED_SCALE_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_benchmark(
    *,
    plan_path: Path,
    output_dir: Path,
    case_ids: Sequence[str],
) -> dict[str, Any]:
    """按案例配置逐项运行，超时或中断后保留已完成结果。"""

    plan = load_plan(plan_path)
    common = dict(plan["common_settings"])
    by_id = {str(case["case_id"]): dict(case) for case in plan["planned_cases"]}
    selected_ids = list(dict.fromkeys(str(item) for item in case_ids))
    unknown = [case_id for case_id in selected_ids if case_id not in by_id]
    if not selected_ids or unknown:
        raise ValueError(f"扩展规模案例不能为空且必须已定义；未知案例：{unknown}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "benchmark_progress.json"
    rows: list[dict[str, Any]] = []
    if progress_path.is_file():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        rows = [dict(row) for row in progress.get("runs", []) if row.get("passed")]
        for row in rows:
            row.update(_read_quality_comparison(Path(row["output_dir"])))

    for case_id in selected_ids:
        if any(row.get("case_id") == case_id for row in rows):
            continue
        case = by_id[case_id]
        run_dir = output_dir / "runs" / case_id
        algorithm_dir = run_dir / "algorithm_output"
        command = command_for_case(case, common, algorithm_dir)
        observed = _run_monitored(command, run_dir, int(case["timeout_s"]))
        extracted = _extract_dispatch_result(algorithm_dir)
        population = _service_population(algorithm_dir, case)
        passed = (
            observed["return_code"] == 0
            and bool(extracted.get("summary_found"))
            and population["service_population_complete"]
        )
        row = {
            "case_id": case_id,
            "scope": case["scope"],
            "train_count": int(case["heavy_count"]) + int(case["empty_count"]),
            "horizon_s": int(case["horizon_s"]),
            "timeout_limit_s": int(case["timeout_s"]),
            "passed": passed,
            **observed,
            **extracted,
            **_extra_dispatch_metrics(algorithm_dir),
            **population,
            **_read_quality_comparison(algorithm_dir),
            "command": command,
            "output_dir": str(algorithm_dir),
        }
        rows.append(row)
        progress_path.write_text(
            json.dumps({"status": "running", "runs": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "schema_version": "1.0",
        "data_status": plan.get("data_status"),
        "plan_path": str(plan_path),
        "requested_case_ids": selected_ids,
        "all_requested_completed": all(
            any(row.get("case_id") == case_id and row.get("passed") for row in rows)
            for case_id in selected_ids
        ),
        "runs": rows,
    }
    (output_dir / "benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(output_dir / "benchmark_runs.csv", rows)
    _write_report(output_dir, rows)
    progress_path.write_text(
        json.dumps({"status": "completed", "runs": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立命令行入口。"""

    parser = argparse.ArgumentParser(description="受监控执行12/16列车双口径扩展规模基准。")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cases", nargs="+", default=["F12", "F16", "E12", "E16"])
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """执行命令并返回统一状态。"""

    args = build_parser().parse_args(argv)
    summary = run_benchmark(
        plan_path=args.plan,
        output_dir=args.output_dir,
        case_ids=args.cases,
    )
    print(json.dumps({
        "all_requested_completed": summary["all_requested_completed"],
        "report": str(args.output_dir / "DISPATCH_EXTENDED_SCALE_REPORT.md"),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["all_requested_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
