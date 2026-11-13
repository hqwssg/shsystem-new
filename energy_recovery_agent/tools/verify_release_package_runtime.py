"""在临时解压目录中验证完整算法交付包能够实际编译和运行。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from release_common import ROOT
from safe_zip import safe_extract_zip


REQUIREMENT_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)$")
SMOKE_CHECKS = [
    "verify_compile_project",
    "verify_database_contract",
    "verify_database_storage_device_binding",
    "verify_energy_settlement_correctness",
    "verify_exact_resource_feasibility",
    "verify_historical_disturbance_replay",
    "verify_interface_contract_freeze",
]


def _verify_dependencies(package_root: Path) -> list[str]:
    """核对当前解释器环境与包内精确依赖版本。"""

    errors: list[str] = []
    for raw in (package_root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        match = REQUIREMENT_PATTERN.fullmatch(text)
        if match is None:
            errors.append(f"无法核验非精确依赖：{text}")
            continue
        distribution, expected = match.groups()
        try:
            actual = version(distribution)
        except PackageNotFoundError:
            errors.append(f"缺少依赖：{distribution}=={expected}")
            continue
        if actual != expected:
            errors.append(f"依赖版本不一致：{distribution}，期望{expected}，实际{actual}")
    return errors


def verify_runtime(zip_path: Path, output_dir: Path) -> dict[str, Any]:
    """解压ZIP并执行一组覆盖关键运行入口的包内smoke。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="algorithm_release_runtime_") as temporary:
        temporary_root = Path(temporary)
        with zipfile.ZipFile(zip_path) as archive:
            safe_extract_zip(archive, temporary_root)
        roots = [path for path in temporary_root.iterdir() if path.is_dir()]
        if len(roots) != 1:
            return {"status": "FAIL", "errors": ["ZIP必须只有一个顶层目录"]}
        package_root = roots[0]
        errors.extend(_verify_dependencies(package_root))
        command = [sys.executable, "run_project.py", "smoke", "--only", *SMOKE_CHECKS]
        completed = subprocess.run(command, cwd=package_root, capture_output=True, text=True, check=False)
        (output_dir / "package_runtime.stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
        (output_dir / "package_runtime.stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            errors.append(f"包内代表性smoke失败，返回码{completed.returncode}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "zip_path": str(zip_path),
        "python": sys.version.split()[0],
        "smoke_checks": SMOKE_CHECKS,
        "errors": errors,
    }


def main() -> int:
    """执行包内运行检查并保存机器可读摘要。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="zip_path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "release_package_runtime")
    args = parser.parse_args()
    zip_path = args.zip_path if args.zip_path.is_absolute() else ROOT / args.zip_path
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = verify_runtime(zip_path, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "package_runtime_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
