"""汇总安全审计证据，区分审计完成状态与生产发布状态。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release_common import verify_source_baseline


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少审计证据：{path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", type=Path, default=ROOT / "outputs/security_audit_20260911")
    args = parser.parse_args()
    audit_root = args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    source = _read_json(audit_root / "source_checks_final/security_source_checks.json")
    composition = _read_json(audit_root / "composition/software_composition_audit.json")
    schema = _read_json(audit_root / "composition/sbom_schema_validation.json")
    release_spec = _read_json(ROOT / "release/package_spec.json")
    release_baseline = _read_json(ROOT / "release/release_baseline.json")

    composition_summary = composition.get("summary", {})
    hash_lock = composition.get("artifact_hash_lock", {})
    evidence_complete = (
        bool(source.get("accepted"))
        and bool(schema.get("accepted"))
        and composition_summary.get("osv_failed_count") == 0
        and composition_summary.get("known_vulnerability_count") == 0
        and composition_summary.get("unknown_license_count") == 0
        and hash_lock.get("valid") is True
    )
    artifacts = []
    for relative in (
        "项目说明文档-9.5.zip",
        "deliverables/database_deployment_integration_package_20260911_v4.zip",
        "deliverables/production_assurance_toolkit_20260911_v2.zip",
    ):
        path = ROOT / relative
        artifacts.append({"path": relative, "exists": path.is_file(), "sha256": _sha256(path) if path.is_file() else None})

    current_spec_hash = _sha256(ROOT / "release/package_spec.json")
    package_spec_matches = current_spec_hash == release_baseline.get("package_spec_sha256")
    source_baseline = verify_source_baseline(ROOT)
    source_baseline_matches = source_baseline.get("status") == "PASS"
    production_release_allowed = evidence_complete and composition.get("status") != "blocked" and source_baseline_matches
    summary = {
        "schema_version": "1.0",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_completed": evidence_complete,
        "production_release_allowed": production_release_allowed,
        "production_blocked": not production_release_allowed,
        "formal_release_version": release_baseline.get("release_version"),
        "working_spec_version": release_spec.get("release_version"),
        "package_spec_matches_frozen_spec": package_spec_matches,
        "working_tree_matches_frozen_spec": source_baseline_matches,
        "source_baseline_error_count": len(source_baseline.get("errors", [])),
        "source_gate": {
            "accepted": source.get("accepted"),
            "scanned_text_files": source.get("scanned_text_files"),
            "scanned_python_files": source.get("scanned_python_files"),
            "reviewed_dynamic_sql_count": len(source.get("reviewed_findings", [])),
        },
        "composition": composition.get("summary"),
        "artifact_hash_lock": hash_lock,
        "composition_status": composition.get("status"),
        "open_findings": composition.get("open_findings", []),
        "cyclonedx_schema_validation": schema,
        "verified_artifacts": artifacts,
    }
    (audit_root / "security_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 依赖、安全与软件成分审计总览", "",
        f"- 审计证据完整：`{str(evidence_complete).lower()}`",
        f"- 允许新生产发布：`{str(production_release_allowed).lower()}`",
        f"- 上一正式冻结版本：`{summary['formal_release_version']}`",
        f"- 工作区匹配冻结基线：`{str(source_baseline_matches).lower()}`", "",
        "## 已验证", "",
        f"- 源码门禁：`PASS`，扫描 {source.get('scanned_text_files')} 个文本文件和 {source.get('scanned_python_files')} 个Python文件。",
        f"- 软件成分：{composition['summary']['component_count']} 个组件，OSV查询失败 {composition['summary']['osv_failed_count']} 个，许可证未知 {composition['summary']['unknown_license_count']} 个。",
        f"- 依赖制品哈希锁：`{'PASS' if hash_lock.get('valid') else 'FAIL'}`，覆盖 {hash_lock.get('locked_component_count')} 个组件。",
        f"- CycloneDX 1.6官方schema：`{'PASS' if schema.get('accepted') else 'FAIL'}`。",
        "- 运行回归结果由独立测试和发布就绪证据记录，不由本审计汇总重复推定。", "",
        "## 开放项", "",
    ]
    lines.extend(f"- [{item['severity']}] {item['message']}" for item in summary["open_findings"])
    if not source_baseline_matches:
        lines.append("- [high] 当前工作区包含未冻结变更；不得把既有验收报告作为当前源码验收报告。")
    lines.extend(["", "## 已核验交付物", "", "| 文件 | 存在 | SHA-256 |", "| --- | --- | --- |"])
    lines.extend(f"| `{item['path']}` | `{str(item['exists']).lower()}` | `{item['sha256'] or ''}` |" for item in artifacts)
    conclusion = (
        "结论：安全审计证据完整，当前工作区满足本工具检查的生产发布条件；仍须完成目标环境和业务验收。"
        if production_release_allowed
        else "结论：安全审计证据已形成，但当前工作区尚不允许生产发布；应先冻结当前变更并完成对应版本验收。"
    )
    lines.extend(["", conclusion, ""])
    (audit_root / "SECURITY_AUDIT_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"audit_completed": evidence_complete, "production_release_allowed": production_release_allowed, "report": str(audit_root / "SECURITY_AUDIT_SUMMARY.md")}, ensure_ascii=False))
    return 0 if evidence_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
