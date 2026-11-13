"""验证平台数据库接口冻结清单、实现白名单、DDL枚举和示例请求的一致性。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.parameters import BOOLEAN_FLAGS, PARAMETER_FLAGS, validate_run_parameters


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"JSON根节点必须是对象：{path}")
    return payload


def _record(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _expected_parameter_names(run_type: str) -> set[str]:
    names = set(PARAMETER_FLAGS[run_type]) | set(BOOLEAN_FLAGS[run_type])
    if run_type in {"timetable_audit", "timetable_optimization"}:
        names.add("timetable_relative_path")
    if run_type == "rolling_rescheduling":
        names.update({"storage_devices", "disturbance_history_relative_path"})
    if run_type == "joint_parameter_robustness":
        names.add("parameter_ranges_relative_path")
    if run_type == "storage_planning":
        names.update({"planning_policy_code", "scenario_set_code"})
    return names


def verify_contract(root: Path = ROOT) -> dict[str, Any]:
    """返回冻结合同的逐项核验结果；失败项不会被其他通过项掩盖。"""

    freeze = _load_json(root / "database/interface_contract_freeze.json")
    checks: list[dict[str, Any]] = []
    _record(checks, "freeze_status", freeze.get("status") == "frozen", str(freeze.get("status")))
    _record(checks, "freeze_version", bool(re.fullmatch(r"\d+\.\d+\.\d+", str(freeze.get("freeze_version", "")))), str(freeze.get("freeze_version")))

    for item in freeze["versioned_components"]:
        path = root / item["path"]
        exists = path.is_file()
        _record(checks, f"exists:{item['path']}", exists, "存在" if exists else "缺失")
        if not exists:
            continue
        actual_hash = _sha256(path)
        _record(checks, f"sha256:{item['path']}", actual_hash == item["sha256"], actual_hash)
        payload = _load_json(path)
        actual_version = str(payload.get(item["version_field"], ""))
        _record(checks, f"version:{item['path']}", actual_version == item["version"], actual_version)

    for item in freeze["immutable_files"]:
        path = root / item["path"]
        exists = path.is_file()
        _record(checks, f"exists:{item['path']}", exists, "存在" if exists else "缺失")
        if exists:
            actual_hash = _sha256(path)
            _record(checks, f"sha256:{item['path']}", actual_hash == item["sha256"], actual_hash)

    database_contract = _load_json(root / "database/database_contract.json")
    platform_contract = _load_json(root / "database/platform_api_contract.json")
    mapping = _load_json(root / "database/io_mapping.json")
    delivery = _load_json(root / "database/delivery_package_manifest.json")
    authority = freeze["authority"]
    for field in ("database", "schema", "table_prefix"):
        values = {
            "freeze": authority[field],
            "mapping": mapping[field],
            "delivery": delivery[field],
        }
        if field in platform_contract:
            values["platform"] = platform_contract[field]
        if field == "database":
            values["database_contract"] = database_contract["database"]["name"]
        elif field == "schema":
            values["database_contract"] = database_contract["database"]["schema"]
        else:
            values["database_contract"] = database_contract["database"]["table_prefix"]
        _record(checks, f"authority:{field}", len(set(values.values())) == 1, json.dumps(values, ensure_ascii=False, sort_keys=True))

    frozen_run_types = set(freeze["public_surface"]["run_types"])
    sources = {
        "implementation": set(PARAMETER_FLAGS),
        "mapping": {
            name for name, value in mapping["run_parameters"].items()
            if isinstance(value, dict)
        },
        "delivery": set(delivery["run_types"]),
    }
    for source, values in sources.items():
        _record(checks, f"run_types:{source}", values == frozen_run_types, ",".join(sorted(values)))

    for run_type in sorted(frozen_run_types):
        mapped = mapping["run_parameters"][run_type]
        contract_names = set(mapped["required"]) | set(mapped["optional"])
        implementation_names = _expected_parameter_names(run_type)
        _record(
            checks,
            f"parameters:{run_type}",
            contract_names == implementation_names,
            f"contract={sorted(contract_names)}; implementation={sorted(implementation_names)}",
        )

    operation_names = set(platform_contract["operations"])
    frozen_operations = set(freeze["public_surface"]["operations"])
    _record(checks, "platform_operations", operation_names == frozen_operations, ",".join(sorted(operation_names)))
    _record(
        checks,
        "run_states",
        set(database_contract["run_status_values"]) == set(freeze["public_surface"]["run_states"])
        and set(platform_contract["run_states"]["terminal"]) == set(freeze["public_surface"]["terminal_states"]),
        json.dumps(platform_contract["run_states"], ensure_ascii=False, sort_keys=True),
    )

    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "database/migrations").glob("[0-9][0-9][0-9]_*.sql"))
    )
    for value in freeze["public_surface"]["run_types"] + freeze["public_surface"]["run_states"] + freeze["public_surface"]["decision_actions"] + freeze["public_surface"]["rolling_commit_statuses"]:
        _record(checks, f"ddl_enum:{value}", f"'{value}'" in sql, value)

    created_tables = set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? energy_recovery\.(simulation_[a-z0-9_]+)", sql))
    mapped_targets: set[str] = set()
    for item in mapping["input_files"]:
        target = item.get("target")
        if isinstance(target, str):
            mapped_targets.add(target)
    for item in mapping["output_files"]:
        mapped_targets.update(item.get("targets", []))
    missing_targets = sorted(mapped_targets - created_tables - {"simulation_project_version"})
    _record(checks, "mapping_targets_exist", not missing_targets, json.dumps(missing_targets, ensure_ascii=False))

    acceptance = _load_json(root / "database/examples/five_run_acceptance_manifest.json")
    example_errors: list[str] = []
    seen_example_types: set[str] = set()
    for entry in acceptance["runs"]:
        run_type = entry["run_type"]
        seen_example_types.add(run_type)
        relative_path = Path(entry["parameters_file"])
        parameters_path = root / relative_path if len(relative_path.parts) > 1 else root / "database/examples" / relative_path
        parameters = _load_json(parameters_path)
        try:
            validate_run_parameters(run_type, parameters)
        except ValueError as exc:
            example_errors.append(f"{run_type}: {exc}")
    _record(checks, "five_run_examples", not example_errors and seen_example_types == frozen_run_types, json.dumps(example_errors, ensure_ascii=False))

    output_paths = [item["path"] for item in mapping["output_files"]]
    _record(checks, "output_mapping_unique", len(output_paths) == len(set(output_paths)), f"count={len(output_paths)}")
    failed = [item for item in checks if not item["passed"]]
    return {
        "schema_version": "1.0",
        "freeze_version": freeze["freeze_version"],
        "status": "PASS" if not failed else "FAIL",
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "checks": checks,
    }


def _write_report(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "interface_contract_freeze_check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 接口契约冻结核验报告",
        "",
        f"- 冻结版本：`{result['freeze_version']}`",
        f"- 状态：`{result['status']}`",
        f"- 检查项：{result['check_count']}",
        f"- 通过：{result['passed_count']}",
        f"- 失败：{result['failed_count']}",
        "",
        "| 检查 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for item in result["checks"]:
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} | {detail} |")
    (output_dir / "INTERFACE_CONTRACT_FREEZE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/interface_contract_freeze")
    args = parser.parse_args()
    result = verify_contract(ROOT)
    _write_report(args.output_dir, result)
    print(json.dumps({key: result[key] for key in ("freeze_version", "status", "check_count", "failed_count")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
