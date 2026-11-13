"""验证冻结接口清单及其语义一致性门禁。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_interface_contract_freeze import _write_report, verify_contract


def main() -> int:
    output_root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", ROOT / "outputs"))
    output_dir = output_root / "interface_contract_freeze_smoke"
    result = verify_contract(ROOT)
    _write_report(output_dir, result)
    assert result["status"] == "PASS", [item for item in result["checks"] if not item["passed"]]
    assert result["freeze_version"] == "1.6.0"
    assert result["failed_count"] == 0
    assert result["check_count"] >= 60
    payload = json.loads((output_dir / "interface_contract_freeze_check.json").read_text(encoding="utf-8"))
    assert payload["passed_count"] == payload["check_count"]
    assert (output_dir / "INTERFACE_CONTRACT_FREEZE_REPORT.md").is_file()

    # 在隔离副本中篡改已冻结示例，必须由哈希门禁明确拒绝。
    with TemporaryDirectory(prefix="interface_contract_tamper_") as temp_dir:
        temp_root = Path(temp_dir)
        shutil.copytree(ROOT / "database", temp_root / "database")
        (temp_root / "docs").mkdir()
        shutil.copy2(ROOT / "docs/prototype_backend_contract.json", temp_root / "docs/prototype_backend_contract.json")
        (temp_root / "data_templates").mkdir()
        for name in ("historical_disturbance_replay_template.json", "joint_parameter_ranges_template.json", "rolling_shadow_request_template.json"):
            shutil.copy2(ROOT / "data_templates" / name, temp_root / "data_templates" / name)
        tampered = temp_root / "database/examples/dispatch_parameters.json"
        tampered.write_text(tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        rejected = verify_contract(temp_root)
        assert rejected["status"] == "FAIL"
        assert any(
            not item["passed"] and item["name"] == "sha256:database/examples/dispatch_parameters.json"
            for item in rejected["checks"]
        )
    print("interface contract freeze verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
