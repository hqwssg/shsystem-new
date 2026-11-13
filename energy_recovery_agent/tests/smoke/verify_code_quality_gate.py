"""验证代码质量门禁能够执行并正确生成报告。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """运行质量门禁的静态子集并核对报告结构。"""

    with tempfile.TemporaryDirectory(prefix="code_quality_gate_") as temporary:
        output_dir = Path(temporary)
        completed = subprocess.run(
            [sys.executable, "tools/code_quality_gate.py", "--skip-critical-tests", "--output-dir", str(output_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"code quality gate failed: {completed.stdout}\n{completed.stderr}")
        summary = json.loads((output_dir / "code_quality_summary.json").read_text(encoding="utf-8"))
        assert summary["accepted"] is True
        assert summary["syntax_error_count"] == 0
        assert summary["source_file_count"] > 100
        assert (output_dir / "CODE_QUALITY_REPORT.md").is_file()
    print("code quality gate smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
