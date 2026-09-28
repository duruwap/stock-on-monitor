"""바탕화면 플로팅 위젯.

구성 (열은 고정):
    종목명        현재가     전일 대비    평단 대비
    ─────────────────────────────────────────────
    투자원금   16,420,000
    평가금액   18,236,196      +0.52%
    평가손익   +1,816,196                 +11.06%

디자인 규칙
- 글자는 모두 같은 색·같은 굵기. 색이 달라지는 것은 변동 값(상승/하락)뿐이다.
- 크기가 흔들리지 않는다: 열 폭은 '넓어지기만' 하고(숫자가 바뀌어도 줄지 않음),
  종목·설정이 바뀔 때만 다시 계산한다. 행 수는 데이터 도착 전후로 같다.

동작
- 평소에는 설정한 불투명도로 옅게, 마우스를 올리면 선명하게
- 드래그로 이동, 화면 가장자리에 자석처럼 붙음, 붙은 모서리를 기준으로 크기가 변함
- 더블클릭: 종목 관리 / 오른쪽 클릭: 메뉴 / 행 위에 머무르면 상세 툴팁
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from stockonmonitor.core import formatting as fmt
from stockonmonitor.core.models import Settings
from stockonmonitor.core.valuation import Position, Summary
from stockonmonitor.platform import windows
from stockonmonitor.ui import theme

SNAP_DISTANCE = 14
SCREEN_MARGIN = 12
NCOLS = 4                     # 종목명 · 현재가 · 전일 대비 · 평단 대비
EMPTY_TEXT = "더블클릭해서 종목 추가"
_DIGITS = re.compile(r"\d")

LEFT = Qt.AlignmentFlag.AlignLeft
RIGHT = Qt.AlignmentFlag.AlignRight


@dataclass
class Cell:
    text: str = ""
    color: QColor | None = None     # None이면 기본 글자색
    align: Qt.AlignmentFlag = RIGHT


@dataclass
class Row:
    cells: list[Cell]
    tooltip: str = ""
    is_summary: bool = False


class FloatingWidget(QWidget):
    context_menu_requested = Signal(QPoint)
    open_portfolio_requested = Signal()
    position_changed = Signal(QPoint)

    def __init__(self, settings: Settings) -> None:
        super().__init__(None)
        self.setObjectName("floating-widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("StockOnMonitor")

        self._settings = settings
        self._positions: list[Position] = []
        self._summary: Summary | None = None
        self._fetched_at: datetime | None = None
        self._offline_reason: str | None = None
        self._fx: float | None = None
        self._rows: list[Row] = []
        self._widths = [0] * NCOLS
        self._structure: tuple = ()
        self._hovered = False
        self._drag_offset: QPoint | None = None
        self._dragged = False

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._leave_timer = QTimer(self, singleShot=True, interval=350, timeout=self._fade_out)

        self._apply_window_flags()
        self.apply_settings(settings)

    # ── 설정 ───────────────────────────────────────────────
    def _apply_window_flags(self) -> None:
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        if self._settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def apply_settings(self, settings: Settings) -> None:
        on_top_changed = settings.always_on_top != self._settings.always_on_top
        self._settings = settings
        if on_top_changed:
            was_visible = self.isVisible()
            pos = self.pos()
            self._apply_window_flags()   # 네이티브 창이 다시 만들어지므로 다시 표시
            self.move(pos)
            if was_visible:
                self.show()
        self._tokens = theme.widget_tokens(theme.resolve_dark(settings.theme), settings.color_scheme)
        self._font = theme.ui_font(settings.font_size)
        self._fm = QFontMetrics(self._font)
        if not self._hovered:
            self.setWindowOpacity(settings.idle_opacity / 100)
        self._apply_capture_exclusion()
        self._rebuild()

    def _apply_capture_exclusion(self) -> None:
        if self.isVisible():
            windows.set_exclude_from_capture(int(self.winId()), self._settings.hide_in_capture)

    # ── 데이터 ─────────────────────────────────────────────
    def set_data(self, positions: list[Position], summary: Summary | None, fetched_at: datetime | None,
                 fx: float | None, offline_reason: str | None) -> None:
        self._positions = positions
        self._summary = summary
        self._fetched_at = fetched_at
        self._fx = fx
        self._offline_reason = offline_reason
        self._rebuild()

    @property
    def _has_holdings(self) -> bool:
        return any(not p.holding.is_watch_only for p in self._positions)

    # ── 행 구성 ────────────────────────────────────────────
    def _change_color(self, value: float | None) -> QColor | None:
        if not value:
            return None
        return self._tokens.up if value > 0 else self._tokens.down

    def _pct(self, value: float | None) -> str:
        if value is None:
            return ""
        text = fmt.pct(value)
        if self._settings.color_scheme == "mono" and abs(value) >= 0.005:
            return f"{fmt.arrow(value)}{text.lstrip('+-')}"
        return text

    def _placeholder(self) -> Cell:
        return Cell(fmt.DASH, self._tokens.text_dim)

    def _build_rows(self) -> list[Row]:
        s = self._settings
        masked, by_amount = s.hide_amounts, s.change_unit == "amount"
        rows: list[Row] = []

        for p in self._positions:
            h, q = p.holding, p.quote
            name = Cell(h.display_name, align=LEFT)
            if q is None:
                rows.append(Row([name, self._placeholder(), Cell(), Cell()], self._tooltip(p)))
                continue
            day = (Cell(fmt.signed_price(q.change, h.currency), self._change_color(q.change)) if by_amount
                   else Cell(self._pct(q.change_pct), self._change_color(q.change)))
            if p.profit is None:
                pl = Cell()
            elif by_amount:
                pl = Cell(fmt.signed_money(p.profit, h.currency, masked), self._change_color(p.profit))
            else:
                pl = Cell(self._pct(p.profit_pct), self._change_color(p.profit))
            rows.append(Row([name, Cell(fmt.price(q.price, h.currency)), day, pl], self._tooltip(p)))

        if s.show_summary and self._has_holdings:
            rows.extend(self._summary_rows())
        return rows

    def _summary_rows(self) -> list[Row]:
        s, sm = self._settings, self._summary
        masked = s.hide_amounts
        tip = self._summary_tooltip()
        if sm is None or sm.is_empty:
            return [Row([Cell(label, align=LEFT), self._placeholder(), Cell(), Cell()], tip, True)
                    for label in ("투자원금", "평가금액", "평가손익")]

        day_color = self._change_color(sm.day_change_krw)
        pl_color = self._change_color(sm.profit_krw)
        day = (fmt.signed_krw_compact(sm.day_change_krw, masked) if s.change_unit == "amount"
               else self._pct(sm.day_change_pct))
        return [
            Row([Cell("투자원금", align=LEFT), Cell(fmt.krw_compact(sm.cost_krw, masked)), Cell(), Cell()],
                tip, True),
            Row([Cell("평가금액", align=LEFT), Cell(fmt.krw_compact(sm.value_krw, masked)),
                 Cell(day, day_color), Cell()], tip, True),
            Row([Cell("평가손익", align=LEFT), Cell(fmt.signed_krw_compact(sm.profit_krw, masked), pl_color),
                 Cell(), Cell(self._pct(sm.profit_pct), pl_color)], tip, True),
        ]

    # ── 툴팁 ───────────────────────────────────────────────
    def _tooltip(self, p: Position) -> str:
        h, q, masked = p.holding, p.quote, self._settings.hide_amounts
        lines = [f"<b>{h.display_name}</b>&nbsp; <span style='color:gray'>{h.symbol} · {h.exchange or h.market}</span>"]
        if q:
            lines.append(f"현재가 {fmt.price(q.price, h.currency)}")
            lines.append(f"전일 대비 {fmt.signed_price(q.change, h.currency)} ({fmt.pct(q.change_pct)})")
        else:
            lines.append("시세를 불러오지 못했습니다")
        if h.is_watch_only:
            lines.append("<span style='color:gray'>관심 종목</span>")
        else:
            qty = fmt.MASK if masked else f"{h.quantity:,.10g}"
            lines.append(f"평단가 {fmt.price(h.avg_price, h.currency)} · {qty}주")
            if p.profit is not None:
                lines.append(f"평단 대비 {fmt.signed_money(p.profit, h.currency, masked)} ({fmt.pct(p.profit_pct)})")
        targets = []
        if h.target_high:
            targets.append(f"↑ {fmt.price(h.target_high, h.currency)}")
        if h.target_low:
            targets.append(f"↓ {fmt.price(h.target_low, h.currency)}")
        if targets:
            lines.append("알림 " + "  ".join(targets))
        return "<br>".join(lines)

    def _summary_tooltip(self) -> str:
        sm, masked = self._summary, self._settings.hide_amounts
        if sm is None or sm.is_empty:
            return "합계 (원화 환산)"
        lines = ["<b>합계 (원화 환산)</b>",
                 f"투자원금 {fmt.money(sm.cost_krw, masked=masked)}",
                 f"평가금액 {fmt.money(sm.value_krw, masked=masked)}",
                 f"평가손익 {fmt.signed_money(sm.profit_krw, masked=masked)} ({fmt.pct(sm.profit_pct)})",
                 f"오늘 변동 {fmt.signed_money(sm.day_change_krw, masked=masked)} ({fmt.pct(sm.day_change_pct)})"]
        if self._fx:
            lines.append(f"<span style='color:gray'>환율 USD/KRW {self._fx:,.2f}</span>")
        if sm.missing_count:
            lines.append(f"<span style='color:gray'>시세 없음 {sm.missing_count}종목 제외</span>")
        return "<br>".join(lines)

    def _status_tooltip(self) -> str:
        parts = []
        if self._offline_reason:
            parts.append("시세 서버에 연결하지 못해 마지막 값을 표시 중입니다")
        if self._fetched_at:
            parts.append(f"마지막 갱신 {self._fetched_at:%H:%M:%S}")
        return "<br>".join(parts)

    # ── 레이아웃 ───────────────────────────────────────────
    def _metrics(self) -> tuple[int, int, int, int, int]:
        """(행 높이, 좌우 여백, 위아래 여백, 열 간격, 합계 구분 간격)"""
        h = self._fm.height()
        return int(h * 1.6), max(12, int(h * 0.9)), max(7, int(h * 0.45)), max(12, int(h * 1.1)), max(6, h // 2)

    def _measure(self, text: str) -> int:
        # 숫자는 모두 '0' 폭으로 계산 → 값이 바뀌어도 폭이 흔들리지 않음
        return self._fm.horizontalAdvance(_DIGITS.sub("0", text)) + 1

    def _minimum_widths(self) -> list[int]:
        s = self._settings
        has_usd = any(p.holding.currency == "USD" for p in self._positions)
        price_sample = "$0,000.00" if has_usd else "000,000"
        change_sample = "+0,000,000" if s.change_unit == "amount" else "+00.00%"
        widths = [self._measure("가나다라"), self._measure(price_sample),
                  self._measure(change_sample), self._measure(change_sample)]
        if s.show_summary and self._has_holdings:
            widths[1] = max(widths[1], self._measure("00,000,000"))
        return widths

    def _rebuild(self) -> None:
        self._rows = self._build_rows()
        s = self._settings
        structure = (tuple(p.holding.key for p in self._positions), s.change_unit, s.hide_amounts,
                     s.show_summary, s.font_size, s.color_scheme, self._has_holdings)
        if structure != self._structure:
            self._structure = structure
            self._widths = self._minimum_widths()   # 구성이 바뀔 때만 폭을 새로 잡는다

        max_name = self._fm.horizontalAdvance("가") * 7
        for row in self._rows:
            for i, cell in enumerate(row.cells):
                w = self._measure(cell.text) if cell.text else 0
                if i == 0:
                    w = min(w + 2, max_name)
                self._widths[i] = max(self._widths[i], w)   # 넓어지기만 한다
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        row_h, pad_x, pad_y, gap, sep = self._metrics()
        if not self._rows:
            self._resize_anchored(self._fm.horizontalAdvance(EMPTY_TEXT) + pad_x * 2, row_h + pad_y * 2)
            return
        width = sum(self._widths) + gap * (NCOLS - 1) + pad_x * 2
        n_summary = sum(r.is_summary for r in self._rows)
        height = len(self._rows) * row_h + pad_y * 2 + (sep * 2 if n_summary else 0)
        self._resize_anchored(width, height)

    def _resize_anchored(self, w: int, h: int) -> None:
        """화면 오른쪽/아래 가장자리에 붙어 있으면 그 모서리를 고정한 채 크기를 바꾼다."""
        if (w, h) == (self.width(), self.height()):
            return
        geo = self.frameGeometry()
        screen = self._screen_rect()
        x, y = geo.x(), geo.y()
        if self.isVisible() and screen is not None:
            if abs(geo.right() - screen.right()) <= SNAP_DISTANCE + SCREEN_MARGIN:
                x = geo.right() - w + 1
            if abs(geo.bottom() - screen.bottom()) <= SNAP_DISTANCE + SCREEN_MARGIN:
                y = geo.bottom() - h + 1
        self.setFixedSize(w, h)
        if self.isVisible():
            self.move(self._clamp(QPoint(x, y)))

    def _row_top(self, index: int) -> int:
        row_h, _, pad_y, _, sep = self._metrics()
        first_summary = next((i for i, r in enumerate(self._rows) if r.is_summary), None)
        extra = sep * 2 if first_summary is not None and index >= first_summary else 0
        return pad_y + index * row_h + extra

    # ── 그리기 ─────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._tokens
        row_h, pad_x, _, gap, sep = self._metrics()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(10.0, row_h * 0.4)
        bg = QColor(t.background)
        if self._hovered:
            bg.setAlpha(min(255, bg.alpha() + 30))
        p.setPen(QPen(t.border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)
        p.setFont(self._font)

        if not self._rows:
            p.setPen(t.text_dim)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, EMPTY_TEXT)
        else:
            drew_rule = False
            for i, row in enumerate(self._rows):
                top = self._row_top(i)
                if row.is_summary and not drew_rule:
                    drew_rule = True
                    y = top - sep
                    p.setPen(QPen(t.hairline, 1))
                    p.drawLine(pad_x, y, self.width() - pad_x, y)
                x = pad_x
                for c, cell in enumerate(row.cells):
                    w = self._widths[c]
                    if cell.text:
                        text = cell.text
                        if c == 0:
                            text = self._fm.elidedText(text, Qt.TextElideMode.ElideRight, w)
                        p.setPen(cell.color or t.text)
                        p.drawText(QRect(x, top, w, row_h), cell.align | Qt.AlignmentFlag.AlignVCenter, text)
                    x += w + gap
        self._paint_status(p)
        p.end()

    def _paint_status(self, p: QPainter) -> None:
        """연결에 문제가 있을 때만 오른쪽 위에 작은 점을 표시 (평소에는 아무것도 없음)."""
        if not self._offline_reason:
            return
        r = 2.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._tokens.warning)
        p.drawEllipse(QRectF(self.width() - 7 - r, 5, r * 2, r * 2))

    # ── 호버 ───────────────────────────────────────────────
    def enterEvent(self, _event) -> None:  # noqa: N802
        self._hovered = True
        self._leave_timer.stop()
        self._animate_opacity(1.0)
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._leave_timer.start()

    def _fade_out(self) -> None:
        if self.underMouse():
            return
        self._hovered = False
        self._animate_opacity(self._settings.idle_opacity / 100)
        self.update()

    def _animate_opacity(self, target: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(target)
        self._fade.start()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            text = self._tooltip_at(e.pos())
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def _tooltip_at(self, pos: QPoint) -> str:
        if not self._rows:
            return self._status_tooltip()
        row_h = self._metrics()[0]
        row = next((r for i, r in enumerate(self._rows)
                    if self._row_top(i) <= pos.y() < self._row_top(i) + row_h), None)
        status = self._status_tooltip()
        if row is None:
            return status
        return row.tooltip + (f"<br><span style='color:gray'>{status}</span>" if status else "")

    # ── 마우스 ─────────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is None or self._settings.locked:
            return
        if not e.buttons() & Qt.MouseButton.LeftButton:
            return
        target = e.globalPosition().toPoint() - self._drag_offset
        if not self._dragged and (target - self.pos()).manhattanLength() < 3:
            return
        self._dragged = True
        QToolTip.hideText()
        self.move(self._snap(target))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._dragged:
            self.position_changed.emit(self.pos())
        self._drag_offset = None
        self._dragged = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_portfolio_requested.emit()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        self.context_menu_requested.emit(e.globalPos())

    # ── 위치 ───────────────────────────────────────────────
    def _screen_rect(self, point: QPoint | None = None) -> QRect | None:
        center = point or self.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _snap(self, pos: QPoint) -> QPoint:
        area = self._screen_rect(pos + QPoint(self.width() // 2, self.height() // 2))
        if area is None:
            return pos
        x, y = pos.x(), pos.y()
        left, top = area.left() + SCREEN_MARGIN, area.top() + SCREEN_MARGIN
        right = area.right() - SCREEN_MARGIN - self.width() + 1
        bottom = area.bottom() - SCREEN_MARGIN - self.height() + 1
        if abs(x - left) <= SNAP_DISTANCE:
            x = left
        elif abs(x - right) <= SNAP_DISTANCE:
            x = right
        if abs(y - top) <= SNAP_DISTANCE:
            y = top
        elif abs(y - bottom) <= SNAP_DISTANCE:
            y = bottom
        return QPoint(x, y)

    def _clamp(self, pos: QPoint) -> QPoint:
        area = self._screen_rect(pos + QPoint(self.width() // 2, self.height() // 2))
        if area is None:
            return pos
        x = min(max(pos.x(), area.left()), area.right() - self.width() + 1)
        y = min(max(pos.y(), area.top()), area.bottom() - self.height() + 1)
        return QPoint(x, y)

    def default_position(self) -> QPoint:
        area = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(area.right() - self.width() - SCREEN_MARGIN - 8,
                      area.bottom() - self.height() - SCREEN_MARGIN - 8)

    def restore_position(self, saved: list[int] | None) -> None:
        if saved:
            pos = QPoint(*saved)
            probe = QRect(pos, self.size())
            for screen in QGuiApplication.screens():
                if screen.availableGeometry().intersects(probe):
                    self.move(self._clamp(pos))
                    return
        self.move(self.default_position())

    def ensure_on_screen(self) -> None:
        """모니터 구성이 바뀌었을 때 화면 밖으로 사라지지 않도록."""
        probe = self.frameGeometry()
        if not any(s.availableGeometry().intersects(probe) for s in QGuiApplication.screens()):
            self.move(self.default_position())
            self.position_changed.emit(self.pos())

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._apply_capture_exclusion()
