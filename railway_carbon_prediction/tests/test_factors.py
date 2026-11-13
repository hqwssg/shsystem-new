import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carbon_prediction.factors import (FactorAmbiguous, FactorNotFound,
                                       FactorResolver, month_start)  # noqa: E402


def _factor(var_id, value, start, end=None, version=None, source="test"):
    return {
        "factor_id": f"{var_id}-{start}",
        "var_id": var_id,
        "factor_value": value,
        "factor_unit": "unit",
        "effective_from": start,
        "effective_to": end,
        "factor_version": version or f"EF-{var_id}-{start.year}",
        "factor_source": source,
        "is_caliber_change": 0,
        "policy_basis": None,
    }


def _rule(rule_id, org_id, value, start, end=None, version=None):
    return {
        "rule_id": rule_id,
        "org_id": org_id,
        "rule_type": "heat_area_factor",
        "rule_value": value,
        "unit": "GJ/m2",
        "effective_from": start,
        "effective_to": end,
        "rule_version": version or f"CAL-{org_id}-{start.year}",
        "source": "test",
        "note": None,
    }


def _resolver(factors, rules=None):
    rules = rules or []

    def fetch_all(sql, params=None):
        if "prediction_emission_factor" in sql:
            var_id, start, end = params
            return [r for r in factors if r["var_id"] == var_id
                    and r["effective_from"] <= start
                    and (r["effective_to"] is None or r["effective_to"] >= end)]
        if "prediction_caliber_rule" in sql:
            org_id, start, end = params
            return [r for r in rules if r["org_id"] in (org_id, "ALL")
                    and r["effective_from"] <= start
                    and (r["effective_to"] is None or r["effective_to"] >= end)]
        raise AssertionError(sql)

    return FactorResolver(fetch_all=fetch_all)


def test_month_start_normalizes():
    assert month_start("2025-06-18") == date(2025, 6, 1)
    assert month_start(date(2024, 2, 29)) == date(2024, 2, 1)


def test_resolve_factor_by_effective_date():
    factors = [
        _factor("ELEC_TOTAL", 0.5703, date(2022, 1, 1), date(2022, 12, 31)),
        _factor("ELEC_TOTAL", 0.5306, date(2025, 1, 1)),
    ]
    r = _resolver(factors)
    assert r.resolve_factor("ELEC_TOTAL", "JLG", "2022-06")["factor_value"] == pytest.approx(0.5703)
    assert r.resolve_factor("ELEC_TOTAL", "JLG", "2025-06")["factor_value"] == pytest.approx(0.5306)


def test_missing_factor_raises():
    with pytest.raises(FactorNotFound):
        _resolver([]).resolve_factor("GAS", "JLG", "2025-06")


def test_overlapping_factor_is_ambiguous():
    factors = [
        _factor("ELEC_TOTAL", 0.5306, date(2025, 1, 1)),
        _factor("ELEC_TOTAL", 0.5400, date(2025, 1, 1)),
    ]
    with pytest.raises(FactorAmbiguous):
        _resolver(factors).resolve_factor("ELEC_TOTAL", "JLG", "2025-06")


def test_heat_area_prefers_org_specific_over_all():
    rules = [
        _rule("ALL-HEAT", "ALL", 0.9224, date(2019, 1, 1)),
        _rule("SNF-HEAT-2025", "SNF", 0.3800, date(2025, 1, 1)),
        _rule("SNF-HEAT-2019", "SNF", 0.9224, date(2019, 1, 1), date(2024, 12, 31)),
    ]
    r = _resolver([], rules)
    assert r.resolve_heat_area("SNF", "2024-06")["rule_value"] == pytest.approx(0.9224)
    assert r.resolve_heat_area("SNF", "2025-06")["rule_value"] == pytest.approx(0.380)
    assert r.resolve_heat_area("JLG", "2025-06")["rule_value"] == pytest.approx(0.9224)


def test_resolve_all_complete_and_snapshot():
    factors = [
        _factor("GAS", 21.621732, date(2019, 1, 1)),
        _factor("GASOLINE", 3.042475, date(2019, 1, 1)),
        _factor("DIESEL", 3.145245, date(2019, 1, 1)),
        _factor("ELEC_TOTAL", 0.5306, date(2025, 1, 1), version="EF-ELEC-2025"),
        _factor("HEAT", 0.11, date(2019, 1, 1)),
    ]
    rules = [_rule("JLG-HEAT-2019", "JLG", 0.9224, date(2019, 1, 1))]
    result = _resolver(factors, rules).resolve_all("JLG", "2025-06")
    assert result["complete"] is True
    assert result["missing"] == []
    assert result["heat_area_factor"] == pytest.approx(0.9224)
    assert "EF-ELEC-2025" in result["factor_version"]
    assert "CAL-JLG-2019" in result["factor_version"]
    assert result["factor_snapshot"]["ELEC_TOTAL"]["factor_value"] == pytest.approx(0.5306)
    assert result["factor_snapshot"]["HEAT_AREA"]["rule_value"] == pytest.approx(0.9224)


def test_resolve_all_reports_missing():
    factors = [_factor("ELEC_TOTAL", 0.5306, date(2025, 1, 1))]
    result = _resolver(factors).resolve_all("JLG", "2025-06")
    assert result["complete"] is False
    assert "GAS" in result["missing"]
    assert result["factor_version"] != "legacy"
