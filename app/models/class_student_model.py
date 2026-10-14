"""Class-student membership data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from app.models.class_model import Class


@dataclass
class ClassStudent:
    class_id: int
    student_id: int
    added_at: str


@dataclass
class TeacherStudentRow:
    """One row per distinct student across a teacher's classes.

    class_names is a comma-separated list of that teacher's class names the
    student currently belongs to (a student can be in more than one).
    student_code is the separate, auto-generated TP#### display code -
    distinct from username, which remains manually typed.
    """

    user_id: int
    username: str
    full_name: str
    created_at: str
    class_names: str
    student_code: Optional[str] = None


@dataclass
class StudentInClassRow:
    user_id: int
    username: str
    full_name: str
    added_at: str


@dataclass
class AdminStudentRow:
    """One row per student account, across every teacher/class (Admin-only
    view - unlike TeacherStudentRow, which is scoped to one teacher).

    class_names and teacher_names are comma-separated lists describing
    every class the student currently belongs to (and that class's
    teacher-in-charge), or "" if they belong to no class yet.
    """

    user_id: int
    student_code: Optional[str]
    username: str
    full_name: str
    class_names: str
    teacher_names: str
    is_active: bool
    created_at: str


UNASSIGNED_FILTER = "unassigned"
"""Sentinel passed as class_id to get_all_students_with_class_info() /
list_all_students() to mean "students in no class at all" - distinct from
None, which means "no filter, show every student"."""


def is_student_in_class(conn: sqlite3.Connection, class_id: int, student_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM class_students WHERE class_id = ? AND student_id = ?",
        (class_id, student_id),
    ).fetchone()
    return row is not None


def add_student_to_class(conn: sqlite3.Connection, class_id: int, student_id: int) -> ClassStudent:
    added_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "INSERT INTO class_students (class_id, student_id, added_at) VALUES (?, ?, ?)",
        (class_id, student_id, added_at),
    )
    conn.commit()
    return ClassStudent(class_id=class_id, student_id=student_id, added_at=added_at)


def remove_student_from_class(conn: sqlite3.Connection, class_id: int, student_id: int) -> None:
    conn.execute(
        "DELETE FROM class_students WHERE class_id = ? AND student_id = ?",
        (class_id, student_id),
    )
    conn.commit()


def get_students_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherStudentRow]:
    """Return one row per distinct student in any of teacher_id's classes."""
    rows = conn.execute(
        """
        SELECT u.user_id, u.username, u.full_name, u.created_at, u.student_code,
               GROUP_CONCAT(c.class_name, ', ') AS class_names
        FROM class_students cs
        JOIN classes c ON c.class_id = cs.class_id
        JOIN users u ON u.user_id = cs.student_id
        WHERE c.teacher_id = ?
        GROUP BY u.user_id, u.username, u.full_name, u.created_at, u.student_code
        ORDER BY u.full_name
        """,
        (teacher_id,),
    ).fetchall()
    return [TeacherStudentRow(**dict(row)) for row in rows]


def count_distinct_students_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT cs.student_id)
        FROM class_students cs
        JOIN classes c ON c.class_id = cs.class_id
        WHERE c.teacher_id = ?
        """,
        (teacher_id,),
    ).fetchone()
    return row[0]


def get_students_in_class(conn: sqlite3.Connection, class_id: int) -> List[StudentInClassRow]:
    rows = conn.execute(
        """
        SELECT u.user_id, u.username, u.full_name, cs.added_at
        FROM class_students cs
        JOIN users u ON u.user_id = cs.student_id
        WHERE cs.class_id = ?
        ORDER BY u.full_name
        """,
        (class_id,),
    ).fetchall()
    return [StudentInClassRow(**dict(row)) for row in rows]


def get_classes_for_student_owned_by_teacher(
    conn: sqlite3.Connection, teacher_id: int, student_id: int
) -> List[Class]:
    """Return teacher_id's own classes that student_id currently belongs to."""
    rows = conn.execute(
        """
        SELECT c.class_id, c.class_name, c.subject, c.teacher_id, c.created_at
        FROM classes c
        JOIN class_students cs ON cs.class_id = c.class_id
        WHERE c.teacher_id = ? AND cs.student_id = ?
        ORDER BY c.class_name
        """,
        (teacher_id, student_id),
    ).fetchall()
    return [Class(**dict(row)) for row in rows]


def get_classes_for_student(conn: sqlite3.Connection, student_id: int) -> List[Class]:
    """Return every class (any teacher) that student_id currently belongs to."""
    rows = conn.execute(
        """
        SELECT c.class_id, c.class_name, c.subject, c.teacher_id, c.created_at
        FROM classes c
        JOIN class_students cs ON cs.class_id = c.class_id
        WHERE cs.student_id = ?
        ORDER BY c.class_name
        """,
        (student_id,),
    ).fetchall()
    return [Class(**dict(row)) for row in rows]


def get_all_students_with_class_info(
    conn: sqlite3.Connection, class_id: Optional[object] = None
) -> List[AdminStudentRow]:
    """Return every student account (Admin-only view - not scoped to any one
    teacher).

    class_id filtering modes:
    - None: no filter, every student is returned.
    - UNASSIGNED_FILTER: only students currently in zero classes.
    - an int: only students currently in that specific class.

    class_names/teacher_names are built from correlated subqueries (rather
    than a JOIN + GROUP_CONCAT(DISTINCT ...), which SQLite does not support
    combined with a custom separator) so students in no class still get a
    row with class_names = "" and teacher_names = "".
    """
    if class_id == UNASSIGNED_FILTER:
        where_clause = "AND u.user_id NOT IN (SELECT student_id FROM class_students)"
        params: tuple = ()
    elif class_id is not None:
        where_clause = "AND u.user_id IN (SELECT student_id FROM class_students WHERE class_id = ?)"
        params = (class_id,)
    else:
        where_clause = ""
        params = ()

    rows = conn.execute(
        f"""
        SELECT u.user_id, u.student_code, u.username, u.full_name, u.is_active, u.created_at,
               (SELECT GROUP_CONCAT(class_name, ', ') FROM (
                   SELECT DISTINCT c2.class_name
                   FROM classes c2
                   JOIN class_students cs2 ON cs2.class_id = c2.class_id
                   WHERE cs2.student_id = u.user_id
               )) AS class_names,
               (SELECT GROUP_CONCAT(full_name, ', ') FROM (
                   SELECT DISTINCT t2.full_name
                   FROM classes c2
                   JOIN class_students cs2 ON cs2.class_id = c2.class_id
                   JOIN users t2 ON t2.user_id = c2.teacher_id
                   WHERE cs2.student_id = u.user_id
               )) AS teacher_names
        FROM users u
        WHERE u.role = 'student'
        {where_clause}
        ORDER BY u.full_name
        """,
        params,
    ).fetchall()

    result = []
    for row in rows:
        data = dict(row)
        data["is_active"] = bool(data["is_active"])
        data["class_names"] = data["class_names"] or ""
        data["teacher_names"] = data["teacher_names"] or ""
        result.append(AdminStudentRow(**data))
    return result
