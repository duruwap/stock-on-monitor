"""디자인 토큰과 스타일시트.

원칙: 무채색 기반. 강조색(accent)은 '저장' 같은 주요 버튼과 포커스 표시에만,
등락 색상은 채도를 낮춰 사무실 화면에서 튀지 않게 한다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo",
                 "Noto Sans KR", "Noto Sans CJK KR", "sans-serif"]


def ui_font(point_size: float = 9, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(point_size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting if sys.platform != "win32"
                           else QFont.HintingPreference.PreferDefaultHinting)
    return f


def system_is_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return True
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def resolve_dark(theme: str) -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    return system_is_dark()


# ─────────────────────────────────────────────────────────────
# 위젯 토큰
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WidgetTokens:
    background: QColor
    border: QColor
    hairline: QColor
    text: QColor          # 종목명·가격·라벨 모두 같은 색 (일관성)
    text_dim: QColor      # 값이 없을 때(—, 불러오는 중)만
    up: QColor
    down: QColor
    warning: QColor


def widget_tokens(dark: bool, color_scheme: str) -> WidgetTokens:
    if dark:
        base = dict(
            background=QColor(22, 23, 26, 205),
            border=QColor(255, 255, 255, 16),
            hairline=QColor(255, 255, 255, 22),
            text=QColor("#D5D8DC"),
            text_dim=QColor("#6B7078"),
            warning=QColor("#C9A04A"),
        )
        red, blue, green = QColor("#E2847C"), QColor("#82A9E2"), QColor("#76BF9A")
    else:
        base = dict(
            background=QColor(250, 250, 251, 220),
            border=QColor(0, 0, 0, 20),
            hairline=QColor(0, 0, 0, 18),
            text=QColor("#30343A"),
            text_dim=QColor("#A3A8AE"),
            warning=QColor("#A87B1E"),
        )
        red, blue, green = QColor("#C0463E"), QColor("#2F66B8"), QColor("#2E8A5E")

    if color_scheme == "global":
        up, down = green, red
    elif color_scheme == "mono":
        up = down = base["text"]
    else:
        up, down = red, blue
    return WidgetTokens(up=up, down=down, **base)


# ─────────────────────────────────────────────────────────────
# 대화상자(설정·종목 관리) 스타일
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DialogTokens:
    window: str
    surface: str
    field: str
    border: str
    border_strong: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    selection: str
    danger: str


LIGHT = DialogTokens(
    window="#FFFFFF", surface="#F6F7F9", field="#FFFFFF", border="#E2E4E8", border_strong="#C9CDD3",
    text="#1F2328", muted="#6A7078", accent="#2F6FEB", accent_hover="#255BC4", accent_text="#FFFFFF",
    selection="#E8EFFD", danger="#C2473F",
)
DARK = DialogTokens(
    window="#1E1F22", surface="#25272B", field="#2B2D31", border="#35383D", border_strong="#4A4E55",
    text="#E4E6E9", muted="#9398A0", accent="#4C8DF6", accent_hover="#6AA0F8", accent_text="#FFFFFF",
    selection="#2C3A52", danger="#E07A72",
)


def dialog_tokens(dark: bool) -> DialogTokens:
    return DARK if dark else LIGHT


def apply_app_palette(dark: bool) -> None:
    t = dialog_tokens(dark)
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.field,
        QPalette.ColorRole.AlternateBase: t.surface,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.surface,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Dark: t.border_strong,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.muted))
    app = QGuiApplication.instance()
    app.setPalette(pal)
    from stockonmonitor.ui.icons import checkmark_file, chevron_file

    app.setStyleSheet(stylesheet(t, checkmark_file(t.accent_text), chevron_file(t.muted)))


def stylesheet(t: DialogTokens, check_image: str = "", chevron_image: str = "") -> str:
    return f"""
    QDialog {{ background: {t.window}; }}
    QLabel {{ color: {t.text}; }}
    QLabel[role="muted"] {{ color: {t.muted}; }}
    QLabel[role="section"] {{ color: {t.muted}; font-weight: 600; padding-top: 6px; }}
    QLabel[role="title"] {{ font-size: 13pt; font-weight: 600; }}
    QLabel[role="warning"] {{ color: {t.danger}; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit QLineEdit {{
        background: {t.field}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 6px; padding: 5px 8px;
        selection-background-color: {t.accent}; selection-color: {t.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{chevron_image}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{
        background: {t.field}; border: 1px solid {t.border}; selection-background-color: {t.selection};
        selection-color: {t.text}; outline: none;
    }}

    QPushButton {{
        background: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 6px; padding: 6px 14px; min-height: 18px;
    }}
    QPushButton:hover {{ border-color: {t.border_strong}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QPushButton[kind="primary"] {{
        background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600;
    }}
    QPushButton[kind="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
    QPushButton[kind="flat"] {{ background: transparent; border-color: transparent; color: {t.muted}; }}
    QPushButton[kind="flat"]:hover {{ color: {t.text}; }}

    QCheckBox {{ spacing: 8px; color: {t.text}; }}
    QCheckBox::indicator, QTableWidget::indicator {{
        width: 15px; height: 15px; border-radius: 4px;
        border: 1px solid {t.border_strong}; background: {t.field};
    }}
    QCheckBox::indicator:checked, QTableWidget::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
        image: url("{check_image}"); }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.muted}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
        background: {t.field}; border: 1px solid {t.border_strong};
    }}

    QListWidget#nav {{
        background: {t.surface}; border: none; border-right: 1px solid {t.border}; outline: none;
        padding: 8px 6px;
    }}
    QListWidget#nav::item {{ padding-left: 12px; border-radius: 6px; color: {t.muted}; }}
    QListWidget#nav::item:selected {{ background: {t.selection}; color: {t.text}; }}
    QListWidget#nav::item:hover:!selected {{ color: {t.text}; }}

    QListWidget#results {{
        background: {t.field}; border: 1px solid {t.border}; border-radius: 6px; outline: none;
    }}
    QListWidget#results::item {{ padding: 6px 8px; }}
    QListWidget#results::item:selected {{ background: {t.selection}; color: {t.text}; }}

    QTableWidget {{
        background: {t.field}; alternate-background-color: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 6px; gridline-color: transparent; outline: none;
        selection-background-color: {t.selection}; selection-color: {t.text};
    }}
    QTableWidget::item {{ padding: 0 6px; }}
    QHeaderView::section {{
        background: {t.surface}; color: {t.muted}; border: none; border-bottom: 1px solid {t.border};
        padding: 6px; font-weight: 600;
    }}
    QTableCornerButton::section {{ background: {t.surface}; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: 3px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QMenu {{
        background: {t.window}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px;
    }}
    QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.selection}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
    QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}

    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px; }}
    QProgressBar {{ border: 1px solid {t.border}; border-radius: 4px; background: {t.surface}; height: 8px;
        text-align: center; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
    """
