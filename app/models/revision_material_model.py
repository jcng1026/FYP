"""Revision material data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

PAPER_TYPE_KERTAS_1 = "Kertas 1"
PAPER_TYPE_KERTAS_2 = "Kertas 2"
PAPER_TYPE_BOTH = "Both"
ALLOWED_PAPER_TYPES = (PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2, PAPER_TYPE_BOTH)
"""Both is a revision material label only in this prototype - it does not
trigger combined Kertas 1 + Kertas 2 marking setup/logic. Anywhere a
workflow needs one specific paper type, a Both material falls back to
existing Kertas 2-shaped behavior rather than crashing (see
teacher_dashboard.handle_open_marking_setup for the explicit label-only gate)."""


@dataclass
class RevisionMaterial:
    material_id: int
    teacher_id: int
    title: str
    paper_type: str
    subject: str
    question_paper_path: str
    marking_scheme_path: str
    created_at: str


@dataclass
class TeacherMaterialRow:
    """One row per revision material owned by a teacher, with assigned
    class names aggregated into a single comma-separated string."""

    material_id: int
    title: str
    paper_type: str
    created_at: str
    class_names: str
    question_paper_path: str
    marking_scheme_path: str


@dataclass
class StudentMaterialRow:
    """One row per (material, class) pair visible to a student."""

    material_id: int
    title: str
    paper_type: str
    class_id: int
    class_name: str
    created_at: str
    question_paper_path: str
    marking_scheme_path: str


def create_material(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    subject: str,
    question_paper_path: str,
    marking_scheme_path: str,
) -> RevisionMaterial:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO revision_materials "
        "(teacher_id, title, paper_type, subject, question_paper_path, marking_scheme_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (teacher_id, title, paper_type, subject, question_paper_path, marking_scheme_path, created_at),
    )
    conn.commit()
    return RevisionMaterial(
        material_id=cursor.lastrowid,
        teacher_id=teacher_id,
        title=title,
        paper_type=paper_type,
        subject=subject,
        question_paper_path=question_paper_path,
        marking_scheme_path=marking_scheme_path,
        created_at=created_at,
    )


def update_material_file_paths(
    conn: sqlite3.Connection, material_id: int, question_paper_path: str, marking_scheme_path: str
) -> None:
    conn.execute(
        "UPDATE revision_materials SET question_paper_path = ?, marking_scheme_path = ? WHERE material_id = ?",
        (question_paper_path, marking_scheme_path, material_id),
    )
    conn.commit()


def get_material_by_id(conn: sqlite3.Connection, material_id: int) -> Optional[RevisionMaterial]:
    row = conn.execute(
        "SELECT material_id, teacher_id, title, paper_type, subject, "
        "question_paper_path, marking_scheme_path, created_at "
        "FROM revision_materials WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    if row is None:
        return None
    return RevisionMaterial(**dict(row))


def assign_material_to_class(conn: sqlite3.Connection, material_id: int, class_id: int) -> None:
    conn.execute(
        "INSERT INTO revision_material_classes (material_id, class_id) VALUES (?, ?)",
        (material_id, class_id),
    )
    conn.commit()


def get_materials_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherMaterialRow]:
    rows = conn.execute(
        """
        SELECT rm.material_id, rm.title, rm.paper_type, rm.created_at,
               rm.question_paper_path, rm.marking_scheme_path,
               GROUP_CONCAT(c.class_name, ', ') AS class_names
        FROM revision_materials rm
        LEFT JOIN revision_material_classes rmc ON rmc.material_id = rm.material_id
        LEFT JOIN classes c ON c.class_id = rmc.class_id
        WHERE rm.teacher_id = ?
        GROUP BY rm.material_id, rm.title, rm.paper_type, rm.created_at,
                 rm.question_paper_path, rm.marking_scheme_path
        ORDER BY rm.created_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [TeacherMaterialRow(**dict(row)) for row in rows]


def count_materials_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM revision_materials WHERE teacher_id = ?", (teacher_id,)
    ).fetchone()
    return row[0]


def count_materials_for_teacher_by_paper_type(conn: sqlite3.Connection, teacher_id: int, paper_type: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM revision_materials WHERE teacher_id = ? AND paper_type = ?",
        (teacher_id, paper_type),
    ).fetchone()
    return row[0]


def get_materials_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentMaterialRow]:
    """Return one row per (material, class) pair visible to this student -
    i.e. classes the student belongs to that have this material assigned."""
    rows = conn.execute(
        """
        SELECT rm.material_id, rm.title, rm.paper_type, c.class_id, c.class_name,
               rm.created_at, rm.question_paper_path, rm.marking_scheme_path
        FROM revision_material_classes rmc
        JOIN revision_materials rm ON rm.material_id = rmc.material_id
        JOIN classes c ON c.class_id = rmc.class_id
        JOIN class_students cs ON cs.class_id = c.class_id
        WHERE cs.student_id = ?
        ORDER BY rm.created_at DESC
        """,
        (student_id,),
    ).fetchall()
    return [StudentMaterialRow(**dict(row)) for row in rows]
