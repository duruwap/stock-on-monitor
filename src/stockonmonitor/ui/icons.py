"""앱 아이콘을 벡터로 직접 그린다.

- 모든 DPI에서 선명하고, 별도 이미지 플러그인이 필요 없다.
- tools/make_icons.py가 같은 함수로 설치 프로그램용 .ico 파일을 만든다.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# 차트 선의 꼭짓점 (0~1 좌표)
_LINE = [(0.20, 0.66), (0.40, 0.48), (0.55, 0.58), (0.80, 0.32)]


def draw_app_icon(size: int, status_dot: QColor | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    s = float(size)
    inset = max(0.5, s * 0.04)
    rect = QRectF(inset, inset, s - inset * 2, s - inset * 2)
    radius = s * 0.22

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0, QColor("#3A3F47"))
    grad.setColorAt(1, QColor("#1D2025"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, radius, radius)

    # 차트 선
    path = QPainterPath()
    for i, (x, y) in enumerate(_LINE):
        pt = QPointF(rect.left() + rect.width() * x, rect.top() + rect.height() * y)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    pen = QPen(QColor("#E9ECEF"), max(1.4, s * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    # 끝점: 절제된 포인트 색 하나
    end = QPointF(rect.left() + rect.width() * _LINE[-1][0], rect.top() + rect.height() * _LINE[-1][1])
    r = max(1.3, s * 0.075)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#7FA8E8"))
    p.drawEllipse(end, r, r)

    if status_dot is not None:
        d = s * 0.36
        dot = QRectF(s - d - inset * 0.2, s - d - inset * 0.2, d, d)
        p.setBrush(QColor("#1D2025"))
        p.drawEllipse(dot.adjusted(-s * 0.05, -s * 0.05, s * 0.05, s * 0.05))
        p.setBrush(status_dot)
        p.drawEllipse(dot)

    p.end()
    return pm


def app_icon(status_dot: QColor | None = None) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(draw_app_icon(size, status_dot))
    return icon


def _glyph_file(kind: str, color: str, points: list[tuple[float, float]], width: float) -> str:
    """스타일시트용 작은 선 그림(체크·화살표). 임시 폴더에 한 번만 만든다."""
    name = f"stockonmonitor-{kind}-{hashlib.md5(color.encode()).hexdigest()[:8]}.png"
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        size = 30  # 고DPI 대비 2배 크기로 그려 두고 스타일시트에서 축소
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        line = QPainterPath(QPointF(*points[0]))
        for pt in points[1:]:
            line.lineTo(*pt)
        p.drawPath(line)
        p.end()
        pm.save(str(path), "PNG")
    return path.as_posix()


def checkmark_file(color: str) -> str:
    return _glyph_file("check", color, [(7.5, 15.5), (12.5, 20.5), (22.5, 9.5)], 3.6)


def chevron_file(color: str) -> str:
    return _glyph_file("chevron", color, [(8, 11.5), (15, 18.5), (22, 11.5)], 3.0)
