"""Admin-only HARD deletion of teacher and student accounts.

Unlike deactivation (which keeps every record and simply blocks sign-in),
hard deletion permanently removes the account row and - for students - the
full tree of records the account owns, including uploaded files on disk.
There is no undo.

Safety rules:
- Only an active admin can delete, and only teacher/student accounts -
  never an admin account, never yourself.
- A STUDENT is deleted with their whole submission tree (class memberships,
  attempts + every marking/extraction/feedback record hanging off them,
  external revisions, transfer requests, uploaded files).
- A TEACHER can only be deleted once they no longer own substantive data
  (classes, subject profiles, marking sessions, revision materials,
  templates, finalised results, AI registry assets). Anything else would
  silently destroy marking history that students and reports depend on -
  the blocker message tells the admin exactly what to clear first.
"""

import shutil
import sqlite3
from pathlib import Path
from typing import List

from app.models.user_model import get_user_by_id
from app.utils.file_storage import EXTERNAL_REVISIONS_DIR, REVISION_ATTEMPTS_DIR

ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"


def _require_admin_actor(conn: sqlite3.Connection, admin_id: int) -> None:
    actor = get_user_by_id(conn, admin_id)
    if actor is None or actor.role != ROLE_ADMIN or not actor.is_active:
        raise ValueError("Only an active admin can delete accounts.")


def get_teacher_hard_delete_blockers(conn: sqlite3.Connection, teacher_id: int) -> List[str]:
    """What still prevents hard-deleting this teacher - empty when clear."""
    checks = (
        ("classes they own", "SELECT COUNT(*) FROM classes WHERE teacher_id = ?"),
        ("subject profiles", "SELECT COUNT(*) FROM subject_profiles WHERE teacher_id = ?"),
        ("marking sessions", "SELECT COUNT(*) FROM main_marking_sessions WHERE teacher_id = ?"),
        ("revision materials", "SELECT COUNT(*) FROM revision_materials WHERE teacher_id = ?"),
        ("answer templates", "SELECT COUNT(*) FROM answer_templates WHERE teacher_id = ?"),
        ("finalised results", "SELECT COUNT(*) FROM main_marking_final_results WHERE teacher_id = ?"),
        ("AI model versions", "SELECT COUNT(*) FROM ai_model_versions WHERE teacher_id = ?"),
        ("AI training jobs", "SELECT COUNT(*) FROM ai_training_jobs WHERE teacher_id = ?"),
        ("AI training datasets", "SELECT COUNT(*) FROM ai_training_datasets WHERE teacher_id = ?"),
    )
    blockers = []
    for label, query in checks:
        count = conn.execute(query, (teacher_id,)).fetchone()[0]
        if count:
            blockers.append(f"{count} {label}")
    return blockers


def _delete_student_attempt_tree(conn: sqlite3.Connection, student_id: int) -> List[int]:
    """Delete every record hanging off the student's revision attempts,
    deepest children first (foreign keys are enforced). Returns the deleted
    attempt ids so the caller can remove their upload folders."""
    attempt_ids = [r[0] for r in conn.execute(
        "SELECT attempt_id FROM revision_attempts WHERE student_id = ?", (student_id,))]
    if not attempt_ids:
        return []
    marks = ",".join("?" for _ in attempt_ids)

    conn.execute(
        f"DELETE FROM marking_review_items WHERE review_id IN "
        f"(SELECT review_id FROM marking_reviews WHERE attempt_id IN ({marks}))", attempt_ids)
    conn.execute(f"DELETE FROM marking_reviews WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(
        f"DELETE FROM marking_question_results WHERE marking_job_id IN "
        f"(SELECT marking_job_id FROM marking_jobs WHERE attempt_id IN ({marks}))", attempt_ids)
    conn.execute(
        f"DELETE FROM kertas2_feedback_review_items WHERE kertas2_review_id IN "
        f"(SELECT kertas2_review_id FROM kertas2_feedback_reviews WHERE attempt_id IN ({marks}))",
        attempt_ids)
    conn.execute(f"DELETE FROM kertas2_feedback_reviews WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(
        f"DELETE FROM kertas2_ai_feedback_items WHERE feedback_job_id IN "
        f"(SELECT feedback_job_id FROM kertas2_ai_feedback_jobs WHERE attempt_id IN ({marks}))",
        attempt_ids)
    conn.execute(f"DELETE FROM marking_jobs WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(f"DELETE FROM kertas2_ai_feedback_jobs WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(
        f"DELETE FROM extracted_attempt_answers WHERE answer_extraction_job_id IN "
        f"(SELECT answer_extraction_job_id FROM answer_extraction_jobs WHERE attempt_id IN ({marks}))",
        attempt_ids)
    conn.execute(f"DELETE FROM answer_extraction_jobs WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(
        f"DELETE FROM extracted_region_results WHERE extraction_job_id IN "
        f"(SELECT extraction_job_id FROM extraction_jobs WHERE attempt_id IN ({marks}))", attempt_ids)
    conn.execute(f"DELETE FROM extraction_jobs WHERE attempt_id IN ({marks})", attempt_ids)
    conn.execute(f"DELETE FROM revision_attempts WHERE attempt_id IN ({marks})", attempt_ids)
    return attempt_ids


def hard_delete_user_account(conn: sqlite3.Connection, admin_id: int, user_id: int) -> str:
    """Permanently delete a teacher or student account. Returns the deleted
    username. Raises ValueError with the reason when deletion is not allowed."""
    _require_admin_actor(conn, admin_id)
    if int(admin_id) == int(user_id):
        raise ValueError("You cannot delete your own account.")
    target = get_user_by_id(conn, user_id)
    if target is None:
        raise ValueError("Account not found.")
    if target.role == ROLE_ADMIN:
        raise ValueError("Admin accounts cannot be hard-deleted.")
    if target.role not in (ROLE_TEACHER, ROLE_STUDENT):
        raise ValueError(f"Unknown role: {target.role}")

    deleted_attempt_ids: List[int] = []
    deleted_external_ids: List[int] = []

    if target.role == ROLE_STUDENT:
        deleted_attempt_ids = _delete_student_attempt_tree(conn, user_id)
        deleted_external_ids = [r[0] for r in conn.execute(
            "SELECT external_revision_id FROM student_external_revisions WHERE student_id = ?",
            (user_id,))]
        conn.execute("DELETE FROM student_external_revisions WHERE student_id = ?", (user_id,))
        conn.execute("DELETE FROM class_students WHERE student_id = ?", (user_id,))
        conn.execute("DELETE FROM student_transfer_requests WHERE student_id = ?", (user_id,))
    else:
        blockers = get_teacher_hard_delete_blockers(conn, user_id)
        if blockers:
            raise ValueError(
                "This teacher still owns records that hard deletion would destroy:\n- "
                + "\n- ".join(blockers)
                + "\nReassign or remove them first (or deactivate the account instead).")
        conn.execute("DELETE FROM teacher_marking_settings WHERE teacher_id = ?", (user_id,))
        conn.execute("DELETE FROM marking_setups WHERE teacher_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM class_transfer_requests WHERE requesting_teacher_id = ? "
            "OR current_teacher_id = ?", (user_id, user_id))
        conn.execute(
            "UPDATE class_transfer_requests SET responded_by_user_id = NULL "
            "WHERE responded_by_user_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM student_transfer_requests WHERE requesting_teacher_id = ? "
            "OR current_teacher_id = ?", (user_id, user_id))
        conn.execute(
            "UPDATE student_transfer_requests SET responded_by_user_id = NULL "
            "WHERE responded_by_user_id = ?", (user_id,))

    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()

    # Uploaded files: best-effort removal AFTER the transaction committed -
    # a file that refuses to delete never leaves the database half-deleted.
    for attempt_id in deleted_attempt_ids:
        shutil.rmtree(Path(REVISION_ATTEMPTS_DIR) / f"attempt_{attempt_id}", ignore_errors=True)
    for external_id in deleted_external_ids:
        shutil.rmtree(Path(EXTERNAL_REVISIONS_DIR) / f"external_{external_id}", ignore_errors=True)

    return target.username
