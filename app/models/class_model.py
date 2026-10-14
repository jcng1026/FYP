"""Class data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class Class:
    class_id: int
    class_name: str
    subject: str
    teacher_id: Optional[int]
    created_at: str


@dataclass
class ClassWithTeacher:
    class_id: int
    class_name: str
    subject: str
    teacher_id: Optional[int]
    teacher_name: Optional[str]
    teacher_username: Optional[str]
    created_at: str


def get_class_by_name_and_subject(
    conn: sqlite3.Connection, class_name: str, subject: str
) -> Optional[Class]:
    row = conn.execute(
        "SELECT class_id, class_name, subject, teacher_id, created_at "
        "FROM classes WHERE class_name = ? AND subject = ?",
        (class_name, subject),
    ).fetchone()
    if row is None:
        return None
    return Class(**dict(row))


def get_class_by_id(conn: sqlite3.Connection, class_id: int) -> Optional[Class]:
    row = conn.execute(
        "SELECT class_id, class_name, subject, teacher_id, created_at "
        "FROM classes WHERE class_id = ?",
        (class_id,),
    ).fetchone()
    if row is None:
        return None
    return Class(**dict(row))


def get_classes_by_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[Class]:
    rows = conn.execute(
        "SELECT class_id, class_name, subject, teacher_id, created_at "
        "FROM classes WHERE teacher_id = ? ORDER BY created_at",
        (teacher_id,),
    ).fetchall()
    return [Class(**dict(row)) for row in rows]


def count_all_classes(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM classes").fetchone()
    return row[0]


def count_assigned_teachers(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT teacher_id) FROM classes").fetchone()
    return row[0]


def count_unassigned_classes(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM classes WHERE teacher_id IS NULL").fetchone()
    return row[0]


def get_all_classes_with_teacher_info(conn: sqlite3.Connection) -> List[ClassWithTeacher]:
    """Return every class in the system along with its owning teacher's name and username.

    teacher_id, teacher_name, and teacher_username are None for unassigned classes.
    """
    rows = conn.execute(
        """
        SELECT c.class_id, c.class_name, c.subject, c.teacher_id,
               u.full_name AS teacher_name, u.username AS teacher_username, c.created_at
        FROM classes c
        LEFT JOIN users u ON u.user_id = c.teacher_id
        ORDER BY c.created_at
        """
    ).fetchall()
    return [ClassWithTeacher(**dict(row)) for row in rows]


def create_class(
    conn: sqlite3.Connection,
    class_name: str,
    subject: str,
    teacher_id: Optional[int],
) -> Class:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO classes (class_name, subject, teacher_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (class_name, subject, teacher_id, created_at),
    )
    conn.commit()
    return Class(
        class_id=cursor.lastrowid,
        class_name=class_name,
        subject=subject,
        teacher_id=teacher_id,
        created_at=created_at,
    )


def update_class_name(conn: sqlite3.Connection, class_id: int, class_name: str) -> None:
    conn.execute(
        "UPDATE classes SET class_name = ? WHERE class_id = ?",
        (class_name, class_id),
    )
    conn.commit()


def update_class_teacher(conn: sqlite3.Connection, class_id: int, teacher_id: Optional[int]) -> None:
    conn.execute(
        "UPDATE classes SET teacher_id = ? WHERE class_id = ?",
        (teacher_id, class_id),
    )
    conn.commit()


def delete_class(conn: sqlite3.Connection, class_id: int) -> None:
    conn.execute("DELETE FROM classes WHERE class_id = ?", (class_id,))
    conn.commit()
