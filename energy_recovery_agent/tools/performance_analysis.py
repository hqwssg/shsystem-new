"""Run a reproducible cProfile benchmark without changing algorithm code.

Examples:
    python tools/performance_analysis.py --output-dir outputs/performance_analysis \
      -- tests/smoke/verify_energy_settlement_correctness.py
    python tools/performance_analysis.py --output-dir outputs/performance_analysis \
      -- run_project.py simulate --search-profile quick --dispatch-population-size 4
"""

from __future__ import annotations

import argparse
import json
import pstats
import subprocess
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    """函数 _parse_args：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/performance_analysis"))
    parser.add_argument("--top", type=int, default=30, help="number of top cumulative functions")
    parser.add_argument("--", dest="separator", nargs="?")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command after --")
    return parser.parse_args()


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if not args.output_dir.is_absolute():
        args.output_dir = project_root / args.output_dir
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = ["tests/smoke/verify_energy_settlement_correctness.py"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = args.output_dir / "profile.prof"
    stdout_path = args.output_dir / "stdout.txt"
    stderr_path = args.output_dir / "stderr.txt"
    report_path = args.output_dir / "PERFORMANCE_REPORT.md"
    summary_path = args.output_dir / "summary.json"
    full_command = [sys.executable, "-m", "cProfile", "-o", str(profile_path), *command]
    started = time.perf_counter()
    completed = subprocess.run(full_command, cwd=project_root, capture_output=True, text=True, check=False)
    wall_s = round(time.perf_counter() - started, 3)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    stats_rows: list[dict[str, object]] = []
    if profile_path.is_file():
        stats = pstats.Stats(str(profile_path)).strip_dirs()
        for (filename, line, function), values in sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[: args.top]:
            cc, nc, tt, ct, callers = values
            stats_rows.append(
                {
                    "function": f"{Path(filename).as_posix()}:{line}::{function}",
                    "calls": nc,
                    "primitive_calls": cc,
                    "total_s": round(tt, 6),
                    "cumulative_s": round(ct, 6),
                }
            )
    summary = {
        "command": command,
        "python": sys.version,
        "return_code": completed.returncode,
        "wall_time_s": wall_s,
        "profile_path": str(profile_path),
        "top_functions": stats_rows,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 性能分析报告",
        "",
        "本报告由独立 `cProfile` 子进程生成，只观测运行时间，不修改算法逻辑、输入或默认参数。",
        "",
        f"- 命令：`{' '.join(command)}`",
        f"- 返回码：`{completed.returncode}`",
        f"- 端到端耗时：`{wall_s:.3f} s`（含 Python 启动与数据读写）",
        f"- 原始 profile：`{profile_path}`",
        "",
        "## 累计耗时最高的函数",
        "",
        "| 函数 | 调用次数 | 自身耗时 (s) | 累计耗时 (s) |",
        "| --- | ---: | ---: | ---: |",
    ]
    if not stats_rows:
        lines.append("| 未生成 profile（命令启动失败或被中断） | — | — | — |")
    else:
        for row in stats_rows:
            lines.append(
                f"| `{row['function']}` | {row['calls']} | {row['total_s']:.6f} | {row['cumulative_s']:.6f} |"
            )
    lines.extend(
        [
            "",
            "## 解读边界",
            "",
            "端到端耗时包含输入解析、输出写盘和 Python 启动；函数累计耗时用于定位热点，不能直接当作算法理论复杂度。",
            "正式数据到位后，应使用固定输入、固定随机种子、固定 profile 和重复次数重新采样，再比较同一函数的累计耗时和输出质量。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "summary": str(summary_path), "return_code": completed.returncode}, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
