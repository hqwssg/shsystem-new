"""统一执行正式基线、交付包、短回归和全部长耗时发布验收。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from release_common import ROOT, load_package_spec


def acceptance_commands(output_dir: Path, package_dir: Path, zip_path: Path, skip_long: bool) -> list[tuple[str, list[str]]]:
    """返回固定顺序的发布门禁，便于编排器和测试复用。"""

    checks = [
        ("release_package", [sys.executable, "tools/verify_algorithm_delivery_package.py", "--source", "--package-dir", str(package_dir), "--zip", str(zip_path)]),
        ("package_runtime", [sys.executable, "tools/verify_release_package_runtime.py", "--zip", str(zip_path), "--output-dir", str(output_dir / "package_runtime")]),
        ("release_security", [sys.executable, "tools/release_security_gate.py", "--output-dir", str(output_dir / "release_security")]),
        ("interface_contract", [sys.executable, "tools/verify_interface_contract_freeze.py", "--output-dir", str(output_dir / "interface_contract")]),
        ("local_ci", [sys.executable, "tools/run_ci_checks.py", "--output-dir", str(output_dir / "local_ci")]),
        ("short_smoke", [sys.executable, "run_project.py", "smoke"]),
    ]
    if not skip_long:
        checks.append(("long_regression", [sys.executable, "tools/run_long_dispatch_tests.py", "--output-dir", str(output_dir / "long_regression")]))
    return checks


def main() -> int:
    """顺序执行所有发布门禁，任一失败即停止后续高成本检查。"""

    spec = load_package_spec(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "release_acceptance")
    parser.add_argument("--package-dir", type=Path, default=ROOT / "deliverables" / str(spec["package_id"]))
    parser.add_argument("--zip", dest="zip_path", type=Path, default=ROOT / "deliverables" / f"{spec['package_id']}.zip")
    parser.add_argument("--skip-long", action="store_true", help="仅供开发诊断；使用后不能形成正式发布通过结论")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    package_dir = args.package_dir if args.package_dir.is_absolute() else ROOT / args.package_dir
    zip_path = args.zip_path if args.zip_path.is_absolute() else ROOT / args.zip_path
    output_dir.mkdir(parents=True, exist_ok=True)
    checks = acceptance_commands(output_dir, package_dir, zip_path, args.skip_long)
    results: list[dict[str, object]] = []
    started_at = datetime.now(timezone.utc).isoformat()
    for name, command in checks:
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        elapsed = round(time.perf_counter() - started, 3)
        (output_dir / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
        (output_dir / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")
        results.append({
            "name": name,
            "command": command,
            "return_code": completed.returncode,
            "passed": completed.returncode == 0,
            "elapsed_s": elapsed,
        })
        if completed.returncode != 0:
            break
    complete_scope = not args.skip_long and len(results) == len(checks)
    accepted = complete_scope and all(bool(item["passed"]) for item in results)
    summary = {
        "schema_version": "1.0",
        "release_version": spec["release_version"],
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete_scope": complete_scope,
        "long_regression_included": not args.skip_long,
        "accepted": accepted,
        "passed_count": sum(bool(item["passed"]) for item in results),
        "failed_count": sum(not bool(item["passed"]) for item in results),
        "checks": results,
    }
    (output_dir / "release_acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 统一发布验收报告",
        "",
        f"- 发布版本：`{summary['release_version']}`",
        f"- 完整范围：`{summary['complete_scope']}`",
        f"- 发布验收：`{'PASS' if accepted else 'FAIL'}`",
        "",
        "| 门禁 | 状态 | 返回码 | 耗时（秒） |",
        "| --- | --- | ---: | ---: |",
    ]
    lines.extend(
        f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | {item['return_code']} | {item['elapsed_s']} |"
        for item in results
    )
    if args.skip_long:
        lines.extend(["", "本次使用了`--skip-long`，只能作为开发诊断，不能据此批准正式发布。"])
    (output_dir / "RELEASE_ACCEPTANCE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"accepted": accepted, "report": str(output_dir / "RELEASE_ACCEPTANCE_REPORT.md"), "failed_count": summary["failed_count"]}, ensure_ascii=False))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
