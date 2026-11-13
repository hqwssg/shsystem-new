"""验证生产保障策略、告警判定、恢复安全边界和本地预检语义。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.production_assurance_preflight as preflight_module
from tools.production_database_backup_restore import (
    _connection_environment,
    validate_restore_database_name,
)
from tools.production_operations_snapshot import DEFAULT_POLICY, evaluate_metric, load_policy


def _expect_error(action, expected_text: str) -> None:
    try:
        action()
    except (ValueError, RuntimeError) as exc:
        if expected_text not in str(exc):
            raise AssertionError(f"异常信息缺少{expected_text!r}：{exc}") from exc
    else:
        raise AssertionError("危险输入必须被拒绝。")


def main() -> None:
    policy = load_policy(DEFAULT_POLICY)
    max_rule = {"warning": 10, "critical": 20, "direction": "max"}
    min_rule = {"warning": 20, "critical": 10, "direction": "min"}
    if [evaluate_metric("x", value, max_rule)["severity"] for value in (9, 10, 20)] != [
        "ok", "warning", "critical"
    ]:
        raise AssertionError("最大值型告警边界错误。")
    if [evaluate_metric("x", value, min_rule)["severity"] for value in (21, 20, 10)] != [
        "ok", "warning", "critical"
    ]:
        raise AssertionError("最小值型告警边界错误。")

    suffix = policy["backup"]["restore_database_suffix"]
    validate_restore_database_name("carbon_emissions_restore_test", suffix, "carbon_emissions")
    _expect_error(
        lambda: validate_restore_database_name("carbon_emissions", suffix, "carbon_emissions"),
        "必须以",
    )
    _expect_error(
        lambda: validate_restore_database_name("other_database", suffix, "carbon_emissions"),
        "必须以",
    )
    _expect_error(
        lambda: validate_restore_database_name("bad-name_restore_test", suffix, "carbon_emissions"),
        "只能包含",
    )

    environment, database = _connection_environment(
        "postgresql://worker:REPLACE_ME_TEST_SECRET@127.0.0.1:5432/carbon_emissions?sslmode=require"
    )
    if database != "carbon_emissions" or environment.get("PGPASSWORD") != "REPLACE_ME_TEST_SECRET":
        raise AssertionError("连接串到PG环境变量的转换错误。")
    serialized = json.dumps({"database": database, "command": ["pg_dump", "--format=custom"]})
    if "REPLACE_ME_TEST_SECRET" in serialized:
        raise AssertionError("密码不得进入命令或报告载荷。")

    with tempfile.TemporaryDirectory(prefix="production_assurance_smoke_") as temp_dir:
        # 预检语义测试只验证外部环境待验收分支；将本机磁盘阈值设为零，
        # 避免测试结果随共享工作盘剩余空间波动。
        test_policy = Path(temp_dir) / "policy.json"
        policy_payload = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
        policy_payload["monitoring"]["thresholds"]["host_disk_free_percent"]["critical"] = 0
        test_policy.write_text(json.dumps(policy_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        original_release_check = preflight_module.verify_source_baseline
        preflight_module.verify_source_baseline = lambda _root: {
            "status": "PASS", "release_version": "test", "errors": []
        }
        try:
            result = preflight_module.run_preflight(
                Path(temp_dir), policy_path=test_policy, database_url=None, require_tls=True
            )
        finally:
            preflight_module.verify_source_baseline = original_release_check
        if not result["local_ready"] or result["production_accepted"] is not False:
            raise AssertionError(f"无目标环境的本地预检语义错误：{result}")
        if result["status"] != "local_ready_external_pending" or not result["external_pending"]:
            raise AssertionError("预检必须明确保留外部待验收项。")
        report_text = (Path(temp_dir) / "PRODUCTION_ASSURANCE_PREFLIGHT.md").read_text(encoding="utf-8")
        if "PENDING_EXTERNAL" not in report_text:
            raise AssertionError("人读报告必须明确生产验收待外部完成。")

    print("production assurance toolkit smoke: PASS")


if __name__ == "__main__":
    main()
