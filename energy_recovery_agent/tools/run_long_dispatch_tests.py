"""独立执行长耗时回归，并对耗时和进程树峰值内存实施性能门禁。"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import psutil

try:
    from release_common import (
        file_records,
        load_package_spec,
        payload_sha256,
        selected_source_files,
        sha256_file,
    )
except ModuleNotFoundError:  # 兼容作为tools包模块导入。
    from tools.release_common import (
        file_records,
        load_package_spec,
        payload_sha256,
        selected_source_files,
        sha256_file,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_CONFIG = ROOT / "release" / "long_test_performance_gate.json"


def _load_gate_config(path: Path) -> dict[str, Any]:
    """读取并严格校验门禁配置，避免缺失阈值时静默放行。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("长测性能门禁配置 schema_version 必须为 1.0。")
    tests = payload.get("tests")
    if not isinstance(tests, dict) or not tests:
        raise ValueError("长测性能门禁配置必须包含非空 tests 对象。")
    for name, rule in tests.items():
        if not isinstance(rule, dict):
            raise ValueError(f"测试 {name} 的配置必须为对象。")
        script = ROOT / str(rule.get("script", ""))
        if not script.is_file():
            raise ValueError(f"测试 {name} 的脚本不存在：{script}")
        for field in ("timeout_s", "repeat_count", "max_median_elapsed_s", "max_peak_rss_mb"):
            value = rule.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"测试 {name} 的 {field} 必须为有限正数。")
        if int(rule["repeat_count"]) != rule["repeat_count"]:
            raise ValueError(f"测试 {name} 的 repeat_count 必须为正整数。")
    return payload


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    """超时后终止被测进程及其后代，避免孤立算法进程继续占用资源。"""
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


def _tree_rss_bytes(pid: int) -> int:
    """返回根进程及当前全部后代的常驻内存总量。"""
    try:
        root_process = psutil.Process(pid)
        processes = [root_process, *root_process.children(recursive=True)]
    except psutil.Error:
        return 0
    total = 0
    for process in processes:
        try:
            if process.is_running():
                total += process.memory_info().rss
        except psutil.Error:
            continue
    return total


def _run_monitored(
    command: Sequence[str], *, timeout_s: float, stdout_path: Path,
    stderr_path: Path, sample_interval_s: float,
) -> dict[str, Any]:
    """执行一次测试，持续采样进程树内存并保留独立日志。"""
    environment = {
        **os.environ, "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }
    peak_rss = 0
    memory_sample_count = 0
    timed_out = False
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            list(command), cwd=ROOT, stdout=stdout, stderr=stderr, text=True, env=environment
        )
        while process.poll() is None:
            sampled_rss = _tree_rss_bytes(process.pid)
            if sampled_rss > 0:
                memory_sample_count += 1
                peak_rss = max(peak_rss, sampled_rss)
            if time.perf_counter() - started > timeout_s:
                timed_out = True
                _terminate_tree(process)
                break
            time.sleep(sample_interval_s)
        peak_rss = max(peak_rss, _tree_rss_bytes(process.pid))
        return_code = process.wait()
    return {
        "return_code": 124 if timed_out else return_code,
        "timed_out": timed_out,
        "passed": return_code == 0 and not timed_out,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "peak_rss_mb": round(peak_rss / 1024 / 1024, 3),
        "memory_sample_count": memory_sample_count,
    }


def _evaluate_test(name: str, rule: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """聚合重复测量，并生成可由自动化系统消费的门禁结论。"""
    successful = [row for row in attempts if bool(row.get("passed"))]
    elapsed_values = [float(row["elapsed_s"]) for row in successful]
    memory_values = [float(row["peak_rss_mb"]) for row in successful]
    expected_count = int(rule["repeat_count"])
    median_elapsed = round(statistics.median(elapsed_values), 3) if elapsed_values else None
    peak_rss = round(max(memory_values), 3) if memory_values else None
    violations: list[dict[str, Any]] = []
    if len(successful) != expected_count:
        violations.append({
            "metric": "successful_repeat_count", "observed": len(successful), "limit": expected_count,
            "message": "功能失败、超时或重复测量不完整。",
        })
    incomplete_memory_attempts = sum(int(row.get("memory_sample_count", 1)) <= 0 for row in successful)
    if incomplete_memory_attempts:
        violations.append({
            "metric": "memory_sample_count", "observed": 0, "limit": 1,
            "message": f"有 {incomplete_memory_attempts} 轮未取得有效进程树内存样本。",
        })
    if median_elapsed is not None and median_elapsed > float(rule["max_median_elapsed_s"]):
        violations.append({
            "metric": "median_elapsed_s", "observed": median_elapsed,
            "limit": float(rule["max_median_elapsed_s"]), "message": "重复测量的中位耗时超过性能回归线。",
        })
    if peak_rss is not None and peak_rss > float(rule["max_peak_rss_mb"]):
        violations.append({
            "metric": "peak_rss_mb", "observed": peak_rss,
            "limit": float(rule["max_peak_rss_mb"]), "message": "任一轮进程树峰值内存超过性能回归线。",
        })
    return {
        "name": name, "script": str(rule["script"]), "repeat_count": expected_count,
        "timeout_s": float(rule["timeout_s"]),
        "baseline_median_elapsed_s": rule.get("baseline_median_elapsed_s"),
        "median_elapsed_s": median_elapsed, "max_median_elapsed_s": float(rule["max_median_elapsed_s"]),
        "peak_rss_mb": peak_rss, "max_peak_rss_mb": float(rule["max_peak_rss_mb"]),
        "functional_passed": len(successful) == expected_count,
        "performance_passed": not any(
            item["metric"] in {"median_elapsed_s", "peak_rss_mb", "memory_sample_count"}
            for item in violations
        ),
        "passed": not violations,
        "violations": violations, "attempts": list(attempts),
    }


def _write_reports(output_dir: Path, summary: Mapping[str, Any]) -> None:
    """写出机器可读摘要和便于人工审查的中文报告。"""
    (output_dir / "long_dispatch_tests.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 长耗时测试性能门禁", "",
        f"- 选定范围：`{'PASS' if summary['selected_scope_passed'] else 'FAIL'}`",
        f"- 完整正式门禁：`{'PASS' if summary['accepted'] else ('FAIL' if summary['complete_scope'] else 'NOT_APPLICABLE')}`",
        f"- 完整范围：`{summary['complete_scope']}`",
        f"- 配置版本：`{summary['gate_version']}`", f"- 测试数量：`{len(summary['results'])}`",
        f"- 独立测量总数：`{summary['attempt_count']}`",
        f"- 候选载荷 SHA-256：`{summary['candidate_payload_sha256_before']}`",
        f"- 门禁配置 SHA-256：`{summary['gate_config_sha256']}`",
        f"- 依赖锁 SHA-256：`{summary['requirements_lock_sha256']}`",
        f"- 测试前后候选载荷不变：`{summary['source_unchanged']}`", "",
        "门禁同时检查功能返回码、独立超时、重复测量中位耗时和进程树峰值 RSS。当前阈值是合成数据工程回归线，不是生产 SLA。", "",
        "| 测试 | 状态 | 重复 | 中位耗时/上限 (s) | 峰值 RSS/上限 (MB) |", "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in summary["results"]:
        elapsed = "-" if row["median_elapsed_s"] is None else f"{row['median_elapsed_s']:.3f}"
        memory = "-" if row["peak_rss_mb"] is None else f"{row['peak_rss_mb']:.3f}"
        lines.append(
            f"| `{row['name']}` | {'PASS' if row['passed'] else 'FAIL'} | {row['repeat_count']} | "
            f"{elapsed} / {row['max_median_elapsed_s']:.3f} | {memory} / {row['max_peak_rss_mb']:.3f} |"
        )
    violations = [(row["name"], item) for row in summary["results"] for item in row["violations"]]
    if violations:
        lines.extend(["", "## 门禁失败原因", ""])
        lines.extend(
            f"- `{name}` / `{item['metric']}`：观测值 `{item['observed']}`，限制 `{item['limit']}`。{item['message']}"
            for name, item in violations
        )
    lines.extend(["", "## 测量明细", "", "| 测试 | 轮次 | 状态 | 返回码 | 耗时 (s) | 峰值 RSS (MB) |", "| --- | ---: | --- | ---: | ---: | ---: |"])
    for row in summary["results"]:
        lines.extend(
            f"| `{row['name']}` | {attempt['attempt']} | {'PASS' if attempt['passed'] else 'FAIL'} | "
            f"{attempt['return_code']} | {attempt['elapsed_s']:.3f} | {attempt['peak_rss_mb']:.3f} |"
            for attempt in row["attempts"]
        )
    (output_dir / "LONG_DISPATCH_TESTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """执行选定长测并以性能门禁结论作为进程退出状态。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/long_dispatch_tests"))
    parser.add_argument("--gate-config", type=Path, default=DEFAULT_GATE_CONFIG)
    parser.add_argument("--test", action="append", help="只执行指定测试，可重复传入")
    parser.add_argument("--timeout-s", type=float, default=0, help="诊断用：覆盖每轮超时，不改变性能阈值")
    parser.add_argument("--repeat", type=int, default=0, help="诊断用：覆盖重复次数，不改变性能阈值")
    parser.add_argument("--sample-interval-s", type=float, default=0.05)
    args = parser.parse_args()
    if args.timeout_s < 0 or args.repeat < 0 or args.sample_interval_s <= 0:
        parser.error("超时、重复次数和采样间隔参数必须为非负值，采样间隔必须大于零。")
    config_path = args.gate_config if args.gate_config.is_absolute() else ROOT / args.gate_config
    config = _load_gate_config(config_path)
    tests = config["tests"]
    selected = args.test or list(tests)
    unknown = sorted(set(selected) - set(tests))
    if unknown:
        parser.error(f"未知长测：{', '.join(unknown)}；可用项：{', '.join(sorted(tests))}")
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source_spec = load_package_spec(ROOT)
    source_records_before = file_records(selected_source_files(ROOT, source_spec), ROOT)
    source_hash_before = payload_sha256(source_records_before)
    results = []
    started_at = datetime.now(timezone.utc).isoformat()
    for name in selected:
        configured_rule = dict(tests[name])
        rule = dict(configured_rule)
        if args.timeout_s:
            rule["timeout_s"] = args.timeout_s
        if args.repeat:
            rule["repeat_count"] = args.repeat
        attempts = []
        for attempt in range(1, int(rule["repeat_count"]) + 1):
            print(f"RUN {name} [{attempt}/{int(rule['repeat_count'])}]", flush=True)
            measured = _run_monitored(
                [sys.executable, str(rule["script"])], timeout_s=float(rule["timeout_s"]),
                stdout_path=output_dir / f"{name}.run{attempt}.stdout.txt",
                stderr_path=output_dir / f"{name}.run{attempt}.stderr.txt",
                sample_interval_s=args.sample_interval_s,
            )
            measured["attempt"] = attempt
            attempts.append(measured)
            print(
                f"  -> {'PASS' if measured['passed'] else 'FAIL'} "
                f"({measured['elapsed_s']:.3f}s, {measured['peak_rss_mb']:.3f}MB)", flush=True
            )
        evaluated = _evaluate_test(name, rule, attempts)
        evaluated["configured_repeat_count"] = int(configured_rule["repeat_count"])
        evaluated["configured_timeout_s"] = float(configured_rule["timeout_s"])
        results.append(evaluated)
    source_records_after = file_records(selected_source_files(ROOT, source_spec), ROOT)
    source_hash_after = payload_sha256(source_records_after)
    source_unchanged = source_records_before == source_records_after
    selected_scope_passed = all(bool(row["passed"]) for row in results) and source_unchanged
    complete_scope = set(selected) == set(tests) and len(selected) == len(tests) and not (args.timeout_s or args.repeat)
    accepted = selected_scope_passed and complete_scope
    summary = {
        "schema_version": "2.0", "gate_version": config["gate_version"],
        "gate_config": str(config_path.relative_to(ROOT)) if config_path.is_relative_to(ROOT) else str(config_path),
        "gate_config_sha256": sha256_file(config_path),
        "requirements_lock_sha256": sha256_file(ROOT / "requirements-lock.txt"),
        "candidate_file_count": len(source_records_before),
        "candidate_payload_sha256_before": source_hash_before,
        "candidate_payload_sha256_after": source_hash_after,
        "source_unchanged": source_unchanged,
        "started_at_utc": started_at, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "logical_cpu_count": psutil.cpu_count(), "physical_cpu_count": psutil.cpu_count(logical=False),
            "total_memory_mb": round(psutil.virtual_memory().total / 1024 / 1024, 3),
        },
        "selected": selected, "attempt_count": sum(len(row["attempts"]) for row in results),
        "passed_count": sum(bool(row["passed"]) for row in results),
        "failed_count": sum(not bool(row["passed"]) for row in results),
        "selected_scope_passed": selected_scope_passed, "complete_scope": complete_scope,
        "accepted": accepted,
        "diagnostic_overrides_used": bool(args.timeout_s or args.repeat),
        "gate_violations": [] if source_unchanged else ["长测期间候选发布载荷发生变化"],
        "results": results,
    }
    _write_reports(output_dir, summary)
    print(json.dumps({
        "accepted": accepted, "report": str(output_dir / "LONG_DISPATCH_TESTS.md"),
        "summary": str(output_dir / "long_dispatch_tests.json"), "failed_count": summary["failed_count"],
    }, ensure_ascii=False))
    # 单项和覆盖参数运行属于诊断，只按选定范围返回退出码；完整运行才产生 accepted=true。
    return 0 if selected_scope_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
