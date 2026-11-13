"""构建按主题分类、绑定当前文档状态基线的项目说明包。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "项目说明文档-9.5"
PACKAGE_FILES = (
    ("docs/project_documentation_package_9_5.md", "00_先读/00_阅读导航.md"),
    ("docs/current_documentation_baseline.md", "00_先读/01_当前状态基线.md"),
    ("docs/algorithm_scope_and_deliverables.md", "00_先读/02_算法边界与交付物.md"),
    ("docs/current_project_status_and_io.md", "01_输入输出与参数/03_输入输出说明.md"),
    ("docs/algorithm_parameters_reference.md", "01_输入输出与参数/04_参数说明.md"),
    ("docs/simulation_program_database_schema.md", "01_输入输出与参数/05_数据库表结构.md"),
    ("docs/algorithm_core_implementation.md", "02_算法实现/06_算法实现说明.md"),
    ("docs/algorithm_api_reference.md", "02_算法实现/07_API参考.md"),
    ("docs/current_algorithm_validity_boundary.md", "03_数据与结论边界/08_算法可信边界.md"),
    ("docs/current_data_gaps_and_next_actions.md", "03_数据与结论边界/09_数据缺口与后续动作.md"),
    ("docs/database_integration_guide.md", "04_数据库与运行保障/10_数据库集成指南.md"),
    ("docs/interface_contract_freeze.md", "04_数据库与运行保障/11_平台接口冻结说明.md"),
    ("docs/production_assurance_toolkit_guide.md", "04_数据库与运行保障/12_生产保障工具包说明.md"),
    ("docs/production_assurance_acceptance_checklist.md", "04_数据库与运行保障/13_生产验收清单.md"),
    ("docs/dependency_security_and_sbom.md", "04_数据库与运行保障/14_依赖安全与SBOM.md"),
    ("docs/maintenance_and_release_automation.md", "04_数据库与运行保障/15_维护与发布自动化.md"),
    ("docs/clean_environment_and_portability.md", "04_数据库与运行保障/16_干净环境与可移植性.md"),
    ("docs/code_quality_gate.md", "04_数据库与运行保障/17_代码质量专项.md"),
)


def _sha256(path: Path) -> str:
    """计算文件SHA-256。"""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_checksums(package_root: Path) -> None:
    """写入包内逐文件校验和。"""

    files = sorted(path for path in package_root.rglob("*") if path.is_file() and path.name != "CHECKSUMS.sha256")
    lines = [f"{_sha256(path)}  {path.relative_to(package_root).as_posix()}" for path in files]
    (package_root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """复制当前文档、写入来源清单并生成ZIP。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "deliverables")
    parser.add_argument("--zip-path", type=Path, default=ROOT / f"{PACKAGE_ID}.zip")
    args = parser.parse_args()
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    package_root = output_root / "project_documentation_9_5"
    zip_path = args.zip_path if args.zip_path.is_absolute() else ROOT / args.zip_path
    if package_root.exists() or zip_path.exists():
        print(f"文档包目标已存在：{package_root} 或 {zip_path}", file=sys.stderr)
        return 1

    registry = json.loads((ROOT / "docs" / "document_status_registry.json").read_text(encoding="utf-8"))
    status_by_path = {
        relative: category
        for category, paths in registry["categories"].items()
        for relative in paths
    }
    records: list[dict[str, object]] = []
    package_root.mkdir(parents=True)
    try:
        for source_relative, target_relative in PACKAGE_FILES:
            source = ROOT / source_relative
            if not source.is_file():
                raise FileNotFoundError(source)
            category = status_by_path.get(source_relative)
            if category not in {"current_authority", "current_supporting"}:
                raise ValueError(f"不允许把非当前文档放入说明包：{source_relative} ({category})")
            target = package_root / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            records.append(
                {
                    "source": source_relative,
                    "target": target_relative,
                    "status": category,
                    "sha256": _sha256(target),
                }
            )
        manifest = {
            "schema_version": "1.0",
            "package_id": PACKAGE_ID,
            "release_version": registry["release_version"],
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "authority_entry": "00_先读/01_当前状态基线.md",
            "data_status": "planning_placeholder",
            "production_accepted": False,
            "document_count": len(records),
            "documents": records,
        }
        (package_root / "DOCUMENTATION_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_checksums(package_root)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(PACKAGE_ID) / path.relative_to(package_root))
    except Exception:
        shutil.rmtree(package_root, ignore_errors=True)
        if zip_path.exists():
            zip_path.unlink()
        raise

    print(
        json.dumps(
            {
                "package_root": str(package_root),
                "zip_path": str(zip_path),
                "release_version": registry["release_version"],
                "document_count": len(records),
                "zip_sha256": _sha256(zip_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
