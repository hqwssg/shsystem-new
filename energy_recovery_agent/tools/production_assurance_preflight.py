"""执行无需甲方环境的生产保障预检，并明确列出仍待外部验收的项目。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.operational_readiness_checks import run_checks as run_operational_checks
from tools.production_operations_snapshot import build_snapshot, load_policy, write_reports
from tools.release_common import verify_source_baseline


REQUIRED_FILES = (
    "operations/production_assurance_policy.json",
    "database/database.env.example",
    "tools/deploy_database.ps1",
    "tools/database_healthcheck.py",
    "tools/run_database_worker_loop.py",
    "tools/production_operations_snapshot.py",
    "tools/production_database_backup_restore.py",
    "tools/build_production_assurance_package.py",
    "tools/verify_production_assurance_package.py",
    "docs/production_operations_runbook.md",
    "docs/production_monitoring_and_incident_response.md",
    "docs/production_backup_restore_drill.md",
    "docs/production_assurance_acceptance_checklist.md",
    "docs/production_assurance_toolkit_guide.md",
)
REQUIRED_PACKAGES = ("psycopg", "psutil", "numpy", "scipy")


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "details": details}


def run_preflight(
    output_dir: Path,
    *,
    policy_path: Path,
    database_url: str | None = None,
    require_tls: bool = True,
) -> dict[str, Any]:
    """运行静态、依赖、发布基线和可选数据库检查。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = load_policy(policy_path)
    checks: list[dict[str, Any]] = []
    missing_files = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    checks.append(_check("required_toolkit_files", not missing_files, {"missing": missing_files}))

    versions = {}
    missing_packages = []
    for package in REQUIRED_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing_packages.append(package)
    checks.append(_check("runtime_dependencies", not missing_packages, {
        "versions": versions, "missing": missing_packages,
    }))

    worker = policy["worker"]
    timing_valid = (
        0 < int(worker["heartbeat_interval_seconds"]) < int(worker["lease_seconds"])
        and int(worker["poll_interval_seconds"]) > 0
        and int(worker["max_attempts"]) > 0
    )
    checks.append(_check("worker_timing_policy", timing_valid, worker))

    env_template = (ROOT / "database" / "database.env.example").read_text(encoding="utf-8")
    required_env_names = {
        "SIMULATION_MIGRATOR_DATABASE_URL", "SIMULATION_PLATFORM_DATABASE_URL",
        "SIMULATION_DATABASE_URL", "SIMULATION_READONLY_DATABASE_URL",
        "SIMULATION_ACCEPTANCE_DATABASE_URL", "SIMULATION_BACKUP_SOURCE_DATABASE_URL",
        "POSTGRES_ADMIN_URL", "SIMULATION_WORKER_ID",
    }
    missing_env_names = sorted(name for name in required_env_names if f"{name}=" not in env_template)
    checks.append(_check(
        "credential_template", "REPLACE_ME" in env_template and not missing_env_names,
        {"uses_placeholders": "REPLACE_ME" in env_template, "missing_names": missing_env_names},
    ))

    release = verify_source_baseline(ROOT)
    checks.append(_check("release_source_baseline", release.get("status") == "PASS", release))

    disk = shutil.disk_usage(ROOT)
    free_percent = disk.free / disk.total * 100
    critical_free_percent = float(
        policy["monitoring"]["thresholds"]["host_disk_free_percent"]["critical"]
    )
    checks.append(_check("local_disk_capacity", free_percent > critical_free_percent, {
        "free_bytes": disk.free, "total_bytes": disk.total,
        "free_percent": round(free_percent, 3), "critical_percent": critical_free_percent,
    }))

    operational = run_operational_checks(output_dir / "algorithm_operational_readiness")
    checks.append(_check("algorithm_operational_readiness", bool(operational["passed"]), {
        "summary": "algorithm_operational_readiness/operational_readiness_summary.json"
    }))

    database_check: dict[str, Any]
    if database_url:
        from tools.database_healthcheck import healthcheck

        health = healthcheck(database_url, require_tls=require_tls)
        checks.append(_check("database_healthcheck", bool(health["accepted"]), health))
        snapshot = build_snapshot(database_url, policy)
        write_reports(output_dir / "operations_snapshot", snapshot)
        checks.append(_check("operations_snapshot", bool(snapshot["healthy"]), {
            "highest_severity": snapshot["highest_severity"],
            "summary": "operations_snapshot/production_operations_snapshot.json",
        }))
        database_check = {"executed": True, "require_tls": require_tls}
    else:
        database_check = {
            "executed": False,
            "reason": "未提供数据库连接；目标平台数据库检查保持待外部执行。",
        }

    local_ready = all(item["passed"] for item in checks)
    result = {
        "schema_version": "1.0",
        "policy_version": policy["policy_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_ready": local_ready,
        "production_accepted": False,
        "status": "local_ready_external_pending" if local_ready else "local_preflight_failed",
        "database_check": database_check,
        "checks": checks,
        "external_pending": list(policy["external_acceptance_items"]),
        "boundary": "production_accepted固定为false，直到目标环境验收清单由责任方完成。",
    }
    (output_dir / "production_assurance_preflight.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 生产运行保障预检", "",
        f"- 本地准备：`{'PASS' if local_ready else 'FAIL'}`",
        "- 生产验收：`PENDING_EXTERNAL`",
        f"- 策略版本：`{policy['policy_version']}`", "",
        "| 本地检查 | 状态 |", "| --- | --- |",
    ]
    lines.extend(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} |" for item in checks)
    lines.extend(["", "## 待甲方环境验收", ""])
    lines.extend(f"- [ ] {item}" for item in policy["external_acceptance_items"])
    lines.extend(["", "本地通过不能改写为生产上线、生产SLA或现场联调通过。"])
    (output_dir / "PRODUCTION_ASSURANCE_PREFLIGHT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "production_assurance_preflight")
    parser.add_argument("--policy", type=Path, default=ROOT / "operations" / "production_assurance_policy.json")
    parser.add_argument("--database-url", default=os.environ.get("SIMULATION_ACCEPTANCE_DATABASE_URL"))
    parser.add_argument("--allow-insecure-local-database", action="store_true")
    args = parser.parse_args(argv)
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    policy_path = args.policy if args.policy.is_absolute() else ROOT / args.policy
    result = run_preflight(
        output_dir, policy_path=policy_path, database_url=args.database_url,
        require_tls=not args.allow_insecure_local_database,
    )
    print(json.dumps({
        "local_ready": result["local_ready"], "production_accepted": False,
        "status": result["status"], "output_dir": str(output_dir),
    }, ensure_ascii=False))
    return 0 if result["local_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
