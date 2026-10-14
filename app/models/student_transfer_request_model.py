"""Student transfer request data model and database access functions.

Distinct from class_transfer_request_model.py, which handles a teacher
requesting ownership of an entire class from another teacher. This model
handles moving a single student between classes/teachers when the student
is already assigned to a class (Stage 10E).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"


@dataclass
class StudentTransferRequest:
    request_id: int
    student_id: int
    source_class_id: int
    target_class_id: int
    requesting_teacher_id: int
    current_teacher_id: int
    status: str
    request_reason: Optional[str]
    response_reason: Optional[str]
    responded_by_user_id: Optional[int]
    created_at: str
    responded_at: Optional[str]


@dataclass
class StudentTransferRequestWithDetails:
    request_id: int
    student_id: int
    student_code: Optional[str]
    student_username: str
    student_full_name: str
    source_class_id: int
    source_class_name: str
    target_class_id: int
    target_class_name: str
    requesting_teacher_id: int
    requesting_teacher_name: str
    current_teacher_id: int
    current_teacher_name: str
    status: str
    request_reason: Optional[str]
    response_reason: Optional[str]
    created_at: str
    responded_at: Optional[str]
    decided_by_name: Optional[str] = None


_SELECT_COLUMNS = (
    "request_id, student_id, source_class_id, target_class_id, requesting_teacher_id, "
    "current_teacher_id, status, request_reason, response_reason, responded_by_user_id, "
    "created_at, responded_at"
)


def create_request(
    conn: sqlite3.Connection,
    student_id: int,
    source_class_id: int,
    target_class_id: int,
    requesting_teacher_id: int,
    current_teacher_id: int,
    request_reason: Optional[str] = None,
) -> StudentTransferRequest:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO student_transfer_requests "
        "(student_id, source_class_id, target_class_id, requesting_teacher_id, current_teacher_id, "
        "status, request_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            student_id,
            source_class_id,
            target_class_id,
            requesting_teacher_id,
            current_teacher_id,
            STATUS_PENDING,
            request_reason,
            created_at,
        ),
    )
    conn.commit()
    return StudentTransferRequest(
        request_id=cursor.lastrowid,
        student_id=student_id,
        source_class_id=source_class_id,
        target_class_id=target_class_id,
        requesting_teacher_id=requesting_teacher_id,
        current_teacher_id=current_teacher_id,
        status=STATUS_PENDING,
        request_reason=request_reason,
        response_reason=None,
        responded_by_user_id=None,
        created_at=created_at,
        responded_at=None,
    )


def get_request_by_id(conn: sqlite3.Connection, request_id: int) -> Optional[StudentTransferRequest]:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM student_transfer_requests WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    return StudentTransferRequest(**dict(row))


def get_pending_request_for_student_and_target(
    conn: sqlite3.Connection, student_id: int, target_class_id: int
) -> Optional[StudentTransferRequest]:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM student_transfer_requests "
        "WHERE student_id = ? AND target_class_id = ? AND status = ?",
        (student_id, target_class_id, STATUS_PENDING),
    ).fetchone()
    if row is None:
        return None
    return StudentTransferRequest(**dict(row))


_DETAILS_QUERY = """
    SELECT r.request_id, r.student_id, su.student_code, su.username AS student_username,
           su.full_name AS student_full_name,
           r.source_class_id, sc.class_name AS source_class_name,
           r.target_class_id, tc.class_name AS target_class_name,
           r.requesting_teacher_id, ru.full_name AS requesting_teacher_name,
           r.current_teacher_id, cu.full_name AS current_teacher_name,
           r.status, r.request_reason, r.response_reason, r.created_at, r.responded_at,
           du.full_name AS decided_by_name
    FROM student_transfer_requests r
    JOIN users su ON su.user_id = r.student_id
    JOIN classes sc ON sc.class_id = r.source_class_id
    JOIN classes tc ON tc.class_id = r.target_class_id
    JOIN users ru ON ru.user_id = r.requesting_teacher_id
    JOIN users cu ON cu.user_id = r.current_teacher_id
    LEFT JOIN users du ON du.user_id = r.responded_by_user_id
"""


def get_all_pending_requests_with_details(conn: sqlite3.Connection) -> List[StudentTransferRequestWithDetails]:
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status = ? ORDER BY r.created_at",
        (STATUS_PENDING,),
    ).fetchall()
    return [StudentTransferRequestWithDetails(**dict(row)) for row in rows]


def get_pending_requests_for_current_teacher_with_details(
    conn: sqlite3.Connection, current_teacher_id: int
) -> List[StudentTransferRequestWithDetails]:
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status = ? AND r.current_teacher_id = ? ORDER BY r.created_at",
        (STATUS_PENDING, current_teacher_id),
    ).fetchall()
    return [StudentTransferRequestWithDetails(**dict(row)) for row in rows]


def get_all_decided_requests_with_details(conn: sqlite3.Connection) -> List[StudentTransferRequestWithDetails]:
    """Return every approved/rejected request in the system (Admin history view).

    Decided requests are never deleted - only their status changes - so
    this always reflects the full approve/reject history.
    """
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status IN (?, ?) ORDER BY r.responded_at DESC",
        (STATUS_APPROVED, STATUS_REJECTED),
    ).fetchall()
    return [StudentTransferRequestWithDetails(**dict(row)) for row in rows]


def get_decided_requests_for_teacher_with_details(
    conn: sqlite3.Connection, teacher_id: int
) -> List[StudentTransferRequestWithDetails]:
    """Return approved/rejected requests this teacher was involved in,
    either as the one who asked for the student (requesting_teacher_id) or
    the one who owned the student's class and decided the request
    (current_teacher_id)."""
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status IN (?, ?) AND (r.requesting_teacher_id = ? OR r.current_teacher_id = ?) "
        "ORDER BY r.responded_at DESC",
        (STATUS_APPROVED, STATUS_REJECTED, teacher_id, teacher_id),
    ).fetchall()
    return [StudentTransferRequestWithDetails(**dict(row)) for row in rows]


def count_pending_requests(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM student_transfer_requests WHERE status = ?", (STATUS_PENDING,)
    ).fetchone()
    return row[0]


def count_pending_requests_for_current_teacher(conn: sqlite3.Connection, current_teacher_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM student_transfer_requests WHERE status = ? AND current_teacher_id = ?",
        (STATUS_PENDING, current_teacher_id),
    ).fetchone()
    return row[0]


def update_request_status(
    conn: sqlite3.Connection,
    request_id: int,
    status: str,
    responded_by_user_id: int,
    response_reason: Optional[str] = None,
) -> None:
    responded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE student_transfer_requests "
        "SET status = ?, response_reason = ?, responded_by_user_id = ?, responded_at = ? "
        "WHERE request_id = ?",
        (status, response_reason, responded_by_user_id, responded_at, request_id),
    )
    conn.commit()


def cancel_other_pending_requests_for_student(
    conn: sqlite3.Connection, student_id: int, exclude_request_id: int, responded_by_user_id: int
) -> None:
    """Cancel every other pending request for this student (any target
    class) once one of them has been approved, so a student can't end up
    the subject of two competing approvals."""
    responded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE student_transfer_requests "
        "SET status = ?, responded_by_user_id = ?, responded_at = ? "
        "WHERE student_id = ? AND status = ? AND request_id != ?",
        (STATUS_CANCELLED, responded_by_user_id, responded_at, student_id, STATUS_PENDING, exclude_request_id),
    )
    conn.commit()
