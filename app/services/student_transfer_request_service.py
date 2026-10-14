"""Student-class assignment and transfer request logic (Stage 10E).

Distinct from class_transfer_request_service.py, which handles a teacher
requesting ownership of an entire class from another teacher. This module
handles a single student's class assignment when a teacher tries to add an
existing student who may already belong to a different class:

- Unassigned student -> added directly, no request needed.
- Already in the target class -> no-op, caller shows an "already in class" message.
- Assigned to a different class -> a pending transfer request is created
  instead of moving the student directly, and must be approved by the
  student's current teacher (or an Admin) before the move happens.

Admin's direct Change Class (see admin_student_service.py) is unaffected -
it remains an immediate move that never goes through this request workflow.
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from app.models.class_model import get_class_by_id
from app.models.class_student_model import (
    add_student_to_class as add_student_to_class_record,
    get_classes_for_student,
    remove_student_from_class as remove_student_from_class_record,
)
from app.models.student_transfer_request_model import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    StudentTransferRequest,
    StudentTransferRequestWithDetails,
    cancel_other_pending_requests_for_student,
    count_pending_requests as count_pending_requests_record,
    count_pending_requests_for_current_teacher as count_pending_requests_for_current_teacher_record,
    create_request,
    get_all_decided_requests_with_details,
    get_all_pending_requests_with_details,
    get_decided_requests_for_teacher_with_details,
    get_pending_request_for_student_and_target,
    get_pending_requests_for_current_teacher_with_details,
    get_request_by_id,
    update_request_status,
)
from app.models.user_model import User, get_user_by_id, get_users_by_role
from app.services.user_service import ADMIN_ROLE, TEACHER_ROLE, validate_teacher_exists

STUDENT_ROLE = "student"

DIRECT_ASSIGNED = "direct_assigned"
ALREADY_IN_CLASS = "already_in_class"
MOVED_WITHIN_OWN_CLASSES = "moved_within_own_classes"
TRANSFER_REQUEST_CREATED = "transfer_request_created"

CANDIDATE_ACTION_ASSIGN_DIRECTLY = "Assign directly"
CANDIDATE_ACTION_MOVE_WITHIN_OWN_CLASSES = "Move within my classes"
CANDIDATE_ACTION_REQUEST_TRANSFER = "Request transfer"


@dataclass
class AddExistingStudentCandidate:
    """One row in the Add Existing Student candidate list - every student
    account in the system, classified by what will happen if
    requesting_teacher_id tries to add them to one of their own classes.

    current_class_name/current_teacher_name are None for an Unassigned
    student, never a raw user_id.
    """

    user_id: int
    student_code: Optional[str]
    username: str
    full_name: str
    current_class_name: Optional[str]
    current_teacher_name: Optional[str]
    expected_action: str


def list_add_existing_student_candidates(
    conn: sqlite3.Connection, requesting_teacher_id: int
) -> List[AddExistingStudentCandidate]:
    """Return every student account, classified as Unassigned (assign
    directly), already in one of requesting_teacher_id's own other classes
    (move within my classes), or in another teacher's class (request
    transfer)."""
    students = get_users_by_role(conn, STUDENT_ROLE)
    candidates = []
    for student in students:
        current_classes = get_classes_for_student(conn, student.user_id)
        if not current_classes:
            current_class_name = None
            current_teacher_name = None
            action = CANDIDATE_ACTION_ASSIGN_DIRECTLY
        else:
            current_class = current_classes[0]
            current_class_name = current_class.class_name
            teacher = get_user_by_id(conn, current_class.teacher_id)
            current_teacher_name = teacher.full_name if teacher else None
            if current_class.teacher_id == requesting_teacher_id:
                action = CANDIDATE_ACTION_MOVE_WITHIN_OWN_CLASSES
            else:
                action = CANDIDATE_ACTION_REQUEST_TRANSFER
        candidates.append(
            AddExistingStudentCandidate(
                user_id=student.user_id,
                student_code=student.student_code,
                username=student.username,
                full_name=student.full_name,
                current_class_name=current_class_name,
                current_teacher_name=current_teacher_name,
                expected_action=action,
            )
        )
    candidates.sort(key=lambda c: c.full_name)
    return candidates


def add_existing_student_to_class(
    conn: sqlite3.Connection, requesting_teacher_id: int, student_id: int, target_class_id: int
) -> str:
    """Add an existing student to one of requesting_teacher_id's own classes.

    Returns DIRECT_ASSIGNED (student was Unassigned), ALREADY_IN_CLASS (no
    change), MOVED_WITHIN_OWN_CLASSES (student was in another of this same
    teacher's classes - moved immediately, no request needed since no other
    teacher's consent is required), or TRANSFER_REQUEST_CREATED (student is
    in a different teacher's class - a pending request was created instead
    of moving them). Raises ValueError if the teacher/class/student aren't
    valid, or a pending request for this exact student and target class
    already exists.
    """
    if not validate_teacher_exists(conn, requesting_teacher_id):
        raise ValueError("Only teacher accounts can add students.")

    target_class = get_class_by_id(conn, target_class_id)
    if target_class is None:
        raise ValueError("Class not found.")
    if target_class.teacher_id != requesting_teacher_id:
        raise ValueError("You can only add students to your own classes.")

    student = get_user_by_id(conn, student_id)
    if student is None or student.role != STUDENT_ROLE:
        raise ValueError("Selected account is not a valid student.")

    current_classes = get_classes_for_student(conn, student_id)

    if not current_classes:
        add_student_to_class_record(conn, target_class_id, student_id)
        return DIRECT_ASSIGNED

    current_class = current_classes[0]
    if current_class.class_id == target_class_id:
        return ALREADY_IN_CLASS

    if current_class.teacher_id == requesting_teacher_id:
        remove_student_from_class_record(conn, current_class.class_id, student_id)
        add_student_to_class_record(conn, target_class_id, student_id)
        return MOVED_WITHIN_OWN_CLASSES

    if get_pending_request_for_student_and_target(conn, student_id, target_class_id) is not None:
        raise ValueError("A pending transfer request for this student and class already exists.")

    create_request(
        conn,
        student_id=student_id,
        source_class_id=current_class.class_id,
        target_class_id=target_class_id,
        requesting_teacher_id=requesting_teacher_id,
        current_teacher_id=current_class.teacher_id,
    )
    return TRANSFER_REQUEST_CREATED


def _authorize_responder(request: StudentTransferRequest, responder: User) -> None:
    if responder.role == ADMIN_ROLE:
        return
    if responder.role == TEACHER_ROLE and responder.user_id == request.current_teacher_id:
        return
    raise ValueError("You are not authorized to respond to this request.")


def approve_student_transfer_request(conn: sqlite3.Connection, request_id: int, responder: User) -> None:
    """Approve a pending student transfer request, moving the student from
    the source class to the target class. The student remains in exactly
    one class.

    Raises ValueError if the request does not exist, is no longer pending,
    or the responder is not authorized (must be Admin or the student's
    current teacher in charge).
    """
    request = get_request_by_id(conn, request_id)
    if request is None:
        raise ValueError("Transfer request not found.")

    _authorize_responder(request, responder)

    if request.status != STATUS_PENDING:
        raise ValueError("This request is no longer pending.")

    remove_student_from_class_record(conn, request.source_class_id, request.student_id)
    add_student_to_class_record(conn, request.target_class_id, request.student_id)
    update_request_status(conn, request_id, STATUS_APPROVED, responder.user_id)
    cancel_other_pending_requests_for_student(
        conn, request.student_id, exclude_request_id=request_id, responded_by_user_id=responder.user_id
    )


def reject_student_transfer_request(
    conn: sqlite3.Connection,
    request_id: int,
    responder: User,
    reason: Optional[str] = None,
) -> None:
    """Reject a pending student transfer request. No class assignment changes.

    Raises ValueError if the request does not exist, is no longer pending,
    or the responder is not authorized.
    """
    request = get_request_by_id(conn, request_id)
    if request is None:
        raise ValueError("Transfer request not found.")

    _authorize_responder(request, responder)

    if request.status != STATUS_PENDING:
        raise ValueError("This request is no longer pending.")

    clean_reason = (reason or "").strip() or None
    update_request_status(conn, request_id, STATUS_REJECTED, responder.user_id, response_reason=clean_reason)


def list_all_pending_student_transfer_requests(conn: sqlite3.Connection) -> List[StudentTransferRequestWithDetails]:
    """Return all pending student transfer requests in the system (Admin view)."""
    return get_all_pending_requests_with_details(conn)


def list_pending_student_transfer_requests_for_teacher(
    conn: sqlite3.Connection, current_teacher_id: int
) -> List[StudentTransferRequestWithDetails]:
    """Return pending student transfer requests for students currently in
    classes owned by current_teacher_id (i.e. requests awaiting their decision)."""
    return get_pending_requests_for_current_teacher_with_details(conn, current_teacher_id)


def count_all_pending_student_transfer_requests(conn: sqlite3.Connection) -> int:
    """Return the total number of pending student transfer requests (Admin view)."""
    return count_pending_requests_record(conn)


def count_pending_student_transfer_requests_for_teacher(conn: sqlite3.Connection, current_teacher_id: int) -> int:
    """Return the number of incoming pending student transfer requests for a teacher's own classes."""
    return count_pending_requests_for_current_teacher_record(conn, current_teacher_id)


def list_all_decided_student_transfer_requests(conn: sqlite3.Connection) -> List[StudentTransferRequestWithDetails]:
    """Return every approved/rejected student transfer request (Admin history view).
    Requests are never deleted after a decision, only their status changes."""
    return get_all_decided_requests_with_details(conn)


def list_decided_student_transfer_requests_for_teacher(
    conn: sqlite3.Connection, teacher_id: int
) -> List[StudentTransferRequestWithDetails]:
    """Return approved/rejected requests teacher_id was involved in, either
    as the requester or as the one who decided the request."""
    return get_decided_requests_for_teacher_with_details(conn, teacher_id)
