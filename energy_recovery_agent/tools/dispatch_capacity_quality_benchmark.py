# 模块功能说明：测量重空协同调度的容量边界以及搜索预算与解质量的关系。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import platform
import sys

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psutil

from tools.algorithm_scale_stability_benchmark import (
    _command_for,
    _extract_dispatch_result,
    _run_monitored,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "real_shuohuang"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "dispatch_capacity_quality"
DEFAULT_BUDGETS = (("quick", 4, 1), ("standard", 8, 3), ("fine", 12, 4))


def _configure_matplotlib_fonts() -> None:
    """选择可用中文字体，确保基准图标题和坐标可读。"""

    available = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in ("Microsoft YaHei", "SimHei", "Arial Unicode MS"):
        if font_name in available:
            matplotlib.rcParams["font.sans-serif"] = [font_name]
            matplotlib.rcParams["font.family"] = "sans-serif"
            matplotlib.rcParams["axes.unicode_minus"] = False
            return


_configure_matplotlib_fonts()


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """按字段首次出现顺序写出便于复核的 CSV。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _extra_dispatch_metrics(output_dir: Path) -> dict[str, Any]:
    """读取容量分析需要、但通用稳定性提取器未返回的诊断指标。"""

    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    diagnostics = summary.get("optimizer_diagnostics", {})
    search = diagnostics.get("search_diagnostics", {})
    cache = search.get("candidate_evaluation_cache", {})
    return {
        "core_robust_feasible": bool(
            diagnostics.get("returned_candidate_core_robust_feasible", False)
        ),
        "nominal_fallback_used": bool(
            diagnostics.get("all_core_robust_candidates_infeasible", False)
        ),
        "evaluation_requests": cache.get("requests"),
        "actual_robust_evaluations": cache.get("actual_robust_evaluations"),
        "evaluation_cache_hits": cache.get("cache_hits"),
        "unique_cached_templates": cache.get("unique_cached_templates"),
        "energy_flat": search.get("energy_flat"),
        "recommended_search_profile": search.get("recommended_search_profile"),
    }


def _write_charts(rows: Sequence[dict[str, Any]], output_dir: Path) -> list[str]:
    """绘制容量耗时曲线与搜索预算质量曲线。"""

    paths: list[str] = []
    capacity = sorted(
        (row for row in rows if row["case_type"] == "capacity"),
        key=lambda row: row["train_count"],
    )
    if capacity:
        fig, axis = plt.subplots(figsize=(7.2, 4.4))
        axis.plot(
            [row["train_count"] for row in capacity],
            [row["wall_time_s"] for row in capacity],
            marker="o",
            color="#176B87",
        )
        axis.axhline(capacity[0]["timeout_limit_s"], color="#B23A48", linestyle="--", label="超时门槛")
        axis.set_xlabel("列车总数")
        axis.set_ylabel("端到端耗时（秒）")
        axis.set_title("重空协同调度容量耗时曲线")
        axis.grid(alpha=0.25)
        axis.legend()
        fig.tight_layout()
        path = output_dir / "capacity_runtime_curve.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path))

    budgets = sorted(
        (row for row in rows if row["case_type"] == "budget" and row.get("passed")),
        key=lambda row: row["evaluation_budget_upper"],
    )
    if budgets:
        fig, left = plt.subplots(figsize=(7.2, 4.4))
        x_values = [row["evaluation_budget_upper"] for row in budgets]
        left.plot(x_values, [row.get("effective_regen_loss_kwh") for row in budgets], marker="o", color="#176B87", label="有效再生损失")
        left.set_xlabel("评价预算上限")
        left.set_ylabel("有效再生损失（kWh）")
        right = left.twinx()
        right.plot(x_values, [row["wall_time_s"] for row in budgets], marker="s", color="#B23A48", label="耗时")
        right.set_ylabel("端到端耗时（秒）")
        left.set_title("搜索预算与解质量/耗时关系")
        left.grid(alpha=0.25)
        fig.tight_layout()
        path = output_dir / "budget_quality_curve.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path))
    return paths


def _recommend_profiles(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """依据实测结果给出快速、标准和精细三档运行建议。"""

    budget_rows = [row for row in rows if row["case_type"] == "budget"]
    quick_row = next((row for row in budget_rows if row["profile"] == "quick"), None)
    quick_loss = quick_row.get("effective_regen_loss_kwh") if quick_row else None
    profiles: dict[str, Any] = {}
    for row in budget_rows:
        current_loss = row.get("effective_regen_loss_kwh")
        improves_energy = (
            quick_loss is not None
            and current_loss is not None
            and float(current_loss) < float(quick_loss) - 1e-6
        )
        profiles[row["profile"]] = {
            "population_size": row["population_size"],
            "generations": row["generations"],
            "wall_time_s": row["wall_time_s"],
            "core_robust_feasible": row.get("core_robust_feasible"),
            "effective_regen_loss_kwh": row.get("effective_regen_loss_kwh"),
            "improves_energy_over_quick": improves_energy,
            "use_for": {
                "quick": "当前规划参数下的默认档，以及界面试算、输入检查和方案初筛",
                "standard": "正式数据到位后复验，或需要扩大稳健可行候选覆盖时使用",
                "fine": "仅在标准档仍有收敛不足证据或目标质量确有改善时使用",
            }[row["profile"]],
        }
    larger_profiles_improve = any(
        item["improves_energy_over_quick"]
        for name, item in profiles.items()
        if name != "quick"
    )
    larger_budget_tested = any(name != "quick" for name in profiles)
    return {
        "current_default": "standard" if larger_profiles_improve else "quick",
        "larger_budget_tested": larger_budget_tested,
        "larger_budget_improves_energy": larger_profiles_improve,
        "profiles": profiles,
    }


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    """生成可直接用于项目和论文实验记录的中文报告。"""

    boundary = summary["capacity_boundary"]
    lines = [
        "# 重空协同调度容量边界与搜索预算基准",
        "",
        "## 结论",
        "",
        f"- 在 `{boundary['timeout_limit_s']} s` 门槛和 4×1 搜索预算下，本轮最大已完成测试规模为 `{boundary['largest_completed_train_count']}` 列车。",
        (
            f"- 4×1 搜索下，本轮最大核心稳健可行规模为 `{boundary['largest_core_robust_feasible_train_count']}` 列车。"
            if boundary["largest_core_robust_feasible_train_count"] > 0
            else "- 4×1 搜索下，本轮测试集合没有找到核心稳健可行方案；不能据此把其他规模记为0列车能力。"
        ),
        "- 超过核心稳健边界的已完成案例会返回标称可行回退方案；这不等于核心稳健可行。",
        "- 该结论基于当前规划/占位参数，只说明软件计算能力，不代表线路正式运输能力。",
        (
            f"- 当前推荐搜索档位为 `{summary['profile_recommendations']['current_default']}`；"
            + (
                "本轮更大预算未改善能量目标。"
                if summary["profile_recommendations"]["larger_budget_tested"]
                and not summary["profile_recommendations"]["larger_budget_improves_energy"]
                else "本轮未重复测试更大搜索预算。"
            )
        ),
        "",
        "## 容量矩阵",
        "",
        "| 列车数 | 耗时/s | 峰值内存/MB | 完成 | 稳健可行 | 候选数 |",
        "|---:|---:|---:|:---:|:---:|---:|",
    ]
    for row in summary["runs"]:
        if row["case_type"] == "capacity":
            lines.append(
                f"| {row['train_count']} | {row['wall_time_s']} | {row['peak_rss_mb']} | "
                f"{'是' if row['passed'] else '否'} | {'是' if row.get('core_robust_feasible') else '否'} | {row.get('candidate_count')} |"
            )
    lines.extend([
        "",
        "## 搜索预算与质量",
        "",
        "| 档位 | 种群×代数 | 评价预算上限 | 耗时/s | 稳健可行 | 有效再生损失/kWh | 电网购电/kWh |",
        "|---|---:|---:|---:|:---:|---:|---:|",
    ])
    for row in summary["runs"]:
        if row["case_type"] == "budget":
            lines.append(
                f"| {row['profile']} | {row['population_size']}×{row['generations']} | "
                f"{row['evaluation_budget_upper']} | {row['wall_time_s']} | "
                f"{'是' if row.get('core_robust_feasible') else '否'} | {row.get('effective_regen_loss_kwh')} | {row.get('grid_kwh')} |"
            )
    lines.extend([
        "",
        "## 超时回退原则",
        "",
        "运行环境应在精细档超时时保留最近一个已完成且稳健可行的标准档结果；标准档超时时回退快速档。超时结果不得覆盖已完成方案，也不得被描述为不可行，只能标记为在给定计算时限内未完成。",
        "",
    ])
    (output_dir / "DISPATCH_CAPACITY_QUALITY_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run_benchmark(
    *,
    output_dir: Path,
    data_dir: Path,
    scales: Sequence[int],
    reference_scale: int,
    seed: int,
    timeout_s: int,
    budgets: Sequence[tuple[str, int, int]] = DEFAULT_BUDGETS,
) -> dict[str, Any]:
    """执行容量和预算矩阵，逐点持久化结果以支持长测续跑。"""

    scales = tuple(sorted(set(int(value) for value in scales)))
    if not scales or min(scales) <= 0 or reference_scale <= 0 or timeout_s <= 0:
        raise ValueError("规模、参考规模和超时必须为正数。")
    if not budgets or any(population < 2 or generations < 1 for _, population, generations in budgets):
        raise ValueError("搜索预算至少需要 2 个个体和 1 代。")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "benchmark_progress.json"
    rows: list[dict[str, Any]] = []
    if progress_path.is_file():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            saved_rows = [dict(row) for row in progress.get("runs", [])]
            for row in saved_rows:
                if "core_robust_feasible" not in row and row.get("output_dir"):
                    row.update(_extra_dispatch_metrics(Path(row["output_dir"])))
            rows = saved_rows if progress.get("status") == "completed" else [
                row for row in saved_rows if row.get("passed")
            ]
        except (OSError, ValueError, TypeError):
            rows = []

    plans = [
        {"case_type": "capacity", "profile": "capacity_quick", "scale": scale, "population_size": 4, "generations": 1}
        for scale in scales
    ] + [
        {"case_type": "budget", "profile": name, "scale": reference_scale, "population_size": population, "generations": generations}
        for name, population, generations in budgets
    ]
    for plan in plans:
        identity = (plan["case_type"], plan["profile"], plan["scale"])
        if any((row["case_type"], row["profile"], row["scale"]) == identity for row in rows):
            continue
        reusable = next(
            (
                row for row in rows
                if row["scale"] == plan["scale"]
                and row["population_size"] == plan["population_size"]
                and row["generations"] == plan["generations"]
            ),
            None,
        )
        if reusable is not None:
            rows.append({
                **reusable,
                **plan,
                "run_id": f"reused_{reusable['run_id']}",
                "reused_from_run_id": reusable["run_id"],
            })
            progress_path.write_text(
                json.dumps({"status": "running", "runs": rows}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            continue
        run_id = f"{len(rows) + 1:03d}_{plan['case_type']}_{plan['profile']}_s{plan['scale']}"
        run_dir = output_dir / "runs" / run_id
        algorithm_dir = run_dir / "algorithm_output"
        command = _command_for(
            "dispatch",
            scale=plan["scale"],
            seed=seed,
            output_dir=algorithm_dir,
            data_dir=data_dir,
            timetable_fixture=None,
            population_size=plan["population_size"],
            generations=plan["generations"],
        )
        observed = _run_monitored(command, run_dir, timeout_s)
        extracted = _extract_dispatch_result(algorithm_dir)
        passed = observed["return_code"] == 0 and bool(extracted.get("summary_found"))
        row = {
            **plan,
            "run_id": run_id,
            "seed": seed,
            "train_count": plan["scale"] * 2,
            "evaluation_budget_upper": plan["population_size"] * (plan["generations"] + 1),
            "timeout_limit_s": timeout_s,
            "passed": passed,
            **observed,
            **extracted,
            **_extra_dispatch_metrics(algorithm_dir),
            "command": command,
            "output_dir": str(algorithm_dir),
        }
        rows.append(row)
        progress_path.write_text(
            json.dumps({"status": "running", "runs": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    capacity = [row for row in rows if row["case_type"] == "capacity"]
    completed = [row["train_count"] for row in capacity if row.get("passed")]
    robust_feasible = [
        row["train_count"]
        for row in capacity
        if row.get("passed") and row.get("core_robust_feasible")
    ]
    summary = {
        "schema_version": "1.0",
        "benchmark_completed": len(rows) == len(plans),
        "data_status": "planning_and_placeholder_inputs",
        "capacity_boundary": {
            "timeout_limit_s": timeout_s,
            "largest_completed_train_count": max(completed, default=0),
            "largest_core_robust_feasible_train_count": max(robust_feasible, default=0),
            "tested_train_counts": [scale * 2 for scale in scales],
        },
        "settings": {
            "scales": list(scales),
            "reference_scale": reference_scale,
            "reference_train_count": reference_scale * 2,
            "seed": seed,
            "budgets": [list(item) for item in budgets],
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpu_count": psutil.cpu_count(),
            "physical_cpu_count": psutil.cpu_count(logical=False),
        },
        "profile_recommendations": _recommend_profiles(rows),
        "runs": rows,
    }
    summary["visualizations"] = _write_charts(rows, output_dir)
    (output_dir / "benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    csv_rows = [
        {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()}
        for row in rows
    ]
    _write_csv(output_dir / "benchmark_runs.csv", csv_rows)
    _write_report(summary, output_dir)
    progress_path.write_text(
        json.dumps({"status": "completed", "runs": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立命令行入口。"""

    parser = argparse.ArgumentParser(description="测量重空协同调度容量边界和搜索预算质量曲线。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3, 4])
    parser.add_argument("--reference-scale", type=int, default=2)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--timeout-s", type=int, default=600)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行基准并返回执行状态。"""

    args = build_parser().parse_args(argv)
    summary = run_benchmark(
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        scales=args.scales,
        reference_scale=args.reference_scale,
        seed=args.seed,
        timeout_s=args.timeout_s,
    )
    print(json.dumps(summary["capacity_boundary"], ensure_ascii=False, indent=2))
    return 0 if summary["benchmark_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
