"""Measure capacity trends across repeatable command sizes.

The default matrix is intentionally lightweight.  Pass ``--command`` to
measure another command; ``{scale}`` is replaced by the case scale value.
No algorithm parameters are changed globally and no results are interpreted as
energy-quality conclusions.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_CASES = (1, 2, 4, 8)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/performance_capacity"))
    parser.add_argument("--case", type=int, action="append", dest="cases", help="scale value; repeatable")
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--command", nargs=argparse.REMAINDER, help="command after --; use {scale} placeholder")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = args.cases or list(DEFAULT_CASES)
    command_template = args.command or ["tests/smoke/verify_energy_scenarios.py"]
    if command_template and command_template[0] == "--":
        command_template = command_template[1:]
    scale_placeholder = any("{scale}" in part for part in command_template)
    rows: list[dict[str, object]] = []
    for scale in cases:
        command = [part.replace("{scale}", str(scale)) for part in command_template]
        started = time.perf_counter()
        try:
            completed = subprocess.run(command if command and command[0].endswith(".py") is False else [sys.executable, *command], cwd=root, capture_output=True, text=True, check=False, timeout=args.timeout_s, env={**os.environ, "PYTHONHASHSEED": "0"})
            timed_out = False
            return_code = completed.returncode
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            return_code = 124
            stderr = (exc.stderr or "") + f"\ntimeout after {args.timeout_s}s"
        elapsed = round(time.perf_counter() - started, 3)
        rows.append({"scale": scale, "command": command, "scale_applied": scale_placeholder, "return_code": return_code, "passed": return_code == 0 and not timed_out, "timed_out": timed_out, "elapsed_s": elapsed, "stderr_tail": stderr[-800:]})
    valid_times = [float(row["elapsed_s"]) for row in rows if row["passed"]]
    summary = {"schema_version": "1.0", "command_template": command_template, "scale_placeholder_used": scale_placeholder, "timeout_s": args.timeout_s, "cases": rows, "passed_count": sum(1 for row in rows if row["passed"]), "failed_count": sum(1 for row in rows if not row["passed"]), "min_elapsed_s": min(valid_times) if valid_times else None, "max_elapsed_s": max(valid_times) if valid_times else None}
    (output_dir / "capacity_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scale_note = "命令使用 `{scale}`，规模参数已实际替换。" if scale_placeholder else "命令未包含 `{scale}`；本次仅重复启动基准命令，不能解释为算法规模扩展。"
    lines = ["# 性能容量分析", "", "本报告以固定命令、固定 `PYTHONHASHSEED=0` 和超时边界观察规模变化；不修改算法逻辑，也不把耗时直接解释为节能效果。", "", f"- 测试命令模板：`{' '.join(command_template)}`", f"- 通过：{summary['passed_count']} / {len(rows)}", f"- 规模参数：{scale_note}", "", "| 规模/重复标记 | 返回码 | 状态 | 耗时 (s) |", "| ---: | ---: | --- | ---: |"]
    lines.extend(f"| {row['scale']} | {row['return_code']} | {'PASS' if row['passed'] else 'FAIL' + (' (TIMEOUT)' if row['timed_out'] else '')} | {row['elapsed_s']} |" for row in rows)
    lines.extend(["", "## 解读", "", "若耗时随规模快速增长，应优先在正式数据到位后对候选评估、场景切片和结算桶进行 profile；本工具只提供容量信号，不自动调整种群、代数或结算步长。"])
    (output_dir / "CAPACITY_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output_dir / "CAPACITY_ANALYSIS.md"), "summary": str(output_dir / "capacity_summary.json"), "failed_count": summary["failed_count"]}, ensure_ascii=False))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
