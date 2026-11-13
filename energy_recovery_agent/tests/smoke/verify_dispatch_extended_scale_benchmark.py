# 模块功能说明：验证扩展规模计划、双口径案例和受监控命令构造契约。

from pathlib import Path
import json
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.dispatch_extended_scale_benchmark import (
    _read_quality_comparison,
    _write_report,
    command_for_case,
    load_plan,
)


def _option(argv: list[str], name: str) -> str:
    """读取生成命令中的选项值。"""

    return argv[argv.index(name) + 1]


def main() -> int:
    """检查4个冻结案例的服务时刻和命令参数。"""

    common = {
        "population_size": 4,
        "generations": 1,
        "seed": 11,
        "parallel_workers": 1,
        "settlement_step_s": 10,
        "scenario_count": 5,
    }
    specifications = {
        "F12": (6, 14400, 2400, 840, 1800, 2700, 2400, 12000, 12840, 720),
        "F16": (8, 14400, 1800, 840, 1500, 2100, 1800, 12600, 13440, 1200),
        "E12": (6, 18000, 3300, 840, 3000, 3600, 5400, 16500, 17340, 720),
        "E16": (8, 25200, 3300, 840, 3000, 3600, 5400, 23100, 23940, 1200),
    }
    planned_cases = []
    for case_id, values in specifications.items():
        count, horizon, headway, phase, minimum, maximum, max_phase, last_heavy, last_empty, timeout = values
        planned_cases.append(
            {
                "case_id": case_id,
                "scope": "fixed_horizon_transport_density" if case_id.startswith("F") else "expanded_horizon_computational_scaling",
                "heavy_count": count,
                "empty_count": count,
                "horizon_s": horizon,
                "heavy_headway_s": headway,
                "empty_headway_s": headway,
                "phase_s": phase,
                "search_min_headway_s": minimum,
                "search_max_headway_s": maximum,
                "search_max_phase_s": max_phase,
                "last_heavy_departure_s": last_heavy,
                "last_empty_departure_s": last_empty,
                "timeout_s": timeout,
            }
        )
    with tempfile.TemporaryDirectory() as plan_temp:
        plan_path = Path(plan_temp) / "plan.json"
        plan_path.write_text(
            json.dumps({"common_settings": common, "planned_cases": planned_cases}),
            encoding="utf-8",
        )
        plan = load_plan(plan_path)
    cases = {case["case_id"]: case for case in plan["planned_cases"]}
    assert set(cases) == {"F12", "F16", "E12", "E16"}
    assert cases["F12"]["horizon_s"] == cases["F16"]["horizon_s"] == 14400
    assert cases["E12"]["heavy_headway_s"] == cases["E16"]["heavy_headway_s"] == 3300
    for case in cases.values():
        assert case["last_heavy_departure_s"] <= case["horizon_s"]
        assert case["last_empty_departure_s"] <= case["horizon_s"]
        command = command_for_case(case, plan["common_settings"], Path("out") / case["case_id"])
        assert _option(command, "--horizon-s") == str(case["horizon_s"])
        assert _option(command, "--search-min-headway-s") == str(case["search_min_headway_s"])
        assert _option(command, "--search-max-headway-s") == str(case["search_max_headway_s"])
        assert _option(command, "--search-max-phase-s") == str(case["search_max_phase_s"])

    with tempfile.TemporaryDirectory() as temporary_dir:
        output_dir = Path(temporary_dir)
        (output_dir / "kpi_summary.csv").write_text(
            "case,resource_conflict_count,constraint_violation,grid_kwh,wasted_kwh,recovery_rate,total_cost\n"
            "baseline,3,0.2,100,200,0.1,300\n"
            "optimized,1,0.05,90,180,0.2,285\n",
            encoding="utf-8",
        )
        quality = _read_quality_comparison(output_dir)
        assert quality["grid_change_pct"] == -10.0
        assert quality["wasted_change_pct"] == -10.0
        assert quality["cost_change_pct"] == -5.0
        report_row = {
            "case_id": "F12",
            "scope": "fixed_horizon_transport_density",
            "train_count": 12,
            "horizon_s": 14400,
            "timeout_limit_s": 720,
            "wall_time_s": 360.0,
            "peak_rss_mb": 140.0,
            "passed": True,
            "service_population_complete": True,
            "core_robust_feasible": False,
            "nominal_fallback_used": True,
            **quality,
        }
        _write_report(output_dir, [report_row])
        report = (output_dir / "DISPATCH_EXTENDED_SCALE_REPORT.md").read_text(encoding="utf-8")
        assert "解质量诊断" in report
        assert "不能作为可实施优化收益" in report
        assert "当前未达到第五阶段架构优化的触发条件" in report
    print("dispatch extended-scale benchmark plan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
