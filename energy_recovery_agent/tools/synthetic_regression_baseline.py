"""Create or verify a reproducible synthetic regression baseline.

The baseline stores scenario pass/fail, normalized output fingerprints, and
timing observations.  Timing is diagnostic only; output fingerprints and
return codes are the strict regression signals.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from synthetic_scenario_matrix import SCENARIOS, run_matrix


def _stable_results(report: dict[str, object]) -> list[dict[str, object]]:
    """函数 _stable_results：执行该模块中的相关处理逻辑。"""
    stable: list[dict[str, object]] = []
    for result in report["scenarios"]:
        stable.append(
            {
                "scenario_id": result["scenario_id"],
                "script": result["script"],
                "expected": result["expected"],
                "return_code": result["return_code"],
                "passed": result["passed"],
                "timed_out": result["timed_out"],
                "output_fingerprint": result["output_fingerprint"],
            }
        )
    return stable


def _compare(expected: dict[str, object], current: dict[str, object]) -> list[str]:
    """函数 _compare：执行该模块中的相关处理逻辑。"""
    expected_by_id = {row["scenario_id"]: row for row in expected.get("scenarios", [])}
    current_by_id = {row["scenario_id"]: row for row in _stable_results(current)}
    differences: list[str] = []
    for scenario_id in sorted(set(expected_by_id) | set(current_by_id)):
        before = expected_by_id.get(scenario_id)
        after = current_by_id.get(scenario_id)
        if before is None or after is None:
            differences.append(f"{scenario_id}: scenario set changed")
            continue
        for key in ("script", "return_code", "passed", "timed_out", "output_fingerprint"):
            if before.get(key) != after.get(key):
                differences.append(f"{scenario_id}: {key} {before.get(key)!r} -> {after.get(key)!r}")
    return differences


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/synthetic_regression_baseline"))
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("tests/fixtures/synthetic_regression_baseline.json"),
        help="受版本控制的稳定基线JSON。",
    )
    parser.add_argument("--write-baseline", action="store_true", help="write/replace baseline after a successful run")
    parser.add_argument("--scenario", action="append", dest="scenario_ids", help="run only this scenario id; repeatable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    current = run_matrix(root, args.scenario_ids)
    baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
    stable = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "scenario_ids": [scenario.scenario_id for scenario in SCENARIOS if not args.scenario_ids or scenario.scenario_id in set(args.scenario_ids)],
        "scenarios": _stable_results(current),
    }
    report_lines = [
        "# 合成数据回归基线",
        "",
        "该基线固定场景脚本、Python 哈希种子和输出指纹；耗时仅作诊断，不作为硬失败条件。",
        "",
        f"- 场景数：{current['scenario_count']}",
        f"- 通过：{current['passed_count']}",
        f"- 失败：{current['failed_count']}",
        "",
        "| 场景 | 返回码 | 状态 | 耗时 (s) | 输出指纹 |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for result in current["scenarios"]:
        report_lines.append(f"| `{result['scenario_id']}` | {result['return_code']} | {'PASS' if result['passed'] else 'FAIL'} | {result['elapsed_s']} | `{result['output_fingerprint'][:12]}` |")
    report_lines.extend(["", "基线 JSON：`baseline.json`；最近一次比对：`latest_check.json`。"])
    (output_dir / "BASELINE_REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    if args.write_baseline:
        if current["failed_count"]:
            print("cannot write baseline: scenario failures detected")
            return 1
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(stable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"mode": "write", "baseline": str(baseline_path), "scenario_count": len(stable["scenarios"])}, ensure_ascii=False))
        return 0
    if not baseline_path.is_file():
        print(json.dumps({"mode": "check", "status": "missing_baseline", "baseline": str(baseline_path)}, ensure_ascii=False))
        return 2
    expected = json.loads(baseline_path.read_text(encoding="utf-8"))
    differences = _compare(expected, current)
    payload = {"mode": "check", "status": "PASS" if not differences and current["failed_count"] == 0 else "FAIL", "differences": differences, "scenario_count": current["scenario_count"], "failed_count": current["failed_count"]}
    (output_dir / "latest_check.json").write_text(json.dumps({**payload, "current": current}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
