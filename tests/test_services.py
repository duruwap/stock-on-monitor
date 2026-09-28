import time
from datetime import date

import pytest

from stockonmonitor import meta
from stockonmonitor.core import transfer
from stockonmonitor.core.models import AppState, Holding, Quote, Settings, Snapshot
from stockonmonitor.platform import windows
from stockonmonitor.services import alerts, updater


# ── 알림 ─────────────────────────────────────────────────────
def test_target_alert_fires_once_per_day():
    h = Holding("005930", "KR", name="삼성전자", target_high=70000, target_low=60000)
    quotes = {h.key: Quote("005930", "KR", 71000, 70000)}
    state, settings = AppState(), Settings()
    first = alerts.evaluate([h], quotes, settings, state, today=date(2026, 9, 28))
    assert len(first) == 1 and "목표가" in first[0].title
    assert alerts.evaluate([h], quotes, settings, state, today=date(2026, 9, 28)) == []
    assert len(alerts.evaluate([h], quotes, settings, state, today=date(2026, 9, 29))) == 1


def test_move_alert_and_disabled_targets():
    h = Holding("AAPL", "US", name="애플", target_high=1)
    quotes = {h.key: Quote("AAPL", "US", 106, 100)}
    s = Settings(notify_targets=False, notify_move_pct=5)
    fired = alerts.evaluate([h], quotes, s, AppState(), today=date(2026, 9, 28))
    assert [a.title for a in fired] == ["애플 6.0% 상승"]


def test_old_alert_log_pruned():
    state = AppState(alert_log={"x:high": "2026-01-01", "y:low": "bad"})
    alerts.evaluate([], {}, Settings(), state, today=date(2026, 9, 28))
    assert state.alert_log == {}


# ── 업데이트 ─────────────────────────────────────────────────
def test_version_compare():
    assert updater.is_newer("2.0.1", "2.0.0")
    assert updater.is_newer("2.10.0", "2.9.9")
    assert not updater.is_newer("2.0.0", "2.0.0")
    assert not updater.is_newer("1.9", "2.0.0")


def test_manifest_validation():
    good = {"version": "2.1.0", "url": "https://x/y.exe", "sha256": "a" * 64}
    assert updater.parse_manifest(good).version == "2.1.0"
    for bad in ({**good, "url": "http://x/y.exe"}, {**good, "sha256": "zz"}, {"url": good["url"]}, []):
        with pytest.raises(ValueError):
            updater.parse_manifest(bad)


# ── 단축키 ───────────────────────────────────────────────────
def test_hotkey_parse():
    assert windows.parse_hotkey("Ctrl+Alt+H") == (windows.MOD_CONTROL | windows.MOD_ALT, ord("H"))
    assert windows.parse_hotkey("F9") == (0, 0x78)
    assert windows.parse_hotkey("Meta+Shift+1") == (windows.MOD_WIN | windows.MOD_SHIFT, ord("1"))
    assert windows.parse_hotkey("Shift+A") is None       # 일반 타이핑과 충돌
    assert windows.parse_hotkey("H") is None
    assert windows.parse_hotkey("Ctrl+Space") is None     # 지원하지 않는 키
    assert windows.parse_hotkey("") is None


# ── 가져오기/내보내기 ────────────────────────────────────────
def test_csv_roundtrip(tmp_path):
    hs = [Holding("005930", "KR", "삼성전자", "KOSPI", 62000, 120, target_high=80000),
          Holding("AAPL", "US", "애플", "NASDAQ", 182.5, 1.5, visible=False)]
    path = tmp_path / "out.csv"
    transfer.export_holdings(hs, path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # 엑셀용 BOM
    back = transfer.import_holdings(path)
    assert [(h.symbol, h.avg_price, h.quantity, h.visible, h.target_high) for h in back] == [
        ("005930", 62000, 120, True, 80000), ("AAPL", 182.5, 1.5, False, None)]
    assert back[0].id != hs[0].id


def test_json_roundtrip(tmp_path):
    path = tmp_path / "out.json"
    transfer.export_holdings([Holding("TSLA", "US", quantity=3, avg_price=200)], path)
    assert transfer.import_holdings(path)[0].symbol == "TSLA"


def test_import_v1_stocks_json(tmp_path):
    path = tmp_path / "stocks.json"
    path.write_text('[{"market":"KR","code":"055550","name":"신한지주","buy_price":13000.0,'
                    '"quantity":120,"active":false}]', encoding="utf-8")
    h = transfer.import_holdings(path)[0]
    assert (h.symbol, h.avg_price, h.quantity, h.visible) == ("055550", 13000, 120, False)


def test_import_cp949_csv(tmp_path):
    path = tmp_path / "k.csv"
    path.write_bytes("시장,종목코드,종목명,평균단가,수량\nKR,005930,삼성전자,\"60,000\",10\n".encode("cp949"))
    h = transfer.import_holdings(path)[0]
    assert h.name == "삼성전자" and h.avg_price == 60000


# ── 시세 서비스 (Qt 이벤트 루프) ─────────────────────────────
class FakeClient:
    def __init__(self):
        self.calls = 0

    def fetch_snapshot(self, holdings, need_fx):
        self.calls += 1
        from datetime import datetime

        if self.calls == 2:  # 두 번째는 실패 → 직전 시세 유지 확인
            return Snapshot({}, None, datetime.now(), [h.key for h in holdings], error="offline")
        return Snapshot({h.key: Quote(h.symbol, h.market, 100 + self.calls, 100) for h in holdings},
                        1300.0, datetime.now())


def test_quote_service_keeps_last_quotes_on_failure(qapp):
    from stockonmonitor.services.quote_service import QuoteService

    fake = FakeClient()
    svc = QuoteService(fake)
    got = []
    svc.snapshot_ready.connect(got.append)
    svc.set_holdings([Holding("005930", "KR")])
    assert fake.calls == 0  # 시작 전에는 조회하지 않음
    svc.start()
    deadline = time.time() + 5
    while len(got) < 1 and time.time() < deadline:
        qapp.processEvents()
    svc.refresh_now()
    while len(got) < 2 and time.time() < deadline:
        qapp.processEvents()
    svc.stop()
    assert len(got) == 2
    assert got[0].ok and got[0].quotes["KR:005930"].price == 101
    assert not got[1].ok and got[1].quotes["KR:005930"].price == 101


def test_meta_consistency():
    assert meta.APP_VERSION.count(".") == 2
    assert meta.INSTALLER_APP_GUID.startswith("{") and meta.INSTALLER_APP_GUID.endswith("}")
