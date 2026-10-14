"""Teacher review-and-override orchestration for completed Kertas 1 marking
jobs.

Lets a teacher accept or override each auto-marked question's score, save
the review as a draft, and finalize it. The original auto marking result
(marking_jobs / marking_question_results) is never modified - it stays as
an untouched audit trail; all overrides live in marking_reviews /
marking_review_items instead. This stage does not build Kertas 2 review,
AI feedback, export, or automatic re-marking.
"""

import sqlite3
from typing import List, Optional

from app.models.class_model import get_class_by_id
from app.models.marking_result_model import (
    STATUS_COMPLETED as MARKING_JOB_STATUS_COMPLETED,
    get_marking_job_by_id,
    get_marking_question_results_for_job,
)
from app.models.marking_review_model import (
    MarkingReview,
    MarkingReviewItem,
    STATUS_DRAFT,
    STATUS_FINALIZED,
    REVIEW_STATUS_AUTO_ACCEPTED,
    REVIEW_STATUS_NEEDS_REVIEW,
    REVIEW_STATUS_OVERRIDDEN,
    add_review_item,
    create_review,
    finalize_review_row,
    get_latest_review_for_attempt,
    get_review_by_id,
    get_review_by_marking_job_id,
    get_review_item_by_id,
    get_review_items_for_review,
    update_review_comment,
    update_review_final_total_score,
    update_review_item_row,
)
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1


def _recalculate_final_total_score(conn: sqlite3.Connection, review_id: int) -> float:
    items = get_review_items_for_review(conn, review_id)
    final_total_score = sum(item.final_score_awarded for item in items)
    update_review_final_total_score(conn, review_id, final_total_score)
    return final_total_score


def start_or_get_review(conn: sqlite3.Connection, marking_job_id: int, teacher_id: int) -> MarkingReview:
    """Return the existing review for marking_job_id, or create one.

    Raises ValueError if the marking job doesn't exist, isn't completed,
    isn't Kertas 1, or doesn't belong to a class owned by teacher_id.
    """
    marking_job = get_marking_job_by_id(conn, marking_job_id)
    if marking_job is None:
        raise ValueError(f"Marking job not found: {marking_job_id}")
    if marking_job.status != MARKING_JOB_STATUS_COMPLETED:
        raise ValueError(f"Marking job {marking_job_id} is not completed (status: {marking_job.status}).")
    if marking_job.paper_type != PAPER_TYPE_KERTAS_1:
        raise ValueError(
            f"{marking_job.paper_type} review is not supported in this stage. "
            "Only Kertas 1 review is available."
        )

    attempt = get_attempt_by_id(conn, marking_job.attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {marking_job.attempt_id}")

    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only review attempts from classes you own.")

    existing = get_review_by_marking_job_id(conn, marking_job_id)
    if existing is not None:
        return existing

    review = create_review(
        conn, marking_job_id, marking_job.attempt_id, teacher_id, marking_job.total_score, marking_job.max_score
    )

    results = get_marking_question_results_for_job(conn, marking_job_id)
    for result in results:
        review_status = REVIEW_STATUS_NEEDS_REVIEW if result.needs_review else REVIEW_STATUS_AUTO_ACCEPTED
        add_review_item(
            conn,
            review.review_id,
            result.marking_result_id,
            result.question_no,
            result.score_awarded,
            result.score_awarded,
            result.max_mark,
            bool(result.is_correct),
            bool(result.is_correct),
            bool(result.needs_review),
            None,
            None,
            review_status,
        )

    return get_review_by_id(conn, review.review_id)


def update_review_item(
    conn: sqlite3.Connection,
    marking_review_item_id: int,
    teacher_id: int,
    final_score_awarded: float,
    final_is_correct: bool,
    teacher_comment: Optional[str] = None,
    override_reason: Optional[str] = None,
) -> MarkingReviewItem:
    """Update one review item's final score/correctness/comment while its
    parent review is still a draft.

    Raises ValueError if the item/review doesn't exist, isn't owned by
    teacher_id, is already finalized, or final_score_awarded is outside
    [0, max_mark].
    """
    item = get_review_item_by_id(conn, marking_review_item_id)
    if item is None:
        raise ValueError(f"Review item not found: {marking_review_item_id}")

    review = get_review_by_id(conn, item.review_id)
    if review is None:
        raise ValueError(f"Review not found: {item.review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only edit your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has been finalized and can no longer be edited.")

    if final_score_awarded < 0 or final_score_awarded > item.max_mark:
        raise ValueError(f"Final score must be between 0 and {item.max_mark}.")

    if final_score_awarded != item.auto_score_awarded or bool(final_is_correct) != bool(item.auto_is_correct):
        review_status = REVIEW_STATUS_OVERRIDDEN
    elif item.needs_review:
        review_status = REVIEW_STATUS_NEEDS_REVIEW
    else:
        review_status = REVIEW_STATUS_AUTO_ACCEPTED

    update_review_item_row(
        conn,
        marking_review_item_id,
        final_score_awarded,
        final_is_correct,
        teacher_comment,
        override_reason,
        review_status,
    )
    _recalculate_final_total_score(conn, review.review_id)

    return get_review_item_by_id(conn, marking_review_item_id)


def save_review_comment(
    conn: sqlite3.Connection, review_id: int, teacher_id: int, teacher_overall_comment: Optional[str]
) -> MarkingReview:
    """Save the overall teacher comment while review_id is still a draft."""
    review = get_review_by_id(conn, review_id)
    if review is None:
        raise ValueError(f"Review not found: {review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only edit your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has been finalized and can no longer be edited.")

    update_review_comment(conn, review_id, teacher_overall_comment)
    return get_review_by_id(conn, review_id)


def finalize_review(conn: sqlite3.Connection, review_id: int, teacher_id: int) -> MarkingReview:
    """Finalize review_id, recalculating its final_total_score first.

    Raises ValueError if the review doesn't exist, isn't owned by
    teacher_id, or is already finalized.
    """
    review = get_review_by_id(conn, review_id)
    if review is None:
        raise ValueError(f"Review not found: {review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only finalize your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has already been finalized.")

    _recalculate_final_total_score(conn, review_id)
    finalize_review_row(conn, review_id)
    return get_review_by_id(conn, review_id)


def get_review_for_student(conn: sqlite3.Connection, attempt_id: int, student_id: int) -> Optional[MarkingReview]:
    """Return the finalized review for attempt_id if student_id owns that
    attempt and a finalized review exists, else None.

    Raises ValueError if the attempt doesn't exist or doesn't belong to
    student_id.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")
    if attempt.student_id != student_id:
        raise ValueError("You can only view your own attempt's review.")

    review = get_latest_review_for_attempt(conn, attempt_id)
    if review is None or review.status != STATUS_FINALIZED:
        return None
    return review


def get_review(conn: sqlite3.Connection, review_id: int) -> Optional[MarkingReview]:
    return get_review_by_id(conn, review_id)


def get_review_for_marking_job(conn: sqlite3.Connection, marking_job_id: int) -> Optional[MarkingReview]:
    return get_review_by_marking_job_id(conn, marking_job_id)


def get_latest_review(conn: sqlite3.Connection, attempt_id: int) -> Optional[MarkingReview]:
    return get_latest_review_for_attempt(conn, attempt_id)


def list_review_items(conn: sqlite3.Connection, review_id: int) -> List[MarkingReviewItem]:
    return get_review_items_for_review(conn, review_id)
