"""编排候选预检、基线冻结、原子构建、包核验和完整发布验收。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from process_lock import ProcessLock
from release_common import ROOT, load_json, load_package_spec, sha256_file
from release_readiness import evaluate_readiness


def _run(name: str, command: list[str], output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    (output_dir / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
    (output_dir / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")
    return {"name": name, "command": command, "return_code": completed.returncode, "passed": completed.returncode == 0, "elapsed_s": round(time.perf_counter() - started, 3)}


def _write_summary(output_dir: Path, mode: str, results: list[dict[str, Any]], accepted: bool) -> None:
    payload = {"schema_version": "1.0", "mode": mode, "completed_at_utc": datetime.now(timezone.utc).isoformat(), "accepted": accepted, "steps": results}
    (output_dir / "release_automation_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 发布自动化总览", "", f"- 模式：`{mode}`", f"- 结论：`{'PASS' if accepted else 'BLOCKED/FAIL'}`", "", "| 步骤 | 状态 | 返回码 | 耗时（秒） |", "| --- | --- | ---: | ---: |"]
    lines.extend(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | {item['return_code']} | {item['elapsed_s']} |" for item in results)
    (output_dir / "RELEASE_AUTOMATION_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_accepted_release_pointer(summary_path: Path, zip_path: Path, spec: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """由完整验收摘要和算法包构造带哈希的正式版本指针。"""

    summary = load_json(summary_path)
    if summary.get("accepted") is not True or summary.get("complete_scope") is not True:
        raise RuntimeError("验收摘要未证明完整发布通过，拒绝推进正式版本指针。")
    if summary.get("release_version") != spec.get("release_version"):
        raise RuntimeError("验收摘要版本与候选发布规格不一致。")
    package_id = str(spec["package_id"])
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    return {
        "schema_version": "1.0",
        "status": "accepted",
        "release_version": spec["release_version"],
        "package_id": package_id,
        "package_directory": f"deliverables/{package_id}",
        "package_zip": f"deliverables/{package_id}.zip",
        "package_zip_sha256": sha256_file(zip_path),
        "acceptance_summary": summary_path.relative_to(root).as_posix(),
        "acceptance_summary_sha256": sha256_file(summary_path),
    }


def _promote_accepted_release(output_dir: Path, spec: dict[str, Any]) -> None:
    """仅在完整验收成功后原子推进正式版本指针。"""

    summary_path = output_dir / "acceptance/release_acceptance_summary.json"
    package_id = str(spec["package_id"])
    zip_path = ROOT / "deliverables" / f"{package_id}.zip"
    pointer = build_accepted_release_pointer(summary_path, zip_path, spec)
    target = ROOT / "release/accepted_release.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".accepted_release.", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(pointer, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "freeze-build", "accept", "all"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/release_automation")
    parser.add_argument(
        "--audit-root",
        type=Path,
        default=ROOT / "outputs/security_audit_20260911",
        help="候选冻结前使用的软件成分与SBOM证据目录",
    )
    parser.add_argument("--built-at-utc", help="传给可复现构建器的固定ISO-8601时间")
    parser.add_argument("--skip-long", action="store_true", help="仅用于诊断，不能形成正式发布结论")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    audit_root = args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    lock_path = ROOT / "outputs/.release_pipeline.lock"

    with ProcessLock(lock_path, "release_pipeline"):
        if args.mode in {"check", "freeze-build", "all"}:
            readiness = evaluate_readiness("candidate", audit_root)
            readiness_dir = output_dir / "candidate_readiness"
            readiness_dir.mkdir(parents=True, exist_ok=True)
            (readiness_dir / "release_readiness.json").write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"name": "candidate_readiness", "command": [], "return_code": 0 if readiness["accepted"] else 1, "passed": readiness["accepted"], "elapsed_s": 0.0})
            if not readiness["accepted"] or args.mode == "check":
                _write_summary(output_dir, args.mode, results, bool(readiness["accepted"]))
                print(json.dumps({"accepted": readiness["accepted"], "report": str(output_dir / "RELEASE_AUTOMATION_SUMMARY.md")}, ensure_ascii=False))
                return 0 if readiness["accepted"] else 1

        spec = load_package_spec(ROOT)
        package_dir = ROOT / "deliverables" / str(spec["package_id"])
        zip_path = ROOT / "deliverables" / f"{spec['package_id']}.zip"
        if args.mode in {"freeze-build", "all"}:
            baseline_path = ROOT / "release/release_baseline.json"
            previous_baseline = baseline_path.read_bytes() if baseline_path.is_file() else None
            created_targets: list[Path] = []
            try:
                freeze = _run(
                    "freeze_baseline",
                    [sys.executable, "tools/freeze_release_baseline.py", "--audit-root", str(audit_root)],
                    output_dir,
                )
                results.append(freeze)
                if not freeze["passed"]:
                    raise RuntimeError("冻结基线失败")
                command = [sys.executable, "tools/build_algorithm_delivery_package.py"]
                if args.built_at_utc:
                    command.extend(["--built-at-utc", args.built_at_utc])
                build = _run("build_package", command, output_dir)
                results.append(build)
                if not build["passed"]:
                    raise RuntimeError("构建交付包失败")
                created_targets.extend([package_dir, zip_path])
                verify = _run("verify_package", [sys.executable, "tools/verify_algorithm_delivery_package.py", "--source", "--package-dir", str(package_dir), "--zip", str(zip_path)], output_dir)
                results.append(verify)
                if not verify["passed"]:
                    raise RuntimeError("交付包核验失败")
            except Exception as exc:
                for target in created_targets:
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    elif target.is_file():
                        target.unlink()
                if previous_baseline is None:
                    if baseline_path.exists():
                        baseline_path.unlink()
                else:
                    baseline_path.write_bytes(previous_baseline)
                results.append({"name": "transaction_rollback", "command": [], "return_code": 1, "passed": False, "elapsed_s": 0.0, "detail": str(exc)})
                _write_summary(output_dir, args.mode, results, False)
                print(json.dumps({"accepted": False, "error": str(exc), "report": str(output_dir / "RELEASE_AUTOMATION_SUMMARY.md")}, ensure_ascii=False))
                return 1
            if args.mode == "freeze-build":
                _write_summary(output_dir, args.mode, results, True)
                print(json.dumps({"accepted": True, "report": str(output_dir / "RELEASE_AUTOMATION_SUMMARY.md")}, ensure_ascii=False))
                return 0

        if args.mode in {"accept", "all"}:
            readiness = evaluate_readiness("acceptance", audit_root)
            results.append({"name": "acceptance_readiness", "command": [], "return_code": 0 if readiness["accepted"] else 1, "passed": readiness["accepted"], "elapsed_s": 0.0})
            if readiness["accepted"]:
                command = [sys.executable, "tools/run_release_acceptance.py", "--output-dir", str(output_dir / "acceptance")]
                if args.skip_long:
                    command.append("--skip-long")
                results.append(_run("release_acceptance", command, output_dir))

    accepted = bool(results) and all(item["passed"] for item in results) and not args.skip_long
    if accepted and args.mode in {"accept", "all"}:
        try:
            _promote_accepted_release(output_dir, spec)
            results.append({"name": "promote_accepted_release", "command": [], "return_code": 0, "passed": True, "elapsed_s": 0.0})
        except Exception as exc:
            accepted = False
            results.append({"name": "promote_accepted_release", "command": [], "return_code": 1, "passed": False, "elapsed_s": 0.0, "detail": str(exc)})
    _write_summary(output_dir, args.mode, results, accepted)
    print(json.dumps({"accepted": accepted, "report": str(output_dir / "RELEASE_AUTOMATION_SUMMARY.md")}, ensure_ascii=False))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
