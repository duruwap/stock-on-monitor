"""숫자 표시 형식."""

from __future__ import annotations

MASK = "•••"
DASH = "—"


def price(value: float | None, currency: str) -> str:
    if value is None:
        return DASH
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{value:,.0f}"


def signed_price(value: float | None, currency: str) -> str:
    if value is None:
        return DASH
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    body = f"{abs(value):,.2f}" if currency == "USD" else f"{abs(value):,.0f}"
    return f"{sign}{'$' if currency == 'USD' else ''}{body}"


def pct(value: float | None) -> str:
    if value is None:
        return DASH
    if abs(value) < 0.005:
        return "0.00%"
    return f"{value:+.2f}%"


def money(value: float | None, currency: str = "KRW", masked: bool = False) -> str:
    if masked:
        return MASK
    return price(value, currency)


def signed_money(value: float | None, currency: str = "KRW", masked: bool = False) -> str:
    if masked:
        return MASK
    return signed_price(value, currency)


def krw_compact(value: float | None, masked: bool = False) -> str:
    """합계 표시용: 1억 이상은 '1.23억' 식으로 짧게."""
    if masked:
        return MASK
    if value is None:
        return DASH
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e8:
        return f"{sign}{v / 1e8:,.2f}억"
    return f"{sign}{v:,.0f}"


def signed_krw_compact(value: float | None, masked: bool = False) -> str:
    if masked:
        return MASK
    if value is None:
        return DASH
    body = krw_compact(abs(value))
    if value > 0:
        return f"+{body}"
    if value < 0:
        return f"-{body}"
    return body


def arrow(value: float | None) -> str:
    if not value:
        return ""
    return "▲" if value > 0 else "▼"


def number_input(value: float | None, currency: str) -> str:
    """편집 칸 표시용 (쉼표 포함, 불필요한 소수점 제거)."""
    if value is None or value == 0:
        return ""
    if currency == "USD" or value != int(value):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{int(value):,}"
