"""Main Marking System session data model and database access functions
(Stage 11L, extended in Stage 11M, Stage 11N, Stage 11O, Stage 11P,
Stage 11Q, Stage 11R, and Stage 11S).

A marking session is a standalone, class-independent unit: a teacher
attaches a question paper and an answer key/marking scheme, then uploads
one or more student answer PDFs - each PDF belongs to exactly one session
and represents exactly one student's answer script (which may itself span
multiple pages). This file only stores session/file/processing-run/OCR-run
metadata - the actual PDF-to-image preprocessing and OCR both happen in
app.services.main_marking_service, and no answer extraction or marking
result computation happens anywhere yet.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_DRAFT = "draft"
STATUS_PREPROCESSED = "preprocessed"
STATUS_OCR_COMPLETED = "ocr_completed"
STATUS_ANSWER_EXTRACTED = "answer_extracted"
STATUS_MARKED = "marked"
STATUS_REVIEWED = "reviewed"
STATUS_FINALIZED = "finalized"

PROCESSING_STATUS_UPLOADED = "uploaded"
PROCESSING_STATUS_PREPROCESSED = "preprocessed"
PROCESSING_STATUS_FAILED = "failed"
PROCESSING_STATUS_OCR_COMPLETED = "ocr_completed"
PROCESSING_STATUS_OCR_FAILED = "ocr_failed"
PROCESSING_STATUS_ANSWER_EXTRACTED = "answer_extracted"
PROCESSING_STATUS_MARKED = "marked"
PROCESSING_STATUS_MARKING_FAILED = "marking_failed"
PROCESSING_STATUS_REVIEWED = "reviewed"
PROCESSING_STATUS_FINALIZED = "finalized"

REVIEW_STATUS_PENDING_REVIEW = "pending_review"
REVIEW_STATUS_REVIEWED = "reviewed"

FINAL_RESULT_STATUS_FINALIZED = "finalized"

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"

PAGE_STATUS_PREPROCESSED = "preprocessed"
PAGE_STATUS_FAILED = "failed"

OCR_RESULT_STATUS_COMPLETED = "ocr_completed"
OCR_RESULT_STATUS_FAILED = "ocr_failed"

EXTRACTED_ANSWER_STATUS_EXTRACTED = "extracted"
EXTRACTED_ANSWER_STATUS_NO_TEXT = "no_text"
EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW = "needs_review"
EXTRACTED_ANSWER_STATUS_FAILED = "failed"

MARKED_ANSWER_STATUS_MARKED = "marked"
MARKED_ANSWER_STATUS_NEEDS_REVIEW = "needs_review"
MARKED_ANSWER_STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MainMarkingSession:
    session_id: int
    teacher_id: int
    title: str
    paper_type: str
    question_paper_path: Optional[str]
    answer_key_path: Optional[str]
    status: str
    created_at: str
    updated_at: Optional[str]
    # Stage 11O: optional link to an answer_templates row for future answer
    # extraction. NULL for every pre-Stage-11O session and for any session
    # the teacher hasn't linked a template to yet - a session is always
    # valid and usable without one.
    template_id: Optional[int] = None


@dataclass
class MainMarkingSessionRow:
    """One row per session owned by a teacher, with its answer file count."""

    session_id: int
    teacher_id: int
    title: str
    paper_type: str
    question_paper_path: Optional[str]
    answer_key_path: Optional[str]
    status: str
    created_at: str
    updated_at: Optional[str]
    answer_file_count: int
    template_id: Optional[int] = None


@dataclass
class MainMarkingAnswerFile:
    answer_file_id: int
    session_id: int
    file_path: str
    original_filename: Optional[str]
    student_name: Optional[str]
    student_code: Optional[str]
    detected_student_name: Optional[str]
    detected_student_code: Optional[str]
    page_count: Optional[int]
    processing_status: str
    created_at: str


@dataclass
class MainMarkingProcessingRun:
    run_id: int
    session_id: int
    status: str
    started_at: str
    completed_at: Optional[str]
    message: Optional[str]


@dataclass
class MainMarkingPreprocessedPage:
    page_id: int
    answer_file_id: int
    page_number: int
    preprocessed_image_path: Optional[str]
    status: str
    message: Optional[str]
    created_at: str
    original_image_path: Optional[str] = None


@dataclass
class MainMarkingOCRRun:
    run_id: int
    session_id: int
    status: str
    started_at: str
    completed_at: Optional[str]
    message: Optional[str]


@dataclass
class MainMarkingOCRResult:
    result_id: int
    answer_file_id: int
    page_number: int
    text: Optional[str]
    confidence: Optional[float]
    status: str
    message: Optional[str]
    created_at: str
    # Stage 11P: nullable snapshot of the OCR engine's per-block text/
    # confidence/pixel-space box output, used for geometry-based answer
    # extraction. NULL for every pre-Stage-11P row.
    ocr_blocks_json: Optional[str] = None


@dataclass
class MainMarkingAnswerExtractionRun:
    run_id: int
    session_id: int
    status: str
    started_at: str
    completed_at: Optional[str]
    message: Optional[str]


@dataclass
class MainMarkingExtractedAnswer:
    extracted_answer_id: int
    answer_file_id: int
    target_kind: str
    region_id: Optional[int]
    group_id: Optional[int]
    target_label: str
    region_type: Optional[str]
    page_numbers_json: str
    extracted_text: Optional[str]
    confidence: Optional[float]
    status: str
    message: Optional[str]
    created_at: str


@dataclass
class MainMarkingMarkingRun:
    run_id: int
    session_id: int
    status: str
    started_at: str
    completed_at: Optional[str]
    message: Optional[str]


@dataclass
class MainMarkingMarkedAnswer:
    marked_answer_id: int
    answer_file_id: int
    extracted_answer_id: Optional[int]
    target_kind: str
    target_label: str
    region_type: Optional[str]
    student_answer_text: Optional[str]
    correct_answer_text: Optional[str]
    score: Optional[float]
    max_score: float
    status: str
    feedback: Optional[str]
    needs_review: int
    created_at: str
    # Stage 11R: teacher review/override fields, stored separately from the
    # machine-generated score/feedback/status/needs_review above (which are
    # never overwritten by a review). NULL/"pending_review" for every
    # pre-Stage-11R row and every row not yet reviewed by a teacher.
    review_status: str = REVIEW_STATUS_PENDING_REVIEW
    teacher_score: Optional[float] = None
    teacher_feedback: Optional[str] = None
    reviewed_at: Optional[str] = None


@dataclass
class MainMarkingFinalResult:
    """A frozen snapshot of one finalized answer file (Stage 11S) - the
    Results page's Main Marking source of truth, decoupled from the live
    main_marking_marked_answers rows a future marking rerun may reset."""

    result_id: int
    session_id: int
    answer_file_id: int
    teacher_id: int
    paper_type: str
    student_name: Optional[str]
    student_code: Optional[str]
    answer_file_display_name: str
    total_score: float
    max_score: float
    status: str
    finalized_at: str
    message: Optional[str]


@dataclass
class MainMarkingFinalResultItem:
    item_id: int
    result_id: int
    marked_answer_id: Optional[int]
    target_label: str
    target_kind: str
    region_type: Optional[str]
    student_answer_text: Optional[str]
    correct_answer_text: Optional[str]
    machine_score: Optional[float]
    teacher_score: Optional[float]
    final_score: float
    max_score: float
    machine_feedback: Optional[str]
    teacher_feedback: Optional[str]
    final_feedback: Optional[str]
    reviewed_at: Optional[str]
    created_at: str


def create_session(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    question_paper_path: Optional[str] = None,
    answer_key_path: Optional[str] = None,
) -> MainMarkingSession:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_sessions "
        "(teacher_id, title, paper_type, question_paper_path, answer_key_path, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (teacher_id, title, paper_type, question_paper_path, answer_key_path, STATUS_DRAFT, created_at, created_at),
    )
    conn.commit()
    return MainMarkingSession(
        session_id=cursor.lastrowid,
        teacher_id=teacher_id,
        title=title,
        paper_type=paper_type,
        question_paper_path=question_paper_path,
        answer_key_path=answer_key_path,
        status=STATUS_DRAFT,
        created_at=created_at,
        updated_at=created_at,
    )


def update_session_file_paths(
    conn: sqlite3.Connection, session_id: int, question_paper_path: Optional[str], answer_key_path: Optional[str]
) -> None:
    conn.execute(
        "UPDATE main_marking_sessions SET question_paper_path = ?, answer_key_path = ?, updated_at = ? "
        "WHERE session_id = ?",
        (question_paper_path, answer_key_path, _now(), session_id),
    )
    conn.commit()


def update_session_details(conn: sqlite3.Connection, session_id: int, title: str, paper_type: str) -> None:
    conn.execute(
        "UPDATE main_marking_sessions SET title = ?, paper_type = ?, updated_at = ? WHERE session_id = ?",
        (title, paper_type, _now(), session_id),
    )
    conn.commit()


def get_session_by_id(conn: sqlite3.Connection, session_id: int) -> Optional[MainMarkingSession]:
    row = conn.execute(
        "SELECT session_id, teacher_id, title, paper_type, question_paper_path, answer_key_path, "
        "status, created_at, updated_at, template_id FROM main_marking_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingSession(**dict(row))


def get_sessions_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[MainMarkingSessionRow]:
    rows = conn.execute(
        """
        SELECT s.session_id, s.teacher_id, s.title, s.paper_type, s.question_paper_path, s.answer_key_path,
               s.status, s.created_at, s.updated_at, s.template_id,
               COUNT(f.answer_file_id) AS answer_file_count
        FROM main_marking_sessions s
        LEFT JOIN main_marking_answer_files f ON f.session_id = s.session_id
        WHERE s.teacher_id = ?
        GROUP BY s.session_id, s.teacher_id, s.title, s.paper_type, s.question_paper_path, s.answer_key_path,
                 s.status, s.created_at, s.updated_at, s.template_id
        ORDER BY s.created_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [MainMarkingSessionRow(**dict(row)) for row in rows]


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Delete a marking session. ON DELETE CASCADE removes its answer-file
    rows only - the copied files on disk are not deleted (matches this
    project's existing pattern, e.g. deleting a template doesn't scrub its
    stored sample file from data/templates/)."""
    conn.execute("DELETE FROM main_marking_sessions WHERE session_id = ?", (session_id,))
    conn.commit()


def add_answer_file(
    conn: sqlite3.Connection,
    session_id: int,
    file_path: str,
    original_filename: Optional[str] = None,
    student_name: Optional[str] = None,
    student_code: Optional[str] = None,
    page_count: Optional[int] = None,
) -> MainMarkingAnswerFile:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_answer_files "
        "(session_id, file_path, original_filename, student_name, student_code, page_count, "
        "processing_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, file_path, original_filename, student_name, student_code, page_count,
         PROCESSING_STATUS_UPLOADED, created_at),
    )
    conn.commit()
    return MainMarkingAnswerFile(
        answer_file_id=cursor.lastrowid,
        session_id=session_id,
        file_path=file_path,
        original_filename=original_filename,
        student_name=student_name,
        student_code=student_code,
        detected_student_name=None,
        detected_student_code=None,
        page_count=page_count,
        processing_status=PROCESSING_STATUS_UPLOADED,
        created_at=created_at,
    )


def update_answer_file_path(conn: sqlite3.Connection, answer_file_id: int, file_path: str) -> None:
    conn.execute(
        "UPDATE main_marking_answer_files SET file_path = ? WHERE answer_file_id = ?", (file_path, answer_file_id)
    )
    conn.commit()


def update_answer_file_page_count(conn: sqlite3.Connection, answer_file_id: int, page_count: Optional[int]) -> None:
    conn.execute(
        "UPDATE main_marking_answer_files SET page_count = ? WHERE answer_file_id = ?", (page_count, answer_file_id)
    )
    conn.commit()


def update_answer_file_student_info(
    conn: sqlite3.Connection, answer_file_id: int, student_name: Optional[str], student_code: Optional[str]
) -> None:
    conn.execute(
        "UPDATE main_marking_answer_files SET student_name = ?, student_code = ? WHERE answer_file_id = ?",
        (student_name, student_code, answer_file_id),
    )
    conn.commit()


def get_answer_file_by_id(conn: sqlite3.Connection, answer_file_id: int) -> Optional[MainMarkingAnswerFile]:
    row = conn.execute(
        "SELECT answer_file_id, session_id, file_path, original_filename, student_name, student_code, "
        "detected_student_name, detected_student_code, page_count, processing_status, created_at "
        "FROM main_marking_answer_files WHERE answer_file_id = ?",
        (answer_file_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingAnswerFile(**dict(row))


def get_answer_files_for_session(conn: sqlite3.Connection, session_id: int) -> List[MainMarkingAnswerFile]:
    rows = conn.execute(
        "SELECT answer_file_id, session_id, file_path, original_filename, student_name, student_code, "
        "detected_student_name, detected_student_code, page_count, processing_status, created_at "
        "FROM main_marking_answer_files WHERE session_id = ? ORDER BY created_at, answer_file_id",
        (session_id,),
    ).fetchall()
    return [MainMarkingAnswerFile(**dict(row)) for row in rows]


def delete_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM main_marking_answer_files WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def update_answer_file_processing_status(conn: sqlite3.Connection, answer_file_id: int, processing_status: str) -> None:
    conn.execute(
        "UPDATE main_marking_answer_files SET processing_status = ? WHERE answer_file_id = ?",
        (processing_status, answer_file_id),
    )
    conn.commit()


def update_session_status(conn: sqlite3.Connection, session_id: int, status: str) -> None:
    conn.execute(
        "UPDATE main_marking_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
        (status, _now(), session_id),
    )
    conn.commit()


def update_session_template_id(conn: sqlite3.Connection, session_id: int, template_id: Optional[int]) -> None:
    """Set (or clear, when template_id is None) a session's linked
    template (Stage 11O). Never touches answer files, preprocessing rows,
    or OCR rows."""
    conn.execute(
        "UPDATE main_marking_sessions SET template_id = ?, updated_at = ? WHERE session_id = ?",
        (template_id, _now(), session_id),
    )
    conn.commit()


def create_processing_run(conn: sqlite3.Connection, session_id: int) -> MainMarkingProcessingRun:
    started_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_processing_runs (session_id, status, started_at, completed_at, message) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, RUN_STATUS_RUNNING, started_at, None, None),
    )
    conn.commit()
    return MainMarkingProcessingRun(
        run_id=cursor.lastrowid,
        session_id=session_id,
        status=RUN_STATUS_RUNNING,
        started_at=started_at,
        completed_at=None,
        message=None,
    )


def _finish_processing_run(conn: sqlite3.Connection, run_id: int, status: str, message: Optional[str]) -> None:
    conn.execute(
        "UPDATE main_marking_processing_runs SET status = ?, completed_at = ?, message = ? WHERE run_id = ?",
        (status, _now(), message, run_id),
    )
    conn.commit()


def mark_processing_run_completed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_processing_run(conn, run_id, RUN_STATUS_COMPLETED, message)


def mark_processing_run_failed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_processing_run(conn, run_id, RUN_STATUS_FAILED, message)


def get_processing_run_by_id(conn: sqlite3.Connection, run_id: int) -> Optional[MainMarkingProcessingRun]:
    row = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_processing_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingProcessingRun(**dict(row))


def get_processing_runs_for_session(conn: sqlite3.Connection, session_id: int) -> List[MainMarkingProcessingRun]:
    rows = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_processing_runs WHERE session_id = ? ORDER BY started_at DESC, run_id DESC",
        (session_id,),
    ).fetchall()
    return [MainMarkingProcessingRun(**dict(row)) for row in rows]


def add_preprocessed_page(
    conn: sqlite3.Connection,
    answer_file_id: int,
    page_number: int,
    preprocessed_image_path: Optional[str],
    status: str,
    message: Optional[str] = None,
    original_image_path: Optional[str] = None,
) -> MainMarkingPreprocessedPage:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_preprocessed_pages "
        "(answer_file_id, page_number, preprocessed_image_path, status, message, created_at, original_image_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, page_number, preprocessed_image_path, status, message, created_at, original_image_path),
    )
    conn.commit()
    return MainMarkingPreprocessedPage(
        page_id=cursor.lastrowid,
        answer_file_id=answer_file_id,
        page_number=page_number,
        preprocessed_image_path=preprocessed_image_path,
        status=status,
        message=message,
        created_at=created_at,
        original_image_path=original_image_path,
    )


def get_preprocessed_pages_for_answer_file(
    conn: sqlite3.Connection, answer_file_id: int
) -> List[MainMarkingPreprocessedPage]:
    rows = conn.execute(
        "SELECT page_id, answer_file_id, page_number, preprocessed_image_path, status, message, created_at, "
        "original_image_path "
        "FROM main_marking_preprocessed_pages WHERE answer_file_id = ? ORDER BY page_number",
        (answer_file_id,),
    ).fetchall()
    return [MainMarkingPreprocessedPage(**dict(row)) for row in rows]


def create_ocr_run(conn: sqlite3.Connection, session_id: int) -> MainMarkingOCRRun:
    started_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_ocr_runs (session_id, status, started_at, completed_at, message) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, RUN_STATUS_RUNNING, started_at, None, None),
    )
    conn.commit()
    return MainMarkingOCRRun(
        run_id=cursor.lastrowid, session_id=session_id, status=RUN_STATUS_RUNNING,
        started_at=started_at, completed_at=None, message=None,
    )


def _finish_ocr_run(conn: sqlite3.Connection, run_id: int, status: str, message: Optional[str]) -> None:
    conn.execute(
        "UPDATE main_marking_ocr_runs SET status = ?, completed_at = ?, message = ? WHERE run_id = ?",
        (status, _now(), message, run_id),
    )
    conn.commit()


def mark_ocr_run_completed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_ocr_run(conn, run_id, RUN_STATUS_COMPLETED, message)


def mark_ocr_run_failed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_ocr_run(conn, run_id, RUN_STATUS_FAILED, message)


def get_ocr_run_by_id(conn: sqlite3.Connection, run_id: int) -> Optional[MainMarkingOCRRun]:
    row = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_ocr_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingOCRRun(**dict(row))


def get_ocr_runs_for_session(conn: sqlite3.Connection, session_id: int) -> List[MainMarkingOCRRun]:
    rows = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_ocr_runs WHERE session_id = ? ORDER BY started_at DESC, run_id DESC",
        (session_id,),
    ).fetchall()
    return [MainMarkingOCRRun(**dict(row)) for row in rows]


def add_ocr_result(
    conn: sqlite3.Connection,
    answer_file_id: int,
    page_number: int,
    text: Optional[str],
    confidence: Optional[float],
    status: str,
    message: Optional[str] = None,
    ocr_blocks_json: Optional[str] = None,
) -> MainMarkingOCRResult:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_ocr_results "
        "(answer_file_id, page_number, text, confidence, status, message, created_at, ocr_blocks_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, page_number, text, confidence, status, message, created_at, ocr_blocks_json),
    )
    conn.commit()
    return MainMarkingOCRResult(
        result_id=cursor.lastrowid, answer_file_id=answer_file_id, page_number=page_number,
        text=text, confidence=confidence, status=status, message=message, created_at=created_at,
        ocr_blocks_json=ocr_blocks_json,
    )


def get_ocr_results_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[MainMarkingOCRResult]:
    rows = conn.execute(
        "SELECT result_id, answer_file_id, page_number, text, confidence, status, message, created_at, "
        "ocr_blocks_json FROM main_marking_ocr_results WHERE answer_file_id = ? ORDER BY page_number",
        (answer_file_id,),
    ).fetchall()
    return [MainMarkingOCRResult(**dict(row)) for row in rows]


def delete_ocr_results_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM main_marking_ocr_results WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def create_answer_extraction_run(conn: sqlite3.Connection, session_id: int) -> MainMarkingAnswerExtractionRun:
    started_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_answer_extraction_runs (session_id, status, started_at, completed_at, message) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, RUN_STATUS_RUNNING, started_at, None, None),
    )
    conn.commit()
    return MainMarkingAnswerExtractionRun(
        run_id=cursor.lastrowid, session_id=session_id, status=RUN_STATUS_RUNNING,
        started_at=started_at, completed_at=None, message=None,
    )


def _finish_answer_extraction_run(conn: sqlite3.Connection, run_id: int, status: str, message: Optional[str]) -> None:
    conn.execute(
        "UPDATE main_marking_answer_extraction_runs SET status = ?, completed_at = ?, message = ? WHERE run_id = ?",
        (status, _now(), message, run_id),
    )
    conn.commit()


def mark_answer_extraction_run_completed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_answer_extraction_run(conn, run_id, RUN_STATUS_COMPLETED, message)


def mark_answer_extraction_run_failed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_answer_extraction_run(conn, run_id, RUN_STATUS_FAILED, message)


def get_answer_extraction_runs_for_session(
    conn: sqlite3.Connection, session_id: int
) -> List[MainMarkingAnswerExtractionRun]:
    rows = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_answer_extraction_runs WHERE session_id = ? ORDER BY started_at DESC, run_id DESC",
        (session_id,),
    ).fetchall()
    return [MainMarkingAnswerExtractionRun(**dict(row)) for row in rows]


def add_extracted_answer(
    conn: sqlite3.Connection,
    answer_file_id: int,
    target_kind: str,
    region_id: Optional[int],
    group_id: Optional[int],
    target_label: str,
    region_type: Optional[str],
    page_numbers_json: str,
    extracted_text: Optional[str],
    confidence: Optional[float],
    status: str,
    message: Optional[str] = None,
) -> MainMarkingExtractedAnswer:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_extracted_answers "
        "(answer_file_id, target_kind, region_id, group_id, target_label, region_type, page_numbers_json, "
        "extracted_text, confidence, status, message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, target_kind, region_id, group_id, target_label, region_type, page_numbers_json,
         extracted_text, confidence, status, message, created_at),
    )
    conn.commit()
    return MainMarkingExtractedAnswer(
        extracted_answer_id=cursor.lastrowid, answer_file_id=answer_file_id, target_kind=target_kind,
        region_id=region_id, group_id=group_id, target_label=target_label, region_type=region_type,
        page_numbers_json=page_numbers_json, extracted_text=extracted_text, confidence=confidence,
        status=status, message=message, created_at=created_at,
    )


def get_extracted_answers_for_answer_file(
    conn: sqlite3.Connection, answer_file_id: int
) -> List[MainMarkingExtractedAnswer]:
    rows = conn.execute(
        "SELECT extracted_answer_id, answer_file_id, target_kind, region_id, group_id, target_label, "
        "region_type, page_numbers_json, extracted_text, confidence, status, message, created_at "
        "FROM main_marking_extracted_answers WHERE answer_file_id = ? ORDER BY extracted_answer_id",
        (answer_file_id,),
    ).fetchall()
    return [MainMarkingExtractedAnswer(**dict(row)) for row in rows]


def delete_extracted_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM main_marking_extracted_answers WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def create_marking_run(conn: sqlite3.Connection, session_id: int) -> MainMarkingMarkingRun:
    started_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_marking_runs (session_id, status, started_at, completed_at, message) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, RUN_STATUS_RUNNING, started_at, None, None),
    )
    conn.commit()
    return MainMarkingMarkingRun(
        run_id=cursor.lastrowid, session_id=session_id, status=RUN_STATUS_RUNNING,
        started_at=started_at, completed_at=None, message=None,
    )


def _finish_marking_run(conn: sqlite3.Connection, run_id: int, status: str, message: Optional[str]) -> None:
    conn.execute(
        "UPDATE main_marking_marking_runs SET status = ?, completed_at = ?, message = ? WHERE run_id = ?",
        (status, _now(), message, run_id),
    )
    conn.commit()


def mark_marking_run_completed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_marking_run(conn, run_id, RUN_STATUS_COMPLETED, message)


def mark_marking_run_failed(conn: sqlite3.Connection, run_id: int, message: Optional[str]) -> None:
    _finish_marking_run(conn, run_id, RUN_STATUS_FAILED, message)


def get_marking_runs_for_session(conn: sqlite3.Connection, session_id: int) -> List[MainMarkingMarkingRun]:
    rows = conn.execute(
        "SELECT run_id, session_id, status, started_at, completed_at, message "
        "FROM main_marking_marking_runs WHERE session_id = ? ORDER BY started_at DESC, run_id DESC",
        (session_id,),
    ).fetchall()
    return [MainMarkingMarkingRun(**dict(row)) for row in rows]


def add_marked_answer(
    conn: sqlite3.Connection,
    answer_file_id: int,
    extracted_answer_id: Optional[int],
    target_kind: str,
    target_label: str,
    region_type: Optional[str],
    student_answer_text: Optional[str],
    correct_answer_text: Optional[str],
    score: Optional[float],
    max_score: float,
    status: str,
    feedback: Optional[str],
    needs_review: bool,
) -> MainMarkingMarkedAnswer:
    created_at = _now()
    needs_review_int = 1 if needs_review else 0
    cursor = conn.execute(
        "INSERT INTO main_marking_marked_answers "
        "(answer_file_id, extracted_answer_id, target_kind, target_label, region_type, student_answer_text, "
        "correct_answer_text, score, max_score, status, feedback, needs_review, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, extracted_answer_id, target_kind, target_label, region_type, student_answer_text,
         correct_answer_text, score, max_score, status, feedback, needs_review_int, created_at),
    )
    conn.commit()
    return MainMarkingMarkedAnswer(
        marked_answer_id=cursor.lastrowid, answer_file_id=answer_file_id, extracted_answer_id=extracted_answer_id,
        target_kind=target_kind, target_label=target_label, region_type=region_type,
        student_answer_text=student_answer_text, correct_answer_text=correct_answer_text, score=score,
        max_score=max_score, status=status, feedback=feedback, needs_review=needs_review_int, created_at=created_at,
    )


def get_marked_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[MainMarkingMarkedAnswer]:
    rows = conn.execute(
        "SELECT marked_answer_id, answer_file_id, extracted_answer_id, target_kind, target_label, region_type, "
        "student_answer_text, correct_answer_text, score, max_score, status, feedback, needs_review, created_at, "
        "review_status, teacher_score, teacher_feedback, reviewed_at "
        "FROM main_marking_marked_answers WHERE answer_file_id = ? ORDER BY marked_answer_id",
        (answer_file_id,),
    ).fetchall()
    return [MainMarkingMarkedAnswer(**dict(row)) for row in rows]


def get_marked_answer_by_id(conn: sqlite3.Connection, marked_answer_id: int) -> Optional[MainMarkingMarkedAnswer]:
    row = conn.execute(
        "SELECT marked_answer_id, answer_file_id, extracted_answer_id, target_kind, target_label, region_type, "
        "student_answer_text, correct_answer_text, score, max_score, status, feedback, needs_review, created_at, "
        "review_status, teacher_score, teacher_feedback, reviewed_at "
        "FROM main_marking_marked_answers WHERE marked_answer_id = ?",
        (marked_answer_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingMarkedAnswer(**dict(row))


def update_marked_answer_review(
    conn: sqlite3.Connection, marked_answer_id: int, teacher_score: Optional[float], teacher_feedback: Optional[str]
) -> None:
    """Save a teacher's score/feedback override for one marked answer and
    mark it reviewed (Stage 11R). Never touches the machine-generated
    score/feedback/status/needs_review columns."""
    conn.execute(
        "UPDATE main_marking_marked_answers SET teacher_score = ?, teacher_feedback = ?, review_status = ?, "
        "reviewed_at = ? WHERE marked_answer_id = ?",
        (teacher_score, teacher_feedback, REVIEW_STATUS_REVIEWED, _now(), marked_answer_id),
    )
    conn.commit()


def delete_marked_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM main_marking_marked_answers WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def create_final_result(
    conn: sqlite3.Connection,
    session_id: int,
    answer_file_id: int,
    teacher_id: int,
    paper_type: str,
    student_name: Optional[str],
    student_code: Optional[str],
    answer_file_display_name: str,
    total_score: float,
    max_score: float,
    message: Optional[str] = None,
) -> MainMarkingFinalResult:
    finalized_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_final_results "
        "(session_id, answer_file_id, teacher_id, paper_type, student_name, student_code, "
        "answer_file_display_name, total_score, max_score, status, finalized_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, answer_file_id, teacher_id, paper_type, student_name, student_code,
         answer_file_display_name, total_score, max_score, FINAL_RESULT_STATUS_FINALIZED, finalized_at, message),
    )
    conn.commit()
    return MainMarkingFinalResult(
        result_id=cursor.lastrowid, session_id=session_id, answer_file_id=answer_file_id, teacher_id=teacher_id,
        paper_type=paper_type, student_name=student_name, student_code=student_code,
        answer_file_display_name=answer_file_display_name, total_score=total_score, max_score=max_score,
        status=FINAL_RESULT_STATUS_FINALIZED, finalized_at=finalized_at, message=message,
    )


def get_final_result_by_id(conn: sqlite3.Connection, result_id: int) -> Optional[MainMarkingFinalResult]:
    row = conn.execute(
        "SELECT result_id, session_id, answer_file_id, teacher_id, paper_type, student_name, student_code, "
        "answer_file_display_name, total_score, max_score, status, finalized_at, message "
        "FROM main_marking_final_results WHERE result_id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingFinalResult(**dict(row))


def get_final_result_by_answer_file_id(conn: sqlite3.Connection, answer_file_id: int) -> Optional[MainMarkingFinalResult]:
    row = conn.execute(
        "SELECT result_id, session_id, answer_file_id, teacher_id, paper_type, student_name, student_code, "
        "answer_file_display_name, total_score, max_score, status, finalized_at, message "
        "FROM main_marking_final_results WHERE answer_file_id = ?",
        (answer_file_id,),
    ).fetchone()
    if row is None:
        return None
    return MainMarkingFinalResult(**dict(row))


def get_final_results_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[MainMarkingFinalResult]:
    rows = conn.execute(
        "SELECT result_id, session_id, answer_file_id, teacher_id, paper_type, student_name, student_code, "
        "answer_file_display_name, total_score, max_score, status, finalized_at, message "
        "FROM main_marking_final_results WHERE teacher_id = ? ORDER BY finalized_at DESC, result_id DESC",
        (teacher_id,),
    ).fetchall()
    return [MainMarkingFinalResult(**dict(row)) for row in rows]


def delete_final_result_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    """Delete answer_file_id's current final result (and its items, via ON
    DELETE CASCADE) if one exists - a no-op otherwise. Used both to replace
    a result on re-finalization and to clear a stale finalized snapshot
    when marking is rerun after finalization (Stage 11S rerun-safety)."""
    conn.execute("DELETE FROM main_marking_final_results WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def add_final_result_item(
    conn: sqlite3.Connection,
    result_id: int,
    marked_answer_id: Optional[int],
    target_label: str,
    target_kind: str,
    region_type: Optional[str],
    student_answer_text: Optional[str],
    correct_answer_text: Optional[str],
    machine_score: Optional[float],
    teacher_score: Optional[float],
    final_score: float,
    max_score: float,
    machine_feedback: Optional[str],
    teacher_feedback: Optional[str],
    final_feedback: Optional[str],
    reviewed_at: Optional[str],
) -> MainMarkingFinalResultItem:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO main_marking_final_result_items "
        "(result_id, marked_answer_id, target_label, target_kind, region_type, student_answer_text, "
        "correct_answer_text, machine_score, teacher_score, final_score, max_score, machine_feedback, "
        "teacher_feedback, final_feedback, reviewed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (result_id, marked_answer_id, target_label, target_kind, region_type, student_answer_text,
         correct_answer_text, machine_score, teacher_score, final_score, max_score, machine_feedback,
         teacher_feedback, final_feedback, reviewed_at, created_at),
    )
    conn.commit()
    return MainMarkingFinalResultItem(
        item_id=cursor.lastrowid, result_id=result_id, marked_answer_id=marked_answer_id,
        target_label=target_label, target_kind=target_kind, region_type=region_type,
        student_answer_text=student_answer_text, correct_answer_text=correct_answer_text,
        machine_score=machine_score, teacher_score=teacher_score, final_score=final_score, max_score=max_score,
        machine_feedback=machine_feedback, teacher_feedback=teacher_feedback, final_feedback=final_feedback,
        reviewed_at=reviewed_at, created_at=created_at,
    )


def get_final_result_items(conn: sqlite3.Connection, result_id: int) -> List[MainMarkingFinalResultItem]:
    rows = conn.execute(
        "SELECT item_id, result_id, marked_answer_id, target_label, target_kind, region_type, "
        "student_answer_text, correct_answer_text, machine_score, teacher_score, final_score, max_score, "
        "machine_feedback, teacher_feedback, final_feedback, reviewed_at, created_at "
        "FROM main_marking_final_result_items WHERE result_id = ? ORDER BY item_id",
        (result_id,),
    ).fetchall()
    return [MainMarkingFinalResultItem(**dict(row)) for row in rows]
