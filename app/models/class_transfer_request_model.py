"""Class transfer/join request data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"


@dataclass
class TransferRequest:
    request_id: int
    class_id: int
    requesting_teacher_id: int
    current_teacher_id: int
    status: str
    request_reason: Optional[str]
    response_reason: Optional[str]
    responded_by_user_id: Optional[int]
    created_at: str
    responded_at: Optional[str]


@dataclass
class TransferRequestWithDetails:
    request_id: int
    class_id: int
    class_name: str
    requesting_teacher_id: int
    requesting_teacher_name: str
    current_teacher_id: int
    current_teacher_name: str
    status: str
    request_reason: Optional[str]
    response_reason: Optional[str]
    created_at: str
    responded_at: Optional[str]


_SELECT_COLUMNS = (
    "request_id, class_id, requesting_teacher_id, current_teacher_id, status, "
    "request_reason, response_reason, responded_by_user_id, created_at, responded_at"
)


def create_request(
    conn: sqlite3.Connection,
    class_id: int,
    requesting_teacher_id: int,
    current_teacher_id: int,
    request_reason: Optional[str],
) -> TransferRequest:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO class_transfer_requests "
        "(class_id, requesting_teacher_id, current_teacher_id, status, request_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (class_id, requesting_teacher_id, current_teacher_id, STATUS_PENDING, request_reason, created_at),
    )
    conn.commit()
    return TransferRequest(
        request_id=cursor.lastrowid,
        class_id=class_id,
        requesting_teacher_id=requesting_teacher_id,
        current_teacher_id=current_teacher_id,
        status=STATUS_PENDING,
        request_reason=request_reason,
        response_reason=None,
        responded_by_user_id=None,
        created_at=created_at,
        responded_at=None,
    )


def get_request_by_id(conn: sqlite3.Connection, request_id: int) -> Optional[TransferRequest]:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM class_transfer_requests WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    return TransferRequest(**dict(row))


def get_pending_request_for_class_and_teacher(
    conn: sqlite3.Connection, class_id: int, requesting_teacher_id: int
) -> Optional[TransferRequest]:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM class_transfer_requests "
        "WHERE class_id = ? AND requesting_teacher_id = ? AND status = ?",
        (class_id, requesting_teacher_id, STATUS_PENDING),
    ).fetchone()
    if row is None:
        return None
    return TransferRequest(**dict(row))


def get_pending_requests_by_requesting_teacher(
    conn: sqlite3.Connection, requesting_teacher_id: int
) -> List[TransferRequest]:
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM class_transfer_requests "
        "WHERE requesting_teacher_id = ? AND status = ?",
        (requesting_teacher_id, STATUS_PENDING),
    ).fetchall()
    return [TransferRequest(**dict(row)) for row in rows]


_DETAILS_QUERY = """
    SELECT r.request_id, r.class_id, c.class_name,
           r.requesting_teacher_id, ru.full_name AS requesting_teacher_name,
           r.current_teacher_id, cu.full_name AS current_teacher_name,
           r.status, r.request_reason, r.response_reason, r.created_at, r.responded_at
    FROM class_transfer_requests r
    JOIN classes c ON c.class_id = r.class_id
    JOIN users ru ON ru.user_id = r.requesting_teacher_id
    JOIN users cu ON cu.user_id = r.current_teacher_id
"""


def get_all_pending_requests_with_details(conn: sqlite3.Connection) -> List[TransferRequestWithDetails]:
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status = ? ORDER BY r.created_at",
        (STATUS_PENDING,),
    ).fetchall()
    return [TransferRequestWithDetails(**dict(row)) for row in rows]


def get_pending_requests_for_current_teacher_with_details(
    conn: sqlite3.Connection, current_teacher_id: int
) -> List[TransferRequestWithDetails]:
    rows = conn.execute(
        f"{_DETAILS_QUERY} WHERE r.status = ? AND r.current_teacher_id = ? ORDER BY r.created_at",
        (STATUS_PENDING, current_teacher_id),
    ).fetchall()
    return [TransferRequestWithDetails(**dict(row)) for row in rows]


def count_pending_requests(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM class_transfer_requests WHERE status = ?", (STATUS_PENDING,)
    ).fetchone()
    return row[0]


def count_pending_requests_for_current_teacher(conn: sqlite3.Connection, current_teacher_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM class_transfer_requests WHERE status = ? AND current_teacher_id = ?",
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
        "UPDATE class_transfer_requests "
        "SET status = ?, response_reason = ?, responded_by_user_id = ?, responded_at = ? "
        "WHERE request_id = ?",
        (status, response_reason, responded_by_user_id, responded_at, request_id),
    )
    conn.commit()


def cancel_other_pending_requests_for_class(
    conn: sqlite3.Connection, class_id: int, exclude_request_id: int, responded_by_user_id: int
) -> None:
    responded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE class_transfer_requests "
        "SET status = ?, responded_by_user_id = ?, responded_at = ? "
        "WHERE class_id = ? AND status = ? AND request_id != ?",
        (STATUS_CANCELLED, responded_by_user_id, responded_at, class_id, STATUS_PENDING, exclude_request_id),
    )
    conn.commit()
