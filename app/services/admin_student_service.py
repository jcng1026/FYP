"""Admin-only student management (Stage 10D).

Distinct from app/services/class_student_service.py and
app/services/student_service.py, which enforce per-teacher ownership for
the Teacher role. Here, Admin can view and manage every student across
every teacher/class directly. This is an Admin maintenance action, not the
Teacher transfer request workflow (see
app/services/class_transfer_request_service.py), which this stage does
not touch.
"""

import sqlite3
from typing import List, Optional

from app.models.class_model import get_class_by_id
from app.models.class_student_model import (
    UNASSIGNED_FILTER,
    AdminStudentRow,
    add_student_to_class,
    get_all_students_with_class_info,
    get_classes_for_student,
    remove_student_from_class,
)
from app.models.user_model import (
    User,
    get_user_by_id,
    get_user_by_username,
    update_full_name,
    update_is_active,
    update_student_code,
    update_username,
)
from app.services.student_service import create_student, validate_student_code

STUDENT_ROLE = "student"


def list_all_students(conn: sqlite3.Connection, class_id: Optional[object] = None) -> List[AdminStudentRow]:
    """Return every student account, optionally filtered to only those
    currently in class_id (or UNASSIGNED_FILTER for students in no class at
    all). Unlike the Teacher-facing student list, this is not scoped to any
    one teacher's classes."""
    return get_all_students_with_class_info(conn, class_id)


def admin_create_student(
    conn: sqlite3.Connection, username: str, full_name: str, password: str, class_id: Optional[int] = None
) -> User:
    """Admin-only student creation: username/full_name/password are the
    same as the Teacher-facing flow (create_student() - auto-generated
    TP#### student_code, hashed password, visible temporary password), but
    class_id may be any class in the system (or None for Unassigned),
    bypassing per-teacher ownership entirely.

    Raises ValueError if any required field is empty, the username is
    already taken, or class_id is given but doesn't refer to an existing class.
    """
    if class_id is not None and get_class_by_id(conn, class_id) is None:
        raise ValueError(f"Class not found: {class_id}")

    student = create_student(conn, username, full_name, password)
    if class_id is not None:
        add_student_to_class(conn, class_id, student.user_id)
    return student


def _require_student(conn: sqlite3.Connection, student_id: int) -> User:
    user = get_user_by_id(conn, student_id)
    if user is None or user.role != STUDENT_ROLE:
        raise ValueError(f"Student not found: {student_id}")
    return user


def get_student_for_admin(conn: sqlite3.Connection, student_id: int) -> User:
    """Return student_id's account.

    Raises ValueError if it doesn't exist or isn't a student account.
    """
    return _require_student(conn, student_id)


def update_student_details(
    conn: sqlite3.Connection, student_id: int, username: str, full_name: str, student_code: str
) -> None:
    """Update a student's username, full name, and student_code (Admin-only edit).

    student_code is required, must look like 'TP0001', and must be unique
    across students (checked via the same validate_student_code() used by
    the Teacher-facing creation flow). teacher_code is never editable here,
    and user_id is never changed.

    Raises ValueError if the student doesn't exist, any field is empty, the
    new username is already taken by a different account, or the new
    student_code fails format/uniqueness validation.
    """
    _require_student(conn, student_id)

    username = username.strip()
    full_name = full_name.strip()
    student_code = student_code.strip()
    if not username or not full_name or not student_code:
        raise ValueError("Username, full name, and student code are all required.")

    existing = get_user_by_username(conn, username)
    if existing is not None and existing.user_id != student_id:
        raise ValueError(f"Username '{username}' already exists.")

    validate_student_code(conn, student_code, exclude_user_id=student_id)

    update_username(conn, student_id, username)
    update_full_name(conn, student_id, full_name)
    update_student_code(conn, student_id, student_code)


def admin_change_student_class(conn: sqlite3.Connection, student_id: int, new_class_id: Optional[int]) -> None:
    """Admin-only direct class change: move student_id out of every class
    they currently belong to, and into new_class_id - or leave them
    Unassigned (in no class at all) when new_class_id is None.

    This is an Admin maintenance action, distinct from the Teacher transfer
    request workflow - it bypasses teacher ownership checks entirely and
    never creates a transfer request. A student always ends up in exactly
    one class, or zero if moved to Unassigned.
    Raises ValueError if the student doesn't exist, or new_class_id is
    given but doesn't refer to an existing class.
    """
    _require_student(conn, student_id)

    if new_class_id is not None:
        new_class = get_class_by_id(conn, new_class_id)
        if new_class is None:
            raise ValueError(f"Class not found: {new_class_id}")

    for class_ in get_classes_for_student(conn, student_id):
        remove_student_from_class(conn, class_.class_id, student_id)

    if new_class_id is not None:
        add_student_to_class(conn, new_class_id, student_id)


def set_student_active_status(conn: sqlite3.Connection, student_id: int, is_active: bool) -> None:
    """Activate or deactivate student_id's account.

    Does not touch their password hash, visible temporary password, or any
    attempt/result/history records - only future login attempts are
    affected (see app/services/auth_service.py), plus class membership on
    deactivation (see below).

    Deactivating additionally removes the student from every class they
    currently belong to (mirrors how deactivating a teacher unassigns their
    classes - see app/services/admin_teacher_service.py). Past revision
    attempts, marking results, and other history rows are never deleted -
    they reference student_id/class_id directly, not the class_students
    membership row, so removing that membership row does not touch them.
    Reactivating only restores login ability - it never automatically
    re-adds the student back to their previous class; an admin or teacher
    must add them to a class again through the existing class/student
    assignment flows.
    """
    _require_student(conn, student_id)
    update_is_active(conn, student_id, is_active)
    if not is_active:
        for class_ in get_classes_for_student(conn, student_id):
            remove_student_from_class(conn, class_.class_id, student_id)
