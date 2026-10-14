"""Reusable layout building blocks: sidebar, header, paged app shell, stat cards."""

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui import styles

PREFERRED_WINDOW_WIDTH = 1920
PREFERRED_WINDOW_HEIGHT = 1080


def apply_fixed_16_9_window(
    widget: QWidget,
    preferred_width: int = PREFERRED_WINDOW_WIDTH,
    preferred_height: int = PREFERRED_WINDOW_HEIGHT,
) -> None:
    """Size widget to a fixed, non-resizable 16:9 window.

    Uses (preferred_width, preferred_height) - 1920x1080 by default - if the
    available screen can fit it, otherwise scales down to the largest 16:9
    size that fits the available screen geometry. The window is centered
    and cannot be resized by the user (setFixedSize removes the resize
    grips/maximize behavior in Qt).
    """
    screen = QGuiApplication.primaryScreen()
    width, height = preferred_width, preferred_height

    if screen is not None:
        available = screen.availableGeometry()
        if available.width() < width or available.height() < height:
            width = min(preferred_width, available.width())
            height = round(width * 9 / 16)
            if height > available.height():
                height = available.height()
                width = round(height * 16 / 9)

        widget.setFixedSize(width, height)
        widget.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )
    else:
        widget.setFixedSize(width, height)


def apply_card_shadow(widget: QWidget, blur_radius: int = 24, y_offset: int = 6, alpha: int = 30) -> None:
    """Give a card-like widget a subtle drop shadow for visual elevation."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur_radius)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


def create_page() -> Tuple[QWidget, QVBoxLayout]:
    """Create a content page widget with the standard content margins/spacing."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 28)
    layout.setSpacing(18)
    return page, layout


class StatCard(QFrame):
    """Small overview card showing a title and a prominent value.

    Interactive upgrades (UI interactivity round):
    - ``on_click``: makes the card a navigation entry point (pointer cursor,
      click fires the callback, hover lifts the shadow).
    - Numeric values count up briefly when they change, so a refreshed
      dashboard visibly reacts instead of silently swapping digits.
    """

    def __init__(self, title: str, value: str, parent: Optional[QWidget] = None,
                 on_click: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setMinimumWidth(170)
        self.setMaximumWidth(260)
        self._on_click = on_click
        self._count_animation: Optional[QVariantAnimation] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("StatCardTitle")
        title_label.setWordWrap(True)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatCardValue")
        self.value_label.setWordWrap(True)
        self.value_label.setMaximumWidth(220)

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

        apply_card_shadow(self)
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Open the related page")

    def set_on_click(self, on_click: Optional[Callable[[], None]]) -> None:
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor if on_click else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._on_click is not None and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._on_click is not None:
            apply_card_shadow(self, blur_radius=36, y_offset=10, alpha=60)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._on_click is not None:
            apply_card_shadow(self)
        super().leaveEvent(event)

    def set_value(self, value: str) -> None:
        """Set the displayed value; a plain-integer change counts up briefly."""
        old_text = self.value_label.text()
        if (value.isdigit() and old_text.isdigit() and value != old_text
                and abs(int(value) - int(old_text)) > 1):
            if self._count_animation is not None:
                self._count_animation.stop()
            animation = QVariantAnimation(self)
            animation.setStartValue(int(old_text))
            animation.setEndValue(int(value))
            animation.setDuration(450)
            animation.valueChanged.connect(
                lambda v: self.value_label.setText(str(int(v))))
            animation.finished.connect(
                lambda: self.value_label.setText(value))
            self._count_animation = animation
            animation.start()
            return
        self.value_label.setText(value)


class CircularProgressWidget(QFrame):
    """A circular progress indicator with a percentage shown inside the
    circle and a current-step status label below it (Stage 11V). Used for
    long-running question-paper/answer-scheme/student-PDF processing so
    the teacher always sees a percentage and a clear "what's happening
    right now" line, per the Stage 11V spec's circular-progress
    requirement."""

    DIAMETER = 120
    THICKNESS = 10

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CircularProgressWidget")
        self._percentage = 0
        self._elapsed = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._circle = _CircularProgressCircle(self.DIAMETER, self.THICKNESS)
        layout.addWidget(self._circle, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.status_label)

        self.elapsed_label = QLabel("")
        self.elapsed_label.setObjectName("StatusLabel")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.elapsed_label)

    def set_progress(self, message: str, current: int, total: int) -> None:
        """Update the displayed percentage and status text. total <= 0 is
        treated as an indeterminate 0%, so callers never need to guard
        against a division by zero. The first update starts a visible
        elapsed-time counter so a long OCR run never looks frozen."""
        if not self._elapsed.isValid():
            self._elapsed.start()
            self._elapsed_timer.start()
        percentage = int(round(current / total * 100)) if total > 0 else 0
        percentage = max(0, min(100, percentage))
        self._percentage = percentage
        self._circle.set_percentage(percentage)
        self.status_label.setText(message)
        self._update_elapsed_label()

    def _update_elapsed_label(self) -> None:
        if not self._elapsed.isValid():
            return
        seconds = self._elapsed.elapsed() // 1000
        self.elapsed_label.setText(f"Elapsed {seconds // 60}:{seconds % 60:02d}")

    def percentage(self) -> int:
        return self._percentage

    def reset(self) -> None:
        self._percentage = 0
        self._circle.set_percentage(0)
        self.status_label.setText("")
        self.elapsed_label.setText("")
        self._elapsed.invalidate()
        self._elapsed_timer.stop()


class _CircularProgressCircle(QWidget):
    """Paints the actual ring + centered percentage text for
    CircularProgressWidget."""

    def __init__(self, diameter: int, thickness: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._thickness = thickness
        self._percentage = 0
        self.setFixedSize(diameter, diameter)

    def set_percentage(self, percentage: int) -> None:
        self._percentage = percentage
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = self._thickness / 2 + 2
        rect = QRectF(margin, margin, self._diameter - 2 * margin, self._diameter - 2 * margin)

        track_pen = QPen(QColor(styles.BORDER), self._thickness)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        progress_pen = QPen(QColor(styles.ACCENT), self._thickness)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        span_angle = int(360 * (self._percentage / 100) * 16)
        painter.drawArc(rect, 90 * 16, -span_angle)

        painter.setPen(QColor(styles.TEXT))
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self._percentage}%")
        painter.end()


class CollapsibleSection(QFrame):
    """A section with a clickable header that shows/hides its body widget
    (Stage 11V) - no generic collapsible/expandable widget existed
    anywhere in this codebase before, so this is a new, minimal building
    block used by the marking editor's five side sections."""

    def __init__(self, title: str, parent: Optional[QWidget] = None, expanded: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.toggle_button = QPushButton(self._header_text(title))
        self.toggle_button.setObjectName("CollapsibleSectionHeader")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self.toggle)
        outer.addWidget(self.toggle_button)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 8, 12, 12)
        self.body_layout.setSpacing(8)
        outer.addWidget(self.body)

        self._title = title
        self.body.setVisible(self._expanded)

    def _header_text(self, title: str) -> str:
        arrow = "▼" if self._expanded else "▶"
        return f"{arrow}  {title}"

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.body.setVisible(expanded)
        self.toggle_button.setText(self._header_text(self._title))

    def is_expanded(self) -> bool:
        return self._expanded

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def clear_body(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class NavButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Sidebar(QFrame):
    def __init__(
        self,
        brand_text: str,
        nav_items: List[str],
        active_item: str,
        on_nav_selected: Callable[[str], None],
        on_logout: Callable[[], None],
        parent: Optional[QWidget] = None,
        group_headings: Optional[Dict[str, str]] = None,
    ) -> None:
        """group_headings optionally maps a nav item name to a visible group
        heading label rendered immediately above it (e.g. "MAIN MARKING
        SYSTEM" above the "Marking" item) - purely cosmetic, does not affect
        navigation. Omitted/None (the default) renders a flat list exactly
        as before, so existing callers are unaffected."""
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        self._buttons: Dict[str, NavButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(6)

        from app.ui import brand as brand_assets

        # The brand block is a "home" affordance: clicking it returns to the
        # first nav page (the dashboard), like a website logo.
        self._home_item = nav_items[0] if nav_items else None
        self._on_nav_selected = on_nav_selected
        brand_widget = QWidget()
        brand_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        brand_widget.setToolTip("Back to the dashboard")
        brand_row = QHBoxLayout(brand_widget)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(9)
        brand_logo = QLabel()
        brand_logo.setPixmap(brand_assets.logo_pixmap(26))
        brand_logo.setStyleSheet("background: transparent;")
        brand_row.addWidget(brand_logo)
        brand = QLabel(brand_text)
        brand.setObjectName("SidebarBrand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        brand_widget.mousePressEvent = lambda _event: self._go_home()
        layout.addWidget(brand_widget)
        layout.addSpacing(24)

        group_headings = group_headings or {}
        for item in nav_items:
            heading_text = group_headings.get(item)
            if heading_text:
                heading_label = QLabel(heading_text)
                heading_label.setObjectName("SidebarGroupHeading")
                layout.addSpacing(12)
                layout.addWidget(heading_label)

            button = NavButton(item)
            button.setChecked(item == active_item)
            button.clicked.connect(lambda _checked=False, name=item: on_nav_selected(name))
            self._button_group.addButton(button)
            self._buttons[item] = button
            layout.addWidget(button)

        layout.addStretch()

        self._on_logout = on_logout
        logout_button = QPushButton("Logout")
        logout_button.setObjectName("LogoutButton")
        logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_button.clicked.connect(self._confirm_logout)
        layout.addWidget(logout_button)

    def _go_home(self) -> None:
        if self._home_item is not None:
            self._on_nav_selected(self._home_item)

    def _confirm_logout(self) -> None:
        """Ask before ending the session - an accidental click on Logout
        otherwise silently throws away the teacher's place in the app."""
        from app.ui.dialogs import prompt_confirm  # local import: dialogs imports components

        if prompt_confirm(self.window(), "Log Out",
                          "End this session and return to the sign-in screen?",
                          confirm_text="Log Out"):
            self._on_logout()

    def set_active(self, name: str) -> None:
        button = self._buttons.get(name)
        if button is not None:
            button.setChecked(True)

    def nav_item_names(self) -> List[str]:
        return list(self._buttons.keys())


class Header(QFrame):
    def __init__(
        self,
        title: str,
        subtitle: str,
        user_full_name: str,
        user_role_label: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Header")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 18)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("HeadingLabel")
        title_label.setWordWrap(True)
        title_label.setMaximumWidth(480)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("StatusLabel")
        subtitle_label.setWordWrap(True)
        subtitle_label.setMaximumWidth(480)
        text_column.addWidget(title_label)
        text_column.addWidget(subtitle_label)
        layout.addLayout(text_column)

        layout.addStretch()

        user_chip = QLabel(f"{user_full_name}  •  {user_role_label}")
        user_chip.setObjectName("UserChip")
        layout.addWidget(user_chip, alignment=Qt.AlignmentFlag.AlignVCenter)


class AppShell(QWidget):
    """Sidebar + header + paged content area shared by all dashboards.

    Callers build one QWidget per sidebar nav item and register it with
    ``add_page(name, widget)``. Clicking a sidebar item (or calling
    ``show_page(name)`` directly, e.g. from a quick-action button) switches
    the visible page and syncs the sidebar's active/checked state.
    """

    def __init__(
        self,
        brand_text: str,
        nav_items: List[str],
        header_title: str,
        header_subtitle: str,
        user_full_name: str,
        user_role_label: str,
        on_logout: Callable[[], None],
        parent: Optional[QWidget] = None,
        group_headings: Optional[Dict[str, str]] = None,
        on_page_shown: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)

        self._pages: Dict[str, QWidget] = {}
        self._on_page_shown = on_page_shown

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(
            brand_text, nav_items, nav_items[0], self.show_page, on_logout, group_headings=group_headings
        )
        root.addWidget(self.sidebar)

        right_widget = QWidget()
        right_column = QVBoxLayout(right_widget)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(0)

        self.header = Header(header_title, header_subtitle, user_full_name, user_role_label)
        right_column.addWidget(self.header)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("ContentScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.pages_stack = QStackedWidget()
        self.pages_stack.setObjectName("ContentArea")

        scroll_area.setWidget(self.pages_stack)
        right_column.addWidget(scroll_area)

        root.addWidget(right_widget)

        # Ctrl+K: jump to any sidebar page by typing part of its name.
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self.open_command_palette)

    def open_command_palette(self) -> None:
        dialog = CommandPaletteDialog(self, self.sidebar.nav_item_names(), self.show_page)
        dialog.exec()

    def add_page(self, name: str, widget: QWidget) -> None:
        """Register a page widget under the given sidebar nav label."""
        self._pages[name] = widget
        self.pages_stack.addWidget(widget)

    def show_page(self, name: str) -> None:
        """Switch the visible page and sync the sidebar's active state."""
        widget = self._pages.get(name)
        if widget is None:
            return
        self.pages_stack.setCurrentWidget(widget)
        self.sidebar.set_active(name)
        if self._on_page_shown is not None:
            self._on_page_shown(name)


class CommandPaletteDialog(QDialog):
    """Ctrl+K quick navigation: type to filter the sidebar pages, Enter (or a
    click) jumps to the highlighted one."""

    def __init__(self, parent: QWidget, page_names: List[str],
                 on_navigate: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(420)
        self._on_navigate = on_navigate

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=60)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Jump to page...  (Esc to close)")
        self.search_input.textChanged.connect(self._filter)
        self.search_input.returnPressed.connect(self._activate_current)
        card_layout.addWidget(self.search_input)

        self.results = QListWidget()
        self.results.setFixedHeight(220)
        for name in page_names:
            QListWidgetItem(name, self.results)
        if self.results.count():
            self.results.setCurrentRow(0)
        self.results.itemActivated.connect(lambda item: self._navigate(item.text()))
        self.results.itemClicked.connect(lambda item: self._navigate(item.text()))
        card_layout.addWidget(self.results)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(card)
        self.search_input.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Arrow keys move the highlighted result even while typing.
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.results.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            visible = [i for i in range(self.results.count())
                       if not self.results.item(i).isHidden()]
            if visible:
                candidates = [i for i in visible if (i > self.results.currentRow())] \
                    if event.key() == Qt.Key.Key_Down else \
                    [i for i in reversed(visible) if (i < self.results.currentRow())]
                self.results.setCurrentRow(candidates[0] if candidates else self.results.currentRow())
            return
        super().keyPressEvent(event)

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        first_visible = None
        for i in range(self.results.count()):
            item = self.results.item(i)
            match = needle in item.text().lower()
            item.setHidden(not match)
            if match and first_visible is None:
                first_visible = i
        if first_visible is not None:
            self.results.setCurrentRow(first_visible)

    def _activate_current(self) -> None:
        item = self.results.currentItem()
        if item is not None and not item.isHidden():
            self._navigate(item.text())

    def _navigate(self, name: str) -> None:
        self.accept()
        self._on_navigate(name)


def attach_table_filter(table: QTableWidget, placeholder: str = "Search...") -> QLineEdit:
    """Return a search box wired to the table: typing hides every row whose
    cells contain no match (case-insensitive). Purely visual - row data,
    cell widgets and selection handling are untouched."""
    search = QLineEdit()
    search.setObjectName("TableSearchInput")
    search.setPlaceholderText(placeholder)
    search.setClearButtonEnabled(True)
    search.setMaximumWidth(320)

    def apply_filter(text: str) -> None:
        needle = text.strip().lower()
        for row in range(table.rowCount()):
            if not needle:
                table.setRowHidden(row, False)
                continue
            match = False
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None and needle in item.text().lower():
                    match = True
                    break
            table.setRowHidden(row, not match)

    search.textChanged.connect(apply_filter)
    return search


def paint_status_item(item, status_text: str) -> None:
    """Colour a table status cell so state reads at a glance without reading:
    teal for done/ready, amber for waiting-on-someone, red for blocked or
    failed. Unknown statuses keep the default text colour."""
    lowered = status_text.lower()
    if any(k in lowered for k in ("ready", "final", "marked -", "completed", "active", "connected")):
        color = QColor("#14B8A6")   # teal - done
    elif any(k in lowered for k in ("blocked", "failed", "error", "deactivated", "rejected")):
        color = QColor("#E4572E")   # red - needs intervention
    elif any(k in lowered for k in ("uploaded", "pending", "marking", "processing", "draft", "needs")):
        color = QColor("#F59E0B")   # amber - in flight
    else:
        return
    item.setForeground(color)
    font = item.font()
    font.setBold(True)
    item.setFont(font)


def show_toast(parent: QWidget, message: str, duration_ms: int = 2600) -> None:
    """Corner toast for low-stakes confirmations: appears bottom-right of the
    window and dismisses itself - no click required. Use modals for anything
    the user must acknowledge."""
    window = parent.window() if parent is not None else None
    if window is None:
        return
    toast = QLabel(message, window)
    toast.setObjectName("Toast")
    toast.setWordWrap(True)
    toast.setMaximumWidth(360)
    toast.adjustSize()
    margin = 24
    toast.move(window.width() - toast.width() - margin,
               window.height() - toast.height() - margin)
    toast.show()
    toast.raise_()
    QTimer.singleShot(duration_ms, toast.deleteLater)
