"""验证储能选址定容阶段A文件合同、跨表约束和稳定指纹。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage_planning_contract import (
    CONTRACT_FILE_NAMES,
    DATA_STATUSES,
    DIRECTIONS,
    OBJECTIVE_MODES,
    OPTION_COLUMNS,
    PARAMETER_OVERRIDE_FIELDS,
    POLICY_OPTIONAL,
    POLICY_REQUIRED,
    RISK_MEASURES,
    SCENARIO_ITEM_OPTIONAL,
    SCENARIO_ITEM_REQUIRED,
    SCENARIO_ROOT_REQUIRED,
    SCHEDULE_TEMPLATE_FIELDS,
    SITE_COLUMNS,
    SOLVER_PROFILES,
    StoragePlanningContractError,
    TARGET_FINAL_SOC_RULES,
    TECHNOLOGY_COLUMNS,
    load_storage_planning_bundle,
    storage_planning_input_status_codes,
    validate_storage_planning_inputs,
    validate_storage_planning_power_arm_references,
    write_storage_planning_validation_report,
)


SOURCE = ROOT / "data_templates" / "storage_planning_synthetic"
FILLABLE_TEMPLATE = ROOT / "data_templates" / "storage_planning_template"
FROZEN_POWER_ARMS = ROOT / "data" / "real_shuohuang" / "power_arm_intervals.csv"


def _copy_bundle(target: Path) -> None:
    """复制最小合同文件集，避免测试修改权威模板。"""
    target.mkdir(parents=True, exist_ok=True)
    for name in CONTRACT_FILE_NAMES:
        shutil.copy2(SOURCE / name, target / name)


def _expect_error(target: Path, code: str) -> None:
    """断言输入被指定合同错误拒绝。"""
    try:
        load_storage_planning_bundle(target)
    except StoragePlanningContractError as exc:
        assert exc.code == code, (exc.code, code, str(exc))
    else:
        raise AssertionError(f"非法规划输入未被拒绝：expected={code}")


def _rewrite_json(path: Path, mutate) -> None:
    """修改临时 JSON 后按 UTF-8 重写。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_csv(path: Path, mutate) -> None:
    """修改临时 CSV 行并保持原表头。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or ())
        rows = list(reader)
    mutate(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_valid_bundle_and_internal_objects() -> None:
    """权威合成模板应完整投影为内部对象。"""
    bundle = load_storage_planning_bundle(SOURCE)
    assert len(bundle.sites) == 3
    assert len(bundle.technologies) == 2
    assert len(bundle.site_technology_options) == 4
    assert len(bundle.scenarios) == 3
    assert bundle.policy.policy_code == "synthetic_cost_robust_v1"
    assert bundle.scenario_set_code == "synthetic_typical_days_v1"
    assert bundle.recommendation_level == "planning_sensitivity"
    assert "synthetic" in {code.lower() for code in storage_planning_input_status_codes(bundle)}
    assert len(bundle.input_fingerprint_sha256) == 64
    assert sum(item.weight for item in bundle.scenarios) == 1.0
    assert sum(item.core_for_feasibility for item in bundle.scenarios) == 2
    assert sum(item.buildable for item in bundle.sites) == 2

    fillable = load_storage_planning_bundle(FILLABLE_TEMPLATE)
    assert len(fillable.sites) == 1
    assert fillable.recommendation_level == "planning_sensitivity"
    assert fillable.input_fingerprint_sha256 != bundle.input_fingerprint_sha256
    validate_storage_planning_power_arm_references(
        bundle,
        FROZEN_POWER_ARMS,
    )


def test_machine_contract_matches_implementation() -> None:
    """机器可读合同必须与代码中的冻结文件、字段和枚举一致。"""
    contract = json.loads(
        (ROOT / "data_templates" / "storage_planning_contract.json").read_text(encoding="utf-8")
    )
    assert contract["schema_version"] == "1.0"
    assert tuple(contract["required_files"]) == CONTRACT_FILE_NAMES
    assert tuple(contract["csv_schemas"][CONTRACT_FILE_NAMES[0]]) == SITE_COLUMNS
    assert tuple(contract["csv_schemas"][CONTRACT_FILE_NAMES[1]]) == TECHNOLOGY_COLUMNS
    assert tuple(contract["csv_schemas"][CONTRACT_FILE_NAMES[2]]) == OPTION_COLUMNS
    scenarios = contract["json_contracts"][CONTRACT_FILE_NAMES[3]]
    assert set(scenarios["root_required"]) == SCENARIO_ROOT_REQUIRED
    assert set(scenarios["scenario_required"]) == SCENARIO_ITEM_REQUIRED
    assert set(scenarios["scenario_optional"]) == SCENARIO_ITEM_OPTIONAL
    assert set(scenarios["schedule_template_required"]) == SCHEDULE_TEMPLATE_FIELDS
    policy = contract["json_contracts"][CONTRACT_FILE_NAMES[4]]
    assert set(policy["required"]) == POLICY_REQUIRED
    assert set(policy["optional"]) == POLICY_OPTIONAL
    enums = contract["enums"]
    assert set(enums["data_status"]) == DATA_STATUSES
    assert set(enums["direction"]) == DIRECTIONS
    assert set(enums["target_final_soc_rule"]) == TARGET_FINAL_SOC_RULES
    assert set(enums["objective_mode"]) == OBJECTIVE_MODES
    assert set(enums["risk_measure"]) == RISK_MEASURES
    assert set(enums["solver_profile"]) == SOLVER_PROFILES
    assert set(enums["parameter_override"]) == PARAMETER_OVERRIDE_FIELDS


def test_fingerprint_is_repeatable_and_order_independent() -> None:
    """同一语义在重复加载和CSV行换序后必须得到相同指纹。"""
    first = load_storage_planning_bundle(SOURCE).input_fingerprint_sha256
    second = load_storage_planning_bundle(SOURCE).input_fingerprint_sha256
    assert first == second
    with TemporaryDirectory(prefix="storage_planning_order_") as name:
        target = Path(name)
        _copy_bundle(target)
        for file_name in CONTRACT_FILE_NAMES[:3]:
            _rewrite_csv(target / file_name, lambda rows: rows.reverse())
        reordered = load_storage_planning_bundle(target).input_fingerprint_sha256
        assert reordered == first


def test_fingerprint_changes_with_business_input() -> None:
    """容量、功率、成本等业务参数变化必须改变输入指纹。"""
    original = load_storage_planning_bundle(SOURCE).input_fingerprint_sha256
    with TemporaryDirectory(prefix="storage_planning_hash_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_candidate_sites.csv",
            lambda rows: rows[0].__setitem__("max_capacity_kwh", "31000"),
        )
        changed = load_storage_planning_bundle(target).input_fingerprint_sha256
        assert changed != original


def test_missing_file_and_invalid_header_are_rejected() -> None:
    """缺失文件或表头漂移不能被静默接受。"""
    with TemporaryDirectory(prefix="storage_planning_missing_") as name:
        target = Path(name)
        _copy_bundle(target)
        (target / "storage_planning_policy.json").unlink()
        _expect_error(target, "missing_file")
    with TemporaryDirectory(prefix="storage_planning_header_") as name:
        target = Path(name)
        _copy_bundle(target)
        path = target / "storage_candidate_sites.csv"
        text = path.read_text(encoding="utf-8-sig").replace("site_name", "renamed_site_name", 1)
        path.write_text(text, encoding="utf-8")
        _expect_error(target, "invalid_header")


def test_scenario_contract_rejects_bad_weights_and_paths() -> None:
    """场景概率和运行图引用必须满足确定合同。"""
    with TemporaryDirectory(prefix="storage_planning_weight_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_json(
            target / "storage_planning_scenarios.json",
            lambda payload: payload["scenarios"][0].__setitem__("weight", 0.5),
        )
        _expect_error(target, "scenario_weight_sum")
    with TemporaryDirectory(prefix="storage_planning_path_") as name:
        target = Path(name)
        _copy_bundle(target)

        def use_unsafe_path(payload) -> None:
            """把一个合法合成运行模板改为目录穿越引用。"""
            scenario = payload["scenarios"][0]
            scenario.pop("schedule_template")
            scenario["timetable_relative_path"] = "../outside.xlsx"

        _rewrite_json(target / "storage_planning_scenarios.json", use_unsafe_path)
        _expect_error(target, "unsafe_relative_path")


def test_cross_file_references_and_limits_are_rejected() -> None:
    """孤儿引用、空容量域和越过接入上限必须阻断。"""
    with TemporaryDirectory(prefix="storage_planning_reference_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_site_technology_options.csv",
            lambda rows: rows[0].__setitem__("site_code", "UNKNOWN-SITE"),
        )
        _expect_error(target, "unknown_site_reference")
    with TemporaryDirectory(prefix="storage_planning_domain_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_site_technology_options.csv",
            lambda rows: rows[0].update({"min_capacity_kwh": "35000", "max_capacity_kwh": "36000"}),
        )
        _expect_error(target, "empty_capacity_domain")
    with TemporaryDirectory(prefix="storage_planning_power_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_site_technology_options.csv",
            lambda rows: rows[0].__setitem__("max_charge_power_kw", "12001"),
        )
        _expect_error(target, "site_power_limit_exceeded")


def test_policy_and_numeric_errors_are_rejected() -> None:
    """互相矛盾的策略和非有限数不能进入后续求解。"""
    with TemporaryDirectory(prefix="storage_planning_policy_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_json(
            target / "storage_planning_policy.json",
            lambda payload: payload.__setitem__("max_site_count", 3),
        )
        _expect_error(target, "max_site_count_exceeds_candidates")
    with TemporaryDirectory(prefix="storage_planning_coordination_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_json(
            target / "storage_planning_policy.json",
            lambda payload: payload.__setitem__("coordination_shortlist_size", 1),
        )
        _expect_error(target, "unexpected_coordination_shortlist")
    with TemporaryDirectory(prefix="storage_planning_number_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_candidate_sites.csv",
            lambda rows: rows[0].__setitem__("max_capacity_kwh", "NaN"),
        )
        _expect_error(target, "non_finite_number")


def test_power_arm_reference_mismatch_is_rejected() -> None:
    """启用基础设施交叉核验后，未知供电臂不能进入规划。"""
    with TemporaryDirectory(prefix="storage_planning_arm_") as name:
        target = Path(name)
        _copy_bundle(target)
        _rewrite_csv(
            target / "storage_candidate_sites.csv",
            lambda rows: rows[0].__setitem__("power_arm_code", "UNKNOWN-POWER-ARM"),
        )
        report = validate_storage_planning_inputs(
            target,
            FROZEN_POWER_ARMS,
        )
        assert report["valid"] is False
        assert report["issues"][0]["code"] == "unknown_power_arm_reference"


def test_validation_report_handles_success_and_failure() -> None:
    """非抛出式接口和报告文件应同时覆盖成功与失败。"""
    valid = validate_storage_planning_inputs(
        SOURCE,
        FROZEN_POWER_ARMS,
    )
    assert valid["valid"] is True and valid["error_count"] == 0
    assert valid["power_arm_reference_check_applied"] is True
    with TemporaryDirectory(prefix="storage_planning_report_") as name:
        root = Path(name)
        invalid_source = root / "input"
        output = root / "output"
        _copy_bundle(invalid_source)
        _rewrite_json(
            invalid_source / "storage_planning_policy.json",
            lambda payload: payload.__setitem__("discount_rate", -0.01),
        )
        report = write_storage_planning_validation_report(invalid_source, output)
        assert report["valid"] is False
        assert report["error_count"] == 1
        assert (output / "storage_planning_validation_summary.json").is_file()
        assert (output / "storage_planning_validation_issues.csv").is_file()
        persisted = json.loads((output / "storage_planning_validation_summary.json").read_text(encoding="utf-8"))
        assert persisted["issues"][0]["code"] == "number_below_minimum"


def test_official_inputs_upgrade_level_to_formal_engineering() -> None:
    """全部关键输入为正式来源时等级升级，任一非正式来源立即回落。"""
    with TemporaryDirectory(prefix="storage_planning_official_") as name:
        target = Path(name)
        _copy_bundle(target)
        for file_name in CONTRACT_FILE_NAMES[:3]:
            _rewrite_csv(
                target / file_name,
                lambda rows: [
                    row.__setitem__("data_status", "official") if "data_status" in row else None
                    for row in rows
                ],
            )
        _rewrite_json(
            target / "storage_planning_scenarios.json",
            lambda payload: [item.__setitem__("data_status", "official") for item in payload["scenarios"]],
        )
        _rewrite_json(
            target / "storage_planning_policy.json",
            lambda payload: payload.__setitem__("data_status", "derived_from_official"),
        )
        official = load_storage_planning_bundle(target)
        assert official.recommendation_level == "formal_engineering"
        assert storage_planning_input_status_codes(official) == ["derived_from_official", "official"]

        _rewrite_json(
            target / "storage_planning_policy.json",
            lambda payload: payload.__setitem__("data_status", "planning_placeholder"),
        )
        downgraded = load_storage_planning_bundle(target)
        assert downgraded.recommendation_level == "planning_sensitivity"


def main() -> None:
    """运行阶段A全部快速合同检查。"""
    test_valid_bundle_and_internal_objects()
    test_machine_contract_matches_implementation()
    test_official_inputs_upgrade_level_to_formal_engineering()
    test_fingerprint_is_repeatable_and_order_independent()
    test_fingerprint_changes_with_business_input()
    test_missing_file_and_invalid_header_are_rejected()
    test_scenario_contract_rejects_bad_weights_and_paths()
    test_cross_file_references_and_limits_are_rejected()
    test_policy_and_numeric_errors_are_rejected()
    test_power_arm_reference_mismatch_is_rejected()
    test_validation_report_handles_success_and_failure()
    print("storage planning phase-A contract smoke: PASS")


if __name__ == "__main__":
    main()
