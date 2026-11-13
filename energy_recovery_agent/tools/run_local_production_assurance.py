"""统一执行本地生产保障预检、运行监控快照和数据库备份恢复演练。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.production_assurance_preflight import run_preflight
from tools.production_database_backup_restore import run_drill
from tools.production_operations_snapshot import build_snapshot, load_policy, write_reports


def _run_smoke(output_root: Path) -> dict[str, Any]:
    """在独立进程执行生产保障专项回归并保留日志。"""
    completed = subprocess.run(
        [sys.executable, "tests/smoke/verify_production_assurance_toolkit.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    (output_root / "toolkit_smoke.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output_root / "toolkit_smoke.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    return {"passed": completed.returncode == 0, "return_code": completed.returncode}


def run_local_assurance(
    *, output_root: Path, policy_path: Path, acceptance_database_url: str,
    readonly_database_url: str, backup_source_url: str, admin_url: str,
    restore_database: str, pg_bin: Path | None,
) -> dict[str, Any]:
    """执行全部可在本机完成的生产保障证据链。"""
    output_root.mkdir(parents=True, exist_ok=True)
    policy = load_policy(policy_path)
    smoke = _run_smoke(output_root)
    preflight = run_preflight(
        output_root / "preflight", policy_path=policy_path,
        database_url=acceptance_database_url, require_tls=False,
    )
    snapshot = build_snapshot(readonly_database_url, policy)
    write_reports(output_root / "operations_snapshot", snapshot)
    backup = run_drill(
        source_url=backup_source_url, admin_url=admin_url,
        restore_database=restore_database, output_dir=output_root / "backup_restore",
        policy_path=policy_path, pg_bin=pg_bin, cleanup=True,
    )
    checks = {
        "toolkit_smoke": bool(smoke["passed"]),
        "preflight_local_ready": bool(preflight["local_ready"]),
        "preflight_production_not_claimed": preflight["production_accepted"] is False,
        "operations_snapshot_healthy": bool(snapshot["healthy"]),
        "backup_restore_accepted": bool(backup["accepted"]),
        "restore_test_database_cleaned": bool(backup["restore_cleaned_up"]),
    }
    local_ready = all(checks.values())
    result = {
        "schema_version": "1.0", "policy_version": policy["policy_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_ready": local_ready, "production_accepted": False,
        "status": "local_ready_external_pending" if local_ready else "local_assurance_failed",
        "checks": checks,
        "evidence": {
            "preflight": "preflight/production_assurance_preflight.json",
            "operations_snapshot": "operations_snapshot/production_operations_snapshot.json",
            "backup_restore": "backup_restore/backup_restore_drill.json",
            "backup_file": backup["backup_path"],
            "backup_sha256": backup["backup_sha256"],
        },
        "external_pending": list(policy["external_acceptance_items"]),
    }
    (output_root / "local_production_assurance_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 本地生产运行保障验收", "", f"- 本地准备：`{'PASS' if local_ready else 'FAIL'}`",
        "- 生产验收：`PENDING_EXTERNAL`", f"- 策略版本：`{policy['policy_version']}`", "",
        "| 检查 | 状态 |", "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in checks.items())
    lines.extend(["", "本报告证明工具包在本地可执行，不替代甲方目标环境验收。"])
    (output_root / "LOCAL_PRODUCTION_ASSURANCE_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "production_assurance_local")
    parser.add_argument("--policy", type=Path, default=ROOT / "operations" / "production_assurance_policy.json")
    parser.add_argument("--acceptance-database-url", default=os.environ.get("SIMULATION_ACCEPTANCE_DATABASE_URL"))
    parser.add_argument("--readonly-database-url", default=os.environ.get("SIMULATION_READONLY_DATABASE_URL"))
    parser.add_argument("--backup-source-url", default=os.environ.get("SIMULATION_BACKUP_SOURCE_DATABASE_URL"))
    parser.add_argument("--admin-url", default=os.environ.get("POSTGRES_ADMIN_URL"))
    parser.add_argument("--restore-database", default="carbon_emissions_restore_test")
    parser.add_argument("--pg-bin", type=Path)
    args = parser.parse_args(argv)
    missing = [name for name, value in {
        "acceptance-database-url": args.acceptance_database_url,
        "readonly-database-url": args.readonly_database_url,
        "backup-source-url": args.backup_source_url,
        "admin-url": args.admin_url,
    }.items() if not value]
    if missing:
        raise RuntimeError(f"本地完整演练缺少连接参数：{', '.join(missing)}")
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    policy_path = args.policy if args.policy.is_absolute() else ROOT / args.policy
    result = run_local_assurance(
        output_root=output_root, policy_path=policy_path,
        acceptance_database_url=args.acceptance_database_url,
        readonly_database_url=args.readonly_database_url,
        backup_source_url=args.backup_source_url, admin_url=args.admin_url,
        restore_database=args.restore_database, pg_bin=args.pg_bin,
    )
    print(json.dumps({
        "local_ready": result["local_ready"], "production_accepted": False,
        "status": result["status"], "output_root": str(output_root),
    }, ensure_ascii=False))
    return 0 if result["local_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
