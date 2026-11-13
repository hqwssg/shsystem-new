"""构建不含凭据和数据库备份本体的生产运行保障工具包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = "2026.09.11.2"
DEFAULT_PACKAGE_ID = "production_assurance_toolkit_20260911_v2"

SOURCE_FILES = (
    "requirements.txt", "requirements-database.txt",
    "operations/README.md", "operations/production_assurance_policy.json",
    "operations/production_worker.env.example",
    "database/database.env.example",
    "tools/production_operations_snapshot.py", "tools/production_assurance_preflight.py",
    "tools/production_database_backup_restore.py", "tools/run_local_production_assurance.py",
    "tools/build_production_assurance_package.py", "tools/verify_production_assurance_package.py",
    "tools/operational_readiness_checks.py", "tools/release_common.py", "tools/safe_zip.py",
    "tools/database_healthcheck.py", "tools/verify_target_database_access.py",
    "tools/run_database_worker_loop.py", "tools/deploy_database.ps1",
    "tools/platform_task_stress_fault.py", "tools/run_database_five_run_acceptance.py",
    "tools/run_release_acceptance.py", "tools/run_long_dispatch_tests.py",
    "docs/production_operations_runbook.md", "docs/production_monitoring_and_incident_response.md",
    "docs/production_backup_restore_drill.md", "docs/production_assurance_acceptance_checklist.md",
    "docs/production_assurance_toolkit_guide.md",
    "docs/database_delivery_package_guide.md", "docs/database_integration_guide.md",
    "docs/database_platform_integration_checklist.md", "docs/platform_task_stress_fault.md",
    "docs/long_test_performance_gate.md", "release/long_test_performance_gate.json",
    "release/package_spec.json", "release/release_baseline.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-id", default=DEFAULT_PACKAGE_ID)
    parser.add_argument("--output-root", type=Path, default=ROOT / "deliverables")
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--release-acceptance", type=Path, required=True)
    args = parser.parse_args(argv)
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    evidence = args.local_evidence if args.local_evidence.is_absolute() else ROOT / args.local_evidence
    release = args.release_acceptance if args.release_acceptance.is_absolute() else ROOT / args.release_acceptance
    package_root = output_root / args.package_id
    zip_path = output_root / f"{args.package_id}.zip"
    if package_root.exists() or zip_path.exists():
        raise RuntimeError(f"交付目标已存在，拒绝覆盖：{package_root} / {zip_path}")
    evidence_files = (
        "local_production_assurance_summary.json", "LOCAL_PRODUCTION_ASSURANCE_REPORT.md",
        "preflight/production_assurance_preflight.json", "preflight/PRODUCTION_ASSURANCE_PREFLIGHT.md",
        "operations_snapshot/production_operations_snapshot.json",
        "operations_snapshot/PRODUCTION_OPERATIONS_SNAPSHOT.md",
        "backup_restore/backup_restore_drill.json", "backup_restore/BACKUP_RESTORE_DRILL.md",
        "toolkit_smoke.stdout.txt", "toolkit_smoke.stderr.txt",
    )
    release_files = (
        "release_acceptance_summary.json", "RELEASE_ACCEPTANCE_REPORT.md",
        "long_regression/long_dispatch_tests.json", "long_regression/LONG_DISPATCH_TESTS.md",
    )
    required = [ROOT / path for path in SOURCE_FILES]
    required.extend(evidence / path for path in evidence_files)
    required.extend(release / path for path in release_files)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"生产保障工具包缺少必要文件：{missing}")
    package_root.mkdir(parents=True)
    try:
        for relative in SOURCE_FILES:
            _copy(ROOT / relative, package_root / relative)
        for relative in evidence_files:
            _copy(evidence / relative, package_root / "evidence/local" / relative)
        for relative in release_files:
            _copy(release / relative, package_root / "evidence/release" / relative)
        manifest = {
            "schema_version": "1.0", "package_version": PACKAGE_VERSION,
            "package_id": args.package_id,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "algorithm_release_version": json.loads(
                (ROOT / "release/package_spec.json").read_text(encoding="utf-8")
            )["release_version"],
            "local_ready": True, "production_accepted": False,
            "contains_database_backup": False, "contains_credentials": False,
            "external_acceptance_required": True,
        }
        (package_root / "PRODUCTION_ASSURANCE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files = sorted(path for path in package_root.rglob("*") if path.is_file())
        checksum_lines = [
            f"{_sha256(path)}  {path.relative_to(package_root).as_posix()}" for path in files
        ]
        (package_root / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(args.package_id) / path.relative_to(package_root))
    except Exception:
        shutil.rmtree(package_root, ignore_errors=True)
        if zip_path.exists():
            zip_path.unlink()
        raise
    print(json.dumps({
        "package_root": str(package_root), "zip_path": str(zip_path),
        "package_version": PACKAGE_VERSION,
        "file_count": sum(path.is_file() for path in package_root.rglob("*")),
        "zip_sha256": _sha256(zip_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
