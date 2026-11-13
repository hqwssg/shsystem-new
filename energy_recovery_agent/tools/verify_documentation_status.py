"""验证文档状态登记、当前版本、权威入口和本地链接。"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "document_status_registry.json"
TRACKED_SUFFIXES = {".md", ".json", ".docx"}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _tracked_documents() -> set[str]:
    """返回应纳入状态登记的全部项目文档。"""

    return {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "docs").rglob("*")
        if path.is_file() and path.suffix.lower() in TRACKED_SUFFIXES
    }


def _under_prefix(path: str, prefixes: set[str]) -> bool:
    """判断项目相对路径是否位于明确排除的目录中。"""

    normalized = path.replace("\\", "/").rstrip("/")
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in prefixes)


def _check_authority_links(paths: list[str], excluded_prefixes: set[str]) -> list[str]:
    """检查当前权威Markdown中的相对文件链接。"""

    errors: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for target in LINK_PATTERN.findall(text):
            clean = target.split("#", 1)[0].strip()
            if not clean or "://" in clean or clean.startswith("#"):
                continue
            resolved = (path.parent / clean).resolve()
            try:
                target_relative = resolved.relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                target_relative = ""
            if not resolved.exists() and not _under_prefix(target_relative, excluded_prefixes):
                errors.append(f"权威文档链接不存在：{relative} -> {clean}")
    return errors


def main() -> int:
    """执行文档覆盖、唯一分类、版本和禁用旧口径检查。"""

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    categories = registry.get("categories", {})
    errors: list[str] = []
    spec = json.loads((ROOT / "release" / "package_spec.json").read_text(encoding="utf-8"))
    excluded_prefixes = {
        str(path).replace("\\", "/").rstrip("/")
        for path in spec.get("excluded_scopes", {})
        if str(path).replace("\\", "/").startswith("docs/")
    }
    seen: dict[str, str] = {}
    for category, paths in categories.items():
        for relative in paths:
            if relative in seen:
                errors.append(f"文档重复分类：{relative} ({seen[relative]}, {category})")
            seen[relative] = category
            if not (ROOT / relative).is_file() and not _under_prefix(relative, excluded_prefixes):
                errors.append(f"登记文档不存在：{relative}")

    tracked = _tracked_documents()
    registered = set(seen)
    for relative in sorted(tracked - registered):
        errors.append(f"文档未分类：{relative}")
    for relative in sorted(registered - tracked):
        if _under_prefix(relative, excluded_prefixes):
            continue
        errors.append(f"登记项不属于当前文档：{relative}")

    authority_entry = str(registry.get("authority_entry", ""))
    if seen.get(authority_entry) != "current_authority":
        errors.append("唯一权威入口未归类为 current_authority")

    release_version = str(registry.get("release_version", ""))
    if release_version != str(spec.get("release_version", "")):
        errors.append("文档登记版本与发布规格版本不一致")

    baseline_text = (ROOT / authority_entry).read_text(encoding="utf-8") if authority_entry else ""
    required_fragments = [release_version, "94 个", "production_accepted=false", "终端 SOC 偏差为 0"]
    for fragment in required_fragments:
        if fragment not in baseline_text:
            errors.append(f"当前文档基线缺少关键口径：{fragment}")

    forbidden_current_fragments = [
        "默认短耗时集合为91项",
        "algorithm_release_20260910_v2",
        "终端SOC仍有7126.289",
    ]
    authority_paths = list(categories.get("current_authority", []))
    for relative in authority_paths:
        path = ROOT / relative
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in forbidden_current_fragments:
            if fragment in text:
                errors.append(f"当前权威文档仍含过时口径：{relative} -> {fragment}")

    errors.extend(_check_authority_links(authority_paths, excluded_prefixes))
    result = {
        "schema_version": "1.0",
        "release_version": release_version,
        "tracked_document_count": len(tracked),
        "registered_document_count": len(registered),
        "category_counts": {key: len(value) for key, value in categories.items()},
        "authority_entry": authority_entry,
        "accepted": not errors,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
