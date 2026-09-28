import pytest

from conftest import load_fixture
from stockonmonitor.core.models import Holding, Quote
from stockonmonitor.providers import client as client_mod
from stockonmonitor.providers import naver, yahoo
from stockonmonitor.providers.http import HttpError


def test_naver_domestic_parsing():
    quotes = naver.fetch_kr_quotes(["005930", "000660", "035720"],
                                   fetch=lambda url, **kw: load_fixture("naver_domestic.json"))
    s = quotes["005930"]
    assert s.price == 71200 and s.prev_close == 70500 and s.session == "open"
    h = quotes["000660"]
    assert h.change == -1500 and h.change_pct == pytest.approx(-0.7009, 1e-3)
    assert quotes["035720"].change == 0 and quotes["035720"].session == "closed"


def test_naver_direction_overrides_unsigned_change():
    item = {"itemCode": "1", "closePrice": "100", "compareToPreviousClosePrice": "5",
            "compareToPreviousPrice": {"name": "FALLING"}}
    assert naver.parse_polling_item(item, "KR").prev_close == 105


def test_naver_world_parsing_and_code_candidates():
    q = naver.fetch_us_quote("AAPL", "NASDAQ", fetch=lambda url, **kw: load_fixture("naver_world.json"))
    assert q.symbol == "AAPL" and q.price == pytest.approx(228.12) and q.prev_close == pytest.approx(226.40)
    assert naver.naver_world_codes("IBM", "NYSE") == ["IBM"]
    assert naver.naver_world_codes("X", "", "X.K") == ["X.K"]


def test_naver_search_filters_nations():
    results = naver.search("삼성", fetch=lambda url, **kw: load_fixture("naver_ac.json"))
    assert [(r.market, r.symbol) for r in results] == [("KR", "005930"), ("KR", "005935"), ("US", "AAPL")]
    assert results[2].naver_code == "AAPL.O"


def test_yahoo_chart_parsing():
    data = load_fixture("yahoo_chart.json")
    q = yahoo.parse_chart(data, "AAPL", "US", now=1790020000)
    assert q.price == 228.12 and q.prev_close == 226.4 and q.session == "open"
    assert yahoo.parse_chart(data, "AAPL", "US", now=1790050000).session == "closed"
    with pytest.raises(HttpError):
        yahoo.parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}}, "X", "US")


def test_yahoo_host_failover():
    calls = []

    def fetch(url, **kw):
        calls.append(url)
        if "query1" in url:
            raise HttpError("down")
        return load_fixture("yahoo_chart.json")

    assert yahoo.fetch_us_quote("AAPL", fetch=fetch).price == 228.12
    assert len(calls) == 2


def test_yahoo_kr_tries_kosdaq_suffix():
    seen = []

    def fetch(url, **kw):
        seen.append(url)
        if ".KS" in url:
            raise HttpError("404")
        return load_fixture("yahoo_chart.json")

    q = yahoo.fetch_kr_quote("247540", fetch=fetch)
    assert q.market == "KR" and q.symbol == "247540"
    assert any(".KQ" in u for u in seen)


def test_yahoo_search_filters():
    results = yahoo.search("apple", fetch=lambda url, **kw: load_fixture("yahoo_search.json"))
    assert [(r.market, r.symbol, r.exchange) for r in results] == [
        ("US", "AAPL", "NASDAQ"), ("US", "BRK-B", "NYSE"), ("KR", "005930", "KOSPI")]


def test_client_falls_back_when_naver_fails(monkeypatch):
    monkeypatch.setattr(naver, "fetch_kr_quotes", lambda codes: (_ for _ in ()).throw(HttpError("blocked")))
    monkeypatch.setattr(yahoo, "fetch_kr_quote", lambda code, exch="": Quote(code, "KR", 100, 90, source="yahoo"))
    monkeypatch.setattr(yahoo, "fetch_us_quote", lambda s: (_ for _ in ()).throw(HttpError("429")))
    monkeypatch.setattr(naver, "fetch_us_quote", lambda s, e="", c="": Quote(s, "US", 10, 9, source="naver"))
    monkeypatch.setattr(yahoo, "fetch_usdkrw", lambda: 1350.0)

    snap = client_mod.MarketDataClient().fetch_snapshot(
        [Holding("005930", "KR"), Holding("AAPL", "US", avg_price=1, quantity=1)], need_fx=True)
    assert snap.ok and not snap.failed
    assert snap.quotes["KR:005930"].source == "yahoo"
    assert snap.quotes["US:AAPL"].source == "naver"
    assert snap.fx_usdkrw == 1350.0


def test_client_reports_total_failure(monkeypatch):
    def boom(*a, **k):
        raise HttpError("offline")

    for mod, name in ((naver, "fetch_kr_quotes"), (yahoo, "fetch_kr_quote")):
        monkeypatch.setattr(mod, name, boom)
    snap = client_mod.MarketDataClient().fetch_snapshot([Holding("005930", "KR")], need_fx=False)
    assert not snap.ok and snap.failed == ["KR:005930"]


def test_client_search_merges_and_prefers_exact(monkeypatch):
    from stockonmonitor.core.models import SearchResult

    monkeypatch.setattr(naver, "search", lambda q: [SearchResult("AAPL", "US", "애플", "NASDAQ", "AAPL.O")])
    monkeypatch.setattr(yahoo, "search", lambda q: [SearchResult("AAPLX", "US", "Other", "NASDAQ"),
                                                    SearchResult("AAPL", "US", "Apple Inc.", "NASDAQ")])
    results = client_mod.MarketDataClient().search("aapl")
    assert results[0].symbol == "AAPL" and results[0].name == "애플"
    assert len(results) == 2


def test_parallel_map_returns_exceptions():
    out = client_mod.parallel_map(lambda x: 10 // x, [1, 0, 5])
    assert out[0] == (1, 10) and isinstance(out[1][1], ZeroDivisionError) and out[2] == (5, 2)
