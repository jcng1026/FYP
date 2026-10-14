"""Teacher marking-review and review-item data model and database access
functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_DRAFT = "draft"
STATUS_FINALIZED = "finalized"

ALLOWED_STATUSES = (STATUS_DRAFT, STATUS_FINALIZED)

REVIEW_STATUS_AUTO_ACCEPTED = "auto_accepted"
REVIEW_STATUS_OVERRIDDEN = "overridden"
REVIEW_STATUS_NEEDS_REVIEW = "needs_review"

ALLOWED_REVIEW_STATUSES = (REVIEW_STATUS_AUTO_ACCEPTED, REVIEW_STATUS_OVERRIDDEN, REVIEW_STATUS_NEEDS_REVIEW)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MarkingReview:
    review_id: int
    marking_job_id: int
    attempt_id: int
    teacher_id: int
    status: str
    auto_total_score: float
    final_total_score: float
    max_score: float
    teacher_overall_comment: Optional[str]
    created_at: str
    updated_at: str
    finalized_at: Optional[str]


@dataclass
class MarkingReviewItem:
    marking_review_item_id: int
    review_id: int
    marking_result_id: int
    question_no: str
    auto_score_awarded: float
    final_score_awarded: float
    max_mark: float
    auto_is_correct: int
    final_is_correct: int
    needs_review: int
    teacher_comment: Optional[str]
    override_reason: Optional[str]
    review_status: str
    created_at: str
    updated_at: str


def create_review(
    conn: sqlite3.Connection,
    marking_job_id: int,
    attempt_id: int,
    teacher_id: int,
    auto_total_score: float,
    max_score: float,
) -> MarkingReview:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO marking_reviews "
        "(marking_job_id, attempt_id, teacher_id, status, auto_total_score, final_total_score, "
        "max_score, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (marking_job_id, attempt_id, teacher_id, STATUS_DRAFT, auto_total_score, auto_total_score, max_score, now, now),
    )
    conn.commit()
    return MarkingReview(
        review_id=cursor.lastrowid,
        marking_job_id=marking_job_id,
        attempt_id=attempt_id,
        teacher_id=teacher_id,
        status=STATUS_DRAFT,
        auto_total_score=auto_total_score,
        final_total_score=auto_total_score,
        max_score=max_score,
        teacher_overall_comment=None,
        created_at=now,
        updated_at=now,
        finalized_at=None,
    )


def update_review_final_total_score(conn: sqlite3.Connection, review_id: int, final_total_score: float) -> None:
    conn.execute(
        "UPDATE marking_reviews SET final_total_score = ?, updated_at = ? WHERE review_id = ?",
        (final_total_score, _now(), review_id),
    )
    conn.commit()


def update_review_comment(conn: sqlite3.Connection, review_id: int, teacher_overall_comment: Optional[str]) -> None:
    conn.execute(
        "UPDATE marking_reviews SET teacher_overall_comment = ?, updated_at = ? WHERE review_id = ?",
        (teacher_overall_comment, _now(), review_id),
    )
    conn.commit()


def finalize_review_row(conn: sqlite3.Connection, review_id: int) -> None:
    now = _now()
    conn.execute(
        "UPDATE marking_reviews SET status = ?, updated_at = ?, finalized_at = ? WHERE review_id = ?",
        (STATUS_FINALIZED, now, now, review_id),
    )
    conn.commit()


def get_review_by_id(conn: sqlite3.Connection, review_id: int) -> Optional[MarkingReview]:
    row = conn.execute(
        "SELECT review_id, marking_job_id, attempt_id, teacher_id, status, auto_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM marking_reviews WHERE review_id = ?",
        (review_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingReview(**dict(row))


def get_review_by_marking_job_id(conn: sqlite3.Connection, marking_job_id: int) -> Optional[MarkingReview]:
    row = conn.execute(
        "SELECT review_id, marking_job_id, attempt_id, teacher_id, status, auto_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM marking_reviews WHERE marking_job_id = ?",
        (marking_job_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingReview(**dict(row))


def get_latest_review_for_attempt(conn: sqlite3.Connection, attempt_id: int) -> Optional[MarkingReview]:
    row = conn.execute(
        "SELECT review_id, marking_job_id, attempt_id, teacher_id, status, auto_total_score, "
        "final_total_score, max_score, teacher_overall_comment, created_at, updated_at, finalized_at "
        "FROM marking_reviews WHERE attempt_id = ? ORDER BY created_at DESC, review_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingReview(**dict(row))


def add_review_item(
    conn: sqlite3.Connection,
    review_id: int,
    marking_result_id: int,
    question_no: str,
    auto_score_awarded: float,
    final_score_awarded: float,
    max_mark: float,
    auto_is_correct: bool,
    final_is_correct: bool,
    needs_review: bool,
    teacher_comment: Optional[str],
    override_reason: Optional[str],
    review_status: str,
) -> MarkingReviewItem:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO marking_review_items "
        "(review_id, marking_result_id, question_no, auto_score_awarded, final_score_awarded, max_mark, "
        "auto_is_correct, final_is_correct, needs_review, teacher_comment, override_reason, review_status, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            review_id,
            marking_result_id,
            question_no,
            auto_score_awarded,
            final_score_awarded,
            max_mark,
            1 if auto_is_correct else 0,
            1 if final_is_correct else 0,
            1 if needs_review else 0,
            teacher_comment,
            override_reason,
            review_status,
            now,
            now,
        ),
    )
    conn.commit()
    return MarkingReviewItem(
        marking_review_item_id=cursor.lastrowid,
        review_id=review_id,
        marking_result_id=marking_result_id,
        question_no=question_no,
        auto_score_awarded=auto_score_awarded,
        final_score_awarded=final_score_awarded,
        max_mark=max_mark,
        auto_is_correct=1 if auto_is_correct else 0,
        final_is_correct=1 if final_is_correct else 0,
        needs_review=1 if needs_review else 0,
        teacher_comment=teacher_comment,
        override_reason=override_reason,
        review_status=review_status,
        created_at=now,
        updated_at=now,
    )


def update_review_item_row(
    conn: sqlite3.Connection,
    marking_review_item_id: int,
    final_score_awarded: float,
    final_is_correct: bool,
    teacher_comment: Optional[str],
    override_reason: Optional[str],
    review_status: str,
) -> None:
    conn.execute(
        "UPDATE marking_review_items SET final_score_awarded = ?, final_is_correct = ?, teacher_comment = ?, "
        "override_reason = ?, review_status = ?, updated_at = ? WHERE marking_review_item_id = ?",
        (
            final_score_awarded,
            1 if final_is_correct else 0,
            teacher_comment,
            override_reason,
            review_status,
            _now(),
            marking_review_item_id,
        ),
    )
    conn.commit()


def get_review_item_by_id(conn: sqlite3.Connection, marking_review_item_id: int) -> Optional[MarkingReviewItem]:
    row = conn.execute(
        "SELECT marking_review_item_id, review_id, marking_result_id, question_no, auto_score_awarded, "
        "final_score_awarded, max_mark, auto_is_correct, final_is_correct, needs_review, teacher_comment, "
        "override_reason, review_status, created_at, updated_at "
        "FROM marking_review_items WHERE marking_review_item_id = ?",
        (marking_review_item_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingReviewItem(**dict(row))


def get_review_items_for_review(conn: sqlite3.Connection, review_id: int) -> List[MarkingReviewItem]:
    rows = conn.execute(
        "SELECT marking_review_item_id, review_id, marking_result_id, question_no, auto_score_awarded, "
        "final_score_awarded, max_mark, auto_is_correct, final_is_correct, needs_review, teacher_comment, "
        "override_reason, review_status, created_at, updated_at "
        "FROM marking_review_items WHERE review_id = ? ORDER BY marking_review_item_id",
        (review_id,),
    ).fetchall()
    return [MarkingReviewItem(**dict(row)) for row in rows]
