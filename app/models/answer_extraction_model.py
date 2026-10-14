"""Structured answer extraction job and result data model and database
access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)

EXTRACTION_STATUS_EXTRACTED = "extracted"
EXTRACTION_STATUS_NO_TEXT = "no_text"
EXTRACTION_STATUS_NO_REGION = "no_region"
EXTRACTION_STATUS_PENDING_DETECTION = "pending_detection"
EXTRACTION_STATUS_FAILED = "failed"

ALLOWED_EXTRACTION_STATUSES = (
    EXTRACTION_STATUS_EXTRACTED,
    EXTRACTION_STATUS_NO_TEXT,
    EXTRACTION_STATUS_NO_REGION,
    EXTRACTION_STATUS_PENDING_DETECTION,
    EXTRACTION_STATUS_FAILED,
)


@dataclass
class AnswerExtractionJob:
    answer_extraction_job_id: int
    attempt_id: int
    extraction_job_id: int
    marking_setup_id: int
    status: str
    question_count: int
    extracted_count: int
    error_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class ExtractedAttemptAnswer:
    extracted_answer_id: int
    answer_extraction_job_id: int
    question_id: int
    question_no: str
    question_type: str
    region_id: Optional[int]
    region_name: Optional[str]
    raw_text: Optional[str]
    extracted_answer: Optional[str]
    confidence: Optional[float]
    extraction_status: str
    created_at: str


def create_answer_extraction_job(
    conn: sqlite3.Connection,
    attempt_id: int,
    extraction_job_id: int,
    marking_setup_id: int,
) -> AnswerExtractionJob:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO answer_extraction_jobs "
        "(attempt_id, extraction_job_id, marking_setup_id, status, question_count, "
        "extracted_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, extraction_job_id, marking_setup_id, STATUS_PENDING, 0, 0, created_at),
    )
    conn.commit()
    return AnswerExtractionJob(
        answer_extraction_job_id=cursor.lastrowid,
        attempt_id=attempt_id,
        extraction_job_id=extraction_job_id,
        marking_setup_id=marking_setup_id,
        status=STATUS_PENDING,
        question_count=0,
        extracted_count=0,
        error_message=None,
        created_at=created_at,
        completed_at=None,
    )


def mark_answer_extraction_job_completed(
    conn: sqlite3.Connection, answer_extraction_job_id: int, question_count: int, extracted_count: int
) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE answer_extraction_jobs SET status = ?, question_count = ?, extracted_count = ?, "
        "completed_at = ? WHERE answer_extraction_job_id = ?",
        (STATUS_COMPLETED, question_count, extracted_count, completed_at, answer_extraction_job_id),
    )
    conn.commit()


def mark_answer_extraction_job_failed(
    conn: sqlite3.Connection, answer_extraction_job_id: int, error_message: str
) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE answer_extraction_jobs SET status = ?, error_message = ?, completed_at = ? "
        "WHERE answer_extraction_job_id = ?",
        (STATUS_FAILED, error_message, completed_at, answer_extraction_job_id),
    )
    conn.commit()


def get_answer_extraction_job_by_id(
    conn: sqlite3.Connection, answer_extraction_job_id: int
) -> Optional[AnswerExtractionJob]:
    row = conn.execute(
        "SELECT answer_extraction_job_id, attempt_id, extraction_job_id, marking_setup_id, status, "
        "question_count, extracted_count, error_message, created_at, completed_at "
        "FROM answer_extraction_jobs WHERE answer_extraction_job_id = ?",
        (answer_extraction_job_id,),
    ).fetchone()
    if row is None:
        return None
    return AnswerExtractionJob(**dict(row))


def get_latest_answer_extraction_job_for_attempt(
    conn: sqlite3.Connection, attempt_id: int
) -> Optional[AnswerExtractionJob]:
    row = conn.execute(
        "SELECT answer_extraction_job_id, attempt_id, extraction_job_id, marking_setup_id, status, "
        "question_count, extracted_count, error_message, created_at, completed_at "
        "FROM answer_extraction_jobs WHERE attempt_id = ? "
        "ORDER BY created_at DESC, answer_extraction_job_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return AnswerExtractionJob(**dict(row))


def get_answer_extraction_job_for_combination(
    conn: sqlite3.Connection, attempt_id: int, extraction_job_id: int
) -> Optional[AnswerExtractionJob]:
    row = conn.execute(
        "SELECT answer_extraction_job_id, attempt_id, extraction_job_id, marking_setup_id, status, "
        "question_count, extracted_count, error_message, created_at, completed_at "
        "FROM answer_extraction_jobs WHERE attempt_id = ? AND extraction_job_id = ? "
        "ORDER BY created_at DESC, answer_extraction_job_id DESC LIMIT 1",
        (attempt_id, extraction_job_id),
    ).fetchone()
    if row is None:
        return None
    return AnswerExtractionJob(**dict(row))


def add_extracted_attempt_answer(
    conn: sqlite3.Connection,
    answer_extraction_job_id: int,
    question_id: int,
    question_no: str,
    question_type: str,
    region_id: Optional[int],
    region_name: Optional[str],
    raw_text: Optional[str],
    extracted_answer: Optional[str],
    confidence: Optional[float],
    extraction_status: str,
) -> ExtractedAttemptAnswer:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO extracted_attempt_answers "
        "(answer_extraction_job_id, question_id, question_no, question_type, region_id, region_name, "
        "raw_text, extracted_answer, confidence, extraction_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            answer_extraction_job_id,
            question_id,
            question_no,
            question_type,
            region_id,
            region_name,
            raw_text,
            extracted_answer,
            confidence,
            extraction_status,
            created_at,
        ),
    )
    conn.commit()
    return ExtractedAttemptAnswer(
        extracted_answer_id=cursor.lastrowid,
        answer_extraction_job_id=answer_extraction_job_id,
        question_id=question_id,
        question_no=question_no,
        question_type=question_type,
        region_id=region_id,
        region_name=region_name,
        raw_text=raw_text,
        extracted_answer=extracted_answer,
        confidence=confidence,
        extraction_status=extraction_status,
        created_at=created_at,
    )


def get_extracted_attempt_answers_for_job(
    conn: sqlite3.Connection, answer_extraction_job_id: int
) -> List[ExtractedAttemptAnswer]:
    rows = conn.execute(
        "SELECT extracted_answer_id, answer_extraction_job_id, question_id, question_no, question_type, "
        "region_id, region_name, raw_text, extracted_answer, confidence, extraction_status, created_at "
        "FROM extracted_attempt_answers WHERE answer_extraction_job_id = ? "
        "ORDER BY extracted_answer_id",
        (answer_extraction_job_id,),
    ).fetchall()
    return [ExtractedAttemptAnswer(**dict(row)) for row in rows]
