"""汇总静态、平台、实时、核心算法及随机差分的异常与极端输入验收。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.algorithm_robustness_checks import run_checks as run_robustness_checks
from tools.platform_parameter_anomaly_matrix import run_matrix as run_parameter_matrix
from tools.random_synthetic_differential import run_differential_tests
from tools.realtime_state_anomaly_matrix import run_matrix as run_realtime_matrix
from tools.synthetic_data_anomaly_matrix import run_matrix as run_data_matrix


DEEP_GUARD_SCRIPTS = (
    "tests/smoke/verify_robustness_contracts.py",
    "tests/smoke/verify_data_ingestion_input_guards.py",
    "tests/smoke/verify_power_arm_input_guards.py",
    "tests/smoke/verify_resource_interval_contracts.py",
    "tests/smoke/verify_historical_disturbance_replay.py",
    "tests/smoke/verify_database_integration.py",
)


def _component(name: str, passed: bool, case_count: int, detail: str, output: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "case_count": int(case_count),
        "detail": detail,
        "output": output,
    }


def _run_guard_scripts(output_dir: Path) -> list[dict[str, Any]]:
    """运行难以用单一案例数表达的深层构造器和合同测试。"""

    log_dir = output_dir / "component_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT"] = str(output_dir / "component_outputs")
    rows: list[dict[str, Any]] = []
    for relative_script in DEEP_GUARD_SCRIPTS:
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, relative_script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        stem = Path(relative_script).stem
        stdout_path = log_dir / f"{stem}.stdout.txt"
        stderr_path = log_dir / f"{stem}.stderr.txt"
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        rows.append({
            "name": stem,
            "passed": completed.returncode == 0,
            "return_code": completed.returncode,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "stdout": str(stdout_path.relative_to(output_dir)).replace("\\", "/"),
            "stderr": str(stderr_path.relative_to(output_dir)).replace("\\", "/"),
        })
    return rows


def run_suite(
    output_dir: Path,
    *,
    seeds: list[int] | None = None,
    energy_cases: int = 500,
    time_slicing_cases: int = 300,
    resource_cases: int = 500,
    pareto_cases: int = 300,
) -> dict[str, Any]:
    """运行全链路异常与极端输入测试并生成统一结论。"""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_seeds = seeds or [20260909, 20260910, 20260911]
    data_result = run_data_matrix(ROOT / "data/real_shuohuang", output_dir / "static_data")
    parameter_result = run_parameter_matrix(output_dir / "platform_parameters")
    realtime_result = run_realtime_matrix(output_dir / "realtime_state")
    robustness_result = run_robustness_checks(output_dir / "core_extremes")
    random_result = run_differential_tests(
        output_dir / "random_differential",
        seeds=selected_seeds,
        energy_cases=energy_cases,
        time_slicing_cases=time_slicing_cases,
        resource_cases=resource_cases,
        pareto_cases=pareto_cases,
    )
    guard_results = _run_guard_scripts(output_dir)

    components = [
        _component("static_data_anomalies", data_result["passed"], data_result["case_count"], "静态数据文件、拓扑、车辆、储能和跨表引用", "static_data/SYNTHETIC_DATA_ANOMALY_REPORT.md"),
        _component("platform_parameter_anomalies", parameter_result["passed"], parameter_result["case_count"], "五类任务的结构、数值、枚举、路径和设备状态", "platform_parameters/PLATFORM_PARAMETER_ANOMALY_REPORT.md"),
        _component("realtime_state_anomalies", realtime_result["passed"], realtime_result["case_count"], "实时字段、时钟、顺序、断流、设备和滚动恢复", "realtime_state/REALTIME_STATE_ANOMALY_MATRIX_REPORT.md"),
        _component("core_extreme_scenarios", robustness_result["passed"], len(robustness_result["extreme_cases"]["checks"]), "空输入、零/满SOC、零效率、极大/极小有限量和多设备隔离", "core_extremes/ALGORITHM_ROBUSTNESS_CHECKS.md"),
        _component("random_differential", random_result["passed"], random_result["total_case_count"], "能量桶、时间切片、资源重叠和Pareto独立参考差分", "random_differential/RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md"),
        _component("deep_guard_scripts", all(row["passed"] for row in guard_results), len(guard_results), "核心构造器、数据导入、供电臂、资源、扰动回放和数据库适配器", "component_logs/"),
    ]
    failed_components = [item["name"] for item in components if not item["passed"]]
    summary = {
        "schema_version": "1.0",
        "passed": not failed_components,
        "component_count": len(components),
        "passed_component_count": len(components) - len(failed_components),
        "failed_component_count": len(failed_components),
        "enumerated_case_count": sum(item["case_count"] for item in components),
        "failed_components": failed_components,
        "components": components,
        "deep_guard_results": guard_results,
        "random_case_set_sha256": random_result["case_set_sha256"],
        "outputs": {
            "report": "ABNORMAL_EXTREME_INPUT_TEST_REPORT.md",
            "summary": "abnormal_extreme_input_summary.json",
        },
    }
    (output_dir / summary["outputs"]["summary"]).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 异常与极端输入测试总报告", "",
        f"- 总状态：`{'PASS' if summary['passed'] else 'FAIL'}`",
        f"- 测试层：{summary['component_count']}",
        f"- 可枚举案例/专项：{summary['enumerated_case_count']}",
        f"- 失败测试层：{summary['failed_component_count']}",
        f"- 随机案例指纹：`{summary['random_case_set_sha256']}`", "",
        "| 测试层 | 案例/专项数 | 范围 | 状态 | 详细结果 |", "| --- | ---: | --- | --- | --- |",
    ]
    for item in components:
        lines.append(f"| `{item['name']}` | {item['case_count']} | {item['detail']} | {'PASS' if item['passed'] else 'FAIL'} | `{item['output']}` |")
    lines.extend([
        "", "## 判定", "",
        "只有六个测试层全部通过时，总状态才为PASS。异常输入必须在进入计算前拒绝；合法边界和极端有限值必须保持能量守恒、数值有限和设备隔离；随机案例必须与独立参考实现一致。",
        "", "## 边界", "",
        "本报告验证当前软件合同中的异常处理和已枚举极端场景，不证明正式工程参数真实，也不替代目标数据库、网络、中间件和现场设备的压力及故障联调。",
        "",
    ])
    (output_dir / summary["outputs"]["report"]).write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper/experiments/abnormal_extreme_input_current")
    parser.add_argument("--seeds", nargs="+", type=int, default=[20260909, 20260910, 20260911])
    parser.add_argument("--energy-cases", type=int, default=500)
    parser.add_argument("--time-slicing-cases", type=int, default=300)
    parser.add_argument("--resource-cases", type=int, default=500)
    parser.add_argument("--pareto-cases", type=int, default=300)
    args = parser.parse_args()
    summary = run_suite(
        args.output_dir,
        seeds=args.seeds,
        energy_cases=args.energy_cases,
        time_slicing_cases=args.time_slicing_cases,
        resource_cases=args.resource_cases,
        pareto_cases=args.pareto_cases,
    )
    print(json.dumps({key: summary[key] for key in ("passed", "enumerated_case_count", "failed_component_count")}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
