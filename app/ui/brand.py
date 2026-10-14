"""MarkAssist brand: name, tagline, and the QPainter-drawn logomark.

The mark is a teacher's tick in a teal tile whose final stroke ends with a
short amber tail - the assistant finishing the stroke alongside the teacher,
never instead. Drawn with QPainter (no image assets, no SVG plugin needed) so
it renders crisply at any size for sidebars, the login card, and window icons.
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap

APP_NAME = "MarkAssist"
TAGLINE = "Marking, review & results - with a second pair of eyes."

_TEAL_TOP = "#14B8A6"
_TEAL_BOTTOM = "#0D9488"
_AMBER = "#FBBF24"


def logo_pixmap(size: int = 44) -> QPixmap:
    """The square logomark at the given pixel size."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(_TEAL_TOP))
    gradient.setColorAt(1.0, QColor(_TEAL_BOTTOM))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.26
    painter.drawRoundedRect(0, 0, size, size, radius, radius)

    def point(x: float, y: float) -> QPointF:
        return QPointF(x * size / 46.0, y * size / 46.0)

    stroke = max(2.0, size * 0.1)
    tick_pen = QPen(QColor("#FFFFFF"), stroke)
    tick_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    tick_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(tick_pen)
    painter.drawPolyline([point(11, 24), point(19, 32), point(35, 14)])

    tail_pen = QPen(QColor(_AMBER), stroke)
    tail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(tail_pen)
    painter.drawLine(point(19, 32), point(21.5, 37.5))

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        icon.addPixmap(logo_pixmap(size))
    return icon
