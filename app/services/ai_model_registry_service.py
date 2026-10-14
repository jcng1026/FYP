"""AI model registry service (Stage 12A foundation).

Provides teacher-owned CRUD over trained model versions and training jobs
for the two confirmed Stage 12 models (Core AI 1: Kertas 2 short-answer
scoring, Core AI 2: answer region detection) and the optional scan-quality
classifier - see docs/stage12_ai_plan.md for the locked AI direction.

Nothing in this module trains a model, loads a model, or does any real ML
work: it only records version/job metadata (paths, metrics, progress,
status) so a future training stage (12B+) has a safe, tested place to
write real results into. No ML library (torch, transformers,
sentence-transformers, ultralytics, sklearn, etc.) is imported anywhere in
this file or its dependencies.
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from app.models.ai_model_registry_model import (
    ALL_JOB_STATUSES,
    ALL_MODEL_KEYS,
    ALL_MODEL_TYPES,
    JOB_STATUS_RUNNING,
    MODEL_KEY_ANSWER_REGION_DETECTION,
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
    MODEL_TYPE_CROSS_ENCODER,
    MODEL_TYPE_YOLO_DETECTOR,
    AIModelVersion,
    AITrainingJob,
    activate_model_version,
    complete_training_job as complete_training_job_record,
    create_model_version,
    create_training_job as create_training_job_record,
    deactivate_model_versions_for_key,
    fail_training_job as fail_training_job_record,
    get_active_model_version,
    get_model_version_by_id,
    get_model_versions_for_teacher,
    get_training_job_by_id,
    get_training_jobs_for_teacher,
    set_training_job_log_path,
    update_model_version_metrics as update_model_version_metrics_record,
    update_training_job_progress as update_training_job_progress_record,
)
from app.services.user_service import validate_ai_manager_exists


@dataclass
class AIModelSpec:
    """Static description of one Stage 12 model - drives both the AI
    Models page UI and the model registry's validated model_key/model_type
    vocabulary. The registry holds exactly two families: Core AI 1 (Kertas 2
    scoring) and Core AI 2 (answer-region detection)."""
    model_key: str
    model_name: str
    model_type: str
    purpose: str
    technique: str


def get_supported_ai_model_specs() -> List[AIModelSpec]:
    """Return the two supported model families, in display order.
    Purely static/descriptive - no database access, no ML dependency."""
    return [
        AIModelSpec(
            model_key=MODEL_KEY_K2_SHORT_ANSWER_SCORING,
            model_name="Kertas 2 Short-Answer Scoring",
            model_type=MODEL_TYPE_CROSS_ENCODER,
            purpose="Predict a draft score and feedback category for Kertas 2 short-answer responses.",
            technique="Transformer Cross-Encoder",
        ),
        AIModelSpec(
            model_key=MODEL_KEY_ANSWER_REGION_DETECTION,
            model_name="Answer Region Detection",
            model_type=MODEL_TYPE_YOLO_DETECTOR,
            purpose="Detect answer/question regions directly on a scanned page image.",
            technique="YOLO nano/small object detection",
        ),
    ]


def get_ai_model_spec(model_key: str) -> Optional[AIModelSpec]:
    for spec in get_supported_ai_model_specs():
        if spec.model_key == model_key:
            return spec
    return None


def _validate_model_key(model_key: str) -> None:
    if model_key not in ALL_MODEL_KEYS:
        raise ValueError(f"Unknown model_key: {model_key!r}. Allowed: {', '.join(ALL_MODEL_KEYS)}.")


def _validate_model_type(model_type: str) -> None:
    if model_type not in ALL_MODEL_TYPES:
        raise ValueError(f"Unknown model_type: {model_type!r}. Allowed: {', '.join(ALL_MODEL_TYPES)}.")


def _validate_status(status: str) -> None:
    if status not in ALL_JOB_STATUSES:
        raise ValueError(f"Unknown training job status: {status!r}. Allowed: {', '.join(ALL_JOB_STATUSES)}.")


def _validate_progress(progress_percent: float) -> None:
    if progress_percent < 0 or progress_percent > 100:
        raise ValueError(f"progress_percent must be between 0 and 100, got {progress_percent!r}.")


def _get_owned_model_version(conn: sqlite3.Connection, teacher_id: int, model_id: int) -> AIModelVersion:
    version = get_model_version_by_id(conn, model_id)
    if version is None:
        raise ValueError("AI model version not found.")
    if version.teacher_id != teacher_id:
        raise ValueError("You can only manage your own AI model versions.")
    return version


def _get_owned_training_job(conn: sqlite3.Connection, teacher_id: int, job_id: int) -> AITrainingJob:
    job = get_training_job_by_id(conn, job_id)
    if job is None:
        raise ValueError("AI training job not found.")
    if job.teacher_id != teacher_id:
        raise ValueError("You can only manage your own AI training jobs.")
    return job


def register_ai_model_version(
    conn: sqlite3.Connection, teacher_id: int, model_key: str, version_label: str,
    model_path: Optional[str] = None, metrics_json: Optional[str] = None,
    config_json: Optional[str] = None, notes: str = "",
) -> AIModelVersion:
    """Register a new model version row (Stage 12A foundation - does not
    require model_path to exist on disk, since no real training happens
    yet; a future training stage should pass a real path once one exists).
    Raises ValueError if teacher_id isn't a teacher or model_key is
    unknown."""
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can register AI model versions.")
    _validate_model_key(model_key)
    spec = get_ai_model_spec(model_key)
    version_label = (version_label or "").strip()
    if not version_label:
        raise ValueError("version_label is required.")
    return create_model_version(
        conn, teacher_id, model_key, spec.model_name, spec.model_type, version_label,
        model_path=model_path, metrics_json=metrics_json, config_json=config_json, notes=notes or None,
    )


def list_ai_model_versions(
    conn: sqlite3.Connection, teacher_id: int, model_key: Optional[str] = None
) -> List[AIModelVersion]:
    if model_key is not None:
        _validate_model_key(model_key)
    return get_model_versions_for_teacher(conn, teacher_id, model_key)


def get_active_ai_model_version(conn: sqlite3.Connection, teacher_id: int, model_key: str) -> Optional[AIModelVersion]:
    _validate_model_key(model_key)
    return get_active_model_version(conn, teacher_id, model_key)


def set_active_ai_model_version(conn: sqlite3.Connection, teacher_id: int, model_id: int) -> AIModelVersion:
    """Activate model_id, deactivating any other active version owned by
    teacher_id for the same model_key first - only one active model per
    teacher per model_key (also enforced at the database level by a
    partial unique index - see app/database/schema.py)."""
    version = _get_owned_model_version(conn, teacher_id, model_id)
    deactivate_model_versions_for_key(conn, teacher_id, version.model_key)
    activate_model_version(conn, model_id)
    return _get_owned_model_version(conn, teacher_id, model_id)


def update_ai_model_version_metrics(
    conn: sqlite3.Connection, teacher_id: int, model_id: int, metrics_json: str
) -> AIModelVersion:
    """Overwrite an owned model version's metrics_json (Stage 12D - used to
    attach evaluation results to an already-trained version). Raises
    ValueError if model_id doesn't exist or isn't owned by teacher_id."""
    _get_owned_model_version(conn, teacher_id, model_id)
    update_model_version_metrics_record(conn, model_id, metrics_json)
    return _get_owned_model_version(conn, teacher_id, model_id)


def create_ai_training_job(
    conn: sqlite3.Connection, teacher_id: int, model_key: str, model_type: str,
    config_json: Optional[str] = None,
) -> AITrainingJob:
    """Create a queued training job row. Does NOT launch any real training
    process - Stage 12A is registry foundation only."""
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create AI training jobs.")
    _validate_model_key(model_key)
    _validate_model_type(model_type)
    job = create_training_job_record(conn, teacher_id, model_key, model_type, config_json=config_json)
    from app.utils.file_storage import get_ai_training_job_log_path
    log_path = get_ai_training_job_log_path(teacher_id, model_key, job.job_id)
    set_training_job_log_path(conn, job.job_id, str(log_path))
    return _get_owned_training_job(conn, teacher_id, job.job_id)


def update_ai_training_job_progress(
    conn: sqlite3.Connection, teacher_id: int, job_id: int, progress_percent: float,
    current_step: Optional[str], status: Optional[str] = None, message: Optional[str] = None,
) -> AITrainingJob:
    _get_owned_training_job(conn, teacher_id, job_id)
    _validate_progress(progress_percent)
    if status is not None:
        _validate_status(status)
    update_training_job_progress_record(conn, job_id, progress_percent, current_step, status=status)
    if message is not None:
        from app.models.ai_model_registry_model import set_training_job_message
        set_training_job_message(conn, job_id, message)
    return _get_owned_training_job(conn, teacher_id, job_id)


def complete_ai_training_job(
    conn: sqlite3.Connection, teacher_id: int, job_id: int, output_model_id: Optional[int] = None,
    metrics_json: Optional[str] = None, message: str = "",
) -> AITrainingJob:
    _get_owned_training_job(conn, teacher_id, job_id)
    if output_model_id is not None:
        _get_owned_model_version(conn, teacher_id, output_model_id)
    complete_training_job_record(conn, job_id, output_model_id, metrics_json, message)
    return _get_owned_training_job(conn, teacher_id, job_id)


def fail_ai_training_job(conn: sqlite3.Connection, teacher_id: int, job_id: int, message: str) -> AITrainingJob:
    _get_owned_training_job(conn, teacher_id, job_id)
    fail_training_job_record(conn, job_id, message)
    return _get_owned_training_job(conn, teacher_id, job_id)


def list_ai_training_jobs(
    conn: sqlite3.Connection, teacher_id: int, model_key: Optional[str] = None, limit: int = 20
) -> List[AITrainingJob]:
    if model_key is not None:
        _validate_model_key(model_key)
    return get_training_jobs_for_teacher(conn, teacher_id, model_key, limit)


def get_ai_training_job(conn: sqlite3.Connection, teacher_id: int, job_id: int) -> AITrainingJob:
    return _get_owned_training_job(conn, teacher_id, job_id)
