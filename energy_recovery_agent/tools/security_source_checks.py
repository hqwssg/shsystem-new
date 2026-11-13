"""执行不联网的源码安全、凭据、依赖锁定和安全解压检查。"""

from __future__ import annotations

import argparse
import ast
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from release_common import ROOT, load_package_spec, selected_source_files
from safe_zip import safe_extract_zip


TEXT_SUFFIXES = {".py", ".ps1", ".sql", ".json", ".md", ".txt", ".example", ".toml", ".ini"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "password_dsn": re.compile(r"postgres(?:ql)?://[^\s:'\"<>]+:([^@\s'\"<>]+)@", re.IGNORECASE),
}
PLACEHOLDER_MARKERS = {"REPLACE_ME", "example", "...", "<密码>", "<password>"}
REVIEWED_DYNAMIC_SQL = {
    ("database/postgres.py", "_delete_run_results"),
    ("tools/platform_task_stress_fault.py", "_result_counts"),
    ("tools/run_database_five_run_acceptance.py", "_account_identity"),
    ("tools/verify_database_five_run_e2e.py", "_count"),
}


def _function_by_line(tree: ast.AST) -> dict[int, str]:
    """建立源码行到最内层函数名的映射。"""

    result: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                result[line] = node.name
    return result


def _call_name(node: ast.Call) -> str:
    """返回调用表达式的点分名称。"""

    parts: list[str] = []
    current: ast.AST = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _scan_python(path: Path, relative: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """扫描高风险调用和需人工确认的受控动态SQL。"""

    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
    function_lines = _function_by_line(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in {"eval", "exec", "os.system", "pickle.load", "pickle.loads", "tempfile.mktemp"}:
            findings.append({"severity": "high", "rule": "dangerous_call", "path": relative, "line": node.lineno, "call": name})
        if name.startswith("subprocess."):
            shell_keyword = next((item for item in node.keywords if item.arg == "shell"), None)
            if shell_keyword and isinstance(shell_keyword.value, ast.Constant) and shell_keyword.value.value is True:
                findings.append({"severity": "high", "rule": "subprocess_shell_true", "path": relative, "line": node.lineno})
        if name.endswith(".extractall"):
            findings.append({"severity": "high", "rule": "unsafe_zip_extractall", "path": relative, "line": node.lineno})
        if name.endswith(".execute") and node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
            function = function_lines.get(node.lineno, "")
            item = {"severity": "medium", "rule": "dynamic_sql", "path": relative, "line": node.lineno, "function": function}
            if (relative, function) in REVIEWED_DYNAMIC_SQL:
                item["disposition"] = "constant_allowlist_identifier_only"
                reviewed.append(item)
            else:
                findings.append(item)
    return findings, reviewed


def _scan_secrets(path: Path, relative: str) -> list[dict[str, Any]]:
    """扫描高置信度密钥和带密码连接串，允许明确模板。"""

    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[dict[str, Any]] = []
    for rule, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(0)
            if rule == "password_dsn" and any(marker.lower() in value.lower() for marker in PLACEHOLDER_MARKERS):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append({"severity": "critical", "rule": rule, "path": relative, "line": line})
    return findings


def _safe_zip_self_test() -> dict[str, bool]:
    """用正常、越界、符号链接和资源超限包验证安全解压。"""

    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="safe_zip_self_test_") as temp_name:
        root = Path(temp_name)
        valid = root / "valid.zip"
        with zipfile.ZipFile(valid, "w") as archive:
            archive.writestr("root/file.txt", "ok")
        with zipfile.ZipFile(valid) as archive:
            safe_extract_zip(archive, root / "valid_out")
        results["valid_archive"] = (root / "valid_out/root/file.txt").read_text() == "ok"

        traversal = root / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr("../outside.txt", "blocked")
        try:
            with zipfile.ZipFile(traversal) as archive:
                safe_extract_zip(archive, root / "traversal_out")
        except ValueError:
            results["path_traversal_rejected"] = not (root / "outside.txt").exists()
        else:
            results["path_traversal_rejected"] = False

        symlink_zip = root / "symlink.zip"
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(symlink_zip, "w") as archive:
            archive.writestr(info, "target")
        try:
            with zipfile.ZipFile(symlink_zip) as archive:
                safe_extract_zip(archive, root / "symlink_out")
        except ValueError:
            results["symlink_rejected"] = True
        else:
            results["symlink_rejected"] = False

        try:
            with zipfile.ZipFile(valid) as archive:
                safe_extract_zip(archive, root / "member_out", max_members=0)
        except ValueError:
            results["invalid_limit_rejected"] = True
        else:
            results["invalid_limit_rejected"] = False
        try:
            with zipfile.ZipFile(valid) as archive:
                safe_extract_zip(archive, root / "size_out", max_uncompressed_bytes=1)
        except ValueError:
            results["size_limit_rejected"] = True
        else:
            results["size_limit_rejected"] = False
    return results


def _requirements_checks() -> list[dict[str, Any]]:
    """确认两个正式依赖入口均使用精确版本。"""

    checks: list[dict[str, Any]] = []
    pattern = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^;\s]+$")
    for relative in ("requirements.txt", "requirements-database.txt"):
        lines = [line.strip() for line in (ROOT / relative).read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        checks.append({"path": relative, "requirement_count": len(lines), "all_exact": all(pattern.fullmatch(line) for line in lines)})
    return checks


def run_checks() -> dict[str, Any]:
    """执行全部本地安全检查并返回结构化结果。"""

    spec = load_package_spec(ROOT)
    files = selected_source_files(ROOT, spec)
    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    scanned_text_files = 0
    scanned_python_files = 0
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        scanned_text_files += 1
        findings.extend(_scan_secrets(path, relative))
        if path.suffix.lower() == ".py":
            scanned_python_files += 1
            python_findings, python_reviewed = _scan_python(path, relative)
            findings.extend(python_findings)
            reviewed.extend(python_reviewed)
    requirement_checks = _requirements_checks()
    zip_self_test = _safe_zip_self_test()
    if not all(item["all_exact"] for item in requirement_checks):
        findings.append({"severity": "high", "rule": "unlocked_direct_requirement", "path": "requirements*.txt"})
    if not all(zip_self_test.values()):
        findings.append({"severity": "high", "rule": "safe_zip_self_test_failed", "details": zip_self_test})
    return {
        "schema_version": "1.0",
        "policy_version": "2026.09.11.1",
        "scanned_text_files": scanned_text_files,
        "scanned_python_files": scanned_python_files,
        "requirements": requirement_checks,
        "safe_zip_self_test": zip_self_test,
        "reviewed_findings": reviewed,
        "blocking_finding_count": len(findings),
        "findings": findings,
        "accepted": not findings,
    }


def main() -> int:
    """运行检查并可选写入JSON和Markdown报告。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_checks()
    if args.output_dir:
        output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "security_source_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            "# 源码安全检查", "",
            f"- 结论：{'通过' if result['accepted'] else '未通过'}",
            f"- 文本文件：{result['scanned_text_files']}",
            f"- Python文件：{result['scanned_python_files']}",
            f"- 阻断发现：{result['blocking_finding_count']}", "",
            "## 安全ZIP自测", "",
        ]
        lines.extend(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in result["safe_zip_self_test"].items())
        lines.extend(["", "## 已复核动态SQL", ""])
        if result["reviewed_findings"]:
            lines.extend(f"- `{item['path']}:{item['line']}`：标识符来自函数内常量白名单。" for item in result["reviewed_findings"])
        else:
            lines.append("- 无。")
        (output_dir / "SECURITY_SOURCE_CHECKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
