"""파일 로깅과 전역 예외 처리."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from stockonmonitor import meta

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"


def setup_logging(log_dir: Path, debug: bool = False) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)

    # 콘솔이 있는 개발 환경에서만 표준 에러로도 출력
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console)

    logging.getLogger(__name__).info("%s %s 시작", meta.APP_NAME, meta.APP_VERSION)
    return log_file


def install_excepthook(on_fatal: Callable[[str], None] | None = None) -> None:
    """처리되지 않은 예외를 기록하고, 필요하면 사용자에게 한 번만 알린다."""
    log = logging.getLogger("crash")
    notified = {"done": False}

    def handle(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))
        if on_fatal and not notified["done"]:
            notified["done"] = True
            try:
                on_fatal(f"{exc_type.__name__}: {exc}")
            except Exception:  # 알림 실패가 또 다른 크래시로 이어지지 않게
                log.exception("오류 알림 표시 실패")

    def thread_handle(args: threading.ExceptHookArgs):
        log.critical(
            "스레드 %s 예외",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle
    threading.excepthook = thread_handle
