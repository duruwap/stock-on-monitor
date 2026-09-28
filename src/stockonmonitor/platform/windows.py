"""Windows 전용 기능. 다른 OS에서는 모두 아무 일도 하지 않는다(개발·테스트용)."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from stockonmonitor import meta

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    _shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]

_mutex_handles: list = []


# ── 프로세스 ────────────────────────────────────────────────
def create_app_mutex() -> None:
    """설치 프로그램(Inno Setup)이 실행 중인 앱을 감지할 수 있도록 이름 있는 뮤텍스를 만든다."""
    if not IS_WINDOWS:
        return
    for name in (meta.APP_MUTEX, f"Global\\{meta.APP_MUTEX}"):
        handle = _kernel32.CreateMutexW(None, False, name)
        if handle:
            _mutex_handles.append(handle)


def set_app_user_model_id() -> None:
    """알림(토스트)에 앱 이름·아이콘이 올바르게 표시되도록 설치 바로가기와 같은 ID를 지정."""
    if IS_WINDOWS:
        try:
            _shell32.SetCurrentProcessExplicitAppUserModelID(meta.APP_USER_MODEL_ID)
        except OSError:
            log.debug("AppUserModelID 설정 실패", exc_info=True)


# ── 창 ──────────────────────────────────────────────────────
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


def set_exclude_from_capture(hwnd: int, exclude: bool) -> bool:
    """화면 공유(Teams·Zoom 등)·캡처에서 창을 제외한다. Windows 10 2004 이상."""
    if not IS_WINDOWS or not hwnd:
        return False
    ok = bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE))
    if not ok and exclude:
        log.info("화면 캡처 제외를 지원하지 않는 Windows 버전 (오류 %s)", ctypes.get_last_error())
    return ok


# QUNS_* 값: 3=전체 화면(D3D), 4=프레젠테이션 모드, 2=전체 화면 앱 실행 중(busy)
_FULLSCREEN_STATES = {2, 3, 4}


def is_fullscreen_app_active() -> bool:
    if not IS_WINDOWS:
        return False
    state = ctypes.c_int(0)
    try:
        if _shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except OSError:
        return False
    return state.value in _FULLSCREEN_STATES


# ── 전역 단축키 ─────────────────────────────────────────────
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {"CTRL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "META": MOD_WIN, "WIN": MOD_WIN}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+H' → (modifiers, virtual-key). 지원하지 않는 조합이면 None.

    실수로 일반 타이핑을 가로채지 않도록 Ctrl/Alt/Win 중 하나 이상을 요구한다(F키 제외).
    """
    parts = [p.strip().upper() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[m]

    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        return None

    is_function_key = key.startswith("F") and len(key) > 1
    if not is_function_key and not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None
    return modifiers, vk


def register_hotkey(hwnd: int, hotkey_id: int, text: str) -> bool:
    if not IS_WINDOWS:
        return parse_hotkey(text) is not None
    parsed = parse_hotkey(text)
    if not parsed:
        return False
    mods, vk = parsed
    ok = bool(_user32.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk))
    if not ok:
        log.warning("단축키 %s 등록 실패 (다른 프로그램이 사용 중일 수 있음, 오류 %s)", text, ctypes.get_last_error())
    return ok


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    if IS_WINDOWS:
        _user32.UnregisterHotKey(hwnd, hotkey_id)


def hotkey_id_from_message(message_ptr: int) -> int | None:
    """Qt nativeEventFilter가 넘겨준 MSG 포인터에서 WM_HOTKEY id를 꺼낸다."""
    if not IS_WINDOWS:
        return None
    msg = wintypes.MSG.from_address(message_ptr)
    if msg.message == WM_HOTKEY:
        return int(msg.wParam)
    return None


# ── 자동 실행 ───────────────────────────────────────────────
def autostart_supported() -> bool:
    return IS_WINDOWS and bool(getattr(sys, "frozen", False))


def _autostart_command() -> str:
    return f'"{Path(sys.executable).resolve()}" --autostart'


def is_autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, meta.RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, meta.APP_ID)
            return bool(value)
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not autostart_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, meta.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, meta.APP_ID, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, meta.APP_ID)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("자동 실행 설정 실패")
        return False


def refresh_autostart_path() -> None:
    """앱이 다른 경로로 재설치되었을 때 자동 실행 경로를 현재 실행 파일로 맞춘다."""
    if autostart_supported() and is_autostart_enabled():
        set_autostart(True)


# ── 탐색기 ──────────────────────────────────────────────────
def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        subprocess.Popen(["explorer", str(path)])
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
