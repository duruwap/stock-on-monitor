"""애플리케이션 진입점과 전체 흐름 제어.

실행 순서
  1. 중복 실행 확인 → 이미 실행 중이면 기존 창을 띄우고 종료
  2. 데이터 폴더·로그·예외 처리 준비
  3. 설정/종목 로드 → 위젯·트레이 아이콘·시세 서비스 시작
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QProgressDialog, QStyleFactory, QSystemTrayIcon

from stockonmonitor import meta
from stockonmonitor.core import formatting as fmt
from stockonmonitor.core.models import Holding, Settings, Snapshot
from stockonmonitor.core.repository import Repository
from stockonmonitor.core.valuation import build_positions, summarize
from stockonmonitor.logging_setup import install_excepthook, setup_logging
from stockonmonitor.paths import AppPaths, resolve_paths
from stockonmonitor.platform import windows
from stockonmonitor.providers.client import MarketDataClient
from stockonmonitor.services import alerts, updater
from stockonmonitor.services.hotkey import GlobalHotkey
from stockonmonitor.services.quote_service import QuoteService
from stockonmonitor.services.single_instance import SingleInstance
from stockonmonitor.ui import theme
from stockonmonitor.ui.icons import app_icon
from stockonmonitor.ui.widget import FloatingWidget

log = logging.getLogger(__name__)

UPDATE_CHECK_DELAY_MS = 20_000
UPDATE_CHECK_INTERVAL_MS = 12 * 3600 * 1000
FULLSCREEN_POLL_MS = 2_000


class Controller(QObject):
    def __init__(self, app: QApplication, paths: AppPaths, repo: Repository, autostarted: bool) -> None:
        super().__init__()
        self.app = app
        self.paths = paths
        self.repo = repo
        self.settings: Settings = repo.settings
        self.autostarted = autostarted
        self.client = MarketDataClient()
        self._snapshot: Snapshot | None = None
        self._auto_hidden = False
        self._portfolio_dialog = None
        self._settings_dialog = None
        self._offline = False
        self._manual_update_check = False

        self._icon = app_icon()
        self._icon_warn = app_icon(theme.widget_tokens(True, "kr").warning)
        app.setWindowIcon(self._icon)
        self._apply_theme()

        # 위젯
        self.widget = FloatingWidget(self.settings)
        self.widget.context_menu_requested.connect(self._show_menu_at)
        self.widget.open_portfolio_requested.connect(self.open_portfolio)
        self.widget.position_changed.connect(self._remember_position)
        self.widget.set_data(build_positions(self.repo.portfolio.visible, {}), None, None, None, None)
        self.widget.restore_position(self.repo.state.widget_pos)

        # 트레이
        self.menu = QMenu()
        self._build_menu()
        self.tray = QSystemTrayIcon(self._icon, self)
        self.tray.setToolTip(meta.APP_NAME)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._tray_click_timer = QTimer(self, singleShot=True, timeout=self.toggle_widget)
        self._tray_click_timer.setInterval(QApplication.doubleClickInterval())

        # 시세
        self.quotes = QuoteService(self.client, self)
        self.quotes.snapshot_ready.connect(self._on_snapshot)
        self.quotes.set_interval(self.settings.refresh_seconds)

        # 전역 단축키
        self.hotkey = GlobalHotkey(self)
        self.hotkey.activated.connect(self.toggle_widget)
        if self.settings.hotkey and not self.hotkey.set_hotkey(self.settings.hotkey):
            QTimer.singleShot(3000, lambda: self._notify(
                "단축키를 사용할 수 없습니다",
                f"{self.settings.hotkey} 는 다른 프로그램이 사용 중입니다. 설정에서 바꿔 주세요."))

        # 업데이트
        self.updater = updater.Updater(self)
        self.updater.update_available.connect(self._on_update_available)
        self.updater.check_finished.connect(self._on_update_checked)
        self.updater.download_progress.connect(self._on_download_progress)
        self.updater.download_finished.connect(self._on_download_finished)
        self.updater.download_failed.connect(self._on_download_failed)
        self._progress: QProgressDialog | None = None
        self._update_timer = QTimer(self, timeout=self._auto_update_check)
        self._update_timer.start(UPDATE_CHECK_INTERVAL_MS)
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self._auto_update_check)

        # 전체 화면 감지
        self._fullscreen_timer = QTimer(self, timeout=self._check_fullscreen)
        if windows.IS_WINDOWS:
            self._fullscreen_timer.start(FULLSCREEN_POLL_MS)

        # 시스템 이벤트
        hints = app.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _s: self._on_system_theme_changed())
        app.screenAdded.connect(lambda _s: QTimer.singleShot(500, self.widget.ensure_on_screen))
        app.screenRemoved.connect(lambda _s: QTimer.singleShot(500, self.widget.ensure_on_screen))
        app.aboutToQuit.connect(self._shutdown)
        app.commitDataRequest.connect(lambda _m: self._persist_state())

    # ── 시작 ───────────────────────────────────────────────
    def start(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self._apply_widget_visibility()
        self.quotes.set_holdings(self.repo.portfolio.visible)
        self.quotes.start()
        windows.refresh_autostart_path()

        for note in self.repo.recovery_notes:
            self._notify("데이터 복구", note)

        if not self.repo.state.first_run_done:
            self.repo.state.first_run_done = True
            self._persist_state()
            QTimer.singleShot(800, self._first_run)

    def _first_run(self) -> None:
        self._notify(f"{meta.APP_NAME} 실행 중",
                     "작업 표시줄 오른쪽 아래 아이콘에서 언제든 열 수 있습니다. "
                     "아이콘이 안 보이면 ^ 버튼(숨겨진 아이콘)을 확인하세요.")
        if not self.repo.portfolio.holdings:
            self.open_portfolio()

    # ── 메뉴 ───────────────────────────────────────────────
    def _build_menu(self) -> None:
        m = self.menu
        m.clear()
        self.act_visible = QAction("위젯 표시", m, checkable=True)
        self.act_visible.triggered.connect(self.set_widget_visible)
        self.act_mask = QAction("금액 숨기기", m, checkable=True)
        self.act_mask.triggered.connect(lambda on: self._update_setting(hide_amounts=on))
        self.act_lock = QAction("위치 잠금", m, checkable=True)
        self.act_lock.triggered.connect(lambda on: self._update_setting(locked=on))
        act_refresh = QAction("지금 새로고침", m)
        act_refresh.triggered.connect(self.quotes_refresh)

        act_portfolio = QAction("종목 관리…", m)
        act_portfolio.triggered.connect(self.open_portfolio)
        act_settings = QAction("설정…", m)
        act_settings.triggered.connect(lambda: self.open_settings())

        self.act_update = QAction("", m)
        self.act_update.triggered.connect(self._install_update)
        self.act_update.setVisible(False)
        act_about = QAction("정보", m)
        act_about.triggered.connect(lambda: self.open_settings(page="about"))
        act_quit = QAction("종료", m)
        act_quit.triggered.connect(self.quit)

        for a in (self.act_visible, self.act_mask, self.act_lock, act_refresh, None,
                  act_portfolio, act_settings, None, self.act_update, act_about, None, act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m.aboutToShow.connect(self._sync_menu)

    def _sync_menu(self) -> None:
        self.act_visible.setChecked(self.repo.state.widget_visible)
        hk = self.hotkey.current
        self.act_visible.setText(f"위젯 표시\t{hk}" if hk else "위젯 표시")
        self.act_mask.setChecked(self.settings.hide_amounts)
        self.act_lock.setChecked(self.settings.locked)

    def _show_menu_at(self, pos: QPoint) -> None:
        self._sync_menu()
        self.menu.popup(pos)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_click_timer.start()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_click_timer.stop()
            self.set_widget_visible(True)
            self.open_portfolio()

    # ── 위젯 표시 ──────────────────────────────────────────
    def toggle_widget(self) -> None:
        self.set_widget_visible(not self.repo.state.widget_visible)

    def set_widget_visible(self, visible: bool) -> None:
        self.repo.state.widget_visible = bool(visible)
        self._persist_state()
        self._apply_widget_visibility()

    def show_from_second_launch(self) -> None:
        """바탕화면 아이콘을 다시 실행한 경우: 위젯을 보이고 종목 관리 창을 연다."""
        self.set_widget_visible(True)
        if not self.repo.portfolio.holdings:
            self.open_portfolio()
        else:
            self._notify(meta.APP_NAME, "이미 실행 중입니다. 작업 표시줄 오른쪽 아래 아이콘을 이용하세요.")

    def _apply_widget_visibility(self) -> None:
        show = self.repo.state.widget_visible and not self._auto_hidden
        if show and not self.widget.isVisible():
            self.widget.show()
            self.widget.ensure_on_screen()
        elif not show and self.widget.isVisible():
            self.widget.hide()

    def _check_fullscreen(self) -> None:
        hidden = self.settings.hide_when_fullscreen and windows.is_fullscreen_app_active()
        if hidden != self._auto_hidden:
            self._auto_hidden = hidden
            self._apply_widget_visibility()

    def _remember_position(self, pos: QPoint) -> None:
        self.repo.state.widget_pos = [pos.x(), pos.y()]
        self._persist_state()

    # ── 시세 ───────────────────────────────────────────────
    def quotes_refresh(self) -> None:
        self.quotes.refresh_now()

    def _on_snapshot(self, snap: Snapshot) -> None:
        self._snapshot = snap
        if snap.fx_usdkrw:
            self.repo.state.last_fx_usdkrw = snap.fx_usdkrw
        fx = snap.fx_usdkrw or self.repo.state.last_fx_usdkrw

        holdings = self.repo.portfolio.visible
        positions = build_positions(holdings, snap.quotes)
        summary = summarize(positions, fx)
        self.widget.set_data(positions, summary, snap.fetched_at, fx, snap.error)

        offline = snap.error is not None
        if offline != self._offline:
            self._offline = offline
            self.tray.setIcon(self._icon_warn if offline else self._icon)

        tip = [meta.APP_NAME]
        if not summary.is_empty:
            # 트레이 툴팁은 금액 없이 비율만 (옆 사람이 봐도 무방하게)
            tip.append(f"수익률 {fmt.pct(summary.profit_pct)} · 오늘 {fmt.pct(summary.day_change_pct)}")
        tip.append("연결 확인 필요" if offline else f"{snap.fetched_at:%H:%M} 갱신")
        self.tray.setToolTip("\n".join(tip))

        fired = alerts.evaluate(self.repo.portfolio.holdings, snap.quotes, self.settings, self.repo.state)
        for a in fired[:3]:  # 한꺼번에 너무 많이 띄우지 않는다
            self._notify(a.title, a.message)
        if fired or snap.fx_usdkrw:
            self._persist_state()

    # ── 대화상자 ───────────────────────────────────────────
    def open_portfolio(self) -> None:
        if self._portfolio_dialog is not None:
            self._raise(self._portfolio_dialog)
            return
        from stockonmonitor.ui.portfolio_dialog import PortfolioDialog

        dlg = PortfolioDialog(self.repo.portfolio.holdings, self.client)
        dlg.saved.connect(self._on_portfolio_saved)
        dlg.finished.connect(lambda _r: setattr(self, "_portfolio_dialog", None))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._portfolio_dialog = dlg
        self._raise(dlg)

    def _on_portfolio_saved(self, holdings: list[Holding]) -> None:
        self.repo.portfolio.holdings = holdings
        try:
            self.repo.save_portfolio()
        except OSError as exc:
            QMessageBox.critical(None, "저장 실패", f"종목을 저장하지 못했습니다.\n{exc}")
            return
        self.quotes.set_holdings(self.repo.portfolio.visible)
        snap = self._snapshot
        self.widget.set_data(build_positions(self.repo.portfolio.visible, snap.quotes if snap else {}),
                             None, snap.fetched_at if snap else None, None, None)
        if holdings and not self.repo.state.widget_visible:
            self.set_widget_visible(True)

    def open_settings(self, page: str | int = 0) -> None:
        from stockonmonitor.ui.settings_dialog import PAGE_ABOUT, SettingsDialog

        index = PAGE_ABOUT if page == "about" else int(page)
        if self._settings_dialog is not None:
            self._settings_dialog.nav.setCurrentRow(index)
            self._raise(self._settings_dialog)
            return
        dlg = SettingsDialog(
            self.settings,
            data_dir=str(self.paths.data_dir),
            log_dir=str(self.paths.log_dir),
            hotkey_validator=self._try_hotkey,
            on_open_folder=lambda p: windows.open_folder(Path(p)),
            on_check_update=self._manual_update if updater.is_enabled() else None,
            page=index,
        )
        dlg.applied.connect(self._on_settings_applied)
        dlg.finished.connect(lambda _r: setattr(self, "_settings_dialog", None))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._settings_dialog = dlg
        self._raise(dlg)

    @staticmethod
    def _raise(dlg) -> None:
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _try_hotkey(self, text: str) -> bool:
        previous = self.hotkey.current
        if self.hotkey.set_hotkey(text):
            return True
        if previous:
            self.hotkey.set_hotkey(previous)
        return False

    def _on_settings_applied(self, new: Settings, autostart: bool) -> None:
        if windows.autostart_supported() and autostart != windows.is_autostart_enabled():
            windows.set_autostart(autostart)
        if new.hotkey != self.hotkey.current:
            self._try_hotkey(new.hotkey)
        self._apply_settings(new)

    def _update_setting(self, **changes) -> None:
        from dataclasses import replace

        self._apply_settings(replace(self.settings, **changes).normalized())

    def _apply_settings(self, new: Settings) -> None:
        old = self.settings
        self.settings = self.repo.settings = new
        try:
            self.repo.save_settings()
        except OSError as exc:
            self._notify("설정 저장 실패", str(exc))
        if new.theme != old.theme:
            self._apply_theme()
        self.widget.apply_settings(new)
        if new.refresh_seconds != old.refresh_seconds:
            self.quotes.set_interval(new.refresh_seconds)
        if not new.hide_when_fullscreen and self._auto_hidden:
            self._auto_hidden = False
            self._apply_widget_visibility()

    def _apply_theme(self) -> None:
        dark = theme.resolve_dark(self.settings.theme)
        theme.apply_app_palette(dark)

    def _on_system_theme_changed(self) -> None:
        if self.settings.theme == "system":
            self._apply_theme()
            self.widget.apply_settings(self.settings)

    # ── 업데이트 ───────────────────────────────────────────
    def _auto_update_check(self) -> None:
        if self.settings.check_updates and updater.is_enabled():
            self.repo.state.last_update_check = time.time()
            self.updater.check()

    def _manual_update(self) -> None:
        self._manual_update_check = True
        self.updater.check()

    def _on_update_checked(self, _has_update: bool, message: str) -> None:
        if self._manual_update_check:
            self._manual_update_check = False
            QMessageBox.information(self._settings_dialog, "업데이트 확인", message)

    def _on_update_available(self, info: updater.UpdateInfo) -> None:
        self.act_update.setText(f"업데이트 설치 ({info.version})")
        self.act_update.setVisible(True)
        if self.repo.state.notified_version != info.version:
            self.repo.state.notified_version = info.version
            self._persist_state()
            self._notify("새 버전을 사용할 수 있습니다",
                         f"{info.version} — 트레이 메뉴의 '업데이트 설치'를 눌러 설치하세요.")

    def _install_update(self) -> None:
        info = self.updater.latest
        if not info:
            return
        notes = f"\n\n{info.notes}" if info.notes else ""
        if QMessageBox.question(None, "업데이트 설치",
                                f"{meta.APP_NAME} {info.version} 을(를) 설치할까요?{notes}\n\n"
                                "설치하는 동안 잠시 종료되었다가 자동으로 다시 실행됩니다.") \
                != QMessageBox.StandardButton.Yes:
            return
        if self._progress is not None:
            return  # 이미 내려받는 중
        self._progress = QProgressDialog("업데이트를 내려받는 중…", "취소", 0, 100)
        self._progress.setWindowTitle("업데이트")
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.canceled.connect(self.updater.cancel)
        self._progress.show()
        self.updater.download(info)

    def _on_download_progress(self, value: int) -> None:
        if self._progress is not None:
            self._progress.setValue(value)

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _on_download_finished(self, path: str) -> None:
        self._close_progress()
        if updater.launch_installer(path):
            self.quit()
        else:
            QMessageBox.warning(None, "업데이트", "설치 프로그램을 실행하지 못했습니다.")

    def _on_download_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.warning(None, "업데이트", f"업데이트를 내려받지 못했습니다.\n{message}")

    # ── 공통 ───────────────────────────────────────────────
    def _notify(self, title: str, message: str) -> None:
        if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, self._icon, 6000)
        else:
            log.info("알림: %s — %s", title, message)

    def _persist_state(self) -> None:
        try:
            self.repo.save_state()
        except OSError:
            pass  # 상태 파일은 저장 실패해도 치명적이지 않음

    def quit(self) -> None:
        QCoreApplication.quit()

    def _shutdown(self) -> None:
        log.info("종료")
        self.quotes.stop()
        self.hotkey.clear()
        self._persist_state()
        self.tray.hide()


# ─────────────────────────────────────────────────────────────
def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog=meta.APP_EXE_NAME, add_help=True)
    p.add_argument("--autostart", action="store_true", help="Windows 시작 시 자동 실행된 경우")
    p.add_argument("--data-dir", help="데이터 폴더 경로 지정")
    p.add_argument("--reset-position", action="store_true", help="위젯 위치 초기화")
    p.add_argument("--debug", action="store_true", help="자세한 로그 기록")
    p.add_argument("--version", action="version", version=f"{meta.APP_NAME} {meta.APP_VERSION}")
    args, _unknown = p.parse_known_args(argv)
    return args


def _install_translations(app: QApplication) -> None:
    """표준 대화상자 버튼(예/아니요/저장/취소 등)을 한국어로."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    QLocale.setDefault(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))
    translator = QTranslator(app)
    candidates = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    import PySide6

    candidates.append(str(Path(PySide6.__file__).parent / "translations"))
    for directory in candidates:
        if translator.load("qtbase_ko", directory):
            app.installTranslator(translator)
            return
    log.debug("Qt 한국어 번역 파일을 찾지 못함")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    windows.set_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setApplicationName(meta.APP_ID)
    QApplication.setOrganizationName(meta.APP_PUBLISHER)
    QApplication.setApplicationVersion(meta.APP_VERSION)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(theme.ui_font(9))
    _install_translations(app)

    instance = SingleInstance()
    if instance.send_to_running("show"):
        return 0

    paths = resolve_paths(args.data_dir)
    try:
        paths.ensure()
        setup_logging(paths.log_dir, debug=args.debug)
    except OSError as exc:
        QMessageBox.critical(None, meta.APP_NAME, f"데이터 폴더를 만들 수 없습니다.\n{paths.data_dir}\n\n{exc}")
        return 1
    log.info("데이터 폴더: %s (%s)", paths.data_dir, paths.source)

    install_excepthook(lambda msg: QMessageBox.warning(
        None, meta.APP_NAME, f"예기치 못한 오류가 발생했습니다. 작업은 계속됩니다.\n\n{msg}\n\n"
                             f"로그: {paths.log_dir}"))
    windows.create_app_mutex()
    instance.listen()

    try:
        repo = Repository(paths)
    except OSError as exc:
        log.exception("데이터 로드 실패")
        QMessageBox.critical(None, meta.APP_NAME, f"데이터를 불러오지 못했습니다.\n{exc}")
        return 1
    if args.reset_position:
        repo.state.widget_pos = None

    controller = Controller(app, paths, repo, autostarted=args.autostart)
    instance.message_received.connect(lambda _m: controller.show_from_second_launch())
    controller.start()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("시스템 트레이를 사용할 수 없는 환경")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
