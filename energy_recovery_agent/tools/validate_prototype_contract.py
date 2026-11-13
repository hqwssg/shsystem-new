"""Validate prototype UI ids against the machine-readable backend contract."""

from __future__ import annotations

import json
import re
from pathlib import Path


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[1]
    contract = json.loads((root / "docs" / "prototype_backend_contract.json").read_text(encoding="utf-8"))
    fragment = (root / "prototypes" / "heavy-empty-coordination-ui.fragment.html").read_text(encoding="utf-8")
    errors: list[str] = []
    for field in contract["input_fields"]:
        ui_id = field["ui_id"]
        if not re.search(rf"id=[\"']{re.escape(ui_id)}[\"']", fragment):
            errors.append(f"missing UI id: {ui_id}")
    for field in contract["derived_fields"]:
        if field == "prediction_window_s" and "hec2-prediction-window" not in fragment:
            errors.append("missing prediction derived field")
        if field == "execution_window_s" and "hec2-execute-window" not in fragment:
            errors.append("missing execution derived field")
        if field == "evaluation_window_s" and "hec2-evaluation-window" not in fragment:
            errors.append("missing evaluation derived field")
    if "不能直接提交" not in fragment:
        errors.append("prototype boundary disclosure missing")
    payload = {"valid": not errors, "error_count": len(errors), "errors": errors, "contract_schema_version": contract["schema_version"]}
    out = root / "outputs" / "prototype_contract_validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "contract_validation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
