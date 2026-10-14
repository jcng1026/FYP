"""Teacher review-and-override data model for Kertas 2 AI feedback drafts,
and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_DRAFT = "draft"
STATUS_FINALIZED = "finalized"

ALLOWED_STATUSES = (STATUS_DRAFT, STATUS_FINALIZED)

REVIEW_STATUS_ACCEPTED = "accepted"
REVIEW_STATUS_EDITED = "edited"
REVIEW_STATUS_NEEDS_REVIEW = "needs_review"

ALLOWED_REVIEW_STATUSES = (REVIEW_STATUS_ACCEPTED, REVIEW_STATUS_EDITED, REVIEW_STATUS_NEEDS_REVIEW)


def _now() -> str:
    """Full microsecond-resolution UTC timestamp (Stage 11Y-Fix).

    Previously truncated to whole-second resolution
    (.replace(microsecond=0)), which let multiple reviews finalized in
    quick succession (e.g. seeded in a tight test loop) land on the exact
    same finalized_at value - k2_training_dataset_service.py's dataset
    export query (ORDER BY kr.finalized_at DESC, kri.kertas2_review_item_id)
    would then tie-break by insertion order, occasionally reordering rows
    versus what a test expected whenever a run happened to straddle a
    one-second clock boundary. Keeping full microsecond precision makes
    finalized_at (and every other _now()-based timestamp column here)
    effectively unique per call, so ordering by it alone is deterministic.
    datetime.fromisoformat (used by app.utils.datetime_utils.format_timestamp
    for display) parses this format unchanged."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Kertas2FeedbackReview:
    kertas2_review_id: int
    feedback_job_id: int
    attempt_id: int
    teacher_id: int
    status: str
    suggested_total_score: float
    final_total_score: float
    max_score: float
    teacher_overall_comment: Optional[str]
    created_at: str
    updated_at: str
    finalized_at: Optional[str]


@dataclass
class Kertas2FeedbackReviewItem:
    kertas2_review_item_id: int
    kertas2_review_id: int
    feedback_item_id: int
    criterion_name: str
    question_type: str
    student_answer: Optional[str]
    sample_answer: Optional[str]
    suggested_score: float
    final_score: float
    max_mark: float
    suggested_feedback: Optional[str]
    final_feedback: Optional[str]
    ai_reason: Optional[str]
    teacher_comment: Optional[str]
    review_status: str
    created_at: str
    updated_at: str


def create_kertas2_review(
    conn: sqlite3.Connection,
    feedback_job_id: int,
    attempt_id: int,
    teacher_id: int,
    suggested_total_score: float,
    max_score: float,
) -> Kertas2FeedbackReview:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO kertas2_feedback_reviews "
        "(feedback_job_id, attempt_id, teacher_id, status, suggested_total_score, final_total_score, "
        "max_score, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            feedback_job_id, attempt_id, teacher_id, STATUS_DRAFT,
            suggested_total_score, suggested_total_score, max_score, now, now,
        ),
    )
    conn.commit()
    return Kertas2FeedbackReview(
        kertas2_review_id=cursor.lastrowid,
        feedback_job_id=feedback_job_id,
        attempt_id=attempt_id,
        teacher_id=teacher_id,
        status=STATUS_DRAFT,
        suggested_total_score=suggested_total_score,
        final_total_score=suggested_total_score,
        max_score=max_score,
        teacher_overall_comment=None,
        created_at=now,
        updated_at=now,
        finalized_at=None,
    )


def update_kertas2_review_final_total_score(
    conn: sqlite3.Connection, kertas2_review_id: int, final_total_score: float
) -> None:
    conn.execute(
        "UPDATE kertas2_feedback_reviews SET final_total_score = ?, updated_at = ? WHERE kertas2_review_id = ?",
        (final_total_score, _now(), kertas2_review_id),
    )
    conn.commit()


def update_kertas2_review_comment(
    conn: sqlite3.Connection, kertas2_review_id: int, teacher_overall_comment: Optional[str]
) -> None:
    conn.execute(
        "UPDATE kertas2_feedback_reviews SET teacher_overall_comment = ?, updated_at = ? "
        "WHERE kertas2_review_id = ?",
        (teacher_overall_comment, _now(), kertas2_review_id),
    )
    conn.commit()


def finalize_kertas2_review_row(conn: sqlite3.Connection, kertas2_review_id: int) -> None:
    now = _now()
    conn.execute(
        "UPDATE kertas2_feedback_reviews SET status = ?, updated_at = ?, finalized_at = ? "
        "WHERE kertas2_review_id = ?",
        (STATUS_FINALIZED, now, now, kertas2_review_id),
    )
    conn.commit()


def get_kertas2_review_by_id(conn: sqlite3.Connection, kertas2_review_id: int) -> Optional[Kertas2FeedbackReview]:
    row = conn.execute(
        "SELECT kertas2_review_id, feedback_job_id, attempt_id, teacher_id, status, suggested_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM kertas2_feedback_reviews WHERE kertas2_review_id = ?",
        (kertas2_review_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2FeedbackReview(**dict(row))


def get_kertas2_review_by_feedback_job_id(
    conn: sqlite3.Connection, feedback_job_id: int
) -> Optional[Kertas2FeedbackReview]:
    row = conn.execute(
        "SELECT kertas2_review_id, feedback_job_id, attempt_id, teacher_id, status, suggested_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM kertas2_feedback_reviews WHERE feedback_job_id = ?",
        (feedback_job_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2FeedbackReview(**dict(row))


def get_latest_kertas2_review_for_attempt(
    conn: sqlite3.Connection, attempt_id: int
) -> Optional[Kertas2FeedbackReview]:
    row = conn.execute(
        "SELECT kertas2_review_id, feedback_job_id, attempt_id, teacher_id, status, suggested_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM kertas2_feedback_reviews WHERE attempt_id = ? "
        "ORDER BY created_at DESC, kertas2_review_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2FeedbackReview(**dict(row))


def add_kertas2_review_item(
    conn: sqlite3.Connection,
    kertas2_review_id: int,
    feedback_item_id: int,
    criterion_name: str,
    question_type: str,
    student_answer: Optional[str],
    sample_answer: Optional[str],
    suggested_score: float,
    final_score: float,
    max_mark: float,
    suggested_feedback: Optional[str],
    final_feedback: Optional[str],
    ai_reason: Optional[str],
    teacher_comment: Optional[str],
    review_status: str,
) -> Kertas2FeedbackReviewItem:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO kertas2_feedback_review_items "
        "(kertas2_review_id, feedback_item_id, criterion_name, question_type, student_answer, sample_answer, "
        "suggested_score, final_score, max_mark, suggested_feedback, final_feedback, ai_reason, "
        "teacher_comment, review_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kertas2_review_id, feedback_item_id, criterion_name, question_type, student_answer, sample_answer,
            suggested_score, final_score, max_mark, suggested_feedback, final_feedback, ai_reason,
            teacher_comment, review_status, now, now,
        ),
    )
    conn.commit()
    return Kertas2FeedbackReviewItem(
        kertas2_review_item_id=cursor.lastrowid,
        kertas2_review_id=kertas2_review_id,
        feedback_item_id=feedback_item_id,
        criterion_name=criterion_name,
        question_type=question_type,
        student_answer=student_answer,
        sample_answer=sample_answer,
        suggested_score=suggested_score,
        final_score=final_score,
        max_mark=max_mark,
        suggested_feedback=suggested_feedback,
        final_feedback=final_feedback,
        ai_reason=ai_reason,
        teacher_comment=teacher_comment,
        review_status=review_status,
        created_at=now,
        updated_at=now,
    )


def update_kertas2_review_item_row(
    conn: sqlite3.Connection,
    kertas2_review_item_id: int,
    final_score: float,
    final_feedback: Optional[str],
    teacher_comment: Optional[str],
    review_status: str,
) -> None:
    conn.execute(
        "UPDATE kertas2_feedback_review_items SET final_score = ?, final_feedback = ?, teacher_comment = ?, "
        "review_status = ?, updated_at = ? WHERE kertas2_review_item_id = ?",
        (final_score, final_feedback, teacher_comment, review_status, _now(), kertas2_review_item_id),
    )
    conn.commit()


def get_kertas2_review_item_by_id(
    conn: sqlite3.Connection, kertas2_review_item_id: int
) -> Optional[Kertas2FeedbackReviewItem]:
    row = conn.execute(
        "SELECT kertas2_review_item_id, kertas2_review_id, feedback_item_id, criterion_name, question_type, "
        "student_answer, sample_answer, suggested_score, final_score, max_mark, suggested_feedback, "
        "final_feedback, ai_reason, teacher_comment, review_status, created_at, updated_at "
        "FROM kertas2_feedback_review_items WHERE kertas2_review_item_id = ?",
        (kertas2_review_item_id,),
    ).fetchone()
    if row is None:
        return None
    return Kertas2FeedbackReviewItem(**dict(row))


def get_kertas2_review_items_for_review(
    conn: sqlite3.Connection, kertas2_review_id: int
) -> List[Kertas2FeedbackReviewItem]:
    rows = conn.execute(
        "SELECT kertas2_review_item_id, kertas2_review_id, feedback_item_id, criterion_name, question_type, "
        "student_answer, sample_answer, suggested_score, final_score, max_mark, suggested_feedback, "
        "final_feedback, ai_reason, teacher_comment, review_status, created_at, updated_at "
        "FROM kertas2_feedback_review_items WHERE kertas2_review_id = ? ORDER BY kertas2_review_item_id",
        (kertas2_review_id,),
    ).fetchall()
    return [Kertas2FeedbackReviewItem(**dict(row)) for row in rows]
