"""刷新软件成分证据并执行正式发布安全门禁。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from release_common import ROOT
from release_readiness import evaluate_readiness
from security_source_checks import run_checks as run_source_checks
from software_composition_audit import run as run_composition_audit


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("发布安全证据目录必须位于项目目录内。") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/release_security_gate")
    parser.add_argument("--reuse-evidence", action="store_true", help="仅供维护诊断；正式发布不得使用")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    composition_dir = output_dir / "composition"
    source_dir = output_dir / "source"
    output_dir.mkdir(parents=True, exist_ok=True)

    source = run_source_checks()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "security_source_checks.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.reuse_evidence:
        previous = ROOT / "outputs/security_audit_20260911/composition"
        composition_dir.mkdir(parents=True, exist_ok=True)
        for name in ("software_composition_audit.json", "sbom.cyclonedx.json"):
            shutil.copy2(previous / name, composition_dir / name)
    else:
        run_composition_audit(composition_dir, query_osv=True)

    pwsh = shutil.which("pwsh")
    schema_command = []
    schema_return_code = 127
    schema_stdout = ""
    schema_stderr = "未找到pwsh，无法执行官方CycloneDX schema验证。"
    if pwsh:
        schema_command = [
            pwsh, "-NoProfile", "-File", str(ROOT / "tools/validate_cyclonedx_sbom.ps1"),
            "-SbomPath", _relative(composition_dir / "sbom.cyclonedx.json"),
            "-OutputPath", _relative(composition_dir / "sbom_schema_validation.json"),
        ]
        completed = subprocess.run(schema_command, cwd=ROOT, capture_output=True, text=True, check=False)
        schema_return_code = completed.returncode
        schema_stdout = completed.stdout
        schema_stderr = completed.stderr
    (output_dir / "schema.stdout.txt").write_text(schema_stdout, encoding="utf-8", errors="replace")
    (output_dir / "schema.stderr.txt").write_text(schema_stderr, encoding="utf-8", errors="replace")

    readiness = evaluate_readiness("acceptance", output_dir, now=datetime.now(timezone.utc))
    if not source.get("accepted"):
        readiness["checks"].append({"name": "refreshed_source_security", "passed": False, "severity": "blocking", "detail": "刷新后的源码安全门禁失败"})
    if schema_return_code != 0:
        readiness["checks"].append({"name": "schema_command", "passed": False, "severity": "blocking", "detail": f"return_code={schema_return_code}"})
    if args.reuse_evidence:
        readiness["checks"].append({"name": "fresh_online_audit", "passed": False, "severity": "blocking", "detail": "使用了--reuse-evidence，只能诊断"})
    failures = [item for item in readiness["checks"] if item["severity"] == "blocking" and not item["passed"]]
    readiness["blocking_failure_count"] = len(failures)
    readiness["accepted"] = not failures
    readiness["schema_command"] = schema_command
    (output_dir / "release_security_gate.json").write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 正式发布安全门禁", "", f"- 结论：`{'PASS' if readiness['accepted'] else 'BLOCKED'}`",
        f"- 联网证据刷新：`{str(not args.reuse_evidence).lower()}`", f"- 阻断项：`{len(failures)}`", "",
        "| 检查 | 状态 | 说明 |", "| --- | --- | --- |",
    ]
    for item in readiness["checks"]:
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | {detail} |")
    (output_dir / "RELEASE_SECURITY_GATE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"accepted": readiness["accepted"], "blocking_failure_count": len(failures), "report": str(output_dir / "RELEASE_SECURITY_GATE.md")}, ensure_ascii=False))
    return 0 if readiness["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

