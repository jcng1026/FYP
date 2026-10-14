"""Revision material creation and visibility logic for the Teacher and Student roles."""

import sqlite3
from pathlib import Path
from typing import List

from app.models.revision_material_model import (
    ALLOWED_PAPER_TYPES,
    RevisionMaterial,
    StudentMaterialRow,
    TeacherMaterialRow,
    assign_material_to_class,
    count_materials_for_teacher as count_materials_for_teacher_record,
    count_materials_for_teacher_by_paper_type as count_materials_for_teacher_by_paper_type_record,
    create_material,
    get_materials_for_student as get_materials_for_student_record,
    get_materials_for_teacher as get_materials_for_teacher_record,
    update_material_file_paths,
)
from app.services.class_service import get_class_by_id
from app.services.user_service import validate_teacher_exists
from app.utils.file_storage import store_material_file

DEFAULT_SUBJECT = "English"


def create_revision_material(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    question_paper_source_path: str,
    marking_scheme_source_path: str,
    class_ids: List[int],
    subject: str = DEFAULT_SUBJECT,
) -> RevisionMaterial:
    """Create a new revision material and assign it to one or more of
    teacher_id's own classes, copying the selected files into a local,
    material-specific folder under data/revision_materials/.

    Raises ValueError if the requester is not a teacher, the title is empty,
    the paper type is not one of Kertas 1 / Kertas 2 / Both, either file path
    is missing or does not exist, no classes are selected, or any selected
    class is not owned by teacher_id (or does not exist).
    """
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create revision materials.")

    title = title.strip()
    if not title:
        raise ValueError("Title is required.")

    if paper_type not in ALLOWED_PAPER_TYPES:
        raise ValueError(f"Paper type must be one of: {', '.join(ALLOWED_PAPER_TYPES)}.")

    question_paper_source_path = (question_paper_source_path or "").strip()
    if not question_paper_source_path:
        raise ValueError("A question paper file is required.")
    if not Path(question_paper_source_path).is_file():
        raise ValueError("The selected question paper file could not be found.")

    marking_scheme_source_path = (marking_scheme_source_path or "").strip()
    if not marking_scheme_source_path:
        raise ValueError("A marking scheme file is required.")
    if not Path(marking_scheme_source_path).is_file():
        raise ValueError("The selected marking scheme file could not be found.")

    if not class_ids:
        raise ValueError("At least one class must be selected.")

    for class_id in class_ids:
        class_ = get_class_by_id(conn, class_id)
        if class_ is None:
            raise ValueError("One of the selected classes could not be found.")
        if class_.teacher_id != teacher_id:
            raise ValueError("You can only assign materials to your own classes.")

    material = create_material(
        conn,
        teacher_id=teacher_id,
        title=title,
        paper_type=paper_type,
        subject=subject,
        question_paper_path="",
        marking_scheme_path="",
    )

    question_paper_path = store_material_file(material.material_id, question_paper_source_path, "question_paper")
    marking_scheme_path = store_material_file(material.material_id, marking_scheme_source_path, "marking_scheme")
    update_material_file_paths(conn, material.material_id, question_paper_path, marking_scheme_path)

    for class_id in class_ids:
        assign_material_to_class(conn, material.material_id, class_id)

    material.question_paper_path = question_paper_path
    material.marking_scheme_path = marking_scheme_path
    return material


def list_materials_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherMaterialRow]:
    return get_materials_for_teacher_record(conn, teacher_id)


def count_materials_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    return count_materials_for_teacher_record(conn, teacher_id)


def count_materials_for_teacher_by_paper_type(conn: sqlite3.Connection, teacher_id: int, paper_type: str) -> int:
    return count_materials_for_teacher_by_paper_type_record(conn, teacher_id, paper_type)


def list_materials_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentMaterialRow]:
    return get_materials_for_student_record(conn, student_id)
