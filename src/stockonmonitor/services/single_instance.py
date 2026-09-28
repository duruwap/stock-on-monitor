"""중복 실행 방지.

두 번째로 실행된 프로세스는 기존 프로세스에 메시지를 보내고 종료한다.
(바탕화면 아이콘을 다시 눌렀을 때 카카오톡처럼 기존 창이 나타나는 동작)
"""

from __future__ import annotations

import getpass
import logging
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from stockonmonitor import meta

log = logging.getLogger(__name__)


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{meta.APP_ID}-{re.sub(r'[^A-Za-z0-9_-]', '_', user)}"


class SingleInstance(QObject):
    message_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = _server_name()
        self._server: QLocalServer | None = None

    def send_to_running(self, message: str = "show", timeout_ms: int = 800) -> bool:
        """이미 실행 중인 인스턴스가 있으면 메시지를 전달하고 True."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(message.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True

    def listen(self) -> bool:
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self._name):
            # 비정상 종료로 남은 소켓 정리 후 재시도
            QLocalServer.removeServer(self._name)
            if not self._server.listen(self._name):
                log.error("단일 인스턴스 서버 시작 실패: %s", self._server.errorString())
                return False
        self._server.newConnection.connect(self._on_connection)
        return True

    def _on_connection(self) -> None:
        while self._server and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(conn.deleteLater)

    def _read(self, conn: QLocalSocket) -> None:
        msg = bytes(conn.readAll()).decode("utf-8", "ignore").strip()
        if msg:
            self.message_received.emit(msg)
