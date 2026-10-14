"""Revision attempt data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_UPLOADED = "uploaded"


@dataclass
class RevisionAttempt:
    attempt_id: int
    material_id: int
    student_id: int
    class_id: int
    attempt_no: int
    completed_answer_path: str
    status: str
    submitted_at: str
    is_deleted_by_student: int


@dataclass
class StudentAttemptRow:
    """One row per attempt, for the submitting student's own history."""

    attempt_id: int
    material_id: int
    material_title: str
    paper_type: str
    class_name: str
    attempt_no: int
    status: str
    submitted_at: str
    completed_answer_path: str


@dataclass
class TeacherAttemptRow:
    """One row per attempt, for a teacher viewing their students' submissions."""

    attempt_id: int
    student_id: int
    username: str
    student_name: str
    class_name: str
    material_title: str
    paper_type: str
    attempt_no: int
    status: str
    submitted_at: str
    completed_answer_path: str


def is_material_assigned_to_class(conn: sqlite3.Connection, material_id: int, class_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM revision_material_classes WHERE material_id = ? AND class_id = ?",
        (material_id, class_id),
    ).fetchone()
    return row is not None


def get_max_attempt_no(conn: sqlite3.Connection, material_id: int, student_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(attempt_no) FROM revision_attempts WHERE material_id = ? AND student_id = ?",
        (material_id, student_id),
    ).fetchone()
    return row[0] if row[0] is not None else 0


def create_attempt(
    conn: sqlite3.Connection,
    material_id: int,
    student_id: int,
    class_id: int,
    attempt_no: int,
    completed_answer_path: str,
) -> RevisionAttempt:
    submitted_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO revision_attempts "
        "(material_id, student_id, class_id, attempt_no, completed_answer_path, status, "
        "submitted_at, is_deleted_by_student) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (material_id, student_id, class_id, attempt_no, completed_answer_path, STATUS_UPLOADED, submitted_at),
    )
    conn.commit()
    return RevisionAttempt(
        attempt_id=cursor.lastrowid,
        material_id=material_id,
        student_id=student_id,
        class_id=class_id,
        attempt_no=attempt_no,
        completed_answer_path=completed_answer_path,
        status=STATUS_UPLOADED,
        submitted_at=submitted_at,
        is_deleted_by_student=0,
    )


def update_attempt_file_path(conn: sqlite3.Connection, attempt_id: int, completed_answer_path: str) -> None:
    conn.execute(
        "UPDATE revision_attempts SET completed_answer_path = ? WHERE attempt_id = ?",
        (completed_answer_path, attempt_id),
    )
    conn.commit()


def get_attempt_by_id(conn: sqlite3.Connection, attempt_id: int) -> Optional[RevisionAttempt]:
    row = conn.execute(
        "SELECT attempt_id, material_id, student_id, class_id, attempt_no, completed_answer_path, "
        "status, submitted_at, is_deleted_by_student FROM revision_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return RevisionAttempt(**dict(row))


def soft_delete_attempt(conn: sqlite3.Connection, attempt_id: int) -> None:
    conn.execute(
        "UPDATE revision_attempts SET is_deleted_by_student = 1 WHERE attempt_id = ?",
        (attempt_id,),
    )
    conn.commit()


def get_attempts_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentAttemptRow]:
    rows = conn.execute(
        """
        SELECT ra.attempt_id, ra.material_id, rm.title AS material_title, rm.paper_type,
               c.class_name, ra.attempt_no, ra.status, ra.submitted_at, ra.completed_answer_path
        FROM revision_attempts ra
        JOIN revision_materials rm ON rm.material_id = ra.material_id
        JOIN classes c ON c.class_id = ra.class_id
        WHERE ra.student_id = ? AND ra.is_deleted_by_student = 0
        ORDER BY ra.submitted_at DESC
        """,
        (student_id,),
    ).fetchall()
    return [StudentAttemptRow(**dict(row)) for row in rows]


def get_attempts_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherAttemptRow]:
    rows = conn.execute(
        """
        SELECT ra.attempt_id, ra.student_id, u.username, u.full_name AS student_name,
               c.class_name, rm.title AS material_title, rm.paper_type, ra.attempt_no,
               ra.status, ra.submitted_at, ra.completed_answer_path
        FROM revision_attempts ra
        JOIN revision_materials rm ON rm.material_id = ra.material_id
        JOIN classes c ON c.class_id = ra.class_id
        JOIN users u ON u.user_id = ra.student_id
        WHERE c.teacher_id = ?
        ORDER BY ra.submitted_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [TeacherAttemptRow(**dict(row)) for row in rows]
