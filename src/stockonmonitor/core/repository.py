"""설정·포트폴리오·상태 파일을 한곳에서 관리한다."""

from __future__ import annotations

import logging

from stockonmonitor.core.models import AppState, Portfolio, Settings
from stockonmonitor.core.storage import JsonDocument
from stockonmonitor.paths import AppPaths

log = logging.getLogger(__name__)

SETTINGS_SCHEMA = 1
PORTFOLIO_SCHEMA = 1
STATE_SCHEMA = 1


class Repository:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        paths.ensure()
        self._settings = JsonDocument(paths.settings_file, SETTINGS_SCHEMA, lambda: Settings().to_dict(),
                                      backup_dir=paths.backup_dir)
        self._portfolio = JsonDocument(paths.portfolio_file, PORTFOLIO_SCHEMA, lambda: Portfolio().to_dict(),
                                       backup_dir=paths.backup_dir, keep_backups=30)
        # 상태 파일은 잃어도 치명적이지 않으므로 백업하지 않는다
        self._state = JsonDocument(paths.state_file, STATE_SCHEMA, lambda: AppState().to_dict())

        self.settings = Settings.from_dict(self._settings.load())
        self.portfolio = Portfolio.from_dict(self._portfolio.load())
        self.state = AppState.from_dict(self._state.load())

        # 파일이 없던 첫 실행이라면 기본값을 바로 기록해 둔다
        for doc, obj in ((self._settings, self.settings), (self._portfolio, self.portfolio)):
            if not doc.path.exists():
                doc.save(obj.to_dict(), backup=False)

    @property
    def recovery_notes(self) -> list[str]:
        notes = []
        for label, doc in (("설정", self._settings), ("종목", self._portfolio)):
            if doc.recovered_from == "default":
                notes.append(f"{label} 파일이 손상되어 초기화했습니다.")
            elif doc.recovered_from:
                notes.append(f"{label} 파일이 손상되어 백업({doc.recovered_from})에서 복원했습니다.")
        return notes

    def save_settings(self) -> None:
        self._safe(self._settings, self.settings.to_dict())

    def save_portfolio(self) -> None:
        self._safe(self._portfolio, self.portfolio.to_dict())

    def save_state(self) -> None:
        self._safe(self._state, self.state.to_dict(), backup=False)

    @staticmethod
    def _safe(doc: JsonDocument, data: dict, backup: bool = True) -> None:
        try:
            doc.save(data, backup=backup)
        except OSError:
            log.exception("%s 저장 실패", doc.path.name)
            raise
