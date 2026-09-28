"""시세원 조합: 1차 시세원이 실패하면 대체 시세원으로 자동 전환한다.

  국내: 네이버(실시간, 일괄 조회) → 야후(.KS/.KQ)
  해외: 야후 → 네이버 해외
  환율: 야후(KRW=X)
  검색: 네이버 자동완성(국내·해외) + 야후 검색(영문) 병합
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TypeVar

from stockonmonitor.core.models import Holding, Quote, SearchResult, Snapshot
from stockonmonitor.providers import naver, yahoo
from stockonmonitor.providers.http import HttpError

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int = 4) -> list[tuple[T, R | Exception]]:
    """데몬 스레드로 병렬 실행. 앱 종료 시 네트워크 대기 때문에 종료가 지연되지 않는다."""
    items = list(items)
    if not items:
        return []
    jobs: queue.Queue = queue.Queue()
    for i, it in enumerate(items):
        jobs.put((i, it))
    out: list = [None] * len(items)

    def worker():
        while True:
            try:
                i, it = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                out[i] = (it, fn(it))
            except Exception as exc:  # 개별 실패는 결과로 돌려준다
                out[i] = (it, exc)

    threads = [threading.Thread(target=worker, daemon=True, name="quote-fetch")
               for _ in range(min(workers, len(items)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


class MarketDataClient:
    def fetch_snapshot(self, holdings: list[Holding], need_fx: bool) -> Snapshot:
        quotes: dict[str, Quote] = {}
        failed: list[str] = []
        errors: list[str] = []

        kr = [h for h in holdings if h.market == "KR"]
        us = [h for h in holdings if h.market == "US"]

        if kr:
            quotes.update(self._fetch_kr(kr, errors))
        if us:
            for h, res in parallel_map(self._fetch_us_one, us):
                if isinstance(res, Quote):
                    quotes[h.key] = res
                else:
                    errors.append(str(res))

        fx = None
        if need_fx:
            try:
                fx = yahoo.fetch_usdkrw()
            except HttpError as exc:
                errors.append(f"환율: {exc}")

        for h in holdings:
            if h.key not in quotes:
                failed.append(h.key)

        all_failed = holdings and len(failed) == len({h.key for h in holdings})
        error = errors[0] if all_failed and errors else None
        if errors:
            log.info("시세 조회 일부 실패: %s", "; ".join(dict.fromkeys(errors)))
        return Snapshot(quotes, fx, datetime.now(), failed, error)

    # ── 국내 ───────────────────────────────────────────────
    def _fetch_kr(self, holdings: list[Holding], errors: list[str]) -> dict[str, Quote]:
        codes = list(dict.fromkeys(h.symbol for h in holdings))
        found: dict[str, Quote] = {}
        try:
            found = naver.fetch_kr_quotes(codes)
        except HttpError as exc:
            errors.append(f"네이버: {exc}")

        missing = [h for h in holdings if h.symbol not in found]
        if missing:
            uniq = list({h.symbol: h for h in missing}.values())
            for h, res in parallel_map(lambda h: yahoo.fetch_kr_quote(h.symbol, h.exchange), uniq):
                if isinstance(res, Quote):
                    found[h.symbol] = res
                else:
                    errors.append(f"{h.symbol}: {res}")
        return {f"KR:{code}": q for code, q in found.items()}

    # ── 해외 ───────────────────────────────────────────────
    @staticmethod
    def _fetch_us_one(h: Holding) -> Quote:
        try:
            return yahoo.fetch_us_quote(h.symbol)
        except HttpError as first:
            try:
                return naver.fetch_us_quote(h.symbol, h.exchange, h.naver_code)
            except HttpError:
                raise first from None

    # ── 검색 ───────────────────────────────────────────────
    def search(self, query: str) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        sources: list[Callable[[str], list[SearchResult]]] = [naver.search]
        if re.search(r"[A-Za-z]", query):
            sources.append(yahoo.search)

        merged: dict[str, SearchResult] = {}
        errors = []
        for _, res in parallel_map(lambda fn: fn(query), sources):
            if isinstance(res, Exception):
                errors.append(res)
                continue
            for r in res:
                prev = merged.get(r.key)
                # 네이버 결과(한글명·해외 코드 포함)를 우선
                if prev is None or (not prev.naver_code and r.naver_code):
                    merged[r.key] = r

        # 6자리 숫자인데 검색 결과가 없으면 코드로 직접 확인
        if not merged and re.fullmatch(r"\d{6}", query):
            try:
                q = yahoo.fetch_kr_quote(query)
                merged[f"KR:{query}"] = SearchResult(query, "KR", q.name or query)
            except HttpError as exc:
                errors.append(exc)

        if not merged and errors:
            raise HttpError(str(errors[0]))

        results = list(merged.values())
        exact = query.upper()
        results.sort(key=lambda r: (r.symbol != exact and r.name != query, r.market != "KR"))
        return results[:15]
