"""Kertas 1 rule-based marking job and result data model and database
access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)


@dataclass
class MarkingJob:
    marking_job_id: int
    attempt_id: int
    answer_extraction_job_id: int
    marking_setup_id: int
    paper_type: str
    status: str
    total_questions: int
    marked_count: int
    correct_count: int
    needs_review_count: int
    total_score: float
    max_score: float
    error_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class MarkingQuestionResult:
    marking_result_id: int
    marking_job_id: int
    question_id: int
    extracted_answer_id: Optional[int]
    question_no: str
    question_type: str
    correct_answer: str
    extracted_answer: Optional[str]
    raw_text: Optional[str]
    is_correct: int
    needs_review: int
    score_awarded: float
    max_mark: float
    confidence: Optional[float]
    reason: Optional[str]
    explanation: Optional[str]
    created_at: str


def create_marking_job(
    conn: sqlite3.Connection,
    attempt_id: int,
    answer_extraction_job_id: int,
    marking_setup_id: int,
    paper_type: str,
) -> MarkingJob:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO marking_jobs "
        "(attempt_id, answer_extraction_job_id, marking_setup_id, paper_type, status, "
        "total_questions, marked_count, correct_count, needs_review_count, total_score, max_score, "
        "created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, answer_extraction_job_id, marking_setup_id, paper_type, STATUS_PENDING, 0, 0, 0, 0, 0, 0, created_at),
    )
    conn.commit()
    return MarkingJob(
        marking_job_id=cursor.lastrowid,
        attempt_id=attempt_id,
        answer_extraction_job_id=answer_extraction_job_id,
        marking_setup_id=marking_setup_id,
        paper_type=paper_type,
        status=STATUS_PENDING,
        total_questions=0,
        marked_count=0,
        correct_count=0,
        needs_review_count=0,
        total_score=0,
        max_score=0,
        error_message=None,
        created_at=created_at,
        completed_at=None,
    )


def mark_marking_job_completed(
    conn: sqlite3.Connection,
    marking_job_id: int,
    total_questions: int,
    marked_count: int,
    correct_count: int,
    needs_review_count: int,
    total_score: float,
    max_score: float,
) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE marking_jobs SET status = ?, total_questions = ?, marked_count = ?, correct_count = ?, "
        "needs_review_count = ?, total_score = ?, max_score = ?, completed_at = ? WHERE marking_job_id = ?",
        (
            STATUS_COMPLETED,
            total_questions,
            marked_count,
            correct_count,
            needs_review_count,
            total_score,
            max_score,
            completed_at,
            marking_job_id,
        ),
    )
    conn.commit()


def mark_marking_job_failed(conn: sqlite3.Connection, marking_job_id: int, error_message: str) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE marking_jobs SET status = ?, error_message = ?, completed_at = ? WHERE marking_job_id = ?",
        (STATUS_FAILED, error_message, completed_at, marking_job_id),
    )
    conn.commit()


def get_marking_job_by_id(conn: sqlite3.Connection, marking_job_id: int) -> Optional[MarkingJob]:
    row = conn.execute(
        "SELECT marking_job_id, attempt_id, answer_extraction_job_id, marking_setup_id, paper_type, status, "
        "total_questions, marked_count, correct_count, needs_review_count, total_score, max_score, "
        "error_message, created_at, completed_at FROM marking_jobs WHERE marking_job_id = ?",
        (marking_job_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingJob(**dict(row))


def get_latest_marking_job_for_attempt(conn: sqlite3.Connection, attempt_id: int) -> Optional[MarkingJob]:
    row = conn.execute(
        "SELECT marking_job_id, attempt_id, answer_extraction_job_id, marking_setup_id, paper_type, status, "
        "total_questions, marked_count, correct_count, needs_review_count, total_score, max_score, "
        "error_message, created_at, completed_at FROM marking_jobs WHERE attempt_id = ? "
        "ORDER BY created_at DESC, marking_job_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingJob(**dict(row))


def get_marking_job_for_answer_extraction_job(
    conn: sqlite3.Connection, answer_extraction_job_id: int
) -> Optional[MarkingJob]:
    row = conn.execute(
        "SELECT marking_job_id, attempt_id, answer_extraction_job_id, marking_setup_id, paper_type, status, "
        "total_questions, marked_count, correct_count, needs_review_count, total_score, max_score, "
        "error_message, created_at, completed_at FROM marking_jobs WHERE answer_extraction_job_id = ? "
        "ORDER BY created_at DESC, marking_job_id DESC LIMIT 1",
        (answer_extraction_job_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingJob(**dict(row))


def add_marking_question_result(
    conn: sqlite3.Connection,
    marking_job_id: int,
    question_id: int,
    extracted_answer_id: Optional[int],
    question_no: str,
    question_type: str,
    correct_answer: str,
    extracted_answer: Optional[str],
    raw_text: Optional[str],
    is_correct: bool,
    needs_review: bool,
    score_awarded: float,
    max_mark: float,
    confidence: Optional[float],
    reason: Optional[str],
    explanation: Optional[str],
) -> MarkingQuestionResult:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO marking_question_results "
        "(marking_job_id, question_id, extracted_answer_id, question_no, question_type, correct_answer, "
        "extracted_answer, raw_text, is_correct, needs_review, score_awarded, max_mark, confidence, "
        "reason, explanation, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            marking_job_id,
            question_id,
            extracted_answer_id,
            question_no,
            question_type,
            correct_answer,
            extracted_answer,
            raw_text,
            1 if is_correct else 0,
            1 if needs_review else 0,
            score_awarded,
            max_mark,
            confidence,
            reason,
            explanation,
            created_at,
        ),
    )
    conn.commit()
    return MarkingQuestionResult(
        marking_result_id=cursor.lastrowid,
        marking_job_id=marking_job_id,
        question_id=question_id,
        extracted_answer_id=extracted_answer_id,
        question_no=question_no,
        question_type=question_type,
        correct_answer=correct_answer,
        extracted_answer=extracted_answer,
        raw_text=raw_text,
        is_correct=1 if is_correct else 0,
        needs_review=1 if needs_review else 0,
        score_awarded=score_awarded,
        max_mark=max_mark,
        confidence=confidence,
        reason=reason,
        explanation=explanation,
        created_at=created_at,
    )


def get_marking_question_results_for_job(
    conn: sqlite3.Connection, marking_job_id: int
) -> List[MarkingQuestionResult]:
    rows = conn.execute(
        "SELECT marking_result_id, marking_job_id, question_id, extracted_answer_id, question_no, "
        "question_type, correct_answer, extracted_answer, raw_text, is_correct, needs_review, "
        "score_awarded, max_mark, confidence, reason, explanation, created_at "
        "FROM marking_question_results WHERE marking_job_id = ? ORDER BY marking_result_id",
        (marking_job_id,),
    ).fetchall()
    return [MarkingQuestionResult(**dict(row)) for row in rows]
