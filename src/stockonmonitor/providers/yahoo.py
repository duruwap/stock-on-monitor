"""Yahoo Finance (해외 시세·환율·영문 검색, 국내 시세 대체 경로).

인증(crumb)이 필요 없는 chart/search 엔드포인트만 사용한다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from stockonmonitor.core.models import Quote, SearchResult
from stockonmonitor.providers.http import HttpError, get_json

HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
CHART = "/v8/finance/chart/{symbol}"
SEARCH = "/v1/finance/search"

US_EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
                "NYQ": "NYSE", "NYS": "NYSE", "ASE": "AMEX", "PCX": "NYSEARCA", "BTS": "BATS"}
KR_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ", "KONEX": ".KN"}

Fetch = Callable[..., Any]


def _get(path: str, params: dict | None, fetch: Fetch) -> Any:
    last: Exception = HttpError("조회 불가")
    for host in HOSTS:
        try:
            return fetch(host + path, params=params)
        except HttpError as exc:
            last = exc
    raise last


def parse_chart(data: Any, symbol: str, market: str, now: float | None = None) -> Quote:
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
    except (KeyError, IndexError, TypeError):
        err = (data or {}).get("chart", {}).get("error") if isinstance(data, dict) else None
        raise HttpError(f"야후 응답 형식 오류: {err or '결과 없음'}") from None

    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    if not price or not prev:
        raise HttpError("야후 응답에 가격 없음")

    session = ""
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    if period.get("start") and period.get("end"):
        now = now or time.time()
        session = "open" if period["start"] <= now < period["end"] else "closed"

    return Quote(
        symbol=symbol,
        market=market,
        price=float(price),
        prev_close=float(prev),
        name=str(meta.get("shortName") or meta.get("longName") or ""),
        session=session,
        source="yahoo",
    )


def fetch_chart(yahoo_symbol: str, symbol: str, market: str, fetch: Fetch = get_json) -> Quote:
    data = _get(CHART.format(symbol=yahoo_symbol), {"range": "1d", "interval": "1d"}, fetch)
    return parse_chart(data, symbol, market)


def fetch_us_quote(symbol: str, fetch: Fetch = get_json) -> Quote:
    return fetch_chart(symbol.replace(".", "-"), symbol, "US", fetch)


def fetch_kr_quote(code: str, exchange: str = "", fetch: Fetch = get_json) -> Quote:
    suffixes = [KR_SUFFIX[exchange]] if exchange in KR_SUFFIX else [".KS", ".KQ"]
    last: Exception = HttpError("조회 불가")
    for suffix in suffixes:
        try:
            return fetch_chart(code + suffix, code, "KR", fetch)
        except HttpError as exc:
            last = exc
    raise last


def fetch_usdkrw(fetch: Fetch = get_json) -> float:
    return fetch_chart("KRW=X", "USDKRW", "FX", fetch).price


def search(query: str, fetch: Fetch = get_json) -> list[SearchResult]:
    data = _get(SEARCH, {"q": query, "quotesCount": 10, "newsCount": 0, "listsCount": 0}, fetch)
    results = []
    for item in (data or {}).get("quotes", []) or []:
        if item.get("quoteType") not in ("EQUITY", "ETF"):
            continue
        symbol = str(item.get("symbol", "")).upper()
        exch = US_EXCHANGES.get(str(item.get("exchange", "")).upper())
        name = str(item.get("longname") or item.get("shortname") or symbol)
        if symbol.endswith((".KS", ".KQ")):
            results.append(SearchResult(symbol[:-3], "KR", name,
                                        "KOSPI" if symbol.endswith(".KS") else "KOSDAQ"))
        elif exch and "." not in symbol:
            results.append(SearchResult(symbol, "US", name, exch))
    return results
