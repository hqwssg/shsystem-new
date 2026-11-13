"""为性能和搜索质量实验记录输入、评价代码与运行环境，不读取凭据文件。"""

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import json
import platform
import sys


ROOT = Path(__file__).resolve().parents[1]


def _inventory(paths, root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths) if path.is_file()}


def _digest(inventory: dict[str, str]) -> str:
    return sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def capture_provenance(data_dir: Path) -> dict:
    data_dir = Path(data_dir).resolve()
    if not data_dir.is_dir():
        raise ValueError("基准必须引用一个明确的数据目录。")
    inputs = _inventory((p for p in data_dir.rglob("*")
                         if p.suffix.lower() in {".csv", ".json", ".xlsx"}), data_dir)
    code = _inventory(ROOT.glob("*.py"), ROOT)
    harness = _inventory((ROOT / "tools" / name for name in
                          ("benchmark_provenance.py", "small_scale_optimality_gap_benchmark.py",
                           "dispatch_single_candidate_profile.py", "benchmark_constraint_guided_search.py",
                           "verify_constraint_guided_search_results.py",
                           "benchmark_constraint_guided_extended.py",
                           "benchmark_budgeted_recovery.py", "verify_budgeted_recovery.py",
                           "verify_constraint_guided_extended.py")), ROOT)
    packages = {}
    for name in ("numpy", "scipy", "pandas", "matplotlib"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"input_sha256": _digest(inputs), "evaluation_code_sha256": _digest(code),
            "input_files": inputs, "evaluation_code_files": code,
            "benchmark_code_sha256": _digest(harness), "benchmark_code_files": harness,
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                            "processor": platform.processor(), "packages": packages}}


def verify_provenance(start: dict, data_dir: Path) -> dict:
    end = capture_provenance(data_dir)
    unchanged = (start["input_sha256"] == end["input_sha256"] and
                 start["evaluation_code_sha256"] == end["evaluation_code_sha256"] and
                 start["benchmark_code_sha256"] == end["benchmark_code_sha256"])
    if not unchanged:
        raise RuntimeError("实验过程中输入或评价代码发生变化，本轮证据不予验收。")
    return {**start, "unchanged_during_run": True}
