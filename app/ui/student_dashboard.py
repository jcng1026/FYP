"""Student dashboard: overview, revision material visibility, and external
revision uploads for the Student role.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
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
from app.models.revision_attempt_model import StudentAttemptRow
from app.models.revision_material_model import StudentMaterialRow
from app.models.student_progress_model import (
    ACTION_SUBMIT_ATTEMPT,
    ACTION_VIEW_ATTEMPT,
    ACTION_VIEW_MATERIAL,
    ACTION_VIEW_RESULT,
    StudentProgressItem,
)
from app.models.marking_result_model import STATUS_COMPLETED as MARKING_STATUS_COMPLETED
from app.models.student_external_revision_model import (
    PAPER_TYPE_KERTAS_1,
    PAPER_TYPE_KERTAS_2,
    StudentExternalRevisionRow,
)
from app.models.user_model import User
from app.services.class_student_service import list_classes_for_student
from app.services.kertas1_marking_service import get_latest_marking_job, list_marking_question_results
from app.services.marking_review_service import get_review_for_student, list_review_items
from app.services.kertas2_feedback_review_service import (
    get_kertas2_review_for_student,
    list_kertas2_review_items,
)
from app.services.result_summary_service import (
    get_result_detail_for_student,
    list_student_finalized_results,
)
from app.services.result_export_service import (
    export_student_result_detail_csv,
    export_student_results_summary_csv,
)
from app.models.result_summary_model import RESULT_TYPE_KERTAS1, RESULT_TYPE_KERTAS2, ResultSummaryRow
from app.services.student_progress_service import get_student_progress_summary
from app.services.revision_attempt_service import list_attempts_for_student, submit_revision_attempt
from app.services.revision_material_service import list_materials_for_student
from app.services.student_external_revision_service import (
    count_external_revisions_for_student,
    count_external_revisions_for_student_by_paper_type,
    create_student_external_revision,
    list_external_revisions_for_student,
)
from app.ui.components import (
    AppShell,
    StatCard,
    apply_card_shadow,
    apply_fixed_16_9_window,
    create_page,
    paint_status_item,
)
from app.ui.dialogs import show_detail, show_error, show_success
from app.utils.datetime_utils import format_timestamp
from app.utils.file_storage import get_safe_display_path

ATTEMPT_TABLE_COLUMNS = [
    "attempt_id",
    "material_title",
    "class_name",
    "attempt_no",
    "status",
    "submitted_at",
    "action",
]

ATTEMPT_TABLE_HEADERS = [
    "ID",
    "Material",
    "Class",
    "Attempt",
    "Status",
    "Submitted",
    "Action",
]

RESULT_SUMMARY_TABLE_COLUMNS = [
    "result_type",
    "material_title",
    "paper_type",
    "final_score",
    "max_score",
    "finalized_at",
    "action",
]

RESULT_SUMMARY_TABLE_HEADERS = [
    "Result Type",
    "Material",
    "Paper",
    "Final Score",
    "Max Score",
    "Finalized",
    "Action",
]

RESULT_SUMMARY_COLUMN_WIDTHS = {
    "result_type": 130,
    "paper_type": 90,
    "final_score": 90,
    "max_score": 90,
    "finalized_at": 150,
    "action": 240,
}

_RESULT_TYPE_LABELS = {
    RESULT_TYPE_KERTAS1: "Kertas 1 Review",
    RESULT_TYPE_KERTAS2: "Kertas 2 Review",
}

PROGRESS_TABLE_COLUMNS = [
    "item_type",
    "material_title",
    "paper_type",
    "display_status",
    "submitted_at_or_finalized_at",
    "action",
]

PROGRESS_TABLE_HEADERS = [
    "Type",
    "Material",
    "Paper",
    "Status",
    "Date",
    "Action",
]

PROGRESS_COLUMN_WIDTHS = {
    "item_type": 90,
    "paper_type": 90,
    "display_status": 170,
    "submitted_at_or_finalized_at": 150,
    "action": 140,
}

ATTEMPT_COLUMN_WIDTHS = {
    "attempt_id": 50,
    "class_name": 110,
    "attempt_no": 90,
    "status": 130,
    "submitted_at": 150,
    "action": 400,
}

MATERIAL_TABLE_COLUMNS = [
    "material_id",
    "title",
    "paper_type",
    "class_name",
    "created_at",
    "action",
]

MATERIAL_TABLE_HEADERS = [
    "ID",
    "Title",
    "Paper Type",
    "Class",
    "Created At",
    "Action",
]

EXTERNAL_REVISION_TABLE_COLUMNS = [
    "external_revision_id",
    "title",
    "paper_type",
    "class_name",
    "status",
    "created_at",
    "action",
]

EXTERNAL_REVISION_TABLE_HEADERS = [
    "ID",
    "Title",
    "Paper",
    "Class",
    "Status",
    "Created",
    "Action",
]

EXTERNAL_REVISION_COLUMN_WIDTHS = {
    "external_revision_id": 50,
    "paper_type": 90,
    "class_name": 110,
    "status": 130,
    "created_at": 150,
    "action": 300,
}


class StudentDashboard(QWidget):
    def __init__(self, user: Optional[User] = None) -> None:
        super().__init__()
        self.setWindowTitle("MarkAssist — Student")
        apply_fixed_16_9_window(self)

        self._student_id: Optional[int] = user.user_id if user else None

        self.shell = AppShell(
            brand_text="MarkAssist",
            nav_items=["Dashboard", "Revision Materials", "External Revision", "My Attempts", "Results"],
            header_title="Student Dashboard",
            header_subtitle=(
                f"Signed in as {user.username}." if user else "Sign in to see your classes and results."
            ),
            user_full_name=user.full_name if user else "Student",
            user_role_label="Student",
            on_logout=self.handle_logout,
            on_page_shown=self._handle_page_shown,
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)

        self._new_external_question_paper_path = ""
        self._new_external_marking_scheme_path = ""
        self._new_external_completed_answer_path = ""
        self._new_attempt_completed_answer_path = ""
        self._submit_attempt_material_row: Optional[StudentMaterialRow] = None

        self.shell.add_page("Dashboard", self._build_dashboard_page())
        self.shell.add_page("Revision Materials", self._build_revision_materials_page())
        self.shell.add_page("External Revision", self._build_external_revision_page())
        self.shell.add_page("Upload External Revision", self._build_upload_external_revision_page())
        self.shell.add_page("My Attempts", self._build_my_attempts_page())
        self.shell.add_page("Submit Attempt", self._build_submit_attempt_page())
        self.shell.add_page("Results", self._build_results_page())
        self.shell.show_page("Dashboard")

        self.refresh_my_classes_count()
        self.refresh_materials_table()
        self.refresh_external_revisions_table()
        self.refresh_attempts_table()
        self.refresh_results_table()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _handle_page_shown(self, name: str) -> None:
        """Refresh live marking state when the student navigates, so a
        teacher finalising in parallel is reflected without a re-login."""
        if name == "My Attempts":
            self.refresh_attempts_table()
        elif name == "Results":
            self.refresh_results_table()
            self.refresh_marked_attempts_table()
        elif name == "External Revision":
            self.refresh_external_revisions_table()

    def _build_dashboard_page(self) -> QWidget:
        page, layout = create_page()

        # Cards double as navigation: click to jump to the page behind the number.
        self.my_classes_card = StatCard("My Classes", "0")
        self.available_materials_card = StatCard(
            "Available Materials", "0", on_click=lambda: self.shell.show_page("Revision Materials"))
        self.submitted_attempts_card = StatCard(
            "Submitted Attempts", "0", on_click=lambda: self.shell.show_page("My Attempts"))
        self.finalized_results_card = StatCard(
            "Finalized Results", "0", on_click=lambda: self.shell.show_page("Results"))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.my_classes_card)
        cards_row.addWidget(self.available_materials_card)
        cards_row.addWidget(self.submitted_attempts_card)
        cards_row.addWidget(self.finalized_results_card)
        layout.addLayout(cards_row)

        progress_heading = QLabel("Recent Activity / My Progress")
        progress_heading.setObjectName("SectionHeading")
        layout.addWidget(progress_heading)

        self.progress_table = QTableWidget(0, len(PROGRESS_TABLE_COLUMNS))
        self.progress_table.setHorizontalHeaderLabels(PROGRESS_TABLE_HEADERS)
        self.progress_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.progress_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.progress_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        progress_header = self.progress_table.horizontalHeader()
        progress_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        progress_header.setSectionResizeMode(
            PROGRESS_TABLE_COLUMNS.index("material_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in PROGRESS_COLUMN_WIDTHS.items():
            self.progress_table.setColumnWidth(PROGRESS_TABLE_COLUMNS.index(key), width)
        self.progress_table.verticalHeader().setVisible(False)
        self.progress_table.verticalHeader().setDefaultSectionSize(44)
        self.progress_table.setAlternatingRowColors(True)
        self.progress_table.setMinimumHeight(240)
        apply_card_shadow(self.progress_table)
        layout.addWidget(self.progress_table)

        layout.addStretch()

        return page

    def _build_progress_action_cell(self, item: StudentProgressItem) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)

        action_button = QPushButton(item.action_label)
        action_button.setObjectName("RowActionButton")
        action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        action_button.clicked.connect(lambda _checked=False, i=item: self.handle_open_progress_item(i))
        cell_layout.addWidget(action_button)
        return cell

    def handle_open_progress_item(self, item: StudentProgressItem) -> None:
        if item.action_label in (ACTION_VIEW_MATERIAL, ACTION_SUBMIT_ATTEMPT):
            self.shell.show_page("Revision Materials")
        elif item.action_label == ACTION_VIEW_ATTEMPT:
            self.shell.show_page("My Attempts")
        elif item.action_label == ACTION_VIEW_RESULT:
            self.shell.show_page("Results")

    def _build_revision_materials_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Revision Materials")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("View revision papers assigned to your class.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        self.materials_table = QTableWidget(0, len(MATERIAL_TABLE_COLUMNS))
        self.materials_table.setHorizontalHeaderLabels(MATERIAL_TABLE_HEADERS)
        self.materials_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.materials_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.materials_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.materials_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.materials_table.horizontalHeader().setSectionResizeMode(
            len(MATERIAL_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.materials_table.setColumnWidth(len(MATERIAL_TABLE_COLUMNS) - 1, 280)
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.verticalHeader().setDefaultSectionSize(44)
        self.materials_table.setAlternatingRowColors(True)
        self.materials_table.setMinimumHeight(260)
        apply_card_shadow(self.materials_table)
        layout.addWidget(self.materials_table)

        layout.addStretch()
        return page

    def _build_material_action_cell(self, row: StudentMaterialRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View Details")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_material_details(r))
        cell_layout.addWidget(view_button)

        submit_button = QPushButton("Submit Attempt")
        submit_button.setObjectName("RowActionButton")
        submit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        submit_button.clicked.connect(lambda _checked=False, r=row: self.handle_open_submit_attempt_page(r))
        cell_layout.addWidget(submit_button)

        return cell

    # --- External Revision page ---------------------------------------------

    def _build_external_revision_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("External Revision")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Upload your own revision paper, answer key, and completed answer.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        upload_button = QPushButton("+ Upload External Revision")
        upload_button.setObjectName("PrimaryButton")
        upload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        upload_button.clicked.connect(self.handle_open_upload_external_revision_page)
        header_row.addWidget(upload_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.total_external_card = StatCard("Total External Uploads", "0")
        self.kertas1_external_card = StatCard("Kertas 1 Uploads", "0")
        self.kertas2_external_card = StatCard("Kertas 2 Uploads", "0")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.total_external_card)
        cards_row.addWidget(self.kertas1_external_card)
        cards_row.addWidget(self.kertas2_external_card)
        layout.addLayout(cards_row)

        self.external_revisions_table = QTableWidget(0, len(EXTERNAL_REVISION_TABLE_COLUMNS))
        self.external_revisions_table.setHorizontalHeaderLabels(EXTERNAL_REVISION_TABLE_HEADERS)
        self.external_revisions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.external_revisions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.external_revisions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.external_revisions_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(
            EXTERNAL_REVISION_TABLE_COLUMNS.index("title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in EXTERNAL_REVISION_COLUMN_WIDTHS.items():
            self.external_revisions_table.setColumnWidth(EXTERNAL_REVISION_TABLE_COLUMNS.index(key), width)
        header.setMinimumSectionSize(80)
        self.external_revisions_table.verticalHeader().setVisible(False)
        self.external_revisions_table.verticalHeader().setDefaultSectionSize(44)
        self.external_revisions_table.setAlternatingRowColors(True)
        self.external_revisions_table.setMinimumHeight(260)
        apply_card_shadow(self.external_revisions_table)
        layout.addWidget(self.external_revisions_table)

        layout.addStretch()
        return page

    def _build_external_revision_action_cell(self, row: StudentExternalRevisionRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(6)

        view_button = QPushButton("View Details")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_external_revision_details(r))
        cell_layout.addWidget(view_button)

        download_button = QPushButton("Download Marked PDF")
        download_button.setObjectName("RowActionButton")
        download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        download_button.setEnabled(self._marked_pdf_available("external", row.external_revision_id))
        download_button.setToolTip("Available once your teacher finalises the marking.")
        download_button.clicked.connect(
            lambda _checked=False, r=row: self.handle_download_marked_pdf(
                "external", r.external_revision_id, r.title))
        cell_layout.addWidget(download_button)

        return cell

    # --- Upload External Revision page (hidden until selected) --------------

    def _build_upload_external_revision_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(10)

        title = QLabel("Upload External Revision")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Upload Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        self.new_external_title_input = QLineEdit()
        self.new_external_title_input.setPlaceholderText("e.g. External Kertas 1 Practice")

        self.new_external_class_dropdown = QComboBox()

        self.new_external_paper_type_dropdown = QComboBox()
        self.new_external_paper_type_dropdown.addItem("-- Select Paper Type --", None)
        self.new_external_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_1)
        self.new_external_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_2, PAPER_TYPE_KERTAS_2)

        form_layout.addWidget(self._field_label("Title"))
        form_layout.addWidget(self.new_external_title_input)
        form_layout.addWidget(self._field_label("Class"))
        form_layout.addWidget(self.new_external_class_dropdown)
        form_layout.addWidget(self._field_label("Paper Type"))
        form_layout.addWidget(self.new_external_paper_type_dropdown)

        note = QLabel(
            "Upload only your completed answer paper. Your teacher supplies the question "
            "paper and answer scheme when they mark it.")
        note.setObjectName("StatusLabel")
        note.setWordWrap(True)
        form_layout.addWidget(note)

        form_layout.addWidget(self._field_label("Completed Answer Paper"))

        # Drag-and-drop zone: dropping a PDF here selects it, same as the
        # Choose File button below.
        self.external_drop_zone = _PdfDropZone(
            "Drag your completed answer PDF here", self._set_external_completed_answer_path)
        form_layout.addWidget(self.external_drop_zone)

        completed_answer_row = QHBoxLayout()
        choose_completed_answer_button = QPushButton("Choose File...")
        choose_completed_answer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_completed_answer_button.clicked.connect(self.handle_choose_external_completed_answer)
        self.external_completed_answer_status_label = QLabel("No file selected")
        self.external_completed_answer_status_label.setObjectName("StatusLabel")
        completed_answer_row.addWidget(choose_completed_answer_button)
        completed_answer_row.addWidget(self.external_completed_answer_status_label)
        completed_answer_row.addStretch()
        form_layout.addLayout(completed_answer_row)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        upload_button = QPushButton("Create / Upload")
        upload_button.setObjectName("PrimaryButton")
        upload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        upload_button.clicked.connect(self.handle_create_external_revision)

        cancel_button = QPushButton("Cancel / Back to External Revision")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_upload_external_revision)

        buttons_row.addWidget(upload_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- My Attempts page -----------------------------------------------------

    def _build_my_attempts_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("My Attempts")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("Your submission history for assigned revision materials.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        self.attempts_table = QTableWidget(0, len(ATTEMPT_TABLE_COLUMNS))
        self.attempts_table.setHorizontalHeaderLabels(ATTEMPT_TABLE_HEADERS)
        self.attempts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attempts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attempts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        attempts_header = self.attempts_table.horizontalHeader()
        attempts_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        attempts_header.setSectionResizeMode(
            ATTEMPT_TABLE_COLUMNS.index("material_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in ATTEMPT_COLUMN_WIDTHS.items():
            self.attempts_table.setColumnWidth(ATTEMPT_TABLE_COLUMNS.index(key), width)
        attempts_header.setMinimumSectionSize(80)
        self.attempts_table.verticalHeader().setVisible(False)
        self.attempts_table.verticalHeader().setDefaultSectionSize(44)
        self.attempts_table.setAlternatingRowColors(True)
        self.attempts_table.setMinimumHeight(260)
        apply_card_shadow(self.attempts_table)
        layout.addWidget(self.attempts_table)

        layout.addStretch()
        return page

    def _build_results_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Results")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Your finalized Kertas 1 and Kertas 2 results.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        export_summary_button = QPushButton("Export Summary CSV")
        export_summary_button.setObjectName("PrimaryButton")
        export_summary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_summary_button.clicked.connect(self.handle_export_student_results_summary_csv)
        header_row.addWidget(export_summary_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        # Grade hero ("results that read kindly"): the latest finalised score
        # as a ring + a plain-language line, before any table.
        self.grade_hero = QFrame()
        self.grade_hero.setObjectName("GradeHero")
        self.grade_hero.setStyleSheet(
            "QFrame#GradeHero { background-color: #474747; border-radius: 14px;"
            " border-top: 1px solid rgba(255,255,255,18); }")
        apply_card_shadow(self.grade_hero, blur_radius=30, y_offset=8, alpha=60)
        grade_layout = QHBoxLayout(self.grade_hero)
        grade_layout.setContentsMargins(22, 16, 22, 16)
        grade_layout.setSpacing(16)
        self.grade_ring = _GradeRing()
        grade_layout.addWidget(self.grade_ring)
        grade_text = QVBoxLayout()
        grade_text.setSpacing(2)
        self.grade_hero_title = QLabel("")
        self.grade_hero_title.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #EDEDED; background: transparent;")
        self.grade_hero_subtitle = QLabel("")
        self.grade_hero_subtitle.setObjectName("StatusLabel")
        grade_text.addWidget(self.grade_hero_title)
        grade_text.addWidget(self.grade_hero_subtitle)
        grade_layout.addLayout(grade_text)
        grade_layout.addStretch()
        self.grade_hero.setVisible(False)
        layout.addWidget(self.grade_hero)

        # Marked attempts: the same layout as the My Attempts tab, but only
        # submissions whose teacher marking is finalised (result ready).
        marked_heading = QLabel("Marked Attempts")
        marked_heading.setObjectName("SectionHeading")
        layout.addWidget(marked_heading)

        marked_subtitle = QLabel("Attempts your teacher has finished marking - view or download the marked paper.")
        marked_subtitle.setObjectName("StatusLabel")
        layout.addWidget(marked_subtitle)

        self.marked_attempts_table = QTableWidget(0, len(ATTEMPT_TABLE_COLUMNS))
        self.marked_attempts_table.setHorizontalHeaderLabels(ATTEMPT_TABLE_HEADERS)
        self.marked_attempts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marked_attempts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marked_attempts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        marked_header = self.marked_attempts_table.horizontalHeader()
        marked_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        marked_header.setSectionResizeMode(
            ATTEMPT_TABLE_COLUMNS.index("material_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in ATTEMPT_COLUMN_WIDTHS.items():
            self.marked_attempts_table.setColumnWidth(ATTEMPT_TABLE_COLUMNS.index(key), width)
        marked_header.setMinimumSectionSize(80)
        self.marked_attempts_table.verticalHeader().setVisible(False)
        self.marked_attempts_table.verticalHeader().setDefaultSectionSize(44)
        self.marked_attempts_table.setAlternatingRowColors(True)
        self.marked_attempts_table.setMinimumHeight(180)
        apply_card_shadow(self.marked_attempts_table)
        layout.addWidget(self.marked_attempts_table)

        self.no_marked_attempts_label = QLabel("No marked attempts yet - they appear here once your teacher finalises the marking.")
        self.no_marked_attempts_label.setObjectName("StatusLabel")
        self.no_marked_attempts_label.setVisible(False)
        layout.addWidget(self.no_marked_attempts_label)

        finalized_heading = QLabel("Finalized Results")
        finalized_heading.setObjectName("SectionHeading")
        layout.addWidget(finalized_heading)

        self.results_table = QTableWidget(0, len(RESULT_SUMMARY_TABLE_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(RESULT_SUMMARY_TABLE_HEADERS)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_header = self.results_table.horizontalHeader()
        results_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        results_header.setSectionResizeMode(
            RESULT_SUMMARY_TABLE_COLUMNS.index("material_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in RESULT_SUMMARY_COLUMN_WIDTHS.items():
            self.results_table.setColumnWidth(RESULT_SUMMARY_TABLE_COLUMNS.index(key), width)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(44)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setMinimumHeight(260)
        apply_card_shadow(self.results_table)
        layout.addWidget(self.results_table)

        self.no_results_label = QLabel("No finalized results yet.")
        self.no_results_label.setObjectName("StatusLabel")
        self.no_results_label.setVisible(False)
        layout.addWidget(self.no_results_label)

        layout.addStretch()
        return page

    def _build_result_action_cell(self, row: ResultSummaryRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)

        view_button = QPushButton("View Result")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_student_result(r))
        cell_layout.addWidget(view_button)

        export_detail_button = QPushButton("Export Detail CSV")
        export_detail_button.setObjectName("RowActionButton")
        export_detail_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_detail_button.clicked.connect(lambda _checked=False, r=row: self.handle_export_student_result_detail_csv(r))
        cell_layout.addWidget(export_detail_button)

        return cell

    def refresh_results_table(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            results = list_student_finalized_results(conn, self._student_id)
        finally:
            conn.close()

        self.no_results_label.setVisible(len(results) == 0)
        self._refresh_grade_hero(results)

        self.results_table.clearContents()
        self.results_table.setRowCount(len(results))
        for row_index, row in enumerate(results):
            values = [
                _RESULT_TYPE_LABELS.get(row.result_type, row.result_type),
                row.material_title,
                row.paper_type,
                row.final_score,
                row.max_score,
                format_timestamp(row.finalized_at),
            ]
            for col_index, value in enumerate(values):
                self.results_table.removeCellWidget(row_index, col_index)
                self.results_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.results_table.item(
                row_index, RESULT_SUMMARY_TABLE_COLUMNS.index("material_title")
            ).setToolTip(row.material_title)
            self.results_table.setCellWidget(
                row_index, len(values), self._build_result_action_cell(row)
            )
        self.refresh_student_progress_dashboard()

    def _refresh_grade_hero(self, results) -> None:
        """Lead the Results page with the newest finalised score as a ring."""
        if not hasattr(self, "grade_hero"):
            return
        newest = None
        for row in results:
            try:
                score, maximum = float(row.final_score), float(row.max_score)
            except (TypeError, ValueError):
                continue
            if maximum > 0:
                newest = (row, score, maximum)
                break
        if newest is None:
            self.grade_hero.setVisible(False)
            return
        row, score, maximum = newest
        percent = round(score / maximum * 100)
        self.grade_ring.set_percent(percent)
        self.grade_hero_title.setText(
            f"Latest result: {score:g} / {maximum:g}  ({percent}%)")
        self.grade_hero_subtitle.setText(
            f"{row.material_title} - {row.paper_type}, finalised {format_timestamp(row.finalized_at)}")
        self.grade_hero.setVisible(True)

    def handle_view_student_result(self, row: ResultSummaryRow) -> None:
        conn = get_connection()
        try:
            try:
                review, detail_rows = get_result_detail_for_student(
                    conn, row.result_type, row.review_id, self._student_id
                )
            except ValueError as exc:
                show_error(self, "View Result Failed", str(exc))
                return
        finally:
            conn.close()

        lines = [
            f"Final Score: {review.final_total_score} / {review.max_score}",
            f"Overall Comment: {review.teacher_overall_comment or '-'}",
            "",
        ]
        if row.result_type == RESULT_TYPE_KERTAS1:
            for detail_row in detail_rows:
                lines.append(
                    f"Question {detail_row.question_no}: {detail_row.final_score}/{detail_row.max_mark}\n"
                    f"  Your Answer: {detail_row.extracted_answer or '(none)'}\n"
                    f"  Correct Answer: {detail_row.correct_answer}\n"
                    f"  Teacher Comment: {detail_row.teacher_comment or '-'}\n"
                    f"  Explanation: {detail_row.explanation or '-'}\n"
                )
        else:
            for detail_row in detail_rows:
                lines.append(
                    f"{detail_row.criterion_name}: {detail_row.final_score}/{detail_row.max_mark}\n"
                    f"  Your Answer: {detail_row.student_answer or '(none)'}\n"
                    f"  Feedback: {detail_row.final_feedback or '-'}\n"
                    f"  Teacher Comment: {detail_row.teacher_comment or '-'}\n"
                )
        lines.append("This result has been reviewed by your teacher.")
        show_detail(self, f"{_RESULT_TYPE_LABELS.get(row.result_type, row.result_type)}", "\n".join(lines))

    def handle_export_student_results_summary_csv(self) -> None:
        conn = get_connection()
        try:
            try:
                path = export_student_results_summary_csv(conn, self._student_id)
            except ValueError as exc:
                show_error(self, "Export Summary CSV Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Export Summary CSV", f"CSV exported successfully: {path}")

    def handle_export_student_result_detail_csv(self, row: ResultSummaryRow) -> None:
        conn = get_connection()
        try:
            try:
                path = export_student_result_detail_csv(conn, row.result_type, row.review_id, self._student_id)
            except ValueError as exc:
                show_error(self, "Export Detail CSV Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Export Detail CSV", f"CSV exported successfully: {path}")

    def _marked_status_label(self, kind: str, item_id: int, base_status: str) -> str:
        """Overlay the marking-bridge state onto the stored status so the
        student sees real progress: submitted -> being marked -> result ready."""
        from app.services import attempt_marking_bridge_service as bridge
        conn = get_connection()
        try:
            state = bridge.get_marking_state(conn, kind, item_id)
        finally:
            conn.close()
        if state["state"] == bridge.STATE_FINAL:
            return "Marked - result ready"
        if state["state"] == bridge.STATE_MARKING:
            return "Being marked"
        return base_status

    def _marked_pdf_available(self, kind: str, item_id: int) -> bool:
        from app.services import attempt_marking_bridge_service as bridge
        conn = get_connection()
        try:
            return bridge.get_marking_state(conn, kind, item_id)["state"] == bridge.STATE_FINAL
        finally:
            conn.close()

    def handle_download_marked_pdf(self, kind: str, item_id: int, default_name: str) -> None:
        """Save a copy of the teacher's finalised marked PDF (the red-marked
        paper) wherever the student chooses."""
        from app.services import attempt_marking_bridge_service as bridge
        conn = get_connection()
        try:
            try:
                marked_pdf = bridge.get_student_marked_pdf(conn, self._student_id, kind, item_id)
            except ValueError as exc:
                show_error(self, "Download Failed", str(exc))
                return
        finally:
            conn.close()
        if not marked_pdf:
            show_error(self, "Download Failed",
                       "This submission has no finalised marked result yet.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Marked PDF", f"{default_name}_marked.pdf", "PDF Files (*.pdf)")
        if not destination:
            return
        import shutil
        shutil.copy2(marked_pdf, destination)
        show_success(self, "Download Marked PDF", f"Saved to: {destination}")

    def _build_attempt_action_cell(self, row: StudentAttemptRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(6)

        view_button = QPushButton("View Details")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_attempt_details(r))
        cell_layout.addWidget(view_button)

        view_marking_button = QPushButton("View Marking")
        view_marking_button.setObjectName("RowActionButton")
        view_marking_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_marking_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_marking_attempt(r))
        cell_layout.addWidget(view_marking_button)

        download_button = QPushButton("Download Marked PDF")
        download_button.setObjectName("RowActionButton")
        download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        download_button.setEnabled(self._marked_pdf_available("attempt", row.attempt_id))
        download_button.setToolTip("Available once your teacher finalises the marking.")
        download_button.clicked.connect(
            lambda _checked=False, r=row: self.handle_download_marked_pdf(
                "attempt", r.attempt_id, f"{r.material_title}_attempt{r.attempt_no}"))
        cell_layout.addWidget(download_button)

        return cell

    # --- Submit Attempt page (hidden until selected) -------------------------

    def _build_submit_attempt_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(10)

        title = QLabel("Submit Attempt")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Attempt Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        self.submit_attempt_material_title_input = QLineEdit()
        self.submit_attempt_material_title_input.setReadOnly(True)

        self.submit_attempt_paper_type_input = QLineEdit()
        self.submit_attempt_paper_type_input.setReadOnly(True)

        self.submit_attempt_class_input = QLineEdit()
        self.submit_attempt_class_input.setReadOnly(True)

        form_layout.addWidget(self._field_label("Material Title"))
        form_layout.addWidget(self.submit_attempt_material_title_input)
        form_layout.addWidget(self._field_label("Paper Type"))
        form_layout.addWidget(self.submit_attempt_paper_type_input)
        form_layout.addWidget(self._field_label("Class"))
        form_layout.addWidget(self.submit_attempt_class_input)

        form_layout.addWidget(self._field_label("Completed Answer Paper"))
        completed_answer_row = QHBoxLayout()
        choose_completed_answer_button = QPushButton("Choose File...")
        choose_completed_answer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_completed_answer_button.clicked.connect(self.handle_choose_attempt_completed_answer)
        self.attempt_completed_answer_status_label = QLabel("No file selected")
        self.attempt_completed_answer_status_label.setObjectName("StatusLabel")
        completed_answer_row.addWidget(choose_completed_answer_button)
        completed_answer_row.addWidget(self.attempt_completed_answer_status_label)
        completed_answer_row.addStretch()
        form_layout.addLayout(completed_answer_row)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        submit_button = QPushButton("Submit Attempt")
        submit_button.setObjectName("PrimaryButton")
        submit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        submit_button.clicked.connect(self.handle_submit_attempt)

        cancel_button = QPushButton("Cancel / Back")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_submit_attempt)

        buttons_row.addWidget(submit_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- Data refresh -----------------------------------------------------

    def refresh_student_progress_dashboard(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            summary = get_student_progress_summary(conn, self._student_id)
        finally:
            conn.close()

        self.my_classes_card.set_value(str(summary.class_count))
        self.available_materials_card.set_value(str(summary.available_materials))
        self.submitted_attempts_card.set_value(str(summary.submitted_attempts))
        self.finalized_results_card.set_value(str(summary.finalized_results))

        self.progress_table.clearContents()
        self.progress_table.setRowCount(len(summary.recent_items))
        for row_index, item in enumerate(summary.recent_items):
            values = [
                item.item_type,
                item.material_title,
                item.paper_type,
                item.display_status,
                format_timestamp(item.submitted_at_or_finalized_at),
            ]
            for col_index, value in enumerate(values):
                self.progress_table.removeCellWidget(row_index, col_index)
                table_item = QTableWidgetItem(str(value))
                if PROGRESS_TABLE_COLUMNS[col_index] == "material_title":
                    table_item.setToolTip(item.material_title)
                self.progress_table.setItem(row_index, col_index, table_item)
            self.progress_table.setCellWidget(
                row_index, len(values), self._build_progress_action_cell(item)
            )

    def refresh_my_classes_count(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            classes = list_classes_for_student(conn, self._student_id)
        finally:
            conn.close()

        self.my_classes_card.set_value(str(len(classes)))
        self.refresh_student_progress_dashboard()

    def refresh_materials_table(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            materials = list_materials_for_student(conn, self._student_id)
        finally:
            conn.close()

        self.materials_table.clearContents()
        self.materials_table.setRowCount(len(materials))
        for row_index, row in enumerate(materials):
            values = [
                row.material_id,
                row.title,
                row.paper_type,
                row.class_name,
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.materials_table.removeCellWidget(row_index, col_index)
                self.materials_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.materials_table.setCellWidget(
                row_index, len(values), self._build_material_action_cell(row)
            )
        self.refresh_student_progress_dashboard()

    def refresh_external_revisions_table(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            revisions = list_external_revisions_for_student(conn, self._student_id)
            total_count = count_external_revisions_for_student(conn, self._student_id)
            kertas1_count = count_external_revisions_for_student_by_paper_type(
                conn, self._student_id, PAPER_TYPE_KERTAS_1
            )
            kertas2_count = count_external_revisions_for_student_by_paper_type(
                conn, self._student_id, PAPER_TYPE_KERTAS_2
            )
        finally:
            conn.close()

        self.external_revisions_table.clearContents()
        self.external_revisions_table.setRowCount(len(revisions))
        for row_index, row in enumerate(revisions):
            values = [
                row.external_revision_id,
                row.title,
                row.paper_type,
                row.class_name,
                self._marked_status_label("external", row.external_revision_id, row.status),
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.external_revisions_table.removeCellWidget(row_index, col_index)
                item = QTableWidgetItem(str(value))
                self.external_revisions_table.setItem(row_index, col_index, item)
            paint_status_item(
                self.external_revisions_table.item(
                    row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("status")),
                str(values[EXTERNAL_REVISION_TABLE_COLUMNS.index("status")]))
            self.external_revisions_table.item(
                row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("title")
            ).setToolTip(row.title)
            self.external_revisions_table.item(
                row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("class_name")
            ).setToolTip(row.class_name)
            self.external_revisions_table.setCellWidget(
                row_index, len(values), self._build_external_revision_action_cell(row)
            )

        self.total_external_card.set_value(str(total_count))
        self.kertas1_external_card.set_value(str(kertas1_count))
        self.kertas2_external_card.set_value(str(kertas2_count))

    def refresh_external_revision_class_dropdown(self) -> None:
        conn = get_connection()
        try:
            my_classes = list_classes_for_student(conn, self._student_id)
        finally:
            conn.close()

        self.new_external_class_dropdown.clear()
        self.new_external_class_dropdown.addItem("-- Select Class --", None)
        for class_ in my_classes:
            self.new_external_class_dropdown.addItem(class_.class_name, class_.class_id)
        self.new_external_class_dropdown.setCurrentIndex(0)

    def refresh_attempts_table(self) -> None:
        if self._student_id is None:
            return

        conn = get_connection()
        try:
            attempts = list_attempts_for_student(conn, self._student_id)
        finally:
            conn.close()

        self.attempts_table.clearContents()
        self.attempts_table.setRowCount(len(attempts))
        for row_index, row in enumerate(attempts):
            values = [
                row.attempt_id,
                row.material_title,
                row.class_name,
                row.attempt_no,
                self._marked_status_label("attempt", row.attempt_id, row.status),
                format_timestamp(row.submitted_at),
            ]
            for col_index, value in enumerate(values):
                self.attempts_table.removeCellWidget(row_index, col_index)
                self.attempts_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.attempts_table.item(row_index, ATTEMPT_TABLE_COLUMNS.index("status")),
                str(values[ATTEMPT_TABLE_COLUMNS.index("status")]))
            self.attempts_table.item(
                row_index, ATTEMPT_TABLE_COLUMNS.index("material_title")
            ).setToolTip(row.material_title)
            self.attempts_table.setCellWidget(
                row_index, len(values), self._build_attempt_action_cell(row)
            )
        self.refresh_student_progress_dashboard()
        self.refresh_marked_attempts_table()

    def refresh_marked_attempts_table(self) -> None:
        """The Results page's 'Marked Attempts' list: identical formatting to
        My Attempts but only submissions whose marking is finalised."""
        if self._student_id is None or not hasattr(self, "marked_attempts_table"):
            return
        from app.services import attempt_marking_bridge_service as bridge

        conn = get_connection()
        try:
            attempts = [
                row for row in list_attempts_for_student(conn, self._student_id)
                if bridge.get_marking_state(conn, bridge.KIND_ATTEMPT, row.attempt_id)["state"]
                == bridge.STATE_FINAL
            ]
        finally:
            conn.close()

        self.marked_attempts_table.clearContents()
        self.marked_attempts_table.setRowCount(len(attempts))
        for row_index, row in enumerate(attempts):
            values = [
                row.attempt_id,
                row.material_title,
                row.class_name,
                row.attempt_no,
                self._marked_status_label("attempt", row.attempt_id, row.status),
                format_timestamp(row.submitted_at),
            ]
            for col_index, value in enumerate(values):
                self.marked_attempts_table.removeCellWidget(row_index, col_index)
                self.marked_attempts_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.marked_attempts_table.item(row_index, ATTEMPT_TABLE_COLUMNS.index("status")),
                str(values[ATTEMPT_TABLE_COLUMNS.index("status")]))
            self.marked_attempts_table.item(
                row_index, ATTEMPT_TABLE_COLUMNS.index("material_title")
            ).setToolTip(row.material_title)
            self.marked_attempts_table.setCellWidget(
                row_index, len(values), self._build_attempt_action_cell(row)
            )
        self.no_marked_attempts_label.setVisible(len(attempts) == 0)
        self.marked_attempts_table.setVisible(len(attempts) > 0)

    # --- Handlers: Revision Materials ---------------------------------------

    def handle_view_marking_attempt(self, row: StudentAttemptRow) -> None:
        if row.paper_type == PAPER_TYPE_KERTAS_2:
            self._show_kertas2_marking_result(row)
            return

        conn = get_connection()
        try:
            review = get_review_for_student(conn, row.attempt_id, self._student_id)
            marking_job = get_latest_marking_job(conn, row.attempt_id)

            if review is not None:
                items = list_review_items(conn, review.review_id)
                results_by_id = (
                    {
                        result.marking_result_id: result
                        for result in list_marking_question_results(conn, marking_job.marking_job_id)
                    }
                    if marking_job is not None
                    else {}
                )
            else:
                items = []
                results_by_id = {}
                if marking_job is None or marking_job.status != MARKING_STATUS_COMPLETED:
                    show_error(self, "View Marking", "Marking results are not available for this attempt yet.")
                    return
                results = list_marking_question_results(conn, marking_job.marking_job_id)
        finally:
            conn.close()

        # Prefer showing the teacher-finalized review when one is available.
        if review is not None:
            lines = [
                f"Final Score: {review.final_total_score} / {review.max_score}",
                f"Overall Comment: {review.teacher_overall_comment or '-'}",
                "",
            ]
            for item in items:
                result = results_by_id.get(item.marking_result_id)
                verdict = "Correct" if item.final_is_correct else "Wrong"
                lines.append(
                    f"Question {item.question_no}: {verdict} ({item.final_score_awarded}/{item.max_mark})\n"
                    f"  Your Answer: {(result.extracted_answer if result else None) or '(none)'}\n"
                    f"  Correct Answer: {result.correct_answer if result else '-'}\n"
                    f"  Teacher Comment: {item.teacher_comment or '-'}\n"
                    f"  Explanation: {result.explanation if result else '-'}\n"
                )
            lines.append("This result has been reviewed by your teacher.")
            show_detail(self, "Marking Result", "\n".join(lines))
            return

        lines = [
            f"Total Score: {marking_job.total_score} / {marking_job.max_score}",
            "",
        ]
        for result in results:
            if result.needs_review:
                verdict = "Needs Review"
            elif result.is_correct:
                verdict = "Correct"
            else:
                verdict = "Wrong"
            lines.append(
                f"Question {result.question_no}: {verdict} ({result.score_awarded}/{result.max_mark})\n"
                f"  Your Answer: {result.extracted_answer or '(none)'}\n"
                f"  Correct Answer: {result.correct_answer}\n"
                f"  Explanation: {result.explanation or '-'}\n"
            )
        lines.append("Your teacher can review this marking and adjust scores or add feedback "
                     "before the result is finalised.")
        show_detail(self, "Marking Result", "\n".join(lines))

    def _show_kertas2_marking_result(self, row: StudentAttemptRow) -> None:
        conn = get_connection()
        try:
            review = get_kertas2_review_for_student(conn, row.attempt_id, self._student_id)
            items = list_kertas2_review_items(conn, review.kertas2_review_id) if review is not None else []
        finally:
            conn.close()

        if review is None:
            show_error(self, "View Marking", "Teacher review is not finalized yet.")
            return

        lines = [
            f"Final Score: {review.final_total_score} / {review.max_score}",
            f"Overall Comment: {review.teacher_overall_comment or '-'}",
            "",
        ]
        for item in items:
            lines.append(
                f"{item.criterion_name}: {item.final_score}/{item.max_mark}\n"
                f"  Your Answer: {item.student_answer or '(none)'}\n"
                f"  Feedback: {item.final_feedback or '-'}\n"
                f"  Teacher Comment: {item.teacher_comment or '-'}\n"
            )
        lines.append("This result has been reviewed by your teacher.")
        show_detail(self, "Marking Result", "\n".join(lines))

    def handle_view_material_details(self, row: StudentMaterialRow) -> None:
        message = (
            f"Paper Type: {row.paper_type}\n"
            f"Class: {row.class_name}\n"
            f"Created: {format_timestamp(row.created_at)}\n\n"
            f"Question Paper: {get_safe_display_path(row.question_paper_path)}\n\n"
            f"Marking Scheme: {get_safe_display_path(row.marking_scheme_path)}\n\n"
            "Use the Submit Attempt button on this material's row to hand in your "
            "completed answer paper."
        )
        show_detail(self, row.title, message)

    def handle_open_submit_attempt_page(self, row: StudentMaterialRow) -> None:
        self._submit_attempt_material_row = row
        self.submit_attempt_material_title_input.setText(row.title)
        self.submit_attempt_paper_type_input.setText(row.paper_type)
        self.submit_attempt_class_input.setText(row.class_name)
        self._new_attempt_completed_answer_path = ""
        self.attempt_completed_answer_status_label.setText("No file selected")
        self.shell.show_page("Submit Attempt")

    def handle_choose_attempt_completed_answer(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Completed Answer Paper", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_attempt_completed_answer_path = path
        self.attempt_completed_answer_status_label.setText(Path(path).name)

    def handle_submit_attempt(self) -> None:
        row = self._submit_attempt_material_row
        if row is None:
            show_error(self, "Submit Attempt Failed", "No revision material was selected.")
            return

        conn = get_connection()
        try:
            submit_revision_attempt(
                conn,
                self._student_id,
                row.material_id,
                row.class_id,
                self._new_attempt_completed_answer_path,
            )
        except ValueError as exc:
            show_error(self, "Submit Attempt Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_attempts_table()
        show_success(self, "Submit Attempt", "Attempt submitted successfully.")
        self.shell.show_page("My Attempts")

    def handle_cancel_submit_attempt(self) -> None:
        self.shell.show_page("Revision Materials")

    def handle_view_attempt_details(self, row: StudentAttemptRow) -> None:
        message = (
            f"Paper Type: {row.paper_type}\n"
            f"Class: {row.class_name}\n"
            f"Attempt No: {row.attempt_no}\n"
            f"Status: {row.status}\n"
            f"Submitted: {format_timestamp(row.submitted_at)}\n\n"
            f"Completed Answer:\n{row.completed_answer_path}\n\n"
            "Your teacher marks submitted attempts from their Attempts / Workflow page; "
            "the result appears under Results once finalised."
        )
        show_detail(self, row.material_title, message)

    # --- Handlers: External Revision -----------------------------------------

    def handle_open_upload_external_revision_page(self) -> None:
        conn = get_connection()
        try:
            my_classes = list_classes_for_student(conn, self._student_id)
        finally:
            conn.close()

        if not my_classes:
            show_error(
                self,
                "Upload External Revision Failed",
                "You do not belong to any classes yet. Join a class before uploading external revisions.",
            )
            return

        self.new_external_title_input.clear()
        self.new_external_paper_type_dropdown.setCurrentIndex(0)
        self._new_external_completed_answer_path = ""
        self.external_completed_answer_status_label.setText("No file selected")
        self.refresh_external_revision_class_dropdown()
        self.shell.show_page("Upload External Revision")

    def handle_choose_external_completed_answer(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Completed Answer Paper", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._set_external_completed_answer_path(path)

    def _set_external_completed_answer_path(self, path: str) -> None:
        """Shared by the Choose File button and the drag-and-drop zone."""
        self._new_external_completed_answer_path = path
        self.external_completed_answer_status_label.setText(Path(path).name)
        if hasattr(self, "external_drop_zone"):
            self.external_drop_zone.set_selected(Path(path).name)

    def handle_create_external_revision(self) -> None:
        title = self.new_external_title_input.text()
        class_id = self.new_external_class_dropdown.currentData()
        paper_type = self.new_external_paper_type_dropdown.currentData()

        if class_id is None:
            show_error(self, "Upload External Revision Failed", "Please select one of your classes.")
            return
        if paper_type is None:
            show_error(self, "Upload External Revision Failed", "Please select a paper type.")
            return

        conn = get_connection()
        try:
            create_student_external_revision(
                conn,
                self._student_id,
                class_id,
                title,
                paper_type,
                self._new_external_completed_answer_path,
            )
        except ValueError as exc:
            show_error(self, "Upload External Revision Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_external_revisions_table()
        show_success(self, "Upload External Revision", "External revision uploaded successfully.")
        self.shell.show_page("External Revision")

    def handle_cancel_upload_external_revision(self) -> None:
        self.shell.show_page("External Revision")

    def handle_view_external_revision_details(self, row: StudentExternalRevisionRow) -> None:
        message = (
            "Source: Student External Revision\n"
            f"Paper Type: {row.paper_type}\n"
            f"Class: {row.class_name}\n"
            f"Status: {row.status}\n"
            f"Created: {format_timestamp(row.created_at)}\n\n"
            f"Question Paper: {get_safe_display_path(row.question_paper_path)}\n\n"
            f"Marking Scheme: {get_safe_display_path(row.marking_scheme_path)}\n\n"
            f"Completed Answer: {get_safe_display_path(row.completed_answer_path)}\n\n"
            "Your teacher marks submitted attempts from their Attempts / Workflow page; "
            "the result appears under Results once finalised."
        )
        show_detail(self, row.title, message)

    def handle_logout(self) -> None:
        from app.ui.login_window import LoginWindow

        self._login_window = LoginWindow()
        self._login_window.show()
        self.close()


class _GradeRing(QWidget):
    """Small conic-style grade ring: green arc for the achieved fraction on a
    charcoal track, percentage in the middle."""

    def __init__(self, diameter: int = 62) -> None:
        super().__init__()
        self._diameter = diameter
        self._percent = 0
        self.setFixedSize(diameter, diameter)

    def set_percent(self, percent: int) -> None:
        self._percent = max(0, min(100, int(percent)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        thickness = 7
        margin = thickness / 2 + 1
        rect = QRectF(margin, margin, self._diameter - 2 * margin, self._diameter - 2 * margin)

        track = QPen(QColor("#545454"), thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        arc_color = QColor("#34D399") if self._percent >= 50 else QColor("#F59E0B")
        arc = QPen(arc_color, thickness)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, 90 * 16, -int(360 * (self._percent / 100) * 16))

        painter.setPen(QColor("#EDEDED"))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self._percent}%")
        painter.end()


class _PdfDropZone(QLabel):
    """Drop target for the upload form: dropping a PDF/image file selects it
    (same effect as Choose File). Purely an input affordance - validation
    still happens in the upload service."""

    _ACCEPTED_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg")

    def __init__(self, prompt: str, on_file_dropped) -> None:
        super().__init__(prompt)
        self._prompt = prompt
        self._on_file_dropped = on_file_dropped
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(84)
        self._set_style(active=False)

    def _set_style(self, active: bool) -> None:
        border = "#14B8A6" if active else "#545454"
        self.setStyleSheet(
            f"border: 2px dashed {border}; border-radius: 10px;"
            "color: #A3A3A3; font-size: 12px; background: transparent; padding: 12px;")

    def set_selected(self, file_name: str) -> None:
        self.setText(f"Selected: {file_name}\n(drop another file to replace it)")
        self._set_style(active=False)

    def _dropped_path(self, event) -> str:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if path.lower().endswith(self._ACCEPTED_SUFFIXES):
                return path
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dropped_path(event):
            self._set_style(active=True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_style(active=False)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._dropped_path(event)
        self._set_style(active=False)
        if path:
            self._on_file_dropped(path)
            event.acceptProposedAction()
