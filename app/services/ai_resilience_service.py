"""Stage 12G-9 - hardening for every AI-assisted workflow.

The application must remain fully usable when the AI side is absent, broken,
slow or cancelled. This module holds the shared guarantees the AI features rely
on, so each feature does not re-invent them:

- one place that turns ANY backend failure into a factual, teacher-readable
  message that never leaks a path, prompt, stack trace, essay text or internal
  identifier;
- a cooperative cancellation token matching the backend's, so a long operation
  can be stopped without leaving a half-written record;
- a single guard that confirms manual operation is unaffected by an AI failure;
- a preflight readiness report a teacher or admin can read before starting.

Nothing here writes marking data.
"""
import re
from typing import List, Optional

from app.services.ai_backend_port import BackendError

# --- failure classification --------------------------------------------------
#
# Every code the application can receive from the AI side, mapped to wording a
# teacher can act on. An unrecognised code degrades to the generic message
# rather than being shown raw.

MANUAL_UNAFFECTED = "Marking this attempt manually is unaffected."

_FAILURE_MESSAGES = {
    # model / runtime availability
    "no_active_model": "No AI model is active yet, so nothing could be generated.",
    "model_not_found": "The requested AI model version is no longer available.",
    "runtime_unavailable": "The local AI runtime is not installed or not running.",
    "runtime_incompatible": "The local AI runtime is not compatible with this model.",
    "out_of_memory": "There was not enough memory to run the AI model.",
    "checksum_mismatch": "The AI model files failed their integrity check and were not used.",
    # inference
    "kertas1_unsupported": "Kertas 1 is marked by rules, so the AI does not score it.",
    "blank_answer": "The student answer is blank, so no draft could be produced.",
    "invalid_maximum_score": "This answer has no valid maximum score.",
    "teacher_reviewed": "You have already scored this answer, so it was left untouched.",
    "unknown_category": "The model returned a feedback category this system does not recognise.",
    # local feedback
    "endpoint_not_allowed": "The configured feedback address is not a local address.",
    "adapter_unsupported": "The configured feedback adapter is not supported.",
    "timeout": "The local runtime did not respond in time.",
    "response_too_large": "The local runtime returned more data than the configured limit.",
    "feedback_field_missing": "The local runtime did not return any feedback text.",
    "feedback_unusable": "The local runtime returned no usable feedback text.",
    # datasets / training / activation
    "dataset_not_found": "That dataset no longer exists.",
    "not_export_valid": "That dataset is not export-valid, so it cannot be used.",
    "already_frozen": "That dataset is already frozen; freezing is permanent.",
    "version_exists": "A dataset with that version already exists and was not overwritten.",
    "validation_failed": "The training request did not pass validation.",
    "evaluation_required": "A passing evaluation is required before a model can be activated.",
    "unsupported_family": "That operation does not apply to this model family.",
    # control flow
    "cancelled": "The operation was cancelled.",
    # Stage 12G-13: codes the real Core AI backend raises.
    "capability_unavailable": "That AI capability is not installed on this computer.",
    "unknown_model_family": "That operation does not apply to this model family.",
    "conversion_unsupported": "Core AI 1 trains from its own exported data, so it has no "
                              "conversion step.",
    "conversion_format_unsupported": "Only YOLO and COCO detector formats are supported.",
    "candidate_version_exists": "That capture version already exists and cannot be replaced.",
    "evaluation_split_empty": "The evaluation split is empty, so no metrics were computed.",
    "evaluation_inference_failed": "Evaluation could not score every sample, so no metrics "
                                   "were produced.",
    "evaluation_required": "A passing evaluation is required before a model can be activated.",
    "job_not_found": "That training job no longer exists.",
}

GENERIC_FAILURE_MESSAGE = "The AI step could not be completed."

# Anything resembling a filesystem path, a prompt/template marker, an essay
# excerpt delimiter or an internal identifier is never shown to a user.
_UNSAFE_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/][^\s]*"),          # Windows path
    re.compile(r"(?:^|\s)/(?:[\w.-]+/)+[\w.-]+"),  # POSIX path
    re.compile(r"\[[A-Z_]{3,}\]"),                 # prompt section marker
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r'File "[^"]+", line \d+'),
    re.compile(r"\b0x[0-9a-fA-F]{6,}\b"),          # memory address
)


def contains_unsafe_detail(text: Optional[str]) -> bool:
    return bool(text) and any(p.search(text) for p in _UNSAFE_PATTERNS)


def describe_failure(error, *, include_manual_note: bool = True) -> str:
    """A safe, factual message for any AI failure. A recognised code gets
    specific wording; anything else - including an unexpected exception - gets
    the generic message. Raw exception text is never shown, because it can carry
    a path, a prompt or student answer content."""
    code = getattr(error, "code", None) or getattr(error, "failure_status", None)
    if isinstance(error, str):
        code = error
    message = _FAILURE_MESSAGES.get(code)
    if message is None:
        safe = getattr(error, "safe_message", None)
        # A backend safe_message is shown only when it is genuinely safe.
        message = (safe if isinstance(error, BackendError) and safe
                   and not contains_unsafe_detail(safe) else GENERIC_FAILURE_MESSAGE)
    if include_manual_note:
        return f"{message} {MANUAL_UNAFFECTED}"
    return message


def failure_code(error) -> Optional[str]:
    if isinstance(error, str):
        return error
    return getattr(error, "code", None) or getattr(error, "failure_status", None)


def is_recoverable(error) -> bool:
    """A recoverable failure is one the teacher can retry after acting; an
    unrecoverable one means this answer simply is not AI-scoreable."""
    return failure_code(error) not in (
        "kertas1_unsupported", "blank_answer", "invalid_maximum_score", "teacher_reviewed")


# --- cooperative cancellation ------------------------------------------------

class CancellationToken:
    """Mirror of the backend's cancellation token. Cancellation is cooperative:
    the worker checks it between steps, so a cancelled operation stops cleanly
    without leaving a half-written record."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise BackendError("cancelled", _FAILURE_MESSAGES["cancelled"])


# --- preflight readiness -----------------------------------------------------

def describe_ai_readiness(conn, teacher_id: Optional[int] = None) -> dict:
    """What AI assistance is available right now, and what still works without
    it. Never raises - an unavailable component is reported, not thrown."""
    draft_scoring = {"available": False, "detail": "No active Core AI 1 model."}
    try:
        from app.services import ai_draft_scoring_service as drafting
        backend = drafting.get_core_ai1_inference_backend()
        version = getattr(backend, "active_model_version", None)
        if version:
            draft_scoring = {"available": True, "detail": f"Core AI 1 model {version}."}
    except Exception:
        draft_scoring = {"available": False, "detail": "The Core AI 1 runtime is unavailable."}

    feedback = {"available": True, "detail": "Built-in offline templates."}
    try:
        from app.services import ai_feedback_generation_service as feedback_service
        report = feedback_service.describe_feedback_availability(conn, teacher_id)
        if report["local_runtime_configured"]:
            feedback = {"available": True,
                        "detail": f"Your local runtime ({report['adapter']}), with template "
                                  "fallback."}
    except Exception:
        pass  # templates always remain available

    region_proposals = {"available": False, "detail": "No active Core AI 2 model."}
    try:
        from app.services import ai_region_proposal_service as proposals
        backend = proposals.get_inference_backend()
        if getattr(backend, "active_model_version", None) or backend is not None:
            region_proposals = {"available": True, "detail": "Core AI 2 proposals available."}
    except Exception:
        region_proposals = {"available": False, "detail": "The Core AI 2 runtime is unavailable."}

    return {
        "draft_scoring": draft_scoring,
        "feedback": feedback,
        "region_proposals": region_proposals,
        "manual_operation": {
            "available": True,
            "detail": "Uploading, extracting, marking, reviewing, finalising and publishing "
                      "results all work without any AI component.",
        },
    }


def manual_workflow_blockers(conn, teacher_id: int, answer_file_id: int) -> List[str]:
    """Everything genuinely blocking a teacher from finishing this attempt BY
    HAND. An absent, failed or stale AI result is never a blocker - that is the
    guarantee this function exists to prove."""
    blockers: List[str] = []
    try:
        import app.services.subject_profile_review_service as review_service
        import app.models.subject_profile_model as spm
        review = spm.get_attempt_review(conn, answer_file_id)
        if review is not None and review.review_state == spm.REVIEW_STATE_FINALISED:
            blockers.append("This attempt is finalised. Reopen it before making changes.")
        else:
            profile_id = review.profile_id if review else None
            if profile_id is not None:
                blockers.extend(review_service.get_finalisation_blockers(
                    conn, teacher_id, profile_id, answer_file_id))
    except Exception:
        # A failure to compute blockers must never claim the teacher is blocked.
        return blockers
    return blockers
