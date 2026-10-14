"""Structured answer extraction orchestration for the Teacher role.

Matches each marking question to its linked template region's extracted
OCR text (from a completed region-extraction job) and stores a structured,
per-question "extracted answer" row. This stage stores raw/normalised text
only - no answer comparison, mark calculation, spelling deduction, MCQ
circle detection, or AI feedback happens here.
"""

import re
import sqlite3
from typing import Dict, List, Optional

from app.models.answer_extraction_model import (
    AnswerExtractionJob,
    add_extracted_attempt_answer,
    create_answer_extraction_job,
    get_answer_extraction_job_by_id,
    get_extracted_attempt_answers_for_job,
    get_latest_answer_extraction_job_for_attempt,
    mark_answer_extraction_job_completed,
    mark_answer_extraction_job_failed,
    EXTRACTION_STATUS_EXTRACTED,
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_NO_REGION,
    EXTRACTION_STATUS_NO_TEXT,
    EXTRACTION_STATUS_PENDING_DETECTION,
)
from app.models.extraction_model import (
    ExtractedRegionResult,
    STATUS_COMPLETED as REGION_EXTRACTION_STATUS_COMPLETED,
    get_extraction_job_by_id,
    get_extracted_region_results_for_job,
)
from app.models.marking_setup_model import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_RUBRIC_CRITERION,
    QUESTION_TYPE_SHORT_WORD,
    QUESTION_TYPE_WRITING_PART,
    QUESTION_TYPE_WRITTEN_LETTER,
    get_marking_questions_for_setup,
    get_marking_setup_by_material,
)
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import get_material_by_id
from app.models.template_model import REGION_TYPE_MCQ_OPTION_BOX

# Region type whose "selected answer" cannot be read directly from raw OCR
# text - matches the "mcq_circle_area" concept from the business rules,
# using this project's existing mcq_option_box region-type taxonomy.
_MCQ_AREA_REGION_TYPE = REGION_TYPE_MCQ_OPTION_BOX

_SINGLE_LETTER_PATTERN = re.compile(r"^[A-Za-z]$")


def _is_clean_single_letter(text: Optional[str]) -> bool:
    return bool(_SINGLE_LETTER_PATTERN.match((text or "").strip()))


def _normalize_extracted_answer(question_type: str, raw_text: str) -> str:
    stripped = raw_text.strip()
    if question_type in (QUESTION_TYPE_MCQ, QUESTION_TYPE_WRITTEN_LETTER):
        if _is_clean_single_letter(stripped):
            return stripped.upper()
        return stripped
    if question_type == QUESTION_TYPE_SHORT_WORD:
        return " ".join(stripped.split())
    if question_type in (QUESTION_TYPE_RUBRIC_CRITERION, QUESTION_TYPE_WRITING_PART):
        return stripped
    return stripped


def run_answer_extraction_for_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    extraction_job_id: int,
) -> AnswerExtractionJob:
    """Build structured per-question answer rows for attempt_id from the
    region results of extraction_job_id.

    Raises ValueError before any answer extraction job is created if the
    attempt, region-extraction job, or marking setup prerequisites are
    invalid - these are invalid requests rather than extraction failures.
    Once the job is created, any unexpected error while building rows is
    caught and stored as a failed job with a readable error_message.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")

    extraction_job = get_extraction_job_by_id(conn, extraction_job_id)
    if extraction_job is None:
        raise ValueError(f"Region extraction job not found: {extraction_job_id}")
    if extraction_job.status != REGION_EXTRACTION_STATUS_COMPLETED:
        raise ValueError(
            f"Region extraction job {extraction_job_id} is not completed "
            f"(status: {extraction_job.status})."
        )
    if extraction_job.attempt_id != attempt_id:
        raise ValueError(f"Region extraction job {extraction_job_id} does not belong to attempt {attempt_id}.")

    material = get_material_by_id(conn, attempt.material_id)
    if material is None:
        raise ValueError(f"Revision material not found for attempt {attempt_id}.")

    marking_setup = get_marking_setup_by_material(conn, material.material_id)
    if marking_setup is None:
        raise ValueError("Create marking setup and questions before extracting answers.")

    questions = get_marking_questions_for_setup(conn, marking_setup.setup_id)
    if not questions:
        raise ValueError("Create marking setup and questions before extracting answers.")

    answer_extraction_job = create_answer_extraction_job(
        conn, attempt_id, extraction_job_id, marking_setup.setup_id
    )

    try:
        region_results = get_extracted_region_results_for_job(conn, extraction_job_id)
        results_by_region_id: Dict[int, ExtractedRegionResult] = {
            result.region_id: result for result in region_results
        }

        extracted_count = 0
        for question in questions:
            if question.region_id is None:
                add_extracted_attempt_answer(
                    conn,
                    answer_extraction_job.answer_extraction_job_id,
                    question.question_id,
                    question.question_no,
                    question.question_type,
                    None,
                    None,
                    None,
                    None,
                    None,
                    EXTRACTION_STATUS_NO_REGION,
                )
                continue

            region_result = results_by_region_id.get(question.region_id)
            if region_result is None:
                add_extracted_attempt_answer(
                    conn,
                    answer_extraction_job.answer_extraction_job_id,
                    question.question_id,
                    question.question_no,
                    question.question_type,
                    question.region_id,
                    None,
                    None,
                    None,
                    None,
                    EXTRACTION_STATUS_FAILED,
                )
                continue

            raw_text = region_result.extracted_text or ""
            confidence = region_result.average_confidence

            if not raw_text.strip():
                add_extracted_attempt_answer(
                    conn,
                    answer_extraction_job.answer_extraction_job_id,
                    question.question_id,
                    question.question_no,
                    question.question_type,
                    question.region_id,
                    region_result.region_name,
                    raw_text,
                    None,
                    confidence,
                    EXTRACTION_STATUS_NO_TEXT,
                )
                continue

            if region_result.region_type == _MCQ_AREA_REGION_TYPE and not _is_clean_single_letter(raw_text):
                add_extracted_attempt_answer(
                    conn,
                    answer_extraction_job.answer_extraction_job_id,
                    question.question_id,
                    question.question_no,
                    question.question_type,
                    question.region_id,
                    region_result.region_name,
                    raw_text,
                    None,
                    confidence,
                    EXTRACTION_STATUS_PENDING_DETECTION,
                )
                continue

            extracted_answer = _normalize_extracted_answer(question.question_type, raw_text)
            add_extracted_attempt_answer(
                conn,
                answer_extraction_job.answer_extraction_job_id,
                question.question_id,
                question.question_no,
                question.question_type,
                question.region_id,
                region_result.region_name,
                raw_text,
                extracted_answer,
                confidence,
                EXTRACTION_STATUS_EXTRACTED,
            )
            extracted_count += 1

        mark_answer_extraction_job_completed(
            conn, answer_extraction_job.answer_extraction_job_id, len(questions), extracted_count
        )
    except Exception as exc:
        mark_answer_extraction_job_failed(conn, answer_extraction_job.answer_extraction_job_id, str(exc))

    return get_answer_extraction_job_by_id(conn, answer_extraction_job.answer_extraction_job_id)


def get_answer_extraction_job(conn: sqlite3.Connection, answer_extraction_job_id: int) -> Optional[AnswerExtractionJob]:
    return get_answer_extraction_job_by_id(conn, answer_extraction_job_id)


def get_latest_answer_extraction_job(conn: sqlite3.Connection, attempt_id: int) -> Optional[AnswerExtractionJob]:
    return get_latest_answer_extraction_job_for_attempt(conn, attempt_id)


def list_extracted_attempt_answers(conn: sqlite3.Connection, answer_extraction_job_id: int) -> List:
    return get_extracted_attempt_answers_for_job(conn, answer_extraction_job_id)
