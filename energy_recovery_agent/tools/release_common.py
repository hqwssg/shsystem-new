"""发布基线和完整算法交付包共用的文件选择与哈希函数。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "release" / "package_spec.json"
BASELINE_PATH = ROOT / "release" / "release_baseline.json"


def sha256_file(path: Path) -> str:
    """按块计算文件SHA-256，避免大文件一次性进入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """读取根节点为对象的UTF-8 JSON。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON根节点必须是对象：{path}")
    return payload


def load_package_spec(root: Path = ROOT) -> dict[str, Any]:
    """读取并执行发布范围清单的最小结构校验。"""

    spec = load_json(root / "release" / "package_spec.json")
    required = {"schema_version", "release_version", "package_id", "include_globs"}
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError(f"发布范围清单缺少字段：{', '.join(missing)}")
    if not isinstance(spec["include_globs"], list) or not spec["include_globs"]:
        raise ValueError("include_globs必须是非空数组")
    return spec


def selected_source_files(root: Path = ROOT, spec: dict[str, Any] | None = None) -> list[Path]:
    """按白名单选择发布文件，并拒绝缓存、基线自身和越界路径。"""

    spec = spec or load_package_spec(root)
    selected: dict[str, Path] = {}
    root_resolved = root.resolve()
    excluded: set[Path] = set()
    for pattern in spec.get("exclude_globs", []):
        for path in root.glob(str(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root_resolved)
            except ValueError as exc:
                raise ValueError(f"排除文件越出项目根目录：{path}") from exc
            excluded.add(resolved)

    for pattern in spec["include_globs"]:
        for path in root.glob(str(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in excluded:
                continue
            try:
                relative = resolved.relative_to(root_resolved)
            except ValueError as exc:
                raise ValueError(f"发布文件越出项目根目录：{path}") from exc
            if "__pycache__" in relative.parts or resolved.suffix.lower() in {".pyc", ".pyo"}:
                continue
            logical = relative.as_posix()
            if logical == "release/release_baseline.json":
                continue
            selected[logical] = resolved
    for required_path in spec.get("required_entry_points", []):
        if required_path not in selected:
            raise ValueError(f"发布范围缺少必要入口：{required_path}")
    return [selected[key] for key in sorted(selected)]


def file_records(paths: Iterable[Path], root: Path = ROOT) -> list[dict[str, Any]]:
    """为选定文件生成稳定排序的路径、大小和哈希记录。"""

    records = []
    root_resolved = root.resolve()
    for path in paths:
        relative = path.resolve().relative_to(root_resolved).as_posix()
        records.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return sorted(records, key=lambda item: item["path"])


def payload_sha256(records: Iterable[dict[str, Any]]) -> str:
    """计算同时绑定逻辑路径、大小与内容哈希的发布载荷摘要。"""

    digest = hashlib.sha256()
    for item in sorted(records, key=lambda row: str(row["path"])):
        line = f"{item['sha256']}  {item['size']}  {item['path']}\n"
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def verify_source_baseline(root: Path = ROOT) -> dict[str, Any]:
    """核验工作区发布白名单与冻结基线完全一致。"""

    baseline_path = root / "release" / "release_baseline.json"
    if not baseline_path.is_file():
        return {"status": "FAIL", "errors": ["缺少release/release_baseline.json"]}
    baseline = load_json(baseline_path)
    spec = load_package_spec(root)
    errors: list[str] = []
    if baseline.get("release_version") != spec.get("release_version"):
        errors.append("基线版本与发布范围清单不一致")
    if baseline.get("package_spec_sha256") != sha256_file(root / "release" / "package_spec.json"):
        errors.append("发布范围清单哈希与基线不一致")
    interface = load_json(root / "database" / "interface_contract_freeze.json")
    if baseline.get("interface_freeze_version") != spec.get("interface_freeze_version"):
        errors.append("基线接口版本与发布范围清单不一致")
    if baseline.get("interface_freeze_version") != interface.get("freeze_version"):
        errors.append("基线接口版本与当前冻结合同不一致")
    actual_records = file_records(selected_source_files(root, spec), root)
    expected_records = baseline.get("files")
    if not isinstance(expected_records, list):
        errors.append("基线files字段无效")
        expected_records = []
    expected_map = {str(item.get("path")): item for item in expected_records if isinstance(item, dict)}
    actual_map = {item["path"]: item for item in actual_records}
    for path in sorted(set(expected_map) - set(actual_map)):
        errors.append(f"基线文件缺失：{path}")
    for path in sorted(set(actual_map) - set(expected_map)):
        errors.append(f"出现未冻结的发布文件：{path}")
    for path in sorted(set(actual_map) & set(expected_map)):
        if actual_map[path] != expected_map[path]:
            errors.append(f"发布文件已变化：{path}")
    actual_payload_hash = payload_sha256(actual_records)
    if baseline.get("payload_sha256") != actual_payload_hash:
        errors.append("发布载荷聚合哈希不一致")
    return {
        "status": "PASS" if not errors else "FAIL",
        "release_version": baseline.get("release_version"),
        "file_count": len(actual_records),
        "payload_sha256": actual_payload_hash,
        "errors": errors,
    }
