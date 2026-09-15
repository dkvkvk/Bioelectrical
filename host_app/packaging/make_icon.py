"""生成软件图标：心电图波形 + 心形轮廓，输出 app_icon.ico / app_icon.png。

只需在改图标时本地跑一次:  python packaging/make_icon.py
产物直接提交入库，云端构建直接使用（CI 不需要跑这个）。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter,
                           QPainterPath, QPixmap, QRadialGradient)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
BG_TOP = QColor("#1e6fd9")
BG_BOTTOM = QColor("#0d3f8f")
WAVE = QColor("#ffffff")
HEART = QColor("#ff5a6e")


def draw(p: QPainter, size: int) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    # 背景圆角渐变
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, BG_TOP)
    grad.setColorAt(1.0, BG_BOTTOM)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    # 心形（上侧，淡淡的）
    s = size
    heart = QPainterPath()
    cx, top, w = s * 0.5, s * 0.16, s * 0.56
    heart.moveTo(cx, s * 0.62)
    heart.cubicTo(cx - w, s * 0.38, cx - w * 0.86, top, cx, s * 0.32)
    heart.cubicTo(cx + w * 0.86, top, cx + w, s * 0.38, cx, s * 0.62)
    p.setBrush(QBrush(HEART))
    p.setOpacity(0.9)
    p.drawPath(heart)
    p.setOpacity(1.0)

    # 心电图折线（穿过中部）
    pts = [(0.06, 0.52), (0.24, 0.52), (0.30, 0.44), (0.36, 0.60),
           (0.43, 0.16), (0.50, 0.82), (0.56, 0.46), (0.63, 0.52),
           (0.94, 0.52)]
    pen_w = max(2.0, s * 0.045)
    from PySide6.QtGui import QPen
    pen = QPen(WAVE, pen_w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(pts[0][0] * s, pts[0][1] * s))
    for x, y in pts[1:]:
        path.lineTo(x * s, y * s)
    p.drawPath(path)


def write_multi_size_ico(base: QPixmap, path: str, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """手工生成多尺寸 .ico（每尺寸内嵌一张PNG，Vista+ 标准格式）。"""
    import struct
    from PySide6.QtCore import QBuffer, QIODevice

    pngs = []
    for s in sizes:
        pm = base.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        pngs.append((s, bytes(buf.data())))
        buf.close()

    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(pngs))          # ICONDIR
    offset = 6 + 16 * len(pngs)
    for s, blob in pngs:
        w = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for _, blob in pngs:
        out += blob
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main() -> None:
    # QPixmap 需要 QGuiApplication 才能使用
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    base = QPixmap(512, 512)
    base.fill(Qt.transparent)
    p = QPainter(base)
    draw(p, 512)
    p.end()
    base.save(os.path.join(OUT_DIR, "app_icon.png"))
    write_multi_size_ico(base, os.path.join(OUT_DIR, "app_icon.ico"))
    print("saved:", OUT_DIR)
    app.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
