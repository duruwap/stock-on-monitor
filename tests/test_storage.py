import json

from stockonmonitor.core.models import Holding, Portfolio, Settings
from stockonmonitor.core.repository import Repository
from stockonmonitor.core.storage import JsonDocument
from stockonmonitor.paths import AppPaths


def _doc(tmp_path, **kw):
    return JsonDocument(tmp_path / "a.json", 2, lambda: {"x": 1}, backup_dir=tmp_path / "b", **kw)


def test_missing_file_returns_default(tmp_path):
    assert _doc(tmp_path).load() == {"x": 1, "schema_version": 2}


def test_atomic_save_roundtrip_and_no_temp_left(tmp_path):
    doc = _doc(tmp_path)
    doc.save({"x": 5, "한글": "값"})
    assert doc.load()["x"] == 5
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    assert len(list((tmp_path / "b").glob("a-*.json"))) == 1


def test_corrupt_file_is_quarantined_and_restored_from_backup(tmp_path):
    doc = _doc(tmp_path)
    doc.save({"x": 7})
    (tmp_path / "a.json").write_text("{broken", encoding="utf-8")
    doc2 = _doc(tmp_path)
    assert doc2.load()["x"] == 7
    assert doc2.recovered_from and doc2.recovered_from.startswith("a-")
    assert list(tmp_path.glob("a.json.corrupt-*"))


def test_corrupt_without_backup_falls_back_to_default(tmp_path):
    (tmp_path / "a.json").write_text("[1,2", encoding="utf-8")
    doc = _doc(tmp_path)
    assert doc.load()["x"] == 1
    assert doc.recovered_from == "default"


def test_migrations_run_in_order(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"schema_version": 1, "old": 3}), encoding="utf-8")
    doc = _doc(tmp_path, migrations={1: lambda d: {"schema_version": 1, "new": d["old"] * 2}})
    data = doc.load()
    assert data == {"schema_version": 2, "new": 6}


def test_backup_rotation(tmp_path):
    doc = _doc(tmp_path, keep_backups=2)
    for day in ("20260101", "20260102", "20260103"):
        (tmp_path / "b").mkdir(exist_ok=True)
        (tmp_path / "b" / f"a-{day}.json").write_text("{}", encoding="utf-8")
    doc.save({"x": 1})
    assert len(list((tmp_path / "b").glob("a-*.json"))) == 2


def test_repository_first_run_creates_files(tmp_path):
    paths = AppPaths(tmp_path / "data", "test")
    repo = Repository(paths)
    assert paths.settings_file.exists() and paths.portfolio_file.exists()
    repo.portfolio.holdings.append(Holding("005930", name="삼성전자", avg_price=1, quantity=1))
    repo.settings.font_size = 11
    repo.save_portfolio()
    repo.save_settings()
    repo2 = Repository(paths)
    assert repo2.portfolio.holdings[0].name == "삼성전자"
    assert repo2.settings.font_size == 11


def test_settings_from_dict_is_tolerant():
    s = Settings.from_dict({"font_size": "99", "theme": "neon", "idle_opacity": -5, "unknown": 1,
                            "refresh_seconds": "abc", "notify_move_pct": "3.25"})
    assert s.font_size == 16 and s.theme == "system" and s.idle_opacity == 20
    assert s.refresh_seconds == 10 and s.notify_move_pct == 3.2


def test_portfolio_skips_invalid_and_duplicate_ids():
    p = Portfolio.from_dict({"holdings": [
        {"symbol": "aapl", "market": "us", "id": "x"},
        {"symbol": "", "market": "KR"},
        "garbage",
        {"symbol": "MSFT", "market": "US", "id": "x"},
    ]})
    assert [h.symbol for h in p.holdings] == ["AAPL"]
    assert p.holdings[0].market == "US"
