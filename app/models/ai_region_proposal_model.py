"""Stage 12G-4 - persistence for Core AI 2 answer-region PROPOSALS.

A proposal is a teacher-reviewed suggestion, never an automatic region/mapping.
Both source (model) and final (teacher) geometry are preserved. Only geometry/
class metadata is stored - never raw essays, prompts or OCR text.

Named outside the Codex `core_ai2_*` namespace on purpose.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

WORKFLOW_SUBJECT_PROFILE = "subject_profile"
WORKFLOW_SEPARATE_ANSWER_PAPER = "separate_answer_paper"

STATUS_PROPOSED = "proposed"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_EDITED = "edited"
STATUS_DEFERRED = "deferred"
ALL_STATUSES = (STATUS_PROPOSED, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_EDITED, STATUS_DEFERRED)
# An "active" proposal is one still awaiting or holding a teacher decision that
# maps to a live artifact (proposed/edited/accepted); rejected/deferred are not.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RegionProposalRecord:
    proposal_id: str
    workflow_context: str
    profile_id: Optional[int]
    answer_file_id: Optional[int]
    source: Optional[str]
    page_number: Optional[int]
    sap_page_id: Optional[int]
    model_family: str
    model_version: Optional[str]
    model_checksum: Optional[str]
    input_page_checksum: Optional[str]
    proposed_class: Optional[str]
    proposed_target_label: Optional[str]
    confidence: Optional[float]
    rationale: Optional[str]
    source_x: Optional[float]
    source_y: Optional[float]
    source_width: Optional[float]
    source_height: Optional[float]
    final_x: Optional[float]
    final_y: Optional[float]
    final_width: Optional[float]
    final_height: Optional[float]
    status: str
    decision_reason: Optional[str]
    accepted_region_id: Optional[int]
    accepted_mapping_id: Optional[int]
    actor_user_id: Optional[int]
    created_at: str
    updated_at: Optional[str]

    @property
    def effective_geometry(self):
        """(x, y, w, h) - the teacher's final geometry when set, else the
        model's source geometry."""
        if self.final_x is not None:
            return (self.final_x, self.final_y, self.final_width, self.final_height)
        return (self.source_x, self.source_y, self.source_width, self.source_height)


_COLUMNS = (
    "proposal_id, workflow_context, profile_id, answer_file_id, source, page_number, sap_page_id, "
    "model_family, model_version, model_checksum, input_page_checksum, proposed_class, "
    "proposed_target_label, confidence, rationale, source_x, source_y, source_width, source_height, "
    "final_x, final_y, final_width, final_height, status, decision_reason, accepted_region_id, "
    "accepted_mapping_id, actor_user_id, created_at, updated_at"
)


def _row(row) -> RegionProposalRecord:
    return RegionProposalRecord(**dict(row))


def create_proposal(
    conn: sqlite3.Connection, *, proposal_id: str, workflow_context: str, model_family: str,
    profile_id: Optional[int] = None, answer_file_id: Optional[int] = None, source: Optional[str] = None,
    page_number: Optional[int] = None, sap_page_id: Optional[int] = None,
    model_version: Optional[str] = None, model_checksum: Optional[str] = None,
    input_page_checksum: Optional[str] = None, proposed_class: Optional[str] = None,
    proposed_target_label: Optional[str] = None, confidence: Optional[float] = None,
    rationale: Optional[str] = None, source_geometry=(None, None, None, None),
    actor_user_id: Optional[int] = None,
) -> RegionProposalRecord:
    now = _now()
    sx, sy, sw, sh = source_geometry
    conn.execute(
        f"INSERT INTO core_ai2_region_proposals ({_COLUMNS}) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (proposal_id, workflow_context, profile_id, answer_file_id, source, page_number, sap_page_id,
         model_family, model_version, model_checksum, input_page_checksum, proposed_class,
         proposed_target_label, confidence, rationale, sx, sy, sw, sh,
         None, None, None, None, STATUS_PROPOSED, None, None, None, actor_user_id, now, now),
    )
    conn.commit()
    return get_proposal(conn, proposal_id)


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> Optional[RegionProposalRecord]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM core_ai2_region_proposals WHERE proposal_id = ?", (proposal_id,),
    ).fetchone()
    return _row(row) if row is not None else None


def list_proposals_for_profile(conn, profile_id: int, status: Optional[str] = None,
                               source: Optional[str] = None) -> List[RegionProposalRecord]:
    clauses = ["profile_id = ?"]
    params = [profile_id]
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM core_ai2_region_proposals WHERE {' AND '.join(clauses)} "
        "ORDER BY page_number, created_at, proposal_id", params,
    ).fetchall()
    return [_row(r) for r in rows]


def list_proposals_for_attempt(conn, answer_file_id: int,
                               status: Optional[str] = None) -> List[RegionProposalRecord]:
    clauses = ["answer_file_id = ?"]
    params = [answer_file_id]
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM core_ai2_region_proposals WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at, proposal_id", params,
    ).fetchall()
    return [_row(r) for r in rows]


def set_status(conn, proposal_id: str, status: str, *, decision_reason: Optional[str] = None,
               accepted_region_id: Optional[int] = None, accepted_mapping_id: Optional[int] = None) -> None:
    conn.execute(
        "UPDATE core_ai2_region_proposals SET status = ?, decision_reason = COALESCE(?, decision_reason), "
        "accepted_region_id = COALESCE(?, accepted_region_id), "
        "accepted_mapping_id = COALESCE(?, accepted_mapping_id), updated_at = ? WHERE proposal_id = ?",
        (status, decision_reason, accepted_region_id, accepted_mapping_id, _now(), proposal_id),
    )
    conn.commit()


def set_final_geometry(conn, proposal_id: str, x: float, y: float, width: float, height: float) -> None:
    """Record the teacher's edited geometry; the source geometry is preserved."""
    conn.execute(
        "UPDATE core_ai2_region_proposals SET final_x = ?, final_y = ?, final_width = ?, final_height = ?, "
        "status = CASE WHEN status = 'proposed' THEN 'edited' ELSE status END, updated_at = ? "
        "WHERE proposal_id = ?",
        (x, y, width, height, _now(), proposal_id),
    )
    conn.commit()


def delete_proposals_for_profile(conn, profile_id: int) -> None:
    conn.execute("DELETE FROM core_ai2_region_proposals WHERE profile_id = ?", (profile_id,))
    conn.commit()
