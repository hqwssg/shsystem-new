import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from carbon_prediction import monthly_source as source  # noqa: E402
from carbon_prediction.schemas import IngestRequest  # noqa: E402


def snapshot(org="SNF", version=4, kind=2, complete=True, values=None, heat=()):
    values = {"ELEC_TOTAL": 12} if values is None else values
    return IngestRequest(
        records=[dict(org_id=org, period="2026-01", var_id=var, value=value, unit=source.UNITS[var])
                 for var, value in values.items()],
        idempotency_key=f"carbon-month-{version}",
        source_snapshot=dict(version=version, org_id=org, period="2026-01", operation_type=kind,
                             complete=complete, heat_sources=list(heat)),
    )


def test_jlg_requires_all_electricity_and_balanced_total():
    _, missing = source._prepare(snapshot(org="JLG"))
    assert missing == {"electricity:incomplete"}
    values = {"ELEC_TOTAL": 12, "ELEC_TRAC": 8, "ELEC_AUX": 3}
    _, missing = source._prepare(snapshot(org="JLG", values=values))
    assert missing == {"electricity:not_closed"}
    values["ELEC_AUX"] = 4
    assert not source._prepare(snapshot(org="JLG", values=values))[1]
    with pytest.raises(ValueError, match="只提交总电"):
        source._prepare(snapshot(values=values))


def test_area_heat_requires_an_approved_company_rule(monkeypatch):
    heat = [dict(kind="measured", amount="8"), dict(kind="area", amount="10")]
    req = snapshot(heat=heat)
    monkeypatch.delenv("PREDICTION_MONTHLY_AREA_RULES_APPROVED", raising=False)
    rows, missing = source._prepare(req)
    assert missing == {"heat:missing_approved_rule"}
    assert "HEAT" not in rows
    monkeypatch.setenv("PREDICTION_MONTHLY_AREA_RULES_APPROVED", "true")
    monkeypatch.setattr(source, "FactorResolver", lambda: Mock(
        resolve_heat_area=Mock(return_value={"org_id": "SNF", "unit": "GJ/m2", "rule_value": "0.8"})
    ))
    rows, missing = source._prepare(req)
    assert not missing
    assert rows["HEAT_REPORTED"]["value"] == 16
    assert rows["HEAT"]["reported_value"] == 16
    assert rows["HEAT"]["value"] == pytest.approx(8 + 10 * source.settings.base_heat_area_factor)
    assert rows["HEAT"]["unit"] == "GJ"


def test_measured_heat_can_be_rebuilt_without_an_area_rule():
    rows, missing = source._prepare(snapshot(
        values={"HEAT_REPORTED": 9}, heat=[dict(kind="measured", amount="9")]))
    assert not missing
    assert rows["HEAT"]["value"] == rows["HEAT_REPORTED"]["value"] == 9


@pytest.fixture
def receiver(monkeypatch):
    head = dict(source_version=3, awaiting_source=0, batch_id=None)
    monkeypatch.setattr(source, "lock_month", Mock(return_value=head))
    monkeypatch.setattr(source.db, "fetch_one", Mock(return_value=None))
    monkeypatch.setattr(source.db, "execute", Mock())
    monkeypatch.setattr(source, "_write_records", Mock(return_value={"status": "completed", "batch_id": "NEW"}))
    for name in ("get_month_activity", "create_batch", "update_batch", "log"):
        monkeypatch.setattr(source.repository, name, Mock())
    source.repository.get_month_activity.return_value = []
    return head


def old_electricity(value=12):
    return [dict(var_id="ELEC_TOTAL", value=value, batch_id="OLD", quality_status="valid")]


def test_first_ingest_and_nightly_existing_skip(receiver):
    assert source._receive(snapshot(kind=1), {})["status"] == "completed"
    assert source._write_records.call_args.kwargs == dict(override=False, override_reason=None)
    source.repository.get_month_activity.return_value = old_electricity()
    source._write_records.reset_mock()
    assert source._receive(snapshot(kind=1), {}) == {"status": "skipped_existing"}
    source._write_records.assert_not_called()


def test_formal_same_values_or_change(receiver):
    source.repository.get_month_activity.return_value = old_electricity("12.000000")
    assert source._receive(snapshot(), {}) == {"status": "unchanged", "batch_id": "OLD"}
    source._write_records.assert_not_called()
    assert source._receive(snapshot(values={"ELEC_TOTAL": 13}), {})["status"] == "completed"
    assert source._write_records.call_args.kwargs == dict(override=True, override_reason=source.OVERRIDE_REASON)


def test_incomplete_month_staged_then_formal_same_values_release_source_review(receiver):
    source.repository.get_month_activity.return_value = old_electricity()
    req = snapshot(complete=False, values={})
    req.source_snapshot.missing = ["point:1:97:2"]
    staged = source._receive(req, {})
    assert staged["status"] == "pending_review"
    assert staged["missing"] == ["point:1:97:2"]
    assert source.db.execute.call_args_list[-2].args[1][:3] == (4, 1, staged["batch_id"])
    source._write_records.assert_not_called()
    receiver.update(source_version=4, awaiting_source=1, batch_id=staged["batch_id"])
    assert source._receive(snapshot(version=5), {})["status"] == "unchanged"
    assert source.db.execute.call_args_list[-2].args[1][:3] == (5, 0, "OLD")
    source.repository.update_batch.assert_called_once_with(
        staged["batch_id"], status="rejected", message="已由新的核算月度快照替代")


def test_lost_response_replay_uses_saved_receipt_without_rewriting(receiver):
    req = snapshot()
    result = source._receive(req, {})
    _, _, _, _, digest, _, response = source.db.execute.call_args.args[1]
    source.db.fetch_one.return_value = dict(request_hash=digest, response=response)
    receiver["source_version"] = 5
    assert source._receive(req, {}) == result
    source._write_records.assert_called_once()
    with pytest.raises(source.IdempotencyConflict):
        source._receive(snapshot(values={"ELEC_TOTAL": 13}), {})
    source.db.fetch_one.return_value = None
    assert source._receive(req, {}) == {"status": "superseded"}


def test_shared_transaction_rolls_back_on_receipt_failure(monkeypatch):
    conn = Mock()
    connect = Mock(return_value=conn)
    monkeypatch.setattr(source.db, "connect", connect)

    def fail_receipt(req, kwargs):
        with source.db.transaction() as nested, source.db.connection() as read:
            assert nested is read is conn
        raise RuntimeError("receipt failed")

    monkeypatch.setattr(source, "_receive", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt failed"):
        source.ingest(snapshot())
    connect.assert_called_once()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_called_once()


def test_model_queries_exclude_awaiting_source_months(monkeypatch):
    fetch_all = Mock(return_value=[])
    fetch_one = Mock(return_value={"p": date(2025, 12, 1)})
    monkeypatch.setattr(source.db, "fetch_all", fetch_all)
    monkeypatch.setattr(source.db, "fetch_one", fetch_one)
    source.repository.load_emission_series("SNF", valid_only=True)
    source.repository.load_activity_wide("SNF", valid_only=True)
    source.repository.latest_period("SNF")
    for call in (*fetch_all.call_args_list, *fetch_one.call_args_list):
        assert "NOT EXISTS" in call.args[0] and "h.awaiting_source=1" in call.args[0]
