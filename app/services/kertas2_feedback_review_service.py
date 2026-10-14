"""Teacher review-and-override orchestration for completed Kertas 2 AI
feedback draft jobs.

Lets a teacher accept or edit each AI-suggested score/feedback, save the
review as a draft, and finalize it. The original AI feedback draft
(kertas2_ai_feedback_jobs / kertas2_ai_feedback_items) is never modified -
it stays as an untouched audit trail; all edits live in
kertas2_feedback_reviews / kertas2_feedback_review_items instead. This
stage does not regenerate AI feedback, call any cloud/network AI, export
results, or touch Kertas 1 review records.
"""

import sqlite3
from typing import List, Optional

from app.models.class_model import get_class_by_id
from app.models.kertas2_ai_feedback_model import (
    STATUS_COMPLETED as FEEDBACK_JOB_STATUS_COMPLETED,
    FEEDBACK_STATUS_GENERATED,
    get_feedback_items_for_job,
    get_feedback_job_by_id,
)
from app.models.kertas2_feedback_review_model import (
    Kertas2FeedbackReview,
    Kertas2FeedbackReviewItem,
    STATUS_DRAFT,
    STATUS_FINALIZED,
    REVIEW_STATUS_ACCEPTED,
    REVIEW_STATUS_EDITED,
    REVIEW_STATUS_NEEDS_REVIEW,
    add_kertas2_review_item,
    create_kertas2_review,
    finalize_kertas2_review_row,
    get_kertas2_review_by_feedback_job_id,
    get_kertas2_review_by_id,
    get_kertas2_review_item_by_id,
    get_kertas2_review_items_for_review,
    get_latest_kertas2_review_for_attempt,
    update_kertas2_review_comment,
    update_kertas2_review_final_total_score,
    update_kertas2_review_item_row,
)
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import PAPER_TYPE_KERTAS_2, get_material_by_id
from app.models.marking_setup_model import get_marking_setup_by_material


def _recalculate_final_total_score(conn: sqlite3.Connection, kertas2_review_id: int) -> float:
    items = get_kertas2_review_items_for_review(conn, kertas2_review_id)
    final_total_score = sum(item.final_score for item in items)
    update_kertas2_review_final_total_score(conn, kertas2_review_id, final_total_score)
    return final_total_score


def start_or_get_kertas2_review(
    conn: sqlite3.Connection, feedback_job_id: int, teacher_id: int
) -> Kertas2FeedbackReview:
    """Return the existing Kertas 2 review for feedback_job_id, or create one.

    Raises ValueError if the feedback job doesn't exist, isn't completed,
    isn't linked to a Kertas 2 marking setup, or doesn't belong to a class
    owned by teacher_id.
    """
    feedback_job = get_feedback_job_by_id(conn, feedback_job_id)
    if feedback_job is None:
        raise ValueError(f"Kertas 2 feedback job not found: {feedback_job_id}")
    if feedback_job.status != FEEDBACK_JOB_STATUS_COMPLETED:
        raise ValueError(
            f"Kertas 2 feedback job {feedback_job_id} is not completed (status: {feedback_job.status})."
        )

    attempt = get_attempt_by_id(conn, feedback_job.attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {feedback_job.attempt_id}")

    material = get_material_by_id(conn, attempt.material_id)
    if material is None:
        raise ValueError(f"Revision material not found for attempt {feedback_job.attempt_id}.")
    if material.paper_type != PAPER_TYPE_KERTAS_2:
        raise ValueError(
            f"{material.paper_type} review is not supported by this flow. Only Kertas 2 review is available."
        )

    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only review attempts from classes you own.")

    existing = get_kertas2_review_by_feedback_job_id(conn, feedback_job_id)
    if existing is not None:
        return existing

    feedback_items = get_feedback_items_for_job(conn, feedback_job_id)
    suggested_total_score = sum(item.suggested_score for item in feedback_items)
    max_score = sum(item.max_mark for item in feedback_items)

    review = create_kertas2_review(
        conn, feedback_job_id, feedback_job.attempt_id, teacher_id, suggested_total_score, max_score
    )

    for item in feedback_items:
        review_status = (
            REVIEW_STATUS_ACCEPTED if item.feedback_status == FEEDBACK_STATUS_GENERATED else REVIEW_STATUS_NEEDS_REVIEW
        )
        add_kertas2_review_item(
            conn,
            review.kertas2_review_id,
            item.feedback_item_id,
            item.criterion_name,
            item.question_type,
            item.student_answer,
            item.sample_answer,
            item.suggested_score,
            item.suggested_score,
            item.max_mark,
            item.feedback_text,
            item.feedback_text,
            item.reason,
            None,
            review_status,
        )

    return get_kertas2_review_by_id(conn, review.kertas2_review_id)


def update_kertas2_review_item(
    conn: sqlite3.Connection,
    kertas2_review_item_id: int,
    teacher_id: int,
    final_score: float,
    final_feedback: Optional[str],
    teacher_comment: Optional[str] = None,
) -> Kertas2FeedbackReviewItem:
    """Update one review item's final score/feedback/comment while its
    parent review is still a draft.

    Raises ValueError if the item/review doesn't exist, isn't owned by
    teacher_id, is already finalized, or final_score is outside [0, max_mark].
    """
    item = get_kertas2_review_item_by_id(conn, kertas2_review_item_id)
    if item is None:
        raise ValueError(f"Review item not found: {kertas2_review_item_id}")

    review = get_kertas2_review_by_id(conn, item.kertas2_review_id)
    if review is None:
        raise ValueError(f"Review not found: {item.kertas2_review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only edit your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has been finalized and can no longer be edited.")

    if final_score < 0 or final_score > item.max_mark:
        raise ValueError(f"Final score must be between 0 and {item.max_mark}.")

    if final_score != item.suggested_score or (final_feedback or "") != (item.suggested_feedback or ""):
        review_status = REVIEW_STATUS_EDITED
    elif item.review_status == REVIEW_STATUS_NEEDS_REVIEW:
        review_status = REVIEW_STATUS_NEEDS_REVIEW
    else:
        review_status = REVIEW_STATUS_ACCEPTED

    update_kertas2_review_item_row(
        conn, kertas2_review_item_id, final_score, final_feedback, teacher_comment, review_status
    )
    _recalculate_final_total_score(conn, review.kertas2_review_id)

    return get_kertas2_review_item_by_id(conn, kertas2_review_item_id)


def save_kertas2_review_comment(
    conn: sqlite3.Connection, kertas2_review_id: int, teacher_id: int, teacher_overall_comment: Optional[str]
) -> Kertas2FeedbackReview:
    """Save the overall teacher comment while kertas2_review_id is still a draft."""
    review = get_kertas2_review_by_id(conn, kertas2_review_id)
    if review is None:
        raise ValueError(f"Review not found: {kertas2_review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only edit your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has been finalized and can no longer be edited.")

    update_kertas2_review_comment(conn, kertas2_review_id, teacher_overall_comment)
    return get_kertas2_review_by_id(conn, kertas2_review_id)


def finalize_kertas2_review(
    conn: sqlite3.Connection, kertas2_review_id: int, teacher_id: int
) -> Kertas2FeedbackReview:
    """Finalize kertas2_review_id, recalculating its final_total_score first.

    Raises ValueError if the review doesn't exist, isn't owned by
    teacher_id, or is already finalized.
    """
    review = get_kertas2_review_by_id(conn, kertas2_review_id)
    if review is None:
        raise ValueError(f"Review not found: {kertas2_review_id}")
    if review.teacher_id != teacher_id:
        raise ValueError("You can only finalize your own reviews.")
    if review.status != STATUS_DRAFT:
        raise ValueError("This review has already been finalized.")

    _recalculate_final_total_score(conn, kertas2_review_id)
    finalize_kertas2_review_row(conn, kertas2_review_id)
    return get_kertas2_review_by_id(conn, kertas2_review_id)


def get_kertas2_review_for_student(
    conn: sqlite3.Connection, attempt_id: int, student_id: int
) -> Optional[Kertas2FeedbackReview]:
    """Return the finalized Kertas 2 review for attempt_id if student_id owns
    that attempt and a finalized review exists, else None.

    Raises ValueError if the attempt doesn't exist or doesn't belong to
    student_id. Never exposes a draft review to the student.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")
    if attempt.student_id != student_id:
        raise ValueError("You can only view your own attempt's review.")

    review = get_latest_kertas2_review_for_attempt(conn, attempt_id)
    if review is None or review.status != STATUS_FINALIZED:
        return None
    return review


def get_kertas2_review(conn: sqlite3.Connection, kertas2_review_id: int) -> Optional[Kertas2FeedbackReview]:
    return get_kertas2_review_by_id(conn, kertas2_review_id)


def get_kertas2_review_for_feedback_job(
    conn: sqlite3.Connection, feedback_job_id: int
) -> Optional[Kertas2FeedbackReview]:
    return get_kertas2_review_by_feedback_job_id(conn, feedback_job_id)


def get_latest_kertas2_review(conn: sqlite3.Connection, attempt_id: int) -> Optional[Kertas2FeedbackReview]:
    return get_latest_kertas2_review_for_attempt(conn, attempt_id)


def list_kertas2_review_items(conn: sqlite3.Connection, kertas2_review_id: int) -> List[Kertas2FeedbackReviewItem]:
    return get_kertas2_review_items_for_review(conn, kertas2_review_id)
