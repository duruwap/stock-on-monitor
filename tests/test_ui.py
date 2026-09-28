"""UI 스모크 테스트: 화면 없이(offscreen) 위젯과 대화상자를 만들고 그려 본다."""

from datetime import datetime

from stockonmonitor.core.models import Holding, Quote, SearchResult, Settings
from stockonmonitor.core.valuation import build_positions, summarize


def _data():
    hs = [Holding("005930", "KR", "삼성전자", "KOSPI", 60000, 10), Holding("AAPL", "US", "애플", quantity=0)]
    qs = {"KR:005930": Quote("005930", "KR", 70000, 69000), "US:AAPL": Quote("AAPL", "US", 200, 201)}
    pos = build_positions(hs, qs)
    return pos, summarize(pos, 1300)


def test_widget_renders_all_variants(qapp):
    from stockonmonitor.ui.widget import FloatingWidget

    pos, summ = _data()
    for settings in (Settings(), Settings(change_unit="amount"), Settings(hide_amounts=True, color_scheme="mono"),
                     Settings(show_summary=False, theme="light")):
        w = FloatingWidget(settings)
        w.set_data(pos, summ, datetime.now(), 1300, None)
        img = w.grab()
        assert img.width() > 100 and img.height() > 20
        w.close()


def test_widget_columns_and_summary(qapp):
    from stockonmonitor.ui.widget import NCOLS, FloatingWidget

    pos, summ = _data()
    w = FloatingWidget(Settings())
    w.set_data(pos, summ, datetime.now(), 1300, None)
    assert all(len(r.cells) == NCOLS for r in w._rows)
    labels = [r.cells[0].text for r in w._rows if r.is_summary]
    assert labels == ["투자원금", "평가금액", "평가손익"]
    first = w._rows[0].cells
    assert [c.text for c in first] == ["삼성전자", "70,000", "+1.45%", "+16.67%"]
    assert first[0].color is None and first[1].color is None  # 이름·가격은 같은 기본 색


def test_widget_masks_amounts(qapp):
    from stockonmonitor.core.formatting import MASK
    from stockonmonitor.ui.widget import FloatingWidget

    pos, summ = _data()
    w = FloatingWidget(Settings(hide_amounts=True, change_unit="amount"))
    w.set_data(pos, summ, datetime.now(), 1300, None)
    texts = [c.text for r in w._rows for c in r.cells]
    assert MASK in texts
    assert "70,000" in texts  # 가격은 공개 정보라 그대로 표시
    assert not any("100,000" in t for t in texts)


def test_widget_size_does_not_jitter(qapp):
    """시세가 바뀌어도(자릿수가 줄어도) 위젯 크기는 변하지 않아야 한다."""
    from stockonmonitor.ui.widget import FloatingWidget

    hs = [Holding("005930", "KR", "삼성전자", "KOSPI", 60000, 10)]
    w = FloatingWidget(Settings())
    w.set_data(build_positions(hs, {}), None, None, None, None)          # 불러오는 중
    loading = w.size()
    sizes = set()
    for price in (99999, 101000, 71111, 9990, 100000):
        pos = build_positions(hs, {"KR:005930": Quote("005930", "KR", price, 70000)})
        w.set_data(pos, summarize(pos, None), datetime.now(), None, None)
        sizes.add((w.width(), w.height()))
    assert len(sizes) == 1
    assert loading.height() == w.height()   # 데이터 도착 전후 행 수 동일


def test_portfolio_dialog_add_and_save(qapp):
    from stockonmonitor.ui.portfolio_dialog import COL_AVG, COL_QTY, PortfolioDialog

    class Client:
        def search(self, q):
            return [SearchResult("000660", "KR", "SK하이닉스", "KOSPI")]

    dlg = PortfolioDialog([Holding("005930", "KR", "삼성전자")], Client())
    saved = []
    dlg.saved.connect(saved.append)
    dlg._on_search_done(dlg._search.run("sk"), Client().search("sk"), "")
    dlg._add_current_result()
    dlg.table.closePersistentEditor(dlg.table.item(1, COL_AVG))
    dlg.table.item(1, COL_AVG).setData(2, 150000.0)
    dlg.table.item(1, COL_QTY).setData(2, 3.0)
    dlg._save()
    assert [h.symbol for h in saved[0]] == ["005930", "000660"]
    assert saved[0][1].avg_price == 150000 and saved[0][1].quantity == 3


def test_settings_dialog_collects(qapp):
    from stockonmonitor.ui.settings_dialog import SettingsDialog

    got = []
    dlg = SettingsDialog(Settings(), data_dir="/tmp", log_dir="/tmp", hotkey_validator=lambda t: True,
                         on_open_folder=lambda p: None, on_check_update=None)
    dlg.applied.connect(lambda s, a: got.append(s))
    dlg.chk_hide_amounts.setChecked(True)
    dlg.cmb_unit.setCurrentIndex(dlg.cmb_unit.findData("amount"))
    dlg._save()
    assert got[0].hide_amounts and got[0].change_unit == "amount" and got[0].hotkey == "Ctrl+Alt+H"
