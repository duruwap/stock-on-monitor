"""설정 대화상자: 왼쪽 목록으로 분류를 고르는 형식 (일반 · 표시 · 개인정보 · 알림 · 정보)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from stockonmonitor import meta
from stockonmonitor.core.models import REFRESH_CHOICES, Settings
from stockonmonitor.platform import windows
from stockonmonitor.ui.icons import draw_app_icon

PAGES = ["일반", "표시", "개인정보", "알림", "정보"]
PAGE_ABOUT = PAGES.index("정보")

OPEN_SOURCE = [
    ("Qt 6 / Qt for Python (PySide6)", "LGPL v3", "https://www.qt.io/licensing"),
    ("Python", "PSF License", "https://docs.python.org/3/license.html"),
    ("PyInstaller 부트로더", "GPL v2 + 예외 조항", "https://pyinstaller.org/en/stable/license.html"),
    ("Inno Setup", "Inno Setup License", "https://jrsoftware.org/files/is/license.txt"),
]


def _combo(options: list[tuple[str, object]], current: object) -> QComboBox:
    c = QComboBox()
    for label, value in options:
        c.addItem(label, value)
    idx = c.findData(current)
    c.setCurrentIndex(max(0, idx))
    return c


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section")
    return lbl


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "muted")
    lbl.setWordWrap(True)
    return lbl


class SettingsDialog(QDialog):
    applied = Signal(object, bool)   # (Settings, 자동 실행 여부)

    def __init__(self, settings: Settings, *, data_dir: str, log_dir: str,
                 hotkey_validator: Callable[[str], bool],
                 on_open_folder: Callable[[str], None],
                 on_check_update: Callable[[], None] | None,
                 page: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._settings = settings
        self._validate_hotkey = hotkey_validator
        self._on_open_folder = on_open_folder
        self._on_check_update = on_check_update
        self._data_dir = data_dir
        self._log_dir = log_dir

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(150)
        self.nav.setSpacing(1)
        for name in PAGES:
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, 34))
            self.nav.addItem(item)
        self.stack = QStackedWidget()
        for build in (self._page_general, self._page_display, self._page_privacy, self._page_alerts,
                      self._page_about):
            page_widget = QWidget()
            lay = QVBoxLayout(page_widget)
            lay.setContentsMargins(24, 20, 24, 12)
            lay.setSpacing(10)
            build(lay)
            lay.addStretch()
            self.stack.addWidget(page_widget)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: palette(mid);")
        root.addWidget(line)

        footer = QHBoxLayout()
        footer.setContentsMargins(16, 10, 16, 12)
        self.warning = QLabel()
        self.warning.setProperty("role", "warning")
        footer.addWidget(self.warning, 1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("저장")
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(ok)
        root.addLayout(footer)

        self.nav.setCurrentRow(page)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, 500)

    # ── 페이지 ─────────────────────────────────────────────
    def _page_general(self, lay: QVBoxLayout) -> None:
        s = self._settings
        self.chk_autostart = QCheckBox("Windows 시작 시 자동 실행")
        self.chk_autostart.setChecked(windows.is_autostart_enabled())
        if not windows.autostart_supported():
            self.chk_autostart.setEnabled(False)
            self.chk_autostart.setToolTip("설치된 버전에서만 사용할 수 있습니다.")
        self.chk_on_top = QCheckBox("위젯을 항상 다른 창 위에 표시")
        self.chk_on_top.setChecked(s.always_on_top)
        self.chk_locked = QCheckBox("위젯 위치 잠금 (드래그로 이동하지 않음)")
        self.chk_locked.setChecked(s.locked)
        for w in (self.chk_autostart, self.chk_on_top, self.chk_locked):
            lay.addWidget(w)

        lay.addWidget(_section("시세"))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        self.cmb_refresh = _combo([(f"{v}초마다", v) for v in REFRESH_CHOICES], s.refresh_seconds)
        form.addRow("새로고침 간격", self.cmb_refresh)
        lay.addLayout(form)
        lay.addWidget(_muted("장이 열리지 않는 시간에는 자동으로 5분 간격으로 줄여 데이터를 아낍니다."))

        lay.addWidget(_section("단축키"))
        row = QHBoxLayout()
        self.key_edit = QKeySequenceEdit(QKeySequence.fromString(s.hotkey, QKeySequence.SequenceFormat.PortableText))
        try:
            self.key_edit.setMaximumSequenceLength(1)
            self.key_edit.setClearButtonEnabled(True)
        except AttributeError:  # Qt < 6.5
            pass
        self.key_edit.setFixedWidth(200)
        row.addWidget(QLabel("위젯 숨기기/보이기"))
        row.addSpacing(12)
        row.addWidget(self.key_edit)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(_muted("어느 프로그램을 쓰고 있든 이 키를 누르면 위젯이 즉시 숨겨지거나 나타납니다."))

    def _page_display(self, lay: QVBoxLayout) -> None:
        s = self._settings
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.cmb_theme = _combo([("시스템 설정 따르기", "system"), ("어둡게", "dark"), ("밝게", "light")], s.theme)
        self.cmb_layout = _combo([("목록", "list"), ("한 줄 (종목을 번갈아 표시)", "ticker")], s.layout)
        self.cmb_colors = _combo([("상승 빨강 · 하락 파랑", "kr"), ("상승 초록 · 하락 빨강", "global"),
                                  ("색 없이 ▲▼ 기호만", "mono")], s.color_scheme)
        self.cmb_font = _combo([(f"{v} pt" + (" (기본)" if v == 9 else ""), v) for v in range(7, 17)], s.font_size)

        opacity_row = QHBoxLayout()
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(20, 100)
        self.sld_opacity.setValue(s.idle_opacity)
        self.lbl_opacity = QLabel(f"{s.idle_opacity}%")
        self.lbl_opacity.setFixedWidth(40)
        self.sld_opacity.valueChanged.connect(lambda v: self.lbl_opacity.setText(f"{v}%"))
        opacity_row.addWidget(self.sld_opacity)
        opacity_row.addWidget(self.lbl_opacity)

        form.addRow("테마", self.cmb_theme)
        form.addRow("배치", self.cmb_layout)
        form.addRow("등락 색상", self.cmb_colors)
        form.addRow("글자 크기", self.cmb_font)
        form.addRow("평소 불투명도", opacity_row)
        lay.addLayout(form)
        lay.addWidget(_muted("마우스를 올리면 잠시 선명하게 보입니다."))

        lay.addWidget(_section("표시 항목"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.chk_cols = {}
        for i, (key, label) in enumerate([
            ("show_change_pct", "오늘 등락률"), ("show_change_amt", "오늘 등락폭"),
            ("show_profit_pct", "수익률"), ("show_profit_amt", "평가손익"),
            ("show_value", "평가금액"), ("show_summary", "합계 행"),
        ]):
            c = QCheckBox(label)
            c.setChecked(getattr(s, key))
            self.chk_cols[key] = c
            grid.addWidget(c, i // 2, i % 2)
        lay.addLayout(grid)

    def _page_privacy(self, lay: QVBoxLayout) -> None:
        s = self._settings
        self.chk_hide_amounts = QCheckBox("금액 숨기기 (수익률 등 % 만 표시)")
        self.chk_hide_amounts.setChecked(s.hide_amounts)
        lay.addWidget(self.chk_hide_amounts)
        lay.addWidget(_muted("평가금액·손익 금액이 ••• 로 표시되어 옆 사람에게 자산 규모가 드러나지 않습니다."))

        self.chk_capture = QCheckBox("화면 공유·녹화·캡처 시 위젯 숨기기")
        self.chk_capture.setChecked(s.hide_in_capture)
        lay.addWidget(self.chk_capture)
        lay.addWidget(_muted("Teams·Zoom 화면 공유나 캡처 이미지에 위젯이 나타나지 않습니다. "
                             "(Windows 10 2004 이상)"))

        self.chk_fullscreen = QCheckBox("전체 화면·발표 중에는 자동으로 숨기기")
        self.chk_fullscreen.setChecked(s.hide_when_fullscreen)
        lay.addWidget(self.chk_fullscreen)
        lay.addWidget(_muted("PowerPoint 슬라이드 쇼, 전체 화면 동영상 등이 실행되는 동안 잠시 숨겨집니다."))

    def _page_alerts(self, lay: QVBoxLayout) -> None:
        s = self._settings
        self.chk_targets = QCheckBox("알림 가격에 도달하면 알리기")
        self.chk_targets.setChecked(s.notify_targets)
        lay.addWidget(self.chk_targets)
        lay.addWidget(_muted("종목 관리에서 종목별 알림 가격(↑ 이상, ↓ 이하)을 지정할 수 있습니다."))

        row = QHBoxLayout()
        row.addWidget(QLabel("하루 등락률이"))
        choices = [0.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0]
        if s.notify_move_pct not in choices:
            choices = sorted(choices + [s.notify_move_pct])
        self.cmb_move = _combo([("사용 안 함" if v == 0 else f"±{v:g}%", v) for v in choices], s.notify_move_pct)
        self.cmb_move.setFixedWidth(120)
        row.addWidget(self.cmb_move)
        row.addWidget(QLabel("이상 움직이면 알리기"))
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(_muted("같은 알림은 하루에 한 번만 표시됩니다."))

        lay.addWidget(_section("업데이트"))
        self.chk_updates = QCheckBox("새 버전이 나오면 알리기")
        self.chk_updates.setChecked(s.check_updates)
        if not self._on_check_update:
            self.chk_updates.setEnabled(False)
            self.chk_updates.setToolTip("업데이트 서버가 설정되지 않은 빌드입니다.")
        lay.addWidget(self.chk_updates)

    def _page_about(self, lay: QVBoxLayout) -> None:
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(draw_app_icon(96).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
        head.addWidget(icon)
        head.addSpacing(8)
        title_box = QVBoxLayout()
        title = QLabel(meta.APP_NAME)
        title.setProperty("role", "title")
        title_box.addWidget(title)
        title_box.addWidget(_muted(f"버전 {meta.APP_VERSION}  ·  {meta.APP_COPYRIGHT}"))
        head.addLayout(title_box)
        head.addStretch()
        lay.addLayout(head)

        buttons = QHBoxLayout()
        if self._on_check_update:
            b = QPushButton("업데이트 확인")
            b.clicked.connect(self._on_check_update)
            buttons.addWidget(b)
        if meta.WEBSITE_URL:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            w = QPushButton("웹사이트")
            w.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(meta.WEBSITE_URL)))
            buttons.addWidget(w)
        buttons.addStretch()
        lay.addLayout(buttons)

        lay.addWidget(_section("데이터 위치"))
        path = QLabel(self._data_dir)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setWordWrap(True)
        lay.addWidget(path)
        folder_row = QHBoxLayout()
        b1 = QPushButton("데이터 폴더 열기")
        b1.clicked.connect(lambda: self._on_open_folder(self._data_dir))
        b2 = QPushButton("로그 폴더 열기")
        b2.clicked.connect(lambda: self._on_open_folder(self._log_dir))
        folder_row.addWidget(b1)
        folder_row.addWidget(b2)
        folder_row.addStretch()
        lay.addLayout(folder_row)
        lay.addWidget(_muted("설정·종목은 이 폴더에 저장되며 매일 자동 백업됩니다(backups 폴더)."))

        lay.addWidget(_section("오픈소스 라이선스"))
        lines = "<br>".join(f"{name} — {lic}  <a href='{url}'>보기</a>" for name, lic, url in OPEN_SOURCE)
        lic = QLabel(lines)
        lic.setOpenExternalLinks(True)
        lic.setProperty("role", "muted")
        lay.addWidget(lic)
        lay.addWidget(_muted("시세 정보는 네이버 증권·Yahoo Finance에서 제공받으며 지연되거나 부정확할 수 있습니다. "
                             "투자 판단의 책임은 이용자에게 있습니다."))

    # ── 저장 ───────────────────────────────────────────────
    def _collect(self) -> Settings:
        s = replace(
            self._settings,
            always_on_top=self.chk_on_top.isChecked(),
            locked=self.chk_locked.isChecked(),
            refresh_seconds=int(self.cmb_refresh.currentData()),
            hotkey=self.key_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
            theme=self.cmb_theme.currentData(),
            layout=self.cmb_layout.currentData(),
            color_scheme=self.cmb_colors.currentData(),
            font_size=int(self.cmb_font.currentData()),
            idle_opacity=self.sld_opacity.value(),
            hide_amounts=self.chk_hide_amounts.isChecked(),
            hide_in_capture=self.chk_capture.isChecked(),
            hide_when_fullscreen=self.chk_fullscreen.isChecked(),
            notify_targets=self.chk_targets.isChecked(),
            notify_move_pct=float(self.cmb_move.currentData()),
            check_updates=self.chk_updates.isChecked(),
            **{k: c.isChecked() for k, c in self.chk_cols.items()},
        )
        return s.normalized()

    def _save(self) -> None:
        s = self._collect()
        if s.hotkey and s.hotkey != self._settings.hotkey and not self._validate_hotkey(s.hotkey):
            self.nav.setCurrentRow(0)
            self.warning.setText("이 단축키는 사용할 수 없습니다. Ctrl·Alt를 포함한 다른 조합을 선택해 주세요.")
            return
        self.applied.emit(s, self.chk_autostart.isChecked())
        self.accept()
