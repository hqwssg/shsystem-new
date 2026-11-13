# 模块功能说明：对运行图优化和重空协同调度执行规模、随机种子稳定性与确定性复现基准。

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "real_shuohuang"
DEFAULT_TIMETABLE = ROOT / "data_templates" / "running_diagram_template.xlsx"
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "algorithm_scale_stability"
TARGETS = ("timetable", "dispatch")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """按所有行字段的首次出现顺序写出 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_scaled_timetable_fixture(source: Path, output_dir: Path, scale: int, shift_s: int) -> Path:
    """复制基础运行图中的列车组并错开时间，形成可重复的列车规模输入。"""
    if scale <= 0:
        raise ValueError("运行图规模必须为正整数。")
    if shift_s <= 0:
        raise ValueError("运行图复制批次的时间偏移必须为正整数秒。")
    from timetable_input import load_canonical_timetable

    timetable = load_canonical_timetable(Path(source))
    if not timetable.validation_report.is_valid:
        raise ValueError("基础运行图存在校验错误，不能生成规模夹具。")
    train_rows: list[dict[str, Any]] = []
    stop_rows: list[dict[str, Any]] = []
    for copy_index in range(scale):
        suffix = f"_S{copy_index + 1:02d}"
        offset = copy_index * shift_s
        for train in timetable.trains:
            train_rows.append({
                "train_id": f"{train.train_id}{suffix}",
                "train_type": train.train_type,
                "direction": train.direction,
                "origin_station": train.origin_station,
                "destination_station": train.destination_station,
                "mass_t": train.mass_t,
                "formation": train.formation,
                "traction_type": train.traction_type,
                "priority": train.priority,
                "formation_category": train.formation_category,
                "formation_mode": train.formation_mode,
                "wagon_count": train.wagon_count,
            })
        for stop in timetable.stops:
            stop_rows.append({
                "train_id": f"{stop.train_id}{suffix}",
                "seq": stop.seq,
                "station_name": stop.station_name,
                "station_km": stop.station_km,
                "arrival_time": stop.arrival_time_s + offset,
                "departure_time": stop.departure_time_s + offset,
                "stop_type": stop.stop_type,
                "track": stop.track,
                "operation_type": stop.operation_type,
                "note": stop.note,
            })
    scenario_rows = []
    for scenario in timetable.scenarios:
        row = asdict(scenario)
        row["direct_use_enabled"] = str(row["direct_use_enabled"]).lower()
        row["storage_enabled"] = str(row["storage_enabled"]).lower()
        scenario_rows.append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "trains.csv", train_rows)
    _write_csv(output_dir / "timetable.csv", stop_rows)
    _write_csv(output_dir / "scenario.csv", scenario_rows)
    _write_csv(output_dir / "constraints.csv", [dict(row) for row in timetable.constraints])
    return output_dir


def _float(value: Any) -> Optional[float]:
    """将有限数值转换为浮点数，缺失或非法值返回空。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _cv(values: Iterable[Any]) -> Optional[float]:
    """计算总体变异系数；均值接近零时只在全零情况下返回 0。"""
    numbers = [number for value in values if (number := _float(value)) is not None]
    if not numbers:
        return None
    mean = statistics.fmean(numbers)
    if abs(mean) <= 1e-12:
        return 0.0 if all(abs(item) <= 1e-12 for item in numbers) else None
    return statistics.pstdev(numbers) / abs(mean)


def _sha256_payload(payload: Any) -> str:
    """为不含运行时间和路径的语义结果生成稳定摘要。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    """读取结果 CSV；文件不存在时返回空列表。"""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _extract_timetable_result(output_dir: Path) -> dict[str, Any]:
    """从运行图优化输出提取稳定性和质量指标。"""
    summary_path = output_dir / "optimizer_summary.json"
    if not summary_path.is_file():
        return {"summary_found": False}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pareto = _read_csv(output_dir / "pareto_candidates.csv")
    feasible = [row for row in pareto if str(row.get("feasible", "")).lower() == "true"]
    ranked = sorted(
        feasible,
        key=lambda row: (
            _float(row.get("effective_regen_loss_kwh_est")) or math.inf,
            _float(row.get("grid_kwh_est")) or math.inf,
            _float(row.get("total_adjustment_min")) or math.inf,
            row.get("candidate_id", ""),
        ),
    )
    best = ranked[0] if ranked else {}
    semantic = {
        "valid": bool(summary.get("valid", False)),
        "candidate_count": summary.get("candidate_count"),
        "feasible_candidate_count": summary.get("feasible_candidate_count"),
        "pareto_count": summary.get("pareto_count"),
        "best": {key: best.get(key) for key in (
            "candidate_id", "scenario_id", "effective_regen_loss_kwh_est",
            "grid_kwh_est", "wasted_kwh_est", "total_adjustment_min", "constraint_violation",
        )},
    }
    return {
        "summary_found": True,
        "valid": semantic["valid"],
        "feasible": bool(feasible),
        "candidate_count": summary.get("candidate_count"),
        "feasible_candidate_count": summary.get("feasible_candidate_count"),
        "pareto_count": summary.get("pareto_count"),
        "grid_kwh": _float(best.get("grid_kwh_est")),
        "wasted_kwh": _float(best.get("wasted_kwh_est")),
        "effective_regen_loss_kwh": _float(best.get("effective_regen_loss_kwh_est")),
        "total_cost": None,
        "constraint_violation": _float(best.get("constraint_violation")),
        "semantic_sha256": _sha256_payload(semantic),
    }


def _extract_dispatch_result(output_dir: Path) -> dict[str, Any]:
    """从重空协同调度输出提取稳定性和质量指标。"""
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        return {"summary_found": False}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    optimized = summary.get("optimized", {})
    diagnostics = summary.get("optimizer_diagnostics", {})
    semantic = {
        "optimized": {key: optimized.get(key) for key in (
            "feasible", "constraint_violation", "grid_kwh", "wasted_kwh", "total_cost",
            "battery_charge_kwh", "battery_discharge_kwh", "resource_conflict_count",
        )},
        "optimized_departures": summary.get("optimized_departures", {}),
        "optimized_storage_preset_id": summary.get("selected_storage_preset", {}).get("optimized_preset_id"),
        "candidate_count": diagnostics.get("candidate_count"),
        "pareto_candidate_count": diagnostics.get("pareto_candidate_count"),
    }
    return {
        "summary_found": True,
        "valid": True,
        "feasible": bool(optimized.get("feasible", False)),
        "candidate_count": diagnostics.get("candidate_count"),
        "feasible_candidate_count": diagnostics.get("core_robust_feasible_candidate_count"),
        "pareto_count": diagnostics.get("pareto_candidate_count"),
        "grid_kwh": _float(optimized.get("grid_kwh")),
        "wasted_kwh": _float(optimized.get("wasted_kwh")),
        "effective_regen_loss_kwh": _float(optimized.get("energy_term")),
        "total_cost": _float(optimized.get("total_cost")),
        "constraint_violation": _float(optimized.get("constraint_violation")),
        "semantic_sha256": _sha256_payload(semantic),
    }


def _terminate_tree(process: subprocess.Popen[Any]) -> None:
    """在单次基准超时后终止该子进程及其后代。"""
    try:
        root_process = psutil.Process(process.pid)
        descendants = root_process.children(recursive=True)
    except psutil.Error:
        descendants = []
    for child in descendants:
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        process.terminate()
    except OSError:
        pass
    _, alive = psutil.wait_procs(descendants, timeout=3)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass
    if process.poll() is None:
        process.kill()


def _run_monitored(command: Sequence[str], output_dir: Path, timeout_s: int) -> dict[str, Any]:
    """在独立进程中运行一次算法，并观测进程树峰值常驻内存。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    environment = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "MPLBACKEND": "Agg",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    peak_rss = 0
    timed_out = False
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, env=environment)
        while process.poll() is None:
            if time.perf_counter() - started > timeout_s:
                timed_out = True
                _terminate_tree(process)
                break
            try:
                root_process = psutil.Process(process.pid)
                processes = [root_process, *root_process.children(recursive=True)]
                rss = sum(item.memory_info().rss for item in processes if item.is_running())
                peak_rss = max(peak_rss, rss)
            except psutil.Error:
                pass
            time.sleep(0.05)
        return_code = process.wait()
    return {
        "return_code": 124 if timed_out else return_code,
        "timed_out": timed_out,
        "wall_time_s": round(time.perf_counter() - started, 6),
        "peak_rss_mb": round(peak_rss / 1024 / 1024, 3),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _command_for(
    target: str,
    *,
    scale: int,
    seed: int,
    output_dir: Path,
    data_dir: Path,
    timetable_fixture: Optional[Path],
    population_size: int,
    generations: int,
) -> list[str]:
    """构造统一项目入口命令，保证日常运行和基准运行参数口径一致。"""
    if target == "timetable":
        assert timetable_fixture is not None
        return [
            sys.executable, "run_project.py", "optimize-timetable",
            "--timetable", str(timetable_fixture), "--data-dir", str(data_dir),
            "--output-dir", str(output_dir), "--mode", "nsga2",
            "--population-size", str(population_size), "--generations", str(generations),
            "--seed", str(seed),
        ]
    if target == "dispatch":
        return [
            sys.executable, "run_project.py", "dispatch-case",
            "--data-dir", str(data_dir), "--output-dir", str(output_dir),
            "--heavy-count", str(scale), "--empty-count", str(scale),
            "--population-size", str(population_size), "--generations", str(generations),
            "--seed", str(seed), "--search-profile", "standard",
        ]
    raise ValueError(f"未知基准目标：{target}")


def _metric_stats(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Optional[float]]:
    """汇总一个数值指标的中位数、范围和变异系数。"""
    values = [number for row in rows if (number := _float(row.get(field))) is not None]
    return {
        "count": len(values),
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "cv": _cv(values),
    }


def summarize_runs(
    rows: Sequence[dict[str, Any]],
    targets: Sequence[str],
    *,
    min_seed_feasible_rate: float,
    max_seed_objective_cv: float,
) -> dict[str, Any]:
    """汇总规模趋势、跨种子波动和同种子复现检查。"""
    target_summaries: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    for target in targets:
        target_rows = [row for row in rows if row["target"] == target]
        scale_rows = [row for row in target_rows if row["case_type"] == "scale"]
        seed_rows = [row for row in target_rows if row["case_type"] == "seed"]
        replay_rows = [row for row in target_rows if row["case_type"] == "replay"]
        successful = [row for row in target_rows if row.get("passed")]
        seed_successful = [row for row in seed_rows if row.get("passed")]
        feasible_rate = (
            sum(bool(row.get("feasible")) for row in seed_successful) / len(seed_successful)
            if seed_successful else 0.0
        )
        grid_stats = _metric_stats(seed_successful, "grid_kwh")
        replay_hashes = {row.get("semantic_sha256") for row in replay_rows if row.get("passed")}
        replay_deterministic = len(replay_hashes) == 1 and len(replay_rows) >= 2 and all(row.get("passed") for row in replay_rows)
        execution_ok = len(successful) == len(target_rows) and bool(target_rows)
        scale_ok = bool(scale_rows) and all(row.get("passed") for row in scale_rows)
        feasible_ok = feasible_rate >= min_seed_feasible_rate
        objective_cv = grid_stats["cv"]
        objective_ok = objective_cv is not None and objective_cv <= max_seed_objective_cv
        for code, passed, observed, required in (
            (f"{target}_all_runs_completed", execution_ok, f"{len(successful)}/{len(target_rows)}", "all"),
            (f"{target}_scale_cases_completed", scale_ok, sum(bool(row.get("passed")) for row in scale_rows), len(scale_rows)),
            (f"{target}_seed_feasible_rate", feasible_ok, feasible_rate, min_seed_feasible_rate),
            (f"{target}_seed_grid_cv", objective_ok, objective_cv, max_seed_objective_cv),
            (f"{target}_same_seed_reproducible", replay_deterministic, len(replay_hashes), 1),
        ):
            checks.append({"code": code, "passed": passed, "observed": observed, "required": required})
        target_summaries[target] = {
            "run_count": len(target_rows),
            "successful_run_count": len(successful),
            "scale_cases": [
                {key: row.get(key) for key in (
                    "scale", "train_count", "passed", "timed_out", "return_code",
                    "wall_time_s", "peak_rss_mb", "feasible",
                    "candidate_count", "grid_kwh", "wasted_kwh", "effective_regen_loss_kwh",
                )}
                for row in sorted(scale_rows, key=lambda item: item["scale"])
            ],
            "seed_stability": {
                "run_count": len(seed_rows),
                "feasible_rate": feasible_rate,
                "unique_semantic_hash_count": len({
                    row.get("semantic_sha256") for row in seed_successful if row.get("semantic_sha256")
                }),
                "wall_time_s": _metric_stats(seed_successful, "wall_time_s"),
                "peak_rss_mb": _metric_stats(seed_successful, "peak_rss_mb"),
                "grid_kwh": grid_stats,
                "wasted_kwh": _metric_stats(seed_successful, "wasted_kwh"),
                "effective_regen_loss_kwh": _metric_stats(seed_successful, "effective_regen_loss_kwh"),
                "total_cost": _metric_stats(seed_successful, "total_cost"),
            },
            "deterministic_replay": {
                "run_count": len(replay_rows),
                "unique_semantic_hash_count": len(replay_hashes),
                "passed": replay_deterministic,
                "runtime_cv": _metric_stats(replay_rows, "wall_time_s")["cv"],
            },
        }
    return {
        "accepted": all(check["passed"] for check in checks),
        "checks": checks,
        "failed_checks": [check["code"] for check in checks if not check["passed"]],
        "targets": target_summaries,
    }


def _write_charts(summary: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """生成论文可继续加工的规模耗时和峰值内存图。"""
    diagnostics: dict[str, Any] = {"status": "complete", "files": {}, "errors": []}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure_dir = output_dir / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        for metric, label, filename in (
            ("wall_time_s", "Wall time (s)", "scale_wall_time.png"),
            ("peak_rss_mb", "Peak process-tree RSS (MB)", "scale_peak_memory.png"),
        ):
            fig, axis = plt.subplots(figsize=(7.2, 4.4))
            for target, item in summary["targets"].items():
                cases = item["scale_cases"]
                completed_cases = [row for row in cases if row.get("passed") and not row.get("timed_out")]
                axis.plot(
                    [row["train_count"] for row in completed_cases],
                    [row[metric] for row in completed_cases],
                    marker="o",
                    label=target,
                )
                for row in cases:
                    if row.get("timed_out"):
                        axis.scatter([row["train_count"]], [row[metric]], marker="x", s=70, color="crimson", zorder=4)
                        axis.annotate("timeout", (row["train_count"], row[metric]), xytext=(4, 5), textcoords="offset points", fontsize=8)
            axis.set_xlabel("Total train count")
            axis.set_ylabel(label)
            axis.grid(True, alpha=0.3)
            axis.legend()
            fig.tight_layout()
            path = figure_dir / filename
            fig.savefig(path, dpi=180)
            plt.close(fig)
            diagnostics["files"][metric] = str(path)
    except Exception as exc:  # 图表失败不能吞掉基准数据，但必须显式记录。
        diagnostics["status"] = "failed"
        diagnostics["errors"].append(f"{type(exc).__name__}: {exc}")
    return diagnostics


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    """写出面向项目和论文实验的中文基准报告。"""
    lines = [
        "# 算法规模与稳定性基准报告", "",
        f"- 基准门禁通过：`{summary['accepted']}`",
        f"- 数据状态：`{summary['data_status']}`",
        f"- 总运行次数：{summary['run_count']}",
        f"- 搜索规模：population={summary['settings']['population_size']}，generations={summary['settings']['generations']}",
        f"- 请求参考规模：{summary['settings']['requested_reference_scale']}；实际稳定性参考规模：`{summary['settings']['effective_reference_scales']}`",
        "",
        "当前使用规划/占位参数与拟真运行图，结果用于验证计算规模、算法稳定性和复现性，不用于发布正式节能量。", "",
    ]
    for target, item in summary["targets"].items():
        lines.extend([
            f"## {target}", "", "### 规模趋势", "",
            "| 规模 | 列车总数 | 耗时 s | 峰值内存 MB | 状态/可行 | 候选数 | 购电 kWh | 弃能 kWh |", 
            "| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
        ])
        for row in item["scale_cases"]:
            status = "TIMEOUT" if row.get("timed_out") else ("PASS" if row.get("passed") else "FAIL")
            elapsed = f">={row['wall_time_s']}" if row.get("timed_out") else row["wall_time_s"]
            lines.append(
                f"| {row['scale']} | {row['train_count']} | {elapsed} | {row['peak_rss_mb']} | {status}/{row['feasible']} | {row['candidate_count']} | {row['grid_kwh']} | {row['wasted_kwh']} |"
            )
        stable = item["seed_stability"]
        lines.extend([
            "", "### 多种子稳定性", "",
            f"- 可行率：{stable['feasible_rate']:.2%}",
            f"- 购电量变异系数：{stable['grid_kwh']['cv']}",
            f"- 弃能量变异系数：{stable['wasted_kwh']['cv']}",
            f"- 跨种子唯一语义方案数：{stable.get('unique_semantic_hash_count')}",
            f"- 耗时中位数：{stable['wall_time_s']['median']} s",
            f"- 峰值内存中位数：{stable['peak_rss_mb']['median']} MB",
            "", "### 同种子复现", "",
            f"- 语义结果完全一致：`{item['deterministic_replay']['passed']}`",
            f"- 唯一语义摘要数：{item['deterministic_replay']['unique_semantic_hash_count']}",
            f"- 重复运行耗时变异系数：{item['deterministic_replay']['runtime_cv']}", "",
        ])
    lines.extend(["## 门禁检查", "", "| 检查 | 通过 | 观测 | 要求 |", "| --- | --- | --- | --- |"])
    for check in summary["checks"]:
        lines.append(f"| `{check['code']}` | {check['passed']} | `{check['observed']}` | `{check['required']}` |")
    lines.extend([
        "", "## 解读边界", "",
        "规模曲线是当前机器、当前代码和固定搜索预算下的经验结果，不等于算法理论复杂度。正式数据到位后必须保留相同口径重跑，并按评价窗分别报告。",
        "跨种子目标波动用于判断搜索偶然性；同种子语义摘要用于检查确定性复现。墙钟时间受机器负载影响，不要求逐次完全相同。", "",
        "超时点的墙钟时间是下界，峰值内存仅是终止前观测值，不能与完整运行的最终峰值直接比较。", "",
    ])
    (output_dir / "ALGORITHM_SCALE_STABILITY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def refresh_benchmark_presentation(output_dir: Path) -> dict[str, Any]:
    """利用已完成的结构化结果重建报告和图表，不重复运行耗时算法。"""
    output_dir = Path(output_dir)
    summary_path = output_dir / "benchmark_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run_rows = _read_csv(output_dir / "benchmark_runs.csv")
    for target, target_summary in summary["targets"].items():
        seed_rows = [
            row for row in run_rows
            if row.get("target") == target
            and row.get("case_type") == "seed"
            and str(row.get("passed", "")).lower() == "true"
        ]
        target_summary["seed_stability"]["unique_semantic_hash_count"] = len({
            row.get("semantic_sha256") for row in seed_rows if row.get("semantic_sha256")
        })
        for scale_case in target_summary["scale_cases"]:
            source = next(
                (
                    row for row in run_rows
                    if row.get("target") == target
                    and row.get("case_type") == "scale"
                    and int(row.get("scale", 0)) == int(scale_case["scale"])
                ),
                {},
            )
            scale_case["passed"] = str(source.get("passed", "")).lower() == "true"
            scale_case["timed_out"] = str(source.get("timed_out", "")).lower() == "true"
            scale_case["return_code"] = int(source["return_code"]) if source.get("return_code") else None
    summary["visualizations"] = _write_charts(summary, output_dir)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(summary, output_dir)
    return summary


def run_benchmark(
    *,
    output_dir: Path,
    data_dir: Path,
    timetable: Path,
    targets: Sequence[str],
    scales: Sequence[int],
    seeds: Sequence[int],
    reference_scale: int,
    replay_count: int,
    population_size: int,
    generations: int,
    timeout_s: int,
    stability_timeout_s: int,
    timetable_copy_shift_s: int,
    min_seed_feasible_rate: float,
    max_seed_objective_cv: float,
) -> dict[str, Any]:
    """执行完整基准矩阵并生成结构化结果、图表和中文报告。"""
    targets = tuple(dict.fromkeys(targets))
    scales = tuple(sorted(set(scales)))
    seeds = tuple(dict.fromkeys(seeds))
    if not targets or any(target not in TARGETS for target in targets):
        raise ValueError(f"targets 必须来自 {TARGETS}。")
    if not scales or min(scales) <= 0 or reference_scale <= 0:
        raise ValueError("规模值和参考规模必须为正整数。")
    if not seeds or replay_count < 2:
        raise ValueError("至少需要一个随机种子，且同种子复现次数不得少于 2。")
    if population_size < 2 or generations < 1 or timeout_s <= 0 or stability_timeout_s <= 0:
        raise ValueError("种群至少为 2、代数至少为 1、两个超时设置都必须为正数。")
    if not 0.0 <= min_seed_feasible_rate <= 1.0 or max_seed_objective_cv < 0.0:
        raise ValueError("稳定性阈值设置无效。")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_root = output_dir / "inputs" / "scaled_timetables"
    fixture_by_scale: dict[int, Path] = {}
    if "timetable" in targets:
        for scale in sorted(set((*scales, reference_scale))):
            fixture_by_scale[scale] = build_scaled_timetable_fixture(
                timetable, fixture_root / f"scale_{scale:03d}", scale, timetable_copy_shift_s
            )

    progress_path = output_dir / "benchmark_progress.json"
    rows: list[dict[str, Any]] = []
    if progress_path.is_file():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if progress.get("status") == "running" and isinstance(progress.get("runs"), list):
                # 规模点即使超时也属于容量结论；其他失败项使用新的稳定性超时重新执行。
                rows = [
                    dict(row) for row in progress["runs"]
                    if row.get("case_type") == "scale" or row.get("passed")
                ]
        except (OSError, ValueError, TypeError):
            rows = []

    def execute(plan: dict[str, Any]) -> None:
        """执行并立即持久化一个基准点，确保长测中断时已有观测不丢失。"""
        if any(
            row.get("target") == plan["target"]
            and row.get("case_type") == plan["case_type"]
            and row.get("scale") == plan["scale"]
            and row.get("seed") == plan["seed"]
            and row.get("repeat") == plan["repeat"]
            for row in rows
        ):
            return
        index = len(rows) + 1
        run_id = f"{index:03d}_{plan['target']}_{plan['case_type']}_s{plan['scale']}_seed{plan['seed']}_r{plan['repeat']}"
        run_dir = output_dir / "runs" / run_id
        algorithm_dir = run_dir / "algorithm_output"
        command = _command_for(
            plan["target"], scale=plan["scale"], seed=plan["seed"], output_dir=algorithm_dir,
            data_dir=data_dir, timetable_fixture=fixture_by_scale.get(plan["scale"]),
            population_size=population_size, generations=generations,
        )
        run_timeout_s = timeout_s if plan["case_type"] == "scale" else stability_timeout_s
        observed = _run_monitored(command, run_dir, run_timeout_s)
        extracted = (
            _extract_timetable_result(algorithm_dir)
            if plan["target"] == "timetable"
            else _extract_dispatch_result(algorithm_dir)
        )
        passed = observed["return_code"] == 0 and bool(extracted.get("summary_found")) and bool(extracted.get("valid"))
        rows.append({
            **plan,
            "run_id": run_id,
            "train_count": plan["scale"] * 2,
            "population_size": population_size,
            "generations": generations,
            "evaluation_budget_upper": population_size * (generations + 1),
            "timeout_limit_s": run_timeout_s,
            "passed": passed,
            **observed,
            **extracted,
            "command": command,
            "output_dir": str(algorithm_dir),
        })
        progress_path.write_text(
            json.dumps({"status": "running", "completed_run_count": len(rows), "runs": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 先探测规模。稳定性测试自动使用不大于请求值的最大成功规模，避免在已知超时点重复计算。
    for target in targets:
        for scale in scales:
            execute({"target": target, "case_type": "scale", "scale": scale, "seed": seeds[0], "repeat": 1})

    effective_reference_scales: dict[str, int] = {}
    for target in targets:
        successful_scales = [
            int(row["scale"])
            for row in rows
            if row["target"] == target and row["case_type"] == "scale" and row.get("passed")
        ]
        at_or_below = [scale for scale in successful_scales if scale <= reference_scale]
        effective_scale = max(at_or_below or successful_scales, default=reference_scale)
        effective_reference_scales[target] = effective_scale
        if target == "timetable" and effective_scale not in fixture_by_scale:
            fixture_by_scale[effective_scale] = build_scaled_timetable_fixture(
                timetable, fixture_root / f"scale_{effective_scale:03d}", effective_scale, timetable_copy_shift_s
            )
        for seed in seeds:
            execute({"target": target, "case_type": "seed", "scale": effective_scale, "seed": seed, "repeat": 1})
        for repeat in range(1, replay_count + 1):
            execute({"target": target, "case_type": "replay", "scale": effective_scale, "seed": seeds[0], "repeat": repeat})

    aggregate = summarize_runs(
        rows, targets,
        min_seed_feasible_rate=min_seed_feasible_rate,
        max_seed_objective_cv=max_seed_objective_cv,
    )
    summary = {
        "schema_version": "1.0",
        "benchmark_completed": True,
        "accepted": aggregate["accepted"],
        "data_status": "planning_and_placeholder_inputs",
        "run_count": len(rows),
        "settings": {
            "targets": list(targets), "scales": list(scales), "seeds": list(seeds),
            "requested_reference_scale": reference_scale,
            "effective_reference_scales": effective_reference_scales,
            "replay_count": replay_count,
            "population_size": population_size, "generations": generations,
            "scale_timeout_s": timeout_s,
            "stability_timeout_s": stability_timeout_s,
            "timetable_copy_shift_s": timetable_copy_shift_s,
            "min_seed_feasible_rate": min_seed_feasible_rate,
            "max_seed_objective_cv": max_seed_objective_cv,
        },
        "environment": {
            "python": sys.version, "platform": platform.platform(),
            "processor": platform.processor(), "logical_cpu_count": psutil.cpu_count(),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "total_memory_mb": round(psutil.virtual_memory().total / 1024 / 1024, 3),
            "controlled_environment": {
                "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg", "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            },
        },
        "inputs": {"data_dir": str(data_dir), "timetable": str(timetable)},
        "checks": aggregate["checks"],
        "failed_checks": aggregate["failed_checks"],
        "targets": aggregate["targets"],
    }
    summary["visualizations"] = _write_charts(summary, output_dir)
    (output_dir / "benchmark_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_rows = [{key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()} for row in rows]
    _write_csv(output_dir / "benchmark_runs.csv", csv_rows)
    _write_report(summary, output_dir)
    progress_path.write_text(
        json.dumps({"status": "completed", "completed_run_count": len(rows), "accepted": summary["accepted"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造独立运行入口。"""
    parser = argparse.ArgumentParser(description="运行算法规模、跨种子稳定性和同种子复现基准。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE)
    parser.add_argument("--target", action="append", choices=TARGETS, dest="targets")
    parser.add_argument("--scales", nargs="+", type=int, default=[1, 2, 3, 4])
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 53, 71])
    parser.add_argument("--reference-scale", type=int, default=3)
    parser.add_argument("--replay-count", type=int, default=2)
    parser.add_argument("--population-size", type=int, default=8)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--stability-timeout-s", type=int, default=1200)
    parser.add_argument("--timetable-copy-shift-s", type=int, default=7200)
    parser.add_argument("--min-seed-feasible-rate", type=float, default=0.8)
    parser.add_argument("--max-seed-objective-cv", type=float, default=0.25)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """执行命令行基准并返回门禁状态。"""
    args = build_parser().parse_args(argv)
    summary = run_benchmark(
        output_dir=args.output_dir, data_dir=args.data_dir, timetable=args.timetable,
        targets=args.targets or TARGETS, scales=args.scales, seeds=args.seeds,
        reference_scale=args.reference_scale, replay_count=args.replay_count,
        population_size=args.population_size, generations=args.generations,
        timeout_s=args.timeout_s, stability_timeout_s=args.stability_timeout_s,
        timetable_copy_shift_s=args.timetable_copy_shift_s,
        min_seed_feasible_rate=args.min_seed_feasible_rate,
        max_seed_objective_cv=args.max_seed_objective_cv,
    )
    print(json.dumps({
        "accepted": summary["accepted"], "run_count": summary["run_count"],
        "failed_checks": summary["failed_checks"],
        "report": str(args.output_dir / "ALGORITHM_SCALE_STABILITY_REPORT.md"),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
