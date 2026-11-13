import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carbon_prediction import repository  # noqa: E402


def test_dataset_version_reuses_matching_content(monkeypatch):
    monkeypatch.setattr(repository.db, "fetch_one", lambda *_: {"version_id": "DV-EXISTING"})
    monkeypatch.setattr(
        repository.db,
        "execute",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not insert a duplicate version")),
    )

    version = repository.save_dataset_version(
        "JLG", date(2019, 1, 1), date(2025, 12, 1), 84, "period,value\n"
    )

    assert version == "DV-EXISTING"


def test_dataset_version_inserts_new_content(monkeypatch):
    calls = []
    monkeypatch.setattr(repository.db, "fetch_one", lambda *_: None)
    monkeypatch.setattr(repository.db, "execute", lambda sql, params: calls.append((sql, params)))

    version = repository.save_dataset_version(
        "SNF", date(2019, 1, 1), date(2025, 12, 1), 84, "period,value\n"
    )

    assert version.startswith("DV-SNF-202512-")
    assert len(calls) == 1
    assert calls[0][1][0] == version
