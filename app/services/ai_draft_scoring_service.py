"""Stage 12G-6 - teacher-facing Core AI 1 draft scoring for Kertas 2.

A draft is a SUGGESTION for the reviewing teacher, never a final result:
- Generating drafts never writes a teacher score, feedback or review state.
- An answer the teacher has already scored is SKIPPED, not overwritten.
- Kertas 1 is rule-based and is never sent to Core AI 1.
- Applying a draft is an explicit, per-answer teacher action that writes the
  teacher's own score through the normal review service, and it remains fully
  editable afterwards.
- A draft is marked STALE when the answer it scored changed or a different
  model was activated; a stale draft is never applied silently.

Manual marking stays completely available when no model is active, the runtime
is missing or inference fails - those paths simply record a non-completed draft
status with a factual reason.
"""
import hashlib
from typing import Dict, List, Optional

import app.models.ai_core1_draft_model as drafts
import app.models.subject_profile_model as spm
from app.services.ai_backend_fake import FakeCoreAI1InferenceBackend
from app.services.ai_backend_port import (
    CORE_AI1_STATUS_COMPLETED,
    CoreAI1InferencePort,
    CoreAI1InferenceRequest,
)

_ANSWER_BOX = "answer_box"
_PAPER_KERTAS2 = "kertas2"

_DEFAULT_INFERENCE: Optional[CoreAI1InferencePort] = None


def get_core_ai1_inference_backend() -> CoreAI1InferencePort:
    """The REAL Core AI 1 inference backend, through the Core AI facade.

    Drafts remain suggestions: the teacher's own score, category and feedback
    are never written from here. Production never falls back to a fake.
    """
    if _DEFAULT_INFERENCE is not None:
        return _DEFAULT_INFERENCE
    from app.services.ai_backend_facade_adapters import FacadeCoreAI1InferenceBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeCoreAI1InferenceBackend(get_backend_facade())


def _backend(backend):
    return backend if backend is not None else get_core_ai1_inference_backend()


class DraftScoringError(ValueError):
    pass


def _part_identifier(target_label: Optional[str]) -> str:
    label = (target_label or "").lower()
    for token, part in (("part1", "part1"), ("_q1_", "part1"), ("part2", "part2"),
                        ("_q2_", "part2"), ("part3", "part3"), ("_q3_", "part3")):
        if token in label:
            return part
    return "part_unknown"


def input_checksum(marked) -> str:
    """Stable checksum of everything the model is shown for this answer. It
    changes whenever the effective answer, scheme, maximum or Part 3 selection
    changes - which is exactly when an existing draft becomes stale."""
    basis = "|".join(str(v) for v in (
        marked.target_label, marked.effective_answer_text, marked.correct_answer_text,
        marked.max_score, marked.effective_selected_question_number))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_scoreable(marked) -> bool:
    """Only Kertas 2 writing answers are scoreable by Core AI 1."""
    return marked.region_type == _ANSWER_BOX


def has_teacher_value(marked) -> bool:
    return marked.teacher_score is not None


def build_request(marked, model_version: Optional[str] = None) -> CoreAI1InferenceRequest:
    return CoreAI1InferenceRequest(
        request_id=str(marked.marked_answer_id),
        task_context=marked.target_label or "",
        marking_scheme=marked.correct_answer_text or "",
        effective_student_answer=marked.effective_answer_text or "",
        paper=_PAPER_KERTAS2,
        part=_part_identifier(marked.target_label),
        maximum_score=float(marked.max_score or 0.0),
        input_checksum=input_checksum(marked),
        selected_part3_question=marked.effective_selected_question_number,
        model_version=model_version,
        existing_teacher_reviewed=has_teacher_value(marked),
    )


def list_scoreable_answers(conn, answer_file_id: int) -> List:
    return [m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)
            if is_scoreable(m)]


def generate_drafts_for_attempt(conn, teacher_id: int, profile_id: Optional[int],
                                answer_file_id: int, model_version: Optional[str] = None,
                                backend=None, cancellation_token=None
                                ) -> List[drafts.CoreAI1DraftRecord]:
    """Run Core AI 1 over every Kertas 2 writing answer in one attempt and
    persist one draft per answer. MAY BLOCK - callers run it in a background
    worker. Writes no teacher score, feedback or review state.

    Cancellation is cooperative and is checked between answers, so a cancelled
    run keeps the drafts already produced and simply stops - it never leaves a
    half-written record.
    """
    answers = list_scoreable_answers(conn, answer_file_id)
    if not answers:
        return []
    if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
        return []
    by_id = {str(m.marked_answer_id): m for m in answers}
    requests = [build_request(m, model_version) for m in answers]
    results = _backend(backend).run_core_ai1_attempt_inference(requests)
    stored = []
    for result in results:
        if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
            break  # keep what has been persisted so far
        marked = by_id.get(result.request_id)
        if marked is None:
            continue  # a result for an answer we did not ask about is ignored
        stored.append(_persist(conn, teacher_id, profile_id, answer_file_id, marked, result))
    return stored


def generate_draft_for_answer(conn, teacher_id: int, profile_id: Optional[int],
                              answer_file_id: int, marked_answer_id: int,
                              model_version: Optional[str] = None,
                              backend=None) -> drafts.CoreAI1DraftRecord:
    """Regenerate the draft for a single answer (used after the teacher edits
    the extracted answer, or after a new model is activated). MAY BLOCK."""
    marked = spm.get_marked_answer_by_id(conn, marked_answer_id)
    if marked is None:
        raise DraftScoringError("That answer no longer exists.")
    if not is_scoreable(marked):
        raise DraftScoringError(
            "Core AI 1 scores Kertas 2 writing answers only; Kertas 1 marking stays rule-based.")
    result = _backend(backend).run_core_ai1_inference(build_request(marked, model_version))
    return _persist(conn, teacher_id, profile_id, answer_file_id, marked, result)


def _persist(conn, teacher_id, profile_id, answer_file_id, marked, result):
    return drafts.upsert_draft(
        conn, marked_answer_id=marked.marked_answer_id, answer_file_id=answer_file_id,
        profile_id=profile_id, status=result.status, input_checksum=result.input_checksum,
        generated_by_user_id=teacher_id, draft_score=result.proposed_application_score,
        draft_raw_score=result.draft_raw_score, normalized_score=result.normalized_score,
        draft_feedback_category=result.feedback_category,
        category_confidence=result.category_confidence, score_confidence=result.score_confidence,
        rounding_policy_version=result.rounding_policy_version, model_version=result.model_version,
        model_checksum=result.model_checksum, dataset_lineage=result.dataset_lineage,
        input_template_version=result.input_template_version,
        truncation_warning=result.truncation_warning,
        missing_scheme_warning=result.missing_scheme_warning, clamped=result.clamped,
        warnings=list(result.warnings), failure_code=result.failure_code, device=result.device,
        runtime_duration_seconds=result.runtime_duration_seconds)


# --- reading drafts for the review workspace --------------------------------

def get_draft_view(conn, marked) -> Optional[dict]:
    """The draft for one answer plus its staleness, ready for display. Returns
    None when no draft has been generated."""
    record = drafts.get_draft_for_marked_answer(conn, marked.marked_answer_id)
    if record is None:
        return None
    current = input_checksum(marked)
    stale = record.is_stale(current)
    return {
        "record": record,
        "stale": stale,
        "stale_reason": record.stale_explanation(current) if stale else None,
        "applicable": (record.status == CORE_AI1_STATUS_COMPLETED and not stale
                       and record.draft_score is not None),
        "display": describe_draft(record, stale),
    }


def list_draft_views(conn, answer_file_id: int) -> Dict[int, dict]:
    by_answer = drafts.drafts_by_marked_answer(conn, answer_file_id)
    if not by_answer:
        return {}
    views = {}
    for marked in list_scoreable_answers(conn, answer_file_id):
        if marked.marked_answer_id in by_answer:
            views[marked.marked_answer_id] = get_draft_view(conn, marked)
    return views


def describe_draft(record: drafts.CoreAI1DraftRecord, stale: bool) -> str:
    """A short factual label. It never claims a score is final and never shows
    a number the backend did not produce."""
    if record.status == drafts.STATUS_SKIPPED:
        return "Skipped (already scored by you)"
    if record.status == drafts.STATUS_ATTENTION_REQUIRED:
        return "Needs your attention (no draft score)"
    if record.status == drafts.STATUS_FAILED:
        return f"Unavailable ({record.failure_code or 'failed'})"
    score = f"{record.draft_score:g}" if record.draft_score is not None else "-"
    category = record.draft_feedback_category or "-"
    label = f"Draft {score} | {category}"
    if record.category_confidence is not None:
        label += f" ({record.category_confidence:.0%} confidence)"
    return label + (" - STALE, regenerate" if stale else "")


def draft_detail_lines(conn, marked) -> List[str]:
    """Full provenance for the review dialog - what produced this suggestion."""
    view = get_draft_view(conn, marked)
    if view is None:
        return ["No Core AI 1 draft has been generated for this answer."]
    record = view["record"]
    lines = [
        f"Status: {record.status}",
        f"Draft score (suggestion only): "
        f"{record.draft_score if record.draft_score is not None else '-'} / {marked.max_score:g}",
        f"Feedback category: {record.draft_feedback_category or '-'}",
        f"Category confidence: "
        f"{f'{record.category_confidence:.0%}' if record.category_confidence is not None else '-'}",
        f"Rounding policy: {record.rounding_policy_version or '-'}",
        f"Model: {record.model_version or '-'} (checksum {record.model_checksum or '-'})",
        f"Trained from dataset: {record.dataset_lineage or '-'}",
        f"Input template: {record.input_template_version or '-'}",
        f"Generated at: {record.generated_at}",
        ("Stale: Yes - " + (view.get("stale_reason") or "its inputs changed")
         if view["stale"] else "Stale: No"),
        f"Superseded drafts kept for lineage: "
        f"{len(drafts.list_draft_history(conn, marked.marked_answer_id))}",
    ]
    if record.clamped:
        lines.append("The raw model score was clamped to the valid mark range.")
    if record.truncation_warning:
        lines.append("The answer was truncated for the model input.")
    if record.missing_scheme_warning:
        lines.append("The marking scheme was missing or unclear for this answer.")
    lines.extend(record.warnings)
    lines.append("This is a draft suggestion. Your score and feedback remain yours to set.")
    return lines


# --- explicit teacher decisions ---------------------------------------------

def apply_draft(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                marked_answer_id: int, apply_category: bool = True) -> drafts.CoreAI1DraftRecord:
    """Copy a draft into the TEACHER'S OWN score/category through the normal
    review service, so it stays fully editable and is validated exactly like a
    manually typed score. Refuses a stale, failed or missing draft."""
    import app.services.subject_profile_review_service as review_service

    marked = spm.get_marked_answer_by_id(conn, marked_answer_id)
    if marked is None:
        raise DraftScoringError("That answer no longer exists.")
    view = get_draft_view(conn, marked)
    if view is None:
        raise DraftScoringError("There is no Core AI 1 draft for this answer yet.")
    record = view["record"]
    if record.status != CORE_AI1_STATUS_COMPLETED or record.draft_score is None:
        raise DraftScoringError(
            "This draft has no score to apply; enter your own score for this answer.")
    if view["stale"]:
        raise DraftScoringError(
            "This draft is out of date because "
            + (view.get("stale_reason") or "its inputs changed")
            + ". Regenerate it before applying.")

    review_service.set_kertas2_teacher_score(
        conn, teacher_id, profile_id, marked_answer_id, record.draft_score)
    if apply_category and record.draft_feedback_category:
        category_ids = {c.category_key: c.category_id
                        for c in spm.list_feedback_categories(conn)}
        category_id = category_ids.get(record.draft_feedback_category)
        if category_id is not None:
            review_service.set_answer_feedback_categories(
                conn, teacher_id, profile_id, marked_answer_id, [category_id])
    return drafts.mark_draft_applied(conn, marked_answer_id)


def dismiss_draft(conn, marked_answer_id: int) -> drafts.CoreAI1DraftRecord:
    record = drafts.get_draft_for_marked_answer(conn, marked_answer_id)
    if record is None:
        raise DraftScoringError("There is no Core AI 1 draft for this answer.")
    return drafts.mark_draft_dismissed(conn, marked_answer_id)


def summarize_attempt_drafts(conn, answer_file_id: int) -> dict:
    """Counts for the review panel. Nothing here changes a review state."""
    records = drafts.list_drafts_for_answer_file(conn, answer_file_id)
    views = list_draft_views(conn, answer_file_id)
    stale = sum(1 for v in views.values() if v and v["stale"])
    return {
        "total": len(records),
        "completed": sum(1 for r in records if r.status == CORE_AI1_STATUS_COMPLETED),
        "attention_required": sum(1 for r in records
                                  if r.status == drafts.STATUS_ATTENTION_REQUIRED),
        "skipped": sum(1 for r in records if r.status == drafts.STATUS_SKIPPED),
        "failed": sum(1 for r in records if r.status == drafts.STATUS_FAILED),
        "applied": sum(1 for r in records if r.applied_at),
        "stale": stale,
    }
