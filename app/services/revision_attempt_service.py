"""Student revision attempt submission logic for the Student and Teacher roles."""

import sqlite3
from pathlib import Path
from typing import List

from app.models.class_student_model import is_student_in_class
from app.models.revision_attempt_model import (
    RevisionAttempt,
    StudentAttemptRow,
    TeacherAttemptRow,
    create_attempt,
    get_attempt_by_id,
    get_attempts_for_student as get_attempts_for_student_record,
    get_attempts_for_teacher as get_attempts_for_teacher_record,
    get_max_attempt_no,
    is_material_assigned_to_class,
    soft_delete_attempt as soft_delete_attempt_record,
    update_attempt_file_path,
)
from app.models.revision_material_model import get_material_by_id
from app.models.user_model import get_user_by_id
from app.utils.file_storage import store_attempt_file

STUDENT_ROLE = "student"


def submit_revision_attempt(
    conn: sqlite3.Connection,
    student_id: int,
    material_id: int,
    class_id: int,
    completed_answer_source_path: str,
) -> RevisionAttempt:
    """Submit a new attempt for a revision material assigned to one of the
    student's classes, copying the selected file into a local, attempt-specific
    folder under data/revision_attempts/. Attempt numbers increment per
    student per material, starting at 1.

    Raises ValueError if the requester is not a student, the material does
    not exist, the student does not belong to class_id, the material is not
    assigned to class_id, or the completed answer file path is missing or
    does not exist.
    """
    student = get_user_by_id(conn, student_id)
    if student is None or student.role != STUDENT_ROLE:
        raise ValueError("Only student accounts can submit revision attempts.")

    material = get_material_by_id(conn, material_id)
    if material is None:
        raise ValueError("Revision material not found.")

    if not is_student_in_class(conn, class_id, student_id):
        raise ValueError("You can only submit attempts for a class you belong to.")

    if not is_material_assigned_to_class(conn, material_id, class_id):
        raise ValueError("This revision material is not assigned to that class.")

    completed_answer_source_path = (completed_answer_source_path or "").strip()
    if not completed_answer_source_path:
        raise ValueError("A completed answer paper file is required.")
    if not Path(completed_answer_source_path).is_file():
        raise ValueError("The selected completed answer paper file could not be found.")

    attempt_no = get_max_attempt_no(conn, material_id, student_id) + 1

    attempt = create_attempt(
        conn,
        material_id=material_id,
        student_id=student_id,
        class_id=class_id,
        attempt_no=attempt_no,
        completed_answer_path="",
    )

    completed_answer_path = store_attempt_file(attempt.attempt_id, completed_answer_source_path, "completed_answer")
    update_attempt_file_path(conn, attempt.attempt_id, completed_answer_path)

    attempt.completed_answer_path = completed_answer_path
    return attempt


def list_attempts_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentAttemptRow]:
    return get_attempts_for_student_record(conn, student_id)


def list_attempts_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherAttemptRow]:
    return get_attempts_for_teacher_record(conn, teacher_id)


def soft_delete_student_attempt(conn: sqlite3.Connection, student_id: int, attempt_id: int) -> None:
    """Hide an attempt from the submitting student's own history.

    The record is not removed from the database - only is_deleted_by_student
    is set - so teacher visibility is unaffected.

    Raises ValueError if the attempt doesn't exist or doesn't belong to student_id.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError("Revision attempt not found.")
    if attempt.student_id != student_id:
        raise ValueError("You can only remove your own revision attempts.")

    soft_delete_attempt_record(conn, attempt_id)
