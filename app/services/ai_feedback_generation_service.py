"""Stage 12G-8 - Kertas 2 natural-language feedback drafts with an offline
template fallback.

Feedback here is WORDING ONLY. Nothing in this module reads, derives, writes or
implies a score, and the generated text is always a draft the teacher may edit,
replace or ignore. The student never sees it until the teacher finalises the
attempt.

The generation chain is deliberately ordered so the application never depends on
a runtime being present:
  1. the teacher's own configured local runtime, when they have one and it is
     usable (background worker only - it can block);
  2. the deterministic offline template, which always works;
and the teacher's existing feedback is never overwritten without their explicit
choice.
"""
import hashlib
from typing import List, Optional

import app.models.subject_profile_model as spm
from app.models.local_ai_settings_model import ADAPTER_NONE
from app.services import local_ai_settings_service as local_ai
from app.services.ai_backend_fake import FakeFeedbackBackend
from app.services.ai_backend_port import (
    FEEDBACK_SOURCE_LOCAL_LLM,
    FEEDBACK_SOURCE_TEMPLATE,
    FeedbackPort,
    LocalFeedbackRequest,
    TemplateFeedbackRequest,
)

_ANSWER_BOX = "answer_box"

_DEFAULT_FEEDBACK_BACKEND: Optional[FeedbackPort] = None


def get_feedback_backend() -> FeedbackPort:
    """The REAL feedback backend, through the Core AI facade.

    The local runtime is tried first and the backend's deterministic templates
    are the fallback, so wording is always available offline. Production never
    falls back to a fake.
    """
    if _DEFAULT_FEEDBACK_BACKEND is not None:
        return _DEFAULT_FEEDBACK_BACKEND
    from app.services.ai_backend_facade_adapters import FacadeFeedbackBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeFeedbackBackend(get_backend_facade())


def _backend(backend):
    return backend if backend is not None else get_feedback_backend()


class FeedbackGenerationError(ValueError):
    pass


def _part_identifier(target_label: Optional[str]) -> str:
    label = (target_label or "").lower()
    for token, part in (("part1", "part1"), ("_q1_", "part1"), ("part2", "part2"),
                        ("_q2_", "part2"), ("part3", "part3"), ("_q3_", "part3")):
        if token in label:
            return part
    return "part_unknown"


def feedback_input_checksum(marked, category_key: Optional[str]) -> str:
    basis = "|".join(str(v) for v in (
        marked.target_label, marked.effective_answer_text, marked.correct_answer_text,
        category_key))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _category_key(conn, marked_answer_id: int) -> Optional[str]:
    ids = spm.get_answer_feedback_category_ids(conn, marked_answer_id)
    if not ids:
        return None
    categories = {c.category_id: c.category_key for c in spm.list_feedback_categories(conn)}
    return categories.get(ids[0])


class FeedbackDraft:
    """A generated feedback draft plus where it came from and why."""

    def __init__(self, text: str, source: str, warnings: List[str],
                 model_name: Optional[str] = None, failure_status: Optional[str] = None,
                 fell_back: bool = False, template_version: Optional[str] = None) -> None:
        self.text = text
        self.source = source
        self.warnings = warnings
        self.model_name = model_name
        self.failure_status = failure_status
        self.fell_back = fell_back
        self.template_version = template_version

    @property
    def source_label(self) -> str:
        if self.source == FEEDBACK_SOURCE_LOCAL_LLM:
            return f"your local runtime ({self.model_name or 'model'})"
        return "the built-in offline templates"

    def describe(self) -> List[str]:
        lines = [f"Source: {self.source_label}"]
        if self.fell_back:
            lines.append(
                "Your local runtime was unavailable"
                + (f" ({self.failure_status})" if self.failure_status else "")
                + ", so the built-in templates were used instead.")
        lines.extend(self.warnings)
        lines.append("This is draft wording only. It carries no score, you may edit or replace it, "
                     "and the student sees nothing until you finalise the attempt.")
        return lines


_TEMPLATE_PERFORMANCE_KEYS = ("correct", "partial", "incorrect", "not_attempted")
_TEMPLATE_ISSUE_KEYS = ("task_fulfilment", "organisation", "grammar", "spelling", "vocabulary")


def _template_category_and_issues(category_key: Optional[str], score, maximum_score):
    """Split one stored feedback category into what the template understands.

    The canonical category keys (grammar, spelling, organisation, ...) name the
    ISSUE the teacher/model flagged - they are not performance levels, so
    passing them as the template's feedback_category could never match its
    correct/partial/incorrect wording and every draft fell through to the
    neutral 'requires teacher attention' sentence. The issue becomes an issue
    tag, and the performance level derives from the teacher's own score when
    one exists (>=75% correct, >=35% partial, else incorrect - deterministic,
    stated bands; the wording always tells the teacher to confirm)."""
    category = (category_key or "").strip()
    issues = []
    if category in _TEMPLATE_ISSUE_KEYS:
        issues.append(category)
        category = ""
    if category not in _TEMPLATE_PERFORMANCE_KEYS:
        category = ""
    if not category and score is not None and maximum_score:
        ratio = float(score) / float(maximum_score)
        category = ("correct" if ratio >= 0.75
                    else "partial" if ratio >= 0.35 else "incorrect")
    return category, tuple(issues)


def build_template_request(conn, marked, category_key: Optional[str]) -> TemplateFeedbackRequest:
    category, issues = _template_category_and_issues(
        category_key, marked.effective_score, marked.max_score)
    return TemplateFeedbackRequest(
        feedback_category=category,
        paper="kertas2",
        part=_part_identifier(marked.target_label),
        score=marked.effective_score,
        maximum_score=marked.max_score,
        marking_scheme_available=bool(marked.correct_answer_text),
        student_answer_blank=not bool((marked.effective_answer_text or "").strip()),
        input_checksum=feedback_input_checksum(marked, category_key),
        issue_tags=issues)


def build_local_request(conn, marked, category_key: Optional[str],
                        runtime) -> LocalFeedbackRequest:
    return LocalFeedbackRequest(
        request_id=str(marked.marked_answer_id),
        adapter=runtime.adapter,
        endpoint=runtime.endpoint or "",
        model_name=runtime.model_name or "",
        question_context=marked.target_label or "",
        marking_scheme=marked.correct_answer_text or "",
        effective_student_answer=marked.effective_answer_text or "",
        feedback_category=category_key or "",
        # The score is passed as fixed CONTEXT only - the runtime is instructed
        # never to restate or change it, and any score-like output is stripped.
        score_context=float(marked.effective_score or 0.0),
        maximum_score=float(marked.max_score or 0.0),
        paper="kertas2",
        part=_part_identifier(marked.target_label),
        input_checksum=feedback_input_checksum(marked, category_key),
        timeout_seconds=runtime.timeout_seconds,
        maximum_output_tokens=runtime.max_output_tokens,
        temperature=runtime.temperature,
        response_size_limit=runtime.response_size_limit,
        requested_feedback_length=runtime.requested_feedback_length,
        allow_private_network=runtime.allow_private_network,
        previous_teacher_feedback=marked.teacher_feedback)


def generate_feedback_draft(conn, teacher_id: int, marked_answer_id: int,
                            backend=None, cancellation_token=None) -> FeedbackDraft:
    """Produce a feedback draft for one Kertas 2 writing answer. MAY BLOCK when
    a local runtime is configured - callers run it in a background worker. Never
    writes anything; the caller decides whether to keep the text."""
    marked = spm.get_marked_answer_by_id(conn, marked_answer_id)
    if marked is None:
        raise FeedbackGenerationError("That answer no longer exists.")
    if marked.region_type != _ANSWER_BOX:
        raise FeedbackGenerationError(
            "Natural-language feedback applies to Kertas 2 writing answers only.")
    category_key = _category_key(conn, marked_answer_id)
    runtime = local_ai.get_teacher_feedback_runtime(conn, teacher_id)
    provider = _backend(backend)

    warnings: List[str] = []
    failure_status = None
    if runtime.adapter != ADAPTER_NONE and not local_ai.validate_feedback_runtime(runtime):
        result = provider.generate_local_feedback(
            build_local_request(conn, marked, category_key, runtime), cancellation_token)
        if result.generated_feedback and result.failure_status is None:
            return FeedbackDraft(result.generated_feedback, FEEDBACK_SOURCE_LOCAL_LLM,
                                 list(result.warnings), model_name=result.model_name)
        failure_status = result.failure_status
        warnings.extend(result.warnings)
    elif runtime.adapter != ADAPTER_NONE:
        warnings.append("Your local runtime configuration is incomplete, so the built-in "
                        "templates were used.")

    template = provider.generate_template_feedback(
        build_template_request(conn, marked, category_key))
    warnings.extend(template.warnings)
    return FeedbackDraft(
        template.generated_text, FEEDBACK_SOURCE_TEMPLATE, warnings,
        failure_status=failure_status, fell_back=failure_status is not None,
        template_version=template.template_version)


def generate_feedback_drafts_for_attempt(conn, teacher_id: int, answer_file_id: int,
                                         backend=None, cancellation_token=None) -> dict:
    """Draft feedback for every Kertas 2 writing answer in one attempt. MAY
    BLOCK. Writes nothing - returns {marked_answer_id: FeedbackDraft}."""
    drafts = {}
    for marked in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        if marked.region_type != _ANSWER_BOX:
            continue
        try:
            drafts[marked.marked_answer_id] = generate_feedback_draft(
                conn, teacher_id, marked.marked_answer_id, backend, cancellation_token)
        except FeedbackGenerationError:
            continue
    return drafts


def apply_feedback_draft(conn, teacher_id: int, profile_id: int, marked_answer_id: int,
                         text: str) -> "spm.SubjectProfileMarkedAnswer":
    """Save draft wording as the teacher's own student-facing feedback, through
    the normal review service so it stays fully editable. Writes no score."""
    import app.services.subject_profile_review_service as review_service
    if not text or not str(text).strip():
        raise FeedbackGenerationError("There is no feedback text to save.")
    return review_service.set_teacher_feedback(
        conn, teacher_id, profile_id, marked_answer_id, teacher_feedback=str(text).strip())


def describe_feedback_availability(conn, teacher_id: int) -> dict:
    """What the teacher can expect before they generate anything."""
    runtime = local_ai.get_teacher_feedback_runtime(conn, teacher_id)
    report = local_ai.describe_feedback_runtime(runtime)
    return {
        "local_runtime_configured": report["configured"],
        "adapter": runtime.adapter,
        "message": ("Feedback wording will use your local runtime, falling back to the built-in "
                    "templates if it is unavailable."
                    if report["configured"] else
                    "Feedback wording uses the built-in offline templates. Configure a local "
                    "runtime in Local AI Settings to have it written in natural language."),
    }
