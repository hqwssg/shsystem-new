"""Run a catalog of deterministic synthetic edge-case scenarios.

The matrix delegates to existing smoke tests so it observes current behavior
without introducing a second implementation of the algorithm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Scenario:
    """类 Scenario：执行该模块中的相关处理逻辑。"""
    scenario_id: str
    script: str
    category: str
    expected: str
    tags: tuple[str, ...] = ()
    timeout_s: int = 180


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("settlement_nominal", "tests/smoke/verify_energy_settlement_correctness.py", "energy", "normal settlement invariants pass", ("nominal",)),
    Scenario("storage_no_direct", "tests/smoke/verify_energy_scenarios.py", "energy", "direct use remains zero and storage scenario completes", ("storage", "regeneration")),
    Scenario("settlement_invariants", "tests/smoke/verify_settlement_invariants.py", "energy", "energy/SOC invariants hold", ("boundary", "soc")),
    Scenario("multi_storage_terminal_soc", "tests/smoke/verify_multi_storage_terminal_soc.py", "dispatch", "terminal SOC is reported per storage device", ("storage", "multi-device")),
    Scenario("zero_length_train", "tests/smoke/verify_zero_length_train_cache.py", "simulation", "zero-length point-mass cache is accepted", ("boundary", "cache")),
    Scenario("resource_conflict_detection", "tests/smoke/verify_timetable_resource_constraints.py", "timetable", "resource conflicts are detected and classified", ("constraints",)),
    Scenario("invalid_input_guards", "tests/smoke/verify_data_ingestion_input_guards.py", "input", "invalid numeric/boolean fields are rejected", ("validation",)),
    Scenario("power_arm_lookup", "tests/smoke/verify_power_arm_lookup.py", "infrastructure", "direction/mainline lookup is deterministic", ("lookup",)),
    Scenario("rolling_constraints", "tests/smoke/verify_rolling_optimizer_constraints.py", "optimization", "constraint domination and Pareto dedup hold", ("optimizer",)),
)


def _normalize_output(text: str) -> str:
    """函数 _normalize_output：执行该模块中的相关处理逻辑。"""
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    text = text.replace("\\", "/")
    text = re.sub(r"[A-Za-z]:/[^\s]*?/Temp/[^\s]*", "<TEMP_PATH>", text, flags=re.IGNORECASE)
    text = re.sub(r"/tmp/[^\s]*", "<TEMP_PATH>", text, flags=re.IGNORECASE)
    text = re.sub(r"\r\n?", "\n", text)
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def output_fingerprint(stdout: str, stderr: str) -> str:
    """函数 output_fingerprint：执行该模块中的相关处理逻辑。"""
    payload = (_normalize_output(stdout) + "\n--- STDERR ---\n" + _normalize_output(stderr)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_scenario(scenario: Scenario, project_root: Path) -> dict[str, object]:
    """函数 run_scenario：执行该模块中的相关处理逻辑。"""
    command = [sys.executable, scenario.script]
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=scenario.timeout_s,
            env=environment,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nscenario timed out after {scenario.timeout_s}s"
    elapsed_s = round(time.perf_counter() - started, 3)
    return {
        "scenario_id": scenario.scenario_id,
        "script": scenario.script,
        "category": scenario.category,
        "expected": scenario.expected,
        "tags": list(scenario.tags),
        "timeout_s": scenario.timeout_s,
        "return_code": return_code,
        "passed": return_code == 0 and not timed_out,
        "timed_out": timed_out,
        "elapsed_s": elapsed_s,
        "output_fingerprint": output_fingerprint(stdout, stderr),
        "stdout_tail": _normalize_output(stdout)[-1200:],
        "stderr_tail": _normalize_output(stderr)[-1200:],
    }


def run_matrix(project_root: Path, selected_ids: Optional[Iterable[str]] = None) -> dict[str, object]:
    """函数 run_matrix：执行该模块中的相关处理逻辑。"""
    selected = set(selected_ids or ())
    scenarios = [scenario for scenario in SCENARIOS if not selected or scenario.scenario_id in selected]
    results = [run_scenario(scenario, project_root) for scenario in scenarios]
    return {
        "schema_version": "1.0",
        "project_root": str(project_root),
        "scenario_count": len(results),
        "passed_count": sum(1 for result in results if result["passed"]),
        "failed_count": sum(1 for result in results if not result["passed"]),
        "scenarios": results,
    }


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/synthetic_scenario_matrix"))
    parser.add_argument("--scenario", action="append", dest="scenario_ids", help="run only this scenario id; repeatable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_matrix(root, args.scenario_ids)
    (output_dir / "scenario_matrix.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 合成场景覆盖矩阵",
        "",
        "本矩阵复用现有 smoke 测试，只记录行为和输出指纹，不改变算法逻辑。",
        "",
        f"- 场景数：{report['scenario_count']}",
        f"- 通过：{report['passed_count']}",
        f"- 失败：{report['failed_count']}",
        "",
        "| 场景 | 类别 | 预期行为 | 状态 | 耗时 (s) | 输出指纹 |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for result in report["scenarios"]:
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"| `{result['scenario_id']}` | {result['category']} | {result['expected']} | {status} | {result['elapsed_s']} | `{result['output_fingerprint'][:12]}` |")
    (output_dir / "SCENARIO_MATRIX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output_dir / "SCENARIO_MATRIX.md"), "json": str(output_dir / "scenario_matrix.json"), "failed_count": report["failed_count"]}, ensure_ascii=False))
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
