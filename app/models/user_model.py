"""User data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

_USER_COLUMNS = (
    "user_id, username, password_hash, full_name, role, created_at, "
    "teacher_code, student_code, visible_temp_password, is_active"
)


@dataclass
class User:
    user_id: int
    username: str
    password_hash: str
    full_name: str
    role: str
    created_at: str
    teacher_code: Optional[str] = None
    student_code: Optional[str] = None
    visible_temp_password: Optional[str] = None
    is_active: bool = True


def _row_to_user(row) -> User:
    data = dict(row)
    data["is_active"] = bool(data["is_active"])
    return User(**data)


def get_user_by_username(conn: sqlite3.Connection, username: str) -> Optional[User]:
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_user_by_teacher_code(conn: sqlite3.Connection, teacher_code: str) -> Optional[User]:
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE teacher_code = ?",
        (teacher_code,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_user_by_student_code(conn: sqlite3.Connection, student_code: str) -> Optional[User]:
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE student_code = ?",
        (student_code,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_users_by_role(conn: sqlite3.Connection, role: str) -> List[User]:
    rows = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE role = ? ORDER BY created_at",
        (role,),
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def update_password_hash(conn: sqlite3.Connection, user_id: int, password_hash: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE user_id = ?",
        (password_hash, user_id),
    )
    conn.commit()


def update_full_name(conn: sqlite3.Connection, user_id: int, full_name: str) -> None:
    conn.execute(
        "UPDATE users SET full_name = ? WHERE user_id = ?",
        (full_name, user_id),
    )
    conn.commit()


def update_username(conn: sqlite3.Connection, user_id: int, username: str) -> None:
    conn.execute(
        "UPDATE users SET username = ? WHERE user_id = ?",
        (username, user_id),
    )
    conn.commit()


def update_teacher_code(conn: sqlite3.Connection, user_id: int, teacher_code: str) -> None:
    conn.execute(
        "UPDATE users SET teacher_code = ? WHERE user_id = ?",
        (teacher_code, user_id),
    )
    conn.commit()


def update_student_code(conn: sqlite3.Connection, user_id: int, student_code: str) -> None:
    conn.execute(
        "UPDATE users SET student_code = ? WHERE user_id = ?",
        (student_code, user_id),
    )
    conn.commit()


def update_visible_temp_password(conn: sqlite3.Connection, user_id: int, visible_temp_password: Optional[str]) -> None:
    """Store a prototype-only, plain-text "visible temporary password" for
    display convenience (e.g. so a teacher can hand a freshly created
    student their password). This is never used for authentication - see
    update_password_hash / app/services/auth_service.py for the real,
    hashed credential."""
    conn.execute(
        "UPDATE users SET visible_temp_password = ? WHERE user_id = ?",
        (visible_temp_password, user_id),
    )
    conn.commit()


def update_is_active(conn: sqlite3.Connection, user_id: int, is_active: bool) -> None:
    """Activate or deactivate a user account. Only affects future login
    attempts (see app/services/auth_service.py) - it does not touch
    password hashes, formal codes, class membership, or any other data."""
    conn.execute(
        "UPDATE users SET is_active = ? WHERE user_id = ?",
        (1 if is_active else 0, user_id),
    )
    conn.commit()


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password_hash: str,
    full_name: str,
    role: str,
) -> User:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (username, password_hash, full_name, role, created_at),
    )
    conn.commit()
    return User(
        user_id=cursor.lastrowid,
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        created_at=created_at,
    )
