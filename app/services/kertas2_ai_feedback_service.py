"""Kertas 2 AI feedback draft orchestration for the Teacher role.

Generates a *draft* suggested score and feedback text per rubric
criterion/question for a Kertas 2 attempt, using a pluggable AI feedback
provider (see app/utils/ai_feedback_engine.py). This stage stores draft
suggestions only - no marking_jobs/marking_reviews are created, no final
score is produced, and nothing is shown to students. No cloud/network AI
calls are made; the production provider is local/offline-only and fails
gracefully if unavailable.

Stage 8C additionally records an audit trail for each item (the exact
prompt sent, the provider's raw output, and any parser error) plus
job-level provider/diagnostic snapshots, so a teacher can inspect why a
given item was generated, failed, or needs review. This is a read-only
audit trail: it never overwrites extracted answers, marking setup, prior
feedback history, or finalized reviews.
"""

import sqlite3
from typing import Dict, List, Optional, Tuple

from app.models.answer_extraction_model import (
    ExtractedAttemptAnswer,
    EXTRACTION_STATUS_EXTRACTED,
    EXTRACTION_STATUS_NO_TEXT,
    STATUS_COMPLETED as ANSWER_EXTRACTION_STATUS_COMPLETED,
    get_answer_extraction_job_by_id,
    get_extracted_attempt_answers_for_job,
)
from app.models.class_model import get_class_by_id
from app.models.kertas2_ai_feedback_model import (
    Kertas2AIFeedbackItem,
    Kertas2AIFeedbackJob,
    add_feedback_item,
    create_feedback_job,
    get_feedback_items_for_job,
    get_feedback_job_by_id,
    get_latest_feedback_job_for_attempt,
    mark_feedback_job_completed,
    mark_feedback_job_failed,
    AUDIT_STATUS_GENERATED,
    AUDIT_STATUS_NEEDS_REVIEW,
    AUDIT_STATUS_NO_ANSWER,
    AUDIT_STATUS_PARSER_FAILED,
    AUDIT_STATUS_PROVIDER_FAILED,
    FEEDBACK_STATUS_FAILED,
    FEEDBACK_STATUS_GENERATED,
    FEEDBACK_STATUS_NEEDS_REVIEW,
    FEEDBACK_STATUS_NO_ANSWER,
)
from app.models.marking_setup_model import get_marking_questions_for_setup, get_marking_setup_by_material
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import PAPER_TYPE_KERTAS_2, get_material_by_id
from app.services.local_ai_settings_service import validate_local_ai_settings
from app.utils.ai_feedback_engine import (
    AIFeedbackInput,
    AIFeedbackParseError,
    AIFeedbackProvider,
    DependencyUnavailableError,
    build_kertas2_feedback_prompt,
    get_default_provider,
)

_NEEDS_REVIEW_REASONS = {
    "no_region": "This criterion has no region linked in the marking setup.",
    "pending_detection": "Answer selection could not be automatically detected yet.",
    "failed": "Region extraction failed for this criterion - needs manual review.",
}
_MISSING_ANSWER_REASON = "No extracted answer was found for this criterion."
_NO_TEXT_REASON = "No text was extracted for this criterion's region."


def run_kertas2_ai_feedback_for_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    answer_extraction_job_id: int,
    provider: Optional[AIFeedbackProvider] = None,
) -> Kertas2AIFeedbackJob:
    """Generate draft AI feedback for attempt_id's Kertas 2 extracted answers.

    Raises ValueError before any feedback job is created if the attempt,
    answer extraction job, or marking setup prerequisites are invalid, or
    if the marking setup is Kertas 1 (this flow is Kertas 2 only). Once the
    job is created, any unexpected error - including the AI provider being
    unavailable - is caught and stored as a failed job with a readable
    error_message instead of propagating or fabricating a result.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")

    answer_extraction_job = get_answer_extraction_job_by_id(conn, answer_extraction_job_id)
    if answer_extraction_job is None:
        raise ValueError(f"Answer extraction job not found: {answer_extraction_job_id}")
    if answer_extraction_job.status != ANSWER_EXTRACTION_STATUS_COMPLETED:
        raise ValueError(
            f"Answer extraction job {answer_extraction_job_id} is not completed "
            f"(status: {answer_extraction_job.status})."
        )
    if answer_extraction_job.attempt_id != attempt_id:
        raise ValueError(
            f"Answer extraction job {answer_extraction_job_id} does not belong to attempt {attempt_id}."
        )

    material = get_material_by_id(conn, attempt.material_id)
    if material is None:
        raise ValueError(f"Revision material not found for attempt {attempt_id}.")

    marking_setup = get_marking_setup_by_material(conn, material.material_id)
    if marking_setup is None:
        raise ValueError("No marking setup found for this revision material. Set up marking first.")

    if marking_setup.paper_type != PAPER_TYPE_KERTAS_2:
        raise ValueError("Kertas 1 uses rule-based marking.")

    questions = get_marking_questions_for_setup(conn, marking_setup.setup_id)
    if not questions:
        raise ValueError("No marking criteria found for this marking setup. Add criteria first.")

    feedback_job = create_feedback_job(conn, attempt_id, answer_extraction_job_id, marking_setup.setup_id)

    provider_backend = None
    provider_model_path = None
    provider_status = None
    diagnostic_message = None

    try:
        answers = get_extracted_attempt_answers_for_job(conn, answer_extraction_job_id)
        answers_by_question_id: Dict[int, ExtractedAttemptAnswer] = {
            answer.question_id: answer for answer in answers
        }

        if provider is not None:
            active_provider = provider
        else:
            # Only the default (local/offline) provider path is backed by an
            # inspectable configuration - a caller-supplied provider (e.g. a
            # test fake) has no local_ai_settings diagnostic to snapshot.
            # Settings are per-teacher (Stage 10B): resolve the teacher who
            # owns the attempt's class, so each teacher's own Local AI
            # Settings are used rather than a single shared configuration.
            owning_class = get_class_by_id(conn, attempt.class_id)
            owning_teacher_id = owning_class.teacher_id if owning_class is not None else None
            diagnostic = validate_local_ai_settings(conn, owning_teacher_id)
            provider_backend = diagnostic.backend_name
            provider_model_path = diagnostic.model_path
            provider_status = diagnostic.status
            diagnostic_message = diagnostic.message
            active_provider = get_default_provider(conn, owning_teacher_id)

        generated_count = 0
        for question in questions:
            answer = answers_by_question_id.get(question.question_id)

            if answer is None:
                add_feedback_item(
                    conn,
                    feedback_job.feedback_job_id,
                    question.question_id,
                    None,
                    question.question_no,
                    question.question_type,
                    None,
                    question.correct_answer or None,
                    0,
                    question.max_mark,
                    None,
                    _MISSING_ANSWER_REASON,
                    None,
                    FEEDBACK_STATUS_NO_ANSWER,
                    audit_status=AUDIT_STATUS_NO_ANSWER,
                )
                continue

            if answer.extraction_status == EXTRACTION_STATUS_NO_TEXT:
                add_feedback_item(
                    conn,
                    feedback_job.feedback_job_id,
                    question.question_id,
                    answer.extracted_answer_id,
                    question.question_no,
                    question.question_type,
                    answer.raw_text,
                    question.correct_answer or None,
                    0,
                    question.max_mark,
                    None,
                    _NO_TEXT_REASON,
                    None,
                    FEEDBACK_STATUS_NO_ANSWER,
                    audit_status=AUDIT_STATUS_NO_ANSWER,
                )
                continue

            if answer.extraction_status != EXTRACTION_STATUS_EXTRACTED:
                reason = _NEEDS_REVIEW_REASONS.get(
                    answer.extraction_status,
                    f"Extraction status '{answer.extraction_status}' needs manual review.",
                )
                add_feedback_item(
                    conn,
                    feedback_job.feedback_job_id,
                    question.question_id,
                    answer.extracted_answer_id,
                    question.question_no,
                    question.question_type,
                    answer.raw_text,
                    question.correct_answer or None,
                    0,
                    question.max_mark,
                    None,
                    reason,
                    None,
                    FEEDBACK_STATUS_NEEDS_REVIEW,
                    audit_status=AUDIT_STATUS_NEEDS_REVIEW,
                )
                continue

            input_data = AIFeedbackInput(
                criterion_name=question.question_no,
                question_type=question.question_type,
                student_answer=answer.extracted_answer or "",
                sample_answer=question.correct_answer or None,
                max_mark=question.max_mark,
                rubric_notes=question.explanation,
            )
            prompt_snapshot = build_kertas2_feedback_prompt(input_data)

            try:
                result = active_provider.generate_feedback(input_data)
            except AIFeedbackParseError as exc:
                # This criterion's provider output could not be parsed - record
                # it for audit and move on to the next criterion, since other
                # criteria may still succeed (this is a per-item failure, not
                # a whole-job failure).
                add_feedback_item(
                    conn,
                    feedback_job.feedback_job_id,
                    question.question_id,
                    answer.extracted_answer_id,
                    question.question_no,
                    question.question_type,
                    answer.extracted_answer,
                    question.correct_answer or None,
                    0,
                    question.max_mark,
                    None,
                    str(exc),
                    None,
                    FEEDBACK_STATUS_FAILED,
                    prompt_snapshot=prompt_snapshot,
                    raw_provider_output=exc.raw_output,
                    parser_error=str(exc),
                    audit_status=AUDIT_STATUS_PARSER_FAILED,
                )
                continue
            except DependencyUnavailableError as exc:
                # The provider itself is unavailable mid-run (e.g. real model
                # inference not implemented yet) - record what we can for this
                # item, then let the whole job fail as before (current
                # architecture treats provider unavailability as job-level).
                add_feedback_item(
                    conn,
                    feedback_job.feedback_job_id,
                    question.question_id,
                    answer.extracted_answer_id,
                    question.question_no,
                    question.question_type,
                    answer.extracted_answer,
                    question.correct_answer or None,
                    0,
                    question.max_mark,
                    None,
                    str(exc),
                    None,
                    FEEDBACK_STATUS_FAILED,
                    prompt_snapshot=prompt_snapshot,
                    audit_status=AUDIT_STATUS_PROVIDER_FAILED,
                )
                raise

            add_feedback_item(
                conn,
                feedback_job.feedback_job_id,
                question.question_id,
                answer.extracted_answer_id,
                question.question_no,
                question.question_type,
                answer.extracted_answer,
                question.correct_answer or None,
                result.suggested_score,
                result.max_mark,
                result.feedback_text,
                result.reason,
                result.confidence,
                FEEDBACK_STATUS_GENERATED,
                prompt_snapshot=prompt_snapshot,
                raw_provider_output=result.raw_output,
                audit_status=AUDIT_STATUS_GENERATED,
            )
            generated_count += 1

        mark_feedback_job_completed(
            conn,
            feedback_job.feedback_job_id,
            len(questions),
            generated_count,
            provider_backend=provider_backend,
            provider_model_path=provider_model_path,
            provider_status=provider_status,
            diagnostic_message=diagnostic_message,
        )
    except Exception as exc:
        mark_feedback_job_failed(
            conn,
            feedback_job.feedback_job_id,
            str(exc),
            provider_backend=provider_backend,
            provider_model_path=provider_model_path,
            provider_status=provider_status,
            diagnostic_message=diagnostic_message,
        )

    return get_feedback_job_by_id(conn, feedback_job.feedback_job_id)


def get_feedback_job(conn: sqlite3.Connection, feedback_job_id: int) -> Optional[Kertas2AIFeedbackJob]:
    return get_feedback_job_by_id(conn, feedback_job_id)


def get_latest_feedback_job(conn: sqlite3.Connection, attempt_id: int) -> Optional[Kertas2AIFeedbackJob]:
    return get_latest_feedback_job_for_attempt(conn, attempt_id)


def list_feedback_items(conn: sqlite3.Connection, feedback_job_id: int) -> List:
    return get_feedback_items_for_job(conn, feedback_job_id)


def get_feedback_job_audit_for_teacher(
    conn: sqlite3.Connection, feedback_job_id: int, teacher_id: int
) -> Tuple[Kertas2AIFeedbackJob, List[Kertas2AIFeedbackItem]]:
    """Return (feedback_job, items) with full audit fields for feedback_job_id,
    if it belongs to a class owned by teacher_id.

    Raises ValueError if the feedback job doesn't exist, or its attempt
    doesn't belong to a class owned by teacher_id. This is a read-only
    lookup - it never modifies extracted answers, marking setup, feedback
    history, or finalized reviews.
    """
    feedback_job = get_feedback_job_by_id(conn, feedback_job_id)
    if feedback_job is None:
        raise ValueError(f"Kertas 2 feedback job not found: {feedback_job_id}")

    attempt = get_attempt_by_id(conn, feedback_job.attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {feedback_job.attempt_id}")

    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only view audit information for attempts from classes you own.")

    items = get_feedback_items_for_job(conn, feedback_job_id)
    return feedback_job, items
