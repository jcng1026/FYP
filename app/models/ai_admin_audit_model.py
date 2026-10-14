"""Stage 12G-2 - persistence for the global AI-admin audit trail.

Records sanitized entries for AI Models registry access/denials, dataset
freeze/conversion, model activation/rollback, Core AI proposal accept/reject
and Local-AI fallback. Notes must always be sanitized JSON - never full
student essays, prompts, raw OCR or secrets (that sanitization is the caller's
responsibility; this layer only persists what it is given).
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

OUTCOME_OK = "ok"
OUTCOME_DENIED = "denied"
OUTCOME_FAILED = "failed"
ALL_OUTCOMES = (OUTCOME_OK, OUTCOME_DENIED, OUTCOME_FAILED)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AIAdminAuditEntry:
    audit_id: int
    actor_user_id: Optional[int]
    actor_role: Optional[str]
    action: str
    target: Optional[str]
    outcome: str
    note: Optional[str]
    created_at: str


_COLUMNS = (
    "audit_id, actor_user_id, actor_role, action, target, outcome, note, created_at"
)


def _row_to_entry(row) -> AIAdminAuditEntry:
    return AIAdminAuditEntry(**dict(row))


def record_ai_admin_action(
    conn: sqlite3.Connection,
    *,
    actor_user_id: Optional[int],
    actor_role: Optional[str],
    action: str,
    outcome: str = OUTCOME_OK,
    target: Optional[str] = None,
    note: Optional[str] = None,
) -> AIAdminAuditEntry:
    """Append one sanitized AI-admin audit entry. `note` should already be
    sanitized JSON (ids/flags/counts only)."""
    if outcome not in ALL_OUTCOMES:
        raise ValueError(f"outcome must be one of {ALL_OUTCOMES}")
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ai_admin_audit (actor_user_id, actor_role, action, target, outcome, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (actor_user_id, actor_role, action, target, outcome, note, now),
    )
    conn.commit()
    return AIAdminAuditEntry(
        audit_id=cursor.lastrowid, actor_user_id=actor_user_id, actor_role=actor_role,
        action=action, target=target, outcome=outcome, note=note, created_at=now,
    )


def list_ai_admin_audit(
    conn: sqlite3.Connection, *, action: Optional[str] = None, outcome: Optional[str] = None,
    limit: int = 100,
) -> List[AIAdminAuditEntry]:
    clauses, params = [], []
    if action is not None:
        clauses.append("action = ?")
        params.append(action)
    if outcome is not None:
        clauses.append("outcome = ?")
        params.append(outcome)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM ai_admin_audit{where} ORDER BY audit_id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_entry(r) for r in rows]
