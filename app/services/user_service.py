"""Account management logic for the System Developer role."""

import sqlite3
from typing import List, Optional

from app.models.user_model import (
    User,
    create_user,
    get_user_by_id,
    get_user_by_teacher_code,
    get_user_by_username,
    get_users_by_role,
    update_full_name,
    update_password_hash,
    update_teacher_code,
    update_visible_temp_password,
)
from app.services.user_code_service import TEACHER_CODE_PREFIX, generate_next_code, is_valid_code_format
from app.utils.password_utils import hash_password

TEACHER_ROLE = "teacher"
ADMIN_ROLE = "admin"

TEACHER_PASSWORD_NOT_AVAILABLE_MESSAGE = "Not available - reset password to create visible temporary password."


def list_teachers(conn: sqlite3.Connection) -> List[User]:
    """Return all accounts with role = teacher."""
    return get_users_by_role(conn, TEACHER_ROLE)


def assign_teacher_code_if_missing(conn: sqlite3.Connection, user_id: int) -> str:
    """Return user_id's teacher_code, generating and persisting the next
    sequential TN#### code if it doesn't have one yet. Never overwrites an
    existing non-empty code."""
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise ValueError(f"User not found: {user_id}")
    if user.teacher_code:
        return user.teacher_code

    code = generate_next_code(conn, "teacher_code", TEACHER_CODE_PREFIX)
    update_teacher_code(conn, user_id, code)
    return code


def backfill_teacher_codes(conn: sqlite3.Connection) -> int:
    """Assign a teacher_code to every existing teacher missing one, strictly
    in user_id order, without overwriting any teacher_code that is already
    set. Returns the number of teachers newly assigned a code."""
    teachers = sorted(get_users_by_role(conn, TEACHER_ROLE), key=lambda teacher: teacher.user_id)
    assigned = 0
    for teacher in teachers:
        if not teacher.teacher_code:
            assign_teacher_code_if_missing(conn, teacher.user_id)
            assigned += 1
    return assigned


def validate_teacher_code(conn: sqlite3.Connection, teacher_code: str, exclude_user_id: Optional[int] = None) -> None:
    """Validate teacher_code's format (TN####) and uniqueness.

    Foundation for a future Admin edit flow - not called by any UI in this
    stage. Raises ValueError if the format is invalid or the code is
    already used by a different user.
    """
    if not is_valid_code_format(teacher_code, TEACHER_CODE_PREFIX):
        raise ValueError(f"Teacher code must look like '{TEACHER_CODE_PREFIX}0001'.")
    existing = get_user_by_teacher_code(conn, teacher_code)
    if existing is not None and existing.user_id != exclude_user_id:
        raise ValueError(f"Teacher code '{teacher_code}' is already in use.")


def create_teacher(conn: sqlite3.Connection, username: str, full_name: str, password: str) -> User:
    """Create a new teacher account with a hashed password, an
    auto-generated, non-editable teacher_code, and a visible temporary
    password (prototype-only convenience, mirroring create_student() - see
    app/models/user_model.update_visible_temp_password).

    Raises ValueError if any field is empty or the username is already taken.
    """
    username = username.strip()
    full_name = full_name.strip()

    if not username or not full_name or not password:
        raise ValueError("Username, full name, and password are all required.")

    if get_user_by_username(conn, username) is not None:
        raise ValueError(f"Username '{username}' already exists.")

    user = create_user(
        conn,
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        role=TEACHER_ROLE,
    )
    assign_teacher_code_if_missing(conn, user.user_id)
    update_visible_temp_password(conn, user.user_id, password)
    return get_user_by_id(conn, user.user_id)


def reset_teacher_password(conn: sqlite3.Connection, user_id: int, new_password: str) -> None:
    """Reset a teacher's password to a new hashed value, and update their
    visible temporary password to match (mirrors reset_student_password()).

    Raises ValueError if the new password is empty.
    """
    if not new_password:
        raise ValueError("New password is required.")

    update_password_hash(conn, user_id, hash_password(new_password))
    update_visible_temp_password(conn, user_id, new_password)


def get_teacher_password_display(conn: sqlite3.Connection, user_id: int) -> str:
    """Return user_id's visible temporary password, or a clear fallback
    message if none has ever been stored (e.g. a teacher created before
    this stage, whose original password was never recoverable from its
    hash). Mirrors get_student_password_display()."""
    user = get_user_by_id(conn, user_id)
    if user is None or not user.visible_temp_password:
        return TEACHER_PASSWORD_NOT_AVAILABLE_MESSAGE
    return user.visible_temp_password


def update_teacher_full_name(conn: sqlite3.Connection, user_id: int, full_name: str) -> None:
    """Update a teacher's full name.

    Raises ValueError if the new full name is empty.
    """
    full_name = full_name.strip()
    if not full_name:
        raise ValueError("Full name is required.")

    update_full_name(conn, user_id, full_name)


def validate_teacher_exists(conn: sqlite3.Connection, teacher_id: int) -> bool:
    """Return True if teacher_id refers to an existing account with role = 'teacher'."""
    user = get_user_by_id(conn, teacher_id)
    return user is not None and user.role == TEACHER_ROLE


def validate_ai_manager_exists(conn: sqlite3.Connection, owner_id: int) -> bool:
    """Stage 12G-2: True if owner_id is an existing teacher OR admin account.

    The global AI registry (model versions, training jobs, datasets) moved to
    the technical developer/admin role, but existing teacher-created records
    and teacher-scoped service tests remain valid, so both roles are accepted
    as record owners here. The admin-only POLICY (only admin may freeze/train/
    activate/rollback) is enforced at the UI/access layer
    (ai_admin_access_service), not by widening this ownership check."""
    user = get_user_by_id(conn, owner_id)
    return user is not None and user.role in (TEACHER_ROLE, ADMIN_ROLE)
