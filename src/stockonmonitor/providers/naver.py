"""네이버 증권 (국내 실시간 시세·종목 검색, 해외 시세 대체 경로).

공개 문서가 없는 웹용 API이므로 응답 파싱을 최대한 관대하게 하고,
형식이 바뀌면 HttpError로 실패해 다른 시세원으로 넘어가도록 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from stockonmonitor.core.models import Quote, SearchResult
from stockonmonitor.providers.http import HttpError, get_json

log = logging.getLogger(__name__)

POLLING_DOMESTIC = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
POLLING_WORLD = "https://polling.finance.naver.com/api/realtime/worldstock/stock/{code}"
AUTOCOMPLETE = "https://ac.stock.naver.com/ac"

_FALLING = {"FALLING", "LOWER_LIMIT", "4", "5"}
_RISING = {"RISING", "UPPER_LIMIT", "1", "2"}
_US_SUFFIX_BY_EXCHANGE = {"NASDAQ": ".O", "NYSE": "", "AMEX": ".A", "NYSEARCA": ".K"}

Fetch = Callable[..., Any]


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        raise HttpError(f"숫자 형식 오류: {value!r}") from None


def _direction(item: dict) -> int:
    info = item.get("compareToPreviousPrice") or {}
    tokens = {str(info.get("name", "")).upper(), str(info.get("code", ""))}
    if tokens & _FALLING:
        return -1
    if tokens & _RISING:
        return 1
    return 0


def _session(item: dict) -> str:
    status = str(item.get("marketStatus", "")).upper()
    if status == "OPEN":
        return "open"
    if status in ("CLOSE", "CLOSED"):
        return "closed"
    return ""


def parse_polling_item(item: dict, market: str, symbol: str | None = None) -> Quote:
    price = _to_float(item.get("closePrice"))
    change = abs(_to_float(item.get("compareToPreviousClosePrice", 0)))
    direction = _direction(item)
    if direction == 0:
        # 방향 정보가 없으면 원래 부호를 신뢰
        change = _to_float(item.get("compareToPreviousClosePrice", 0))
    else:
        change *= direction
    if price <= 0:
        raise HttpError("가격이 0 이하")
    sym = symbol or str(item.get("itemCode") or item.get("symbolCode") or "").upper()
    return Quote(
        symbol=sym,
        market=market,
        price=price,
        prev_close=price - change,
        name=str(item.get("stockName") or ""),
        session=_session(item),
        source="naver",
    )


def fetch_kr_quotes(codes: list[str], fetch: Fetch = get_json) -> dict[str, Quote]:
    """국내 종목을 한 번의 요청으로 조회. 반환 키는 종목코드."""
    result: dict[str, Quote] = {}
    for start in range(0, len(codes), 40):  # URL 길이 제한 대비
        chunk = codes[start:start + 40]
        data = fetch(POLLING_DOMESTIC.format(codes=",".join(chunk)))
        for item in (data or {}).get("datas", []) or []:
            try:
                q = parse_polling_item(item, "KR")
            except HttpError as exc:
                log.debug("네이버 항목 파싱 실패: %s", exc)
                continue
            if q.symbol:
                result[q.symbol] = q
    return result


def naver_world_codes(symbol: str, exchange: str, known: str = "") -> list[str]:
    if known:
        return [known]
    suffix = _US_SUFFIX_BY_EXCHANGE.get(exchange.upper())
    if suffix is not None:
        return [symbol + suffix]
    return [symbol + ".O", symbol, symbol + ".K"]


def fetch_us_quote(symbol: str, exchange: str = "", naver_code: str = "", fetch: Fetch = get_json) -> Quote:
    last_error: Exception = HttpError("조회 불가")
    for code in naver_world_codes(symbol, exchange, naver_code):
        try:
            data = fetch(POLLING_WORLD.format(code=code))
            items = (data or {}).get("datas") or []
            if items:
                return parse_polling_item(items[0], "US", symbol=symbol)
        except HttpError as exc:
            last_error = exc
    raise last_error


def search(query: str, fetch: Fetch = get_json) -> list[SearchResult]:
    data = fetch(AUTOCOMPLETE, params={"q": query, "target": "stock"})
    results: list[SearchResult] = []
    for item in (data or {}).get("items", []) or []:
        if not isinstance(item, dict):
            continue
        nation = str(item.get("nationCode", "")).upper()
        code = str(item.get("code", "")).strip().upper()
        name = str(item.get("name", "")).strip()
        exchange = str(item.get("typeCode") or item.get("typeName") or "").upper()
        if not code or not name:
            continue
        if nation == "KOR":
            results.append(SearchResult(code, "KR", name, exchange))
        elif nation == "USA":
            results.append(SearchResult(code, "US", name, exchange, str(item.get("reutersCode") or "")))
    return results
