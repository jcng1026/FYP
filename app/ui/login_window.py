"""Login window: authenticates a user and opens their role dashboard."""

import random

from PySide6.QtCore import QPoint, QPointF, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.database.db import get_connection
from app.services.auth_service import login
from app.ui import brand
from app.ui.components import apply_card_shadow, apply_fixed_16_9_window
from app.ui.dialogs import show_error
from app.ui.developer_dashboard import DeveloperDashboard
from app.ui.student_dashboard import StudentDashboard
from app.ui.teacher_dashboard import TeacherDashboard

ROLE_DASHBOARDS = {
    "admin": DeveloperDashboard,
    "teacher": TeacherDashboard,
    "student": StudentDashboard,
}


def _new_bubble() -> dict:
    """One background bubble: position/size/opacity/velocity in normalized
    coordinates, mostly faint charcoal-white with the occasional teal."""
    return {
        "x": random.uniform(0.0, 1.0),
        "y": random.uniform(0.0, 1.0),
        "r": random.uniform(5, 42),
        "alpha": random.randint(8, 26),
        "speed": random.uniform(0.0004, 0.0016),
        "drift": random.uniform(-0.0003, 0.0003),
        "teal": random.random() < 0.35,
    }


def _make_bubbles(count: int) -> list:
    return [_new_bubble() for _ in range(count)]


class LoginWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MarkAssist — Sign in")
        self.setWindowIcon(brand.app_icon())
        apply_fixed_16_9_window(self)

        self._dashboard: QWidget | None = None
        self._shake_animation: QPropertyAnimation | None = None

        # "One door, three rooms": a single centered card on quiet charcoal.
        # The ground is alive: slow teal bubbles drift up behind the card and
        # shy away from the cursor (painted in paintEvent, driven by a timer).
        self.setObjectName("LoginHeroPanel")
        self._bubbles = _make_bubbles(count=26)
        self._cursor_pos: QPointF | None = None
        self.setMouseTracking(True)
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setInterval(33)
        self._bubble_timer.timeout.connect(self._advance_bubbles)
        self._bubble_timer.start()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)
        card_row = QHBoxLayout()
        card_row.addStretch(1)
        self._card = self._build_login_card()
        self._card.setFixedWidth(420)
        card_row.addWidget(self._card)
        card_row.addStretch(1)
        root.addLayout(card_row)
        root.addStretch(1)

    def _build_login_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LoginCard")
        apply_card_shadow(card, blur_radius=48, y_offset=14, alpha=90)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(40, 36, 40, 36)
        outer.setSpacing(6)

        # Brand lockup: logo + name, then the tagline.
        lockup = QHBoxLayout()
        lockup.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(brand.logo_pixmap(34))
        logo.setStyleSheet("background: transparent;")
        lockup.addWidget(logo)
        heading = QLabel(brand.APP_NAME)
        heading.setObjectName("LoginCardTitle")
        lockup.addWidget(heading)
        lockup.addStretch()

        subtitle = QLabel(brand.TAGLINE)
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)

        username_label = QLabel("Username")
        username_label.setObjectName("FieldLabel")

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your username")
        self.username_input.returnPressed.connect(self.handle_login)
        self.username_input.textChanged.connect(self._clear_field_error)

        password_label = QLabel("Password")
        password_label.setObjectName("FieldLabel")

        # Password field with a show/hide toggle inside the row.
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self.handle_login)
        self.password_input.textChanged.connect(self._clear_field_error)

        self.show_password_button = QPushButton("Show")
        self.show_password_button.setObjectName("RowActionButton")
        self.show_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_password_button.setFixedWidth(64)
        self.show_password_button.setToolTip("Show or hide the password")
        self.show_password_button.clicked.connect(self._toggle_password_visibility)

        password_row = QHBoxLayout()
        password_row.setSpacing(8)
        password_row.addWidget(self.password_input, stretch=1)
        password_row.addWidget(self.show_password_button)

        # Inline failure reason - faster and calmer than a modal.
        self.error_label = QLabel("")
        self.error_label.setObjectName("LoginErrorLabel")
        self.error_label.setStyleSheet("color: #E4572E; background: transparent; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.login_button = QPushButton("Sign In")
        self.login_button.setObjectName("PrimaryButton")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self.handle_login)

        outer.addLayout(lockup)
        outer.addWidget(subtitle)
        outer.addSpacing(22)
        outer.addWidget(username_label)
        outer.addWidget(self.username_input)
        outer.addSpacing(10)
        outer.addWidget(password_label)
        outer.addLayout(password_row)
        outer.addSpacing(8)
        outer.addWidget(self.error_label)
        outer.addSpacing(16)
        outer.addWidget(self.login_button)

        return card

    # --- animated bubble ground ---------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#303030"))
        painter.setPen(Qt.PenStyle.NoPen)
        for b in self._bubbles:
            x = b["x"] * self.width()
            y = b["y"] * self.height()
            color = QColor(20, 184, 166, b["alpha"]) if b["teal"] else QColor(255, 255, 255, b["alpha"])
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), b["r"], b["r"])
        painter.end()

    def _advance_bubbles(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        for b in self._bubbles:
            b["y"] -= b["speed"]                       # slow rise
            b["x"] += b["drift"]
            # Bubbles shy away from the cursor - the interactive part.
            if self._cursor_pos is not None:
                dx = b["x"] * width - self._cursor_pos.x()
                dy = b["y"] * height - self._cursor_pos.y()
                distance_sq = dx * dx + dy * dy
                if distance_sq < 150 * 150 and distance_sq > 1:
                    push = (150 * 150 - distance_sq) / (150 * 150) * 1.8
                    length = distance_sq ** 0.5
                    b["x"] += dx / length * push / width
                    b["y"] += dy / length * push / height
            # Wrap: a bubble leaving the top re-enters below with a new look.
            if b["y"] < -0.06:
                b.update(_new_bubble())
                b["y"] = 1.06
            b["x"] = max(-0.08, min(1.08, b["x"]))
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._cursor_pos = QPointF(event.position())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._cursor_pos = None
        super().leaveEvent(event)

    # --- interactivity helpers ----------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.username_input.clear()
            self.password_input.clear()
            self._clear_field_error()
            self.username_input.setFocus()
            return
        super().keyPressEvent(event)

    def _toggle_password_visibility(self) -> None:
        hidden = self.password_input.echoMode() == QLineEdit.EchoMode.Password
        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_password_button.setText("Hide" if hidden else "Show")

    def _clear_field_error(self) -> None:
        self.error_label.setVisible(False)
        for field in (self.username_input, self.password_input):
            field.setObjectName("")
            field.style().unpolish(field)
            field.style().polish(field)

    def _show_inline_error(self, message: str, focus_field: QLineEdit) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        focus_field.setObjectName("ValidatedInputError")
        focus_field.style().unpolish(focus_field)
        focus_field.style().polish(focus_field)
        focus_field.setFocus()
        self._shake_card()

    def _shake_card(self) -> None:
        """Short horizontal shake of the sign-in card on failure."""
        if self._shake_animation is not None:
            self._shake_animation.stop()
        origin = self._card.pos()
        animation = QPropertyAnimation(self._card, b"pos", self)
        animation.setDuration(280)
        for step, offset in enumerate((0, -8, 8, -5, 5, -2, 0)):
            animation.setKeyValueAt(step / 6, origin + QPoint(offset, 0))
        self._shake_animation = animation
        animation.start()

    def _set_signing_in(self, busy: bool) -> None:
        self.login_button.setEnabled(not busy)
        self.login_button.setText("Signing in..." if busy else "Sign In")

    # --- auth ----------------------------------------------------------------

    def handle_login(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username:
            self._show_inline_error("Enter your username.", self.username_input)
            return
        if not password:
            self._show_inline_error("Enter your password.", self.password_input)
            return

        self._clear_field_error()
        self._set_signing_in(True)
        # Let the button repaint to its busy state before the auth call.
        QTimer.singleShot(30, lambda: self._finish_login(username, password))

    def _finish_login(self, username: str, password: str) -> None:
        try:
            conn = get_connection()
            try:
                result = login(conn, username, password)
            finally:
                conn.close()
        finally:
            self._set_signing_in(False)

        if not result.success:
            self._show_inline_error(result.error_message, self.password_input)
            return

        dashboard_class = ROLE_DASHBOARDS.get(result.user.role)
        if dashboard_class is None:
            show_error(self, "Login Failed", f"Unknown role: {result.user.role}")
            return

        self._dashboard = dashboard_class(result.user)
        self._dashboard.show()
        self.close()
