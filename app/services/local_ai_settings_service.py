"""Local AI provider configuration and diagnostic service (per-teacher,
Stage 10B).

Configuration is intentionally minimal and local-only: no API key fields,
no cloud provider names, and the diagnostic check never makes a network or
localhost call - it only inspects local configuration state (is it
enabled? does the model file exist? is the optional backend's Python
module importable?). No real model is ever loaded or downloaded here.

Each teacher owns their own settings row (teacher_id). A legacy/global row
(teacher_id = NULL) may still exist from before per-teacher settings were
introduced; it is preserved only so a pre-existing database does not crash
on lookup - it is NOT used as a fallback for teacher-owned behavior. A
teacher who has not saved their own settings yet always gets fresh, safe
defaults (disabled, backend='none', empty model path), never another
teacher's or the legacy row's configured values. Saving always creates or
updates a row scoped to that specific teacher - it never mutates the
legacy row or another teacher's row.
"""

import os
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.models.local_ai_settings_model import (
    ALLOWED_BACKEND_NAMES,
    BACKEND_NONE,
    BACKEND_OPTIONAL_PYTHON_MODULE,
    LocalAISettings,
    create_default_settings,
    get_local_ai_settings,
    update_settings,
)
from app.utils.ai_feedback_engine import (
    DependencyUnavailableError,
    load_optional_python_backend,
    validate_backend_contract,
)

_CLOUD_LIKE_BACKEND_KEYWORDS = (
    "openai", "anthropic", "google", "gemini", "claude", "gpt", "azure", "aws", "cloud", "api",
)

STATUS_DISABLED = "disabled"
STATUS_MODEL_PATH_MISSING = "model_path_missing"
STATUS_BACKEND_UNAVAILABLE = "backend_unavailable"
STATUS_AVAILABLE = "available"

MESSAGE_NOT_CONFIGURED = "Local AI provider is not configured."
MESSAGE_MODEL_PATH_MISSING = "Configured local AI model path does not exist."
MESSAGE_BACKEND_UNAVAILABLE = "Configured local AI backend is not available."
MESSAGE_AVAILABLE = "Local AI provider is available."


@dataclass
class LocalAIDiagnosticResult:
    is_available: bool
    status: str
    message: str
    backend_name: str
    model_path: Optional[str]


def get_or_create_local_ai_settings(conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> LocalAISettings:
    """Return teacher_id's own settings row, creating safe disabled defaults
    (backend='none', empty model path) if none exists yet.

    Never borrows another owner's settings: a teacher_id with no row of its
    own always gets fresh defaults, not the legacy/global row's configured
    values and not another teacher's values - each teacher's Local AI
    Settings are fully isolated. Passing teacher_id=None addresses the
    legacy/global row directly (preserved only so a pre-existing database
    does not crash on lookup); it is never read as a fallback for a real
    teacher_id.
    """
    settings = get_local_ai_settings(conn, teacher_id)
    if settings is not None:
        return settings
    return create_default_settings(conn, teacher_id)


def _is_cloud_like_backend(name: str) -> bool:
    lowered = name.strip().lower()
    return any(keyword in lowered for keyword in _CLOUD_LIKE_BACKEND_KEYWORDS)


def _is_url_like(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or "localhost" in lowered


def update_local_ai_settings(
    conn: sqlite3.Connection,
    teacher_id: Optional[int],
    backend_name: str,
    model_path: str,
    is_enabled: bool,
) -> LocalAISettings:
    """Validate and save teacher_id's own settings row.

    Raises ValueError for cloud-like or otherwise unsupported backend
    names, URL-like model paths, or an empty model_path while is_enabled
    is True. Does NOT require model_path to exist on disk - a teacher may
    save an enabled configuration before the model file is actually in
    place; use validate_local_ai_settings for that check. Always creates
    or updates a row scoped to teacher_id - never the legacy/global row or
    another teacher's row, so different teachers' settings stay isolated.
    """
    if _is_cloud_like_backend(backend_name):
        raise ValueError(
            f"Cloud AI backends are not supported: '{backend_name}'. Only local/offline backends are allowed."
        )
    if backend_name not in ALLOWED_BACKEND_NAMES:
        raise ValueError(
            f"Unsupported local AI backend: '{backend_name}'. Allowed backends: {', '.join(ALLOWED_BACKEND_NAMES)}."
        )
    if model_path and _is_url_like(model_path):
        raise ValueError("Model path must be a local file path, not a URL or network address.")
    if is_enabled and not model_path.strip():
        raise ValueError("Model path is required when local AI is enabled.")

    settings = get_or_create_local_ai_settings(conn, teacher_id)
    update_settings(conn, settings.setting_id, backend_name, model_path, is_enabled)
    return get_local_ai_settings(conn, teacher_id)


def validate_local_ai_settings(conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> LocalAIDiagnosticResult:
    """Run a safe, fully offline diagnostic against teacher_id's settings
    (or the legacy/global settings if teacher_id is None).

    Never makes a network/localhost call and never loads a real AI model -
    only checks configuration state, local file existence, and (for
    optional_python_module) whether the configured local Python file loads
    and implements a supported backend interface.
    """
    settings = get_or_create_local_ai_settings(conn, teacher_id)

    if not settings.is_enabled or settings.backend_name == BACKEND_NONE:
        return LocalAIDiagnosticResult(
            is_available=False,
            status=STATUS_DISABLED,
            message=MESSAGE_NOT_CONFIGURED,
            backend_name=settings.backend_name,
            model_path=settings.model_path,
        )

    if not settings.model_path or not os.path.isfile(settings.model_path):
        return LocalAIDiagnosticResult(
            is_available=False,
            status=STATUS_MODEL_PATH_MISSING,
            message=MESSAGE_MODEL_PATH_MISSING,
            backend_name=settings.backend_name,
            model_path=settings.model_path,
        )

    if settings.backend_name == BACKEND_OPTIONAL_PYTHON_MODULE:
        try:
            backend = load_optional_python_backend(settings.model_path)
            validate_backend_contract(backend)
        except DependencyUnavailableError:
            return LocalAIDiagnosticResult(
                is_available=False,
                status=STATUS_BACKEND_UNAVAILABLE,
                message=MESSAGE_BACKEND_UNAVAILABLE,
                backend_name=settings.backend_name,
                model_path=settings.model_path,
            )

    return LocalAIDiagnosticResult(
        is_available=True,
        status=STATUS_AVAILABLE,
        message=MESSAGE_AVAILABLE,
        backend_name=settings.backend_name,
        model_path=settings.model_path,
    )


# --- Stage 12G-7: per-teacher local feedback runtime configuration ----------
#
# The runtime a teacher points at is validated with the SAME localhost/private
# allow-list the AI backend enforces, so a configuration the backend would
# reject can never be saved in the first place. Validation is purely local -
# saving and diagnosing never open a network connection.

import ipaddress as _ipaddress
from urllib.parse import urlparse as _urlparse

from app.models.local_ai_settings_model import (
    ADAPTER_NONE,
    ALLOWED_FEEDBACK_ADAPTERS,
    LocalFeedbackRuntimeSettings,
    get_feedback_runtime_settings,
    update_feedback_runtime_settings,
)

RUNTIME_STATUS_NOT_CONFIGURED = "not_configured"
RUNTIME_STATUS_CONFIGURED = "configured"

MAX_FEEDBACK_TIMEOUT_SECONDS = 120.0
MAX_FEEDBACK_OUTPUT_TOKENS = 2048
MAX_FEEDBACK_RESPONSE_SIZE_LIMIT = 1_048_576
MAX_FEEDBACK_REQUESTED_LENGTH = 4000


def endpoint_is_allowed(endpoint: Optional[str], allow_private_network: bool = False) -> bool:
    """Mirror of the backend's endpoint allow-list: http/https to localhost or
    a loopback address, plus private addresses only when the teacher has
    explicitly allowed them. Any public host is rejected."""
    if not endpoint:
        return False
    parsed = _urlparse(endpoint)
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = _ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    return bool(allow_private_network and ip.is_private)


def validate_feedback_runtime(runtime: LocalFeedbackRuntimeSettings) -> list:
    """Every reason this configuration cannot be used, in teacher-readable
    wording. An empty list means it is usable."""
    problems = []
    if runtime.adapter not in ALLOWED_FEEDBACK_ADAPTERS:
        problems.append(f"'{runtime.adapter}' is not a supported local adapter.")
    if runtime.adapter == ADAPTER_NONE:
        return problems
    if not runtime.model_name or not str(runtime.model_name).strip():
        problems.append("A local model name is required.")
    if not runtime.endpoint:
        problems.append("A local endpoint address is required.")
    elif not endpoint_is_allowed(runtime.endpoint, runtime.allow_private_network):
        problems.append(
            "The endpoint must be a local address (localhost or 127.0.0.1). Cloud and public "
            "network addresses are not supported."
            + ("" if runtime.allow_private_network
               else " Tick 'allow private network' to use another machine on your local network."))
    if not 0 < runtime.timeout_seconds <= MAX_FEEDBACK_TIMEOUT_SECONDS:
        problems.append(f"Timeout must be between 0 and {MAX_FEEDBACK_TIMEOUT_SECONDS:g} seconds.")
    if not 0 < runtime.max_output_tokens <= MAX_FEEDBACK_OUTPUT_TOKENS:
        problems.append(f"Maximum output tokens must be between 1 and {MAX_FEEDBACK_OUTPUT_TOKENS}.")
    if not 0 <= runtime.temperature <= 2:
        problems.append("Temperature must be between 0 and 2.")
    if not 0 < runtime.response_size_limit <= MAX_FEEDBACK_RESPONSE_SIZE_LIMIT:
        problems.append(
            f"Response size limit must be between 1 and {MAX_FEEDBACK_RESPONSE_SIZE_LIMIT} bytes.")
    if not 0 < runtime.requested_feedback_length <= MAX_FEEDBACK_REQUESTED_LENGTH:
        problems.append(
            f"Feedback length must be between 1 and {MAX_FEEDBACK_REQUESTED_LENGTH} characters.")
    return problems


def get_teacher_feedback_runtime(conn, teacher_id: Optional[int]) -> LocalFeedbackRuntimeSettings:
    """The teacher's own runtime settings, creating their settings row if this
    is their first visit. Never returns another teacher's configuration."""
    get_or_create_local_ai_settings(conn, teacher_id)
    return get_feedback_runtime_settings(conn, teacher_id)


def save_teacher_feedback_runtime(conn, teacher_id: Optional[int],
                                  runtime: LocalFeedbackRuntimeSettings
                                  ) -> LocalFeedbackRuntimeSettings:
    """Save a teacher's own runtime settings after validating them. Raises
    ValueError listing every problem; writes nothing when invalid."""
    problems = validate_feedback_runtime(runtime)
    if problems:
        raise ValueError("\n".join(problems))
    settings = get_or_create_local_ai_settings(conn, teacher_id)
    update_feedback_runtime_settings(conn, settings.setting_id, runtime)
    return get_feedback_runtime_settings(conn, teacher_id)


def describe_feedback_runtime(runtime: LocalFeedbackRuntimeSettings) -> dict:
    """A local-only readiness report. Makes NO network call - it reports what
    is configured and whether the configuration is usable."""
    problems = validate_feedback_runtime(runtime)
    configured = runtime.is_configured and not problems
    return {
        "status": RUNTIME_STATUS_CONFIGURED if configured else RUNTIME_STATUS_NOT_CONFIGURED,
        "configured": configured,
        "adapter": runtime.adapter,
        "endpoint": runtime.endpoint or "-",
        "model_name": runtime.model_name or "-",
        "problems": problems,
        "message": ("This local runtime is configured. Natural feedback will use it, and fall "
                    "back to the built-in templates whenever it is unavailable."
                    if configured else
                    "No local runtime is configured. Natural feedback uses the built-in "
                    "templates, which always work offline."),
    }
