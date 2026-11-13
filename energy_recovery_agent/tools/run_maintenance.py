"""执行日常维护检查并生成统一、非破坏性的状态报告。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from process_lock import ProcessLock
from release_common import ROOT, load_json


def _run(name: str, command: list[str], severity: str, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    elapsed = round(time.perf_counter() - started, 3)
    (output_dir / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
    (output_dir / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")
    return {"name": name, "command": command, "severity": severity, "passed": completed.returncode == 0, "return_code": completed.returncode, "elapsed_s": elapsed}


def _artifact_command(item: dict[str, Any]) -> list[str]:
    verifier = str(item["verifier"])
    if verifier.endswith("verify_algorithm_delivery_package.py"):
        return [sys.executable, verifier, "--package-dir", str(item["directory"]), "--zip", str(item["zip"])]
    if verifier.endswith("verify_project_documentation_package.py"):
        return [sys.executable, verifier, "--package-dir", str(item["directory"]), "--zip", str(item["zip"])]
    return [sys.executable, verifier, "--package-dir", str(item["directory"]), "--zip", str(item["zip"])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/maintenance_current")
    parser.add_argument("--full-smoke", action="store_true", help="在CI后追加94项默认短测")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = load_json(ROOT / "maintenance/maintenance_policy.json")
    accepted_release = load_json(ROOT / "release/accepted_release.json")
    lock_path = ROOT / "outputs/.maintenance.lock"
    with ProcessLock(lock_path, "project_maintenance"):
        checks: list[tuple[str, list[str], str]] = [
            ("local_ci", [sys.executable, "tools/run_ci_checks.py", "--output-dir", str(output_dir / "ci")], "blocking"),
            ("project_hygiene", [sys.executable, "tools/project_hygiene.py", "report", "--no-hashes", "--output-dir", str(output_dir / "hygiene")], "blocking"),
            ("release_readiness", [sys.executable, "tools/release_readiness.py", "--stage", "maintenance", "--output-dir", str(output_dir / "readiness")], "advisory"),
        ]
        artifact_specs = [
            {
                "name": "algorithm_release",
                "directory": accepted_release["package_directory"],
                "zip": accepted_release["package_zip"],
                "verifier": "tools/verify_algorithm_delivery_package.py",
            },
            *policy["current_artifacts"],
        ]
        for item in artifact_specs:
            checks.append((f"artifact_{item['name']}", _artifact_command(item), "blocking"))
        if args.full_smoke:
            checks.append(("default_short_smoke", [sys.executable, "run_project.py", "smoke"], "blocking"))
        results = [_run(name, command, severity, output_dir) for name, command, severity in checks]

    blocking_failures = [item for item in results if item["severity"] == "blocking" and not item["passed"]]
    advisory_failures = [item for item in results if item["severity"] == "advisory" and not item["passed"]]
    summary = {
        "schema_version": "1.0", "policy_version": policy["policy_version"],
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "maintenance_passed": not blocking_failures,
        "production_release_ready": not advisory_failures and not blocking_failures,
        "blocking_failure_count": len(blocking_failures), "advisory_failure_count": len(advisory_failures),
        "automatic_deletion": policy["retention"]["automatic_deletion"], "checks": results,
    }
    (output_dir / "maintenance_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 项目维护总览", "", f"- 维护检查：`{'PASS' if summary['maintenance_passed'] else 'FAIL'}`",
        f"- 生产发布就绪：`{str(summary['production_release_ready']).lower()}`",
        f"- 自动删除：`{str(summary['automatic_deletion']).lower()}`", "",
        "| 检查 | 状态 | 级别 | 耗时（秒） |", "| --- | --- | --- | ---: |",
    ]
    lines.extend(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | `{item['severity']}` | {item['elapsed_s']} |" for item in results)
    lines.extend(["", "说明：发布就绪失败不会阻止日常维护完成；它表示不得生成新的正式生产发布。维护流程不自动删除或覆盖任何历史证据。", ""])
    (output_dir / "MAINTENANCE_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"maintenance_passed": summary["maintenance_passed"], "production_release_ready": summary["production_release_ready"], "report": str(output_dir / "MAINTENANCE_SUMMARY.md")}, ensure_ascii=False))
    return 0 if summary["maintenance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
