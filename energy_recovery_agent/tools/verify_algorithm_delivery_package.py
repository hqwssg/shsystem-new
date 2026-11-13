"""核验完整算法交付目录或ZIP的文件集合、哈希和正式基线。"""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from release_common import ROOT, load_json, payload_sha256, sha256_file, verify_source_baseline
from safe_zip import safe_extract_zip


def _parse_checksums(path: Path) -> tuple[dict[str, str], list[str]]:
    """读取标准双空格分隔的SHA-256清单。"""

    checksums: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            errors.append(f"校验清单第{line_number}行格式错误")
            continue
        digest, logical = parts
        if logical in checksums:
            errors.append(f"校验清单路径重复：{logical}")
        checksums[logical] = digest.lower()
    return checksums, errors


def verify_directory(package_root: Path) -> dict[str, Any]:
    """验证目录包不存在缺失、篡改或未登记文件。"""

    errors: list[str] = []
    checksum_path = package_root / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        return {"status": "FAIL", "package_root": str(package_root), "errors": ["缺少CHECKSUMS.sha256"]}
    checksums, parse_errors = _parse_checksums(checksum_path)
    errors.extend(parse_errors)
    actual_files = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    }
    for logical in sorted(set(checksums) - actual_files):
        errors.append(f"登记文件缺失：{logical}")
    for logical in sorted(actual_files - set(checksums)):
        errors.append(f"存在未登记文件：{logical}")
    for logical in sorted(actual_files & set(checksums)):
        if sha256_file(package_root / logical) != checksums[logical]:
            errors.append(f"文件哈希不一致：{logical}")
    manifest_path = package_root / "RELEASE_MANIFEST.json"
    baseline_path = package_root / "release" / "release_baseline.json"
    if not manifest_path.is_file() or not baseline_path.is_file():
        errors.append("缺少发布清单或正式基线")
        manifest: dict[str, Any] = {}
        baseline: dict[str, Any] = {}
    else:
        manifest = load_json(manifest_path)
        baseline = load_json(baseline_path)
        if manifest.get("baseline_sha256") != sha256_file(baseline_path):
            errors.append("发布清单中的基线哈希不一致")
        if manifest.get("release_version") != baseline.get("release_version"):
            errors.append("发布清单与基线版本不一致")
        records = baseline.get("files", [])
        if not isinstance(records, list) or payload_sha256(records) != baseline.get("payload_sha256"):
            errors.append("基线载荷聚合哈希无效")
        for item in records if isinstance(records, list) else []:
            logical = str(item.get("path", ""))
            path = package_root / logical
            if not path.is_file():
                continue
            if path.stat().st_size != item.get("size") or sha256_file(path) != item.get("sha256"):
                errors.append(f"包内文件不符合正式基线：{logical}")
        expected_files = {str(item.get("path")) for item in records if isinstance(item, dict)}
        expected_files.update({"release/release_baseline.json", "RELEASE_MANIFEST.json"})
        if actual_files != expected_files:
            errors.append("包内文件集合与正式基线不一致")
    return {
        "status": "PASS" if not errors else "FAIL",
        "package_root": str(package_root),
        "release_version": manifest.get("release_version"),
        "file_count": len(actual_files) + 1,
        "checksum_count": len(checksums),
        "errors": errors,
    }


def verify_zip(zip_path: Path) -> dict[str, Any]:
    """安全解压到临时目录后复用目录核验。"""

    with tempfile.TemporaryDirectory(prefix="algorithm_release_verify_") as temporary:
        temporary_root = Path(temporary)
        with zipfile.ZipFile(zip_path) as archive:
            safe_extract_zip(archive, temporary_root)
        roots = [path for path in temporary_root.iterdir() if path.is_dir()]
        if len(roots) != 1:
            return {"status": "FAIL", "zip_path": str(zip_path), "errors": ["ZIP必须只有一个顶层目录"]}
        result = verify_directory(roots[0])
        result["zip_path"] = str(zip_path)
        result["zip_sha256"] = sha256_file(zip_path)
        return result


def main() -> int:
    """按参数核验工作区基线、目录包和ZIP。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="核验当前工作区是否仍匹配正式基线")
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    args = parser.parse_args()
    if not args.source and args.package_dir is None and args.zip_path is None:
        parser.error("至少指定--source、--package-dir或--zip之一")
    result: dict[str, Any] = {"schema_version": "1.0"}
    if args.source:
        result["source"] = verify_source_baseline(ROOT)
    if args.package_dir is not None:
        path = args.package_dir if args.package_dir.is_absolute() else ROOT / args.package_dir
        result["directory"] = verify_directory(path)
    if args.zip_path is not None:
        path = args.zip_path if args.zip_path.is_absolute() else ROOT / args.zip_path
        result["zip"] = verify_zip(path)
    failed = [name for name, item in result.items() if name != "schema_version" and item.get("status") != "PASS"]
    result["status"] = "PASS" if not failed else "FAIL"
    result["failed_targets"] = failed
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
