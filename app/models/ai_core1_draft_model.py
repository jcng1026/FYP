"""Stage 12G-6 - persistence for Core AI 1 Kertas 2 draft scores.

A draft is an AI SUGGESTION attached to one marked answer. It is never a final
score: the teacher's own score/feedback live on the marked answer and are never
written here, and nothing in this module writes back to them. A draft carries
the input checksum and model version it was produced from so the review
workspace can mark it STALE when the answer or the active model changes.
"""
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

STATUS_COMPLETED = "completed"
STATUS_SKIPPED = "skipped"
STATUS_ATTENTION_REQUIRED = "attention_required"
STATUS_FAILED = "failed"

_COLUMNS = (
    "draft_id, marked_answer_id, answer_file_id, profile_id, status, draft_score, draft_raw_score, "
    "normalized_score, draft_feedback_category, category_confidence, score_confidence, "
    "rounding_policy_version, model_version, model_checksum, dataset_lineage, "
    "input_template_version, input_checksum, truncation_warning, missing_scheme_warning, clamped, "
    "warnings, failure_code, device, runtime_duration_seconds, generated_by_user_id, generated_at, "
    "applied_at, dismissed_at, stale_reason, stale_marked_at"
)

STALE_REASON_INPUT_CHANGED = "input_changed"
STALE_REASON_MODEL_CHANGED = "model_changed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CoreAI1DraftRecord:
    draft_id: str
    marked_answer_id: int
    answer_file_id: int
    profile_id: Optional[int]
    status: str
    draft_score: Optional[float]
    draft_raw_score: Optional[float]
    normalized_score: Optional[float]
    draft_feedback_category: Optional[str]
    category_confidence: Optional[float]
    score_confidence: Optional[float]
    rounding_policy_version: Optional[str]
    model_version: Optional[str]
    model_checksum: Optional[str]
    dataset_lineage: Optional[str]
    input_template_version: Optional[str]
    input_checksum: str
    truncation_warning: bool
    missing_scheme_warning: bool
    clamped: bool
    warnings: List[str]
    failure_code: Optional[str]
    device: Optional[str]
    runtime_duration_seconds: Optional[float]
    generated_by_user_id: Optional[int]
    generated_at: str
    applied_at: Optional[str]
    dismissed_at: Optional[str]
    stale_reason: Optional[str] = None
    stale_marked_at: Optional[str] = None

    def is_stale(self, current_input_checksum: str,
                 active_model_version: Optional[str] = None) -> bool:
        """A draft is stale when anything it was computed from has changed: the
        answer text, mapping, Part 3 selection, marking scheme or question
        content (all folded into the input checksum), or the active Core AI 1
        model. A staleness marker persisted at activation/rollback counts too."""
        if self.stale_reason:
            return True
        if self.input_checksum != current_input_checksum:
            return True
        return bool(active_model_version and self.model_version
                    and self.model_version != active_model_version)

    def stale_explanation(self, current_input_checksum: str) -> Optional[str]:
        if self.input_checksum != current_input_checksum:
            return "the answer or its marking inputs changed since this draft"
        if self.stale_reason == STALE_REASON_MODEL_CHANGED:
            return "a different Core AI 1 model is now active"
        if self.stale_reason:
            return self.stale_reason
        return None


def _row_to_record(row) -> CoreAI1DraftRecord:
    data = dict(row)
    return CoreAI1DraftRecord(
        draft_id=data["draft_id"], marked_answer_id=data["marked_answer_id"],
        answer_file_id=data["answer_file_id"], profile_id=data["profile_id"],
        status=data["status"], draft_score=data["draft_score"],
        draft_raw_score=data["draft_raw_score"], normalized_score=data["normalized_score"],
        draft_feedback_category=data["draft_feedback_category"],
        category_confidence=data["category_confidence"], score_confidence=data["score_confidence"],
        rounding_policy_version=data["rounding_policy_version"],
        model_version=data["model_version"], model_checksum=data["model_checksum"],
        dataset_lineage=data["dataset_lineage"],
        input_template_version=data["input_template_version"],
        input_checksum=data["input_checksum"],
        truncation_warning=bool(data["truncation_warning"]),
        missing_scheme_warning=bool(data["missing_scheme_warning"]),
        clamped=bool(data["clamped"]),
        warnings=json.loads(data["warnings"]) if data["warnings"] else [],
        failure_code=data["failure_code"], device=data["device"],
        runtime_duration_seconds=data["runtime_duration_seconds"],
        generated_by_user_id=data["generated_by_user_id"], generated_at=data["generated_at"],
        applied_at=data["applied_at"], dismissed_at=data["dismissed_at"],
        stale_reason=data["stale_reason"], stale_marked_at=data["stale_marked_at"])


def upsert_draft(conn, *, marked_answer_id: int, answer_file_id: int, profile_id: Optional[int],
                 status: str, input_checksum: str, generated_by_user_id: Optional[int] = None,
                 draft_score: Optional[float] = None, draft_raw_score: Optional[float] = None,
                 normalized_score: Optional[float] = None,
                 draft_feedback_category: Optional[str] = None,
                 category_confidence: Optional[float] = None,
                 score_confidence: Optional[float] = None,
                 rounding_policy_version: Optional[str] = None,
                 model_version: Optional[str] = None, model_checksum: Optional[str] = None,
                 dataset_lineage: Optional[str] = None,
                 input_template_version: Optional[str] = None,
                 truncation_warning: bool = False, missing_scheme_warning: bool = False,
                 clamped: bool = False, warnings: Optional[List[str]] = None,
                 failure_code: Optional[str] = None, device: Optional[str] = None,
                 runtime_duration_seconds: Optional[float] = None) -> CoreAI1DraftRecord:
    """Store (or regenerate) the single draft for a marked answer. Regenerating
    replaces the previous draft and clears any applied/dismissed marker, because
    it is a new suggestion for the teacher to consider."""
    existing = get_draft_for_marked_answer(conn, marked_answer_id)
    if existing is not None:
        # Preserve the superseded draft for lineage before replacing it.
        archive_draft(conn, existing, reason="regenerated")
    draft_id = existing.draft_id if existing else uuid.uuid4().hex
    values = (
        draft_id, marked_answer_id, answer_file_id, profile_id, status, draft_score,
        draft_raw_score, normalized_score, draft_feedback_category, category_confidence,
        score_confidence, rounding_policy_version, model_version, model_checksum, dataset_lineage,
        input_template_version, input_checksum, int(bool(truncation_warning)),
        int(bool(missing_scheme_warning)), int(bool(clamped)),
        json.dumps(warnings or []), failure_code, device, runtime_duration_seconds,
        generated_by_user_id, _now(), None, None, None, None,
    )
    conn.execute(
        f"INSERT OR REPLACE INTO core_ai1_answer_drafts ({_COLUMNS}) "
        f"VALUES ({', '.join('?' * len(values))})", values)
    conn.commit()
    return get_draft_for_marked_answer(conn, marked_answer_id)


def get_draft_for_marked_answer(conn, marked_answer_id: int) -> Optional[CoreAI1DraftRecord]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM core_ai1_answer_drafts WHERE marked_answer_id = ?",
        (marked_answer_id,)).fetchone()
    return _row_to_record(row) if row else None


def list_drafts_for_answer_file(conn, answer_file_id: int) -> List[CoreAI1DraftRecord]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM core_ai1_answer_drafts WHERE answer_file_id = ? "
        "ORDER BY marked_answer_id", (answer_file_id,)).fetchall()
    return [_row_to_record(r) for r in rows]


def drafts_by_marked_answer(conn, answer_file_id: int) -> Dict[int, CoreAI1DraftRecord]:
    return {d.marked_answer_id: d for d in list_drafts_for_answer_file(conn, answer_file_id)}


def mark_draft_applied(conn, marked_answer_id: int) -> Optional[CoreAI1DraftRecord]:
    """Record that the teacher copied the suggestion into their own entry. The
    teacher's score itself is written by the review service, not here."""
    conn.execute("UPDATE core_ai1_answer_drafts SET applied_at = ?, dismissed_at = NULL "
                 "WHERE marked_answer_id = ?", (_now(), marked_answer_id))
    conn.commit()
    return get_draft_for_marked_answer(conn, marked_answer_id)


def mark_draft_dismissed(conn, marked_answer_id: int) -> Optional[CoreAI1DraftRecord]:
    conn.execute("UPDATE core_ai1_answer_drafts SET dismissed_at = ?, applied_at = NULL "
                 "WHERE marked_answer_id = ?", (_now(), marked_answer_id))
    conn.commit()
    return get_draft_for_marked_answer(conn, marked_answer_id)


def delete_drafts_for_answer_file(conn, answer_file_id: int) -> int:
    cursor = conn.execute("DELETE FROM core_ai1_answer_drafts WHERE answer_file_id = ?",
                          (answer_file_id,))
    conn.commit()
    return cursor.rowcount


# --- lineage + persisted staleness -------------------------------------------

def archive_draft(conn, record: CoreAI1DraftRecord, reason: str) -> None:
    """Keep a superseded draft. A regenerated draft never erases what the model
    previously suggested, or whether the teacher had applied it."""
    conn.execute(
        "INSERT INTO core_ai1_draft_history (draft_id, marked_answer_id, answer_file_id, status, "
        "draft_score, draft_feedback_category, model_version, model_checksum, dataset_lineage, "
        "input_checksum, generated_at, applied_at, superseded_at, superseded_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record.draft_id, record.marked_answer_id, record.answer_file_id, record.status,
         record.draft_score, record.draft_feedback_category, record.model_version,
         record.model_checksum, record.dataset_lineage, record.input_checksum,
         record.generated_at, record.applied_at, _now(), reason))
    conn.commit()


def list_draft_history(conn, marked_answer_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM core_ai1_draft_history WHERE marked_answer_id = ? "
        "ORDER BY history_id", (marked_answer_id,)).fetchall()
    return [dict(r) for r in rows]


def mark_stale(conn, marked_answer_id: int, reason: str) -> Optional[CoreAI1DraftRecord]:
    conn.execute("UPDATE core_ai1_answer_drafts SET stale_reason = ?, stale_marked_at = ? "
                 "WHERE marked_answer_id = ?", (reason, _now(), marked_answer_id))
    conn.commit()
    return get_draft_for_marked_answer(conn, marked_answer_id)


def mark_drafts_stale_for_other_models(conn, active_model_version: Optional[str]) -> int:
    """Mark every draft produced by a DIFFERENT model version stale. Called on
    activation and rollback so an old draft is never silently applied against a
    model that is no longer live. Teacher-final values are untouched."""
    if not active_model_version:
        return 0
    cursor = conn.execute(
        "UPDATE core_ai1_answer_drafts SET stale_reason = ?, stale_marked_at = ? "
        "WHERE model_version IS NOT NULL AND model_version != ? AND stale_reason IS NULL",
        (STALE_REASON_MODEL_CHANGED, _now(), active_model_version))
    conn.commit()
    return cursor.rowcount
