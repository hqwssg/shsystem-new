"""冻结完整算法发布白名单中的源码、配置、模板、测试和文档。"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from datetime import date
from pathlib import Path

from release_common import ROOT, file_records, load_json, load_package_spec, payload_sha256, selected_source_files, sha256_file
from release_readiness import DEFAULT_AUDIT_ROOT, evaluate_readiness


def main() -> int:
    """生成需要显式提交的正式发布基线。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release" / "release_baseline.json")
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT_ROOT)
    args = parser.parse_args()
    audit_root = args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    readiness = evaluate_readiness("candidate", audit_root)
    if not readiness["accepted"]:
        print(json.dumps({"status": "BLOCKED", "reason": "candidate_readiness", "checks": [item for item in readiness["checks"] if not item["passed"]]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    spec = load_package_spec(ROOT)
    records = file_records(selected_source_files(ROOT, spec), ROOT)
    interface = load_json(ROOT / "database" / "interface_contract_freeze.json")
    baseline = {
        "schema_version": "1.0",
        "status": "frozen",
        "release_version": spec["release_version"],
        "effective_date": date.today().isoformat(),
        "module": spec.get("module"),
        "python_requires": spec.get("python_requires"),
        "frozen_with_python": platform.python_version(),
        "interface_freeze_version": interface.get("freeze_version"),
        "data_status": spec.get("data_status"),
        "package_spec_sha256": sha256_file(ROOT / "release" / "package_spec.json"),
        "payload_sha256": payload_sha256(records),
        "file_count": len(records),
        "files": records,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(baseline, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({key: baseline[key] for key in ("release_version", "file_count", "payload_sha256")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
