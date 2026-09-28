"""종목 관리 대화상자.

검색창에 입력하면 자동으로 검색(국내·해외 통합)하고, 결과를 선택하면 표에 추가된다.
표에서 평균단가·수량·알림 가격을 바로 수정한다. 수량이 비어 있으면 관심 종목.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stockonmonitor.core import formatting as fmt
from stockonmonitor.core import transfer
from stockonmonitor.core.models import Holding, SearchResult
from stockonmonitor.providers.client import MarketDataClient

log = logging.getLogger(__name__)

COL_NAME, COL_CODE, COL_AVG, COL_QTY, COL_HIGH, COL_LOW, COL_SHOW = range(7)
HEADERS = ["종목명", "코드", "평균단가", "수량", "알림 ↑", "알림 ↓", "표시"]
NUMERIC_COLS = (COL_AVG, COL_QTY, COL_HIGH, COL_LOW)
ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_CURRENCY = Qt.ItemDataRole.UserRole + 1


def _parse_number(text: str) -> float:
    try:
        return max(0.0, float(text.replace(",", "").strip() or 0))
    except ValueError:
        return 0.0


class _NumberDelegate(QStyledItemDelegate):
    """숫자 칸: 쉼표 표시, 숫자만 입력 가능, 0은 빈칸으로 보여 준다."""

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9,]*\.?[0-9]*"), editor))
        editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        value = float(index.data(Qt.ItemDataRole.EditRole) or 0)
        editor.setText(fmt.number_input(value, index.data(ROLE_CURRENCY) or "KRW"))
        editor.selectAll()

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, _parse_number(editor.text()), Qt.ItemDataRole.EditRole)

    def initStyleOption(self, option, index):  # noqa: N802
        super().initStyleOption(option, index)
        value = float(index.data(Qt.ItemDataRole.EditRole) or 0)
        currency = index.data(ROLE_CURRENCY) or "KRW"
        if index.column() == COL_QTY:
            option.text = f"{value:,.10g}" if value else ""
        else:
            option.text = fmt.price(value, currency) if value else ""
        option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class _SearchRunner(QObject):
    finished = Signal(int, object, str)   # (요청 번호, 결과 목록, 오류 메시지)

    def __init__(self, client: MarketDataClient) -> None:
        super().__init__()
        self._client = client
        self._seq = 0

    def run(self, query: str) -> int:
        self._seq += 1
        seq = self._seq

        def work():
            try:
                results = self._client.search(query)
                self.finished.emit(seq, results, "")
            except Exception as exc:
                log.info("검색 실패: %s", exc)
                self.finished.emit(seq, [], str(exc))

        threading.Thread(target=work, daemon=True, name="search").start()
        return seq

    @property
    def latest(self) -> int:
        return self._seq


class PortfolioDialog(QDialog):
    saved = Signal(list)   # list[Holding]

    def __init__(self, holdings: list[Holding], client: MarketDataClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("종목 관리")
        self.setMinimumSize(720, 520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._holdings = [Holding.from_dict(h.to_dict()) for h in holdings]
        self._dirty = False
        self._search = _SearchRunner(client)
        self._search.finished.connect(self._on_search_done)
        self._debounce = QTimer(self, singleShot=True, interval=350, timeout=self._run_search)

        self._build()
        self._render()

    # ── UI ─────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("종목명 또는 코드로 검색  (예: 삼성전자, 005930, AAPL, 테슬라)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_query_changed)
        self.search_edit.returnPressed.connect(self._add_current_result)
        self.search_edit.installEventFilter(self)
        root.addWidget(self.search_edit)

        self.results = QListWidget()
        self.results.setObjectName("results")
        self.results.setVisible(False)
        self.results.itemActivated.connect(lambda _i: self._add_current_result())
        self.results.itemClicked.connect(lambda _i: self._add_current_result())
        root.addWidget(self.results)

        self.search_status = QLabel()
        self.search_status.setProperty("role", "muted")
        self.search_status.setVisible(False)
        root.addWidget(self.search_status)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.EditKeyPressed |
                                   QAbstractItemView.EditTrigger.AnyKeyPressed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_CODE, 120), (COL_AVG, 100), (COL_QTY, 80), (COL_HIGH, 90), (COL_LOW, 90),
                           (COL_SHOW, 48)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        delegate = _NumberDelegate(self.table)
        for col in NUMERIC_COLS:
            self.table.setItemDelegateForColumn(col, delegate)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.table, 1)

        hint = QLabel("수량을 비워 두면 관심 종목으로 표시됩니다.  알림 가격에 도달하면 한 번 알려 드립니다.")
        hint.setProperty("role", "muted")
        root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_up = self._flat("위로", lambda: self._move(-1))
        self.btn_down = self._flat("아래로", lambda: self._move(1))
        self.btn_remove = self._flat("삭제", self._remove_selected)
        for b in (self.btn_up, self.btn_down, self.btn_remove):
            buttons.addWidget(b)
        buttons.addSpacing(12)
        buttons.addWidget(self._flat("가져오기…", self._import))
        buttons.addWidget(self._flat("내보내기…", self._export))
        buttons.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        save = QPushButton("저장")
        save.setProperty("kind", "primary")
        save.setDefault(False)
        save.setAutoDefault(False)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        QShortcut(QKeySequence.StandardKey.Delete, self.table, self._remove_selected)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_edit.setFocus)
        self._update_buttons()

    @staticmethod
    def _flat(text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("kind", "flat")
        b.setAutoDefault(False)
        b.clicked.connect(slot)
        return b

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(780, 560)

    # ── 표 ─────────────────────────────────────────────────
    def _render(self, select_id: str | None = None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._holdings))
        for r, h in enumerate(self._holdings):
            name = QTableWidgetItem(h.name or h.symbol)
            name.setData(ROLE_ID, h.id)
            self.table.setItem(r, COL_NAME, name)

            code = QTableWidgetItem(f"{h.symbol} · {h.exchange or h.market}")
            code.setFlags(code.flags() & ~Qt.ItemFlag.ItemIsEditable)
            code.setForeground(self.palette().placeholderText())
            self.table.setItem(r, COL_CODE, code)

            for col, value in ((COL_AVG, h.avg_price), (COL_QTY, h.quantity),
                               (COL_HIGH, h.target_high or 0.0), (COL_LOW, h.target_low or 0.0)):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.EditRole, float(value))
                item.setData(ROLE_CURRENCY, h.currency)
                self.table.setItem(r, col, item)

            show = QTableWidgetItem()
            show.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            show.setCheckState(Qt.CheckState.Checked if h.visible else Qt.CheckState.Unchecked)
            self.table.setItem(r, COL_SHOW, show)
        self.table.blockSignals(False)

        if select_id:
            for r, h in enumerate(self._holdings):
                if h.id == select_id:
                    self.table.selectRow(r)
                    self.table.scrollToItem(self.table.item(r, COL_NAME))
                    break
        self._update_buttons()

    def _commit_table(self) -> None:
        """표에 입력된 값을 self._holdings에 반영."""
        for r, h in enumerate(self._holdings):
            name = self.table.item(r, COL_NAME).text().strip()
            h.name = name or h.name or h.symbol
            h.avg_price = float(self.table.item(r, COL_AVG).data(Qt.ItemDataRole.EditRole) or 0)
            h.quantity = float(self.table.item(r, COL_QTY).data(Qt.ItemDataRole.EditRole) or 0)
            h.target_high = float(self.table.item(r, COL_HIGH).data(Qt.ItemDataRole.EditRole) or 0) or None
            h.target_low = float(self.table.item(r, COL_LOW).data(Qt.ItemDataRole.EditRole) or 0) or None
            h.visible = self.table.item(r, COL_SHOW).checkState() == Qt.CheckState.Checked

    def _on_item_changed(self, _item) -> None:
        self._dirty = True

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _update_buttons(self) -> None:
        rows = self._selected_rows()
        self.btn_remove.setEnabled(bool(rows))
        self.btn_up.setEnabled(len(rows) == 1 and rows[0] > 0)
        self.btn_down.setEnabled(len(rows) == 1 and rows[0] < len(self._holdings) - 1)

    def _move(self, step: int) -> None:
        rows = self._selected_rows()
        if len(rows) != 1:
            return
        r = rows[0]
        target = r + step
        if not 0 <= target < len(self._holdings):
            return
        self._commit_table()
        self._holdings[r], self._holdings[target] = self._holdings[target], self._holdings[r]
        self._dirty = True
        self._render(select_id=self._holdings[target].id)

    def _remove_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        self._commit_table()
        names = ", ".join(self._holdings[r].display_name for r in rows[:3]) + (" 외" if len(rows) > 3 else "")
        if QMessageBox.question(self, "종목 삭제", f"{names} 을(를) 목록에서 삭제할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        for r in reversed(rows):
            del self._holdings[r]
        self._dirty = True
        self._render()

    # ── 검색 ───────────────────────────────────────────────
    def eventFilter(self, obj, event):  # noqa: N802
        # 검색창에서 ↓ 키로 결과 목록 이동
        if obj is self.search_edit and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and self.results.isVisible() and self.results.count():
                self.results.setFocus()
                self.results.setCurrentRow(0)
                return True
            if event.key() == Qt.Key.Key_Escape and self.results.isVisible():
                self._hide_results()
                return True
        return super().eventFilter(obj, event)

    def _on_query_changed(self, text: str) -> None:
        if len(text.strip()) < 1:
            self._debounce.stop()
            self._hide_results()
            return
        self._debounce.start()

    def _run_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self._show_status("검색 중…")
        self._search.run(query)

    def _on_search_done(self, seq: int, results: list[SearchResult], error: str) -> None:
        if seq != self._search.latest:
            return  # 더 최근 검색이 진행 중
        self.results.clear()
        if error:
            self._show_status("검색하지 못했습니다. 인터넷 연결을 확인해 주세요.")
            self.results.setVisible(False)
            return
        if not results:
            self._show_status("검색 결과가 없습니다.")
            self.results.setVisible(False)
            return
        existing = {h.key for h in self._holdings}
        for r in results:
            label = f"{r.name}    {r.symbol} · {r.exchange or r.market}"
            if r.key in existing:
                label += "    (추가됨)"
            item = QListWidgetItem(label)
            item.setData(ROLE_ID, r)
            self.results.addItem(item)
        self.results.setCurrentRow(0)
        row_h = self.results.sizeHintForRow(0) if self.results.count() else 28
        self.results.setFixedHeight(min(6, self.results.count()) * row_h + 6)
        self.results.setVisible(True)
        self.search_status.setVisible(False)

    def _show_status(self, text: str) -> None:
        self.search_status.setText(text)
        self.search_status.setVisible(True)

    def _hide_results(self) -> None:
        self.results.clear()
        self.results.setVisible(False)
        self.search_status.setVisible(False)

    def _add_current_result(self) -> None:
        item = self.results.currentItem()
        if item is None:
            if self.search_edit.text().strip():
                self._debounce.stop()
                self._run_search()
            return
        r: SearchResult = item.data(ROLE_ID)
        self._commit_table()
        for h in self._holdings:
            if h.key == r.key:
                self._render(select_id=h.id)
                self._show_status(f"{h.display_name} 은(는) 이미 목록에 있습니다.")
                return
        h = Holding(symbol=r.symbol, market=r.market, name=r.name, exchange=r.exchange, naver_code=r.naver_code)
        self._holdings.append(h)
        self._dirty = True
        self._render(select_id=h.id)
        self.search_edit.clear()
        self._hide_results()
        # 바로 평균단가 입력으로 이동
        row = len(self._holdings) - 1
        self.table.setCurrentCell(row, COL_AVG)
        self.table.setFocus()
        self.table.editItem(self.table.item(row, COL_AVG))

    # ── 가져오기/내보내기 ──────────────────────────────────
    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "종목 가져오기", str(Path.home()),
                                              "종목 파일 (*.csv *.json);;모든 파일 (*)")
        if not path:
            return
        try:
            imported = transfer.import_holdings(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "가져오기 실패", f"파일을 읽을 수 없습니다.\n{exc}")
            return
        self._commit_table()
        if self._holdings:
            box = QMessageBox(QMessageBox.Icon.Question, "종목 가져오기",
                              f"{len(imported)}개 종목을 불러왔습니다. 기존 목록을 어떻게 할까요?", parent=self)
            merge = box.addButton("기존 목록에 추가", QMessageBox.ButtonRole.AcceptRole)
            replace = box.addButton("기존 목록 교체", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is replace:
                self._holdings = []
            elif box.clickedButton() is not merge:
                return
        existing = {h.key for h in self._holdings}
        added = [h for h in imported if h.key not in existing]
        self._holdings.extend(added)
        self._dirty = True
        self._render()
        skipped = len(imported) - len(added)
        if skipped:
            self._show_status(f"{len(added)}개 추가, 중복 {skipped}개는 건너뛰었습니다.")

    def _export(self) -> None:
        self._commit_table()
        path, selected = QFileDialog.getSaveFileName(self, "종목 내보내기", str(Path.home() / "종목목록.csv"),
                                                     "CSV (엑셀) (*.csv);;JSON (*.json)")
        if not path:
            return
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".json" if "json" in selected.lower() else ".csv")
        try:
            transfer.export_holdings(self._holdings, p)
        except OSError as exc:
            QMessageBox.warning(self, "내보내기 실패", str(exc))
            return
        self._show_status(f"{p.name} 로 내보냈습니다.")

    # ── 저장/닫기 ──────────────────────────────────────────
    def _save(self) -> None:
        if self.table.state() == QAbstractItemView.State.EditingState:
            # Ctrl+S로 저장할 때 편집 중인 칸의 값을 먼저 확정
            editor = QApplication.focusWidget()
            if editor is not None:
                self.table.commitData(editor)
                self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        self._commit_table()
        self.saved.emit(self._holdings)
        self._dirty = False
        self.accept()

    def reject(self) -> None:
        if self._dirty:
            answer = QMessageBox.question(
                self, "변경 사항", "저장하지 않은 변경 사항이 있습니다. 저장할까요?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Save:
                self._save()
                return
            if answer == QMessageBox.StandardButton.Cancel:
                return
        super().reject()
