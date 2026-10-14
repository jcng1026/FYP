"""Class management logic for the Teacher and Admin roles."""

import sqlite3
from typing import List, Optional

from app.models.class_model import (
    Class,
    ClassWithTeacher,
    count_all_classes as count_all_classes_record,
    count_assigned_teachers as count_assigned_teachers_record,
    count_unassigned_classes as count_unassigned_classes_record,
    create_class as create_class_record,
    delete_class as delete_class_record,
    get_all_classes_with_teacher_info as get_all_classes_with_teacher_info_record,
    get_class_by_id as get_class_by_id_record,
    get_class_by_name_and_subject,
    get_classes_by_teacher,
    update_class_name as update_class_name_record,
    update_class_teacher as update_class_teacher_record,
)
from app.services.user_service import validate_teacher_exists

DEFAULT_SUBJECT = "English"


def list_teacher_classes(conn: sqlite3.Connection, teacher_id: int) -> List[Class]:
    """Return only the classes owned by the given teacher."""
    return get_classes_by_teacher(conn, teacher_id)


def list_all_classes_with_teacher_info(conn: sqlite3.Connection) -> List[ClassWithTeacher]:
    """Return every class in the system with its owning teacher's name attached."""
    return get_all_classes_with_teacher_info_record(conn)


def get_class_by_id(conn: sqlite3.Connection, class_id: int) -> Optional[Class]:
    return get_class_by_id_record(conn, class_id)


def count_all_classes(conn: sqlite3.Connection) -> int:
    """Return the total number of classes across all teachers."""
    return count_all_classes_record(conn)


def count_assigned_teachers(conn: sqlite3.Connection) -> int:
    """Return the number of distinct teachers who currently have at least one class."""
    return count_assigned_teachers_record(conn)


def count_unassigned_classes(conn: sqlite3.Connection) -> int:
    """Return the number of classes that have no teacher in charge yet."""
    return count_unassigned_classes_record(conn)


def create_class(
    conn: sqlite3.Connection,
    teacher_id: int,
    class_name: str,
    subject: str = DEFAULT_SUBJECT,
) -> Class:
    """Create a new class owned by the given teacher.

    Raises ValueError if the class name is empty or already taken for the subject.
    """
    class_name = class_name.strip()

    if not class_name:
        raise ValueError("Class name is required.")

    if get_class_by_name_and_subject(conn, class_name, subject) is not None:
        raise ValueError(f"A class named '{class_name}' already exists for {subject}.")

    return create_class_record(conn, class_name=class_name, subject=subject, teacher_id=teacher_id)


def create_class_for_teacher(
    conn: sqlite3.Connection,
    class_name: str,
    teacher_id: Optional[int],
    subject: str = DEFAULT_SUBJECT,
) -> Class:
    """Create a new class (Admin-initiated), optionally assigned to teacher_id.

    Pass teacher_id=None to create an unassigned class.

    Raises ValueError if the class name is empty, teacher_id is given but does
    not refer to an existing teacher account, or the name is already taken
    for the subject.
    """
    class_name = class_name.strip()

    if not class_name:
        raise ValueError("Class name is required.")

    if teacher_id is not None and not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Selected teacher account does not exist.")

    if get_class_by_name_and_subject(conn, class_name, subject) is not None:
        raise ValueError(f"A class named '{class_name}' already exists for {subject}.")

    return create_class_record(conn, class_name=class_name, subject=subject, teacher_id=teacher_id)


def update_class_name(conn: sqlite3.Connection, class_id: int, new_name: str) -> None:
    """Rename a class.

    Raises ValueError if the new name is empty, the class does not exist, or
    another class already has that name for the same subject.
    """
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Class name is required.")

    existing_class = get_class_by_id_record(conn, class_id)
    if existing_class is None:
        raise ValueError("Class not found.")

    duplicate = get_class_by_name_and_subject(conn, new_name, existing_class.subject)
    if duplicate is not None and duplicate.class_id != class_id:
        raise ValueError(f"A class named '{new_name}' already exists for {existing_class.subject}.")

    update_class_name_record(conn, class_id, new_name)


def update_class_teacher(conn: sqlite3.Connection, class_id: int, teacher_id: Optional[int]) -> None:
    """Reassign a class to a different teacher, or unassign it with teacher_id=None.

    Raises ValueError if the class does not exist, or teacher_id is given but
    does not refer to an existing teacher account.
    """
    if get_class_by_id_record(conn, class_id) is None:
        raise ValueError("Class not found.")

    if teacher_id is not None and not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Selected account is not a valid teacher.")

    update_class_teacher_record(conn, class_id, teacher_id)


def join_unassigned_class(conn: sqlite3.Connection, teacher_id: int, class_id: int) -> None:
    """Let a teacher directly claim an unassigned class as its teacher in charge.

    Raises ValueError if teacher_id is not a valid teacher, the class does
    not exist, or the class is already assigned to a teacher (a transfer
    request must be used instead).
    """
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can join a class.")

    class_ = get_class_by_id_record(conn, class_id)
    if class_ is None:
        raise ValueError("Class not found.")

    if class_.teacher_id is not None:
        raise ValueError(
            "This class is already assigned to a teacher. Please request a transfer instead."
        )

    update_class_teacher_record(conn, class_id, teacher_id)


def delete_class(conn: sqlite3.Connection, class_id: int) -> None:
    """Permanently delete a class. Hard delete for now (no student/attempt records exist yet)."""
    delete_class_record(conn, class_id)


def unassign_all_classes_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    """Unassign every class currently owned by teacher_id (each class's
    teacher_id becomes None/Unassigned). Students already enrolled in those
    classes are left exactly where they are - only class ownership changes.

    Returns the number of classes unassigned. Used when a teacher account is
    deactivated (see app/services/admin_teacher_service.py); does not check
    whether teacher_id is currently active - that is the caller's responsibility.
    """
    owned_classes = get_classes_by_teacher(conn, teacher_id)
    for class_ in owned_classes:
        update_class_teacher_record(conn, class_.class_id, None)
    return len(owned_classes)
