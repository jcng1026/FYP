"""Class transfer/join request logic for the Teacher and Admin roles."""

import sqlite3
from typing import List, Optional

from app.models.class_transfer_request_model import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    TransferRequest,
    TransferRequestWithDetails,
    cancel_other_pending_requests_for_class,
    count_pending_requests as count_pending_requests_record,
    count_pending_requests_for_current_teacher as count_pending_requests_for_current_teacher_record,
    create_request,
    get_all_pending_requests_with_details,
    get_pending_request_for_class_and_teacher,
    get_pending_requests_by_requesting_teacher,
    get_pending_requests_for_current_teacher_with_details,
    get_request_by_id,
    update_request_status,
)
from app.models.user_model import User
from app.services.class_service import get_class_by_id, update_class_teacher
from app.services.user_service import ADMIN_ROLE, TEACHER_ROLE, validate_teacher_exists


def create_transfer_request(
    conn: sqlite3.Connection,
    requesting_teacher_id: int,
    class_id: int,
    request_reason: Optional[str] = None,
) -> TransferRequest:
    """Create a pending transfer request for a class occupied by another teacher.

    Raises ValueError if the requesting user is not a teacher, the class does
    not exist, the class is unassigned (use join_unassigned_class instead),
    the class already belongs to the requesting teacher, or a pending
    request from this teacher for this class already exists.
    """
    if not validate_teacher_exists(conn, requesting_teacher_id):
        raise ValueError("Only teacher accounts can request a class transfer.")

    class_ = get_class_by_id(conn, class_id)
    if class_ is None:
        raise ValueError("Class not found.")

    if class_.teacher_id is None:
        raise ValueError("This class is unassigned. Use Join instead of requesting a transfer.")

    if class_.teacher_id == requesting_teacher_id:
        raise ValueError("You cannot request a transfer for a class you already own.")

    if get_pending_request_for_class_and_teacher(conn, class_id, requesting_teacher_id) is not None:
        raise ValueError("You already have a pending request for this class.")

    reason = (request_reason or "").strip() or None
    return create_request(conn, class_id, requesting_teacher_id, class_.teacher_id, reason)


def _authorize_responder(request: TransferRequest, responder: User) -> None:
    if responder.role == ADMIN_ROLE:
        return
    if responder.role == TEACHER_ROLE and responder.user_id == request.current_teacher_id:
        return
    raise ValueError("You are not authorized to respond to this request.")


def approve_transfer_request(conn: sqlite3.Connection, request_id: int, responder: User) -> None:
    """Approve a pending transfer request, transferring class ownership.

    Raises ValueError if the request does not exist, is no longer pending, or
    the responder is not authorized (must be Admin or the class's current
    teacher in charge).
    """
    request = get_request_by_id(conn, request_id)
    if request is None:
        raise ValueError("Transfer request not found.")

    _authorize_responder(request, responder)

    if request.status != STATUS_PENDING:
        raise ValueError("This request is no longer pending.")

    update_class_teacher(conn, request.class_id, request.requesting_teacher_id)
    update_request_status(conn, request_id, STATUS_APPROVED, responder.user_id)
    cancel_other_pending_requests_for_class(
        conn, request.class_id, exclude_request_id=request_id, responded_by_user_id=responder.user_id
    )


def reject_transfer_request(
    conn: sqlite3.Connection,
    request_id: int,
    responder: User,
    reason: Optional[str] = None,
) -> None:
    """Reject a pending transfer request.

    Raises ValueError if the request does not exist, is no longer pending, or
    the responder is not authorized.
    """
    request = get_request_by_id(conn, request_id)
    if request is None:
        raise ValueError("Transfer request not found.")

    _authorize_responder(request, responder)

    if request.status != STATUS_PENDING:
        raise ValueError("This request is no longer pending.")

    clean_reason = (reason or "").strip() or None
    update_request_status(conn, request_id, STATUS_REJECTED, responder.user_id, response_reason=clean_reason)


def list_all_pending_requests(conn: sqlite3.Connection) -> List[TransferRequestWithDetails]:
    """Return all pending transfer requests in the system (Admin view)."""
    return get_all_pending_requests_with_details(conn)


def list_pending_requests_for_teacher(
    conn: sqlite3.Connection, current_teacher_id: int
) -> List[TransferRequestWithDetails]:
    """Return pending transfer requests for classes owned by current_teacher_id."""
    return get_pending_requests_for_current_teacher_with_details(conn, current_teacher_id)


def count_pending_requests(conn: sqlite3.Connection) -> int:
    """Return the total number of pending transfer requests (Admin view)."""
    return count_pending_requests_record(conn)


def count_pending_requests_for_teacher(conn: sqlite3.Connection, current_teacher_id: int) -> int:
    """Return the number of incoming pending transfer requests for a teacher's own classes."""
    return count_pending_requests_for_current_teacher_record(conn, current_teacher_id)


def has_pending_request(conn: sqlite3.Connection, class_id: int, requesting_teacher_id: int) -> bool:
    """Return True if requesting_teacher_id already has a pending request for class_id."""
    return get_pending_request_for_class_and_teacher(conn, class_id, requesting_teacher_id) is not None


def list_my_pending_requests(conn: sqlite3.Connection, requesting_teacher_id: int) -> List[TransferRequest]:
    """Return all pending requests this teacher has submitted (for button-state lookups)."""
    return get_pending_requests_by_requesting_teacher(conn, requesting_teacher_id)
