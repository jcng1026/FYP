"""Admin dashboard: overview, teacher account management, and class
administration for the Admin role.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.db import get_connection
from app.models.class_model import ClassWithTeacher
from app.models.class_student_model import AdminStudentRow, get_classes_for_student
from app.models.class_transfer_request_model import TransferRequestWithDetails
from app.models.student_transfer_request_model import StudentTransferRequestWithDetails
from app.models.user_model import User
from app.services.admin_student_service import (
    UNASSIGNED_FILTER,
    admin_change_student_class,
    admin_create_student,
    get_student_for_admin,
    list_all_students,
    set_student_active_status,
    update_student_details,
)
from app.services.admin_teacher_service import (
    get_teacher_for_admin,
    set_teacher_active_status,
    update_teacher_details,
)
from app.services.class_service import (
    count_all_classes,
    count_assigned_teachers,
    count_unassigned_classes,
    create_class_for_teacher,
    delete_class,
    list_all_classes_with_teacher_info,
    list_teacher_classes,
    update_class_name,
    update_class_teacher,
)
from app.services.class_transfer_request_service import (
    approve_transfer_request,
    count_pending_requests,
    list_all_pending_requests,
    reject_transfer_request,
)
from app.services.student_service import (
    STUDENT_PASSWORD_NOT_AVAILABLE_MESSAGE,
    get_student_password_display,
    reset_student_password,
)
from app.services.student_transfer_request_service import (
    approve_student_transfer_request,
    list_all_decided_student_transfer_requests,
    list_all_pending_student_transfer_requests,
    reject_student_transfer_request,
)
from app.services.user_service import (
    TEACHER_PASSWORD_NOT_AVAILABLE_MESSAGE,
    create_teacher,
    get_teacher_password_display,
    list_teachers,
    reset_teacher_password,
)
from app.ui.ai_models_admin_page import AIModelsAdminPageMixin
from app.ui.components import (
    AppShell,
    StatCard,
    apply_card_shadow,
    apply_fixed_16_9_window,
    attach_table_filter,
    create_page,
    paint_status_item,
)
from app.ui.dialogs import (
    CANCELLED,
    prompt_confirm,
    prompt_input,
    prompt_select,
    show_error,
    show_password_reveal,
    show_success,
)
from app.utils.datetime_utils import format_timestamp

TEACHER_TABLE_COLUMNS = ["teacher_code", "username", "full_name", "role", "status", "created_at", "actions"]

TEACHER_TABLE_HEADERS = ["Teacher Code", "Username", "Full Name", "Role", "Status", "Created At", "Actions"]

CLASS_TABLE_COLUMNS = [
    "class_id",
    "class_name",
    "subject",
    "teacher_in_charge",
    "teacher_username",
    "created_at",
    "actions",
]

CLASS_TABLE_HEADERS = [
    "Class ID",
    "Class Name",
    "Subject",
    "Teacher In Charge",
    "Teacher Username",
    "Created At",
    "Actions",
]

REQUEST_TABLE_COLUMNS = [
    "request_id",
    "class_name",
    "current_teacher",
    "requesting_teacher",
    "request_reason",
    "created_at",
    "actions",
]

REQUEST_TABLE_HEADERS = [
    "Request ID",
    "Class Name",
    "Current Teacher",
    "Requesting Teacher",
    "Reason",
    "Created At",
    "Actions",
]

ADMIN_STUDENT_TABLE_COLUMNS = [
    "student_code",
    "username",
    "full_name",
    "class_names",
    "teacher_in_charge",
    "status",
    "created_at",
    "actions",
]

ADMIN_STUDENT_TABLE_HEADERS = [
    "Student Code",
    "Username",
    "Full Name",
    "Class",
    "Teacher In Charge",
    "Status",
    "Created At",
    "Actions",
]

STUDENT_TRANSFER_REQUEST_TABLE_COLUMNS = [
    "request_id",
    "student_code",
    "student_name",
    "source_class",
    "current_teacher",
    "target_class",
    "requesting_teacher",
    "created_at",
    "actions",
]

STUDENT_TRANSFER_REQUEST_TABLE_HEADERS = [
    "Request ID",
    "Student Code",
    "Student Name",
    "Source Class",
    "Current Teacher",
    "Target Class",
    "Requesting Teacher",
    "Created At",
    "Actions",
]

STUDENT_TRANSFER_HISTORY_TABLE_COLUMNS = [
    "request_id",
    "student_code",
    "student_name",
    "source_class",
    "target_class",
    "requesting_teacher",
    "decided_by",
    "status",
    "rejection_reason",
    "decided_at",
]

STUDENT_TRANSFER_HISTORY_TABLE_HEADERS = [
    "Request ID",
    "Student Code",
    "Student Name",
    "Source Class",
    "Target Class",
    "Requesting Teacher",
    "Decided By",
    "Status",
    "Rejection Reason",
    "Decided At",
]


class DeveloperDashboard(AIModelsAdminPageMixin, QWidget):
    def __init__(self, user: Optional[User] = None) -> None:
        super().__init__()
        self.setWindowTitle("MarkAssist — Admin")
        apply_fixed_16_9_window(self)

        self._user = user
        self._current_admin_student_id: Optional[int] = None
        self._current_admin_teacher_id: Optional[int] = None

        self.shell = AppShell(
            brand_text="MarkAssist",
            nav_items=["Dashboard", "Teachers", "Classes", "Students", "AI Models"],
            group_headings={"AI Models": "AI SYSTEM"},
            header_title="Admin Dashboard",
            header_subtitle="Overview of accounts and classes across the system.",
            user_full_name=user.full_name if user else "System Developer",
            user_role_label="Admin",
            on_logout=self.handle_logout,
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)

        self.shell.add_page("Dashboard", self._build_dashboard_page())
        self.shell.add_page("Teachers", self._build_teachers_page())
        self.shell.add_page("Create New Teacher", self._build_create_teacher_page())
        self.shell.add_page("Teacher Detail", self._build_admin_teacher_detail_page())
        self.shell.add_page("Classes", self._build_classes_page())
        self.shell.add_page("Create New Class", self._build_create_class_page())
        self.shell.add_page("Students", self._build_admin_students_page())
        self.shell.add_page("Create Student", self._build_admin_create_student_page())
        self.shell.add_page("Student Detail", self._build_admin_student_detail_page())
        self.shell.add_page("AI Models", self._build_ai_models_page())
        self.shell.show_page("Dashboard")

        self.refresh_table()
        self.refresh_classes_table()
        self.refresh_requests_table()
        self.refresh_admin_students_class_filter()
        self.refresh_admin_students_table()
        self.refresh_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        self.refresh_ai_models_page()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # --- Dashboard page (overview only) ---------------------------------

    def _build_dashboard_page(self) -> QWidget:
        page, layout = create_page()

        # Cards double as navigation: click to open the page behind the number.
        self.total_teachers_card = StatCard(
            "Total Teachers", "0", on_click=lambda: self.shell.show_page("Teachers"))
        self.total_classes_card = StatCard(
            "Total Classes", "0", on_click=lambda: self.shell.show_page("Classes"))
        self.total_students_card = StatCard(
            "Total Students", "0", on_click=lambda: self.shell.show_page("Students"))
        self.pending_join_requests_card = StatCard(
            "Pending Join Requests", "0", on_click=lambda: self.shell.show_page("Classes"))
        self.unassigned_classes_card = StatCard(
            "Unassigned Classes", "0", on_click=lambda: self.shell.show_page("Classes"))
        self.db_status_card = StatCard("Database Status", "Connected")

        cards_row_1 = QHBoxLayout()
        cards_row_1.setSpacing(16)
        cards_row_1.addWidget(self.total_teachers_card)
        cards_row_1.addWidget(self.total_classes_card)
        cards_row_1.addWidget(self.total_students_card)
        layout.addLayout(cards_row_1)

        cards_row_2 = QHBoxLayout()
        cards_row_2.setSpacing(16)
        cards_row_2.addWidget(self.unassigned_classes_card)
        cards_row_2.addWidget(self.pending_join_requests_card)
        cards_row_2.addWidget(self.db_status_card)
        cards_row_2.addStretch()
        layout.addLayout(cards_row_2)

        # AI runtime strip ("the engine room"): what is live right now, as
        # dots + names - refreshed with the rest of the dashboard.
        self.runtime_strip = QLabel("")
        self.runtime_strip.setObjectName("StatusLabel")
        self.runtime_strip.setTextFormat(Qt.TextFormat.RichText)
        self.runtime_strip.setStyleSheet(
            "background-color: #3A3A3A; border-radius: 10px; padding: 10px 16px;"
            " font-size: 12px; color: #A5A5A5;")
        apply_card_shadow(self.runtime_strip, blur_radius=20, y_offset=4, alpha=40)
        layout.addWidget(self.runtime_strip)
        self._refresh_runtime_strip()

        activity_group = QGroupBox("Recent Activity")
        apply_card_shadow(activity_group)
        activity_layout = QVBoxLayout(activity_group)
        self.activity_feed_label = QLabel("No activity recorded yet.")
        self.activity_feed_label.setObjectName("StatusLabel")
        self.activity_feed_label.setWordWrap(True)
        activity_layout.addWidget(self.activity_feed_label)
        layout.addWidget(activity_group)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(16)

        manage_teachers_button = QPushButton("Manage Teachers")
        manage_teachers_button.setObjectName("PrimaryButton")
        manage_teachers_button.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_teachers_button.clicked.connect(lambda: self.shell.show_page("Teachers"))

        manage_classes_button = QPushButton("Manage Classes")
        manage_classes_button.setObjectName("PrimaryButton")
        manage_classes_button.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_classes_button.clicked.connect(lambda: self.shell.show_page("Classes"))

        actions_row.addWidget(manage_teachers_button)
        actions_row.addWidget(manage_classes_button)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        layout.addStretch()
        return page

    # --- Teachers page (table-focused) -----------------------------------

    def _build_teachers_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Teachers")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Manage teacher accounts.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_teacher_button = QPushButton("+ Create New Teacher")
        create_teacher_button.setObjectName("PrimaryButton")
        create_teacher_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_teacher_button.clicked.connect(lambda: self.shell.show_page("Create New Teacher"))
        header_row.addWidget(create_teacher_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.table = QTableWidget(0, len(TEACHER_TABLE_COLUMNS))
        teachers_search = attach_table_filter(self.table, "Search teachers by name, code or status...")
        layout.addWidget(teachers_search)
        self.table.setHorizontalHeaderLabels(TEACHER_TABLE_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            len(TEACHER_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(len(TEACHER_TABLE_COLUMNS) - 1, 420)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(260)
        apply_card_shadow(self.table)
        layout.addWidget(self.table)

        layout.addStretch()
        return page

    def _build_actions_cell(self, teacher: User) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(6)

        view_button = QPushButton("View / Edit")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, t=teacher: self.handle_view_admin_teacher(t))
        cell_layout.addWidget(view_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("DangerButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.setToolTip("Permanently delete this account - cannot be undone.")
        delete_button.clicked.connect(
            lambda _checked=False, t=teacher: self.handle_hard_delete_account(
                t.user_id, t.username, "teacher"))
        cell_layout.addWidget(delete_button)

        return cell

    # --- Create New Teacher page (hidden until selected) ------------------

    def _build_create_teacher_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Create New Teacher")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Teacher Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(6)

        self.new_username_input = QLineEdit()
        self.new_username_input.setPlaceholderText("e.g. teacher001")

        self.new_full_name_input = QLineEdit()
        self.new_full_name_input.setPlaceholderText("e.g. Zailan Arabee")

        self.new_password_input = QLineEdit()
        self.new_password_input.setPlaceholderText("Enter a password")
        self.new_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        # Live feedback while typing: username availability + password strength.
        self.new_teacher_form_hint = QLabel("")
        self.new_teacher_form_hint.setObjectName("HelperText")
        self.new_teacher_form_hint.setWordWrap(True)
        self.new_username_input.textChanged.connect(
            lambda _t: self._update_account_form_hint(
                self.new_username_input, self.new_password_input, self.new_teacher_form_hint))
        self.new_password_input.textChanged.connect(
            lambda _t: self._update_account_form_hint(
                self.new_username_input, self.new_password_input, self.new_teacher_form_hint))

        form_layout.addWidget(self._field_label("Username"))
        form_layout.addWidget(self.new_username_input)
        form_layout.addWidget(self._field_label("Full Name"))
        form_layout.addWidget(self.new_full_name_input)
        form_layout.addWidget(self._field_label("Password"))
        form_layout.addWidget(self.new_password_input)
        form_layout.addWidget(self.new_teacher_form_hint)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        create_button = QPushButton("Create Teacher")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_create_teacher)

        cancel_button = QPushButton("Cancel / Back to Teachers")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_create_teacher)

        buttons_row.addWidget(create_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- Classes page (real class management) ------------------------------

    def _build_classes_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Classes")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Manage English classes.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_class_button = QPushButton("+ Create New Class")
        create_class_button.setObjectName("PrimaryButton")
        create_class_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_class_button.clicked.connect(self.handle_open_create_class_page)
        header_row.addWidget(create_class_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.classes_total_card = StatCard("Total Classes", "0")
        self.assigned_teachers_card = StatCard("Assigned Teachers", "0")
        self.classes_subject_card = StatCard("Subject", "English")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.classes_total_card)
        cards_row.addWidget(self.assigned_teachers_card)
        cards_row.addWidget(self.classes_subject_card)
        layout.addLayout(cards_row)

        self.classes_table = QTableWidget(0, len(CLASS_TABLE_COLUMNS))
        classes_search = attach_table_filter(self.classes_table, "Search classes or teachers...")
        layout.addWidget(classes_search)
        self.classes_table.setHorizontalHeaderLabels(CLASS_TABLE_HEADERS)
        self.classes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.classes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.classes_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.classes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.classes_table.horizontalHeader().setSectionResizeMode(
            len(CLASS_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.classes_table.setColumnWidth(len(CLASS_TABLE_COLUMNS) - 1, 420)
        self.classes_table.verticalHeader().setVisible(False)
        self.classes_table.verticalHeader().setDefaultSectionSize(44)
        self.classes_table.setAlternatingRowColors(True)
        self.classes_table.setMinimumHeight(260)
        apply_card_shadow(self.classes_table)
        layout.addWidget(self.classes_table)

        requests_heading = QLabel("Transfer Requests")
        requests_heading.setObjectName("SectionHeading")
        layout.addWidget(requests_heading)

        requests_subtitle = QLabel("Pending class transfer requests awaiting a decision.")
        requests_subtitle.setObjectName("StatusLabel")
        layout.addWidget(requests_subtitle)

        self.requests_table = QTableWidget(0, len(REQUEST_TABLE_COLUMNS))
        self.requests_table.setHorizontalHeaderLabels(REQUEST_TABLE_HEADERS)
        self.requests_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.requests_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.requests_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.requests_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.requests_table.horizontalHeader().setSectionResizeMode(
            len(REQUEST_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.requests_table.setColumnWidth(len(REQUEST_TABLE_COLUMNS) - 1, 170)
        self.requests_table.verticalHeader().setVisible(False)
        self.requests_table.verticalHeader().setDefaultSectionSize(44)
        self.requests_table.setAlternatingRowColors(True)
        self.requests_table.setMinimumHeight(180)
        apply_card_shadow(self.requests_table)
        layout.addWidget(self.requests_table)

        layout.addStretch()
        return page

    def _build_class_actions_cell(self, class_: ClassWithTeacher) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit Name")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, c=class_: self.handle_edit_class_name(c))

        change_teacher_button = QPushButton("Change Teacher")
        change_teacher_button.setObjectName("RowActionButton")
        change_teacher_button.setCursor(Qt.CursorShape.PointingHandCursor)
        change_teacher_button.clicked.connect(
            lambda _checked=False, c=class_: self.handle_change_teacher(c)
        )

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, c=class_: self.handle_delete_class(c))

        cell_layout.addWidget(edit_button)
        cell_layout.addWidget(change_teacher_button)
        cell_layout.addWidget(delete_button)

        return cell

    def _build_request_actions_cell(self, request: TransferRequestWithDetails) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        approve_button = QPushButton("Approve")
        approve_button.setObjectName("RowActionButton")
        approve_button.setCursor(Qt.CursorShape.PointingHandCursor)
        approve_button.clicked.connect(
            lambda _checked=False, r=request: self.handle_approve_request(r)
        )

        reject_button = QPushButton("Reject")
        reject_button.setObjectName("RowActionButton")
        reject_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reject_button.clicked.connect(lambda _checked=False, r=request: self.handle_reject_request(r))

        cell_layout.addWidget(approve_button)
        cell_layout.addWidget(reject_button)

        return cell

    # --- Create New Class page (hidden until selected) ---------------------

    def _build_create_class_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Create New Class")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Class Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(6)

        self.new_class_name_input = QLineEdit()
        self.new_class_name_input.setPlaceholderText("e.g. 5A")

        self.teacher_dropdown = QComboBox()

        form_layout.addWidget(self._field_label("Class Name"))
        form_layout.addWidget(self.new_class_name_input)
        form_layout.addWidget(self._field_label("Teacher In Charge"))
        form_layout.addWidget(self.teacher_dropdown)
        form_layout.addWidget(self._field_label("Subject"))
        form_layout.addWidget(QLabel("English"))

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        self.create_class_button = QPushButton("Create Class")
        self.create_class_button.setObjectName("PrimaryButton")
        self.create_class_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_class_button.clicked.connect(self.handle_create_class)

        cancel_button = QPushButton("Cancel / Back to Classes")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_create_class)

        buttons_row.addWidget(self.create_class_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- Data refresh -----------------------------------------------------

    def refresh_table(self) -> None:
        conn = get_connection()
        try:
            teachers = list_teachers(conn)
            total_students = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'student' AND is_active = 1"
            ).fetchone()[0]
            db_stats = {
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "classes": conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
                "results": conn.execute("SELECT COUNT(*) FROM main_marking_final_results").fetchone()[0],
                "last_account": conn.execute("SELECT MAX(created_at) FROM users").fetchone()[0],
            }
        finally:
            conn.close()

        # Fully clear before rebuilding (rather than just resizing in place)
        # so no item or cell widget from a previous population can ever
        # linger at a stale row/column position.
        self.table.setRowCount(0)
        self.table.setRowCount(len(teachers))
        for row_index, teacher in enumerate(teachers):
            values = [
                teacher.teacher_code or "-",
                teacher.username,
                teacher.full_name,
                teacher.role,
                "Active" if teacher.is_active else "Deactivated",
                format_timestamp(teacher.created_at),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.table.item(row_index, TEACHER_TABLE_COLUMNS.index("status")),
                "Active" if teacher.is_active else "Deactivated")
            self.table.setCellWidget(row_index, len(values), self._build_actions_cell(teacher))
        # Force the pending item-widget layout to complete synchronously
        # (QTableWidget otherwise defers it), so the actions button is
        # never painted at a stale position after a refresh.
        self.table.doItemsLayout()

        self.total_teachers_card.set_value(str(len(teachers)))
        self.total_students_card.set_value(str(total_students))
        # Real health signal instead of a static "Connected": the query above
        # succeeding proves the DB answers, and the tooltip carries the vitals.
        self.db_status_card.set_value("Healthy")
        self.db_status_card.setToolTip(
            f"Users: {db_stats['users']}  |  Classes: {db_stats['classes']}  |  "
            f"Finalised results: {db_stats['results']}\n"
            f"Last account created: {format_timestamp(db_stats['last_account']) if db_stats['last_account'] else '-'}"
        )
        self.refresh_activity_feed()

    def refresh_activity_feed(self) -> None:
        """The newest account/class/result events across the system, straight
        from the tables that already record them - no separate event log."""
        conn = get_connection()
        try:
            events = []
            for username, full_name, role, created_at in conn.execute(
                    "SELECT username, full_name, role, created_at FROM users "
                    "ORDER BY created_at DESC LIMIT 5"):
                events.append((created_at, f"{role.title()} account created: {full_name} ({username})"))
            for class_name, created_at in conn.execute(
                    "SELECT class_name, created_at FROM classes ORDER BY created_at DESC LIMIT 5"):
                events.append((created_at, f"Class created: {class_name}"))
            for display_name, total, maximum, finalized_at in conn.execute(
                    "SELECT answer_file_display_name, total_score, max_score, finalized_at "
                    "FROM main_marking_final_results ORDER BY finalized_at DESC LIMIT 5"):
                events.append((finalized_at, f"Result finalised: {display_name} ({total:g}/{maximum:g})"))
        finally:
            conn.close()
        events.sort(key=lambda e: e[0] or "", reverse=True)
        if not events:
            self.activity_feed_label.setText("No activity recorded yet.")
            return
        lines = [f"{self._relative_time(when)}  -  {text}" for when, text in events[:8]]
        self.activity_feed_label.setText(chr(10).join(lines))
        # Absolute timestamps stay one hover away.
        self.activity_feed_label.setToolTip(
            chr(10).join(f"{format_timestamp(when)} - {text}" for when, text in events[:8]))

    def _refresh_runtime_strip(self) -> None:
        """Live AI stack status: which Core AI models are active (from the
        backend's activation pointers) and whether a local feedback runtime
        is configured. Green dot = live, grey dot = not set up."""
        import json
        from app.database.db import DATA_DIR

        def dot(ok: bool) -> str:
            return ("<span style='color:#34D399'>&#9679;</span>" if ok
                    else "<span style='color:#7E7E7E'>&#9679;</span>")

        active_root = DATA_DIR / "ai" / "active"
        parts = []
        for family, label in (("core_ai1", "Core AI 1"), ("core_ai2", "Core AI 2")):
            pointer = active_root / f"{family}.json"
            version = None
            if pointer.exists():
                try:
                    version = json.loads(pointer.read_text(encoding="utf-8")).get("model_version")
                except (OSError, ValueError):
                    version = None
            parts.append(f"{dot(bool(version))} {label}: {version or 'no active model'}")

        conn = get_connection()
        try:
            runtime_row = conn.execute(
                "SELECT feedback_adapter, feedback_model_name FROM local_ai_settings "
                "WHERE feedback_adapter IS NOT NULL AND feedback_adapter != 'none' LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if runtime_row:
            parts.append(f"{dot(True)} Feedback runtime: {runtime_row[0]} ({runtime_row[1] or '-'})")
        else:
            parts.append(f"{dot(False)} Feedback runtime: not configured")
        self.runtime_strip.setText("&nbsp;&nbsp;&nbsp;".join(parts))

    def handle_hard_delete_account(self, user_id: int, username: str, role: str) -> None:
        """HARD delete (no undo). Students go with their whole submission
        tree; a teacher who still owns classes/profiles/sessions/materials is
        refused with the exact list of what to clear first."""
        if self._user is None:
            return
        consequence = (
            "every record they own - class memberships, attempts, marking "
            "results, external revisions and uploaded files - is permanently deleted with them."
            if role == "student" else
            "the account is permanently removed. It must no longer own classes, "
            "profiles, sessions or materials.")
        if not prompt_confirm(
                self, "Delete Account Permanently",
                f"Hard-delete {role} '{username}'? This CANNOT be undone: {consequence}",
                confirm_text="Delete permanently"):
            return
        from app.services.admin_account_service import hard_delete_user_account
        conn = get_connection()
        try:
            try:
                deleted = hard_delete_user_account(conn, self._user.user_id, user_id)
            except ValueError as exc:
                show_error(self, "Delete Account Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_table()
        self.refresh_admin_students_table()
        self.refresh_classes_table()
        show_success(self, "Account Deleted", f"'{deleted}' was permanently deleted.")

    def _update_account_form_hint(self, username_input: QLineEdit,
                                  password_input: QLineEdit, hint_label: QLabel) -> None:
        """Live username-availability + password-strength feedback while the
        admin types - catches duplicate usernames and weak passwords before
        the failed submit."""
        parts = []
        username = username_input.text().strip()
        if username:
            conn = get_connection()
            try:
                taken = conn.execute(
                    "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None
            finally:
                conn.close()
            parts.append("Username already taken" if taken else "Username available")
        password = password_input.text()
        if password:
            if len(password) < 6:
                parts.append("Password: weak (under 6 characters)")
            elif len(password) < 10:
                parts.append("Password: okay")
            else:
                parts.append("Password: strong")
        hint_label.setText("  |  ".join(parts))

    @staticmethod
    def _relative_time(iso_value) -> str:
        """'12m ago' / '3h ago' / '2d ago' for feed scannability; falls back
        to the absolute timestamp when the value can't be parsed."""
        from datetime import datetime, timezone
        try:
            then = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return format_timestamp(iso_value)
        seconds = int((datetime.now(timezone.utc) - then).total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"

    def refresh_classes_table(self) -> None:
        conn = get_connection()
        try:
            classes = list_all_classes_with_teacher_info(conn)
            total_classes = count_all_classes(conn)
            assigned_teachers = count_assigned_teachers(conn)
            unassigned_classes = count_unassigned_classes(conn)
        finally:
            conn.close()

        self.classes_table.setRowCount(len(classes))
        for row_index, class_ in enumerate(classes):
            values = [
                class_.class_id,
                class_.class_name,
                class_.subject,
                class_.teacher_name or "Unassigned",
                class_.teacher_username or "-",
                format_timestamp(class_.created_at),
            ]
            for col_index, value in enumerate(values):
                self.classes_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.classes_table.setCellWidget(
                row_index, len(values), self._build_class_actions_cell(class_)
            )

        self.total_classes_card.set_value(str(total_classes))
        self.classes_total_card.set_value(str(total_classes))
        self.assigned_teachers_card.set_value(str(assigned_teachers))
        self.unassigned_classes_card.set_value(str(unassigned_classes))

    def refresh_requests_table(self) -> None:
        conn = get_connection()
        try:
            requests = list_all_pending_requests(conn)
            pending_count = count_pending_requests(conn)
        finally:
            conn.close()

        self.requests_table.setRowCount(len(requests))
        for row_index, request in enumerate(requests):
            values = [
                request.request_id,
                request.class_name,
                request.current_teacher_name,
                request.requesting_teacher_name,
                request.request_reason or "",
                format_timestamp(request.created_at),
            ]
            for col_index, value in enumerate(values):
                self.requests_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.requests_table.setCellWidget(
                row_index, len(values), self._build_request_actions_cell(request)
            )

        self.pending_join_requests_card.set_value(str(pending_count))

    def refresh_teacher_dropdown(self) -> None:
        conn = get_connection()
        try:
            teachers = list_teachers(conn)
        finally:
            conn.close()

        self.teacher_dropdown.clear()
        self.teacher_dropdown.addItem("-- No teacher assigned --", None)
        for teacher in teachers:
            self.teacher_dropdown.addItem(f"{teacher.full_name} ({teacher.username})", teacher.user_id)
        self.teacher_dropdown.setCurrentIndex(0)

    # --- Handlers: Teachers -------------------------------------------------

    def handle_create_teacher(self) -> None:
        username = self.new_username_input.text()
        full_name = self.new_full_name_input.text()
        password = self.new_password_input.text()

        conn = get_connection()
        try:
            create_teacher(conn, username, full_name, password)
        except ValueError as exc:
            show_error(self, "Create Teacher Failed", str(exc))
            return
        finally:
            conn.close()

        self.new_username_input.clear()
        self.new_full_name_input.clear()
        self.new_password_input.clear()
        self.refresh_table()
        show_success(self, "Create Teacher", "Teacher account created successfully.")
        self.shell.show_page("Teachers")

    def handle_cancel_create_teacher(self) -> None:
        self.new_username_input.clear()
        self.new_full_name_input.clear()
        self.new_password_input.clear()
        self.shell.show_page("Teachers")

    def handle_view_admin_teacher(self, teacher: User) -> None:
        self._current_admin_teacher_id = teacher.user_id
        self.refresh_admin_teacher_detail_page()
        self.shell.show_page("Teacher Detail")

    # --- Teacher Detail page (Admin-only edit/password/status) -------------

    def _build_admin_teacher_detail_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title = QLabel("Teacher Detail")
        title.setObjectName("SectionHeading")
        header_row.addWidget(title)
        header_row.addStretch()

        back_button = QPushButton("Back to Teachers")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(lambda: self.shell.show_page("Teachers"))
        header_row.addWidget(back_button)
        layout.addLayout(header_row)

        self.admin_teacher_status_label = QLabel("")
        self.admin_teacher_status_label.setObjectName("StatusLabel")
        layout.addWidget(self.admin_teacher_status_label)

        details_group = QGroupBox("Teacher Details")
        apply_card_shadow(details_group)
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(4)

        details_layout.addWidget(self._field_label("Teacher Code"))
        self.admin_teacher_code_label = QLabel("-")
        details_layout.addWidget(self.admin_teacher_code_label)

        details_layout.addWidget(self._field_label("Username"))
        self.admin_teacher_username_input = QLineEdit()
        details_layout.addWidget(self.admin_teacher_username_input)

        details_layout.addWidget(self._field_label("Full Name"))
        self.admin_teacher_full_name_input = QLineEdit()
        details_layout.addWidget(self.admin_teacher_full_name_input)

        details_layout.addWidget(self._field_label("Role"))
        self.admin_teacher_role_label = QLabel("Teacher")
        details_layout.addWidget(self.admin_teacher_role_label)

        details_layout.addWidget(self._field_label("Created At"))
        self.admin_teacher_created_at_label = QLabel("-")
        details_layout.addWidget(self.admin_teacher_created_at_label)

        save_details_button = QPushButton("Save Details")
        save_details_button.setObjectName("PrimaryButton")
        save_details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_details_button.clicked.connect(self.handle_save_admin_teacher_details)
        details_layout.addWidget(save_details_button)

        layout.addWidget(details_group)

        classes_group = QGroupBox("Assigned Classes")
        apply_card_shadow(classes_group)
        classes_layout = QVBoxLayout(classes_group)
        classes_layout.setSpacing(4)

        classes_layout.addWidget(self._field_label("Classes Owned"))
        self.admin_teacher_classes_label = QLabel("-")
        self.admin_teacher_classes_label.setWordWrap(True)
        classes_layout.addWidget(self.admin_teacher_classes_label)

        layout.addWidget(classes_group)

        password_group = QGroupBox("Password")
        apply_card_shadow(password_group)
        password_layout = QHBoxLayout(password_group)
        password_layout.setSpacing(16)

        reset_password_button = QPushButton("Reset Password")
        reset_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_password_button.clicked.connect(self.handle_reset_admin_teacher_password)
        password_layout.addWidget(reset_password_button)

        view_password_button = QPushButton("View Password")
        view_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_password_button.clicked.connect(self.handle_view_admin_teacher_password)
        password_layout.addWidget(view_password_button)
        password_layout.addStretch()

        layout.addWidget(password_group)

        status_group = QGroupBox("Account Status")
        apply_card_shadow(status_group)
        status_layout = QHBoxLayout(status_group)

        self.admin_teacher_toggle_active_button = QPushButton("Deactivate")
        self.admin_teacher_toggle_active_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.admin_teacher_toggle_active_button.clicked.connect(self.handle_toggle_admin_teacher_active_status)
        status_layout.addWidget(self.admin_teacher_toggle_active_button)
        status_layout.addStretch()

        layout.addWidget(status_group)

        layout.addStretch()
        return page

    def refresh_admin_teacher_detail_page(self) -> None:
        if self._current_admin_teacher_id is None:
            return

        conn = get_connection()
        try:
            teacher = get_teacher_for_admin(conn, self._current_admin_teacher_id)
            owned_classes = list_teacher_classes(conn, self._current_admin_teacher_id)
        finally:
            conn.close()

        self.admin_teacher_status_label.setText(
            f"{teacher.full_name} ({teacher.username}) - {'Active' if teacher.is_active else 'Deactivated'}"
        )
        self.admin_teacher_code_label.setText(teacher.teacher_code or "-")
        self.admin_teacher_username_input.setText(teacher.username)
        self.admin_teacher_full_name_input.setText(teacher.full_name)
        self.admin_teacher_created_at_label.setText(format_timestamp(teacher.created_at))
        self.admin_teacher_classes_label.setText(
            ", ".join(c.class_name for c in owned_classes) or "None"
        )
        self.admin_teacher_toggle_active_button.setText("Deactivate" if teacher.is_active else "Activate")

    def handle_save_admin_teacher_details(self) -> None:
        if self._current_admin_teacher_id is None:
            return

        username = self.admin_teacher_username_input.text()
        full_name = self.admin_teacher_full_name_input.text()

        conn = get_connection()
        try:
            try:
                update_teacher_details(conn, self._current_admin_teacher_id, username, full_name)
            except ValueError as exc:
                show_error(self, "Save Details Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_teacher_detail_page()
        self.refresh_table()
        show_success(self, "Save Details", "Teacher details updated successfully.")

    def handle_reset_admin_teacher_password(self) -> None:
        if self._current_admin_teacher_id is None:
            return

        new_password = prompt_input(
            self,
            "Reset Password",
            "Enter a new password for this teacher.",
            is_password=True,
        )
        if new_password is None:
            return

        conn = get_connection()
        try:
            try:
                reset_teacher_password(conn, self._current_admin_teacher_id, new_password)
            except ValueError as exc:
                show_error(self, "Reset Password Failed", str(exc))
                return
        finally:
            conn.close()

        show_success(self, "Reset Password", "Password reset successfully.")

    def handle_view_admin_teacher_password(self) -> None:
        if self._current_admin_teacher_id is None:
            return

        conn = get_connection()
        try:
            teacher = get_teacher_for_admin(conn, self._current_admin_teacher_id)
            password_display = get_teacher_password_display(conn, self._current_admin_teacher_id)
        finally:
            conn.close()

        is_available = password_display != TEACHER_PASSWORD_NOT_AVAILABLE_MESSAGE
        show_password_reveal(
            self,
            "Teacher Password",
            f"{teacher.full_name} ({teacher.username})",
            password_display,
            is_available,
        )

    def handle_toggle_admin_teacher_active_status(self) -> None:
        if self._current_admin_teacher_id is None:
            return

        conn = get_connection()
        try:
            teacher = get_teacher_for_admin(conn, self._current_admin_teacher_id)
        finally:
            conn.close()

        new_status = not teacher.is_active
        action_label = "Activate" if new_status else "Deactivate"
        message = f"{action_label} '{teacher.full_name}' ({teacher.username})?"
        if not new_status:
            message += " Their classes will become unassigned; students will remain in those classes."
        confirmed = prompt_confirm(
            self,
            f"{action_label} Teacher",
            message,
            confirm_text=action_label,
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                set_teacher_active_status(conn, self._current_admin_teacher_id, new_status)
            except ValueError as exc:
                show_error(self, f"{action_label} Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_teacher_detail_page()
        self.refresh_table()
        self.refresh_classes_table()
        show_success(self, action_label, f"Teacher {'activated' if new_status else 'deactivated'} successfully.")

    # --- Handlers: Classes ---------------------------------------------------

    def handle_open_create_class_page(self) -> None:
        self.refresh_teacher_dropdown()
        self.shell.show_page("Create New Class")

    def handle_create_class(self) -> None:
        class_name = self.new_class_name_input.text()
        teacher_id = self.teacher_dropdown.currentData()

        conn = get_connection()
        try:
            create_class_for_teacher(conn, class_name, teacher_id)
        except ValueError as exc:
            show_error(self, "Create Class Failed", str(exc))
            return
        finally:
            conn.close()

        self.new_class_name_input.clear()
        self.refresh_classes_table()
        show_success(self, "Create Class", "Class created successfully.")
        self.shell.show_page("Classes")

    def handle_cancel_create_class(self) -> None:
        self.new_class_name_input.clear()
        self.shell.show_page("Classes")

    def handle_edit_class_name(self, class_: ClassWithTeacher) -> None:
        new_name = prompt_input(
            self,
            "Edit Class Name",
            f"Enter a new name for '{class_.class_name}'.",
            placeholder=class_.class_name,
        )
        if new_name is None:
            return

        conn = get_connection()
        try:
            update_class_name(conn, class_.class_id, new_name)
        except ValueError as exc:
            show_error(self, "Edit Class Name Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_classes_table()
        show_success(self, "Edit Class Name", "Class name updated successfully.")

    def handle_change_teacher(self, class_: ClassWithTeacher) -> None:
        conn = get_connection()
        try:
            teachers = list_teachers(conn)
        finally:
            conn.close()

        options = [("-- No teacher assigned --", None)] + [
            (f"{t.full_name} ({t.username})", t.user_id) for t in teachers
        ]
        new_teacher_id = prompt_select(
            self,
            "Change Teacher In Charge",
            f"Select the new teacher in charge for '{class_.class_name}'.",
            options,
        )
        if new_teacher_id is CANCELLED:
            return

        conn = get_connection()
        try:
            update_class_teacher(conn, class_.class_id, new_teacher_id)
        except ValueError as exc:
            show_error(self, "Change Teacher Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_classes_table()
        show_success(self, "Change Teacher", "Teacher in charge updated successfully.")

    def handle_delete_class(self, class_: ClassWithTeacher) -> None:
        confirmed = prompt_confirm(
            self,
            "Delete Class",
            f"Are you sure you want to delete '{class_.class_name}'? This cannot be undone.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            delete_class(conn, class_.class_id)
        finally:
            conn.close()

        self.refresh_classes_table()
        self.refresh_requests_table()
        show_success(self, "Delete Class", "Class deleted successfully.")

    def handle_approve_request(self, request: TransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Approve Request Failed", "No logged-in admin user was found.")
            return

        confirmed = prompt_confirm(
            self,
            "Approve Transfer Request",
            f"Approve transferring '{request.class_name}' to {request.requesting_teacher_name}?",
            confirm_text="Approve",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            approve_transfer_request(conn, request.request_id, self._user)
        except ValueError as exc:
            show_error(self, "Approve Request Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_classes_table()
        self.refresh_requests_table()
        show_success(self, "Approve Request", "Transfer request approved successfully.")

    def handle_reject_request(self, request: TransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Reject Request Failed", "No logged-in admin user was found.")
            return

        reason = prompt_input(
            self,
            "Reject Transfer Request",
            f"Optional reason for rejecting {request.requesting_teacher_name}'s request for "
            f"'{request.class_name}' (leave blank if none).",
        )
        if reason is None:
            return

        conn = get_connection()
        try:
            reject_transfer_request(conn, request.request_id, self._user, reason)
        except ValueError as exc:
            show_error(self, "Reject Request Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_requests_table()
        show_success(self, "Reject Request", "Transfer request rejected.")

    # --- Students page (Admin-only, all students across all teachers) ----

    def _build_admin_students_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Students")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("View and manage every student account across all teachers and classes.")
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_student_button = QPushButton("+ Create Student")
        create_student_button.setObjectName("PrimaryButton")
        create_student_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_student_button.clicked.connect(self.handle_open_admin_create_student_page)
        header_row.addWidget(create_student_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        filter_row.addWidget(self._field_label("Filter by Class"))
        self.admin_students_class_filter = QComboBox()
        self.admin_students_class_filter.currentIndexChanged.connect(
            lambda _index: self.refresh_admin_students_table()
        )
        filter_row.addWidget(self.admin_students_class_filter)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.admin_students_table = QTableWidget(0, len(ADMIN_STUDENT_TABLE_COLUMNS))
        students_search = attach_table_filter(
            self.admin_students_table, "Search students by name, code or class...")
        layout.addWidget(students_search)
        self.admin_students_table.setHorizontalHeaderLabels(ADMIN_STUDENT_TABLE_HEADERS)
        self.admin_students_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.admin_students_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.admin_students_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.admin_students_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.admin_students_table.horizontalHeader().setSectionResizeMode(
            len(ADMIN_STUDENT_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.admin_students_table.setColumnWidth(len(ADMIN_STUDENT_TABLE_COLUMNS) - 1, 160)
        self.admin_students_table.verticalHeader().setVisible(False)
        self.admin_students_table.verticalHeader().setDefaultSectionSize(44)
        self.admin_students_table.setAlternatingRowColors(True)
        self.admin_students_table.setMinimumHeight(260)
        apply_card_shadow(self.admin_students_table)
        layout.addWidget(self.admin_students_table)

        transfer_requests_heading = QLabel("Student Transfer Requests")
        transfer_requests_heading.setObjectName("SectionHeading")
        layout.addWidget(transfer_requests_heading)

        transfer_requests_subtitle = QLabel("Pending requests to move a student from one class to another.")
        transfer_requests_subtitle.setObjectName("StatusLabel")
        layout.addWidget(transfer_requests_subtitle)

        self.student_transfer_requests_table = QTableWidget(0, len(STUDENT_TRANSFER_REQUEST_TABLE_COLUMNS))
        self.student_transfer_requests_table.setHorizontalHeaderLabels(STUDENT_TRANSFER_REQUEST_TABLE_HEADERS)
        self.student_transfer_requests_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.student_transfer_requests_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.student_transfer_requests_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.student_transfer_requests_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.student_transfer_requests_table.horizontalHeader().setSectionResizeMode(
            len(STUDENT_TRANSFER_REQUEST_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.student_transfer_requests_table.setColumnWidth(len(STUDENT_TRANSFER_REQUEST_TABLE_COLUMNS) - 1, 170)
        self.student_transfer_requests_table.verticalHeader().setVisible(False)
        self.student_transfer_requests_table.verticalHeader().setDefaultSectionSize(44)
        self.student_transfer_requests_table.setAlternatingRowColors(True)
        self.student_transfer_requests_table.setMinimumHeight(180)
        apply_card_shadow(self.student_transfer_requests_table)
        layout.addWidget(self.student_transfer_requests_table)

        history_heading = QLabel("Transfer Request History")
        history_heading.setObjectName("SectionHeading")
        layout.addWidget(history_heading)

        history_subtitle = QLabel("Every approved/rejected student transfer request - decisions are never deleted.")
        history_subtitle.setObjectName("StatusLabel")
        layout.addWidget(history_subtitle)

        self.student_transfer_history_table = QTableWidget(0, len(STUDENT_TRANSFER_HISTORY_TABLE_COLUMNS))
        self.student_transfer_history_table.setHorizontalHeaderLabels(STUDENT_TRANSFER_HISTORY_TABLE_HEADERS)
        self.student_transfer_history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.student_transfer_history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.student_transfer_history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.student_transfer_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.student_transfer_history_table.verticalHeader().setVisible(False)
        self.student_transfer_history_table.verticalHeader().setDefaultSectionSize(44)
        self.student_transfer_history_table.setAlternatingRowColors(True)
        self.student_transfer_history_table.setMinimumHeight(180)
        apply_card_shadow(self.student_transfer_history_table)
        layout.addWidget(self.student_transfer_history_table)

        layout.addStretch()
        return page

    def _build_admin_create_student_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title = QLabel("Create Student")
        title.setObjectName("SectionHeading")
        header_row.addWidget(title)
        header_row.addStretch()

        back_button = QPushButton("Cancel / Back to Students")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_cancel_admin_create_student)
        header_row.addWidget(back_button)
        layout.addLayout(header_row)

        form_group = QGroupBox("Student Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(6)

        self.admin_new_student_username_input = QLineEdit()
        self.admin_new_student_username_input.setPlaceholderText("e.g. TP070498")

        self.admin_new_student_full_name_input = QLineEdit()
        self.admin_new_student_full_name_input.setPlaceholderText("e.g. Ng Jia Chern")

        self.admin_new_student_password_input = QLineEdit()
        self.admin_new_student_password_input.setPlaceholderText("Enter a password")
        self.admin_new_student_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.admin_new_student_show_password_checkbox = QCheckBox("Show password?")
        self.admin_new_student_show_password_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.admin_new_student_show_password_checkbox.toggled.connect(
            self.handle_toggle_admin_new_student_show_password
        )

        self.admin_new_student_class_dropdown = QComboBox()

        self.admin_new_student_form_hint = QLabel("")
        self.admin_new_student_form_hint.setObjectName("HelperText")
        self.admin_new_student_form_hint.setWordWrap(True)
        self.admin_new_student_username_input.textChanged.connect(
            lambda _t: self._update_account_form_hint(
                self.admin_new_student_username_input,
                self.admin_new_student_password_input,
                self.admin_new_student_form_hint))
        self.admin_new_student_password_input.textChanged.connect(
            lambda _t: self._update_account_form_hint(
                self.admin_new_student_username_input,
                self.admin_new_student_password_input,
                self.admin_new_student_form_hint))

        form_layout.addWidget(self._field_label("Username"))
        form_layout.addWidget(self.admin_new_student_username_input)
        form_layout.addWidget(self._field_label("Full Name"))
        form_layout.addWidget(self.admin_new_student_full_name_input)
        form_layout.addWidget(self._field_label("Password"))
        form_layout.addWidget(self.admin_new_student_password_input)
        form_layout.addWidget(self.admin_new_student_show_password_checkbox)
        form_layout.addWidget(self.admin_new_student_form_hint)
        form_layout.addWidget(self._field_label("Assign to Class (any teacher's class, or Unassigned)"))
        form_layout.addWidget(self.admin_new_student_class_dropdown)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        create_button = QPushButton("Create Student")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_admin_create_student)

        cancel_button = QPushButton("Cancel / Back to Students")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_admin_create_student)

        buttons_row.addWidget(create_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    def _build_admin_student_actions_cell(self, row: AdminStudentRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(6)

        view_button = QPushButton("View / Edit")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_admin_student(r))
        cell_layout.addWidget(view_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("DangerButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.setToolTip("Permanently delete this account and all their submissions - cannot be undone.")
        delete_button.clicked.connect(
            lambda _checked=False, r=row: self.handle_hard_delete_account(
                r.user_id, r.username, "student"))
        cell_layout.addWidget(delete_button)

        return cell

    def _build_student_transfer_request_actions_cell(self, request: StudentTransferRequestWithDetails) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)

        approve_button = QPushButton("Approve")
        approve_button.setObjectName("RowActionButton")
        approve_button.setCursor(Qt.CursorShape.PointingHandCursor)
        approve_button.clicked.connect(
            lambda _checked=False, r=request: self.handle_approve_student_transfer_request(r)
        )
        cell_layout.addWidget(approve_button)

        reject_button = QPushButton("Reject")
        reject_button.setObjectName("RowActionButton")
        reject_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reject_button.clicked.connect(
            lambda _checked=False, r=request: self.handle_reject_student_transfer_request(r)
        )
        cell_layout.addWidget(reject_button)

        return cell

    def refresh_admin_students_class_filter(self) -> None:
        conn = get_connection()
        try:
            classes = list_all_classes_with_teacher_info(conn)
        finally:
            conn.close()

        self.admin_students_class_filter.blockSignals(True)
        self.admin_students_class_filter.clear()
        self.admin_students_class_filter.addItem("All Students", None)
        self.admin_students_class_filter.addItem("Unassigned", UNASSIGNED_FILTER)
        for class_ in classes:
            self.admin_students_class_filter.addItem(class_.class_name, class_.class_id)
        self.admin_students_class_filter.setCurrentIndex(0)
        self.admin_students_class_filter.blockSignals(False)

    def refresh_admin_students_table(self) -> None:
        class_id = self.admin_students_class_filter.currentData()

        conn = get_connection()
        try:
            students = list_all_students(conn, class_id)
        finally:
            conn.close()

        # Fully clear before rebuilding (rather than just resizing in place)
        # so no item or cell widget from a previous population can ever
        # linger at a stale row/column position.
        self.admin_students_table.setRowCount(0)
        self.admin_students_table.setRowCount(len(students))
        for row_index, row in enumerate(students):
            values = [
                row.student_code or "-",
                row.username,
                row.full_name,
                row.class_names or "Unassigned",
                row.teacher_names or "-",
                "Active" if row.is_active else "Deactivated",
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.admin_students_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.admin_students_table.item(
                    row_index, ADMIN_STUDENT_TABLE_COLUMNS.index("status")),
                "Active" if row.is_active else "Deactivated")
            self.admin_students_table.setCellWidget(
                row_index, len(values), self._build_admin_student_actions_cell(row)
            )
        # Force the pending item-widget layout to complete synchronously
        # (QTableWidget otherwise defers it), so the actions button is
        # never painted at a stale position after a refresh.
        self.admin_students_table.doItemsLayout()

    def refresh_student_transfer_requests_table(self) -> None:
        conn = get_connection()
        try:
            requests = list_all_pending_student_transfer_requests(conn)
        finally:
            conn.close()

        table = self.student_transfer_requests_table
        table.setRowCount(0)
        table.setRowCount(len(requests))
        for row_index, request in enumerate(requests):
            values = [
                request.request_id,
                request.student_code or "-",
                f"{request.student_full_name} ({request.student_username})",
                request.source_class_name,
                request.current_teacher_name,
                request.target_class_name,
                request.requesting_teacher_name,
                format_timestamp(request.created_at),
            ]
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            table.setCellWidget(
                row_index, len(values), self._build_student_transfer_request_actions_cell(request)
            )
        table.doItemsLayout()

    def refresh_student_transfer_history_table(self) -> None:
        conn = get_connection()
        try:
            requests = list_all_decided_student_transfer_requests(conn)
        finally:
            conn.close()

        table = self.student_transfer_history_table
        table.setRowCount(0)
        table.setRowCount(len(requests))
        for row_index, request in enumerate(requests):
            values = [
                request.request_id,
                request.student_code or "-",
                f"{request.student_full_name} ({request.student_username})",
                request.source_class_name,
                request.target_class_name,
                request.requesting_teacher_name,
                request.decided_by_name or "-",
                request.status.capitalize(),
                request.response_reason or "-",
                format_timestamp(request.responded_at) if request.responded_at else "-",
            ]
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        table.doItemsLayout()

    def handle_open_admin_create_student_page(self) -> None:
        self.refresh_admin_new_student_class_dropdown()
        self.shell.show_page("Create Student")

    def refresh_admin_new_student_class_dropdown(self) -> None:
        conn = get_connection()
        try:
            classes = list_all_classes_with_teacher_info(conn)
        finally:
            conn.close()

        self.admin_new_student_class_dropdown.clear()
        self.admin_new_student_class_dropdown.addItem("Unassigned (No Class)", None)
        for class_ in classes:
            label = f"{class_.class_name} ({class_.teacher_name or 'Unassigned'})"
            self.admin_new_student_class_dropdown.addItem(label, class_.class_id)
        self.admin_new_student_class_dropdown.setCurrentIndex(0)

    def handle_toggle_admin_new_student_show_password(self, checked: bool) -> None:
        self.admin_new_student_password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def handle_admin_create_student(self) -> None:
        username = self.admin_new_student_username_input.text()
        full_name = self.admin_new_student_full_name_input.text()
        password = self.admin_new_student_password_input.text()
        class_id = self.admin_new_student_class_dropdown.currentData()

        conn = get_connection()
        try:
            try:
                admin_create_student(conn, username, full_name, password, class_id)
            except ValueError as exc:
                show_error(self, "Create Student Failed", str(exc))
                return
        finally:
            conn.close()

        self.admin_new_student_username_input.clear()
        self.admin_new_student_full_name_input.clear()
        self.admin_new_student_password_input.clear()
        self.admin_new_student_show_password_checkbox.setChecked(False)
        self.refresh_admin_students_table()
        show_success(self, "Create Student", "Student account created successfully.")
        self.shell.show_page("Students")

    def handle_cancel_admin_create_student(self) -> None:
        self.admin_new_student_username_input.clear()
        self.admin_new_student_full_name_input.clear()
        self.admin_new_student_password_input.clear()
        self.admin_new_student_show_password_checkbox.setChecked(False)
        self.shell.show_page("Students")

    def handle_view_admin_student(self, row: AdminStudentRow) -> None:
        self._current_admin_student_id = row.user_id
        self.refresh_admin_student_detail_page()
        self.shell.show_page("Student Detail")

    # --- Student Detail page (Admin-only edit/change class/password/status) --

    def _build_admin_student_detail_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title = QLabel("Student Detail")
        title.setObjectName("SectionHeading")
        header_row.addWidget(title)
        header_row.addStretch()

        back_button = QPushButton("Back to Students")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(lambda: self.shell.show_page("Students"))
        header_row.addWidget(back_button)
        layout.addLayout(header_row)

        self.admin_student_status_label = QLabel("")
        self.admin_student_status_label.setObjectName("StatusLabel")
        layout.addWidget(self.admin_student_status_label)

        details_group = QGroupBox("Student Details")
        apply_card_shadow(details_group)
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(4)

        details_layout.addWidget(self._field_label("Student Code (e.g. TP0001)"))
        self.admin_student_code_input = QLineEdit()
        details_layout.addWidget(self.admin_student_code_input)

        details_layout.addWidget(self._field_label("Username"))
        self.admin_student_username_input = QLineEdit()
        details_layout.addWidget(self.admin_student_username_input)

        details_layout.addWidget(self._field_label("Full Name"))
        self.admin_student_full_name_input = QLineEdit()
        details_layout.addWidget(self.admin_student_full_name_input)

        details_layout.addWidget(self._field_label("Created At"))
        self.admin_student_created_at_label = QLabel("-")
        details_layout.addWidget(self.admin_student_created_at_label)

        save_details_button = QPushButton("Save Details")
        save_details_button.setObjectName("PrimaryButton")
        save_details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_details_button.clicked.connect(self.handle_save_admin_student_details)
        details_layout.addWidget(save_details_button)

        layout.addWidget(details_group)

        class_group = QGroupBox("Class")
        apply_card_shadow(class_group)
        class_layout = QVBoxLayout(class_group)
        class_layout.setSpacing(4)

        class_layout.addWidget(self._field_label("Current Class(es)"))
        self.admin_student_classes_label = QLabel("-")
        self.admin_student_classes_label.setWordWrap(True)
        class_layout.addWidget(self.admin_student_classes_label)

        change_class_button = QPushButton("Change Class")
        change_class_button.setCursor(Qt.CursorShape.PointingHandCursor)
        change_class_button.clicked.connect(self.handle_admin_change_student_class)
        class_layout.addWidget(change_class_button)

        layout.addWidget(class_group)

        password_group = QGroupBox("Password")
        apply_card_shadow(password_group)
        password_layout = QHBoxLayout(password_group)
        password_layout.setSpacing(16)

        reset_password_button = QPushButton("Reset Password")
        reset_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_password_button.clicked.connect(self.handle_reset_admin_student_password)
        password_layout.addWidget(reset_password_button)

        view_password_button = QPushButton("View Password")
        view_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_password_button.clicked.connect(self.handle_view_admin_student_password)
        password_layout.addWidget(view_password_button)
        password_layout.addStretch()

        layout.addWidget(password_group)

        status_group = QGroupBox("Account Status")
        apply_card_shadow(status_group)
        status_layout = QHBoxLayout(status_group)

        self.admin_student_toggle_active_button = QPushButton("Deactivate")
        self.admin_student_toggle_active_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.admin_student_toggle_active_button.clicked.connect(self.handle_toggle_admin_student_active_status)
        status_layout.addWidget(self.admin_student_toggle_active_button)
        status_layout.addStretch()

        layout.addWidget(status_group)

        layout.addStretch()
        return page

    def refresh_admin_student_detail_page(self) -> None:
        if self._current_admin_student_id is None:
            return

        conn = get_connection()
        try:
            student = get_student_for_admin(conn, self._current_admin_student_id)
            current_classes = get_classes_for_student(conn, self._current_admin_student_id)
        finally:
            conn.close()

        self.admin_student_status_label.setText(
            f"{student.full_name} ({student.username}) - {'Active' if student.is_active else 'Deactivated'}"
        )
        self.admin_student_code_input.setText(student.student_code or "")
        self.admin_student_username_input.setText(student.username)
        self.admin_student_full_name_input.setText(student.full_name)
        self.admin_student_created_at_label.setText(format_timestamp(student.created_at))
        self.admin_student_classes_label.setText(
            ", ".join(c.class_name for c in current_classes) or "Unassigned"
        )
        self.admin_student_toggle_active_button.setText("Deactivate" if student.is_active else "Activate")

    def handle_save_admin_student_details(self) -> None:
        if self._current_admin_student_id is None:
            return

        username = self.admin_student_username_input.text()
        full_name = self.admin_student_full_name_input.text()
        student_code = self.admin_student_code_input.text()

        conn = get_connection()
        try:
            try:
                update_student_details(conn, self._current_admin_student_id, username, full_name, student_code)
            except ValueError as exc:
                show_error(self, "Save Details Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_student_detail_page()
        self.refresh_admin_students_table()
        show_success(self, "Save Details", "Student details updated successfully.")

    def handle_admin_change_student_class(self) -> None:
        if self._current_admin_student_id is None:
            return

        conn = get_connection()
        try:
            classes = list_all_classes_with_teacher_info(conn)
        finally:
            conn.close()

        options = [("Unassigned", None)]
        options += [(f"{c.class_name} ({c.teacher_name or 'Unassigned'})", c.class_id) for c in classes]
        new_class_id = prompt_select(
            self,
            "Change Class",
            "Select the class to move this student into, or Unassigned to remove them from any class.",
            options,
        )
        if new_class_id is CANCELLED:
            return

        conn = get_connection()
        try:
            try:
                admin_change_student_class(conn, self._current_admin_student_id, new_class_id)
            except ValueError as exc:
                show_error(self, "Change Class Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_student_detail_page()
        self.refresh_admin_students_table()
        show_success(self, "Change Class", "Student's class updated successfully.")

    def handle_reset_admin_student_password(self) -> None:
        if self._current_admin_student_id is None:
            return

        new_password = prompt_input(
            self,
            "Reset Password",
            "Enter a new password for this student.",
            is_password=True,
        )
        if new_password is None:
            return

        conn = get_connection()
        try:
            try:
                reset_student_password(conn, self._current_admin_student_id, new_password)
            except ValueError as exc:
                show_error(self, "Reset Password Failed", str(exc))
                return
        finally:
            conn.close()

        show_success(self, "Reset Password", "Password reset successfully.")

    def handle_view_admin_student_password(self) -> None:
        if self._current_admin_student_id is None:
            return

        conn = get_connection()
        try:
            student = get_student_for_admin(conn, self._current_admin_student_id)
            password_display = get_student_password_display(conn, self._current_admin_student_id)
        finally:
            conn.close()

        is_available = password_display != STUDENT_PASSWORD_NOT_AVAILABLE_MESSAGE
        show_password_reveal(
            self,
            "Student Password",
            f"{student.full_name} ({student.username})",
            password_display,
            is_available,
        )

    def handle_toggle_admin_student_active_status(self) -> None:
        if self._current_admin_student_id is None:
            return

        conn = get_connection()
        try:
            student = get_student_for_admin(conn, self._current_admin_student_id)
        finally:
            conn.close()

        new_status = not student.is_active
        action_label = "Activate" if new_status else "Deactivate"
        confirmed = prompt_confirm(
            self,
            f"{action_label} Student",
            f"{action_label} '{student.full_name}' ({student.username})?",
            confirm_text=action_label,
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                set_student_active_status(conn, self._current_admin_student_id, new_status)
            except ValueError as exc:
                show_error(self, f"{action_label} Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_student_detail_page()
        self.refresh_admin_students_table()
        show_success(self, action_label, f"Student {'activated' if new_status else 'deactivated'} successfully.")

    def handle_approve_student_transfer_request(self, request: StudentTransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Approve Request Failed", "No logged-in admin was found.")
            return

        confirmed = prompt_confirm(
            self,
            "Approve Transfer Request",
            f"Move {request.student_full_name} ({request.student_code or request.student_username}) "
            f"from '{request.source_class_name}' to '{request.target_class_name}'?",
            confirm_text="Approve",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                approve_student_transfer_request(conn, request.request_id, self._user)
            except ValueError as exc:
                show_error(self, "Approve Request Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_admin_students_table()
        self.refresh_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        show_success(self, "Approve Request", "Student transfer request approved successfully.")

    def handle_reject_student_transfer_request(self, request: StudentTransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Reject Request Failed", "No logged-in admin was found.")
            return

        reason = prompt_input(
            self,
            "Reject Transfer Request",
            f"Optional reason for rejecting the request to move "
            f"{request.student_full_name} to '{request.target_class_name}' (leave blank if none).",
        )
        if reason is None:
            return

        conn = get_connection()
        try:
            try:
                reject_student_transfer_request(conn, request.request_id, self._user, reason)
            except ValueError as exc:
                show_error(self, "Reject Request Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        show_success(self, "Reject Request", "Student transfer request rejected.")

    def handle_logout(self) -> None:
        from app.ui.login_window import LoginWindow

        self._login_window = LoginWindow()
        self._login_window.show()
        self.close()
