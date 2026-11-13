"""基准证据记录输入与评价代码，输入变更时拒绝本轮证据。"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.benchmark_provenance import capture_provenance, verify_provenance


def main() -> int:
    with TemporaryDirectory() as directory:
        data = Path(directory)
        source = data / "input.json"
        source.write_text(json.dumps({"power": 10}), encoding="utf-8")
        (data / "credential.txt").write_text("not an input", encoding="utf-8")
        first = capture_provenance(data)
        assert set(first["input_files"]) == {"input.json"}
        assert "tools/benchmark_provenance.py" in first["benchmark_code_files"]
        assert verify_provenance(first, data)["unchanged_during_run"]
        source.write_text(json.dumps({"power": 11}), encoding="utf-8")
        try:
            verify_provenance(first, data)
        except RuntimeError:
            pass
        else:
            raise AssertionError("输入变化不得继续验收")
    print("benchmark input/code provenance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
