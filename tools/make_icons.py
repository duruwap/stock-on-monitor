"""앱 아이콘(.ico/.png)과 설치 마법사 이미지를 생성한다.

런타임 아이콘과 같은 그리기 코드(ui/icons.py)를 사용하므로 모양이 항상 일치한다.
아이콘 디자인을 바꾼 뒤에만 실행하면 된다. (결과물은 저장소에 커밋)

    pip install pillow
    python tools/make_icons.py
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap  # noqa: E402

from stockonmonitor.ui.icons import draw_app_icon  # noqa: E402

ASSETS = ROOT / "assets"
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def to_pil(pm: QPixmap) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def wizard_image(w: int, h: int, icon: int) -> Image.Image:
    pm = QPixmap(w, h)
    pm.fill(QColor("#FFFFFF"))
    p = QPainter(pm)
    p.drawPixmap((w - icon) // 2, (h - icon) // 2, draw_app_icon(icon))
    p.end()
    return to_pil(pm).convert("RGB")


def main() -> None:
    QGuiApplication([])
    ASSETS.mkdir(exist_ok=True)
    images = {s: to_pil(draw_app_icon(s)) for s in ICO_SIZES}
    images[256].save(ASSETS / "app.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                     append_images=[images[s] for s in ICO_SIZES[:-1]])
    images[256].save(ASSETS / "app.png")
    # Inno Setup 마법사 오른쪽 위 작은 이미지 (100%/200% 배율)
    wizard_image(55, 55, 48).save(ASSETS / "wizard-small.bmp")
    wizard_image(110, 110, 96).save(ASSETS / "wizard-small-200.bmp")
    print("생성 완료:", ", ".join(p.name for p in sorted(ASSETS.iterdir())))


if __name__ == "__main__":
    main()
