"""Main Marking System session editing logic for the Teacher role
(Stage 11L, extended with preprocessing in Stage 11M, OCR in Stage 11N,
template linking in Stage 11O, answer extraction in Stage 11P, Kertas 1
rule-based draft marking in Stage 11Q, teacher review/override in
Stage 11R, and final result finalization in Stage 11S).

Standalone, class-independent marking sessions: a teacher attaches a
question paper and an answer key/marking scheme, then uploads one or more
student answer PDFs (each PDF belongs to exactly one session and represents
exactly one student). Stage 11P adds the first answer-extraction layer -
matching each linked template's extraction targets against OCR'd page text
- but still no marking, review, or final-result computation happens here
(see later stages). No class selection and no student-account linking are
required anywhere in this workflow.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.models.main_marking_model import (
    EXTRACTED_ANSWER_STATUS_EXTRACTED,
    EXTRACTED_ANSWER_STATUS_FAILED,
    EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
    EXTRACTED_ANSWER_STATUS_NO_TEXT,
    FINAL_RESULT_STATUS_FINALIZED,
    MARKED_ANSWER_STATUS_MARKED,
    MARKED_ANSWER_STATUS_NEEDS_REVIEW,
    MainMarkingAnswerExtractionRun,
    MainMarkingAnswerFile,
    MainMarkingExtractedAnswer,
    MainMarkingFinalResult,
    MainMarkingFinalResultItem,
    MainMarkingMarkedAnswer,
    MainMarkingMarkingRun,
    MainMarkingOCRResult,
    MainMarkingOCRRun,
    MainMarkingPreprocessedPage,
    MainMarkingProcessingRun,
    MainMarkingSession,
    MainMarkingSessionRow,
    OCR_RESULT_STATUS_COMPLETED,
    OCR_RESULT_STATUS_FAILED,
    PAGE_STATUS_FAILED,
    PAGE_STATUS_PREPROCESSED,
    PROCESSING_STATUS_ANSWER_EXTRACTED,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_FINALIZED,
    PROCESSING_STATUS_MARKED,
    PROCESSING_STATUS_MARKING_FAILED,
    PROCESSING_STATUS_OCR_COMPLETED,
    PROCESSING_STATUS_OCR_FAILED,
    PROCESSING_STATUS_PREPROCESSED,
    PROCESSING_STATUS_REVIEWED,
    REVIEW_STATUS_PENDING_REVIEW,
    REVIEW_STATUS_REVIEWED,
    STATUS_ANSWER_EXTRACTED,
    STATUS_FINALIZED,
    STATUS_MARKED,
    STATUS_OCR_COMPLETED,
    STATUS_PREPROCESSED,
    STATUS_REVIEWED,
    add_answer_file as add_answer_file_record,
    add_extracted_answer as add_extracted_answer_record,
    add_final_result_item as add_final_result_item_record,
    add_marked_answer as add_marked_answer_record,
    add_ocr_result as add_ocr_result_record,
    add_preprocessed_page as add_preprocessed_page_record,
    create_answer_extraction_run as create_answer_extraction_run_record,
    create_final_result as create_final_result_record,
    create_marking_run as create_marking_run_record,
    create_ocr_run as create_ocr_run_record,
    create_processing_run as create_processing_run_record,
    create_session as create_session_record,
    delete_answer_file as delete_answer_file_record,
    delete_extracted_answers_for_answer_file as delete_extracted_answers_for_answer_file_record,
    delete_final_result_for_answer_file as delete_final_result_for_answer_file_record,
    delete_marked_answers_for_answer_file as delete_marked_answers_for_answer_file_record,
    delete_ocr_results_for_answer_file as delete_ocr_results_for_answer_file_record,
    delete_session as delete_session_record,
    get_answer_file_by_id,
    get_answer_files_for_session as get_answer_files_for_session_record,
    get_answer_extraction_runs_for_session as get_answer_extraction_runs_for_session_record,
    get_extracted_answers_for_answer_file as get_extracted_answers_for_answer_file_record,
    get_final_result_by_answer_file_id as get_final_result_by_answer_file_id_record,
    get_final_result_by_id as get_final_result_by_id_record,
    get_final_result_items as get_final_result_items_record,
    get_final_results_for_teacher as get_final_results_for_teacher_record,
    get_marked_answer_by_id,
    get_marked_answers_for_answer_file as get_marked_answers_for_answer_file_record,
    get_marking_runs_for_session as get_marking_runs_for_session_record,
    get_ocr_results_for_answer_file as get_ocr_results_for_answer_file_record,
    get_ocr_runs_for_session as get_ocr_runs_for_session_record,
    get_preprocessed_pages_for_answer_file as get_preprocessed_pages_for_answer_file_record,
    get_processing_runs_for_session as get_processing_runs_for_session_record,
    get_session_by_id,
    get_sessions_for_teacher as get_sessions_for_teacher_record,
    mark_answer_extraction_run_completed,
    mark_answer_extraction_run_failed,
    mark_marking_run_completed,
    mark_marking_run_failed,
    mark_ocr_run_completed,
    mark_ocr_run_failed,
    mark_processing_run_completed,
    mark_processing_run_failed,
    update_answer_file_page_count,
    update_answer_file_path,
    update_answer_file_processing_status,
    update_answer_file_student_info as update_answer_file_student_info_record,
    update_marked_answer_review as update_marked_answer_review_record,
    update_session_details as update_session_details_record,
    update_session_file_paths,
    update_session_status,
    update_session_template_id as update_session_template_id_record,
)
from app.models.marking_setup_model import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_WRITTEN_LETTER,
    MarkingQuestion,
    get_marking_questions_for_setup,
    get_marking_setups_by_template,
)
from app.models.revision_material_model import ALLOWED_PAPER_TYPES, PAPER_TYPE_KERTAS_1
from app.models.template_model import (
    SHAPE_TYPE_POLYGON,
    SHAPE_TYPE_RECTANGLE,
    AnswerTemplate,
    TeacherTemplateRow,
    get_template_by_id,
)
from app.services.extraction_target_service import (
    TARGET_KIND_GROUP,
    TARGET_KIND_REGION,
    ExtractionTarget,
    list_template_extraction_targets,
)
from app.services.template_service import get_owned_template, list_templates_for_teacher
from app.services.user_service import validate_teacher_exists
from app.utils.document_preprocessing import (
    get_image_dimensions,
    get_pdf_page_count,
    get_region_rotation_angle,
    load_page_images,
    match_ocr_blocks_to_region,
    preprocess_page_image,
    save_page_image,
)
from app.utils.file_storage import (
    get_marking_answer_file_original_folder,
    get_marking_answer_file_preprocessed_folder,
    store_marking_session_file,
)
from app.utils.ocr_engine import OCREngine, get_default_engine

MAX_TITLE_LENGTH = 150


def _validate_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise ValueError("Session title is required.")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Session title must be {MAX_TITLE_LENGTH} characters or fewer.")
    return title


def _validate_paper_type(paper_type: str) -> None:
    if paper_type not in ALLOWED_PAPER_TYPES:
        raise ValueError(f"Paper type must be one of: {', '.join(ALLOWED_PAPER_TYPES)}.")


def get_owned_session(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> MainMarkingSession:
    """Return session_id if it exists and is owned by teacher_id. Raises
    ValueError otherwise."""
    session = get_session_by_id(conn, session_id)
    if session is None:
        raise ValueError("Marking session not found.")
    if session.teacher_id != teacher_id:
        raise ValueError("You can only manage your own marking sessions.")
    return session


def create_marking_session(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    question_paper_source_path: Optional[str] = None,
    answer_key_source_path: Optional[str] = None,
) -> MainMarkingSession:
    """Create a new standalone marking session owned by teacher_id, copying
    the optional question paper / answer key into a local, session-specific
    folder under data/main_marking_sessions/. No class_id is used or
    required - this workflow is entirely independent of class management.

    Raises ValueError if the requester is not a teacher, the title is
    empty/too long, or the paper type isn't Kertas 1/Kertas 2/Both.
    """
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create marking sessions.")

    title = _validate_title(title)
    _validate_paper_type(paper_type)

    session = create_session_record(conn, teacher_id, title, paper_type, None, None)

    question_paper_path = None
    if question_paper_source_path:
        question_paper_path = store_marking_session_file(session.session_id, question_paper_source_path, "question_paper")
    answer_key_path = None
    if answer_key_source_path:
        answer_key_path = store_marking_session_file(session.session_id, answer_key_source_path, "answer_key")

    if question_paper_path or answer_key_path:
        update_session_file_paths(conn, session.session_id, question_paper_path, answer_key_path)

    session.question_paper_path = question_paper_path
    session.answer_key_path = answer_key_path
    return session


def list_marking_sessions_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[MainMarkingSessionRow]:
    return get_sessions_for_teacher_record(conn, teacher_id)


def get_marking_session(conn: sqlite3.Connection, session_id: int, teacher_id: int) -> MainMarkingSession:
    return get_owned_session(conn, teacher_id, session_id)


def update_marking_session_details(
    conn: sqlite3.Connection, teacher_id: int, session_id: int, title: str, paper_type: str
) -> MainMarkingSession:
    """Update a session's title/paper type. Raises ValueError if the
    session doesn't exist, isn't owned by teacher_id, or any field is
    invalid."""
    get_owned_session(conn, teacher_id, session_id)
    title = _validate_title(title)
    _validate_paper_type(paper_type)
    update_session_details_record(conn, session_id, title, paper_type)
    return get_session_by_id(conn, session_id)


def delete_marking_session(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> None:
    """Delete a marking session owned by teacher_id and all of its answer
    file rows (ON DELETE CASCADE) - the copied files on disk are not
    deleted. Raises ValueError if the session doesn't exist or isn't owned
    by teacher_id."""
    get_owned_session(conn, teacher_id, session_id)
    delete_session_record(conn, session_id)


def add_answer_file_to_session(
    conn: sqlite3.Connection,
    session_id: int,
    teacher_id: int,
    file_source_path: str,
    student_name: str = "",
    student_code: str = "",
) -> MainMarkingAnswerFile:
    """Add one student answer PDF to a session owned by teacher_id, copying
    it into the session's storage folder. One uploaded file always creates
    exactly one answer_file row, regardless of how many pages the PDF has.
    page_count is detected automatically for PDFs where possible and left
    as None otherwise (safe fallback - no error is raised for undetectable
    page counts).

    Raises ValueError if the session doesn't exist or isn't owned by
    teacher_id.
    """
    session = get_owned_session(conn, teacher_id, session_id)

    original_filename = Path(file_source_path).name
    answer_file = add_answer_file_record(
        conn, session.session_id, "", original_filename,
        student_name.strip() or None, student_code.strip() or None, None,
    )

    destination_name = f"answer_{answer_file.answer_file_id}"
    stored_path = store_marking_session_file(session.session_id, file_source_path, destination_name)
    update_answer_file_path(conn, answer_file.answer_file_id, stored_path)

    page_count = get_pdf_page_count(stored_path)
    if page_count is not None:
        update_answer_file_page_count(conn, answer_file.answer_file_id, page_count)

    answer_file.file_path = stored_path
    answer_file.page_count = page_count
    return answer_file


def list_answer_files_for_session(
    conn: sqlite3.Connection, session_id: int, teacher_id: int
) -> List[MainMarkingAnswerFile]:
    get_owned_session(conn, teacher_id, session_id)
    return get_answer_files_for_session_record(conn, session_id)


def update_answer_file_student_info(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int, student_name: str = "", student_code: str = ""
) -> MainMarkingAnswerFile:
    """Update an answer file's optional student name/code. Raises
    ValueError if the answer file doesn't exist or its session isn't owned
    by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)

    update_answer_file_student_info_record(
        conn, answer_file_id, student_name.strip() or None, student_code.strip() or None
    )
    return get_answer_file_by_id(conn, answer_file_id)


def remove_answer_file_from_session(conn: sqlite3.Connection, teacher_id: int, answer_file_id: int) -> None:
    """Remove one answer file from its session. Raises ValueError if the
    answer file doesn't exist or its session isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)

    delete_answer_file_record(conn, answer_file_id)


def get_answer_file_display_name(answer_file: MainMarkingAnswerFile) -> str:
    """Return the best available label for answer_file: its student name if
    set, otherwise its original filename, otherwise a generic fallback."""
    if answer_file.student_name:
        return answer_file.student_name
    if answer_file.original_filename:
        return answer_file.original_filename
    return f"Answer File {answer_file.answer_file_id}"


# --- Stage 11M: preprocessing-only run foundation ---------------------------
#
# "Run Preprocessing" converts each of a session's uploaded student answer
# PDFs into cleaned page images (reusing the same load_page_images /
# preprocess_page_image / save_page_image helpers already relied on by
# app/services/preprocessing_service.py for other document types) and
# records per-page + per-answer-file outcomes. It never OCRs, extracts
# template regions, scores, or creates review/result rows - those are later
# stages. Uploaded original PDFs are only ever read, never modified.


@dataclass
class MarkingSessionProcessingSummary:
    session_id: int
    total_answer_files: int
    uploaded_count: int
    preprocessed_count: int
    failed_count: int
    latest_run: Optional[MainMarkingProcessingRun]


def _preprocess_one_answer_file(
    conn: sqlite3.Connection, session_id: int, answer_file: MainMarkingAnswerFile,
    page_progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Convert answer_file's uploaded PDF into cleaned page images, recording
    one main_marking_preprocessed_pages row per page and updating the answer
    file's processing_status. Returns True if every page succeeded, False if
    any page failed (or the file couldn't be opened/rendered at all) - in
    either case, this only ever touches this one answer_file's own status/
    pages, so a failure here never stops other answer files from being
    processed.

    Stage 11W: also saves each page's ORIGINAL (un-degraded) rendered image
    alongside the CLAHE/denoise/threshold-processed one used for OCR, so a
    clean digital PDF's preview never looks worse than the source - see
    original_image_path on MainMarkingPreprocessedPage. page_progress_
    callback(page_number, total_pages), if given, is called just before each
    page is processed (optional, additive - existing callers unaffected)."""
    try:
        pages = load_page_images(answer_file.file_path)
    except Exception as exc:
        update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_FAILED)
        add_preprocessed_page_record(conn, answer_file.answer_file_id, 1, None, PAGE_STATUS_FAILED, str(exc))
        return False

    output_folder = get_marking_answer_file_preprocessed_folder(session_id, answer_file.answer_file_id)
    original_folder = get_marking_answer_file_original_folder(session_id, answer_file.answer_file_id)
    any_page_failed = False
    total_pages = len(pages)
    for page_number, page_image in enumerate(pages, start=1):
        if page_progress_callback is not None:
            page_progress_callback(page_number, total_pages)
        try:
            original_path = original_folder / f"page_{page_number:03d}.png"
            save_page_image(page_image, original_path)

            processed = preprocess_page_image(page_image)
            output_path = output_folder / f"page_{page_number:03d}.png"
            save_page_image(processed, output_path)
            add_preprocessed_page_record(
                conn, answer_file.answer_file_id, page_number, str(output_path), PAGE_STATUS_PREPROCESSED,
                original_image_path=str(original_path),
            )
        except Exception as exc:
            any_page_failed = True
            add_preprocessed_page_record(conn, answer_file.answer_file_id, page_number, None, PAGE_STATUS_FAILED, str(exc))

    if any_page_failed:
        update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_FAILED)
        return False

    update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_PREPROCESSED)
    if answer_file.page_count != len(pages):
        update_answer_file_page_count(conn, answer_file.answer_file_id, len(pages))
    return True


def run_preprocessing_for_session(
    conn: sqlite3.Connection, session_id: int, teacher_id: int,
    page_progress_callback: Optional[Callable[[int, int], None]] = None,
) -> MainMarkingProcessingRun:
    """Run preprocessing for every uploaded answer file in a session owned by
    teacher_id: converts each answer PDF's pages into cleaned page images
    under that answer file's own preprocessed/ subfolder. Does not OCR,
    extract, score, or create any review/result rows - only this stage's
    preprocessing metadata.

    page_progress_callback(page_number, total_pages), if given, is called
    just before each page of each answer file is processed (Stage 11W,
    additive/optional - existing callers unaffected) - lets a caller show
    genuinely gradual progress instead of a single all-or-nothing step.

    Raises ValueError (before any run row is created) if the session isn't
    owned by teacher_id, is missing its question paper or answer key, or has
    no uploaded answer files yet.
    """
    session = get_owned_session(conn, teacher_id, session_id)
    if not session.question_paper_path:
        raise ValueError("Attach a question paper before running preprocessing.")
    if not session.answer_key_path:
        raise ValueError("Attach an answer key / marking scheme before running preprocessing.")

    answer_files = get_answer_files_for_session_record(conn, session_id)
    if not answer_files:
        raise ValueError("Upload at least one student answer PDF before running preprocessing.")

    run = create_processing_run_record(conn, session_id)

    success_count = 0
    failure_labels = []
    for answer_file in answer_files:
        succeeded = _preprocess_one_answer_file(conn, session_id, answer_file, page_progress_callback)
        if succeeded:
            success_count += 1
        else:
            failure_labels.append(get_answer_file_display_name(answer_file))

    if success_count > 0:
        update_session_status(conn, session_id, STATUS_PREPROCESSED)

    total = len(answer_files)
    if not failure_labels:
        message = f"All {total} answer file(s) preprocessed successfully."
        mark_processing_run_completed(conn, run.run_id, message)
    else:
        message = (
            f"{success_count} of {total} answer file(s) preprocessed successfully. "
            f"Failed: {', '.join(failure_labels)}."
        )
        if success_count > 0:
            mark_processing_run_completed(conn, run.run_id, message)
        else:
            mark_processing_run_failed(conn, run.run_id, message)

    return get_processing_runs_for_session_record(conn, session_id)[0]


def list_preprocessing_runs_for_session(
    conn: sqlite3.Connection, session_id: int, teacher_id: int
) -> List[MainMarkingProcessingRun]:
    get_owned_session(conn, teacher_id, session_id)
    return get_processing_runs_for_session_record(conn, session_id)


def list_preprocessed_pages_for_answer_file(
    conn: sqlite3.Connection, answer_file_id: int, teacher_id: int
) -> List[MainMarkingPreprocessedPage]:
    """Raises ValueError if the answer file doesn't exist or its session
    isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)
    return get_preprocessed_pages_for_answer_file_record(conn, answer_file_id)


def get_session_processing_summary(
    conn: sqlite3.Connection, session_id: int, teacher_id: int
) -> MarkingSessionProcessingSummary:
    get_owned_session(conn, teacher_id, session_id)
    answer_files = get_answer_files_for_session_record(conn, session_id)
    runs = get_processing_runs_for_session_record(conn, session_id)
    return MarkingSessionProcessingSummary(
        session_id=session_id,
        total_answer_files=len(answer_files),
        uploaded_count=sum(1 for f in answer_files if f.processing_status == "uploaded"),
        preprocessed_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_PREPROCESSED),
        failed_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_FAILED),
        latest_run=runs[0] if runs else None,
    )


# --- Stage 11N: OCR run foundation -------------------------------------------
#
# "Run OCR" runs the shared OCR engine abstraction (app.utils.ocr_engine -
# the same PaddleOCR adapter already used by app/services/ocr_service.py for
# other document types, injectable via `engine` for tests, exactly like that
# service's own `engine` parameter) against each of a session's already-
# preprocessed page images (Stage 11M). It only stores raw text/confidence
# per page - no answer extraction, template region matching, or marking
# happens here. app/services/ocr_service.py's own OCR job tables are tied to
# document_preprocessing_jobs, which Main Marking's Stage 11M preprocessing
# deliberately never populates (it uses its own main_marking_preprocessed_
# pages table instead), so this stage reuses only the decoupled OCREngine
# abstraction and adds its own small, additive OCR tables - consistent with
# Stage 11M's own choice not to reuse the generic preprocessing tables.
#
# Rerunning OCR for a session deletes and recreates each answer file's OCR
# result rows (Option A - simplest for this prototype) so the latest visible
# results never duplicate, while the run itself is still recorded in
# main_marking_ocr_runs for history.


def _run_ocr_for_answer_file(
    conn: sqlite3.Connection, answer_file: MainMarkingAnswerFile, engine: OCREngine,
    page_progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Run OCR on every successfully preprocessed page of answer_file,
    recording one main_marking_ocr_results row per page. Returns True if at
    least one page's OCR succeeded (this file counts as ocr_completed),
    False if every page failed or there were no preprocessed pages to OCR at
    all (this file counts as ocr_failed) - either way, a failure here never
    stops other answer files in the same run from being processed.

    page_progress_callback(page_number, total_pages), if given, is called
    just before each page's OCR runs (Stage 11W, additive/optional)."""
    preprocessed_pages = [
        page for page in get_preprocessed_pages_for_answer_file_record(conn, answer_file.answer_file_id)
        if page.status == PAGE_STATUS_PREPROCESSED
    ]
    if not preprocessed_pages:
        add_ocr_result_record(
            conn, answer_file.answer_file_id, 1, None, None, OCR_RESULT_STATUS_FAILED,
            "No preprocessed page images are available for this answer file.",
        )
        update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_OCR_FAILED)
        return False

    any_page_succeeded = False
    total_pages = len(preprocessed_pages)
    for page in preprocessed_pages:
        if page_progress_callback is not None:
            page_progress_callback(page.page_number, total_pages)
        try:
            result = engine.run_page(page.preprocessed_image_path)
            blocks_json = (
                json.dumps([{"text": b.text, "confidence": b.confidence, "box": b.box} for b in result.blocks])
                if result.blocks else None
            )
            add_ocr_result_record(
                conn, answer_file.answer_file_id, page.page_number, result.text, result.average_confidence,
                OCR_RESULT_STATUS_COMPLETED, ocr_blocks_json=blocks_json,
            )
            any_page_succeeded = True
        except Exception as exc:
            add_ocr_result_record(
                conn, answer_file.answer_file_id, page.page_number, None, None, OCR_RESULT_STATUS_FAILED, str(exc)
            )

    update_answer_file_processing_status(
        conn, answer_file.answer_file_id,
        PROCESSING_STATUS_OCR_COMPLETED if any_page_succeeded else PROCESSING_STATUS_OCR_FAILED,
    )
    return any_page_succeeded


def run_ocr_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int, engine: Optional[OCREngine] = None,
    page_progress_callback: Optional[Callable[[int, int], None]] = None,
) -> MainMarkingOCRRun:
    """Run OCR for every answer file in a session owned by teacher_id, using
    each file's already-preprocessed page images (Stage 11M). Only stores
    raw OCR text/confidence - never extracts answers, matches template
    regions, or marks anything.

    Reruns are safe: each answer file's previous OCR result rows are
    deleted and recreated, while the run itself is still recorded in
    main_marking_ocr_runs for history.

    Raises ValueError (before any run row is created) if the session isn't
    owned by teacher_id, hasn't been preprocessed yet, or has no
    successfully preprocessed pages at all.

    If the OCR engine itself can't be constructed (e.g. the OCR dependency
    is unavailable), the whole run - not any individual answer file - is
    recorded as failed with a readable message, mirroring
    app/services/ocr_service.py's existing behavior.
    """
    session = get_owned_session(conn, teacher_id, session_id)
    if session.status not in (
        STATUS_PREPROCESSED, STATUS_OCR_COMPLETED, STATUS_ANSWER_EXTRACTED, STATUS_MARKED, STATUS_REVIEWED,
        STATUS_FINALIZED,
    ):
        raise ValueError("Run preprocessing successfully before running OCR.")

    answer_files = get_answer_files_for_session_record(conn, session_id)
    if not answer_files:
        raise ValueError("Upload at least one student answer PDF before running OCR.")

    has_any_preprocessed_page = any(
        page.status == PAGE_STATUS_PREPROCESSED
        for answer_file in answer_files
        for page in get_preprocessed_pages_for_answer_file_record(conn, answer_file.answer_file_id)
    )
    if not has_any_preprocessed_page:
        raise ValueError("Run preprocessing successfully for at least one answer file before running OCR.")

    for answer_file in answer_files:
        delete_ocr_results_for_answer_file_record(conn, answer_file.answer_file_id)

    run = create_ocr_run_record(conn, session_id)

    try:
        active_engine = engine if engine is not None else get_default_engine()
    except Exception as exc:
        mark_ocr_run_failed(conn, run.run_id, f"OCR engine unavailable: {exc}")
        return get_ocr_runs_for_session_record(conn, session_id)[0]

    success_count = 0
    failure_labels = []
    for answer_file in answer_files:
        if _run_ocr_for_answer_file(conn, answer_file, active_engine, page_progress_callback):
            success_count += 1
        else:
            failure_labels.append(get_answer_file_display_name(answer_file))

    if success_count > 0:
        update_session_status(conn, session_id, STATUS_OCR_COMPLETED)

    total = len(answer_files)
    if not failure_labels:
        message = f"OCR completed for {total} answer file(s)."
        mark_ocr_run_completed(conn, run.run_id, message)
    else:
        message = (
            f"{success_count} of {total} answer file(s) completed OCR successfully. "
            f"Failed: {', '.join(failure_labels)}."
        )
        if success_count > 0:
            mark_ocr_run_completed(conn, run.run_id, message)
        else:
            mark_ocr_run_failed(conn, run.run_id, message)

    return get_ocr_runs_for_session_record(conn, session_id)[0]


def list_ocr_runs_for_session(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> List[MainMarkingOCRRun]:
    get_owned_session(conn, teacher_id, session_id)
    return get_ocr_runs_for_session_record(conn, session_id)


def list_ocr_results_for_answer_file(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int
) -> List[MainMarkingOCRResult]:
    """Raises ValueError if the answer file doesn't exist or its session
    isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)
    return get_ocr_results_for_answer_file_record(conn, answer_file_id)


@dataclass
class MarkingSessionOCRSummary:
    session_id: int
    total_answer_files: int
    ocr_completed_count: int
    ocr_failed_count: int
    latest_run: Optional[MainMarkingOCRRun]


def get_session_ocr_summary(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> MarkingSessionOCRSummary:
    get_owned_session(conn, teacher_id, session_id)
    answer_files = get_answer_files_for_session_record(conn, session_id)
    runs = get_ocr_runs_for_session_record(conn, session_id)
    return MarkingSessionOCRSummary(
        session_id=session_id,
        total_answer_files=len(answer_files),
        ocr_completed_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_OCR_COMPLETED),
        ocr_failed_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_OCR_FAILED),
        latest_run=runs[0] if runs else None,
    )


# --- Stage 11O: template linking / extraction-readiness foundation ----------
#
# Lets a teacher optionally link an existing (own, paper-type-matching)
# template to a Main Marking session, and reports whether that session is
# ready for a *future* answer-extraction stage. Nothing here runs
# extraction, writes an extracted answer, creates a marking job, or creates
# a review/result row - it only reads session/template/OCR state that
# already exists and reports it back to the teacher.
#
# Template compatibility is a strict paper_type equality check
# (session.paper_type == template.paper_type), deliberately mirroring the
# existing Marking Setup template dropdown's own filtering
# (refresh_marking_setup_template_dropdown in teacher_dashboard.py) rather
# than inventing new "Both" special-casing: templates don't actually
# support paper_type="Both" in a usable way today (get_allowed_region_types
# returns an empty list for it, so such a template could never hold any
# region), so a "Both" Main Marking session simply has no compatible
# templates yet, exactly like a "Both" revision material already behaves
# in Marking Setup - not a new limitation introduced by this stage.
#
# Templates cannot currently be deleted anywhere in this project (no
# delete_template function/UI exists), so main_marking_sessions.template_id
# referencing answer_templates(template_id) never faces an FK/cascade
# conflict in practice.


def _is_compatible_template_paper_type(session_paper_type: str, template_paper_type: str) -> bool:
    return template_paper_type == session_paper_type


def list_compatible_templates_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> List[TeacherTemplateRow]:
    """Return teacher_id's own templates whose paper_type matches the
    session's paper_type - candidates for assign_template_to_marking_session.
    Raises ValueError if the session isn't owned by teacher_id."""
    session = get_owned_session(conn, teacher_id, session_id)
    templates = list_templates_for_teacher(conn, teacher_id)
    return [t for t in templates if _is_compatible_template_paper_type(session.paper_type, t.paper_type)]


def assign_template_to_marking_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int, template_id: int
) -> MainMarkingSession:
    """Link template_id to a session owned by teacher_id. The template must
    also be owned by teacher_id and match the session's paper_type.

    Raises ValueError if the session or template doesn't exist / isn't
    owned by teacher_id, or the paper types don't match.
    """
    session = get_owned_session(conn, teacher_id, session_id)
    template = get_owned_template(conn, teacher_id, template_id)
    if not _is_compatible_template_paper_type(session.paper_type, template.paper_type):
        raise ValueError(
            f"Template paper type ({template.paper_type}) does not match "
            f"session paper type ({session.paper_type})."
        )
    update_session_template_id_record(conn, session_id, template_id)
    return get_session_by_id(conn, session_id)


def remove_template_from_marking_session(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> MainMarkingSession:
    """Unlink whatever template a session owned by teacher_id has linked
    (a no-op if none is linked). Never deletes the template itself - only
    clears this session's template_id."""
    get_owned_session(conn, teacher_id, session_id)
    update_session_template_id_record(conn, session_id, None)
    return get_session_by_id(conn, session_id)


@dataclass
class ExtractionTargetSummary:
    total_region_targets: int
    rectangle_targets: int
    polygon_targets: int
    rotated_targets: int
    group_targets: int
    cross_page_group_targets: int
    page_numbers: List[int]


def _compute_extraction_target_summary(conn: sqlite3.Connection, template_id: int) -> ExtractionTargetSummary:
    """Summarize template_id's Stage 11K extraction targets for teacher
    visibility - reuses list_template_extraction_targets() directly and
    read-only; never writes extraction/marking/result data."""
    targets = list_template_extraction_targets(conn, template_id)
    region_targets = [t for t in targets if t.kind == TARGET_KIND_REGION]
    group_targets = [t for t in targets if t.kind == TARGET_KIND_GROUP]

    page_numbers = set()
    for target in targets:
        page_numbers.update(target.page_numbers)

    return ExtractionTargetSummary(
        total_region_targets=len(region_targets),
        rectangle_targets=sum(1 for t in region_targets if t.shape_type == SHAPE_TYPE_RECTANGLE),
        polygon_targets=sum(1 for t in region_targets if t.shape_type == SHAPE_TYPE_POLYGON),
        rotated_targets=sum(1 for t in region_targets if t.rotation_angle),
        group_targets=len(group_targets),
        cross_page_group_targets=sum(1 for t in group_targets if len(set(t.page_numbers)) > 1),
        page_numbers=sorted(page_numbers),
    )


@dataclass
class MarkingSessionTemplateSummary:
    session_id: int
    template: Optional[AnswerTemplate]
    extraction_targets: Optional[ExtractionTargetSummary]


def get_marking_session_template_summary(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MarkingSessionTemplateSummary:
    """Return session_id's linked template (if any) plus its extraction
    target summary, for display on the Main Marking session detail page.
    Raises ValueError if the session isn't owned by teacher_id."""
    session = get_owned_session(conn, teacher_id, session_id)
    if session.template_id is None:
        return MarkingSessionTemplateSummary(session_id=session_id, template=None, extraction_targets=None)

    template = get_template_by_id(conn, session.template_id)
    if template is None:
        return MarkingSessionTemplateSummary(session_id=session_id, template=None, extraction_targets=None)

    return MarkingSessionTemplateSummary(
        session_id=session_id,
        template=template,
        extraction_targets=_compute_extraction_target_summary(conn, session.template_id),
    )


@dataclass
class MarkingSessionExtractionReadiness:
    is_ready: bool
    reason: str


def get_marking_session_extraction_readiness(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MarkingSessionExtractionReadiness:
    """Report whether session_id is ready for a *future* answer-extraction
    stage - this function never runs extraction or writes anything. Ready
    only once: OCR has completed, a template is linked, that template has
    at least one non-ignore extraction target, and at least one OCR result
    row exists. Raises ValueError if the session isn't owned by teacher_id.
    """
    session = get_owned_session(conn, teacher_id, session_id)

    if session.status not in (
        STATUS_OCR_COMPLETED, STATUS_ANSWER_EXTRACTED, STATUS_MARKED, STATUS_REVIEWED, STATUS_FINALIZED
    ):
        return MarkingSessionExtractionReadiness(is_ready=False, reason="OCR has not been completed.")

    if session.template_id is None:
        return MarkingSessionExtractionReadiness(is_ready=False, reason="No template linked.")

    target_summary = _compute_extraction_target_summary(conn, session.template_id)
    if target_summary.total_region_targets == 0:
        return MarkingSessionExtractionReadiness(is_ready=False, reason="Linked template has no answer regions.")

    answer_files = get_answer_files_for_session_record(conn, session_id)
    has_ocr_results = any(get_ocr_results_for_answer_file_record(conn, f.answer_file_id) for f in answer_files)
    if not has_ocr_results:
        return MarkingSessionExtractionReadiness(is_ready=False, reason="No OCR results available.")

    return MarkingSessionExtractionReadiness(is_ready=True, reason="Ready for answer extraction.")


# --- Stage 11P: answer-extraction foundation ---------------------------------
#
# "Run Extraction" matches each of a session's linked template's Stage 11K
# extraction targets against the session's own OCR'd page text/blocks
# (Stage 11N, extended with block storage in this same stage) and stores one
# main_marking_extracted_answers row per target per answer file. It only
# ever reads the existing generic answer_extraction_jobs/extracted_attempt_
# answers tables' *absence* of applicability - those are hardwired to the
# class-based attempt/marking-setup/question workflow and are never touched
# here. This stage never scores, never compares against an answer key,
# never creates a marking job/review, and never writes a final result -
# only raw extracted text plus a clear per-target status/message.
#
# Geometry: a plain rectangle or polygon region with rotation_angle == 0
# uses match_ocr_blocks_to_region (real OCR-block geometry matching, Stage
# 11P). Any region with a non-zero rotation - or any page whose OCR result
# has no stored block data at all (e.g. it predates Stage 11P, or the OCR
# engine/test double didn't supply blocks) - conservatively falls back to
# that page's plain OCR text, marked "needs_review" with a clear message,
# rather than risking an unproven geometry match (matches
# crop_rotated_region_from_image's own documented caveat about unconfirmed
# rotated-region pixel accuracy).
#
# Rerunning extraction for a session deletes and recreates each answer
# file's extracted-answer rows (Option A, matching Stage 11M/11N's own
# rerun precedent) so the latest visible extraction never duplicates, while
# the run itself is still recorded in main_marking_answer_extraction_runs
# for history.


def _preprocessed_image_path_for_page(conn: sqlite3.Connection, answer_file_id: int, page_number: int) -> Optional[str]:
    for page in get_preprocessed_pages_for_answer_file_record(conn, answer_file_id):
        if page.page_number == page_number and page.status == PAGE_STATUS_PREPROCESSED:
            return page.preprocessed_image_path
    return None


def _extract_text_for_region_target(
    conn: sqlite3.Connection, answer_file_id: int, region, ocr_results_by_page: dict
) -> tuple:
    """Return (extracted_text, confidence, status, message) for one region
    target on one answer file's OCR results. Never raises - any lookup/
    geometry error is converted into a 'failed' status/message instead."""
    ocr_result = ocr_results_by_page.get(region.page_number)
    if ocr_result is None or ocr_result.status != OCR_RESULT_STATUS_COMPLETED:
        return None, None, EXTRACTED_ANSWER_STATUS_NO_TEXT, f"No OCR result available for page {region.page_number}."

    if not ocr_result.ocr_blocks_json:
        return (
            ocr_result.text, ocr_result.confidence, EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
            "OCR block coordinates were not available for this page; used the full page's OCR text as a fallback.",
        )

    if get_region_rotation_angle(region):
        return (
            ocr_result.text, ocr_result.confidence, EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
            "Rotated-region text matching is not yet supported; used the full page's OCR text as a fallback.",
        )

    image_path = _preprocessed_image_path_for_page(conn, answer_file_id, region.page_number)
    if image_path is None:
        return (
            ocr_result.text, ocr_result.confidence, EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
            "Preprocessed page image was not available; used the full page's OCR text as a fallback.",
        )

    try:
        width, height = get_image_dimensions(image_path)
        matched_text = match_ocr_blocks_to_region(ocr_result.ocr_blocks_json, region, width, height)
    except Exception as exc:
        return (
            ocr_result.text, ocr_result.confidence, EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
            f"Region geometry matching failed ({exc}); used the full page's OCR text as a fallback.",
        )

    if not matched_text:
        return "", None, EXTRACTED_ANSWER_STATUS_NO_TEXT, "No OCR text was found inside this region."

    return matched_text, ocr_result.confidence, EXTRACTED_ANSWER_STATUS_EXTRACTED, None


def _extract_answers_for_answer_file(
    conn: sqlite3.Connection,
    answer_file: MainMarkingAnswerFile,
    region_targets: List[ExtractionTarget],
    group_targets: List[ExtractionTarget],
) -> None:
    """Create one main_marking_extracted_answers row per region target and
    per group target for answer_file. Never raises - each target's own
    failure is recorded as its own row so it can never stop sibling targets
    or other answer files in the same run."""
    ocr_results_by_page = {r.page_number: r for r in get_ocr_results_for_answer_file_record(conn, answer_file.answer_file_id)}
    text_by_region_id = {}

    for target in region_targets:
        region = target.source_region
        try:
            text, confidence, status, message = _extract_text_for_region_target(
                conn, answer_file.answer_file_id, region, ocr_results_by_page
            )
        except Exception as exc:
            text, confidence, status, message = None, None, EXTRACTED_ANSWER_STATUS_FAILED, str(exc)

        text_by_region_id[region.region_id] = text or ""
        add_extracted_answer_record(
            conn, answer_file.answer_file_id, TARGET_KIND_REGION, region.region_id, None,
            target.label, target.region_type, json.dumps(target.page_numbers),
            text, confidence, status, message,
        )

    for target in group_targets:
        member_texts = [text_by_region_id.get(region.region_id, "") for region in target.member_regions]
        combined_text = "\n".join(t for t in member_texts if t)
        status = EXTRACTED_ANSWER_STATUS_EXTRACTED if combined_text else EXTRACTED_ANSWER_STATUS_NO_TEXT
        add_extracted_answer_record(
            conn, answer_file.answer_file_id, TARGET_KIND_GROUP, None, target.group_id,
            target.label, target.region_type, json.dumps(target.page_numbers),
            combined_text or None, None, status,
            None if combined_text else "No member region produced any text.",
        )


def run_answer_extraction_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MainMarkingAnswerExtractionRun:
    """Run answer extraction for every answer file in a session owned by
    teacher_id, matching its linked template's Stage 11K extraction targets
    against the session's OCR results. Only stores raw extracted text/
    status - never scores, never creates a marking job/review, never
    writes a final result.

    Raises ValueError (before any run row is created) if the session isn't
    owned by teacher_id, or extraction readiness (Stage 11O) is not ready.
    """
    session = get_owned_session(conn, teacher_id, session_id)
    readiness = get_marking_session_extraction_readiness(conn, teacher_id, session_id)
    if not readiness.is_ready:
        raise ValueError(f"Session is not ready for answer extraction: {readiness.reason}")

    answer_files = get_answer_files_for_session_record(conn, session_id)

    targets = list_template_extraction_targets(conn, session.template_id)
    region_targets = [t for t in targets if t.kind == TARGET_KIND_REGION]
    group_targets = [t for t in targets if t.kind == TARGET_KIND_GROUP]

    for answer_file in answer_files:
        delete_extracted_answers_for_answer_file_record(conn, answer_file.answer_file_id)

    run = create_answer_extraction_run_record(conn, session_id)

    success_count = 0
    failure_labels = []
    for answer_file in answer_files:
        try:
            _extract_answers_for_answer_file(conn, answer_file, region_targets, group_targets)
            update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_ANSWER_EXTRACTED)
            success_count += 1
        except Exception as exc:
            failure_labels.append(f"{get_answer_file_display_name(answer_file)}: {exc}")

    if success_count > 0:
        update_session_status(conn, session_id, STATUS_ANSWER_EXTRACTED)

    total = len(answer_files)
    if not failure_labels:
        message = f"Answer extraction completed for {total} answer file(s)."
        mark_answer_extraction_run_completed(conn, run.run_id, message)
    else:
        message = (
            f"{success_count} of {total} answer file(s) completed answer extraction. "
            f"Failed: {'; '.join(failure_labels)}."
        )
        if success_count > 0:
            mark_answer_extraction_run_completed(conn, run.run_id, message)
        else:
            mark_answer_extraction_run_failed(conn, run.run_id, message)

    return get_answer_extraction_runs_for_session_record(conn, session_id)[0]


def list_answer_extraction_runs_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> List[MainMarkingAnswerExtractionRun]:
    get_owned_session(conn, teacher_id, session_id)
    return get_answer_extraction_runs_for_session_record(conn, session_id)


def list_extracted_answers_for_answer_file(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int
) -> List[MainMarkingExtractedAnswer]:
    """Raises ValueError if the answer file doesn't exist or its session
    isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)
    return get_extracted_answers_for_answer_file_record(conn, answer_file_id)


@dataclass
class MarkingSessionAnswerExtractionSummary:
    session_id: int
    total_answer_files: int
    extracted_count: int
    latest_run: Optional[MainMarkingAnswerExtractionRun]


def get_session_answer_extraction_summary(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MarkingSessionAnswerExtractionSummary:
    get_owned_session(conn, teacher_id, session_id)
    answer_files = get_answer_files_for_session_record(conn, session_id)
    runs = get_answer_extraction_runs_for_session_record(conn, session_id)
    return MarkingSessionAnswerExtractionSummary(
        session_id=session_id,
        total_answer_files=len(answer_files),
        extracted_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_ANSWER_EXTRACTED),
        latest_run=runs[0] if runs else None,
    )


# --- Stage 11Q: Kertas 1 rule-based marking foundation -----------------------
#
# "Run Marking" compares each of a session's extracted answers (Stage 11P)
# against a correct answer sourced from the existing Marking Setup feature
# (app/models/marking_setup_model.py) - specifically, a marking_questions
# row whose region_id matches the extracted answer's own region_id, found
# via a marking_setups row configured against the SAME template this
# session links to (Stage 11O). This is preferred-match-route #1 from the
# spec ("marking setup linked region ID matches extracted answer
# region_id") - no label/name-based fuzzy matching is used. If no marking
# setup exists for the template (or a region has no linked question), that
# target is marked needs_review with a clear message rather than guessing.
#
# Comparison itself reimplements app/services/kertas1_marking_service.py's
# own simple deterministic rule (single-letter case-insensitive match for
# mcq/written_letter question types, else whitespace-normalized case-
# insensitive exact text match) rather than importing that module's private
# helper - this keeps Main Marking's marking self-contained from the class-
# attempt workflow, exactly like Stage 11P did for extraction. No AI, no
# fuzzy similarity, no spelling-deduction logic (out of scope for this
# foundation stage) - a wrong answer is simply scored 0, not needs_review.
#
# Group targets: marking_questions has no group_id column at all, so there
# is no non-guessing way to link a correct answer to a combined group
# output. Per the spec's explicit guidance, every group-kind extracted
# answer is marked needs_review with a clear explanatory message - member
# regions are still marked individually and are unaffected.
#
# This stage only ever reads main_marking_extracted_answers/marking_setups/
# marking_questions and writes to its own new main_marking_marking_runs/
# main_marking_marked_answers tables - it never touches marking_jobs,
# marking_question_results, marking_reviews, or any finalized-results table.
#
# Rerunning marking for a session deletes and recreates each answer file's
# marked-answer rows (Option A, matching Stage 11M/11N/11P's own rerun
# precedent) so the latest visible marking never duplicates, while the run
# itself is still recorded in main_marking_marking_runs for history.

_KERTAS1_SINGLE_LETTER_QUESTION_TYPES = (QUESTION_TYPE_MCQ, QUESTION_TYPE_WRITTEN_LETTER)
_DEFAULT_MARKED_ANSWER_MAX_SCORE = 1.0

_NO_MARKING_SETUP_MESSAGE = "No marking setup / correct answer is configured for this template."
_NO_CORRECT_ANSWER_MESSAGE = "No correct answer is configured for this region in the marking setup."
_MISSING_EXTRACTED_ANSWER_MESSAGE = "No extracted answer was found for this region."
_NO_EXTRACTED_ANSWER_MESSAGE = "No usable extracted text is available for this region."
_GROUP_MARKING_MESSAGE = (
    "Automatic marking of grouped answer targets is not supported yet - the marking setup has no way to "
    "link a correct answer to a region group. Mark this manually."
)
_MATCH_MESSAGE = "Answer matches the correct answer."
_MISMATCH_MESSAGE = "Answer does not match the correct answer."


def _normalize_whitespace_for_marking(text: Optional[str]) -> str:
    return " ".join((text or "").strip().split())


def _is_clean_single_letter_for_marking(text: Optional[str]) -> bool:
    stripped = (text or "").strip()
    return len(stripped) == 1 and stripped.isalpha()


def _kertas1_texts_match(question_type: str, student_text: Optional[str], correct_text: str) -> bool:
    """Deterministic, rule-based comparison - no AI, no fuzzy similarity."""
    if question_type in _KERTAS1_SINGLE_LETTER_QUESTION_TYPES:
        if not _is_clean_single_letter_for_marking(student_text) or not _is_clean_single_letter_for_marking(correct_text):
            return False
        return student_text.strip().upper() == correct_text.strip().upper()
    return _normalize_whitespace_for_marking(student_text).lower() == _normalize_whitespace_for_marking(correct_text).lower()


def _mark_answers_for_answer_file(
    conn: sqlite3.Connection,
    answer_file: MainMarkingAnswerFile,
    targets: List[ExtractionTarget],
    questions_by_region_id: dict,
    has_marking_setup: bool,
) -> None:
    """Create one main_marking_marked_answers row per template extraction
    target (Stage 11K) for answer_file - the same target set Stage 11P's
    extraction itself iterates over, so a target with no matching extracted
    answer at all (e.g. the template gained a region after the last
    extraction run) is still marked needs_review rather than silently
    skipped. Never raises - each target's own failure is recorded as its
    own needs_review row so it can never stop sibling targets or other
    answer files in the same run."""
    extracted_by_region_id = {}
    extracted_by_group_id = {}
    for extracted in get_extracted_answers_for_answer_file_record(conn, answer_file.answer_file_id):
        if extracted.target_kind == TARGET_KIND_GROUP:
            extracted_by_group_id[extracted.group_id] = extracted
        else:
            extracted_by_region_id[extracted.region_id] = extracted

    for target in targets:
        if target.kind == TARGET_KIND_GROUP:
            extracted = extracted_by_group_id.get(target.group_id)
            add_marked_answer_record(
                conn, answer_file.answer_file_id, extracted.extracted_answer_id if extracted else None,
                TARGET_KIND_GROUP, target.label, target.region_type,
                extracted.extracted_text if extracted else None, None, None,
                _DEFAULT_MARKED_ANSWER_MAX_SCORE, MARKED_ANSWER_STATUS_NEEDS_REVIEW, _GROUP_MARKING_MESSAGE, True,
            )
            continue

        region_id = target.region_id
        question = questions_by_region_id.get(region_id)
        extracted = extracted_by_region_id.get(region_id)

        if question is None:
            message = _NO_CORRECT_ANSWER_MESSAGE if has_marking_setup else _NO_MARKING_SETUP_MESSAGE
            add_marked_answer_record(
                conn, answer_file.answer_file_id, extracted.extracted_answer_id if extracted else None,
                TARGET_KIND_REGION, target.label, target.region_type,
                extracted.extracted_text if extracted else None, None, 0.0,
                _DEFAULT_MARKED_ANSWER_MAX_SCORE, MARKED_ANSWER_STATUS_NEEDS_REVIEW, message, True,
            )
            continue

        if extracted is None:
            add_marked_answer_record(
                conn, answer_file.answer_file_id, None, TARGET_KIND_REGION, target.label, target.region_type,
                None, question.correct_answer, 0.0, question.max_mark, MARKED_ANSWER_STATUS_NEEDS_REVIEW,
                _MISSING_EXTRACTED_ANSWER_MESSAGE, True,
            )
            continue

        if extracted.status != EXTRACTED_ANSWER_STATUS_EXTRACTED or not (extracted.extracted_text or "").strip():
            add_marked_answer_record(
                conn, answer_file.answer_file_id, extracted.extracted_answer_id, TARGET_KIND_REGION,
                target.label, target.region_type, extracted.extracted_text,
                question.correct_answer, 0.0, question.max_mark, MARKED_ANSWER_STATUS_NEEDS_REVIEW,
                _NO_EXTRACTED_ANSWER_MESSAGE, True,
            )
            continue

        if _kertas1_texts_match(question.question_type, extracted.extracted_text, question.correct_answer):
            add_marked_answer_record(
                conn, answer_file.answer_file_id, extracted.extracted_answer_id, TARGET_KIND_REGION,
                target.label, target.region_type, extracted.extracted_text,
                question.correct_answer, question.max_mark, question.max_mark, MARKED_ANSWER_STATUS_MARKED,
                _MATCH_MESSAGE, False,
            )
        else:
            add_marked_answer_record(
                conn, answer_file.answer_file_id, extracted.extracted_answer_id, TARGET_KIND_REGION,
                target.label, target.region_type, extracted.extracted_text,
                question.correct_answer, 0.0, question.max_mark, MARKED_ANSWER_STATUS_MARKED,
                _MISMATCH_MESSAGE, False,
            )


def run_kertas1_marking_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MainMarkingMarkingRun:
    """Run Kertas 1 rule-based draft marking for every answer file in a
    session owned by teacher_id. Only stores draft scores/status - never
    finalizes a result, never creates a teacher-review row.

    Raises ValueError (before any run row is created) if the session isn't
    owned by teacher_id, isn't Kertas 1, hasn't had answer extraction run,
    has no linked template, or has no extracted answers at all.
    """
    session = get_owned_session(conn, teacher_id, session_id)

    if session.paper_type != PAPER_TYPE_KERTAS_1:
        raise ValueError(
            f"{session.paper_type} marking is not supported in this stage. "
            "Only Kertas 1 rule-based marking is available."
        )

    if session.status not in (STATUS_ANSWER_EXTRACTED, STATUS_MARKED, STATUS_REVIEWED, STATUS_FINALIZED):
        raise ValueError("Run answer extraction successfully before running marking.")

    if session.template_id is None:
        raise ValueError("Link a template before running marking.")

    answer_files = get_answer_files_for_session_record(conn, session_id)
    if not answer_files:
        raise ValueError("Upload at least one student answer PDF before running marking.")

    has_extracted_answers = any(
        get_extracted_answers_for_answer_file_record(conn, f.answer_file_id) for f in answer_files
    )
    if not has_extracted_answers:
        raise ValueError("Run answer extraction successfully before running marking.")

    marking_setups = get_marking_setups_by_template(conn, session.template_id)
    kertas1_setup = next((s for s in marking_setups if s.paper_type == PAPER_TYPE_KERTAS_1), None)
    questions_by_region_id: dict = {}
    if kertas1_setup is not None:
        for question in get_marking_questions_for_setup(conn, kertas1_setup.setup_id):
            if question.region_id is not None:
                questions_by_region_id[question.region_id] = question

    targets = list_template_extraction_targets(conn, session.template_id)

    for answer_file in answer_files:
        delete_marked_answers_for_answer_file_record(conn, answer_file.answer_file_id)
        # Stage 11S rerun-safety: a rerun invalidates any machine
        # score/feedback a previous finalized snapshot was built from, so
        # that stale snapshot must not keep appearing on the Results page.
        delete_final_result_for_answer_file_record(conn, answer_file.answer_file_id)

    run = create_marking_run_record(conn, session_id)

    success_count = 0
    failure_labels = []
    for answer_file in answer_files:
        try:
            _mark_answers_for_answer_file(conn, answer_file, targets, questions_by_region_id, kertas1_setup is not None)
            update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_MARKED)
            success_count += 1
        except Exception as exc:
            update_answer_file_processing_status(conn, answer_file.answer_file_id, PROCESSING_STATUS_MARKING_FAILED)
            failure_labels.append(f"{get_answer_file_display_name(answer_file)}: {exc}")

    if success_count > 0:
        update_session_status(conn, session_id, STATUS_MARKED)

    total = len(answer_files)
    if not failure_labels:
        message = f"Marking completed for {total} answer file(s)."
        mark_marking_run_completed(conn, run.run_id, message)
    else:
        message = (
            f"{success_count} of {total} answer file(s) completed marking. "
            f"Failed: {'; '.join(failure_labels)}."
        )
        if success_count > 0:
            mark_marking_run_completed(conn, run.run_id, message)
        else:
            mark_marking_run_failed(conn, run.run_id, message)

    return get_marking_runs_for_session_record(conn, session_id)[0]


def list_marking_runs_for_session(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> List[MainMarkingMarkingRun]:
    get_owned_session(conn, teacher_id, session_id)
    return get_marking_runs_for_session_record(conn, session_id)


def list_marked_answers_for_answer_file(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int
) -> List[MainMarkingMarkedAnswer]:
    """Raises ValueError if the answer file doesn't exist or its session
    isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)
    return get_marked_answers_for_answer_file_record(conn, answer_file_id)


@dataclass
class MarkingSessionMarkingSummary:
    session_id: int
    total_answer_files: int
    marked_count: int
    latest_run: Optional[MainMarkingMarkingRun]


def get_session_marking_summary(
    conn: sqlite3.Connection, teacher_id: int, session_id: int
) -> MarkingSessionMarkingSummary:
    get_owned_session(conn, teacher_id, session_id)
    answer_files = get_answer_files_for_session_record(conn, session_id)
    runs = get_marking_runs_for_session_record(conn, session_id)
    return MarkingSessionMarkingSummary(
        session_id=session_id,
        total_answer_files=len(answer_files),
        marked_count=sum(1 for f in answer_files if f.processing_status == PROCESSING_STATUS_MARKED),
        latest_run=runs[0] if runs else None,
    )


# --- Stage 11R: teacher review / override foundation -------------------------
#
# Lets a teacher accept or override each Kertas 1 draft-marked answer's
# score/feedback (Stage 11Q) and mark it reviewed. Overrides are stored in
# main_marking_marked_answers' own review_status/teacher_score/
# teacher_feedback/reviewed_at columns (Stage 11R) - the machine-generated
# score/feedback/status/needs_review columns are NEVER modified by a
# review, mirroring the existing class-based marking_reviews/marking_
# review_items pattern of never mutating the original auto-marking result
# (just via extra columns on the same row here, rather than a second
# table - safe because main_marking_marked_answers is Main Marking's own
# table, not shared with that older workflow).
#
# This stage never creates a finalized Results row and never touches the
# Results page - "reviewed" is purely a Main Marking review-progress status,
# not a publication step.
#
# Rerun note: Stage 11Q's "Run Marking" rerun already deletes and recreates
# an answer file's main_marking_marked_answers rows (Option A). Since
# review fields live on those same rows, rerunning marking after a review
# has been saved will reset that file's review progress back to
# "pending_review" on the new rows, exactly like it already resets
# machine scores - this is documented, expected behavior, not a bug.


@dataclass
class ReviewableMainMarkingFile:
    session_id: int
    session_title: str
    paper_type: str
    answer_file_id: int
    answer_file_display_name: str
    student_name: Optional[str]
    student_code: Optional[str]
    processing_status: str
    total_marked_answers: int
    reviewed_count: int


def list_reviewable_main_marking_files(conn: sqlite3.Connection, teacher_id: int) -> List[ReviewableMainMarkingFile]:
    """Return every Kertas 1 answer file belonging to teacher_id that has
    been through Run Marking at least once (processing_status 'marked' or
    'reviewed'), for the Review page. Kertas 2 sessions are never included
    - Kertas 2 marking/review remains unsupported."""
    reviewable = []
    for session_row in get_sessions_for_teacher_record(conn, teacher_id):
        if session_row.paper_type != PAPER_TYPE_KERTAS_1:
            continue
        for answer_file in get_answer_files_for_session_record(conn, session_row.session_id):
            if answer_file.processing_status not in (PROCESSING_STATUS_MARKED, PROCESSING_STATUS_REVIEWED):
                continue
            marked_answers = get_marked_answers_for_answer_file_record(conn, answer_file.answer_file_id)
            reviewable.append(
                ReviewableMainMarkingFile(
                    session_id=session_row.session_id,
                    session_title=session_row.title,
                    paper_type=session_row.paper_type,
                    answer_file_id=answer_file.answer_file_id,
                    answer_file_display_name=get_answer_file_display_name(answer_file),
                    student_name=answer_file.student_name,
                    student_code=answer_file.student_code,
                    processing_status=answer_file.processing_status,
                    total_marked_answers=len(marked_answers),
                    reviewed_count=sum(1 for m in marked_answers if m.review_status == REVIEW_STATUS_REVIEWED),
                )
            )
    return reviewable


def get_marked_answers_for_review(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int
) -> List[MainMarkingMarkedAnswer]:
    """Raises ValueError if the answer file doesn't exist or its session
    isn't owned by teacher_id."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)
    return get_marked_answers_for_answer_file_record(conn, answer_file_id)


def review_marked_answer(
    conn: sqlite3.Connection,
    teacher_id: int,
    marked_answer_id: int,
    teacher_score: float,
    teacher_feedback: Optional[str] = None,
) -> MainMarkingMarkedAnswer:
    """Save a teacher's score/feedback override for one marked answer and
    mark it reviewed. Empty/None teacher_feedback is allowed.

    Raises ValueError if the marked answer doesn't exist, its session isn't
    owned by teacher_id, teacher_score isn't numeric, or teacher_score is
    outside [0, max_score].
    """
    marked_answer = get_marked_answer_by_id(conn, marked_answer_id)
    if marked_answer is None:
        raise ValueError("Marked answer not found.")

    answer_file = get_answer_file_by_id(conn, marked_answer.answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    get_owned_session(conn, teacher_id, answer_file.session_id)

    try:
        teacher_score = float(teacher_score)
    except (TypeError, ValueError):
        raise ValueError("Teacher score must be a number.")

    if teacher_score < 0:
        raise ValueError("Teacher score cannot be negative.")
    if teacher_score > marked_answer.max_score:
        raise ValueError(f"Teacher score cannot exceed the max score ({marked_answer.max_score}).")

    update_marked_answer_review_record(conn, marked_answer_id, teacher_score, teacher_feedback or None)
    return get_marked_answer_by_id(conn, marked_answer_id)


def mark_answer_file_reviewed(conn: sqlite3.Connection, teacher_id: int, answer_file_id: int) -> MainMarkingAnswerFile:
    """Mark answer_file_id as reviewed once every one of its marked answers
    has review_status='reviewed'. If at least one other answer file in the
    same session was already reviewed (or this is the first), the session
    itself also moves to 'reviewed' - matching every earlier stage's "at
    least one file done" session-status rule.

    Raises ValueError if the answer file doesn't exist, its session isn't
    owned by teacher_id, it has no marked answers, or not all of its marked
    answers have been reviewed yet.
    """
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    session = get_owned_session(conn, teacher_id, answer_file.session_id)

    marked_answers = get_marked_answers_for_answer_file_record(conn, answer_file_id)
    if not marked_answers:
        raise ValueError("This answer file has no marked answers to review.")

    unreviewed_count = sum(1 for m in marked_answers if m.review_status != REVIEW_STATUS_REVIEWED)
    if unreviewed_count > 0:
        raise ValueError(
            f"Not all answers have been reviewed yet ({unreviewed_count} of {len(marked_answers)} remaining)."
        )

    update_answer_file_processing_status(conn, answer_file_id, PROCESSING_STATUS_REVIEWED)
    if session.status != STATUS_REVIEWED:
        update_session_status(conn, session.session_id, STATUS_REVIEWED)

    return get_answer_file_by_id(conn, answer_file_id)


@dataclass
class MainMarkingReviewSummary:
    total_reviewable_files: int
    fully_reviewed_files: int
    partially_reviewed_files: int
    pending_files: int


def get_main_marking_review_summary(conn: sqlite3.Connection, teacher_id: int) -> MainMarkingReviewSummary:
    files = list_reviewable_main_marking_files(conn, teacher_id)
    fully_reviewed = sum(1 for f in files if f.total_marked_answers > 0 and f.reviewed_count == f.total_marked_answers)
    partially_reviewed = sum(1 for f in files if 0 < f.reviewed_count < f.total_marked_answers)
    pending = sum(1 for f in files if f.reviewed_count == 0)
    return MainMarkingReviewSummary(
        total_reviewable_files=len(files),
        fully_reviewed_files=fully_reviewed,
        partially_reviewed_files=partially_reviewed,
        pending_files=pending,
    )


# --- Stage 11S: final result finalization foundation ------------------------
#
# Lets a teacher "publish" one fully-reviewed Kertas 1 answer file as a
# finalized result that appears on the Results page. Finalizing takes a
# frozen snapshot of that file's main_marking_marked_answers rows (Stage
# 11Q/11R) into main_marking_final_results / main_marking_final_result_items
# rather than reading them live, because Stage 11Q's "Run Marking" rerun
# already unconditionally deletes and recreates those rows (and Stage 11R's
# review fields live on the very same rows) - a live-query Results view
# would make a "finalized" result silently change or vanish under a rerun.
# This deliberately differs from the existing class-based Results system
# (app/services/result_summary_service.py), which has no snapshot table of
# its own and queries marking_reviews/kertas2_feedback_reviews live; that
# system is untouched by this stage.
#
# Per item, final_score/final_feedback prefer the teacher's override
# (teacher_score/teacher_feedback) and fall back to the machine-generated
# score/feedback only when no override was saved on that row - this can only
# happen if an answer file's processing_status was already 'reviewed'
# (satisfying the precondition below) while an individual row somehow has no
# teacher_score, which should not occur via the normal review flow but is
# handled safely rather than crashing.
#
# Rerun-safety: run_kertas1_marking_for_session (Stage 11Q) now also deletes
# any existing final result for each answer file it reruns marking for, so a
# stale finalized snapshot never lingers once its underlying machine marking
# has been redone. The answer file/session status naturally moves back to
# 'marked' by that same function, requiring a fresh review + finalize before
# reappearing on the Results page.


def finalize_main_marking_answer_file(
    conn: sqlite3.Connection, teacher_id: int, answer_file_id: int
) -> MainMarkingFinalResult:
    """Finalize one reviewed Kertas 1 answer file, snapshotting its marked
    answers into a main_marking_final_results row (replacing any existing
    final result for the same answer file, so finalizing again never
    duplicates). The answer file and its session both move to status
    'finalized'.

    Raises ValueError if the answer file doesn't exist, its session isn't
    owned by teacher_id, its session isn't Kertas 1, it has no marked
    answers, or it hasn't been fully reviewed yet.
    """
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    session = get_owned_session(conn, teacher_id, answer_file.session_id)

    if session.paper_type != PAPER_TYPE_KERTAS_1:
        raise ValueError(
            f"{session.paper_type} finalization is not supported in this stage. "
            "Only Kertas 1 results can be finalized."
        )

    marked_answers = get_marked_answers_for_answer_file_record(conn, answer_file_id)
    if not marked_answers:
        raise ValueError("Run marking before finalizing this answer file.")

    is_reviewed = answer_file.processing_status in (PROCESSING_STATUS_REVIEWED, PROCESSING_STATUS_FINALIZED) or all(
        m.review_status == REVIEW_STATUS_REVIEWED for m in marked_answers
    )
    if not is_reviewed:
        raise ValueError("Review and mark this answer file as reviewed before finalizing it.")

    delete_final_result_for_answer_file_record(conn, answer_file_id)

    total_score = 0.0
    max_score_sum = 0.0
    for m in marked_answers:
        final_score = m.teacher_score if m.teacher_score is not None else (m.score or 0.0)
        total_score += final_score
        max_score_sum += m.max_score

    result = create_final_result_record(
        conn,
        session_id=session.session_id,
        answer_file_id=answer_file_id,
        teacher_id=teacher_id,
        paper_type=session.paper_type,
        student_name=answer_file.student_name,
        student_code=answer_file.student_code,
        answer_file_display_name=get_answer_file_display_name(answer_file),
        total_score=total_score,
        max_score=max_score_sum,
    )

    for m in marked_answers:
        final_score = m.teacher_score if m.teacher_score is not None else (m.score or 0.0)
        final_feedback = m.teacher_feedback if m.teacher_feedback else m.feedback
        add_final_result_item_record(
            conn,
            result_id=result.result_id,
            marked_answer_id=m.marked_answer_id,
            target_label=m.target_label,
            target_kind=m.target_kind,
            region_type=m.region_type,
            student_answer_text=m.student_answer_text,
            correct_answer_text=m.correct_answer_text,
            machine_score=m.score,
            teacher_score=m.teacher_score,
            final_score=final_score,
            max_score=m.max_score,
            machine_feedback=m.feedback,
            teacher_feedback=m.teacher_feedback,
            final_feedback=final_feedback,
            reviewed_at=m.reviewed_at,
        )

    update_answer_file_processing_status(conn, answer_file_id, PROCESSING_STATUS_FINALIZED)
    if session.status != STATUS_FINALIZED:
        update_session_status(conn, session.session_id, STATUS_FINALIZED)

    return get_final_result_by_id_record(conn, result.result_id)


@dataclass
class MainMarkingFinalResultRow:
    result: MainMarkingFinalResult
    session_title: str


def list_main_marking_final_results_for_teacher(
    conn: sqlite3.Connection, teacher_id: int
) -> List[MainMarkingFinalResultRow]:
    """Return every finalized Main Marking result belonging to teacher_id,
    newest first, for the Results page's Main Marking section."""
    results = get_final_results_for_teacher_record(conn, teacher_id)
    session_titles: dict = {}
    rows = []
    for result in results:
        if result.session_id not in session_titles:
            session = get_session_by_id(conn, result.session_id)
            session_titles[result.session_id] = session.title if session else ""
        rows.append(MainMarkingFinalResultRow(result=result, session_title=session_titles[result.session_id]))
    return rows


@dataclass
class MainMarkingFinalResultDetail:
    result: MainMarkingFinalResult
    session_title: str
    items: List[MainMarkingFinalResultItem]


def get_main_marking_final_result_detail(
    conn: sqlite3.Connection, teacher_id: int, result_id: int
) -> MainMarkingFinalResultDetail:
    """Raises ValueError if the final result doesn't exist or isn't owned by
    teacher_id."""
    result = get_final_result_by_id_record(conn, result_id)
    if result is None:
        raise ValueError("Final result not found.")
    if result.teacher_id != teacher_id:
        raise ValueError("You can only view your own final results.")

    session = get_session_by_id(conn, result.session_id)
    items = get_final_result_items_record(conn, result_id)
    return MainMarkingFinalResultDetail(result=result, session_title=session.title if session else "", items=items)


def delete_main_marking_final_result(conn: sqlite3.Connection, teacher_id: int, result_id: int) -> None:
    """Hard-delete a finalized Main Marking result and ALL of its dependent
    data (Data Management Readiness Fix). Deletes the underlying
    main_marking_answer_files row - with PRAGMA foreign_keys=ON (see
    app.database.db.get_connection), ON DELETE CASCADE removes every row
    that references it in the same atomic DELETE statement: main_marking_
    preprocessed_pages, main_marking_ocr_results, main_marking_extracted_
    answers, main_marking_marked_answers, subject_profile_extracted_
    answers, subject_profile_marked_answers, subject_profile_overlays, and
    this final result row itself (whose own main_marking_final_result_items
    cascade one level further). Never touches the session, other answer
    files in the same session, the student account, the Subject Profile,
    or its original PDFs.

    Raises ValueError (leaving the database completely untouched) if the
    result doesn't exist or isn't owned by teacher_id. On-disk cleanup (the
    answer file's own uploaded PDF and its per-answer-file preprocessed/
    original page-image folder) is attempted only after the DB delete
    commits, and is best-effort - a disk-cleanup failure is swallowed
    rather than reported as an overall delete failure, since the
    authoritative database state is already correctly deleted by then."""
    result = get_final_result_by_id_record(conn, result_id)
    if result is None:
        raise ValueError("Final result not found.")
    if result.teacher_id != teacher_id:
        raise ValueError("You can only delete your own final results.")

    answer_file = get_answer_file_by_id(conn, result.answer_file_id)

    try:
        conn.execute("DELETE FROM main_marking_answer_files WHERE answer_file_id = ?", (result.answer_file_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if answer_file is not None:
        _delete_answer_file_disk_data(result.session_id, answer_file)


def _delete_answer_file_disk_data(session_id: int, answer_file: MainMarkingAnswerFile) -> None:
    """Best-effort on-disk cleanup for one deleted answer file - never
    raises. Only removes data exclusively scoped to this one answer_file:
    its own uploaded PDF and its own answer_file_{id}/ subfolder. Never
    touches the session's own folder or any other answer file's files."""
    import shutil

    from app.utils.file_storage import MAIN_MARKING_SESSIONS_DIR

    try:
        if answer_file.file_path and Path(answer_file.file_path).is_file():
            Path(answer_file.file_path).unlink()
    except OSError:
        pass

    answer_file_folder = MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}" / f"answer_file_{answer_file.answer_file_id}"
    try:
        if answer_file_folder.is_dir():
            shutil.rmtree(answer_file_folder)
    except OSError:
        pass


@dataclass
class MainMarkingFinalResultSummary:
    total_finalized_results: int


def get_main_marking_final_result_summary(conn: sqlite3.Connection, teacher_id: int) -> MainMarkingFinalResultSummary:
    results = get_final_results_for_teacher_record(conn, teacher_id)
    return MainMarkingFinalResultSummary(total_finalized_results=len(results))
