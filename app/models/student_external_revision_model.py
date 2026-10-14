"""Student external revision upload data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

PAPER_TYPE_KERTAS_1 = "Kertas 1"
PAPER_TYPE_KERTAS_2 = "Kertas 2"
ALLOWED_PAPER_TYPES = (PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2)

STATUS_UPLOADED = "uploaded"


@dataclass
class StudentExternalRevision:
    external_revision_id: int
    student_id: int
    class_id: int
    title: str
    paper_type: str
    question_paper_path: str
    marking_scheme_path: str
    completed_answer_path: str
    status: str
    is_deleted_by_student: int
    created_at: str


@dataclass
class StudentExternalRevisionRow:
    """One row per external revision upload, for the uploading student's own history."""

    external_revision_id: int
    title: str
    paper_type: str
    class_name: str
    status: str
    created_at: str
    question_paper_path: str
    marking_scheme_path: str
    completed_answer_path: str


@dataclass
class TeacherExternalRevisionRow:
    """One row per external revision upload, for a teacher viewing their students' uploads."""

    external_revision_id: int
    student_id: int
    username: str
    student_name: str
    class_name: str
    title: str
    paper_type: str
    status: str
    created_at: str
    question_paper_path: str
    marking_scheme_path: str
    completed_answer_path: str


def create_external_revision(
    conn: sqlite3.Connection,
    student_id: int,
    class_id: int,
    title: str,
    paper_type: str,
    question_paper_path: str,
    marking_scheme_path: str,
    completed_answer_path: str,
) -> StudentExternalRevision:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO student_external_revisions "
        "(student_id, class_id, title, paper_type, question_paper_path, marking_scheme_path, "
        "completed_answer_path, status, is_deleted_by_student, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (
            student_id,
            class_id,
            title,
            paper_type,
            question_paper_path,
            marking_scheme_path,
            completed_answer_path,
            STATUS_UPLOADED,
            created_at,
        ),
    )
    conn.commit()
    return StudentExternalRevision(
        external_revision_id=cursor.lastrowid,
        student_id=student_id,
        class_id=class_id,
        title=title,
        paper_type=paper_type,
        question_paper_path=question_paper_path,
        marking_scheme_path=marking_scheme_path,
        completed_answer_path=completed_answer_path,
        status=STATUS_UPLOADED,
        is_deleted_by_student=0,
        created_at=created_at,
    )


def update_external_revision_file_paths(
    conn: sqlite3.Connection,
    external_revision_id: int,
    question_paper_path: str,
    marking_scheme_path: str,
    completed_answer_path: str,
) -> None:
    conn.execute(
        "UPDATE student_external_revisions "
        "SET question_paper_path = ?, marking_scheme_path = ?, completed_answer_path = ? "
        "WHERE external_revision_id = ?",
        (question_paper_path, marking_scheme_path, completed_answer_path, external_revision_id),
    )
    conn.commit()


def get_external_revision_by_id(conn: sqlite3.Connection, external_revision_id: int) -> Optional[StudentExternalRevision]:
    row = conn.execute(
        "SELECT external_revision_id, student_id, class_id, title, paper_type, question_paper_path, "
        "marking_scheme_path, completed_answer_path, status, is_deleted_by_student, created_at "
        "FROM student_external_revisions WHERE external_revision_id = ?",
        (external_revision_id,),
    ).fetchone()
    if row is None:
        return None
    return StudentExternalRevision(**dict(row))


def soft_delete_external_revision(conn: sqlite3.Connection, external_revision_id: int) -> None:
    conn.execute(
        "UPDATE student_external_revisions SET is_deleted_by_student = 1 WHERE external_revision_id = ?",
        (external_revision_id,),
    )
    conn.commit()


def get_external_revisions_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentExternalRevisionRow]:
    rows = conn.execute(
        """
        SELECT ser.external_revision_id, ser.title, ser.paper_type, c.class_name, ser.status,
               ser.created_at, ser.question_paper_path, ser.marking_scheme_path, ser.completed_answer_path
        FROM student_external_revisions ser
        JOIN classes c ON c.class_id = ser.class_id
        WHERE ser.student_id = ? AND ser.is_deleted_by_student = 0
        ORDER BY ser.created_at DESC
        """,
        (student_id,),
    ).fetchall()
    return [StudentExternalRevisionRow(**dict(row)) for row in rows]


def count_external_revisions_for_student(conn: sqlite3.Connection, student_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM student_external_revisions WHERE student_id = ? AND is_deleted_by_student = 0",
        (student_id,),
    ).fetchone()
    return row[0]


def count_external_revisions_for_student_by_paper_type(
    conn: sqlite3.Connection, student_id: int, paper_type: str
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM student_external_revisions "
        "WHERE student_id = ? AND paper_type = ? AND is_deleted_by_student = 0",
        (student_id, paper_type),
    ).fetchone()
    return row[0]


def get_external_revisions_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherExternalRevisionRow]:
    rows = conn.execute(
        """
        SELECT ser.external_revision_id, ser.student_id, u.username, u.full_name AS student_name,
               c.class_name, ser.title, ser.paper_type, ser.status, ser.created_at,
               ser.question_paper_path, ser.marking_scheme_path, ser.completed_answer_path
        FROM student_external_revisions ser
        JOIN classes c ON c.class_id = ser.class_id
        JOIN users u ON u.user_id = ser.student_id
        WHERE c.teacher_id = ?
        ORDER BY ser.created_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [TeacherExternalRevisionRow(**dict(row)) for row in rows]
