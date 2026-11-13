"""第二轮规划算法：完整离散域、粗到细与小规模精确一致性。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storage_planning_contract import load_storage_planning_bundle
from storage_planning_mixed import build_storage_planning_mixed_inputs
from storage_planning_mvp import (
    _annualized_lifecycle_investment,
    enumerate_storage_plans,
    run_storage_planning_mvp,
)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _tiny_exact_case(inputs: Path) -> None:
    site_fields, sites = _read_csv(inputs / "storage_candidate_sites.csv")
    kept_site = sites[:1]
    kept_site[0]["fixed_site_cost_cny"] = "0"
    kept_site[0]["max_capacity_kwh"] = "20000"
    kept_site[0]["max_connection_power_kw"] = "10000"
    _write_csv(inputs / "storage_candidate_sites.csv", site_fields, kept_site)

    tech_fields, technologies = _read_csv(inputs / "storage_technologies.csv")
    tech = technologies[0]
    tech.update({
        "min_capacity_kwh": "10000", "max_capacity_kwh": "20000", "capacity_step_kwh": "5000",
        "min_charge_power_kw": "5000", "max_charge_power_kw": "10000", "charge_power_step_kw": "2500",
        "min_discharge_power_kw": "5000", "max_discharge_power_kw": "10000", "discharge_power_step_kw": "2500",
        "fixed_device_cost_cny": "0", "cost_per_kwh_cny": "0",
        "charge_power_cost_per_kw_cny": "0", "discharge_power_cost_per_kw_cny": "0",
        "annual_om_rate": "0", "throughput_degradation_cost_per_kwh": "0",
    })
    _write_csv(inputs / "storage_technologies.csv", tech_fields, [tech])

    option_fields, options = _read_csv(inputs / "storage_site_technology_options.csv")
    option = next(row for row in options if row["site_code"] == kept_site[0]["site_code"])
    option.update({
        "min_capacity_kwh": "10000", "max_capacity_kwh": "20000",
        "max_charge_power_kw": "10000", "max_discharge_power_kw": "10000",
    })
    _write_csv(inputs / "storage_site_technology_options.csv", option_fields, [option])

    scenario_path = inputs / "storage_planning_scenarios.json"
    scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
    nominal = scenarios["scenarios"][0]
    nominal["weight"] = 1.0
    nominal["storage_outage_site_codes"] = []
    scenarios["scenarios"] = [nominal]
    scenario_path.write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")

    policy_path = inputs / "storage_planning_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.update({
        "max_site_count": 1,
        "minimum_grid_reduction_kwh": 0,
        "minimum_annual_saving_cny": 0,
        "max_wall_clock_s": 180,
    })
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    with TemporaryDirectory(prefix="storage_round2_") as name:
        root = Path(name)
        inputs = root / "inputs"
        build_storage_planning_mixed_inputs(
            ROOT / "data" / "real_shuohuang",
            ROOT / "data_templates" / "running_diagram_template.xlsx",
            inputs,
        )
        _tiny_exact_case(inputs)
        bundle = load_storage_planning_bundle(inputs)
        coarse = enumerate_storage_plans(bundle, max_levels=2)
        exhaustive = enumerate_storage_plans(bundle, max_levels=None)
        assert len(coarse) == 9
        assert len(exhaustive) == 28
        probe_device = exhaustive[1][0]
        _annualized, lifecycle = _annualized_lifecycle_investment(
            (probe_device,),
            {item.site_code: item for item in bundle.sites},
            {item.technology_code: item for item in bundle.technologies},
            planning_horizon_years=12,
            discount_rate=0.06,
            annual_cycles_by_site={probe_device.site_code: 1000.0},
        )
        assert lifecycle[0]["effective_life_years"] == 6.0
        assert lifecycle[0]["replacement_count"] == 1
        assert lifecycle[0]["replacement_years"] == "6"

        exhaustive_result = run_storage_planning_mvp(
            inputs, ROOT / "data" / "real_shuohuang", root / "exhaustive",
            max_levels_per_dimension=2, settlement_step_s=300, search_mode="exhaustive",
        )
        refined_result = run_storage_planning_mvp(
            inputs, ROOT / "data" / "real_shuohuang", root / "refined",
            max_levels_per_dimension=2, settlement_step_s=300,
            search_mode="coarse_to_fine", refinement_shortlist_size=1,
        )
        assert exhaustive_result["declared_search_domain"]["original_step_domain_exhaustive"] is True
        assert exhaustive_result["declared_search_domain"]["evaluated_plan_count"] == 28
        assert refined_result["declared_search_domain"]["evaluated_plan_count"] == 28
        exact = exhaustive_result["selected_plan"]
        refined = refined_result["selected_plan"]
        for field in ("site_codes", "total_capacity_kwh", "total_charge_power_kw", "total_discharge_power_kw"):
            assert refined[field] == exact[field], (field, refined[field], exact[field])
        assert abs(refined["annual_total_cost_cny"] - exact["annual_total_cost_cny"]) < 1e-6
        assert refined["break_even_grid_price_cny_per_kwh"] is not None
        assert (root / "refined" / "storage_economic_sensitivity.csv").is_file()
    print("storage planning algorithm round-2 smoke: PASS")


if __name__ == "__main__":
    main()
