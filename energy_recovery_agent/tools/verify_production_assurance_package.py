"""核验生产运行保障工具包的结构、证据边界和逐文件校验和。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Sequence

from safe_zip import safe_extract_zip


REQUIRED_PATHS = {
    "CHECKSUMS.sha256", "PRODUCTION_ASSURANCE_MANIFEST.json",
    "operations/production_assurance_policy.json",
    "tools/production_operations_snapshot.py", "tools/production_assurance_preflight.py",
    "tools/production_database_backup_restore.py", "tools/run_local_production_assurance.py",
    "tools/build_production_assurance_package.py", "tools/verify_production_assurance_package.py",
    "tools/safe_zip.py",
    "docs/production_operations_runbook.md", "docs/production_monitoring_and_incident_response.md",
    "docs/production_backup_restore_drill.md", "docs/production_assurance_acceptance_checklist.md",
    "docs/production_assurance_toolkit_guide.md",
    "evidence/local/local_production_assurance_summary.json",
    "evidence/local/preflight/production_assurance_preflight.json",
    "evidence/local/operations_snapshot/production_operations_snapshot.json",
    "evidence/local/backup_restore/backup_restore_drill.json",
    "evidence/release/release_acceptance_summary.json",
    "evidence/release/long_regression/long_dispatch_tests.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_directory(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise AssertionError(f"工具包目录不存在：{root}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    missing = sorted(REQUIRED_PATHS - actual)
    if missing:
        raise AssertionError(f"工具包缺少必要文件：{missing}")
    forbidden = sorted(path for path in actual if path.endswith(".dump") or "__pycache__" in path or path.endswith(".pyc"))
    if forbidden:
        raise AssertionError(f"工具包包含禁止文件：{forbidden}")
    credential_pattern = re.compile(r"postgres(?:ql)?://[^\s'\"<>]+:[^@\s'\"<>]+@", re.IGNORECASE)
    credential_hits = []
    for relative in sorted(actual):
        path = root / relative
        if path.suffix.lower() not in {".py", ".ps1", ".md", ".json", ".example", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in credential_pattern.findall(text):
            if "REPLACE_ME" not in match and ":...@" not in match:
                credential_hits.append(relative)
                break
    if credential_hits:
        raise AssertionError(f"工具包疑似包含带密码的连接串：{credential_hits}")
    manifest = json.loads((root / "PRODUCTION_ASSURANCE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("local_ready") is not True or manifest.get("production_accepted") is not False:
        raise AssertionError("工具包必须声明本地就绪且生产验收待外部完成。")
    if manifest.get("contains_database_backup") or manifest.get("contains_credentials"):
        raise AssertionError("工具包不得包含数据库备份或凭据。")
    local = json.loads((root / "evidence/local/local_production_assurance_summary.json").read_text(encoding="utf-8"))
    preflight = json.loads((root / "evidence/local/preflight/production_assurance_preflight.json").read_text(encoding="utf-8"))
    snapshot = json.loads((root / "evidence/local/operations_snapshot/production_operations_snapshot.json").read_text(encoding="utf-8"))
    backup = json.loads((root / "evidence/local/backup_restore/backup_restore_drill.json").read_text(encoding="utf-8"))
    release = json.loads((root / "evidence/release/release_acceptance_summary.json").read_text(encoding="utf-8"))
    long_gate = json.loads((root / "evidence/release/long_regression/long_dispatch_tests.json").read_text(encoding="utf-8"))
    if not local.get("local_ready") or local.get("production_accepted") is not False:
        raise AssertionError("本地总控证据状态无效。")
    if not preflight.get("local_ready") or preflight.get("production_accepted") is not False:
        raise AssertionError("预检证据状态无效。")
    if snapshot.get("highest_severity") == "critical" or not snapshot.get("healthy"):
        raise AssertionError("运行快照包含Critical告警。")
    if not backup.get("accepted") or not backup.get("restore_cleaned_up"):
        raise AssertionError("备份恢复证据未通过或未清理隔离库。")
    if not release.get("accepted") or not release.get("complete_scope"):
        raise AssertionError("正式算法发布验收证据未通过。")
    if not long_gate.get("accepted") or not long_gate.get("complete_scope"):
        raise AssertionError("长测性能门禁证据未通过。")
    checksums = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        checksums[relative] = digest
    expected = actual - {"CHECKSUMS.sha256"}
    if set(checksums) != expected:
        raise AssertionError("CHECKSUMS.sha256与文件集合不一致。")
    mismatches = [path for path, digest in checksums.items() if _sha256(root / path) != digest]
    if mismatches:
        raise AssertionError(f"工具包文件哈希不一致：{mismatches}")
    return {
        "accepted": True, "package_root": str(root.resolve()), "file_count": len(actual),
        "checksum_count": len(checksums), "package_version": manifest["package_version"],
        "algorithm_release_version": manifest["algorithm_release_version"],
    }


def verify_zip(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssertionError(f"工具包ZIP不存在：{path}")
    with tempfile.TemporaryDirectory(prefix="production_assurance_verify_") as temp_dir:
        with zipfile.ZipFile(path) as archive:
            safe_extract_zip(archive, Path(temp_dir))
        roots = [item for item in Path(temp_dir).iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise AssertionError("ZIP必须只有一个顶层目录。")
        result = verify_directory(roots[0])
    result["zip_path"] = str(path.resolve())
    result["zip_sha256"] = _sha256(path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--zip", dest="zip_path", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"directory": verify_directory(args.package_dir), "zip": verify_zip(args.zip_path)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
