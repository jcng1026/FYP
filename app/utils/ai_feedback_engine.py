"""AI feedback provider adapter layer for Kertas 2 draft feedback.

Wraps whatever local/offline AI feedback model the project eventually uses
behind a small interface, so the rest of the app never depends on a
specific model library. Import of any heavy AI/ML dependency is deferred
into the provider's own __init__ (via importlib, only when a backend name
is explicitly configured), so simply importing this module never requires
such a dependency to be installed, and a missing/unconfigured/unavailable
provider is surfaced as a clear DependencyUnavailableError instead of
crashing the app or silently faking a result.

No cloud or network AI calls are made anywhere in this module.
"""

import importlib.util
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional, Protocol


class DependencyUnavailableError(Exception):
    """Raised when a local AI feedback provider cannot run: no model/backend
    is configured, or the configured backend is unavailable (e.g. its
    optional library is not installed)."""


# Alternate, more descriptive name for the same error, per the provider
# design requirements. Kept as an alias (not a subclass) so existing
# `except DependencyUnavailableError` call sites keep working unchanged.
LocalProviderUnavailableError = DependencyUnavailableError


class AIProviderExecutionError(Exception):
    """Raised when a loaded local backend module's own generate function or
    method raises an exception, or returns output of the wrong type, while
    actually producing feedback (as opposed to the module failing to load,
    or its returned text failing to parse - see DependencyUnavailableError
    and AIFeedbackParseError respectively for those cases)."""


class AIFeedbackParseError(ValueError):
    """Raised by parse_ai_feedback_output (or a provider wrapping it) when
    raw provider output cannot be parsed into a valid AIFeedbackResult.

    Subclasses ValueError so existing `except ValueError` call sites keep
    working unchanged. Carries the original raw_output so callers can store
    it for audit purposes even though parsing failed.
    """

    def __init__(self, message: str, raw_output: Optional[str] = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass
class AIFeedbackInput:
    """Structured input handed to an AI feedback provider for one criterion."""

    criterion_name: str
    question_type: str
    student_answer: str
    sample_answer: Optional[str]
    max_mark: float
    rubric_notes: Optional[str] = None


@dataclass
class AIFeedbackResult:
    suggested_score: float
    max_mark: float
    feedback_text: str
    reason: str
    confidence: Optional[float] = None
    raw_output: Optional[str] = None


class AIFeedbackProvider(Protocol):
    """Lightweight interface AI feedback providers (real or fake/test) must satisfy."""

    def generate_feedback(self, input_data: AIFeedbackInput) -> AIFeedbackResult:
        ...


def build_kertas2_feedback_prompt(input_data: AIFeedbackInput) -> str:
    """Build the prompt text a local model would be given for one criterion.

    Instructs the model to reply with strict JSON only, and to treat the
    result as draft feedback that a teacher must still review.
    """
    lines = [
        "You are assisting a teacher by drafting Kertas 2 feedback for one marking criterion.",
        "This is draft feedback only. Teacher must review final score.",
        "",
        f"Criterion: {input_data.criterion_name}",
        f"Question type: {input_data.question_type}",
        f"Maximum mark: {input_data.max_mark}",
    ]
    if input_data.rubric_notes:
        lines.append(f"Rubric notes: {input_data.rubric_notes}")
    if input_data.sample_answer:
        lines.append(f"Sample/model answer: {input_data.sample_answer}")
    lines.append(f"Student answer: {input_data.student_answer}")
    lines.extend(
        [
            "",
            "Respond with strict JSON only - no markdown fences, no extra commentary - "
            "matching exactly this shape:",
            '{"suggested_score": number, "feedback_text": "...", "reason": "...", "confidence": number}',
        ]
    )
    return "\n".join(lines)


def _extract_json_object(raw_text: str) -> str:
    """Best-effort extraction of the first balanced {...} block from raw_text,
    tolerating surrounding text or ```json fences a local model might add."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()

    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def parse_ai_feedback_output(raw_text: str, max_mark: float) -> AIFeedbackResult:
    """Parse and validate a local model's raw text response into an
    AIFeedbackResult, clamping numeric fields into their valid ranges.

    Raises AIFeedbackParseError (a ValueError subclass) with a clear message
    and the original raw_output attached if the output is not valid JSON, or
    is missing required fields - callers should treat this the same as any
    other feedback-generation failure (safe failure, no fabricated data),
    while still being able to store the raw output for audit purposes.
    """
    if not raw_text or not raw_text.strip():
        raise AIFeedbackParseError("AI provider returned empty output.", raw_text)

    json_text = _extract_json_object(raw_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise AIFeedbackParseError(f"AI provider output is not valid JSON: {exc}", raw_text) from exc

    if not isinstance(data, dict):
        raise AIFeedbackParseError("AI provider output JSON must be an object.", raw_text)

    feedback_text = data.get("feedback_text")
    if not feedback_text or not str(feedback_text).strip():
        raise AIFeedbackParseError("AI provider output is missing required 'feedback_text'.", raw_text)

    reason = data.get("reason")
    if not reason or not str(reason).strip():
        raise AIFeedbackParseError("AI provider output is missing required 'reason'.", raw_text)

    try:
        suggested_score = float(data.get("suggested_score", 0))
    except (TypeError, ValueError) as exc:
        raise AIFeedbackParseError("AI provider output 'suggested_score' must be a number.", raw_text) from exc
    suggested_score = max(0.0, min(suggested_score, max_mark))

    confidence = None
    raw_confidence = data.get("confidence")
    if raw_confidence is not None:
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError) as exc:
            raise AIFeedbackParseError("AI provider output 'confidence' must be a number.", raw_text) from exc
        confidence = max(0.0, min(confidence, 1.0))

    return AIFeedbackResult(
        suggested_score=suggested_score,
        max_mark=max_mark,
        feedback_text=str(feedback_text),
        reason=str(reason),
        confidence=confidence,
        raw_output=raw_text,
    )


BACKEND_OPTIONAL_PYTHON_MODULE = "optional_python_module"

_BACKEND_FUNCTION_NAME = "generate_kertas2_feedback"
_BACKEND_CLASS_NAME = "LocalKertas2FeedbackBackend"
_BACKEND_CLASS_METHOD_NAME = "generate"


def _is_url_like_backend_path(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or "localhost" in lowered


def load_optional_python_backend(module_path: Optional[str]):
    """Dynamically load a single local Python file as the optional_python_module
    backend plugin.

    SECURITY: this executes an arbitrary local .py file as Python code.
    Only ever point the local AI settings' model_path at a local file that
    you (the developer/Admin) wrote and trust yourself - never at a
    downloaded, shared, or otherwise untrusted file. This function never
    fetches anything over a network: it only reads a path already present
    on local disk, and rejects URL-like paths outright.

    Raises DependencyUnavailableError with a clear message if module_path is
    missing, URL-like, does not point to an existing file, or fails to
    execute as Python.
    """
    if not module_path or not module_path.strip():
        raise DependencyUnavailableError(
            "No local Python backend file is configured for optional_python_module."
        )
    if _is_url_like_backend_path(module_path):
        raise DependencyUnavailableError(
            "Local AI backend module path must be a local file path, not a URL or network address."
        )
    if not os.path.isfile(module_path):
        raise DependencyUnavailableError(
            f"Configured local AI backend module file does not exist: {module_path}"
        )

    spec = importlib.util.spec_from_file_location("local_kertas2_feedback_backend", module_path)
    if spec is None or spec.loader is None:
        raise DependencyUnavailableError(
            f"Could not load local AI backend module file: {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise DependencyUnavailableError(
            f"Local AI backend module file failed to load: {exc}"
        ) from exc
    return module


def validate_backend_contract(backend) -> None:
    """Confirm backend exposes one of the two supported interfaces:

    - a generate_kertas2_feedback(prompt, input_data) function, or
    - a LocalKertas2FeedbackBackend class with a generate(prompt, input_data) method.

    Raises DependencyUnavailableError with a clear message if neither is present.
    """
    function = getattr(backend, _BACKEND_FUNCTION_NAME, None)
    if callable(function):
        return

    backend_class = getattr(backend, _BACKEND_CLASS_NAME, None)
    if backend_class is not None and callable(getattr(backend_class, _BACKEND_CLASS_METHOD_NAME, None)):
        return

    raise DependencyUnavailableError(
        "Local AI backend module does not implement a supported interface. Expected a "
        f"'{_BACKEND_FUNCTION_NAME}(prompt, input_data)' function or a "
        f"'{_BACKEND_CLASS_NAME}.{_BACKEND_CLASS_METHOD_NAME}(prompt, input_data)' method."
    )


def call_optional_python_backend(backend, prompt: str, input_data: dict) -> str:
    """Call an already-loaded optional_python_module backend's supported
    interface and return its raw text output.

    Raises AIProviderExecutionError (readable) if the backend's own
    function/method raises, or if it returns something other than a
    string. Does not parse the output - see parse_ai_feedback_output for
    that, and let its errors (AIFeedbackParseError) flow through the
    existing parser/audit path unchanged.
    """
    try:
        function = getattr(backend, _BACKEND_FUNCTION_NAME, None)
        if callable(function):
            raw_output = function(prompt, input_data)
        else:
            backend_class = getattr(backend, _BACKEND_CLASS_NAME)
            raw_output = backend_class().generate(prompt, input_data)
    except Exception as exc:
        raise AIProviderExecutionError(
            f"Local AI backend raised an error while generating feedback: {exc}"
        ) from exc

    if not isinstance(raw_output, str):
        raise AIProviderExecutionError(
            f"Local AI backend must return a string of raw text, got {type(raw_output).__name__}."
        )
    return raw_output


class LocalAIFeedbackProvider:
    """Adapter for a local/offline AI feedback model.

    Construction reads the current teacher's local_ai_settings row (see
    app/services/local_ai_settings_service.py - Stage 10B made settings
    per-teacher) and runs its fully offline diagnostic (enabled? model file
    present? optional backend module loadable and contract-valid?) - it
    never installs, downloads, or calls out to any cloud/network/localhost
    service.

    When backend_name is optional_python_module, generate_feedback loads
    and calls a developer-provided local Python file (see
    load_optional_python_backend / validate_backend_contract /
    call_optional_python_backend above) and parses its raw text output via
    parse_ai_feedback_output - the same parser/audit path used everywhere
    else in this module.
    """

    def __init__(self, conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> None:
        from app.services.local_ai_settings_service import validate_local_ai_settings

        diagnostic = validate_local_ai_settings(conn, teacher_id)
        if not diagnostic.is_available:
            raise DependencyUnavailableError(diagnostic.message)

        self._backend_name = diagnostic.backend_name
        self._model_path = diagnostic.model_path
        self._backend = None

        if self._backend_name == BACKEND_OPTIONAL_PYTHON_MODULE:
            backend = load_optional_python_backend(self._model_path)
            validate_backend_contract(backend)
            self._backend = backend

    def generate_feedback(self, input_data: AIFeedbackInput) -> AIFeedbackResult:
        prompt = build_kertas2_feedback_prompt(input_data)

        if self._backend_name == BACKEND_OPTIONAL_PYTHON_MODULE:
            input_dict = {
                "criterion_name": input_data.criterion_name,
                "question_type": input_data.question_type,
                "student_answer": input_data.student_answer,
                "sample_answer": input_data.sample_answer,
                "max_mark": input_data.max_mark,
                "rubric_notes": input_data.rubric_notes,
            }
            raw_output = call_optional_python_backend(self._backend, prompt, input_dict)
            return parse_ai_feedback_output(raw_output, input_data.max_mark)

        raise DependencyUnavailableError(
            f"Local AI backend '{self._backend_name}' is configured and available, but real model "
            "inference is not implemented yet in this foundation stage."
        )


def get_default_provider(conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> AIFeedbackProvider:
    """Return the default (local/offline) AI feedback provider, configured
    from teacher_id's local_ai_settings row on conn (or the legacy/global
    row if teacher_id is None).

    Raises DependencyUnavailableError if no local provider is configured or
    available - callers should catch this and surface a clear message
    instead of crashing or faking a result.
    """
    return LocalAIFeedbackProvider(conn, teacher_id)
