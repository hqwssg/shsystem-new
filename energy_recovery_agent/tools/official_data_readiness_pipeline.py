# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Read-only readiness pipeline for an eventual official-data delivery.

The pipeline never replaces ``data/real_shuohuang``.  It fingerprints the
candidate tree, runs the strict acceptance gate, and optionally runs a
simulation in an isolated output directory followed by the result audit.
"""

import argparse, hashlib, json, subprocess, sys
from pathlib import Path
from typing import Any, Optional, Sequence

# 允许直接从 ``tools`` 目录执行。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from formal_data_acceptance import run_acceptance, write_report as write_acceptance_report
from result_quality_audit import audit_output_root, write_report as write_quality_report


def file_manifest(root: Path) -> list[dict[str, Any]]:
    """函数 file_manifest：执行该模块中的相关处理逻辑。"""
    root = Path(root)
    rows = []
    if not root.is_dir():
        return rows
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({"path": str(path.relative_to(root)), "size": path.stat().st_size, "sha256": digest})
    return rows


def _numeric_metrics(root: Path) -> dict[str, float]:
    """函数 _numeric_metrics：执行该模块中的相关处理逻辑。"""
    metrics: dict[str, float] = {}
    for path in sorted(Path(root).rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        def walk(obj: Any, prefix: str = "") -> None:
            """函数 walk：执行该模块中的相关处理逻辑。"""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    name = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        if key.endswith(("_kwh", "_kw", "_cost", "_s", "_count")):
                            metrics[name] = float(value)
                    walk(value, name)
            elif isinstance(obj, list):
                for i, value in enumerate(obj):
                    walk(value, f"{prefix}[{i}]")
        walk(payload, path.relative_to(root).as_posix())
    return metrics


def compare_results(baseline: Path, candidate: Path, tolerance: float = 1e-6) -> dict[str, Any]:
    """函数 compare_results：执行该模块中的相关处理逻辑。"""
    left, right = _numeric_metrics(baseline), _numeric_metrics(candidate)
    keys = sorted(set(left) | set(right))
    changes = []
    for key in keys:
        if key not in left or key not in right:
            changes.append({"metric": key, "baseline": left.get(key), "candidate": right.get(key), "status": "added_or_removed"})
        elif abs(left[key] - right[key]) > tolerance * max(1.0, abs(left[key]), abs(right[key])):
            changes.append({"metric": key, "baseline": left[key], "candidate": right[key], "status": "changed"})
    return {"baseline": str(baseline), "candidate": str(candidate), "metric_count": len(keys), "changed_count": len(changes), "changes": changes}


def run_pipeline(data_dir: Path, source_dir: Path, timetable: Path, output_dir: Path,
                 run_simulation: bool = False, baseline_output: Optional[Path] = None) -> dict[str, Any]:
    """函数 run_pipeline：执行该模块中的相关处理逻辑。"""
    data_dir, source_dir, timetable, output_dir = map(Path, (data_dir, source_dir, timetable, output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    acceptance = run_acceptance(data_dir, source_dir, timetable)
    write_acceptance_report(acceptance, output_dir)
    (output_dir / "candidate_manifest.json").write_text(json.dumps({"root": str(data_dir), "files": file_manifest(data_dir)}, ensure_ascii=False, indent=2), encoding="utf-8")
    result: dict[str, Any] = {"accepted": acceptance["accepted"], "acceptance": acceptance, "simulation": None, "comparison": None}
    if acceptance["accepted"] and run_simulation:
        sim_root = output_dir / "simulation"
        cmd = [sys.executable, str(PROJECT_ROOT / "run_project.py"), "simulate", "--data-dir", str(data_dir), "--source-dir", str(source_dir), "--timetable", str(timetable), "--output-root", str(sim_root), "--require-official-data"]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)
        result["simulation"] = {"returncode": proc.returncode, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:]}
        audit = audit_output_root(sim_root)
        write_quality_report(audit, output_dir / "simulation_quality_audit")
        result["simulation"]["audit"] = audit
        if baseline_output and audit["accepted"]:
            result["comparison"] = compare_results(Path(baseline_output), sim_root)
    (output_dir / "readiness_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    p = argparse.ArgumentParser(description="正式数据只读验收、隔离仿真和结果对比流水线")
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--timetable", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--run-simulation", action="store_true")
    p.add_argument("--baseline-output", type=Path)
    args = p.parse_args(argv)
    result = run_pipeline(**vars(args))
    print(json.dumps({"accepted": result["accepted"], "simulation": result["simulation"] is not None, "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] and (not result["simulation"] or result["simulation"].get("returncode") == 0 and result["simulation"]["audit"]["accepted"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
