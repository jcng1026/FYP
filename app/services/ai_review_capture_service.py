"""Stage 12G-11 - feeding teacher review decisions back to the AI side.

After a teacher finalises an attempt, what they actually decided is the most
valuable training signal the system has: where they accepted the model's draft,
where they changed it, and which region proposals they accepted, edited or
rejected. This module builds those records from application state and hands them
to the backend's review capture.

Three rules govern everything here:

- capture NEVER blocks marking. A capture failure is recorded and reported, but
  finalisation still succeeds and no teacher decision is erased;
- only FINALISED, non-stale, fully-labelled records are captured - a stale draft
  or a missing teacher label is excluded with its reason;
- a record is captured once. Duplicates are excluded rather than double-counted.
"""
import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import app.models.ai_core1_draft_model as drafts
import app.models.ai_region_proposal_model as proposals_model
import app.models.subject_profile_model as spm

# --- mirrors of the Codex review-capture records ----------------------------


@dataclass(frozen=True)
class CoreAI1ReviewedRecord:
    """Mirror of Codex `CoreAI1ReviewedRecord` (field order preserved)."""
    record_id: str
    finalized: bool
    stale_draft: bool
    original_draft_score: Optional[float]
    original_draft_category: Optional[str]
    teacher_final_score: Optional[float]
    teacher_final_category: Optional[str]
    draft_disposition: str
    input_checksum: str
    model_version: str
    teacher_final_student_feedback: Optional[str]
    feedback_capture_permitted: bool
    paper: str
    part: str
    question_context: str
    marking_scheme_checksum: Optional[str]
    attempt_group_id: str
    student_group_id: str
    profile_group_id: str
    finalized_at: str


@dataclass(frozen=True)
class CoreAI2ReviewedProposal:
    """Mirror of Codex `CoreAI2ReviewedProposal` (field order preserved)."""
    proposal_id: str
    proposed_class: str
    proposed_geometry: Sequence[float]
    final_teacher_class: Optional[str]
    final_teacher_geometry: Optional[Sequence[float]]
    review_status: str
    model_version: str
    model_checksum: str
    page_checksum: str
    profile_group_id: str
    attempt_group_id: str
    reason_code: Optional[str] = None


@dataclass
class CaptureOutcome:
    """What a capture attempt did. `ok=False` never means marking failed."""
    ok: bool
    family: str
    candidate_version: Optional[str] = None
    captured: int = 0
    excluded: List[Dict[str, Any]] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    failure_message: Optional[str] = None

    @property
    def excluded_reasons(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.excluded:
            counts[entry["reason"]] = counts.get(entry["reason"], 0) + 1
        return counts


DISPOSITION_APPLIED = "applied_unchanged"
DISPOSITION_EDITED = "applied_then_edited"
DISPOSITION_DISMISSED = "dismissed"
DISPOSITION_IGNORED = "ignored"


def _checksum(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _disposition(record, marked) -> str:
    if record.dismissed_at:
        return DISPOSITION_DISMISSED
    if not record.applied_at:
        return DISPOSITION_IGNORED
    if record.draft_score is not None and marked.teacher_score != record.draft_score:
        return DISPOSITION_EDITED
    return DISPOSITION_APPLIED


# --- building records from application state --------------------------------

def build_core_ai1_records(conn, answer_file_id: int) -> List[CoreAI1ReviewedRecord]:
    """One record per Kertas 2 writing answer of a FINALISED attempt that has a
    draft. Stale drafts and unlabelled answers are still emitted - the capture
    layer excludes them with a reason rather than silently dropping them."""
    from app.services import ai_draft_scoring_service as drafting

    review = spm.get_attempt_review(conn, answer_file_id)
    finalized = bool(review and review.review_state == spm.REVIEW_STATE_FINALISED)
    finalized_at = (getattr(review, "finalised_at", None) or "") if review else ""
    profile_id = review.profile_id if review else None
    categories = {c.category_id: c.category_key for c in spm.list_feedback_categories(conn)}

    records: List[CoreAI1ReviewedRecord] = []
    for marked in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        if marked.region_type != "answer_box":
            continue
        record = drafts.get_draft_for_marked_answer(conn, marked.marked_answer_id)
        if record is None:
            continue
        current_checksum = drafting.input_checksum(marked)
        category_ids = spm.get_answer_feedback_category_ids(conn, marked.marked_answer_id)
        teacher_category = categories.get(category_ids[0]) if category_ids else None
        records.append(CoreAI1ReviewedRecord(
            record_id=f"answer_{marked.marked_answer_id}",
            finalized=finalized,
            stale_draft=record.is_stale(current_checksum),
            original_draft_score=record.draft_score,
            original_draft_category=record.draft_feedback_category,
            teacher_final_score=marked.teacher_score,
            teacher_final_category=teacher_category,
            draft_disposition=_disposition(record, marked),
            input_checksum=record.input_checksum,
            model_version=record.model_version or "",
            teacher_final_student_feedback=marked.teacher_feedback,
            feedback_capture_permitted=True,
            paper="kertas2",
            part=drafting._part_identifier(marked.target_label),
            question_context=marked.target_label or "",
            marking_scheme_checksum=_checksum(marked.correct_answer_text),
            attempt_group_id=f"attempt_{answer_file_id}",
            student_group_id=f"student_{answer_file_id}",
            profile_group_id=f"profile_{profile_id}",
            finalized_at=finalized_at,
        ))
    return records


def build_core_ai2_proposals(conn, answer_file_id: Optional[int] = None,
                             profile_id: Optional[int] = None
                             ) -> List[CoreAI2ReviewedProposal]:
    """Every reviewed Core AI 2 proposal - accepted, edited, rejected and
    deferred alike. The capture layer decides which become training labels,
    which become rejection evidence and which are excluded."""
    if answer_file_id is not None:
        records = proposals_model.list_proposals_for_attempt(conn, answer_file_id)
    else:
        records = proposals_model.list_proposals_for_profile(conn, profile_id)
    out: List[CoreAI2ReviewedProposal] = []
    for record in records:
        final_geometry = None
        if record.final_x is not None:
            final_geometry = [record.final_x, record.final_y,
                              record.final_width, record.final_height]
        out.append(CoreAI2ReviewedProposal(
            proposal_id=record.proposal_id,
            proposed_class=record.proposed_class or "",
            proposed_geometry=[record.source_x, record.source_y,
                               record.source_width, record.source_height],
            final_teacher_class=record.proposed_target_label,
            final_teacher_geometry=final_geometry,
            review_status=record.status,
            model_version=record.model_version or "",
            model_checksum=record.model_checksum or "",
            page_checksum=record.input_page_checksum or "",
            profile_group_id=f"profile_{record.profile_id}",
            attempt_group_id=f"attempt_{record.answer_file_id}",
            reason_code=record.decision_reason,
        ))
    return out


# --- proving capture is non-authoritative ------------------------------------
#
# Capture is a post-finalisation SIDE EFFECT. It must never be able to change a
# teacher-owned value, so the capture path both (a) writes nothing to any
# teacher column by construction, and (b) runs inside a SQLite savepoint that is
# rolled back if anything goes wrong. `snapshot_teacher_state` captures every
# teacher-owned field of an attempt so a caller - or a test - can prove nothing
# moved.

TEACHER_OWNED_FIELDS = (
    "teacher_score", "teacher_status", "teacher_feedback", "private_comment",
    "teacher_selected_question_number", "reviewed_by", "reviewed_at",
)


def snapshot_teacher_state(conn, answer_file_id: int) -> Dict[str, Any]:
    """Every teacher-owned value of an attempt: per-answer final score, status,
    student-facing feedback, private comment and feedback categories, plus the
    attempt's review state and published output references."""
    review = spm.get_attempt_review(conn, answer_file_id)
    answers = {}
    for marked in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        answers[marked.marked_answer_id] = {
            field: getattr(marked, field, None) for field in TEACHER_OWNED_FIELDS
        }
        answers[marked.marked_answer_id]["feedback_category_ids"] = list(
            spm.get_answer_feedback_category_ids(conn, marked.marked_answer_id))
    return {
        "answers": answers,
        "review_state": getattr(review, "review_state", None),
        "finalised_at": getattr(review, "finalised_at", None),
        "reviewer_id": getattr(review, "reviewer_id", None),
        "output_references": _output_references(conn, answer_file_id),
    }


def _output_references(conn, answer_file_id: int) -> Dict[str, Any]:
    """Published output references for the attempt, if the schema records any."""
    try:
        row = conn.execute(
            "SELECT final_marked_pdf_path, final_comments_path, final_output_generated_at, "
            "final_output_version FROM subject_profile_attempt_reviews WHERE answer_file_id = ?",
            (answer_file_id,)).fetchone()
    except Exception:
        return {}
    return dict(row) if row else {}


def _audit_capture_failure(conn, family: str, candidate_version: Optional[str],
                           message: Optional[str]) -> None:
    """A capture failure may produce ONLY a sanitized audit entry - never a
    change to marking data."""
    try:
        from app.models import ai_admin_audit_model as audit
        import json
        audit.record_ai_admin_action(
            conn, actor_user_id=None, actor_role=None,
            action=f"ai_models.{family}_review_capture", target=candidate_version,
            note=json.dumps({"outcome": "failed", "message": message}),
            outcome=audit.OUTCOME_FAILED)
    except Exception:
        pass  # even the audit is best-effort; marking must never be affected


# --- the capture itself ------------------------------------------------------

_DEFAULT_CAPTURE_BACKEND = None


def get_capture_backend():
    """The REAL review-capture backend, through the Core AI facade.

    Capture stays a non-authoritative post-finalisation side effect regardless
    of which backend serves it. Production never falls back to a fake.
    """
    if _DEFAULT_CAPTURE_BACKEND is not None:
        return _DEFAULT_CAPTURE_BACKEND
    from app.services.ai_backend_facade_adapters import FacadeReviewCaptureBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeReviewCaptureBackend(get_backend_facade())


def _backend(backend):
    return backend if backend is not None else get_capture_backend()


@contextmanager
def _isolated(conn):
    """Run a capture inside a savepoint that is released on success and rolled
    back on failure, so a partially-applied capture can never leave state
    behind. Marking data is already committed and outside this scope."""
    name = f"ai_capture_{uuid.uuid4().hex[:8]}"
    try:
        conn.execute(f"SAVEPOINT {name}")
    except Exception:
        yield  # a connection that cannot hold a savepoint still must not break
        return
    try:
        yield
    except BaseException:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        except Exception:
            pass
        raise
    finally:
        try:
            conn.execute(f"RELEASE SAVEPOINT {name}")
        except Exception:
            pass


def _normalise_capture_result(result) -> Dict[str, Any]:
    """Read either shape the capture layer can return.

    The real backend publishes the candidate set to disk and returns a
    `CandidateCaptureResult` summary; the deterministic fake returns the
    candidate/exclusion lists inline. Both carry the same statistics, so the
    outcome is built from those.
    """
    if isinstance(result, dict):
        return {
            "candidates": list(result.get("candidates", [])),
            "exclusions": list(result.get("exclusions", [])),
            "statistics": dict(result.get("statistics", {})),
            "path": result.get("path"),
        }
    statistics = dict(getattr(result, "statistics", {}) or {})
    captured = statistics.get("candidate_count", 0)
    return {
        # The real backend does not return the rows themselves - the count it
        # reports is authoritative, so a placeholder list of that length keeps
        # `captured` accurate without inventing row content.
        "candidates": [None] * int(captured or 0),
        "exclusions": list(statistics.get("exclusions", []) or []),
        "statistics": statistics,
        "path": getattr(result, "path", None),
    }


def capture_core_ai1_reviews(conn, answer_file_id: int, candidate_version: str,
                             backend=None) -> CaptureOutcome:
    """Capture a finalised attempt's Core AI 1 decisions. Never raises: a
    failure is returned as a non-ok outcome so finalisation is unaffected."""
    with _isolated(conn):
        try:
            records = build_core_ai1_records(conn, answer_file_id)
            raw = _backend(backend).capture_core_ai1_reviews(candidate_version, records)
            result = _normalise_capture_result(raw)
            return CaptureOutcome(
                ok=True, family="core_ai1", candidate_version=candidate_version,
                captured=len(result["candidates"]),
                excluded=result["exclusions"],
                statistics=result["statistics"])
        except Exception as exc:  # capture must never break marking
            from app.services import ai_resilience_service as resilience
            message = resilience.describe_failure(exc, include_manual_note=False)
            _audit_capture_failure(conn, "core_ai1", candidate_version, message)
            return CaptureOutcome(ok=False, family="core_ai1",
                                  candidate_version=candidate_version,
                                  failure_message=message)


def capture_core_ai2_reviews(conn, candidate_version: str, answer_file_id: Optional[int] = None,
                             profile_id: Optional[int] = None, backend=None) -> CaptureOutcome:
    with _isolated(conn):
        try:
            records = build_core_ai2_proposals(conn, answer_file_id, profile_id)
            raw = _backend(backend).capture_core_ai2_reviews(candidate_version, records)
            result = _normalise_capture_result(raw)
            return CaptureOutcome(
                ok=True, family="core_ai2", candidate_version=candidate_version,
                captured=len(result["candidates"]),
                excluded=result["exclusions"],
                statistics=result["statistics"])
        except Exception as exc:
            from app.services import ai_resilience_service as resilience
            message = resilience.describe_failure(exc, include_manual_note=False)
            _audit_capture_failure(conn, "core_ai2", candidate_version, message)
            return CaptureOutcome(ok=False, family="core_ai2",
                                  candidate_version=candidate_version,
                                  failure_message=message)
