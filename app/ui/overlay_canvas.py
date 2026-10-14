"""Interactive canvas for tick/X/percentage overlay marks on a rendered
student answer page (Stage 11V).

Unlike TemplateCanvas's regions (drawn once, then static - repositioning
requires "Redefine" and redrawing from scratch), overlay marks here are
genuinely interactive QGraphicsItems: they can be dragged directly (Qt's
native ItemIsMovable), resized via a corner handle, and rotated via a
handle above the item, matching the Stage 11V spec's explicit "direct
preview editing" requirement. This is new machinery - no existing widget
in this codebase supported drag/resize/rotate before this stage.
"""

import math
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QWidget

HANDLE_SIZE = 10.0
ROTATE_HANDLE_OFFSET = 28.0
MIN_SIZE_PIXELS = 14.0


class OverlayMarkItem(QGraphicsRectItem):
    """One draggable/resizable/rotatable tick, cross, or percentage mark.

    Selecting the item (single click, via ItemIsSelectable) reveals a
    resize handle (bottom-right corner) and a rotate handle (small circle
    above the item, connected by a thin guide line). Dragging the item
    body itself moves it (Qt's built-in ItemIsMovable - no custom code
    needed for plain move). on_change(item) is called after any move/
    resize/rotate gesture completes (mouse release), so the caller can
    persist the new fractional x/y/width/height/rotation.
    """

    def __init__(
        self, overlay_id: int, kind: str, rect: QRectF,
        rotation_angle: float = 0.0, text_value: Optional[str] = None,
        on_change: Optional[Callable[["OverlayMarkItem"], None]] = None,
        font_size: Optional[int] = None,
    ) -> None:
        super().__init__(rect)
        self.overlay_id = overlay_id
        self.kind = kind
        self.text_value = text_value
        # Manual font size in PDF points for a feedback note (None = automatic).
        self.font_size = font_size
        self._on_change = on_change
        self._resizing = False
        self._rotating = False
        self._resize_start_rect: Optional[QRectF] = None
        self._press_pos: Optional[QPointF] = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setTransformOriginPoint(rect.center())
        self.setRotation(rotation_angle)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        base = super().boundingRect()
        margin = ROTATE_HANDLE_OFFSET + HANDLE_SIZE
        return base.adjusted(-margin, -margin, margin, margin)

    def _resize_handle_rect(self) -> QRectF:
        r = self.rect()
        return QRectF(r.right() - HANDLE_SIZE / 2, r.bottom() - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)

    def _rotate_handle_rect(self) -> QRectF:
        r = self.rect()
        cx = r.center().x()
        return QRectF(cx - HANDLE_SIZE / 2, r.top() - ROTATE_HANDLE_OFFSET, HANDLE_SIZE, HANDLE_SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802 - Qt override
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        red = QColor(220, 38, 38)
        pen = QPen(red, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        if self.kind == "tick":
            mid_x, mid_y = rect.left() + rect.width() * 0.35, rect.top() + rect.height() * 0.65
            painter.drawLine(QPointF(rect.left(), rect.top() + rect.height() * 0.5), QPointF(mid_x, rect.bottom()))
            painter.drawLine(QPointF(mid_x, rect.bottom()), QPointF(rect.right(), rect.top()))
        elif self.kind == "cross":
            painter.drawLine(rect.topLeft(), rect.bottomRight())
            painter.drawLine(rect.bottomLeft(), rect.topRight())
        elif self.kind == "percentage":
            # The text must always be fully readable: start from the rect-based
            # size and shrink until the whole string fits INSIDE the rect
            # (never clipped mid-word like "Teach|"), floor at 6pt.
            text = self.text_value or ""
            font = QFont()
            font.setBold(True)
            size = max(8, int(rect.height() * 0.4))
            from PySide6.QtGui import QFontMetricsF
            while size > 6:
                font.setPointSize(size)
                metrics = QFontMetricsF(font)
                if (metrics.horizontalAdvance(text) <= rect.width() - 4
                        and metrics.height() <= rect.height()):
                    break
                size -= 1
            font.setPointSize(max(6, size))
            painter.setFont(font)
            painter.setPen(QPen(red))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        elif self.kind == "feedback":
            # A wrapped red feedback note over a faint panel so it stays legible
            # on top of the essay lines. Word-wrapped inside the (resizable) rect.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QPen(red, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)
            font = QFont()
            if self.font_size:
                # Manual size is stored in PDF points; approximate the on-screen
                # pixel size from the page image width (PDF pages are ~595 pt wide).
                scene = self.scene()
                scene_w = scene.sceneRect().width() if scene is not None else 595.0
                font.setPixelSize(max(6, round(self.font_size * (scene_w / 595.0))))
            else:
                font.setPointSize(max(7, int(rect.height() * 0.11)))
            painter.setFont(font)
            painter.setPen(QPen(red))
            painter.drawText(
                rect.adjusted(5, 4, -5, -4),
                int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.AlignmentFlag.AlignLeft),
                self.text_value or "",
            )

        if self.isSelected():
            painter.setPen(QPen(QColor(124, 58, 237), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(QBrush(QColor(124, 58, 237)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(self._resize_handle_rect())
            painter.drawEllipse(self._rotate_handle_rect())
            painter.setPen(QPen(QColor(124, 58, 237), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.center().x(), rect.top()), self._rotate_handle_rect().center())

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        pos = event.pos()
        self._press_pos = self.pos()
        if self.isSelected() and self._resize_handle_rect().contains(pos):
            self._resizing = True
            self._resize_start_rect = QRectF(self.rect())
            event.accept()
            return
        if self.isSelected() and self._rotate_handle_rect().contains(pos):
            self._rotating = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._resizing and self._resize_start_rect is not None:
            pos = event.pos()
            new_rect = QRectF(self._resize_start_rect)
            new_rect.setBottomRight(pos)
            if new_rect.width() >= MIN_SIZE_PIXELS and new_rect.height() >= MIN_SIZE_PIXELS:
                self.prepareGeometryChange()
                self.setRect(new_rect)
                self.setTransformOriginPoint(new_rect.center())
            event.accept()
            return
        if self._rotating:
            center_scene = self.mapToScene(self.rect().center())
            scene_pos = event.scenePos()
            angle = math.degrees(math.atan2(scene_pos.y() - center_scene.y(), scene_pos.x() - center_scene.x()))
            self.setRotation(angle + 90)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        was_transforming = self._resizing or self._rotating
        self._resizing = False
        self._rotating = False
        self._resize_start_rect = None
        super().mouseReleaseEvent(event)
        # Only persist (and let the caller rebuild the canvas) when the gesture
        # actually changed the geometry. A plain click just selects the item -
        # firing on_change there would rebuild the overlays and immediately drop
        # the selection, making it impossible to keep a note selected (e.g. to
        # adjust its feedback font).
        moved = was_transforming or (self._press_pos is not None and self.pos() != self._press_pos)
        if moved and self._on_change is not None:
            self._on_change(self)


class OverlayCanvas(QGraphicsView):
    """Displays a rendered student answer page with its overlay marks -
    each overlay directly draggable/resizable/rotatable on the preview."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(360)
        self._pixmap_item = None
        self._image_size: Tuple[int, int] = (1, 1)
        self._overlay_items: List[OverlayMarkItem] = []

    def load_image(self, image: QImage) -> None:
        self._scene.clear()
        self._overlay_items = []
        pixmap = QPixmap.fromImage(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._image_size = (max(image.width(), 1), max(image.height(), 1))
        self._scene.setSceneRect(0, 0, self._image_size[0], self._image_size[1])
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def add_overlay(
        self, overlay_id: int, kind: str, x: float, y: float, width: float, height: float,
        rotation_angle: float = 0.0, text_value: Optional[str] = None,
        on_change: Optional[Callable[[OverlayMarkItem], None]] = None,
        font_size: Optional[int] = None,
    ) -> OverlayMarkItem:
        img_w, img_h = self._image_size
        rect = QRectF(x * img_w, y * img_h, width * img_w, height * img_h)
        item = OverlayMarkItem(overlay_id, kind, rect, rotation_angle, text_value, on_change, font_size)
        self._scene.addItem(item)
        self._overlay_items.append(item)
        return item

    def clear_overlays(self) -> None:
        for item in self._overlay_items:
            self._scene.removeItem(item)
        self._overlay_items = []

    def get_overlay_items(self) -> List[OverlayMarkItem]:
        return list(self._overlay_items)

    def get_overlay_fractional_transform(self, item: OverlayMarkItem) -> Tuple[float, float, float, float, float]:
        """Return (x, y, width, height, rotation_angle) as fractions (0-1)
        of the loaded page image, from item's current scene position/rect/
        rotation - the values to persist after a move/resize/rotate."""
        img_w, img_h = self._image_size
        rect = item.rect()
        top_left_scene = item.mapToScene(rect.topLeft())
        x = max(0.0, top_left_scene.x() / img_w)
        y = max(0.0, top_left_scene.y() / img_h)
        width = rect.width() / img_w
        height = rect.height() / img_h
        return x, y, width, height, item.rotation()

    def remove_overlay_item(self, item: OverlayMarkItem) -> None:
        if item in self._overlay_items:
            self._scene.removeItem(item)
            self._overlay_items.remove(item)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
