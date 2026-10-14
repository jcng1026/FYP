"""Local AI provider configuration data model and database access functions.

Stage 10B: settings are per-teacher. Each teacher may have at most one
settings row (enforced by a partial unique index on teacher_id where
teacher_id IS NOT NULL - see app/database/schema.py). A row with
teacher_id = NULL is the legacy/global row that existed before per-teacher
settings were introduced; it is preserved as a read fallback for teachers
who have not yet saved their own settings, but is never written to by the
per-teacher save path. There are no API key fields anywhere in this table -
only local/offline provider configuration (backend name and a local model
file path) is represented.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

DEFAULT_PROVIDER_NAME = "local"
DEFAULT_BACKEND_NAME = "none"
DEFAULT_MODEL_PATH = ""
DEFAULT_IS_ENABLED = False

BACKEND_NONE = "none"
BACKEND_OPTIONAL_PYTHON_MODULE = "optional_python_module"
ALLOWED_BACKEND_NAMES = (BACKEND_NONE, BACKEND_OPTIONAL_PYTHON_MODULE)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class LocalAISettings:
    setting_id: int
    teacher_id: Optional[int]
    provider_name: str
    backend_name: str
    model_path: Optional[str]
    is_enabled: bool
    created_at: str
    updated_at: str


def _row_to_settings(row) -> LocalAISettings:
    data = dict(row)
    data["is_enabled"] = bool(data["is_enabled"])
    return LocalAISettings(**data)


def create_default_settings(conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> LocalAISettings:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO local_ai_settings "
        "(teacher_id, provider_name, backend_name, model_path, is_enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (teacher_id, DEFAULT_PROVIDER_NAME, DEFAULT_BACKEND_NAME, DEFAULT_MODEL_PATH, 0, now, now),
    )
    conn.commit()
    return LocalAISettings(
        setting_id=cursor.lastrowid,
        teacher_id=teacher_id,
        provider_name=DEFAULT_PROVIDER_NAME,
        backend_name=DEFAULT_BACKEND_NAME,
        model_path=DEFAULT_MODEL_PATH,
        is_enabled=DEFAULT_IS_ENABLED,
        created_at=now,
        updated_at=now,
    )


def get_local_ai_settings(conn: sqlite3.Connection, teacher_id: Optional[int] = None) -> Optional[LocalAISettings]:
    """Return teacher_id's settings row, or the legacy/global row if
    teacher_id is None. Returns None if no such row exists yet."""
    if teacher_id is None:
        row = conn.execute(
            "SELECT setting_id, teacher_id, provider_name, backend_name, model_path, is_enabled, "
            "created_at, updated_at FROM local_ai_settings WHERE teacher_id IS NULL "
            "ORDER BY setting_id ASC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT setting_id, teacher_id, provider_name, backend_name, model_path, is_enabled, "
            "created_at, updated_at FROM local_ai_settings WHERE teacher_id = ? LIMIT 1",
            (teacher_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_settings(row)


def update_settings(
    conn: sqlite3.Connection,
    setting_id: int,
    backend_name: str,
    model_path: str,
    is_enabled: bool,
) -> None:
    conn.execute(
        "UPDATE local_ai_settings SET backend_name = ?, model_path = ?, is_enabled = ?, updated_at = ? "
        "WHERE setting_id = ?",
        (backend_name, model_path, 1 if is_enabled else 0, _now(), setting_id),
    )
    conn.commit()


# --- Stage 12G-7: per-teacher local natural-language feedback runtime -------
#
# These columns configure WHICH local runtime a teacher's Kertas 2 natural
# feedback goes to (adapter + localhost endpoint + model name + limits). They
# are additive and default to a fully disabled 'none' adapter, so a teacher who
# configures nothing keeps the existing template-only behaviour. There are
# still no API key fields, and no cloud provider is representable.

ADAPTER_NONE = "none"
ADAPTER_OPENAI = "openai"
ADAPTER_OLLAMA = "ollama"
ALLOWED_FEEDBACK_ADAPTERS = (ADAPTER_NONE, ADAPTER_OPENAI, ADAPTER_OLLAMA)

DEFAULT_FEEDBACK_TIMEOUT_SECONDS = 15.0
DEFAULT_FEEDBACK_MAX_OUTPUT_TOKENS = 180
DEFAULT_FEEDBACK_TEMPERATURE = 0.2
DEFAULT_FEEDBACK_RESPONSE_SIZE_LIMIT = 8192
DEFAULT_FEEDBACK_REQUESTED_LENGTH = 500

_RUNTIME_COLUMNS = (
    "feedback_adapter, feedback_endpoint, feedback_model_name, feedback_timeout_seconds, "
    "feedback_max_output_tokens, feedback_temperature, feedback_response_size_limit, "
    "feedback_requested_length, feedback_allow_private_network"
)


@dataclass
class LocalFeedbackRuntimeSettings:
    """A teacher's own local feedback runtime configuration."""
    adapter: str = ADAPTER_NONE
    endpoint: Optional[str] = None
    model_name: Optional[str] = None
    timeout_seconds: float = DEFAULT_FEEDBACK_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_FEEDBACK_MAX_OUTPUT_TOKENS
    temperature: float = DEFAULT_FEEDBACK_TEMPERATURE
    response_size_limit: int = DEFAULT_FEEDBACK_RESPONSE_SIZE_LIMIT
    requested_feedback_length: int = DEFAULT_FEEDBACK_REQUESTED_LENGTH
    allow_private_network: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.adapter != ADAPTER_NONE and self.endpoint and self.model_name)


def get_feedback_runtime_settings(conn: sqlite3.Connection,
                                  teacher_id: Optional[int]) -> LocalFeedbackRuntimeSettings:
    """A teacher's own runtime settings. A teacher with no row - or a row
    predating these columns - gets safe disabled defaults, never another
    teacher's configuration."""
    if teacher_id is None:
        row = conn.execute(
            f"SELECT {_RUNTIME_COLUMNS} FROM local_ai_settings WHERE teacher_id IS NULL "
            "ORDER BY setting_id ASC LIMIT 1").fetchone()
    else:
        row = conn.execute(
            f"SELECT {_RUNTIME_COLUMNS} FROM local_ai_settings WHERE teacher_id = ? LIMIT 1",
            (teacher_id,)).fetchone()
    if row is None:
        return LocalFeedbackRuntimeSettings()
    data = dict(row)
    return LocalFeedbackRuntimeSettings(
        adapter=data["feedback_adapter"] or ADAPTER_NONE,
        endpoint=data["feedback_endpoint"],
        model_name=data["feedback_model_name"],
        timeout_seconds=data["feedback_timeout_seconds"],
        max_output_tokens=data["feedback_max_output_tokens"],
        temperature=data["feedback_temperature"],
        response_size_limit=data["feedback_response_size_limit"],
        requested_feedback_length=data["feedback_requested_length"],
        allow_private_network=bool(data["feedback_allow_private_network"]))


def update_feedback_runtime_settings(conn: sqlite3.Connection, setting_id: int,
                                     runtime: LocalFeedbackRuntimeSettings) -> None:
    conn.execute(
        "UPDATE local_ai_settings SET feedback_adapter = ?, feedback_endpoint = ?, "
        "feedback_model_name = ?, feedback_timeout_seconds = ?, feedback_max_output_tokens = ?, "
        "feedback_temperature = ?, feedback_response_size_limit = ?, feedback_requested_length = ?, "
        "feedback_allow_private_network = ?, updated_at = ? WHERE setting_id = ?",
        (runtime.adapter, runtime.endpoint, runtime.model_name, runtime.timeout_seconds,
         runtime.max_output_tokens, runtime.temperature, runtime.response_size_limit,
         runtime.requested_feedback_length, 1 if runtime.allow_private_network else 0,
         _now(), setting_id))
    conn.commit()
