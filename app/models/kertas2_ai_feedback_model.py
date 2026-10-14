"""Kertas 2 AI feedback draft job and item data model and database access
functions.

Stage 8C extends both tables with an audit trail (prompt snapshot, raw
provider output, parser error, and a structured audit_status) so a teacher
can inspect exactly what input/prompt was used and what the provider
returned or why it failed - without changing draft-only behavior or
touching finalized reviews.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)

FEEDBACK_STATUS_GENERATED = "generated"
FEEDBACK_STATUS_NO_ANSWER = "no_answer"
FEEDBACK_STATUS_NEEDS_REVIEW = "needs_review"
FEEDBACK_STATUS_FAILED = "failed"

ALLOWED_FEEDBACK_STATUSES = (
    FEEDBACK_STATUS_GENERATED,
    FEEDBACK_STATUS_NO_ANSWER,
    FEEDBACK_STATUS_NEEDS_REVIEW,
    FEEDBACK_STATUS_FAILED,
)

AUDIT_STATUS_NOT_RUN = "not_run"
AUDIT_STATUS_GENERATED = "generated"
AUDIT_STATUS_PROVIDER_FAILED = "provider_failed"
AUDIT_STATUS_PARSER_FAILED = "parser_failed"
AUDIT_STATUS_NO_ANSWER = "no_answer"
AUDIT_STATUS_NEEDS_REVIEW = "needs_review"

ALLOWED_AUDIT_STATUSES = (
    AUDIT_STATUS_NOT_RUN,
    AUDIT_STATUS_GENERATED,
    AUDIT_STATUS_PROVIDER_FAILED,
    AUDIT_STATUS_PARSER_FAILED,
    AUDIT_STATUS_NO_ANSWER,
    AUDIT_STATUS_NEEDS_REVIEW,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Kertas2AIFeedbackJob:
    feedback_job_id: int
    attempt_id: int
    answer_extraction_job_id: int
    marking_setup_id: int
    status: str
    criterion_count: int
    generated_count: int
    error_message: Optional[str]
    provider_backend: Optional[str]
    provider_model_path: Optional[str]
    provider_status: Optional[str]
    diagnostic_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class Kertas2AIFeedbackItem:
    feedback_item_id: int
    feedback_job_id: int
    question_id: int
    extracted_answer_id: Optional[int]
    criterion_name: str
    question_type: str
    student_answer: Optional[str]
    sample_answer: Optional[str]
    suggested_score: float
    max_mark: float
    feedback_text: Optional[str]
    reason: Optional[str]
    confidence: Optional[float]
    feedback_status: str
    prompt_snapshot: Optional[str]
    raw_provider_output: Optional[str]
    parser_error: Optional[str]
    audit_status: Optional[str]
    created_at: str


def create_feedback_job(
    conn: sqlite3.Connection,
    attempt_id: int,
    answer_extraction_job_id: int,
    marking_setup_id: int,
) -> Kertas2AIFeedbackJob:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO kertas2_ai_feedback_jobs "
        "(attempt_id, answer_extraction_job_id, marking_setup_id, status, criterion_count, "
        "generated_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, answer_extraction_job_id, marking_setup_id, STATUS_PENDING, 0, 0, created_at),
    )
    conn.commit()
    return Kertas2AIFeedbackJob(
        feedback_job_id=cursor.lastrowid,
        attempt_id=attempt_id,
        answer_extraction_job_id=answer_extraction_job_id,
        marking_setup_id=marking_setup_id,
        status=STATUS_PENDING,
        criterion_count=0,
        generated_count=0,
        error_message=None,
        provider_backend=None,
        provider_model_path=None,
        provider_status=None,
        diagnostic_message=None,
        created_at=created_at,
        completed_at=None,
    )


def mark_feedback_job_completed(
    conn: sqlite3.Connection,
    feedback_job_id: int,
    criterion_count: int,
    generated_count: int,
    provider_backend: Optional[str] = None,
    provider_model_path: Optional[str] = None,
    provider_status: Optional[str] = None,
    diagnostic_message: Optional[str] = None,
) -> None:
    completed_at = _now()
    conn.execute(
        "UPDATE kertas2_ai_feedback_jobs SET status = ?, criterion_count = ?, generated_count = ?, "
        "completed_at = ?, provider_backend = ?, provider_model_path = ?, provider_status = ?, "
        "diagnostic_message = ? WHERE feedback_job_id = ?",
        (
            STATUS_COMPLETED,
            criterion_count,
            generated_count,
            completed_at,
            provider_backend,
            provider_model_path,
            provider_status,
            diagnostic_message,
            feedback_job_id,
        ),
    )
    conn.commit()


def mark_feedback_job_failed(
    conn: sqlite3.Connection,
    feedback_job_id: int,
    error_message: str,
    provider_backend: Optional[str] = None,
    provider_model_path: Optional[str] = None,
    provider_status: Optional[str] = None,
    diagnostic_message: Optional[str] = None,
) -> None:
    completed_at = _now()
    conn.execute(
        "UPDATE kertas2_ai_feedback_jobs SET status = ?, error_message = ?, completed_at = ?, "
        "provider_backend = ?, provider_model_path = ?, provider_status = ?, diagnostic_message = ? "
        "WHERE feedback_job_id = ?",
        (
            STATUS_FAILED,
            error_message,
            completed_at,
            provider_backend,
            provider_model_path,
            provider_status,
            diagnostic_message,
            feedback_job_id,
        ),
    )
    conn.commit()


def get_feedback_job_by_id(conn: sqlite3.Connection, feedback_job_id: int) -> Optional[Kertas2AIFeedbackJob]:
    row = conn.execute(
        "SELECT feedback_job_id, attempt_id, answer_extraction_job_id, marking_setup_id, status, "
        "criterion_count, generated_count, error_message, provider_backend, provider_model_path, "
        "provider_status, diagnostic_message, created_at, completed_at "
        "FROM kertas2_ai_feedback_jobs WHERE feedback_job_id = ?",
        (feedback_job_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2AIFeedbackJob(**dict(row))


def get_latest_feedback_job_for_attempt(
    conn: sqlite3.Connection, attempt_id: int
) -> Optional[Kertas2AIFeedbackJob]:
    row = conn.execute(
        "SELECT feedback_job_id, attempt_id, answer_extraction_job_id, marking_setup_id, status, "
        "criterion_count, generated_count, error_message, provider_backend, provider_model_path, "
        "provider_status, diagnostic_message, created_at, completed_at "
        "FROM kertas2_ai_feedback_jobs WHERE attempt_id = ? "
        "ORDER BY created_at DESC, feedback_job_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2AIFeedbackJob(**dict(row))


def add_feedback_item(
    conn: sqlite3.Connection,
    feedback_job_id: int,
    question_id: int,
    extracted_answer_id: Optional[int],
    criterion_name: str,
    question_type: str,
    student_answer: Optional[str],
    sample_answer: Optional[str],
    suggested_score: float,
    max_mark: float,
    feedback_text: Optional[str],
    reason: Optional[str],
    confidence: Optional[float],
    feedback_status: str,
    prompt_snapshot: Optional[str] = None,
    raw_provider_output: Optional[str] = None,
    parser_error: Optional[str] = None,
    audit_status: Optional[str] = None,
) -> Kertas2AIFeedbackItem:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO kertas2_ai_feedback_items "
        "(feedback_job_id, question_id, extracted_answer_id, criterion_name, question_type, "
        "student_answer, sample_answer, suggested_score, max_mark, feedback_text, reason, "
        "confidence, feedback_status, prompt_snapshot, raw_provider_output, parser_error, "
        "audit_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            feedback_job_id,
            question_id,
            extracted_answer_id,
            criterion_name,
            question_type,
            student_answer,
            sample_answer,
            suggested_score,
            max_mark,
            feedback_text,
            reason,
            confidence,
            feedback_status,
            prompt_snapshot,
            raw_provider_output,
            parser_error,
            audit_status,
            created_at,
        ),
    )
    conn.commit()
    return Kertas2AIFeedbackItem(
        feedback_item_id=cursor.lastrowid,
        feedback_job_id=feedback_job_id,
        question_id=question_id,
        extracted_answer_id=extracted_answer_id,
        criterion_name=criterion_name,
        question_type=question_type,
        student_answer=student_answer,
        sample_answer=sample_answer,
        suggested_score=suggested_score,
        max_mark=max_mark,
        feedback_text=feedback_text,
        reason=reason,
        confidence=confidence,
        feedback_status=feedback_status,
        prompt_snapshot=prompt_snapshot,
        raw_provider_output=raw_provider_output,
        parser_error=parser_error,
        audit_status=audit_status,
        created_at=created_at,
    )


def get_feedback_items_for_job(
    conn: sqlite3.Connection, feedback_job_id: int
) -> List[Kertas2AIFeedbackItem]:
    rows = conn.execute(
        "SELECT feedback_item_id, feedback_job_id, question_id, extracted_answer_id, criterion_name, "
        "question_type, student_answer, sample_answer, suggested_score, max_mark, feedback_text, "
        "reason, confidence, feedback_status, prompt_snapshot, raw_provider_output, parser_error, "
        "audit_status, created_at "
        "FROM kertas2_ai_feedback_items WHERE feedback_job_id = ? ORDER BY feedback_item_id",
        (feedback_job_id,),
    ).fetchall()
    return [Kertas2AIFeedbackItem(**dict(row)) for row in rows]
