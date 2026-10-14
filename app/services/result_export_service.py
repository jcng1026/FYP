"""CSV export foundation for finalized Kertas 1 / Kertas 2 results.

Reads already-finalized results via the Stage 7E result_summary_service and
writes them to plain CSV files under data/exports/ using only the Python
standard library csv module. This stage never creates, modifies, or
reopens any marking/review record - it only reads and writes CSV files.
"""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from app.models.result_summary_model import RESULT_TYPE_KERTAS1, RESULT_TYPE_KERTAS2, ResultSummaryRow
from app.services.result_summary_service import (
    get_result_detail_for_student,
    get_result_detail_for_teacher,
    list_student_finalized_results,
    list_teacher_finalized_results,
)
from app.utils.file_storage import get_exports_dir

SUMMARY_HEADERS_TEACHER = [
    "result_type",
    "review_id",
    "attempt_id",
    "student_id",
    "student_name",
    "class_name",
    "material_title",
    "paper_type",
    "final_score",
    "max_score",
    "finalized_at",
]

SUMMARY_HEADERS_STUDENT = [
    "result_type",
    "review_id",
    "attempt_id",
    "material_title",
    "paper_type",
    "final_score",
    "max_score",
    "finalized_at",
]

KERTAS1_DETAIL_HEADERS = [
    "result_type",
    "review_id",
    "question_no",
    "extracted_answer",
    "correct_answer",
    "final_score",
    "max_mark",
    "teacher_comment",
    "explanation",
]

KERTAS2_DETAIL_HEADERS = [
    "result_type",
    "review_id",
    "criterion_name",
    "student_answer",
    "sample_answer",
    "final_score",
    "max_mark",
    "final_feedback",
    "teacher_comment",
]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _unique_path(path: Path) -> Path:
    """Return path unchanged if it doesn't exist yet, otherwise append an
    incrementing counter so a same-second re-export never overwrites a
    previous export file."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _write_csv(filename: str, headers: List[str], rows: List[list]) -> str:
    exports_dir = get_exports_dir()
    path = _unique_path(exports_dir / filename)
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


def export_teacher_results_summary_csv(conn: sqlite3.Connection, teacher_id: int) -> str:
    """Export teacher_id's finalized Kertas 1 + Kertas 2 result summaries to
    a CSV file under data/exports/. Returns the exported file's path.

    Raises ValueError if there are no finalized results to export.
    """
    results = list_teacher_finalized_results(conn, teacher_id)
    if not results:
        raise ValueError("No finalized results available to export.")

    rows = [
        [
            r.result_type, r.review_id, r.attempt_id, r.username, r.student_name,
            r.class_name, r.material_title, r.paper_type, r.final_score, r.max_score, r.finalized_at,
        ]
        for r in results
    ]
    filename = f"teacher_{teacher_id}_results_summary_{_timestamp()}.csv"
    return _write_csv(filename, SUMMARY_HEADERS_TEACHER, rows)


def export_student_results_summary_csv(conn: sqlite3.Connection, student_id: int) -> str:
    """Export student_id's own finalized Kertas 1 + Kertas 2 result
    summaries to a CSV file under data/exports/. Returns the exported
    file's path.

    Raises ValueError if there are no finalized results to export.
    """
    results = list_student_finalized_results(conn, student_id)
    if not results:
        raise ValueError("No finalized results available to export.")

    rows = [
        [
            r.result_type, r.review_id, r.attempt_id,
            r.material_title, r.paper_type, r.final_score, r.max_score, r.finalized_at,
        ]
        for r in results
    ]
    filename = f"student_{student_id}_results_summary_{_timestamp()}.csv"
    return _write_csv(filename, SUMMARY_HEADERS_STUDENT, rows)


def _detail_rows_to_csv_rows(result_type: str, review_id: int, detail_rows: list) -> List[list]:
    if result_type == RESULT_TYPE_KERTAS1:
        return [
            [
                result_type, review_id, row.question_no, row.extracted_answer, row.correct_answer,
                row.final_score, row.max_mark, row.teacher_comment, row.explanation,
            ]
            for row in detail_rows
        ]
    return [
        [
            result_type, review_id, row.criterion_name, row.student_answer, row.sample_answer,
            row.final_score, row.max_mark, row.final_feedback, row.teacher_comment,
        ]
        for row in detail_rows
    ]


def export_teacher_result_detail_csv(
    conn: sqlite3.Connection, result_type: str, review_id: int, teacher_id: int
) -> str:
    """Export one finalized result's detail rows (validated for teacher_id's
    ownership) to a CSV file under data/exports/. Returns the exported
    file's path.

    Raises ValueError if result_type/review_id is invalid or not owned by
    teacher_id (propagated from get_result_detail_for_teacher).
    """
    review, detail_rows = get_result_detail_for_teacher(conn, result_type, review_id, teacher_id)
    headers = KERTAS1_DETAIL_HEADERS if result_type == RESULT_TYPE_KERTAS1 else KERTAS2_DETAIL_HEADERS
    rows = _detail_rows_to_csv_rows(result_type, review_id, detail_rows)
    filename = f"teacher_{teacher_id}_{result_type}_{review_id}_detail_{_timestamp()}.csv"
    return _write_csv(filename, headers, rows)


def export_student_result_detail_csv(
    conn: sqlite3.Connection, result_type: str, review_id: int, student_id: int
) -> str:
    """Export one finalized result's detail rows (validated for student_id's
    ownership) to a CSV file under data/exports/. Returns the exported
    file's path.

    Raises ValueError if result_type/review_id is invalid or not owned by
    student_id (propagated from get_result_detail_for_student).
    """
    review, detail_rows = get_result_detail_for_student(conn, result_type, review_id, student_id)
    headers = KERTAS1_DETAIL_HEADERS if result_type == RESULT_TYPE_KERTAS1 else KERTAS2_DETAIL_HEADERS
    rows = _detail_rows_to_csv_rows(result_type, review_id, detail_rows)
    filename = f"student_{student_id}_{result_type}_{review_id}_detail_{_timestamp()}.csv"
    return _write_csv(filename, headers, rows)
