"""데이터 폴더 위치 결정.

우선순위
  1. 명령줄 --data-dir
  2. 환경 변수 STOCKONMONITOR_DATA_DIR
  3. 포터블 모드: 실행 파일 옆에 'portable' 파일이 있으면 <exe 폴더>/data
  4. 설치 프로그램이 기록한 레지스트리 값 HKCU\\Software\\StockOnMonitor\\DataDir
  5. 기본값: %APPDATA%\\StockOnMonitor  (Windows 외: ~/.config/StockOnMonitor)

선택된 폴더에 쓸 수 없으면 기본값으로 되돌아간다.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from stockonmonitor import meta


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    source: str  # 어떤 규칙으로 결정되었는지 (진단용)

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def portfolio_file(self) -> Path:
        return self.data_dir / "portfolio.json"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure(self) -> None:
        for d in (self.data_dir, self.backup_dir, self.log_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]  # 저장소 루트


def resource_path(*parts: str) -> Path:
    """번들된 리소스(assets) 경로. PyInstaller 번들과 소스 실행 모두 지원."""
    base = Path(getattr(sys, "_MEIPASS", executable_dir()))
    return base.joinpath(*parts)


def default_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / meta.APP_ID
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / meta.APP_ID


def _registry_data_dir() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, meta.REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, meta.REGISTRY_DATA_DIR_VALUE)
            return str(value) if value else None
    except OSError:
        return None


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_paths(cli_data_dir: str | None = None) -> AppPaths:
    candidates: list[tuple[str | Path | None, str]] = [
        (cli_data_dir, "command-line"),
        (os.environ.get("STOCKONMONITOR_DATA_DIR"), "environment"),
    ]
    if (executable_dir() / "portable").exists():
        candidates.append((executable_dir() / "data", "portable"))
    candidates.append((_registry_data_dir(), "installer"))

    for raw, source in candidates:
        if not raw:
            continue
        path = Path(os.path.expandvars(str(raw))).expanduser()
        if _writable(path):
            return AppPaths(path.resolve(), source)

    return AppPaths(default_data_dir(), "default")
