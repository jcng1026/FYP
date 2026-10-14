"""Kertas 1 rule-based marking orchestration for the Teacher role.

Compares each marking question's extracted answer against its
correct_answer using simple, deterministic string-comparison rules (no AI,
no similarity scoring) and stores a per-question result plus an
attempt-level summary. This stage is Kertas 1 only - Kertas 2 (essay/
writing) and Kertas 3 are explicitly out of scope and rejected.
"""

import sqlite3
from typing import Dict, List, Optional

from app.models.answer_extraction_model import (
    ExtractedAttemptAnswer,
    EXTRACTION_STATUS_EXTRACTED,
    STATUS_COMPLETED as ANSWER_EXTRACTION_STATUS_COMPLETED,
    get_answer_extraction_job_by_id,
    get_extracted_attempt_answers_for_job,
)
from app.models.class_model import get_class_by_id
from app.models.marking_result_model import (
    MarkingJob,
    add_marking_question_result,
    create_marking_job,
    get_latest_marking_job_for_attempt,
    get_marking_job_by_id,
    mark_marking_job_completed,
    mark_marking_job_failed,
    get_marking_question_results_for_job,
)
from app.models.marking_setup_model import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_SHORT_WORD,
    QUESTION_TYPE_WRITTEN_LETTER,
    get_marking_questions_for_setup,
    get_marking_setup_by_material,
)
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, get_material_by_id
from app.services.teacher_marking_settings_service import get_teacher_marking_settings
from app.utils.spelling_utils import is_likely_spelling_error

# Human-readable reasons for questions that could not be auto-marked because
# their extracted answer isn't in a directly-comparable state yet.
_NEEDS_REVIEW_REASONS = {
    "no_text": "No text was extracted for this question's region.",
    "no_region": "This question has no region linked in the marking setup.",
    "pending_detection": "Answer selection could not be automatically detected yet.",
    "failed": "Region extraction failed for this question - needs manual review.",
}
_MISSING_ANSWER_REASON = "No extracted answer was found for this question."
_SPELLING_DEDUCTION_REASON = "Likely spelling error detected. Spelling deduction applied."

# Question types considered "written/text" for spelling-deduction purposes.
# mcq/written_letter are single-letter answers (never text), and "other" is
# an ambiguous catch-all - per the conservative instruction to flag fewer
# spelling cases rather than more, only short_word is treated as free text.
_SPELLING_DEDUCTION_ELIGIBLE_QUESTION_TYPES = (QUESTION_TYPE_SHORT_WORD,)


def _normalize_whitespace(text: Optional[str]) -> str:
    return " ".join((text or "").strip().split())


def _is_clean_single_letter(text: Optional[str]) -> bool:
    stripped = (text or "").strip()
    return len(stripped) == 1 and stripped.isalpha()


def _is_answer_correct(question_type: str, extracted_answer: Optional[str], correct_answer: str) -> bool:
    """Deterministic, case rules per question_type - no AI, no fuzzy similarity."""
    if question_type in (QUESTION_TYPE_MCQ, QUESTION_TYPE_WRITTEN_LETTER):
        if not _is_clean_single_letter(extracted_answer) or not _is_clean_single_letter(correct_answer):
            return False
        return extracted_answer.strip().upper() == correct_answer.strip().upper()

    if question_type == QUESTION_TYPE_SHORT_WORD:
        return _normalize_whitespace(extracted_answer).lower() == _normalize_whitespace(correct_answer).lower()

    # "other" (and any other Kertas 1 question type): exact normalised text match only.
    return _normalize_whitespace(extracted_answer) == _normalize_whitespace(correct_answer)


def run_kertas1_marking_for_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    answer_extraction_job_id: int,
) -> MarkingJob:
    """Rule-based mark attempt_id's extracted answers using answer_extraction_job_id.

    Raises ValueError before any marking job is created if the attempt,
    answer extraction job, or marking setup prerequisites are invalid (this
    includes non-Kertas-1 papers, which are explicitly out of scope for this
    stage). Once the marking job is created, any unexpected error while
    scoring is caught and stored as a failed job with a readable
    error_message.
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

    if marking_setup.paper_type != PAPER_TYPE_KERTAS_1:
        raise ValueError(
            f"{marking_setup.paper_type} marking is not supported in this stage. "
            "Only Kertas 1 rule-based marking is available."
        )

    questions = get_marking_questions_for_setup(conn, marking_setup.setup_id)
    if not questions:
        raise ValueError("No marking questions found for this marking setup. Add questions first.")

    # Spelling deduction uses the settings of the teacher who owns the
    # attempt's class - falls back to the (enabled-by-default) settings if
    # the class has no owning teacher for some reason.
    marking_settings = None
    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is not None and class_.teacher_id is not None:
        marking_settings = get_teacher_marking_settings(conn, class_.teacher_id)

    marking_job = create_marking_job(
        conn, attempt_id, answer_extraction_job_id, marking_setup.setup_id, marking_setup.paper_type
    )

    try:
        answers = get_extracted_attempt_answers_for_job(conn, answer_extraction_job_id)
        answers_by_question_id: Dict[int, ExtractedAttemptAnswer] = {
            answer.question_id: answer for answer in answers
        }

        correct_count = 0
        needs_review_count = 0
        total_score = 0.0
        max_score = 0.0

        for question in questions:
            max_score += question.max_mark
            answer = answers_by_question_id.get(question.question_id)

            if answer is None:
                add_marking_question_result(
                    conn,
                    marking_job.marking_job_id,
                    question.question_id,
                    None,
                    question.question_no,
                    question.question_type,
                    question.correct_answer,
                    None,
                    None,
                    False,
                    True,
                    0,
                    question.max_mark,
                    None,
                    _MISSING_ANSWER_REASON,
                    question.explanation,
                )
                needs_review_count += 1
                continue

            if answer.extraction_status != EXTRACTION_STATUS_EXTRACTED:
                reason = _NEEDS_REVIEW_REASONS.get(
                    answer.extraction_status, f"Extraction status '{answer.extraction_status}' needs manual review."
                )
                add_marking_question_result(
                    conn,
                    marking_job.marking_job_id,
                    question.question_id,
                    answer.extracted_answer_id,
                    question.question_no,
                    question.question_type,
                    question.correct_answer,
                    answer.extracted_answer,
                    answer.raw_text,
                    False,
                    True,
                    0,
                    question.max_mark,
                    None,
                    reason,
                    question.explanation,
                )
                needs_review_count += 1
                continue

            is_correct = _is_answer_correct(question.question_type, answer.extracted_answer, question.correct_answer)
            needs_review_flag = False

            if is_correct:
                score_awarded = question.max_mark
                reason = "Answer matches the correct answer."
            elif (
                marking_settings is not None
                and marking_settings.spelling_deduction_enabled
                and question.question_type in _SPELLING_DEDUCTION_ELIGIBLE_QUESTION_TYPES
                and is_likely_spelling_error(answer.extracted_answer, question.correct_answer)
            ):
                score_awarded = max(0.0, question.max_mark - marking_settings.spelling_deduction_points)
                reason = _SPELLING_DEDUCTION_REASON
                needs_review_flag = True
            else:
                score_awarded = 0.0
                reason = "Answer does not match the correct answer."

            add_marking_question_result(
                conn,
                marking_job.marking_job_id,
                question.question_id,
                answer.extracted_answer_id,
                question.question_no,
                question.question_type,
                question.correct_answer,
                answer.extracted_answer,
                answer.raw_text,
                is_correct,
                needs_review_flag,
                score_awarded,
                question.max_mark,
                answer.confidence,
                reason,
                question.explanation,
            )
            if needs_review_flag:
                needs_review_count += 1
            if is_correct:
                correct_count += 1
            total_score += score_awarded

        mark_marking_job_completed(
            conn,
            marking_job.marking_job_id,
            len(questions),
            len(questions),
            correct_count,
            needs_review_count,
            total_score,
            max_score,
        )
    except Exception as exc:
        mark_marking_job_failed(conn, marking_job.marking_job_id, str(exc))

    return get_marking_job_by_id(conn, marking_job.marking_job_id)


def get_marking_job(conn: sqlite3.Connection, marking_job_id: int) -> Optional[MarkingJob]:
    return get_marking_job_by_id(conn, marking_job_id)


def get_latest_marking_job(conn: sqlite3.Connection, attempt_id: int) -> Optional[MarkingJob]:
    return get_latest_marking_job_for_attempt(conn, attempt_id)


def list_marking_question_results(conn: sqlite3.Connection, marking_job_id: int) -> List:
    return get_marking_question_results_for_job(conn, marking_job_id)
