"""核验数据库交付目录和压缩包的结构、清单与文件校验和。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from safe_zip import safe_extract_zip


REQUIRED_PATHS = {
    "CHECKSUMS.sha256",
    "requirements-database.txt",
    "database/bootstrap.sql",
    "database/security_roles.sql",
    "database/database.env.example",
    "database/delivery_package_manifest.json",
    "database/interface_contract_freeze.json",
    "database/platform_api_contract.json",
    "database/solver_budget.py",
    "database/platform_query_examples.sql",
    "database/migrations/007_joint_parameter_robustness.sql",
    "database/examples/five_run_acceptance_manifest.json",
    "tools/deploy_database.ps1",
    "tools/database_healthcheck.py",
    "tools/verify_target_database_access.py",
    "tools/run_database_worker_loop.py",
    "tools/run_database_five_run_acceptance.py",
    "tools/verify_database_five_run_e2e.py",
    "tools/platform_task_stress_fault.py",
    "tools/verify_platform_task_stress_results.py",
    "tools/verify_interface_contract_freeze.py",
    "tools/safe_zip.py",
    "docs/database_delivery_package_guide.md",
    "docs/interface_contract_freeze.md",
    "docs/solver_resource_budget_and_degradation.md",
    "docs/prototype_backend_contract.json",
    "docs/optimization_attribution_and_bottleneck_report.md",
    "docs/database_platform_integration_handoff.md",
    "docs/database_platform_integration_checklist.md",
    "docs/platform_task_stress_fault.md",
    "outputs/target_platform_predeployment/local_healthcheck.json",
    "outputs/target_platform_predeployment/local_four_account_access.json",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/DATABASE_FIVE_RUN_E2E_REPORT.md",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/database_five_run_e2e_summary.json",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/segregated_account_acceptance_summary.json",
    "outputs/platform_task_stress_fault_current/PLATFORM_TASK_STRESS_FAULT_REPORT.md",
    "outputs/platform_task_stress_fault_scale_matrix/PLATFORM_TASK_STRESS_SCALE_REPORT.md",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_directory(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise AssertionError(f"交付目录不存在：{root}")
    root = root.resolve()
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    missing = sorted(REQUIRED_PATHS - actual)
    if missing:
        raise AssertionError(f"交付包缺少必要文件：{missing}")
    forbidden = sorted(
        path for path in actual if "__pycache__" in path or path.endswith(".pyc")
    )
    if forbidden:
        raise AssertionError(f"交付包含缓存文件：{forbidden}")

    manifest = json.loads(
        (root / "database/delivery_package_manifest.json").read_text(encoding="utf-8")
    )
    if manifest["database"] != "carbon_emissions":
        raise AssertionError("交付清单数据库名不正确")
    if manifest["package_version"] != "2026.09.10.3":
        raise AssertionError("交付清单版本必须为2026.09.10.3")
    if manifest["schema"] != "energy_recovery":
        raise AssertionError("交付清单 schema 不正确")
    if len(manifest["run_types"]) != 5:
        raise AssertionError("交付清单必须包含五类任务")
    if manifest["security"]["credentials_included"] is not False:
        raise AssertionError("交付清单不得声明包含凭据")

    health = json.loads(
        (root / "outputs/target_platform_predeployment/local_healthcheck.json").read_text(
            encoding="utf-8"
        )
    )
    access = json.loads(
        (root / "outputs/target_platform_predeployment/local_four_account_access.json").read_text(
            encoding="utf-8"
        )
    )
    five_run = json.loads(
        (
            root
            / "outputs/database_postgres_segregated_e2e_acceptance_v4/database_five_run_e2e_summary.json"
        ).read_text(encoding="utf-8")
    )
    segregated = json.loads(
        (
            root
            / "outputs/database_postgres_segregated_e2e_acceptance_v4/segregated_account_acceptance_summary.json"
        ).read_text(encoding="utf-8")
    )
    if not health.get("accepted") or not access.get("accepted"):
        raise AssertionError("交付包中的本地健康或四账号权限证据未通过")
    if not five_run.get("accepted") or int(five_run.get("successful_run_count", 0)) != 5:
        raise AssertionError("交付包中的五类任务验收证据未达到5/5")
    if not segregated.get("accepted") or int(segregated.get("successful_run_count", 0)) != 5:
        raise AssertionError("交付包中的分角色验收摘要未通过")
    accounts = segregated.get("accounts", {})
    if len({accounts.get("platform"), accounts.get("worker"), accounts.get("readonly")}) != 3:
        raise AssertionError("分角色验收没有使用三个不同登录账号")
    if five_run.get("audit_account") != accounts.get("readonly"):
        raise AssertionError("五任务报告的审计账号与分角色摘要不一致")

    checksum_entries: dict[str, str] = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        expected_hash, relative_path = line.split("  ", 1)
        checksum_entries[relative_path] = expected_hash
    expected_checksum_paths = actual - {"CHECKSUMS.sha256"}
    if set(checksum_entries) != expected_checksum_paths:
        raise AssertionError("CHECKSUMS.sha256 与交付文件集合不一致")
    mismatches = [
        path
        for path, expected_hash in checksum_entries.items()
        if sha256(root / path) != expected_hash
    ]
    if mismatches:
        raise AssertionError(f"文件校验和不一致：{mismatches}")

    env_text = (root / "database/database.env.example").read_text(encoding="utf-8")
    if "REPLACE_ME" not in env_text:
        raise AssertionError("环境模板必须使用显式凭据占位符")

    # 从待验收交付目录自身启动冻结检查，避免只验证开发目录中的副本。
    with tempfile.TemporaryDirectory(prefix="interface_contract_package_check_") as output_dir:
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "tools/verify_interface_contract_freeze.py"),
                "--output-dir",
                output_dir,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    if completed.returncode != 0:
        raise AssertionError(
            "交付包内部接口冻结检查失败："
            f"stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
        )
    generated_cache = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ("__pycache__" in path.parts or path.suffix == ".pyc")
    )
    if generated_cache:
        raise AssertionError(f"包内核验过程生成了缓存文件：{generated_cache}")
    return {
        "accepted": True,
        "package_root": str(root.resolve()),
        "file_count": len(actual),
        "checksum_count": len(checksum_entries),
        "package_version": manifest["package_version"],
    }


def verify_zip(zip_path: Path) -> dict[str, object]:
    if not zip_path.is_file():
        raise AssertionError(f"交付压缩包不存在：{zip_path}")
    with tempfile.TemporaryDirectory(prefix="database_delivery_verify_") as temp_dir:
        with zipfile.ZipFile(zip_path) as archive:
            safe_extract_zip(archive, Path(temp_dir))
        roots = [path for path in Path(temp_dir).iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise AssertionError("压缩包必须只包含一个顶层交付目录")
        result = verify_directory(roots[0])
    result["zip_path"] = str(zip_path.resolve())
    result["zip_sha256"] = sha256(zip_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--zip", dest="zip_path", type=Path, required=True)
    args = parser.parse_args()
    directory_result = verify_directory(args.package_dir)
    zip_result = verify_zip(args.zip_path)
    print(json.dumps({"directory": directory_result, "zip": zip_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
