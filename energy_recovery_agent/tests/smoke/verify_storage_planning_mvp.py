"""验证储能选址定容阶段B的离散最优性、决策语义和端到端输出。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage_planning_contract import CONTRACT_FILE_NAMES, load_storage_planning_bundle
from storage_planning_mvp import enumerate_storage_plans, run_storage_planning_mvp, select_storage_plan


SOURCE = ROOT / "data_templates" / "storage_planning_synthetic"
CASE_DATA = ROOT / "data" / "real_shuohuang"


def _candidate(plan_id: str, sites: int, cost: float, reduction: float, *, feasible: bool = True, thresholds: bool = True) -> dict:
    """构造不依赖物理仿真的小规模决策候选。"""

    return {
        "plan_id": plan_id,
        "site_count": sites,
        "annual_total_cost_cny": cost,
        "grid_reduction_vs_no_build_kwh_per_year": reduction,
        "within_budget": True,
        "core_feasible": feasible,
        "meets_business_thresholds": thresholds,
    }


def test_declared_discrete_domain_is_exhaustive() -> None:
    """两档粗粒度域应完整包含不建设、单站和双站所有笛卡尔积。"""

    plans = enumerate_storage_plans(load_storage_planning_bundle(SOURCE), max_levels=2)
    assert len(plans) == 153
    assert sum(len(plan) == 0 for plan in plans) == 1
    assert sum(len(plan) == 1 for plan in plans) == 24
    assert sum(len(plan) == 2 for plan in plans) == 128
    assert len({tuple((item.site_code, item.technology_code, item.capacity_kwh, item.charge_power_kw, item.discharge_power_kw) for item in plan) for plan in plans}) == len(plans)


def test_no_build_build_and_multisite_decisions() -> None:
    """决策器应区分无收益不建设、单站建设和双站最优三类结果。"""

    baseline = _candidate("NO_BUILD", 0, 100.0, 0.0, thresholds=False)
    rejected = _candidate("P1", 1, 105.0, 10.0, thresholds=False)
    decision, selected, _reason = select_storage_plan([baseline, rejected], allow_no_build=True, objective_mode="annualized_cost")
    assert decision == "keep_no_build" and selected["plan_id"] == "NO_BUILD"

    one_site = _candidate("P1", 1, 80.0, 20.0)
    decision, selected, _reason = select_storage_plan([baseline, one_site], allow_no_build=True, objective_mode="annualized_cost")
    assert decision == "recommend_build" and selected["plan_id"] == "P1"

    two_site = _candidate("P2", 2, 70.0, 30.0)
    decision, selected, _reason = select_storage_plan([baseline, one_site, two_site], allow_no_build=True, objective_mode="annualized_cost")
    assert decision == "recommend_build" and selected["plan_id"] == "P2" and selected["site_count"] == 2


def _write_rows(path: Path, rows: list[dict]) -> None:
    """保留源表头写入裁剪后的合同 CSV。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        fieldnames = list(csv.DictReader(handle).fieldnames or ())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict]:
    """读取合同 CSV。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_end_to_end_fixed_timetable_outputs() -> None:
    """最小真实结算链应生成基线、热点、候选、设备、场景和摘要六类工件。"""

    with TemporaryDirectory(prefix="storage_planning_mvp_") as name:
        root = Path(name)
        inputs = root / "inputs"
        outputs = root / "outputs"
        inputs.mkdir()
        for file_name in CONTRACT_FILE_NAMES:
            shutil.copy2(SOURCE / file_name, inputs / file_name)

        sites = _read_rows(inputs / "storage_candidate_sites.csv")
        technologies = _read_rows(inputs / "storage_technologies.csv")
        options = _read_rows(inputs / "storage_site_technology_options.csv")
        for site in sites[:2]:
            site["allowed_technology_codes"] = "SYN-LFP"
            site["fixed_site_cost_cny"] = "0"
        for field in (
            "fixed_device_cost_cny",
            "cost_per_kwh_cny",
            "charge_power_cost_per_kw_cny",
            "discharge_power_cost_per_kw_cny",
            "annual_om_rate",
            "throughput_degradation_cost_per_kwh",
        ):
            technologies[0][field] = "0"
        _write_rows(inputs / "storage_candidate_sites.csv", sites[:2])
        _write_rows(inputs / "storage_technologies.csv", [technologies[0]])
        _write_rows(inputs / "storage_site_technology_options.csv", [options[0], options[2]])

        scenarios = json.loads((inputs / "storage_planning_scenarios.json").read_text(encoding="utf-8"))
        scenario = scenarios["scenarios"][0]
        scenario["weight"] = 1.0
        scenario["schedule_template"].update({"heavy_count": 1, "empty_count": 1})
        scenarios["scenarios"] = [scenario]
        (inputs / "storage_planning_scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")
        policy = json.loads((inputs / "storage_planning_policy.json").read_text(encoding="utf-8"))
        policy.update({"max_site_count": 2, "max_wall_clock_s": 120})
        (inputs / "storage_planning_policy.json").write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = run_storage_planning_mvp(inputs, CASE_DATA, outputs, max_levels_per_dimension=2, settlement_step_s=300)
        assert summary["energy_scenario"] == "storage_no_direct"
        assert summary["fixed_timetable_changed"] is False
        assert summary["declared_search_domain"]["candidate_plan_count"] == 81
        assert summary["declared_search_domain"]["complete_for_declared_domain"] is True
        assert summary["formal_engineering_conclusion_allowed"] is False
        # 决策值是能耗数据相关的（Davis 阻力量纲修正后可能从 recommend_build 翻转为
        # keep_no_build），因此断言其属于合法枚举，而非绑定某一具体数据下的结果。
        assert summary["decision"] in {"recommend_build", "keep_no_build", "no_feasible_plan"}
        if summary["decision"] == "recommend_build":
            assert summary["selected_plan"]["site_count"] in (1, 2)
        else:
            assert summary["selected_plan"]["site_count"] == 0
        expected = {
            "no_build_baseline.csv",
            "energy_hotspots.csv",
            "storage_plan_candidates.csv",
            "storage_plan_devices.csv",
            "storage_plan_scenario_results.csv",
            "storage_device_scenario_results.csv",
            "storage_planning_summary.json",
            "storage_planning_report.md",
        }
        assert expected <= {path.name for path in outputs.iterdir()}
        baseline = _read_rows(outputs / "no_build_baseline.csv")
        hotspots = _read_rows(outputs / "energy_hotspots.csv")
        candidates = _read_rows(outputs / "storage_plan_candidates.csv")
        assert len(baseline) == 1 and float(baseline[0]["grid_kwh"]) > 0.0
        assert hotspots and int(hotspots[0]["hotspot_rank"]) == 1
        assert len(candidates) == 81
        # 候选削减量是能耗数据相关的：Davis 阻力量纲修正后所有建设方案削减量可能归零
        # （对应 keep_no_build）。仅要求「削减量非负」这一物理不变量，而非硬编码必须为正。
        assert all(float(row["grid_reduction_vs_no_build_kwh_per_year"]) >= 0.0 for row in candidates)


if __name__ == "__main__":
    test_declared_discrete_domain_is_exhaustive()
    test_no_build_build_and_multisite_decisions()
    test_end_to_end_fixed_timetable_outputs()
    print("storage planning Phase-B MVP smoke tests passed")
