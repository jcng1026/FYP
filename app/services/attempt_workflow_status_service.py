"""Read-only attempt workflow status and next-action orchestration (Stage 9A).

Inspects the existing pipeline tables (preprocessing, OCR, template region
extraction, answer extraction, Kertas 1 marking/review or Kertas 2 AI
feedback/review, finalized results) for a revision attempt and reports:
- which steps are done, pending, failed, or blocked on a prior step
- the single recommended next action
- an overall status summary

This module is strictly read-only: it never creates preprocessing/OCR/
extraction/marking/feedback jobs, never creates or edits review records,
and never writes an export file. It only calls existing get_latest_*
lookups from other services/models.
"""

import sqlite3
from typing import List, Optional, Tuple

from app.models.answer_extraction_model import STATUS_COMPLETED as ANSWER_EXTRACTION_STATUS_COMPLETED
from app.models.attempt_workflow_status_model import (
    AttemptWorkflowStatus,
    NEXT_ACTION_WORKFLOW_COMPLETE,
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_FINALIZED,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_STARTED,
    STATUS_PENDING,
    WorkflowStep,
)
from app.models.class_model import get_class_by_id
from app.models.extraction_model import STATUS_COMPLETED as EXTRACTION_STATUS_COMPLETED
from app.models.kertas2_ai_feedback_model import STATUS_COMPLETED as KERTAS2_FEEDBACK_STATUS_COMPLETED
from app.models.kertas2_feedback_review_model import STATUS_FINALIZED as KERTAS2_REVIEW_STATUS_FINALIZED
from app.models.marking_review_model import STATUS_FINALIZED as KERTAS1_REVIEW_STATUS_FINALIZED
from app.models.ocr_model import STATUS_COMPLETED as OCR_STATUS_COMPLETED
from app.models.preprocessing_model import (
    SOURCE_TYPE_REVISION_ATTEMPT_ANSWER,
    STATUS_COMPLETED as PREPROCESSING_STATUS_COMPLETED,
)
from app.models.revision_attempt_model import get_attempt_by_id, get_attempts_for_teacher
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, get_material_by_id
from app.models.user_model import get_user_by_id
from app.services.answer_extraction_service import get_latest_answer_extraction_job
from app.services.extraction_service import get_latest_extraction_job
from app.services.kertas1_marking_service import get_latest_marking_job
from app.services.kertas2_ai_feedback_service import get_latest_feedback_job
from app.services.kertas2_feedback_review_service import get_latest_kertas2_review
from app.services.marking_review_service import get_latest_review
from app.services.ocr_service import get_latest_ocr_job
from app.services.preprocessing_service import get_latest_preprocessing_job

STEP_ATTEMPT_UPLOADED = "attempt_uploaded"
STEP_PREPROCESSING = "preprocessing"
STEP_OCR = "ocr"
STEP_REGION_EXTRACTION = "region_extraction"
STEP_ANSWER_EXTRACTION = "answer_extraction"
STEP_KERTAS1_MARKING = "kertas1_marking"
STEP_KERTAS1_REVIEW = "kertas1_review"
STEP_KERTAS2_FEEDBACK = "kertas2_feedback"
STEP_KERTAS2_REVIEW = "kertas2_review"
STEP_FINAL_RESULT = "final_result"
STEP_CSV_EXPORT = "csv_export"

_NEXT_ACTION_BY_STEP = {
    STEP_PREPROCESSING: "Preprocess document",
    STEP_OCR: "Run OCR",
    STEP_REGION_EXTRACTION: "Extract template regions",
    STEP_ANSWER_EXTRACTION: "Extract answers",
    STEP_KERTAS1_MARKING: "Mark Kertas 1",
    STEP_KERTAS1_REVIEW: "Review Kertas 1 marking",
    STEP_KERTAS2_FEEDBACK: "Generate Kertas 2 feedback",
    STEP_KERTAS2_REVIEW: "Review Kertas 2 feedback",
}
_INVESTIGATE_FAILED_KERTAS2_FEEDBACK = "Investigate failed Kertas 2 AI feedback"


def _step(step_key: str, step_label: str, status: str, related_record_id: Optional[int], message: str) -> WorkflowStep:
    return WorkflowStep(
        step_key=step_key,
        step_label=step_label,
        status=status,
        related_record_id=related_record_id,
        message=message,
    )


def _common_steps(conn: sqlite3.Connection, attempt) -> List[WorkflowStep]:
    steps = [
        _step(
            STEP_ATTEMPT_UPLOADED, "Attempt uploaded", STATUS_COMPLETED, attempt.attempt_id,
            "Student submitted this attempt.",
        )
    ]

    preprocessing_job = get_latest_preprocessing_job(conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, attempt.attempt_id)
    if preprocessing_job is None:
        steps.append(_step(STEP_PREPROCESSING, "Preprocessing completed", STATUS_NOT_STARTED, None, "Not started yet."))
    elif preprocessing_job.status == PREPROCESSING_STATUS_COMPLETED:
        steps.append(_step(
            STEP_PREPROCESSING, "Preprocessing completed", STATUS_COMPLETED, preprocessing_job.job_id,
            "Preprocessing completed.",
        ))
    elif preprocessing_job.status == "failed":
        steps.append(_step(
            STEP_PREPROCESSING, "Preprocessing completed", STATUS_FAILED, preprocessing_job.job_id,
            preprocessing_job.error_message or "Preprocessing failed.",
        ))
    else:
        steps.append(_step(
            STEP_PREPROCESSING, "Preprocessing completed", STATUS_PENDING, preprocessing_job.job_id,
            "Preprocessing is in progress.",
        ))

    preprocessing_done = steps[-1].status == STATUS_COMPLETED
    if not preprocessing_done:
        steps.append(_step(STEP_OCR, "OCR completed", STATUS_BLOCKED, None, "Waiting for preprocessing to complete first."))
    else:
        ocr_job = get_latest_ocr_job(conn, preprocessing_job.job_id)
        if ocr_job is None:
            steps.append(_step(STEP_OCR, "OCR completed", STATUS_NOT_STARTED, None, "Not started yet."))
        elif ocr_job.status == OCR_STATUS_COMPLETED:
            steps.append(_step(STEP_OCR, "OCR completed", STATUS_COMPLETED, ocr_job.ocr_job_id, "OCR completed."))
        elif ocr_job.status == "failed":
            steps.append(_step(
                STEP_OCR, "OCR completed", STATUS_FAILED, ocr_job.ocr_job_id,
                ocr_job.error_message or "OCR failed.",
            ))
        else:
            steps.append(_step(STEP_OCR, "OCR completed", STATUS_PENDING, ocr_job.ocr_job_id, "OCR is in progress."))

    ocr_done = steps[-1].status == STATUS_COMPLETED
    if not ocr_done:
        steps.append(_step(
            STEP_REGION_EXTRACTION, "Template region extraction completed", STATUS_BLOCKED, None,
            "Waiting for OCR to complete first.",
        ))
    else:
        extraction_job = get_latest_extraction_job(conn, attempt.attempt_id)
        if extraction_job is None:
            steps.append(_step(
                STEP_REGION_EXTRACTION, "Template region extraction completed", STATUS_NOT_STARTED, None,
                "Not started yet.",
            ))
        elif extraction_job.status == EXTRACTION_STATUS_COMPLETED:
            steps.append(_step(
                STEP_REGION_EXTRACTION, "Template region extraction completed", STATUS_COMPLETED,
                extraction_job.extraction_job_id, "Template region extraction completed.",
            ))
        elif extraction_job.status == "failed":
            steps.append(_step(
                STEP_REGION_EXTRACTION, "Template region extraction completed", STATUS_FAILED,
                extraction_job.extraction_job_id, extraction_job.error_message or "Template region extraction failed.",
            ))
        else:
            steps.append(_step(
                STEP_REGION_EXTRACTION, "Template region extraction completed", STATUS_PENDING,
                extraction_job.extraction_job_id, "Template region extraction is in progress.",
            ))

    region_extraction_done = steps[-1].status == STATUS_COMPLETED
    if not region_extraction_done:
        steps.append(_step(
            STEP_ANSWER_EXTRACTION, "Structured answer extraction completed", STATUS_BLOCKED, None,
            "Waiting for template region extraction to complete first.",
        ))
    else:
        answer_job = get_latest_answer_extraction_job(conn, attempt.attempt_id)
        if answer_job is None:
            steps.append(_step(
                STEP_ANSWER_EXTRACTION, "Structured answer extraction completed", STATUS_NOT_STARTED, None,
                "Not started yet.",
            ))
        elif answer_job.status == ANSWER_EXTRACTION_STATUS_COMPLETED:
            steps.append(_step(
                STEP_ANSWER_EXTRACTION, "Structured answer extraction completed", STATUS_COMPLETED,
                answer_job.answer_extraction_job_id, "Structured answer extraction completed.",
            ))
        elif answer_job.status == "failed":
            steps.append(_step(
                STEP_ANSWER_EXTRACTION, "Structured answer extraction completed", STATUS_FAILED,
                answer_job.answer_extraction_job_id, answer_job.error_message or "Answer extraction failed.",
            ))
        else:
            steps.append(_step(
                STEP_ANSWER_EXTRACTION, "Structured answer extraction completed", STATUS_PENDING,
                answer_job.answer_extraction_job_id, "Structured answer extraction is in progress.",
            ))

    return steps


def _kertas1_steps(conn: sqlite3.Connection, attempt, answer_extraction_done: bool) -> List[WorkflowStep]:
    steps = []

    if not answer_extraction_done:
        steps.append(_step(
            STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_BLOCKED, None,
            "Waiting for answer extraction to complete first.",
        ))
    else:
        marking_job = get_latest_marking_job(conn, attempt.attempt_id)
        if marking_job is None:
            steps.append(_step(STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_NOT_STARTED, None, "Not started yet."))
        elif marking_job.status == "failed":
            steps.append(_step(
                STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_FAILED, marking_job.marking_job_id,
                marking_job.error_message or "Kertas 1 marking failed.",
            ))
        elif marking_job.status == STATUS_COMPLETED:
            if marking_job.needs_review_count > 0:
                steps.append(_step(
                    STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_NEEDS_REVIEW, marking_job.marking_job_id,
                    f"{marking_job.needs_review_count} question(s) flagged for manual review.",
                ))
            else:
                steps.append(_step(
                    STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_COMPLETED, marking_job.marking_job_id,
                    "Kertas 1 marking completed.",
                ))
        else:
            steps.append(_step(
                STEP_KERTAS1_MARKING, "Kertas 1 marking completed", STATUS_PENDING, marking_job.marking_job_id,
                "Kertas 1 marking is in progress.",
            ))

    marking_done = steps[-1].status in (STATUS_COMPLETED, STATUS_NEEDS_REVIEW)
    if not marking_done:
        steps.append(_step(
            STEP_KERTAS1_REVIEW, "Kertas 1 teacher review finalized", STATUS_BLOCKED, None,
            "Waiting for Kertas 1 marking to complete first.",
        ))
    else:
        review = get_latest_review(conn, attempt.attempt_id)
        if review is None:
            steps.append(_step(STEP_KERTAS1_REVIEW, "Kertas 1 teacher review finalized", STATUS_NOT_STARTED, None, "Not started yet."))
        elif review.status == KERTAS1_REVIEW_STATUS_FINALIZED:
            steps.append(_step(
                STEP_KERTAS1_REVIEW, "Kertas 1 teacher review finalized", STATUS_FINALIZED, review.review_id,
                "Kertas 1 review finalized.",
            ))
        else:
            steps.append(_step(
                STEP_KERTAS1_REVIEW, "Kertas 1 teacher review finalized", STATUS_PENDING, review.review_id,
                "Kertas 1 review is still a draft - not yet finalized.",
            ))

    review_finalized = steps[-1].status == STATUS_FINALIZED
    related_record_id = steps[-1].related_record_id if review_finalized else None
    steps.append(_final_result_step(review_finalized, related_record_id))
    steps.append(_csv_export_step(review_finalized))
    return steps


def _kertas2_steps(conn: sqlite3.Connection, attempt, answer_extraction_done: bool) -> List[WorkflowStep]:
    steps = []

    if not answer_extraction_done:
        steps.append(_step(
            STEP_KERTAS2_FEEDBACK, "Kertas 2 AI feedback draft completed or failed", STATUS_BLOCKED, None,
            "Waiting for answer extraction to complete first.",
        ))
    else:
        feedback_job = get_latest_feedback_job(conn, attempt.attempt_id)
        if feedback_job is None:
            steps.append(_step(
                STEP_KERTAS2_FEEDBACK, "Kertas 2 AI feedback draft completed or failed", STATUS_NOT_STARTED, None,
                "Not started yet.",
            ))
        elif feedback_job.status == "failed":
            steps.append(_step(
                STEP_KERTAS2_FEEDBACK, "Kertas 2 AI feedback draft completed or failed", STATUS_FAILED,
                feedback_job.feedback_job_id, feedback_job.error_message or "Kertas 2 AI feedback generation failed.",
            ))
        elif feedback_job.status == KERTAS2_FEEDBACK_STATUS_COMPLETED:
            steps.append(_step(
                STEP_KERTAS2_FEEDBACK, "Kertas 2 AI feedback draft completed or failed", STATUS_COMPLETED,
                feedback_job.feedback_job_id, "Kertas 2 AI feedback draft generated.",
            ))
        else:
            steps.append(_step(
                STEP_KERTAS2_FEEDBACK, "Kertas 2 AI feedback draft completed or failed", STATUS_PENDING,
                feedback_job.feedback_job_id, "Kertas 2 AI feedback generation is in progress.",
            ))

    feedback_status = steps[-1].status
    if feedback_status == STATUS_FAILED:
        steps.append(_step(
            STEP_KERTAS2_REVIEW, "Kertas 2 teacher review finalized", STATUS_BLOCKED, None,
            "Kertas 2 AI feedback failed - investigate before reviewing.",
        ))
    elif feedback_status != STATUS_COMPLETED:
        steps.append(_step(
            STEP_KERTAS2_REVIEW, "Kertas 2 teacher review finalized", STATUS_BLOCKED, None,
            "Waiting for Kertas 2 AI feedback to complete first.",
        ))
    else:
        review = get_latest_kertas2_review(conn, attempt.attempt_id)
        if review is None:
            steps.append(_step(STEP_KERTAS2_REVIEW, "Kertas 2 teacher review finalized", STATUS_NOT_STARTED, None, "Not started yet."))
        elif review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            steps.append(_step(
                STEP_KERTAS2_REVIEW, "Kertas 2 teacher review finalized", STATUS_FINALIZED, review.kertas2_review_id,
                "Kertas 2 review finalized.",
            ))
        else:
            steps.append(_step(
                STEP_KERTAS2_REVIEW, "Kertas 2 teacher review finalized", STATUS_PENDING, review.kertas2_review_id,
                "Kertas 2 review is still a draft - not yet finalized.",
            ))

    review_finalized = steps[-1].status == STATUS_FINALIZED
    related_record_id = steps[-1].related_record_id if review_finalized else None
    steps.append(_final_result_step(review_finalized, related_record_id))
    steps.append(_csv_export_step(review_finalized))
    return steps


def _final_result_step(review_finalized: bool, related_record_id: Optional[int]) -> WorkflowStep:
    if review_finalized:
        return _step(STEP_FINAL_RESULT, "Final result available", STATUS_AVAILABLE, related_record_id, "Finalized result is available to view.")
    return _step(STEP_FINAL_RESULT, "Final result available", STATUS_BLOCKED, None, "Waiting for teacher review to be finalized first.")


def _csv_export_step(review_finalized: bool) -> WorkflowStep:
    if review_finalized:
        return _step(STEP_CSV_EXPORT, "CSV export available", STATUS_AVAILABLE, None, "Result can be exported to CSV.")
    return _step(STEP_CSV_EXPORT, "CSV export available", STATUS_BLOCKED, None, "Waiting for a finalized result first.")


def get_next_action_for_attempt(steps: List[WorkflowStep]) -> Tuple[str, str]:
    """Return (next_action, current_stage) from an already-computed step list.

    Walks the steps in order and recommends the action for the first step
    that is not yet completed/finalized/available. Two steps are
    special-cased:
    - A failed Kertas 2 AI feedback step recommends investigating the
      failure rather than "Generate Kertas 2 feedback" again.
    - A finalized Kertas 1/Kertas 2 review recommends exporting the result
      (final_result/csv_export are always available once the review is
      finalized, so there is nothing further to check).
    """
    for step in steps:
        if step.step_key == STEP_ATTEMPT_UPLOADED:
            continue
        if step.step_key == STEP_KERTAS2_FEEDBACK and step.status == STATUS_FAILED:
            return _INVESTIGATE_FAILED_KERTAS2_FEEDBACK, step.step_key
        if step.step_key in (STEP_KERTAS1_REVIEW, STEP_KERTAS2_REVIEW) and step.status == STATUS_FINALIZED:
            return "Export finalized result", STEP_CSV_EXPORT
        if step.step_key in (STEP_FINAL_RESULT, STEP_CSV_EXPORT):
            continue
        if step.status not in (STATUS_COMPLETED, STATUS_NEEDS_REVIEW, STATUS_FINALIZED, STATUS_AVAILABLE):
            return _NEXT_ACTION_BY_STEP.get(step.step_key, step.step_label), step.step_key
        # STATUS_NEEDS_REVIEW (e.g. Kertas 1 marking with flagged questions)
        # still allows moving on to the review step, so keep walking.

    # Defensive fallback - not normally reachable given the step statuses
    # this service produces today, but kept in case a future step type adds
    # a status this loop doesn't otherwise resolve.
    return NEXT_ACTION_WORKFLOW_COMPLETE, STEP_CSV_EXPORT


def _overall_status(steps: List[WorkflowStep]) -> str:
    if any(step.status == STATUS_FAILED for step in steps):
        return STATUS_FAILED
    if any(step.status == STATUS_NEEDS_REVIEW for step in steps):
        return STATUS_NEEDS_REVIEW
    if steps[-1].status == STATUS_AVAILABLE:
        return STATUS_AVAILABLE
    if steps[1].status == STATUS_NOT_STARTED:
        return STATUS_NOT_STARTED
    return STATUS_PENDING


def _build_status(conn: sqlite3.Connection, attempt) -> AttemptWorkflowStatus:
    material = get_material_by_id(conn, attempt.material_id)
    class_ = get_class_by_id(conn, attempt.class_id)
    student = get_user_by_id(conn, attempt.student_id)

    steps = _common_steps(conn, attempt)
    answer_extraction_done = steps[-1].step_key == STEP_ANSWER_EXTRACTION and steps[-1].status == STATUS_COMPLETED

    if material.paper_type == PAPER_TYPE_KERTAS_1:
        steps.extend(_kertas1_steps(conn, attempt, answer_extraction_done))
    else:
        steps.extend(_kertas2_steps(conn, attempt, answer_extraction_done))

    next_action, current_stage = get_next_action_for_attempt(steps)
    overall_status = _overall_status(steps)

    return AttemptWorkflowStatus(
        attempt_id=attempt.attempt_id,
        material_title=material.title,
        paper_type=material.paper_type,
        student_id=attempt.student_id,
        student_name=student.full_name if student else "Unknown",
        class_name=class_.class_name if class_ else "Unknown",
        overall_status=overall_status,
        next_action=next_action,
        current_stage=current_stage,
        steps=steps,
    )


def get_attempt_workflow_status(conn: sqlite3.Connection, attempt_id: int, teacher_id: int) -> AttemptWorkflowStatus:
    """Return the read-only workflow status for attempt_id.

    Raises ValueError if the attempt doesn't exist, or doesn't belong to a
    class owned by teacher_id. Never creates or modifies any record - every
    lookup used here is an existing get_latest_* read.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")

    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only view workflow status for attempts from classes you own.")

    return _build_status(conn, attempt)


def list_teacher_attempt_workflow_statuses(conn: sqlite3.Connection, teacher_id: int) -> List[AttemptWorkflowStatus]:
    """Return workflow statuses for every attempt belonging to teacher_id,
    newest attempts first. Never includes another teacher's attempts, since
    get_attempts_for_teacher is already scoped to teacher_id."""
    rows = get_attempts_for_teacher(conn, teacher_id)
    statuses = []
    for row in rows:
        attempt = get_attempt_by_id(conn, row.attempt_id)
        if attempt is None:
            continue
        statuses.append(_build_status(conn, attempt))
    statuses.sort(key=lambda status: status.attempt_id, reverse=True)
    return statuses
