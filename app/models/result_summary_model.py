"""Read-only aggregation of finalized Kertas 1 and Kertas 2 review results
for the unified teacher/student results views.

No new tables - this module only queries the existing finalized
marking_reviews / kertas2_feedback_reviews tables (joined with
revision_attempts/revision_materials/classes/users) and never writes
anything.
"""

import sqlite3
from dataclasses import dataclass
from typing import List

RESULT_TYPE_KERTAS1 = "kertas1_review"
RESULT_TYPE_KERTAS2 = "kertas2_review"


@dataclass
class ResultSummaryRow:
    result_type: str
    review_id: int
    attempt_id: int
    student_id: int
    username: str
    student_name: str
    class_name: str
    material_title: str
    paper_type: str
    final_score: float
    max_score: float
    finalized_at: str


_KERTAS1_SELECT = """
    SELECT
        'kertas1_review' AS result_type,
        mr.review_id AS review_id,
        mr.attempt_id AS attempt_id,
        u.user_id AS student_id,
        u.username AS username,
        u.full_name AS student_name,
        c.class_name AS class_name,
        rm.title AS material_title,
        rm.paper_type AS paper_type,
        mr.final_total_score AS final_score,
        mr.max_score AS max_score,
        mr.finalized_at AS finalized_at
    FROM marking_reviews mr
    JOIN revision_attempts ra ON ra.attempt_id = mr.attempt_id
    JOIN revision_materials rm ON rm.material_id = ra.material_id
    JOIN classes c ON c.class_id = ra.class_id
    JOIN users u ON u.user_id = ra.student_id
    WHERE mr.status = 'finalized'
"""

_KERTAS2_SELECT = """
    SELECT
        'kertas2_review' AS result_type,
        kr.kertas2_review_id AS review_id,
        kr.attempt_id AS attempt_id,
        u.user_id AS student_id,
        u.username AS username,
        u.full_name AS student_name,
        c.class_name AS class_name,
        rm.title AS material_title,
        rm.paper_type AS paper_type,
        kr.final_total_score AS final_score,
        kr.max_score AS max_score,
        kr.finalized_at AS finalized_at
    FROM kertas2_feedback_reviews kr
    JOIN revision_attempts ra ON ra.attempt_id = kr.attempt_id
    JOIN revision_materials rm ON rm.material_id = ra.material_id
    JOIN classes c ON c.class_id = ra.class_id
    JOIN users u ON u.user_id = ra.student_id
    WHERE kr.status = 'finalized'
"""


def _rows_to_summaries(rows) -> List[ResultSummaryRow]:
    return [ResultSummaryRow(**dict(row)) for row in rows]


def get_teacher_finalized_results(conn: sqlite3.Connection, teacher_id: int) -> List[ResultSummaryRow]:
    """Return finalized Kertas 1 + Kertas 2 results for classes owned by
    teacher_id, newest finalized_at first. Draft reviews are never included
    (both queries filter on status = 'finalized')."""
    kertas1_rows = conn.execute(_KERTAS1_SELECT + " AND c.teacher_id = ?", (teacher_id,)).fetchall()
    kertas2_rows = conn.execute(_KERTAS2_SELECT + " AND c.teacher_id = ?", (teacher_id,)).fetchall()
    results = _rows_to_summaries(kertas1_rows) + _rows_to_summaries(kertas2_rows)
    results.sort(key=lambda r: r.finalized_at, reverse=True)
    return results


def get_student_finalized_results(conn: sqlite3.Connection, student_id: int) -> List[ResultSummaryRow]:
    """Return finalized Kertas 1 + Kertas 2 results for student_id's own
    attempts only, newest finalized_at first."""
    kertas1_rows = conn.execute(_KERTAS1_SELECT + " AND ra.student_id = ?", (student_id,)).fetchall()
    kertas2_rows = conn.execute(_KERTAS2_SELECT + " AND ra.student_id = ?", (student_id,)).fetchall()
    results = _rows_to_summaries(kertas1_rows) + _rows_to_summaries(kertas2_rows)
    results.sort(key=lambda r: r.finalized_at, reverse=True)
    return results
