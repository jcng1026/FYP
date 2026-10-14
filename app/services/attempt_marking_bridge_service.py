"""Bridge between student submissions and the Subject Profile marking flow.

A revision attempt or external revision that a teacher marks through the
Subject Profile pipeline records which answer file / profile carry its
marking (marked_answer_file_id / marked_profile_id). The teacher's one
"Mark Attempt" button uses the link to resume marking, and the student's
pages use it to show progress and - once the teacher finalises - the
final marked PDF (the red-marked paper only; comments stay teacher-side).
"""
import sqlite3
from pathlib import Path
from typing import Optional

import app.models.subject_profile_model as spm

KIND_ATTEMPT = "attempt"
KIND_EXTERNAL = "external"

_TABLES = {
    KIND_ATTEMPT: ("revision_attempts", "attempt_id"),
    KIND_EXTERNAL: ("student_external_revisions", "external_revision_id"),
}

STATE_NOT_MARKED = "not_marked"
STATE_MARKING = "marking"
STATE_FINAL = "final"


def link_marked_attempt(conn: sqlite3.Connection, kind: str, item_id: int,
                        answer_file_id: int, profile_id: int) -> None:
    table, key = _TABLES[kind]
    conn.execute(
        f"UPDATE {table} SET marked_answer_file_id = ?, marked_profile_id = ? WHERE {key} = ?",
        (answer_file_id, profile_id, item_id),
    )
    conn.commit()


def get_marked_link(conn: sqlite3.Connection, kind: str, item_id: int):
    """(answer_file_id, profile_id) or None when never marked."""
    table, key = _TABLES[kind]
    row = conn.execute(
        f"SELECT marked_answer_file_id, marked_profile_id FROM {table} WHERE {key} = ?",
        (item_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0]), int(row[1]) if row[1] is not None else None


def get_marking_state(conn: sqlite3.Connection, kind: str, item_id: int) -> dict:
    """The marking progress of one submission, for either role's UI:
      {state: not_marked | marking | final, marked_pdf: path-or-None,
       answer_file_id, profile_id}
    'final' requires the finalised review's published marked PDF to exist on
    disk - a reopened or not-yet-finalised attempt reports 'marking'."""
    link = get_marked_link(conn, kind, item_id)
    if link is None:
        return {"state": STATE_NOT_MARKED, "marked_pdf": None,
                "answer_file_id": None, "profile_id": None}
    answer_file_id, profile_id = link
    review = spm.get_attempt_review(conn, answer_file_id)
    if (review is not None and review.review_state == spm.REVIEW_STATE_FINALISED
            and review.final_marked_pdf_path
            and Path(review.final_marked_pdf_path).exists()):
        return {"state": STATE_FINAL, "marked_pdf": review.final_marked_pdf_path,
                "answer_file_id": answer_file_id, "profile_id": profile_id}
    return {"state": STATE_MARKING, "marked_pdf": None,
            "answer_file_id": answer_file_id, "profile_id": profile_id}


def get_student_marked_pdf(conn: sqlite3.Connection, student_id: int, kind: str,
                           item_id: int) -> Optional[str]:
    """The finalised marked PDF path for a submission OWNED by student_id,
    or None. Ownership is checked against the submission row itself, so a
    student can never fetch another student's marked paper."""
    table, key = _TABLES[kind]
    row = conn.execute(
        f"SELECT student_id FROM {table} WHERE {key} = ?", (item_id,)
    ).fetchone()
    if row is None or int(row[0]) != int(student_id):
        raise ValueError("Submission not found for this student.")
    state = get_marking_state(conn, kind, item_id)
    return state["marked_pdf"] if state["state"] == STATE_FINAL else None
