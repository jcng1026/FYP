"""Student account management logic for the Teacher role."""

import sqlite3
from typing import Optional

from app.models.user_model import (
    User,
    create_user,
    get_user_by_id,
    get_user_by_student_code,
    get_user_by_username,
    get_users_by_role,
    update_password_hash,
    update_student_code,
    update_visible_temp_password,
)
from app.services.class_student_service import add_student_to_class
from app.services.user_code_service import STUDENT_CODE_PREFIX, generate_next_code, is_valid_code_format
from app.utils.password_utils import hash_password

STUDENT_ROLE = "student"

STUDENT_PASSWORD_NOT_AVAILABLE_MESSAGE = "Not available - reset password to create visible temporary password."


def assign_student_code_if_missing(conn: sqlite3.Connection, user_id: int) -> str:
    """Return user_id's student_code, generating and persisting the next
    sequential TP#### code if it doesn't have one yet. Never overwrites an
    existing non-empty code. Fully independent of username, which remains
    manually typed by the teacher."""
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise ValueError(f"User not found: {user_id}")
    if user.student_code:
        return user.student_code

    code = generate_next_code(conn, "student_code", STUDENT_CODE_PREFIX)
    update_student_code(conn, user_id, code)
    return code


def backfill_student_codes(conn: sqlite3.Connection) -> int:
    """Assign a student_code to every existing student missing one, strictly
    in user_id order, without overwriting any student_code that is already
    set. Returns the number of students newly assigned a code."""
    students = sorted(get_users_by_role(conn, STUDENT_ROLE), key=lambda student: student.user_id)
    assigned = 0
    for student in students:
        if not student.student_code:
            assign_student_code_if_missing(conn, student.user_id)
            assigned += 1
    return assigned


def validate_student_code(conn: sqlite3.Connection, student_code: str, exclude_user_id: Optional[int] = None) -> None:
    """Validate student_code's format (TP####) and uniqueness.

    Foundation for a future Admin edit flow - not called by any UI in this
    stage. Raises ValueError if the format is invalid or the code is
    already used by a different user.
    """
    if not is_valid_code_format(student_code, STUDENT_CODE_PREFIX):
        raise ValueError(f"Student code must look like '{STUDENT_CODE_PREFIX}0001'.")
    existing = get_user_by_student_code(conn, student_code)
    if existing is not None and existing.user_id != exclude_user_id:
        raise ValueError(f"Student code '{student_code}' is already in use.")


def create_student(conn: sqlite3.Connection, username: str, full_name: str, password: str) -> User:
    """Create a new student account with a hashed password, an
    auto-generated student_code, and a visible temporary password.

    The username is manually typed by the teacher (e.g. 'TP070498') and is
    intentionally kept separate from the auto-generated student_code. The
    plain-text password is stored as a prototype-only "visible temporary
    password" for teacher convenience (see
    app/models/user_model.update_visible_temp_password) - the real
    authentication credential remains the hashed password.

    Raises ValueError if any field is empty or the username is already taken.
    """
    username = username.strip()
    full_name = full_name.strip()

    if not username or not full_name or not password:
        raise ValueError("Student ID, full name, and password are all required.")

    if get_user_by_username(conn, username) is not None:
        raise ValueError(f"Username '{username}' already exists.")

    user = create_user(
        conn,
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        role=STUDENT_ROLE,
    )
    assign_student_code_if_missing(conn, user.user_id)
    update_visible_temp_password(conn, user.user_id, password)
    return get_user_by_id(conn, user.user_id)


def create_student_in_class(
    conn: sqlite3.Connection,
    teacher_id: int,
    username: str,
    full_name: str,
    password: str,
    class_id: int,
) -> User:
    """Create a new student account and immediately enroll them in one of
    teacher_id's own classes.

    Raises ValueError if any field is empty, the username is already taken,
    or class_id does not refer to a class owned by teacher_id.
    """
    student = create_student(conn, username, full_name, password)
    add_student_to_class(conn, teacher_id, class_id, student.user_id)
    return student


def reset_student_password(conn: sqlite3.Connection, student_id: int, new_password: str) -> None:
    """Reset a student's password to a new hashed value, and update their
    visible temporary password to match.

    Raises ValueError if the new password is empty.
    """
    if not new_password:
        raise ValueError("New password is required.")

    update_password_hash(conn, student_id, hash_password(new_password))
    update_visible_temp_password(conn, student_id, new_password)


def get_student_password_display(conn: sqlite3.Connection, student_id: int) -> str:
    """Return student_id's visible temporary password, or a clear fallback
    message if none has ever been stored (e.g. a student created before
    this stage, whose original password was never recoverable from its
    hash)."""
    user = get_user_by_id(conn, student_id)
    if user is None or not user.visible_temp_password:
        return STUDENT_PASSWORD_NOT_AVAILABLE_MESSAGE
    return user.visible_temp_password


def find_student_by_username(conn: sqlite3.Connection, username: str) -> Optional[User]:
    """Return the user if username exists and has role='student', else None."""
    user = get_user_by_username(conn, username.strip())
    if user is None or user.role != STUDENT_ROLE:
        return None
    return user


def find_student_by_identifier(conn: sqlite3.Connection, identifier: str) -> Optional[User]:
    """Look up a student account by student_code (e.g. 'TP0001') or, failing
    that, by username - so callers never need to know or type a raw
    internal user_id. Returns None if neither lookup finds a student."""
    identifier = identifier.strip()
    if not identifier:
        return None

    user = get_user_by_student_code(conn, identifier)
    if user is not None and user.role == STUDENT_ROLE:
        return user

    return find_student_by_username(conn, identifier)
