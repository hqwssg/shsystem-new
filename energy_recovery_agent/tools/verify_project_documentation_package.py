"""验证项目说明文档目录包与ZIP的版本、来源和校验和。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from safe_zip import safe_extract_zip
from build_project_documentation_package import PACKAGE_FILES


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "项目说明文档-9.5"


def _sha256(path: Path) -> str:
    """计算文件SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_directory(package_root: Path) -> dict[str, object]:
    """核对一个已解压文档包。"""

    errors: list[str] = []
    manifest_path = package_root / "DOCUMENTATION_MANIFEST.json"
    checksums_path = package_root / "CHECKSUMS.sha256"
    if not manifest_path.is_file() or not checksums_path.is_file():
        return {"accepted": False, "errors": ["缺少manifest或校验和文件"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = json.loads((ROOT / "release" / "package_spec.json").read_text(encoding="utf-8"))
    if manifest.get("package_id") != PACKAGE_ID:
        errors.append("文档包ID不一致")
    if manifest.get("release_version") != spec.get("release_version"):
        errors.append("文档包版本与当前发布规格不一致")
    if manifest.get("production_accepted") is not False:
        errors.append("文档包不得声明正式生产验收通过")
    documents = manifest.get("documents", [])
    if manifest.get("document_count") != len(documents) or len(documents) < 10:
        errors.append("文档数量与manifest不一致或分类包内容不足")
    expected_sources = {source: target for source, target in PACKAGE_FILES}
    actual_sources = {str(item.get("source", "")): str(item.get("target", "")) for item in documents}
    if actual_sources != expected_sources:
        errors.append("文档包来源集合或目标分类与当前构建规格不一致")
    for item in documents:
        target = package_root / str(item.get("target", ""))
        source = ROOT / str(item.get("source", ""))
        if not target.is_file():
            errors.append(f"包内文档缺失：{item.get('target')}")
        elif _sha256(target) != item.get("sha256"):
            errors.append(f"文档来源哈希不一致：{item.get('target')}")
        if not source.is_file():
            errors.append(f"当前源文档缺失：{item.get('source')}")
        elif _sha256(source) != item.get("sha256"):
            errors.append(f"包内副本已落后于当前源文档：{item.get('source')}")
        if item.get("status") not in {"current_authority", "current_supporting"}:
            errors.append(f"包内含非当前文档：{item.get('target')}")

    expected_checksums: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        expected_checksums[relative] = digest
    actual_files = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    }
    if actual_files != set(expected_checksums):
        errors.append("包内文件集合与校验清单不一致")
    for relative, digest in expected_checksums.items():
        if _sha256(package_root / relative) != digest:
            errors.append(f"逐文件校验失败：{relative}")
    return {
        "accepted": not errors,
        "package_root": str(package_root),
        "release_version": manifest.get("release_version"),
        "document_count": len(documents),
        "errors": errors,
    }


def main() -> int:
    """先验证文档登记，再验证目录包和ZIP。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=ROOT / "deliverables" / "project_documentation_9_5")
    parser.add_argument("--zip", type=Path, default=ROOT / f"{PACKAGE_ID}.zip")
    args = parser.parse_args()
    registry_check = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_documentation_status.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result: dict[str, object] = {
        "registry": json.loads(registry_check.stdout) if registry_check.stdout.strip() else {"accepted": False}
    }
    package_dir = args.package_dir if args.package_dir.is_absolute() else ROOT / args.package_dir
    zip_path = args.zip if args.zip.is_absolute() else ROOT / args.zip
    result["directory"] = _verify_directory(package_dir)
    with tempfile.TemporaryDirectory(prefix="project_documentation_verify_") as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as archive:
            safe_extract_zip(archive, Path(temp_dir))
        extracted = Path(temp_dir) / PACKAGE_ID
        zip_result = _verify_directory(extracted)
        zip_result["zip_path"] = str(zip_path)
        zip_result["zip_sha256"] = _sha256(zip_path)
        result["zip"] = zip_result
    accepted = registry_check.returncode == 0 and all(
        bool(result[key].get("accepted")) for key in ("directory", "zip")  # type: ignore[union-attr]
    )
    result["accepted"] = accepted
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
