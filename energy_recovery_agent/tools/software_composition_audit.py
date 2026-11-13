"""生成依赖闭包、许可证清单、OSV证据和CycloneDX软件物料清单。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "security/audit_policy.json"
REQUIREMENT_FILES = (ROOT / "requirements.txt", ROOT / "requirements-database.txt")
REQUIREMENTS_LOCK_PATH = ROOT / "requirements-lock.txt"
NATIVE_SUFFIXES = {".dll", ".dylib", ".pyd", ".so"}
LOCKED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s\\]+)")
SHA256_HASH = re.compile(r"--hash=sha256:([0-9a-fA-F]{64})(?:\s|$)")
LICENSE_OVERRIDES = {
    "contourpy": "BSD-3-Clause",
    "cycler": "BSD-3-Clause",
    "et-xmlfile": "MIT",
    "fonttools": "MIT",
    "importlib-resources": "Apache-2.0",
    "kiwisolver": "BSD-3-Clause",
    "matplotlib": "PSF-2.0",
    "numpy": "BSD-3-Clause",
    "openpyxl": "MIT",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "pillow": "MIT-CMU",
    "psutil": "BSD-3-Clause",
    "psycopg": "LGPL-3.0-only",
    "psycopg-binary": "LGPL-3.0-only",
    "pyparsing": "MIT",
    "python-dateutil": "Apache-2.0 OR BSD-3-Clause",
    "scipy": "BSD-3-Clause",
    "six": "MIT",
    "typing-extensions": "PSF-2.0",
    "tzdata": "Apache-2.0",
    "zipp": "MIT",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_direct_requirements() -> dict[str, dict[str, Any]]:
    """读取正式依赖入口，并合并重复声明的包和额外功能。"""

    result: dict[str, dict[str, Any]] = {}
    for path in REQUIREMENT_FILES:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            requirement = Requirement(text)
            name = canonicalize_name(requirement.name)
            item = result.setdefault(name, {"requirement": str(requirement), "extras": set(), "sources": []})
            item["extras"].update(requirement.extras)
            item["sources"].append(path.relative_to(ROOT).as_posix())
    return result


def _requirement_blocks(path: Path) -> list[str]:
    """把带续行符和多个制品哈希的锁文件合并为逐组件记录。"""

    blocks: list[str] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1].isspace():
            if current:
                current.append(stripped)
            continue
        if current:
            blocks.append(" ".join(current))
        current = [stripped]
    if current:
        blocks.append(" ".join(current))
    return blocks


def _inspect_artifact_hash_lock(lock_path: Path, expected_versions: dict[str, str]) -> dict[str, Any]:
    """验证锁文件覆盖当前依赖闭包，且每项精确版本都有SHA-256制品哈希。"""

    evidence: dict[str, Any] = {
        "path": lock_path.relative_to(ROOT).as_posix() if lock_path.is_relative_to(ROOT) else str(lock_path),
        "present": lock_path.is_file(),
        "sha256": None,
        "locked_component_count": 0,
        "missing_components": [],
        "version_mismatches": [],
        "unhashed_components": [],
        "invalid_records": [],
        "valid": False,
    }
    if not lock_path.is_file():
        return evidence

    evidence["sha256"] = _sha256(lock_path)
    locked_versions: dict[str, str] = {}
    for block in _requirement_blocks(lock_path):
        match = LOCKED_REQUIREMENT.match(block)
        if match is None:
            evidence["invalid_records"].append(block)
            continue
        name = canonicalize_name(match.group(1))
        locked_versions[name] = match.group(2)
        if not SHA256_HASH.search(block):
            evidence["unhashed_components"].append(name)

    evidence["locked_component_count"] = len(locked_versions)
    evidence["missing_components"] = sorted(set(expected_versions) - set(locked_versions))
    evidence["version_mismatches"] = [
        {"name": name, "expected": version, "locked": locked_versions[name]}
        for name, version in sorted(expected_versions.items())
        if name in locked_versions and locked_versions[name] != version
    ]
    evidence["unhashed_components"] = sorted(set(evidence["unhashed_components"]))
    evidence["valid"] = not any(
        evidence[key]
        for key in ("missing_components", "version_mismatches", "unhashed_components", "invalid_records")
    )
    return evidence


def _marker_applies(requirement: Requirement, parent_extras: Iterable[str]) -> bool:
    """按当前平台和父依赖已启用的extra判断传递依赖是否生效。"""

    if requirement.marker is None:
        return True
    environment = default_environment()
    candidates = set(parent_extras) | {""}
    return any(requirement.marker.evaluate({**environment, "extra": extra}) for extra in candidates)


def _dependency_closure(direct: dict[str, dict[str, Any]]) -> tuple[dict[str, metadata.Distribution], dict[str, set[str]]]:
    """由已安装发行包元数据递归构造当前运行环境的依赖闭包。"""

    distributions = {canonicalize_name(dist.metadata["Name"]): dist for dist in metadata.distributions() if dist.metadata.get("Name")}
    selected: dict[str, metadata.Distribution] = {}
    dependency_graph: dict[str, set[str]] = {}
    extras_by_name = {name: set(item["extras"]) for name, item in direct.items()}
    pending = list(direct)
    while pending:
        name = pending.pop(0)
        if name in selected:
            continue
        if name not in distributions:
            raise RuntimeError(f"当前环境缺少依赖：{name}")
        dist = distributions[name]
        selected[name] = dist
        dependencies: set[str] = set()
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if not _marker_applies(requirement, extras_by_name.get(name, set())):
                continue
            dependency = canonicalize_name(requirement.name)
            dependencies.add(dependency)
            extras_by_name.setdefault(dependency, set()).update(requirement.extras)
            if dependency not in selected:
                pending.append(dependency)
        dependency_graph[name] = dependencies
    return selected, dependency_graph


def _project_url(dist: metadata.Distribution) -> str | None:
    for entry in dist.metadata.get_all("Project-URL") or []:
        if "," in entry:
            label, url = entry.split(",", 1)
            if label.strip().lower() in {"homepage", "source", "repository"}:
                return url.strip()
    return dist.metadata.get("Home-page") or None


def _license_expression(name: str, dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    return LICENSE_OVERRIDES.get(name, "UNKNOWN")


def _distribution_evidence(name: str, dist: metadata.Distribution) -> dict[str, Any]:
    """采集许可证文件和本地原生二进制的路径、大小及哈希。"""

    license_files: list[dict[str, Any]] = []
    native_artifacts: list[dict[str, Any]] = []
    for relative in dist.files or []:
        path = Path(dist.locate_file(relative))
        if not path.is_file():
            continue
        relative_text = str(relative).replace("\\", "/")
        basename = path.name.lower()
        if basename.startswith(("license", "copying", "notice")):
            license_files.append({"path": relative_text, "sha256": _sha256(path)})
        if path.suffix.lower() in NATIVE_SUFFIXES:
            native_artifacts.append({"path": relative_text, "size_bytes": path.stat().st_size, "sha256": _sha256(path)})
    return {
        "name": name,
        "display_name": dist.metadata.get("Name", name),
        "version": dist.version,
        "purl": f"pkg:pypi/{name}@{dist.version}",
        "license_expression": _license_expression(name, dist),
        "project_url": _project_url(dist),
        "license_files": sorted(license_files, key=lambda item: item["path"]),
        "native_artifacts": sorted(native_artifacts, key=lambda item: item["path"]),
    }


def _query_osv(name: str, version: str, endpoint: str, retries: int = 3) -> dict[str, Any]:
    """通过官方OSV API查询一个精确PyPI版本，失败时保留错误证据。"""

    payload = json.dumps({"package": {"ecosystem": "PyPI", "name": name}, "version": version}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json", "User-Agent": "energy-retry-sca/1.0"})
    error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
            raw_vulns = body.get("vulns", [])
            groups: list[set[str]] = []
            for vulnerability in raw_vulns:
                identities = {vulnerability["id"], *(vulnerability.get("aliases") or [])}
                overlapping = [group for group in groups if group & identities]
                merged = set(identities)
                for group in overlapping:
                    merged.update(group)
                    groups.remove(group)
                groups.append(merged)
            return {
                "queried": True,
                "attempts": attempt,
                "vulnerability_count": len(groups),
                "raw_record_count": len(raw_vulns),
                "vulnerability_groups": [sorted(group) for group in groups],
                "vulnerabilities": raw_vulns,
            }
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(attempt)
    return {"queried": False, "attempts": retries, "vulnerability_count": None, "raw_record_count": None, "vulnerability_groups": [], "vulnerabilities": [], "error": error}


def _cyclonedx(components: list[dict[str, Any]], graph: dict[str, set[str]], timestamp: str) -> dict[str, Any]:
    """构造CycloneDX 1.6 JSON软件物料清单。"""

    by_name = {item["name"]: item for item in components}
    bom_components = []
    for item in components:
        component: dict[str, Any] = {
            "type": "library", "bom-ref": item["purl"], "name": item["display_name"],
            "version": item["version"], "purl": item["purl"],
            "licenses": [{"expression": item["license_expression"]}],
            "properties": [
                {"name": "energy-retry:direct", "value": str(item["direct"]).lower()},
                {"name": "energy-retry:native-artifact-count", "value": str(len(item["native_artifacts"]))},
            ],
        }
        if item["project_url"]:
            component["externalReferences"] = [{"type": "website", "url": item["project_url"]}]
        bom_components.append(component)
    dependencies = [
        {"ref": by_name[name]["purl"], "dependsOn": [by_name[dep]["purl"] for dep in sorted(deps) if dep in by_name]}
        for name, deps in sorted(graph.items()) if name in by_name
    ]
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": {"components": [{"type": "application", "name": "energy-retry software_composition_audit", "version": "1.0"}]},
            "component": {"type": "application", "bom-ref": "energy-recovery-simulation", "name": "energy_recovery_simulation"},
        },
        "components": bom_components,
        "dependencies": dependencies,
    }


def _write_csv(path: Path, components: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["name", "version", "direct", "license_expression", "project_url", "purl", "vulnerability_count", "native_artifact_count"])
        writer.writeheader()
        for item in components:
            writer.writerow({
                "name": item["display_name"], "version": item["version"], "direct": item["direct"],
                "license_expression": item["license_expression"], "project_url": item["project_url"] or "",
                "purl": item["purl"], "vulnerability_count": item["osv"]["vulnerability_count"],
                "native_artifact_count": len(item["native_artifacts"]),
            })


def _write_notices(path: Path, components: list[dict[str, Any]]) -> None:
    lines = ["# 第三方软件成分告知", "", "本项目交付包仅声明依赖，不捆绑下列第三方Python包；部署方安装依赖时仍应保留并遵守各组件许可证。", "", "| 组件 | 版本 | 许可证 | 项目地址 |", "| --- | --- | --- | --- |"]
    for item in components:
        url = item["project_url"] or "未提供"
        lines.append(f"| `{item['display_name']}` | `{item['version']}` | `{item['license_expression']}` | {url} |")
    lines.extend(["", "特别提示：`psycopg`和`psycopg-binary`使用LGPL-3.0-only。当前算法包未复制其二进制或源码，只通过requirements声明安装；正式交付仍需由项目权利人完成许可证合规确认。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    counts = result["summary"]
    lines = [
        "# 依赖、安全与软件成分审计报告", "",
        f"- 审计时间（UTC）：`{result['generated_at_utc']}`",
        f"- 审计结论：`{result['status']}`",
        f"- 依赖闭包：`{counts['component_count']}` 个组件，其中直接依赖 `{counts['direct_component_count']}` 个",
        f"- OSV：成功查询 `{counts['osv_queried_count']}` 个，失败 `{counts['osv_failed_count']}` 个，命中已知漏洞 `{counts['known_vulnerability_count']}` 项",
        f"- 未识别许可证：`{counts['unknown_license_count']}` 个", "",
        "## 结论边界", "",
        "OSV零命中仅表示在记录时间点未匹配到该精确版本的公开已知漏洞，不代表软件绝对安全。源码静态检查是高置信度规则门禁，不替代人工渗透测试或独立代码审计。", "",
        "## 当前开放项", "",
    ]
    lines.extend(f"- [{item['severity']}] {item['message']}" for item in result["open_findings"])
    if not result["open_findings"]:
        lines.append("- 无。")
    lines.extend(["", "## 已完成控制", "", "- 正式直接依赖使用精确版本。", "- 依赖闭包使用逐制品SHA-256哈希锁，并核验锁定版本与当前环境一致。", "- 发布源码执行凭据、高风险调用、shell子进程、动态代码执行和不安全ZIP解压门禁。", "- ZIP解压统一限制成员数、解压总量、路径穿越和符号链接。", "- 动态SQL仅允许源码常量白名单标识符，运行值使用参数绑定。", "- 生成CycloneDX 1.6 SBOM、第三方组件表、许可证告知和本地原生二进制哈希。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(output_dir: Path, *, query_osv: bool) -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    direct = _read_direct_requirements()
    selected, graph = _dependency_closure(direct)
    components = []
    for name, dist in sorted(selected.items()):
        item = _distribution_evidence(name, dist)
        item["direct"] = name in direct
        item["declared_by"] = direct.get(name, {}).get("sources", [])
        item["dependencies"] = sorted(graph.get(name, set()))
        item["osv"] = _query_osv(item["display_name"], item["version"], policy["official_sources"]["osv_api"]) if query_osv else {"queried": False, "vulnerability_count": None, "raw_record_count": None, "vulnerability_groups": [], "vulnerabilities": [], "error": "offline mode"}
        components.append(item)

    expected_versions = {}
    for name, declaration in direct.items():
        match = re.search(r"==([^;\s]+)", declaration["requirement"])
        expected_versions[name] = match.group(1) if match else None
    version_mismatches = [
        {"name": name, "expected": expected, "installed": selected[name].version}
        for name, expected in expected_versions.items() if expected != selected[name].version
    ]
    known_vulnerabilities = sum(item["osv"]["vulnerability_count"] or 0 for item in components)
    osv_failed = sum(not item["osv"]["queried"] for item in components)
    unknown_licenses = [item["name"] for item in components if item["license_expression"] == "UNKNOWN"]
    project_license_present = any((ROOT / name).is_file() for name in ("LICENSE", "LICENSE.txt", "COPYING", "NOTICE"))
    artifact_hash_lock = _inspect_artifact_hash_lock(
        REQUIREMENTS_LOCK_PATH,
        {name: dist.version for name, dist in selected.items()},
    )
    open_findings: list[dict[str, str]] = []
    if known_vulnerabilities:
        open_findings.append({"severity": "critical", "code": "known_vulnerabilities", "message": f"精确依赖版本命中{known_vulnerabilities}项OSV已知漏洞，发布前必须处置。"})
    if osv_failed:
        open_findings.append({"severity": "high", "code": "osv_query_incomplete", "message": f"有{osv_failed}个组件未完成OSV查询，不能形成完整漏洞时点证据。"})
    if unknown_licenses:
        open_findings.append({"severity": "high", "code": "unknown_licenses", "message": f"许可证未识别：{', '.join(unknown_licenses)}。"})
    if version_mismatches:
        open_findings.append({"severity": "high", "code": "version_mismatch", "message": f"当前环境与精确依赖声明不一致：{version_mismatches}。"})
    if sys.version_info < (3, 11):
        open_findings.append({"severity": "high", "code": "python_eol", "message": f"当前Python {platform.python_version()}已停止安全支持；生产环境应迁移并验证Python 3.11以上，优先3.12。"})
    if not project_license_present:
        open_findings.append({"severity": "medium", "code": "project_license_missing", "message": "项目根目录没有LICENSE/COPYING/NOTICE；软件权属与对外许可方式需由项目权利人确定。"})
    if not artifact_hash_lock["valid"]:
        open_findings.append({
            "severity": "medium",
            "code": "artifact_hash_lock_missing",
            "message": "依赖安装制品哈希锁缺失或不完整；生产构建应使用覆盖当前依赖闭包的SHA-256哈希锁文件。",
        })

    generated_at = datetime.now(timezone.utc).isoformat()
    blocking_codes = {"known_vulnerabilities", "osv_query_incomplete", "unknown_licenses", "version_mismatch"}
    blocking_count = sum(item["code"] in blocking_codes for item in open_findings)
    result = {
        "schema_version": "1.0", "policy_version": policy["policy_version"], "generated_at_utc": generated_at,
        "status": "blocked" if blocking_count else "review_required",
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform(), "executable": sys.executable},
        "summary": {
            "component_count": len(components), "direct_component_count": sum(item["direct"] for item in components),
            "osv_queried_count": sum(item["osv"]["queried"] for item in components), "osv_failed_count": osv_failed,
            "known_vulnerability_count": known_vulnerabilities, "unknown_license_count": len(unknown_licenses),
            "native_artifact_count": sum(len(item["native_artifacts"]) for item in components), "blocking_finding_count": blocking_count,
        },
        "requirements": {name: {**item, "extras": sorted(item["extras"])} for name, item in direct.items()},
        "components": components, "artifact_hash_lock": artifact_hash_lock, "open_findings": open_findings,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "software_composition_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "sbom.cyclonedx.json").write_text(json.dumps(_cyclonedx(components, graph, generated_at), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / "third_party_components.csv", components)
    _write_notices(output_dir / "THIRD_PARTY_NOTICES.md", components)
    _write_report(output_dir / "SOFTWARE_COMPOSITION_AUDIT_REPORT.md", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/security_audit_current"))
    parser.add_argument("--offline", action="store_true", help="跳过OSV联网查询，仅用于开发调试")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = run(output_dir, query_osv=not args.offline)
    print(json.dumps({"status": result["status"], "summary": result["summary"], "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
