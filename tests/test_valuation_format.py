from datetime import datetime, timezone

import pytest

from stockonmonitor.core import formatting as fmt
from stockonmonitor.core import market_hours as mh
from stockonmonitor.core.models import Holding, Quote
from stockonmonitor.core.valuation import build_positions, summarize


def test_position_and_summary_with_fx():
    holdings = [
        Holding("005930", "KR", avg_price=60000, quantity=10),
        Holding("AAPL", "US", avg_price=100, quantity=2),
        Holding("NVDA", "US"),  # 관심 종목: 합계 제외
    ]
    quotes = {
        "KR:005930": Quote("005930", "KR", 70000, 69000),
        "US:AAPL": Quote("AAPL", "US", 110, 100),
        "US:NVDA": Quote("NVDA", "US", 130, 131),
    }
    pos = build_positions(holdings, quotes)
    assert pos[0].profit == 100000 and pos[0].profit_pct == pytest.approx(16.6667, 1e-3)
    assert pos[2].profit is None

    s = summarize(pos, fx_usdkrw=1300)
    assert s.value_krw == 700000 + 220 * 1300
    assert s.cost_krw == 600000 + 200 * 1300
    assert s.day_change_krw == 10000 + 20 * 1300
    assert s.priced_count == 2 and s.missing_count == 0


def test_summary_excludes_usd_without_fx():
    holdings = [Holding("AAPL", "US", avg_price=100, quantity=2)]
    s = summarize(build_positions(holdings, {"US:AAPL": Quote("AAPL", "US", 110, 100)}), None)
    assert s.is_empty and s.fx_missing


def test_formatting():
    assert fmt.price(71200, "KRW") == "71,200"
    assert fmt.price(228.1, "USD") == "$228.10"
    assert fmt.signed_price(-1500, "KRW") == "-1,500"
    assert fmt.signed_price(1.5, "USD") == "+$1.50"
    assert fmt.pct(0.001) == "0.00%" and fmt.pct(1.234) == "+1.23%"
    assert fmt.money(100, masked=True) == fmt.MASK
    assert fmt.krw_compact(123_456_789) == "1.23억"
    assert fmt.signed_krw_compact(-2_000_000) == "-2,000,000"
    assert fmt.number_input(1234.5, "USD") == "1,234.5"
    assert fmt.number_input(60000, "KRW") == "60,000"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_kr_session():
    assert mh.is_regular_session("KR", utc(2026, 9, 28, 1, 0))       # 월 10:00 KST
    assert not mh.is_regular_session("KR", utc(2026, 9, 28, 7, 0))   # 16:00 KST
    assert not mh.is_regular_session("KR", utc(2026, 9, 27, 1, 0))   # 일요일
    assert mh.is_active_window("KR", utc(2026, 9, 28, 10, 0))        # 19:00 KST (NXT)


def test_us_dst_boundaries():
    assert mh.us_eastern_offset(utc(2026, 3, 8, 6, 59)).total_seconds() == -5 * 3600
    assert mh.us_eastern_offset(utc(2026, 3, 8, 7, 0)).total_seconds() == -4 * 3600
    assert mh.us_eastern_offset(utc(2026, 11, 1, 5, 59)).total_seconds() == -4 * 3600
    assert mh.us_eastern_offset(utc(2026, 11, 1, 6, 0)).total_seconds() == -5 * 3600


def test_us_session():
    assert mh.is_regular_session("US", utc(2026, 9, 28, 14, 0))       # 10:00 EDT
    assert not mh.is_regular_session("US", utc(2026, 9, 28, 20, 30))  # 16:30 EDT
    assert mh.is_regular_session("US", utc(2026, 12, 7, 15, 0))       # 10:00 EST
