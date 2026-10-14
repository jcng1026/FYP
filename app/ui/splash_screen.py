"""MarkAssist boot splash: the tick draws itself.

A frameless charcoal card appears while the application does its real
start-up work (database init, self-check, interface imports). The teal tile
fades in, the white tick strokes itself along its path, the amber tail
flicks in last, then the wordmark fades up - the same anatomy, colours and
geometry as the brand logomark in app/ui/brand.py.

Honest by design: the status line shows the actual start-up step, the
animation only masks latency that exists anyway, and any click skips it.
"""

from PySide6.QtCore import QElapsedTimer, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui import brand

# Timeline (milliseconds from show) - a deliberate 3-second boot moment.
_TILE_END = 600          # tile fade + scale in
_TICK_END = 2000         # white tick draws on
_TAIL_END = 2350         # amber tail draws on
_TEXT_END = 3000         # wordmark + tagline fade in; minimum display time

_CARD_WIDTH, _CARD_HEIGHT = 460, 400
_LOGO_SIZE = 120

# Tick geometry in the brand's 46x46 viewbox (see brand.logo_pixmap).
_TICK_POINTS = [(11.0, 24.0), (19.0, 32.0), (35.0, 14.0)]
_TAIL_START, _TAIL_END_POINT = (19.0, 32.0), (21.5, 37.5)


def _partial_polyline(points, fraction):
    """The leading `fraction` (0..1) of a polyline, by arc length."""
    if fraction >= 1.0:
        return [QPointF(x, y) for x, y in points]
    lengths = []
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        lengths.append(seg)
        total += seg
    remaining = total * max(0.0, fraction)
    out = [QPointF(*points[0])]
    for (x1, y1), (x2, y2), seg in zip(points, points[1:], lengths):
        if remaining <= 0:
            break
        if remaining >= seg:
            out.append(QPointF(x2, y2))
            remaining -= seg
        else:
            t = remaining / seg
            out.append(QPointF(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            remaining = 0
    return out


class SplashScreen(QWidget):
    """Show immediately, call set_status() between real start-up steps, then
    finish(callback) - the callback runs after the minimum display time and a
    short fade-out. Any click skips straight to the end."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_CARD_WIDTH, _CARD_HEIGHT)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(available.x() + (available.width() - _CARD_WIDTH) // 2,
                      available.y() + (available.height() - _CARD_HEIGHT) // 2)

        self._status = "Starting MarkAssist..."
        self._skipped = False
        self._fade: QPropertyAnimation | None = None
        self._clock = QElapsedTimer()
        self._clock.start()
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self.update)
        self._frame_timer.start()

    # --- public API ----------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status = text
        self.update()

    def finish(self, on_done) -> None:
        """Fade out once the minimum display time has passed (immediately if
        the user clicked to skip), then invoke on_done."""
        delay = 0 if self._skipped else max(0, _TEXT_END - self._clock.elapsed())

        def start_fade() -> None:
            self._frame_timer.stop()
            fade = QPropertyAnimation(self, b"windowOpacity", self)
            fade.setDuration(280)
            fade.setStartValue(1.0)
            fade.setEndValue(0.0)

            def done() -> None:
                self.close()
                on_done()

            fade.finished.connect(done)
            self._fade = fade
            fade.start()

        QTimer.singleShot(delay, start_fade)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._skipped = True
        self.update()

    # --- painting ------------------------------------------------------------

    def _elapsed(self) -> int:
        return _TEXT_END if self._skipped else self._clock.elapsed()

    @staticmethod
    def _phase(elapsed: int, start: int, end: int) -> float:
        if elapsed <= start:
            return 0.0
        if elapsed >= end:
            return 1.0
        return (elapsed - start) / (end - start)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        elapsed = self._elapsed()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Card: charcoal with the brand's hairline top highlight.
        card = QRectF(0, 0, _CARD_WIDTH, _CARD_HEIGHT)
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(QColor("#3A3A3A"))
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 18, 18)

        # --- Phase 1: teal tile fades + scales in ---
        tile_fraction = self._phase(elapsed, 0, _TILE_END)  # 3s total timeline
        eased = 1 - (1 - tile_fraction) ** 3  # ease-out cubic
        size = _LOGO_SIZE * (0.85 + 0.15 * eased)
        center_x, tile_top = _CARD_WIDTH / 2, 72
        tile = QRectF(center_x - size / 2, tile_top + (_LOGO_SIZE - size) / 2, size, size)
        painter.setOpacity(eased)
        gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
        gradient.setColorAt(0.0, QColor("#14B8A6"))
        gradient.setColorAt(1.0, QColor("#0D9488"))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tile, size * 0.26, size * 0.26)

        # --- Phase 2: the tick strokes itself along its path ---
        def to_tile(point: QPointF) -> QPointF:
            return QPointF(tile.x() + point.x() * size / 46.0,
                           tile.y() + point.y() * size / 46.0)

        stroke = max(2.0, size * 0.1)
        tick_fraction = self._phase(elapsed, _TILE_END, _TICK_END)
        if tick_fraction > 0:
            pen = QPen(QColor("#FFFFFF"), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline([to_tile(p) for p in _partial_polyline(_TICK_POINTS, tick_fraction)])

        # --- Phase 3: the amber tail flicks in ---
        tail_fraction = self._phase(elapsed, _TICK_END, _TAIL_END)
        if tail_fraction > 0:
            pen = QPen(QColor("#FBBF24"), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            segment = _partial_polyline([_TAIL_START, _TAIL_END_POINT], tail_fraction)
            if len(segment) == 2:
                painter.drawLine(to_tile(segment[0]), to_tile(segment[1]))

        # --- Phase 4: wordmark + tagline fade up ---
        text_fraction = self._phase(elapsed, _TAIL_END, _TEXT_END)
        painter.setOpacity(text_fraction)
        name_font = QFont()
        name_font.setPointSize(21)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor("#EDEDED"))
        painter.drawText(QRectF(0, tile_top + _LOGO_SIZE + 18, _CARD_WIDTH, 40),
                         Qt.AlignmentFlag.AlignHCenter, brand.APP_NAME)
        tagline_font = QFont()
        tagline_font.setPointSize(9)
        painter.setFont(tagline_font)
        painter.setPen(QColor("#A5A5A5"))
        painter.drawText(QRectF(30, tile_top + _LOGO_SIZE + 62, _CARD_WIDTH - 60, 36),
                         Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, brand.TAGLINE)

        # Status line: the real start-up step, always fully visible.
        painter.setOpacity(1.0)
        status_font = QFont()
        status_font.setPointSize(9)
        painter.setFont(status_font)
        painter.setPen(QColor("#7E7E7E"))
        painter.drawText(QRectF(20, _CARD_HEIGHT - 46, _CARD_WIDTH - 40, 30),
                         Qt.AlignmentFlag.AlignHCenter, self._status)
        painter.end()
