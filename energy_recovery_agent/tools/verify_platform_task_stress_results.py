"""核验多档平台任务压力结果并生成容量对照报告。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Sequence


EXPECTED_FAULT_IDS = {f"PF-F0{index}" for index in range(1, 7)}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_results(input_dirs: Sequence[Path], output_dir: Path) -> dict[str, Any]:
    """逐档核对工件合同、样本数量、门禁和故障覆盖。"""

    if not input_dirs:
        raise ValueError("至少需要一个压力结果目录")
    levels: list[dict[str, Any]] = []
    task_counts: list[int] = []
    for input_dir in input_dirs:
        root = Path(input_dir)
        summary = json.loads(
            (root / "platform_task_stress_fault_summary.json").read_text(encoding="utf-8")
        )
        samples = _read_csv(root / "platform_task_operation_samples.csv")
        fault_rows = _read_csv(root / "platform_task_fault_cases.csv")
        failures = json.loads(
            (root / "platform_task_stress_fault_failures.json").read_text(encoding="utf-8")
        )["failures"]
        configuration = summary["pressure"]["configuration"]
        task_count = int(configuration["task_count"])
        worker_count = int(configuration["worker_count"])
        burst = int(configuration["idempotency_burst"])
        conflict_count = max(4, min(burst, worker_count))
        expected_samples = task_count + burst + conflict_count + 3 * (task_count + 1)
        operation_counts: dict[str, int] = {}
        for row in samples:
            operation_counts[row["operation"]] = operation_counts.get(row["operation"], 0) + 1
        checks = {
            "summary_passed": summary["passed"] is True,
            "all_pressure_checks_passed": all(summary["pressure"]["checks"].values()),
            "sample_count_complete": len(samples) == expected_samples,
            "operation_counts_complete": operation_counts == {
                "create": task_count,
                "idempotent_create": burst,
                "idempotency_conflict": conflict_count,
                "claim": task_count + 1,
                "heartbeat": task_count + 1,
                "cancel": task_count + 1,
            },
            "fault_ids_complete": {row["case_id"] for row in fault_rows} == EXPECTED_FAULT_IDS,
            "all_faults_passed": len(fault_rows) == 6 and all(row["passed"] == "True" for row in fault_rows),
            "failure_file_empty": failures == [],
            "test_project_cleaned": summary["cleanup"]["project_deleted"] is True,
        }
        levels.append({
            "input_dir": str(root),
            "task_count": task_count,
            "worker_count": worker_count,
            "idempotency_burst": burst,
            "passed": all(checks.values()),
            "checks": checks,
            "sample_count": len(samples),
            "create_throughput_per_s": summary["pressure"]["create_throughput_per_s"],
            "claim_throughput_per_s": summary["pressure"]["claim_throughput_per_s"],
            "claimed_worker_count": summary["pressure"]["claimed_worker_count"],
            "latencies": summary["pressure"]["latencies"],
        })
        task_counts.append(task_count)
    summary = {
        "schema_version": "1.0",
        "accepted": all(level["passed"] for level in levels)
        and task_counts == sorted(set(task_counts)),
        "level_count": len(levels),
        "task_counts_strictly_increasing": task_counts == sorted(set(task_counts)),
        "levels": levels,
        "limitations": [
            "容量对照仅代表当前本机PostgreSQL测试实例。",
            "测试不包含算法本体执行时间。",
            "目标平台仍需按实际连接池、网络和硬件重复测试。",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "platform_task_stress_scale_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 平台任务压力容量对照",
        "",
        f"结论：`{'PASS' if summary['accepted'] else 'FAIL'}`；共核验{len(levels)}档真实PostgreSQL压力结果。",
        "",
        "| 任务数 | 并发worker | 幂等突发 | 创建吞吐/项每秒 | 领取吞吐/项每秒 | 创建P95/ms | 领取P95/ms | 心跳P95/ms | 取消P95/ms |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for level in levels:
        latency = level["latencies"]
        lines.append(
            f"| {level['task_count']} | {level['worker_count']} | {level['idempotency_burst']} | "
            f"{level['create_throughput_per_s']} | {level['claim_throughput_per_s']} | "
            f"{latency['create']['p95_ms']} | {latency['claim']['p95_ms']} | "
            f"{latency['heartbeat']['p95_ms']} | {latency['cancel']['p95_ms']} |"
        )
    lines.extend([
        "",
        "每档均验证任务唯一领取、同键幂等、异内容冲突、心跳、取消、状态事件完整、六类故障注入和测试项目清理。",
        "本报告不定义生产SLA；吞吐和时延只能作为当前测试机基线。",
    ])
    (output_dir / "PLATFORM_TASK_STRESS_SCALE_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", action="append", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "platform_task_stress_fault_scale_matrix",
    )
    args = parser.parse_args()
    summary = verify_results(args.input_dir, args.output_dir)
    print(json.dumps({
        "accepted": summary["accepted"],
        "level_count": summary["level_count"],
        "report": str(args.output_dir / "PLATFORM_TASK_STRESS_SCALE_REPORT.md"),
    }, ensure_ascii=False))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
