"""CSV export foundation for finalized Main Marking (Stage 11S) results.

Reads already-finalized Main Marking results exclusively through the Stage
11S final-result snapshot functions (list_main_marking_final_results_for_
teacher / get_main_marking_final_result_detail) and writes them to plain
CSV files under data/exports/ using only the Python standard library csv
module. This module never creates, modifies, or finalizes any result - it
only reads the frozen Stage 11S snapshot and writes CSV files, exactly
mirroring the read-only contract of the existing class-based
app/services/result_export_service.py (left untouched by this stage).

A separate file/module (rather than reusing result_export_service.py) is
used deliberately: the two export pipelines read from unrelated storage
(main_marking_final_results/_items vs. marking_reviews/kertas2_feedback_
reviews) and mixing them would risk the old export accidentally picking up
Main Marking rows, or vice versa.
"""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from app.services.main_marking_service import (
    get_main_marking_final_result_detail,
    list_main_marking_final_results_for_teacher,
)
from app.utils.file_storage import get_exports_dir

MAIN_MARKING_SUMMARY_HEADERS = [
    "result_id",
    "session_id",
    "session_title",
    "answer_file_id",
    "answer_file",
    "student_name",
    "student_code",
    "paper_type",
    "final_score",
    "max_score",
    "percentage",
    "finalized_at",
    "teacher_id",
    "message",
]

MAIN_MARKING_DETAIL_HEADERS = [
    "result_id",
    "session_title",
    "answer_file",
    "student_name",
    "student_code",
    "paper_type",
    "target_label",
    "target_kind",
    "region_type",
    "student_answer",
    "correct_answer",
    "machine_score",
    "teacher_score",
    "final_score",
    "max_score",
    "machine_feedback",
    "teacher_feedback",
    "final_feedback",
    "reviewed_at",
    "finalized_at",
]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _unique_path(path: Path) -> Path:
    """Return path unchanged if it doesn't exist yet, otherwise append an
    incrementing counter so a same-second re-export never overwrites a
    previous export file (mirrors result_export_service.py's own helper)."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _write_csv(filename: str, headers: List[str], rows: List[list]) -> str:
    """Write rows to data/exports/filename using utf-8-sig (BOM) so Excel
    opens the CSV cleanly - a deliberate improvement over the plain utf-8
    used by the older result_export_service.py, which is left unchanged."""
    exports_dir = get_exports_dir()
    path = _unique_path(exports_dir / filename)
    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


def _percentage(final_score: float, max_score: float):
    """Return final_score as a percentage of max_score rounded to 2 decimal
    places, or "" (blank) if max_score is 0 - avoids a ZeroDivisionError
    while making the "no meaningful percentage" case unambiguous in the
    exported CSV rather than silently writing 0."""
    if max_score > 0:
        return round(final_score / max_score * 100, 2)
    return ""


def build_main_marking_final_results_summary_rows(conn: sqlite3.Connection, teacher_id: int) -> List[list]:
    """Return one row per teacher_id's finalized Main Marking answer file,
    built entirely from the Stage 11S main_marking_final_results snapshot -
    never recalculated from live marked answers."""
    rows = []
    for row in list_main_marking_final_results_for_teacher(conn, teacher_id):
        result = row.result
        rows.append([
            result.result_id,
            result.session_id,
            row.session_title,
            result.answer_file_id,
            result.answer_file_display_name,
            result.student_name or "",
            result.student_code or "",
            result.paper_type,
            result.total_score,
            result.max_score,
            _percentage(result.total_score, result.max_score),
            result.finalized_at,
            result.teacher_id,
            result.message or "",
        ])
    return rows


def export_main_marking_final_results_summary_csv(conn: sqlite3.Connection, teacher_id: int) -> Tuple[str, int]:
    """Export teacher_id's finalized Main Marking result summaries to a CSV
    file under data/exports/. Returns (file_path, exported_row_count).

    Raises ValueError if there are no finalized Main Marking results to
    export - unfinalized (draft/marked/reviewed-only) answer files are
    never included, since they simply don't appear in the Stage 11S
    final-result snapshot table this reads from.
    """
    rows = build_main_marking_final_results_summary_rows(conn, teacher_id)
    if not rows:
        raise ValueError("No finalized Main Marking results available to export.")

    filename = f"main_marking_results_summary_{_timestamp()}.csv"
    path = _write_csv(filename, MAIN_MARKING_SUMMARY_HEADERS, rows)
    return path, len(rows)


def build_main_marking_final_result_detail_rows(
    conn: sqlite3.Connection, teacher_id: int, result_id: int
) -> List[list]:
    """Return one row per item of one finalized Main Marking result
    (ownership-checked via get_main_marking_final_result_detail), built
    entirely from the Stage 11S final-result-item snapshot.

    If the result has no items (should not normally happen, but handled
    safely), a single metadata-only row is returned with blank item
    fields, so the exported CSV always documents which result it covers.

    Raises ValueError if result_id doesn't exist or isn't owned by
    teacher_id (propagated from get_main_marking_final_result_detail).
    """
    detail = get_main_marking_final_result_detail(conn, teacher_id, result_id)
    return _detail_rows_from_detail(detail)


def _detail_rows_from_detail(detail) -> List[list]:
    result = detail.result
    metadata = [
        result.result_id, detail.session_title, result.answer_file_display_name,
        result.student_name or "", result.student_code or "", result.paper_type,
    ]

    if not detail.items:
        return [metadata + ["", "", "", "", "", "", "", "", "", "", "", "", "", result.finalized_at]]

    rows = []
    for item in detail.items:
        rows.append(metadata + [
            item.target_label,
            item.target_kind,
            item.region_type or "",
            item.student_answer_text or "",
            item.correct_answer_text or "",
            item.machine_score if item.machine_score is not None else "",
            item.teacher_score if item.teacher_score is not None else "",
            item.final_score,
            item.max_score,
            item.machine_feedback or "",
            item.teacher_feedback or "",
            item.final_feedback or "",
            item.reviewed_at or "",
            result.finalized_at,
        ])
    return rows


def export_main_marking_final_result_detail_csv(
    conn: sqlite3.Connection, teacher_id: int, result_id: int
) -> Tuple[str, int]:
    """Export one finalized Main Marking result's item-level detail rows to
    a CSV file under data/exports/. Returns (file_path, item_count) - a
    returned item_count of 0 means the result had no items and the CSV
    contains only a metadata row, which the caller should surface clearly.

    Raises ValueError if result_id doesn't exist or isn't owned by
    teacher_id (propagated from get_main_marking_final_result_detail).
    """
    detail = get_main_marking_final_result_detail(conn, teacher_id, result_id)
    rows = _detail_rows_from_detail(detail)
    filename = f"main_marking_result_{result_id}_detail_{_timestamp()}.csv"
    path = _write_csv(filename, MAIN_MARKING_DETAIL_HEADERS, rows)
    return path, len(detail.items)
