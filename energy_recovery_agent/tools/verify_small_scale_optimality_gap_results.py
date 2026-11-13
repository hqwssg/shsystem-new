"""验收 E12 小规模穷举最优与启发式差距实验输出。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import csv
import json
import math


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT_DIR = ROOT / "paper" / "experiments" / "E12_small_scale_optimality_gap"


def _read_csv(path: Path) -> list[dict[str, str]]:
    """读取实验CSV。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def verify_results(result_dir: Path) -> dict[str, Any]:
    """逐项验证候选完备性、精确最优、差距公式和输出完整性。"""

    summary_path = result_dir / "benchmark_summary.json"
    progress_path = result_dir / "benchmark_progress.json"
    candidates_path = result_dir / "exact_candidates.csv"
    heuristic_path = result_dir / "heuristic_runs.csv"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    candidates = _read_csv(candidates_path)
    heuristic_runs = _read_csv(heuristic_path)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    expected_scales = [int(value) for value in summary["settings"]["scales"]]
    expected_profiles = [str(value) for value in summary["settings"]["profiles"]]
    expected_seeds = [int(value) for value in summary["settings"]["seeds"]]
    domain_count = int(summary["domain"]["candidate_count_per_scale"])
    check("benchmark_completed", summary.get("benchmark_completed") is True, "主摘要完成标志")
    check(
        "progress_completed",
        progress.get("status") == "completed"
        and progress.get("completed_scales") == expected_scales,
        "增量进度覆盖全部请求规模",
    )
    check(
        "candidate_row_count",
        len(candidates) == domain_count * len(expected_scales),
        f"候选行={len(candidates)}，期望={domain_count * len(expected_scales)}",
    )
    check(
        "heuristic_run_count",
        len(heuristic_runs)
        == len(expected_scales) * len(expected_profiles) * len(expected_seeds),
        f"启发式运行={len(heuristic_runs)}",
    )

    exact_checks_passed = True
    uniqueness_passed = True
    gap_checks_passed = True
    no_false_zero_passed = True
    for scale_summary in summary["scale_summaries"]:
        scale = int(scale_summary["scale"])
        scale_rows = [row for row in candidates if int(row["scale"]) == scale]
        keys = {
            (
                row["heavy_headway_s"],
                row["empty_headway_s"],
                row["phase_s"],
                row["hold_s"],
                row["storage_align_shift_s"],
                row["storage_preset_id"],
            )
            for row in scale_rows
        }
        uniqueness_passed &= len(keys) == domain_count
        feasible_rows = [row for row in scale_rows if row["feasible"].lower() == "true"]
        if not feasible_rows:
            exact_checks_passed = False
            continue
        exact_row = min(
            feasible_rows,
            key=lambda row: tuple(float(row[f"selection_key_{index}"]) for index in range(6)),
        )
        expected = float(scale_summary["exact_primary_energy_objective"])
        exact_checks_passed &= math.isclose(
            float(exact_row["primary_energy_objective"]), expected, rel_tol=1e-12, abs_tol=1e-9
        )

    exact_by_scale = {
        int(row["scale"]): float(row["exact_primary_energy_objective"])
        for row in summary["scale_summaries"]
    }
    for row in heuristic_runs:
        found = row["heuristic_found_feasible"].lower() == "true"
        gap_text = row.get("primary_energy_optimality_gap_pct", "").strip()
        if not found:
            no_false_zero_passed &= gap_text == ""
            continue
        candidate = float(row["heuristic_primary_energy_objective"])
        optimum = exact_by_scale[int(row["scale"])]
        expected_gap = 0.0 if math.isclose(candidate, optimum, rel_tol=1e-12, abs_tol=1e-9) else max(
            0.0, (candidate - optimum) / abs(optimum) * 100.0
        )
        gap_checks_passed &= math.isclose(float(gap_text), expected_gap, rel_tol=1e-12, abs_tol=1e-12)

    check("domain_unique_per_scale", uniqueness_passed, "每个规模覆盖完整且无重复的离散域")
    check("exact_best_recomputed", exact_checks_passed, "从候选明细重新计算的词典序最优与摘要一致")
    check("gap_formula", gap_checks_passed, "所有可行运行的主目标差距公式正确")
    check("infeasible_gap_not_zero", no_false_zero_passed, "未找到可行解时差距留空")
    output_files = [
        result_dir / "SMALL_SCALE_OPTIMALITY_GAP_REPORT.md",
        result_dir / "optimality_gap_by_scale.png",
        summary_path,
        candidates_path,
        heuristic_path,
    ]
    check(
        "output_files",
        all(path.is_file() and path.stat().st_size > 0 for path in output_files),
        "报告、图、摘要和两份明细均存在且非空",
    )
    result = {
        "passed": all(item["passed"] for item in checks),
        "check_count": len(checks),
        "failure_count": sum(not item["passed"] for item in checks),
        "checks": checks,
    }
    (result_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行验收并返回适合CI的退出码。"""

    parser = argparse.ArgumentParser(description="验收小规模最优性差距实验输出")
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    args = parser.parse_args(argv)
    result = verify_results(args.result_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
