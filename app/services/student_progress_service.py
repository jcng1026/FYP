"""Read-only student dashboard progress summary service (Stage 9E).

This service summarizes only student-visible material, attempt, and
finalized-result information. It never creates attempts, preprocessing, OCR,
extraction, marking, review, AI feedback, or export records, and it does not
expose teacher-only workflow/audit/readiness details.
"""

import sqlite3
from datetime import datetime
from typing import List, Set

from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2
from app.models.student_progress_model import (
    ACTION_SUBMIT_ATTEMPT,
    ACTION_VIEW_ATTEMPT,
    ACTION_VIEW_RESULT,
    DISPLAY_STATUS_AVAILABLE_MATERIAL,
    DISPLAY_STATUS_FINAL_RESULT_AVAILABLE,
    DISPLAY_STATUS_PENDING_REVIEW,
    ITEM_TYPE_ATTEMPT,
    ITEM_TYPE_MATERIAL,
    ITEM_TYPE_RESULT,
    StudentProgressItem,
    StudentProgressSummary,
)
from app.models.user_model import get_user_by_id
from app.services.class_student_service import list_classes_for_student
from app.services.result_summary_service import list_student_finalized_results
from app.services.revision_attempt_service import list_attempts_for_student
from app.services.revision_material_service import list_materials_for_student


def _timestamp(value: str) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0


def _sort_recent_items(items: List[StudentProgressItem]) -> List[StudentProgressItem]:
    return sorted(items, key=lambda item: -_timestamp(item.submitted_at_or_finalized_at))


def get_student_progress_summary(conn: sqlite3.Connection, student_id: int) -> StudentProgressSummary:
    """Return read-only dashboard progress data for one student."""
    student = get_user_by_id(conn, student_id)
    classes = list_classes_for_student(conn, student_id)
    materials = list_materials_for_student(conn, student_id)
    attempts = list_attempts_for_student(conn, student_id)
    finalized_results = list_student_finalized_results(conn, student_id)
    finalized_attempt_ids: Set[int] = {result.attempt_id for result in finalized_results}

    kertas1_attempts = sum(1 for attempt in attempts if attempt.paper_type == PAPER_TYPE_KERTAS_1)
    kertas2_attempts = sum(1 for attempt in attempts if attempt.paper_type == PAPER_TYPE_KERTAS_2)

    recent_items: List[StudentProgressItem] = []
    for material in materials:
        recent_items.append(
            StudentProgressItem(
                item_type=ITEM_TYPE_MATERIAL,
                material_id=material.material_id,
                attempt_id=None,
                review_id=None,
                result_type=None,
                material_title=material.title,
                paper_type=material.paper_type,
                status=DISPLAY_STATUS_AVAILABLE_MATERIAL,
                display_status=DISPLAY_STATUS_AVAILABLE_MATERIAL,
                submitted_at_or_finalized_at=material.created_at,
                action_label=ACTION_SUBMIT_ATTEMPT,
            )
        )

    for attempt in attempts:
        display_status = (
            DISPLAY_STATUS_FINAL_RESULT_AVAILABLE
            if attempt.attempt_id in finalized_attempt_ids
            else DISPLAY_STATUS_PENDING_REVIEW
        )
        recent_items.append(
            StudentProgressItem(
                item_type=ITEM_TYPE_ATTEMPT,
                material_id=attempt.material_id,
                attempt_id=attempt.attempt_id,
                review_id=None,
                result_type=None,
                material_title=attempt.material_title,
                paper_type=attempt.paper_type,
                status=attempt.status,
                display_status=display_status,
                submitted_at_or_finalized_at=attempt.submitted_at,
                action_label=ACTION_VIEW_ATTEMPT,
            )
        )

    for result in finalized_results:
        recent_items.append(
            StudentProgressItem(
                item_type=ITEM_TYPE_RESULT,
                material_id=None,
                attempt_id=result.attempt_id,
                review_id=result.review_id,
                result_type=result.result_type,
                material_title=result.material_title,
                paper_type=result.paper_type,
                status=DISPLAY_STATUS_FINAL_RESULT_AVAILABLE,
                display_status=DISPLAY_STATUS_FINAL_RESULT_AVAILABLE,
                submitted_at_or_finalized_at=result.finalized_at,
                action_label=ACTION_VIEW_RESULT,
            )
        )

    return StudentProgressSummary(
        student_id=student_id,
        student_name=student.full_name if student else "Student",
        class_count=len(classes),
        available_materials=len(materials),
        submitted_attempts=len(attempts),
        pending_attempts=sum(1 for attempt in attempts if attempt.attempt_id not in finalized_attempt_ids),
        finalized_results=len(finalized_results),
        kertas1_attempts=kertas1_attempts,
        kertas2_attempts=kertas2_attempts,
        recent_items=_sort_recent_items(recent_items),
    )
