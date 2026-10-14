"""Interactive canvas for defining rectangular answer regions on a rendered
template sample page.

Regions are stored and emitted as fractions (0-1) of the page image's width
and height, so they remain valid regardless of the on-screen zoom level or
the resolution the page was rendered at. Multi-page PDF sample files are
supported via render_page_image's page_index parameter and get_page_count()
(Stage 11E) - both use PySide6's built-in QtPdf module (already a project
dependency), so no new dependency was added. Image sample files (png/jpg)
are always treated as a single page.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from app.ui import styles

_PDF_SUFFIXES = {".pdf"}

# Stage 12E-2 UX Fix: deterministic per-region-type preview colors, so
# different region types are visually distinguishable at a glance instead
# of every non-ignore region sharing one accent purple. Deliberately a
# plain string-keyed dict (not importing app.models.subject_profile_model's
# REGION_TYPE_* constants) - TemplateCanvas is a generic, reusable widget
# shared with the older Template Editor (app.models.template_model's own,
# slightly different region-type vocabulary), so it stays decoupled from
# any one model module; any type not in this mapping (e.g. an older
# Template Editor type) falls back to DEFAULT_REGION_COLOR_HEX, the
# original accent purple, so nothing regresses visually for those.
REGION_TYPE_COLOR_HEX: Dict[str, str] = {
    "question_area": "#3B82F6",         # blue
    "question_number_box": "#F59E0B",   # amber
    "answer_region": "#10B981",         # emerald
    "answer_box": styles.ACCENT,        # "#7C3AED" - keeps the original accent purple (most common type)
    "bubble_area": "#EC4899",           # pink
    "letter_box": "#06B6D4",            # cyan
    "underline_answer": "#F97316",      # orange
    "student_info_area": "#84CC16",     # lime
    "extra_page_label": "#6366F1",      # indigo
    "ignore_region": styles.DESTRUCTIVE,  # "#DC2626" - matches the existing is_ignore red convention
}
DEFAULT_REGION_COLOR_HEX = styles.ACCENT

SELECTED_REGION_PEN_WIDTH = 4
NORMAL_REGION_PEN_WIDTH = 2


def get_region_type_color(region_type: Optional[str]) -> QColor:
    """The preview color for region_type - DEFAULT_REGION_COLOR_HEX (the
    original accent purple) for None or any type not in REGION_TYPE_COLOR_
    HEX, so an unmapped/legacy region type never goes uncolored."""
    return QColor(REGION_TYPE_COLOR_HEX.get(region_type, DEFAULT_REGION_COLOR_HEX))


def _geometry_contains(geometry, point: QPointF) -> bool:
    if isinstance(geometry, QPolygonF):
        return geometry.containsPoint(point, Qt.FillRule.OddEvenFill)
    return geometry.contains(point)


def _geometry_area(geometry) -> float:
    rect = geometry.boundingRect() if isinstance(geometry, QPolygonF) else geometry
    return abs(rect.width() * rect.height())


def get_page_count(file_path: str) -> int:
    """Return the number of pages in file_path.

    PDFs report their real page count via QtPdf. Image files (png/jpg/jpeg)
    are always a single page. Returns 1 (a safe minimum) if the file cannot
    be loaded, so callers can always treat page count as >= 1.
    """
    suffix = Path(file_path).suffix.lower()

    if suffix in _PDF_SUFFIXES:
        from PySide6.QtPdf import QPdfDocument

        document = QPdfDocument()
        document.load(file_path)
        if document.status() != QPdfDocument.Status.Ready:
            return 1
        return max(1, document.pageCount())

    return 1


def render_page_image(file_path: str, max_width: int = 900, page_index: int = 0) -> QImage:
    """Render page page_index (0-based) of file_path (PDF or image) to a
    QImage, scaled so its width is at most max_width. Returns a null QImage
    if the file or the requested page cannot be loaded.

    Image files (png/jpg/jpeg) only ever have page_index 0 - any other
    value returns a null QImage, since they are not paginated.
    """
    suffix = Path(file_path).suffix.lower()

    if suffix in _PDF_SUFFIXES:
        from PySide6.QtCore import QSize
        from PySide6.QtPdf import QPdfDocument

        document = QPdfDocument()
        document.load(file_path)
        if document.status() != QPdfDocument.Status.Ready or document.pageCount() < 1:
            return QImage()
        if page_index < 0 or page_index >= document.pageCount():
            return QImage()

        page_size = document.pagePointSize(page_index)
        if page_size.width() <= 0:
            return QImage()
        scale = max_width / page_size.width()
        target_size = QSize(int(page_size.width() * scale), int(page_size.height() * scale))
        return document.render(page_index, target_size)

    if page_index != 0:
        return QImage()

    image = QImage(file_path)
    if image.isNull():
        return image
    if image.width() > max_width:
        image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    return image


class TemplateCanvas(QGraphicsView):
    """Displays a rendered template page and lets the user either drag out
    rectangular regions or (Stage 11G) click out polygon/freeform regions
    with the mouse.

    Emits region_drawn(x, y, width, height) with fractional (0-1)
    coordinates relative to the loaded page image once the user releases
    the mouse after a large-enough drag, in rectangle mode (the default).

    Emits polygon_region_drawn(points) - a list of (x, y) fractional
    coordinate tuples - once finish_polygon() is called with at least
    MIN_POLYGON_POINTS points already clicked, in polygon mode.

    Emits region_selected(region_id) / region_deselected() (Stage 12E-2 UX
    Fix) when a plain click (no real drag) in rectangle mode hits/misses an
    existing region overlay that was registered with a region_id via
    add_region_overlay/add_polygon_region_overlay. Only click-to-select in
    rectangle mode is supported - polygon mode's clicks are already fully
    claimed by in-progress polygon-point placement, so it is left untouched.

    Emits region_moved(region_id, x, y) / polygon_region_moved(region_id,
    points) (Stage 12E-2 UX Fix 2) when a drag that STARTS on an existing
    region overlay moves it (rectangle mode only, same reasoning as
    click-to-select) - the move is clamped to stay within the page image.

    Emits region_resized(region_id, x, y, width, height) (Stage 12E-2 UX
    Fix 2) when a drag on one of the selected region's 4 corner resize
    handles changes its size/position - clamped to a minimum size and to
    the page image bounds. Resize handles/dragging are only offered for
    axis-aligned (rotation_angle == 0) RECTANGLE-shaped regions - polygon
    regions and rotated regions can still be MOVED (a pure translation is
    always safe) but never resized this way, to avoid any risk of
    corrupting polygon_points_json or rotation_angle; this is a deliberate,
    documented limitation, not an oversight.

    In all cases, this canvas only emits the intent - it never persists
    anything itself. The overlay is snapped back to its pre-drag position/
    size immediately after emitting, so the caller is responsible for
    persisting the new geometry and redrawing from the authoritative
    source (same contract as region_drawn/polygon_region_drawn)."""

    region_drawn = Signal(float, float, float, float)
    polygon_region_drawn = Signal(list)
    region_selected = Signal(int)
    region_deselected = Signal()
    region_moved = Signal(int, float, float)
    polygon_region_moved = Signal(int, list)
    region_resized = Signal(int, float, float, float, float)

    MIN_DRAG_PIXELS = 6
    MIN_POLYGON_POINTS = 3
    HANDLE_SIZE = 10
    MIN_REGION_SIZE_PIXELS = 16
    RESIZE_HANDLE_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")

    MODE_RECTANGLE = "rectangle"
    MODE_POLYGON = "polygon"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(360)
        self.setMouseTracking(True)

        self._pixmap_item = None
        self._image_size: Tuple[int, int] = (1, 1)
        self._drag_start = None
        self._drag_rect_item = None
        self._overlay_items = []
        self._region_overlays: Dict[int, dict] = {}
        self._selected_region_id: Optional[int] = None
        self._moving_region_id: Optional[int] = None
        self._resizing_region_id: Optional[int] = None
        self._resizing_corner: Optional[str] = None
        self._resize_original_rect: Optional[QRectF] = None
        self._resize_handle_items: List[Tuple[object, str]] = []

        self._mode = self.MODE_RECTANGLE
        self._polygon_points_scene: List[QPointF] = []
        self._polygon_point_items = []
        self._polygon_line_items = []
        self._polygon_preview_line_item = None

    def set_mode(self, mode: str) -> None:
        """Switch between MODE_RECTANGLE and MODE_POLYGON. Switching modes
        discards any in-progress (unfinished) polygon points."""
        if mode not in (self.MODE_RECTANGLE, self.MODE_POLYGON):
            raise ValueError(f"Unknown TemplateCanvas mode: {mode!r}")
        if mode != self._mode:
            self.cancel_polygon()
        self._mode = mode

    def get_mode(self) -> str:
        return self._mode

    def has_pending_polygon_points(self) -> bool:
        return len(self._polygon_points_scene) > 0

    def load_image(self, image: QImage) -> None:
        """Replace the displayed page with image and clear any overlays."""
        self._scene.clear()
        self._overlay_items = []
        self._region_overlays = {}
        self._selected_region_id = None
        self._moving_region_id = None
        self._resizing_region_id = None
        self._resizing_corner = None
        self._resize_original_rect = None
        self._resize_handle_items = []
        self._drag_start = None
        self._drag_rect_item = None
        self._polygon_points_scene = []
        self._polygon_point_items = []
        self._polygon_line_items = []
        self._polygon_preview_line_item = None

        pixmap = QPixmap.fromImage(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._image_size = (max(image.width(), 1), max(image.height(), 1))
        self._scene.setSceneRect(0, 0, self._image_size[0], self._image_size[1])
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def add_region_overlay(
        self,
        label: str,
        x: float,
        y: float,
        width: float,
        height: float,
        is_ignore: bool = False,
        rotation_angle: float = 0.0,
        region_id: Optional[int] = None,
        region_type: Optional[str] = None,
    ) -> None:
        """Draw a saved rectangle region as a labeled overlay rectangle.

        is_ignore (Stage 11I) draws it in a visually distinct destructive/red
        style instead of the normal accent purple, so ignore regions are
        clearly distinguishable from normal answer/question/student-id
        regions on the preview.

        rotation_angle (Stage 11J, degrees) rotates only the drawn overlay
        item around its own center, via Qt's native item rotation - the
        underlying page image/pixmap is never rotated, and the label text
        stays upright for readability.

        region_id/region_type (Stage 12E-2 UX Fix, both optional) register
        this overlay for click-to-select/hit-testing/table-sync and for
        per-region-type coloring (is_ignore still overrides region_type's
        color, matching the pre-existing ignore-region visual convention).
        Callers that omit region_id (there are none left in this codebase,
        but the parameter stays optional for any future/test caller) simply
        get a non-selectable, non-type-colored overlay, matching the old
        behavior."""
        img_w, img_h = self._image_size
        rect = QRectF(x * img_w, y * img_h, width * img_w, height * img_h)
        color = QColor(styles.DESTRUCTIVE) if is_ignore else get_region_type_color(region_type)
        selected = region_id is not None and region_id == self._selected_region_id
        pen, fill = self._pen_and_brush_for(color, selected)

        rect_item = self._scene.addRect(rect, pen, fill)
        if rotation_angle:
            rect_item.setTransformOriginPoint(rect.center())
            rect_item.setRotation(rotation_angle)
        text_item = self._scene.addSimpleText(f"{label} (IGNORE)" if is_ignore else label)
        text_item.setBrush(QBrush(color))
        text_item.setPos(rect.topLeft())
        self._overlay_items.append((rect_item, text_item))

        if region_id is not None:
            self._region_overlays[region_id] = {
                "shape_item": rect_item,
                "text_item": text_item,
                "text_origin": rect.topLeft(),
                "geometry": QRectF(rect),
                "color": color,
                "region_type": region_type,
                "rotation_angle": rotation_angle,
            }
            if selected:
                self._rebuild_resize_handles_for(region_id)

    def add_polygon_region_overlay(
        self,
        label: str,
        points: List[Tuple[float, float]],
        is_ignore: bool = False,
        rotation_angle: float = 0.0,
        region_id: Optional[int] = None,
        region_type: Optional[str] = None,
    ) -> None:
        """Draw a saved polygon region as a labeled, filled outline.

        is_ignore (Stage 11I) draws it in the same distinct destructive/red
        style as add_region_overlay's ignore rectangles.

        rotation_angle (Stage 11J, degrees) rotates the drawn polygon item
        around its own bounding-box center, via Qt's native item rotation -
        the stored points/underlying page image are never rotated, and the
        label text stays upright for readability.

        region_id/region_type (Stage 12E-2 UX Fix): see add_region_overlay -
        same registration for click-to-select/hit-testing/table-sync/color."""
        img_w, img_h = self._image_size
        polygon = QPolygonF([QPointF(x * img_w, y * img_h) for x, y in points])
        color = QColor(styles.DESTRUCTIVE) if is_ignore else get_region_type_color(region_type)
        selected = region_id is not None and region_id == self._selected_region_id
        pen, fill = self._pen_and_brush_for(color, selected)

        polygon_item = self._scene.addPolygon(polygon, pen, fill)
        if rotation_angle:
            polygon_item.setTransformOriginPoint(polygon.boundingRect().center())
            polygon_item.setRotation(rotation_angle)
        text_item = self._scene.addSimpleText(f"{label} (IGNORE)" if is_ignore else label)
        text_item.setBrush(QBrush(color))
        text_item.setPos(polygon.boundingRect().topLeft())
        self._overlay_items.append((polygon_item, text_item))

        if region_id is not None:
            self._region_overlays[region_id] = {
                "shape_item": polygon_item,
                "text_item": text_item,
                "text_origin": polygon.boundingRect().topLeft(),
                "geometry": QPolygonF(polygon),
                "color": color,
                "region_type": region_type,
                "rotation_angle": rotation_angle,
            }
            if selected:
                # Polygon regions never get resize handles (Stage 12E-2 UX
                # Fix 2 - see class docstring) - this only clears any stale
                # handles left over from a previously selected region.
                self._rebuild_resize_handles_for(region_id)

    @staticmethod
    def _pen_and_brush_for(color: QColor, selected: bool) -> Tuple[QPen, QBrush]:
        """Pen/brush pair for color, stronger (thicker stroke + a more
        opaque highlight fill) when selected - the Stage 12E-2 UX Fix
        "selected region visually stands out" requirement. Unselected alpha
        (40) matches the original hardcoded overlay fill values."""
        pen_width = SELECTED_REGION_PEN_WIDTH if selected else NORMAL_REGION_PEN_WIDTH
        alpha = 90 if selected else 40
        pen = QPen(color, pen_width)
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), alpha))
        return pen, brush

    def _restyle_all_overlays(self) -> None:
        for region_id, info in self._region_overlays.items():
            selected = region_id == self._selected_region_id
            pen, brush = self._pen_and_brush_for(info["color"], selected)
            info["shape_item"].setPen(pen)
            info["shape_item"].setBrush(brush)

    def set_selected_region(self, region_id: Optional[int]) -> None:
        """Update the visually-selected region and restyle overlays to
        match. Deliberately never emits region_selected/region_deselected
        itself (Stage 12E-2 UX Fix) - this method is called both by this
        canvas's own click handling AND externally (e.g. by a region table's
        selection-changed handler), and having it stay silent avoids an
        infinite signal loop between preview-click <-> table-selection sync.
        Only the canvas's own click handler emits those signals, explicitly,
        after calling this method."""
        if region_id == self._selected_region_id:
            return
        self._selected_region_id = region_id
        self._restyle_all_overlays()
        if region_id is not None and region_id in self._region_overlays:
            self._rebuild_resize_handles_for(region_id)
        else:
            self._clear_resize_handles()

    def get_selected_region(self) -> Optional[int]:
        return self._selected_region_id

    def clear_selection(self) -> None:
        self.set_selected_region(None)

    def _hit_test_region(self, scene_pos: QPointF) -> Optional[int]:
        """Resolve which registered region (if any) is under scene_pos, for
        click-to-select. When regions overlap, prefers the smallest-area
        region, with ties broken toward the most-recently-drawn region.

        Known limitation: does not account for a region's rotation_angle -
        hit-testing uses each region's unrotated stored geometry, while the
        visual item may be rotated via Qt's native item rotation. Considered
        out of scope for this focused UX fix."""
        candidates = []
        for region_id in reversed(list(self._region_overlays.keys())):
            geometry = self._region_overlays[region_id]["geometry"]
            if _geometry_contains(geometry, scene_pos):
                candidates.append((_geometry_area(geometry), region_id))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def _clamp_move_delta(self, region_id: int, delta: QPointF) -> QPointF:
        """Clamp a proposed drag-move translation so region_id's bounding
        box stays fully within the loaded page image - applied uniformly to
        every point (not per-point), so a polygon's shape is preserved
        exactly rather than distorted at the boundary."""
        img_w, img_h = self._image_size
        geometry = self._region_overlays[region_id]["geometry"]
        bounding = geometry.boundingRect() if isinstance(geometry, QPolygonF) else geometry
        dx = max(-bounding.x(), min(img_w - bounding.x() - bounding.width(), delta.x()))
        dy = max(-bounding.y(), min(img_h - bounding.y() - bounding.height(), delta.y()))
        return QPointF(dx, dy)

    def _region_supports_resize(self, region_id: int) -> bool:
        """Only axis-aligned (rotation_angle == 0) RECTANGLE-shaped regions
        get resize handles - see the class docstring for why polygon and
        rotated regions are excluded."""
        info = self._region_overlays.get(region_id)
        if info is None:
            return False
        return isinstance(info["geometry"], QRectF) and not info.get("rotation_angle")

    def _clear_resize_handles(self) -> None:
        for item, _corner in self._resize_handle_items:
            self._scene.removeItem(item)
        self._resize_handle_items = []

    def _rebuild_resize_handles_for(self, region_id: int) -> None:
        self._clear_resize_handles()
        if not self._region_supports_resize(region_id):
            return
        self._reposition_handles(self._region_overlays[region_id]["geometry"], create=True)

    def _reposition_handles(self, rect: QRectF, create: bool = False) -> None:
        """Move the 4 resize-handle overlay items to rect's corners - or,
        with create=True (only called from _rebuild_resize_handles_for,
        right after clearing any old handles), create them fresh. A no-op
        if there are no handles to update and create is False, so this can
        be called unconditionally during a move-drag even for a region
        that has no handles (e.g. moving a polygon)."""
        half = self.HANDLE_SIZE / 2
        corners = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        if create:
            for corner in self.RESIZE_HANDLE_CORNERS:
                point = corners[corner]
                handle_rect = QRectF(point.x() - half, point.y() - half, self.HANDLE_SIZE, self.HANDLE_SIZE)
                item = self._scene.addRect(handle_rect, QPen(QColor("#FFFFFF"), 1), QBrush(QColor(styles.ACCENT)))
                item.setZValue(10)
                self._resize_handle_items.append((item, corner))
            return
        for item, corner in self._resize_handle_items:
            point = corners[corner]
            item.setRect(point.x() - half, point.y() - half, self.HANDLE_SIZE, self.HANDLE_SIZE)

    def _handle_at(self, scene_pos: QPointF) -> Optional[str]:
        for item, corner in self._resize_handle_items:
            if item.rect().contains(scene_pos):
                return corner
        return None

    def _resized_rect(self, original: QRectF, corner: str, current: QPointF) -> QRectF:
        """The new rect when dragging corner from original toward current,
        clamped to MIN_REGION_SIZE_PIXELS and the page image bounds. Only
        the 2 edges named by corner move - the opposite 2 stay fixed at
        their original position, so this is always a true corner-resize
        (never an accidental move)."""
        img_w, img_h = self._image_size
        cx = max(0.0, min(img_w, current.x()))
        cy = max(0.0, min(img_h, current.y()))
        left, top, right, bottom = original.left(), original.top(), original.right(), original.bottom()
        if "left" in corner:
            left = min(cx, right - self.MIN_REGION_SIZE_PIXELS)
        if "right" in corner:
            right = max(cx, left + self.MIN_REGION_SIZE_PIXELS)
        if "top" in corner:
            top = min(cy, bottom - self.MIN_REGION_SIZE_PIXELS)
        if "bottom" in corner:
            bottom = max(cy, top + self.MIN_REGION_SIZE_PIXELS)
        left = max(0.0, left)
        top = max(0.0, top)
        right = min(float(img_w), right)
        bottom = min(float(img_h), bottom)
        return QRectF(QPointF(left, top), QPointF(right, bottom))

    def _update_hover_cursor(self, scene_pos: QPointF) -> None:
        corner = self._handle_at(scene_pos)
        if corner is not None:
            if corner in ("top_left", "bottom_right"):
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.viewport().setCursor(Qt.CursorShape.SizeBDiagCursor)
            return
        if self._hit_test_region(scene_pos) is not None:
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            return
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def clear_overlays(self) -> None:
        for shape_item, text_item in self._overlay_items:
            self._scene.removeItem(shape_item)
            self._scene.removeItem(text_item)
        self._overlay_items = []
        self._region_overlays = {}
        self._clear_resize_handles()
        self._moving_region_id = None
        self._resizing_region_id = None
        self._resizing_corner = None
        self._resize_original_rect = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _add_polygon_point(self, scene_pos: QPointF) -> None:
        marker = self._scene.addEllipse(
            scene_pos.x() - 3, scene_pos.y() - 3, 6, 6,
            QPen(QColor(styles.WARNING), 1), QBrush(QColor(styles.WARNING)),
        )
        self._polygon_point_items.append(marker)

        if self._polygon_points_scene:
            previous = self._polygon_points_scene[-1]
            line = self._scene.addLine(
                previous.x(), previous.y(), scene_pos.x(), scene_pos.y(), QPen(QColor(styles.WARNING), 2)
            )
            self._polygon_line_items.append(line)

        self._polygon_points_scene.append(scene_pos)

    def cancel_polygon(self) -> None:
        """Discard any in-progress (unfinished) polygon points/markers."""
        for item in self._polygon_point_items:
            self._scene.removeItem(item)
        for item in self._polygon_line_items:
            self._scene.removeItem(item)
        if self._polygon_preview_line_item is not None:
            self._scene.removeItem(self._polygon_preview_line_item)
            self._polygon_preview_line_item = None
        self._polygon_points_scene = []
        self._polygon_point_items = []
        self._polygon_line_items = []

    def finish_polygon(self) -> bool:
        """Complete the in-progress polygon and emit polygon_region_drawn
        with its fractional (0-1) points. Returns False (without clearing
        the in-progress points, so the teacher can keep adding more) if
        fewer than MIN_POLYGON_POINTS points have been clicked yet."""
        if len(self._polygon_points_scene) < self.MIN_POLYGON_POINTS:
            return False

        img_w, img_h = self._image_size
        points = [
            (max(0.0, min(1.0, p.x() / img_w)), max(0.0, min(1.0, p.y() / img_h)))
            for p in self._polygon_points_scene
        ]
        self.cancel_polygon()
        self.polygon_region_drawn.emit(points)
        return True

    def mousePressEvent(self, event) -> None:
        if self._pixmap_item is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if self._mode == self.MODE_POLYGON:
            self._add_polygon_point(self.mapToScene(event.pos()))
            return

        self._drag_start = self.mapToScene(event.pos())

        handle_corner = self._handle_at(self._drag_start)
        if handle_corner is not None and self._selected_region_id is not None:
            self._resizing_region_id = self._selected_region_id
            self._resizing_corner = handle_corner
            self._resize_original_rect = QRectF(self._region_overlays[self._selected_region_id]["geometry"])
            self._moving_region_id = None
            self._drag_rect_item = None
            super().mousePressEvent(event)
            return

        hit_region_id = self._hit_test_region(self._drag_start)
        if hit_region_id is not None:
            # Drag starting on an existing region moves it instead of
            # drawing a new one - no rubber-band preview rect is created.
            self._moving_region_id = hit_region_id
            self._drag_rect_item = None
        else:
            self._moving_region_id = None
            self._drag_rect_item = self._scene.addRect(
                QRectF(self._drag_start, self._drag_start), QPen(QColor(styles.WARNING), 2)
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._mode == self.MODE_POLYGON:
            if self._polygon_points_scene:
                current = self.mapToScene(event.pos())
                last = self._polygon_points_scene[-1]
                if self._polygon_preview_line_item is None:
                    self._polygon_preview_line_item = self._scene.addLine(
                        last.x(), last.y(), current.x(), current.y(),
                        QPen(QColor(styles.WARNING), 1, Qt.PenStyle.DashLine),
                    )
                else:
                    self._polygon_preview_line_item.setLine(last.x(), last.y(), current.x(), current.y())
            super().mouseMoveEvent(event)
            return

        current = self.mapToScene(event.pos())

        if self._resizing_region_id is not None:
            new_rect = self._resized_rect(self._resize_original_rect, self._resizing_corner, current)
            info = self._region_overlays[self._resizing_region_id]
            info["shape_item"].setRect(new_rect)
            info["text_item"].setPos(new_rect.topLeft())
            self._reposition_handles(new_rect)
            super().mouseMoveEvent(event)
            return

        if self._moving_region_id is not None and self._drag_start is not None:
            delta = self._clamp_move_delta(self._moving_region_id, current - self._drag_start)
            info = self._region_overlays[self._moving_region_id]
            info["shape_item"].setPos(delta)
            info["text_item"].setPos(info["text_origin"] + delta)
            if isinstance(info["geometry"], QRectF):
                self._reposition_handles(info["geometry"].translated(delta))
            super().mouseMoveEvent(event)
            return

        if self._drag_start is not None and self._drag_rect_item is not None:
            self._drag_rect_item.setRect(QRectF(self._drag_start, current).normalized())
            super().mouseMoveEvent(event)
            return

        # Plain hover (no button held, no active drag) - cursor feedback.
        self._update_hover_cursor(current)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._mode == self.MODE_POLYGON:
            super().mouseReleaseEvent(event)
            return

        if self._resizing_region_id is not None:
            region_id = self._resizing_region_id
            current = self.mapToScene(event.pos())
            original_rect = self._resize_original_rect
            new_rect = self._resized_rect(original_rect, self._resizing_corner, current)
            info = self._region_overlays[region_id]
            # Snap back - the caller redraws from the persisted geometry
            # after handling region_resized below (same contract as move).
            info["shape_item"].setRect(original_rect)
            info["text_item"].setPos(original_rect.topLeft())
            self._reposition_handles(original_rect)
            self._resizing_region_id = None
            self._resizing_corner = None
            self._resize_original_rect = None
            self._drag_start = None

            resized_enough = (
                abs(new_rect.width() - original_rect.width()) >= self.MIN_DRAG_PIXELS
                or abs(new_rect.height() - original_rect.height()) >= self.MIN_DRAG_PIXELS
                or abs(new_rect.x() - original_rect.x()) >= self.MIN_DRAG_PIXELS
                or abs(new_rect.y() - original_rect.y()) >= self.MIN_DRAG_PIXELS
            )
            if resized_enough:
                img_w, img_h = self._image_size
                x = max(0.0, min(1.0, new_rect.x() / img_w))
                y = max(0.0, min(1.0, new_rect.y() / img_h))
                width = max(0.0, min(1.0 - x, new_rect.width() / img_w))
                height = max(0.0, min(1.0 - y, new_rect.height() / img_h))
                self.region_resized.emit(region_id, x, y, width, height)
            super().mouseReleaseEvent(event)
            return

        if self._moving_region_id is not None:
            region_id = self._moving_region_id
            current = self.mapToScene(event.pos())
            delta = self._clamp_move_delta(region_id, current - self._drag_start)
            info = self._region_overlays[region_id]
            # Snap back - the caller redraws from the persisted geometry
            # after handling region_moved/polygon_region_moved below.
            info["shape_item"].setPos(0, 0)
            info["text_item"].setPos(info["text_origin"])
            if isinstance(info["geometry"], QRectF):
                self._reposition_handles(info["geometry"])
            self._moving_region_id = None
            self._drag_start = None

            if abs(delta.x()) < self.MIN_DRAG_PIXELS and abs(delta.y()) < self.MIN_DRAG_PIXELS:
                # Not a real drag - treat exactly like the existing plain-
                # click-to-select behavior.
                if region_id != self._selected_region_id:
                    self.set_selected_region(region_id)
                    self.region_selected.emit(region_id)
            else:
                img_w, img_h = self._image_size
                was_selected = region_id == self._selected_region_id
                if not was_selected:
                    self.set_selected_region(region_id)
                geometry = info["geometry"]
                if isinstance(geometry, QPolygonF):
                    new_points = [
                        (max(0.0, min(1.0, (p.x() + delta.x()) / img_w)),
                         max(0.0, min(1.0, (p.y() + delta.y()) / img_h)))
                        for p in geometry
                    ]
                    if not was_selected:
                        self.region_selected.emit(region_id)
                    self.polygon_region_moved.emit(region_id, new_points)
                else:
                    new_x = max(0.0, min(1.0, (geometry.x() + delta.x()) / img_w))
                    new_y = max(0.0, min(1.0, (geometry.y() + delta.y()) / img_h))
                    if not was_selected:
                        self.region_selected.emit(region_id)
                    self.region_moved.emit(region_id, new_x, new_y)
            super().mouseReleaseEvent(event)
            return

        if self._drag_start is not None and self._drag_rect_item is not None:
            rect = self._drag_rect_item.rect()
            click_scene_pos = self.mapToScene(event.pos())
            self._scene.removeItem(self._drag_rect_item)
            self._drag_rect_item = None
            self._drag_start = None

            if rect.width() >= self.MIN_DRAG_PIXELS and rect.height() >= self.MIN_DRAG_PIXELS:
                img_w, img_h = self._image_size
                x = max(0.0, rect.x() / img_w)
                y = max(0.0, rect.y() / img_h)
                width = min(1.0 - x, rect.width() / img_w)
                height = min(1.0 - y, rect.height() / img_h)
                self.region_drawn.emit(x, y, width, height)
            else:
                # Plain click, no real drag (Stage 12E-2 UX Fix click-to-
                # select) - hit-test and select/deselect. Only reachable in
                # rectangle mode; polygon mode's clicks are handled entirely
                # in mousePressEvent and never reach here.
                hit_region_id = self._hit_test_region(click_scene_pos)
                if hit_region_id != self._selected_region_id:
                    self.set_selected_region(hit_region_id)
                    if hit_region_id is not None:
                        self.region_selected.emit(hit_region_id)
                    else:
                        self.region_deselected.emit()
        super().mouseReleaseEvent(event)
