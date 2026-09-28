"""손상에 강한 JSON 파일 저장소.

- 원자적 쓰기: 임시 파일에 쓰고 fsync 후 os.replace → 전원이 꺼져도 반쪽짜리 파일이 남지 않음
- 스키마 버전: 모든 파일에 "schema_version"을 기록하고, 읽을 때 순차 마이그레이션
- 손상 복구: 파싱 실패 시 원본을 *.corrupt-<시각>으로 보존하고 최신 백업에서 복원
- 일일 백업: 하루 한 번 스냅숏을 backups/에 남기고 오래된 것은 정리
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

Migration = Callable[[dict], dict]


class JsonDocument:
    """하나의 JSON 파일을 관리한다. 메인 스레드에서만 사용한다."""

    def __init__(
        self,
        path: Path,
        schema_version: int,
        default: Callable[[], dict],
        backup_dir: Path | None = None,
        migrations: dict[int, Migration] | None = None,
        keep_backups: int = 14,
    ) -> None:
        self.path = path
        self.schema_version = schema_version
        self._default = default
        self.backup_dir = backup_dir
        self.migrations = migrations or {}
        self.keep_backups = keep_backups
        self.recovered_from: str | None = None  # 복구가 일어났다면 사용자에게 알리기 위함

    # ── 읽기 ────────────────────────────────────────────────
    def load(self) -> dict:
        if not self.path.exists():
            return self._fresh()
        try:
            data = self._read(self.path)
        except (OSError, ValueError) as exc:
            log.error("%s 읽기 실패: %s", self.path.name, exc)
            self._quarantine()
            data = self._restore_from_backup()
            if data is None:
                self.recovered_from = "default"
                return self._fresh()
        return self._migrate(data)

    def _fresh(self) -> dict:
        data = self._default()
        data["schema_version"] = self.schema_version
        return data

    @staticmethod
    def _read(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("최상위 값이 객체가 아님")
        return data

    def _quarantine(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, target)
            log.warning("손상된 파일을 %s 로 보존", target.name)
        except OSError:
            log.exception("손상 파일 격리 실패")

    def _restore_from_backup(self) -> dict | None:
        for backup in self._backups():
            try:
                data = self._read(backup)
            except (OSError, ValueError):
                continue
            log.warning("%s 를 백업 %s 에서 복원", self.path.name, backup.name)
            self.recovered_from = backup.name
            self.save(data, backup=False)
            return data
        return None

    def _migrate(self, data: dict) -> dict:
        version = int(data.get("schema_version", 1) or 1)
        if version > self.schema_version:
            # 새 버전 앱이 만든 파일 — 모르는 필드는 모델 계층이 무시한다
            log.warning("%s 스키마 %s 가 현재 %s 보다 새로움", self.path.name, version, self.schema_version)
            return data
        while version < self.schema_version:
            step = self.migrations.get(version)
            if step:
                data = step(data)
            version += 1
            data["schema_version"] = version
            log.info("%s 스키마를 %s 로 마이그레이션", self.path.name, version)
        return data

    # ── 쓰기 ────────────────────────────────────────────────
    def save(self, data: dict[str, Any], backup: bool = True) -> None:
        data = dict(data)
        data["schema_version"] = max(self.schema_version, int(data.get("schema_version", 0) or 0))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)

        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        if backup:
            self._daily_backup(payload)

    @staticmethod
    def _replace_with_retry(src: str, dst: Path) -> None:
        # Windows에서 백신·검색 인덱서가 파일을 잠깐 잡고 있으면 PermissionError가 난다.
        for attempt in range(5):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _backups(self) -> list[Path]:
        if not self.backup_dir or not self.backup_dir.exists():
            return []
        pattern = f"{self.path.stem}-*.json"
        return sorted(self.backup_dir.glob(pattern), reverse=True)

    def _daily_backup(self, payload: str) -> None:
        if not self.backup_dir:
            return
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y%m%d")
            target = self.backup_dir / f"{self.path.stem}-{today}.json"
            target.write_text(payload, encoding="utf-8")
            for old in self._backups()[self.keep_backups:]:
                old.unlink(missing_ok=True)
        except OSError:
            log.exception("백업 실패 (%s)", self.path.name)
