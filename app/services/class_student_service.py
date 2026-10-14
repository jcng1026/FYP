"""Class-student membership logic for the Teacher role."""

import sqlite3
from typing import List

from app.models.class_model import Class
from app.models.class_student_model import (
    StudentInClassRow,
    TeacherStudentRow,
    add_student_to_class as add_student_to_class_record,
    count_distinct_students_for_teacher as count_distinct_students_for_teacher_record,
    get_classes_for_student as get_classes_for_student_record,
    get_classes_for_student_owned_by_teacher as get_classes_for_student_owned_by_teacher_record,
    get_students_for_teacher as get_students_for_teacher_record,
    get_students_in_class as get_students_in_class_record,
    is_student_in_class,
    remove_student_from_class as remove_student_from_class_record,
)
from app.models.user_model import get_user_by_id
from app.services.class_service import get_class_by_id

STUDENT_ROLE = "student"


def add_student_to_class(conn: sqlite3.Connection, teacher_id: int, class_id: int, student_id: int) -> None:
    """Add a student to a class owned by teacher_id.

    Raises ValueError if the class doesn't exist or isn't owned by
    teacher_id, the target account doesn't exist or isn't a student, or the
    student is already in the class.
    """
    class_ = get_class_by_id(conn, class_id)
    if class_ is None:
        raise ValueError("Class not found.")
    if class_.teacher_id != teacher_id:
        raise ValueError("You can only add students to your own classes.")

    student = get_user_by_id(conn, student_id)
    if student is None or student.role != STUDENT_ROLE:
        raise ValueError("Selected account is not a valid student.")

    if is_student_in_class(conn, class_id, student_id):
        raise ValueError("This student is already in the class.")

    add_student_to_class_record(conn, class_id, student_id)


def remove_student_from_class(conn: sqlite3.Connection, teacher_id: int, class_id: int, student_id: int) -> None:
    """Remove a student from a class owned by teacher_id. The student account is not deleted.

    Raises ValueError if the class doesn't exist or isn't owned by teacher_id.
    """
    class_ = get_class_by_id(conn, class_id)
    if class_ is None:
        raise ValueError("Class not found.")
    if class_.teacher_id != teacher_id:
        raise ValueError("You can only remove students from your own classes.")

    remove_student_from_class_record(conn, class_id, student_id)


def list_students_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherStudentRow]:
    """Return one row per distinct student across all of teacher_id's classes."""
    return get_students_for_teacher_record(conn, teacher_id)


def count_distinct_students_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    """Return the number of distinct students across all of teacher_id's classes."""
    return count_distinct_students_for_teacher_record(conn, teacher_id)


def get_students_in_class_for_teacher(
    conn: sqlite3.Connection, teacher_id: int, class_id: int
) -> List[StudentInClassRow]:
    """Return the students in class_id, if class_id is owned by teacher_id.

    Raises ValueError if the class doesn't exist or isn't owned by teacher_id.
    """
    class_ = get_class_by_id(conn, class_id)
    if class_ is None:
        raise ValueError("Class not found.")
    if class_.teacher_id != teacher_id:
        raise ValueError("You can only view students in your own classes.")

    return get_students_in_class_record(conn, class_id)


def get_classes_for_student_owned_by_teacher(
    conn: sqlite3.Connection, teacher_id: int, student_id: int
) -> List[Class]:
    """Return teacher_id's own classes that student_id currently belongs to."""
    return get_classes_for_student_owned_by_teacher_record(conn, teacher_id, student_id)


def list_classes_for_student(conn: sqlite3.Connection, student_id: int) -> List[Class]:
    """Return every class (any teacher) that student_id currently belongs to."""
    return get_classes_for_student_record(conn, student_id)
