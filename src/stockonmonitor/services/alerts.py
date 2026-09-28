"""가격 알림 판정 (순수 로직).

같은 종목·같은 종류의 알림은 하루에 한 번만 보낸다. 기록은 AppState.alert_log에 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stockonmonitor.core import formatting as fmt
from stockonmonitor.core.models import AppState, Holding, Quote, Settings


@dataclass(frozen=True)
class Alert:
    title: str
    message: str


def evaluate(holdings: list[Holding], quotes: dict[str, Quote], settings: Settings, state: AppState,
             today: date | None = None) -> list[Alert]:
    today_s = (today or date.today()).isoformat()
    alerts: list[Alert] = []

    def once(key: str) -> bool:
        if state.alert_log.get(key) == today_s:
            return False
        state.alert_log[key] = today_s
        return True

    for h in holdings:
        q = quotes.get(h.key)
        if not q:
            continue
        price_text = fmt.price(q.price, h.currency)
        change_text = fmt.pct(q.change_pct)

        if settings.notify_targets:
            if h.target_high and q.price >= h.target_high and once(f"{h.id}:high"):
                alerts.append(Alert(f"{h.display_name} 목표가 도달",
                                    f"현재 {price_text} ({change_text}) · 목표 {fmt.price(h.target_high, h.currency)} 이상"))
            if h.target_low and q.price <= h.target_low and once(f"{h.id}:low"):
                alerts.append(Alert(f"{h.display_name} 하한가 도달",
                                    f"현재 {price_text} ({change_text}) · 기준 {fmt.price(h.target_low, h.currency)} 이하"))

        threshold = settings.notify_move_pct
        if threshold > 0 and abs(q.change_pct) >= threshold:
            kind = "up" if q.change_pct > 0 else "down"
            if once(f"{h.id}:move-{kind}"):
                word = "상승" if kind == "up" else "하락"
                alerts.append(Alert(f"{h.display_name} {abs(q.change_pct):.1f}% {word}",
                                    f"현재 {price_text} ({change_text})"))

    # 오래된 기록 정리 (7일 이상 지난 것)
    cutoff = date.fromisoformat(today_s).toordinal() - 7
    for key, day in list(state.alert_log.items()):
        try:
            if date.fromisoformat(day).toordinal() < cutoff:
                del state.alert_log[key]
        except ValueError:
            del state.alert_log[key]
    return alerts
