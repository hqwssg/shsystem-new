"""从已冻结的发布基线构建完整、可校验的算法交付包。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from process_lock import ProcessLock
from release_common import ROOT, load_json, load_package_spec, sha256_file, verify_source_baseline


def _copy_payload(package_root: Path, baseline: dict[str, object]) -> None:
    """严格按基线复制载荷，不在构建时重新解释通配规则。"""

    for item in baseline["files"]:  # type: ignore[index]
        relative = Path(str(item["path"]))
        source = ROOT / relative
        destination = package_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    release_dir = package_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "release" / "release_baseline.json", release_dir / "release_baseline.json")


def _write_checksums(package_root: Path) -> int:
    """为包内除校验清单自身外的每个文件生成SHA-256。"""

    files = sorted(path for path in package_root.rglob("*") if path.is_file() and path.name != "CHECKSUMS.sha256")
    lines = [f"{sha256_file(path)}  {path.relative_to(package_root).as_posix()}" for path in files]
    (package_root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(files) + 1


def _build_time(value: str | None) -> datetime:
    """解析显式构建时间或SOURCE_DATE_EPOCH，便于复现相同ZIP。"""

    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("--built-at-utc必须包含时区。")
        return parsed.astimezone(timezone.utc)
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _write_reproducible_zip(source_root: Path, zip_path: Path, top_level: str, built_at: datetime) -> None:
    """以统一时间、权限和顺序写ZIP，使相同输入与时间得到相同字节。"""

    stamp = max(built_at, datetime(1980, 1, 1, tzinfo=timezone.utc))
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            logical = (Path(top_level) / path.relative_to(source_root)).as_posix()
            info = zipfile.ZipInfo(logical, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    """校验源基线后创建目录包和同名ZIP。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "deliverables")
    parser.add_argument("--package-id")
    parser.add_argument("--built-at-utc", help="固定ISO-8601构建时间；也可使用SOURCE_DATE_EPOCH")
    args = parser.parse_args()
    source_check = verify_source_baseline(ROOT)
    if source_check["status"] != "PASS":
        print(json.dumps(source_check, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    spec = load_package_spec(ROOT)
    baseline = load_json(ROOT / "release" / "release_baseline.json")
    package_id = args.package_id or str(spec["package_id"])
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    package_root = output_root / package_id
    zip_path = output_root / f"{package_id}.zip"
    output_root.mkdir(parents=True, exist_ok=True)
    built_at = _build_time(args.built_at_utc)
    lock_path = output_root / ".algorithm_release_build.lock"
    with ProcessLock(lock_path, "algorithm_release_build"):
        if package_root.exists() or zip_path.exists():
            print(f"交付包目标已存在：{package_root} 或 {zip_path}", file=sys.stderr)
            return 1
        staging_root = Path(tempfile.mkdtemp(prefix=f".{package_id}.staging-", dir=output_root))
        staged_package = staging_root / package_id
        staged_zip = staging_root / f"{package_id}.zip"
        staged_package.mkdir()
        try:
            _copy_payload(staged_package, baseline)
            manifest = {
                "schema_version": "1.0",
                "release_version": baseline["release_version"],
                "package_id": package_id,
                "built_at_utc": built_at.isoformat(),
                "baseline_sha256": sha256_file(ROOT / "release" / "release_baseline.json"),
                "payload_sha256": baseline["payload_sha256"],
                "payload_file_count": baseline["file_count"],
                "interface_freeze_version": baseline["interface_freeze_version"],
                "data_status": baseline["data_status"],
                "entry_points": spec.get("required_entry_points", []),
                "excluded_scopes": spec.get("excluded_scopes", {}),
            }
            (staged_package / "RELEASE_MANIFEST.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            file_count = _write_checksums(staged_package)
            _write_reproducible_zip(staged_package, staged_zip, package_id, built_at)
            staged_package.replace(package_root)
            try:
                staged_zip.replace(zip_path)
            except Exception:
                shutil.rmtree(package_root, ignore_errors=True)
                raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
    result = {
        "package_root": str(package_root),
        "zip_path": str(zip_path),
        "release_version": baseline["release_version"],
        "file_count": file_count,
        "zip_sha256": sha256_file(zip_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
