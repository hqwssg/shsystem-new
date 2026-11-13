import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carbon_prediction.ingest_guard import payload_hash  # noqa: E402


def _records(value=1000):
    return [
        {"org_id": "JLG", "period": "2030-01", "var_id": "ELEC_TOTAL", "value": value, "unit": "MWh"},
        {"org_id": "JLG", "period": "2030-01", "var_id": "ELEC_TRAC", "value": value - 100, "unit": "MWh"},
        {"org_id": "JLG", "period": "2030-01", "var_id": "ELEC_AUX", "value": 100, "unit": "MWh"},
    ]


def test_payload_hash_is_order_insensitive():
    a = payload_hash(_records(), operator="tester")
    b = payload_hash(list(reversed(_records())), operator="tester")
    assert a == b
    assert len(a) == 64


def test_payload_hash_changes_with_value_or_override():
    base = payload_hash(_records(), operator="tester")
    assert payload_hash(_records(1100), operator="tester") != base
    assert payload_hash(_records(), operator="tester", override=True) != base
    assert payload_hash(_records(), operator="other") != base
