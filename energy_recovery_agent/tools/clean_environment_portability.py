"""在全新隔离环境中验证正式发布包和当前候选代码的可移植性。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release_common import ROOT, load_json, load_package_spec, selected_source_files
from safe_zip import safe_extract_zip


DEFAULT_PYTHONS = ("3.11.15", "3.12.13")
REPRESENTATIVE_SMOKES = (
    "verify_compile_project",
    "verify_database_contract",
    "verify_database_storage_device_binding",
    "verify_energy_settlement_correctness",
    "verify_exact_resource_feasibility",
    "verify_historical_disturbance_replay",
    "verify_interface_contract_freeze",
)
IGNORED_MUTATION_PARTS = {"__pycache__", "outputs", ".pytest_cache"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    """记录载荷文件哈希，忽略运行时输出和字节码缓存。"""

    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not any(part in IGNORED_MUTATION_PARTS for part in path.relative_to(root).parts)
    }


def _tree_digest(hashes: dict[str, str]) -> str:
    """把逻辑路径和文件哈希绑定为一个稳定的载荷指纹。"""

    digest = hashlib.sha256()
    for relative, file_hash in sorted(hashes.items()):
        digest.update(f"{file_hash}  {relative}\n".encode("utf-8"))
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_dir: Path,
    name: str,
    timeout_s: int,
) -> dict[str, Any]:
    """运行一条命令并把完整标准输出、错误和耗时写入独立日志。"""

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        error = None
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        error = f"超过{timeout_s}秒超时上限"
    elapsed = round(time.perf_counter() - started, 3)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{name}.stdout.txt").write_text(stdout, encoding="utf-8", errors="replace")
    (log_dir / f"{name}.stderr.txt").write_text(stderr, encoding="utf-8", errors="replace")
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "return_code": return_code,
        "passed": return_code == 0,
        "elapsed_s": elapsed,
        "error": error,
    }


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _copy_current_candidate(destination: Path) -> None:
    spec = load_package_spec(ROOT)
    for source in selected_source_files(ROOT, spec):
        relative = source.resolve().relative_to(ROOT.resolve())
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _extract_single_root(zip_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        safe_extract_zip(archive, destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise ValueError("算法ZIP必须且只能包含一个顶层目录")
    return roots[0]


def _environment_probe(python: Path) -> list[str]:
    code = (
        "import json,site,sys;"
        "from importlib.metadata import version;"
        "names=['matplotlib','numpy','openpyxl','psutil','psycopg','scipy'];"
        "assert sys.prefix!=sys.base_prefix and not site.ENABLE_USER_SITE;"
        "print(json.dumps({'version':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'isolated_venv':sys.prefix!=sys.base_prefix,'user_site_enabled':site.ENABLE_USER_SITE,"
        "'packages':{name:version(name) for name in names}},ensure_ascii=False))"
    )
    return [str(python), "-c", code]


def _test_payload(
    payload_name: str,
    payload_root: Path,
    python: Path,
    python_label: str,
    neutral_cwd: Path,
    output_root: Path,
    base_env: dict[str, str],
    *,
    full_smoke: bool,
) -> dict[str, Any]:
    log_dir = output_root / "logs" / python_label / payload_name
    external_dispatch = output_root / "runtime_outputs" / python_label / payload_name / "调度 输出"
    before = _tree_hashes(payload_root)
    commands = [
        _run(
            [str(python), str(payload_root / "tools/compile_project.py")],
            cwd=neutral_cwd,
            env=base_env,
            log_dir=log_dir,
            name="compile",
            timeout_s=300,
        ),
        _run(
            [
                str(python),
                "run_project.py",
                "smoke",
                "--only",
                *REPRESENTATIVE_SMOKES,
            ],
            cwd=payload_root,
            env=base_env,
            log_dir=log_dir,
            name="representative_smoke",
            timeout_s=1800,
        ),
        _run(
            [
                str(python),
                str(payload_root / "run_project.py"),
                "dispatch-case",
                "--data-dir",
                str(payload_root / "data/real_shuohuang"),
                "--output-dir",
                str(external_dispatch),
                "--population-size",
                "2",
                "--generations",
                "1",
                "--heavy-count",
                "1",
                "--empty-count",
                "1",
                "--seed",
                "42",
            ],
            cwd=neutral_cwd,
            env=base_env,
            log_dir=log_dir,
            name="neutral_cwd_dispatch",
            timeout_s=900,
        ),
    ]
    if full_smoke:
        commands.append(
            _run(
                [str(python), "run_project.py", "smoke"],
                cwd=payload_root,
                env=base_env,
                log_dir=log_dir,
                name="full_short_smoke",
                timeout_s=7200,
            )
        )
    after = _tree_hashes(payload_root)
    changed = sorted(path for path in set(before) & set(after) if before[path] != after[path])
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    summary_path = external_dispatch / "summary.json"
    errors: list[str] = []
    if not summary_path.is_file():
        errors.append("从中立工作目录执行后未生成调度summary.json")
    if changed or removed or added:
        errors.append("运行过程改变了发布载荷文件")
    if any(not command["passed"] for command in commands):
        errors.append("至少一条运行验证命令失败")
    return {
        "payload": payload_name,
        "payload_root": str(payload_root),
        "python": python_label,
        "commands": commands,
        "dispatch_summary": str(summary_path),
        "source_mutation": {"changed": changed, "removed": removed, "added": added},
        "payload_sha256_before": _tree_digest(before),
        "payload_sha256_after": _tree_digest(after),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 干净环境与可移植性验证报告",
        "",
        f"- 总体状态：**{report['status']}**",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 正式发布包：`{report['accepted_package']['path']}`",
        f"- 正式发布包哈希校验：`{report['accepted_package']['hash_verified']}`",
        "- 平台范围：Windows x64；Linux/macOS 本轮未执行运行验证。",
        "- 数据范围：项目内规划/合成数据；正式甲方数据及真实 PostgreSQL 网络环境不在本轮范围内。",
        "",
        "## 验证矩阵",
        "",
        "| Python | 载荷 | 编译 | 关键测试 | 中立目录调度 | 完整短测试 | 源文件不变 | 结论 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["payload_results"]:
        by_name = {item["name"]: item for item in row["commands"]}
        state = lambda name: "PASS" if by_name.get(name, {}).get("passed") else ("未执行" if name not in by_name else "FAIL")
        unchanged = not any(row["source_mutation"].values())
        lines.append(
            f"| `{row['python']}` | `{row['payload']}` | {state('compile')} | {state('representative_smoke')} | "
            f"{state('neutral_cwd_dispatch')} | {state('full_short_smoke')} | {'PASS' if unchanged else 'FAIL'} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "## 依赖与边界结论",
            "",
            "指定发布包优先使用 `requirements-lock.txt` 和 `--require-hashes` 安装；仅当旧包不含锁文件时退回精确直接依赖安装，并在机器报告中明确标记。",
            "指定发布包与当前候选代码均从含中文和空格的目录执行；最小调度还从项目外中立目录启动，用于发现当前目录假设和绝对路径依赖。",
            "本报告证明的是可安装性、基础运行性和载荷只读性，不替代正式数据验收、真实数据库联调、Linux部署验证或业务性能验收。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-zip", type=Path)
    parser.add_argument("--python", action="append", dest="pythons")
    parser.add_argument("--uv", default="uv")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "clean_environment_portability_20260911",
    )
    parser.add_argument("--skip-full-smoke", action="store_true")
    parser.add_argument(
        "--allow-download-cache",
        action="store_true",
        help="允许uv复用下载缓存；虚拟环境仍为全新隔离环境。",
    )
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()

    output_root = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    pointer = load_json(ROOT / "release/accepted_release.json")
    package_zip = args.package_zip or ROOT / str(pointer["package_zip"])
    package_zip = package_zip if package_zip.is_absolute() else ROOT / package_zip
    actual_hash = _sha256(package_zip)
    expected_hash = str(pointer.get("package_zip_sha256", "")) if args.package_zip is None else actual_hash

    temporary_context = None
    if args.keep_workdir:
        work_root = output_root / "retained_clean_workdir"
        if work_root.exists():
            raise FileExistsError(f"保留目录已存在，拒绝覆盖：{work_root}")
        work_root.mkdir(parents=True)
    else:
        temporary_context = tempfile.TemporaryDirectory(prefix="energy_retry_clean_portability_")
        work_root = Path(temporary_context.name)

    try:
        package_root = _extract_single_root(package_zip, work_root / "候选 发布包")
        candidate_root = work_root / "当前 候选代码"
        candidate_root.mkdir(parents=True)
        _copy_current_candidate(candidate_root)
        neutral_cwd = work_root / "中立 工作目录"
        neutral_cwd.mkdir()
        base_env = os.environ.copy()
        base_env.update(
            {
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": str(work_root / "matplotlib 配置"),
            }
        )

        environment_results: list[dict[str, Any]] = []
        payload_results: list[dict[str, Any]] = []
        python_versions = args.pythons or list(DEFAULT_PYTHONS)
        for python_version in python_versions:
            python_slug = python_version.replace(".", "_")
            venv = work_root / f"venv_py{python_slug}"
            env_log_dir = output_root / "logs" / python_version / "environment"
            create = _run(
                [args.uv, "venv", str(venv), "--python", python_version, "--managed-python", "--no-project"],
                cwd=neutral_cwd,
                env=base_env,
                log_dir=env_log_dir,
                name="create_venv",
                timeout_s=600,
            )
            python = _venv_python(venv)
            requirement_file = package_root / "requirements-lock.txt"
            if not requirement_file.is_file():
                requirement_file = package_root / "requirements.txt"
            install_command = [args.uv, "pip", "install", "--python", str(python)]
            if not args.allow_download_cache:
                install_command.append("--no-cache")
            if requirement_file.name == "requirements-lock.txt":
                install_command.append("--require-hashes")
            install_command.extend(["-r", str(requirement_file)])
            install = _run(
                install_command,
                cwd=neutral_cwd,
                env=base_env,
                log_dir=env_log_dir,
                name="install_dependencies",
                timeout_s=1800,
            )
            probe = _run(
                _environment_probe(python),
                cwd=neutral_cwd,
                env=base_env,
                log_dir=env_log_dir,
                name="environment_probe",
                timeout_s=120,
            )
            freeze = _run(
                [args.uv, "pip", "freeze", "--python", str(python)],
                cwd=neutral_cwd,
                env=base_env,
                log_dir=env_log_dir,
                name="installed_packages",
                timeout_s=120,
            )
            environment_results.append(
                {
                    "python": python_version,
                    "requirement_source": str(requirement_file),
                    "hash_locked_install": requirement_file.name == "requirements-lock.txt",
                    "commands": [create, install, probe, freeze],
                    "status": "PASS" if all(item["passed"] for item in (create, install, probe, freeze)) else "FAIL",
                }
            )
            if not all(item["passed"] for item in (create, install, probe)):
                continue
            for payload_name, payload_root in (("package_zip", package_root), ("current_candidate", candidate_root)):
                payload_results.append(
                    _test_payload(
                        payload_name,
                        payload_root,
                        python,
                        python_version,
                        neutral_cwd,
                        output_root,
                        base_env,
                        full_smoke=(
                            not args.skip_full_smoke
                            and payload_name == "package_zip"
                        ),
                    )
                )

        errors = []
        if actual_hash.lower() != expected_hash.lower():
            errors.append("正式发布包哈希与已验收指针不一致")
        if any(row["status"] != "PASS" for row in environment_results):
            errors.append("至少一个干净Python环境创建或依赖安装失败")
        expected_payload_runs = len(python_versions) * 2
        if len(payload_results) != expected_payload_runs or any(row["status"] != "PASS" for row in payload_results):
            errors.append("可移植性验证矩阵未全部通过")
        report = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if not errors else "FAIL",
            "platform": {"os": os.name, "sys_platform": sys.platform},
            "accepted_package": {
                "path": str(package_zip),
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "hash_verified": actual_hash.lower() == expected_hash.lower(),
            },
            "environment_results": environment_results,
            "payload_results": payload_results,
            "download_cache_allowed": args.allow_download_cache,
            "limitations": [
                "未使用正式甲方数据",
                "未连接真实PostgreSQL服务器",
                "未在Linux或macOS执行",
                "若指定包不含requirements-lock.txt则只能退回精确直接依赖安装，并在报告中标记未使用哈希锁",
            ],
            "errors": errors,
        }
        (output_root / "clean_environment_portability.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_root / "CLEAN_ENVIRONMENT_PORTABILITY_REPORT.md").write_text(
            _markdown(report), encoding="utf-8"
        )
        print(json.dumps({"status": report["status"], "report": str(output_root), "errors": errors}, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 1
    finally:
        if temporary_context is not None:
            temporary_context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
