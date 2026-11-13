"""只读检查维护、候选冻结或正式验收阶段的发布就绪状态。"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.version import Version

from release_common import ROOT, load_json, load_package_spec, sha256_file, verify_source_baseline
from security_source_checks import run_checks as run_source_security_checks


DEFAULT_AUDIT_ROOT = ROOT / "outputs/security_audit_20260911"


def _result(name: str, passed: bool, severity: str, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "severity": severity, "detail": detail}


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else None


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate_readiness(stage: str, audit_root: Path, now: datetime | None = None) -> dict[str, Any]:
    """汇总发布元数据、源码、审计证据和包目标检查。"""

    now = now or datetime.now(timezone.utc)
    spec = load_package_spec(ROOT)
    accepted_release = load_json(ROOT / "release/accepted_release.json")
    policy = load_json(ROOT / "security/audit_policy.json")
    checks: list[dict[str, Any]] = []

    release_version = str(spec["release_version"])
    package_id = str(spec["package_id"])
    match = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})\.(\d+)", release_version)
    expected_package = f"algorithm_release_{''.join(match.groups()[:3])}_v{int(match.group(4))}" if match else ""
    checks.append(_result("release_version_format", bool(match), "blocking", release_version))
    checks.append(_result("package_id_matches_version", bool(match) and package_id == expected_package, "blocking", f"expected={expected_package}, actual={package_id}"))

    registry = load_json(ROOT / "docs/document_status_registry.json")
    checks.append(_result("documentation_version", registry.get("release_version") == release_version, "blocking", f"registry={registry.get('release_version')}, spec={release_version}"))
    docs = subprocess.run([sys.executable, "tools/verify_documentation_status.py"], cwd=ROOT, capture_output=True, text=True, check=False)
    checks.append(_result("documentation_status", docs.returncode == 0, "blocking", docs.stdout.strip() or docs.stderr.strip()))
    accepted_summary_path = ROOT / str(accepted_release.get("acceptance_summary", ""))
    accepted_zip_path = ROOT / str(accepted_release.get("package_zip", ""))
    accepted_summary = _load_optional(accepted_summary_path)
    accepted_pointer_valid = (
        accepted_release.get("status") == "accepted"
        and accepted_summary is not None
        and accepted_summary.get("accepted") is True
        and accepted_summary.get("complete_scope") is True
        and accepted_summary.get("release_version") == accepted_release.get("release_version")
        and sha256_file(accepted_summary_path) == accepted_release.get("acceptance_summary_sha256")
        and accepted_zip_path.is_file()
        and sha256_file(accepted_zip_path) == accepted_release.get("package_zip_sha256")
    )
    checks.append(_result("accepted_release_pointer", accepted_pointer_valid, "blocking", f"version={accepted_release.get('release_version')}, package={accepted_release.get('package_id')}"))

    source = verify_source_baseline(ROOT)
    source_clean = source["status"] == "PASS"
    accepted_version = str(accepted_release.get("release_version", ""))
    if stage == "maintenance":
        checks.append(_result("source_baseline", True, "info", "clean" if source_clean else f"存在未冻结开发变更：{len(source.get('errors', []))}项"))
    elif stage == "candidate":
        try:
            version_advanced = bool(match) and Version(release_version) > Version(accepted_version)
        except ValueError:
            version_advanced = False
        checks.append(_result("release_version_advanced", version_advanced, "blocking", f"accepted={accepted_version}, candidate={release_version}"))
        checks.append(_result("candidate_has_changes", not source_clean, "blocking", "候选版本应包含待冻结变化" if not source_clean else "工作区仍与旧基线完全一致"))
    else:
        checks.append(_result("source_baseline", source_clean, "blocking", "clean" if source_clean else "; ".join(source.get("errors", [])[:10])))
        try:
            candidate_is_new = bool(match) and Version(release_version) > Version(accepted_version)
        except ValueError:
            candidate_is_new = False
        checks.append(_result("candidate_not_yet_accepted", candidate_is_new, "blocking", f"accepted={accepted_version}, candidate={release_version}"))

    source_security = run_source_security_checks()
    checks.append(_result("source_security", bool(source_security.get("accepted")), "blocking", f"blocking={source_security.get('blocking_finding_count')}"))

    composition = _load_optional(audit_root / "composition/software_composition_audit.json")
    schema = _load_optional(audit_root / "composition/sbom_schema_validation.json")
    if composition is None:
        checks.append(_result("composition_evidence", False, "blocking", "缺少软件成分审计证据"))
    else:
        generated = _parse_utc(str(composition["generated_at_utc"]))
        age_days = (now - generated).total_seconds() / 86400
        max_age = int(policy["maximum_vulnerability_data_age_days"])
        summary = composition.get("summary", {})
        checks.append(_result("composition_freshness", 0 <= age_days <= max_age, "blocking", f"age_days={age_days:.3f}, max={max_age}"))
        checks.append(_result("osv_query_complete", summary.get("osv_failed_count") == 0, "blocking", f"failed={summary.get('osv_failed_count')}"))
        checks.append(_result("known_vulnerabilities", summary.get("known_vulnerability_count") == 0, "blocking", f"count={summary.get('known_vulnerability_count')}"))
        checks.append(_result("known_licenses", summary.get("unknown_license_count") == 0, "blocking", f"unknown={summary.get('unknown_license_count')}"))
        hash_lock = composition.get("artifact_hash_lock", {})
        checks.append(_result(
            "artifact_hash_lock",
            hash_lock.get("valid") is True,
            "blocking",
            f"valid={hash_lock.get('valid')}, locked_components={hash_lock.get('locked_component_count')}",
        ))
    checks.append(_result("cyclonedx_schema", bool(schema and schema.get("accepted")), "blocking", "validated" if schema and schema.get("accepted") else "缺少或未通过官方schema验证"))

    minimum = Version(str(policy["runtime_policy"]["production_minimum_python"]))
    current_python = Version(platform.python_version())
    checks.append(_result("supported_python", current_python >= minimum, "blocking", f"current={current_python}, minimum={minimum}"))

    package_dir = ROOT / "deliverables" / package_id
    zip_path = ROOT / "deliverables" / f"{package_id}.zip"
    if stage == "candidate":
        targets_free = not package_dir.exists() and not zip_path.exists()
        checks.append(_result("release_targets_free", targets_free, "blocking", f"directory={package_dir.exists()}, zip={zip_path.exists()}"))
    elif stage == "acceptance":
        checks.append(_result("release_targets_exist", package_dir.is_dir() and zip_path.is_file(), "blocking", f"directory={package_dir.is_dir()}, zip={zip_path.is_file()}"))

    blocking_failures = [item for item in checks if item["severity"] == "blocking" and not item["passed"]]
    return {
        "schema_version": "1.0", "stage": stage, "checked_at_utc": now.isoformat(),
        "release_version": release_version, "package_id": package_id,
        "accepted": not blocking_failures, "blocking_failure_count": len(blocking_failures),
        "checks": checks,
    }


def _write_report(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "release_readiness.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 发布就绪检查", "", f"- 阶段：`{result['stage']}`", f"- 版本：`{result['release_version']}`",
        f"- 结论：`{'PASS' if result['accepted'] else 'BLOCKED'}`", "", "| 检查 | 状态 | 级别 | 说明 |", "| --- | --- | --- | --- |",
    ]
    for item in result["checks"]:
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | `{item['severity']}` | {detail} |")
    (output_dir / "RELEASE_READINESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("maintenance", "candidate", "acceptance"), default="maintenance")
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/release_readiness")
    args = parser.parse_args()
    audit_root = args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = evaluate_readiness(args.stage, audit_root)
    _write_report(output_dir, result)
    print(json.dumps({"accepted": result["accepted"], "stage": result["stage"], "blocking_failure_count": result["blocking_failure_count"], "report": str(output_dir / "RELEASE_READINESS.md")}, ensure_ascii=False))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
