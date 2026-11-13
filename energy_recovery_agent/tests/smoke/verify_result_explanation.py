"""方案解释必须保守展示，缺失证据不能被转换成现场采用许可。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from result_explanation import build_result_explanation
from tools.export_result_explanation import export_explanation


def main() -> int:
    source = {"valid": True}
    attribution = {"decision": {"action": "optimize", "reason": "material_energy_improvement_found",
                                "selected_candidate_id": "C001"},
                   "attribution_scope": {"dispatch_only_attribution_allowed": True}}
    arguments = dict(run_id="R001", run_status="succeeded", summary=source, attribution=attribution,
                     candidate_rows=[{"candidate_id": "C001", "feasible": "true"}])
    result = build_result_explanation(**arguments)
    assert result["decision"]["candidate_review_recommended"] is True
    assert result["production_dispatch_allowed"] is False
    assert result["data_confidence"]["formal_engineering_conclusion_allowed"] is False
    assert all(item["status"] == "unverified" for item in result["data_confidence"]["items"])
    for status in ("pending", "running", "failed", "cancelled", "unknown"):
        assert not build_result_explanation(**{**arguments, "run_status": status})["decision"]["candidate_review_recommended"]
    for invalid in (False, "false", "yes", None):
        assert not build_result_explanation(**{**arguments, "candidate_rows": [{"candidate_id": "C001", "feasible": invalid}]})["decision"]["candidate_review_recommended"]
    for flag in (False, "true", "false", None):
        assert not build_result_explanation(**{**arguments, "summary": {"valid": flag}})["decision"]["candidate_review_recommended"]
    assert not build_result_explanation(**{**arguments, "run_id": ""})["decision"]["candidate_review_recommended"]
    for flag in (False, "true", None):
        changed = {**attribution, "attribution_scope": {"dispatch_only_attribution_allowed": flag}}
        assert not build_result_explanation(**{**arguments, "attribution": changed})["decision"]["candidate_review_recommended"]
    for action in ("keep_baseline", "no_feasible_solution", "unknown"):
        changed = {**attribution, "decision": {"action": action, "reason": "no_material_energy_improvement"}}
        value = build_result_explanation(**{**arguments, "attribution": changed})
        assert not value["decision"]["candidate_review_recommended"]
        if action == "no_feasible_solution":
            assert "不等于已证明" in value["decision"]["explanation"]
    metrics = [{"benefit_direction": "lower", "metric_label": "购电", "baseline": 100, "optimized": 90,
                "improvement": 10, "unit": "kWh"},
               {"benefit_direction": "neutral", "metric_label": "SOC", "baseline": 0, "optimized": 40, "improvement": 40},
               {"benefit_direction": "lower", "baseline": "nan", "optimized": 90, "improvement": 10}]
    value = build_result_explanation(**arguments, metric_rows=metrics)
    assert len(value["improvements"]) == 1 and value["improvements"][0]["improvement"] == 10
    assert not value["adjustment_summary"]["departure_attribution_available"]
    zero_change = [{"dimension_type": "train", "dimension_id": "H001", "metric": "depart_time_s", "optimized_minus_baseline": "0"}]
    value = build_result_explanation(**arguments, dimension_rows=zero_change)
    assert value["adjustment_summary"]["departure_attribution_available"] and "未改变" in value["adjustment_summary"]["text"]
    value = build_result_explanation(**arguments, dimension_rows=[{**zero_change[0], "optimized_minus_baseline": "-60"}])
    assert "提前 60 秒" in value["adjustments"][0]["text"]
    changed = {**attribution, "top_bottlenecks": [{"scope": "baseline", "bottleneck_type": "storage_charge_power_or_capacity", "bottleneck_id": "battery_charge_limited_kwh", "blocking": False}]}
    value = build_result_explanation(**{**arguments, "attribution": changed})
    assert value["bottlenecks"][0]["scope_label"] == "原方案"
    assert value["bottlenecks"][0]["location_label"] == "受限未充入量"
    evidence = {"run_id": "R001", "data_status": "official", "formal_engineering_conclusion_allowed": True,
                "official_data_acceptance": True, "model_calibration": True, "result_audit": True,
                "deployment_acceptance": True,
                "items": {item["key"]: {"status": "confirmed"} for item in result["data_confidence"]["items"]}}
    assert build_result_explanation(**arguments, data_evidence=evidence)["data_confidence"]["formal_engineering_conclusion_allowed"]
    for wrong_id in (None, "R002", ""):
        assert not build_result_explanation(**arguments, data_evidence={**evidence, "run_id": wrong_id})["data_confidence"]["formal_engineering_conclusion_allowed"]
    changed = {**attribution, "decision": {**attribution["decision"], "reason": "unknown"}}
    assert not build_result_explanation(**{**arguments, "attribution": changed})["decision"]["candidate_review_recommended"]
    for key in ("official_data_acceptance", "model_calibration", "result_audit", "deployment_acceptance"):
        for flag in (False, "true", None):
            assert not build_result_explanation(**arguments, data_evidence={**evidence, key: flag})["data_confidence"]["formal_engineering_conclusion_allowed"]
    with TemporaryDirectory() as directory:
        path = Path(directory)
        summary_path = path / "summary.json"
        original = json.dumps(source)
        summary_path.write_text(original, encoding="utf-8")
        (path / "optimization_attribution_summary.json").write_text(json.dumps(attribution), encoding="utf-8")
        exported = export_explanation(path, path / "result_explanation.json", "R001", "unknown")
        assert not exported["decision"]["candidate_review_recommended"]
        assert summary_path.read_text(encoding="utf-8") == original
        try:
            export_explanation(path, summary_path, "R001", "succeeded")
        except ValueError:
            pass
        else:
            raise AssertionError("不得覆盖原始算法摘要")
    print("result explanation fail-closed display: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
