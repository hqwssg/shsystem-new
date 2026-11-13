"""在专用PostgreSQL测试库中复验平台任务压力和故障合同。"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.platform_task_stress_fault import run_stress_fault_test


def main() -> int:
    database_url = os.environ.get("SIMULATION_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("未设置SIMULATION_TEST_DATABASE_URL，真实压力集成测试未执行。")
    with tempfile.TemporaryDirectory(prefix="platform_task_stress_integration_") as temp_name:
        summary = run_stress_fault_test(
            database_url,
            output_dir=Path(temp_name),
            task_count=24,
            worker_count=4,
            idempotency_burst=8,
        )
    assert summary["passed"] is True, summary
    assert summary["pressure"]["checks"]["idempotency_burst_single_run"] is True
    assert summary["pressure"]["checks"]["all_tasks_claimed_once"] is True
    assert summary["pressure"]["checks"]["state_event_versions_complete"] is True
    assert summary["fault_injection"] == {
        "case_count": 6,
        "passed_count": 6,
        "failed_count": 0,
    }
    assert summary["cleanup"]["project_deleted"] is True
    print("platform task stress and fault integration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
