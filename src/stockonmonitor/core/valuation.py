"""평가 금액·손익 계산. UI와 분리된 순수 함수."""

from __future__ import annotations

from dataclasses import dataclass

from stockonmonitor.core.models import Holding, Quote


@dataclass(frozen=True)
class Position:
    holding: Holding
    quote: Quote | None

    @property
    def has_quote(self) -> bool:
        return self.quote is not None

    @property
    def value(self) -> float | None:
        """평가 금액(현지 통화)"""
        if not self.quote or self.holding.quantity <= 0:
            return None
        return self.quote.price * self.holding.quantity

    @property
    def cost(self) -> float | None:
        if self.holding.is_watch_only:
            return None
        return self.holding.avg_price * self.holding.quantity

    @property
    def profit(self) -> float | None:
        if self.value is None or self.cost is None:
            return None
        return self.value - self.cost

    @property
    def profit_pct(self) -> float | None:
        if self.profit is None or not self.cost:
            return None
        return self.profit / self.cost * 100

    @property
    def day_change_value(self) -> float | None:
        """오늘 평가 금액 변동(현지 통화)"""
        if not self.quote or self.holding.quantity <= 0:
            return None
        return self.quote.change * self.holding.quantity


@dataclass(frozen=True)
class Summary:
    value_krw: float
    cost_krw: float
    day_change_krw: float
    priced_count: int          # 합계에 반영된 보유 종목 수
    missing_count: int         # 시세가 없어 빠진 보유 종목 수
    fx_missing: bool           # 미국 종목이 있는데 환율이 없어 제외됨

    @property
    def profit_krw(self) -> float:
        return self.value_krw - self.cost_krw

    @property
    def profit_pct(self) -> float | None:
        return self.profit_krw / self.cost_krw * 100 if self.cost_krw else None

    @property
    def day_change_pct(self) -> float | None:
        prev = self.value_krw - self.day_change_krw
        return self.day_change_krw / prev * 100 if prev else None

    @property
    def is_empty(self) -> bool:
        return self.priced_count == 0


def build_positions(holdings: list[Holding], quotes: dict[str, Quote]) -> list[Position]:
    return [Position(h, quotes.get(h.key)) for h in holdings]


def summarize(positions: list[Position], fx_usdkrw: float | None) -> Summary:
    value = cost = day = 0.0
    priced = missing = 0
    fx_missing = False
    for p in positions:
        if p.holding.is_watch_only:
            continue
        if p.value is None or p.cost is None:
            missing += 1
            continue
        rate = 1.0
        if p.holding.currency == "USD":
            if not fx_usdkrw:
                fx_missing = True
                missing += 1
                continue
            rate = fx_usdkrw
        value += p.value * rate
        cost += p.cost * rate
        day += (p.day_change_value or 0.0) * rate
        priced += 1
    return Summary(value, cost, day, priced, missing, fx_missing)
