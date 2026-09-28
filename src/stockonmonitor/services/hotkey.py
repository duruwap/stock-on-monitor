"""전역 단축키 (위젯 즉시 숨기기/보이기).

단축키는 절대 다시 만들어지지 않는 전용 숨은 창에 등록한다.
(위젯은 '항상 위' 설정을 바꿀 때 네이티브 창이 새로 만들어져 등록이 풀릴 수 있기 때문)
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QWidget

from stockonmonitor.platform import windows

log = logging.getLogger(__name__)

HOTKEY_ID = 0xB055  # 임의의 고정 id


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt API)
        try:
            if bytes(event_type) == b"windows_generic_MSG" and \
                    windows.hotkey_id_from_message(int(message)) == HOTKEY_ID:
                self._callback()
                return True, 0
        except (TypeError, ValueError):
            pass
        return False, 0


class GlobalHotkey(QObject):
    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = QWidget()
        self._window.setObjectName("hotkey-sink")
        self._hwnd = int(self._window.winId())  # 네이티브 창만 만들고 표시하지 않음
        self._filter = _Filter(self.activated.emit)
        QCoreApplication.instance().installNativeEventFilter(self._filter)
        self._current = ""

    @property
    def current(self) -> str:
        return self._current

    def set_hotkey(self, text: str) -> bool:
        """새 단축키로 교체. 빈 문자열이면 해제. 등록 실패 시 False."""
        self.clear()
        if not text:
            return True
        if windows.register_hotkey(self._hwnd, HOTKEY_ID, text):
            self._current = text
            log.info("전역 단축키 등록: %s", text)
            return True
        return False

    def clear(self) -> None:
        if self._current:
            windows.unregister_hotkey(self._hwnd, HOTKEY_ID)
            self._current = ""
