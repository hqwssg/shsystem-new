"""独立运行精确资源可行性求解，并输出机器可读证据。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional, Sequence
import argparse
import json
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exact_resource_feasibility import (
    solve_exact_resource_feasibility,
    solve_quality_optimized_resource_feasibility,
)
from rolling_optimizer import ScheduleTemplate, default_scenarios
from run_dispatch_case import load_case_inputs
from scheduler_nsga2 import build_power_cache


def run(args: argparse.Namespace) -> dict:
    if args.optimize_adjustment_quality and args.max_adjustment_s is not None:
        raise ValueError("质量优化模式由程序搜索偏移边界，不能同时指定--max-adjustment-s。")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    case_inputs = load_case_inputs(Path(args.data_dir), output_dir / "input_check")
    heavy_cache = build_power_cache(
        case_inputs.trains["Heavy"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    empty_cache = build_power_cache(
        case_inputs.trains["Empty"],
        case_inputs.route,
        power_arm_interval_path=case_inputs.power_arm_path,
        storage_sections=case_inputs.storage_sections,
    )
    template = ScheduleTemplate(
        heavy_headway_s=args.heavy_headway_s,
        empty_headway_s=args.empty_headway_s,
        heavy_empty_phase_s=args.phase_s,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
    )
    started = time.perf_counter()
    common_arguments = {
        "horizon_s": args.horizon_s,
        "time_limit_s": args.time_limit_s,
        "include_multi_capacity_resources": args.full_capacity_model,
    }
    if args.optimize_adjustment_quality:
        result = solve_quality_optimized_resource_feasibility(
            template,
            default_scenarios(),
            case_inputs.resource_model,
            heavy_cache,
            empty_cache,
            initial_adjustment_bound_s=args.initial_adjustment_bound_s,
            **common_arguments,
        )
    else:
        result = solve_exact_resource_feasibility(
            template,
            default_scenarios(),
            case_inputs.resource_model,
            heavy_cache,
            empty_cache,
            max_adjustment_s=args.max_adjustment_s,
            **common_arguments,
        )
    payload = {
        "schema_version": "1.0",
        "data_status": "planning_and_placeholder_inputs",
        "status": result.status,
        "proof": result.proof,
        "elapsed_s": round(time.perf_counter() - started, 6),
        "output_path": str(output_dir / "exact_resource_feasibility.json"),
        "base_template": asdict(template),
        "solved_template": None if result.schedule_template is None else asdict(result.schedule_template),
        "diagnostics": dict(result.diagnostics),
        "interpretation": {
            "feasible_verified": "精确层找到整数秒方案，且现有完整资源检查器验证通过。",
            "model_infeasible": "HiGHS已证明指定时域和变量边界内的资源模型不可行。",
            "solver_limit_no_solution": "达到求解上限且尚无解，模型可行性仍未知。",
            "solver_candidate_rejected": "MILP候选未通过完整检查，模型可行性仍未知。",
            "solver_error": "求解器异常，模型可行性仍未知。"
        }.get(result.status, "未知状态"),
    }
    (output_dir / "exact_resource_feasibility.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="精确判定重空协同调度的核心稳健资源可行性。")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "real_shuohuang")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper" / "experiments" / "dispatch_exact_resource")
    parser.add_argument("--heavy-count", type=int, default=8)
    parser.add_argument("--empty-count", type=int, default=8)
    parser.add_argument("--heavy-headway-s", type=int, default=1800)
    parser.add_argument("--empty-headway-s", type=int, default=1800)
    parser.add_argument("--phase-s", type=int, default=1590)
    parser.add_argument("--horizon-s", type=int, default=14400)
    parser.add_argument("--max-adjustment-s", type=int)
    parser.add_argument("--time-limit-s", type=float, default=300.0)
    parser.add_argument("--full-capacity-model", action="store_true")
    parser.add_argument("--optimize-adjustment-quality", action="store_true")
    parser.add_argument("--initial-adjustment-bound-s", type=int, default=600)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run(args)
    print(json.dumps({
        "status": payload["status"],
        "proof": payload["proof"],
        "elapsed_s": payload["elapsed_s"],
        "output": payload["output_path"],
    }, ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"feasible_verified", "model_infeasible"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
