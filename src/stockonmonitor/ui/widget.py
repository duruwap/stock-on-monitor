"""바탕화면 플로팅 위젯.

직접 그리기(QPainter) 방식이라 숫자 열이 정확히 오른쪽 정렬되고, 라벨 위젯 수십 개를
만들고 지우는 비용이 없다.

동작
- 평소에는 설정한 불투명도로 옅게, 마우스를 올리면 선명하게
- 드래그로 이동, 화면 가장자리에 자석처럼 붙음, 붙은 모서리를 기준으로 크기가 변함
- 더블클릭: 종목 관리 / 오른쪽 클릭: 메뉴 / 행 위에 머무르면 상세 툴팁
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from stockonmonitor.core import formatting as fmt
from stockonmonitor.core.models import Settings
from stockonmonitor.core.valuation import Position, Summary
from stockonmonitor.platform import windows
from stockonmonitor.ui import theme

SNAP_DISTANCE = 14
SCREEN_MARGIN = 12


@dataclass
class Cell:
    text: str
    color: QColor
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight
    bold: bool = False


@dataclass
class Row:
    cells: list[Cell]
    tooltip: str = ""
    is_summary: bool = False
    indicator: QColor | None = None     # 행 오른쪽 끝 작은 점 (알림 조건 충족 등)


@dataclass
class _Layout:
    widths: list[int] = field(default_factory=list)
    row_h: int = 0
    pad_x: int = 12
    pad_y: int = 8
    gap: int = 14


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
        self._layout = _Layout()
        self._ticker_index = 0
        self._hovered = False
        self._drag_offset: QPoint | None = None
        self._dragged = False
        self._has_data = False

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._leave_timer = QTimer(self, singleShot=True, interval=350, timeout=self._fade_out)

        self._ticker_timer = QTimer(self, timeout=self._next_ticker)

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
        self._font_bold = theme.ui_font(settings.font_size, QFont.Weight.DemiBold)
        self._fm = QFontMetrics(self._font)
        self._fm_bold = QFontMetrics(self._font_bold)

        if settings.layout == "ticker" and len(self._positions) > 0:
            self._ticker_timer.start(settings.ticker_seconds * 1000)
        else:
            self._ticker_timer.stop()

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
        self._has_data = fetched_at is not None
        if self._settings.layout == "ticker" and positions and not self._ticker_timer.isActive():
            self._ticker_timer.start(self._settings.ticker_seconds * 1000)
        self._rebuild()

    def _next_ticker(self) -> None:
        if self._hovered:  # 읽는 중에는 넘기지 않는다
            return
        count = len(self._rows)
        if count > 1:
            self._ticker_index = (self._ticker_index + 1) % count
            self.update()

    # ── 행 구성 ────────────────────────────────────────────
    def _color_for(self, value: float | None) -> QColor:
        t = self._tokens
        if not value:
            return t.text_secondary
        return t.up if value > 0 else t.down

    def _signed_pct(self, value: float | None) -> str:
        text = fmt.pct(value)
        if self._settings.color_scheme == "mono" and value:
            return f"{fmt.arrow(value)}{text.lstrip('+-')}"
        return text

    def _build_rows(self) -> list[Row]:
        s, t = self._settings, self._tokens
        masked = s.hide_amounts
        rows: list[Row] = []

        for p in self._positions:
            h, q = p.holding, p.quote
            cells = [Cell(h.display_name, t.text_secondary, Qt.AlignmentFlag.AlignLeft)]
            if q is None:
                cells.append(Cell(fmt.DASH if self._has_data else "···", t.text_tertiary))
                cells += [Cell("", t.text_tertiary) for _ in range(self._extra_columns())]
                rows.append(Row(cells, self._tooltip(p)))
                continue

            cells.append(Cell(fmt.price(q.price, h.currency), t.text, bold=True))
            if s.show_change_amt:
                cells.append(Cell(fmt.signed_price(q.change, h.currency), self._color_for(q.change)))
            if s.show_change_pct:
                cells.append(Cell(self._signed_pct(q.change_pct), self._color_for(q.change)))
            if s.show_profit_amt:
                cells.append(Cell(fmt.signed_money(p.profit, h.currency, masked) if p.profit is not None else "",
                                  self._color_for(p.profit)))
            if s.show_profit_pct:
                cells.append(Cell(self._signed_pct(p.profit_pct) if p.profit_pct is not None else "",
                                  self._color_for(p.profit_pct)))
            if s.show_value:
                cells.append(Cell(fmt.money(p.value, h.currency, masked) if p.value is not None else "",
                                  t.text_secondary))
            rows.append(Row(cells, self._tooltip(p)))

        if s.show_summary and self._summary and not self._summary.is_empty:
            rows.append(self._summary_row())
        return rows

    def _extra_columns(self) -> int:
        s = self._settings
        return sum([s.show_change_amt, s.show_change_pct, s.show_profit_amt, s.show_profit_pct, s.show_value])

    def _summary_row(self) -> Row:
        """합계 행은 각 열의 의미에 맞춰 채운다: 가격 열 → 총 평가금액, 등락 열 → 오늘 변동, 손익 열 → 총 손익."""
        s, t, sm = self._settings, self._tokens, self._summary
        masked = s.hide_amounts
        day_color = self._color_for(sm.day_change_krw)
        accent = self._color_for(sm.profit_krw)
        cells = [Cell("합계", t.text_tertiary, Qt.AlignmentFlag.AlignLeft),
                 Cell(fmt.krw_compact(sm.value_krw, masked), t.text, bold=True)]
        if s.show_change_amt:
            cells.append(Cell(fmt.signed_krw_compact(sm.day_change_krw, masked), day_color))
        if s.show_change_pct:
            cells.append(Cell(self._signed_pct(sm.day_change_pct), day_color))
        if s.show_profit_amt:
            cells.append(Cell(fmt.signed_krw_compact(sm.profit_krw, masked), accent,
                              bold=not s.show_profit_pct))
        if s.show_profit_pct:
            cells.append(Cell(self._signed_pct(sm.profit_pct), accent, bold=True))
        if s.show_value:
            cells.append(Cell("", t.text_tertiary))
        return Row(cells, self._summary_tooltip(), is_summary=True)

    # ── 툴팁 ───────────────────────────────────────────────
    def _tooltip(self, p: Position) -> str:
        h, q, masked = p.holding, p.quote, self._settings.hide_amounts
        lines = [f"<b>{h.display_name}</b> <span style='color:gray'>{h.symbol} · {h.exchange or h.market}</span>"]
        if q:
            lines.append(f"현재가 {fmt.price(q.price, h.currency)}  "
                         f"({fmt.signed_price(q.change, h.currency)}, {fmt.pct(q.change_pct)})")
        else:
            lines.append("시세를 불러오지 못했습니다")
        if not h.is_watch_only:
            lines.append(f"평균단가 {fmt.price(h.avg_price, h.currency)} · 수량 "
                         f"{fmt.MASK if masked else f'{h.quantity:,.10g}'}")
            if p.profit is not None:
                lines.append(f"평가손익 {fmt.signed_money(p.profit, h.currency, masked)} ({fmt.pct(p.profit_pct)})")
                lines.append(f"평가금액 {fmt.money(p.value, h.currency, masked)}")
        else:
            lines.append("관심 종목")
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
        lines = ["<b>합계 (원화 환산)</b>",
                 f"평가금액 {fmt.money(sm.value_krw, masked=masked)}",
                 f"매입금액 {fmt.money(sm.cost_krw, masked=masked)}",
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
            parts.append(f"연결 문제: {self._offline_reason}")
        if self._fetched_at:
            parts.append(f"마지막 갱신 {self._fetched_at:%H:%M:%S}")
        return "<br>".join(parts)

    # ── 레이아웃 ───────────────────────────────────────────
    def _rebuild(self) -> None:
        self._rows = self._build_rows()
        if self._ticker_index >= len(self._rows):
            self._ticker_index = 0
        self._compute_layout()
        self.update()

    def _text_width(self, cell: Cell) -> int:
        return (self._fm_bold if cell.bold else self._fm).horizontalAdvance(cell.text)

    def _compute_layout(self) -> None:
        lay = self._layout
        lay.row_h = int(self._fm.height() * 1.5)
        lay.pad_x = max(10, int(self._fm.height() * 0.8))
        lay.pad_y = max(6, int(self._fm.height() * 0.4))
        lay.gap = max(10, int(self._fm.height() * 0.9))

        if not self._rows:
            text = "종목을 추가하려면 더블클릭" if self._has_data or not self._positions else "불러오는 중…"
            w = self._fm.horizontalAdvance(text) + lay.pad_x * 2
            lay.widths = []
            self._resize_anchored(w, lay.row_h + lay.pad_y * 2)
            return

        ncols = max(len(r.cells) for r in self._rows)
        widths = [0] * ncols
        max_name = self._fm.horizontalAdvance("가") * 7  # 한글 7자
        for r in self._rows:
            for i, c in enumerate(r.cells):
                w = self._text_width(c)
                if i == 0:
                    w = min(w + 2, max_name)  # +2: 글꼴 대체 시 소수점 폭 반올림 여유
                widths[i] = max(widths[i], w)
        lay.widths = widths

        content_w = sum(widths) + lay.gap * (ncols - 1)
        width = content_w + lay.pad_x * 2
        if self._settings.layout == "ticker":
            height = lay.row_h + lay.pad_y * 2
        else:
            n = len(self._rows)
            has_summary = self._rows[-1].is_summary
            height = n * lay.row_h + lay.pad_y * 2 + (4 if has_summary else 0)
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

    # ── 그리기 ─────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        t, lay = self._tokens, self._layout
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(10.0, lay.row_h * 0.45)
        p.setPen(QPen(t.border, 1))
        bg = QColor(t.background)
        if self._hovered:
            bg.setAlpha(min(255, bg.alpha() + 30))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)

        if not self._rows:
            p.setFont(self._font)
            p.setPen(t.text_tertiary)
            text = "종목을 추가하려면 더블클릭" if self._has_data or not self._positions else "불러오는 중…"
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
            self._paint_status(p)
            p.end()
            return

        if self._settings.layout == "ticker":
            self._paint_row(p, self._rows[self._ticker_index], lay.pad_y)
        else:
            y = lay.pad_y
            for row in self._rows:
                if row.is_summary:
                    p.setPen(QPen(t.hairline, 1))
                    p.drawLine(lay.pad_x, y + 2, self.width() - lay.pad_x, y + 2)
                    y += 4
                self._paint_row(p, row, y)
                y += lay.row_h
        self._paint_status(p)
        p.end()

    def _paint_row(self, p: QPainter, row: Row, y: int) -> None:
        lay = self._layout
        x = lay.pad_x
        for i, cell in enumerate(row.cells):
            w = lay.widths[i] if i < len(lay.widths) else self._text_width(cell)
            p.setFont(self._font_bold if cell.bold else self._font)
            p.setPen(cell.color)
            text = cell.text
            if i == 0:
                text = self._fm.elidedText(text, Qt.TextElideMode.ElideRight, w)
            p.drawText(QRect(x, y, w, lay.row_h), cell.align | Qt.AlignmentFlag.AlignVCenter, text)
            x += w + lay.gap

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
        lay = self._layout
        if self._offline_reason and pos.x() > self.width() - 18 and pos.y() < 18:
            return self._status_tooltip()
        if not self._rows:
            return self._status_tooltip()
        if self._settings.layout == "ticker":
            row = self._rows[self._ticker_index]
        else:
            y = pos.y() - lay.pad_y
            idx = y // lay.row_h if lay.row_h else -1
            if self._rows[-1].is_summary and y >= (len(self._rows) - 1) * lay.row_h:
                idx = len(self._rows) - 1
            if not 0 <= idx < len(self._rows):
                return ""
            row = self._rows[idx]
        extra = self._status_tooltip()
        return row.tooltip + (f"<br><span style='color:gray'>{extra}</span>" if extra else "")

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

    def wheelEvent(self, e) -> None:  # noqa: N802
        # 한 줄 모드에서는 휠로 종목을 넘겨 볼 수 있다
        if self._settings.layout == "ticker" and self._rows:
            step = -1 if e.angleDelta().y() > 0 else 1
            self._ticker_index = (self._ticker_index + step) % len(self._rows)
            self.update()

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
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
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
