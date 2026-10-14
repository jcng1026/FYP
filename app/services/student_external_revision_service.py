"""Student external revision upload logic for the Student and Teacher roles."""

import sqlite3
from pathlib import Path
from typing import List

from app.models.class_student_model import is_student_in_class
from app.models.student_external_revision_model import (
    ALLOWED_PAPER_TYPES,
    StudentExternalRevision,
    StudentExternalRevisionRow,
    TeacherExternalRevisionRow,
    count_external_revisions_for_student as count_external_revisions_for_student_record,
    count_external_revisions_for_student_by_paper_type as count_external_revisions_for_student_by_paper_type_record,
    create_external_revision,
    get_external_revision_by_id,
    get_external_revisions_for_student as get_external_revisions_for_student_record,
    get_external_revisions_for_teacher as get_external_revisions_for_teacher_record,
    soft_delete_external_revision as soft_delete_external_revision_record,
    update_external_revision_file_paths,
)
from app.models.user_model import get_user_by_id
from app.utils.file_storage import store_external_revision_file

STUDENT_ROLE = "student"


def create_student_external_revision(
    conn: sqlite3.Connection,
    student_id: int,
    class_id: int,
    title: str,
    paper_type: str,
    completed_answer_source_path: str,
    question_paper_source_path: str = "",
    marking_scheme_source_path: str = "",
) -> StudentExternalRevision:
    """Create a new external revision upload for student_id, copying the
    selected files into a local, upload-specific folder under
    data/external_revisions/.

    The student supplies only their COMPLETED ANSWER paper. The question
    paper and answer scheme are the teacher's side of the workflow - they
    come from the Subject Profile the teacher picks (or imports) when
    marking, so both are optional here and kept only for older uploads
    that still carry them.

    Raises ValueError if the requester is not a student, the student does
    not belong to class_id, the title is empty, the paper type is not
    Kertas 1/2, or the completed answer file is missing or does not exist.
    """
    student = get_user_by_id(conn, student_id)
    if student is None or student.role != STUDENT_ROLE:
        raise ValueError("Only student accounts can create external revision uploads.")

    if not is_student_in_class(conn, class_id, student_id):
        raise ValueError("You can only submit external revisions for a class you belong to.")

    title = title.strip()
    if not title:
        raise ValueError("Title is required.")

    if paper_type not in ALLOWED_PAPER_TYPES:
        raise ValueError("Paper type must be Kertas 1 or Kertas 2.")

    question_paper_source_path = (question_paper_source_path or "").strip()
    if question_paper_source_path and not Path(question_paper_source_path).is_file():
        raise ValueError("The selected question paper file could not be found.")

    marking_scheme_source_path = (marking_scheme_source_path or "").strip()
    if marking_scheme_source_path and not Path(marking_scheme_source_path).is_file():
        raise ValueError("The selected marking scheme file could not be found.")

    completed_answer_source_path = (completed_answer_source_path or "").strip()
    if not completed_answer_source_path:
        raise ValueError("A completed answer paper file is required.")
    if not Path(completed_answer_source_path).is_file():
        raise ValueError("The selected completed answer paper file could not be found.")

    revision = create_external_revision(
        conn,
        student_id=student_id,
        class_id=class_id,
        title=title,
        paper_type=paper_type,
        question_paper_path="",
        marking_scheme_path="",
        completed_answer_path="",
    )

    question_paper_path = (store_external_revision_file(
        revision.external_revision_id, question_paper_source_path, "question_paper"
    ) if question_paper_source_path else "")
    marking_scheme_path = (store_external_revision_file(
        revision.external_revision_id, marking_scheme_source_path, "marking_scheme"
    ) if marking_scheme_source_path else "")
    completed_answer_path = store_external_revision_file(
        revision.external_revision_id, completed_answer_source_path, "completed_answer"
    )
    update_external_revision_file_paths(
        conn, revision.external_revision_id, question_paper_path, marking_scheme_path, completed_answer_path
    )

    revision.question_paper_path = question_paper_path
    revision.marking_scheme_path = marking_scheme_path
    revision.completed_answer_path = completed_answer_path
    return revision


def list_external_revisions_for_student(conn: sqlite3.Connection, student_id: int) -> List[StudentExternalRevisionRow]:
    return get_external_revisions_for_student_record(conn, student_id)


def count_external_revisions_for_student(conn: sqlite3.Connection, student_id: int) -> int:
    return count_external_revisions_for_student_record(conn, student_id)


def count_external_revisions_for_student_by_paper_type(
    conn: sqlite3.Connection, student_id: int, paper_type: str
) -> int:
    return count_external_revisions_for_student_by_paper_type_record(conn, student_id, paper_type)


def list_external_revisions_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherExternalRevisionRow]:
    return get_external_revisions_for_teacher_record(conn, teacher_id)


def soft_delete_student_external_revision(conn: sqlite3.Connection, student_id: int, external_revision_id: int) -> None:
    """Hide an external revision upload from the uploading student's own list.

    The record is not removed from the database - only is_deleted_by_student
    is set - so teacher visibility is unaffected.

    Raises ValueError if the upload doesn't exist or doesn't belong to student_id.
    """
    revision = get_external_revision_by_id(conn, external_revision_id)
    if revision is None:
        raise ValueError("External revision upload not found.")
    if revision.student_id != student_id:
        raise ValueError("You can only remove your own external revision uploads.")

    soft_delete_external_revision_record(conn, external_revision_id)
