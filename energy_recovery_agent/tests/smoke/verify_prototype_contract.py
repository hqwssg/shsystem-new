"""Smoke check for prototype/backend contract consistency."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(root / "tools" / "validate_prototype_contract.py")]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    payload = json.loads(completed.stdout.strip())
    if not payload.get("valid") or payload.get("error_count") != 0:
        raise AssertionError(payload)
    fragment = (root / "prototypes" / "heavy-empty-coordination-ui.fragment.html").read_text(encoding="utf-8")
    for value in ("delay", "weather", "device"):
        if f'value="{value}" disabled' not in fragment:
            raise AssertionError(f"unsupported scenario {value} must remain disabled in prototype")
    print("prototype/backend contract verification: PASS")


if __name__ == "__main__":
    main()
