# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 설정. packaging/build.ps1 에서 호출한다.
#
# onefile이 아닌 onedir 방식을 쓰는 이유
#  - onefile은 실행할 때마다 임시 폴더에 압축을 풀어 시작이 느리고, 백신 오탐이 잦다.
#  - 설치 프로그램이 폴더째 배포하므로 onedir이 더 빠르고 안정적이다.

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "build"

# 사용하지 않는 Qt 모듈 (용량 절감)
QT_EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml",
    "PySide6.QtDBus", "PySide6.QtPrintSupport", "PySide6.QtConcurrent", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
]
PY_EXCLUDES = ["tkinter", "unittest", "pydoc", "doctest", "pytest", "PIL", "numpy", "pandas"]

# 번들에서 제외할 대용량 DLL (소프트웨어 OpenGL 등 — 위젯 앱에는 불필요)
DROP_BINARIES = ("opengl32sw.dll", "Qt6Pdf.dll", "Qt6Qml", "Qt6Quick", "Qt6VirtualKeyboard", "d3dcompiler_47.dll")

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "assets" / "app.ico"), "assets")],
    hiddenimports=[],
    excludes=QT_EXCLUDES + PY_EXCLUDES,
    noarchive=False,
    optimize=1,
)

a.binaries = [b for b in a.binaries if not any(tok.lower() in b[0].lower() for tok in DROP_BINARIES)]
# 한국어·영어 이외의 Qt 번역 파일 제외
a.datas = [d for d in a.datas
           if not (d[0].replace("\\", "/").count("/translations/") and d[0].endswith(".qm")
                   and not os.path.basename(d[0]).endswith(("_ko.qm", "_en.qm")))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockOnMonitor",
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(BUILD / "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,          # UPX 압축은 백신 오탐을 늘리므로 사용하지 않음
    debug=False,
    strip=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StockOnMonitor",
)
