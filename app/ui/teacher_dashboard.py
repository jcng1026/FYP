"""Teacher dashboard: overview, class visibility, transfer requests, and
student/class-membership management for the Teacher role.
"""

import json
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.database.db import get_connection
from app.models.class_model import ClassWithTeacher
from app.models.class_student_model import TeacherStudentRow, get_classes_for_student
from app.models.class_transfer_request_model import TransferRequestWithDetails
from app.models.student_transfer_request_model import StudentTransferRequestWithDetails
from app.models.revision_material_model import (
    PAPER_TYPE_BOTH,
    PAPER_TYPE_KERTAS_1,
    PAPER_TYPE_KERTAS_2,
    TeacherMaterialRow,
)
from app.models.revision_attempt_model import TeacherAttemptRow
from app.models.teacher_attention_model import TeacherAttentionItem
from app.models.marking_setup_model import (
    DEFAULT_KERTAS_2_RUBRIC_CRITERIA,
    KERTAS_1_QUESTION_TYPES,
    KERTAS_2_QUESTION_TYPES,
    MarkingQuestionRow,
    MarkingSetup,
    QUESTION_TYPE_RUBRIC_CRITERION,
)
from app.models.preprocessing_model import (
    SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER,
    SOURCE_TYPE_REVISION_ATTEMPT_ANSWER,
    STATUS_COMPLETED,
)
from app.models.ocr_model import STATUS_COMPLETED as OCR_STATUS_COMPLETED, OCRJob
from app.models.extraction_model import (
    ExtractionJob,
    STATUS_COMPLETED as EXTRACTION_STATUS_COMPLETED,
)
from app.models.answer_extraction_model import (
    AnswerExtractionJob,
    STATUS_COMPLETED as ANSWER_EXTRACTION_STATUS_COMPLETED,
)
from app.models.marking_result_model import (
    MarkingJob,
    STATUS_COMPLETED as MARKING_STATUS_COMPLETED,
)
from app.models.marking_review_model import (
    MarkingReview,
    MarkingReviewItem,
    STATUS_FINALIZED as REVIEW_STATUS_FINALIZED,
)
from app.models.kertas2_ai_feedback_model import (
    Kertas2AIFeedbackJob,
    STATUS_COMPLETED as KERTAS2_FEEDBACK_STATUS_COMPLETED,
)
from app.models.kertas2_feedback_review_model import (
    Kertas2FeedbackReview,
    Kertas2FeedbackReviewItem,
    STATUS_FINALIZED as KERTAS2_REVIEW_STATUS_FINALIZED,
)
from app.models.student_external_revision_model import TeacherExternalRevisionRow
from app.models.main_marking_model import (
    PROCESSING_STATUS_FINALIZED as MAIN_MARKING_PROCESSING_STATUS_FINALIZED,
    PROCESSING_STATUS_REVIEWED as MAIN_MARKING_PROCESSING_STATUS_REVIEWED,
    REVIEW_STATUS_REVIEWED,
    RUN_STATUS_FAILED,
    STATUS_ANSWER_EXTRACTED,
    STATUS_MARKED,
    STATUS_OCR_COMPLETED,
    STATUS_PREPROCESSED,
    MainMarkingAnswerFile,
    MainMarkingFinalResult,
    MainMarkingMarkedAnswer,
    MainMarkingSession,
    MainMarkingSessionRow,
)
from app.models.template_model import (
    AnswerTemplate,
    REGION_TYPE_IGNORE,
    SHAPE_TYPE_POLYGON,
    SHAPE_TYPE_RECTANGLE,
    TeacherTemplateRow,
    TemplateRegion,
    get_allowed_region_types,
    get_template_by_id,
)
from app.models.template_region_group_model import TemplateRegionGroup
from app.models.user_model import User, get_user_by_id
from app.services.class_service import (
    DEFAULT_SUBJECT,
    join_unassigned_class,
    list_all_classes_with_teacher_info,
    list_teacher_classes,
)
from app.services.class_student_service import (
    count_distinct_students_for_teacher,
    get_classes_for_student_owned_by_teacher,
    get_students_in_class_for_teacher,
    list_students_for_teacher,
    remove_student_from_class,
)
from app.services.class_transfer_request_service import (
    approve_transfer_request,
    count_pending_requests_for_teacher,
    create_transfer_request,
    list_my_pending_requests,
    list_pending_requests_for_teacher,
    reject_transfer_request,
)
from app.services.student_transfer_request_service import (
    ALREADY_IN_CLASS,
    DIRECT_ASSIGNED,
    MOVED_WITHIN_OWN_CLASSES,
    TRANSFER_REQUEST_CREATED,
    add_existing_student_to_class,
    approve_student_transfer_request,
    count_pending_student_transfer_requests_for_teacher,
    list_add_existing_student_candidates,
    list_decided_student_transfer_requests_for_teacher,
    list_pending_student_transfer_requests_for_teacher,
    reject_student_transfer_request,
)
from app.services.revision_material_service import (
    count_materials_for_teacher,
    count_materials_for_teacher_by_paper_type,
    create_revision_material,
    list_materials_for_teacher,
)
from app.services.preprocessing_service import get_latest_preprocessing_job, preprocess_document
from app.services.ocr_service import get_latest_ocr_job, run_ocr_for_preprocessing_job
from app.services.extraction_service import (
    get_latest_extraction_job,
    list_extracted_region_results,
    run_extraction_for_attempt,
)
from app.services.answer_extraction_service import (
    get_latest_answer_extraction_job,
    list_extracted_attempt_answers,
    run_answer_extraction_for_attempt,
)
from app.services.kertas1_marking_service import (
    get_latest_marking_job,
    list_marking_question_results,
    run_kertas1_marking_for_attempt,
)
from app.services.marking_review_service import (
    finalize_review,
    get_latest_review,
    get_review,
    list_review_items,
    save_review_comment,
    start_or_get_review,
    update_review_item,
)
from app.services.kertas2_ai_feedback_service import (
    get_feedback_job_audit_for_teacher,
    get_latest_feedback_job,
    list_feedback_items,
    run_kertas2_ai_feedback_for_attempt,
)
from app.services.kertas2_feedback_review_service import (
    finalize_kertas2_review,
    get_kertas2_review,
    get_latest_kertas2_review,
    list_kertas2_review_items,
    save_kertas2_review_comment,
    start_or_get_kertas2_review,
    update_kertas2_review_item,
)
from app.services.result_summary_service import (
    get_result_detail_for_teacher,
    list_teacher_finalized_results,
)
from app.services.attempt_workflow_status_service import (
    get_attempt_workflow_status,
    list_teacher_attempt_workflow_statuses,
)
from app.services.attempt_readiness_service import (
    get_attempt_readiness_report,
    list_teacher_attempt_readiness_reports,
)
from app.services.guided_attempt_action_service import (
    ACTION_EXTRACT_ANSWERS,
    ACTION_EXTRACT_REGIONS,
    ACTION_GENERATE_KERTAS2_FEEDBACK,
    ACTION_MARK_KERTAS1,
    ACTION_PREPROCESS,
    ACTION_REVIEW_KERTAS1,
    ACTION_REVIEW_KERTAS2,
    ACTION_RUN_OCR,
    ACTION_VIEW_ANSWERS,
    ACTION_VIEW_DETAILS,
    ACTION_VIEW_EXTRACTION,
    ACTION_VIEW_ISSUES,
    ACTION_VIEW_KERTAS1_REVIEW,
    ACTION_VIEW_KERTAS2_FEEDBACK,
    ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT,
    ACTION_VIEW_KERTAS2_REVIEW,
    ACTION_VIEW_MARKING,
    ACTION_VIEW_OCR,
    ACTION_VIEW_WORKFLOW,
    get_guided_actions_for_attempt,
)
from app.services.teacher_attention_service import get_teacher_attention_summary
from app.services.result_export_service import (
    export_teacher_result_detail_csv,
    export_teacher_results_summary_csv,
)
from app.services.main_marking_export_service import (
    export_main_marking_final_result_detail_csv,
    export_main_marking_final_results_summary_csv,
)
from app.services.teacher_marking_settings_service import (
    get_teacher_marking_settings,
    reset_teacher_marking_settings_to_defaults,
    update_teacher_marking_settings,
)
from app.services.local_ai_settings_service import (
    get_or_create_local_ai_settings,
    update_local_ai_settings,
    validate_local_ai_settings,
)
from app.services.ai_model_registry_service import (
    get_active_ai_model_version,
    get_supported_ai_model_specs,
    list_ai_training_jobs,
)
from app.models.ai_model_registry_model import MODEL_KEY_ANSWER_REGION_DETECTION, MODEL_KEY_K2_SHORT_ANSWER_SCORING
from app.services.k2_training_dataset_service import (
    export_k2_training_dataset,
    list_k2_training_datasets,
)
from app.services.k2_cross_encoder_training_service import has_k2_training_dataset
from app.ui.k2_training_worker import K2TrainingWorker
from app.services.k2_cross_encoder_evaluation_service import (
    has_active_k2_model_version,
    is_k2_evaluation_job,
    list_k2_evaluation_jobs,
    list_k2_training_only_jobs,
)
from app.ui.k2_evaluation_worker import K2EvaluationWorker
from app.services.region_detection_dataset_service import (
    export_region_detection_dataset,
    has_exportable_subject_profiles,
    list_region_detection_datasets,
)
from app.models.result_summary_model import (
    RESULT_TYPE_KERTAS1,
    RESULT_TYPE_KERTAS2,
    ResultSummaryRow,
)
from app.services.main_marking_service import (
    MainMarkingFinalResultRow,
    ReviewableMainMarkingFile,
    add_answer_file_to_session,
    assign_template_to_marking_session,
    create_marking_session,
    delete_main_marking_final_result,
    delete_marking_session,
    finalize_main_marking_answer_file,
    get_answer_file_display_name,
    get_main_marking_final_result_detail,
    get_main_marking_final_result_summary,
    get_marked_answers_for_review,
    get_marking_session,
    get_marking_session_extraction_readiness,
    get_marking_session_template_summary,
    list_answer_files_for_session,
    list_compatible_templates_for_session,
    list_extracted_answers_for_answer_file,
    list_main_marking_final_results_for_teacher,
    list_marked_answers_for_answer_file,
    list_marking_sessions_for_teacher,
    list_reviewable_main_marking_files,
    mark_answer_file_reviewed,
    remove_answer_file_from_session,
    remove_template_from_marking_session,
    review_marked_answer,
    run_answer_extraction_for_session,
    run_kertas1_marking_for_session,
    run_ocr_for_session,
    run_preprocessing_for_session,
    update_answer_file_student_info,
    update_marking_session_details,
)
from app.services.marking_setup_service import (
    DEFAULT_QUESTION_MARK,
    DEFAULT_SPELLING_DEDUCTION,
    add_marking_question,
    delete_marking_question,
    get_marking_setup_for_material,
    list_marking_questions,
    save_marking_setup,
    update_marking_question,
)
from app.services.revision_attempt_service import list_attempts_for_teacher
from app.services.student_external_revision_service import list_external_revisions_for_teacher
from app.services.student_service import (
    create_student,
    create_student_in_class,
    find_student_by_identifier,
    get_student_password_display,
    reset_student_password,
)
from app.services.template_service import (
    add_polygon_template_region,
    add_template_region,
    count_templates_for_teacher,
    count_templates_for_teacher_by_paper_type,
    create_template,
    get_non_ignore_regions_for_template,
    list_template_regions,
    list_templates_for_teacher,
    parse_polygon_points,
    remove_template_region,
    update_polygon_template_region,
    update_template_region,
)
from app.services.template_region_group_service import (
    MIN_GROUP_MEMBERS,
    create_region_group,
    delete_region_group,
    list_group_members,
    list_region_groups,
    move_group_member,
    update_region_group,
)
from app.ui.components import (
    AppShell,
    CircularProgressWidget,
    CollapsibleSection,
    StatCard,
    apply_card_shadow,
    apply_fixed_16_9_window,
    attach_table_filter,
    create_page,
    paint_status_item,
)
from app.ui.dialogs import (
    CANCELLED,
    prompt_answer_key_entry,
    prompt_confirm,
    prompt_edit_region,
    prompt_input,
    prompt_kertas2_review_item,
    prompt_main_marking_review,
    prompt_marking_question,
    OverlayEditorDialog as _OverlayEditorDialog,  # noqa: F401 (kept for parity)
    RegionOverrideDialog,
    RegionProposalReviewDialog,
    SeparateMappingDialog,
    SeparateParserReviewDialog,
    prompt_overlay_editor,
    prompt_teacher_review,
    prompt_three_way_choice,
    prompt_region_group_form,
    prompt_review_item,
    prompt_select,
    prompt_select_from_table,
    prompt_student_info,
    show_detail,
    show_error,
    show_info,
    show_success,
    show_warning,
)
from app.ui import styles
from app.ui.template_canvas import TemplateCanvas, get_page_count, render_page_image
from app.ui.overlay_canvas import OverlayCanvas
from app.ui.subject_profile_worker import (
    MarkAnswerFileSubprocessWorker,
    StudentPdfProcessingSubprocessWorker,
    StudentPdfProcessingWorker,
)
from app.utils.datetime_utils import format_timestamp
from app.utils.file_storage import get_safe_display_path
from app.models.subject_profile_model import (
    ALL_SUBJECT_PROFILE_REGION_TYPES,
    IGNORED_REGION_TYPES,
    MARKED_ANSWER_STATUS_TEACHER_SCORED,
    REGION_TYPE_ANSWER_BOX,
    SOURCE_ANSWER_SCHEME,
    SOURCE_QUESTION_PAPER,
    STATUS_FAILED as SUBJECT_PROFILE_STATUS_FAILED,
    STATUS_PROCESSING as SUBJECT_PROFILE_STATUS_PROCESSING,
    STATUS_READY as SUBJECT_PROFILE_STATUS_READY,
    TARGET_KIND_GROUP as SUBJECT_PROFILE_TARGET_KIND_GROUP,
    region_type_friendly_label,
)
from app.services.subject_profile_service import (
    StudentPdfResult,
    add_region as add_subject_profile_region_svc,
    apply_parsed_answer_scheme_entries,
    create_region_group as create_subject_profile_region_group_svc,
    create_subject_profile,
    delete_overlay as delete_subject_profile_overlay,
    delete_subject_profile,
    edit_region as edit_subject_profile_region_svc,
    effective_overlay_kind_text,
    export_all_student_results,
    export_student_result,
    get_document_page_image_paths,
    get_subject_profile,
    list_answer_key_entries,
    list_missing_answer_key_targets,
    list_overlays as list_subject_profile_overlays,
    list_region_groups as list_subject_profile_region_groups,
    list_regions as list_subject_profile_regions,
    list_student_results_for_profile,
    list_subject_profiles_for_teacher,
    move_overlay as move_subject_profile_overlay,
    move_region as move_subject_profile_region_svc,
    process_subject_profile_documents,
    remove_region as remove_subject_profile_region_svc,
    edit_region_group as edit_subject_profile_region_group_svc,
    remove_region_group as remove_subject_profile_region_group_svc,
    resize_overlay as resize_subject_profile_overlay,
    rotate_overlay as rotate_subject_profile_overlay,
    list_subject_profile_extraction_targets as list_subject_profile_extraction_targets_ui,
    ensure_full_page_render_for_answer_file,
    preview_answer_scheme_answer_list,
    preview_answer_scheme_formatted_text,
    extract_answer_key_from_answer_scheme,
    extract_question_number_from_label,
    save_answer_key_entry,
    set_teacher_score_for_marked_answer,
    summarize_document_processing,
    delete_student_marking,
)
from app.models.subject_profile_model import (
    get_extracted_answers_for_answer_file as get_extracted_answers_for_answer_file_ui,
    get_marked_answers_for_answer_file as get_marked_answers_for_answer_file_ui,
)
from app.models.main_marking_model import (
    get_preprocessed_pages_for_answer_file,
)
from app.services.subject_profile_export_service import default_export_filename, export_subject_profile
from app.services.subject_profile_import_service import DuplicateProfileNameError, import_subject_profile
import app.services.subject_profile_review_service as review_service
import app.services.separate_answer_paper_service as separate_paper_service
import app.models.separate_answer_paper_model as separate_model
import app.models.subject_profile_model as subject_profile_model

CLASS_TABLE_COLUMNS = [
    "class_id",
    "class_name",
    "subject",
    "teacher_in_charge",
    "status",
    "created_at",
    "action",
]

CLASS_TABLE_HEADERS = [
    "Class ID",
    "Class Name",
    "Subject",
    "Teacher In Charge",
    "Status",
    "Created At",
    "Action",
]

REQUEST_TABLE_COLUMNS = [
    "request_id",
    "class_name",
    "requesting_teacher",
    "request_reason",
    "created_at",
    "actions",
]

REQUEST_TABLE_HEADERS = [
    "Request ID",
    "Class Name",
    "Requesting Teacher",
    "Reason",
    "Created At",
    "Actions",
]

STUDENT_TRANSFER_REQUEST_TABLE_COLUMNS = [
    "request_id",
    "student_code",
    "student_name",
    "source_class",
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

ATTENTION_TABLE_COLUMNS = [
    "student_name",
    "class_name",
    "material_title",
    "paper_type",
    "priority",
    "recommended_action",
    "issue_count",
    "action",
]

ATTENTION_TABLE_HEADERS = [
    "Student",
    "Class",
    "Material",
    "Paper",
    "Priority",
    "Recommended Action",
    "Issues",
    "Action",
]

ATTENTION_COLUMN_WIDTHS = {
    "student_name": 150,
    "class_name": 110,
    "material_title": 260,
    "paper_type": 90,
    "priority": 90,
    "recommended_action": 220,
    "issue_count": 80,
    "action": 150,
}

STUDENT_TABLE_COLUMNS = [
    "student_code",
    "username",
    "full_name",
    "classes",
    "created_at",
    "actions",
]

STUDENT_TABLE_HEADERS = [
    "Student Code",
    "Username",
    "Full Name",
    "Class",
    "Created At",
    "Actions",
]

MATERIAL_TABLE_COLUMNS = [
    "material_id",
    "title",
    "paper_type",
    "assigned_classes",
    "created_at",
    "actions",
]

MATERIAL_TABLE_HEADERS = [
    "ID",
    "Title",
    "Paper Type",
    "Assigned Classes",
    "Created At",
    "Actions",
]

EXTERNAL_REVISION_TABLE_COLUMNS = [
    "external_revision_id",
    "username",
    "student_name",
    "class_name",
    "title",
    "paper_type",
    "status",
    "created_at",
    "action",
]

EXTERNAL_REVISION_TABLE_HEADERS = [
    "ID",
    "Student ID",
    "Student Name",
    "Class",
    "Title",
    "Paper",
    "Status",
    "Created",
    "Action",
]

EXTERNAL_REVISION_COLUMN_WIDTHS = {
    "external_revision_id": 50,
    "username": 110,
    "student_name": 140,
    "class_name": 90,
    "title": 220,
    "paper_type": 90,
    "status": 100,
    "created_at": 150,
    "action": 420,
}

ATTEMPT_TABLE_COLUMNS = [
    "attempt_id",
    "username",
    "student_name",
    "class_name",
    "material_title",
    "paper_type",
    "attempt_no",
    "status",
    "submitted_at",
    "action",
]

ATTEMPT_TABLE_HEADERS = [
    "ID",
    "Student ID",
    "Student Name",
    "Class",
    "Material",
    "Paper",
    "Attempt",
    "Status",
    "Submitted",
    "Action",
]

ATTEMPT_COLUMN_WIDTHS = {
    "attempt_id": 50,
    "username": 110,
    "student_name": 140,
    "class_name": 90,
    "material_title": 200,
    "paper_type": 90,
    "attempt_no": 90,
    "status": 100,
    "submitted_at": 150,
    "action": 190,
}

TEMPLATE_TABLE_COLUMNS = [
    "template_id",
    "title",
    "paper_type",
    "region_count",
    "created_at",
    "action",
]

TEMPLATE_TABLE_HEADERS = [
    "ID",
    "Title",
    "Paper",
    "Regions",
    "Created",
    "Action",
]

TEMPLATE_COLUMN_WIDTHS = {
    "template_id": 50,
    "paper_type": 90,
    "region_count": 90,
    "created_at": 150,
    "action": 150,
}

TEMPLATE_REGION_TABLE_COLUMNS = ["select", "label", "page_number", "shape_type", "action"]
TEMPLATE_REGION_TABLE_HEADERS = ["", "Label", "Page", "Shape", "Action"]

TEMPLATE_REGION_GROUP_TABLE_COLUMNS = ["label", "region_type", "members", "action"]
TEMPLATE_REGION_GROUP_TABLE_HEADERS = ["Group Label", "Type", "Members", "Action"]

MARKING_SESSION_TABLE_COLUMNS = ["title", "paper_type", "status", "answer_file_count", "created_at", "action"]
MARKING_SESSION_TABLE_HEADERS = ["Session Title", "Paper Type", "Status", "Answer Files", "Created At", "Actions"]

# Stage 11V: Subject Profile workflow tables.
SUBJECT_PROFILE_TABLE_COLUMNS = ["profile_name", "status", "updated_at", "action"]
SUBJECT_PROFILE_TABLE_HEADERS = ["Profile Name", "Status", "Last Updated", "Actions"]

STUDENT_RESULT_TABLE_COLUMNS = ["student_name", "status", "score", "action"]
STUDENT_RESULT_TABLE_HEADERS = ["Student Name", "Result Status", "Score / Percentage", "Download"]

SUBJECT_PROFILE_REGION_TABLE_COLUMNS = ["select", "label", "type", "page", "action"]
SUBJECT_PROFILE_REGION_TABLE_HEADERS = ["", "Label", "Type", "Page", "Actions"]

SUBJECT_PROFILE_REGION_GROUP_TABLE_COLUMNS = ["label", "type", "members", "action"]
SUBJECT_PROFILE_REGION_GROUP_TABLE_HEADERS = ["Group", "Type", "Members", "Actions"]

SUBJECT_PROFILE_ANSWER_KEY_TABLE_COLUMNS = ["question_no", "target_label", "correct_answer", "max_mark", "action"]
SUBJECT_PROFILE_ANSWER_KEY_TABLE_HEADERS = ["Q#", "Target", "Correct Answer", "Max Mark", "Actions"]

MARKING_COMMENT_TABLE_COLUMNS = ["target_label", "student_answer", "correct_answer", "score",
                                 "ai_draft", "comment", "status", "review"]
MARKING_COMMENT_TABLE_HEADERS = ["Question", "Answer", "Expected", "Score", "AI Draft (suggestion)",
                                 "Comment", "Status", "Review"]

OVERLAY_TABLE_COLUMNS = ["paper", "label", "page", "status", "symbol", "x", "y", "visibility", "adjusted"]
OVERLAY_TABLE_HEADERS = ["Paper", "Part / Question", "Page", "Status", "Symbol", "X", "Y", "Visibility", "Adjusted"]

SAP_TARGET_TABLE_COLUMNS = ["paper", "target", "state", "mappings", "flags"]
SAP_TARGET_TABLE_HEADERS = ["Paper", "Target", "State", "Mappings", "Flags"]
SAP_MAPPING_TABLE_COLUMNS = ["order", "type", "page", "geometry", "text"]
SAP_MAPPING_TABLE_HEADERS = ["Order", "Type", "Page", "Geometry (x,y,w,h)", "Effective text"]

REGION_TABLE_COLUMNS = ["paper", "label", "page", "override", "original", "effective", "stale"]
REGION_TABLE_HEADERS = ["Paper", "Part / Question", "Page", "Override", "Original (x,y,w,h)", "Effective (x,y,w,h)", "Review"]


class OverlayOutputWorker(QThread):
    """Phase 2B: regenerate the reviewed marked PDF + comments off the UI
    thread. A finalised attempt re-publishes its FINAL outputs; any other
    attempt produces a teacher-only DRAFT preview (never published as final)."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id: int, profile_id: int, answer_file_id: int, is_finalised: bool) -> None:
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._answer_file_id = answer_file_id
        self._is_finalised = is_finalised

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        conn = get_connection()
        try:
            if self._is_finalised:
                payload = review_service.regenerate_reviewed_final_outputs(
                    conn, self._teacher_id, self._profile_id, self._answer_file_id)
                payload["is_final"] = True
            else:
                payload = review_service.generate_draft_preview_outputs(
                    conn, self._teacher_id, self._profile_id, self._answer_file_id)
                payload["is_final"] = False
            self.succeeded.emit(payload)
        except Exception as exc:  # surfaced to the teacher via failed signal
            self.failed.emit(str(exc))
        finally:
            conn.close()


class RegionOcrRerunWorker(QThread):
    """Phase 2C: re-run OCR for one attempt region override off the UI thread
    (real OCR is slow). Emits the OCR lineage (original vs rerun) on success."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id: int, profile_id: int, answer_file_id: int, label: str) -> None:
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._answer_file_id = answer_file_id
        self._label = label

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        conn = get_connection()
        try:
            review_service.rerun_ocr_for_region_override(
                conn, self._teacher_id, self._profile_id, self._answer_file_id, self._label)
            lineage = review_service.get_region_override_lineage(
                conn, self._teacher_id, self._profile_id, self._answer_file_id, self._label)
            self.succeeded.emit(lineage)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


class SeparatePaperOcrWorker(QThread):
    """Stage 12G-1B: run OCR for one Separate Answer Paper mapping off the UI
    thread. The service keeps the original and rerun OCR separate and leaves
    teacher-corrected text untouched; a failure changes nothing."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id: int, profile_id: int, answer_file_id: int, mapping_id: int) -> None:
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._answer_file_id = answer_file_id
        self._mapping_id = mapping_id

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.models import separate_answer_paper_model as sap
        conn = get_connection()
        try:
            separate_paper_service.run_mapping_ocr(
                conn, self._teacher_id, self._profile_id, self._answer_file_id,
                self._mapping_id, force_rerun=True)
            mapping = sap.get_mapping(conn, self._mapping_id)
            self.succeeded.emit({
                "original": mapping.original_ocr_text if mapping else None,
                "rerun": mapping.rerun_ocr_text if mapping else None,
                "corrected": mapping.corrected_text if mapping else None,
            })
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


def _image_dims_and_checksum(path):
    """(width, height, sha256) for a page image, or (0, 0, '') on failure."""
    import hashlib
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0, 0, ""
    checksum = hashlib.sha256(data).hexdigest()
    try:
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is not None:
            return int(image.shape[1]), int(image.shape[0]), checksum
    except Exception:
        pass
    return 0, 0, checksum


class SeparatePaperProposalWorker(QThread):
    """Stage 12G-4: run Core AI 2 region proposals for one separate-paper page
    off the UI thread. A no-model/failure/cancel result persists no proposals -
    manual mapping stays fully usable."""

    succeeded = Signal(int)
    failed = Signal(str)

    def __init__(self, teacher_id, profile_id, answer_file_id, sap_page_id,
                 page_image_path, page_width, page_height, page_checksum):
        super().__init__()
        self._args = (teacher_id, profile_id, answer_file_id, sap_page_id,
                      page_image_path, page_width, page_height, page_checksum)

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.services import ai_region_proposal_service as proposals
        conn = get_connection()
        try:
            records = proposals.run_separate_paper_proposals(conn, *self._args)
            self.succeeded.emit(len(records))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


class SubjectProfileProposalWorker(QThread):
    """Stage 12G-4: run Core AI 2 region proposals for one Subject Profile page
    off the UI thread. Manual/rule-based region drawing stays fully usable when
    no model is available or inference fails."""

    succeeded = Signal(int)
    failed = Signal(str)

    def __init__(self, teacher_id, profile_id, source, page_number, page_image_path):
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._source = source
        self._page_number = page_number
        self._page_image_path = page_image_path

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.services import ai_region_proposal_service as proposals
        width, height, checksum = _image_dims_and_checksum(self._page_image_path)
        conn = get_connection()
        try:
            records = proposals.run_subject_profile_proposals(
                conn, self._teacher_id, self._profile_id, self._source, self._page_number,
                self._page_image_path, width, height, checksum)
            self.succeeded.emit(len(records))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


class SubjectProfileAllPagesProposalWorker(QThread):
    """Run Core AI 2 region proposals for EVERY rendered page of the current
    Subject Profile source off the UI thread, reporting per-page progress.
    Like the single-page worker: a failure on one page persists nothing for
    that page and never blocks manual drawing."""

    progressed = Signal(str, int, int)  # message, current, total
    succeeded = Signal(int)             # total proposals persisted
    failed = Signal(str)

    def __init__(self, teacher_id, profile_id, source, page_paths):
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._source = source
        # [(page_number, rendered_page_path), ...] - only rendered pages
        self._page_paths = page_paths

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.services import ai_region_proposal_service as proposals
        total_pages = len(self._page_paths)
        persisted = 0
        conn = get_connection()
        try:
            for index, (page_number, path) in enumerate(self._page_paths, start=1):
                self.progressed.emit(f"Detecting regions on page {page_number}...",
                                     index - 1, total_pages)
                width, height, checksum = _image_dims_and_checksum(path)
                records = proposals.run_subject_profile_proposals(
                    conn, self._teacher_id, self._profile_id, self._source,
                    page_number, path, width, height, checksum)
                persisted += len(records)
                self.progressed.emit(f"Page {page_number} done.", index, total_pages)
            self.succeeded.emit(persisted)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


class CoreAI1DraftWorker(QThread):
    """Stage 12G-6: generate Core AI 1 Kertas 2 draft scores for one attempt
    off the UI thread. Drafts are suggestions only - this worker never writes a
    teacher score, feedback or review state, and manual marking stays fully
    usable when no model is available or inference fails."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id, profile_id, answer_file_id, marked_answer_id=None):
        super().__init__()
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._answer_file_id = answer_file_id
        self._marked_answer_id = marked_answer_id
        from app.services.ai_resilience_service import CancellationToken
        self.cancellation_token = CancellationToken()

    def request_cancel(self) -> None:
        """Stop between answers. Drafts already produced are kept."""
        self.cancellation_token.cancel()

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.services import ai_draft_scoring_service as drafting
        conn = get_connection()
        try:
            if self._marked_answer_id is None:
                drafting.generate_drafts_for_attempt(
                    conn, self._teacher_id, self._profile_id, self._answer_file_id,
                    cancellation_token=self.cancellation_token)
            else:
                drafting.generate_draft_for_answer(
                    conn, self._teacher_id, self._profile_id, self._answer_file_id,
                    self._marked_answer_id)
            self.succeeded.emit(drafting.summarize_attempt_drafts(conn, self._answer_file_id))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


class Kertas2FeedbackWorker(QThread):
    """Stage 12G-8: draft Kertas 2 natural-language feedback off the UI thread.
    A configured local runtime can block, so this never runs inline. The worker
    writes nothing - it returns draft wording for the teacher to accept, edit or
    discard, and it carries no score."""

    # Signal(object), NOT Signal(dict): the payload is keyed by marked_answer_id
    # (an int), and a queued cross-thread Signal(dict) marshals through
    # QVariantMap, which silently drops dicts with non-string keys - the slot
    # then receives {} and every feedback draft looks like "nothing produced".
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, teacher_id, answer_file_id, marked_answer_id=None):
        super().__init__()
        self._teacher_id = teacher_id
        self._answer_file_id = answer_file_id
        self._marked_answer_id = marked_answer_id
        from app.services.ai_resilience_service import CancellationToken
        self.cancellation_token = CancellationToken()

    def request_cancel(self) -> None:
        """Stop the local generation at its next checkpoint. A cancelled run
        falls back to the offline templates rather than losing feedback."""
        self.cancellation_token.cancel()

    def run(self) -> None:  # noqa: N802 - Qt override
        from app.database.db import get_connection
        from app.services import ai_feedback_generation_service as feedback
        conn = get_connection()
        try:
            token = self.cancellation_token
            if self._marked_answer_id is None:
                drafts = feedback.generate_feedback_drafts_for_attempt(
                    conn, self._teacher_id, self._answer_file_id, cancellation_token=token)
            else:
                drafts = {self._marked_answer_id: feedback.generate_feedback_draft(
                    conn, self._teacher_id, self._marked_answer_id, cancellation_token=token)}
            self.succeeded.emit({
                marked_id: {"text": draft.text, "source": draft.source,
                            "source_label": draft.source_label, "fell_back": draft.fell_back,
                            "failure_status": draft.failure_status, "warnings": draft.warnings,
                            "lines": draft.describe()}
                for marked_id, draft in drafts.items()})
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


MARKING_STATUS_DISPLAY_LABELS = {
    "draft": "Draft",
    "uploaded": "Uploaded",
    "preprocessed": "Preprocessed",
    "failed": "Failed",
    "ocr_completed": "OCR Completed",
    "ocr_failed": "OCR Failed",
    "answer_extracted": "Answer Extracted",
    "marked": "Marked",
    "marking_failed": "Marking Failed",
    "reviewed": "Reviewed",
    "pending_review": "Pending Review",
}


def format_marking_status_label(status: str) -> str:
    """Return a clear, human-readable label for a Main Marking session or
    answer file status value (e.g. "ocr_completed" -> "OCR Completed"),
    falling back to Python's plain .capitalize() for any status value that
    predates this lookup table."""
    return MARKING_STATUS_DISPLAY_LABELS.get(status, status.capitalize())

MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS = [
    "display_name", "student_name", "student_code", "page_count", "processing_status", "action",
]
MARKING_SESSION_ANSWER_FILE_TABLE_HEADERS = [
    "Display Name / Filename", "Student Name", "Student Code", "Pages", "Status", "Actions",
]

MARKING_REVIEW_ITEM_TABLE_COLUMNS = [
    "question_no",
    "correct_answer",
    "extracted_answer",
    "auto_score",
    "final_score",
    "final_result",
    "review_status",
    "action",
]

MARKING_REVIEW_ITEM_TABLE_HEADERS = [
    "Question",
    "Correct Answer",
    "Extracted Answer",
    "Auto Score",
    "Final Score",
    "Result",
    "Review Status",
    "Action",
]

MARKING_REVIEW_ITEM_COLUMN_WIDTHS = {
    "question_no": 90,
    "correct_answer": 110,
    "auto_score": 90,
    "final_score": 90,
    "final_result": 90,
    "review_status": 120,
    "action": 90,
}

KERTAS2_REVIEW_ITEM_TABLE_COLUMNS = [
    "criterion_name",
    "student_answer",
    "suggested_score",
    "final_score",
    "final_feedback",
    "review_status",
    "action",
]

KERTAS2_REVIEW_ITEM_TABLE_HEADERS = [
    "Criterion",
    "Student Answer",
    "Suggested Score",
    "Final Score",
    "Final Feedback",
    "Review Status",
    "Action",
]

KERTAS2_REVIEW_ITEM_COLUMN_WIDTHS = {
    "criterion_name": 130,
    "suggested_score": 110,
    "final_score": 110,
    "review_status": 120,
    "action": 90,
}

# --- Stage 11R: standalone Main Marking review (separate from the
# class/revision review above - Attempts / Workflow's own review entry
# point is unaffected) ---------------------------------------------------

MAIN_MARKING_REVIEW_TABLE_COLUMNS = [
    "session_title", "paper_type", "answer_file", "student_name", "student_code",
    "marking_status", "review_status", "action",
]
MAIN_MARKING_REVIEW_TABLE_HEADERS = [
    "Session", "Paper Type", "Answer File", "Student Name", "Student Code",
    "Marking Status", "Review Status", "Actions",
]

MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS = [
    "target_label", "target_kind", "student_answer", "correct_answer",
    "machine_score", "teacher_score", "review_status", "action",
]
MAIN_MARKING_REVIEW_DETAIL_TABLE_HEADERS = [
    "Target", "Kind", "Student Answer", "Correct Answer",
    "Machine Score", "Teacher Score", "Review Status", "Actions",
]

RESULT_SUMMARY_TABLE_COLUMNS = [
    "result_type",
    "username",
    "student_name",
    "class_name",
    "material_title",
    "paper_type",
    "final_score",
    "max_score",
    "finalized_at",
    "action",
]

RESULT_SUMMARY_TABLE_HEADERS = [
    "Result Type",
    "Student ID",
    "Student Name",
    "Class",
    "Material",
    "Paper",
    "Final Score",
    "Max Score",
    "Finalized",
    "Action",
]

RESULT_SUMMARY_COLUMN_WIDTHS = {
    "result_type": 130,
    "username": 110,
    "student_name": 140,
    "class_name": 90,
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

# Stage 11S: a separate table for finalized standalone Main Marking results -
# the existing RESULT_SUMMARY_TABLE_* above (and its class-based query) is
# left completely untouched.
MAIN_MARKING_RESULT_TABLE_COLUMNS = [
    "session_title",
    "answer_file",
    "student_name",
    "student_code",
    "paper_type",
    "total_score",
    "max_score",
    "finalized_at",
    "action",
]

MAIN_MARKING_RESULT_TABLE_HEADERS = [
    "Session",
    "Answer File",
    "Student Name",
    "Student Code",
    "Paper",
    "Final Score",
    "Max Score",
    "Finalized",
    "Action",
]

MAIN_MARKING_RESULT_COLUMN_WIDTHS = {
    "answer_file": 150,
    "student_name": 130,
    "student_code": 110,
    "paper_type": 90,
    "total_score": 90,
    "max_score": 90,
    "finalized_at": 150,
    "action": 310,
}

MARKING_QUESTION_TABLE_COLUMNS = [
    "question_no",
    "correct_answer",
    "max_mark",
    "question_type",
    "explanation",
    "linked_region",
    "action",
]

MARKING_QUESTION_TABLE_HEADERS = [
    "Question No",
    "Correct Answer",
    "Max Mark",
    "Type",
    "Explanation",
    "Linked Region",
    "Action",
]

MARKING_QUESTION_COLUMN_WIDTHS = {
    "question_no": 90,
    "correct_answer": 110,
    "max_mark": 80,
    "question_type": 130,
    "linked_region": 120,
    "action": 140,
}

MY_CLASS_STATUS = "My Class"
AVAILABLE_STATUS = "Available"
OCCUPIED_STATUS = "Occupied"

OCR_TEXT_PREVIEW_LIMIT = 3000


def _build_ocr_result_message(ocr_job: OCRJob) -> str:
    full_text = ocr_job.full_text or ""
    preview = full_text[:OCR_TEXT_PREVIEW_LIMIT]
    if len(full_text) > OCR_TEXT_PREVIEW_LIMIT:
        preview += "\n\n... (preview truncated)"
    return (
        f"Status: {ocr_job.status}\n"
        f"Pages Processed: {ocr_job.page_count}\n\n"
        f"Extracted Text Preview:\n{preview or '(no text extracted)'}\n\n"
        "Run answer extraction and marking from this attempt's row actions."
    )


EXTRACTION_TEXT_PREVIEW_LIMIT = 200


def _build_extraction_summary_message(extraction_job: ExtractionJob) -> str:
    return (
        f"Status: {extraction_job.status}\n"
        f"Region Count: {extraction_job.region_count}\n"
        f"Extracted Count: {extraction_job.extracted_count}\n\n"
        "Run marking from this attempt's row actions once extraction looks right."
    )


def _build_extraction_preview_message(extraction_job: ExtractionJob, template_title: str, results: list) -> str:
    lines = [
        f"Status: {extraction_job.status}",
        f"Template: {template_title}",
        f"Region Count: {extraction_job.region_count}",
        f"Extracted Count: {extraction_job.extracted_count}",
        "",
    ]
    if extraction_job.status != EXTRACTION_STATUS_COMPLETED:
        lines.append(
            f"Error: {extraction_job.error_message or 'Extraction failed for an unknown reason.'}"
        )
    else:
        for result in results:
            preview = (result.extracted_text or "")[:EXTRACTION_TEXT_PREVIEW_LIMIT]
            confidence = (
                f"{result.average_confidence:.2f}" if result.average_confidence is not None else "N/A"
            )
            lines.append(
                f"[Page {result.page_number}] {result.region_name} ({result.region_type}) "
                f"- {result.extraction_status}\n"
                f"  Confidence: {confidence}\n"
                f"  Text: {preview or '(no text)'}\n"
            )
    lines.append("Run marking from this attempt's row actions once extraction looks right.")
    return "\n".join(lines)


ANSWER_TEXT_PREVIEW_LIMIT = 200


def _build_answer_extraction_summary_message(answer_job: AnswerExtractionJob) -> str:
    return (
        f"Status: {answer_job.status}\n"
        f"Question Count: {answer_job.question_count}\n"
        f"Extracted Count: {answer_job.extracted_count}\n\n"
        "Run Kertas 1 marking from this attempt's row actions when the answers look right."
    )


def _build_answer_extraction_preview_message(answer_job: AnswerExtractionJob, answers: list) -> str:
    lines = [
        f"Status: {answer_job.status}",
        f"Question Count: {answer_job.question_count}",
        f"Extracted Count: {answer_job.extracted_count}",
        "",
    ]
    if answer_job.status != ANSWER_EXTRACTION_STATUS_COMPLETED:
        lines.append(f"Error: {answer_job.error_message or 'Answer extraction failed for an unknown reason.'}")
    else:
        for answer in answers:
            raw_preview = (answer.raw_text or "")[:ANSWER_TEXT_PREVIEW_LIMIT]
            confidence = f"{answer.confidence:.2f}" if answer.confidence is not None else "N/A"
            lines.append(
                f"Question {answer.question_no} ({answer.question_type}) - Region: {answer.region_name or 'None'} "
                f"- {answer.extraction_status}\n"
                f"  Confidence: {confidence}\n"
                f"  Raw Text: {raw_preview or '(no text)'}\n"
                f"  Extracted Answer: {answer.extracted_answer or '(none)'}\n"
            )
    lines.append("Run Kertas 1 marking from this attempt's row actions when the answers look right.")
    return "\n".join(lines)


def _build_marking_summary_message(marking_job: MarkingJob) -> str:
    return (
        f"Status: {marking_job.status}\n"
        f"Total Score: {marking_job.total_score} / {marking_job.max_score}\n"
        f"Correct: {marking_job.correct_count}\n"
        f"Needs Review: {marking_job.needs_review_count}\n\n"
        "Review the marking from this attempt's row actions; finalised results can be "
        "exported from the Results page."
    )


def _build_marking_preview_message(marking_job: MarkingJob, results: list) -> str:
    lines = [
        f"Status: {marking_job.status}",
        f"Total Score: {marking_job.total_score} / {marking_job.max_score}",
        f"Correct: {marking_job.correct_count}",
        f"Needs Review: {marking_job.needs_review_count}",
        "",
    ]
    if marking_job.status != MARKING_STATUS_COMPLETED:
        lines.append(f"Error: {marking_job.error_message or 'Marking failed for an unknown reason.'}")
    else:
        for result in results:
            if result.needs_review:
                verdict = "needs review"
            elif result.is_correct:
                verdict = "correct"
            else:
                verdict = "wrong"
            lines.append(
                f"Question {result.question_no}: {verdict} ({result.score_awarded}/{result.max_mark})\n"
                f"  Correct Answer: {result.correct_answer}\n"
                f"  Extracted Answer: {result.extracted_answer or '(none)'}\n"
                f"  Reason: {result.reason or '-'}\n"
                f"  Explanation: {result.explanation or '-'}\n"
            )
    lines.append("Review the marking from this attempt's row actions; finalised results can be "
                 "exported from the Results page.")
    return "\n".join(lines)


KERTAS2_FEEDBACK_TEXT_PREVIEW_LIMIT = 200


def _build_kertas2_feedback_summary_message(feedback_job: Kertas2AIFeedbackJob) -> str:
    return (
        f"Status: {feedback_job.status}\n"
        f"Criterion Count: {feedback_job.criterion_count}\n"
        f"Generated Count: {feedback_job.generated_count}\n"
        f"Provider Backend: {feedback_job.provider_backend or '-'}\n"
        f"Provider Status: {feedback_job.provider_status or '-'}\n"
        f"Diagnostic Message: {feedback_job.diagnostic_message or '-'}\n\n"
        "These are draft suggestions - review each one and set the final score yourself "
        "before finalising."
    )


def _build_kertas2_feedback_preview_message(feedback_job: Kertas2AIFeedbackJob, items: list) -> str:
    lines = [
        f"Status: {feedback_job.status}",
        f"Criterion Count: {feedback_job.criterion_count}",
        f"Generated Count: {feedback_job.generated_count}",
        f"Provider Backend: {feedback_job.provider_backend or '-'}",
        f"Provider Status: {feedback_job.provider_status or '-'}",
        f"Diagnostic Message: {feedback_job.diagnostic_message or '-'}",
        "",
    ]
    if feedback_job.status != KERTAS2_FEEDBACK_STATUS_COMPLETED:
        lines.append(f"Error: {feedback_job.error_message or 'Feedback generation failed for an unknown reason.'}")
    else:
        for item in items:
            student_answer_preview = (item.student_answer or "")[:KERTAS2_FEEDBACK_TEXT_PREVIEW_LIMIT]
            confidence = f"{item.confidence:.2f}" if item.confidence is not None else "N/A"
            lines.append(
                f"{item.criterion_name} ({item.question_type}) - {item.feedback_status} "
                f"[audit: {item.audit_status or '-'}]\n"
                f"  Student Answer: {student_answer_preview or '(none)'}\n"
                f"  Suggested Score: {item.suggested_score}/{item.max_mark} (draft only)\n"
                f"  Feedback: {item.feedback_text or '-'}\n"
                f"  Reason: {item.reason or '-'}\n"
                f"  Confidence: {confidence}\n"
            )
    lines.append("These are draft suggestions - review each one and set the final score yourself "
                 "before finalising.")
    lines.append("Click 'View Kertas 2 Feedback Audit' for prompt/raw output/parser details.")
    return "\n".join(lines)


KERTAS2_AUDIT_TEXT_PREVIEW_LIMIT = 2000


def _build_kertas2_feedback_audit_message(feedback_job: Kertas2AIFeedbackJob, items: list) -> str:
    lines = [
        f"Job Status: {feedback_job.status}",
        f"Provider Backend: {feedback_job.provider_backend or '-'}",
        f"Provider Model Path: {feedback_job.provider_model_path or '-'}",
        f"Provider Status: {feedback_job.provider_status or '-'}",
        f"Diagnostic Message: {feedback_job.diagnostic_message or '-'}",
        f"Job Error: {feedback_job.error_message or '-'}",
        "",
        "This AI feedback is a draft. Teacher review and final scoring remain required.",
        "",
    ]
    for item in items:
        prompt_preview = (item.prompt_snapshot or "-")[:KERTAS2_AUDIT_TEXT_PREVIEW_LIMIT]
        raw_output_preview = (item.raw_provider_output or "-")[:KERTAS2_AUDIT_TEXT_PREVIEW_LIMIT]
        lines.append(
            f"--- {item.criterion_name} (audit: {item.audit_status or '-'}) ---\n"
            f"Prompt Snapshot:\n{prompt_preview}\n\n"
            f"Raw Provider Output:\n{raw_output_preview}\n\n"
            f"Parser Error: {item.parser_error or '-'}\n"
        )
    return "\n".join(lines)


def _build_readiness_issues_message(readiness) -> str:
    lines = [
        f"Attempt: #{readiness.target_id} ({readiness.paper_type})",
        f"Readiness: {readiness.readiness_status}",
        f"Issues: {readiness.issue_count} total, {readiness.blocker_count} blocker(s), {readiness.warning_count} warning(s)",
        f"Summary: {readiness.issue_summary}",
        f"Current Stage: {readiness.current_stage}",
        f"Next Action: {readiness.next_action}",
        "",
        "Readiness Issue Flags:",
    ]
    if readiness.issues:
        for issue in readiness.issues:
            related = f" (record #{issue.related_record_id})" if issue.related_record_id else ""
            lines.append(
                f"  [{issue.severity}] {issue.title}: {issue.status}{related}\n"
                f"    Key: {issue.issue_key}\n"
                f"    Message: {issue.message}\n"
                f"    Recommended Action: {issue.recommended_action}"
            )
    else:
        lines.append("  No setup or attempt-readiness issues found.")
    lines.append("")
    lines.append("This page is read-only. Use the existing action buttons to continue the workflow.")
    return "\n".join(lines)


def _build_workflow_status_message(status, readiness=None) -> str:
    lines = [
        f"Attempt: {status.material_title} ({status.paper_type})",
        f"Student: {status.student_name} - Class: {status.class_name}",
        "",
        f"Overall Status: {status.overall_status}",
        f"Current Stage: {status.current_stage}",
        f"Next Action: {status.next_action}",
        "",
        "Workflow Steps:",
    ]
    for step in status.steps:
        related = f" (record #{step.related_record_id})" if step.related_record_id else ""
        lines.append(f"  {step.step_label}: {step.status}{related}\n    {step.message}")
    lines.append("")
    if readiness is not None:
        lines.append("Readiness Summary:")
        lines.append(
            f"  {readiness.readiness_status}: {readiness.issue_count} issue(s), "
            f"{readiness.blocker_count} blocker(s), {readiness.warning_count} warning(s)"
        )
        lines.append("  Use View Issues for the dedicated setup/readiness issue list.")
        lines.append("")
    lines.append("This page is read-only. Use the existing action buttons to continue the workflow.")
    return "\n".join(lines)


def _build_result_detail_message(result_type: str, review, detail_rows: list) -> str:
    lines = [
        f"Final Score: {review.final_total_score} / {review.max_score}",
        f"Overall Comment: {review.teacher_overall_comment or '-'}",
        "",
    ]
    if result_type == RESULT_TYPE_KERTAS1:
        for detail_row in detail_rows:
            lines.append(
                f"Question {detail_row.question_no}: {detail_row.final_score}/{detail_row.max_mark}\n"
                f"  Extracted Answer: {detail_row.extracted_answer or '(none)'}\n"
                f"  Correct Answer: {detail_row.correct_answer}\n"
                f"  Teacher Comment: {detail_row.teacher_comment or '-'}\n"
                f"  Explanation: {detail_row.explanation or '-'}\n"
            )
    else:
        for detail_row in detail_rows:
            lines.append(
                f"{detail_row.criterion_name}: {detail_row.final_score}/{detail_row.max_mark}\n"
                f"  Student Answer: {detail_row.student_answer or '(none)'}\n"
                f"  Final Feedback: {detail_row.final_feedback or '-'}\n"
                f"  Teacher Comment: {detail_row.teacher_comment or '-'}\n"
            )
    lines.append("Use Export Summary / Detail CSV on the Results page to export this result.")
    return "\n".join(lines)


def _build_main_marking_result_detail_message(detail) -> str:
    """Format one finalized Main Marking result (Stage 11S) for the Results
    page's detail view - a frozen, teacher-reviewed snapshot, distinct from
    the class-based marking_reviews detail above."""
    result = detail.result
    lines = [
        f"Session: {detail.session_title}",
        f"Answer File: {result.answer_file_display_name}",
        f"Student: {result.student_name or '-'} ({result.student_code or '-'})",
        f"Paper Type: {result.paper_type}",
        f"Final Score: {result.total_score} / {result.max_score}",
        f"Finalized: {format_timestamp(result.finalized_at)}",
        "",
        "This is a finalized, teacher-reviewed result.",
        "",
    ]
    for item in detail.items:
        machine_text = f"{item.machine_score if item.machine_score is not None else '-'} / {item.max_score}"
        teacher_text = f"{item.teacher_score if item.teacher_score is not None else 'Not reviewed'}"
        lines.append(
            f"{item.target_label}: {item.final_score}/{item.max_score}\n"
            f"  Student Answer: {item.student_answer_text or '(none)'}\n"
            f"  Correct Answer: {item.correct_answer_text or '(none)'}\n"
            f"  Machine Score: {machine_text}\n"
            f"  Teacher Score: {teacher_text}\n"
            f"  Final Feedback: {item.final_feedback or '-'}\n"
        )
    return "\n".join(lines)


class GroupMemberOrderDialog(QDialog):
    """Small modal listing a region group's members in their current order,
    with Move Up/Move Down buttons that immediately persist the new order
    via move_group_member (Stage 11H)."""

    def __init__(self, parent: Optional[QWidget], teacher_id: int, group_id: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adjust Member Order")
        self.setModal(True)
        self._teacher_id = teacher_id
        self._group_id = group_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title_label = QLabel("Adjust Member Order")
        title_label.setObjectName("LoginCardTitle")
        layout.addWidget(title_label)

        hint_label = QLabel("Select a member below, then Move Up/Move Down to change extraction order.")
        hint_label.setObjectName("StatusLabel")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        self.member_list = QListWidget()
        layout.addWidget(self.member_list)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.move_up_button.clicked.connect(lambda: self._move("up"))
        buttons_row.addWidget(self.move_up_button)

        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.move_down_button.clicked.connect(lambda: self._move("down"))
        buttons_row.addWidget(self.move_down_button)

        layout.addLayout(buttons_row)

        close_button = QPushButton("Close")
        close_button.setObjectName("PrimaryButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._refresh_members()

    def _refresh_members(self, select_region_id: Optional[int] = None) -> None:
        self.member_list.clear()
        conn = get_connection()
        try:
            members = list_group_members(conn, self._teacher_id, self._group_id)
        finally:
            conn.close()

        select_row = 0
        for index, member in enumerate(members):
            item = QListWidgetItem(f"{member.label} (P{member.page_number})")
            item.setData(Qt.ItemDataRole.UserRole, member.region_id)
            self.member_list.addItem(item)
            if select_region_id is not None and member.region_id == select_region_id:
                select_row = index

        if self.member_list.count() > 0:
            self.member_list.setCurrentRow(select_row)

    def _move(self, direction: str) -> None:
        item = self.member_list.currentItem()
        if item is None:
            return
        region_id = item.data(Qt.ItemDataRole.UserRole)

        conn = get_connection()
        try:
            move_group_member(conn, self._teacher_id, self._group_id, region_id, direction)
        except ValueError as exc:
            show_error(self, "Reorder Failed", str(exc))
            return
        finally:
            conn.close()

        self._refresh_members(select_region_id=region_id)


class _NoAutoToggleCheckDelegate(QStyledItemDelegate):
    """Disables the default tiny-indicator-only checkbox toggle so the whole
    row can be made clickable without double-toggling on the indicator."""

    def editorEvent(self, event, model, option, index):
        return False


# --- AI Models card display formatting (Stage 12D-fix) -----------------------
#
# Pure formatting helpers - no business logic. Long raw metrics JSON and
# unbroken storage paths on the AI Models card were forcing the whole page
# (and, since QStackedWidget's layout sizes itself to the largest page it
# has ever shown, every OTHER page too) wider than the fixed app window,
# producing a horizontal scrollbar everywhere. These helpers turn the same
# underlying data into short, single-purpose display strings; the full
# values remain available via tooltip (storage path) or the log file
# (View Logs) - never dropped, just not forced onto the card itself.

AI_MODEL_CARD_LABEL_MAX_WIDTH = 900


def _shorten_path_for_display(path_str: Optional[str], keep_parts: int = 3) -> str:
    """Return the last keep_parts path segments (e.g.
    '.../k2_scoring/teacher_1/k2_cross_encoder_20260716_034336') instead of
    a full, unbroken path - a QLabel can't word-wrap a path with no spaces,
    so shortening the text itself is what actually prevents page overflow."""
    if not path_str:
        return "Not available"
    parts = Path(path_str).parts
    if len(parts) <= keep_parts:
        return str(Path(path_str))
    return ".../" + "/".join(parts[-keep_parts:])


def _format_training_metrics_summary(metrics: Optional[dict]) -> str:
    """Short, readable one-line summary of training metrics for the AI
    Models card - never the raw metrics dict/JSON. The full metrics remain
    available in the training log (View Logs)."""
    if not metrics:
        return "Not available"
    row_count = metrics.get("usable_row_count", metrics.get("row_count", "-"))
    val_mae = metrics.get("val_mae")
    val_mae_text = f"{val_mae:.4f}" if isinstance(val_mae, (int, float)) else "N/A"
    category_accuracy = metrics.get("category_accuracy")
    category_text = f"{category_accuracy:.1%}" if isinstance(category_accuracy, (int, float)) else "N/A"
    demo_text = "Demo data" if metrics.get("demo_mode") else "Real data"
    return f"Rows: {row_count} | Val MAE: {val_mae_text} | Category accuracy: {category_text} | {demo_text}"


def _format_evaluation_metrics_summary(metrics: Optional[dict]) -> str:
    """Short, readable one-line summary of evaluation metrics for the AI
    Models card - never the raw metrics dict/JSON. The full metrics remain
    available in the evaluation log (View Logs)."""
    if not metrics:
        return "None yet"
    row_count = metrics.get("usable_row_count", "-")
    mae = metrics.get("mean_absolute_error")
    mae_text = f"{mae:.4f}" if isinstance(mae, (int, float)) else "N/A"
    category_accuracy = metrics.get("category_accuracy")
    category_text = f"{category_accuracy:.1%}" if isinstance(category_accuracy, (int, float)) else "N/A"
    demo_text = "Demo evaluation" if metrics.get("demo_mode") else "Real evaluation"
    return f"Rows: {row_count} | MAE: {mae_text} | Category accuracy: {category_text} | {demo_text}"


_TEXT_ENTRY_WIDGET_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox)


class SubjectProfileEditorKeyFilter(QObject):
    """Stage 12E-2 UX Fix: application-wide event filter providing A/D page
    navigation plus Delete/Esc region shortcuts while the Subject Profile
    Editor page is visible. Extended (Data Management Readiness Fix) with
    Ctrl+Z region-editing undo.

    Installed on QApplication.instance() rather than any single widget: the
    Subject Profile Editor page (built by app.ui.components.create_page) is
    a plain QWidget with several different focusable child widget types
    (QTableWidget, QPushButton, the QGraphicsView-based TemplateCanvas),
    and relying on Qt's normal key-event bubbling across all of them would
    be fragile. is_active() confirms the Subject Profile Editor page is the
    CURRENTLY VISIBLE page (the filter itself is global/app-wide) before
    acting, and any focused text-entry-style widget (_TEXT_ENTRY_WIDGET_
    TYPES) blocks A/D/Delete/Escape so typing in a region name/label field,
    a combo box, or a spin box is never interpreted as a shortcut."""

    def __init__(self, dashboard: "TeacherDashboard") -> None:
        super().__init__(dashboard)
        self._dashboard = dashboard

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        focus_widget = QApplication.focusWidget()
        if isinstance(focus_widget, _TEXT_ENTRY_WIDGET_TYPES):
            return False

        # Marking Editor: same A/D previous/next page navigation the Subject
        # Profile editor has (guarded by the identical text-entry focus check).
        if self._dashboard.is_marking_editor_page_active():
            if event.key() == Qt.Key.Key_D:
                self._dashboard.handle_marking_editor_next_page()
                return True
            if event.key() == Qt.Key.Key_A:
                self._dashboard.handle_marking_editor_prev_page()
                return True
            return False

        if not self._dashboard.is_subject_profile_editor_page_active():
            return False

        key = event.key()
        if key == Qt.Key.Key_D:
            self._dashboard.handle_subject_profile_next_page()
            return True
        if key == Qt.Key.Key_A:
            self._dashboard.handle_subject_profile_prev_page()
            return True
        if key == Qt.Key.Key_Delete:
            self._dashboard.handle_delete_selected_subject_profile_region()
            return True
        if key == Qt.Key.Key_Escape:
            self._dashboard.handle_clear_subject_profile_region_selection()
            return True
        if key == Qt.Key.Key_Z and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._dashboard.handle_subject_profile_region_undo()
            return True
        return False


class TeacherDashboard(QWidget):
    def __init__(self, user: Optional[User] = None) -> None:
        super().__init__()
        self.setWindowTitle("MarkAssist — Teacher")
        apply_fixed_16_9_window(self)

        self._user = user
        self._teacher_id: Optional[int] = user.user_id if user else None

        self.shell = AppShell(
            brand_text="MarkAssist",
            on_page_shown=self._handle_page_shown,
            # Stage 11W: "Templates" and "Marking Setup" are hidden from the
            # teacher-facing sidebar now that Subject Profiles are the only
            # marking workflow entry point - their pages/backend are still
            # fully intact and reachable via shell.show_page(...) directly
            # (see handle_material_setup and similar), only the sidebar nav
            # buttons are removed.
            nav_items=[
                "Dashboard",
                "Marking",
                "Results",
                "Local AI Settings",
                "All Classes",
                "Students",
                "Attempts / Workflow",
                "Revision Materials",
                "External Revisions",
            ],
            group_headings={
                "Marking": "MAIN MARKING SYSTEM",
                "All Classes": "CLASS MANAGEMENT",
            },
            header_title="Teacher Dashboard",
            header_subtitle="Overview of your English classes.",
            user_full_name=user.full_name if user else "Teacher",
            user_role_label="Teacher",
            on_logout=self.handle_logout,
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)

        self._new_material_question_paper_path = ""
        self._new_material_marking_scheme_path = ""
        self._new_template_sample_path = ""
        self._new_marking_session_question_paper_path = ""
        self._new_marking_session_answer_key_path = ""
        self._current_marking_session: Optional[MainMarkingSession] = None
        self._current_template: Optional[AnswerTemplate] = None
        self._current_template_page: int = 1
        self._current_template_page_count: int = 1
        self._redefine_region_id: Optional[int] = None
        self._redefine_pending_label: Optional[str] = None
        self._redefine_pending_region_type: Optional[str] = None
        self._redefine_pending_order_index: Optional[int] = None
        self._redefine_pending_notes: Optional[str] = None
        self._redefine_shape_type: Optional[str] = None
        self._redefine_pending_rotation_angle: Optional[float] = None
        self._template_region_checkboxes: dict = {}
        self._current_marking_material: Optional[TeacherMaterialRow] = None
        self._current_marking_setup: Optional[MarkingSetup] = None
        self._current_review: Optional[MarkingReview] = None
        self._current_review_attempt_row: Optional[TeacherAttemptRow] = None
        self._current_review_results_by_id: dict = {}
        self._current_kertas2_review: Optional[Kertas2FeedbackReview] = None
        self._current_kertas2_review_attempt_row: Optional[TeacherAttemptRow] = None
        self._current_main_marking_review_file: Optional[ReviewableMainMarkingFile] = None
        self._subject_profile_editor_key_filter: Optional["SubjectProfileEditorKeyFilter"] = None

        self.shell.add_page("Dashboard", self._build_dashboard_page())
        self.shell.add_page("Marking", self._build_marking_page())
        self._subject_profile_editor_page_widget = self._build_subject_profile_editor_page()
        self.shell.add_page("Subject Profile Editor", self._subject_profile_editor_page_widget)
        self._marking_editor_page_widget = self._build_subject_profile_marking_editor_page()
        self.shell.add_page("Marking Editor", self._marking_editor_page_widget)
        self.shell.add_page("Marking Session Detail", self._build_marking_session_detail_page())
        self.shell.add_page("Main Marking Review Detail", self._build_main_marking_review_detail_page())
        self.shell.add_page("All Classes", self._build_classes_page())
        self.shell.add_page("Students", self._build_students_page())
        self.shell.add_page("Create Student", self._build_create_student_page())
        self.shell.add_page("Revision Materials", self._build_revision_materials_page())
        self.shell.add_page("Create Revision Material", self._build_create_revision_material_page())
        self.shell.add_page("External Revisions", self._build_external_revisions_page())
        self.shell.add_page("Attempts / Workflow", self._build_revision_attempts_page())
        self.shell.add_page("Templates", self._build_templates_page())
        self.shell.add_page("Create Template", self._build_create_template_page())
        self.shell.add_page("Template Editor", self._build_template_editor_page())
        # "Material Marking Setup" is the existing per-material setup page
        # (opened via a Revision Materials row's "Setup" button); its key is
        # kept distinct from the new "Marking Setup" sidebar item below,
        # which opens the existing teacher-wide marking settings page.
        self.shell.add_page("Material Marking Setup", self._build_marking_setup_page())
        self.shell.add_page("Marking Review", self._build_marking_review_page())
        self.shell.add_page("Kertas 2 Review", self._build_kertas2_review_page())
        self.shell.add_page("Results", self._build_results_page())
        self.shell.add_page("Marking Setup", self._build_marking_settings_page())
        self.shell.add_page("Local AI Settings", self._build_local_ai_settings_page())
        # Stage 12G-2: the global AI Models registry moved to the technical
        # developer/admin dashboard (app/ui/ai_models_admin_page.py). Teachers
        # keep only their own per-teacher Local AI Settings above.
        self.shell.show_page("Dashboard")

        self.refresh_table()
        self.refresh_incoming_requests_table()
        self.refresh_students_table()
        self.refresh_incoming_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        self.refresh_materials_table()
        self.refresh_external_revisions_table()
        self.refresh_attempts_table()
        self.refresh_templates_table()
        self.refresh_results_table()
        self.refresh_marking_settings_page()
        self.refresh_local_ai_settings_page()
        self.refresh_marking_sessions_table()
        self.refresh_main_marking_results_table()
        self.refresh_subject_profiles_table()

        self._subject_profile_editor_key_filter = SubjectProfileEditorKeyFilter(self)
        QApplication.instance().installEventFilter(self._subject_profile_editor_key_filter)

    def _handle_page_shown(self, name: str) -> None:
        """Refresh data-backed pages when the teacher navigates to them, so
        results written since the dashboard was built (e.g. an attempt
        finalised in the Marking Editor) are always visible."""
        if name == "Results":
            self.refresh_results_table()
            self.refresh_main_marking_results_table()
        elif name == "Marking":
            self.refresh_subject_profiles_table()

    def is_subject_profile_editor_page_active(self) -> bool:
        return self.shell.pages_stack.currentWidget() is self._subject_profile_editor_page_widget

    def is_marking_editor_page_active(self) -> bool:
        return self.shell.pages_stack.currentWidget() is self._marking_editor_page_widget

    def closeEvent(self, event) -> None:
        """Removes the Stage 12E-2 UX Fix global key event filter before
        this dashboard is destroyed - without this, TeacherDashboard
        instances created/destroyed repeatedly (e.g. across tests) would
        leave stale filters on QApplication referencing deleted C++ Qt
        objects, crashing later, unrelated tests."""
        app_instance = QApplication.instance()
        if app_instance is not None and self._subject_profile_editor_key_filter is not None:
            app_instance.removeEventFilter(self._subject_profile_editor_key_filter)
        self._subject_profile_editor_key_filter = None
        super().closeEvent(event)

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # --- Dashboard page (overview only) ---------------------------------

    def _build_dashboard_page(self) -> QWidget:
        page, layout = create_page()

        # Hero KPI ("start where the work is"): the one loud element on the
        # desk - how many submissions wait for marking, and the way in.
        hero = QFrame()
        hero.setObjectName("HeroKpiBanner")
        hero.setStyleSheet(
            "QFrame#HeroKpiBanner { background-color: #474747; border-radius: 14px;"
            " border-top: 1px solid rgba(255,255,255,18); }")
        apply_card_shadow(hero, blur_radius=34, y_offset=10, alpha=70)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 18, 24, 18)
        hero_layout.setSpacing(18)

        self.hero_kpi_number_label = QLabel("0")
        self.hero_kpi_number_label.setStyleSheet(
            "font-size: 44px; font-weight: 800; color: #F59E0B; background: transparent;")
        hero_layout.addWidget(self.hero_kpi_number_label)

        hero_text_column = QVBoxLayout()
        hero_text_column.setSpacing(2)
        self.hero_kpi_title_label = QLabel("submissions waiting for your marking")
        self.hero_kpi_title_label.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #EDEDED; background: transparent;")
        self.hero_kpi_subtitle_label = QLabel("Attempts and external revisions not yet finalised.")
        self.hero_kpi_subtitle_label.setObjectName("StatusLabel")
        hero_text_column.addWidget(self.hero_kpi_title_label)
        hero_text_column.addWidget(self.hero_kpi_subtitle_label)
        hero_layout.addLayout(hero_text_column)
        hero_layout.addStretch()

        hero_go_button = QPushButton("Continue marking")
        hero_go_button.setObjectName("CtaButton")
        hero_go_button.setCursor(Qt.CursorShape.PointingHandCursor)
        hero_go_button.clicked.connect(lambda: self.shell.show_page("Attempts / Workflow"))
        hero_layout.addWidget(hero_go_button)

        layout.addWidget(hero)

        # Stat cards double as navigation: clicking one jumps to the page
        # where that number lives.
        self.my_classes_card = StatCard(
            "My Classes", "0", on_click=lambda: self.shell.show_page("All Classes"))
        self.my_students_card = StatCard(
            "My Students", "0", on_click=lambda: self.shell.show_page("Students"))
        self.subject_card = StatCard("Subject", DEFAULT_SUBJECT)
        self.pending_join_requests_card = StatCard(
            "Pending Join Requests", "0", on_click=lambda: self.shell.show_page("All Classes"))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.my_classes_card)
        cards_row.addWidget(self.my_students_card)
        cards_row.addWidget(self.subject_card)
        cards_row.addWidget(self.pending_join_requests_card)
        layout.addLayout(cards_row)

        self.total_attempts_card = StatCard(
            "Total Attempts", "0", on_click=lambda: self.shell.show_page("Attempts / Workflow"))
        self.blocked_attempts_card = StatCard(
            "Blocked Attempts", "0", on_click=lambda: self.shell.show_page("Attempts / Workflow"))
        self.pending_review_attempts_card = StatCard(
            "Pending Review", "0", on_click=lambda: self.shell.show_page("Marking"))
        self.finalized_results_summary_card = StatCard(
            "Finalized Results", "0", on_click=lambda: self.shell.show_page("Results"))

        attention_cards_row = QHBoxLayout()
        attention_cards_row.setSpacing(16)
        attention_cards_row.addWidget(self.total_attempts_card)
        attention_cards_row.addWidget(self.blocked_attempts_card)
        attention_cards_row.addWidget(self.pending_review_attempts_card)
        attention_cards_row.addWidget(self.finalized_results_summary_card)
        layout.addLayout(attention_cards_row)

        queue_heading = QLabel("Attention Queue")
        queue_heading.setObjectName("SectionHeading")
        layout.addWidget(queue_heading)

        self.attention_table = QTableWidget(0, len(ATTENTION_TABLE_COLUMNS))
        self.attention_table.setHorizontalHeaderLabels(ATTENTION_TABLE_HEADERS)
        self.attention_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attention_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attention_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        attention_header = self.attention_table.horizontalHeader()
        attention_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        attention_header.setSectionResizeMode(
            ATTENTION_TABLE_COLUMNS.index("material_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in ATTENTION_COLUMN_WIDTHS.items():
            self.attention_table.setColumnWidth(ATTENTION_TABLE_COLUMNS.index(key), width)
        self.attention_table.verticalHeader().setVisible(False)
        self.attention_table.verticalHeader().setDefaultSectionSize(44)
        self.attention_table.setAlternatingRowColors(True)
        self.attention_table.setMinimumHeight(220)
        apply_card_shadow(self.attention_table)
        layout.addWidget(self.attention_table)

        view_classes_button = QPushButton("View Classes")
        view_classes_button.setObjectName("PrimaryButton")
        view_classes_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_classes_button.clicked.connect(lambda: self.shell.show_page("All Classes"))

        view_students_button = QPushButton("View Students")
        view_students_button.setObjectName("PrimaryButton")
        view_students_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_students_button.clicked.connect(lambda: self.shell.show_page("Students"))

        actions_row = QHBoxLayout()
        actions_row.setSpacing(16)
        actions_row.addWidget(view_classes_button)
        actions_row.addWidget(view_students_button)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        layout.addStretch()
        return page

    def _build_attention_action_cell(self, _item: TeacherAttentionItem) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        open_attempts_button = QPushButton("Open Attempts")
        open_attempts_button.setObjectName("RowActionButton")
        open_attempts_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_attempts_button.clicked.connect(lambda: self.shell.show_page("Attempts / Workflow"))
        cell_layout.addWidget(open_attempts_button)
        return cell

    # --- Main Marking System: Marking Session foundation (Stage 11L) --------
    #
    # "Marking" is the entry page for the new standalone Main Marking System
    # workflow: session creation + an "Existing Marking Sessions" list. It
    # deliberately requires no class selection and no student-account link -
    # a session is a self-contained bundle of a question paper, an answer
    # key/marking scheme, and one or more per-student answer PDFs.
    # Preprocessing/OCR/extraction/marking are explicitly NOT run here yet -
    # legacy pages kept reachable in code only; the Review tab was removed.

    def _build_marking_page(self) -> QWidget:
        """Stage 11V: Subject Profile workflow. Replaces the old teacher-
        facing "choose a Template + paper type" marking-session creation
        form - the teacher never sees a template or paper-type selector
        here anymore. The old Main Marking session/answer-file/
        preprocessing/OCR service layer (Stage 11L-11N) is still reused
        under the hood for student PDF processing (see
        app/services/subject_profile_service.py); the old Marking Session
        Detail / Review / Results pages are untouched and still reachable
        for any pre-Stage-11V session, they are simply no longer the entry
        point from this redesigned page."""
        self._current_subject_profile = None
        self._subject_profile_draft_qp_path: Optional[str] = None
        self._subject_profile_draft_as_path: Optional[str] = None

        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(10)

        title = QLabel("Marking")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel(
            "Create a Subject Profile from a question paper and answer scheme, define regions once, "
            "then mark any number of student answer PDFs against it - no template or paper type "
            "selection required."
        )
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- Section 1: Create Subject Profile -----------------------------
        create_group = QGroupBox("Create Subject Profile")
        apply_card_shadow(create_group)
        create_layout = QVBoxLayout(create_group)
        create_layout.setSpacing(4)

        self.new_subject_profile_name_input = QLineEdit()
        self.new_subject_profile_name_input.setPlaceholderText("e.g. Form 5 English Kertas 1 - March Test")
        create_layout.addWidget(self._field_label("Subject Profile Name"))
        create_layout.addWidget(self.new_subject_profile_name_input)

        create_layout.addWidget(self._field_label("Question Paper"))
        qp_row = QHBoxLayout()
        choose_qp_button = QPushButton("Choose File...")
        choose_qp_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_qp_button.clicked.connect(self.handle_choose_subject_profile_question_paper)
        self.subject_profile_qp_status_label = QLabel("No file selected")
        self.subject_profile_qp_status_label.setObjectName("StatusLabel")
        qp_row.addWidget(choose_qp_button)
        qp_row.addWidget(self.subject_profile_qp_status_label)
        qp_row.addStretch()
        create_layout.addLayout(qp_row)

        create_layout.addWidget(self._field_label("Answer Scheme"))
        as_row = QHBoxLayout()
        choose_as_button = QPushButton("Choose File...")
        choose_as_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_as_button.clicked.connect(self.handle_choose_subject_profile_answer_scheme)
        self.subject_profile_as_status_label = QLabel("No file selected")
        self.subject_profile_as_status_label.setObjectName("StatusLabel")
        as_row.addWidget(choose_as_button)
        as_row.addWidget(self.subject_profile_as_status_label)
        as_row.addStretch()
        create_layout.addLayout(as_row)

        create_button = QPushButton("Create Subject Profile")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_create_subject_profile)
        create_layout.addWidget(create_button)

        layout.addWidget(create_group)

        # --- Section 2: Existing Subject Profiles --------------------------
        existing_heading = QLabel("Existing Subject Profiles")
        existing_heading.setObjectName("SectionHeading")
        layout.addWidget(existing_heading)

        import_row = QHBoxLayout()
        import_profile_button = QPushButton("Import Subject Profile")
        import_profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_profile_button.clicked.connect(self.handle_import_subject_profile)
        import_row.addWidget(import_profile_button)
        import_row.addStretch()
        layout.addLayout(import_row)

        self.subject_profiles_table = QTableWidget(0, len(SUBJECT_PROFILE_TABLE_COLUMNS))
        self.subject_profiles_table.setHorizontalHeaderLabels(SUBJECT_PROFILE_TABLE_HEADERS)
        self.subject_profiles_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_profiles_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subject_profiles_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        profiles_header = self.subject_profiles_table.horizontalHeader()
        profiles_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        profiles_header.setSectionResizeMode(
            SUBJECT_PROFILE_TABLE_COLUMNS.index("profile_name"), QHeaderView.ResizeMode.Stretch
        )
        self.subject_profiles_table.setColumnWidth(SUBJECT_PROFILE_TABLE_COLUMNS.index("status"), 100)
        self.subject_profiles_table.setColumnWidth(SUBJECT_PROFILE_TABLE_COLUMNS.index("updated_at"), 150)
        self.subject_profiles_table.setColumnWidth(SUBJECT_PROFILE_TABLE_COLUMNS.index("action"), 340)
        self.subject_profiles_table.verticalHeader().setVisible(False)
        self.subject_profiles_table.verticalHeader().setDefaultSectionSize(44)
        self.subject_profiles_table.setAlternatingRowColors(True)
        self.subject_profiles_table.setMinimumHeight(180)
        apply_card_shadow(self.subject_profiles_table)
        layout.addWidget(self.subject_profiles_table)

        # --- Section 3: Mark Student Answers --------------------------------
        mark_heading = QLabel("Mark Student Answers")
        mark_heading.setObjectName("SectionHeading")
        layout.addWidget(mark_heading)

        self.mark_student_answers_profile_label = QLabel(
            "No Subject Profile selected - click \"Use for Marking\" on a Subject Profile above."
        )
        self.mark_student_answers_profile_label.setObjectName("StatusLabel")
        self.mark_student_answers_profile_label.setWordWrap(True)
        layout.addWidget(self.mark_student_answers_profile_label)

        upload_row = QHBoxLayout()
        self.upload_student_answers_button = QPushButton("Upload Student Answer PDFs")
        self.upload_student_answers_button.setObjectName("PrimaryButton")
        self.upload_student_answers_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_student_answers_button.setEnabled(False)
        self.upload_student_answers_button.clicked.connect(self.handle_upload_student_answer_pdfs)
        upload_row.addWidget(self.upload_student_answers_button)

        # Stage 12G-1B: strictly binary attempt mode. Unchecked (default) =
        # Standard - the student answered on the question paper. Checked =
        # the upload is a standalone answer paper mapped per attempt.
        self.separate_answer_paper_checkbox = QCheckBox("Separate answer paper")
        self.separate_answer_paper_checkbox.setToolTip(
            "Tick when the student answered on a separate answer paper (PDF or images) instead of "
            "on the question paper. Answer areas are then mapped for this attempt.")
        self.separate_answer_paper_checkbox.setEnabled(False)
        upload_row.addWidget(self.separate_answer_paper_checkbox)

        self.download_all_results_button = QPushButton("Download All (ZIP)")
        self.download_all_results_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_all_results_button.setEnabled(False)
        self.download_all_results_button.clicked.connect(self.handle_download_all_student_results)
        upload_row.addWidget(self.download_all_results_button)
        upload_row.addStretch()
        layout.addLayout(upload_row)

        self.student_results_table = QTableWidget(0, len(STUDENT_RESULT_TABLE_COLUMNS))
        self.student_results_table.setHorizontalHeaderLabels(STUDENT_RESULT_TABLE_HEADERS)
        self.student_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.student_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.student_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_header = self.student_results_table.horizontalHeader()
        results_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        results_header.setSectionResizeMode(
            STUDENT_RESULT_TABLE_COLUMNS.index("student_name"), QHeaderView.ResizeMode.Stretch
        )
        self.student_results_table.setColumnWidth(STUDENT_RESULT_TABLE_COLUMNS.index("status"), 130)
        self.student_results_table.setColumnWidth(STUDENT_RESULT_TABLE_COLUMNS.index("score"), 170)
        self.student_results_table.setColumnWidth(STUDENT_RESULT_TABLE_COLUMNS.index("action"), 300)
        self.student_results_table.verticalHeader().setVisible(False)
        self.student_results_table.verticalHeader().setDefaultSectionSize(44)
        self.student_results_table.setAlternatingRowColors(True)
        self.student_results_table.setMinimumHeight(200)
        apply_card_shadow(self.student_results_table)
        layout.addWidget(self.student_results_table)

        layout.addStretch()

        # The three stacked sections (create / profiles table / mark student
        # answers) together need more height than the fixed 16:9 window has, so
        # without this the "Mark Student Answers" heading and its controls were
        # squeezed into - and drawn over - the Subject Profile table. Scrolling
        # the page VERTICALLY keeps every section at its natural size; the page
        # never scrolls horizontally, so the upload controls stay reachable.
        scroller = QScrollArea()
        scroller.setObjectName("MarkingPageScroll")
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.setWidget(page)
        self.marking_page_scroll_area = scroller
        return scroller

    # --- Subject Profile Editor page (Stage 11V, hidden until selected) ----
    #
    # Reuses TemplateCanvas as-is (Stage 11E-11J's region-drawing widget) -
    # region_drawn/polygon_region_drawn are wired to Subject-Profile-scoped
    # handlers instead of Template ones. Automatic AI region detection is
    # Stage 12 (see docs/stage12_ai_plan.md) - regions are always manually
    # drawn here, exactly like the existing Template Editor.

    def _build_subject_profile_editor_page(self) -> QWidget:
        self._subject_profile_editor_source = SOURCE_QUESTION_PAPER
        self._subject_profile_editor_page = 1
        self._subject_profile_editor_page_paths: list = []
        self._subject_profile_region_checkboxes: dict = {}
        self._subject_profile_region_undo_stack: List[Callable[[], None]] = []

        page, layout = create_page()
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(6)

        # Title row carries the exit actions so they are always visible -
        # the page is taller than the viewport and a bottom row was clipped.
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.subject_profile_editor_title_label = QLabel("Subject Profile Editor")
        self.subject_profile_editor_title_label.setObjectName("SectionHeading")
        title_row.addWidget(self.subject_profile_editor_title_label)
        title_row.addStretch()
        save_button = QPushButton("Save Subject Profile")
        save_button.setObjectName("PrimaryButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.clicked.connect(self.handle_save_subject_profile_editor)
        title_row.addWidget(save_button)
        back_button = QPushButton("Back to Marking")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_subject_profile_editor)
        title_row.addWidget(back_button)
        layout.addLayout(title_row)

        ai_note = QLabel(
            "\"Detect Answer Regions\" runs the trained AI detector on the page and proposes regions for "
            "your review - accept, move, resize, retype or reject each one; nothing is applied without you. "
            "Manual drawing always stays available."
        )
        ai_note.setObjectName("StatusLabel")
        ai_note.setWordWrap(True)
        layout.addWidget(ai_note)

        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        self.subject_profile_qp_source_button = QPushButton("Question Paper")
        self.subject_profile_qp_source_button.setCheckable(True)
        self.subject_profile_qp_source_button.setChecked(True)
        self.subject_profile_qp_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_qp_source_button.clicked.connect(
            lambda: self.handle_switch_subject_profile_source(SOURCE_QUESTION_PAPER)
        )
        source_row.addWidget(self.subject_profile_qp_source_button)

        self.subject_profile_as_source_button = QPushButton("Answer Scheme")
        self.subject_profile_as_source_button.setCheckable(True)
        self.subject_profile_as_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_as_source_button.clicked.connect(
            lambda: self.handle_switch_subject_profile_source(SOURCE_ANSWER_SCHEME)
        )
        source_row.addWidget(self.subject_profile_as_source_button)
        # Source toggle and page navigation share one row: sources left,
        # page nav right, breathing room between the groups.
        source_row.addStretch()

        page_nav_row = source_row
        page_nav_row.setSpacing(10)
        self.subject_profile_prev_page_button = QPushButton("< Previous Page")
        self.subject_profile_prev_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_prev_page_button.clicked.connect(self.handle_subject_profile_prev_page)
        page_nav_row.addWidget(self.subject_profile_prev_page_button)

        self.subject_profile_page_label = QLabel("Page 1 of 1")
        self.subject_profile_page_label.setObjectName("FieldLabel")
        page_nav_row.addWidget(self.subject_profile_page_label)

        self.subject_profile_next_page_button = QPushButton("Next Page >")
        self.subject_profile_next_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_next_page_button.clicked.connect(self.handle_subject_profile_next_page)
        page_nav_row.addWidget(self.subject_profile_next_page_button)
        layout.addLayout(page_nav_row)

        # Drawing tools left, AI detection + utilities right - two clear
        # groups instead of four left-packed rows.
        draw_mode_row = QHBoxLayout()
        draw_mode_row.setSpacing(10)
        self.subject_profile_draw_rectangle_button = QPushButton("Draw Rectangle Region")
        self.subject_profile_draw_rectangle_button.setCheckable(True)
        self.subject_profile_draw_rectangle_button.setChecked(True)
        self.subject_profile_draw_rectangle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_draw_rectangle_button.clicked.connect(self.handle_set_subject_profile_rectangle_mode)
        draw_mode_row.addWidget(self.subject_profile_draw_rectangle_button)

        self.subject_profile_draw_polygon_button = QPushButton("Draw Polygon Region")
        self.subject_profile_draw_polygon_button.setCheckable(True)
        self.subject_profile_draw_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_draw_polygon_button.clicked.connect(self.handle_set_subject_profile_polygon_mode)
        draw_mode_row.addWidget(self.subject_profile_draw_polygon_button)

        self.subject_profile_finish_polygon_button = QPushButton("Finish Polygon")
        self.subject_profile_finish_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_finish_polygon_button.clicked.connect(self.handle_finish_subject_profile_polygon)
        self.subject_profile_finish_polygon_button.setVisible(False)
        draw_mode_row.addWidget(self.subject_profile_finish_polygon_button)

        self.subject_profile_cancel_polygon_button = QPushButton("Cancel Polygon")
        self.subject_profile_cancel_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subject_profile_cancel_polygon_button.clicked.connect(self.handle_cancel_subject_profile_polygon)
        self.subject_profile_cancel_polygon_button.setVisible(False)
        draw_mode_row.addWidget(self.subject_profile_cancel_polygon_button)
        # Uniform 10px gap between every toolbar button (no mid-row stretch
        # splitting them into two far-apart groups).

        suggest_row = draw_mode_row
        self.core_ai2_proposals_button = QPushButton("Detect Answer Regions — This Page")
        self.core_ai2_proposals_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.core_ai2_proposals_button.setToolTip(
            "Run the trained Core AI 2 detector on this page. Proposals are reviewed and accepted "
            "individually - nothing is applied automatically, and manual drawing always remains available.")
        self.core_ai2_proposals_button.clicked.connect(self.handle_subject_profile_run_proposals)
        suggest_row.addWidget(self.core_ai2_proposals_button)

        self.core_ai2_proposals_all_button = QPushButton("Detect Answer Regions — All Pages")
        self.core_ai2_proposals_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.core_ai2_proposals_all_button.setToolTip(
            "Run the trained Core AI 2 detector on every rendered page of this document. "
            "Proposals are reviewed and accepted individually or with Apply All Proposals - "
            "nothing is applied automatically.")
        self.core_ai2_proposals_all_button.clicked.connect(
            self.handle_subject_profile_run_proposals_all_pages)
        suggest_row.addWidget(self.core_ai2_proposals_all_button)

        self.core_ai2_apply_all_button = QPushButton("Accept All Detected Regions")
        self.core_ai2_apply_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.core_ai2_apply_all_button.setToolTip(
            "Accept every pending Core AI 2 proposal on this document as a normal editable "
            "region (one confirmation first). Existing manual regions are never overwritten.")
        self.core_ai2_apply_all_button.clicked.connect(self.handle_apply_all_proposals)
        suggest_row.addWidget(self.core_ai2_apply_all_button)

        self.preview_answer_scheme_button = QPushButton("Preview Answer Scheme Answers")
        self.preview_answer_scheme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_answer_scheme_button.clicked.connect(self.handle_preview_answer_scheme_answers)
        suggest_row.addWidget(self.preview_answer_scheme_button)
        suggest_row.addStretch()
        layout.addLayout(suggest_row)

        self.subject_profile_editor_status_label = QLabel("")
        self.subject_profile_editor_status_label.setObjectName("StatusLabel")
        self.subject_profile_editor_status_label.setWordWrap(True)
        layout.addWidget(self.subject_profile_editor_status_label)

        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        self.subject_profile_canvas = TemplateCanvas()
        self.subject_profile_canvas.setMinimumHeight(560)
        apply_card_shadow(self.subject_profile_canvas)
        self.subject_profile_canvas.region_drawn.connect(self.handle_subject_profile_region_drawn)
        self.subject_profile_canvas.polygon_region_drawn.connect(self.handle_subject_profile_polygon_region_drawn)
        self.subject_profile_canvas.region_selected.connect(self.handle_subject_profile_canvas_region_selected)
        self.subject_profile_canvas.region_deselected.connect(self.handle_subject_profile_canvas_region_deselected)
        self.subject_profile_canvas.region_moved.connect(self.handle_subject_profile_region_moved)
        self.subject_profile_canvas.polygon_region_moved.connect(self.handle_subject_profile_polygon_region_moved)
        self.subject_profile_canvas.region_resized.connect(self.handle_subject_profile_region_resized)
        body_row.addWidget(self.subject_profile_canvas, stretch=3)

        side_column = QVBoxLayout()
        side_column.setSpacing(6)

        regions_heading = QLabel("Regions (Current Source, All Pages)")
        regions_heading.setObjectName("FieldLabel")
        side_column.addWidget(regions_heading)

        self.subject_profile_regions_table = QTableWidget(0, len(SUBJECT_PROFILE_REGION_TABLE_COLUMNS))
        self.subject_profile_regions_table.setHorizontalHeaderLabels(SUBJECT_PROFILE_REGION_TABLE_HEADERS)
        self.subject_profile_regions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_profile_regions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        regions_header = self.subject_profile_regions_table.horizontalHeader()
        regions_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        regions_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.subject_profile_regions_table.setColumnWidth(0, 30)
        self.subject_profile_regions_table.setColumnWidth(2, 140)
        self.subject_profile_regions_table.setColumnWidth(3, 50)
        self.subject_profile_regions_table.setColumnWidth(4, 150)
        self.subject_profile_regions_table.verticalHeader().setVisible(False)
        self.subject_profile_regions_table.verticalHeader().setDefaultSectionSize(40)
        self.subject_profile_regions_table.setAlternatingRowColors(True)
        self.subject_profile_regions_table.setMinimumWidth(360)
        self.subject_profile_regions_table.itemSelectionChanged.connect(
            self.handle_subject_profile_region_table_selection_changed
        )
        apply_card_shadow(self.subject_profile_regions_table)
        side_column.addWidget(self.subject_profile_regions_table, stretch=1)

        self.create_subject_profile_group_button = QPushButton("Create Group / Combine Selected")
        self.create_subject_profile_group_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_subject_profile_group_button.clicked.connect(self.handle_create_subject_profile_region_group)
        side_column.addWidget(self.create_subject_profile_group_button)

        groups_heading = QLabel("Region Groups")
        groups_heading.setObjectName("FieldLabel")
        side_column.addWidget(groups_heading)

        self.subject_profile_region_groups_table = QTableWidget(0, len(SUBJECT_PROFILE_REGION_GROUP_TABLE_COLUMNS))
        self.subject_profile_region_groups_table.setHorizontalHeaderLabels(SUBJECT_PROFILE_REGION_GROUP_TABLE_HEADERS)
        self.subject_profile_region_groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_profile_region_groups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        groups_header = self.subject_profile_region_groups_table.horizontalHeader()
        groups_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        groups_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.subject_profile_region_groups_table.setColumnWidth(0, 90)
        self.subject_profile_region_groups_table.setColumnWidth(2, 80)
        self.subject_profile_region_groups_table.setColumnWidth(3, 150)
        self.subject_profile_region_groups_table.verticalHeader().setVisible(False)
        self.subject_profile_region_groups_table.verticalHeader().setDefaultSectionSize(40)
        self.subject_profile_region_groups_table.setAlternatingRowColors(True)
        self.subject_profile_region_groups_table.setMinimumWidth(360)
        apply_card_shadow(self.subject_profile_region_groups_table)
        side_column.addWidget(self.subject_profile_region_groups_table, stretch=1)

        extracted_heading = QLabel("Extracted Content (Current Source)")
        extracted_heading.setObjectName("FieldLabel")
        side_column.addWidget(extracted_heading)

        self.subject_profile_extracted_content_view = QPlainTextEdit()
        self.subject_profile_extracted_content_view.setReadOnly(True)
        self.subject_profile_extracted_content_view.setMaximumHeight(120)
        side_column.addWidget(self.subject_profile_extracted_content_view)

        answer_key_heading = QLabel("Answer Key (Confirm / Edit)")
        answer_key_heading.setObjectName("FieldLabel")
        side_column.addWidget(answer_key_heading)

        # Marking Fix Follow-up 3 (requirement 2): lets a teacher auto-fill
        # Q1-Q40 from the answer scheme's own printed answer list instead
        # of typing all 40 in by hand - see handle_extract_answer_key_
        # from_answer_scheme / extract_answer_key_from_answer_scheme.
        self.extract_answer_key_button = QPushButton("Fill Answer Key from Scheme")
        self.extract_answer_key_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.extract_answer_key_button.clicked.connect(self.handle_extract_answer_key_from_answer_scheme)
        side_column.addWidget(self.extract_answer_key_button)

        self.subject_profile_answer_key_table = QTableWidget(0, len(SUBJECT_PROFILE_ANSWER_KEY_TABLE_COLUMNS))
        self.subject_profile_answer_key_table.setHorizontalHeaderLabels(SUBJECT_PROFILE_ANSWER_KEY_TABLE_HEADERS)
        self.subject_profile_answer_key_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_profile_answer_key_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        answer_key_header = self.subject_profile_answer_key_table.horizontalHeader()
        answer_key_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        answer_key_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.subject_profile_answer_key_table.setColumnWidth(0, 70)
        self.subject_profile_answer_key_table.setColumnWidth(2, 70)
        self.subject_profile_answer_key_table.setColumnWidth(3, 80)
        self.subject_profile_answer_key_table.verticalHeader().setVisible(False)
        self.subject_profile_answer_key_table.verticalHeader().setDefaultSectionSize(40)
        self.subject_profile_answer_key_table.setAlternatingRowColors(True)
        self.subject_profile_answer_key_table.setMinimumWidth(360)
        apply_card_shadow(self.subject_profile_answer_key_table)
        side_column.addWidget(self.subject_profile_answer_key_table, stretch=1)

        body_row.addLayout(side_column, stretch=2)
        layout.addLayout(body_row, stretch=1)

        return page

    def _build_subject_profile_region_action_cell(self, region) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, r=region: self.handle_edit_subject_profile_region(r))
        cell_layout.addWidget(edit_button)

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("RowActionButton")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False, r=region: self.handle_remove_subject_profile_region(r))
        cell_layout.addWidget(remove_button)

        return cell

    def _build_subject_profile_region_group_action_cell(self, group) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, g=group: self.handle_edit_subject_profile_region_group(g))
        cell_layout.addWidget(edit_button)

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("RowActionButton")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False, g=group: self.handle_remove_subject_profile_region_group(g))
        cell_layout.addWidget(remove_button)

        return cell

    def _build_subject_profile_answer_key_action_cell(self, entry_or_target) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(
            lambda _checked=False, t=entry_or_target: self.handle_edit_subject_profile_answer_key(t)
        )
        cell_layout.addWidget(edit_button)
        return cell

    # --- Marking Editor page (Stage 11V, hidden until selected) -------------

    def _build_subject_profile_marking_editor_page(self) -> QWidget:
        self._marking_editor_answer_file_id: Optional[int] = None
        self._marking_editor_page_index = 1
        self._marking_editor_page_paths: list = []
        self._marking_editor_overlay_by_id: dict = {}

        page, layout = create_page()
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(6)

        self.marking_editor_title_label = QLabel("Marking Editor")
        self.marking_editor_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.marking_editor_title_label)

        page_nav_row = QHBoxLayout()
        page_nav_row.setSpacing(10)
        self.marking_editor_prev_page_button = QPushButton("< Previous Page")
        self.marking_editor_prev_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_editor_prev_page_button.clicked.connect(self.handle_marking_editor_prev_page)
        page_nav_row.addWidget(self.marking_editor_prev_page_button)

        self.marking_editor_page_label = QLabel("Page 1 of 1")
        self.marking_editor_page_label.setObjectName("FieldLabel")
        page_nav_row.addWidget(self.marking_editor_page_label)

        self.marking_editor_next_page_button = QPushButton("Next Page >")
        self.marking_editor_next_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_editor_next_page_button.clicked.connect(self.handle_marking_editor_next_page)
        page_nav_row.addWidget(self.marking_editor_next_page_button)

        self.mark_answers_button = QPushButton("Mark Answers")
        self.mark_answers_button.setObjectName("PrimaryButton")
        self.mark_answers_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mark_answers_button.clicked.connect(self.handle_mark_answers_clicked)
        page_nav_row.addWidget(self.mark_answers_button)
        page_nav_row.addStretch()
        # Always-visible exit: the page is taller than the viewport, so a
        # bottom-row button was clipped until the teacher scrolled.
        marking_editor_back_button = QPushButton("Back to Marking")
        marking_editor_back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        marking_editor_back_button.clicked.connect(lambda: self.shell.show_page("Marking"))
        page_nav_row.addWidget(marking_editor_back_button)
        layout.addLayout(page_nav_row)

        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        self.marking_editor_canvas = OverlayCanvas()
        self.marking_editor_canvas.setMinimumHeight(600)
        apply_card_shadow(self.marking_editor_canvas)
        body_row.addWidget(self.marking_editor_canvas, stretch=3)

        sections_column = QVBoxLayout()
        sections_column.setSpacing(8)

        # Stage 12G-1A: Teacher Review summary + workflow actions.
        self.marking_editor_review_section = CollapsibleSection("Teacher Review")
        self.review_summary_label = QLabel("No marked answers yet.")
        self.review_summary_label.setObjectName("StatusLabel")
        self.review_summary_label.setWordWrap(True)
        self.marking_editor_review_section.add_widget(self.review_summary_label)
        review_actions = QWidget()
        review_actions_layout = QHBoxLayout(review_actions)
        review_actions_layout.setContentsMargins(0, 4, 0, 0)
        review_actions_layout.setSpacing(6)
        self.review_save_draft_button = QPushButton("Save Draft")
        self.review_save_draft_button.setObjectName("RowActionButton")
        self.review_save_draft_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_save_draft_button.clicked.connect(self.handle_save_review_draft)
        review_actions_layout.addWidget(self.review_save_draft_button)
        self.review_finalise_button = QPushButton("Finalise Marking")
        self.review_finalise_button.setObjectName("CtaButton")
        self.review_finalise_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_finalise_button.clicked.connect(self.handle_finalise_review)
        review_actions_layout.addWidget(self.review_finalise_button)
        self.review_reopen_button = QPushButton("Reopen for Editing")
        self.review_reopen_button.setObjectName("RowActionButton")
        self.review_reopen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_reopen_button.clicked.connect(self.handle_reopen_review)
        review_actions_layout.addWidget(self.review_reopen_button)
        review_actions_layout.addStretch()
        self.marking_editor_review_section.add_widget(review_actions)
        sections_column.addWidget(self.marking_editor_review_section)

        self.marking_editor_regions_section = CollapsibleSection("Regions")
        self.marking_editor_regions_table = QTableWidget(0, 3)
        self.marking_editor_regions_table.setHorizontalHeaderLabels(["Label", "Type", "Page"])
        self.marking_editor_regions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_editor_regions_table.verticalHeader().setVisible(False)
        self.marking_editor_regions_table.setMaximumHeight(160)
        self.marking_editor_regions_section.add_widget(self.marking_editor_regions_table)
        sections_column.addWidget(self.marking_editor_regions_section)

        self.marking_editor_groups_section = CollapsibleSection("Region Groups", expanded=False)
        self.marking_editor_groups_table = QTableWidget(0, 2)
        self.marking_editor_groups_table.setHorizontalHeaderLabels(["Group", "Type"])
        self.marking_editor_groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_editor_groups_table.verticalHeader().setVisible(False)
        self.marking_editor_groups_table.setMaximumHeight(160)
        self.marking_editor_groups_section.add_widget(self.marking_editor_groups_table)
        sections_column.addWidget(self.marking_editor_groups_section)

        self.marking_editor_extracted_section = CollapsibleSection("Extracted Content", expanded=False)
        self.marking_editor_extracted_view = QPlainTextEdit()
        self.marking_editor_extracted_view.setReadOnly(True)
        self.marking_editor_extracted_view.setMaximumHeight(140)
        self.marking_editor_extracted_section.add_widget(self.marking_editor_extracted_view)
        sections_column.addWidget(self.marking_editor_extracted_section)

        self.marking_editor_comment_section = CollapsibleSection("Marking / Comment")
        # Stage 12G-1A: a fixed, always-visible primary entry point to the
        # answer editor - no need to horizontally scroll to a hidden action
        # column. Select a row (or double-click it) then click this button.
        review_entry_row = QWidget()
        review_entry_layout = QHBoxLayout(review_entry_row)
        review_entry_layout.setContentsMargins(0, 0, 0, 4)
        self.review_selected_button = QPushButton("Check Detected Text")
        self.review_selected_button.setObjectName("PrimaryButton")
        self.review_selected_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_selected_button.clicked.connect(self.handle_review_selected_answer)
        review_entry_layout.addWidget(self.review_selected_button)
        hint = QLabel("(select a row, or double-click it)")
        hint.setObjectName("StatusLabel")
        review_entry_layout.addWidget(hint)
        review_entry_layout.addStretch()
        self.marking_editor_comment_section.add_widget(review_entry_row)

        # Stage 12G-6: Core AI 1 draft scoring. Drafts are suggestions the
        # teacher may apply, edit or ignore - they are never a final score and
        # every one of these actions is explicit.
        draft_row = QWidget()
        draft_layout = QHBoxLayout(draft_row)
        draft_layout.setContentsMargins(0, 0, 0, 4)
        for text, slot, attr in (
            ("Suggest Scores (AI)", self.handle_generate_core_ai1_drafts,
             "core_ai1_generate_drafts_button"),
            ("Re-suggest for Selected", self.handle_regenerate_core_ai1_draft,
             "core_ai1_regenerate_draft_button"),
            ("View Draft Details", self.handle_view_core_ai1_draft,
             "core_ai1_view_draft_button"),
            ("Apply Draft to My Score", self.handle_apply_core_ai1_draft,
             "core_ai1_apply_draft_button"),
            ("Dismiss Draft", self.handle_dismiss_core_ai1_draft,
             "core_ai1_dismiss_draft_button"),
            ("Write Feedback for Me (AI)", self.handle_generate_feedback_wording,
             "feedback_generate_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            setattr(self, attr, button)
            draft_layout.addWidget(button)
        draft_layout.addStretch()
        self.marking_editor_comment_section.add_widget(draft_row)

        self.core_ai1_draft_status_label = QLabel(
            "AI score suggestions apply to Kertas 2 writing answers only. Your score and "
            "feedback stay yours - applying a suggestion fills in your own entry, which you can "
            "still edit. Kertas 1 marking remains rule-based.")
        self.core_ai1_draft_status_label.setObjectName("StatusLabel")
        self.core_ai1_draft_status_label.setWordWrap(True)
        self.marking_editor_comment_section.add_widget(self.core_ai1_draft_status_label)

        # Stage 12G-12: a stale draft is called out in its own full-width
        # banner, so the reason is never truncated by the table column. It says
        # what went stale and what to do, and the Apply action is disabled
        # while it shows.
        self.core_ai1_stale_banner = QLabel("")
        self.core_ai1_stale_banner.setObjectName("StatusLabel")
        self.core_ai1_stale_banner.setWordWrap(True)
        self.core_ai1_stale_banner.setStyleSheet(
            "color: #c0392b; font-weight: 600; padding: 4px 0;")
        self.core_ai1_stale_banner.setVisible(False)
        self.marking_editor_comment_section.add_widget(self.core_ai1_stale_banner)

        self.marking_editor_comment_table = QTableWidget(0, len(MARKING_COMMENT_TABLE_COLUMNS))
        self.marking_editor_comment_table.setHorizontalHeaderLabels(MARKING_COMMENT_TABLE_HEADERS)
        self.marking_editor_comment_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_editor_comment_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_editor_comment_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.marking_editor_comment_table.verticalHeader().setVisible(False)
        self.marking_editor_comment_table.setMaximumHeight(220)
        self.marking_editor_comment_table.cellDoubleClicked.connect(self.handle_comment_row_double_clicked)
        self.marking_editor_comment_table.itemSelectionChanged.connect(
            self._refresh_core_ai1_draft_controls)
        self.marking_editor_comment_section.add_widget(self.marking_editor_comment_table)
        sections_column.addWidget(self.marking_editor_comment_section)
        self._marking_editor_row_marked_ids: list = []

        self.marking_editor_overlay_section = CollapsibleSection("Overlay Marks", expanded=False)
        # Phase 2B: fixed, always-visible overlay-editing toolbar (no horizontal
        # scrolling needed to reach the primary action).
        overlay_toolbar = QHBoxLayout()
        overlay_toolbar.setSpacing(6)
        self.overlay_edit_selected_button = QPushButton("Edit Selected Overlay")
        self.overlay_edit_selected_button.setObjectName("PrimaryButton")
        self.overlay_edit_selected_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_edit_selected_button.clicked.connect(self.handle_edit_selected_overlay)
        overlay_toolbar.addWidget(self.overlay_edit_selected_button)
        self.overlay_refresh_from_review_button = QPushButton("Refresh Overlays from Teacher Review")
        self.overlay_refresh_from_review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_refresh_from_review_button.clicked.connect(self.handle_refresh_overlays_from_review)
        overlay_toolbar.addWidget(self.overlay_refresh_from_review_button)
        self.overlay_regenerate_outputs_button = QPushButton("Regenerate Reviewed Outputs")
        self.overlay_regenerate_outputs_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_regenerate_outputs_button.clicked.connect(self.handle_regenerate_reviewed_outputs)
        overlay_toolbar.addWidget(self.overlay_regenerate_outputs_button)
        # Feedback-note font size: select a red feedback note on the page, then
        # set its point size here. 0 = Auto (size chosen to fit the note's box).
        overlay_toolbar.addSpacing(12)
        self.feedback_font_label = QLabel("Feedback font:")
        overlay_toolbar.addWidget(self.feedback_font_label)
        self.feedback_font_spin = QSpinBox()
        self.feedback_font_spin.setRange(0, 40)
        self.feedback_font_spin.setSpecialValueText("Auto")
        self.feedback_font_spin.setSuffix(" pt")
        self.feedback_font_spin.setToolTip(
            "Select a red feedback note on the page, then set its font size (0 = Auto)."
        )
        self.feedback_font_spin.setEnabled(False)
        self.feedback_font_spin.valueChanged.connect(self.handle_feedback_font_changed)
        overlay_toolbar.addWidget(self.feedback_font_spin)
        self._selected_feedback_overlay_id = None
        self._marking_editor_selected_overlay_id = None
        self._suppress_selection_sync = False
        self.marking_editor_canvas.scene().selectionChanged.connect(self._sync_feedback_font_control)
        overlay_toolbar.addStretch()
        overlay_toolbar_wrap = QWidget()
        overlay_toolbar_wrap.setLayout(overlay_toolbar)
        self.marking_editor_overlay_section.add_widget(overlay_toolbar_wrap)

        self.overlay_lock_hint = QLabel("")
        self.overlay_lock_hint.setObjectName("StatusLabel")
        self.overlay_lock_hint.setWordWrap(True)
        self.marking_editor_overlay_section.add_widget(self.overlay_lock_hint)

        self.marking_editor_overlay_table = QTableWidget(0, len(OVERLAY_TABLE_COLUMNS))
        self.marking_editor_overlay_table.setHorizontalHeaderLabels(OVERLAY_TABLE_HEADERS)
        self.marking_editor_overlay_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_editor_overlay_table.verticalHeader().setVisible(False)
        self.marking_editor_overlay_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_editor_overlay_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.marking_editor_overlay_table.setMaximumHeight(220)
        self.marking_editor_overlay_table.cellDoubleClicked.connect(self.handle_overlay_row_double_clicked)
        self.marking_editor_overlay_table.itemSelectionChanged.connect(self.handle_overlay_row_selected)
        self.marking_editor_overlay_section.add_widget(self.marking_editor_overlay_table)
        self._marking_editor_overlay_row_ids: list = []
        sections_column.addWidget(self.marking_editor_overlay_section)

        # --- Phase 2C: attempt-specific Region Review panel ---
        self.marking_editor_region_section = CollapsibleSection("Region Review", expanded=False)
        region_toolbar = QHBoxLayout()
        region_toolbar.setSpacing(6)
        self.region_edit_button = QPushButton("Edit Region Override")
        self.region_edit_button.setObjectName("PrimaryButton")
        self.region_edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.region_edit_button.clicked.connect(self.handle_edit_selected_region)
        region_toolbar.addWidget(self.region_edit_button)
        self.region_rerun_ocr_button = QPushButton("Rerun OCR")
        self.region_rerun_ocr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.region_rerun_ocr_button.clicked.connect(self.handle_rerun_region_ocr)
        region_toolbar.addWidget(self.region_rerun_ocr_button)
        self.region_reconfirm_button = QPushButton("Reconfirm Review")
        self.region_reconfirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.region_reconfirm_button.clicked.connect(self.handle_reconfirm_region_review)
        region_toolbar.addWidget(self.region_reconfirm_button)
        self.region_apply_profile_button = QPushButton("Apply to Subject Profile")
        self.region_apply_profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.region_apply_profile_button.clicked.connect(self.handle_apply_region_to_profile)
        region_toolbar.addWidget(self.region_apply_profile_button)
        region_toolbar.addStretch()
        region_toolbar_wrap = QWidget()
        region_toolbar_wrap.setLayout(region_toolbar)
        self.marking_editor_region_section.add_widget(region_toolbar_wrap)
        self.region_lock_hint = QLabel("")
        self.region_lock_hint.setObjectName("StatusLabel")
        self.region_lock_hint.setWordWrap(True)
        self.marking_editor_region_section.add_widget(self.region_lock_hint)
        self.marking_editor_region_table = QTableWidget(0, len(REGION_TABLE_COLUMNS))
        self.marking_editor_region_table.setHorizontalHeaderLabels(REGION_TABLE_HEADERS)
        self.marking_editor_region_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_editor_region_table.verticalHeader().setVisible(False)
        self.marking_editor_region_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_editor_region_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.marking_editor_region_table.setMaximumHeight(220)
        self.marking_editor_region_table.cellDoubleClicked.connect(self.handle_region_row_double_clicked)
        self.marking_editor_region_section.add_widget(self.marking_editor_region_table)
        self._marking_editor_region_row_labels: list = []
        sections_column.addWidget(self.marking_editor_region_section)

        # --- Stage 12G-1B: Separate Answer Paper mapping workspace ---
        self.marking_editor_sap_section = CollapsibleSection("Map Separate Answer Paper", expanded=False)
        self.sap_mode_label = QLabel("")
        self.sap_mode_label.setObjectName("StatusLabel")
        self.sap_mode_label.setWordWrap(True)
        self.marking_editor_sap_section.add_widget(self.sap_mode_label)

        sap_page_row = QHBoxLayout()
        self.sap_prev_page_button = QPushButton("< Page")
        self.sap_prev_page_button.clicked.connect(self.handle_sap_prev_page)
        sap_page_row.addWidget(self.sap_prev_page_button)
        self.sap_page_label = QLabel("Page - of -")
        sap_page_row.addWidget(self.sap_page_label)
        self.sap_next_page_button = QPushButton("Page >")
        self.sap_next_page_button.clicked.connect(self.handle_sap_next_page)
        sap_page_row.addWidget(self.sap_next_page_button)
        self.sap_move_page_up_button = QPushButton("Move Page Up")
        self.sap_move_page_up_button.clicked.connect(lambda: self.handle_sap_reorder_page(-1))
        sap_page_row.addWidget(self.sap_move_page_up_button)
        self.sap_move_page_down_button = QPushButton("Move Page Down")
        self.sap_move_page_down_button.clicked.connect(lambda: self.handle_sap_reorder_page(1))
        sap_page_row.addWidget(self.sap_move_page_down_button)
        sap_page_row.addStretch()
        sap_page_wrap = QWidget()
        sap_page_wrap.setLayout(sap_page_row)
        self.marking_editor_sap_section.add_widget(sap_page_wrap)

        self.sap_page_preview_label = QLabel("(no page preview)")
        self.sap_page_preview_label.setMinimumHeight(220)
        self.sap_page_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sap_page_preview_label.setStyleSheet("border: 1px solid #ccc;")
        self.marking_editor_sap_section.add_widget(self.sap_page_preview_label)

        self.sap_counts_label = QLabel("")
        self.sap_counts_label.setObjectName("StatusLabel")
        self.sap_counts_label.setWordWrap(True)
        self.marking_editor_sap_section.add_widget(self.sap_counts_label)

        sap_actions = QHBoxLayout()
        for text, slot, attr in (
            ("Add Mapping", self.handle_sap_add_mapping, "sap_add_mapping_button"),
            ("Edit Mapping", self.handle_sap_edit_mapping, "sap_edit_mapping_button"),
            ("Delete Mapping", self.handle_sap_delete_mapping, "sap_delete_mapping_button"),
            ("Mark Blank", self.handle_sap_mark_blank, "sap_mark_blank_button"),
            ("Clear Blank", self.handle_sap_clear_blank, "sap_clear_blank_button"),
        ):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            setattr(self, attr, button)
            sap_actions.addWidget(button)
        sap_actions.addStretch()
        sap_actions_wrap = QWidget()
        sap_actions_wrap.setLayout(sap_actions)
        self.marking_editor_sap_section.add_widget(sap_actions_wrap)

        sap_actions2 = QHBoxLayout()
        for text, slot, attr in (
            ("Rerun OCR", self.handle_sap_rerun_ocr, "sap_rerun_ocr_button"),
            ("Parse K1 Block", self.handle_sap_parse_block, "sap_parse_block_button"),
            ("K1 Parser Review", self.handle_sap_open_parser_review, "sap_parser_review_button"),
            ("Confirm Part 3 Question", self.handle_sap_confirm_part3, "sap_part3_button"),
            ("Detect Answer Regions (AI)", self.handle_sap_run_proposals, "sap_proposals_button"),
            ("Load into Teacher Review", self.handle_sap_sync_review, "sap_sync_button"),
        ):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            setattr(self, attr, button)
            sap_actions2.addWidget(button)
        sap_actions2.addStretch()
        sap_actions2_wrap = QWidget()
        sap_actions2_wrap.setLayout(sap_actions2)
        self.marking_editor_sap_section.add_widget(sap_actions2_wrap)

        self.sap_target_table = QTableWidget(0, len(SAP_TARGET_TABLE_COLUMNS))
        self.sap_target_table.setHorizontalHeaderLabels(SAP_TARGET_TABLE_HEADERS)
        self.sap_target_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sap_target_table.verticalHeader().setVisible(False)
        self.sap_target_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sap_target_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sap_target_table.setMaximumHeight(200)
        self.sap_target_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sap_target_table.itemSelectionChanged.connect(self.handle_sap_target_selected)
        self.marking_editor_sap_section.add_widget(self.sap_target_table)

        self.sap_mapping_table = QTableWidget(0, len(SAP_MAPPING_TABLE_COLUMNS))
        self.sap_mapping_table.setHorizontalHeaderLabels(SAP_MAPPING_TABLE_HEADERS)
        self.sap_mapping_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sap_mapping_table.verticalHeader().setVisible(False)
        self.sap_mapping_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sap_mapping_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sap_mapping_table.setMaximumHeight(160)
        self.sap_mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.marking_editor_sap_section.add_widget(self.sap_mapping_table)

        self.sap_combined_text_label = QLabel("")
        self.sap_combined_text_label.setObjectName("StatusLabel")
        self.sap_combined_text_label.setWordWrap(True)
        self.marking_editor_sap_section.add_widget(self.sap_combined_text_label)

        self._sap_target_rows: list = []
        self._sap_mapping_rows: list = []
        self._sap_page_index = 1
        sections_column.addWidget(self.marking_editor_sap_section)

        sections_column.addStretch()
        body_row.addLayout(sections_column, stretch=2)
        layout.addLayout(body_row, stretch=1)

        return page

    def _build_marking_session_action_cell(self, row: MainMarkingSessionRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View / Manage")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_open_marking_session(r))
        cell_layout.addWidget(view_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, r=row: self.handle_delete_marking_session(r))
        cell_layout.addWidget(delete_button)

        return cell

    # --- Main Marking System: Marking Session detail/manage (Stage 11L) -----

    def _build_marking_session_detail_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(8)

        self.marking_session_detail_title_label = QLabel("Marking Session")
        self.marking_session_detail_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.marking_session_detail_title_label)

        self.marking_session_detail_subtitle_label = QLabel("")
        self.marking_session_detail_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.marking_session_detail_subtitle_label)

        form_group = QGroupBox("Session Files")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        form_layout.addWidget(self._field_label("Question Paper"))
        self.marking_session_detail_question_paper_label = QLabel("Not available")
        self.marking_session_detail_question_paper_label.setObjectName("StatusLabel")
        self.marking_session_detail_question_paper_label.setWordWrap(True)
        form_layout.addWidget(self.marking_session_detail_question_paper_label)

        form_layout.addWidget(self._field_label("Answer Key / Marking Scheme"))
        self.marking_session_detail_answer_key_label = QLabel("Not available")
        self.marking_session_detail_answer_key_label.setObjectName("StatusLabel")
        self.marking_session_detail_answer_key_label.setWordWrap(True)
        form_layout.addWidget(self.marking_session_detail_answer_key_label)

        layout.addWidget(form_group)

        template_group = QGroupBox("Linked Template")
        apply_card_shadow(template_group)
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(4)

        self.marking_session_template_info_label = QLabel("No template linked.")
        self.marking_session_template_info_label.setObjectName("StatusLabel")
        self.marking_session_template_info_label.setWordWrap(True)
        template_layout.addWidget(self.marking_session_template_info_label)

        self.marking_session_template_targets_label = QLabel("")
        self.marking_session_template_targets_label.setObjectName("StatusLabel")
        self.marking_session_template_targets_label.setWordWrap(True)
        template_layout.addWidget(self.marking_session_template_targets_label)

        self.marking_session_template_readiness_label = QLabel("")
        self.marking_session_template_readiness_label.setObjectName("StatusLabel")
        self.marking_session_template_readiness_label.setWordWrap(True)
        template_layout.addWidget(self.marking_session_template_readiness_label)

        template_buttons_row = QHBoxLayout()
        template_buttons_row.setSpacing(16)

        self.marking_session_choose_template_button = QPushButton("Choose Template")
        self.marking_session_choose_template_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_choose_template_button.clicked.connect(self.handle_choose_marking_session_template)
        template_buttons_row.addWidget(self.marking_session_choose_template_button)

        self.marking_session_remove_template_button = QPushButton("Remove Template")
        self.marking_session_remove_template_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_remove_template_button.setEnabled(False)
        self.marking_session_remove_template_button.clicked.connect(self.handle_remove_marking_session_template)
        template_buttons_row.addWidget(self.marking_session_remove_template_button)

        template_buttons_row.addStretch()
        template_layout.addLayout(template_buttons_row)

        layout.addWidget(template_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        add_files_button = QPushButton("Add Student Answer PDFs")
        add_files_button.setObjectName("PrimaryButton")
        add_files_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_files_button.clicked.connect(self.handle_add_marking_session_answer_files)
        buttons_row.addWidget(add_files_button)

        self.marking_session_run_preprocessing_button = QPushButton("Run Preprocessing")
        self.marking_session_run_preprocessing_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_run_preprocessing_button.setEnabled(False)
        self.marking_session_run_preprocessing_button.clicked.connect(self.handle_run_marking_session_preprocessing)
        buttons_row.addWidget(self.marking_session_run_preprocessing_button)

        self.marking_session_run_ocr_button = QPushButton("Run OCR")
        self.marking_session_run_ocr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_run_ocr_button.setEnabled(False)
        self.marking_session_run_ocr_button.clicked.connect(self.handle_run_marking_session_ocr)
        buttons_row.addWidget(self.marking_session_run_ocr_button)

        self.marking_session_run_extraction_button = QPushButton("Run Extraction")
        self.marking_session_run_extraction_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_run_extraction_button.setEnabled(False)
        self.marking_session_run_extraction_button.clicked.connect(self.handle_run_marking_session_extraction)
        buttons_row.addWidget(self.marking_session_run_extraction_button)

        self.marking_session_run_marking_button = QPushButton("Run Marking")
        self.marking_session_run_marking_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_session_run_marking_button.setEnabled(False)
        self.marking_session_run_marking_button.clicked.connect(self.handle_run_marking_session_marking)
        buttons_row.addWidget(self.marking_session_run_marking_button)

        back_button = QPushButton("Back to Marking Sessions")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_marking_session_detail)
        buttons_row.addWidget(back_button)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        answer_files_heading = QLabel("Student Answer Files")
        answer_files_heading.setObjectName("SectionHeading")
        layout.addWidget(answer_files_heading)

        self.marking_session_answer_files_table = QTableWidget(0, len(MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS))
        self.marking_session_answer_files_table.setHorizontalHeaderLabels(MARKING_SESSION_ANSWER_FILE_TABLE_HEADERS)
        self.marking_session_answer_files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_session_answer_files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_session_answer_files_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        answer_files_header = self.marking_session_answer_files_table.horizontalHeader()
        answer_files_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        answer_files_header.setSectionResizeMode(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("display_name"), QHeaderView.ResizeMode.Stretch
        )
        self.marking_session_answer_files_table.setColumnWidth(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("student_name"), 130
        )
        self.marking_session_answer_files_table.setColumnWidth(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("student_code"), 110
        )
        self.marking_session_answer_files_table.setColumnWidth(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("page_count"), 60
        )
        self.marking_session_answer_files_table.setColumnWidth(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("processing_status"), 130
        )
        self.marking_session_answer_files_table.setColumnWidth(
            MARKING_SESSION_ANSWER_FILE_TABLE_COLUMNS.index("action"), 530
        )
        self.marking_session_answer_files_table.verticalHeader().setVisible(False)
        self.marking_session_answer_files_table.verticalHeader().setDefaultSectionSize(44)
        self.marking_session_answer_files_table.setAlternatingRowColors(True)
        self.marking_session_answer_files_table.setMinimumHeight(240)
        apply_card_shadow(self.marking_session_answer_files_table)
        layout.addWidget(self.marking_session_answer_files_table)

        layout.addStretch()
        return page

    def _build_marking_session_answer_file_action_cell(self, answer_file: MainMarkingAnswerFile) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit Info")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_edit_marking_session_answer_file_student_info(f)
        )
        cell_layout.addWidget(edit_button)

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("RowActionButton")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_remove_marking_session_answer_file(f)
        )
        cell_layout.addWidget(remove_button)

        view_extracted_button = QPushButton("View Extracted")
        view_extracted_button.setObjectName("RowActionButton")
        view_extracted_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_extracted_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_view_extracted_answers(f)
        )
        cell_layout.addWidget(view_extracted_button)

        view_marking_button = QPushButton("View Marking")
        view_marking_button.setObjectName("RowActionButton")
        view_marking_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_marking_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_view_marked_answers(f)
        )
        cell_layout.addWidget(view_marking_button)

        review_button = QPushButton("Review")
        review_button.setObjectName("RowActionButton")
        review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        review_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_review_answer_file_from_session_detail(f)
        )
        cell_layout.addWidget(review_button)

        finalize_button = QPushButton("Finalize Result")
        finalize_button.setObjectName("RowActionButton")
        finalize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        is_kertas1 = (
            self._current_marking_session is not None
            and self._current_marking_session.paper_type == PAPER_TYPE_KERTAS_1
        )
        is_reviewed_or_finalized = answer_file.processing_status in (
            MAIN_MARKING_PROCESSING_STATUS_REVIEWED, MAIN_MARKING_PROCESSING_STATUS_FINALIZED,
        )
        finalize_button.setEnabled(is_kertas1 and is_reviewed_or_finalized)
        finalize_button.clicked.connect(
            lambda _checked=False, f=answer_file: self.handle_finalize_main_marking_answer_file(f)
        )
        cell_layout.addWidget(finalize_button)

        return cell

    def _build_review_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(8)

        title = QLabel("Review")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel(
            "Review draft Kertas 1 marking for legacy standalone Main Marking sessions (created "
            "without a Subject Profile). Subject Profile attempts are reviewed and finalised in the "
            "Marking Editor instead, and finalised results appear on the Results page. Class and "
            "revision submissions are reviewed from Attempts / Workflow."
        )
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.main_marking_review_empty_label = QLabel(
            "No Main Marking answer files are ready for review yet. Run Kertas 1 marking for a session first."
        )
        self.main_marking_review_empty_label.setObjectName("StatusLabel")
        self.main_marking_review_empty_label.setWordWrap(True)
        layout.addWidget(self.main_marking_review_empty_label)

        self.main_marking_review_table = QTableWidget(0, len(MAIN_MARKING_REVIEW_TABLE_COLUMNS))
        self.main_marking_review_table.setHorizontalHeaderLabels(MAIN_MARKING_REVIEW_TABLE_HEADERS)
        self.main_marking_review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.main_marking_review_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.main_marking_review_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        review_header = self.main_marking_review_table.horizontalHeader()
        review_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        review_header.setSectionResizeMode(
            MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("session_title"), QHeaderView.ResizeMode.Stretch
        )
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("paper_type"), 90)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("answer_file"), 180)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("student_name"), 130)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("student_code"), 110)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("marking_status"), 120)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("review_status"), 150)
        self.main_marking_review_table.setColumnWidth(MAIN_MARKING_REVIEW_TABLE_COLUMNS.index("action"), 100)
        self.main_marking_review_table.verticalHeader().setVisible(False)
        self.main_marking_review_table.verticalHeader().setDefaultSectionSize(44)
        self.main_marking_review_table.setAlternatingRowColors(True)
        self.main_marking_review_table.setMinimumHeight(240)
        apply_card_shadow(self.main_marking_review_table)
        layout.addWidget(self.main_marking_review_table)

        layout.addStretch()
        return page

    def _build_main_marking_review_action_cell(self, file_row: ReviewableMainMarkingFile) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        review_button = QPushButton("Review")
        review_button.setObjectName("RowActionButton")
        review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        review_button.clicked.connect(lambda _checked=False, f=file_row: self.handle_open_main_marking_review(f))
        cell_layout.addWidget(review_button)

        return cell

    def _build_main_marking_review_detail_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(8)

        self.main_marking_review_detail_title_label = QLabel("Review")
        self.main_marking_review_detail_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.main_marking_review_detail_title_label)

        self.main_marking_review_detail_subtitle_label = QLabel("")
        self.main_marking_review_detail_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.main_marking_review_detail_subtitle_label)

        note = QLabel(
            "Overriding a score/feedback here only updates this Main Marking review - it does not create "
            "a finalized result. The Results page is unaffected until a later stage."
        )
        note.setObjectName("StatusLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        self.main_marking_mark_file_reviewed_button = QPushButton("Mark Answer File Reviewed")
        self.main_marking_mark_file_reviewed_button.setObjectName("PrimaryButton")
        self.main_marking_mark_file_reviewed_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_marking_mark_file_reviewed_button.setEnabled(False)
        self.main_marking_mark_file_reviewed_button.clicked.connect(
            self.handle_mark_main_marking_answer_file_reviewed
        )
        buttons_row.addWidget(self.main_marking_mark_file_reviewed_button)

        back_button = QPushButton("Back to Review")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_main_marking_review_detail)
        buttons_row.addWidget(back_button)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        self.main_marking_review_detail_table = QTableWidget(0, len(MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS))
        self.main_marking_review_detail_table.setHorizontalHeaderLabels(MAIN_MARKING_REVIEW_DETAIL_TABLE_HEADERS)
        self.main_marking_review_detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.main_marking_review_detail_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.main_marking_review_detail_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        detail_header = self.main_marking_review_detail_table.horizontalHeader()
        detail_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        detail_header.setSectionResizeMode(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("student_answer"), QHeaderView.ResizeMode.Stretch
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("target_label"), 110
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("target_kind"), 80
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("correct_answer"), 160
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("machine_score"), 110
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("teacher_score"), 110
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("review_status"), 130
        )
        self.main_marking_review_detail_table.setColumnWidth(
            MAIN_MARKING_REVIEW_DETAIL_TABLE_COLUMNS.index("action"), 90
        )
        self.main_marking_review_detail_table.verticalHeader().setVisible(False)
        self.main_marking_review_detail_table.verticalHeader().setDefaultSectionSize(44)
        self.main_marking_review_detail_table.setAlternatingRowColors(True)
        self.main_marking_review_detail_table.setMinimumHeight(280)
        apply_card_shadow(self.main_marking_review_detail_table)
        layout.addWidget(self.main_marking_review_detail_table)

        layout.addStretch()
        return page

    def _build_marked_answer_review_action_cell(self, marked_answer: MainMarkingMarkedAnswer) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        review_button = QPushButton("Review")
        review_button.setObjectName("RowActionButton")
        review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        review_button.clicked.connect(
            lambda _checked=False, m=marked_answer: self.handle_review_marked_answer(m)
        )
        cell_layout.addWidget(review_button)

        return cell

    # --- Classes page (system-wide visibility + transfer requests) ---------

    def _build_classes_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Classes")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("All English classes in the system.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, len(CLASS_TABLE_COLUMNS))
        classes_search = attach_table_filter(self.table, "Search classes...")
        layout.addWidget(classes_search)
        self.table.setHorizontalHeaderLabels(CLASS_TABLE_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            len(CLASS_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(len(CLASS_TABLE_COLUMNS) - 1, 220)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(220)
        apply_card_shadow(self.table)
        layout.addWidget(self.table)

        requests_heading = QLabel("Incoming Transfer Requests")
        requests_heading.setObjectName("SectionHeading")
        layout.addWidget(requests_heading)

        requests_subtitle = QLabel("Requests from other teachers to take over your classes.")
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

    def _build_action_cell(self, status: str, class_: ClassWithTeacher, has_pending: bool) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        if status == MY_CLASS_STATUS:
            joined_button = QPushButton("Joined")
            joined_button.setObjectName("RowActionButton")
            joined_button.setEnabled(False)
            cell_layout.addWidget(joined_button)

            view_students_button = QPushButton("View Students")
            view_students_button.setObjectName("RowActionButton")
            view_students_button.setCursor(Qt.CursorShape.PointingHandCursor)
            view_students_button.clicked.connect(
                lambda _checked=False, c=class_: self.handle_view_students(c)
            )
            cell_layout.addWidget(view_students_button)
            return cell

        if status == AVAILABLE_STATUS:
            button = QPushButton("Join")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, c=class_: self.handle_join_class(c))
        elif has_pending:
            button = QPushButton("Pending")
            button.setEnabled(False)
        else:
            button = QPushButton("Request Transfer")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, c=class_: self.handle_request_transfer(c)
            )

        button.setObjectName("RowActionButton")
        cell_layout.addWidget(button)

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

    # --- Students page (create students, manage class membership) ---------

    def _build_students_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Students")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Create student accounts and manage class membership.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_student_button = QPushButton("+ Create Student")
        create_student_button.setObjectName("PrimaryButton")
        create_student_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_student_button.clicked.connect(self.handle_open_create_student_page)
        header_row.addWidget(create_student_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        add_existing_button = QPushButton("+ Add Existing Student")
        add_existing_button.setObjectName("PrimaryButton")
        add_existing_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_existing_button.clicked.connect(self.handle_add_existing_student)
        header_row.addWidget(add_existing_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        find_by_identifier_button = QPushButton("Find by Code/Username")
        find_by_identifier_button.setCursor(Qt.CursorShape.PointingHandCursor)
        find_by_identifier_button.clicked.connect(self.handle_find_existing_student_by_identifier)
        header_row.addWidget(find_by_identifier_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.total_my_students_card = StatCard("Total My Students", "0")
        self.students_my_classes_card = StatCard("My Classes", "0")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.total_my_students_card)
        cards_row.addWidget(self.students_my_classes_card)
        layout.addLayout(cards_row)

        self.students_table = QTableWidget(0, len(STUDENT_TABLE_COLUMNS))
        students_search = attach_table_filter(
            self.students_table, "Search students by name, code or class...")
        layout.addWidget(students_search)
        self.students_table.setHorizontalHeaderLabels(STUDENT_TABLE_HEADERS)
        self.students_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.students_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.students_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.students_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.students_table.horizontalHeader().setSectionResizeMode(
            len(STUDENT_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.students_table.setColumnWidth(len(STUDENT_TABLE_COLUMNS) - 1, 420)
        self.students_table.verticalHeader().setVisible(False)
        self.students_table.verticalHeader().setDefaultSectionSize(44)
        self.students_table.setAlternatingRowColors(True)
        self.students_table.setMinimumHeight(260)
        apply_card_shadow(self.students_table)
        layout.addWidget(self.students_table)

        transfer_requests_heading = QLabel("Incoming Student Transfer Requests")
        transfer_requests_heading.setObjectName("SectionHeading")
        layout.addWidget(transfer_requests_heading)

        transfer_requests_subtitle = QLabel(
            "Other teachers asking to move a student who is currently in one of your classes."
        )
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

        history_subtitle = QLabel("Requests you made or decided that have since been approved or rejected.")
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

    def _build_student_actions_cell(self, row: TeacherStudentRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        reset_password_button = QPushButton("Reset Password")
        reset_password_button.setObjectName("RowActionButton")
        reset_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_password_button.clicked.connect(lambda _checked=False, r=row: self.handle_reset_student_password(r))
        cell_layout.addWidget(reset_password_button)

        view_password_button = QPushButton("View Password")
        view_password_button.setObjectName("RowActionButton")
        view_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_password_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_student_password(r))
        cell_layout.addWidget(view_password_button)

        remove_button = QPushButton("Remove from Class")
        remove_button.setObjectName("RowActionButton")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False, r=row: self.handle_remove_student(r))
        cell_layout.addWidget(remove_button)

        return cell

    def _build_student_transfer_request_actions_cell(self, request: StudentTransferRequestWithDetails) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

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

    def handle_reset_student_password(self, row: TeacherStudentRow) -> None:
        new_password = prompt_input(
            self,
            "Reset Password",
            f"Enter a new password for '{row.username}'.",
            is_password=True,
        )
        if new_password is None:
            return

        conn = get_connection()
        try:
            try:
                reset_student_password(conn, row.user_id, new_password)
            except ValueError as exc:
                show_error(self, "Reset Password Failed", str(exc))
                return
        finally:
            conn.close()

        show_success(self, "Reset Password", "Password reset successfully.")

    def handle_view_student_password(self, row: TeacherStudentRow) -> None:
        conn = get_connection()
        try:
            password_display = get_student_password_display(conn, row.user_id)
        finally:
            conn.close()

        show_detail(
            self,
            "Student Password",
            f"Student: {row.full_name} ({row.username})\n\nVisible Temporary Password: {password_display}",
        )

    # --- Create Student page (hidden until selected) -----------------------

    def _build_create_student_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Create Student")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Student Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(6)

        self.new_student_username_input = QLineEdit()
        self.new_student_username_input.setPlaceholderText("e.g. TP070498")

        self.new_student_full_name_input = QLineEdit()
        self.new_student_full_name_input.setPlaceholderText("e.g. Ng Jia Chern")

        self.new_student_password_input = QLineEdit()
        self.new_student_password_input.setPlaceholderText("Enter a password")
        self.new_student_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.new_student_show_password_checkbox = QCheckBox("Show password?")
        self.new_student_show_password_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_student_show_password_checkbox.toggled.connect(self.handle_toggle_new_student_show_password)

        self.new_student_class_dropdown = QComboBox()

        form_layout.addWidget(self._field_label("Student ID / Username"))
        form_layout.addWidget(self.new_student_username_input)
        form_layout.addWidget(self._field_label("Full Name"))
        form_layout.addWidget(self.new_student_full_name_input)
        form_layout.addWidget(self._field_label("Password"))
        form_layout.addWidget(self.new_student_password_input)
        form_layout.addWidget(self.new_student_show_password_checkbox)
        form_layout.addWidget(self._field_label("Assign to Class"))
        form_layout.addWidget(self.new_student_class_dropdown)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        create_button = QPushButton("Create Student")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_create_student)

        cancel_button = QPushButton("Cancel / Back to Students")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_create_student)

        buttons_row.addWidget(create_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- Revision Materials page --------------------------------------------

    def _build_revision_materials_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Revision Materials")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Create and manage class revision papers.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_material_button = QPushButton("+ Create Revision Material")
        create_material_button.setObjectName("PrimaryButton")
        create_material_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_material_button.clicked.connect(self.handle_open_create_material_page)
        header_row.addWidget(create_material_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.total_materials_card = StatCard("Total Materials", "0")
        self.kertas1_materials_card = StatCard("Kertas 1 Materials", "0")
        self.kertas2_materials_card = StatCard("Kertas 2 Materials", "0")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.total_materials_card)
        cards_row.addWidget(self.kertas1_materials_card)
        cards_row.addWidget(self.kertas2_materials_card)
        layout.addLayout(cards_row)

        self.materials_table = QTableWidget(0, len(MATERIAL_TABLE_COLUMNS))
        self.materials_table.setHorizontalHeaderLabels(MATERIAL_TABLE_HEADERS)
        self.materials_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.materials_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.materials_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.materials_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.materials_table.horizontalHeader().setSectionResizeMode(
            len(MATERIAL_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed
        )
        self.materials_table.setColumnWidth(len(MATERIAL_TABLE_COLUMNS) - 1, 220)
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.verticalHeader().setDefaultSectionSize(44)
        self.materials_table.setAlternatingRowColors(True)
        self.materials_table.setMinimumHeight(260)
        apply_card_shadow(self.materials_table)
        layout.addWidget(self.materials_table)

        layout.addStretch()
        return page

    def _build_material_actions_cell(self, row: TeacherMaterialRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View Details")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_material_details(r))
        cell_layout.addWidget(view_button)

        setup_button = QPushButton("Setup")
        setup_button.setObjectName("RowActionButton")
        setup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        setup_button.clicked.connect(lambda _checked=False, r=row: self.handle_open_marking_setup(r))
        cell_layout.addWidget(setup_button)

        return cell

    # --- Create Revision Material page (hidden until selected) --------------

    def _build_create_revision_material_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(10)

        title = QLabel("Create Revision Material")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Material Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        self.new_material_title_input = QLineEdit()
        self.new_material_title_input.setPlaceholderText("e.g. Kertas Model 1 Practice")

        self.new_material_paper_type_dropdown = QComboBox()
        self.new_material_paper_type_dropdown.addItem("-- Select Paper Type --", None)
        self.new_material_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_1)
        self.new_material_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_2, PAPER_TYPE_KERTAS_2)
        self.new_material_paper_type_dropdown.addItem(PAPER_TYPE_BOTH, PAPER_TYPE_BOTH)

        both_note_label = QLabel(
            "Both is a revision material label only in this prototype. Kertas 1 and Kertas 2 "
            "marking remain separate."
        )
        both_note_label.setObjectName("StatusLabel")
        both_note_label.setWordWrap(True)

        form_layout.addWidget(self._field_label("Title"))
        form_layout.addWidget(self.new_material_title_input)
        form_layout.addWidget(self._field_label("Paper Type"))
        form_layout.addWidget(self.new_material_paper_type_dropdown)
        form_layout.addWidget(both_note_label)

        form_layout.addWidget(self._field_label("Question Paper"))
        question_paper_row = QHBoxLayout()
        choose_question_paper_button = QPushButton("Choose File...")
        choose_question_paper_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_question_paper_button.clicked.connect(self.handle_choose_question_paper)
        self.question_paper_status_label = QLabel("No file selected")
        self.question_paper_status_label.setObjectName("StatusLabel")
        question_paper_row.addWidget(choose_question_paper_button)
        question_paper_row.addWidget(self.question_paper_status_label)
        question_paper_row.addStretch()
        form_layout.addLayout(question_paper_row)

        form_layout.addWidget(self._field_label("Marking Scheme / Answer Key"))
        marking_scheme_row = QHBoxLayout()
        choose_marking_scheme_button = QPushButton("Choose File...")
        choose_marking_scheme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_marking_scheme_button.clicked.connect(self.handle_choose_marking_scheme)
        self.marking_scheme_status_label = QLabel("No file selected")
        self.marking_scheme_status_label.setObjectName("StatusLabel")
        marking_scheme_row.addWidget(choose_marking_scheme_button)
        marking_scheme_row.addWidget(self.marking_scheme_status_label)
        marking_scheme_row.addStretch()
        form_layout.addLayout(marking_scheme_row)

        form_layout.addWidget(self._field_label("Assign to Classes"))
        self.material_classes_list = QListWidget()
        self.material_classes_list.setMinimumHeight(84)
        self.material_classes_list.setMaximumHeight(110)
        self.material_classes_list.setItemDelegate(_NoAutoToggleCheckDelegate(self.material_classes_list))
        self.material_classes_list.itemClicked.connect(self.handle_toggle_material_class_item)
        form_layout.addWidget(self.material_classes_list)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        create_button = QPushButton("Create Material")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_create_revision_material)

        cancel_button = QPushButton("Cancel / Back to Revision Materials")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_create_material)

        buttons_row.addWidget(create_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- External Revisions page --------------------------------------------

    def _build_external_revisions_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("External Revisions")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("View external revision uploads submitted by your students.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        self.external_revisions_table = QTableWidget(0, len(EXTERNAL_REVISION_TABLE_COLUMNS))
        external_search = attach_table_filter(
            self.external_revisions_table, "Search student, class or title...")
        layout.addWidget(external_search)
        self.external_revisions_table.setHorizontalHeaderLabels(EXTERNAL_REVISION_TABLE_HEADERS)
        self.external_revisions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.external_revisions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.external_revisions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Same fill-the-page sizing as the classes table: every column
        # stretches, only the action column stays fixed.
        external_header = self.external_revisions_table.horizontalHeader()
        external_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        external_header.setSectionResizeMode(
            len(EXTERNAL_REVISION_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed)
        self.external_revisions_table.setColumnWidth(
            len(EXTERNAL_REVISION_TABLE_COLUMNS) - 1, EXTERNAL_REVISION_COLUMN_WIDTHS["action"])
        self.external_revisions_table.verticalHeader().setVisible(False)
        # 52px so the amber "Mark Attempt" CtaButton (taller padding) is not clipped.
        self.external_revisions_table.verticalHeader().setDefaultSectionSize(52)
        self.external_revisions_table.setAlternatingRowColors(True)
        self.external_revisions_table.setMinimumHeight(260)
        apply_card_shadow(self.external_revisions_table)
        layout.addWidget(self.external_revisions_table, stretch=1)

        return page

    def _build_external_revision_actions_cell(self, row: TeacherExternalRevisionRow) -> QWidget:
        """Same single action as the Attempts tab: the student supplies only
        their completed answer paper; the question paper and answer scheme come
        from the Subject Profile the teacher picks (or imports) here."""
        from app.services import attempt_marking_bridge_service as bridge
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        conn = get_connection()
        try:
            state = bridge.get_marking_state(conn, bridge.KIND_EXTERNAL, row.external_revision_id)
        finally:
            conn.close()
        if state["state"] == bridge.STATE_NOT_MARKED:
            label, style_name = "Mark Attempt", "CtaButton"          # amber: action needed
        elif state["state"] == bridge.STATE_FINAL:
            label, style_name = "Open Marked Result", "PrimaryButton"  # teal: done
        else:
            label, style_name = "Continue Marking", "RowActionButton"
        display = f"{row.title} - {row.student_name}"
        button = QPushButton(label)
        button.setObjectName(style_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Opens this upload in the Marking Editor. You will be asked which Subject "
            "Profile (question paper + answer scheme) to mark it against the first time.")
        button.clicked.connect(
            lambda _checked=False, r=row, d=display: self.handle_mark_attempt_via_profile(
                "external", r.external_revision_id, r.completed_answer_path, d))
        cell_layout.addWidget(button)
        return cell

    # --- Revision Attempts page ----------------------------------------------

    def _build_revision_attempts_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Revision Attempts")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("View revision attempt submissions from students in your classes.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        self.attempts_table = QTableWidget(0, len(ATTEMPT_TABLE_COLUMNS))
        attempts_search = attach_table_filter(
            self.attempts_table, "Search student, class or material...")
        layout.addWidget(attempts_search)
        self.attempts_table.setHorizontalHeaderLabels(ATTEMPT_TABLE_HEADERS)
        self.attempts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attempts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attempts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Same fill-the-page sizing as the classes table: every column
        # stretches, only the action column stays fixed.
        attempts_header = self.attempts_table.horizontalHeader()
        attempts_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        attempts_header.setSectionResizeMode(
            len(ATTEMPT_TABLE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed)
        self.attempts_table.setColumnWidth(
            len(ATTEMPT_TABLE_COLUMNS) - 1, ATTEMPT_COLUMN_WIDTHS["action"])
        self.attempts_table.verticalHeader().setVisible(False)
        # 52px so the amber "Mark Attempt" CtaButton (taller padding) is not clipped.
        self.attempts_table.verticalHeader().setDefaultSectionSize(52)
        self.attempts_table.setAlternatingRowColors(True)
        self.attempts_table.setMinimumHeight(260)
        apply_card_shadow(self.attempts_table)
        layout.addWidget(self.attempts_table, stretch=1)

        return page

    def _guided_action_by_key(self, guided) -> dict:
        return {action.action_key: action for action in guided.actions} if guided is not None else {}

    def _guided_action_allows_continue(self, row: TeacherAttemptRow, action_key: str, action_label: str) -> bool:
        conn = get_connection()
        try:
            try:
                guided = get_guided_actions_for_attempt(conn, row.attempt_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, f"{action_label} Failed", str(exc))
                return False
        finally:
            conn.close()

        action = self._guided_action_by_key(guided).get(action_key)
        if action is not None and action.warning_required:
            show_warning(self, f"{action_label} Warning", action.warning_message)
            return False
        return True

    def _add_guided_attempt_button(self, layout: QHBoxLayout, row: TeacherAttemptRow, guided_actions: dict, action_key: str, label: str, handler) -> None:
        guided_action = guided_actions.get(action_key)
        display_label = f"* {label}" if guided_action is not None and guided_action.is_recommended else label
        button = QPushButton(display_label)
        button.setObjectName("RowActionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if guided_action is not None:
            if guided_action.is_recommended:
                button.setToolTip(f"Recommended action: {guided_action.label}")
            elif guided_action.warning_required:
                button.setToolTip(guided_action.warning_message)
        button.clicked.connect(
            lambda _checked=False, r=row, key=action_key, text=label, h=handler: h(r)
            if self._guided_action_allows_continue(r, key, text)
            else None
        )
        layout.addWidget(button)

    # --- Mark Attempt via Subject Profile (unified single-button flow) ------

    def _choose_or_import_profile_for_marking(self):
        """Ask the teacher which Subject Profile carries the question paper and
        answer scheme for this attempt: pick an existing READY profile, or
        import a new one from two PDFs (processed with the normal creation
        pipeline + progress). Returns the profile or None if cancelled."""
        conn = get_connection()
        try:
            profiles = [p for p in list_subject_profiles_for_teacher(conn, self._teacher_id)
                        if p.status == SUBJECT_PROFILE_STATUS_READY]
        finally:
            conn.close()
        options = [(p.profile_name, p.profile_id) for p in profiles]
        options.append(("Import a new Subject Profile (choose question paper + answer scheme PDFs)...",
                        "__import__"))
        choice = prompt_select(
            self, "Mark Attempt",
            "Which Subject Profile holds this paper's question paper and answer scheme?",
            options)
        if choice is CANCELLED:
            return None
        if choice != "__import__":
            conn = get_connection()
            try:
                return get_subject_profile(conn, self._teacher_id, choice)
            finally:
                conn.close()

        name = prompt_input(self, "Import Subject Profile", "Name for the new Subject Profile.")
        if not name:
            return None
        qp_path, _ = QFileDialog.getOpenFileName(self, "Choose Question Paper PDF", "", "PDF Files (*.pdf)")
        if not qp_path:
            return None
        as_path, _ = QFileDialog.getOpenFileName(self, "Choose Answer Scheme PDF", "", "PDF Files (*.pdf)")
        if not as_path:
            return None
        conn = get_connection()
        try:
            try:
                profile = create_subject_profile(conn, self._teacher_id, name)
            except ValueError as exc:
                show_error(self, "Import Subject Profile Failed", str(exc))
                return None
        finally:
            conn.close()
        progress_dialog, progress_widget = self._show_progress_dialog("Processing Subject Profile")

        def progress_callback(message: str, current: int, total: int) -> None:
            progress_widget.set_progress(message, current, total)
            QApplication.processEvents()

        conn = get_connection()
        try:
            try:
                profile = process_subject_profile_documents(
                    conn, self._teacher_id, profile.profile_id, qp_path, as_path,
                    progress_callback=progress_callback,
                )
            except ValueError as exc:
                progress_dialog.close()
                show_error(self, "Import Subject Profile Failed", str(exc))
                return None
        finally:
            conn.close()
            progress_dialog.close()
        self.refresh_subject_profiles_table()
        return profile

    def _open_marking_editor_for_linked_attempt(self, answer_file_id: int, profile_id: int,
                                                display_name: str) -> None:
        conn = get_connection()
        try:
            profile = get_subject_profile(conn, self._teacher_id, profile_id)
        finally:
            conn.close()
        self._selected_profile_for_marking = profile
        self.refresh_student_results_table()
        self.handle_open_marking_editor(
            {"answer_file_id": answer_file_id, "display_name": display_name})

    def handle_mark_attempt_via_profile(self, kind: str, item_id: int,
                                        completed_answer_path: str, display_name: str) -> None:
        """The one attempt-row action: resume marking when a link already
        exists, otherwise ask for the Subject Profile (existing or imported),
        run the real marking pipeline on the student's submitted PDF, link the
        result to the submission, and open the Marking Editor."""
        from app.services import attempt_marking_bridge_service as bridge
        conn = get_connection()
        try:
            link = bridge.get_marked_link(conn, kind, item_id)
        finally:
            conn.close()
        if link is not None:
            self._open_marking_editor_for_linked_attempt(link[0], link[1], display_name)
            return

        if not completed_answer_path or not Path(completed_answer_path).exists():
            show_error(self, "Mark Attempt Failed",
                       "The student's submitted answer file could not be found on disk.")
            return
        profile = self._choose_or_import_profile_for_marking()
        if profile is None:
            return

        progress_dialog, progress_widget = self._show_progress_dialog("Marking Student Answer")
        self._attempt_marking_progress_dialog = progress_dialog
        self._attempt_marking_context = {
            "kind": kind, "item_id": item_id, "display_name": display_name,
            "profile_id": profile.profile_id,
        }
        # Same hang-safe subprocess worker the upload flow uses - real OCR
        # runs in a separate OS process while the progress ring updates here.
        worker = StudentPdfProcessingSubprocessWorker(
            self._teacher_id, profile.profile_id, [completed_answer_path], parent=self)
        worker.progress.connect(progress_widget.set_progress)
        worker.succeeded.connect(self._on_attempt_marking_succeeded)
        worker.failed.connect(self._on_attempt_marking_failed)
        worker.finished.connect(self._on_attempt_marking_finished)
        self._attempt_marking_worker = worker
        worker.start()

    def _on_attempt_marking_succeeded(self, results) -> None:
        from app.services import attempt_marking_bridge_service as bridge
        context = getattr(self, "_attempt_marking_context", None)
        if context is None:
            return
        if not results or not results[0].succeeded or results[0].answer_file_id is None:
            error = results[0].error if results else "Marking produced no result."
            show_error(self, "Mark Attempt Failed", error or "Marking failed.")
            return
        answer_file_id = results[0].answer_file_id
        conn = get_connection()
        try:
            bridge.link_marked_attempt(conn, context["kind"], context["item_id"],
                                       answer_file_id, context["profile_id"])
        finally:
            conn.close()
        self.refresh_attempts_table()
        self.refresh_external_revisions_table()
        self._open_marking_editor_for_linked_attempt(
            answer_file_id, context["profile_id"], context["display_name"])

    def _on_attempt_marking_failed(self, message: str) -> None:
        show_error(self, "Mark Attempt Failed", message)

    def _on_attempt_marking_finished(self) -> None:
        dialog = getattr(self, "_attempt_marking_progress_dialog", None)
        self._attempt_marking_progress_dialog = None
        if dialog is not None:
            dialog.close()
        self._attempt_marking_context = None
        self._attempt_marking_worker = None

    def _build_attempt_actions_cell(self, row: TeacherAttemptRow, guided=None) -> QWidget:
        """One action per attempt: mark it (choosing/importing the Subject
        Profile that holds the question paper and answer scheme) or resume the
        marking already linked to it. Everything else - review, finalise,
        download - happens in the Marking Editor this opens."""
        from app.services import attempt_marking_bridge_service as bridge
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        conn = get_connection()
        try:
            state = bridge.get_marking_state(conn, bridge.KIND_ATTEMPT, row.attempt_id)
        finally:
            conn.close()
        if state["state"] == bridge.STATE_NOT_MARKED:
            label, style_name = "Mark Attempt", "CtaButton"          # amber: action needed
        elif state["state"] == bridge.STATE_FINAL:
            label, style_name = "Open Marked Result", "PrimaryButton"  # teal: done
        else:
            label, style_name = "Continue Marking", "RowActionButton"
        display = f"{row.material_title} - {row.student_name} (attempt {row.attempt_no})"
        button = QPushButton(label)
        button.setObjectName(style_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Opens this submission in the Marking Editor. You will be asked which Subject "
            "Profile (question paper + answer scheme) to mark it against the first time.")
        button.clicked.connect(
            lambda _checked=False, r=row, d=display: self.handle_mark_attempt_via_profile(
                "attempt", r.attempt_id, r.completed_answer_path, d))
        cell_layout.addWidget(button)
        return cell

    # --- Templates page --------------------------------------------------

    def _build_templates_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Templates")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Define answer regions on Kertas 1 and Kertas 2 sample papers.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        create_template_button = QPushButton("+ Create Template")
        create_template_button.setObjectName("PrimaryButton")
        create_template_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_template_button.clicked.connect(self.handle_open_create_template_page)
        header_row.addWidget(create_template_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.total_templates_card = StatCard("Total Templates", "0")
        self.kertas1_templates_card = StatCard("Kertas 1 Templates", "0")
        self.kertas2_templates_card = StatCard("Kertas 2 Templates", "0")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.total_templates_card)
        cards_row.addWidget(self.kertas1_templates_card)
        cards_row.addWidget(self.kertas2_templates_card)
        layout.addLayout(cards_row)

        self.templates_table = QTableWidget(0, len(TEMPLATE_TABLE_COLUMNS))
        self.templates_table.setHorizontalHeaderLabels(TEMPLATE_TABLE_HEADERS)
        self.templates_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.templates_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.templates_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        templates_header = self.templates_table.horizontalHeader()
        templates_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        templates_header.setSectionResizeMode(
            TEMPLATE_TABLE_COLUMNS.index("title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in TEMPLATE_COLUMN_WIDTHS.items():
            self.templates_table.setColumnWidth(TEMPLATE_TABLE_COLUMNS.index(key), width)
        self.templates_table.verticalHeader().setVisible(False)
        self.templates_table.verticalHeader().setDefaultSectionSize(44)
        self.templates_table.setAlternatingRowColors(True)
        self.templates_table.setMinimumHeight(220)
        apply_card_shadow(self.templates_table)
        layout.addWidget(self.templates_table)

        layout.addStretch()
        return page

    def _build_template_actions_cell(self, row: TeacherTemplateRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)

        edit_button = QPushButton("Edit Regions")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, r=row: self.handle_open_template_editor(r))
        cell_layout.addWidget(edit_button)

        return cell

    # --- Create Template page (hidden until selected) -----------------------

    def _build_create_template_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(10)

        title = QLabel("Create Template")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        form_group = QGroupBox("Template Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        self.new_template_title_input = QLineEdit()
        self.new_template_title_input.setPlaceholderText("e.g. SPM English Kertas 1 Layout")

        self.new_template_paper_type_dropdown = QComboBox()
        self.new_template_paper_type_dropdown.addItem("-- Select Paper Type --", None)
        self.new_template_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_1)
        self.new_template_paper_type_dropdown.addItem(PAPER_TYPE_KERTAS_2, PAPER_TYPE_KERTAS_2)

        form_layout.addWidget(self._field_label("Title"))
        form_layout.addWidget(self.new_template_title_input)
        form_layout.addWidget(self._field_label("Paper Type"))
        form_layout.addWidget(self.new_template_paper_type_dropdown)

        form_layout.addWidget(self._field_label("Sample / Blank Paper"))
        sample_row = QHBoxLayout()
        choose_sample_button = QPushButton("Choose File...")
        choose_sample_button.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_sample_button.clicked.connect(self.handle_choose_template_sample_file)
        self.template_sample_status_label = QLabel("No file selected")
        self.template_sample_status_label.setObjectName("StatusLabel")
        sample_row.addWidget(choose_sample_button)
        sample_row.addWidget(self.template_sample_status_label)
        sample_row.addStretch()
        form_layout.addLayout(sample_row)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        create_button = QPushButton("Create Template")
        create_button.setObjectName("PrimaryButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.handle_create_template)

        cancel_button = QPushButton("Cancel / Back to Templates")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.handle_cancel_create_template)

        buttons_row.addWidget(create_button)
        buttons_row.addWidget(cancel_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    # --- Template Editor page (hidden until selected) -----------------------

    def _build_template_editor_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(6)

        self.template_editor_title_label = QLabel("Template Editor")
        self.template_editor_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.template_editor_title_label)

        self.template_editor_subtitle_label = QLabel(
            "Click and drag on the page below to define a region, then give it a label."
        )
        self.template_editor_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.template_editor_subtitle_label)

        page_nav_row = QHBoxLayout()
        page_nav_row.setSpacing(10)

        self.template_prev_page_button = QPushButton("< Previous Page")
        self.template_prev_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_prev_page_button.clicked.connect(self.handle_template_prev_page)
        page_nav_row.addWidget(self.template_prev_page_button)

        self.template_page_label = QLabel("Page 1 of 1")
        self.template_page_label.setObjectName("FieldLabel")
        page_nav_row.addWidget(self.template_page_label)

        self.template_next_page_button = QPushButton("Next Page >")
        self.template_next_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_next_page_button.clicked.connect(self.handle_template_next_page)
        page_nav_row.addWidget(self.template_next_page_button)

        page_nav_row.addStretch()
        layout.addLayout(page_nav_row)

        draw_mode_row = QHBoxLayout()
        draw_mode_row.setSpacing(10)

        self.template_draw_rectangle_button = QPushButton("Draw Rectangle Region")
        self.template_draw_rectangle_button.setCheckable(True)
        self.template_draw_rectangle_button.setChecked(True)
        self.template_draw_rectangle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_draw_rectangle_button.clicked.connect(self.handle_set_rectangle_mode)
        draw_mode_row.addWidget(self.template_draw_rectangle_button)

        self.template_draw_polygon_button = QPushButton("Draw Polygon Region")
        self.template_draw_polygon_button.setCheckable(True)
        self.template_draw_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_draw_polygon_button.clicked.connect(self.handle_set_polygon_mode)
        draw_mode_row.addWidget(self.template_draw_polygon_button)

        self.template_finish_polygon_button = QPushButton("Finish Polygon")
        self.template_finish_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_finish_polygon_button.clicked.connect(self.handle_finish_polygon)
        self.template_finish_polygon_button.setVisible(False)
        draw_mode_row.addWidget(self.template_finish_polygon_button)

        self.template_cancel_polygon_button = QPushButton("Cancel Polygon")
        self.template_cancel_polygon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_cancel_polygon_button.clicked.connect(self.handle_cancel_polygon)
        self.template_cancel_polygon_button.setVisible(False)
        draw_mode_row.addWidget(self.template_cancel_polygon_button)

        draw_mode_row.addStretch()
        layout.addLayout(draw_mode_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)

        self.template_editor_status_label = QLabel("")
        self.template_editor_status_label.setObjectName("StatusLabel")
        self.template_editor_status_label.setWordWrap(True)
        status_row.addWidget(self.template_editor_status_label, stretch=1)

        self.template_cancel_redefine_button = QPushButton("Cancel Redefine")
        self.template_cancel_redefine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_cancel_redefine_button.clicked.connect(self.handle_cancel_redefine_region)
        self.template_cancel_redefine_button.setVisible(False)
        status_row.addWidget(self.template_cancel_redefine_button)

        layout.addLayout(status_row)

        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        self.template_canvas = TemplateCanvas()
        self.template_canvas.setMinimumHeight(600)
        apply_card_shadow(self.template_canvas)
        self.template_canvas.region_drawn.connect(self.handle_template_region_drawn)
        self.template_canvas.polygon_region_drawn.connect(self.handle_template_polygon_region_drawn)
        body_row.addWidget(self.template_canvas, stretch=3)

        regions_column = QVBoxLayout()
        regions_column.setSpacing(6)
        regions_heading = QLabel("Defined Regions (All Pages)")
        regions_heading.setObjectName("FieldLabel")
        regions_column.addWidget(regions_heading)

        regions_hint = QLabel("Only the current page's regions are highlighted on the preview.")
        regions_hint.setObjectName("StatusLabel")
        regions_hint.setWordWrap(True)
        regions_column.addWidget(regions_hint)

        self.template_regions_table = QTableWidget(0, len(TEMPLATE_REGION_TABLE_COLUMNS))
        self.template_regions_table.setHorizontalHeaderLabels(TEMPLATE_REGION_TABLE_HEADERS)
        self.template_regions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.template_regions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.template_regions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        regions_header = self.template_regions_table.horizontalHeader()
        regions_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        regions_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.template_regions_table.setColumnWidth(0, 30)
        self.template_regions_table.setColumnWidth(2, 50)
        self.template_regions_table.setColumnWidth(3, 80)
        self.template_regions_table.setColumnWidth(4, 150)
        self.template_regions_table.verticalHeader().setVisible(False)
        self.template_regions_table.verticalHeader().setDefaultSectionSize(40)
        self.template_regions_table.setAlternatingRowColors(True)
        self.template_regions_table.setMinimumWidth(330)
        apply_card_shadow(self.template_regions_table)
        regions_column.addWidget(self.template_regions_table, stretch=1)

        self.create_region_group_button = QPushButton("Create Group / Combine Selected")
        self.create_region_group_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_region_group_button.clicked.connect(self.handle_create_region_group)
        regions_column.addWidget(self.create_region_group_button)

        groups_heading = QLabel("Region Groups")
        groups_heading.setObjectName("FieldLabel")
        regions_column.addWidget(groups_heading)

        groups_hint = QLabel(
            "Groups combine 2+ regions (e.g. an answer split across pages) into one logical unit. "
            "Original regions above are unchanged."
        )
        groups_hint.setObjectName("StatusLabel")
        groups_hint.setWordWrap(True)
        regions_column.addWidget(groups_hint)

        self.template_region_groups_table = QTableWidget(0, len(TEMPLATE_REGION_GROUP_TABLE_COLUMNS))
        self.template_region_groups_table.setHorizontalHeaderLabels(TEMPLATE_REGION_GROUP_TABLE_HEADERS)
        self.template_region_groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.template_region_groups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.template_region_groups_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        groups_header = self.template_region_groups_table.horizontalHeader()
        groups_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        groups_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.template_region_groups_table.setColumnWidth(0, 100)
        self.template_region_groups_table.setColumnWidth(1, 80)
        self.template_region_groups_table.setColumnWidth(3, 90)
        self.template_region_groups_table.verticalHeader().setVisible(False)
        self.template_region_groups_table.verticalHeader().setDefaultSectionSize(100)
        self.template_region_groups_table.setAlternatingRowColors(True)
        self.template_region_groups_table.setMinimumWidth(330)
        apply_card_shadow(self.template_region_groups_table)
        regions_column.addWidget(self.template_region_groups_table, stretch=1)

        body_row.addLayout(regions_column, stretch=1)
        layout.addLayout(body_row, stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)

        done_button = QPushButton("Done")
        done_button.setObjectName("PrimaryButton")
        done_button.setCursor(Qt.CursorShape.PointingHandCursor)
        done_button.clicked.connect(self.handle_template_editor_done)
        bottom_row.addWidget(done_button)

        back_button = QPushButton("Back to Templates")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_to_templates)
        bottom_row.addWidget(back_button)

        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        return page

    def _build_template_region_action_cell(self, region: TemplateRegion) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, r=region: self.handle_edit_template_region(r))
        cell_layout.addWidget(edit_button)

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("RowActionButton")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False, r=region: self.handle_remove_template_region(r))
        cell_layout.addWidget(remove_button)

        return cell

    def _build_template_region_select_cell(self, region: TemplateRegion) -> QWidget:
        """A centered checkbox used to pick regions to combine into a group
        (Stage 11H). The checkbox is tracked in self._template_region_checkboxes
        keyed by region_id so handle_create_region_group can read which
        regions are currently checked."""
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._template_region_checkboxes[region.region_id] = checkbox
        cell_layout.addWidget(checkbox)

        return cell

    def _build_region_group_action_cell(self, group: TemplateRegionGroup) -> QWidget:
        # Stacked vertically (unlike the 2-button region action cell) since
        # three buttons (Edit/Order/Delete) don't fit comfortably side by
        # side in this narrow side-panel table's Action column.
        cell = QWidget()
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(2)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, g=group: self.handle_edit_region_group(g))
        cell_layout.addWidget(edit_button)

        order_button = QPushButton("Order")
        order_button.setObjectName("RowActionButton")
        order_button.setCursor(Qt.CursorShape.PointingHandCursor)
        order_button.clicked.connect(lambda _checked=False, g=group: self.handle_manage_group_order(g))
        cell_layout.addWidget(order_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, g=group: self.handle_delete_region_group(g))
        cell_layout.addWidget(delete_button)

        return cell

    # --- Marking Setup page --------------------------------------------------

    def _build_marking_setup_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 12, 28, 12)
        layout.setSpacing(8)

        self.marking_setup_title_label = QLabel("Marking Setup")
        self.marking_setup_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.marking_setup_title_label)

        self.marking_setup_subtitle_label = QLabel("")
        self.marking_setup_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.marking_setup_subtitle_label)

        form_group = QGroupBox("Setup Details")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        self.marking_setup_classes_label = QLabel("")
        self.marking_setup_classes_label.setObjectName("StatusLabel")
        form_layout.addWidget(self._field_label("Assigned Classes"))
        form_layout.addWidget(self.marking_setup_classes_label)

        self.marking_setup_template_dropdown = QComboBox()
        form_layout.addWidget(self._field_label("Linked Template"))
        form_layout.addWidget(self.marking_setup_template_dropdown)

        marks_row = QHBoxLayout()
        spelling_column = QVBoxLayout()
        spelling_column.addWidget(self._field_label("Spelling Deduction"))
        self.marking_setup_spelling_deduction_input = QLineEdit()
        spelling_column.addWidget(self.marking_setup_spelling_deduction_input)
        mark_column = QVBoxLayout()
        mark_column.addWidget(self._field_label("Default Question Mark"))
        self.marking_setup_default_mark_input = QLineEdit()
        mark_column.addWidget(self.marking_setup_default_mark_input)
        marks_row.addLayout(spelling_column)
        marks_row.addLayout(mark_column)
        form_layout.addLayout(marks_row)

        layout.addWidget(form_group)

        setup_buttons_row = QHBoxLayout()
        setup_buttons_row.setSpacing(16)

        save_setup_button = QPushButton("Save Setup")
        save_setup_button.setObjectName("PrimaryButton")
        save_setup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_setup_button.clicked.connect(self.handle_save_marking_setup)

        back_button = QPushButton("Back")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_marking_setup)

        setup_buttons_row.addWidget(save_setup_button)
        setup_buttons_row.addWidget(back_button)
        setup_buttons_row.addStretch()
        layout.addLayout(setup_buttons_row)

        questions_header_row = QHBoxLayout()
        self.marking_questions_heading_label = QLabel("Answer Key")
        self.marking_questions_heading_label.setObjectName("SectionHeading")
        questions_header_row.addWidget(self.marking_questions_heading_label)
        questions_header_row.addStretch()

        self.add_default_criteria_button = QPushButton("+ Add Default Criteria")
        self.add_default_criteria_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_default_criteria_button.clicked.connect(self.handle_add_default_kertas2_criteria)
        self.add_default_criteria_button.setVisible(False)
        questions_header_row.addWidget(self.add_default_criteria_button)

        self.add_question_button = QPushButton("+ Add Question")
        self.add_question_button.setObjectName("PrimaryButton")
        self.add_question_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_question_button.clicked.connect(self.handle_open_add_question_dialog)
        questions_header_row.addWidget(self.add_question_button)

        layout.addLayout(questions_header_row)

        self.marking_questions_table = QTableWidget(0, len(MARKING_QUESTION_TABLE_COLUMNS))
        self.marking_questions_table.setHorizontalHeaderLabels(MARKING_QUESTION_TABLE_HEADERS)
        self.marking_questions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_questions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_questions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        questions_header = self.marking_questions_table.horizontalHeader()
        questions_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        questions_header.setSectionResizeMode(
            MARKING_QUESTION_TABLE_COLUMNS.index("explanation"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in MARKING_QUESTION_COLUMN_WIDTHS.items():
            self.marking_questions_table.setColumnWidth(MARKING_QUESTION_TABLE_COLUMNS.index(key), width)
        self.marking_questions_table.verticalHeader().setVisible(False)
        self.marking_questions_table.verticalHeader().setDefaultSectionSize(44)
        self.marking_questions_table.setAlternatingRowColors(True)
        self.marking_questions_table.setMinimumHeight(220)
        apply_card_shadow(self.marking_questions_table)
        layout.addWidget(self.marking_questions_table)

        layout.addStretch()
        return page

    def _build_marking_question_action_cell(self, row: MarkingQuestionRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda _checked=False, r=row: self.handle_edit_marking_question(r))
        cell_layout.addWidget(edit_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, r=row: self.handle_delete_marking_question(r))
        cell_layout.addWidget(delete_button)

        return cell

    # --- Marking Review page --------------------------------------------

    def _build_marking_review_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 12, 28, 12)
        layout.setSpacing(8)

        self.marking_review_title_label = QLabel("Marking Review")
        self.marking_review_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.marking_review_title_label)

        self.marking_review_subtitle_label = QLabel("")
        self.marking_review_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.marking_review_subtitle_label)

        summary_group = QGroupBox("Summary")
        apply_card_shadow(summary_group)
        summary_layout = QVBoxLayout(summary_group)
        self.marking_review_summary_label = QLabel("")
        self.marking_review_summary_label.setObjectName("StatusLabel")
        summary_layout.addWidget(self.marking_review_summary_label)
        layout.addWidget(summary_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        self.marking_review_save_draft_button = QPushButton("Save Draft")
        self.marking_review_save_draft_button.setObjectName("PrimaryButton")
        self.marking_review_save_draft_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_review_save_draft_button.clicked.connect(self.handle_save_review_draft_comment)

        self.marking_review_finalize_button = QPushButton("Finalize Review")
        self.marking_review_finalize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marking_review_finalize_button.clicked.connect(self.handle_finalize_review)

        back_button = QPushButton("Back")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_marking_review)

        buttons_row.addWidget(self.marking_review_save_draft_button)
        buttons_row.addWidget(self.marking_review_finalize_button)
        buttons_row.addWidget(back_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        self.marking_review_items_table = QTableWidget(0, len(MARKING_REVIEW_ITEM_TABLE_COLUMNS))
        self.marking_review_items_table.setHorizontalHeaderLabels(MARKING_REVIEW_ITEM_TABLE_HEADERS)
        self.marking_review_items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marking_review_items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marking_review_items_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        review_items_header = self.marking_review_items_table.horizontalHeader()
        review_items_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        review_items_header.setSectionResizeMode(
            MARKING_REVIEW_ITEM_TABLE_COLUMNS.index("extracted_answer"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in MARKING_REVIEW_ITEM_COLUMN_WIDTHS.items():
            self.marking_review_items_table.setColumnWidth(MARKING_REVIEW_ITEM_TABLE_COLUMNS.index(key), width)
        self.marking_review_items_table.verticalHeader().setVisible(False)
        self.marking_review_items_table.verticalHeader().setDefaultSectionSize(44)
        self.marking_review_items_table.setAlternatingRowColors(True)
        self.marking_review_items_table.setMinimumHeight(220)
        apply_card_shadow(self.marking_review_items_table)
        layout.addWidget(self.marking_review_items_table)

        layout.addStretch()
        return page

    def _build_marking_review_item_action_cell(self, item: MarkingReviewItem, is_finalized: bool) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.setEnabled(not is_finalized)
        edit_button.clicked.connect(lambda _checked=False, i=item: self.handle_edit_review_item(i))
        cell_layout.addWidget(edit_button)

        return cell

    def refresh_marking_review_page(self) -> None:
        if self._current_review is None:
            return

        conn = get_connection()
        try:
            review = get_review(conn, self._current_review.review_id)
            items = list_review_items(conn, review.review_id)
        finally:
            conn.close()

        self._current_review = review
        is_finalized = review.status == REVIEW_STATUS_FINALIZED

        self.marking_review_summary_label.setText(
            f"Status: {review.status}\n"
            f"Auto Total: {review.auto_total_score} / {review.max_score}\n"
            f"Final Total: {review.final_total_score} / {review.max_score}\n"
            f"Overall Comment: {review.teacher_overall_comment or '-'}"
        )
        self.marking_review_save_draft_button.setEnabled(not is_finalized)
        self.marking_review_finalize_button.setEnabled(not is_finalized)

        self.marking_review_items_table.clearContents()
        self.marking_review_items_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            result = self._current_review_results_by_id.get(item.marking_result_id)
            correct_answer = result.correct_answer if result else ""
            extracted_answer_full = (result.extracted_answer or "") if result else ""
            extracted_answer_preview = (
                extracted_answer_full[:80] + "..." if len(extracted_answer_full) > 80 else extracted_answer_full
            )
            values = [
                item.question_no,
                correct_answer,
                extracted_answer_preview,
                f"{item.auto_score_awarded}/{item.max_mark}",
                f"{item.final_score_awarded}/{item.max_mark}",
                "Correct" if item.final_is_correct else "Wrong",
                item.review_status,
            ]
            for col_index, value in enumerate(values):
                self.marking_review_items_table.removeCellWidget(row_index, col_index)
                self.marking_review_items_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.marking_review_items_table.item(
                row_index, MARKING_REVIEW_ITEM_TABLE_COLUMNS.index("extracted_answer")
            ).setToolTip(extracted_answer_full)
            self.marking_review_items_table.setCellWidget(
                row_index, len(values), self._build_marking_review_item_action_cell(item, is_finalized)
            )

    # --- Kertas 2 Review page ------------------------------------------

    def _build_kertas2_review_page(self) -> QWidget:
        page, layout = create_page()
        layout.setContentsMargins(28, 12, 28, 12)
        layout.setSpacing(8)

        self.kertas2_review_title_label = QLabel("Kertas 2 Review")
        self.kertas2_review_title_label.setObjectName("SectionHeading")
        layout.addWidget(self.kertas2_review_title_label)

        self.kertas2_review_subtitle_label = QLabel("")
        self.kertas2_review_subtitle_label.setObjectName("StatusLabel")
        layout.addWidget(self.kertas2_review_subtitle_label)

        summary_group = QGroupBox("Summary")
        apply_card_shadow(summary_group)
        summary_layout = QVBoxLayout(summary_group)
        self.kertas2_review_summary_label = QLabel("")
        self.kertas2_review_summary_label.setObjectName("StatusLabel")
        summary_layout.addWidget(self.kertas2_review_summary_label)
        layout.addWidget(summary_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        self.kertas2_review_save_draft_button = QPushButton("Save Draft")
        self.kertas2_review_save_draft_button.setObjectName("PrimaryButton")
        self.kertas2_review_save_draft_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kertas2_review_save_draft_button.clicked.connect(self.handle_save_kertas2_review_draft_comment)

        self.kertas2_review_finalize_button = QPushButton("Finalize Review")
        self.kertas2_review_finalize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kertas2_review_finalize_button.clicked.connect(self.handle_finalize_kertas2_review)

        back_button = QPushButton("Back")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self.handle_back_from_kertas2_review)

        buttons_row.addWidget(self.kertas2_review_save_draft_button)
        buttons_row.addWidget(self.kertas2_review_finalize_button)
        buttons_row.addWidget(back_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        self.kertas2_review_items_table = QTableWidget(0, len(KERTAS2_REVIEW_ITEM_TABLE_COLUMNS))
        self.kertas2_review_items_table.setHorizontalHeaderLabels(KERTAS2_REVIEW_ITEM_TABLE_HEADERS)
        self.kertas2_review_items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.kertas2_review_items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.kertas2_review_items_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        kertas2_review_items_header = self.kertas2_review_items_table.horizontalHeader()
        kertas2_review_items_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        kertas2_review_items_header.setSectionResizeMode(
            KERTAS2_REVIEW_ITEM_TABLE_COLUMNS.index("student_answer"), QHeaderView.ResizeMode.Stretch
        )
        kertas2_review_items_header.setSectionResizeMode(
            KERTAS2_REVIEW_ITEM_TABLE_COLUMNS.index("final_feedback"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in KERTAS2_REVIEW_ITEM_COLUMN_WIDTHS.items():
            self.kertas2_review_items_table.setColumnWidth(KERTAS2_REVIEW_ITEM_TABLE_COLUMNS.index(key), width)
        self.kertas2_review_items_table.verticalHeader().setVisible(False)
        self.kertas2_review_items_table.verticalHeader().setDefaultSectionSize(44)
        self.kertas2_review_items_table.setAlternatingRowColors(True)
        self.kertas2_review_items_table.setMinimumHeight(220)
        apply_card_shadow(self.kertas2_review_items_table)
        layout.addWidget(self.kertas2_review_items_table)

        layout.addStretch()
        return page

    def _build_kertas2_review_item_action_cell(self, item: Kertas2FeedbackReviewItem, is_finalized: bool) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        edit_button = QPushButton("Edit")
        edit_button.setObjectName("RowActionButton")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.setEnabled(not is_finalized)
        edit_button.clicked.connect(lambda _checked=False, i=item: self.handle_edit_kertas2_review_item(i))
        cell_layout.addWidget(edit_button)

        return cell

    def refresh_kertas2_review_page(self) -> None:
        if self._current_kertas2_review is None:
            return

        conn = get_connection()
        try:
            review = get_kertas2_review(conn, self._current_kertas2_review.kertas2_review_id)
            items = list_kertas2_review_items(conn, review.kertas2_review_id)
        finally:
            conn.close()

        self._current_kertas2_review = review
        is_finalized = review.status == KERTAS2_REVIEW_STATUS_FINALIZED

        self.kertas2_review_summary_label.setText(
            f"Status: {review.status}\n"
            f"Suggested Total: {review.suggested_total_score} / {review.max_score}\n"
            f"Final Total: {review.final_total_score} / {review.max_score}\n"
            f"Overall Comment: {review.teacher_overall_comment or '-'}"
        )
        self.kertas2_review_save_draft_button.setEnabled(not is_finalized)
        self.kertas2_review_finalize_button.setEnabled(not is_finalized)

        self.kertas2_review_items_table.clearContents()
        self.kertas2_review_items_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            student_answer_full = item.student_answer or ""
            student_answer_preview = (
                student_answer_full[:80] + "..." if len(student_answer_full) > 80 else student_answer_full
            )
            final_feedback_full = item.final_feedback or ""
            final_feedback_preview = (
                final_feedback_full[:80] + "..." if len(final_feedback_full) > 80 else final_feedback_full
            )
            values = [
                item.criterion_name,
                student_answer_preview,
                f"{item.suggested_score}/{item.max_mark}",
                f"{item.final_score}/{item.max_mark}",
                final_feedback_preview,
                item.review_status,
            ]
            for col_index, value in enumerate(values):
                self.kertas2_review_items_table.removeCellWidget(row_index, col_index)
                self.kertas2_review_items_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.kertas2_review_items_table.item(
                row_index, KERTAS2_REVIEW_ITEM_TABLE_COLUMNS.index("student_answer")
            ).setToolTip(student_answer_full)
            self.kertas2_review_items_table.item(
                row_index, KERTAS2_REVIEW_ITEM_TABLE_COLUMNS.index("final_feedback")
            ).setToolTip(final_feedback_full)
            self.kertas2_review_items_table.setCellWidget(
                row_index, len(values), self._build_kertas2_review_item_action_cell(item, is_finalized)
            )

    # --- Results page -------------------------------------------------

    def _build_results_page(self) -> QWidget:
        page, layout = create_page()

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("Results")
        title.setObjectName("SectionHeading")
        subtitle = QLabel("Finalized Kertas 1 and Kertas 2 results for your classes.")
        subtitle.setObjectName("StatusLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch()

        export_summary_button = QPushButton("Export Summary CSV")
        export_summary_button.setObjectName("PrimaryButton")
        export_summary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_summary_button.clicked.connect(self.handle_export_teacher_results_summary_csv)
        header_row.addWidget(export_summary_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header_row)

        self.total_results_card = StatCard("Total Finalized Results", "0")
        self.kertas1_results_card = StatCard("Kertas 1 Results", "0")
        self.kertas2_results_card = StatCard("Kertas 2 Results", "0")
        self.main_marking_results_card = StatCard("Main Marking Results", "0")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(self.total_results_card)
        cards_row.addWidget(self.kertas1_results_card)
        cards_row.addWidget(self.kertas2_results_card)
        cards_row.addWidget(self.main_marking_results_card)
        layout.addLayout(cards_row)

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

        main_marking_header_row = QHBoxLayout()
        main_marking_title_column = QVBoxLayout()
        main_marking_title_column.setSpacing(2)
        main_marking_heading = QLabel("Main Marking Finalized Results")
        main_marking_heading.setObjectName("SectionHeading")
        main_marking_subtitle = QLabel(
            "Finalized results from standalone Main Marking sessions (Kertas 1 only in this stage)."
        )
        main_marking_subtitle.setObjectName("StatusLabel")
        main_marking_subtitle.setWordWrap(True)
        main_marking_title_column.addWidget(main_marking_heading)
        main_marking_title_column.addWidget(main_marking_subtitle)
        main_marking_header_row.addLayout(main_marking_title_column)
        main_marking_header_row.addStretch()

        self.main_marking_export_summary_button = QPushButton("Export Main Marking Summary CSV")
        self.main_marking_export_summary_button.setObjectName("PrimaryButton")
        self.main_marking_export_summary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_marking_export_summary_button.clicked.connect(
            self.handle_export_main_marking_results_summary_csv
        )
        main_marking_header_row.addWidget(self.main_marking_export_summary_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(main_marking_header_row)

        self.main_marking_results_table = QTableWidget(0, len(MAIN_MARKING_RESULT_TABLE_COLUMNS))
        self.main_marking_results_table.setHorizontalHeaderLabels(MAIN_MARKING_RESULT_TABLE_HEADERS)
        self.main_marking_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.main_marking_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.main_marking_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        main_marking_results_header = self.main_marking_results_table.horizontalHeader()
        main_marking_results_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        main_marking_results_header.setSectionResizeMode(
            MAIN_MARKING_RESULT_TABLE_COLUMNS.index("session_title"), QHeaderView.ResizeMode.Stretch
        )
        for key, width in MAIN_MARKING_RESULT_COLUMN_WIDTHS.items():
            self.main_marking_results_table.setColumnWidth(MAIN_MARKING_RESULT_TABLE_COLUMNS.index(key), width)
        self.main_marking_results_table.verticalHeader().setVisible(False)
        self.main_marking_results_table.verticalHeader().setDefaultSectionSize(44)
        self.main_marking_results_table.setAlternatingRowColors(True)
        self.main_marking_results_table.setMinimumHeight(220)
        apply_card_shadow(self.main_marking_results_table)
        layout.addWidget(self.main_marking_results_table)

        layout.addStretch()
        return page

    def _build_result_action_cell(self, row: ResultSummaryRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View Result")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_result(r))
        cell_layout.addWidget(view_button)

        export_detail_button = QPushButton("Export Detail CSV")
        export_detail_button.setObjectName("RowActionButton")
        export_detail_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_detail_button.clicked.connect(lambda _checked=False, r=row: self.handle_export_teacher_result_detail_csv(r))
        cell_layout.addWidget(export_detail_button)

        return cell

    def refresh_results_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            results = list_teacher_finalized_results(conn, self._teacher_id)
        finally:
            conn.close()

        kertas1_count = sum(1 for r in results if r.result_type == RESULT_TYPE_KERTAS1)
        kertas2_count = sum(1 for r in results if r.result_type == RESULT_TYPE_KERTAS2)
        self.total_results_card.set_value(str(len(results)))
        self.kertas1_results_card.set_value(str(kertas1_count))
        self.kertas2_results_card.set_value(str(kertas2_count))

        self.results_table.clearContents()
        self.results_table.setRowCount(len(results))
        for row_index, row in enumerate(results):
            values = [
                _RESULT_TYPE_LABELS.get(row.result_type, row.result_type),
                row.username,
                row.student_name,
                row.class_name,
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
                row_index, RESULT_SUMMARY_TABLE_COLUMNS.index("student_name")
            ).setToolTip(row.student_name)
            self.results_table.item(
                row_index, RESULT_SUMMARY_TABLE_COLUMNS.index("material_title")
            ).setToolTip(row.material_title)
            self.results_table.setCellWidget(
                row_index, len(values), self._build_result_action_cell(row)
            )

    def handle_view_result(self, row: ResultSummaryRow) -> None:
        conn = get_connection()
        try:
            try:
                review, detail_rows = get_result_detail_for_teacher(
                    conn, row.result_type, row.review_id, self._teacher_id
                )
            except ValueError as exc:
                show_error(self, "View Result Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(
            self,
            f"{_RESULT_TYPE_LABELS.get(row.result_type, row.result_type)} - {row.student_name}",
            _build_result_detail_message(row.result_type, review, detail_rows),
        )

    def _build_main_marking_result_action_cell(self, row: MainMarkingFinalResultRow) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View Details")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_view_main_marking_result(r))
        cell_layout.addWidget(view_button)

        export_detail_button = QPushButton("Export Detail CSV")
        export_detail_button.setObjectName("RowActionButton")
        export_detail_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_detail_button.clicked.connect(
            lambda _checked=False, r=row: self.handle_export_main_marking_result_detail_csv(r)
        )
        cell_layout.addWidget(export_detail_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, r=row: self.handle_delete_main_marking_result(r))
        cell_layout.addWidget(delete_button)

        return cell

    def refresh_main_marking_results_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            rows = list_main_marking_final_results_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.main_marking_results_card.set_value(str(len(rows)))
        self.main_marking_export_summary_button.setEnabled(len(rows) > 0)

        self.main_marking_results_table.clearContents()
        self.main_marking_results_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            result = row.result
            values = [
                row.session_title,
                result.answer_file_display_name,
                result.student_name or "-",
                result.student_code or "-",
                result.paper_type,
                result.total_score,
                result.max_score,
                format_timestamp(result.finalized_at),
            ]
            for col_index, value in enumerate(values):
                self.main_marking_results_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.main_marking_results_table.setCellWidget(
                row_index, len(values), self._build_main_marking_result_action_cell(row)
            )

    def handle_view_main_marking_result(self, row: MainMarkingFinalResultRow) -> None:
        conn = get_connection()
        try:
            try:
                detail = get_main_marking_final_result_detail(conn, self._teacher_id, row.result.result_id)
            except ValueError as exc:
                show_error(self, "View Result Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(
            self,
            f"Main Marking Result - {detail.result.answer_file_display_name}",
            _build_main_marking_result_detail_message(detail),
        )

    def handle_export_main_marking_results_summary_csv(self) -> None:
        conn = get_connection()
        try:
            try:
                path, count = export_main_marking_final_results_summary_csv(conn, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Export Main Marking Summary CSV Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(
            self, "Export Main Marking Summary CSV",
            f"Exported {count} finalized Main Marking result(s) successfully: {path}",
        )

    def handle_export_main_marking_result_detail_csv(self, row: MainMarkingFinalResultRow) -> None:
        conn = get_connection()
        try:
            try:
                path, item_count = export_main_marking_final_result_detail_csv(
                    conn, self._teacher_id, row.result.result_id
                )
            except ValueError as exc:
                show_error(self, "Export Detail CSV Failed", str(exc))
                return
        finally:
            conn.close()

        if item_count == 0:
            message = (
                f"Exported successfully, but this result has no item rows - only its "
                f"summary metadata was written: {path}"
            )
        else:
            message = f"Exported {item_count} item row(s) successfully: {path}"
        show_detail(self, "Export Detail CSV", message)

    def handle_delete_main_marking_result(self, row: MainMarkingFinalResultRow) -> None:
        """Data Management Readiness Fix: hard delete (not soft delete) of a
        finalized Main Marking result and all of its dependent data - see
        delete_main_marking_final_result's docstring for exactly which
        tables/files this removes. Never touches the student account, the
        Subject Profile, its original PDFs, or other results/answer files."""
        confirmed = prompt_confirm(
            self, "Delete Marked Result",
            "Are you sure you want to permanently delete this marked student answer/result? "
            "This action cannot be undone.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                delete_main_marking_final_result(conn, self._teacher_id, row.result.result_id)
            except ValueError as exc:
                show_error(self, "Delete Marked Result Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_main_marking_results_table()
        show_success(self, "Marked Result Deleted", "The marked student answer/result was permanently deleted.")

    def handle_export_teacher_results_summary_csv(self) -> None:
        conn = get_connection()
        try:
            try:
                path = export_teacher_results_summary_csv(conn, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Export Summary CSV Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Export Summary CSV", f"CSV exported successfully: {path}")

    def handle_export_teacher_result_detail_csv(self, row: ResultSummaryRow) -> None:
        conn = get_connection()
        try:
            try:
                path = export_teacher_result_detail_csv(conn, row.result_type, row.review_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Export Detail CSV Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Export Detail CSV", f"CSV exported successfully: {path}")

    # --- Marking Settings page --------------------------------------------

    def _build_marking_settings_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Marking Settings")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel("These settings apply to your marking workflow only.")
        subtitle.setObjectName("StatusLabel")
        layout.addWidget(subtitle)

        form_group = QGroupBox("Kertas 1 / Kertas 2 Defaults")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        form_layout.addWidget(self._field_label("Spelling Deduction"))
        self.spelling_deduction_enabled_dropdown = QComboBox()
        self.spelling_deduction_enabled_dropdown.addItem("Enabled", True)
        self.spelling_deduction_enabled_dropdown.addItem("Disabled", False)
        form_layout.addWidget(self.spelling_deduction_enabled_dropdown)

        form_layout.addWidget(self._field_label("Spelling Deduction Points"))
        self.spelling_deduction_points_input = QLineEdit()
        form_layout.addWidget(self.spelling_deduction_points_input)

        form_layout.addWidget(self._field_label("Kertas 2 Partial Mark Default"))
        self.kertas2_partial_mark_default_input = QLineEdit()
        form_layout.addWidget(self.kertas2_partial_mark_default_input)

        layout.addWidget(form_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        save_settings_button = QPushButton("Save Settings")
        save_settings_button.setObjectName("PrimaryButton")
        save_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_settings_button.clicked.connect(self.handle_save_marking_settings)

        reset_settings_button = QPushButton("Reset to Defaults")
        reset_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_settings_button.clicked.connect(self.handle_reset_marking_settings)

        buttons_row.addWidget(save_settings_button)
        buttons_row.addWidget(reset_settings_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    def refresh_marking_settings_page(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            settings = get_teacher_marking_settings(conn, self._teacher_id)
        finally:
            conn.close()

        index = self.spelling_deduction_enabled_dropdown.findData(settings.spelling_deduction_enabled)
        self.spelling_deduction_enabled_dropdown.setCurrentIndex(index if index >= 0 else 0)
        self.spelling_deduction_points_input.setText(str(settings.spelling_deduction_points))
        self.kertas2_partial_mark_default_input.setText(str(settings.kertas2_partial_mark_default))

    def handle_save_marking_settings(self) -> None:
        spelling_deduction_enabled = self.spelling_deduction_enabled_dropdown.currentData()

        try:
            spelling_deduction_points = float(self.spelling_deduction_points_input.text())
            kertas2_partial_mark_default = float(self.kertas2_partial_mark_default_input.text())
        except ValueError:
            show_error(self, "Save Settings Failed", "Spelling deduction points and partial mark default must be numbers.")
            return

        conn = get_connection()
        try:
            try:
                update_teacher_marking_settings(
                    conn, self._teacher_id, spelling_deduction_enabled, spelling_deduction_points,
                    kertas2_partial_mark_default,
                )
            except ValueError as exc:
                show_error(self, "Save Settings Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_marking_settings_page()
        show_success(self, "Save Settings", "Marking settings saved successfully.")

    def handle_reset_marking_settings(self) -> None:
        conn = get_connection()
        try:
            reset_teacher_marking_settings_to_defaults(conn, self._teacher_id)
        finally:
            conn.close()

        self.refresh_marking_settings_page()
        show_success(self, "Reset Settings", "Marking settings reset to defaults.")

    # --- Local AI Settings page (per-teacher local/offline AI config) -----

    def _build_local_ai_settings_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("Local AI Settings")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel(
            "Only local/offline AI providers are supported. Cloud or network AI providers are not "
            "supported. These settings apply only to your own Kertas 2 AI feedback generation."
        )
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form_group = QGroupBox("Kertas 2 AI Feedback Provider")
        apply_card_shadow(form_group)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(4)

        form_layout.addWidget(self._field_label("Enabled"))
        self.local_ai_enabled_dropdown = QComboBox()
        self.local_ai_enabled_dropdown.addItem("Enabled", True)
        self.local_ai_enabled_dropdown.addItem("Disabled", False)
        form_layout.addWidget(self.local_ai_enabled_dropdown)

        form_layout.addWidget(self._field_label("Backend"))
        self.local_ai_backend_dropdown = QComboBox()
        self.local_ai_backend_dropdown.addItem("none", "none")
        self.local_ai_backend_dropdown.addItem("optional_python_module", "optional_python_module")
        form_layout.addWidget(self.local_ai_backend_dropdown)

        backend_help_label = QLabel(
            "optional_python_module expects a trusted local Python file implementing "
            "generate_kertas2_feedback(prompt, input_data)."
        )
        backend_help_label.setObjectName("StatusLabel")
        backend_help_label.setWordWrap(True)
        form_layout.addWidget(backend_help_label)

        form_layout.addWidget(self._field_label("Model Path (local Python file only)"))
        self.local_ai_model_path_input = QLineEdit()
        self.local_ai_model_path_input.setPlaceholderText("e.g. C:/backends/my_local_backend.py")
        form_layout.addWidget(self.local_ai_model_path_input)

        layout.addWidget(form_group)

        # Stage 12G-7: the local natural-language feedback runtime, owned by
        # this teacher alone. Only local addresses are accepted - the same
        # allow-list the AI backend enforces - so a cloud endpoint cannot be
        # saved here at all. Nothing on this page contacts a network.
        runtime_group = QGroupBox("Local Feedback Runtime (natural-language wording)")
        apply_card_shadow(runtime_group)
        runtime_layout = QVBoxLayout(runtime_group)
        runtime_layout.setSpacing(4)

        runtime_help = QLabel(
            "Optional. Point this at a local model server (for example Ollama on your own "
            "machine) to have Kertas 2 feedback written in natural language. Only localhost "
            "addresses are accepted. When it is not configured or not reachable, feedback falls "
            "back to the built-in templates, which always work offline. This never changes any "
            "score.")
        runtime_help.setObjectName("StatusLabel")
        runtime_help.setWordWrap(True)
        runtime_layout.addWidget(runtime_help)

        runtime_layout.addWidget(self._field_label("Adapter"))
        self.local_ai_adapter_dropdown = QComboBox()
        for label, value in (("none (templates only)", "none"), ("ollama", "ollama"),
                             ("openai-compatible", "openai")):
            self.local_ai_adapter_dropdown.addItem(label, value)
        runtime_layout.addWidget(self.local_ai_adapter_dropdown)

        runtime_layout.addWidget(self._field_label("Endpoint (localhost only)"))
        self.local_ai_endpoint_input = QLineEdit()
        self.local_ai_endpoint_input.setPlaceholderText("e.g. http://localhost:11434/api/chat")
        runtime_layout.addWidget(self.local_ai_endpoint_input)

        runtime_layout.addWidget(self._field_label("Model name"))
        self.local_ai_model_name_input = QLineEdit()
        self.local_ai_model_name_input.setPlaceholderText("e.g. llama3.1:8b")
        runtime_layout.addWidget(self.local_ai_model_name_input)

        runtime_layout.addWidget(self._field_label("Timeout (seconds)"))
        self.local_ai_timeout_input = QLineEdit()
        runtime_layout.addWidget(self.local_ai_timeout_input)

        runtime_layout.addWidget(self._field_label("Maximum output tokens"))
        self.local_ai_max_tokens_input = QLineEdit()
        runtime_layout.addWidget(self.local_ai_max_tokens_input)

        runtime_layout.addWidget(self._field_label("Feedback length limit (characters)"))
        self.local_ai_feedback_length_input = QLineEdit()
        runtime_layout.addWidget(self.local_ai_feedback_length_input)

        runtime_layout.addWidget(self._field_label(
            "Allow another machine on my local network"))
        self.local_ai_allow_private_dropdown = QComboBox()
        self.local_ai_allow_private_dropdown.addItem("No (this machine only)", False)
        self.local_ai_allow_private_dropdown.addItem("Yes (private network address)", True)
        runtime_layout.addWidget(self.local_ai_allow_private_dropdown)

        self.local_ai_runtime_status_label = QLabel("")
        self.local_ai_runtime_status_label.setObjectName("StatusLabel")
        self.local_ai_runtime_status_label.setWordWrap(True)
        runtime_layout.addWidget(self.local_ai_runtime_status_label)

        # A rejected configuration reports why, inline and in red, and stays
        # visible until a valid configuration is saved.
        self.local_ai_runtime_error_label = QLabel("")
        self.local_ai_runtime_error_label.setObjectName("StatusLabel")
        self.local_ai_runtime_error_label.setWordWrap(True)
        self.local_ai_runtime_error_label.setStyleSheet("color: #c0392b;")
        self.local_ai_runtime_error_label.setVisible(False)
        runtime_layout.addWidget(self.local_ai_runtime_error_label)

        runtime_buttons = QHBoxLayout()
        for text, slot, attr in (
            ("Save Feedback Runtime", self.handle_save_local_feedback_runtime,
             "local_ai_save_runtime_button"),
            ("Check Runtime", self.handle_check_local_feedback_runtime,
             "local_ai_check_runtime_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            setattr(self, attr, button)
            runtime_buttons.addWidget(button)
        runtime_buttons.addStretch()
        runtime_buttons_wrap = QWidget()
        runtime_buttons_wrap.setLayout(runtime_buttons)
        runtime_layout.addWidget(runtime_buttons_wrap)

        layout.addWidget(runtime_group)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(16)

        save_settings_button = QPushButton("Save Settings")
        save_settings_button.setObjectName("PrimaryButton")
        save_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_settings_button.clicked.connect(self.handle_save_local_ai_settings)

        run_diagnostic_button = QPushButton("Run Diagnostic")
        run_diagnostic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        run_diagnostic_button.clicked.connect(self.handle_run_local_ai_diagnostic)

        buttons_row.addWidget(save_settings_button)
        buttons_row.addWidget(run_diagnostic_button)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        layout.addStretch()
        return page

    def refresh_local_ai_settings_page(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            settings = get_or_create_local_ai_settings(conn, self._teacher_id)
        finally:
            conn.close()

        enabled_index = self.local_ai_enabled_dropdown.findData(settings.is_enabled)
        self.local_ai_enabled_dropdown.setCurrentIndex(enabled_index if enabled_index >= 0 else 1)
        backend_index = self.local_ai_backend_dropdown.findData(settings.backend_name)
        self.local_ai_backend_dropdown.setCurrentIndex(backend_index if backend_index >= 0 else 0)
        self.local_ai_model_path_input.setText(settings.model_path or "")
        self._refresh_local_feedback_runtime_fields()

    # --- Local feedback runtime (Stage 12G-7) -------------------------------

    def _refresh_local_feedback_runtime_fields(self) -> None:
        if not hasattr(self, "local_ai_adapter_dropdown") or self._teacher_id is None:
            return
        from app.services import local_ai_settings_service as local_ai
        conn = get_connection()
        try:
            runtime = local_ai.get_teacher_feedback_runtime(conn, self._teacher_id)
        finally:
            conn.close()
        index = self.local_ai_adapter_dropdown.findData(runtime.adapter)
        self.local_ai_adapter_dropdown.setCurrentIndex(index if index >= 0 else 0)
        self.local_ai_endpoint_input.setText(runtime.endpoint or "")
        self.local_ai_model_name_input.setText(runtime.model_name or "")
        self.local_ai_timeout_input.setText(f"{runtime.timeout_seconds:g}")
        self.local_ai_max_tokens_input.setText(str(runtime.max_output_tokens))
        self.local_ai_feedback_length_input.setText(str(runtime.requested_feedback_length))
        private_index = self.local_ai_allow_private_dropdown.findData(runtime.allow_private_network)
        self.local_ai_allow_private_dropdown.setCurrentIndex(
            private_index if private_index >= 0 else 0)
        self.local_ai_runtime_status_label.setText(
            local_ai.describe_feedback_runtime(runtime)["message"])
        self._clear_runtime_validation_error()

    def _collect_local_feedback_runtime(self):
        """Read the form. Returns (runtime, error_message)."""
        from app.models.local_ai_settings_model import LocalFeedbackRuntimeSettings
        numbers = {}
        for field, widget, caster, label in (
            ("timeout_seconds", self.local_ai_timeout_input, float, "Timeout"),
            ("max_output_tokens", self.local_ai_max_tokens_input, int, "Maximum output tokens"),
            ("requested_feedback_length", self.local_ai_feedback_length_input, int,
             "Feedback length limit"),
        ):
            raw = widget.text().strip()
            try:
                numbers[field] = caster(raw)
            except (TypeError, ValueError):
                return None, f"{label} must be a number."
        endpoint = self.local_ai_endpoint_input.text().strip()
        model_name = self.local_ai_model_name_input.text().strip()
        return LocalFeedbackRuntimeSettings(
            adapter=self.local_ai_adapter_dropdown.currentData(),
            endpoint=endpoint or None, model_name=model_name or None,
            allow_private_network=bool(self.local_ai_allow_private_dropdown.currentData()),
            **numbers), None

    def _show_runtime_validation_error(self, message: str) -> None:
        """Stage 12G-11: an invalid runtime is rejected VISIBLY - the reason is
        shown inline on the page (not only in a dialog that can be dismissed),
        and connection testing stays disabled until the configuration is valid.
        The previously saved configuration is left untouched."""
        self.local_ai_runtime_error_label.setText(message)
        self.local_ai_runtime_error_label.setVisible(True)
        self.local_ai_check_runtime_button.setEnabled(False)
        self.local_ai_runtime_status_label.setText(
            "Not saved. Your previously saved runtime configuration is unchanged.")
        show_error(self, "Save Feedback Runtime Failed", message)

    def _clear_runtime_validation_error(self) -> None:
        self.local_ai_runtime_error_label.setText("")
        self.local_ai_runtime_error_label.setVisible(False)
        self.local_ai_check_runtime_button.setEnabled(True)

    def handle_save_local_feedback_runtime(self) -> None:
        from app.services import local_ai_settings_service as local_ai
        runtime, error = self._collect_local_feedback_runtime()
        if error:
            self._show_runtime_validation_error(error)
            return
        conn = get_connection()
        try:
            local_ai.save_teacher_feedback_runtime(conn, self._teacher_id, runtime)
        except ValueError as exc:
            # Nothing was written - save_teacher_feedback_runtime validates
            # before it touches the row, so the last valid configuration stands.
            self._show_runtime_validation_error(str(exc))
            return
        finally:
            conn.close()
        self._clear_runtime_validation_error()
        self._refresh_local_feedback_runtime_fields()
        show_success(self, "Save Feedback Runtime",
                     "Your local feedback runtime was saved. It applies only to your own "
                     "feedback generation.")

    def handle_check_local_feedback_runtime(self) -> None:
        """A local-only readiness report - it never opens a connection."""
        from app.services import local_ai_settings_service as local_ai
        runtime, error = self._collect_local_feedback_runtime()
        if error:
            self._show_runtime_validation_error(error)
            return
        report = local_ai.describe_feedback_runtime(runtime)
        if report["problems"]:
            self._show_runtime_validation_error("\n".join(report["problems"]))
            return
        lines = [
            f"Status: {report['status']}",
            f"Adapter: {report['adapter']}",
            f"Endpoint: {report['endpoint']}",
            f"Model: {report['model_name']}",
            "",
            report["message"],
        ]
        if report["problems"]:
            lines.append("")
            lines.append("Problems:")
            lines.extend(f"- {p}" for p in report["problems"])
        lines.append("")
        lines.append("This check inspects your configuration only; it does not contact the "
                     "runtime and never changes a score.")
        self.local_ai_runtime_status_label.setText(report["message"])
        show_detail(self, "Local Feedback Runtime", "\n".join(lines))

    def handle_save_local_ai_settings(self) -> None:
        is_enabled = self.local_ai_enabled_dropdown.currentData()
        backend_name = self.local_ai_backend_dropdown.currentData()
        model_path = self.local_ai_model_path_input.text().strip()

        conn = get_connection()
        try:
            try:
                update_local_ai_settings(conn, self._teacher_id, backend_name, model_path, is_enabled)
            except ValueError as exc:
                show_error(self, "Save Settings Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_local_ai_settings_page()
        show_success(self, "Save Settings", "Local AI settings saved successfully.")

    def handle_run_local_ai_diagnostic(self) -> None:
        conn = get_connection()
        try:
            diagnostic = validate_local_ai_settings(conn, self._teacher_id)
        finally:
            conn.close()

        lines = [
            f"Available: {'Yes' if diagnostic.is_available else 'No'}",
            f"Status: {diagnostic.status}",
            f"Reason: {diagnostic.message}",
            f"Backend: {diagnostic.backend_name}",
            f"Model Path: {diagnostic.model_path or '-'}",
        ]
        show_detail(self, "Local AI Diagnostic", "\n".join(lines))

    # --- Data refresh -----------------------------------------------------

    def _refresh_hero_kpi(self) -> None:
        """The dashboard's lead number: submissions (attempts + external
        revisions) not yet finalised through the one-button marking flow."""
        if self._teacher_id is None or not hasattr(self, "hero_kpi_number_label"):
            return
        from app.services import attempt_marking_bridge_service as bridge
        conn = get_connection()
        try:
            waiting = sum(
                1 for row in list_attempts_for_teacher(conn, self._teacher_id)
                if bridge.get_marking_state(conn, bridge.KIND_ATTEMPT, row.attempt_id)["state"]
                != bridge.STATE_FINAL)
            waiting += sum(
                1 for row in list_external_revisions_for_teacher(conn, self._teacher_id)
                if bridge.get_marking_state(conn, bridge.KIND_EXTERNAL, row.external_revision_id)["state"]
                != bridge.STATE_FINAL)
        finally:
            conn.close()
        self.hero_kpi_number_label.setText(str(waiting))
        self.hero_kpi_title_label.setText(
            "submission waiting for your marking" if waiting == 1
            else "submissions waiting for your marking")
        if waiting == 0:
            self.hero_kpi_subtitle_label.setText("All caught up - nothing waiting right now.")
        else:
            self.hero_kpi_subtitle_label.setText(
                "Attempts and external revisions not yet finalised.")

    def refresh_teacher_attention_dashboard(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            summary = get_teacher_attention_summary(conn, self._teacher_id)
        finally:
            conn.close()

        self.total_attempts_card.set_value(str(summary.total_attempts))
        self.blocked_attempts_card.set_value(str(summary.blocked_attempts))
        self.pending_review_attempts_card.set_value(str(summary.pending_review_attempts))
        self.finalized_results_summary_card.set_value(str(summary.finalized_results))
        self._refresh_hero_kpi()

        self.attention_table.clearContents()
        self.attention_table.setRowCount(len(summary.attention_items))
        for row_index, item in enumerate(summary.attention_items):
            issue_summary = f"{item.issue_count} / {item.blocker_count}"
            values = [
                item.student_name,
                item.class_name,
                item.material_title,
                item.paper_type,
                item.priority,
                item.recommended_action,
                issue_summary,
            ]
            for col_index, value in enumerate(values):
                self.attention_table.removeCellWidget(row_index, col_index)
                table_item = QTableWidgetItem(str(value))
                if ATTENTION_TABLE_COLUMNS[col_index] == "material_title":
                    table_item.setToolTip(item.material_title)
                if ATTENTION_TABLE_COLUMNS[col_index] == "priority":
                    table_item.setToolTip(item.reason)
                self.attention_table.setItem(row_index, col_index, table_item)
            self.attention_table.setCellWidget(
                row_index, len(values), self._build_attention_action_cell(item)
            )

    def refresh_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            classes = list_all_classes_with_teacher_info(conn)
            my_pending_class_ids = {r.class_id for r in list_my_pending_requests(conn, self._teacher_id)}
        finally:
            conn.close()

        # Pin this teacher's own classes to the top (stable sort - order is
        # otherwise unchanged within each group), and visually highlight them.
        classes = sorted(classes, key=lambda c: c.teacher_id != self._teacher_id)

        my_class_count = 0
        self.table.setRowCount(0)
        self.table.setRowCount(len(classes))
        for row_index, class_ in enumerate(classes):
            is_mine = class_.teacher_id == self._teacher_id
            if is_mine:
                status = MY_CLASS_STATUS
                my_class_count += 1
            elif class_.teacher_id is None:
                status = AVAILABLE_STATUS
            else:
                status = OCCUPIED_STATUS

            class_label = f"★ {class_.class_name}" if is_mine else class_.class_name
            values = [
                class_.class_id,
                class_label,
                class_.subject,
                class_.teacher_name or "Unassigned",
                status,
                format_timestamp(class_.created_at),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if is_mine:
                    item.setBackground(QBrush(QColor(styles.ACCENT_LIGHT)))
                self.table.setItem(row_index, col_index, item)
            has_pending = class_.class_id in my_pending_class_ids
            self.table.setCellWidget(
                row_index, len(values), self._build_action_cell(status, class_, has_pending)
            )
        self.table.doItemsLayout()

        self.my_classes_card.set_value(str(my_class_count))
        self.refresh_teacher_attention_dashboard()

    def refresh_incoming_requests_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            requests = list_pending_requests_for_teacher(conn, self._teacher_id)
            pending_count = count_pending_requests_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.requests_table.setRowCount(len(requests))
        for row_index, request in enumerate(requests):
            values = [
                request.request_id,
                request.class_name,
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

    def refresh_students_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            students = list_students_for_teacher(conn, self._teacher_id)
            student_count = count_distinct_students_for_teacher(conn, self._teacher_id)
            my_classes = list_teacher_classes(conn, self._teacher_id)
        finally:
            conn.close()

        self.students_table.setRowCount(len(students))
        for row_index, row in enumerate(students):
            values = [
                row.student_code or "-",
                row.username,
                row.full_name,
                row.class_names,
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.students_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.students_table.setCellWidget(
                row_index, len(values), self._build_student_actions_cell(row)
            )

        self.total_my_students_card.set_value(str(student_count))
        self.students_my_classes_card.set_value(str(len(my_classes)))
        self.my_students_card.set_value(str(student_count))

    def refresh_incoming_student_transfer_requests_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            requests = list_pending_student_transfer_requests_for_teacher(conn, self._teacher_id)
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
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            requests = list_decided_student_transfer_requests_for_teacher(conn, self._teacher_id)
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

    def refresh_student_class_dropdown(self) -> None:
        conn = get_connection()
        try:
            my_classes = list_teacher_classes(conn, self._teacher_id)
        finally:
            conn.close()

        self.new_student_class_dropdown.clear()
        self.new_student_class_dropdown.addItem("Unassigned (No Class)", None)
        for class_ in my_classes:
            self.new_student_class_dropdown.addItem(class_.class_name, class_.class_id)
        self.new_student_class_dropdown.setCurrentIndex(0)

    def refresh_materials_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            materials = list_materials_for_teacher(conn, self._teacher_id)
            total_count = count_materials_for_teacher(conn, self._teacher_id)
            kertas1_count = count_materials_for_teacher_by_paper_type(conn, self._teacher_id, PAPER_TYPE_KERTAS_1)
            kertas2_count = count_materials_for_teacher_by_paper_type(conn, self._teacher_id, PAPER_TYPE_KERTAS_2)
        finally:
            conn.close()

        self.materials_table.clearContents()
        self.materials_table.setRowCount(len(materials))
        for row_index, row in enumerate(materials):
            values = [
                row.material_id,
                row.title,
                row.paper_type,
                row.class_names or "",
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.materials_table.removeCellWidget(row_index, col_index)
                self.materials_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.materials_table.setCellWidget(
                row_index, len(values), self._build_material_actions_cell(row)
            )

        self.total_materials_card.set_value(str(total_count))
        self.kertas1_materials_card.set_value(str(kertas1_count))
        self.kertas2_materials_card.set_value(str(kertas2_count))

    def refresh_material_classes_checklist(self) -> None:
        conn = get_connection()
        try:
            my_classes = list_teacher_classes(conn, self._teacher_id)
        finally:
            conn.close()

        self.material_classes_list.clear()
        for class_ in my_classes:
            item = QListWidgetItem(class_.class_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, class_.class_id)
            self.material_classes_list.addItem(item)

    def handle_toggle_material_class_item(self, item: QListWidgetItem) -> None:
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def refresh_external_revisions_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            revisions = list_external_revisions_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.external_revisions_table.clearContents()
        self.external_revisions_table.setRowCount(len(revisions))
        for row_index, row in enumerate(revisions):
            values = [
                row.external_revision_id,
                row.username,
                row.student_name,
                row.class_name,
                row.title,
                row.paper_type,
                row.status,
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.external_revisions_table.removeCellWidget(row_index, col_index)
                self.external_revisions_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.external_revisions_table.item(
                    row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("status")),
                str(row.status))
            self.external_revisions_table.item(
                row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("student_name")
            ).setToolTip(row.student_name)
            self.external_revisions_table.item(
                row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("class_name")
            ).setToolTip(row.class_name)
            self.external_revisions_table.item(
                row_index, EXTERNAL_REVISION_TABLE_COLUMNS.index("title")
            ).setToolTip(row.title)
            self.external_revisions_table.setCellWidget(
                row_index, len(values), self._build_external_revision_actions_cell(row)
            )

    def refresh_attempts_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            attempts = list_attempts_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.attempts_table.clearContents()
        self.attempts_table.setRowCount(len(attempts))
        for row_index, row in enumerate(attempts):
            values = [
                row.attempt_id,
                row.username,
                row.student_name,
                row.class_name,
                row.material_title,
                row.paper_type,
                row.attempt_no,
                row.status,
                format_timestamp(row.submitted_at),
            ]
            for col_index, value in enumerate(values):
                self.attempts_table.removeCellWidget(row_index, col_index)
                self.attempts_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            paint_status_item(
                self.attempts_table.item(row_index, ATTEMPT_TABLE_COLUMNS.index("status")),
                str(row.status))
            self.attempts_table.item(
                row_index, ATTEMPT_TABLE_COLUMNS.index("student_name")
            ).setToolTip(row.student_name)
            self.attempts_table.item(
                row_index, ATTEMPT_TABLE_COLUMNS.index("material_title")
            ).setToolTip(row.material_title)
            self.attempts_table.setCellWidget(
                row_index, len(values), self._build_attempt_actions_cell(row)
            )
        self.refresh_teacher_attention_dashboard()

    def refresh_templates_table(self) -> None:
        if self._teacher_id is None:
            return

        conn = get_connection()
        try:
            templates = list_templates_for_teacher(conn, self._teacher_id)
            total_count = count_templates_for_teacher(conn, self._teacher_id)
            kertas1_count = count_templates_for_teacher_by_paper_type(conn, self._teacher_id, PAPER_TYPE_KERTAS_1)
            kertas2_count = count_templates_for_teacher_by_paper_type(conn, self._teacher_id, PAPER_TYPE_KERTAS_2)
        finally:
            conn.close()

        self.templates_table.clearContents()
        self.templates_table.setRowCount(len(templates))
        for row_index, row in enumerate(templates):
            values = [
                row.template_id,
                row.title,
                row.paper_type,
                row.region_count,
                format_timestamp(row.created_at),
            ]
            for col_index, value in enumerate(values):
                self.templates_table.removeCellWidget(row_index, col_index)
                self.templates_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.templates_table.item(row_index, TEMPLATE_TABLE_COLUMNS.index("title")).setToolTip(row.title)
            self.templates_table.setCellWidget(
                row_index, len(values), self._build_template_actions_cell(row)
            )

        self.total_templates_card.set_value(str(total_count))
        self.kertas1_templates_card.set_value(str(kertas1_count))
        self.kertas2_templates_card.set_value(str(kertas2_count))

    def refresh_template_regions(self) -> None:
        if self._current_template is None:
            return

        conn = get_connection()
        try:
            regions = list_template_regions(conn, self._teacher_id, self._current_template.template_id)
        except ValueError as exc:
            show_error(self, "Load Regions Failed", str(exc))
            return
        finally:
            conn.close()

        self.template_canvas.clear_overlays()
        self.template_regions_table.clearContents()
        self.template_regions_table.setRowCount(len(regions))
        self._template_region_checkboxes = {}
        for row_index, region in enumerate(regions):
            is_ignore = region.region_type == REGION_TYPE_IGNORE
            self.template_regions_table.setCellWidget(
                row_index, 0, self._build_template_region_select_cell(region)
            )
            label_text = f"{region.label} (IGNORE)" if is_ignore else region.label
            label_item = QTableWidgetItem(label_text)
            if is_ignore:
                label_item.setForeground(QBrush(QColor(styles.DESTRUCTIVE)))
                label_item.setToolTip("Ignore region - excluded from marking, groups, and extraction.")
            self.template_regions_table.setItem(row_index, 1, label_item)
            self.template_regions_table.setItem(row_index, 2, QTableWidgetItem(str(region.page_number)))
            self.template_regions_table.setItem(row_index, 3, QTableWidgetItem(region.shape_type.capitalize()))
            self.template_regions_table.setCellWidget(
                row_index, 4, self._build_template_region_action_cell(region)
            )
            # Only highlight the current page's regions on the preview - the
            # table above still lists every region across every page.
            if region.page_number != self._current_template_page:
                continue
            if region.shape_type == SHAPE_TYPE_POLYGON:
                points = parse_polygon_points(region.polygon_points_json)
                self.template_canvas.add_polygon_region_overlay(
                    region.label, points, is_ignore=is_ignore, rotation_angle=region.rotation_angle
                )
            else:
                self.template_canvas.add_region_overlay(
                    region.label, region.x, region.y, region.width, region.height,
                    is_ignore=is_ignore, rotation_angle=region.rotation_angle,
                )

        self.refresh_template_region_groups()

    def refresh_template_region_groups(self) -> None:
        if self._current_template is None:
            return

        conn = get_connection()
        try:
            groups = list_region_groups(conn, self._teacher_id, self._current_template.template_id)
            members_by_group = {
                group.group_id: list_group_members(conn, self._teacher_id, group.group_id) for group in groups
            }
        except ValueError as exc:
            show_error(self, "Load Groups Failed", str(exc))
            return
        finally:
            conn.close()

        self.template_region_groups_table.clearContents()
        self.template_region_groups_table.setRowCount(len(groups))
        for row_index, group in enumerate(groups):
            members = members_by_group[group.group_id]
            members_text = ", ".join(f"{member.label} (P{member.page_number})" for member in members)
            self.template_region_groups_table.setItem(row_index, 0, QTableWidgetItem(group.label))
            self.template_region_groups_table.setItem(row_index, 1, QTableWidgetItem(group.region_type))
            members_item = QTableWidgetItem(members_text)
            members_item.setToolTip(members_text)
            self.template_region_groups_table.setItem(row_index, 2, members_item)
            self.template_region_groups_table.setCellWidget(
                row_index, 3, self._build_region_group_action_cell(group)
            )

    def refresh_marking_questions_table(self) -> None:
        if self._current_marking_setup is None:
            self.marking_questions_table.clearContents()
            self.marking_questions_table.setRowCount(0)
            return

        conn = get_connection()
        try:
            questions = list_marking_questions(conn, self._teacher_id, self._current_marking_setup.setup_id)
        except ValueError as exc:
            show_error(self, "Load Marking Questions Failed", str(exc))
            return
        finally:
            conn.close()

        self.marking_questions_table.clearContents()
        self.marking_questions_table.setRowCount(len(questions))
        for row_index, row in enumerate(questions):
            values = [
                row.question_no,
                row.correct_answer,
                row.max_mark,
                row.question_type,
                row.explanation or "",
                row.region_label or "",
            ]
            for col_index, value in enumerate(values):
                self.marking_questions_table.removeCellWidget(row_index, col_index)
                self.marking_questions_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.marking_questions_table.setCellWidget(
                row_index, len(values), self._build_marking_question_action_cell(row)
            )

    def refresh_marking_setup_template_dropdown(self) -> None:
        if self._current_marking_material is None:
            return

        conn = get_connection()
        try:
            templates = [
                t for t in list_templates_for_teacher(conn, self._teacher_id)
                if t.paper_type == self._current_marking_material.paper_type
            ]
        finally:
            conn.close()

        self.marking_setup_template_dropdown.clear()
        self.marking_setup_template_dropdown.addItem("-- No template selected --", None)
        for template in templates:
            self.marking_setup_template_dropdown.addItem(template.title, template.template_id)

    # --- Handlers: Classes / transfer requests -------------------------------

    def handle_join_class(self, class_: ClassWithTeacher) -> None:
        confirmed = prompt_confirm(
            self,
            "Join Class",
            "Join this class as teacher in charge?",
            confirm_text="Join",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            join_unassigned_class(conn, self._teacher_id, class_.class_id)
            error_message = None
        except ValueError as exc:
            error_message = str(exc)
        finally:
            conn.close()

        self.refresh_table()

        if error_message is not None:
            show_error(self, "Join Class Failed", error_message)
            return

        show_success(self, "Join Class", "You have joined this class as teacher in charge.")

    def handle_request_transfer(self, class_: ClassWithTeacher) -> None:
        reason = prompt_input(
            self,
            "Request Transfer",
            f"Optionally explain why you'd like to take over '{class_.class_name}' "
            "(leave blank if none).",
        )
        if reason is None:
            return

        conn = get_connection()
        try:
            create_transfer_request(conn, self._teacher_id, class_.class_id, reason)
        except ValueError as exc:
            show_error(self, "Request Transfer Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_table()
        show_success(self, "Request Transfer", "Transfer request submitted successfully.")

    def handle_approve_request(self, request: TransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Approve Request Failed", "No logged-in teacher was found.")
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

        self.refresh_table()
        self.refresh_incoming_requests_table()
        show_success(self, "Approve Request", "Transfer request approved successfully.")

    def handle_reject_request(self, request: TransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Reject Request Failed", "No logged-in teacher was found.")
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

        self.refresh_incoming_requests_table()
        show_success(self, "Reject Request", "Transfer request rejected.")

    def handle_view_students(self, class_: ClassWithTeacher) -> None:
        conn = get_connection()
        try:
            students = get_students_in_class_for_teacher(conn, self._teacher_id, class_.class_id)
        except ValueError as exc:
            show_error(self, "View Students Failed", str(exc))
            return
        finally:
            conn.close()

        if not students:
            message = f"No students have been added to '{class_.class_name}' yet."
        else:
            lines = [f"• {s.full_name} ({s.username})" for s in students]
            message = f"Students in '{class_.class_name}':\n\n" + "\n".join(lines)

        show_info(self, f"Students in {class_.class_name}", message)

    # --- Handlers: Students -------------------------------------------------

    def handle_open_create_student_page(self) -> None:
        self.refresh_student_class_dropdown()
        self.shell.show_page("Create Student")

    def handle_toggle_new_student_show_password(self, checked: bool) -> None:
        self.new_student_password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def handle_create_student(self) -> None:
        username = self.new_student_username_input.text()
        full_name = self.new_student_full_name_input.text()
        password = self.new_student_password_input.text()
        class_id = self.new_student_class_dropdown.currentData()

        conn = get_connection()
        try:
            if class_id is None:
                create_student(conn, username, full_name, password)
            else:
                create_student_in_class(conn, self._teacher_id, username, full_name, password, class_id)
        except ValueError as exc:
            show_error(self, "Create Student Failed", str(exc))
            return
        finally:
            conn.close()

        self.new_student_username_input.clear()
        self.new_student_full_name_input.clear()
        self.new_student_password_input.clear()
        self.new_student_show_password_checkbox.setChecked(False)
        self.refresh_students_table()
        show_success(self, "Create Student", "Student account created successfully.")
        self.shell.show_page("Students")

    def handle_cancel_create_student(self) -> None:
        self.new_student_username_input.clear()
        self.new_student_full_name_input.clear()
        self.new_student_password_input.clear()
        self.new_student_show_password_checkbox.setChecked(False)
        self.shell.show_page("Students")

    def handle_add_existing_student(self) -> None:
        """Primary Add Existing Student entry point: shows every student
        account as a candidate row (student_code, username, full_name,
        current class/Unassigned, current teacher, and the expected action),
        so a teacher never has to already know a code/username by heart."""
        conn = get_connection()
        try:
            candidates = list_add_existing_student_candidates(conn, self._teacher_id)
        finally:
            conn.close()

        if not candidates:
            show_error(self, "Add Existing Student Failed", "There are no student accounts in the system yet.")
            return

        column_labels = ["Student Code", "Username", "Full Name", "Current Class", "Current Teacher", "Expected Action"]
        rows = [
            (
                [
                    c.student_code or "-",
                    c.username,
                    c.full_name,
                    c.current_class_name or "Unassigned",
                    c.current_teacher_name or "-",
                    c.expected_action,
                ],
                c.user_id,
            )
            for c in candidates
        ]
        student_id = prompt_select_from_table(
            self,
            "Add Existing Student",
            "Pick a student to add to one of your classes. Expected Action shows what will "
            "happen based on where they are now.",
            column_labels,
            rows,
        )
        if student_id is CANCELLED:
            return

        conn = get_connection()
        try:
            student = get_user_by_id(conn, student_id)
        finally:
            conn.close()

        self._complete_add_existing_student(student)

    def handle_find_existing_student_by_identifier(self) -> None:
        """Secondary helper: find a single student directly by Student Code
        or username, for when a teacher already knows the identifier and
        wants to skip the candidate list."""
        identifier = prompt_input(
            self,
            "Find Existing Student",
            "Enter the student's Student Code (e.g. TP0001) or username.",
        )
        if identifier is None:
            return

        conn = get_connection()
        try:
            student = find_student_by_identifier(conn, identifier)
        finally:
            conn.close()

        if student is None:
            show_error(self, "Add Existing Student Failed", f"No student account found for '{identifier.strip()}'.")
            return

        self._complete_add_existing_student(student)

    def _complete_add_existing_student(self, student) -> None:
        conn = get_connection()
        try:
            my_classes = list_teacher_classes(conn, self._teacher_id)
            current_classes = get_classes_for_student(conn, student.user_id)
        finally:
            conn.close()

        if not my_classes:
            show_error(self, "Add Existing Student Failed", "You do not own any classes yet.")
            return

        options = [(class_.class_name, class_.class_id) for class_ in my_classes]
        class_id = prompt_select(
            self,
            "Add Existing Student",
            f"Select the class to add {student.full_name} ({student.student_code or student.username}) to.",
            options,
        )
        if class_id is CANCELLED:
            return

        if (
            current_classes
            and current_classes[0].teacher_id == self._teacher_id
            and current_classes[0].class_id != class_id
        ):
            target_name = next(c.class_name for c in my_classes if c.class_id == class_id)
            confirmed = prompt_confirm(
                self,
                "Move Student",
                f"{student.full_name} is currently in your class '{current_classes[0].class_name}'. "
                f"Move them to '{target_name}'?",
                confirm_text="Move",
            )
            if not confirmed:
                return

        conn = get_connection()
        try:
            try:
                outcome = add_existing_student_to_class(conn, self._teacher_id, student.user_id, class_id)
            except ValueError as exc:
                show_error(self, "Add Existing Student Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_students_table()
        self.refresh_incoming_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()

        if outcome == DIRECT_ASSIGNED:
            show_success(self, "Add Existing Student", "Student was Unassigned and has been added directly.")
        elif outcome == ALREADY_IN_CLASS:
            show_info(self, "Add Existing Student", "This student is already in this class.")
        elif outcome == MOVED_WITHIN_OWN_CLASSES:
            show_success(self, "Add Existing Student", "Student moved to the new class successfully.")
        elif outcome == TRANSFER_REQUEST_CREATED:
            show_success(
                self,
                "Add Existing Student",
                "This student is currently in another class. A transfer request has been "
                "sent to their current teacher for approval.",
            )

    def handle_remove_student(self, row: TeacherStudentRow) -> None:
        conn = get_connection()
        try:
            my_classes_with_student = get_classes_for_student_owned_by_teacher(
                conn, self._teacher_id, row.user_id
            )
        finally:
            conn.close()

        if not my_classes_with_student:
            show_error(self, "Remove Student Failed", "This student is not in any of your classes.")
            return

        if len(my_classes_with_student) == 1:
            class_id = my_classes_with_student[0].class_id
            class_name = my_classes_with_student[0].class_name
        else:
            options = [(c.class_name, c.class_id) for c in my_classes_with_student]
            selected = prompt_select(
                self,
                "Remove From Class",
                f"Select which class to remove {row.full_name} from.",
                options,
            )
            if selected is CANCELLED:
                return
            class_id = selected
            class_name = next(c.class_name for c in my_classes_with_student if c.class_id == class_id)

        confirmed = prompt_confirm(
            self,
            "Remove Student",
            f"Remove {row.full_name} from '{class_name}'? Their account will remain active.",
            confirm_text="Remove",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            remove_student_from_class(conn, self._teacher_id, class_id, row.user_id)
        except ValueError as exc:
            show_error(self, "Remove Student Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_students_table()
        show_success(self, "Remove Student", "Student removed from class successfully.")

    def handle_approve_student_transfer_request(self, request: StudentTransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Approve Request Failed", "No logged-in teacher was found.")
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

        self.refresh_students_table()
        self.refresh_incoming_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        show_success(self, "Approve Request", "Student transfer request approved successfully.")

    def handle_reject_student_transfer_request(self, request: StudentTransferRequestWithDetails) -> None:
        if self._user is None:
            show_error(self, "Reject Request Failed", "No logged-in teacher was found.")
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

        self.refresh_incoming_student_transfer_requests_table()
        self.refresh_student_transfer_history_table()
        show_success(self, "Reject Request", "Student transfer request rejected.")

    # --- Handlers: Revision Materials ---------------------------------------

    def handle_open_create_material_page(self) -> None:
        conn = get_connection()
        try:
            my_classes = list_teacher_classes(conn, self._teacher_id)
        finally:
            conn.close()

        if not my_classes:
            show_error(
                self,
                "Create Revision Material Failed",
                "You do not own any classes yet. Create or join a class before adding revision materials.",
            )
            return

        self.new_material_title_input.clear()
        self.new_material_paper_type_dropdown.setCurrentIndex(0)
        self._new_material_question_paper_path = ""
        self._new_material_marking_scheme_path = ""
        self.question_paper_status_label.setText("No file selected")
        self.marking_scheme_status_label.setText("No file selected")
        self.refresh_material_classes_checklist()
        self.shell.show_page("Create Revision Material")

    def handle_choose_question_paper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Question Paper", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_material_question_paper_path = path
        self.question_paper_status_label.setText(Path(path).name)

    def handle_choose_marking_scheme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Marking Scheme", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_material_marking_scheme_path = path
        self.marking_scheme_status_label.setText(Path(path).name)

    def handle_create_revision_material(self) -> None:
        title = self.new_material_title_input.text()
        paper_type = self.new_material_paper_type_dropdown.currentData()
        class_ids = [
            self.material_classes_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.material_classes_list.count())
            if self.material_classes_list.item(i).checkState() == Qt.CheckState.Checked
        ]

        if paper_type is None:
            show_error(self, "Create Revision Material Failed", "Please select a paper type.")
            return

        conn = get_connection()
        try:
            create_revision_material(
                conn,
                self._teacher_id,
                title,
                paper_type,
                self._new_material_question_paper_path,
                self._new_material_marking_scheme_path,
                class_ids,
            )
        except ValueError as exc:
            show_error(self, "Create Revision Material Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_materials_table()
        show_success(self, "Create Revision Material", "Revision material created successfully.")
        self.shell.show_page("Revision Materials")

    def handle_cancel_create_material(self) -> None:
        self.shell.show_page("Revision Materials")

    # --- Main Marking System: Marking Session handlers (Stage 11L) ----------

    def handle_choose_marking_session_question_paper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Question Paper", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_marking_session_question_paper_path = path
        self.marking_session_question_paper_status_label.setText(Path(path).name)

    def handle_choose_marking_session_answer_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Answer Key / Marking Scheme", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_marking_session_answer_key_path = path
        self.marking_session_answer_key_status_label.setText(Path(path).name)

    def handle_create_marking_session(self) -> None:
        title = self.new_marking_session_title_input.text()
        paper_type = self.new_marking_session_paper_type_dropdown.currentData()

        if paper_type is None:
            show_error(self, "Create Marking Session Failed", "Please select a paper type.")
            return

        conn = get_connection()
        try:
            create_marking_session(
                conn,
                self._teacher_id,
                title,
                paper_type,
                self._new_marking_session_question_paper_path or None,
                self._new_marking_session_answer_key_path or None,
            )
        except ValueError as exc:
            show_error(self, "Create Marking Session Failed", str(exc))
            return
        finally:
            conn.close()

        self.new_marking_session_title_input.clear()
        self.new_marking_session_paper_type_dropdown.setCurrentIndex(0)
        self._new_marking_session_question_paper_path = ""
        self._new_marking_session_answer_key_path = ""
        self.marking_session_question_paper_status_label.setText("No file selected")
        self.marking_session_answer_key_status_label.setText("No file selected")

        self.refresh_marking_sessions_table()
        show_success(self, "Create Marking Session", "Marking session created successfully.")

    def refresh_marking_sessions_table(self) -> None:
        # Stage 11V removed the old top-level "Existing Marking Sessions"
        # table from the Marking page (replaced by the Subject Profile
        # table) - this method is still called by several still-existing
        # Marking Session Detail handlers (which remain reachable/tested
        # via direct service calls, not this removed table), so it safely
        # no-ops rather than being hunted down and removed from every call
        # site.
        if not hasattr(self, "marking_sessions_table"):
            return
        conn = get_connection()
        try:
            sessions = list_marking_sessions_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.marking_sessions_table.clearContents()
        self.marking_sessions_table.setRowCount(len(sessions))
        for row_index, row in enumerate(sessions):
            self.marking_sessions_table.setItem(row_index, 0, QTableWidgetItem(row.title))
            self.marking_sessions_table.setItem(row_index, 1, QTableWidgetItem(row.paper_type))
            self.marking_sessions_table.setItem(row_index, 2, QTableWidgetItem(format_marking_status_label(row.status)))
            self.marking_sessions_table.setItem(row_index, 3, QTableWidgetItem(str(row.answer_file_count)))
            self.marking_sessions_table.setItem(row_index, 4, QTableWidgetItem(format_timestamp(row.created_at)))
            self.marking_sessions_table.setCellWidget(row_index, 5, self._build_marking_session_action_cell(row))

    def handle_open_marking_session(self, row: MainMarkingSessionRow) -> None:
        conn = get_connection()
        try:
            session = get_marking_session(conn, row.session_id, self._teacher_id)
        except ValueError as exc:
            show_error(self, "Open Marking Session Failed", str(exc))
            return
        finally:
            conn.close()

        self._current_marking_session = session
        self.marking_session_detail_title_label.setText(f"Marking Session - {session.title}")
        self.marking_session_detail_subtitle_label.setText(
            f"Paper Type: {session.paper_type}  |  Status: {format_marking_status_label(session.status)}"
        )
        self.marking_session_detail_question_paper_label.setText(get_safe_display_path(session.question_paper_path))
        self.marking_session_detail_answer_key_label.setText(get_safe_display_path(session.answer_key_path))

        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_session_template_section()
        self.shell.show_page("Marking Session Detail")

    def _update_marking_session_run_preprocessing_button_state(self, answer_file_count: int) -> None:
        session = self._current_marking_session
        ready = bool(
            session is not None and session.question_paper_path and session.answer_key_path and answer_file_count > 0
        )
        self.marking_session_run_preprocessing_button.setEnabled(ready)
        self.marking_session_run_preprocessing_button.setToolTip(
            ""
            if ready
            else "Add a question paper, an answer key / marking scheme, and at least one "
            "student answer PDF before running preprocessing."
        )

    def _update_marking_session_run_ocr_button_state(self) -> None:
        session = self._current_marking_session
        ready = bool(
            session is not None
            and session.status in (STATUS_PREPROCESSED, STATUS_OCR_COMPLETED, STATUS_ANSWER_EXTRACTED, STATUS_MARKED)
        )
        self.marking_session_run_ocr_button.setEnabled(ready)
        self.marking_session_run_ocr_button.setToolTip(
            "" if ready else "Run preprocessing successfully before running OCR."
        )

    def _update_marking_session_run_marking_button_state(self) -> None:
        session = self._current_marking_session
        if session is None:
            self.marking_session_run_marking_button.setEnabled(False)
            return

        if session.paper_type != PAPER_TYPE_KERTAS_1:
            self.marking_session_run_marking_button.setEnabled(False)
            self.marking_session_run_marking_button.setToolTip(
                "Kertas 2 marking is not supported in this stage. Only Kertas 1 rule-based marking is available."
            )
            return

        ready = session.status in (STATUS_ANSWER_EXTRACTED, STATUS_MARKED)
        self.marking_session_run_marking_button.setEnabled(ready)
        self.marking_session_run_marking_button.setToolTip(
            "" if ready else "Run answer extraction successfully before running marking."
        )

    def handle_delete_marking_session(self, row: MainMarkingSessionRow) -> None:
        confirmed = prompt_confirm(
            self,
            "Delete Marking Session",
            f"Delete marking session '{row.title}'? Its uploaded answer files will also be removed from this list.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            delete_marking_session(conn, self._teacher_id, row.session_id)
        except ValueError as exc:
            show_error(self, "Delete Marking Session Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_sessions_table()

    def handle_back_from_marking_session_detail(self) -> None:
        self._current_marking_session = None
        self.shell.show_page("Marking")

    def handle_add_marking_session_answer_files(self) -> None:
        if self._current_marking_session is None:
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Student Answer PDFs", "", "PDF Files (*.pdf)"
        )
        if not paths:
            return

        conn = get_connection()
        errors = []
        try:
            for path in paths:
                try:
                    add_answer_file_to_session(conn, self._current_marking_session.session_id, self._teacher_id, path)
                except ValueError as exc:
                    errors.append(f"{Path(path).name}: {exc}")
        finally:
            conn.close()

        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_sessions_table()

        if errors:
            show_error(self, "Some Files Failed to Upload", "\n".join(errors))
        else:
            show_success(self, "Add Student Answer PDFs", f"Added {len(paths)} answer file(s) successfully.")

    def refresh_marking_session_answer_files_table(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            answer_files = list_answer_files_for_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        finally:
            conn.close()

        self.marking_session_answer_files_table.clearContents()
        self.marking_session_answer_files_table.setRowCount(len(answer_files))
        for row_index, answer_file in enumerate(answer_files):
            self.marking_session_answer_files_table.setItem(
                row_index, 0, QTableWidgetItem(get_answer_file_display_name(answer_file))
            )
            self.marking_session_answer_files_table.setItem(
                row_index, 1, QTableWidgetItem(answer_file.student_name or "")
            )
            self.marking_session_answer_files_table.setItem(
                row_index, 2, QTableWidgetItem(answer_file.student_code or "")
            )
            self.marking_session_answer_files_table.setItem(
                row_index, 3, QTableWidgetItem(str(answer_file.page_count) if answer_file.page_count else "-")
            )
            self.marking_session_answer_files_table.setItem(
                row_index, 4, QTableWidgetItem(format_marking_status_label(answer_file.processing_status))
            )
            self.marking_session_answer_files_table.setCellWidget(
                row_index, 5, self._build_marking_session_answer_file_action_cell(answer_file)
            )

        self._update_marking_session_run_preprocessing_button_state(len(answer_files))
        self._update_marking_session_run_ocr_button_state()
        self._update_marking_session_run_marking_button_state()

    def handle_run_marking_session_preprocessing(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            run = run_preprocessing_for_session(conn, self._current_marking_session.session_id, self._teacher_id)
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Run Preprocessing Failed", str(exc))
            return
        finally:
            conn.close()

        self.marking_session_detail_subtitle_label.setText(
            f"Paper Type: {self._current_marking_session.paper_type}  |  "
            f"Status: {format_marking_status_label(self._current_marking_session.status)}"
        )
        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_session_template_section()

        message = f"{run.message}\n\nOCR, answer extraction, and marking will be added in later stages."
        if run.status == RUN_STATUS_FAILED:
            show_error(self, "Run Preprocessing", message)
        else:
            show_success(self, "Run Preprocessing", message)

    def handle_run_marking_session_ocr(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            run = run_ocr_for_session(conn, self._teacher_id, self._current_marking_session.session_id)
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Run OCR Failed", str(exc))
            return
        finally:
            conn.close()

        self.marking_session_detail_subtitle_label.setText(
            f"Paper Type: {self._current_marking_session.paper_type}  |  "
            f"Status: {format_marking_status_label(self._current_marking_session.status)}"
        )
        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_session_template_section()

        message = f"{run.message}\n\nAnswer extraction and marking will be added in a later stage."
        if run.status == RUN_STATUS_FAILED:
            show_error(self, "Run OCR", message)
        else:
            show_success(self, "Run OCR", message)

    def refresh_marking_session_template_section(self) -> None:
        session = self._current_marking_session
        if session is None:
            return

        conn = get_connection()
        try:
            template_summary = get_marking_session_template_summary(conn, self._teacher_id, session.session_id)
            readiness = get_marking_session_extraction_readiness(conn, self._teacher_id, session.session_id)
        finally:
            conn.close()

        if template_summary.template is None:
            self.marking_session_template_info_label.setText(
                "No template linked. Choose a template before future answer extraction."
            )
            self.marking_session_template_targets_label.setText("")
            self.marking_session_remove_template_button.setEnabled(False)
        else:
            template = template_summary.template
            self.marking_session_template_info_label.setText(
                f"{template.title}  (Paper Type: {template.paper_type})"
            )
            targets = template_summary.extraction_targets
            self.marking_session_template_targets_label.setText(
                f"Extraction Targets: {targets.total_region_targets} region(s) "
                f"({targets.rectangle_targets} rectangle, {targets.polygon_targets} polygon, "
                f"{targets.rotated_targets} rotated), {targets.group_targets} group(s) "
                f"({targets.cross_page_group_targets} cross-page), pages: {targets.page_numbers}"
            )
            self.marking_session_remove_template_button.setEnabled(True)

        if readiness.is_ready:
            self.marking_session_template_readiness_label.setText("Ready for answer extraction.")
        else:
            self.marking_session_template_readiness_label.setText(
                f"Not ready for answer extraction: {readiness.reason}"
            )

        self.marking_session_run_extraction_button.setEnabled(readiness.is_ready)
        self.marking_session_run_extraction_button.setToolTip("" if readiness.is_ready else readiness.reason)

    def handle_run_marking_session_extraction(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            run = run_answer_extraction_for_session(conn, self._teacher_id, self._current_marking_session.session_id)
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Run Extraction Failed", str(exc))
            return
        finally:
            conn.close()

        self.marking_session_detail_subtitle_label.setText(
            f"Paper Type: {self._current_marking_session.paper_type}  |  "
            f"Status: {format_marking_status_label(self._current_marking_session.status)}"
        )
        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_session_template_section()

        message = f"{run.message}\n\nMarking and review will be added in a later stage."
        if run.status == RUN_STATUS_FAILED:
            show_error(self, "Run Extraction", message)
        else:
            show_success(self, "Run Extraction", message)

    def handle_run_marking_session_marking(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            run = run_kertas1_marking_for_session(conn, self._teacher_id, self._current_marking_session.session_id)
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Run Marking Failed", str(exc))
            return
        finally:
            conn.close()

        self.marking_session_detail_subtitle_label.setText(
            f"Paper Type: {self._current_marking_session.paper_type}  |  "
            f"Status: {format_marking_status_label(self._current_marking_session.status)}"
        )
        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_session_template_section()
        self.refresh_main_marking_review_table()

        message = f"{run.message}\n\nTeacher review and final results will be added in a later stage."
        if run.status == RUN_STATUS_FAILED:
            show_error(self, "Run Marking", message)
        else:
            show_success(self, "Run Marking", message)

    def handle_view_extracted_answers(self, answer_file: MainMarkingAnswerFile) -> None:
        conn = get_connection()
        try:
            extracted_answers = list_extracted_answers_for_answer_file(
                conn, self._teacher_id, answer_file.answer_file_id
            )
        except ValueError as exc:
            show_error(self, "View Extracted Answers Failed", str(exc))
            return
        finally:
            conn.close()

        if not extracted_answers:
            show_detail(
                self, f"Extracted Answers - {get_answer_file_display_name(answer_file)}",
                "No extracted answers yet. Run Extraction for this session first.",
            )
            return

        lines = []
        for answer in extracted_answers:
            pages = ", ".join(str(p) for p in json.loads(answer.page_numbers_json))
            lines.append(
                f"[{answer.target_kind.upper()}] {answer.target_label}  "
                f"(Type: {answer.region_type or 'unknown'}, Page(s): {pages})\n"
                f"Status: {format_marking_status_label(answer.status)}"
                f"{'  - ' + answer.message if answer.message else ''}\n"
                f"Text: {answer.extracted_text or '(none)'}\n"
            )

        show_detail(
            self, f"Extracted Answers - {get_answer_file_display_name(answer_file)}", "\n".join(lines)
        )

    def handle_view_marked_answers(self, answer_file: MainMarkingAnswerFile) -> None:
        conn = get_connection()
        try:
            marked_answers = list_marked_answers_for_answer_file(conn, self._teacher_id, answer_file.answer_file_id)
        except ValueError as exc:
            show_error(self, "View Marking Failed", str(exc))
            return
        finally:
            conn.close()

        if not marked_answers:
            show_detail(
                self, f"Marking - {get_answer_file_display_name(answer_file)}",
                "No marking yet. Run Marking for this session first.",
            )
            return

        lines = []
        for marked in marked_answers:
            lines.append(
                f"[{marked.target_kind.upper()}] {marked.target_label}  (Type: {marked.region_type or 'unknown'})\n"
                f"Student Answer: {marked.student_answer_text or '(none)'}\n"
                f"Correct Answer: {marked.correct_answer_text or '(none)'}\n"
                f"Score: {marked.score if marked.score is not None else '-'} / {marked.max_score}\n"
                f"Status: {format_marking_status_label(marked.status)}"
                f"{'  - ' + marked.feedback if marked.feedback else ''}\n"
            )

        show_detail(
            self, f"Marking - {get_answer_file_display_name(answer_file)}", "\n".join(lines)
        )

    # --- Stage 11R: standalone Main Marking review --------------------------

    def refresh_main_marking_review_table(self) -> None:
        # The legacy Review tab was removed; the table only exists if the
        # legacy page was ever built (it no longer is).
        if not hasattr(self, "main_marking_review_table"):
            return
        conn = get_connection()
        try:
            files = list_reviewable_main_marking_files(conn, self._teacher_id)
        finally:
            conn.close()

        self.main_marking_review_empty_label.setVisible(len(files) == 0)
        self.main_marking_review_table.setVisible(len(files) > 0)

        self.main_marking_review_table.clearContents()
        self.main_marking_review_table.setRowCount(len(files))
        for row_index, file_row in enumerate(files):
            self.main_marking_review_table.setItem(row_index, 0, QTableWidgetItem(file_row.session_title))
            self.main_marking_review_table.setItem(row_index, 1, QTableWidgetItem(file_row.paper_type))
            self.main_marking_review_table.setItem(row_index, 2, QTableWidgetItem(file_row.answer_file_display_name))
            self.main_marking_review_table.setItem(row_index, 3, QTableWidgetItem(file_row.student_name or ""))
            self.main_marking_review_table.setItem(row_index, 4, QTableWidgetItem(file_row.student_code or ""))
            self.main_marking_review_table.setItem(
                row_index, 5, QTableWidgetItem(format_marking_status_label(file_row.processing_status))
            )
            if file_row.total_marked_answers == 0:
                review_text = "No Marked Answers"
            elif file_row.reviewed_count == file_row.total_marked_answers:
                review_text = "Reviewed"
            elif file_row.reviewed_count > 0:
                review_text = f"{file_row.reviewed_count}/{file_row.total_marked_answers} Reviewed"
            else:
                review_text = "Pending Review"
            self.main_marking_review_table.setItem(row_index, 6, QTableWidgetItem(review_text))
            self.main_marking_review_table.setCellWidget(
                row_index, 7, self._build_main_marking_review_action_cell(file_row)
            )

    def handle_open_main_marking_review(self, file_row: ReviewableMainMarkingFile) -> None:
        conn = get_connection()
        try:
            marked_answers = get_marked_answers_for_review(conn, self._teacher_id, file_row.answer_file_id)
        except ValueError as exc:
            show_error(self, "Open Review Failed", str(exc))
            return
        finally:
            conn.close()

        if not marked_answers:
            show_error(self, "Open Review Failed", "No marked answers yet. Run Marking for this session first.")
            return

        self._current_main_marking_review_file = file_row
        self.main_marking_review_detail_title_label.setText(f"Review - {file_row.answer_file_display_name}")
        self.main_marking_review_detail_subtitle_label.setText(
            f"Session: {file_row.session_title}  |  Paper Type: {file_row.paper_type}"
        )
        self.refresh_main_marking_review_detail_table()
        self.shell.show_page("Main Marking Review Detail")

    def handle_review_answer_file_from_session_detail(self, answer_file: MainMarkingAnswerFile) -> None:
        if self._current_marking_session is None:
            return
        file_row = ReviewableMainMarkingFile(
            session_id=self._current_marking_session.session_id,
            session_title=self._current_marking_session.title,
            paper_type=self._current_marking_session.paper_type,
            answer_file_id=answer_file.answer_file_id,
            answer_file_display_name=get_answer_file_display_name(answer_file),
            student_name=answer_file.student_name,
            student_code=answer_file.student_code,
            processing_status=answer_file.processing_status,
            total_marked_answers=0,
            reviewed_count=0,
        )
        self.handle_open_main_marking_review(file_row)

    def handle_finalize_main_marking_answer_file(self, answer_file: MainMarkingAnswerFile) -> None:
        conn = get_connection()
        try:
            result = finalize_main_marking_answer_file(conn, self._teacher_id, answer_file.answer_file_id)
            if self._current_marking_session is not None:
                self._current_marking_session = get_marking_session(
                    conn, self._current_marking_session.session_id, self._teacher_id
                )
        except ValueError as exc:
            show_error(self, "Finalize Result Failed", str(exc))
            return
        finally:
            conn.close()

        if self._current_marking_session is not None:
            self.marking_session_detail_subtitle_label.setText(
                f"Paper Type: {self._current_marking_session.paper_type}  |  "
                f"Status: {format_marking_status_label(self._current_marking_session.status)}"
            )
        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_sessions_table()
        self.refresh_main_marking_results_table()
        show_success(
            self, "Finalize Result",
            f"Result finalized. Final score: {result.total_score} / {result.max_score}",
        )

    def refresh_main_marking_review_detail_table(self) -> None:
        if self._current_main_marking_review_file is None:
            return

        conn = get_connection()
        try:
            marked_answers = get_marked_answers_for_review(
                conn, self._teacher_id, self._current_main_marking_review_file.answer_file_id
            )
        finally:
            conn.close()

        self.main_marking_review_detail_table.clearContents()
        self.main_marking_review_detail_table.setRowCount(len(marked_answers))
        for row_index, marked in enumerate(marked_answers):
            self.main_marking_review_detail_table.setItem(row_index, 0, QTableWidgetItem(marked.target_label))
            self.main_marking_review_detail_table.setItem(row_index, 1, QTableWidgetItem(marked.target_kind))
            self.main_marking_review_detail_table.setItem(
                row_index, 2, QTableWidgetItem(marked.student_answer_text or "(none)")
            )
            self.main_marking_review_detail_table.setItem(
                row_index, 3, QTableWidgetItem(marked.correct_answer_text or "(none)")
            )
            machine_score_text = f"{marked.score if marked.score is not None else '-'} / {marked.max_score}"
            self.main_marking_review_detail_table.setItem(row_index, 4, QTableWidgetItem(machine_score_text))
            teacher_score_text = (
                f"{marked.teacher_score} / {marked.max_score}" if marked.teacher_score is not None else "Not reviewed"
            )
            self.main_marking_review_detail_table.setItem(row_index, 5, QTableWidgetItem(teacher_score_text))
            self.main_marking_review_detail_table.setItem(
                row_index, 6, QTableWidgetItem(format_marking_status_label(marked.review_status))
            )
            self.main_marking_review_detail_table.setCellWidget(
                row_index, 7, self._build_marked_answer_review_action_cell(marked)
            )

        all_reviewed = len(marked_answers) > 0 and all(
            m.review_status == REVIEW_STATUS_REVIEWED for m in marked_answers
        )
        self.main_marking_mark_file_reviewed_button.setEnabled(all_reviewed)

    def handle_review_marked_answer(self, marked_answer: MainMarkingMarkedAnswer) -> None:
        context = (
            f"Student Answer: {marked_answer.student_answer_text or '(none)'}\n"
            f"Correct Answer: {marked_answer.correct_answer_text or '(none)'}\n"
            f"Machine Score: {marked_answer.score if marked_answer.score is not None else '-'} / "
            f"{marked_answer.max_score}\n"
            f"Machine Status: {format_marking_status_label(marked_answer.status)}"
            f"{'  - ' + marked_answer.feedback if marked_answer.feedback else ''}"
        )
        initial = {
            "teacher_score": marked_answer.teacher_score if marked_answer.teacher_score is not None else marked_answer.score,
            "teacher_feedback": marked_answer.teacher_feedback,
            "max_score": marked_answer.max_score,
        }
        values = prompt_main_marking_review(self, f"Review - {marked_answer.target_label}", context, initial)
        if values is None:
            return

        try:
            teacher_score = float(values["teacher_score"])
        except (TypeError, ValueError):
            show_error(self, "Save Review Failed", "Teacher score must be a number.")
            return

        conn = get_connection()
        try:
            try:
                review_marked_answer(
                    conn, self._teacher_id, marked_answer.marked_answer_id, teacher_score,
                    values["teacher_feedback"] or None,
                )
            except ValueError as exc:
                show_error(self, "Save Review Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_main_marking_review_detail_table()
        show_success(self, "Save Review", "Review saved.")

    def handle_mark_main_marking_answer_file_reviewed(self) -> None:
        if self._current_main_marking_review_file is None:
            return

        conn = get_connection()
        try:
            mark_answer_file_reviewed(conn, self._teacher_id, self._current_main_marking_review_file.answer_file_id)
        except ValueError as exc:
            show_error(self, "Mark Reviewed Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_main_marking_review_detail_table()
        self.refresh_main_marking_review_table()
        self.refresh_marking_session_answer_files_table()
        show_success(self, "Mark Reviewed", "Answer file marked as reviewed.")

    def handle_back_from_main_marking_review_detail(self) -> None:
        self._current_main_marking_review_file = None
        self.shell.show_page("Review")

    def handle_choose_marking_session_template(self) -> None:
        if self._current_marking_session is None:
            return

        conn = get_connection()
        try:
            compatible_templates = list_compatible_templates_for_session(
                conn, self._teacher_id, self._current_marking_session.session_id
            )
        finally:
            conn.close()

        if not compatible_templates:
            show_error(
                self, "Choose Template",
                "No compatible templates found for this session's paper type. "
                "Create a matching template in Template Editor first.",
            )
            return

        options = [(template.title, template.template_id) for template in compatible_templates]
        template_id = prompt_select(
            self, "Choose Template", "Select a template to link to this marking session.", options
        )
        if template_id is CANCELLED:
            return

        conn = get_connection()
        try:
            assign_template_to_marking_session(
                conn, self._teacher_id, self._current_marking_session.session_id, template_id
            )
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Choose Template Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_session_template_section()
        show_success(self, "Choose Template", "Template linked successfully.")

    def handle_remove_marking_session_template(self) -> None:
        if self._current_marking_session is None:
            return

        confirmed = prompt_confirm(
            self, "Remove Template",
            "Remove the linked template from this session? The template itself will not be deleted.",
            confirm_text="Remove",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            remove_template_from_marking_session(conn, self._teacher_id, self._current_marking_session.session_id)
            self._current_marking_session = get_marking_session(
                conn, self._current_marking_session.session_id, self._teacher_id
            )
        except ValueError as exc:
            show_error(self, "Remove Template Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_session_template_section()

    def handle_edit_marking_session_answer_file_student_info(self, answer_file: MainMarkingAnswerFile) -> None:
        values = prompt_student_info(
            self,
            f"Edit Student Info - {get_answer_file_display_name(answer_file)}",
            "Update this answer file's student name/code (both optional).",
            {"student_name": answer_file.student_name, "student_code": answer_file.student_code},
        )
        if values is None:
            return

        conn = get_connection()
        try:
            update_answer_file_student_info(
                conn, self._teacher_id, answer_file.answer_file_id, values["student_name"], values["student_code"]
            )
        except ValueError as exc:
            show_error(self, "Edit Student Info Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_session_answer_files_table()
        show_success(self, "Edit Student Info", "Student info updated successfully.")

    def handle_remove_marking_session_answer_file(self, answer_file: MainMarkingAnswerFile) -> None:
        confirmed = prompt_confirm(
            self,
            "Remove Answer File",
            f"Remove '{get_answer_file_display_name(answer_file)}' from this session?",
            confirm_text="Remove",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            remove_answer_file_from_session(conn, self._teacher_id, answer_file.answer_file_id)
        except ValueError as exc:
            show_error(self, "Remove Answer File Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_session_answer_files_table()
        self.refresh_marking_sessions_table()

    def handle_view_material_details(self, row: TeacherMaterialRow) -> None:
        message = (
            f"Paper Type: {row.paper_type}\n"
            f"Assigned Classes: {row.class_names or 'None'}\n"
            f"Created: {format_timestamp(row.created_at)}\n\n"
            f"Question Paper: {get_safe_display_path(row.question_paper_path)}\n\n"
            f"Marking Scheme: {get_safe_display_path(row.marking_scheme_path)}"
        )
        if row.paper_type == PAPER_TYPE_BOTH:
            message += (
                "\n\nNote: Both is a revision material label only in this prototype. "
                "Kertas 1 and Kertas 2 marking remain separate."
            )
        show_detail(self, row.title, message)

    # --- Handlers: External Revisions ---------------------------------------

    def handle_view_external_revision_details(self, row: TeacherExternalRevisionRow) -> None:
        message = (
            f"Student ID: {row.username}\n"
            f"Student Name: {row.student_name}\n"
            f"Class: {row.class_name}\n"
            f"Paper Type: {row.paper_type}\n"
            f"Status: {row.status}\n"
            f"Created: {format_timestamp(row.created_at)}\n\n"
            f"Question Paper: {get_safe_display_path(row.question_paper_path)}\n\n"
            f"Marking Scheme: {get_safe_display_path(row.marking_scheme_path)}\n\n"
            f"Completed Answer: {get_safe_display_path(row.completed_answer_path)}\n\n"
            "Teacher review and AI marking will be implemented in a later stage."
        )
        show_detail(self, row.title, message)

    def handle_preprocess_external_revision_answer(self, row: TeacherExternalRevisionRow) -> None:
        conn = get_connection()
        try:
            job = preprocess_document(
                conn,
                row.completed_answer_path,
                SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER,
                row.external_revision_id,
            )
        except ValueError as exc:
            show_error(self, "Preprocess Completed Answer Failed", str(exc))
            return
        finally:
            conn.close()

        if job.status == STATUS_COMPLETED:
            message = (
                f"Status: {job.status}\n"
                f"Pages Processed: {job.page_count}\n\n"
                f"Output Folder:\n{job.output_folder_path}\n\n"
                "OCR and marking will be implemented in a later stage."
            )
            show_detail(self, "Preprocess Completed Answer", message)
        else:
            show_error(
                self,
                "Preprocess Completed Answer Failed",
                job.error_message or "Preprocessing failed for an unknown reason.",
            )

    def handle_run_ocr_external_revision_answer(self, row: TeacherExternalRevisionRow) -> None:
        conn = get_connection()
        try:
            preprocessing_job = get_latest_preprocessing_job(
                conn, SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER, row.external_revision_id
            )
            if preprocessing_job is None or preprocessing_job.status != STATUS_COMPLETED:
                show_error(
                    self,
                    "Run OCR Failed",
                    "No completed preprocessing output found. Click Preprocess first.",
                )
                return
            try:
                ocr_job = run_ocr_for_preprocessing_job(
                    conn,
                    preprocessing_job.job_id,
                    SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER,
                    row.external_revision_id,
                )
            except ValueError as exc:
                show_error(self, "Run OCR Failed", str(exc))
                return
        finally:
            conn.close()

        if ocr_job.status == OCR_STATUS_COMPLETED:
            show_detail(self, "OCR Result", _build_ocr_result_message(ocr_job))
        else:
            show_error(self, "Run OCR Failed", ocr_job.error_message or "OCR failed for an unknown reason.")

    def handle_view_ocr_result_external_revision(self, row: TeacherExternalRevisionRow) -> None:
        conn = get_connection()
        try:
            preprocessing_job = get_latest_preprocessing_job(
                conn, SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER, row.external_revision_id
            )
            if preprocessing_job is None:
                show_error(self, "View OCR Result", "No preprocessing output found. Click Preprocess first.")
                return
            ocr_job = get_latest_ocr_job(conn, preprocessing_job.job_id)
        finally:
            conn.close()

        if ocr_job is None:
            show_error(self, "View OCR Result", "No OCR result found. Click Run OCR first.")
            return
        show_detail(self, "OCR Result", _build_ocr_result_message(ocr_job))

    # --- Handlers: Revision Attempts -----------------------------------------

    def handle_view_attempt_details(self, row: TeacherAttemptRow) -> None:
        message = (
            f"Student ID: {row.username}\n"
            f"Student Name: {row.student_name}\n"
            f"Class: {row.class_name}\n"
            f"Paper Type: {row.paper_type}\n"
            f"Attempt No: {row.attempt_no}\n"
            f"Status: {row.status}\n"
            f"Submitted: {format_timestamp(row.submitted_at)}\n\n"
            f"Completed Answer:\n{row.completed_answer_path}\n\n"
            "Teacher review, OCR, and AI marking will be implemented in a later stage."
        )
        show_detail(self, row.material_title, message)

    def handle_preprocess_attempt_answer(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            job = preprocess_document(
                conn, row.completed_answer_path, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, row.attempt_id
            )
        except ValueError as exc:
            show_error(self, "Preprocess Answer Failed", str(exc))
            return
        finally:
            conn.close()

        if job.status == STATUS_COMPLETED:
            message = (
                f"Status: {job.status}\n"
                f"Pages Processed: {job.page_count}\n\n"
                f"Output Folder:\n{job.output_folder_path}\n\n"
                "OCR and marking will be implemented in a later stage."
            )
            show_detail(self, "Preprocess Answer", message)
        else:
            show_error(
                self, "Preprocess Answer Failed", job.error_message or "Preprocessing failed for an unknown reason."
            )

    def handle_run_ocr_attempt_answer(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            preprocessing_job = get_latest_preprocessing_job(
                conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, row.attempt_id
            )
            if preprocessing_job is None or preprocessing_job.status != STATUS_COMPLETED:
                show_error(
                    self,
                    "Run OCR Failed",
                    "No completed preprocessing output found. Click Preprocess Answer first.",
                )
                return
            try:
                ocr_job = run_ocr_for_preprocessing_job(
                    conn, preprocessing_job.job_id, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, row.attempt_id
                )
            except ValueError as exc:
                show_error(self, "Run OCR Failed", str(exc))
                return
        finally:
            conn.close()

        if ocr_job.status == OCR_STATUS_COMPLETED:
            show_detail(self, "OCR Result", _build_ocr_result_message(ocr_job))
        else:
            show_error(self, "Run OCR Failed", ocr_job.error_message or "OCR failed for an unknown reason.")

    def handle_view_ocr_result_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            preprocessing_job = get_latest_preprocessing_job(
                conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, row.attempt_id
            )
            if preprocessing_job is None:
                show_error(self, "View OCR Result", "No preprocessing output found. Click Preprocess Answer first.")
                return
            ocr_job = get_latest_ocr_job(conn, preprocessing_job.job_id)
        finally:
            conn.close()

        if ocr_job is None:
            show_error(self, "View OCR Result", "No OCR result found. Click Run OCR first.")
            return
        show_detail(self, "OCR Result", _build_ocr_result_message(ocr_job))

    def handle_extract_regions_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            preprocessing_job = get_latest_preprocessing_job(
                conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, row.attempt_id
            )
            ocr_job = None
            if preprocessing_job is not None and preprocessing_job.status == STATUS_COMPLETED:
                ocr_job = get_latest_ocr_job(conn, preprocessing_job.job_id)
            if ocr_job is None or ocr_job.status != OCR_STATUS_COMPLETED:
                show_error(self, "Extract Regions Failed", "Run OCR before extracting regions.")
                return
            try:
                extraction_job = run_extraction_for_attempt(conn, row.attempt_id, ocr_job.ocr_job_id)
            except ValueError as exc:
                show_error(self, "Extract Regions Failed", str(exc))
                return
        finally:
            conn.close()

        if extraction_job.status == EXTRACTION_STATUS_COMPLETED:
            show_detail(self, "Extract Regions", _build_extraction_summary_message(extraction_job))
        else:
            show_error(
                self,
                "Extract Regions Failed",
                extraction_job.error_message or "Extraction failed for an unknown reason.",
            )

    def handle_view_extraction_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            extraction_job = get_latest_extraction_job(conn, row.attempt_id)
            if extraction_job is None:
                show_error(self, "View Extraction", "No extraction result found. Click Extract Regions first.")
                return
            results = (
                list_extracted_region_results(conn, extraction_job.extraction_job_id)
                if extraction_job.status == EXTRACTION_STATUS_COMPLETED
                else []
            )
            template = get_template_by_id(conn, extraction_job.template_id)
        finally:
            conn.close()

        template_title = template.title if template is not None else "Unknown"
        show_detail(
            self, "Extraction Result", _build_extraction_preview_message(extraction_job, template_title, results)
        )

    def handle_extract_answers_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            extraction_job = get_latest_extraction_job(conn, row.attempt_id)
            if extraction_job is None or extraction_job.status != EXTRACTION_STATUS_COMPLETED:
                show_error(self, "Extract Answers Failed", "Extract regions before extracting answers.")
                return
            try:
                answer_job = run_answer_extraction_for_attempt(
                    conn, row.attempt_id, extraction_job.extraction_job_id
                )
            except ValueError as exc:
                show_error(self, "Extract Answers Failed", str(exc))
                return
        finally:
            conn.close()

        if answer_job.status == ANSWER_EXTRACTION_STATUS_COMPLETED:
            show_detail(self, "Extract Answers", _build_answer_extraction_summary_message(answer_job))
        else:
            show_error(
                self,
                "Extract Answers Failed",
                answer_job.error_message or "Answer extraction failed for an unknown reason.",
            )

    def handle_view_answers_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            answer_job = get_latest_answer_extraction_job(conn, row.attempt_id)
            if answer_job is None:
                show_error(self, "View Answers", "No extracted answers found. Click Extract Answers first.")
                return
            answers = (
                list_extracted_attempt_answers(conn, answer_job.answer_extraction_job_id)
                if answer_job.status == ANSWER_EXTRACTION_STATUS_COMPLETED
                else []
            )
        finally:
            conn.close()

        show_detail(self, "Extracted Answers", _build_answer_extraction_preview_message(answer_job, answers))

    def handle_mark_kertas1_attempt(self, row: TeacherAttemptRow) -> None:
        if row.paper_type == PAPER_TYPE_KERTAS_2:
            show_error(self, "Mark Kertas 1 Failed", "Kertas 2 marking will be implemented in a later stage.")
            return

        conn = get_connection()
        try:
            answer_job = get_latest_answer_extraction_job(conn, row.attempt_id)
            if answer_job is None or answer_job.status != ANSWER_EXTRACTION_STATUS_COMPLETED:
                show_error(self, "Mark Kertas 1 Failed", "Extract answers before marking.")
                return
            try:
                marking_job = run_kertas1_marking_for_attempt(
                    conn, row.attempt_id, answer_job.answer_extraction_job_id
                )
            except ValueError as exc:
                show_error(self, "Mark Kertas 1 Failed", str(exc))
                return
        finally:
            conn.close()

        if marking_job.status == MARKING_STATUS_COMPLETED:
            show_detail(self, "Mark Kertas 1", _build_marking_summary_message(marking_job))
        else:
            show_error(
                self, "Mark Kertas 1 Failed", marking_job.error_message or "Marking failed for an unknown reason."
            )

    def handle_view_marking_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            marking_job = get_latest_marking_job(conn, row.attempt_id)
            if marking_job is None:
                show_error(self, "View Marking", "No marking result found. Click Mark Kertas 1 first.")
                return
            results = (
                list_marking_question_results(conn, marking_job.marking_job_id)
                if marking_job.status == MARKING_STATUS_COMPLETED
                else []
            )
        finally:
            conn.close()

        show_detail(self, "Marking Result", _build_marking_preview_message(marking_job, results))

    def handle_open_marking_review(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            marking_job = get_latest_marking_job(conn, row.attempt_id)
            if marking_job is None or marking_job.status != MARKING_STATUS_COMPLETED:
                show_error(self, "Review Marking Failed", "Mark Kertas 1 before starting a review.")
                return
            try:
                review = start_or_get_review(conn, marking_job.marking_job_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Review Marking Failed", str(exc))
                return
            results_by_id = {
                result.marking_result_id: result
                for result in list_marking_question_results(conn, marking_job.marking_job_id)
            }
        finally:
            conn.close()

        self._current_review = review
        self._current_review_attempt_row = row
        self._current_review_results_by_id = results_by_id
        self.marking_review_title_label.setText(f"Marking Review - {row.material_title} (Attempt {row.attempt_no})")
        self.marking_review_subtitle_label.setText(f"Student: {row.student_name} ({row.username})")
        self.refresh_marking_review_page()
        self.shell.show_page("Marking Review")

    def handle_edit_review_item(self, item: MarkingReviewItem) -> None:
        if self._current_review is not None and self._current_review.status == REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has been finalized and can no longer be edited.")
            return

        result = self._current_review_results_by_id.get(item.marking_result_id)
        context = (
            f"Correct Answer: {result.correct_answer if result else '-'}\n"
            f"Extracted Answer: {(result.extracted_answer or '(none)') if result else '-'}\n"
            f"Auto Reason: {result.reason if result else '-'}\n"
            f"Explanation: {result.explanation if result else '-'}"
        )
        initial = {
            "final_score_awarded": item.final_score_awarded,
            "final_is_correct": bool(item.final_is_correct),
            "teacher_comment": item.teacher_comment,
            "override_reason": item.override_reason,
            "max_mark": item.max_mark,
        }
        values = prompt_review_item(self, f"Review Question {item.question_no}", context, initial)
        if values is None:
            return

        try:
            final_score_awarded = float(values["final_score_awarded"])
        except ValueError:
            show_error(self, "Save Review Item Failed", "Final score must be a number.")
            return

        conn = get_connection()
        try:
            try:
                update_review_item(
                    conn,
                    item.marking_review_item_id,
                    self._teacher_id,
                    final_score_awarded,
                    bool(values["final_is_correct"]),
                    values["teacher_comment"] or None,
                    values["override_reason"] or None,
                )
            except ValueError as exc:
                show_error(self, "Save Review Item Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_marking_review_page()
        show_success(self, "Save Review Item", "Review item saved.")

    def handle_save_review_draft_comment(self) -> None:
        if self._current_review is None:
            return
        if self._current_review.status == REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has been finalized and can no longer be edited.")
            return

        comment = prompt_input(
            self,
            "Save Draft",
            "Overall comment for this attempt (optional):",
            placeholder="e.g. Good effort overall",
        )
        if comment is None:
            return

        conn = get_connection()
        try:
            try:
                save_review_comment(conn, self._current_review.review_id, self._teacher_id, comment or None)
            except ValueError as exc:
                show_error(self, "Save Draft Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_marking_review_page()
        show_success(self, "Save Draft", "Draft saved.")

    def handle_finalize_review(self) -> None:
        if self._current_review is None:
            return
        if self._current_review.status == REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has already been finalized.")
            return

        if not prompt_confirm(
            self,
            "Finalize Review",
            "Finalize this review? Once finalized, it can no longer be edited.",
            confirm_text="Finalize",
        ):
            return

        conn = get_connection()
        try:
            try:
                review = finalize_review(conn, self._current_review.review_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Finalize Review Failed", str(exc))
                return
        finally:
            conn.close()

        self._current_review = review
        self.refresh_marking_review_page()
        show_success(
            self, "Finalize Review", f"Review finalized. Final score: {review.final_total_score} / {review.max_score}"
        )

    def handle_back_from_marking_review(self) -> None:
        self._current_review = None
        self._current_review_attempt_row = None
        self._current_review_results_by_id = {}
        self.shell.show_page("Attempts / Workflow")

    def handle_view_review_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            review = get_latest_review(conn, row.attempt_id)
            if review is None:
                show_error(self, "View Review", "No review found. Click Review Marking first.")
                return
            items = list_review_items(conn, review.review_id)
            marking_job = get_latest_marking_job(conn, row.attempt_id)
            results_by_id = (
                {
                    result.marking_result_id: result
                    for result in list_marking_question_results(conn, marking_job.marking_job_id)
                }
                if marking_job is not None
                else {}
            )
        finally:
            conn.close()

        lines = [
            f"Status: {review.status}",
            f"Auto Total: {review.auto_total_score} / {review.max_score}",
            f"Final Total: {review.final_total_score} / {review.max_score}",
            f"Overall Comment: {review.teacher_overall_comment or '-'}",
            "",
        ]
        for item in items:
            result = results_by_id.get(item.marking_result_id)
            lines.append(
                f"Question {item.question_no}: {item.review_status} - "
                f"{'Correct' if item.final_is_correct else 'Wrong'} ({item.final_score_awarded}/{item.max_mark})\n"
                f"  Correct Answer: {result.correct_answer if result else '-'}\n"
                f"  Teacher Comment: {item.teacher_comment or '-'}\n"
            )
        lines.append("Use Export Summary / Detail CSV on the Results page to export this result.")
        show_detail(self, "Marking Review", "\n".join(lines))

    def handle_generate_kertas2_feedback_attempt(self, row: TeacherAttemptRow) -> None:
        if row.paper_type == PAPER_TYPE_KERTAS_1:
            show_error(self, "Generate Kertas 2 Feedback Failed", "Kertas 1 uses rule-based marking.")
            return

        conn = get_connection()
        try:
            answer_job = get_latest_answer_extraction_job(conn, row.attempt_id)
            if answer_job is None or answer_job.status != ANSWER_EXTRACTION_STATUS_COMPLETED:
                show_error(
                    self,
                    "Generate Kertas 2 Feedback Failed",
                    "Extract answers before generating Kertas 2 feedback.",
                )
                return
            try:
                feedback_job = run_kertas2_ai_feedback_for_attempt(
                    conn, row.attempt_id, answer_job.answer_extraction_job_id
                )
            except ValueError as exc:
                show_error(self, "Generate Kertas 2 Feedback Failed", str(exc))
                return
        finally:
            conn.close()

        if feedback_job.status == KERTAS2_FEEDBACK_STATUS_COMPLETED:
            show_detail(self, "Generate Kertas 2 Feedback", _build_kertas2_feedback_summary_message(feedback_job))
        else:
            show_error(
                self,
                "Generate Kertas 2 Feedback Failed",
                feedback_job.error_message or "Feedback generation failed for an unknown reason.",
            )

    def handle_view_kertas2_feedback_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            feedback_job = get_latest_feedback_job(conn, row.attempt_id)
            if feedback_job is None:
                show_error(
                    self, "View Kertas 2 Feedback", "No feedback draft found. Click Generate Kertas 2 Feedback first."
                )
                return
            items = (
                list_feedback_items(conn, feedback_job.feedback_job_id)
                if feedback_job.status == KERTAS2_FEEDBACK_STATUS_COMPLETED
                else []
            )
        finally:
            conn.close()

        show_detail(
            self, "Kertas 2 Feedback Draft", _build_kertas2_feedback_preview_message(feedback_job, items)
        )

    def handle_view_kertas2_feedback_audit_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            feedback_job = get_latest_feedback_job(conn, row.attempt_id)
            if feedback_job is None:
                show_error(
                    self, "View Kertas 2 Feedback Audit",
                    "No feedback draft found. Click Generate Kertas 2 Feedback first.",
                )
                return
            try:
                feedback_job, items = get_feedback_job_audit_for_teacher(
                    conn, feedback_job.feedback_job_id, self._teacher_id
                )
            except ValueError as exc:
                show_error(self, "View Kertas 2 Feedback Audit", str(exc))
                return
        finally:
            conn.close()

        show_detail(
            self, "Kertas 2 Feedback Audit", _build_kertas2_feedback_audit_message(feedback_job, items)
        )

    def handle_view_workflow_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            try:
                status = get_attempt_workflow_status(conn, row.attempt_id, self._teacher_id)
                readiness = get_attempt_readiness_report(conn, row.attempt_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "View Workflow Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Attempt Workflow", _build_workflow_status_message(status, readiness))

    def handle_view_readiness_issues_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            try:
                readiness = get_attempt_readiness_report(conn, row.attempt_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "View Issues Failed", str(exc))
                return
        finally:
            conn.close()

        show_detail(self, "Readiness Issue Flags", _build_readiness_issues_message(readiness))

    def handle_open_kertas2_review(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            feedback_job = get_latest_feedback_job(conn, row.attempt_id)
            if feedback_job is None or feedback_job.status != KERTAS2_FEEDBACK_STATUS_COMPLETED:
                show_error(
                    self, "Review Kertas 2 Failed", "Generate Kertas 2 feedback before starting a review."
                )
                return
            try:
                review = start_or_get_kertas2_review(conn, feedback_job.feedback_job_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Review Kertas 2 Failed", str(exc))
                return
        finally:
            conn.close()

        self._current_kertas2_review = review
        self._current_kertas2_review_attempt_row = row
        self.kertas2_review_title_label.setText(f"Kertas 2 Review - {row.material_title} (Attempt {row.attempt_no})")
        self.kertas2_review_subtitle_label.setText(f"Student: {row.student_name} ({row.username})")
        self.refresh_kertas2_review_page()
        self.shell.show_page("Kertas 2 Review")

    def handle_edit_kertas2_review_item(self, item: Kertas2FeedbackReviewItem) -> None:
        if self._current_kertas2_review is not None and self._current_kertas2_review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has been finalized and can no longer be edited.")
            return

        context = (
            f"Student Answer: {item.student_answer or '(none)'}\n"
            f"Sample Answer: {item.sample_answer or '-'}\n"
            f"AI Suggested Feedback: {item.suggested_feedback or '-'}\n"
            f"AI Reason: {item.ai_reason or '-'}"
        )
        initial = {
            "final_score": item.final_score,
            "final_feedback": item.final_feedback,
            "teacher_comment": item.teacher_comment,
            "max_mark": item.max_mark,
        }
        values = prompt_kertas2_review_item(self, f"Review Criterion: {item.criterion_name}", context, initial)
        if values is None:
            return

        try:
            final_score = float(values["final_score"])
        except ValueError:
            show_error(self, "Save Review Item Failed", "Final score must be a number.")
            return

        conn = get_connection()
        try:
            try:
                update_kertas2_review_item(
                    conn,
                    item.kertas2_review_item_id,
                    self._teacher_id,
                    final_score,
                    values["final_feedback"] or None,
                    values["teacher_comment"] or None,
                )
            except ValueError as exc:
                show_error(self, "Save Review Item Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_kertas2_review_page()
        show_success(self, "Save Review Item", "Review item saved.")

    def handle_save_kertas2_review_draft_comment(self) -> None:
        if self._current_kertas2_review is None:
            return
        if self._current_kertas2_review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has been finalized and can no longer be edited.")
            return

        comment = prompt_input(
            self,
            "Save Draft",
            "Overall comment for this attempt (optional):",
            placeholder="e.g. Strong essay overall",
        )
        if comment is None:
            return

        conn = get_connection()
        try:
            try:
                save_kertas2_review_comment(
                    conn, self._current_kertas2_review.kertas2_review_id, self._teacher_id, comment or None
                )
            except ValueError as exc:
                show_error(self, "Save Draft Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_kertas2_review_page()
        show_success(self, "Save Draft", "Draft saved.")

    def handle_finalize_kertas2_review(self) -> None:
        if self._current_kertas2_review is None:
            return
        if self._current_kertas2_review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            show_error(self, "Review Finalized", "This review has already been finalized.")
            return

        if not prompt_confirm(
            self,
            "Finalize Review",
            "Finalize this Kertas 2 review? Once finalized, it can no longer be edited.",
            confirm_text="Finalize",
        ):
            return

        conn = get_connection()
        try:
            try:
                review = finalize_kertas2_review(conn, self._current_kertas2_review.kertas2_review_id, self._teacher_id)
            except ValueError as exc:
                show_error(self, "Finalize Review Failed", str(exc))
                return
        finally:
            conn.close()

        self._current_kertas2_review = review
        self.refresh_kertas2_review_page()
        show_success(
            self,
            "Finalize Review",
            f"Review finalized. Final score: {review.final_total_score} / {review.max_score}",
        )

    def handle_back_from_kertas2_review(self) -> None:
        self._current_kertas2_review = None
        self._current_kertas2_review_attempt_row = None
        self.shell.show_page("Attempts / Workflow")

    def handle_view_kertas2_review_attempt(self, row: TeacherAttemptRow) -> None:
        conn = get_connection()
        try:
            review = get_latest_kertas2_review(conn, row.attempt_id)
            if review is None:
                show_error(self, "View Kertas 2 Review", "No review found. Click Review Kertas 2 first.")
                return
            items = list_kertas2_review_items(conn, review.kertas2_review_id)
        finally:
            conn.close()

        lines = [
            f"Status: {review.status}",
            f"Suggested Total: {review.suggested_total_score} / {review.max_score}",
            f"Final Total: {review.final_total_score} / {review.max_score}",
            f"Overall Comment: {review.teacher_overall_comment or '-'}",
            "",
        ]
        for item in items:
            lines.append(
                f"{item.criterion_name} - {item.review_status} ({item.final_score}/{item.max_mark})\n"
                f"  Final Feedback: {item.final_feedback or '-'}\n"
                f"  Teacher Comment: {item.teacher_comment or '-'}\n"
            )
        lines.append("Use Export Summary / Detail CSV on the Results page to export this result.")
        show_detail(self, "Kertas 2 Review", "\n".join(lines))

    # --- Handlers: Templates -------------------------------------------------

    def handle_open_create_template_page(self) -> None:
        self.new_template_title_input.clear()
        self.new_template_paper_type_dropdown.setCurrentIndex(0)
        self._new_template_sample_path = ""
        self.template_sample_status_label.setText("No file selected")
        self.shell.show_page("Create Template")

    def handle_choose_template_sample_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Sample / Blank Paper", "", "PDF and Images (*.pdf *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self._new_template_sample_path = path
        self.template_sample_status_label.setText(Path(path).name)

    def handle_create_template(self) -> None:
        title = self.new_template_title_input.text()
        paper_type = self.new_template_paper_type_dropdown.currentData()

        if paper_type is None:
            show_error(self, "Create Template Failed", "Please select a paper type.")
            return

        conn = get_connection()
        try:
            template = create_template(
                conn,
                self._teacher_id,
                title,
                paper_type,
                self._new_template_sample_path,
            )
        except ValueError as exc:
            show_error(self, "Create Template Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_templates_table()
        show_success(self, "Create Template", "Template created. Now define its answer regions.")
        self._open_template_editor(template.template_id, template.title, template.paper_type, template.sample_file_path)

    def handle_cancel_create_template(self) -> None:
        self.shell.show_page("Templates")

    def handle_open_template_editor(self, row: TeacherTemplateRow) -> None:
        self._open_template_editor(row.template_id, row.title, row.paper_type, row.sample_file_path)

    def _open_template_editor(self, template_id: int, title: str, paper_type: str, sample_file_path: str) -> None:
        self._current_template = AnswerTemplate(
            template_id=template_id,
            teacher_id=self._teacher_id,
            title=title,
            paper_type=paper_type,
            sample_file_path=sample_file_path,
            created_at="",
        )
        self.template_editor_title_label.setText(f"Template Editor - {title} ({paper_type})")
        self.template_editor_status_label.setText("")
        self._current_template_page = 1
        self._current_template_page_count = max(1, get_page_count(sample_file_path))
        self._clear_redefine_state()
        self._set_canvas_mode(TemplateCanvas.MODE_RECTANGLE)

        if not self._load_current_template_page():
            self.shell.show_page("Templates")
            return

        self.shell.show_page("Template Editor")

    def _load_current_template_page(self) -> bool:
        """Render/display self._current_template_page for the current
        template, refresh the page-nav label/buttons, and refresh the
        Defined Regions list (whose canvas overlay is filtered to only the
        current page - see refresh_template_regions). Returns False (and
        shows an error) if the page image could not be rendered."""
        if self._current_template is None:
            return False

        image = render_page_image(self._current_template.sample_file_path, page_index=self._current_template_page - 1)
        if image.isNull():
            show_error(
                self,
                "Template Editor Failed",
                "The sample paper file could not be rendered. It may be missing or in an unsupported format.",
            )
            return False

        self.template_canvas.load_image(image)
        self.template_page_label.setText(f"Page {self._current_template_page} of {self._current_template_page_count}")
        self.template_prev_page_button.setEnabled(self._current_template_page > 1)
        self.template_next_page_button.setEnabled(self._current_template_page < self._current_template_page_count)
        self.refresh_template_regions()
        return True

    def handle_template_prev_page(self) -> None:
        if self._current_template is None or self._current_template_page <= 1:
            return
        self._current_template_page -= 1
        self._load_current_template_page()

    def handle_template_next_page(self) -> None:
        if self._current_template is None or self._current_template_page >= self._current_template_page_count:
            return
        self._current_template_page += 1
        self._load_current_template_page()

    def _set_canvas_mode(self, mode: str) -> None:
        """Switch the canvas between rectangle- and polygon-drawing mode,
        and keep the mode toggle/Finish/Cancel Polygon buttons in sync."""
        self.template_canvas.set_mode(mode)
        is_polygon = mode == TemplateCanvas.MODE_POLYGON
        self.template_draw_rectangle_button.setChecked(not is_polygon)
        self.template_draw_polygon_button.setChecked(is_polygon)
        self.template_finish_polygon_button.setVisible(is_polygon)
        self.template_cancel_polygon_button.setVisible(is_polygon)

    def handle_set_rectangle_mode(self) -> None:
        self._set_canvas_mode(TemplateCanvas.MODE_RECTANGLE)

    def handle_set_polygon_mode(self) -> None:
        self._set_canvas_mode(TemplateCanvas.MODE_POLYGON)

    def handle_finish_polygon(self) -> None:
        if not self.template_canvas.finish_polygon():
            show_error(
                self,
                "Finish Polygon Failed",
                f"A polygon region needs at least {TemplateCanvas.MIN_POLYGON_POINTS} points. "
                "Keep clicking to add more points, then try Finish Polygon again.",
            )

    def handle_cancel_polygon(self) -> None:
        self.template_canvas.cancel_polygon()
        self.template_editor_status_label.setText("Polygon drawing cancelled.")

    def handle_template_editor_done(self) -> None:
        if self._current_template is None:
            return
        confirmed = prompt_confirm(
            self,
            "Done Editing",
            "Save changes before finishing?",
            confirm_text="Save",
        )
        if not confirmed:
            return
        self.refresh_template_regions()
        self.template_editor_status_label.setText("Saved. Template regions are up to date.")
        show_success(self, "Template Editor", "Template regions saved.")

    def handle_template_region_drawn(self, x: float, y: float, width: float, height: float) -> None:
        if self._current_template is None:
            return

        if self._redefine_region_id is not None:
            self._finish_redefine_region(x, y, width, height)
            return

        label = prompt_input(
            self,
            "New Region",
            "Enter a name for this region (e.g. Q1).",
        )
        if label is None:
            self.refresh_template_regions()
            return

        allowed_types = get_allowed_region_types(self._current_template.paper_type)
        region_type = prompt_select(
            self,
            "New Region",
            "Select a region type.",
            [(rt, rt) for rt in allowed_types],
        )
        if region_type is CANCELLED:
            self.refresh_template_regions()
            return

        conn = get_connection()
        try:
            add_template_region(
                conn,
                self._teacher_id,
                self._current_template.template_id,
                label,
                region_type,
                x,
                y,
                width,
                height,
                page_number=self._current_template_page,
            )
        except ValueError as exc:
            show_error(self, "Add Region Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        self.refresh_templates_table()

    def handle_template_polygon_region_drawn(self, points: list) -> None:
        if self._current_template is None:
            return

        if self._redefine_region_id is not None:
            self._finish_redefine_polygon_region(points)
            return

        label = prompt_input(
            self,
            "New Polygon Region",
            "Enter a name for this region (e.g. Q3_irregular).",
        )
        if label is None:
            self.refresh_template_regions()
            return

        allowed_types = get_allowed_region_types(self._current_template.paper_type)
        region_type = prompt_select(
            self,
            "New Polygon Region",
            "Select a region type.",
            [(rt, rt) for rt in allowed_types],
        )
        if region_type is CANCELLED:
            self.refresh_template_regions()
            return

        conn = get_connection()
        try:
            add_polygon_template_region(
                conn,
                self._teacher_id,
                self._current_template.template_id,
                label,
                region_type,
                points,
                page_number=self._current_template_page,
            )
        except ValueError as exc:
            show_error(self, "Add Region Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        self.refresh_templates_table()

    def handle_edit_template_region(self, region: TemplateRegion) -> None:
        if self._current_template is None:
            return

        allowed_types = get_allowed_region_types(self._current_template.paper_type)
        initial = {
            "label": region.label,
            "region_type": region.region_type,
            "page_number": region.page_number,
            "order_index": region.order_index,
            "rotation_angle": region.rotation_angle,
            "notes": region.notes,
        }
        values = prompt_edit_region(
            self,
            f"Edit Region - {region.label}",
            [(rt, rt) for rt in allowed_types],
            initial,
        )
        if values is None:
            return

        try:
            order_index = int(values["order_index"])
        except (TypeError, ValueError):
            show_error(self, "Edit Region Failed", "Region order must be a whole number.")
            return

        try:
            rotation_angle = float(values.get("rotation_angle", 0.0))
        except (TypeError, ValueError):
            show_error(self, "Edit Region Failed", "Rotation angle must be a number.")
            return

        if values["action"] == "redefine":
            self._begin_redefine_region(
                region, values["label"], values["region_type"], order_index, values["notes"], rotation_angle
            )
            return

        # action == "save": name/type/order/rotation/notes only -
        # coordinates/points and page number are unchanged (use Redefine
        # Region to change those). Dispatch on the region's own existing
        # shape so a polygon region's points are preserved rather than
        # being overwritten with its rectangle-style bounding box.
        conn = get_connection()
        try:
            if region.shape_type == SHAPE_TYPE_POLYGON:
                update_polygon_template_region(
                    conn,
                    self._teacher_id,
                    region.region_id,
                    values["label"],
                    values["region_type"],
                    region.page_number,
                    parse_polygon_points(region.polygon_points_json),
                    order_index,
                    values["notes"],
                    rotation_angle,
                )
            else:
                update_template_region(
                    conn,
                    self._teacher_id,
                    region.region_id,
                    values["label"],
                    values["region_type"],
                    region.page_number,
                    region.x,
                    region.y,
                    region.width,
                    region.height,
                    order_index,
                    values["notes"],
                    rotation_angle,
                )
        except ValueError as exc:
            show_error(self, "Edit Region Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        show_success(self, "Edit Region", "Region updated successfully.")

    def _begin_redefine_region(
        self,
        region: TemplateRegion,
        label: str,
        region_type: str,
        order_index: int,
        notes: str,
        rotation_angle: float = 0.0,
    ) -> None:
        """Enter redefine mode: the next shape drawn on the preview (on
        whichever page is currently selected) replaces region's
        coordinates/points and page number, keeping the label/type/order/
        rotation/notes the teacher confirmed in the Edit dialog (Stage 11J:
        rotation_angle is whatever the teacher left in the dialog's
        Rotation Angle field - unchanged from the region's own current
        value unless they edited it before clicking Redefine Region). The
        canvas is switched to match region's own shape (rectangle or
        polygon) so the correct drawing gesture is expected."""
        self._redefine_region_id = region.region_id
        self._redefine_pending_label = label
        self._redefine_pending_region_type = region_type
        self._redefine_pending_order_index = order_index
        self._redefine_pending_notes = notes
        self._redefine_pending_rotation_angle = rotation_angle
        self._redefine_shape_type = region.shape_type
        self.template_cancel_redefine_button.setVisible(True)

        if region.shape_type == SHAPE_TYPE_POLYGON:
            self._set_canvas_mode(TemplateCanvas.MODE_POLYGON)
            message = (
                f"Redefining region {region.label}. Click at least "
                f"{TemplateCanvas.MIN_POLYGON_POINTS} points to draw a new polygon, then Finish Polygon."
            )
        else:
            self._set_canvas_mode(TemplateCanvas.MODE_RECTANGLE)
            message = f"Redefining region {region.label}. Draw a new rectangle on the preview."
        self.template_editor_status_label.setText(message)

    def handle_cancel_redefine_region(self) -> None:
        if self._redefine_region_id is None:
            return
        self._clear_redefine_state()
        self.template_editor_status_label.setText("Redefine cancelled.")

    def _clear_redefine_state(self) -> None:
        self._redefine_region_id = None
        self._redefine_pending_label = None
        self._redefine_pending_region_type = None
        self._redefine_pending_order_index = None
        self._redefine_pending_notes = None
        self._redefine_pending_rotation_angle = None
        self._redefine_shape_type = None
        self.template_cancel_redefine_button.setVisible(False)
        self._set_canvas_mode(TemplateCanvas.MODE_RECTANGLE)

    def _finish_redefine_region(self, x: float, y: float, width: float, height: float) -> None:
        region_id = self._redefine_region_id
        label = self._redefine_pending_label
        region_type = self._redefine_pending_region_type
        order_index = self._redefine_pending_order_index
        notes = self._redefine_pending_notes
        rotation_angle = self._redefine_pending_rotation_angle

        conn = get_connection()
        try:
            update_template_region(
                conn,
                self._teacher_id,
                region_id,
                label,
                region_type,
                self._current_template_page,
                x,
                y,
                width,
                height,
                order_index,
                notes,
                rotation_angle,
            )
        except ValueError as exc:
            show_error(self, "Redefine Region Failed", str(exc))
        finally:
            conn.close()
            self._clear_redefine_state()

        self.refresh_template_regions()
        self.template_editor_status_label.setText("Region redefined successfully.")

    def _finish_redefine_polygon_region(self, points: list) -> None:
        region_id = self._redefine_region_id
        label = self._redefine_pending_label
        region_type = self._redefine_pending_region_type
        order_index = self._redefine_pending_order_index
        notes = self._redefine_pending_notes
        rotation_angle = self._redefine_pending_rotation_angle

        conn = get_connection()
        try:
            update_polygon_template_region(
                conn,
                self._teacher_id,
                region_id,
                label,
                region_type,
                self._current_template_page,
                points,
                order_index,
                notes,
                rotation_angle,
            )
        except ValueError as exc:
            show_error(self, "Redefine Region Failed", str(exc))
        finally:
            conn.close()
            self._clear_redefine_state()

        self.refresh_template_regions()
        self.template_editor_status_label.setText("Region redefined successfully.")

    def handle_remove_template_region(self, region: TemplateRegion) -> None:
        confirmed = prompt_confirm(
            self,
            "Remove Region",
            f"Remove region '{region.label}'?",
            confirm_text="Remove",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            remove_template_region(conn, self._teacher_id, region.region_id)
        except ValueError as exc:
            show_error(self, "Remove Region Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        self.refresh_templates_table()

    def handle_create_region_group(self) -> None:
        if self._current_template is None:
            return

        selected_region_ids = [
            region_id for region_id, checkbox in self._template_region_checkboxes.items() if checkbox.isChecked()
        ]
        if len(selected_region_ids) < MIN_GROUP_MEMBERS:
            show_error(
                self,
                "Create Group Failed",
                f"Select at least {MIN_GROUP_MEMBERS} regions (checkboxes in the Defined Regions list) to combine into a group.",
            )
            return

        conn = get_connection()
        try:
            all_regions = list_template_regions(conn, self._teacher_id, self._current_template.template_id)
        except ValueError as exc:
            show_error(self, "Create Group Failed", str(exc))
            return
        finally:
            conn.close()

        selected_regions = [region for region in all_regions if region.region_id in selected_region_ids]
        selected_regions.sort(key=lambda r: (r.page_number, r.order_index, r.region_id))
        preview = ", ".join(f"{r.label} (P{r.page_number})" for r in selected_regions)

        # A group is itself a logical answer/question/student-id component,
        # so it cannot be typed as ignore_region even though that type is
        # valid for individual regions (Stage 11I).
        allowed_types = [rt for rt in get_allowed_region_types(self._current_template.paper_type) if rt != REGION_TYPE_IGNORE]
        values = prompt_region_group_form(
            self,
            "Create Region Group",
            f"Combining {len(selected_regions)} regions: {preview}",
            [(rt, rt) for rt in allowed_types],
        )
        if values is None:
            return

        conn = get_connection()
        try:
            create_region_group(
                conn,
                self._teacher_id,
                self._current_template.template_id,
                values["label"],
                values["region_type"],
                selected_region_ids,
                values["notes"],
            )
        except ValueError as exc:
            show_error(self, "Create Group Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        show_success(self, "Create Region Group", "Region group created successfully.")

    def handle_edit_region_group(self, group: TemplateRegionGroup) -> None:
        if self._current_template is None:
            return

        allowed_types = [rt for rt in get_allowed_region_types(self._current_template.paper_type) if rt != REGION_TYPE_IGNORE]
        initial = {"label": group.label, "region_type": group.region_type, "notes": group.notes}
        values = prompt_region_group_form(
            self,
            f"Edit Group - {group.label}",
            "Update this group's name, type, or notes. Membership and order are unchanged here.",
            [(rt, rt) for rt in allowed_types],
            initial,
        )
        if values is None:
            return

        conn = get_connection()
        try:
            update_region_group(
                conn, self._teacher_id, group.group_id, values["label"], values["region_type"], values["notes"]
            )
        except ValueError as exc:
            show_error(self, "Edit Group Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()
        show_success(self, "Edit Group", "Region group updated successfully.")

    def handle_manage_group_order(self, group: TemplateRegionGroup) -> None:
        dialog = GroupMemberOrderDialog(self, self._teacher_id, group.group_id)
        dialog.exec()
        self.refresh_template_regions()

    def handle_delete_region_group(self, group: TemplateRegionGroup) -> None:
        confirmed = prompt_confirm(
            self,
            "Delete Region Group",
            f"Delete group '{group.label}'? Its member regions will NOT be deleted.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            delete_region_group(conn, self._teacher_id, group.group_id)
        except ValueError as exc:
            show_error(self, "Delete Group Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_template_regions()

    def handle_back_to_templates(self) -> None:
        self._current_template = None
        self._current_template_page = 1
        self._current_template_page_count = 1
        self._clear_redefine_state()
        self.shell.show_page("Templates")

    # --- Handlers: Marking Setup ---------------------------------------------

    def handle_open_marking_setup(self, row: TeacherMaterialRow) -> None:
        if row.paper_type == PAPER_TYPE_BOTH:
            show_info(
                self,
                "Both is Label-Only",
                "Both is a revision material label only in this prototype. Kertas 1 and Kertas 2 "
                "marking setup remain separate, so there is no combined Setup for a Both material. "
                "Create a separate Kertas 1 or Kertas 2 material to use Marking Setup.",
            )
            return

        self._current_marking_material = row
        self.marking_setup_title_label.setText(f"Marking Setup - {row.title}")
        self.marking_setup_subtitle_label.setText(f"Paper Type: {row.paper_type}")
        self.marking_setup_classes_label.setText(row.class_names or "None")

        conn = get_connection()
        try:
            setup = get_marking_setup_for_material(conn, self._teacher_id, row.material_id)
        except ValueError as exc:
            show_error(self, "Marking Setup Failed", str(exc))
            return
        finally:
            conn.close()

        self._current_marking_setup = setup
        self.refresh_marking_setup_template_dropdown()

        if setup is not None:
            template_index = self.marking_setup_template_dropdown.findData(setup.template_id)
            self.marking_setup_template_dropdown.setCurrentIndex(template_index if template_index >= 0 else 0)
            self.marking_setup_spelling_deduction_input.setText(str(setup.spelling_deduction))
            self.marking_setup_default_mark_input.setText(str(setup.default_question_mark))
        else:
            self.marking_setup_template_dropdown.setCurrentIndex(0)
            self.marking_setup_spelling_deduction_input.setText(str(DEFAULT_SPELLING_DEDUCTION))
            self.marking_setup_default_mark_input.setText(str(DEFAULT_QUESTION_MARK))

        is_kertas1 = row.paper_type == PAPER_TYPE_KERTAS_1
        self.marking_questions_heading_label.setText("Answer Key" if is_kertas1 else "Rubric Placeholder")
        self.add_default_criteria_button.setVisible(not is_kertas1)
        self.add_question_button.setText("+ Add Question" if is_kertas1 else "+ Add Criterion")

        self.refresh_marking_questions_table()
        self.shell.show_page("Material Marking Setup")

    def handle_save_marking_setup(self) -> None:
        if self._current_marking_material is None:
            return

        template_id = self.marking_setup_template_dropdown.currentData()

        try:
            spelling_deduction = float(self.marking_setup_spelling_deduction_input.text())
            default_question_mark = float(self.marking_setup_default_mark_input.text())
        except ValueError:
            show_error(
                self, "Save Setup Failed", "Spelling deduction and default question mark must be numbers."
            )
            return

        conn = get_connection()
        try:
            setup = save_marking_setup(
                conn,
                self._teacher_id,
                self._current_marking_material.material_id,
                template_id,
                spelling_deduction,
                default_question_mark,
            )
        except ValueError as exc:
            show_error(self, "Save Setup Failed", str(exc))
            return
        finally:
            conn.close()

        self._current_marking_setup = setup
        self.refresh_marking_questions_table()
        show_success(self, "Save Setup", "Marking setup saved successfully.")

    def handle_back_from_marking_setup(self) -> None:
        self._current_marking_material = None
        self._current_marking_setup = None
        self.shell.show_page("Revision Materials")

    def _marking_question_type_options(self) -> list:
        paper_type = self._current_marking_setup.paper_type
        types = KERTAS_1_QUESTION_TYPES if paper_type == PAPER_TYPE_KERTAS_1 else KERTAS_2_QUESTION_TYPES
        return [(qt, qt) for qt in types]

    def _marking_region_options(self) -> list:
        # Ignore regions are exclusion masks, not selectable answer/question/
        # student-id components - excluded from Marking Setup's normal
        # region choices (Stage 11I).
        if self._current_marking_setup.template_id is None:
            return []
        conn = get_connection()
        try:
            regions = get_non_ignore_regions_for_template(
                conn, self._teacher_id, self._current_marking_setup.template_id
            )
        finally:
            conn.close()
        return [(r.label, r.region_id) for r in regions]

    def handle_open_add_question_dialog(self) -> None:
        if self._current_marking_setup is None:
            show_error(self, "Add Question Failed", "Please save the marking setup before adding questions.")
            return

        is_kertas1 = self._current_marking_setup.paper_type == PAPER_TYPE_KERTAS_1
        dialog_title = "Add Question" if is_kertas1 else "Add Criterion"

        next_order = self.marking_questions_table.rowCount() + 1
        values = prompt_marking_question(
            self,
            dialog_title,
            self._marking_question_type_options(),
            self._marking_region_options(),
            {"display_order": next_order},
        )
        if values is None:
            return

        try:
            max_mark = float(values["max_mark"])
        except (TypeError, ValueError):
            show_error(self, f"{dialog_title} Failed", "Max mark must be a number.")
            return

        display_order = None
        if str(values["display_order"]).strip():
            try:
                display_order = int(values["display_order"])
            except ValueError:
                show_error(self, f"{dialog_title} Failed", "Display order must be a whole number.")
                return

        conn = get_connection()
        try:
            add_marking_question(
                conn,
                self._teacher_id,
                self._current_marking_setup.setup_id,
                values["question_no"],
                values["correct_answer"],
                max_mark,
                values["question_type"],
                values["explanation"],
                values["region_id"],
                display_order,
            )
        except ValueError as exc:
            show_error(self, f"{dialog_title} Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_questions_table()
        item_noun = "Question" if is_kertas1 else "Criterion"
        show_success(self, dialog_title, f"{item_noun} added successfully.")

    def handle_edit_marking_question(self, row: MarkingQuestionRow) -> None:
        is_kertas1 = self._current_marking_setup is not None and self._current_marking_setup.paper_type == PAPER_TYPE_KERTAS_1
        item_noun = "Question" if is_kertas1 else "Criterion"
        dialog_title = f"Edit {item_noun} - {row.question_no}"

        initial = {
            "question_no": row.question_no,
            "correct_answer": row.correct_answer,
            "max_mark": row.max_mark,
            "question_type": row.question_type,
            "explanation": row.explanation,
            "region_id": row.region_id,
            "display_order": row.display_order,
        }
        values = prompt_marking_question(
            self,
            dialog_title,
            self._marking_question_type_options(),
            self._marking_region_options(),
            initial,
        )
        if values is None:
            return

        try:
            max_mark = float(values["max_mark"])
            display_order = int(values["display_order"])
        except (TypeError, ValueError):
            show_error(
                self, f"Edit {item_noun} Failed", "Max mark must be a number and display order a whole number."
            )
            return

        conn = get_connection()
        try:
            update_marking_question(
                conn,
                self._teacher_id,
                row.question_id,
                values["question_no"],
                values["correct_answer"],
                max_mark,
                values["question_type"],
                values["explanation"],
                values["region_id"],
                display_order,
            )
        except ValueError as exc:
            show_error(self, f"Edit {item_noun} Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_questions_table()
        show_success(self, f"Edit {item_noun}", f"{item_noun} updated successfully.")

    def handle_delete_marking_question(self, row: MarkingQuestionRow) -> None:
        is_kertas1 = self._current_marking_setup is not None and self._current_marking_setup.paper_type == PAPER_TYPE_KERTAS_1
        item_noun = "Question" if is_kertas1 else "Criterion"

        confirmed = prompt_confirm(
            self,
            f"Delete {item_noun}",
            f"Delete {item_noun.lower()} '{row.question_no}'?",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            delete_marking_question(conn, self._teacher_id, row.question_id)
        except ValueError as exc:
            show_error(self, f"Delete {item_noun} Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_questions_table()
        show_success(self, f"Delete {item_noun}", f"{item_noun} deleted successfully.")

    def handle_add_default_kertas2_criteria(self) -> None:
        if self._current_marking_setup is None:
            show_error(self, "Add Default Criteria Failed", "Please save the marking setup first.")
            return

        conn = get_connection()
        try:
            existing = list_marking_questions(conn, self._teacher_id, self._current_marking_setup.setup_id)
            existing_names = {q.question_no for q in existing}
            for name in DEFAULT_KERTAS_2_RUBRIC_CRITERIA:
                if name in existing_names:
                    continue
                add_marking_question(
                    conn,
                    self._teacher_id,
                    self._current_marking_setup.setup_id,
                    name,
                    "",
                    self._current_marking_setup.default_question_mark,
                    QUESTION_TYPE_RUBRIC_CRITERION,
                )
        except ValueError as exc:
            show_error(self, "Add Default Criteria Failed", str(exc))
            return
        finally:
            conn.close()

        self.refresh_marking_questions_table()
        show_success(self, "Add Default Criteria", "Default rubric criteria added successfully.")

    def handle_logout(self) -> None:
        from app.ui.login_window import LoginWindow

        self._login_window = LoginWindow()
        self._login_window.show()
        self.close()

    # --- Stage 11V: Subject Profile marking workflow ------------------------
    #
    # Replaces the old teacher-facing "choose a Template + paper type"
    # Marking tab. See app/services/subject_profile_service.py for the
    # backend; app/ui/overlay_canvas.py for the draggable/resizable/
    # rotatable overlay widget; docs/stage12_ai_plan.md for the (not yet
    # implemented) Stage 12 AI region-detection direction referenced by the
    # Subject Profile Editor's "AI region detection will be available in
    # Stage 12" note.

    def _show_progress_dialog(self, title: str) -> tuple:
        """Show a small modal dialog containing a CircularProgressWidget
        and return (dialog, widget), shown via .show() (not .exec(), so the
        caller regains control immediately) so processing can proceed while
        it's visible.

        Two update patterns coexist in this dashboard: Subject Profile
        creation (question paper/answer scheme processing) still runs
        synchronously on the UI thread, with its own progress_callback
        calling QApplication.processEvents() after each update so the UI
        repaints between steps - short enough in practice not to freeze the
        window. Student answer PDF processing (Stage 11W) instead runs on a
        StudentPdfProcessingWorker (QThread) - see handle_upload_student_
        answer_pdfs - since real OCR over a multi-PDF batch can run long
        enough to make a synchronous UI-thread loop visibly "Not
        Responding"; that worker's progress signal updates this same
        CircularProgressWidget without any processEvents() call needed."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setFixedSize(280, 220)
        dialog_layout = QVBoxLayout(dialog)
        widget = CircularProgressWidget()
        dialog_layout.addWidget(widget)
        dialog.show()
        QApplication.processEvents()
        return dialog, widget

    # --- Create Subject Profile ---------------------------------------------

    def handle_choose_subject_profile_question_paper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Question Paper PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        self._subject_profile_draft_qp_path = path
        self.subject_profile_qp_status_label.setText(Path(path).name)

    def handle_choose_subject_profile_answer_scheme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Answer Scheme PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        self._subject_profile_draft_as_path = path
        self.subject_profile_as_status_label.setText(Path(path).name)

    def handle_create_subject_profile(self) -> None:
        name = self.new_subject_profile_name_input.text()
        qp_path = self._subject_profile_draft_qp_path
        as_path = self._subject_profile_draft_as_path
        if not qp_path or not as_path:
            show_error(self, "Create Subject Profile Failed", "Choose both a question paper and an answer scheme PDF.")
            return

        conn = get_connection()
        try:
            try:
                profile = create_subject_profile(conn, self._teacher_id, name)
            except ValueError as exc:
                show_error(self, "Create Subject Profile Failed", str(exc))
                return
        finally:
            conn.close()

        progress_dialog, progress_widget = self._show_progress_dialog("Processing Subject Profile")

        def progress_callback(message: str, current: int, total: int) -> None:
            progress_widget.set_progress(message, current, total)
            QApplication.processEvents()

        conn = get_connection()
        try:
            try:
                profile = process_subject_profile_documents(
                    conn, self._teacher_id, profile.profile_id, qp_path, as_path,
                    progress_callback=progress_callback,
                )
            except ValueError as exc:
                progress_dialog.close()
                show_error(self, "Create Subject Profile Failed", str(exc))
                return
        finally:
            conn.close()

        progress_dialog.close()
        self.new_subject_profile_name_input.clear()
        self._subject_profile_draft_qp_path = None
        self._subject_profile_draft_as_path = None
        self.subject_profile_qp_status_label.setText("No file selected")
        self.subject_profile_as_status_label.setText("No file selected")
        self.refresh_subject_profiles_table()

        # Stage 12E-2-Fix: tell the teacher clearly (but calmly) how each
        # page's text was resolved - a fully "digital" PDF (every page has
        # its own text layer) never needed OCR at all, which is worth
        # surfacing since it explains why processing was fast/safe; an OCR
        # failure on some page is a non-blocking warning, never a reason to
        # refuse opening the editor - Suggest Regions works from the PDF's
        # text/layout regardless of whether OCR ever ran.
        usage = summarize_document_processing(profile)
        if usage["ocr_failed_pages"] > 0:
            message = (
                f"'{profile.profile_name}' created. {usage['ocr_failed_pages']} page(s) could not be OCR'd and have "
                "no extracted text, but the profile was created successfully - you can still open the editor and "
                "draw regions manually or run Detect Answer Regions."
            )
        elif usage["total_pages"] > 0 and usage["ocr_pages"] == 0 and usage["ocr_failed_pages"] == 0:
            message = f"'{profile.profile_name}' created. PDF text layer detected; OCR skipped for setup."
        else:
            message = f"'{profile.profile_name}' processed successfully. Define regions in the editor now."
        show_success(self, "Subject Profile Created", message)
        self.handle_open_subject_profile_editor(profile)

    # --- Existing Subject Profiles ------------------------------------------

    def refresh_subject_profiles_table(self) -> None:
        if self._teacher_id is None:
            return
        conn = get_connection()
        try:
            profiles = list_subject_profiles_for_teacher(conn, self._teacher_id)
        finally:
            conn.close()

        self.subject_profiles_table.setRowCount(len(profiles))
        for row_index, profile in enumerate(profiles):
            values = [
                profile.profile_name, profile.status.title(),
                format_timestamp(profile.updated_at or profile.created_at),
            ]
            for col_index, value in enumerate(values):
                self.subject_profiles_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.subject_profiles_table.setCellWidget(
                row_index, len(values), self._build_subject_profile_action_cell(profile)
            )

    def _build_subject_profile_action_cell(self, profile) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        open_button = QPushButton("Open / Edit")
        open_button.setObjectName("RowActionButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.setEnabled(profile.status != SUBJECT_PROFILE_STATUS_PROCESSING)
        open_button.clicked.connect(lambda _checked=False, p=profile: self.handle_open_subject_profile_editor(p))
        cell_layout.addWidget(open_button)

        use_button = QPushButton("Use for Marking")
        use_button.setObjectName("RowActionButton")
        use_button.setCursor(Qt.CursorShape.PointingHandCursor)
        use_button.setEnabled(profile.status == SUBJECT_PROFILE_STATUS_READY)
        use_button.clicked.connect(lambda _checked=False, p=profile: self.handle_use_subject_profile_for_marking(p))
        cell_layout.addWidget(use_button)

        export_button = QPushButton("Export")
        export_button.setObjectName("RowActionButton")
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(lambda _checked=False, p=profile: self.handle_export_subject_profile(p))
        cell_layout.addWidget(export_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.setEnabled(profile.status != SUBJECT_PROFILE_STATUS_PROCESSING)
        delete_button.clicked.connect(lambda _checked=False, p=profile: self.handle_delete_subject_profile(p))
        cell_layout.addWidget(delete_button)

        return cell

    def handle_delete_subject_profile(self, profile) -> None:
        confirmed = prompt_confirm(
            self, "Delete Subject Profile",
            f"Delete '{profile.profile_name}'? This permanently removes its question paper, answer scheme, "
            f"regions, answer key, and all student results. This cannot be undone.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                delete_subject_profile(conn, self._teacher_id, profile.profile_id)
            except ValueError as exc:
                show_error(self, "Delete Subject Profile Failed", str(exc))
                return
        finally:
            conn.close()

        selected = getattr(self, "_selected_profile_for_marking", None)
        if selected is not None and selected.profile_id == profile.profile_id:
            self._selected_profile_for_marking = None
            self.mark_student_answers_profile_label.setText(
                "No Subject Profile selected - click \"Use for Marking\" on a Subject Profile above."
            )
            self.upload_student_answers_button.setEnabled(False)
            self.refresh_student_results_table()

        self.refresh_subject_profiles_table()
        show_success(self, "Subject Profile Deleted", f"'{profile.profile_name}' was deleted.")

    def handle_export_subject_profile(self, profile) -> None:
        """Data Management Readiness Fix: export profile to a local .zip the
        teacher picks via a file-save dialog. Read-only against the
        profile - never fails just because some optional data (answer key,
        OCR content, an original PDF no longer on disk, ...) is missing;
        see export_manifest.json inside the zip for exactly what was
        included/omitted."""
        default_name = default_export_filename(profile.profile_name)
        destination_path, _ = QFileDialog.getSaveFileName(self, "Export Subject Profile", default_name, "Zip Files (*.zip)")
        if not destination_path:
            return

        conn = get_connection()
        try:
            try:
                manifest = export_subject_profile(conn, self._teacher_id, profile.profile_id, destination_path)
            except ValueError as exc:
                show_error(self, "Export Subject Profile Failed", str(exc))
                return
            except OSError as exc:
                show_error(self, "Export Subject Profile Failed", f"Could not write the export file: {exc}")
                return
        finally:
            conn.close()

        message = f"Exported '{profile.profile_name}' to:\n{destination_path}\n\nIncluded {len(manifest['files_included'])} file(s)."
        if manifest["files_missing"]:
            message += f"\n{len(manifest['files_missing'])} optional file(s) were omitted (see export_manifest.json)."
        show_success(self, "Subject Profile Exported", message)

    def handle_import_subject_profile(self) -> None:
        """Data Management Follow-up (feature 1): choose a previously
        exported Subject Profile .zip and recreate it as a brand-new,
        fully usable local profile - see
        app.services.subject_profile_import_service.import_subject_profile
        for exactly what's required/optional and how name collisions are
        resolved."""
        zip_path, _ = QFileDialog.getOpenFileName(self, "Choose Subject Profile Export", "", "Zip Files (*.zip)")
        if not zip_path:
            return
        self._run_subject_profile_import(zip_path, rename_as_copy=False)

    def _run_subject_profile_import(self, zip_path: str, rename_as_copy: bool) -> None:
        conn = get_connection()
        summary = None
        duplicate_error: Optional[DuplicateProfileNameError] = None
        try:
            try:
                summary = import_subject_profile(conn, self._teacher_id, zip_path, rename_as_copy=rename_as_copy)
            except DuplicateProfileNameError as exc:
                duplicate_error = exc
            except ValueError as exc:
                show_error(self, "Import Subject Profile Failed", str(exc))
                return
        finally:
            conn.close()

        if duplicate_error is not None:
            choice = prompt_confirm(
                self, "Subject Profile Already Exists",
                f"{duplicate_error}\n\nImport as a new copy named '{duplicate_error.suggested_name}' instead?",
                confirm_text="Import as Copy",
            )
            if choice:
                self._run_subject_profile_import(zip_path, rename_as_copy=True)
            return

        self.refresh_subject_profiles_table()
        lines = [f"Imported '{summary['profile_name']}' successfully."]
        if summary["renamed"]:
            lines.append("A profile with the original name already existed, so this was imported as a renamed copy.")
        lines.append(f"Regions restored: {summary['regions_imported']}.")
        if summary["regions_skipped"]:
            lines.append(f"{len(summary['regions_skipped'])} region(s) could not be restored.")
        lines.append(f"Region groups restored: {summary['groups_imported']}.")
        lines.append(f"Answer key entries restored: {summary['answer_key_entries_imported']}.")
        for warning in summary["warnings"]:
            lines.append(warning)
        show_success(self, "Subject Profile Imported", "\n".join(lines))

    def handle_use_subject_profile_for_marking(self, profile) -> None:
        self._selected_profile_for_marking = profile
        self.mark_student_answers_profile_label.setText(f"Selected Subject Profile: {profile.profile_name}")
        self.upload_student_answers_button.setEnabled(True)
        self.separate_answer_paper_checkbox.setEnabled(True)
        self.refresh_student_results_table()

    # --- Mark Student Answers ------------------------------------------------

    def handle_upload_student_answer_pdfs(self) -> None:
        """Stage 11W: runs the whole PDF-by-PDF batch on a background
        worker instead of synchronously on the UI thread - fixes the
        "jumps to 100% and the app becomes Not Responding" bug. Progress
        arrives via the worker's progress signal so the UI stays
        responsive and the CircularProgressWidget updates gradually,
        page by page.

        Marking Fix Follow-up: uses StudentPdfProcessingSubprocessWorker
        (a genuinely separate OS process via QProcess), not the original
        QThread-based StudentPdfProcessingWorker - running real PaddleOCR
        inside that QThread was found to crash the whole app with no
        Python traceback, reproduced repeatedly (about 1 success in 5
        attempts), while the identical work in a plain separate process
        completed reliably every time - see subject_profile_marking_
        worker_process.py's docstring. StudentPdfProcessingWorker itself
        is left in place (still covered by its own tests, which use a fake
        OCR engine and never hit the real-PaddleOCR-specific instability)
        rather than deleted, in case a future caller has a use for the
        lighter-weight in-process path with an injectable fake engine."""
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            show_error(self, "Upload Student Answer PDFs Failed", "Select a Subject Profile first.")
            return

        # Stage 12G-1B: Separate Answer Paper mode takes a different upload
        # path - the pages are standalone answers, so no Subject Profile
        # region extraction runs; the teacher maps the answers instead.
        if getattr(self, "separate_answer_paper_checkbox", None) is not None \
                and self.separate_answer_paper_checkbox.isChecked():
            self.handle_upload_separate_answer_paper()
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "Choose Student Answer PDFs", "", "PDF Files (*.pdf)")
        if not paths:
            return

        conn = get_connection()
        try:
            missing_targets = list_missing_answer_key_targets(conn, self._teacher_id, profile.profile_id)
        finally:
            conn.close()
        if missing_targets:
            preview = ", ".join(missing_targets[:15])
            if len(missing_targets) > 15:
                preview += f", and {len(missing_targets) - 15} more"
            # Marking Fix Follow-up (requirement 2): a plain Continue/
            # Cancel choice left a teacher with no useful path but to
            # guess - a third "Open Answer Key Setup" option jumps
            # straight to the Subject Profile Editor's Answer Key table
            # instead. missing_targets is already "Question N" (see
            # list_missing_answer_key_targets), never a raw region label.
            choice = prompt_three_way_choice(
                self, "Answer Key Incomplete",
                f"{len(missing_targets)} question(s) have no answer key entry defined yet: {preview}.\n\n"
                "These will be marked 'Missing Answer Key' (not scored as wrong) instead of silently "
                "showing 0.0.",
                primary_text="Open Answer Key Setup", secondary_text="Continue Anyway",
            )
            if choice == "cancel":
                return
            if choice == "primary":
                self.handle_open_subject_profile_editor(profile)
                return

        self.upload_student_answers_button.setEnabled(False)
        progress_dialog, progress_widget = self._show_progress_dialog("Marking Student Answers")
        self._student_pdf_progress_dialog = progress_dialog
        self._student_pdf_progress_widget = progress_widget

        worker = StudentPdfProcessingSubprocessWorker(self._teacher_id, profile.profile_id, paths, parent=self)
        worker.progress.connect(self.handle_student_pdf_worker_progress)
        worker.succeeded.connect(self.handle_student_pdf_worker_succeeded)
        worker.failed.connect(self.handle_student_pdf_worker_failed)
        worker.finished.connect(self.handle_student_pdf_worker_finished)
        self._student_pdf_worker = worker
        worker.start()

    def handle_student_pdf_worker_progress(self, message: str, current: int, total: int) -> None:
        self._student_pdf_progress_widget.set_progress(message, current, total)

    def handle_student_pdf_worker_succeeded(self, results: List[StudentPdfResult]) -> None:
        self._student_pdf_last_results = results
        self.refresh_student_results_table()

        failed = [r for r in results if not r.succeeded]
        if failed:
            details = "\n".join(f"{r.display_name}: {r.error}" for r in failed)
            show_error(
                self, "Some Student PDFs Failed",
                f"{len(results) - len(failed)} of {len(results)} processed successfully. Failed:\n{details}",
            )
        else:
            show_success(self, "Mark Student Answers", f"Processed {len(results)} student answer PDF(s) successfully.")

    def handle_student_pdf_worker_failed(self, message: str) -> None:
        show_error(self, "Mark Student Answers Failed", message)

    # --- Stage 12G-1B: Separate Answer Paper upload --------------------------

    def handle_upload_separate_answer_paper(self) -> None:
        """Create a Separate Answer Paper attempt from a PDF and/or ordered
        images. No Subject Profile region extraction runs - the teacher maps
        the answers in the Separate Answer Paper workspace."""
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose Separate Answer Paper Files (PDF or images, in order)", "",
            "Answer papers (*.pdf *.png *.jpg *.jpeg)")
        if not paths:
            return
        conn = get_connection()
        try:
            try:
                answer_file_id = separate_paper_service.create_separate_paper_attempt(
                    conn, self._teacher_id, profile.profile_id, list(paths))
                separate_paper_service.render_page_previews(
                    conn, self._teacher_id, profile.profile_id, answer_file_id)
                pages = separate_model.get_separate_pages(conn, answer_file_id)
            except ValueError as exc:
                show_error(self, "Separate Answer Paper Upload Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_student_results_table()
        show_detail(self, "Separate Answer Paper Uploaded",
                    f"{len(pages)} answer page(s) registered in Separate Answer Paper mode.\n\n"
                    "Open the attempt's Marking Editor and use 'Map Separate Answer Paper' to map "
                    "each required answer, then review and finalise as usual.")

    def handle_student_pdf_worker_finished(self) -> None:
        dialog = getattr(self, "_student_pdf_progress_dialog", None)
        if dialog is not None:
            dialog.close()
        self.upload_student_answers_button.setEnabled(True)
        self.separate_answer_paper_checkbox.setEnabled(True)
        self._student_pdf_worker = None

    def refresh_student_results_table(self) -> None:
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            self.student_results_table.setRowCount(0)
            self.download_all_results_button.setEnabled(False)
            return

        conn = get_connection()
        try:
            rows = list_student_results_for_profile(conn, self._teacher_id, profile.profile_id)
        finally:
            conn.close()

        self.download_all_results_button.setEnabled(len(rows) > 0)
        self.student_results_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            # Marking Fix Follow-up: Kertas 1/Kertas 2/Final are shown
            # separately (Kertas 2 essays only ever count once a teacher
            # enters a score - see compute_score_summary) instead of one
            # blended percentage that used to fold un-teacher-scored essays
            # in as misleading 0/20s.
            score_text = (
                f"K1: {row['kertas1_display']} | K2: {row['kertas2_display']} | Final: {row['final_display']}"
                if row["marked_count"] else "-"
            )
            values = [row["display_name"], format_marking_status_label(row["processing_status"]), score_text]
            for col_index, value in enumerate(values):
                self.student_results_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.student_results_table.setCellWidget(
                row_index, len(values), self._build_student_result_action_cell(row)
            )

    def _build_student_result_action_cell(self, row: dict) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        view_button = QPushButton("View / Mark")
        view_button.setObjectName("RowActionButton")
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.clicked.connect(lambda _checked=False, r=row: self.handle_open_marking_editor(r))
        cell_layout.addWidget(view_button)

        download_button = QPushButton("Download")
        download_button.setObjectName("RowActionButton")
        download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        download_button.clicked.connect(lambda _checked=False, r=row: self.handle_download_student_result(r))
        cell_layout.addWidget(download_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, r=row: self.handle_delete_student_marking(r))
        cell_layout.addWidget(delete_button)

        return cell

    def handle_delete_student_marking(self, row: dict) -> None:
        """Data Management Follow-up (feature 2): permanent hard delete for
        one student marking row, regardless of its processing_status
        (uploaded/preprocessed/marked/needs review) - see
        subject_profile_service.delete_student_marking for the exact
        cascade/disk-cleanup scope."""
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            return
        confirmed = prompt_confirm(
            self, "Delete Student Marking",
            "Are you sure you want to permanently delete this student marking? This will delete the uploaded "
            "answer file, extracted answers, marking results, generated outputs, and related processing data. "
            "This action cannot be undone.",
            confirm_text="Delete",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            try:
                delete_student_marking(conn, self._teacher_id, profile.profile_id, row["answer_file_id"])
            except ValueError as exc:
                show_error(self, "Delete Student Marking Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_student_results_table()
        show_success(self, "Student Marking Deleted", f"'{row['display_name']}' was permanently deleted.")

    def handle_download_student_result(self, row: dict) -> None:
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            return
        conn = get_connection()
        try:
            try:
                # Phase 2B: serve the latest FINAL teacher-reviewed outputs when
                # the attempt is finalised; otherwise fall back to the historical
                # on-the-fly export (clearly flagged as not the final result).
                resolved = review_service.get_download_output_folder(
                    conn, self._teacher_id, profile.profile_id, row["answer_file_id"])
            except ValueError as exc:
                show_error(self, "Download Failed", str(exc))
                return
        finally:
            conn.close()
        if resolved.get("is_final"):
            show_detail(self, "Download Student Result",
                        f"Final teacher-reviewed marked PDF and comments:\n{resolved['folder']}")
        else:
            show_detail(self, "Download Student Result (not finalised)",
                        "This attempt is not finalised - these are a non-final preview of the current "
                        f"marking, not the student's approved result:\n{resolved['folder']}")

    def handle_download_all_student_results(self) -> None:
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            return
        conn = get_connection()
        try:
            try:
                zip_path = export_all_student_results(conn, self._teacher_id, profile.profile_id)
            except ValueError as exc:
                show_error(self, "Download All Failed", str(exc))
                return
        finally:
            conn.close()
        show_detail(self, "Download All Student Results", f"ZIP file saved successfully:\n{zip_path}")

    # --- Subject Profile Editor ----------------------------------------------

    def handle_open_subject_profile_editor(self, profile) -> None:
        self._current_subject_profile = profile
        self.subject_profile_editor_title_label.setText(f"Subject Profile Editor - {profile.profile_name}")
        self._subject_profile_editor_source = SOURCE_QUESTION_PAPER
        self.subject_profile_qp_source_button.setChecked(True)
        self.subject_profile_as_source_button.setChecked(False)
        self._subject_profile_editor_page = 1
        self._subject_profile_region_undo_stack = []
        self._load_subject_profile_editor_source()
        self.shell.show_page("Subject Profile Editor")

    def handle_switch_subject_profile_source(self, source: str) -> None:
        self._subject_profile_editor_source = source
        self.subject_profile_qp_source_button.setChecked(source == SOURCE_QUESTION_PAPER)
        self.subject_profile_as_source_button.setChecked(source == SOURCE_ANSWER_SCHEME)
        self._subject_profile_editor_page = 1
        self._subject_profile_region_undo_stack = []
        self._load_subject_profile_editor_source()

    def _load_subject_profile_editor_source(self) -> None:
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            paths = get_document_page_image_paths(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
        finally:
            conn.close()
        self._subject_profile_editor_page_paths = paths
        self._load_current_subject_profile_editor_page()

    def _load_current_subject_profile_editor_page(self) -> bool:
        paths = self._subject_profile_editor_page_paths
        if not paths:
            self.subject_profile_page_label.setText("Page 0 of 0")
            return False
        index = max(0, min(self._subject_profile_editor_page - 1, len(paths) - 1))
        self._subject_profile_editor_page = index + 1
        image = render_page_image(paths[index], page_index=0)
        if image.isNull():
            show_error(self, "Subject Profile Editor Failed", "The processed page image could not be rendered.")
            return False
        self.subject_profile_canvas.load_image(image)
        self.subject_profile_page_label.setText(f"Page {self._subject_profile_editor_page} of {len(paths)}")
        self.subject_profile_prev_page_button.setEnabled(self._subject_profile_editor_page > 1)
        self.subject_profile_next_page_button.setEnabled(self._subject_profile_editor_page < len(paths))
        self.refresh_subject_profile_regions()
        self.refresh_subject_profile_region_groups()
        self.refresh_subject_profile_extracted_content()
        self.refresh_subject_profile_answer_key()
        return True

    def handle_subject_profile_prev_page(self) -> None:
        if self._subject_profile_editor_page <= 1:
            return
        self._subject_profile_editor_page -= 1
        self._load_current_subject_profile_editor_page()

    def handle_subject_profile_next_page(self) -> None:
        if self._subject_profile_editor_page >= len(self._subject_profile_editor_page_paths):
            return
        self._subject_profile_editor_page += 1
        self._load_current_subject_profile_editor_page()

    def handle_set_subject_profile_rectangle_mode(self) -> None:
        self.subject_profile_draw_rectangle_button.setChecked(True)
        self.subject_profile_draw_polygon_button.setChecked(False)
        self.subject_profile_finish_polygon_button.setVisible(False)
        self.subject_profile_cancel_polygon_button.setVisible(False)
        self.subject_profile_canvas.set_mode(TemplateCanvas.MODE_RECTANGLE)

    def handle_set_subject_profile_polygon_mode(self) -> None:
        self.subject_profile_draw_rectangle_button.setChecked(False)
        self.subject_profile_draw_polygon_button.setChecked(True)
        self.subject_profile_finish_polygon_button.setVisible(True)
        self.subject_profile_cancel_polygon_button.setVisible(True)
        self.subject_profile_canvas.set_mode(TemplateCanvas.MODE_POLYGON)

    def handle_finish_subject_profile_polygon(self) -> None:
        if not self.subject_profile_canvas.finish_polygon():
            show_error(self, "Finish Polygon", "Add at least 3 points before finishing the polygon.")

    def handle_cancel_subject_profile_polygon(self) -> None:
        self.subject_profile_canvas.cancel_polygon()

    def _close_sp_proposal_progress(self) -> None:
        dialog = getattr(self, "_sp_proposal_progress_dialog", None)
        self._sp_proposal_progress_dialog = None
        if dialog is not None:
            dialog.close()

    def handle_subject_profile_run_proposals(self) -> None:
        """Stage 12G-4 (workflow A): run Core AI 2 proposals on the current
        Subject Profile page (background) with a progress dialog, then open the
        review dialog. A no-model/failure result changes nothing - drawing
        regions manually remains available."""
        if self._current_subject_profile is None:
            return
        paths = getattr(self, "_subject_profile_editor_page_paths", [])
        index = self._subject_profile_editor_page - 1
        if not (0 <= index < len(paths)) or not paths[index]:
            self.subject_profile_editor_status_label.setText("Render the page first.")
            return
        self.core_ai2_proposals_button.setEnabled(False)
        dialog, widget = self._show_progress_dialog("Detecting Answer Regions")
        widget.set_progress("Running the region detector on this page...", 0, 1)
        self._sp_proposal_progress_dialog = dialog
        self._sp_proposal_worker = SubjectProfileProposalWorker(
            self._teacher_id, self._current_subject_profile.profile_id,
            self._subject_profile_editor_source, self._subject_profile_editor_page, paths[index])
        self._sp_proposal_worker.succeeded.connect(self._on_sp_proposals_ready)
        self._sp_proposal_worker.failed.connect(self._on_sp_proposals_failed)
        self._sp_proposal_worker.finished.connect(self._close_sp_proposal_progress)
        self._sp_proposal_worker.finished.connect(
            lambda: self.core_ai2_proposals_button.setEnabled(True))
        self._sp_proposal_worker.start()

    def handle_subject_profile_run_proposals_all_pages(self) -> None:
        """Run Core AI 2 proposals for every rendered page of the current
        source (background, per-page progress), then open the review dialog
        covering all pages."""
        if self._current_subject_profile is None:
            return
        paths = getattr(self, "_subject_profile_editor_page_paths", [])
        page_paths = [(number, path) for number, path in enumerate(paths, start=1) if path]
        if not page_paths:
            self.subject_profile_editor_status_label.setText("Render the pages first.")
            return
        self.core_ai2_proposals_all_button.setEnabled(False)
        dialog, widget = self._show_progress_dialog("Detecting Answer Regions")
        widget.set_progress(f"Detecting regions on {len(page_paths)} page(s)...",
                            0, len(page_paths))
        self._sp_proposal_progress_dialog = dialog
        self._sp_all_proposal_worker = SubjectProfileAllPagesProposalWorker(
            self._teacher_id, self._current_subject_profile.profile_id,
            self._subject_profile_editor_source, page_paths)
        self._sp_all_proposal_worker.progressed.connect(widget.set_progress)
        self._sp_all_proposal_worker.succeeded.connect(self._on_sp_proposals_ready)
        self._sp_all_proposal_worker.failed.connect(self._on_sp_proposals_failed)
        self._sp_all_proposal_worker.finished.connect(self._close_sp_proposal_progress)
        self._sp_all_proposal_worker.finished.connect(
            lambda: self.core_ai2_proposals_all_button.setEnabled(True))
        self._sp_all_proposal_worker.start()

    def handle_apply_all_proposals(self) -> None:
        """Accept EVERY pending Core AI 2 proposal on this document as a
        normal editable region, after one explicit confirmation. Existing
        manual regions are never overwritten (service guarantee), and each
        accepted region stays fully editable/deletable."""
        from app.services import ai_region_proposal_service as proposals_svc
        from app.models import ai_region_proposal_model as rp
        if self._current_subject_profile is None:
            return
        profile_id = self._current_subject_profile.profile_id
        conn = get_connection()
        try:
            pending = [r.proposal_id for r in proposals_svc.list_profile_proposals(
                conn, self._teacher_id, profile_id, source=self._subject_profile_editor_source)
                if r.status in (rp.STATUS_PROPOSED, rp.STATUS_EDITED)]
        finally:
            conn.close()
        if not pending:
            self.subject_profile_editor_status_label.setText("No proposals awaiting review.")
            return
        if not prompt_confirm(
                self, "Apply All Proposals",
                f"Accept all {len(pending)} pending proposal(s) as editable regions?\n\n"
                "Existing manual regions are never overwritten, and every accepted region "
                "stays fully editable and deletable afterwards.",
                confirm_text="Accept all"):
            return
        conn = get_connection()
        try:
            accepted = proposals_svc.bulk_accept(conn, self._teacher_id, pending)
        finally:
            conn.close()
        self.subject_profile_editor_status_label.setText(
            f"Accepted {accepted} proposal(s) as editable regions. Review and adjust them "
            "like any manually drawn region.")
        self.refresh_subject_profile_regions()

    def _on_sp_proposals_ready(self, count: int) -> None:
        if count == 0:
            self.subject_profile_editor_status_label.setText(
                "No regions detected (no active AI model, or nothing was found). Draw regions "
                "manually.")
            return
        self.handle_subject_profile_open_proposal_review()

    def _on_sp_proposals_failed(self, message: str) -> None:
        show_error(self, "Region Detection Failed",
                   f"{message}\n\nNo proposals were applied - draw regions manually.")

    def handle_subject_profile_open_proposal_review(self) -> None:
        from app.services import ai_region_proposal_service as proposals_svc
        from app.models import ai_region_proposal_model as rp
        if self._current_subject_profile is None:
            return
        profile_id = self._current_subject_profile.profile_id
        while True:
            conn = get_connection()
            try:
                records = [r for r in proposals_svc.list_profile_proposals(
                    conn, self._teacher_id, profile_id, source=self._subject_profile_editor_source)
                    if r.status in (rp.STATUS_PROPOSED, rp.STATUS_EDITED)]
            finally:
                conn.close()
            if not records:
                self.subject_profile_editor_status_label.setText("No proposals awaiting review.")
                return
            data = [{
                "proposal_id": r.proposal_id, "proposed_class": r.proposed_class,
                "confidence": r.confidence, "model_version": r.model_version,
                "rationale": r.rationale, "status": r.status, "geometry": r.effective_geometry,
            } for r in records]
            dialog = RegionProposalReviewDialog(self, "Detected Answer Regions", data, targets=[])
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dialog.values()
            conn = get_connection()
            try:
                try:
                    self._apply_proposal_decision(conn, proposals_svc, decision)
                except (proposals_svc.ProposalError, ValueError) as exc:
                    show_error(self, "Proposal Decision Failed", str(exc))
                    return
            finally:
                conn.close()
            self.refresh_subject_profile_regions()
            if not decision.get("keep_open"):
                return

    def handle_preview_answer_scheme_answers(self) -> None:
        """Stage 12E-2 requirement 7: read-only preview of the answer
        scheme's parsed objective answer list - never writes to the answer
        key until the teacher explicitly confirms via the follow-up
        prompt, and never overwrites an existing answer-key entry that
        already has a value unless that confirmation is given."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            entries = preview_answer_scheme_answer_list(conn, self._teacher_id, self._current_subject_profile.profile_id)
            preview_text = preview_answer_scheme_formatted_text(conn, self._teacher_id, self._current_subject_profile.profile_id)
        finally:
            conn.close()

        if not entries:
            show_error(self, "Preview Answer Scheme", "No objective answer-list entries (e.g. \"1. A\") were detected in the answer scheme PDF.")
            return

        confirmed = prompt_confirm(
            self, "Preview Answer Scheme",
            f"Detected {len(entries)} answer(s):\n\n{preview_text}\n\n"
            "Apply these to the answer key? Existing answers already set are left untouched.",
            confirm_text="Apply",
        )
        if not confirmed:
            return

        conn = get_connection()
        try:
            written = apply_parsed_answer_scheme_entries(
                conn, self._teacher_id, self._current_subject_profile.profile_id, entries, overwrite=False,
            )
        finally:
            conn.close()
        show_success(self, "Preview Answer Scheme", f"Applied {len(written)} answer(s) to the answer key.")
        self.refresh_subject_profile_answer_key()

    # --- Region editing undo (Data Management Readiness Fix, Ctrl+Z) -------
    #
    # The Subject Profile region editor autosaves every action immediately
    # (each handler below calls its service function, which commits to the
    # database right away, then refreshes the canvas/table) - there is no
    # in-memory "unsaved draft" region list to roll back. So undo here
    # restores the previous SAVED state by re-saving it: each handler pushes
    # a small closure onto _subject_profile_region_undo_stack right after
    # its own successful save, capturing exactly the prior values needed to
    # reverse that one action via the same service functions. Ctrl+Z pops
    # and calls the most recent closure, then does one refresh. The stack is
    # cleared whenever a different profile/source is opened (see
    # handle_open_subject_profile_editor / handle_switch_subject_profile_
    # source) - it is NOT cleared on page navigation, since an edit made
    # just before flipping pages should still be undoable.

    def _push_region_undo(self, undo_action: Callable[[], None]) -> None:
        self._subject_profile_region_undo_stack.append(undo_action)

    def handle_subject_profile_region_undo(self) -> None:
        """Ctrl+Z - undo the most recent region-editing action, if any.
        Gracefully does nothing when the stack is empty."""
        if not self._subject_profile_region_undo_stack:
            return
        undo_action = self._subject_profile_region_undo_stack.pop()
        undo_action()
        self.refresh_subject_profile_regions()

    def _undo_delete_region(self, region_id: int) -> None:
        """Reverses a CREATE: deletes the region that was just created."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            remove_subject_profile_region_svc(conn, self._teacher_id, self._current_subject_profile.profile_id, region_id)
        except ValueError:
            pass  # already gone somehow - undo is best-effort, never raises
        finally:
            conn.close()

    def _undo_recreate_region(
        self, source: str, label: str, region_type: str, page_number: int,
        x: float, y: float, width: float, height: float,
        shape_type: str, polygon_points_json: Optional[str], rotation_angle: float, notes: Optional[str],
    ) -> None:
        """Reverses a DELETE: recreates an equivalent region with the same
        label/type/geometry/notes. Known limitation: the restored region
        gets a NEW region_id (SQLite auto-assigns it), so if the deleted
        region was a member of a region group, undo does not automatically
        re-add it to that group - restoring group membership on undo was
        judged out of scope for this focused fix (there is no existing
        "edit a region's group" action either)."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            try:
                add_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id,
                    source, label, region_type, page_number, x, y, width, height,
                    shape_type=shape_type, polygon_points_json=polygon_points_json,
                    rotation_angle=rotation_angle, notes=notes,
                )
            except ValueError:
                pass
        finally:
            conn.close()

    def _undo_move_region(
        self, region_id: int, x: float, y: float, width: float, height: float,
        polygon_points_json: Optional[str] = None,
    ) -> None:
        """Reverses a MOVE or RESIZE: restores the previous x/y/width/
        height (and polygon points, for a moved polygon region)."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            move_subject_profile_region_svc(
                conn, self._teacher_id, self._current_subject_profile.profile_id, region_id,
                x, y, width, height, polygon_points_json=polygon_points_json,
            )
        except ValueError:
            pass
        finally:
            conn.close()

    def _undo_edit_region(self, region_id: int, label: str, region_type: str, rotation_angle: float, notes: Optional[str]) -> None:
        """Reverses a label/type change: restores the previous label/
        region_type/rotation_angle/notes."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            edit_subject_profile_region_svc(
                conn, self._teacher_id, self._current_subject_profile.profile_id, region_id,
                label, region_type, rotation_angle, notes,
            )
        except ValueError:
            pass
        finally:
            conn.close()

    def handle_subject_profile_region_drawn(self, x: float, y: float, width: float, height: float) -> None:
        if self._current_subject_profile is None:
            return
        self._save_new_subject_profile_region(x, y, width, height, "rectangle", None)

    def handle_subject_profile_polygon_region_drawn(self, points: list) -> None:
        if self._current_subject_profile is None:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x, y = min(xs), min(ys)
        width, height = max(xs) - x, max(ys) - y
        self._save_new_subject_profile_region(x, y, width, height, "polygon", points)

    def handle_subject_profile_region_moved(self, region_id: int, x: float, y: float) -> None:
        """Drag-to-move a rectangle region (Stage 12E-2 UX Fix 2). width/
        height are unchanged - only x/y move. Reuses the existing move_
        region service path - never touches label/type/notes."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            regions = list_subject_profile_regions(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
            region = next((r for r in regions if r.region_id == region_id), None)
            if region is None:
                return
            old_x, old_y, old_width, old_height = region.x, region.y, region.width, region.height
            try:
                move_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, region_id,
                    x, y, region.width, region.height,
                )
            except ValueError as exc:
                show_error(self, "Move Region Failed", str(exc))
                return
        finally:
            conn.close()
        self._push_region_undo(
            lambda rid=region_id, ox=old_x, oy=old_y, ow=old_width, oh=old_height:
                self._undo_move_region(rid, ox, oy, ow, oh)
        )
        self.refresh_subject_profile_regions()

    def handle_subject_profile_polygon_region_moved(self, region_id: int, points: list) -> None:
        """Drag-to-move a polygon region (Stage 12E-2 UX Fix 2). Recomputes
        the bounding-box x/y/width/height from the new points, same
        convention as handle_subject_profile_polygon_region_drawn - the
        polygon's own points are the source of truth, x/y/width/height are
        only a cached bounding box for rectangle-compatible consumers."""
        if self._current_subject_profile is None:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x, y = min(xs), min(ys)
        width, height = max(xs) - x, max(ys) - y
        conn = get_connection()
        try:
            regions = list_subject_profile_regions(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
            region = next((r for r in regions if r.region_id == region_id), None)
            if region is None:
                return
            old_x, old_y, old_width, old_height = region.x, region.y, region.width, region.height
            old_points_json = region.polygon_points_json
            try:
                move_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, region_id,
                    x, y, width, height, polygon_points_json=json.dumps(points),
                )
            except ValueError as exc:
                show_error(self, "Move Region Failed", str(exc))
                return
        finally:
            conn.close()
        self._push_region_undo(
            lambda rid=region_id, ox=old_x, oy=old_y, ow=old_width, oh=old_height, opts=old_points_json:
                self._undo_move_region(rid, ox, oy, ow, oh, polygon_points_json=opts)
        )
        self.refresh_subject_profile_regions()

    def handle_subject_profile_region_resized(self, region_id: int, x: float, y: float, width: float, height: float) -> None:
        """Corner-handle resize (Stage 12E-2 UX Fix 2) - only ever emitted
        by the canvas for axis-aligned rectangle regions (never polygon or
        rotated regions - see TemplateCanvas's class docstring), so this
        always persists a plain x/y/width/height update with no polygon
        points involved."""
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            regions = list_subject_profile_regions(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
            region = next((r for r in regions if r.region_id == region_id), None)
            if region is None:
                return
            old_x, old_y, old_width, old_height = region.x, region.y, region.width, region.height
            try:
                move_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, region_id,
                    x, y, width, height,
                )
            except ValueError as exc:
                show_error(self, "Resize Region Failed", str(exc))
                return
        finally:
            conn.close()
        self._push_region_undo(
            lambda rid=region_id, ox=old_x, oy=old_y, ow=old_width, oh=old_height:
                self._undo_move_region(rid, ox, oy, ow, oh)
        )
        self.refresh_subject_profile_regions()

    def _save_new_subject_profile_region(
        self, x: float, y: float, width: float, height: float, shape_type: str, polygon_points: Optional[list]
    ) -> None:
        label = prompt_input(self, "New Region", "Enter a name for this region (e.g. Q1).")
        if label is None:
            self.refresh_subject_profile_regions()
            return

        region_type = prompt_select(
            self, "New Region", "Select a region type.",
            [(region_type_friendly_label(rt), rt) for rt in ALL_SUBJECT_PROFILE_REGION_TYPES],
        )
        if region_type is CANCELLED:
            self.refresh_subject_profile_regions()
            return

        conn = get_connection()
        try:
            try:
                created_region = add_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id,
                    self._subject_profile_editor_source, label, region_type,
                    self._subject_profile_editor_page, x, y, width, height,
                    shape_type=shape_type,
                    polygon_points_json=json.dumps(polygon_points) if polygon_points else None,
                )
            except ValueError as exc:
                show_error(self, "Add Region Failed", str(exc))
                return
        finally:
            conn.close()

        self._push_region_undo(lambda rid=created_region.region_id: self._undo_delete_region(rid))
        self.refresh_subject_profile_regions()

    def refresh_subject_profile_regions(self) -> None:
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            regions = list_subject_profile_regions(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
        finally:
            conn.close()

        self.subject_profile_canvas.clear_overlays()
        self._subject_profile_region_checkboxes = {}
        current_page_regions = [r for r in regions if r.page_number == self._subject_profile_editor_page]
        for region in current_page_regions:
            is_ignore = region.region_type in IGNORED_REGION_TYPES
            if region.shape_type == "polygon" and region.polygon_points_json:
                points = json.loads(region.polygon_points_json)
                self.subject_profile_canvas.add_polygon_region_overlay(
                    region.label, points, is_ignore=is_ignore, rotation_angle=region.rotation_angle,
                    region_id=region.region_id, region_type=region.region_type,
                )
            else:
                self.subject_profile_canvas.add_region_overlay(
                    region.label, region.x, region.y, region.width, region.height,
                    is_ignore=is_ignore, rotation_angle=region.rotation_angle,
                    region_id=region.region_id, region_type=region.region_type,
                )

        # Stage 12E-2 UX Fix: signals blocked while rebuilding rows, so the
        # itemSelectionChanged connection doesn't fire (and echo back into
        # the canvas) for every intermediate row add/remove during rebuild -
        # only the final, deliberate selectRow/clearSelection below matters.
        self.subject_profile_regions_table.blockSignals(True)
        self.subject_profile_regions_table.setRowCount(len(regions))
        selected_region_id = self.subject_profile_canvas.get_selected_region()
        selected_row_index = None
        for row_index, region in enumerate(regions):
            checkbox = QCheckBox()
            self._subject_profile_region_checkboxes[region.region_id] = checkbox
            self.subject_profile_regions_table.setCellWidget(row_index, 0, checkbox)
            label_item = QTableWidgetItem(region.label)
            label_item.setData(Qt.ItemDataRole.UserRole, region.region_id)
            self.subject_profile_regions_table.setItem(row_index, 1, label_item)
            self.subject_profile_regions_table.setItem(row_index, 2, QTableWidgetItem(region_type_friendly_label(region.region_type)))
            self.subject_profile_regions_table.setItem(row_index, 3, QTableWidgetItem(str(region.page_number)))
            self.subject_profile_regions_table.setCellWidget(
                row_index, 4, self._build_subject_profile_region_action_cell(region)
            )
            if region.region_id == selected_region_id:
                selected_row_index = row_index
        if selected_row_index is not None:
            self.subject_profile_regions_table.selectRow(selected_row_index)
            self.subject_profile_regions_table.scrollToItem(self.subject_profile_regions_table.item(selected_row_index, 1))
        else:
            self.subject_profile_regions_table.clearSelection()
        self.subject_profile_regions_table.blockSignals(False)

    def handle_edit_subject_profile_region(self, region) -> None:
        label = prompt_input(self, "Edit Region", "Region name.", placeholder=region.label)
        if label is None:
            return
        region_type = prompt_select(
            self, "Edit Region", "Select a region type.",
            [(region_type_friendly_label(rt), rt) for rt in ALL_SUBJECT_PROFILE_REGION_TYPES],
        )
        if region_type is CANCELLED:
            return
        old_label, old_region_type, old_rotation, old_notes = region.label, region.region_type, region.rotation_angle, region.notes
        conn = get_connection()
        try:
            try:
                edit_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, region.region_id,
                    label or region.label, region_type, region.rotation_angle, region.notes,
                )
            except ValueError as exc:
                show_error(self, "Edit Region Failed", str(exc))
                return
        finally:
            conn.close()
        self._push_region_undo(
            lambda rid=region.region_id, ol=old_label, ot=old_region_type, orot=old_rotation, on=old_notes:
                self._undo_edit_region(rid, ol, ot, orot, on)
        )
        self.refresh_subject_profile_regions()

    def handle_remove_subject_profile_region(self, region) -> None:
        confirmed = prompt_confirm(self, "Remove Region", f"Remove region '{region.label}'?", confirm_text="Remove")
        if not confirmed:
            return
        conn = get_connection()
        try:
            try:
                remove_subject_profile_region_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, region.region_id
                )
            except ValueError as exc:
                show_error(self, "Remove Region Failed", str(exc))
                return
        finally:
            conn.close()
        self._push_region_undo(
            lambda src=region.source, l=region.label, rt=region.region_type, pn=region.page_number,
                   x=region.x, y=region.y, w=region.width, h=region.height, st=region.shape_type,
                   ppj=region.polygon_points_json, rot=region.rotation_angle, n=region.notes:
                self._undo_recreate_region(src, l, rt, pn, x, y, w, h, st, ppj, rot, n)
        )
        self.refresh_subject_profile_regions()

    def handle_subject_profile_canvas_region_selected(self, region_id: int) -> None:
        """Preview click selected region_id (Stage 12E-2 UX Fix) - select
        and scroll to the matching region table row. Signals are blocked
        around the table update so this can't loop back into
        handle_subject_profile_region_table_selection_changed."""
        table = self.subject_profile_regions_table
        for row_index in range(table.rowCount()):
            label_item = table.item(row_index, 1)
            if label_item is not None and label_item.data(Qt.ItemDataRole.UserRole) == region_id:
                table.blockSignals(True)
                table.selectRow(row_index)
                table.blockSignals(False)
                table.scrollToItem(label_item)
                break

    def handle_subject_profile_canvas_region_deselected(self) -> None:
        table = self.subject_profile_regions_table
        table.blockSignals(True)
        table.clearSelection()
        table.blockSignals(False)

    def handle_subject_profile_region_table_selection_changed(self) -> None:
        """Region table row selection changed (Stage 12E-2 UX Fix) - sync
        the matching preview region highlight. set_selected_region never
        itself emits region_selected/region_deselected, so this cannot loop
        back into handle_subject_profile_canvas_region_selected/deselected."""
        selected_rows = self.subject_profile_regions_table.selectionModel().selectedRows()
        if not selected_rows:
            self.subject_profile_canvas.clear_selection()
            return
        label_item = self.subject_profile_regions_table.item(selected_rows[0].row(), 1)
        region_id = label_item.data(Qt.ItemDataRole.UserRole) if label_item is not None else None
        self.subject_profile_canvas.set_selected_region(region_id)

    def handle_delete_selected_subject_profile_region(self) -> None:
        """Delete key (Stage 12E-2 UX Fix) - reuses the exact existing
        handle_remove_subject_profile_region confirm+delete path (its own
        confirmation dialog included) for whichever region is currently
        selected in the preview/table; a no-op if nothing is selected.

        Known minor limitation: the preview/table selection is cleared
        afterward even if the user cancels the confirmation dialog, since
        handle_remove_subject_profile_region does not report whether the
        delete actually happened - low risk, since only the highlight is
        affected, never the region itself."""
        region_id = self.subject_profile_canvas.get_selected_region()
        if region_id is None or self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            regions = list_subject_profile_regions(
                conn, self._teacher_id, self._current_subject_profile.profile_id, self._subject_profile_editor_source
            )
        finally:
            conn.close()
        region = next((r for r in regions if r.region_id == region_id), None)
        if region is None:
            return
        self.handle_remove_subject_profile_region(region)
        self.subject_profile_canvas.clear_selection()
        self.subject_profile_regions_table.blockSignals(True)
        self.subject_profile_regions_table.clearSelection()
        self.subject_profile_regions_table.blockSignals(False)

    def handle_clear_subject_profile_region_selection(self) -> None:
        """Esc key (Stage 12E-2 UX Fix) - deselect the selected preview
        region and its matching table row, if any."""
        self.subject_profile_canvas.clear_selection()
        self.subject_profile_regions_table.blockSignals(True)
        self.subject_profile_regions_table.clearSelection()
        self.subject_profile_regions_table.blockSignals(False)

    def handle_create_subject_profile_region_group(self) -> None:
        selected_ids = [rid for rid, cb in self._subject_profile_region_checkboxes.items() if cb.isChecked()]
        if len(selected_ids) < 2:
            show_error(self, "Create Group Failed", "Select at least 2 regions (checkboxes) to combine into a group.")
            return

        values = prompt_region_group_form(
            self, "Create Region Group", f"Combining {len(selected_ids)} region(s).",
            [(region_type_friendly_label(rt), rt) for rt in ALL_SUBJECT_PROFILE_REGION_TYPES if rt not in IGNORED_REGION_TYPES],
        )
        if values is None:
            return

        conn = get_connection()
        try:
            try:
                create_subject_profile_region_group_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id,
                    values["label"], values["region_type"], selected_ids, values.get("notes") or None,
                )
            except ValueError as exc:
                show_error(self, "Create Group Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_subject_profile_regions()
        self.refresh_subject_profile_region_groups()
        show_success(self, "Create Group", "Region group created successfully.")

    def refresh_subject_profile_region_groups(self) -> None:
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            groups = list_subject_profile_region_groups(conn, self._teacher_id, self._current_subject_profile.profile_id)
        finally:
            conn.close()

        conn = get_connection()
        try:
            member_counts = {
                group.group_id: len(subject_profile_model.get_members_for_group(conn, group.group_id))
                for group in groups
            }
        finally:
            conn.close()
        self.subject_profile_region_groups_table.setRowCount(len(groups))
        for row_index, group in enumerate(groups):
            self.subject_profile_region_groups_table.setItem(row_index, 0, QTableWidgetItem(group.label))
            self.subject_profile_region_groups_table.setItem(row_index, 1, QTableWidgetItem(region_type_friendly_label(group.region_type)))
            self.subject_profile_region_groups_table.setItem(
                row_index, 2, QTableWidgetItem(str(member_counts.get(group.group_id, 0))))
            self.subject_profile_region_groups_table.setCellWidget(
                row_index, 3, self._build_subject_profile_region_group_action_cell(group)
            )

    def handle_edit_subject_profile_region_group(self, group) -> None:
        label = prompt_input(self, "Edit Group", "Group name.", placeholder=group.label)
        if label is None:
            return
        region_type = prompt_select(
            self, "Edit Group", "Select a region type.",
            [(region_type_friendly_label(rt), rt) for rt in ALL_SUBJECT_PROFILE_REGION_TYPES],
        )
        if region_type is CANCELLED:
            return
        conn = get_connection()
        try:
            try:
                edit_subject_profile_region_group_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id,
                    group.group_id, label or group.label, region_type,
                )
            except ValueError as exc:
                show_error(self, "Edit Group Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_subject_profile_region_groups()

    def handle_remove_subject_profile_region_group(self, group) -> None:
        confirmed = prompt_confirm(self, "Delete Group", f"Delete region group '{group.label}'?", confirm_text="Delete")
        if not confirmed:
            return
        conn = get_connection()
        try:
            try:
                remove_subject_profile_region_group_svc(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, group.group_id
                )
            except ValueError as exc:
                show_error(self, "Delete Group Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_subject_profile_region_groups()

    def refresh_subject_profile_extracted_content(self) -> None:
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            profile = get_subject_profile(conn, self._teacher_id, self._current_subject_profile.profile_id)
        finally:
            conn.close()

        raw_json = (
            profile.question_paper_extracted_json if self._subject_profile_editor_source == SOURCE_QUESTION_PAPER
            else profile.answer_scheme_extracted_json
        )
        if not raw_json:
            self.subject_profile_extracted_content_view.setPlainText("")
            return
        pages = json.loads(raw_json)
        text = "\n\n".join(f"Page {i + 1}: {page_text}" for i, page_text in enumerate(pages))
        self.subject_profile_extracted_content_view.setPlainText(text)

    def refresh_subject_profile_answer_key(self) -> None:
        if self._current_subject_profile is None:
            return
        conn = get_connection()
        try:
            entries = list_answer_key_entries(conn, self._teacher_id, self._current_subject_profile.profile_id)
            targets = list_subject_profile_extraction_targets_ui(
                conn, self._current_subject_profile.profile_id
            )
        finally:
            conn.close()

        entries_by_label = {e.target_label: e for e in entries}
        # Union of existing answer-key entries and current question-paper
        # targets, so a target with no entry yet still shows an editable
        # row. Stage 12E-2 Precision Fix requirement 7: an UNREVIEWED
        # assisted region suggestion (still carrying its "Suggested: ..."
        # label) is a layout label, not a confirmed gradable target yet -
        # it's excluded here until the teacher either gives it a real
        # answer key entry (at which point it shows like any other target)
        # or renames/accepts it in the region editor. This only affects
        # what's DISPLAYED here; the region itself is untouched.
        target_labels = [t.label for t in targets if not t.label.startswith("Suggested: ") or t.label in entries_by_label]
        labels = list(dict.fromkeys(target_labels + list(entries_by_label.keys())))

        self.subject_profile_answer_key_table.setRowCount(len(labels))
        for row_index, label in enumerate(labels):
            entry = entries_by_label.get(label)
            target_kind = next((t.kind for t in targets if t.label == label), "region")
            # Marking Fix Follow-up (requirement 3): auto-derive the
            # question number straight from the label's own "..._q<N>_..."
            # convention (qp_p8_q27_blank -> 27) so a teacher immediately
            # SEES which question a row is for, without typing it in - a
            # label with no derivable number (a helper/legend region) just
            # shows blank, same as before.
            suggested_question_no = extract_question_number_from_label(label)
            values = [
                entry.question_no if entry else (suggested_question_no or ""),
                label,
                entry.correct_answer if entry else "",
                str(entry.max_mark) if entry else "1.0",
            ]
            for col_index, value in enumerate(values):
                self.subject_profile_answer_key_table.setItem(row_index, col_index, QTableWidgetItem(str(value or "")))
            self.subject_profile_answer_key_table.setCellWidget(
                row_index, 4,
                self._build_subject_profile_answer_key_action_cell((label, target_kind, entry)),
            )

    def handle_edit_subject_profile_answer_key(self, target) -> None:
        label, target_kind, entry = target
        initial = {
            "question_no": entry.question_no if entry else (extract_question_number_from_label(label) or ""),
            "correct_answer": entry.correct_answer if entry else "",
            "max_mark": entry.max_mark if entry else 1.0,
            "comment": entry.comment if entry else "",
        }
        values = prompt_answer_key_entry(self, f"Answer Key - {label}", f"Target: {label}", initial)
        if values is None:
            return
        try:
            max_mark = float(values["max_mark"])
        except (TypeError, ValueError):
            show_error(self, "Save Answer Key Failed", "Max mark must be a number.")
            return

        conn = get_connection()
        try:
            try:
                save_answer_key_entry(
                    conn, self._teacher_id, self._current_subject_profile.profile_id, label, target_kind,
                    values["question_no"] or None, values["correct_answer"] or None, max_mark,
                    values["comment"] or None,
                )
            except ValueError as exc:
                show_error(self, "Save Answer Key Failed", str(exc))
                return
        finally:
            conn.close()

        self.refresh_subject_profile_answer_key()
        show_success(self, "Save Answer Key", "Answer key entry saved successfully.")

    def handle_extract_answer_key_from_answer_scheme(self) -> None:
        """Marking Fix Follow-up 3 (requirement 2): OCR the answer scheme's
        own printed answer list and auto-fill Q1-Q40 - see extract_answer_
        key_from_answer_scheme's docstring for how. Works identically for
        a profile created before this fix existed (requirement 4's
        "backfill") since it's a plain on-demand action, not a one-time
        setup step - the teacher can click this any time."""
        if self._current_subject_profile is None:
            return
        progress_dialog, progress_widget = self._show_progress_dialog("Extracting Answer Key")

        def report(message: str, current: int, total: int) -> None:
            progress_widget.set_progress(message, current, total)
            QApplication.processEvents()

        conn = get_connection()
        try:
            try:
                summary = extract_answer_key_from_answer_scheme(
                    conn, self._teacher_id, self._current_subject_profile.profile_id,
                    progress_callback=report)
            except ValueError as exc:
                progress_dialog.close()
                show_error(self, "Extract Answer Key Failed", str(exc))
                return
        finally:
            conn.close()
            progress_dialog.close()

        self.refresh_subject_profile_answer_key()

        extracted_count = len(summary["extracted"])
        overwritten_count = len(summary["overwritten"])
        already_set_count = len(summary["already_set"])
        missing = summary["missing"]
        unlabelled = summary.get("unlabelled", [])
        recovered = summary.get("recovered", [])
        lines = [
            f"Extracted: {extracted_count} question(s) newly filled.",
            f"Already set (unchanged): {already_set_count} question(s).",
            f"Overwritten: {overwritten_count} question(s) had a different answer, now replaced.",
        ]
        if recovered:
            preview = ", ".join(recovered[:15])
            if len(recovered) > 15:
                preview += f", and {len(recovered) - 15} more"
            lines.append(
                f"\n{len(recovered)} answer(s) were filled using a question number read from the "
                f"detected number box (auto-detected regions whose label had no question number). "
                f"Please double-check these are correct: {preview}.")
        if missing:
            preview = ", ".join(missing[:15])
            if len(missing) > 15:
                preview += f", and {len(missing) - 15} more"
            lines.append(f"Still missing (not found in the answer scheme): {len(missing)} - {preview}.")
        if unlabelled:
            preview = ", ".join(unlabelled[:10])
            if len(unlabelled) > 10:
                preview += f", and {len(unlabelled) - 10} more"
            lines.append(
                f"\n{len(unlabelled)} answer box(es) could not be auto-filled because their labels "
                f"carry no question number or Kertas 2 Part - these are usually auto-detected "
                f"'ai_...' regions accepted from Detect Answer Regions. Auto-fill matches answers by "
                f"question number, which these labels do not have.\n"
                f"To set their answers: use the Edit button beside each entry in the Answer Key "
                f"table below to type the answer directly; or open the region in the editor and give "
                f"it a proper label (a question number, e.g. _q33_, or a Kertas 2 Part _q1_/_q2_/"
                f"part3) and run this again.\nAffected: {preview}."
            )
        if not missing and not unlabelled:
            lines.append("No questions are missing - every required question now has an answer key entry.")
        show_detail(self, "Fill Answer Key from Scheme", "\n".join(lines))

    def handle_save_subject_profile_editor(self) -> None:
        show_success(self, "Save Subject Profile", "Subject Profile saved successfully.")
        self.refresh_subject_profiles_table()

    def handle_back_from_subject_profile_editor(self) -> None:
        self._current_subject_profile = None
        self.shell.show_page("Marking")

    # --- Marking Editor -------------------------------------------------------

    def handle_open_marking_editor(self, row: dict) -> None:
        profile = getattr(self, "_selected_profile_for_marking", None)
        if profile is None:
            return
        self._marking_editor_profile = profile
        self._marking_editor_answer_file_id = row["answer_file_id"]
        self._marking_editor_page_index = 1
        self.marking_editor_title_label.setText(f"Marking Editor - {row['display_name']}")
        self._load_marking_editor_page_paths()
        self.refresh_marking_editor()
        self.shell.show_page("Marking Editor")

    def _load_marking_editor_page_paths(self) -> None:
        """Stage 11W: prefer each page's ORIGINAL (un-degraded) rendered
        image for the Marking Editor preview - falls back to the CLAHE/
        denoise/threshold-processed image for any page preprocessed before
        original_image_path existed.

        Stage 11Y-Fix: student marking/extraction no longer renders every
        page up front (it crops answer regions directly from the PDF), so
        this preview's full-page images may not exist yet the first time a
        teacher opens the Marking Editor for a given student - lazily
        render them here, once, on demand (see
        ensure_full_page_render_for_answer_file), deliberately outside the
        extraction timing log since this is a preview cost, not extraction."""
        conn = get_connection()
        try:
            # Stage 12G-1B: a Separate Answer Paper attempt's pages ARE the
            # uploaded answer paper - the Subject Profile question paper is
            # not involved, so the standard full-page render is skipped.
            if separate_paper_service.is_separate_mode(conn, self._marking_editor_answer_file_id):
                separate_pages = separate_model.get_separate_pages(
                    conn, self._marking_editor_answer_file_id)
                if not any(p.preview_image_path for p in separate_pages):
                    separate_paper_service.render_page_previews(
                        conn, self._teacher_id, self._marking_editor_profile.profile_id,
                        self._marking_editor_answer_file_id)
                    separate_pages = separate_model.get_separate_pages(
                        conn, self._marking_editor_answer_file_id)
                self._marking_editor_page_paths = [
                    p.preview_image_path for p in separate_pages if p.preview_image_path]
                return
            ensure_full_page_render_for_answer_file(conn, self._teacher_id, self._marking_editor_answer_file_id)
            pages = get_preprocessed_pages_for_answer_file(conn, self._marking_editor_answer_file_id)
        finally:
            conn.close()
        self._marking_editor_page_paths = [
            (p.original_image_path or p.preprocessed_image_path)
            for p in sorted(pages, key=lambda p: p.page_number)
            if (p.original_image_path or p.preprocessed_image_path)
        ]

    def refresh_marking_editor(self) -> None:
        if self._marking_editor_answer_file_id is None:
            return
        paths = self._marking_editor_page_paths
        if not paths:
            return
        index = max(0, min(self._marking_editor_page_index - 1, len(paths) - 1))
        self._marking_editor_page_index = index + 1
        image = render_page_image(paths[index], page_index=0)
        if not image.isNull():
            self.marking_editor_canvas.load_image(image)
        self.marking_editor_page_label.setText(f"Page {self._marking_editor_page_index} of {len(paths)}")
        self.marking_editor_prev_page_button.setEnabled(self._marking_editor_page_index > 1)
        self.marking_editor_next_page_button.setEnabled(self._marking_editor_page_index < len(paths))

        conn = get_connection()
        try:
            profile_id = self._marking_editor_profile.profile_id
            regions = list_subject_profile_regions(conn, self._teacher_id, profile_id, SOURCE_QUESTION_PAPER)
            groups = list_subject_profile_region_groups(conn, self._teacher_id, profile_id)
            extracted = get_extracted_answers_for_answer_file_ui(conn, self._marking_editor_answer_file_id)
            marked = get_marked_answers_for_answer_file_ui(conn, self._marking_editor_answer_file_id)
            overlays = list_subject_profile_overlays(conn, self._marking_editor_answer_file_id)
        finally:
            conn.close()

        # --- Regions section ---
        page_regions = [r for r in regions if r.page_number == self._marking_editor_page_index]
        self.marking_editor_regions_table.setRowCount(len(page_regions))
        for row_index, region in enumerate(page_regions):
            self.marking_editor_regions_table.setItem(row_index, 0, QTableWidgetItem(region.label))
            self.marking_editor_regions_table.setItem(row_index, 1, QTableWidgetItem(region_type_friendly_label(region.region_type)))
            self.marking_editor_regions_table.setItem(row_index, 2, QTableWidgetItem(str(region.page_number)))

        # --- Region Groups section ---
        self.marking_editor_groups_table.setRowCount(len(groups))
        for row_index, group in enumerate(groups):
            self.marking_editor_groups_table.setItem(row_index, 0, QTableWidgetItem(group.label))
            self.marking_editor_groups_table.setItem(row_index, 1, QTableWidgetItem(region_type_friendly_label(group.region_type)))

        # --- Extracted Content section ---
        extracted_lines = [f"{e.target_label}: {e.extracted_text or '(none)'}" for e in extracted]
        self.marking_editor_extracted_view.setPlainText("\n".join(extracted_lines))

        # --- Marking / Comment section (empty until Mark Answers clicked) ---
        # Stage 12G-1A: show the EFFECTIVE (teacher-corrected where present,
        # else machine) answer/status/score, plus a "Review / Correct" action
        # per row that opens the full teacher review editor.
        # Stage 12G-6: the AI Draft column shows the Core AI 1 SUGGESTION beside
        # (never inside) the teacher's own Score column, and says so plainly.
        draft_views = self._core_ai1_draft_views(self._marking_editor_answer_file_id)
        self.marking_editor_comment_table.setRowCount(len(marked))
        self._marking_editor_row_marked_ids = [m.marked_answer_id for m in marked]
        for row_index, item in enumerate(marked):
            eff_answer = item.effective_answer_text or "(none)"
            eff_status = self._effective_status_display(item)
            eff_score = item.effective_score
            score_text = f"{eff_score:g}/{item.max_score:g}" if eff_score is not None else "Pending"
            comment = item.teacher_feedback or item.feedback or ""
            corrected_marker = " *" if item.corrected_answer_text is not None else ""
            view = draft_views.get(item.marked_answer_id)
            draft_text = view["display"] if view else ("-" if item.region_type != "answer_box"
                                                       else "Not generated")
            values = [
                item.target_label, f"{eff_answer}{corrected_marker}", item.correct_answer_text or "(none)",
                score_text, draft_text, comment, eff_status,
            ]
            for col_index, value in enumerate(values):
                self.marking_editor_comment_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self.marking_editor_comment_table.setCellWidget(
                row_index, 7, self._build_review_action_cell(item)
            )
        self._refresh_core_ai1_draft_controls()

        # --- Overlay Marks section + canvas (Phase 2B editable workspace) ---
        # Canvas: draw the CURRENT page's overlays using each one's EFFECTIVE
        # symbol (teacher override wins; hidden overlays are not drawn).
        self._suppress_selection_sync = True
        self.marking_editor_canvas.clear_overlays()
        self._marking_editor_overlay_by_id = {}
        editing_locked = self._overlay_editing_locked(answer_file_id=self._marking_editor_answer_file_id)
        for overlay in overlays:
            if overlay.page_number != self._marking_editor_page_index:
                continue
            resolved = effective_overlay_kind_text(overlay)
            if resolved is None:
                continue  # hidden - not shown on the preview
            draw_kind, draw_text = resolved
            item = self.marking_editor_canvas.add_overlay(
                overlay.overlay_id, draw_kind, overlay.x, overlay.y, overlay.width, overlay.height,
                overlay.rotation_angle, draw_text,
                on_change=(None if editing_locked else self.handle_overlay_dragged),
                font_size=overlay.font_size,
            )
            self._marking_editor_overlay_by_id[overlay.overlay_id] = item
        self._suppress_selection_sync = False
        # Restore the previously selected overlay so dragging a note (which
        # persists and rebuilds the overlays) keeps it selected - required for
        # the feedback-font control to stay active on the selected note.
        _sel_id = getattr(self, "_marking_editor_selected_overlay_id", None)
        if _sel_id is not None and _sel_id in self._marking_editor_overlay_by_id:
            self._marking_editor_overlay_by_id[_sel_id].setSelected(True)
        self._sync_feedback_font_control()

        # Table: one row per real logical answer target (all pages).
        try:
            edit_rows = review_service.list_overlay_edit_rows(
                get_connection_for_rows := get_connection(), self._teacher_id,
                self._marking_editor_profile.profile_id, self._marking_editor_answer_file_id,
            )
        finally:
            get_connection_for_rows.close()
        self._marking_editor_overlay_row_ids = [r.overlay_id for r in edit_rows]
        self.marking_editor_overlay_table.setRowCount(len(edit_rows))
        for row_index, r in enumerate(edit_rows):
            cells = [
                r.paper, r.answer_label, str(r.page_number), r.status_display, r.symbol_display,
                f"{r.x:.3f}", f"{r.y:.3f}", ("Hidden" if r.hidden else "Visible"),
                ("Yes" if r.teacher_adjusted else "-"),
            ]
            for col, text in enumerate(cells):
                self.marking_editor_overlay_table.setItem(row_index, col, QTableWidgetItem(text))

        self.overlay_edit_selected_button.setEnabled(not editing_locked)
        self.overlay_refresh_from_review_button.setEnabled(not editing_locked)
        if editing_locked:
            self.overlay_lock_hint.setText(
                "This attempt is finalised - overlay editing is locked. Use 'Reopen for Editing' "
                "in the Teacher Review panel to make changes.")
        else:
            self.overlay_lock_hint.setText(
                "Select an overlay row to highlight it on the page, then Edit Selected Overlay "
                "(or double-click). You can also drag a marker on the preview.")

        # --- Phase 2C: Region Review panel ---
        self._refresh_region_panel(editing_locked)

        # --- Stage 12G-1B: Separate Answer Paper mapping workspace ---
        self._refresh_sap_panel(editing_locked)

        # --- Stage 12G-1A: Teacher Review summary + action button states ---
        self._refresh_review_panel()

    def _refresh_region_panel(self, editing_locked: bool) -> None:
        try:
            conn = get_connection()
            rows = review_service.list_region_edit_rows(
                conn, self._teacher_id, self._marking_editor_profile.profile_id,
                self._marking_editor_answer_file_id)
        finally:
            conn.close()

        def _g(geom):
            if not geom:
                return "-"
            return f"{geom['x']:.3f}, {geom['y']:.3f}, {geom['width']:.3f}, {geom['height']:.3f}"

        self._marking_editor_region_row_labels = [r.target_label for r in rows]
        self.marking_editor_region_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            cells = [
                r.paper, r.answer_label, str(r.page_number),
                ("Yes" if r.has_override else "-"), _g(r.original_geometry), _g(r.effective_geometry),
                ("Reconfirm" if r.stale else "OK"),
            ]
            for col, text in enumerate(cells):
                self.marking_editor_region_table.setItem(row_index, col, QTableWidgetItem(text))
        for btn in (self.region_edit_button, self.region_rerun_ocr_button,
                    self.region_reconfirm_button, self.region_apply_profile_button):
            btn.setEnabled(not editing_locked)
        if editing_locked:
            self.region_lock_hint.setText(
                "This attempt is finalised - region editing is locked. Use 'Reopen for Editing' first.")
        else:
            self.region_lock_hint.setText(
                "Select a row, then Edit Region Override (numeric geometry with a live crop preview), "
                "Rerun OCR, or Reconfirm Review after an extraction change.")

    # --- Stage 12G-1A: teacher review workspace -----------------------------

    def _effective_status_display(self, item) -> str:
        """Human label for a marked answer's effective (teacher-reviewed
        where set, else machine) status."""
        eff = item.effective_status
        labels = {
            subject_profile_model.TEACHER_STATUS_CORRECT: "Correct",
            subject_profile_model.TEACHER_STATUS_WRONG: "Wrong",
            subject_profile_model.TEACHER_STATUS_NEEDS_REVIEW: "Needs Review",
            subject_profile_model.TEACHER_STATUS_TEACHER_SCORED: "Teacher Scored",
            subject_profile_model.TEACHER_STATUS_PENDING_TEACHER_SCORE: "Pending Teacher Score",
            subject_profile_model.MARKED_ANSWER_STATUS_MARKED: "Correct" if item.is_correct else "Wrong",
            subject_profile_model.MARKED_ANSWER_STATUS_NEEDS_REVIEW: "Needs Review",
            subject_profile_model.MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE: "Pending Teacher Score",
            subject_profile_model.MARKED_ANSWER_STATUS_MISSING_ANSWER_KEY: "Missing Answer Key",
            subject_profile_model.MARKED_ANSWER_STATUS_FAILED: "Detection Failed",
        }
        return labels.get(eff, str(eff))

    def _build_review_action_cell(self, item) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)
        review_button = QPushButton("Review / Correct")
        review_button.setObjectName("RowActionButton")
        review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        review_button.clicked.connect(
            lambda _checked=False, mid=item.marked_answer_id: self.handle_open_teacher_review(mid)
        )
        cell_layout.addWidget(review_button)
        return cell

    def _current_review_context(self):
        """Return (profile, answer_file_id) for the open attempt, or (None, None)."""
        profile = getattr(self, "_marking_editor_profile", None)
        answer_file_id = getattr(self, "_marking_editor_answer_file_id", None)
        return profile, answer_file_id

    def _selected_comment_marked_id(self) -> Optional[int]:
        row = self.marking_editor_comment_table.currentRow()
        ids = getattr(self, "_marking_editor_row_marked_ids", [])
        if 0 <= row < len(ids):
            return ids[row]
        return None

    # --- Core AI 1 draft scoring (Stage 12G-6) ------------------------------
    #
    # Drafts are SUGGESTIONS. Generating them writes no teacher score, feedback
    # or review state; applying one is an explicit per-answer action that fills
    # in the teacher's own (still editable) score. A stale draft - the answer or
    # the model changed since it was produced - can be viewed but not applied.
    # Generation always runs in a background worker.

    def _core_ai1_draft_views(self, answer_file_id) -> dict:
        if answer_file_id is None:
            return {}
        conn = get_connection()
        try:
            from app.services import ai_draft_scoring_service as drafting
            return drafting.list_draft_views(conn, answer_file_id)
        except Exception:
            # A draft is never required to review an attempt.
            return {}
        finally:
            conn.close()

    def _core_ai1_draft_worker_running(self) -> bool:
        worker = getattr(self, "_core_ai1_draft_worker", None)
        return worker is not None and worker.isRunning()

    def _selected_core_ai1_draft_view(self):
        marked_id = self._selected_comment_marked_id()
        if marked_id is None:
            return None, None
        views = self._core_ai1_draft_views(getattr(self, "_marking_editor_answer_file_id", None))
        return marked_id, views.get(marked_id)

    def _refresh_core_ai1_draft_controls(self) -> None:
        if not hasattr(self, "core_ai1_apply_draft_button"):
            return
        busy = self._core_ai1_draft_worker_running()
        finalised = self._review_is_finalised()
        marked_id, view = self._selected_core_ai1_draft_view()
        for attr in ("core_ai1_generate_drafts_button", "core_ai1_regenerate_draft_button"):
            getattr(self, attr).setEnabled(not busy and not finalised)
        # Feedback wording is likewise locked once the attempt is finalised.
        if hasattr(self, "feedback_generate_button"):
            self.feedback_generate_button.setEnabled(
                not finalised and not self._feedback_worker_running())
        self.core_ai1_view_draft_button.setEnabled(view is not None)
        self.core_ai1_dismiss_draft_button.setEnabled(view is not None)
        # Applying requires a completed, non-stale draft on an open attempt.
        self.core_ai1_apply_draft_button.setEnabled(
            bool(view and view["applicable"]) and not finalised and not busy)
        # Regenerating stays available precisely so a stale draft can be
        # refreshed; only a finalised attempt or a running job disables it.
        self.core_ai1_regenerate_draft_button.setEnabled(
            marked_id is not None and not finalised and not busy)
        self._refresh_stale_banner(view)

    def _refresh_stale_banner(self, view) -> None:
        """Show, in full, why the selected answer's draft is out of date."""
        banner = getattr(self, "core_ai1_stale_banner", None)
        if banner is None:
            return
        if not view or not view.get("stale"):
            banner.setVisible(False)
            banner.setText("")
            return
        reason = view.get("stale_reason") or "its inputs changed"
        banner.setText(
            f"STALE DRAFT - this suggestion is out of date because {reason}. "
            "Apply Draft to My Score is disabled until you regenerate it. "
            "Your own score, category and feedback are unchanged.")
        banner.setVisible(True)

    def _review_is_finalised(self) -> bool:
        _, answer_file_id = self._current_review_context()
        if answer_file_id is None:
            return False
        conn = get_connection()
        try:
            review = subject_profile_model.get_attempt_review(conn, answer_file_id)
        finally:
            conn.close()
        return review is not None and review.review_state == subject_profile_model.REVIEW_STATE_FINALISED

    def _start_core_ai1_draft_worker(self, marked_answer_id=None) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        if self._core_ai1_draft_worker_running():
            show_error(self, "AI Drafts Busy", "Draft generation is already running.")
            return
        self.core_ai1_draft_status_label.setText(
            "Generating AI score suggestions in the background. Marking stays available.")
        dialog, widget = self._show_progress_dialog("Suggesting Scores")
        widget.set_progress("Scoring the Kertas 2 answers with the local model...", 0, 1)
        self._core_ai1_draft_progress_dialog = dialog
        worker = CoreAI1DraftWorker(self._teacher_id, profile.profile_id, answer_file_id,
                                    marked_answer_id)
        worker.succeeded.connect(self.handle_core_ai1_drafts_ready)
        worker.failed.connect(self.handle_core_ai1_drafts_failed)
        # The reference is released only on finished: the result signals are
        # emitted while run() is still unwinding, and dropping the last Python
        # reference there destroys a live QThread (hard crash).
        worker.finished.connect(self._on_core_ai1_draft_worker_finished)
        self._core_ai1_draft_worker = worker
        self._refresh_core_ai1_draft_controls()
        worker.start()

    def _on_core_ai1_draft_worker_finished(self) -> None:
        dialog = getattr(self, "_core_ai1_draft_progress_dialog", None)
        self._core_ai1_draft_progress_dialog = None
        if dialog is not None:
            dialog.close()
        worker = getattr(self, "_core_ai1_draft_worker", None)
        self._core_ai1_draft_worker = None
        if worker is not None:
            worker.deleteLater()
        self._refresh_core_ai1_draft_controls()

    def handle_generate_core_ai1_drafts(self) -> None:
        self._start_core_ai1_draft_worker()

    def handle_regenerate_core_ai1_draft(self) -> None:
        marked_id = self._selected_comment_marked_id()
        if marked_id is None:
            show_error(self, "No Answer Selected",
                       "Select a Kertas 2 writing answer row first.")
            return
        self._start_core_ai1_draft_worker(marked_id)

    def handle_core_ai1_drafts_ready(self, summary: dict) -> None:
        self.refresh_marking_editor()
        parts = [f"{summary.get('completed', 0)} draft suggestion(s)"]
        for key, label in (("attention_required", "need your attention"),
                           ("skipped", "skipped (already scored by you)"),
                           ("failed", "unavailable"), ("stale", "out of date")):
            if summary.get(key):
                parts.append(f"{summary[key]} {label}")
        self.core_ai1_draft_status_label.setText(
            ", ".join(parts) + ". These are suggestions - your score and feedback stay yours.")

    def handle_core_ai1_drafts_failed(self, message: str) -> None:
        # Stage 12G-9: the raw failure never reaches the teacher - it can carry
        # a path, a prompt or answer text. describe_failure yields safe wording
        # and always states that manual marking is unaffected.
        from app.services import ai_resilience_service as resilience
        self._refresh_core_ai1_draft_controls()
        self.core_ai1_draft_status_label.setText(
            "AI score suggestions are unavailable. " + resilience.describe_failure(message))

    def handle_view_core_ai1_draft(self) -> None:
        marked_id = self._selected_comment_marked_id()
        if marked_id is None:
            show_error(self, "No Answer Selected", "Select an answer row first.")
            return
        conn = get_connection()
        try:
            from app.services import ai_draft_scoring_service as drafting
            marked = subject_profile_model.get_marked_answer_by_id(conn, marked_id)
            if marked is None:
                return
            lines = drafting.draft_detail_lines(conn, marked)
        finally:
            conn.close()
        show_detail(self, f"AI Score Suggestion - {marked.target_label}", "\n".join(lines))

    def handle_apply_core_ai1_draft(self) -> None:
        profile, answer_file_id = self._current_review_context()
        marked_id, view = self._selected_core_ai1_draft_view()
        if profile is None or marked_id is None or view is None:
            show_error(self, "No Draft Selected",
                       "Select an answer row that has a Core AI 1 draft.")
            return
        record = view["record"]
        if not prompt_confirm(
            self, "Apply AI Draft",
            f"Copy the draft score {record.draft_score:g} and category "
            f"'{record.draft_feedback_category or '-'}' into YOUR review for this answer? "
            "You can still edit both afterwards, and nothing is shown to the student until you "
            "finalise the attempt.", confirm_text="Apply to my score"):
            return
        conn = get_connection()
        try:
            from app.services import ai_draft_scoring_service as drafting
            drafting.apply_draft(conn, self._teacher_id, profile.profile_id, answer_file_id,
                                 marked_id)
        except ValueError as exc:
            show_error(self, "Apply Draft Failed", str(exc))
            return
        finally:
            conn.close()
        self._regenerate_marking_overlays()
        self.refresh_marking_editor()
        show_success(self, "Draft Applied",
                     "The suggestion was copied into your review. It is your score now - edit it "
                     "freely before finalising.")

    def handle_dismiss_core_ai1_draft(self) -> None:
        marked_id = self._selected_comment_marked_id()
        if marked_id is None:
            show_error(self, "No Answer Selected", "Select an answer row first.")
            return
        conn = get_connection()
        try:
            from app.services import ai_draft_scoring_service as drafting
            drafting.dismiss_draft(conn, marked_id)
        except ValueError as exc:
            show_error(self, "Dismiss Draft Failed", str(exc))
            return
        finally:
            conn.close()
        self.refresh_marking_editor()

    # --- Kertas 2 natural-language feedback wording (Stage 12G-8) -----------
    #
    # Wording only. The draft carries no score, is never saved automatically,
    # and falls back to the built-in offline templates whenever the teacher's
    # local runtime is absent or unavailable - so this control always works.

    def _feedback_worker_running(self) -> bool:
        worker = getattr(self, "_feedback_worker", None)
        return worker is not None and worker.isRunning()

    def handle_generate_feedback_wording(self) -> None:
        profile, answer_file_id = self._current_review_context()
        marked_id = self._selected_comment_marked_id()
        if profile is None or answer_file_id is None:
            return
        if marked_id is None:
            show_error(self, "No Answer Selected",
                       "Select a Kertas 2 writing answer row first.")
            return
        if self._review_is_finalised():
            show_error(self, "Attempt Finalised",
                       "Reopen this attempt before changing its feedback.")
            return
        if self._feedback_worker_running():
            show_error(self, "Feedback Busy", "Feedback drafting is already running.")
            return
        conn = get_connection()
        try:
            from app.services import ai_feedback_generation_service as feedback
            availability = feedback.describe_feedback_availability(conn, self._teacher_id)
        finally:
            conn.close()
        self.core_ai1_draft_status_label.setText(
            f"Drafting feedback wording in the background. {availability['message']}")
        dialog, widget = self._show_progress_dialog("Writing Feedback")
        widget.set_progress("Writing feedback with your local runtime...", 0, 1)
        self._feedback_progress_dialog = dialog
        worker = Kertas2FeedbackWorker(self._teacher_id, answer_file_id, marked_id)
        worker.succeeded.connect(self.handle_feedback_wording_ready)
        worker.failed.connect(self.handle_feedback_wording_failed)
        # Released only on finished - see _on_core_ai1_draft_worker_finished.
        worker.finished.connect(self._on_feedback_worker_finished)
        self._feedback_worker = worker
        worker.start()

    def _on_feedback_worker_finished(self) -> None:
        dialog = getattr(self, "_feedback_progress_dialog", None)
        self._feedback_progress_dialog = None
        if dialog is not None:
            dialog.close()
        worker = getattr(self, "_feedback_worker", None)
        self._feedback_worker = None
        if worker is not None:
            worker.deleteLater()

    def handle_feedback_wording_ready(self, drafts: dict) -> None:
        profile, answer_file_id = self._current_review_context()
        if not drafts or profile is None:
            self.core_ai1_draft_status_label.setText("No feedback wording was produced.")
            return
        marked_id, draft = next(iter(drafts.items()))
        # The teacher reads the wording and its provenance, then chooses whether
        # to save it. Nothing is written unless they confirm.
        body = draft["text"] + "\n\n" + "\n".join(draft["lines"])
        if not prompt_confirm(self, "Draft Feedback Wording",
                              body + "\n\nSave this as your feedback for this answer? You can "
                              "edit it afterwards.", confirm_text="Save as my feedback"):
            self.core_ai1_draft_status_label.setText(
                f"Feedback wording drafted from {draft['source_label']} and discarded.")
            return
        conn = get_connection()
        try:
            from app.services import ai_feedback_generation_service as feedback
            feedback.apply_feedback_draft(conn, self._teacher_id, profile.profile_id, marked_id,
                                          draft["text"])
        except ValueError as exc:
            show_error(self, "Save Feedback Failed", str(exc))
            return
        finally:
            conn.close()
        # Regenerate overlays so the new feedback appears as a red note on the
        # page preview (and in any regenerated marked PDF) right away.
        self._regenerate_marking_overlays()
        self.refresh_marking_editor()
        self.core_ai1_draft_status_label.setText(
            f"Feedback wording saved from {draft['source_label']}. It is your feedback now - edit "
            "it freely before finalising.")

    def handle_feedback_wording_failed(self, message: str) -> None:
        from app.services import ai_resilience_service as resilience
        self._refresh_core_ai1_draft_controls()
        self.core_ai1_draft_status_label.setText(
            "Feedback wording could not be drafted. "
            + resilience.describe_failure(message, include_manual_note=False)
            + " Writing feedback yourself is unaffected.")

    def handle_review_selected_answer(self) -> None:
        """Stage 12G-1A: primary, always-visible entry point to the answer
        editor - opens the review dialog for the selected comment row."""
        marked_id = self._selected_comment_marked_id()
        if marked_id is None:
            show_error(self, "No Answer Selected", "Select an answer row in the Marking / Comment table first.")
            return
        self.handle_open_teacher_review(marked_id)

    def handle_comment_row_double_clicked(self, row: int, _column: int) -> None:
        ids = getattr(self, "_marking_editor_row_marked_ids", [])
        if 0 <= row < len(ids):
            self.handle_open_teacher_review(ids[row])

    def handle_open_teacher_review(self, marked_answer_id: int) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            marked = subject_profile_model.get_marked_answer_by_id(conn, marked_answer_id)
            if marked is None:
                return
            review = subject_profile_model.get_attempt_review(conn, answer_file_id)
            is_finalised = review is not None and review.review_state == subject_profile_model.REVIEW_STATE_FINALISED
            all_categories = subject_profile_model.list_feedback_categories(conn, active_only=False)
            selected = set(subject_profile_model.get_answer_feedback_category_ids(conn, marked_answer_id))
        finally:
            conn.close()

        # Active categories are always offered; an inactive category only
        # appears (disabled) when this answer already has it selected, so
        # historical selections stay visible but no new inactive pick is made.
        categories = [
            c for c in all_categories if c.is_active or c.category_id in selected
        ]

        is_box = marked.region_type == REGION_TYPE_ANSWER_BOX
        is_part3 = review_service._is_part3_answer_box(marked.region_type, marked.target_label)
        initial = {
            "is_answer_box": is_box,
            "is_part3": is_part3,
            "part3_machine_number": marked.extracted_selected_question_number,
            "part3_teacher_number": marked.teacher_selected_question_number,
            "part3_valid_choices": list(review_service.PART3_VALID_QUESTION_NUMBERS),
            "detected": marked.student_answer_text,
            "expected": marked.correct_answer_text,
            "automated_status": self._effective_status_display(
                subject_profile_model.SubjectProfileMarkedAnswer(
                    **{**marked.__dict__, "teacher_status": None})
            ),
            "automated_score_display": (f"{marked.score:g}/{marked.max_score:g}" if marked.score is not None else "Pending"),
            "max_score": marked.max_score,
            "raw_ocr": marked.raw_ocr_text if marked.raw_ocr_text is not None else marked.student_answer_text,
            "corrected_text": marked.corrected_answer_text,
            "teacher_status": marked.teacher_status,
            "teacher_score": marked.teacher_score,
            "teacher_feedback": marked.teacher_feedback,
            "private_comment": marked.private_comment,
            "categories": [
                (c.category_id, c.label if c.is_active else f"{c.label} (inactive)",
                 c.category_id in selected, bool(c.is_active))
                for c in categories
            ],
            "extraction_method": marked.extraction_method,
            "extraction_confidence": marked.extraction_confidence,
            "extraction_timestamp": marked.extraction_timestamp,
        }
        result = prompt_teacher_review(self, f"Review / Correct - {marked.target_label}", initial, read_only=is_finalised)
        if result is None:
            return

        conn = get_connection()
        try:
            try:
                review_service.save_corrected_answer_text(
                    conn, self._teacher_id, profile.profile_id, marked_answer_id,
                    result["corrected_text"] or None,
                )
                if result["is_answer_box"]:
                    if not result.get("leave_pending"):
                        review_service.set_kertas2_teacher_score(
                            conn, self._teacher_id, profile.profile_id, marked_answer_id, result["teacher_score"]
                        )
                    if result.get("is_part3"):
                        # None clears the teacher choice (reverts to machine);
                        # a value is validated against the valid Part 3 set.
                        review_service.set_part3_selected_question_number(
                            conn, self._teacher_id, profile.profile_id, marked_answer_id,
                            result.get("selected_question_number"),
                        )
                else:
                    review_service.set_kertas1_teacher_status(
                        conn, self._teacher_id, profile.profile_id, marked_answer_id, result["teacher_status"]
                    )
                review_service.set_teacher_feedback(
                    conn, self._teacher_id, profile.profile_id, marked_answer_id,
                    teacher_feedback=result["teacher_feedback"] or None,
                    private_comment=result["private_comment"] or None,
                )
                review_service.set_answer_feedback_categories(
                    conn, self._teacher_id, profile.profile_id, marked_answer_id, result["category_ids"]
                )
            except ValueError as exc:
                show_error(self, "Save Correction Failed", str(exc))
                return
        finally:
            conn.close()
        # Real-time red marks: the tick/cross/score/"?" markers follow the
        # effective status immediately, not only at finalisation - so the
        # preview always shows what the student's final PDF will contain.
        self._regenerate_marking_overlays()
        self.refresh_marking_editor()
        show_success(self, "Correction Saved", "The teacher review for this answer was saved.")

    def _regenerate_marking_overlays(self) -> None:
        """Rebuild this attempt's overlay markers from the effective
        (teacher-reviewed) status right away, preserving manual moves and
        hidden flags - keeps the editor preview and any regenerated final
        PDF in lockstep with the teacher's latest marking."""
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            try:
                review_service.regenerate_overlays_from_review(
                    conn, self._teacher_id, profile.profile_id, answer_file_id)
            except ValueError:
                # e.g. finalised (locked) attempt - the stored final overlays
                # are authoritative until the teacher reopens it.
                pass
        finally:
            conn.close()

    def _refresh_review_panel(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            summary = review_service.get_review_summary(conn, self._teacher_id, profile.profile_id, answer_file_id)
            review = subject_profile_model.get_attempt_review(conn, answer_file_id)
            stale_targets = review_service.list_stale_extraction_targets(
                conn, self._teacher_id, profile.profile_id, answer_file_id)
            from app.services import ai_draft_scoring_service as drafting
            draft_summary = drafting.summarize_attempt_drafts(conn, answer_file_id)
            separate = separate_paper_service.is_separate_mode(conn, answer_file_id)
            separate_blockers = (
                separate_paper_service.get_separate_mode_blockers(
                    conn, self._teacher_id, profile.profile_id, answer_file_id)
                if separate else [])
        finally:
            conn.close()
        state = review.review_state if review else subject_profile_model.REVIEW_STATE_DRAFT
        state_label = {"draft": "Draft", "needs_review": "Needs Review", "finalised": "Finalised"}.get(state, state)
        # Phase 2C: extraction-change staleness warning (K1/K2 reviews needing
        # reconfirmation after a region override / rerun OCR changed input).
        stale_text = (
            "None" if not stale_targets
            else f"<span style='color:#c0392b'>{len(stale_targets)} target(s) need reconfirmation</span>"
        )
        # Stage 12G-6: draft suggestions are counted separately from the
        # teacher's own review progress - they never advance it.
        if not draft_summary["total"]:
            draft_text = "None generated"
        else:
            draft_text = f"{draft_summary['completed']} suggestion(s), {draft_summary['applied']} applied"
            if draft_summary["stale"]:
                draft_text += (f" - <span style='color:#c0392b'>{draft_summary['stale']} out of "
                               "date</span>")
            if draft_summary["attention_required"]:
                draft_text += f", {draft_summary['attention_required']} need attention"

        # Stage 12G-1A: readable labelled rows (HTML two-column table) with
        # real Part 1/2/3 - Question labels; never the generic word "answer".
        def _score_cell(label, value, maxv):
            shown = f"{value:g}/{maxv:g}" if value is not None else "Pending"
            return f"<tr><td style='padding-right:14px'>{label}</td><td>{shown}</td></tr>"

        k2_rows = "".join(
            _score_cell(summary.kertas2_part_labels.get(lbl, lbl), v, summary.kertas2_part_max.get(lbl, 20.0))
            for lbl, v in summary.kertas2_part_scores.items()
        ) or "<tr><td colspan='2'>(no Kertas 2 answers)</td></tr>"
        missing = summary.missing_required_fields
        missing_text = "None" if missing == 0 else f"{missing} unresolved"
        part3_text = (
            "Confirmed" if summary.part3_question_confirmed
            else "<span style='color:#c0392b'>Needs Confirmation</span>"
        )

        # Stage 12G-1B: the attempt mode is always visible in the review panel,
        # together with any mapping work still blocking finalisation.
        mode_text = "Separate Answer Paper" if separate else "Standard (answers on the question paper)"
        mapping_row = ""
        if separate:
            mapping_row = (
                "<tr><td style='padding-right:14px'>Mapping</td><td>"
                + ("Complete" if not separate_blockers
                   else f"<span style='color:#c0392b'>{len(separate_blockers)} item(s) outstanding</span>")
                + "</td></tr>"
            )

        self.review_summary_label.setText(
            "<table style='border-spacing:0'>"
            f"<tr><td style='padding-right:14px'><b>Attempt mode</b></td><td>{mode_text}</td></tr>"
            f"{mapping_row}"
            f"<tr><td style='padding-right:14px'><b>Review state</b></td><td>{state_label}</td></tr>"
            f"<tr><td style='padding-right:14px'>Reviewer</td><td>{summary.reviewer_id or '-'}</td></tr>"
            f"<tr><td style='padding-right:14px'>Last saved</td><td>{summary.last_saved_at or '-'}</td></tr>"
            f"<tr><td style='padding-right:14px'>Kertas 1</td><td>{summary.kertas1_display}</td></tr>"
            f"{k2_rows}"
            f"<tr><td style='padding-right:14px'>Kertas 2 total</td><td>{summary.kertas2_display}</td></tr>"
            f"<tr><td style='padding-right:14px'>Part 3 selection</td><td>{part3_text}</td></tr>"
            f"<tr><td style='padding-right:14px'><b>Final result</b></td><td><b>{summary.final_display}</b></td></tr>"
            f"<tr><td style='padding-right:14px'>Needs Review</td><td>{summary.needs_review_count}</td></tr>"
            f"<tr><td style='padding-right:14px'>Pending Teacher Score</td><td>{summary.pending_teacher_score_count}</td></tr>"
            f"<tr><td style='padding-right:14px'>Missing required fields</td><td>{missing_text}</td></tr>"
            f"<tr><td style='padding-right:14px'>Extraction changes</td><td>{stale_text}</td></tr>"
            f"<tr><td style='padding-right:14px'>AI drafts (suggestions)</td><td>{draft_text}</td></tr>"
            "</table>"
        )
        is_finalised = state == subject_profile_model.REVIEW_STATE_FINALISED
        self.review_save_draft_button.setEnabled(not is_finalised)
        self.review_finalise_button.setEnabled(not is_finalised)
        self.review_reopen_button.setEnabled(is_finalised)
        if hasattr(self, "review_selected_button"):
            self.review_selected_button.setEnabled(True)

    def handle_save_review_draft(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            try:
                review_service.save_attempt_review_draft(conn, self._teacher_id, profile.profile_id, answer_file_id)
            except ValueError as exc:
                show_error(self, "Save Draft Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Draft Saved", "The review draft was saved. It is not shown to the student as final yet.")

    def handle_finalise_review(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            blockers = review_service.get_finalisation_blockers(conn, self._teacher_id, profile.profile_id, answer_file_id)
        finally:
            conn.close()
        if blockers:
            show_error(self, "Cannot Finalise", "Resolve these first:\n" + "\n".join(blockers))
            return
        if not prompt_confirm(
            self, "Finalise Marking",
            "Finalise this reviewed result? It becomes the student-visible final result and is locked "
            "until you reopen it for editing.", confirm_text="Finalise",
        ):
            return
        conn = get_connection()
        try:
            try:
                review_service.finalise_attempt_review(conn, self._teacher_id, profile.profile_id, answer_file_id)
            except ValueError as exc:
                show_error(self, "Finalise Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_main_marking_results_table()
        self.refresh_results_table()
        # Stage 12G-11: once the attempt is finalised, feed the teacher's own
        # decisions back for future training. This runs AFTER finalisation has
        # already succeeded, so it can never undo it - a capture failure is
        # reported as a note and no teacher decision is erased.
        capture_note = self._capture_review_decisions(profile, answer_file_id)
        self.refresh_marking_editor()
        self.refresh_student_results_table()
        show_success(self, "Marking Finalised",
                     "The reviewed result was finalised and outputs regenerated." + capture_note)

    def _capture_review_decisions(self, profile, answer_file_id) -> str:
        """Capture the Core AI 1 and Core AI 2 review decisions for this
        attempt. Returns a short note for the success message. Never raises -
        capture is a training convenience, never a marking requirement."""
        note_parts = []
        conn = get_connection()
        try:
            from app.services import ai_review_capture_service as capture
            version = f"attempt_{answer_file_id}_profile_{profile.profile_id}"
            core1 = capture.capture_core_ai1_reviews(conn, answer_file_id, version)
            core2 = capture.capture_core_ai2_reviews(conn, version, answer_file_id=answer_file_id)
            for outcome in (core1, core2):
                if outcome.ok and outcome.captured:
                    note_parts.append(
                        f"{outcome.captured} {outcome.family} decision(s) captured for training")
                elif not outcome.ok:
                    note_parts.append(f"{outcome.family} review capture was unavailable")
        except Exception:
            return "\n\nReview capture was unavailable. Your finalised result is unaffected."
        finally:
            conn.close()
        if not note_parts:
            return ""
        return "\n\n" + "; ".join(note_parts) + ". Your finalised result is unaffected."

    def handle_reopen_review(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        if not prompt_confirm(
            self, "Reopen for Editing",
            "Reopen this finalised result for editing? This is recorded in the review history.",
            confirm_text="Reopen",
        ):
            return
        conn = get_connection()
        try:
            try:
                review_service.reopen_attempt_review(conn, self._teacher_id, profile.profile_id, answer_file_id)
            except ValueError as exc:
                show_error(self, "Reopen Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        self.refresh_main_marking_results_table()
        self.refresh_results_table()
        show_success(self, "Reopened for Editing", "The result was reopened. Make your corrections, then finalise again.")

    def _build_teacher_score_entry_cell(self, marked_answer) -> QWidget:
        """Marking Fix Follow-up: score-entry widget for a Kertas 2 writing
        (answer_box) marked answer - a spin box pre-filled with its current
        score (0 if still Pending Teacher Score) plus a Save button wired to
        set_teacher_score_for_marked_answer. This is the only UI path that
        ever moves such a target from Pending Teacher Score to Teacher
        Scored (and therefore into the Kertas 2/final total)."""
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        spin_box = QDoubleSpinBox()
        spin_box.setRange(0.0, marked_answer.max_score)
        spin_box.setDecimals(1)
        spin_box.setValue(marked_answer.score if marked_answer.score is not None else 0.0)
        cell_layout.addWidget(spin_box)

        save_button = QPushButton("Save")
        save_button.setObjectName("RowActionButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.clicked.connect(
            lambda _checked=False, mid=marked_answer.marked_answer_id, box=spin_box: self.handle_save_teacher_score(mid, box.value())
        )
        cell_layout.addWidget(save_button)
        return cell

    def handle_save_teacher_score(self, marked_answer_id: int, score: float) -> None:
        profile = getattr(self, "_marking_editor_profile", None)
        if profile is None:
            return
        conn = get_connection()
        try:
            try:
                set_teacher_score_for_marked_answer(conn, self._teacher_id, profile.profile_id, marked_answer_id, score)
            except ValueError as exc:
                show_error(self, "Save Teacher Score Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        self.refresh_student_results_table()

    def _build_overlay_action_cell(self, overlay_id: int) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 2, 4, 2)
        cell_layout.setSpacing(4)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("RowActionButton")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_button.clicked.connect(lambda _checked=False, oid=overlay_id: self.handle_delete_overlay(oid))
        cell_layout.addWidget(delete_button)
        return cell

    def handle_overlay_transform_changed(self, item) -> None:
        """Persist an overlay's new position/size/rotation after a direct
        drag/resize/rotate gesture on the preview completes (mouse
        release) - see app/ui/overlay_canvas.py's OverlayMarkItem."""
        x, y, width, height, rotation = self.marking_editor_canvas.get_overlay_fractional_transform(item)
        conn = get_connection()
        try:
            move_subject_profile_overlay(conn, item.overlay_id, x, y)
            resize_subject_profile_overlay(conn, item.overlay_id, width, height)
            rotate_subject_profile_overlay(conn, item.overlay_id, rotation)
        finally:
            conn.close()

    # --- Phase 2B: editable overlay workspace --------------------------------

    def _overlay_editing_locked(self, answer_file_id) -> bool:
        """True when the attempt is finalised (overlay editing is locked until
        Reopen for Editing)."""
        if answer_file_id is None:
            return False
        conn = get_connection()
        try:
            review = subject_profile_model.get_attempt_review(conn, answer_file_id)
        finally:
            conn.close()
        return review is not None and review.review_state == subject_profile_model.REVIEW_STATE_FINALISED

    def _selected_overlay_id(self):
        row = self.marking_editor_overlay_table.currentRow()
        ids = getattr(self, "_marking_editor_overlay_row_ids", [])
        if 0 <= row < len(ids):
            return ids[row]
        return None

    def handle_overlay_row_selected(self) -> None:
        """Navigate the preview to the selected overlay's page and highlight it."""
        overlay_id = self._selected_overlay_id()
        if overlay_id is None:
            return
        conn = get_connection()
        try:
            overlay = subject_profile_model.get_overlay_by_id(conn, overlay_id)
        finally:
            conn.close()
        if overlay is None:
            return
        if overlay.page_number != self._marking_editor_page_index:
            self._marking_editor_page_index = overlay.page_number
            self.refresh_marking_editor()
        item = getattr(self, "_marking_editor_overlay_by_id", {}).get(overlay_id)
        if item is not None:
            self.marking_editor_canvas.scene().clearSelection()
            item.setSelected(True)
            self.marking_editor_canvas.centerOn(item)

    def handle_overlay_row_double_clicked(self, row: int, _column: int) -> None:
        ids = getattr(self, "_marking_editor_overlay_row_ids", [])
        if 0 <= row < len(ids):
            self.handle_open_overlay_editor(ids[row])

    def handle_edit_selected_overlay(self) -> None:
        overlay_id = self._selected_overlay_id()
        if overlay_id is None:
            show_error(self, "No Overlay Selected", "Select an overlay row in the Overlay Marks table first.")
            return
        self.handle_open_overlay_editor(overlay_id)

    def handle_open_overlay_editor(self, overlay_id: int) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        locked = self._overlay_editing_locked(answer_file_id)
        conn = get_connection()
        try:
            rows = review_service.list_overlay_edit_rows(conn, self._teacher_id, profile.profile_id, answer_file_id)
            overlay = subject_profile_model.get_overlay_by_id(conn, overlay_id)
        finally:
            conn.close()
        row = next((r for r in rows if r.overlay_id == overlay_id), None)
        if row is None or overlay is None:
            return
        initial = {
            "paper": row.paper, "answer_label": row.answer_label, "status_display": row.status_display,
            "auto_symbol_display": row.symbol_display, "is_kertas1": row.is_kertas1, "hidden": row.hidden,
            "x": overlay.x, "y": overlay.y,
            "original_x": overlay.original_x if overlay.original_x is not None else overlay.x,
            "original_y": overlay.original_y if overlay.original_y is not None else overlay.y,
        }
        result = prompt_overlay_editor(self, f"Edit Overlay - {row.paper} {row.answer_label}", initial, read_only=locked)
        if result is None:
            return

        target_label = overlay.target_label
        status_symbol = result.get("status_symbol")
        # A Tick/X/Question Mark choice changes the FINAL teacher status (with a
        # confirmation) - never a contradictory visual-only override.
        if status_symbol:
            change_label = review_service.status_symbol_change_label(status_symbol)
            if not prompt_confirm(
                self, "Change Final Marking Status",
                f"This changes the final marking status of {row.paper} {row.answer_label} to "
                f"{change_label}. The score, summary and finalisation checks update accordingly. Continue?",
                confirm_text="Change Status",
            ):
                return
        conn = get_connection()
        try:
            try:
                if status_symbol:
                    review_service.apply_overlay_status_symbol(
                        conn, self._teacher_id, profile.profile_id, overlay_id, status_symbol)
                    # Regeneration reassigns overlay ids; re-resolve this target.
                    overlay = next(
                        (o for o in subject_profile_model.get_overlays_for_answer_file(conn, answer_file_id)
                         if o.target_label == target_label), None)
                if overlay is not None:
                    review_service.set_overlay_visibility(conn, self._teacher_id, profile.profile_id, overlay.overlay_id, result["hidden"])
                    if (round(overlay.x, 3), round(overlay.y, 3)) != (result["x"], result["y"]):
                        review_service.move_overlay_position(conn, self._teacher_id, profile.profile_id, overlay.overlay_id, result["x"], result["y"])
            except ValueError as exc:
                show_error(self, "Overlay Update Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Overlay Updated", "The overlay mark was updated.")

    def handle_overlay_dragged(self, item) -> None:
        """Persist a drag on the preview as a teacher-adjusted position (Phase
        2B), rejecting an out-of-page drop rather than silently clamping."""
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        x, y, _w, _h, _r = self.marking_editor_canvas.get_overlay_fractional_transform(item)
        conn = get_connection()
        try:
            try:
                review_service.move_overlay_position(conn, self._teacher_id, profile.profile_id, item.overlay_id, x, y)
            except ValueError as exc:
                show_error(self, "Move Overlay Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()

    def _sync_feedback_font_control(self) -> None:
        """Remember the current canvas selection and reflect the feedback-font
        spinbox for the selected feedback note (disabled when no feedback note
        is selected or editing is locked). Skipped while overlays are being
        rebuilt so a programmatic clear doesn't wipe the remembered selection."""
        if getattr(self, "_suppress_selection_sync", False):
            return
        spin = getattr(self, "feedback_font_spin", None)
        if spin is None:
            return
        selected_id = None
        feedback_item = None
        try:
            for it in self.marking_editor_canvas.scene().selectedItems():
                oid = getattr(it, "overlay_id", None)
                if selected_id is None and oid is not None:
                    selected_id = oid
                if feedback_item is None and getattr(it, "kind", None) == "feedback":
                    feedback_item = it
        except Exception:
            pass
        # Persist the selection so refresh_marking_editor can restore it after a
        # drag rebuilds the overlays (otherwise the note would deselect on drop).
        self._marking_editor_selected_overlay_id = selected_id
        _profile, answer_file_id = self._current_review_context()
        locked = answer_file_id is not None and self._overlay_editing_locked(answer_file_id)
        spin.blockSignals(True)
        if feedback_item is None or locked:
            self._selected_feedback_overlay_id = None
            spin.setValue(0)
            spin.setEnabled(False)
        else:
            self._selected_feedback_overlay_id = feedback_item.overlay_id
            spin.setValue(int(feedback_item.font_size) if feedback_item.font_size else 0)
            spin.setEnabled(True)
        spin.blockSignals(False)

    def handle_feedback_font_changed(self, value: int) -> None:
        """Persist a manual font size (0 = Auto) for the selected feedback note
        and repaint it live on the preview."""
        overlay_id = getattr(self, "_selected_feedback_overlay_id", None)
        if overlay_id is None:
            return
        font_size = None if int(value) == 0 else int(value)
        conn = get_connection()
        try:
            subject_profile_model.set_overlay_font_size(conn, overlay_id, font_size)
        finally:
            conn.close()
        item = self._marking_editor_overlay_by_id.get(overlay_id)
        if item is not None:
            item.font_size = font_size
            item.update()

    def handle_refresh_overlays_from_review(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            would_change = review_service.overlay_symbols_would_change(conn, self._teacher_id, profile.profile_id, answer_file_id)
        finally:
            conn.close()
        if would_change and not prompt_confirm(
            self, "Refresh Overlays from Review",
            "Refreshing will update Auto-mode overlay symbols to match the current teacher-reviewed "
            "status. Teacher-adjusted positions, hidden markers and explicit symbol overrides are kept. Continue?",
            confirm_text="Refresh",
        ):
            return
        conn = get_connection()
        try:
            try:
                review_service.regenerate_overlays_from_review(conn, self._teacher_id, profile.profile_id, answer_file_id)
            except ValueError as exc:
                show_error(self, "Refresh Overlays Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Overlays Refreshed", "Auto-mode overlay symbols were refreshed from the teacher review.")

    def handle_regenerate_reviewed_outputs(self) -> None:
        profile, answer_file_id = self._current_review_context()
        if profile is None or answer_file_id is None:
            return
        conn = get_connection()
        try:
            review = subject_profile_model.get_attempt_review(conn, answer_file_id)
        finally:
            conn.close()
        is_finalised = review is not None and review.review_state == subject_profile_model.REVIEW_STATE_FINALISED
        self.overlay_regenerate_outputs_button.setEnabled(False)
        self._overlay_output_worker = OverlayOutputWorker(
            self._teacher_id, profile.profile_id, answer_file_id, is_finalised)
        self._overlay_output_worker.succeeded.connect(self._on_overlay_outputs_succeeded)
        self._overlay_output_worker.failed.connect(self._on_overlay_outputs_failed)
        self._overlay_output_worker.finished.connect(
            lambda: self.overlay_regenerate_outputs_button.setEnabled(True))
        self._overlay_output_worker.start()

    def _on_overlay_outputs_succeeded(self, payload: dict) -> None:
        self.refresh_marking_editor()
        self.refresh_student_results_table()
        if payload.get("is_final"):
            show_detail(self, "Final Outputs Regenerated",
                        f"The final reviewed marked PDF and comments were republished:\n{payload.get('folder')}")
        else:
            show_detail(self, "Draft Preview Generated",
                        "A teacher-only DRAFT preview was generated (NOT the student's final result):\n"
                        f"{payload.get('folder')}")

    def _on_overlay_outputs_failed(self, message: str) -> None:
        show_error(self, "Regenerate Outputs Failed", message)

    # --- Phase 2C: attempt-specific Region editor ----------------------------

    def _selected_region_label(self):
        row = self.marking_editor_region_table.currentRow()
        labels = getattr(self, "_marking_editor_region_row_labels", [])
        if 0 <= row < len(labels):
            return labels[row]
        return None

    def handle_region_row_double_clicked(self, row: int, _column: int) -> None:
        labels = getattr(self, "_marking_editor_region_row_labels", [])
        if 0 <= row < len(labels):
            self.handle_edit_region_override(labels[row])

    def handle_edit_selected_region(self) -> None:
        label = self._selected_region_label()
        if label is None:
            show_error(self, "No Region Selected", "Select a row in the Region Review table first.")
            return
        self.handle_edit_region_override(label)

    def handle_edit_region_override(self, label: str) -> None:
        import tempfile
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        locked = self._overlay_editing_locked(answer_file_id)
        crop_dir = Path(tempfile.mkdtemp(prefix="regioncrop_"))
        conn = get_connection()
        try:
            lineage = review_service.get_region_override_lineage(conn, self._teacher_id, profile.profile_id, answer_file_id, label)
            geom = review_service.get_region_geometry(conn, self._teacher_id, profile.profile_id, answer_file_id, label)
            orig_path = crop_dir / "original.png"
            eff_path = crop_dir / "effective.png"
            review_service.render_region_crop_to_file(conn, self._teacher_id, profile.profile_id, answer_file_id, label, use_override=False, out_path=str(orig_path))
            review_service.render_region_crop_to_file(conn, self._teacher_id, profile.profile_id, answer_file_id, label, use_override=True, out_path=str(eff_path))
        finally:
            conn.close()
        eff = geom.get("effective") or geom.get("original") or {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05}
        initial = {
            "paper": lineage["paper"], "answer_label": lineage["answer_label"],
            "page_number": self._region_page_for(label), "region_type": lineage.get("region_type"),
            "x": eff["x"], "y": eff["y"], "width": eff["width"], "height": eff["height"],
            "has_override": geom["has_override"], "stale": lineage["stale"],
            "original_crop_path": str(orig_path) if orig_path.exists() else None,
            "effective_crop_path": str(eff_path) if eff_path.exists() else None,
        }
        dialog = RegionOverrideDialog(self, f"Region Override - {lineage['paper']} {lineage['answer_label']}", initial, read_only=locked)

        def _on_preview(px, py, pw, ph):
            conn2 = get_connection()
            try:
                preview_path = crop_dir / "preview.png"
                review_service.render_region_crop_for_geometry(
                    conn2, self._teacher_id, profile.profile_id, answer_file_id, label,
                    x=px, y=py, width=pw, height=ph, out_path=str(preview_path))
                dialog.set_effective_crop(str(preview_path))
            except ValueError as exc:
                dialog.geometry_error_label.setText(str(exc))
            finally:
                conn2.close()

        dialog.preview_requested.connect(_on_preview)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.values()
        conn = get_connection()
        try:
            try:
                if result["action"] == "restore":
                    review_service.remove_region_override(conn, self._teacher_id, profile.profile_id, answer_file_id, label)
                else:
                    review_service.save_region_override(
                        conn, self._teacher_id, profile.profile_id, answer_file_id, label,
                        x=result["x"], y=result["y"], width=result["width"], height=result["height"],
                        correction_reason=result.get("correction_reason"))
            except ValueError as exc:
                show_error(self, "Region Override Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Region Override Saved",
                     "The attempt region override was updated. Rerun OCR and reconfirm the review if the extraction changed.")

    def _region_page_for(self, label: str) -> int:
        conn = get_connection()
        try:
            rows = review_service.list_region_edit_rows(conn, self._teacher_id, self._marking_editor_profile.profile_id, self._marking_editor_answer_file_id)
        finally:
            conn.close()
        r = next((r for r in rows if r.target_label == label), None)
        return r.page_number if r else 1

    def handle_reconfirm_region_review(self) -> None:
        label = self._selected_region_label()
        if label is None:
            show_error(self, "No Region Selected", "Select a row in the Region Review table first.")
            return
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            try:
                review_service.reconfirm_extraction_change(conn, self._teacher_id, profile.profile_id, answer_file_id, label)
            except ValueError as exc:
                show_error(self, "Reconfirm Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Review Reconfirmed", "The extraction change was reconfirmed; finalisation is no longer blocked for this target.")

    def handle_rerun_region_ocr(self) -> None:
        label = self._selected_region_label()
        if label is None:
            show_error(self, "No Region Selected", "Select a row in the Region Review table first.")
            return
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            has_override = review_service.get_region_geometry(conn, self._teacher_id, profile.profile_id, answer_file_id, label)["has_override"]
        finally:
            conn.close()
        if not has_override:
            show_error(self, "No Region Override", "Draw or adjust a region override first, then Rerun OCR on it.")
            return
        for btn in (self.region_rerun_ocr_button, self.region_edit_button):
            btn.setEnabled(False)
        self._region_ocr_worker = RegionOcrRerunWorker(self._teacher_id, profile.profile_id, answer_file_id, label)
        self._region_ocr_worker.succeeded.connect(self._on_region_ocr_succeeded)
        self._region_ocr_worker.failed.connect(self._on_region_ocr_failed)
        self._region_ocr_worker.finished.connect(lambda: [b.setEnabled(True) for b in (self.region_rerun_ocr_button, self.region_edit_button)])
        self._region_ocr_worker.start()

    def _on_region_ocr_succeeded(self, payload: dict) -> None:
        self.refresh_marking_editor()
        show_detail(self, "Rerun OCR Complete",
                    "Original OCR (from marking): {orig}\n\nRerun OCR (this override geometry): {rerun}\n\n"
                    "The rerun result is stored separately. Use Review / Correct to accept it as the corrected "
                    "text and reconfirm the score/status.".format(
                        orig=(payload.get("original_ocr") or "(none)"), rerun=(payload.get("rerun_ocr") or "(none)")))

    def _on_region_ocr_failed(self, message: str) -> None:
        show_error(self, "Rerun OCR Failed", message)

    def handle_apply_region_to_profile(self) -> None:
        label = self._selected_region_label()
        if label is None:
            show_error(self, "No Region Selected", "Select a row in the Region Review table first.")
            return
        profile, answer_file_id = self._current_review_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            geom = review_service.get_region_geometry(conn, self._teacher_id, profile.profile_id, answer_file_id, label)
        finally:
            conn.close()
        if not geom["has_override"]:
            show_error(self, "No Region Override", "There is no attempt override to apply for this target.")
            return
        o = geom["effective"]
        p = geom["original"]
        if not prompt_confirm(
            self, "Apply to Subject Profile",
            "Apply this attempt's region geometry to the SHARED Subject Profile (affects future attempts)?\n\n"
            f"Original (profile): x={p['x']:.3f}, y={p['y']:.3f}, w={p['width']:.3f}, h={p['height']:.3f}\n"
            f"Proposed (this attempt): x={o['x']:.3f}, y={o['y']:.3f}, w={o['width']:.3f}, h={o['height']:.3f}",
            confirm_text="Apply to Profile",
        ):
            return
        conn = get_connection()
        try:
            try:
                review_service.apply_region_override_to_profile(conn, self._teacher_id, profile.profile_id, answer_file_id, label, confirm=True)
            except ValueError as exc:
                show_error(self, "Apply to Profile Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()
        show_success(self, "Applied to Subject Profile", "The shared Subject Profile region geometry was updated for future attempts.")

    # --- Stage 12G-1B: Separate Answer Paper mapping workspace ---------------

    def _sap_context(self):
        profile, answer_file_id = self._current_review_context()
        return profile, answer_file_id

    def _reload_sap_workspace(self) -> None:
        """Refresh the mapping workspace and the review summary after a
        mapping change, keeping the teacher's selected target in place."""
        profile, af = self._sap_context()
        if profile is None or af is None:
            return
        # Real-time red marks (separate mode included): markers follow the
        # latest mapping/score/Part-3 state immediately.
        self._regenerate_marking_overlays()
        self._refresh_sap_panel(self._overlay_editing_locked(answer_file_id=af))
        self._refresh_review_panel()
        self.refresh_marking_editor()

    def _refresh_sap_panel(self, editing_locked: bool) -> None:
        profile, af = self._sap_context()
        if profile is None or af is None:
            return
        conn = get_connection()
        try:
            separate = separate_paper_service.is_separate_mode(conn, af)
            self.marking_editor_sap_section.setVisible(separate)
            # In separate mode the Subject Profile answer coordinates are not
            # used at all, so the profile-geometry panels are hidden rather
            # than left on screen showing irrelevant regions.
            for section in (self.marking_editor_regions_section, self.marking_editor_groups_section,
                            self.marking_editor_region_section):
                section.setVisible(not separate)
            if not separate:
                return
            # Open the workspace the first time a separate attempt is loaded -
            # in this mode it is the main thing the teacher has to do - but
            # respect a later manual collapse.
            if getattr(self, "_sap_expanded_for", None) != af:
                self._sap_expanded_for = af
                self.marking_editor_sap_section.set_expanded(True)
            pages = separate_model.get_separate_pages(conn, af)
            targets = separate_paper_service.list_required_targets(conn, self._teacher_id, profile.profile_id, af)
            counts = separate_paper_service.target_summary(conn, self._teacher_id, profile.profile_id, af)
            has_mappings = bool(separate_model.get_mappings_for_answer_file(conn, af))
        finally:
            conn.close()

        self.sap_mode_label.setText(
            "<b>Separate Answer Paper Mode</b> - answers are mapped for this attempt; "
            "Subject Profile coordinates are not used.")
        self._sap_page_index = max(1, min(self._sap_page_index, max(len(pages), 1)))
        self.sap_page_label.setText(f"Page {self._sap_page_index} of {len(pages)}")
        current = next((p for p in pages if p.page_number == self._sap_page_index), None)
        if current is not None and current.preview_image_path and Path(current.preview_image_path).is_file():
            pix = QPixmap(current.preview_image_path)
            if not pix.isNull():
                self.sap_page_preview_label.setPixmap(pix.scaled(
                    520, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.sap_page_preview_label.setText("(preview could not be loaded)")
        else:
            self.sap_page_preview_label.setText("(no page preview)")

        self.sap_counts_label.setText(
            f"Targets {counts['total']} | mapped {counts['mapped']} | blank {counts['blank']} | "
            f"<span style='color:#c0392b'>unresolved {counts['unresolved']}</span> | "
            f"stale {counts['stale']} | conflicts {counts['conflicts']}")

        previously_selected = self._selected_sap_target()
        self._sap_target_rows = [t.target_label for t in targets]
        self.sap_target_table.setRowCount(len(targets))
        for row_index, t in enumerate(targets):
            flags = []
            if t.has_conflict:
                flags.append("conflict")
            if t.review_stale:
                flags.append("stale")
            if not t.is_gradeable:
                flags.append("metadata")
            state_display = {
                separate_model.TARGET_STATE_MAPPED: "Mapped",
                separate_model.TARGET_STATE_UNRESOLVED: "Unresolved",
                separate_model.TARGET_STATE_EXPLICITLY_BLANK: "Blank (confirmed)",
            }.get(t.state, t.state)
            # A K1 question can be resolved by the numbered-answer block rather
            # than by a mapping of its own - say so instead of showing "0".
            count_display = str(t.mapping_count) if t.mapping_count else (
                "via answer block" if t.state == separate_model.TARGET_STATE_MAPPED else "0")
            cells = [t.paper, t.display_label, state_display, count_display, ", ".join(flags) or "-"]
            for col, text in enumerate(cells):
                self.sap_target_table.setItem(row_index, col, QTableWidgetItem(text))

        # Page reordering is only legal before mappings exist.
        for button in (self.sap_move_page_up_button, self.sap_move_page_down_button):
            button.setEnabled(not editing_locked and not has_mappings)
        for attr in ("sap_add_mapping_button", "sap_edit_mapping_button", "sap_delete_mapping_button",
                     "sap_mark_blank_button", "sap_clear_blank_button", "sap_rerun_ocr_button",
                     "sap_parse_block_button", "sap_part3_button", "sap_sync_button"):
            getattr(self, attr).setEnabled(not editing_locked)
        self.sap_parser_review_button.setEnabled(True)
        if previously_selected in self._sap_target_rows:
            self.sap_target_table.selectRow(self._sap_target_rows.index(previously_selected))
        self._refresh_sap_mapping_table()

    def _selected_sap_target(self):
        row = self.sap_target_table.currentRow()
        rows = getattr(self, "_sap_target_rows", [])
        return rows[row] if 0 <= row < len(rows) else None

    def _selected_sap_mapping_id(self):
        row = self.sap_mapping_table.currentRow()
        rows = getattr(self, "_sap_mapping_rows", [])
        return rows[row] if 0 <= row < len(rows) else None

    def _refresh_sap_mapping_table(self) -> None:
        profile, af = self._sap_context()
        target = self._selected_sap_target()
        if profile is None or af is None or target is None:
            self.sap_mapping_table.setRowCount(0)
            self._sap_mapping_rows = []
            self.sap_combined_text_label.setText("")
            return
        conn = get_connection()
        try:
            mappings = separate_model.get_mappings_for_target(conn, af, target)
            pages = {p.sap_page_id: p.page_number for p in separate_model.get_separate_pages(conn, af)}
            combined = separate_paper_service.assemble_k2_text(conn, af, target)
        finally:
            conn.close()
        self._sap_mapping_rows = [m.mapping_id for m in mappings]
        self.sap_mapping_table.setRowCount(len(mappings))
        for row_index, m in enumerate(mappings):
            text = (m.effective_text or "")[:60].replace("\n", " ")
            cells = [str(m.reading_order), m.mapping_type, str(pages.get(m.sap_page_id, "?")),
                     f"{m.x:.3f}, {m.y:.3f}, {m.width:.3f}, {m.height:.3f}", text or "-"]
            for col, value in enumerate(cells):
                self.sap_mapping_table.setItem(row_index, col, QTableWidgetItem(value))
        self.sap_combined_text_label.setText(
            f"<b>Combined text (reading order):</b> {(combined or '(none)')[:400]}")

    def handle_sap_target_selected(self) -> None:
        self._refresh_sap_mapping_table()

    def handle_sap_prev_page(self) -> None:
        if self._sap_page_index > 1:
            self._sap_page_index -= 1
            self._reload_sap_workspace()

    def handle_sap_next_page(self) -> None:
        self._sap_page_index += 1
        self._reload_sap_workspace()

    def handle_sap_reorder_page(self, delta: int) -> None:
        profile, af = self._sap_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            pages = separate_model.get_separate_pages(conn, af)
            order = [p.sap_page_id for p in pages]
            index = self._sap_page_index - 1
            target_index = index + delta
            if not (0 <= index < len(order)) or not (0 <= target_index < len(order)):
                return
            order[index], order[target_index] = order[target_index], order[index]
            try:
                separate_paper_service.reorder_separate_paper_pages(
                    conn, self._teacher_id, profile.profile_id, af, order)
            except ValueError as exc:
                show_error(self, "Reorder Pages Failed", str(exc))
                return
        finally:
            conn.close()
        self._sap_page_index = target_index + 1
        self._reload_sap_workspace()

    def handle_sap_add_mapping(self) -> None:
        target = self._selected_sap_target()
        if target is None:
            show_error(self, "No Target Selected", "Select a target in the list first.")
            return
        self._open_sap_mapping_dialog(target, mapping_id=None)

    def handle_sap_edit_mapping(self) -> None:
        target = self._selected_sap_target()
        mapping_id = self._selected_sap_mapping_id()
        if target is None or mapping_id is None:
            show_error(self, "No Mapping Selected", "Select a target and one of its mappings first.")
            return
        self._open_sap_mapping_dialog(target, mapping_id=mapping_id)

    def _suggested_sap_mapping_type(self, target):
        """The mapping type a target most likely needs, so the teacher starts
        from the right one instead of the first in the list. Still editable."""
        if target is None:
            return None
        if not target.is_gradeable:
            return separate_model.MAPPING_TYPE_PART3_SELECTED_QUESTION
        if target.paper == "Kertas 1":
            return separate_model.MAPPING_TYPE_K1_INDIVIDUAL
        label = (target.display_label or "").lower()
        if "part 2" in label:
            return separate_model.MAPPING_TYPE_K2_PART2
        if "part 3" in label:
            return separate_model.MAPPING_TYPE_K2_PART3
        return separate_model.MAPPING_TYPE_K2_PART1

    def _open_sap_mapping_dialog(self, target_label: str, mapping_id) -> None:
        import tempfile
        profile, af = self._sap_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            pages = separate_model.get_separate_pages(conn, af)
            mapping = separate_model.get_mapping(conn, mapping_id) if mapping_id else None
            existing = separate_model.get_mappings_for_target(conn, af, target_label)
            targets = {t.target_label: t for t in separate_paper_service.list_required_targets(
                conn, self._teacher_id, profile.profile_id, af)}
        finally:
            conn.close()
        target = targets.get(target_label)
        crop_dir = Path(tempfile.mkdtemp(prefix="sapcrop_"))
        initial = {
            "target_label": target_label,
            "display_label": target.display_label if target else target_label,
            "paper": target.paper if target else "",
            "pages": [(p.sap_page_id, f"Page {p.page_number}") for p in pages],
            "sap_page_id": mapping.sap_page_id if mapping else (pages[0].sap_page_id if pages else None),
            "mapping_type": mapping.mapping_type if mapping else None,
            "suggested_mapping_type": self._suggested_sap_mapping_type(target),
            "x": mapping.x if mapping else 0.1, "y": mapping.y if mapping else 0.1,
            "width": mapping.width if mapping else 0.6, "height": mapping.height if mapping else 0.15,
            "reading_order": mapping.reading_order if mapping else (
                max((m.reading_order for m in existing), default=0) + 1),
            "is_continuation": mapping.is_continuation if mapping else False,
            "crop_path": None,
        }
        if mapping is not None:
            crop = crop_dir / "crop.png"
            conn = get_connection()
            try:
                separate_paper_service.render_mapping_crop(
                    conn, self._teacher_id, profile.profile_id, af, mapping.mapping_id, str(crop))
            except Exception:
                pass
            finally:
                conn.close()
            if crop.is_file():
                initial["crop_path"] = str(crop)

        dialog = SeparateMappingDialog(self, f"Mapping - {initial['display_label']}", initial)

        def _on_preview(page_id, px, py, pw, ph):
            conn2 = get_connection()
            try:
                preview = crop_dir / "preview.png"
                separate_paper_service.render_geometry_crop(
                    conn2, self._teacher_id, profile.profile_id, af, int(page_id),
                    px, py, pw, ph, str(preview))
                dialog.set_crop(str(preview))
            except Exception as exc:
                dialog.set_geometry_error(str(exc))
            finally:
                conn2.close()

        dialog.preview_requested.connect(_on_preview)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        conn = get_connection()
        try:
            try:
                if mapping_id is None:
                    separate_paper_service.create_mapping(
                        conn, self._teacher_id, profile.profile_id, af, target_label,
                        values["mapping_type"], values["sap_page_id"], values["x"], values["y"],
                        values["width"], values["height"], reading_order=values["reading_order"],
                        is_continuation=values["is_continuation"],
                        paper=target.paper if target else None,
                        question_no=target.question_no if target else None)
                else:
                    separate_paper_service.update_mapping(
                        conn, self._teacher_id, profile.profile_id, af, mapping_id,
                        sap_page_id=values["sap_page_id"], x=values["x"], y=values["y"],
                        width=values["width"], height=values["height"],
                        reading_order=values["reading_order"])
            except ValueError as exc:
                show_error(self, "Mapping Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()
        show_success(self, "Mapping Saved", "The attempt mapping was saved.")

    def handle_sap_delete_mapping(self) -> None:
        profile, af = self._sap_context()
        mapping_id = self._selected_sap_mapping_id()
        if profile is None or mapping_id is None:
            show_error(self, "No Mapping Selected", "Select a mapping first.")
            return
        if not prompt_confirm(self, "Delete Mapping",
                              "Delete this mapping? The target returns to unresolved if it has no other mapping.",
                              confirm_text="Delete"):
            return
        conn = get_connection()
        try:
            try:
                separate_paper_service.delete_mapping(conn, self._teacher_id, profile.profile_id, af, mapping_id)
            except ValueError as exc:
                show_error(self, "Delete Mapping Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()

    def handle_sap_mark_blank(self) -> None:
        profile, af = self._sap_context()
        target = self._selected_sap_target()
        if profile is None or target is None:
            show_error(self, "No Target Selected", "Select a target first.")
            return
        if not prompt_confirm(self, "Mark Explicitly Blank",
                              "Confirm the student left this answer blank? Unmapped is never treated as blank.",
                              confirm_text="Confirm Blank"):
            return
        conn = get_connection()
        try:
            try:
                separate_paper_service.mark_target_blank(conn, self._teacher_id, profile.profile_id, af, target)
            except ValueError as exc:
                show_error(self, "Mark Blank Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()

    def handle_sap_clear_blank(self) -> None:
        profile, af = self._sap_context()
        target = self._selected_sap_target()
        if profile is None or target is None:
            return
        conn = get_connection()
        try:
            separate_paper_service.clear_target_blank(conn, self._teacher_id, profile.profile_id, af, target)
        finally:
            conn.close()
        self._reload_sap_workspace()

    def handle_sap_rerun_ocr(self) -> None:
        profile, af = self._sap_context()
        mapping_id = self._selected_sap_mapping_id()
        if profile is None or mapping_id is None:
            show_error(self, "No Mapping Selected", "Select a mapping to run OCR on.")
            return
        self.sap_rerun_ocr_button.setEnabled(False)
        self._sap_ocr_worker = SeparatePaperOcrWorker(self._teacher_id, profile.profile_id, af, mapping_id)
        self._sap_ocr_worker.succeeded.connect(self._on_sap_ocr_succeeded)
        self._sap_ocr_worker.failed.connect(self._on_sap_ocr_failed)
        self._sap_ocr_worker.finished.connect(lambda: self.sap_rerun_ocr_button.setEnabled(True))
        self._sap_ocr_worker.start()

    def _on_sap_ocr_succeeded(self, payload: dict) -> None:
        self._reload_sap_workspace()
        show_detail(self, "OCR Complete",
                    f"Original OCR: {payload.get('original') or '(none)'}\n\n"
                    f"Rerun OCR: {payload.get('rerun') or '(none)'}\n\n"
                    "Original, rerun and teacher-corrected text are stored separately.")

    def _on_sap_ocr_failed(self, message: str) -> None:
        show_error(self, "OCR Failed", f"{message}\n\nExisting mappings and OCR text were not changed.")

    def handle_sap_parse_block(self) -> None:
        profile, af = self._sap_context()
        mapping_id = self._selected_sap_mapping_id()
        if profile is None or mapping_id is None:
            show_error(self, "No Mapping Selected", "Select the Kertas 1 numbered-answer block mapping.")
            return
        conn = get_connection()
        try:
            try:
                result = separate_paper_service.parse_k1_block_mapping(
                    conn, self._teacher_id, profile.profile_id, af, mapping_id)
            except ValueError as exc:
                show_error(self, "Parse Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()
        show_detail(self, "Kertas 1 Block Parsed",
                    f"{len(result.rows)} answer row(s) parsed; {len(result.conflicts)} conflict(s).\n\n"
                    "Open 'K1 Parser Review' to confirm or correct each answer.")

    def handle_sap_open_parser_review(self) -> None:
        profile, af = self._sap_context()
        if profile is None:
            return
        locked = self._overlay_editing_locked(af)
        while True:
            conn = get_connection()
            try:
                rows = separate_model.get_parsed_answers(conn, af)
            finally:
                conn.close()
            if not rows:
                show_error(self, "No Parsed Answers",
                           "Parse a Kertas 1 numbered-answer block mapping first.")
                return
            initial = [{
                "parsed_id": r.parsed_id, "question_no": r.question_no,
                "parsed_answer": r.parsed_answer, "warning": r.warning,
                "has_conflict": r.has_conflict, "teacher_answer": r.teacher_answer,
                "state": r.state, "source_text": r.source_text, "confidence": r.confidence,
            } for r in rows]
            dialog = SeparateParserReviewDialog(self, "Kertas 1 Parser Review", initial, read_only=locked)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dialog.values()
            conn = get_connection()
            try:
                try:
                    separate_paper_service.correct_parsed_answer(
                        conn, self._teacher_id, profile.profile_id, af, decision["parsed_id"],
                        teacher_answer=decision.get("teacher_answer"), state=decision.get("state"))
                except ValueError as exc:
                    show_error(self, "Parser Correction Failed", str(exc))
                    return
            finally:
                conn.close()
            self._reload_sap_workspace()
            if not decision.get("keep_open"):
                return

    def handle_sap_confirm_part3(self) -> None:
        profile, af = self._sap_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            current = separate_paper_service.get_part3_selected_question(conn, af)
        finally:
            conn.close()
        choice = prompt_select(
            self, "Confirm Part 3 Question",
            f"Which Part 3 question did the student answer? (required, not scored)\n"
            f"Currently recorded: {current or 'not confirmed'}",
            [(f"Question {n}", str(n)) for n in (3, 4, 5)])
        if choice is CANCELLED or choice is None:
            return
        conn = get_connection()
        try:
            try:
                separate_paper_service.confirm_part3_selected_question(
                    conn, self._teacher_id, profile.profile_id, af, choice)
            except ValueError as exc:
                show_error(self, "Part 3 Confirmation Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()

    def handle_sap_sync_review(self) -> None:
        """Project the mapped/parsed separate-paper answers into the standard
        marked-answer rows so the existing Teacher Review controls show them."""
        profile, af = self._sap_context()
        if profile is None:
            return
        conn = get_connection()
        try:
            try:
                count = separate_paper_service.sync_separate_mode_marked_answers(
                    conn, self._teacher_id, profile.profile_id, af)
            except ValueError as exc:
                show_error(self, "Load into Teacher Review Failed", str(exc))
                return
        finally:
            conn.close()
        self._reload_sap_workspace()
        show_success(self, "Loaded into Teacher Review",
                     f"{count} target(s) loaded into the Teacher Review workspace.")

    def handle_sap_run_proposals(self) -> None:
        """Stage 12G-4: run Core AI 2 region proposals for the current
        separate-paper page (background), then open the review dialog. A
        no-model/failure result changes nothing - manual mapping stays usable."""
        import hashlib
        profile, af = self._sap_context()
        if profile is None or af is None:
            return
        conn = get_connection()
        try:
            pages = separate_model.get_separate_pages(conn, af)
        finally:
            conn.close()
        page = next((p for p in pages if p.page_number == self._sap_page_index), None)
        if page is None or not page.preview_image_path:
            show_error(self, "Detect Answer Regions", "Render the page preview first.")
            return
        try:
            checksum = hashlib.sha256(Path(page.preview_image_path).read_bytes()).hexdigest()
        except OSError:
            checksum = ""
        self.sap_proposals_button.setEnabled(False)
        self._sap_proposal_worker = SeparatePaperProposalWorker(
            self._teacher_id, profile.profile_id, af, page.sap_page_id, page.preview_image_path,
            page.width_px or 0, page.height_px or 0, checksum)
        self._sap_proposal_worker.succeeded.connect(self._on_sap_proposals_ready)
        self._sap_proposal_worker.failed.connect(self._on_sap_proposals_failed)
        self._sap_proposal_worker.finished.connect(lambda: self.sap_proposals_button.setEnabled(True))
        self._sap_proposal_worker.start()

    def _on_sap_proposals_ready(self, count: int) -> None:
        if count == 0:
            show_detail(self, "Detect Answer Regions",
                        "No proposals were produced (no active/compatible model or the model found "
                        "nothing). Continue mapping manually.")
            return
        self.handle_sap_open_proposal_review()

    def _on_sap_proposals_failed(self, message: str) -> None:
        show_error(self, "Region Detection Failed",
                   f"{message}\n\nNo proposals were applied - continue mapping manually.")

    def handle_sap_open_proposal_review(self) -> None:
        from app.services import ai_region_proposal_service as proposals_svc
        from app.models import ai_region_proposal_model as rp
        profile, af = self._sap_context()
        if profile is None or af is None:
            return
        locked = self._overlay_editing_locked(answer_file_id=af)
        while True:
            conn = get_connection()
            try:
                records = [r for r in proposals_svc.list_attempt_proposals(
                    conn, self._teacher_id, profile.profile_id, af)
                    if r.status in (rp.STATUS_PROPOSED, rp.STATUS_EDITED)]
                targets = [(t.display_label, t.target_label) for t in
                           separate_paper_service.list_required_targets(
                               conn, self._teacher_id, profile.profile_id, af)]
            finally:
                conn.close()
            if not records:
                show_detail(self, "Detect Answer Regions", "No proposals are awaiting review.")
                return
            data = [{
                "proposal_id": r.proposal_id, "proposed_class": r.proposed_class,
                "confidence": r.confidence, "model_version": r.model_version,
                "rationale": r.rationale, "status": r.status, "geometry": r.effective_geometry,
            } for r in records]
            dialog = RegionProposalReviewDialog(self, "Detected Answer Regions", data,
                                                targets=targets, read_only=locked)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dialog.values()
            conn = get_connection()
            try:
                try:
                    self._apply_proposal_decision(conn, proposals_svc, decision)
                except (proposals_svc.ProposalError, ValueError) as exc:
                    show_error(self, "Proposal Decision Failed", str(exc))
                    return
            finally:
                conn.close()
            self._reload_sap_workspace()
            if not decision.get("keep_open"):
                return

    def _apply_proposal_decision(self, conn, proposals_svc, decision) -> None:
        pid = decision["proposal_id"]
        action = decision["action"]
        if action == "accept":
            proposals_svc.accept_proposal(conn, self._teacher_id, pid,
                                          target_label=decision.get("target_label"))
        elif action == "reject":
            proposals_svc.reject_proposal(conn, self._teacher_id, pid)
        elif action == "defer":
            proposals_svc.defer_proposal(conn, self._teacher_id, pid)
        elif action == "edit":
            x, y, w, h = decision["geometry"]
            proposals_svc.edit_proposal_geometry(conn, self._teacher_id, pid, x, y, w, h)

    def handle_delete_overlay(self, overlay_id: int) -> None:
        conn = get_connection()
        try:
            try:
                delete_subject_profile_overlay(conn, overlay_id)
            except ValueError as exc:
                show_error(self, "Delete Overlay Failed", str(exc))
                return
        finally:
            conn.close()
        self.refresh_marking_editor()

    def handle_marking_editor_prev_page(self) -> None:
        if self._marking_editor_page_index <= 1:
            return
        self._marking_editor_page_index -= 1
        self.refresh_marking_editor()

    def handle_marking_editor_next_page(self) -> None:
        if self._marking_editor_page_index >= len(self._marking_editor_page_paths):
            return
        self._marking_editor_page_index += 1
        self.refresh_marking_editor()

    def handle_mark_answers_clicked(self) -> None:
        """Data Management Follow-up (feature 3): runs extraction + marking
        + overlay creation for the current student on a background
        MarkAnswerFileSubprocessWorker (a separate OS process, mirroring
        the student-PDF upload worker - see that class's docstring for why
        real OCR must never run inside a QThread in this process) instead
        of synchronously on the UI thread, so the window never freezes and
        a circular progress indicator (reused CircularProgressWidget - see
        _show_progress_dialog) is visible the whole time. The button is
        disabled for the duration so a repeated click can never start a
        second marking job for the same answer file while one is already
        running (guarded twice: the button itself, and _mark_answers_worker
        being non-None)."""
        profile = getattr(self, "_marking_editor_profile", None)
        if profile is None or self._marking_editor_answer_file_id is None:
            return
        if getattr(self, "_mark_answers_worker", None) is not None:
            return

        self.mark_answers_button.setEnabled(False)
        progress_dialog, progress_widget = self._show_progress_dialog("Marking Student Answer")
        self._mark_answers_progress_dialog = progress_dialog
        self._mark_answers_progress_widget = progress_widget

        worker = MarkAnswerFileSubprocessWorker(
            self._teacher_id, profile.profile_id, self._marking_editor_answer_file_id, parent=self
        )
        worker.progress.connect(self.handle_mark_answers_worker_progress)
        worker.succeeded.connect(self.handle_mark_answers_worker_succeeded)
        worker.failed.connect(self.handle_mark_answers_worker_failed)
        worker.finished.connect(self.handle_mark_answers_worker_finished)
        self._mark_answers_worker = worker
        worker.start()

    def handle_mark_answers_worker_progress(self, message: str, current: int, total: int) -> None:
        self._mark_answers_progress_widget.set_progress(message, current, total)

    def handle_mark_answers_worker_succeeded(self) -> None:
        self.refresh_marking_editor()
        self.refresh_student_results_table()
        show_success(self, "Mark Answers", "Answers marked successfully.")

    def handle_mark_answers_worker_failed(self, message: str) -> None:
        show_error(self, "Mark Answers Failed", message)

    def handle_mark_answers_worker_finished(self) -> None:
        dialog = getattr(self, "_mark_answers_progress_dialog", None)
        if dialog is not None:
            dialog.close()
        self.mark_answers_button.setEnabled(True)
        self._mark_answers_worker = None
