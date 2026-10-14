"""Admin-only teacher account management (Stage 11B).

Mirrors app/services/admin_student_service.py's split for the Teacher role:
username/full-name editing with uniqueness validation, and activate/
deactivate. Teacher password reset/view remain in
app/services/user_service.py (mirroring how student password reset/view
live in app/services/student_service.py, not admin_student_service.py).

Deactivating a teacher additionally unassigns every class they currently
own (students stay in those classes; only the class's teacher_id becomes
None/Unassigned) - see
app/services/class_service.py::unassign_all_classes_for_teacher.
Reactivating a teacher only restores login ability; it never re-assigns
their previous classes back to them - an admin or another teacher must
claim/reassign those classes through the existing class ownership flows
(Change Teacher, Join Unassigned Class, transfer requests).
"""

import sqlite3

from app.models.user_model import (
    User,
    get_user_by_id,
    get_user_by_username,
    update_full_name,
    update_is_active,
    update_username,
)
from app.services.class_service import unassign_all_classes_for_teacher

TEACHER_ROLE = "teacher"


def _require_teacher(conn: sqlite3.Connection, teacher_id: int) -> User:
    user = get_user_by_id(conn, teacher_id)
    if user is None or user.role != TEACHER_ROLE:
        raise ValueError(f"Teacher not found: {teacher_id}")
    return user


def get_teacher_for_admin(conn: sqlite3.Connection, teacher_id: int) -> User:
    """Return teacher_id's account.

    Raises ValueError if it doesn't exist or isn't a teacher account.
    """
    return _require_teacher(conn, teacher_id)


def update_teacher_details(conn: sqlite3.Connection, teacher_id: int, username: str, full_name: str) -> None:
    """Update a teacher's username and full name (Admin-only edit).

    teacher_code is never editable here, and user_id is never changed.

    Raises ValueError if the teacher doesn't exist, either field is empty,
    or the new username is already taken by a different account.
    """
    _require_teacher(conn, teacher_id)

    username = username.strip()
    full_name = full_name.strip()
    if not username or not full_name:
        raise ValueError("Username and full name are both required.")

    existing = get_user_by_username(conn, username)
    if existing is not None and existing.user_id != teacher_id:
        raise ValueError(f"Username '{username}' already exists.")

    update_username(conn, teacher_id, username)
    update_full_name(conn, teacher_id, full_name)


def set_teacher_active_status(conn: sqlite3.Connection, teacher_id: int, is_active: bool) -> None:
    """Activate or deactivate teacher_id's account.

    Does not touch their password hash or visible temporary password -
    only future login attempts are affected (see app/services/auth_service.py).

    Deactivating additionally unassigns every class currently owned by this
    teacher (each class's teacher_id becomes None/Unassigned; students
    already in those classes are left exactly where they are). Reactivating
    only restores login ability - it never automatically re-assigns those
    classes back to the teacher.
    """
    _require_teacher(conn, teacher_id)
    update_is_active(conn, teacher_id, is_active)
    if not is_active:
        unassign_all_classes_for_teacher(conn, teacher_id)
