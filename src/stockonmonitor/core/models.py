"""도메인 모델.

from_dict()는 관대하게 동작한다: 모르는 키는 무시하고, 타입이 틀리거나 범위를 벗어난 값은
기본값/경계값으로 바로잡는다. 사용자가 JSON을 직접 고쳐도 앱이 죽지 않게 하기 위함이다.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any, Literal

Market = Literal["KR", "US"]
MARKETS: tuple[str, ...] = ("KR", "US")
CURRENCY = {"KR": "KRW", "US": "USD"}


def _num(value: Any, default: float = 0.0, lo: float | None = None, hi: float | None = None) -> float:
    try:
        v = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _opt_num(value: Any) -> float | None:
    if value in (None, "", 0, 0.0):
        return None
    v = _num(value, default=0.0, lo=0.0)
    return v or None


def _choice(value: Any, options: tuple[str, ...], default: str) -> str:
    return value if value in options else default


# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────
THEMES = ("system", "dark", "light")
LAYOUTS = ("list", "ticker")
COLOR_SCHEMES = ("kr", "global", "mono")   # 빨강↑파랑↓ / 초록↑빨강↓ / 무채색
REFRESH_CHOICES = (5, 10, 30, 60)


@dataclass
class Settings:
    # 일반
    always_on_top: bool = True
    locked: bool = False
    refresh_seconds: int = 10
    hotkey: str = "Ctrl+Alt+H"              # 위젯 숨기기/보이기. 빈 문자열이면 사용 안 함

    # 표시
    theme: str = "system"
    layout: str = "list"
    font_size: int = 9
    idle_opacity: int = 70                  # 마우스를 올리지 않았을 때 불투명도(%)
    color_scheme: str = "kr"
    show_change_pct: bool = True
    show_change_amt: bool = False
    show_profit_pct: bool = True
    show_profit_amt: bool = False
    show_value: bool = False
    show_summary: bool = True
    ticker_seconds: int = 5

    # 개인정보·방해 금지
    hide_amounts: bool = False              # 금액 대신 •••, 비율(%)만 표시
    hide_in_capture: bool = True            # 화면 공유·캡처에서 제외 (Windows 10 2004+)
    hide_when_fullscreen: bool = True       # 전체 화면·프레젠테이션 중 자동 숨김

    # 알림
    notify_targets: bool = True             # 목표가 도달 알림
    notify_move_pct: float = 0.0            # 당일 등락률 ±N% 도달 시 알림 (0 = 끔)
    check_updates: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> Settings:
        s = cls()
        for f in fields(cls):
            if f.name in d:
                setattr(s, f.name, d[f.name])
        return s.normalized()

    def normalized(self) -> Settings:
        for name in ("always_on_top", "locked", "show_change_pct", "show_change_amt", "show_profit_pct",
                     "show_profit_amt", "show_value", "show_summary", "hide_amounts", "hide_in_capture",
                     "hide_when_fullscreen", "notify_targets", "check_updates"):
            setattr(self, name, bool(getattr(self, name)))
        self.refresh_seconds = int(_num(self.refresh_seconds, 10, 5, 600))
        self.hotkey = str(self.hotkey or "").strip()
        self.theme = _choice(self.theme, THEMES, "system")
        self.layout = _choice(self.layout, LAYOUTS, "list")
        self.font_size = int(_num(self.font_size, 9, 7, 16))
        self.idle_opacity = int(_num(self.idle_opacity, 70, 20, 100))
        self.color_scheme = _choice(self.color_scheme, COLOR_SCHEMES, "kr")
        self.ticker_seconds = int(_num(self.ticker_seconds, 5, 2, 60))
        self.notify_move_pct = round(_num(self.notify_move_pct, 0.0, 0.0, 30.0), 1)
        return self

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# 보유 종목
# ─────────────────────────────────────────────────────────────
@dataclass
class Holding:
    symbol: str                          # KR: 6자리 코드, US: 티커
    market: str = "KR"
    name: str = ""
    exchange: str = ""                   # KOSPI, KOSDAQ, NASDAQ, NYSE ...
    avg_price: float = 0.0               # 평균 매입 단가 (현지 통화)
    quantity: float = 0.0                # 0이면 관심 종목(손익 계산 제외)
    target_high: float | None = None     # 이 가격 이상이면 알림
    target_low: float | None = None      # 이 가격 이하이면 알림
    visible: bool = True                 # 위젯 표시 여부
    naver_code: str = ""                 # 네이버 해외 종목 코드(예: AAPL.O) — 대체 시세원 조회용
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}"

    @property
    def currency(self) -> str:
        return CURRENCY.get(self.market, "KRW")

    @property
    def is_watch_only(self) -> bool:
        return self.quantity <= 0 or self.avg_price <= 0

    @property
    def display_name(self) -> str:
        return self.name or self.symbol

    @classmethod
    def from_dict(cls, d: dict) -> Holding | None:
        symbol = str(d.get("symbol") or d.get("code") or "").strip().upper()
        if not symbol:
            return None
        market = _choice(str(d.get("market", "KR")).upper(), MARKETS, "KR")
        h = cls(
            symbol=symbol,
            market=market,
            name=str(d.get("name") or "").strip(),
            exchange=str(d.get("exchange") or "").strip().upper(),
            avg_price=_num(d.get("avg_price", d.get("buy_price", 0)), 0.0, 0.0),
            quantity=_num(d.get("quantity", 0), 0.0, 0.0),
            target_high=_opt_num(d.get("target_high")),
            target_low=_opt_num(d.get("target_low")),
            visible=bool(d.get("visible", d.get("active", True))),
            naver_code=str(d.get("naver_code") or "").strip(),
        )
        if d.get("id"):
            h.id = str(d["id"])
        return h

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Portfolio:
    holdings: list[Holding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Portfolio:
        items = d.get("holdings", [])
        holdings: list[Holding] = []
        seen: set[str] = set()
        for raw in items if isinstance(items, list) else []:
            if not isinstance(raw, dict):
                continue
            h = Holding.from_dict(raw)
            if h and h.id not in seen:
                seen.add(h.id)
                holdings.append(h)
        return cls(holdings)

    def to_dict(self) -> dict:
        return {"holdings": [h.to_dict() for h in self.holdings]}

    @property
    def visible(self) -> list[Holding]:
        return [h for h in self.holdings if h.visible]


# ─────────────────────────────────────────────────────────────
# 앱 상태 (사용자 설정이 아닌, 앱이 스스로 기억하는 값)
# ─────────────────────────────────────────────────────────────
@dataclass
class AppState:
    widget_pos: list[int] | None = None      # [x, y]
    widget_visible: bool = True
    first_run_done: bool = False
    last_fx_usdkrw: float | None = None
    last_update_check: float = 0.0           # epoch seconds
    notified_version: str = ""               # 이미 알린 업데이트 버전
    alert_log: dict[str, str] = field(default_factory=dict)  # "<holding id>:<kind>" → "YYYY-MM-DD"

    @classmethod
    def from_dict(cls, d: dict) -> AppState:
        s = cls()
        pos = d.get("widget_pos")
        if isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, (int, float)) for v in pos):
            s.widget_pos = [int(pos[0]), int(pos[1])]
        s.widget_visible = bool(d.get("widget_visible", True))
        s.first_run_done = bool(d.get("first_run_done", False))
        fx = _num(d.get("last_fx_usdkrw"), 0.0, 0.0)
        s.last_fx_usdkrw = fx or None
        s.last_update_check = _num(d.get("last_update_check"), 0.0, 0.0)
        s.notified_version = str(d.get("notified_version") or "")
        log_ = d.get("alert_log")
        if isinstance(log_, dict):
            s.alert_log = {str(k): str(v) for k, v in log_.items()}
        return s

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# 시세
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Quote:
    symbol: str
    market: str
    price: float
    prev_close: float
    name: str = ""
    session: str = ""        # "open" | "closed" | "" (알 수 없음)
    source: str = ""

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100) if self.prev_close else 0.0


@dataclass(frozen=True)
class SearchResult:
    symbol: str
    market: str
    name: str
    exchange: str = ""
    naver_code: str = ""

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}"


@dataclass
class Snapshot:
    quotes: dict[str, Quote]
    fx_usdkrw: float | None
    fetched_at: datetime
    failed: list[str] = field(default_factory=list)   # 조회 실패 종목 key
    error: str | None = None                          # 전체 실패 시 원인

    @property
    def ok(self) -> bool:
        return self.error is None
