"""第三轮可信度：重优化敏感性、稳定区间和质量门禁回归。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storage_planning_credibility import (
    _stability_summary,
    audit_storage_planning_result,
    run_storage_planning_credibility,
)


def main() -> None:
    unstable = _stability_summary([
        {
            "decision": "keep_no_build", "selected_sites": "",
            "best_alternative_sites": "A", "best_alternative_capacity_kwh": 10,
            "best_alternative_charge_power_kw": 5, "best_alternative_discharge_power_kw": 5,
            "best_alternative_annual_saving_cny": -1,
        },
        {
            "decision": "recommend_build", "selected_sites": "B",
            "best_alternative_sites": "B", "best_alternative_capacity_kwh": 20,
            "best_alternative_charge_power_kw": 10, "best_alternative_discharge_power_kw": 10,
            "best_alternative_annual_saving_cny": 2,
        },
    ])
    assert unstable["stability_grade"] == "low"
    assert unstable["best_alternative_capacity_kwh_range"] == [10.0, 20.0]

    cases = (
        {"case_code": "base", "case_name": "基准"},
        {"case_code": "capex_low", "case_name": "投资降低30%", "storage_cost_factor": 0.7},
    )
    with TemporaryDirectory(prefix="storage_credibility_round3_") as name:
        output = Path(name)
        summary = run_storage_planning_credibility(
            ROOT / "data" / "real_shuohuang",
            ROOT / "data_templates" / "running_diagram_template.xlsx",
            output,
            cases=cases,
            settlement_step_s=300,
        )
        assert summary["case_count"] == 2
        assert summary["all_quality_gates_passed"] is True
        assert summary["formal_engineering_conclusion_allowed"] is False
        assert summary["stability"]["best_alternative_capacity_kwh_range"] is not None
        for filename in (
            "credibility_summary.json", "credibility_report.md",
            "sensitivity_runs.csv", "quality_gate_results.csv",
        ):
            assert (output / filename).is_file(), filename

        base_inputs = output / "case_inputs" / "base"
        base_results = output / "case_results" / "base"
        candidates_path = base_results / "storage_plan_candidates.csv"
        with candidates_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or ())
            rows = list(reader)
        rows.append(dict(rows[0]))
        with candidates_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        failed = audit_storage_planning_result(base_inputs, base_results)
        assert failed["passed"] is False
        assert "candidate_ids_unique" in failed["failed_gates"]
        assert "candidate_count_matches" in failed["failed_gates"]
    print("storage planning credibility round-3 smoke: PASS")


if __name__ == "__main__":
    main()
