"""Unified, read-only finalized-result summary and detail service for
teachers and students.

This stage only aggregates and reads already-finalized review data - it
never creates, modifies, or reopens any marking/review record, and never
exports anything.
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from app.models.class_model import get_class_by_id
from app.models.marking_review_model import STATUS_FINALIZED as KERTAS1_REVIEW_STATUS_FINALIZED
from app.models.kertas2_feedback_review_model import STATUS_FINALIZED as KERTAS2_REVIEW_STATUS_FINALIZED
from app.models.result_summary_model import (
    RESULT_TYPE_KERTAS1,
    RESULT_TYPE_KERTAS2,
    ResultSummaryRow,
    get_student_finalized_results,
    get_teacher_finalized_results,
)
from app.models.revision_attempt_model import get_attempt_by_id
from app.services.kertas1_marking_service import list_marking_question_results
from app.services.kertas2_feedback_review_service import get_kertas2_review, list_kertas2_review_items
from app.services.marking_review_service import get_review, list_review_items

ALLOWED_RESULT_TYPES = (RESULT_TYPE_KERTAS1, RESULT_TYPE_KERTAS2)


@dataclass
class Kertas1ResultDetailRow:
    question_no: str
    extracted_answer: Optional[str]
    correct_answer: str
    final_score: float
    max_mark: float
    teacher_comment: Optional[str]
    explanation: Optional[str]


@dataclass
class Kertas2ResultDetailRow:
    criterion_name: str
    student_answer: Optional[str]
    sample_answer: Optional[str]
    final_score: float
    max_mark: float
    final_feedback: Optional[str]
    teacher_comment: Optional[str]


def _validate_teacher_owns_attempt(conn: sqlite3.Connection, attempt_id: int, teacher_id: int) -> None:
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")
    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only view results for classes you own.")


def _validate_student_owns_attempt(conn: sqlite3.Connection, attempt_id: int, student_id: int) -> None:
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")
    if attempt.student_id != student_id:
        raise ValueError("You can only view your own results.")


def _build_kertas1_detail(conn: sqlite3.Connection, review_id: int):
    review = get_review(conn, review_id)
    if review is None or review.status != KERTAS1_REVIEW_STATUS_FINALIZED:
        raise ValueError(f"Finalized Kertas 1 review not found: {review_id}")

    items = list_review_items(conn, review.review_id)
    results_by_id = {
        result.marking_result_id: result
        for result in list_marking_question_results(conn, review.marking_job_id)
    }
    detail_rows = [
        Kertas1ResultDetailRow(
            question_no=item.question_no,
            extracted_answer=(results_by_id.get(item.marking_result_id).extracted_answer if item.marking_result_id in results_by_id else None),
            correct_answer=(results_by_id.get(item.marking_result_id).correct_answer if item.marking_result_id in results_by_id else ""),
            final_score=item.final_score_awarded,
            max_mark=item.max_mark,
            teacher_comment=item.teacher_comment,
            explanation=(results_by_id.get(item.marking_result_id).explanation if item.marking_result_id in results_by_id else None),
        )
        for item in items
    ]
    return review, detail_rows


def _build_kertas2_detail(conn: sqlite3.Connection, review_id: int):
    review = get_kertas2_review(conn, review_id)
    if review is None or review.status != KERTAS2_REVIEW_STATUS_FINALIZED:
        raise ValueError(f"Finalized Kertas 2 review not found: {review_id}")

    items = list_kertas2_review_items(conn, review.kertas2_review_id)
    detail_rows = [
        Kertas2ResultDetailRow(
            criterion_name=item.criterion_name,
            student_answer=item.student_answer,
            sample_answer=item.sample_answer,
            final_score=item.final_score,
            max_mark=item.max_mark,
            final_feedback=item.final_feedback,
            teacher_comment=item.teacher_comment,
        )
        for item in items
    ]
    return review, detail_rows


def list_teacher_finalized_results(conn: sqlite3.Connection, teacher_id: int) -> List[ResultSummaryRow]:
    return get_teacher_finalized_results(conn, teacher_id)


def list_student_finalized_results(conn: sqlite3.Connection, student_id: int) -> List[ResultSummaryRow]:
    return get_student_finalized_results(conn, student_id)


def get_result_detail_for_teacher(
    conn: sqlite3.Connection, result_type: str, review_id: int, teacher_id: int
) -> Tuple[object, List[Union[Kertas1ResultDetailRow, Kertas2ResultDetailRow]]]:
    """Return (review, detail_rows) for review_id, validating that
    result_type is supported and that teacher_id owns the attempt's class.

    Raises ValueError if result_type is unknown, the review doesn't exist
    or isn't finalized, or teacher_id doesn't own the class.
    """
    if result_type == RESULT_TYPE_KERTAS1:
        review, detail_rows = _build_kertas1_detail(conn, review_id)
    elif result_type == RESULT_TYPE_KERTAS2:
        review, detail_rows = _build_kertas2_detail(conn, review_id)
    else:
        raise ValueError(f"Unknown result_type: {result_type}")

    _validate_teacher_owns_attempt(conn, review.attempt_id, teacher_id)
    return review, detail_rows


def get_result_detail_for_student(
    conn: sqlite3.Connection, result_type: str, review_id: int, student_id: int
) -> Tuple[object, List[Union[Kertas1ResultDetailRow, Kertas2ResultDetailRow]]]:
    """Return (review, detail_rows) for review_id, validating that
    result_type is supported and that student_id owns the attempt.

    Raises ValueError if result_type is unknown, the review doesn't exist
    or isn't finalized, or student_id doesn't own the attempt.
    """
    if result_type == RESULT_TYPE_KERTAS1:
        review, detail_rows = _build_kertas1_detail(conn, review_id)
    elif result_type == RESULT_TYPE_KERTAS2:
        review, detail_rows = _build_kertas2_detail(conn, review_id)
    else:
        raise ValueError(f"Unknown result_type: {result_type}")

    _validate_student_owns_attempt(conn, review.attempt_id, student_id)
    return review, detail_rows
