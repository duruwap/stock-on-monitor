"""주기적 시세 갱신.

- 네트워크 작업은 백그라운드 스레드에서 수행 → UI가 절대 멈추지 않는다
- 이전 조회가 끝나기 전에는 새 조회를 시작하지 않는다
- 장이 닫힌 시간에는 5분 간격으로 조회 빈도를 낮춘다
- 연속 실패 시 간격을 점차 늘린다(최대 5분)
- 절전 모드에서 깨어나거나 네트워크가 복구되면 refresh_now()로 즉시 갱신
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from stockonmonitor.core import market_hours
from stockonmonitor.core.models import Holding, Snapshot
from stockonmonitor.providers.client import MarketDataClient

log = logging.getLogger(__name__)

IDLE_INTERVAL = 300
MAX_BACKOFF = 300


class QuoteService(QObject):
    snapshot_ready = Signal(object)   # Snapshot
    busy_changed = Signal(bool)
    _finished = Signal(object, int)   # 워커 스레드 → 메인 스레드 전달용

    def __init__(self, client: MarketDataClient | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._client = client or MarketDataClient()
        self._holdings: list[Holding] = []
        self._interval = 10
        self._failures = 0
        self._running = False
        self._pending = False         # 조회 중 새로고침 요청이 들어왔는지
        self._started = False
        self._generation = 0          # 종목이 바뀌면 이전 결과를 버리기 위한 세대 번호
        self._last_quotes: dict = {}
        self._last_session: dict[str, str] = {}

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_fetch)
        self._finished.connect(self._on_finished)

        # 절전 복귀 감지: 타이머가 예상보다 훨씬 늦게 울리면 즉시 갱신
        self._last_tick = time.monotonic()
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(15_000)
        self._watchdog.timeout.connect(self._check_resume)

    # ── 공개 API ────────────────────────────────────────────
    def start(self) -> None:
        self._started = True
        self._watchdog.start()
        self.refresh_now()

    def stop(self) -> None:
        self._started = False
        self._timer.stop()
        self._watchdog.stop()

    def set_holdings(self, holdings: list[Holding]) -> None:
        self._holdings = list(holdings)
        self._generation += 1
        self.refresh_now()

    def set_interval(self, seconds: int) -> None:
        self._interval = max(5, int(seconds))
        if self._started and not self._running:
            self._schedule()

    def refresh_now(self) -> None:
        if not self._started:
            return
        self._timer.stop()
        if self._running:
            self._pending = True   # 진행 중인 조회가 끝나면 곧바로 다시 조회
            return
        self._start_fetch()

    @property
    def is_busy(self) -> bool:
        return self._running

    # ── 내부 ────────────────────────────────────────────────
    def _check_resume(self) -> None:
        now = time.monotonic()
        gap = now - self._last_tick
        self._last_tick = now
        if gap > 60:
            log.info("장시간 중단(%.0f초) 후 복귀 — 즉시 갱신", gap)
            self.refresh_now()

    def _start_fetch(self) -> None:
        if self._running:
            self._pending = True
            return
        self._pending = False
        holdings = list(self._holdings)
        if not holdings:
            self.snapshot_ready.emit(Snapshot({}, None, _now(), []))
            self._schedule()
            return

        self._running = True
        self.busy_changed.emit(True)
        need_fx = any(h.market == "US" and not h.is_watch_only for h in holdings)
        generation = self._generation

        def work():
            try:
                snap = self._client.fetch_snapshot(holdings, need_fx)
            except Exception as exc:  # 예기치 못한 오류도 UI로 전달
                log.exception("시세 조회 중 예외")
                snap = Snapshot({}, None, _now(), [h.key for h in holdings], error=str(exc))
            self._finished.emit(snap, generation)

        threading.Thread(target=work, daemon=True, name="quote-cycle").start()

    def _on_finished(self, snap: Snapshot, generation: int) -> None:
        self._running = False
        self.busy_changed.emit(False)
        if generation != self._generation or self._pending:
            self._start_fetch()
            if generation != self._generation:
                return

        if snap.ok:
            self._failures = 0
        else:
            self._failures += 1
            log.warning("시세 조회 실패(%d회 연속): %s", self._failures, snap.error)

        # 이번에 실패한 종목은 직전 시세를 유지해 화면이 깜빡이지 않게 한다
        merged = dict(self._last_quotes)
        merged.update(snap.quotes)
        valid_keys = {h.key for h in self._holdings}
        self._last_quotes = {k: v for k, v in merged.items() if k in valid_keys}
        for q in snap.quotes.values():
            if q.session:
                self._last_session[q.market] = q.session

        self.snapshot_ready.emit(Snapshot(dict(self._last_quotes), snap.fx_usdkrw, snap.fetched_at,
                                          snap.failed, snap.error))
        if not self._running:  # 위에서 즉시 재조회를 시작했다면 예약하지 않는다
            self._schedule()

    def _markets_active(self) -> bool:
        markets = {h.market for h in self._holdings}
        for m in markets:
            if not market_hours.is_active_window(m):
                continue
            # 시세원이 '장 마감'이라고 알려준 경우(공휴일 등)는 정규장 시간 중이 아니면 쉬어도 된다
            if self._last_session.get(m) == "closed" and not market_hours.is_regular_session(m):
                continue
            return True
        return False

    def _schedule(self) -> None:
        if self._failures:
            delay = min(self._interval * (2 ** min(self._failures, 5)), MAX_BACKOFF)
        elif self._holdings and not self._markets_active():
            delay = IDLE_INTERVAL
        else:
            delay = self._interval
        self._timer.start(int(delay * 1000))


def _now() -> datetime:
    return datetime.now()
