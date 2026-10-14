"""Custom modal feedback popup (success/error/warning/info), replacing QMessageBox.

Visual style (rounded card, icon badge, title, message, single confirm button)
is an original adaptation matching this app's purple/light theme - no assets
or exact artwork copied from any reference image.
"""

from typing import Any, List, Optional, Tuple

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui import styles
from app.ui.components import apply_card_shadow

_KIND_STYLES = {
    "success": ("✓", styles.SUCCESS, styles.SUCCESS_LIGHT),
    "error": ("✕", styles.DESTRUCTIVE, styles.DESTRUCTIVE_LIGHT),
    "warning": ("!", styles.WARNING, styles.WARNING_LIGHT),
    "info": ("i", styles.ACCENT, styles.ACCENT_LIGHT),
}

_SOUND_KINDS = {"success", "info"}

CANCELLED = object()
"""Sentinel returned by prompt_select() when the dialog is dismissed without
confirming, distinguishing that from a confirmed selection whose value is
legitimately None (e.g. an "unassigned" placeholder option)."""


def _play_confirmation_sound() -> None:
    """Play a short built-in system beep. Never raises - sound is optional polish."""
    try:
        QApplication.beep()
    except Exception:
        pass


class FeedbackDialog(QDialog):
    """Rounded-card popup used for success/error/warning/info feedback."""

    def __init__(self, parent: Optional[QWidget], kind: str, title: str, message: str) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)

        symbol, color, light_color = _KIND_STYLES.get(kind, _KIND_STYLES["info"])

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        badge = QLabel(symbol)
        badge.setFixedSize(56, 56)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {light_color}; color: {color}; "
            f"border-radius: 28px; font-size: 22px; font-weight: 700;"
        )
        card_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        ok_button = QPushButton("OK")
        ok_button.setObjectName("PrimaryButton")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        card_layout.addSpacing(6)
        card_layout.addWidget(ok_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

        if kind in _SOUND_KINDS:
            _play_confirmation_sound()


def _show(parent: Optional[QWidget], kind: str, title: str, message: str) -> None:
    dialog = FeedbackDialog(parent, kind, title, message)
    dialog.exec()


def show_success(parent: Optional[QWidget], title: str, message: str) -> None:
    _show(parent, "success", title, message)


def show_error(parent: Optional[QWidget], title: str, message: str) -> None:
    _show(parent, "error", title, message)


def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    _show(parent, "warning", title, message)


def show_info(parent: Optional[QWidget], title: str, message: str) -> None:
    _show(parent, "info", title, message)


class DetailDialog(QDialog):
    """Wider rounded-card modal for read-only text that is too long to fit
    comfortably in FeedbackDialog's fixed narrow width (e.g. file paths) -
    the text is wrapped, scrollable, and selectable/copyable."""

    def __init__(self, parent: Optional[QWidget], title: str, message: str) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(560)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        text_area = QPlainTextEdit(message)
        text_area.setReadOnly(True)
        text_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        text_area.setMinimumHeight(220)
        text_area.setMaximumHeight(320)
        card_layout.addWidget(text_area)

        ok_button = QPushButton("OK")
        ok_button.setObjectName("PrimaryButton")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        card_layout.addSpacing(6)
        card_layout.addWidget(ok_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)


def show_detail(parent: Optional[QWidget], title: str, message: str) -> None:
    """Show a wider, scrollable popup for longer read-only text (e.g. file paths)
    that the user needs to fully read or copy, unlike the narrow FeedbackDialog."""
    dialog = DetailDialog(parent, title, message)
    dialog.exec()


class PasswordRevealDialog(QDialog):
    """Small rounded-card modal that displays a sensitive value only after
    the user explicitly checks 'Show password?' - used for the student
    visible temporary password, which must never be revealed by default."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        subject_line: str,
        password_value: str,
        is_available: bool,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)

        self._password_value = password_value
        self._is_available = is_available

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        subject_label = QLabel(subject_line)
        subject_label.setObjectName("StatusLabel")
        subject_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subject_label.setWordWrap(True)
        card_layout.addWidget(subject_label)

        self.value_label = QLabel(self._display_text(revealed=False))
        self.value_label.setObjectName("StatusLabel")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setWordWrap(True)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.value_label)

        if is_available:
            show_password_checkbox = QCheckBox("Show password?")
            show_password_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
            show_password_checkbox.toggled.connect(self._on_show_password_toggled)
            card_layout.addWidget(show_password_checkbox)

        ok_button = QPushButton("OK")
        ok_button.setObjectName("PrimaryButton")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        card_layout.addSpacing(6)
        card_layout.addWidget(ok_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def _display_text(self, revealed: bool) -> str:
        if not self._is_available:
            return self._password_value
        return self._password_value if revealed else "•" * 10

    def _on_show_password_toggled(self, checked: bool) -> None:
        self.value_label.setText(self._display_text(revealed=checked))


def show_password_reveal(
    parent: Optional[QWidget],
    title: str,
    subject_line: str,
    password_value: str,
    is_available: bool = True,
) -> None:
    """Show a modal that hides a sensitive value (masked dots) until the
    user checks 'Show password?'. When is_available is False, password_value
    is assumed to already be a non-sensitive fallback message and is shown
    as-is with no checkbox."""
    dialog = PasswordRevealDialog(parent, title, subject_line, password_value, is_available)
    dialog.exec()


class InputDialog(QDialog):
    """Small rounded-card modal that collects a single text value."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        placeholder: str = "",
        is_password: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(placeholder)
        if is_password:
            self.input_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_field.returnPressed.connect(self.accept)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.input_field)

        if is_password:
            show_password_checkbox = QCheckBox("Show password?")
            show_password_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
            show_password_checkbox.toggled.connect(
                lambda checked: self.input_field.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                )
            )
            card_layout.addWidget(show_password_checkbox)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton("Confirm")
        confirm_button.setObjectName("PrimaryButton")
        confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(confirm_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def value(self) -> str:
        return self.input_field.text()


def prompt_input(
    parent: Optional[QWidget],
    title: str,
    message: str,
    placeholder: str = "",
    is_password: bool = False,
) -> Optional[str]:
    """Show a small modal text-input dialog; return the entered value, or None if cancelled."""
    dialog = InputDialog(parent, title, message, placeholder, is_password)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.value()
    return None


class SelectDialog(QDialog):
    """Small rounded-card modal that collects a single choice from a dropdown."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        options: List[Tuple[str, Any]],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        self.combo = QComboBox()
        for label, value in options:
            self.combo.addItem(label, value)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.combo)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton("Confirm")
        confirm_button.setObjectName("PrimaryButton")
        confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(confirm_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def value(self) -> Any:
        return self.combo.currentData()


def prompt_select(
    parent: Optional[QWidget],
    title: str,
    message: str,
    options: List[Tuple[str, Any]],
) -> Any:
    """Show a small modal dropdown-selection dialog.

    Returns the chosen value if confirmed - which may legitimately be None,
    e.g. for an "unassigned"/"no selection" placeholder option - or the
    CANCELLED sentinel if the user dismissed the dialog without confirming.
    """
    if not options:
        return CANCELLED
    dialog = SelectDialog(parent, title, message, options)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.value()
    return CANCELLED


class CandidateTableDialog(QDialog):
    """Wider rounded-card modal listing candidate rows in a table, each with
    a per-row 'Select' button - used where a single dropdown isn't
    informative enough (e.g. showing a student's current class/teacher and
    expected action before picking them)."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        column_labels: List[str],
        rows: List[Tuple[List[str], Any]],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(1020)

        self._selected_value: Any = CANCELLED

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        columns = column_labels + ["actions"]
        self.table = QTableWidget(len(rows), len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(len(columns) - 1, 90)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(280)
        self.table.setMaximumHeight(420)

        for row_index, (values, value) in enumerate(rows):
            for col_index, cell_text in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(cell_text)))
            select_button = QPushButton("Select")
            select_button.setObjectName("RowActionButton")
            select_button.setCursor(Qt.CursorShape.PointingHandCursor)
            select_button.clicked.connect(lambda _checked=False, v=value: self._select(v))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.addWidget(select_button)
            self.table.setCellWidget(row_index, len(columns) - 1, cell)
        self.table.doItemsLayout()

        card_layout.addWidget(self.table)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        card_layout.addWidget(cancel_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def _select(self, value: Any) -> None:
        self._selected_value = value
        self.accept()

    def value(self) -> Any:
        return self._selected_value


def prompt_select_from_table(
    parent: Optional[QWidget],
    title: str,
    message: str,
    column_labels: List[str],
    rows: List[Tuple[List[str], Any]],
) -> Any:
    """Show a modal table of candidate rows, each with its own 'Select' button.

    rows is a list of (display_values, return_value) pairs. Returns the
    return_value of whichever row was selected, or the CANCELLED sentinel if
    the dialog was dismissed without picking a row.
    """
    if not rows:
        return CANCELLED
    dialog = CandidateTableDialog(parent, title, message, column_labels, rows)
    dialog.exec()
    return dialog.value()


class ConfirmDialog(QDialog):
    """Small rounded-card modal asking the user to confirm a (typically destructive) action."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        confirm_text: str = "Confirm",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)

        symbol, color, light_color = _KIND_STYLES["warning"]

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        badge = QLabel(symbol)
        badge.setFixedSize(56, 56)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {light_color}; color: {color}; "
            f"border-radius: 28px; font-size: 22px; font-weight: 700;"
        )
        card_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton(confirm_text)
        confirm_button.setObjectName("DestructiveButton")
        confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(confirm_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)


def prompt_confirm(
    parent: Optional[QWidget],
    title: str,
    message: str,
    confirm_text: str = "Confirm",
) -> bool:
    """Show a small modal confirmation dialog; return True only if the user confirms."""
    dialog = ConfirmDialog(parent, title, message, confirm_text)
    return dialog.exec() == QDialog.DialogCode.Accepted


class ThreeWayChoiceDialog(QDialog):
    """Marking Fix Follow-up: like ConfirmDialog, but for a warning with a
    THIRD, more useful option than a bare Confirm/Cancel - e.g. "Answer Key
    Incomplete" should offer "Open Answer Key Setup" (go fix it now) as
    well as "Continue Anyway" (proceed as-is) and "Cancel" (back out),
    rather than forcing a teacher to guess/back out entirely just to go
    fix the missing entries."""

    def __init__(
        self, parent: Optional[QWidget], title: str, message: str,
        primary_text: str, secondary_text: str,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(420)

        self.choice = "cancel"

        symbol, color, light_color = _KIND_STYLES["warning"]

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        badge = QLabel(symbol)
        badge.setFixedSize(56, 56)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {light_color}; color: {color}; "
            f"border-radius: 28px; font-size: 22px; font-weight: 700;"
        )
        card_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self._choose_cancel)

        secondary_button = QPushButton(secondary_text)
        secondary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        secondary_button.clicked.connect(self._choose_secondary)

        primary_button = QPushButton(primary_text)
        primary_button.setObjectName("PrimaryButton")
        primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        primary_button.setDefault(True)
        primary_button.clicked.connect(self._choose_primary)

        buttons_column = QVBoxLayout()
        buttons_column.setSpacing(8)
        buttons_column.addWidget(primary_button)
        buttons_column.addWidget(secondary_button)
        buttons_column.addWidget(cancel_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_column)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def _choose_primary(self) -> None:
        self.choice = "primary"
        self.accept()

    def _choose_secondary(self) -> None:
        self.choice = "secondary"
        self.accept()

    def _choose_cancel(self) -> None:
        self.choice = "cancel"
        self.reject()


def prompt_three_way_choice(
    parent: Optional[QWidget], title: str, message: str, primary_text: str, secondary_text: str,
) -> str:
    """Show a 3-button modal warning; returns "primary", "secondary", or
    "cancel" depending on which button the user picked (or "cancel" if the
    dialog was dismissed/closed without a button click)."""
    dialog = ThreeWayChoiceDialog(parent, title, message, primary_text, secondary_text)
    dialog.exec()
    return dialog.choice


class EditRegionDialog(QDialog):
    """Rounded-card modal form for editing a template region's descriptive
    fields (name, type, order, rotation angle, notes). Raw coordinates
    (x/y/width/height) are intentionally not shown or editable here - use
    "Redefine Region?" to redraw a region's rectangle on the preview
    instead (Stage 11F). Rotation Angle (Stage 11J) is a plain numeric
    field validated by the caller, not this dialog."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        region_type_options: List[Tuple[str, str]],
        initial: dict,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        self._action = "cancel"

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        self.name_input = QLineEdit(str(initial.get("label", "")))
        self.type_dropdown = QComboBox()
        for label_text, value in region_type_options:
            self.type_dropdown.addItem(label_text, value)
        current_type_index = self.type_dropdown.findData(initial.get("region_type"))
        if current_type_index >= 0:
            self.type_dropdown.setCurrentIndex(current_type_index)

        self.order_input = QLineEdit(str(initial.get("order_index", 1)))
        self.rotation_angle_input = QLineEdit(str(initial.get("rotation_angle", 0.0)))
        self.notes_input = QLineEdit(str(initial.get("notes") or ""))
        self.page_number_label = QLabel(str(initial.get("page_number", 1)))
        self.page_number_label.setObjectName("StatusLabel")

        card_layout.addWidget(field_label("Region Name"))
        card_layout.addWidget(self.name_input)
        card_layout.addWidget(field_label("Region Type"))
        card_layout.addWidget(self.type_dropdown)

        page_order_row = QHBoxLayout()
        page_column = QVBoxLayout()
        page_column.addWidget(field_label("Page Number"))
        page_column.addWidget(self.page_number_label)
        order_column = QVBoxLayout()
        order_column.addWidget(field_label("Region Order"))
        order_column.addWidget(self.order_input)
        page_order_row.addLayout(page_column)
        page_order_row.addLayout(order_column)
        card_layout.addLayout(page_order_row)

        card_layout.addWidget(field_label("Rotation Angle (degrees, -180 to 180)"))
        card_layout.addWidget(self.rotation_angle_input)

        card_layout.addWidget(field_label("Notes (optional)"))
        card_layout.addWidget(self.notes_input)

        redefine_button = QPushButton("Redefine Region?")
        redefine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        redefine_button.clicked.connect(self._handle_redefine)
        card_layout.addSpacing(4)
        card_layout.addWidget(redefine_button)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self._handle_save)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def _handle_save(self) -> None:
        self._action = "save"
        self.accept()

    def _handle_redefine(self) -> None:
        self._action = "redefine"
        self.accept()

    def values(self) -> dict:
        return {
            "label": self.name_input.text(),
            "region_type": self.type_dropdown.currentData(),
            "order_index": self.order_input.text(),
            "rotation_angle": self.rotation_angle_input.text(),
            "notes": self.notes_input.text(),
            "action": self._action,
        }


def prompt_edit_region(
    parent: Optional[QWidget],
    title: str,
    region_type_options: List[Tuple[str, str]],
    initial: dict,
) -> Optional[dict]:
    """Show a modal form for editing a template region's name/type/order/
    notes (page number is shown read-only; raw x/y/width/height are not
    shown at all - see EditRegionDialog).

    Returns a dict of raw string field values (plus an "action" key of
    "save" or "redefine") if the dialog was accepted, or None if cancelled.
    Numeric parsing and validation happen in the caller.
    """
    dialog = EditRegionDialog(parent, title, region_type_options, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class RegionGroupDialog(QDialog):
    """Rounded-card modal form for creating or editing a region group's
    name/type/notes (Stage 11H). Used both to name a brand-new group formed
    from selected regions, and to edit an existing group's metadata -
    membership/order are not touched by this dialog."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        region_type_options: List[Tuple[str, str]],
        initial: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        initial = initial or {}
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        self.name_input = QLineEdit(str(initial.get("label", "")))
        self.type_dropdown = QComboBox()
        for label_text, value in region_type_options:
            self.type_dropdown.addItem(label_text, value)
        current_type_index = self.type_dropdown.findData(initial.get("region_type"))
        if current_type_index >= 0:
            self.type_dropdown.setCurrentIndex(current_type_index)
        self.notes_input = QLineEdit(str(initial.get("notes") or ""))

        card_layout.addSpacing(4)
        card_layout.addWidget(field_label("Group Name"))
        card_layout.addWidget(self.name_input)
        card_layout.addWidget(field_label("Group Type"))
        card_layout.addWidget(self.type_dropdown)
        card_layout.addWidget(field_label("Notes (optional)"))
        card_layout.addWidget(self.notes_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton("Confirm")
        confirm_button.setObjectName("PrimaryButton")
        confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(confirm_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "label": self.name_input.text(),
            "region_type": self.type_dropdown.currentData(),
            "notes": self.notes_input.text(),
        }


def prompt_region_group_form(
    parent: Optional[QWidget],
    title: str,
    message: str,
    region_type_options: List[Tuple[str, str]],
    initial: Optional[dict] = None,
) -> Optional[dict]:
    """Show a modal form for naming/typing a region group (create or edit).

    Returns a dict of raw string field values ("label", "region_type",
    "notes") if the dialog was accepted, or None if cancelled. Validation
    happens in the caller (app.services.template_region_group_service).
    """
    dialog = RegionGroupDialog(parent, title, message, region_type_options, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class StudentInfoDialog(QDialog):
    """Rounded-card modal form for editing a Main Marking System answer
    file's optional student name/code (Stage 11L). Both fields are prefilled
    with their current values so the teacher edits rather than retypes."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        initial: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        initial = initial or {}
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("StatusLabel")
        message_label.setWordWrap(True)
        card_layout.addWidget(message_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        self.student_name_input = QLineEdit(str(initial.get("student_name") or ""))
        self.student_code_input = QLineEdit(str(initial.get("student_code") or ""))

        card_layout.addSpacing(4)
        card_layout.addWidget(field_label("Student Name (optional)"))
        card_layout.addWidget(self.student_name_input)
        card_layout.addWidget(field_label("Student Code (optional)"))
        card_layout.addWidget(self.student_code_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton("Save")
        confirm_button.setObjectName("PrimaryButton")
        confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(confirm_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "student_name": self.student_name_input.text(),
            "student_code": self.student_code_input.text(),
        }


def prompt_student_info(
    parent: Optional[QWidget],
    title: str,
    message: str,
    initial: Optional[dict] = None,
) -> Optional[dict]:
    """Show a modal form for editing an answer file's optional student
    name/code.

    Returns a dict of raw string field values ("student_name",
    "student_code") if the dialog was accepted, or None if cancelled.
    """
    dialog = StudentInfoDialog(parent, title, message, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class MarkingQuestionDialog(QDialog):
    """Rounded-card modal form for adding/editing a marking question (Kertas 1
    answer key row) or a rubric criterion placeholder (Kertas 2)."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        question_type_options: List[Tuple[str, str]],
        region_options: List[Tuple[str, Any]],
        initial: dict,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        self.question_no_input = QLineEdit(str(initial.get("question_no", "")))
        self.correct_answer_input = QLineEdit(str(initial.get("correct_answer", "")))
        self.max_mark_input = QLineEdit(str(initial.get("max_mark", "")))

        self.question_type_dropdown = QComboBox()
        for label_text, value in question_type_options:
            self.question_type_dropdown.addItem(label_text, value)
        current_type_index = self.question_type_dropdown.findData(initial.get("question_type"))
        if current_type_index >= 0:
            self.question_type_dropdown.setCurrentIndex(current_type_index)

        self.explanation_input = QLineEdit(str(initial.get("explanation") or ""))

        self.region_dropdown = QComboBox()
        self.region_dropdown.addItem("-- No Region --", None)
        for label_text, value in region_options:
            self.region_dropdown.addItem(label_text, value)
        current_region_index = self.region_dropdown.findData(initial.get("region_id"))
        if current_region_index >= 0:
            self.region_dropdown.setCurrentIndex(current_region_index)

        self.display_order_input = QLineEdit(str(initial.get("display_order", 1)))

        card_layout.addWidget(field_label("Question No / Criterion Name"))
        card_layout.addWidget(self.question_no_input)
        card_layout.addWidget(field_label("Correct Answer (required for Kertas 1)"))
        card_layout.addWidget(self.correct_answer_input)

        mark_type_row = QHBoxLayout()
        mark_column = QVBoxLayout()
        mark_column.addWidget(field_label("Max Mark"))
        mark_column.addWidget(self.max_mark_input)
        type_column = QVBoxLayout()
        type_column.addWidget(field_label("Question Type"))
        type_column.addWidget(self.question_type_dropdown)
        mark_type_row.addLayout(mark_column)
        mark_type_row.addLayout(type_column)
        card_layout.addLayout(mark_type_row)

        card_layout.addWidget(field_label("Explanation (optional)"))
        card_layout.addWidget(self.explanation_input)

        card_layout.addWidget(field_label("Linked Region (optional)"))
        card_layout.addWidget(self.region_dropdown)

        card_layout.addWidget(field_label("Display Order"))
        card_layout.addWidget(self.display_order_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "question_no": self.question_no_input.text(),
            "correct_answer": self.correct_answer_input.text(),
            "max_mark": self.max_mark_input.text(),
            "question_type": self.question_type_dropdown.currentData(),
            "explanation": self.explanation_input.text(),
            "region_id": self.region_dropdown.currentData(),
            "display_order": self.display_order_input.text(),
        }


def prompt_marking_question(
    parent: Optional[QWidget],
    title: str,
    question_type_options: List[Tuple[str, str]],
    region_options: List[Tuple[str, Any]],
    initial: dict,
) -> Optional[dict]:
    """Show a modal form for adding/editing a marking question or rubric criterion.

    Returns a dict of raw string field values if saved, or None if cancelled.
    Numeric parsing and validation happen in the caller.
    """
    dialog = MarkingQuestionDialog(parent, title, question_type_options, region_options, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class ReviewItemDialog(QDialog):
    """Rounded-card modal form for a teacher to accept or override one
    marking-review item's final score/correctness/comment."""

    def __init__(self, parent: Optional[QWidget], title: str, context: str, initial: dict) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        context_label = QLabel(context)
        context_label.setObjectName("StatusLabel")
        context_label.setWordWrap(True)
        card_layout.addWidget(context_label)

        self.final_score_input = QLineEdit(str(initial.get("final_score_awarded", "")))
        self.final_is_correct_dropdown = QComboBox()
        self.final_is_correct_dropdown.addItem("Correct", True)
        self.final_is_correct_dropdown.addItem("Wrong", False)
        current_index = self.final_is_correct_dropdown.findData(bool(initial.get("final_is_correct")))
        if current_index >= 0:
            self.final_is_correct_dropdown.setCurrentIndex(current_index)

        self.teacher_comment_input = QLineEdit(str(initial.get("teacher_comment") or ""))
        self.override_reason_input = QLineEdit(str(initial.get("override_reason") or ""))

        card_layout.addWidget(field_label(f"Final Score (0 - {initial.get('max_mark', 1)})"))
        card_layout.addWidget(self.final_score_input)
        card_layout.addWidget(field_label("Final Result"))
        card_layout.addWidget(self.final_is_correct_dropdown)
        card_layout.addWidget(field_label("Teacher Comment (optional)"))
        card_layout.addWidget(self.teacher_comment_input)
        card_layout.addWidget(field_label("Override Reason (optional)"))
        card_layout.addWidget(self.override_reason_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "final_score_awarded": self.final_score_input.text(),
            "final_is_correct": self.final_is_correct_dropdown.currentData(),
            "teacher_comment": self.teacher_comment_input.text(),
            "override_reason": self.override_reason_input.text(),
        }


def prompt_review_item(
    parent: Optional[QWidget],
    title: str,
    context: str,
    initial: dict,
) -> Optional[dict]:
    """Show a modal form for a teacher to accept/override one marking-review item.

    Returns a dict of raw field values if saved, or None if cancelled.
    Numeric parsing and validation happen in the caller.
    """
    dialog = ReviewItemDialog(parent, title, context, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class MainMarkingReviewDialog(QDialog):
    """Rounded-card modal form for a teacher to accept or override one Main
    Marking marked answer's score/feedback (Stage 11R)."""

    def __init__(self, parent: Optional[QWidget], title: str, context: str, initial: dict) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        context_label = QLabel(context)
        context_label.setObjectName("StatusLabel")
        context_label.setWordWrap(True)
        card_layout.addWidget(context_label)

        self.teacher_score_input = QLineEdit(str(initial.get("teacher_score", "")))
        self.teacher_feedback_input = QLineEdit(str(initial.get("teacher_feedback") or ""))

        card_layout.addWidget(field_label(f"Teacher Score (0 - {initial.get('max_score', 1)})"))
        card_layout.addWidget(self.teacher_score_input)
        card_layout.addWidget(field_label("Teacher Feedback (optional)"))
        card_layout.addWidget(self.teacher_feedback_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save Review")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "teacher_score": self.teacher_score_input.text(),
            "teacher_feedback": self.teacher_feedback_input.text(),
        }


def prompt_main_marking_review(
    parent: Optional[QWidget],
    title: str,
    context: str,
    initial: dict,
) -> Optional[dict]:
    """Show a modal form for a teacher to accept/override one Main Marking
    marked answer's score/feedback.

    Returns a dict of raw field values if saved, or None if cancelled.
    Numeric parsing and validation happen in the caller.
    """
    dialog = MainMarkingReviewDialog(parent, title, context, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class AnswerKeyEntryDialog(QDialog):
    """Rounded-card modal form for a teacher to confirm/edit one Subject
    Profile answer-key entry (Stage 11V) - question number, correct answer,
    max mark, and an optional comment."""

    def __init__(self, parent: Optional[QWidget], title: str, context: str, initial: dict) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        context_label = QLabel(context)
        context_label.setObjectName("StatusLabel")
        context_label.setWordWrap(True)
        card_layout.addWidget(context_label)

        self.question_no_input = QLineEdit(str(initial.get("question_no") or ""))
        self.correct_answer_input = QLineEdit(str(initial.get("correct_answer") or ""))
        self.max_mark_input = QLineEdit(str(initial.get("max_mark", 1.0)))
        self.comment_input = QLineEdit(str(initial.get("comment") or ""))

        card_layout.addWidget(field_label("Question Number"))
        card_layout.addWidget(self.question_no_input)
        card_layout.addWidget(field_label("Correct Answer"))
        card_layout.addWidget(self.correct_answer_input)
        card_layout.addWidget(field_label("Max Mark"))
        card_layout.addWidget(self.max_mark_input)
        card_layout.addWidget(field_label("Comment (optional)"))
        card_layout.addWidget(self.comment_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save Answer Key")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "question_no": self.question_no_input.text(),
            "correct_answer": self.correct_answer_input.text(),
            "max_mark": self.max_mark_input.text(),
            "comment": self.comment_input.text(),
        }


def prompt_answer_key_entry(
    parent: Optional[QWidget], title: str, context: str, initial: dict
) -> Optional[dict]:
    """Show a modal form for a teacher to confirm/edit one Subject Profile
    answer-key entry. Returns a dict of raw field values if saved, or None
    if cancelled. Numeric parsing/validation happens in the caller."""
    dialog = AnswerKeyEntryDialog(parent, title, context, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class TeacherReviewDialog(QDialog):
    """Stage 12G-1A: the per-answer teacher review/correction editor.

    Shows the ORIGINAL machine result read-only (detected answer, expected,
    automated status/score) and the raw OCR read-only, alongside EDITABLE
    teacher fields: corrected answer text (with Copy-Raw / Reset actions and
    a "differs from raw OCR" indicator), a Kertas 1 status dropdown OR a
    Kertas 2 score spin box, multi-select feedback categories, student-facing
    final feedback, and a clearly-separated private teacher comment. When
    read_only=True (a finalised result) every editor is disabled.

    `initial` keys: is_answer_box (bool), detected, expected, automated_status,
    automated_score_display, max_score (float), raw_ocr, corrected_text,
    teacher_status, teacher_score (float|None), teacher_feedback,
    private_comment, categories (list of (id, label, checked)),
    extraction_method, extraction_confidence (float|None),
    extraction_timestamp."""

    def __init__(self, parent: Optional[QWidget], title: str, initial: dict, read_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(600)
        self._is_answer_box = bool(initial.get("is_answer_box"))
        self._is_part3 = bool(initial.get("is_part3"))
        self._raw_ocr = initial.get("raw_ocr") or ""
        self._read_only = read_only
        self._max_score = float(initial.get("max_score", 20.0))
        self.part3_combo = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("SectionHeading")
        outer.addWidget(title_label)

        if read_only:
            banner = QLabel("This result is finalised - reopen it for editing to make changes.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        form = QVBoxLayout(body)
        form.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)
        self._scroll_body = body  # full-height content (for evidence capture)
        self._scroll_area = scroll

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        # --- Original automated result (read-only) ---
        form.addWidget(field_label("Original Automated Result (read-only)"))
        machine = QGridLayout()
        machine.setContentsMargins(0, 0, 0, 0)
        machine.addWidget(QLabel("Detected:"), 0, 0)
        machine.addWidget(QLabel(str(initial.get("detected") or "(none)")), 0, 1)
        machine.addWidget(QLabel("Expected:"), 1, 0)
        machine.addWidget(QLabel(str(initial.get("expected") or "(not set)")), 1, 1)
        machine.addWidget(QLabel("Auto status:"), 2, 0)
        machine.addWidget(QLabel(str(initial.get("automated_status") or "")), 2, 1)
        machine.addWidget(QLabel("Auto score:"), 3, 0)
        machine.addWidget(QLabel(str(initial.get("automated_score_display") or "")), 3, 1)
        machine_wrap = QWidget()
        machine_wrap.setLayout(machine)
        form.addWidget(machine_wrap)

        # --- Extraction provenance (read-only) ---
        form.addWidget(field_label("Extraction Provenance (read-only)"))
        prov = QGridLayout()
        prov.setContentsMargins(0, 0, 0, 0)
        method = initial.get("extraction_method")
        conf = initial.get("extraction_confidence")
        ts = initial.get("extraction_timestamp")
        conf_display = f"{float(conf) * 100:.1f}%" if conf is not None else "Unavailable"
        prov.addWidget(QLabel("Method:"), 0, 0)
        prov.addWidget(QLabel(str(method) if method else "Unavailable"), 0, 1)
        prov.addWidget(QLabel("Confidence:"), 1, 0)
        prov.addWidget(QLabel(conf_display), 1, 1)
        prov.addWidget(QLabel("Extracted at:"), 2, 0)
        prov.addWidget(QLabel(str(ts) if ts else "Unavailable"), 2, 1)
        prov_wrap = QWidget()
        prov_wrap.setLayout(prov)
        form.addWidget(prov_wrap)

        # --- Raw OCR vs corrected text ---
        form.addWidget(field_label("Raw OCR (read-only)"))
        self.raw_ocr_view = QPlainTextEdit(self._raw_ocr)
        self.raw_ocr_view.setReadOnly(True)
        self.raw_ocr_view.setMaximumHeight(110 if self._is_answer_box else 60)
        form.addWidget(self.raw_ocr_view)

        corrected_header = QHBoxLayout()
        corrected_header.addWidget(field_label("Teacher-Corrected Text"))
        self.diff_indicator = QLabel("")
        self.diff_indicator.setObjectName("StatusLabel")
        corrected_header.addWidget(self.diff_indicator)
        corrected_header.addStretch()
        self.copy_raw_button = QPushButton("Copy Raw OCR")
        self.reset_raw_button = QPushButton("Reset to Raw")
        for b in (self.copy_raw_button, self.reset_raw_button):
            b.setObjectName("RowActionButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setEnabled(not read_only)
            corrected_header.addWidget(b)
        form.addLayout(corrected_header)
        self.corrected_input = QPlainTextEdit(str(initial.get("corrected_text") or ""))
        self.corrected_input.setReadOnly(read_only)
        self.corrected_input.setMaximumHeight(140 if self._is_answer_box else 60)
        form.addWidget(self.corrected_input)
        self.copy_raw_button.clicked.connect(lambda: self.corrected_input.setPlainText(self._raw_ocr))
        self.reset_raw_button.clicked.connect(lambda: self.corrected_input.setPlainText(""))
        self.corrected_input.textChanged.connect(self._update_diff_indicator)

        # --- K1 status OR K2 score ---
        if self._is_answer_box:
            form.addWidget(field_label(f"Kertas 2 Teacher Score (0 - {self._max_score:g})"))
            # Free-text input, validated on Save so invalid marks are REJECTED
            # with a visible message rather than silently clamped.
            self.score_input = QLineEdit()
            if initial.get("teacher_score") is not None:
                self.score_input.setText(f"{float(initial['teacher_score']):g}")
            self.score_input.setPlaceholderText(f"Enter a score between 0 and {self._max_score:g}")
            self.score_input.setReadOnly(read_only)
            form.addWidget(self.score_input)
            self.score_error_label = QLabel("")
            self.score_error_label.setObjectName("ErrorLabel")
            self.score_error_label.setStyleSheet("color: #c0392b;")
            self.score_error_label.setWordWrap(True)
            form.addWidget(self.score_error_label)
            self._pending_checkbox = QCheckBox("Leave as Pending Teacher Score (do not record a mark yet)")
            self._pending_checkbox.setChecked(initial.get("teacher_score") is None)
            self._pending_checkbox.setEnabled(not read_only)
            form.addWidget(self._pending_checkbox)
            self.score_input.textChanged.connect(lambda: self.score_error_label.setText(""))
            self.status_combo = None

            # --- Part 3: which question (3/4/5) did the student answer? ---
            if self._is_part3:
                form.addWidget(field_label("Selected Part 3 Question"))
                machine_no = initial.get("part3_machine_number")
                machine_lbl = f"Question {machine_no}" if machine_no else "Needs Confirmation"
                machine_row = QLabel(f"Machine-detected: {machine_lbl}")
                machine_row.setObjectName("FieldValue")
                form.addWidget(machine_row)
                self.part3_combo = QComboBox()
                self.part3_combo.addItem("Needs Confirmation", None)
                for choice in (initial.get("part3_valid_choices") or ["3", "4", "5"]):
                    self.part3_combo.addItem(f"Question {choice}", str(choice))
                effective_no = initial.get("part3_teacher_number") or machine_no
                if effective_no is not None:
                    idx = self.part3_combo.findData(str(effective_no))
                    if idx >= 0:
                        self.part3_combo.setCurrentIndex(idx)
                self.part3_combo.setEnabled(not read_only)
                form.addWidget(self.part3_combo)
                self.part3_hint = QLabel("Confirm the Part 3 question before finalising.")
                self.part3_hint.setObjectName("StatusLabel")
                self.part3_hint.setWordWrap(True)
                form.addWidget(self.part3_hint)
        else:
            form.addWidget(field_label("Kertas 1 Final Status"))
            self.status_combo = QComboBox()
            self.status_combo.addItem("Correct", "correct")
            self.status_combo.addItem("Wrong", "wrong")
            self.status_combo.addItem("Needs Review", "needs_review")
            current = initial.get("teacher_status")
            if current:
                idx = self.status_combo.findData(current)
                if idx >= 0:
                    self.status_combo.setCurrentIndex(idx)
            self.status_combo.setEnabled(not read_only)
            form.addWidget(self.status_combo)
            self.score_input = None

        # --- Feedback categories ---
        form.addWidget(field_label("Feedback Categories"))
        self._category_boxes: List[Tuple[int, QCheckBox]] = []
        cats_grid = QGridLayout()
        cats_grid.setContentsMargins(0, 0, 0, 0)
        for i, entry in enumerate(initial.get("categories", [])):
            # Accept (id, label, checked) or (id, label, checked, active).
            cid, label, checked = entry[0], entry[1], entry[2]
            active = entry[3] if len(entry) > 3 else True
            cb = QCheckBox(label)
            cb.setChecked(bool(checked))
            # Inactive categories stay visible but cannot be toggled, so a
            # historical selection is preserved and no new inactive pick is made.
            cb.setEnabled(not read_only and bool(active))
            cats_grid.addWidget(cb, i // 2, i % 2)
            self._category_boxes.append((cid, cb))
        cats_wrap = QWidget()
        cats_wrap.setLayout(cats_grid)
        form.addWidget(cats_wrap)

        # --- Feedback + private comment ---
        form.addWidget(field_label("Final Teacher Feedback (shown to student)"))
        self.feedback_input = QPlainTextEdit(str(initial.get("teacher_feedback") or ""))
        self.feedback_input.setReadOnly(read_only)
        self.feedback_input.setMaximumHeight(70)
        form.addWidget(self.feedback_input)

        form.addWidget(field_label("Private Teacher Comment (internal - NOT shown to student)"))
        self.private_input = QPlainTextEdit(str(initial.get("private_comment") or ""))
        self.private_input.setReadOnly(read_only)
        self.private_input.setMaximumHeight(60)
        form.addWidget(self.private_input)

        # --- Buttons ---
        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_button)
        if not read_only:
            save_button = QPushButton("Save Correction")
            save_button.setObjectName("PrimaryButton")
            save_button.setCursor(Qt.CursorShape.PointingHandCursor)
            save_button.setDefault(True)
            save_button.clicked.connect(self.accept)
            buttons_row.addWidget(save_button)
        outer.addLayout(buttons_row)

        self._update_diff_indicator()
        self._initial_snapshot = self._current_snapshot()

    def _update_diff_indicator(self) -> None:
        corrected = self.corrected_input.toPlainText()
        if not corrected:
            self.diff_indicator.setText("")
        elif corrected != self._raw_ocr:
            self.diff_indicator.setText("(differs from raw OCR)")
        else:
            self.diff_indicator.setText("(identical to raw OCR)")

    # --- score validation -------------------------------------------------
    def _validate_score(self) -> Tuple[bool, Optional[float], str]:
        """Return (ok, value, error). value is None when left pending."""
        if self._pending_checkbox.isChecked():
            return True, None, ""
        raw = self.score_input.text().strip()
        if raw == "":
            return False, None, "Enter a numeric score, or tick \"Leave as Pending\"."
        try:
            value = float(raw)
        except ValueError:
            return False, None, f"\"{raw}\" is not a valid number."
        if value < 0:
            return False, None, "Score cannot be negative."
        if value > self._max_score:
            return False, None, f"Score cannot exceed the maximum of {self._max_score:g}."
        return True, value, ""

    def accept(self) -> None:  # type: ignore[override]
        if not self._read_only and self._is_answer_box:
            ok, _value, error = self._validate_score()
            if not ok:
                self.score_error_label.setText(error)
                return
        super().accept()

    # --- dirty tracking / unsaved-change protection -----------------------
    def _current_snapshot(self) -> tuple:
        base = (
            self.corrected_input.toPlainText(),
            self.feedback_input.toPlainText(),
            self.private_input.toPlainText(),
            tuple(cid for cid, cb in self._category_boxes if cb.isChecked()),
        )
        if self._is_answer_box:
            part3 = self.part3_combo.currentData() if self.part3_combo is not None else None
            return base + (self.score_input.text().strip(), self._pending_checkbox.isChecked(), part3)
        return base + (self.status_combo.currentData(),)

    def is_dirty(self) -> bool:
        if self._read_only:
            return False
        return self._current_snapshot() != self._initial_snapshot

    def _confirm_discard_unsaved(self) -> str:
        """Prompt Save / Discard / Cancel; returns "save"/"discard"/"cancel"."""
        choice = prompt_three_way_choice(
            self,
            "Unsaved Changes",
            "You have unsaved corrections for this answer. Save them, discard "
            "them, or keep editing?",
            "Save",
            "Discard",
        )
        return {"primary": "save", "secondary": "discard"}.get(choice, "cancel")

    def reject(self) -> None:  # type: ignore[override]
        if self.is_dirty():
            choice = self._confirm_discard_unsaved()
            if choice == "save":
                self.accept()
                return
            if choice == "cancel":
                return
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Route the window "X" through the same unsaved-change guard.
        event.ignore()
        self.reject()

    def values(self) -> dict:
        result = {
            "corrected_text": self.corrected_input.toPlainText(),
            "teacher_feedback": self.feedback_input.toPlainText(),
            "private_comment": self.private_input.toPlainText(),
            "category_ids": [cid for cid, cb in self._category_boxes if cb.isChecked()],
            "is_answer_box": self._is_answer_box,
        }
        if self._is_answer_box:
            _ok, value, _error = self._validate_score()
            result["leave_pending"] = self._pending_checkbox.isChecked()
            result["teacher_score"] = value if value is not None else 0.0
            result["is_part3"] = self._is_part3
            result["selected_question_number"] = (
                self.part3_combo.currentData() if self.part3_combo is not None else None
            )
        else:
            result["teacher_status"] = self.status_combo.currentData()
        return result


def prompt_teacher_review(parent, title: str, initial: dict, read_only: bool = False) -> Optional[dict]:
    """Show the per-answer teacher review editor. Returns the entered values
    dict when saved, or None if cancelled/read-only-dismissed."""
    dialog = TeacherReviewDialog(parent, title, initial, read_only=read_only)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class OverlayEditorDialog(QDialog):
    """Stage 12G-1A Phase 2B (consistency fix): edit one attempt overlay
    marker - its VISIBILITY (Visible/Hidden) and page-relative position (X/Y).
    The symbol always follows the effective status, so there is no visual-only
    symbol override. For a Kertas 1 answer the editor also offers "change the
    final status" shortcuts (Correct/Wrong/Needs Review) which the CALLER
    applies through the review service with a confirmation - after which the
    Auto symbol follows. Read-only when the attempt is finalised.

    `initial` keys: paper, answer_label, status_display, auto_symbol_display,
    is_kertas1 (bool), hidden (bool), x, y (float), original_x, original_y."""

    def __init__(self, parent: Optional[QWidget], title: str, initial: dict, read_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self._read_only = read_only
        self._is_kertas1 = bool(initial.get("is_kertas1"))
        self._orig_x = float(initial.get("original_x", initial.get("x", 0.0)) or 0.0)
        self._orig_y = float(initial.get("original_y", initial.get("y", 0.0)) or 0.0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        if read_only:
            banner = QLabel("This attempt is finalised - reopen it for editing to change overlays.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        info = QGridLayout()
        info.addWidget(QLabel("Paper:"), 0, 0)
        info.addWidget(QLabel(str(initial.get("paper") or "")), 0, 1)
        info.addWidget(QLabel("Answer:"), 1, 0)
        info.addWidget(QLabel(str(initial.get("answer_label") or "")), 1, 1)
        info.addWidget(QLabel("Effective status:"), 2, 0)
        info.addWidget(QLabel(str(initial.get("status_display") or "")), 2, 1)
        info.addWidget(QLabel("Auto symbol:"), 3, 0)
        info.addWidget(QLabel(str(initial.get("auto_symbol_display") or "")), 3, 1)
        info_wrap = QWidget()
        info_wrap.setLayout(info)
        outer.addWidget(info_wrap)

        outer.addWidget(field_label("Symbol"))
        self.symbol_combo = QComboBox()
        # The symbol always follows the final status. For Kertas 1 the extra
        # options are a shortcut to CHANGE that status (confirmed by the caller);
        # for Kertas 2 only Auto is offered (change the score in Teacher Review).
        self.symbol_combo.addItem("Auto (follows Final Status)", "auto")
        if self._is_kertas1:
            self.symbol_combo.addItem("Change status to Correct (Tick)", "tick")
            self.symbol_combo.addItem("Change status to Wrong (X)", "cross")
            self.symbol_combo.addItem("Change status to Needs Review (Question Mark)", "question_mark")
        self.symbol_combo.setCurrentIndex(0)
        self.symbol_combo.setEnabled(not read_only)
        outer.addWidget(self.symbol_combo)
        if self._is_kertas1:
            hint = QLabel("Choosing a status option updates the teacher's final marking (score + summary).")
        else:
            hint = QLabel("A Kertas 2 marker follows its teacher score - change the score in Teacher Review.")
        hint.setObjectName("StatusLabel")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        outer.addWidget(field_label("Visibility"))
        self.visibility_combo = QComboBox()
        self.visibility_combo.addItem("Visible", False)
        self.visibility_combo.addItem("Hidden", True)
        self.visibility_combo.setCurrentIndex(1 if initial.get("hidden") else 0)
        self.visibility_combo.setEnabled(not read_only)
        outer.addWidget(self.visibility_combo)

        pos_row = QHBoxLayout()
        pos_row.addWidget(field_label("X (0-1)"))
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setDecimals(3)
        self.x_spin.setRange(0.0, 1.0)
        self.x_spin.setSingleStep(0.005)
        self.x_spin.setValue(float(initial.get("x", 0.0) or 0.0))
        self.x_spin.setEnabled(not read_only)
        pos_row.addWidget(self.x_spin)
        pos_row.addWidget(field_label("Y (0-1)"))
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setDecimals(3)
        self.y_spin.setRange(0.0, 1.0)
        self.y_spin.setSingleStep(0.005)
        self.y_spin.setValue(float(initial.get("y", 0.0) or 0.0))
        self.y_spin.setEnabled(not read_only)
        pos_row.addWidget(self.y_spin)
        outer.addLayout(pos_row)

        restore_row = QHBoxLayout()
        self.restore_position_button = QPushButton("Restore Original Position")
        self.restore_position_button.setObjectName("RowActionButton")
        self.restore_position_button.setEnabled(not read_only)
        self.restore_position_button.clicked.connect(self._restore_position)
        restore_row.addWidget(self.restore_position_button)
        restore_row.addStretch()
        outer.addLayout(restore_row)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_button)
        if not read_only:
            save_button = QPushButton("Save Overlay Changes")
            save_button.setObjectName("PrimaryButton")
            save_button.setDefault(True)
            save_button.clicked.connect(self.accept)
            buttons_row.addWidget(save_button)
        outer.addLayout(buttons_row)

        self._initial_snapshot = self._snapshot()

    def _restore_position(self) -> None:
        self.x_spin.setValue(self._orig_x)
        self.y_spin.setValue(self._orig_y)

    def _snapshot(self) -> tuple:
        return (self.symbol_combo.currentData(), self.visibility_combo.currentData(),
                round(self.x_spin.value(), 3), round(self.y_spin.value(), 3))

    def is_dirty(self) -> bool:
        if self._read_only:
            return False
        return self._snapshot() != self._initial_snapshot

    def _confirm_discard_unsaved(self) -> str:
        choice = prompt_three_way_choice(
            self, "Unsaved Overlay Changes",
            "You have unsaved overlay changes. Save them, discard them, or keep editing?",
            "Save", "Discard")
        return {"primary": "save", "secondary": "discard"}.get(choice, "cancel")

    def reject(self) -> None:  # type: ignore[override]
        if self.is_dirty():
            choice = self._confirm_discard_unsaved()
            if choice == "save":
                self.accept()
                return
            if choice == "cancel":
                return
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.reject()

    def values(self) -> dict:
        symbol = self.symbol_combo.currentData()
        return {
            # None = Auto (no status change); else 'tick'/'cross'/'question_mark'
            # requests a Kertas 1 final-status change (caller confirms + applies).
            "status_symbol": None if symbol == "auto" else symbol,
            "hidden": bool(self.visibility_combo.currentData()),
            "x": round(self.x_spin.value(), 3),
            "y": round(self.y_spin.value(), 3),
        }


def prompt_overlay_editor(parent, title: str, initial: dict, read_only: bool = False) -> Optional[dict]:
    """Show the overlay editor. Returns the chosen state dict on Save, else None."""
    dialog = OverlayEditorDialog(parent, title, initial, read_only=read_only)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


class RegionOverrideDialog(QDialog):
    """Stage 12G-1A Phase 2C: edit one attempt-specific region override -
    numeric page-relative geometry (X/Y/W/H) with a LIVE effective-crop
    preview beside the original-crop preview, plus Restore Original Region.
    The shared Subject Profile region is never touched here. Draw/move/resize
    is done with the validated numeric controls + live preview (reliable across
    preview scaling); the caller renders crops and answers `preview_requested`.
    Read-only when the attempt is finalised.

    `initial` keys: paper, answer_label, page_number, region_type, x, y, width,
    height, has_override (bool), stale (bool), correction_reason,
    original_crop_path, effective_crop_path (paths or None)."""

    preview_requested = Signal(float, float, float, float)  # x, y, width, height

    def __init__(self, parent: Optional[QWidget], title: str, initial: dict, read_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(600)
        self._read_only = read_only
        self.action = "cancel"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        if read_only:
            banner = QLabel("This attempt is finalised - reopen it for editing to change region overrides.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)
        if initial.get("stale"):
            stale = QLabel("This target's extraction changed - reconfirm its review before finalising.")
            stale.setObjectName("StatusLabel")
            stale.setStyleSheet("color: #c0392b;")
            stale.setWordWrap(True)
            outer.addWidget(stale)

        info = QGridLayout()
        info.addWidget(QLabel("Paper:"), 0, 0)
        info.addWidget(QLabel(str(initial.get("paper") or "")), 0, 1)
        info.addWidget(QLabel("Answer:"), 1, 0)
        info.addWidget(QLabel(str(initial.get("answer_label") or "")), 1, 1)
        info.addWidget(QLabel("Page:"), 2, 0)
        info.addWidget(QLabel(str(initial.get("page_number") or "")), 2, 1)
        info_wrap = QWidget()
        info_wrap.setLayout(info)
        outer.addWidget(info_wrap)

        # Original vs effective crop previews.
        crops = QHBoxLayout()
        orig_col = QVBoxLayout()
        orig_lbl = QLabel("Original region crop")
        orig_lbl.setObjectName("FieldLabel")
        orig_col.addWidget(orig_lbl)
        self.original_crop_label = QLabel("(no preview)")
        self.original_crop_label.setMinimumSize(240, 120)
        self.original_crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_crop_label.setStyleSheet("border: 1px solid #ccc;")
        orig_col.addWidget(self.original_crop_label)
        crops.addLayout(orig_col)
        eff_col = QVBoxLayout()
        eff_lbl = QLabel("Effective (override) crop")
        eff_lbl.setObjectName("FieldLabel")
        eff_col.addWidget(eff_lbl)
        self.effective_crop_label = QLabel("(no preview)")
        self.effective_crop_label.setMinimumSize(240, 120)
        self.effective_crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.effective_crop_label.setStyleSheet("border: 1px solid #ccc;")
        eff_col.addWidget(self.effective_crop_label)
        crops.addLayout(eff_col)
        outer.addLayout(crops)
        self.set_original_crop(initial.get("original_crop_path"))
        self.set_effective_crop(initial.get("effective_crop_path"))

        # Numeric geometry controls.
        def _spin(value):
            s = QDoubleSpinBox()
            s.setDecimals(3)
            s.setRange(0.0, 1.0)
            s.setSingleStep(0.005)
            s.setValue(float(value or 0.0))
            s.setEnabled(not read_only)
            return s

        geo = QGridLayout()
        geo.addWidget(QLabel("X"), 0, 0)
        self.x_spin = _spin(initial.get("x"))
        geo.addWidget(self.x_spin, 0, 1)
        geo.addWidget(QLabel("Y"), 0, 2)
        self.y_spin = _spin(initial.get("y"))
        geo.addWidget(self.y_spin, 0, 3)
        geo.addWidget(QLabel("Width"), 1, 0)
        self.w_spin = _spin(initial.get("width"))
        geo.addWidget(self.w_spin, 1, 1)
        geo.addWidget(QLabel("Height"), 1, 2)
        self.h_spin = _spin(initial.get("height"))
        geo.addWidget(self.h_spin, 1, 3)
        geo_wrap = QWidget()
        geo_wrap.setLayout(geo)
        outer.addWidget(geo_wrap)

        self.geometry_error_label = QLabel("")
        self.geometry_error_label.setStyleSheet("color: #c0392b;")
        self.geometry_error_label.setWordWrap(True)
        outer.addWidget(self.geometry_error_label)

        outer.addWidget(QLabel("Correction reason (optional)"))
        self.reason_input = QLineEdit(str(initial.get("correction_reason") or ""))
        self.reason_input.setEnabled(not read_only)
        outer.addWidget(self.reason_input)

        buttons_row = QHBoxLayout()
        self.preview_button = QPushButton("Update Effective Preview")
        self.preview_button.setObjectName("RowActionButton")
        self.preview_button.setEnabled(not read_only)
        self.preview_button.clicked.connect(self._emit_preview)
        buttons_row.addWidget(self.preview_button)
        buttons_row.addStretch()
        if initial.get("has_override") and not read_only:
            self.restore_button = QPushButton("Restore Original Region")
            self.restore_button.setObjectName("RowActionButton")
            self.restore_button.clicked.connect(self._restore)
            buttons_row.addWidget(self.restore_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_button)
        if not read_only:
            save_button = QPushButton("Save Region Override")
            save_button.setObjectName("PrimaryButton")
            save_button.setDefault(True)
            save_button.clicked.connect(self._save)
            buttons_row.addWidget(save_button)
        outer.addLayout(buttons_row)

    def _pixmap_into(self, label, path) -> None:
        if path and Path(path).is_file():
            pix = QPixmap(str(path))
            if not pix.isNull():
                label.setPixmap(pix.scaled(300, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
                return
        label.setText("(no preview)")

    def set_original_crop(self, path) -> None:
        self._pixmap_into(self.original_crop_label, path)

    def set_effective_crop(self, path) -> None:
        self._pixmap_into(self.effective_crop_label, path)

    def _current_geometry(self):
        return (round(self.x_spin.value(), 3), round(self.y_spin.value(), 3),
                round(self.w_spin.value(), 3), round(self.h_spin.value(), 3))

    def _emit_preview(self) -> None:
        x, y, w, h = self._current_geometry()
        self.geometry_error_label.setText("")
        self.preview_requested.emit(x, y, w, h)

    def _validate(self) -> bool:
        x, y, w, h = self._current_geometry()
        if w <= 0 or h <= 0:
            self.geometry_error_label.setText("Width and height must be greater than zero.")
            return False
        if x < 0 or y < 0 or x + w > 1.0 or y + h > 1.0:
            self.geometry_error_label.setText("Region must lie inside the page (x+width and y+height must be <= 1.0).")
            return False
        return True

    def _save(self) -> None:
        if not self._validate():
            return
        self.action = "save"
        self.accept()

    def _restore(self) -> None:
        self.action = "restore"
        self.accept()

    def values(self) -> dict:
        x, y, w, h = self._current_geometry()
        return {"x": x, "y": y, "width": w, "height": h,
                "correction_reason": self.reason_input.text().strip() or None, "action": self.action}


class Kertas2ReviewItemDialog(QDialog):
    """Rounded-card modal form for a teacher to accept or edit one Kertas 2
    AI-feedback-review item's final score/feedback/comment."""

    def __init__(self, parent: Optional[QWidget], title: str, context: str, initial: dict) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(460)

        card = QFrame(self)
        card.setObjectName("FeedbackCard")
        apply_card_shadow(card, blur_radius=36, y_offset=10, alpha=45)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("LoginCardTitle")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        context_label = QLabel(context)
        context_label.setObjectName("StatusLabel")
        context_label.setWordWrap(True)
        card_layout.addWidget(context_label)

        self.final_score_input = QLineEdit(str(initial.get("final_score", "")))
        self.final_feedback_input = QLineEdit(str(initial.get("final_feedback") or ""))
        self.teacher_comment_input = QLineEdit(str(initial.get("teacher_comment") or ""))

        card_layout.addWidget(field_label(f"Final Score (0 - {initial.get('max_mark', 1)})"))
        card_layout.addWidget(self.final_score_input)
        card_layout.addWidget(field_label("Final Feedback"))
        card_layout.addWidget(self.final_feedback_input)
        card_layout.addWidget(field_label("Teacher Comment (optional)"))
        card_layout.addWidget(self.teacher_comment_input)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)

        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(card)

    def values(self) -> dict:
        return {
            "final_score": self.final_score_input.text(),
            "final_feedback": self.final_feedback_input.text(),
            "teacher_comment": self.teacher_comment_input.text(),
        }


def prompt_kertas2_review_item(
    parent: Optional[QWidget],
    title: str,
    context: str,
    initial: dict,
) -> Optional[dict]:
    """Show a modal form for a teacher to accept/edit one Kertas 2 AI
    feedback review item.

    Returns a dict of raw field values if saved, or None if cancelled.
    Numeric parsing and validation happen in the caller.
    """
    dialog = Kertas2ReviewItemDialog(parent, title, context, initial)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.values()
    return None


# --- Stage 12G-1B: Separate Answer Paper -----------------------------------


class SeparateMappingDialog(QDialog):
    """Stage 12G-1B: create or edit one Separate Answer Paper mapping - the
    page it sits on, what kind of answer region it is, its page-relative
    geometry, its reading order, and whether it continues an earlier region.

    Geometry is entered with validated numeric controls and checked with a
    live crop preview so the teacher can see exactly what will be OCR'd
    before saving. Nothing is written until Save Mapping is pressed.

    `initial` keys: target_label, display_label, paper, pages (list of
    (sap_page_id, label)), sap_page_id, mapping_type, x, y, width, height,
    reading_order, is_continuation, crop_path.
    """

    # sap_page_id, x, y, width, height
    preview_requested = Signal(int, float, float, float, float)

    MAPPING_TYPE_CHOICES = [
        ("Kertas 1 - numbered answer block", "k1_answer_block"),
        ("Kertas 1 - single answer", "k1_individual_answer"),
        ("Kertas 2 - Part 1", "k2_part1"),
        ("Kertas 2 - Part 2", "k2_part2"),
        ("Kertas 2 - Part 3", "k2_part3"),
        ("Part 3 selected question number", "part3_selected_question"),
        ("Continuation of an earlier region", "continuation"),
    ]

    def __init__(self, parent: Optional[QWidget], title: str, initial: dict,
                 read_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(620)
        self._read_only = read_only
        self._dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        subtitle = QLabel(
            f"{initial.get('paper') or ''} - {initial.get('display_label') or ''}. "
            "Geometry is relative to the page (0.0-1.0). Use Update Crop Preview to "
            "confirm the rectangle before saving.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("StatusLabel")
        outer.addWidget(subtitle)

        if read_only:
            banner = QLabel("This attempt is finalised - reopen it for editing to change mappings.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        form = QGridLayout()
        form.addWidget(QLabel("Page"), 0, 0)
        self.page_combo = QComboBox()
        for page_id, label in (initial.get("pages") or []):
            self.page_combo.addItem(str(label), page_id)
        current_page = initial.get("sap_page_id")
        if current_page is not None:
            index = self.page_combo.findData(current_page)
            if index >= 0:
                self.page_combo.setCurrentIndex(index)
        self.page_combo.setEnabled(not read_only)
        form.addWidget(self.page_combo, 0, 1)

        form.addWidget(QLabel("Mapping type"), 0, 2)
        self.type_combo = QComboBox()
        for label, value in self.MAPPING_TYPE_CHOICES:
            self.type_combo.addItem(label, value)
        current_type = initial.get("mapping_type")
        # An existing mapping keeps its type; a new one starts on the type the
        # caller suggests for this target rather than the first in the list.
        preselect = current_type or initial.get("suggested_mapping_type")
        if preselect:
            index = self.type_combo.findData(preselect)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
        # Type is structural: changing it on an existing mapping would change
        # what the answer means, so it is fixed once the mapping exists.
        self.type_combo.setEnabled(not read_only and not current_type)
        form.addWidget(self.type_combo, 0, 3)
        form_wrap = QWidget()
        form_wrap.setLayout(form)
        outer.addWidget(form_wrap)

        crop_heading = QLabel("Crop preview")
        crop_heading.setObjectName("FieldLabel")
        outer.addWidget(crop_heading)
        self.crop_label = QLabel("(no preview)")
        self.crop_label.setMinimumSize(420, 140)
        self.crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_label.setStyleSheet("border: 1px solid #ccc;")
        outer.addWidget(self.crop_label)
        self.set_crop(initial.get("crop_path"))

        def _spin(value):
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.005)
            spin.setValue(float(value or 0.0))
            spin.setEnabled(not read_only)
            spin.valueChanged.connect(self._mark_dirty)
            return spin

        geo = QGridLayout()
        geo.addWidget(QLabel("X"), 0, 0)
        self.x_spin = _spin(initial.get("x"))
        geo.addWidget(self.x_spin, 0, 1)
        geo.addWidget(QLabel("Y"), 0, 2)
        self.y_spin = _spin(initial.get("y"))
        geo.addWidget(self.y_spin, 0, 3)
        geo.addWidget(QLabel("Width"), 1, 0)
        self.w_spin = _spin(initial.get("width"))
        geo.addWidget(self.w_spin, 1, 1)
        geo.addWidget(QLabel("Height"), 1, 2)
        self.h_spin = _spin(initial.get("height"))
        geo.addWidget(self.h_spin, 1, 3)

        geo.addWidget(QLabel("Reading order"), 2, 0)
        self.order_spin = QDoubleSpinBox()
        self.order_spin.setDecimals(0)
        self.order_spin.setRange(1, 999)
        self.order_spin.setValue(float(initial.get("reading_order") or 1))
        self.order_spin.setEnabled(not read_only)
        self.order_spin.valueChanged.connect(self._mark_dirty)
        geo.addWidget(self.order_spin, 2, 1)
        self.continuation_check = QCheckBox("This region continues the previous one")
        self.continuation_check.setChecked(bool(initial.get("is_continuation")))
        self.continuation_check.setEnabled(not read_only and not current_type)
        self.continuation_check.toggled.connect(self._mark_dirty)
        geo.addWidget(self.continuation_check, 2, 2, 1, 2)
        geo_wrap = QWidget()
        geo_wrap.setLayout(geo)
        outer.addWidget(geo_wrap)

        self.geometry_error_label = QLabel("")
        self.geometry_error_label.setStyleSheet("color: #c0392b;")
        self.geometry_error_label.setWordWrap(True)
        outer.addWidget(self.geometry_error_label)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Update Crop Preview")
        self.preview_button.setObjectName("RowActionButton")
        self.preview_button.clicked.connect(self._emit_preview)
        buttons.addWidget(self.preview_button)
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(cancel_button)
        if not read_only:
            save_button = QPushButton("Save Mapping")
            save_button.setObjectName("PrimaryButton")
            save_button.setDefault(True)
            save_button.clicked.connect(self._save)
            buttons.addWidget(save_button)
        outer.addLayout(buttons)

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True

    def set_crop(self, path) -> None:
        if path and Path(path).is_file():
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.crop_label.setPixmap(pix.scaled(
                    460, 150, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                self.geometry_error_label.setText("")
                return
        self.crop_label.setText("(no preview)")

    def set_geometry_error(self, message: str) -> None:
        self.geometry_error_label.setText(message)

    def _geometry(self):
        return (round(self.x_spin.value(), 3), round(self.y_spin.value(), 3),
                round(self.w_spin.value(), 3), round(self.h_spin.value(), 3))

    def _emit_preview(self) -> None:
        page_id = self.page_combo.currentData()
        if page_id is None:
            self.geometry_error_label.setText("Select a page first.")
            return
        if not self._validate():
            return
        x, y, w, h = self._geometry()
        self.preview_requested.emit(int(page_id), x, y, w, h)

    def _validate(self) -> bool:
        x, y, w, h = self._geometry()
        if w <= 0 or h <= 0:
            self.geometry_error_label.setText("Width and height must be greater than zero.")
            return False
        if x + w > 1.0 or y + h > 1.0:
            self.geometry_error_label.setText(
                "The region must lie inside the page (x+width and y+height must be <= 1.0).")
            return False
        self.geometry_error_label.setText("")
        return True

    def _cancel(self) -> None:
        if self._dirty and not self._read_only:
            if not prompt_confirm(self, "Discard Mapping Changes",
                                  "Discard the unsaved changes to this mapping?",
                                  confirm_text="Discard"):
                return
        self.reject()

    def _save(self) -> None:
        if self.page_combo.currentData() is None:
            self.geometry_error_label.setText("Select a page first.")
            return
        if not self.type_combo.currentData():
            self.geometry_error_label.setText("Select a mapping type.")
            return
        if not self._validate():
            return
        self.accept()

    def values(self) -> dict:
        x, y, w, h = self._geometry()
        return {
            "sap_page_id": int(self.page_combo.currentData()),
            "mapping_type": self.type_combo.currentData(),
            "x": x, "y": y, "width": w, "height": h,
            "reading_order": int(self.order_spin.value()),
            "is_continuation": self.continuation_check.isChecked(),
        }


class SeparateParserReviewDialog(QDialog):
    """Stage 12G-1B: review the Kertas 1 numbered-answer block parser output.

    Every parsed row is shown with its question number, the parser's answer,
    the exact source text it came from, its confidence, and any warning or
    conflict. The teacher then acts on ONE row at a time: confirm it, replace
    the answer, mark the question explicitly blank, or leave it unresolved.
    The parser output itself is never overwritten - the teacher's answer is
    stored beside it - and a conflict is never auto-resolved.

    `rows` items: parsed_id, question_no, parsed_answer, warning, has_conflict,
    teacher_answer, state, source_text, confidence.
    """

    COLUMNS = ["Q", "Parser answer", "Teacher answer", "State", "Confidence",
               "Source text", "Warning / conflict"]

    def __init__(self, parent: Optional[QWidget], title: str, rows: List[dict],
                 read_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(880, 520)
        self._rows = rows
        self._read_only = read_only
        self._decision: dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        conflicts = sum(1 for r in rows if r.get("has_conflict"))
        unconfirmed = sum(1 for r in rows if (r.get("state") or "unconfirmed") == "unconfirmed")
        summary = QLabel(
            f"{len(rows)} parsed row(s) | {unconfirmed} awaiting confirmation | "
            f"{conflicts} conflict(s). A conflict is never resolved automatically - "
            "select the row and record your decision.")
        summary.setWordWrap(True)
        summary.setObjectName("StatusLabel")
        if conflicts:
            summary.setStyleSheet("color: #c0392b;")
        outer.addWidget(summary)

        if read_only:
            banner = QLabel("This attempt is finalised - parser answers are read-only.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        self.table = QTableWidget(len(rows), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row_index, row in enumerate(rows):
            cells = [
                str(row.get("question_no") or "-"),
                str(row.get("parsed_answer") or "(none)"),
                str(row.get("teacher_answer") if row.get("teacher_answer") is not None else "-"),
                str(row.get("state") or "unconfirmed"),
                f"{float(row.get('confidence') or 0.0):.2f}",
                (str(row.get("source_text") or "")[:60]),
                str(row.get("warning") or ("CONFLICT" if row.get("has_conflict") else "-")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row.get("has_conflict"):
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(row_index, col, item)
        self.table.currentCellChanged.connect(lambda *_: self._load_selected())
        outer.addWidget(self.table)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Teacher answer"))
        self.answer_input = QLineEdit()
        self.answer_input.setEnabled(not read_only)
        edit_row.addWidget(self.answer_input)
        edit_row.addWidget(QLabel("Decision"))
        self.state_combo = QComboBox()
        for label, value in [("Confirm this answer", "confirmed"),
                             ("Explicitly blank", "blank"),
                             ("Leave unresolved", "unresolved")]:
            self.state_combo.addItem(label, value)
        self.state_combo.setEnabled(not read_only)
        edit_row.addWidget(self.state_combo)
        outer.addLayout(edit_row)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        if not read_only:
            apply_next = QPushButton("Save and Keep Reviewing")
            apply_next.setObjectName("RowActionButton")
            apply_next.clicked.connect(lambda: self._save(keep_open=True))
            buttons.addWidget(apply_next)
            save_button = QPushButton("Save Decision")
            save_button.setObjectName("PrimaryButton")
            save_button.setDefault(True)
            save_button.clicked.connect(lambda: self._save(keep_open=False))
            buttons.addWidget(save_button)
        outer.addLayout(buttons)

        if rows:
            self.table.selectRow(0)
            self._load_selected()

    def _selected_row(self) -> Optional[dict]:
        index = self.table.currentRow()
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def _load_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        existing = row.get("teacher_answer")
        self.answer_input.setText(
            str(existing) if existing is not None else str(row.get("parsed_answer") or ""))
        state = row.get("state") or "unconfirmed"
        index = self.state_combo.findData(state)
        self.state_combo.setCurrentIndex(index if index >= 0 else 0)

    def _save(self, keep_open: bool) -> None:
        row = self._selected_row()
        if row is None:
            self.error_label.setText("Select a parsed row first.")
            return
        state = self.state_combo.currentData()
        answer = self.answer_input.text().strip()
        if state == "confirmed" and not answer:
            self.error_label.setText(
                "A confirmed answer cannot be empty. Use 'Explicitly blank' if the student left it blank.")
            return
        self._decision = {
            "parsed_id": row.get("parsed_id"),
            "teacher_answer": (answer or None) if state != "blank" else None,
            "state": state,
            "keep_open": keep_open,
        }
        self.accept()

    def values(self) -> dict:
        return dict(self._decision)


class RegionProposalReviewDialog(QDialog):
    """Stage 12G-4: review Core AI 2 region proposals one at a time.

    Each proposal shows its class, confidence, model version, geometry and any
    model rationale (never invented). The teacher acts on the SELECTED proposal:
    Accept (optionally assigning a logical target), Reject, Edit geometry, or
    Defer. A proposal is never an automatic region/mapping. Returns one decision
    dict per Save; the caller loops until Close.

    `proposals` items: proposal_id, proposed_class, confidence, model_version,
    rationale, status, geometry (x,y,w,h), source (str). `targets` is an
    optional list of (label, value) for the Accept target selector (Separate
    Answer Paper); empty for Subject Profile.
    """

    COLUMNS = ["Class", "Confidence", "Model", "Status", "Geometry (x,y,w,h)", "Rationale"]

    def __init__(self, parent, title, proposals, targets=None, read_only=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(820, 520)
        self._proposals = proposals
        self._targets = targets or []
        self._read_only = read_only
        self._decision = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        pending = sum(1 for p in proposals if (p.get("status") or "proposed") in ("proposed", "edited"))
        summary = QLabel(
            f"{len(proposals)} proposal(s) | {pending} awaiting a decision. A proposal is only a "
            "suggestion - nothing is applied until you Accept it. Rejected proposals are kept as review "
            "evidence.")
        summary.setObjectName("StatusLabel")
        summary.setWordWrap(True)
        outer.addWidget(summary)

        if read_only:
            banner = QLabel("This attempt is finalised - proposals are read-only.")
            banner.setObjectName("StatusLabel")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        self.table = QTableWidget(len(proposals), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for r, p in enumerate(proposals):
            g = p.get("geometry") or (None, None, None, None)
            geom = ", ".join(f"{v:.3f}" if isinstance(v, (int, float)) else "-" for v in g)
            cells = [str(p.get("proposed_class") or "-"),
                     f"{float(p.get('confidence') or 0):.2f}", str(p.get("model_version") or "-"),
                     str(p.get("status") or "proposed"), geom, str(p.get("rationale") or "(none)")]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.currentCellChanged.connect(lambda *a: self._load_selected())
        outer.addWidget(self.table)

        row = QHBoxLayout()
        row.addWidget(QLabel("Decision"))
        self.action_combo = QComboBox()
        for label, value in [("Accept", "accept"), ("Reject", "reject"),
                             ("Edit geometry", "edit"), ("Defer", "defer")]:
            self.action_combo.addItem(label, value)
        self.action_combo.setEnabled(not read_only)
        self.action_combo.currentIndexChanged.connect(self._sync_action_widgets)
        row.addWidget(self.action_combo)

        self.target_combo = QComboBox()
        self.target_combo.addItem("(assign target...)", None)
        for label, value in self._targets:
            self.target_combo.addItem(label, value)
        self.target_combo.setEnabled(not read_only and bool(self._targets))
        row.addWidget(QLabel("Target"))
        row.addWidget(self.target_combo)
        outer.addLayout(row)

        geo = QHBoxLayout()
        self._spins = {}
        for key in ("x", "y", "w", "h"):
            geo.addWidget(QLabel(key.upper()))
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.005)
            spin.setEnabled(not read_only)
            self._spins[key] = spin
            geo.addWidget(spin)
        outer.addLayout(geo)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        if not read_only:
            save_next = QPushButton("Apply and Keep Reviewing")
            save_next.setObjectName("RowActionButton")
            save_next.clicked.connect(lambda: self._save(keep_open=True))
            buttons.addWidget(save_next)
            save = QPushButton("Apply Decision")
            save.setObjectName("PrimaryButton")
            save.setDefault(True)
            save.clicked.connect(lambda: self._save(keep_open=False))
            buttons.addWidget(save)
        outer.addLayout(buttons)

        if proposals:
            self.table.selectRow(0)
            self._load_selected()
        self._sync_action_widgets()

    def _selected(self):
        i = self.table.currentRow()
        return self._proposals[i] if 0 <= i < len(self._proposals) else None

    def _load_selected(self):
        p = self._selected()
        if p is None:
            return
        g = p.get("geometry") or (0.1, 0.1, 0.2, 0.1)
        for key, value in zip(("x", "y", "w", "h"), g):
            self._spins[key].setValue(float(value) if isinstance(value, (int, float)) else 0.0)

    def _sync_action_widgets(self, *args):
        action = self.action_combo.currentData()
        self.target_combo.setEnabled(not self._read_only and action == "accept" and bool(self._targets))
        for spin in self._spins.values():
            spin.setEnabled(not self._read_only and action == "edit")

    def _save(self, keep_open):
        p = self._selected()
        if p is None:
            self.error_label.setText("Select a proposal first.")
            return
        action = self.action_combo.currentData()
        decision = {"proposal_id": p.get("proposal_id"), "action": action, "keep_open": keep_open}
        if action == "accept" and self._targets:
            target = self.target_combo.currentData()
            if target is None:
                self.error_label.setText("Assign a logical target before accepting.")
                return
            decision["target_label"] = target
        if action == "edit":
            x, y, w, h = (self._spins[k].value() for k in ("x", "y", "w", "h"))
            if w <= 0 or h <= 0 or x + w > 1.0001 or y + h > 1.0001:
                self.error_label.setText("Geometry must lie inside the page (0-1).")
                return
            decision["geometry"] = (round(x, 3), round(y, 3), round(w, 3), round(h, 3))
        self._decision = decision
        self.accept()

    def values(self):
        return dict(self._decision)
