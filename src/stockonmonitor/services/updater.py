"""자동 업데이트.

배포 사이트에 올려 둔 latest.json(매니페스트)을 확인하고, 새 버전이 있으면
설치 파일을 내려받아 SHA-256을 검증한 뒤 조용히(/SILENT) 설치한다.
설치 프로그램은 앱이 종료되기를 기다렸다가 파일을 교체하고, 끝나면 앱을 다시 실행한다.

latest.json 형식 (packaging/build.ps1이 자동 생성):
{
  "version": "2.0.1",
  "url": "https://example.com/download/StockOnMonitor-Setup-2.0.1.exe",
  "sha256": "…64자리 16진수…",
  "notes": "변경 사항 요약",
  "published": "2026-10-01"
}
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from stockonmonitor import meta
from stockonmonitor.providers.http import HttpError, get_json, open_stream

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = meta.APP_VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def parse_manifest(data: object) -> UpdateInfo:
    if not isinstance(data, dict):
        raise ValueError("매니페스트 형식 오류")
    version = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    sha = str(data.get("sha256", "")).strip().lower()
    if not version or not url.startswith("https://"):
        raise ValueError("매니페스트에 버전 또는 https 다운로드 주소가 없음")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("매니페스트의 sha256 값이 올바르지 않음")
    return UpdateInfo(version, url, sha, str(data.get("notes", "")).strip())


def is_enabled() -> bool:
    return meta.UPDATE_MANIFEST_URL.startswith("https://")


class Updater(QObject):
    update_available = Signal(object)     # UpdateInfo
    check_finished = Signal(bool, str)    # (새 버전 있음, 메시지) — 수동 확인 결과 표시용
    download_progress = Signal(int)       # 0~100
    download_finished = Signal(str)       # 설치 파일 경로
    download_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.latest: UpdateInfo | None = None
        self._cancel = threading.Event()

    def check(self) -> None:
        if not is_enabled():
            self.check_finished.emit(False, "업데이트 서버가 설정되지 않았습니다.")
            return

        def work():
            try:
                info = parse_manifest(get_json(meta.UPDATE_MANIFEST_URL, timeout=10))
            except (HttpError, ValueError) as exc:
                log.info("업데이트 확인 실패: %s", exc)
                self.check_finished.emit(False, f"업데이트를 확인하지 못했습니다.\n{exc}")
                return
            if is_newer(info.version):
                self.latest = info
                self.update_available.emit(info)
                self.check_finished.emit(True, f"새 버전 {info.version}을(를) 사용할 수 있습니다.")
            else:
                self.check_finished.emit(False, f"최신 버전({meta.APP_VERSION})을 사용 중입니다.")

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def download(self, info: UpdateInfo) -> None:
        self._cancel.clear()

        def work():
            try:
                path = self._download(info, self.download_progress.emit)
            except Exception as exc:
                log.warning("업데이트 다운로드 실패: %s", exc)
                self.download_failed.emit(str(exc))
                return
            self.download_finished.emit(str(path))

        threading.Thread(target=work, daemon=True, name="update-download").start()

    def cancel(self) -> None:
        self._cancel.set()

    def _download(self, info: UpdateInfo, progress: Callable[[int], None]) -> Path:
        target_dir = Path(tempfile.gettempdir()) / f"{meta.APP_ID}-update"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{meta.APP_ID}-Setup-{info.version}.exe"

        digest = hashlib.sha256()
        with open_stream(info.url) as resp, open(target, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(256 * 1024):
                if self._cancel.is_set():
                    raise RuntimeError("사용자가 취소했습니다.")
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total:
                    progress(min(99, done * 100 // total))

        if digest.hexdigest() != info.sha256:
            target.unlink(missing_ok=True)
            raise RuntimeError("다운로드한 파일의 무결성 검증(SHA-256)에 실패했습니다.")
        progress(100)
        return target


def launch_installer(path: str) -> bool:
    """설치 프로그램을 조용히 실행한다. 호출한 쪽은 곧바로 앱을 종료해야 한다."""
    from PySide6.QtCore import QProcess

    log_file = Path(tempfile.gettempdir()) / f"{meta.APP_ID}-update.log"
    args = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={log_file}"]
    result = QProcess.startDetached(path, args)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    log.info("업데이트 설치 프로그램 실행 %s: %s", "성공" if ok else "실패", path)
    return bool(ok)

