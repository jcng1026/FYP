"""AI model registry data model (Stage 12A foundation).

Deliberately separate from app.models.local_ai_settings_model:
local_ai_settings configures the teacher's LOCAL AI BACKEND for Kertas 2
draft feedback generation (which pluggable backend to call and its model
file path) - it has nothing to do with trained model versions. The tables
here are this project's OWN model registry - trained model versions (Core
AI 1's Cross-Encoder, Core AI 2's YOLO detector, and the optional scan-
quality classifier), their training jobs/progress/logs, and which version
is "active" per teacher per model_key.

No training happens here or anywhere in Stage 12A - this module only
provides CRUD over the registry tables so a future training stage (12B+)
has a safe, tested place to record versions/jobs.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

MODEL_KEY_K2_SHORT_ANSWER_SCORING = "k2_short_answer_scoring"
MODEL_KEY_ANSWER_REGION_DETECTION = "answer_region_detection"

# Only Core AI 1 (Kertas 2 scoring) and Core AI 2 (answer-region detection)
# belong in the global registry.
ALL_MODEL_KEYS = (
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
    MODEL_KEY_ANSWER_REGION_DETECTION,
)

MODEL_TYPE_CROSS_ENCODER = "cross_encoder"
MODEL_TYPE_YOLO_DETECTOR = "yolo_detector"

ALL_MODEL_TYPES = (MODEL_TYPE_CROSS_ENCODER, MODEL_TYPE_YOLO_DETECTOR)

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"

ALL_JOB_STATUSES = (
    JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class AIModelVersion:
    model_id: int
    teacher_id: int
    model_key: str
    model_name: str
    model_type: str
    version_label: str
    model_path: Optional[str]
    metrics_json: Optional[str]
    config_json: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class AITrainingJob:
    job_id: int
    teacher_id: int
    model_key: str
    model_type: str
    status: str
    progress_percent: float
    current_step: Optional[str]
    log_path: Optional[str]
    output_model_id: Optional[int]
    config_json: Optional[str]
    metrics_json: Optional[str]
    message: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    updated_at: str


def _row_to_model_version(row) -> AIModelVersion:
    data = dict(row)
    data["is_active"] = bool(data["is_active"])
    return AIModelVersion(**data)


def _row_to_training_job(row) -> AITrainingJob:
    return AITrainingJob(**dict(row))


_MODEL_VERSION_COLUMNS = (
    "model_id, teacher_id, model_key, model_name, model_type, version_label, model_path, "
    "metrics_json, config_json, notes, is_active, created_at, updated_at"
)

_TRAINING_JOB_COLUMNS = (
    "job_id, teacher_id, model_key, model_type, status, progress_percent, current_step, log_path, "
    "output_model_id, config_json, metrics_json, message, created_at, started_at, completed_at, updated_at"
)


def create_model_version(
    conn: sqlite3.Connection, teacher_id: int, model_key: str, model_name: str, model_type: str,
    version_label: str, model_path: Optional[str] = None, metrics_json: Optional[str] = None,
    config_json: Optional[str] = None, notes: Optional[str] = None,
) -> AIModelVersion:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ai_model_versions "
        "(teacher_id, model_key, model_name, model_type, version_label, model_path, metrics_json, "
        "config_json, notes, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (teacher_id, model_key, model_name, model_type, version_label, model_path, metrics_json,
         config_json, notes, now, now),
    )
    conn.commit()
    return AIModelVersion(
        model_id=cursor.lastrowid, teacher_id=teacher_id, model_key=model_key, model_name=model_name,
        model_type=model_type, version_label=version_label, model_path=model_path, metrics_json=metrics_json,
        config_json=config_json, notes=notes, is_active=False, created_at=now, updated_at=now,
    )


def get_model_version_by_id(conn: sqlite3.Connection, model_id: int) -> Optional[AIModelVersion]:
    row = conn.execute(
        f"SELECT {_MODEL_VERSION_COLUMNS} FROM ai_model_versions WHERE model_id = ?", (model_id,)
    ).fetchone()
    return _row_to_model_version(row) if row is not None else None


def get_model_versions_for_teacher(
    conn: sqlite3.Connection, teacher_id: int, model_key: Optional[str] = None
) -> List[AIModelVersion]:
    if model_key is None:
        rows = conn.execute(
            f"SELECT {_MODEL_VERSION_COLUMNS} FROM ai_model_versions WHERE teacher_id = ? "
            "ORDER BY created_at DESC, model_id DESC",
            (teacher_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_MODEL_VERSION_COLUMNS} FROM ai_model_versions WHERE teacher_id = ? AND model_key = ? "
            "ORDER BY created_at DESC, model_id DESC",
            (teacher_id, model_key),
        ).fetchall()
    return [_row_to_model_version(row) for row in rows]


def get_active_model_version(conn: sqlite3.Connection, teacher_id: int, model_key: str) -> Optional[AIModelVersion]:
    row = conn.execute(
        f"SELECT {_MODEL_VERSION_COLUMNS} FROM ai_model_versions "
        "WHERE teacher_id = ? AND model_key = ? AND is_active = 1 LIMIT 1",
        (teacher_id, model_key),
    ).fetchone()
    return _row_to_model_version(row) if row is not None else None


def deactivate_model_versions_for_key(conn: sqlite3.Connection, teacher_id: int, model_key: str) -> None:
    conn.execute(
        "UPDATE ai_model_versions SET is_active = 0, updated_at = ? WHERE teacher_id = ? AND model_key = ?",
        (_now(), teacher_id, model_key),
    )
    conn.commit()


def activate_model_version(conn: sqlite3.Connection, model_id: int) -> None:
    conn.execute(
        "UPDATE ai_model_versions SET is_active = 1, updated_at = ? WHERE model_id = ?",
        (_now(), model_id),
    )
    conn.commit()


def update_model_version_metrics(conn: sqlite3.Connection, model_id: int, metrics_json: str) -> None:
    """Overwrite a model version's metrics_json in place (Stage 12D) -
    used to merge evaluation results into an already-trained version's
    metrics without creating a new version row, since evaluating a model
    doesn't produce a new trained artifact."""
    conn.execute(
        "UPDATE ai_model_versions SET metrics_json = ?, updated_at = ? WHERE model_id = ?",
        (metrics_json, _now(), model_id),
    )
    conn.commit()


def create_training_job(
    conn: sqlite3.Connection, teacher_id: int, model_key: str, model_type: str,
    config_json: Optional[str] = None,
) -> AITrainingJob:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ai_training_jobs "
        "(teacher_id, model_key, model_type, status, progress_percent, current_step, log_path, "
        "output_model_id, config_json, metrics_json, message, created_at, started_at, completed_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, ?, NULL, NULL, ?, NULL, NULL, ?)",
        (teacher_id, model_key, model_type, JOB_STATUS_QUEUED, config_json, now, now),
    )
    conn.commit()
    return AITrainingJob(
        job_id=cursor.lastrowid, teacher_id=teacher_id, model_key=model_key, model_type=model_type,
        status=JOB_STATUS_QUEUED, progress_percent=0, current_step=None, log_path=None, output_model_id=None,
        config_json=config_json, metrics_json=None, message=None, created_at=now, started_at=None,
        completed_at=None, updated_at=now,
    )


def get_training_job_by_id(conn: sqlite3.Connection, job_id: int) -> Optional[AITrainingJob]:
    row = conn.execute(
        f"SELECT {_TRAINING_JOB_COLUMNS} FROM ai_training_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return _row_to_training_job(row) if row is not None else None


def get_training_jobs_for_teacher(
    conn: sqlite3.Connection, teacher_id: int, model_key: Optional[str] = None, limit: int = 20
) -> List[AITrainingJob]:
    if model_key is None:
        rows = conn.execute(
            f"SELECT {_TRAINING_JOB_COLUMNS} FROM ai_training_jobs WHERE teacher_id = ? "
            "ORDER BY created_at DESC, job_id DESC LIMIT ?",
            (teacher_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_TRAINING_JOB_COLUMNS} FROM ai_training_jobs WHERE teacher_id = ? AND model_key = ? "
            "ORDER BY created_at DESC, job_id DESC LIMIT ?",
            (teacher_id, model_key, limit),
        ).fetchall()
    return [_row_to_training_job(row) for row in rows]


def update_training_job_progress(
    conn: sqlite3.Connection, job_id: int, progress_percent: float, current_step: Optional[str],
    status: Optional[str] = None,
) -> None:
    if status is not None:
        started_at_clause = ", started_at = COALESCE(started_at, ?)" if status == JOB_STATUS_RUNNING else ""
        params = [progress_percent, current_step, status]
        if status == JOB_STATUS_RUNNING:
            params.append(_now())
        params.append(_now())
        params.append(job_id)
        conn.execute(
            f"UPDATE ai_training_jobs SET progress_percent = ?, current_step = ?, status = ?{started_at_clause}, "
            "updated_at = ? WHERE job_id = ?",
            params,
        )
    else:
        conn.execute(
            "UPDATE ai_training_jobs SET progress_percent = ?, current_step = ?, updated_at = ? WHERE job_id = ?",
            (progress_percent, current_step, _now(), job_id),
        )
    conn.commit()


def set_training_job_message(conn: sqlite3.Connection, job_id: int, message: str) -> None:
    conn.execute(
        "UPDATE ai_training_jobs SET message = ?, updated_at = ? WHERE job_id = ?",
        (message, _now(), job_id),
    )
    conn.commit()


def complete_training_job(
    conn: sqlite3.Connection, job_id: int, output_model_id: Optional[int], metrics_json: Optional[str],
    message: str,
) -> None:
    now = _now()
    conn.execute(
        "UPDATE ai_training_jobs SET status = ?, progress_percent = 100, output_model_id = ?, "
        "metrics_json = ?, message = ?, completed_at = ?, updated_at = ? WHERE job_id = ?",
        (JOB_STATUS_COMPLETED, output_model_id, metrics_json, message, now, now, job_id),
    )
    conn.commit()


def fail_training_job(conn: sqlite3.Connection, job_id: int, message: str) -> None:
    now = _now()
    conn.execute(
        "UPDATE ai_training_jobs SET status = ?, message = ?, completed_at = ?, updated_at = ? WHERE job_id = ?",
        (JOB_STATUS_FAILED, message, now, now, job_id),
    )
    conn.commit()


def set_training_job_log_path(conn: sqlite3.Connection, job_id: int, log_path: str) -> None:
    conn.execute(
        "UPDATE ai_training_jobs SET log_path = ?, updated_at = ? WHERE job_id = ?",
        (log_path, _now(), job_id),
    )
    conn.commit()


# --- Stage 12B: training dataset export records ------------------------------
#
# Records metadata about an exported CSV/JSONL training dataset snapshot
# (see app/services/k2_training_dataset_service.py) - the actual dataset
# rows live in files under data/ai_training_datasets/, never in this table.


@dataclass
class AITrainingDataset:
    dataset_id: int
    teacher_id: int
    model_key: str
    dataset_name: str
    dataset_format: str
    row_count: int
    csv_path: Optional[str]
    jsonl_path: Optional[str]
    summary_json: Optional[str]
    source_filter_json: Optional[str]
    created_at: str
    updated_at: str
    dataset_folder_path: Optional[str] = None


_TRAINING_DATASET_COLUMNS = (
    "dataset_id, teacher_id, model_key, dataset_name, dataset_format, row_count, csv_path, jsonl_path, "
    "summary_json, source_filter_json, created_at, updated_at, dataset_folder_path"
)


def _row_to_training_dataset(row) -> AITrainingDataset:
    return AITrainingDataset(**dict(row))


def create_training_dataset(
    conn: sqlite3.Connection, teacher_id: int, model_key: str, dataset_name: str, dataset_format: str,
    row_count: int, csv_path: Optional[str], jsonl_path: Optional[str],
    summary_json: Optional[str] = None, source_filter_json: Optional[str] = None,
    dataset_folder_path: Optional[str] = None,
) -> AITrainingDataset:
    """dataset_folder_path (Stage 12E) is for folder-of-files datasets
    (e.g. Answer Region Detection's YOLO image/label export) that
    csv_path/jsonl_path can't represent - None for Kertas 2's CSV/JSONL
    exports, which keep using csv_path/jsonl_path as before."""
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ai_training_datasets "
        "(teacher_id, model_key, dataset_name, dataset_format, row_count, csv_path, jsonl_path, "
        "summary_json, source_filter_json, created_at, updated_at, dataset_folder_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (teacher_id, model_key, dataset_name, dataset_format, row_count, csv_path, jsonl_path,
         summary_json, source_filter_json, now, now, dataset_folder_path),
    )
    conn.commit()
    return AITrainingDataset(
        dataset_id=cursor.lastrowid, teacher_id=teacher_id, model_key=model_key, dataset_name=dataset_name,
        dataset_format=dataset_format, row_count=row_count, csv_path=csv_path, jsonl_path=jsonl_path,
        summary_json=summary_json, source_filter_json=source_filter_json, created_at=now, updated_at=now,
        dataset_folder_path=dataset_folder_path,
    )


def get_training_dataset_by_id(conn: sqlite3.Connection, dataset_id: int) -> Optional[AITrainingDataset]:
    row = conn.execute(
        f"SELECT {_TRAINING_DATASET_COLUMNS} FROM ai_training_datasets WHERE dataset_id = ?", (dataset_id,)
    ).fetchone()
    return _row_to_training_dataset(row) if row is not None else None


def get_training_datasets_for_teacher(
    conn: sqlite3.Connection, teacher_id: int, model_key: Optional[str] = None, limit: int = 10
) -> List[AITrainingDataset]:
    if model_key is None:
        rows = conn.execute(
            f"SELECT {_TRAINING_DATASET_COLUMNS} FROM ai_training_datasets WHERE teacher_id = ? "
            "ORDER BY created_at DESC, dataset_id DESC LIMIT ?",
            (teacher_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_TRAINING_DATASET_COLUMNS} FROM ai_training_datasets WHERE teacher_id = ? AND model_key = ? "
            "ORDER BY created_at DESC, dataset_id DESC LIMIT ?",
            (teacher_id, model_key, limit),
        ).fetchall()
    return [_row_to_training_dataset(row) for row in rows]
