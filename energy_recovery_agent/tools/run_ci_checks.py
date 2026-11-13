"""运行本地持续集成式质量门禁并写入机器可读报告。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/ci_checks"))
    parser.add_argument("--full-smoke", action="store_true", help="also run the full smoke suite")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    checks = [
        ("compile", [sys.executable, "tools/compile_project.py"]),
        ("code_quality", [sys.executable, "tools/code_quality_gate.py"]),
        ("dependency_lock", [sys.executable, "tests/smoke/verify_dependency_lock.py"]),
        ("prototype_contract", [sys.executable, "tools/validate_prototype_contract.py"]),
        ("prototype_assets", [sys.executable, "tests/smoke/verify_prototype_assets.py"]),
        ("performance_capacity", [sys.executable, "tests/smoke/verify_performance_capacity.py"]),
        ("synthetic_matrix", [sys.executable, "tests/smoke/verify_synthetic_scenario_matrix.py"]),
        ("synthetic_baseline", [sys.executable, "tests/smoke/verify_synthetic_regression_baseline.py"]),
        ("synthetic_data_anomalies", [sys.executable, "tests/smoke/verify_synthetic_data_anomaly_matrix.py"]),
        ("interface_contract_freeze", [sys.executable, "tests/smoke/verify_interface_contract_freeze.py"]),
        ("documentation_status", [sys.executable, "tools/verify_documentation_status.py"]),
        ("security_source", [sys.executable, "tools/security_source_checks.py", "--output-dir", str(output_dir / "security_source")]),
        ("maintenance_release_automation", [sys.executable, "tests/integration/verify_maintenance_release_automation.py"]),
        ("paper_experiment_aggregate", [sys.executable, "tests/smoke/verify_paper_experiment_aggregator.py"]),
        ("abnormal_extreme_inputs", [sys.executable, "tests/smoke/verify_abnormal_extreme_input_suite.py"]),
        ("algorithm_consistency", [sys.executable, "tools/algorithm_consistency_checks.py", "--output-dir", str(output_dir / "algorithm_consistency")]),
        ("algorithm_robustness", [sys.executable, "tools/algorithm_robustness_checks.py", "--output-dir", str(output_dir / "algorithm_robustness")]),
        ("algorithm_properties", [sys.executable, "tools/algorithm_property_checks.py", "--output-dir", str(output_dir / "algorithm_properties")]),
        ("algorithm_extended", [sys.executable, "tools/algorithm_extended_checks.py", "--output-dir", str(output_dir / "algorithm_extended")]),
        ("algorithm_validation", [sys.executable, "tools/algorithm_validation_suite.py", "--output-dir", str(output_dir / "algorithm_validation")]),
        ("operational_readiness", [sys.executable, "tools/operational_readiness_checks.py", "--output-dir", str(output_dir / "operational_readiness")]),
    ]
    if args.full_smoke:
        checks.append(("full_smoke", [sys.executable, "run_project.py", "smoke"]))
    results: list[dict[str, object]] = []
    for name, command in checks:
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        elapsed = round(time.perf_counter() - started, 3)
        (output_dir / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (output_dir / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        results.append({"name": name, "command": command, "return_code": completed.returncode, "passed": completed.returncode == 0, "elapsed_s": elapsed})
    report = {"schema_version": "1.0", "full_smoke": args.full_smoke, "passed_count": sum(1 for row in results if row["passed"]), "failed_count": sum(1 for row in results if not row["passed"]), "checks": results}
    (output_dir / "ci_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 本地 CI 式检查", "", "该检查只验证构建、契约、原型、合成回归和性能工具，不改变算法逻辑。", "", "| 检查 | 状态 | 耗时 (s) |", "| --- | --- | ---: |"]
    lines.extend(f"| `{row['name']}` | {'PASS' if row['passed'] else 'FAIL'} | {row['elapsed_s']} |" for row in results)
    (output_dir / "CI_CHECKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output_dir / "CI_CHECKS.md"), "summary": str(output_dir / "ci_summary.json"), "failed_count": report["failed_count"]}, ensure_ascii=False))
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
