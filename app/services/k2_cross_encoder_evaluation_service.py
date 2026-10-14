"""Kertas 2 Cross-Encoder evaluation pipeline foundation (Stage 12D).

Evaluates the teacher's ACTIVE Kertas 2 Cross-Encoder model version (see
app/services/k2_cross_encoder_training_service.py, Stage 12C) against a
Stage 12B exported dataset: loads the dataset's labeled rows, predicts
each one via app/services/k2_prediction_service.py, and compares
predictions against the dataset's own teacher-derived labels (normalized_
score, feedback_category).

This is evaluation only:
- It never changes the active model version, never trains anything, and
  never touches Marking/Review/Results.
- It reuses app/services/k2_cross_encoder_training_service.py's dataset
  loader (load_training_rows_from_dataset) and log writer
  (_TrainingLogWriter) so evaluation logs/validation match training's
  behavior exactly - the same "student answer + normalized score +
  feedback category required, question_text may be blank" rules apply.
- Results are merged into the evaluated model version's own metrics_json
  under an "evaluation" key (via ai_model_registry_service.
  update_ai_model_version_metrics) - training metrics are preserved
  alongside it, not overwritten - and reuses ai_training_jobs (Stage 12A)
  to track status/progress/log_path exactly like a training job, tagged
  via config_json {"job_kind": "evaluation", ...} rather than adding a new
  column (the same additive-config convention Stage 12C used for its own
  dataset reference).

Dependency policy: identical to k2_cross_encoder_training_service - torch/
transformers are never imported at module level here; k2_prediction_
service.predict_k2_answer_item lazily resolves the real predictor only
when no predictor_fn is injected and the dependencies are available.

DATA QUALITY NOTE: fewer than MIN_ROWS_FOR_MEANINGFUL_EVAL usable rows
produces metrics stamped demo_mode=True, meaningful=False - an evaluation
against a handful of examples is not a meaningful accuracy signal, and
this stage never claims otherwise.
"""

import json
import traceback
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Optional

from app.models.ai_model_registry_model import (
    AITrainingJob,
    JOB_STATUS_RUNNING,
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
    MODEL_TYPE_CROSS_ENCODER,
)
from app.services.ai_model_registry_service import (
    complete_ai_training_job,
    create_ai_training_job,
    fail_ai_training_job,
    get_active_ai_model_version,
    list_ai_training_jobs,
    update_ai_model_version_metrics,
    update_ai_training_job_progress,
)
from app.services.k2_cross_encoder_training_service import (
    MissingMLDependencyError,
    _TrainingLogWriter,
    check_ml_dependencies_available,
    load_training_rows_from_dataset,
)
from app.services.k2_prediction_service import K2PredictionInput, _fake_predict, predict_k2_answer_item
from app.services.k2_training_dataset_service import get_k2_training_dataset
from app.services.user_service import validate_ai_manager_exists

MIN_ROWS_FOR_MEANINGFUL_EVAL = 5


def has_active_k2_model_version(conn, teacher_id: int) -> bool:
    """Used by the AI Models page to decide whether Evaluate should be
    enabled - True only once a Kertas 2 model version has been trained and
    activated (Stage 12C)."""
    return get_active_ai_model_version(conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING) is not None


def is_k2_evaluation_job(job: AITrainingJob) -> bool:
    """ai_training_jobs rows are shared between training (Stage 12C) and
    evaluation (Stage 12D) jobs - distinguished only via config_json's
    job_kind, never a new column. Old training jobs (no job_kind key) are
    correctly treated as NOT an evaluation job."""
    if not job.config_json:
        return False
    try:
        return json.loads(job.config_json).get("job_kind") == "evaluation"
    except json.JSONDecodeError:
        return False


def list_k2_evaluation_jobs(conn, teacher_id: int, limit: int = 10):
    """Latest evaluation-only jobs for teacher_id, newest first."""
    jobs = list_ai_training_jobs(conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, limit=50)
    return [job for job in jobs if is_k2_evaluation_job(job)][:limit]


def list_k2_training_only_jobs(conn, teacher_id: int, limit: int = 10):
    """Latest training-only jobs for teacher_id, newest first - excludes
    evaluation jobs so the AI Models page's "Last training job" status
    never shows an evaluation run instead."""
    jobs = list_ai_training_jobs(conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, limit=50)
    return [job for job in jobs if not is_k2_evaluation_job(job)][:limit]


def run_k2_cross_encoder_evaluation(
    conn, teacher_id: int, dataset_id: int,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    predictor_fn: Optional[Callable] = None,
) -> dict:
    """Run one Kertas 2 Cross-Encoder evaluation job end-to-end.

    Creates an ai_training_jobs row (config_json job_kind="evaluation"),
    loads+validates rows from dataset_id's exported JSONL (same rules as
    training), predicts each row via k2_prediction_service (the real
    predictor by default, or predictor_fn if given - tests inject a fake
    predictor here), computes score/category metrics, merges them into the
    active model version's metrics_json, and completes the job.

    Raises ValueError before any job is created if teacher_id/dataset_id
    are invalid or no active Kertas 2 model version exists. Once a job
    exists, any failure (missing ML dependency, no usable rows, a real
    prediction error) marks that job 'failed' with a clear message and a
    written log entry, then re-raises as ValueError so the UI's existing
    show_error(...) pattern handles it unchanged.
    """
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can run Kertas 2 evaluation.")

    model_version = get_active_ai_model_version(conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING)
    if model_version is None:
        raise ValueError("No active Kertas 2 Cross-Encoder model version exists - train a model first.")

    dataset = get_k2_training_dataset(conn, teacher_id, dataset_id)

    config = {
        "job_kind": "evaluation", "dataset_id": dataset_id, "dataset_name": dataset["dataset_name"],
        "model_id": model_version.model_id, "model_version_label": model_version.version_label,
    }
    job = create_ai_training_job(
        conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, MODEL_TYPE_CROSS_ENCODER,
        config_json=json.dumps(config),
    )
    log = _TrainingLogWriter(job.log_path)
    total_steps = 4  # preparing dataset, predicting, scoring, saving results

    def _emit(message: str, current: int, total: int) -> None:
        percent = round(current / total * 100, 1) if total > 0 else 0
        update_ai_training_job_progress(conn, teacher_id, job.job_id, percent, message, status=JOB_STATUS_RUNNING)
        if progress_callback is not None:
            progress_callback(message, current, total)

    try:
        log.write(f"Starting Kertas 2 evaluation job {job.job_id} for teacher {teacher_id}")
        log.write(f"Model version: {model_version.version_label} (model_id={model_version.model_id})")
        log.write(f"Dataset: {dataset['jsonl_path']} (exported row_count={dataset['row_count']})")

        _emit("Preparing dataset", 1, total_steps)
        rows, stats = load_training_rows_from_dataset(dataset["jsonl_path"])
        log.write(
            f"Loaded rows: row_count={stats['row_count']} usable_row_count={stats['usable_row_count']} "
            f"skipped_row_count={stats['skipped_row_count']}"
        )
        if stats["usable_row_count"] == 0:
            raise ValueError(
                "No usable rows found in this dataset to evaluate (each row needs a student answer, a "
                "normalized score, and a feedback category)."
            )

        demo_mode = stats["usable_row_count"] < MIN_ROWS_FOR_MEANINGFUL_EVAL
        if demo_mode:
            log.write(
                f"DEMO MODE: only {stats['usable_row_count']} usable rows (fewer than "
                f"{MIN_ROWS_FOR_MEANINGFUL_EVAL}) - metrics will be marked not meaningful."
            )

        active_predictor_fn = predictor_fn
        using_fake = False
        if active_predictor_fn is None:
            available, message = check_ml_dependencies_available()
            if not available:
                raise MissingMLDependencyError(message)
        else:
            using_fake = active_predictor_fn is _fake_predict
        log.write(f"Predictor: {'fake (dependency-free stand-in)' if using_fake else 'real'}")

        _emit("Predicting", 2, total_steps)
        absolute_errors = []
        squared_errors = []
        category_correct = 0
        actual_label_counts: Counter = Counter()
        predicted_label_counts: Counter = Counter()

        for row in rows:
            # row.text_a is already the merged question/marking-scheme/
            # expected-answer text from load_training_rows_from_dataset -
            # passed as marking_scheme_text only (leaving expected_answer_
            # text/question_text blank) so k2_prediction_service doesn't
            # re-concatenate and duplicate it.
            item = K2PredictionInput(
                question_text=None, marking_scheme_text=row.text_a, expected_answer_text=None,
                student_answer_text=row.text_b, max_mark=1.0,
            )
            prediction = predict_k2_answer_item(item, model_version, predictor_fn=active_predictor_fn)
            error = abs(prediction["predicted_normalized_score"] - row.normalized_score)
            absolute_errors.append(error)
            squared_errors.append(error ** 2)
            actual_label_counts[row.feedback_category] += 1
            predicted_label_counts[prediction["predicted_feedback_category"]] += 1
            if prediction["predicted_feedback_category"] == row.feedback_category:
                category_correct += 1

        _emit("Scoring", 3, total_steps)
        mean_absolute_error = round(sum(absolute_errors) / len(absolute_errors), 4)
        mean_squared_error = round(sum(squared_errors) / len(squared_errors), 4)
        category_accuracy = round(category_correct / len(rows), 4)

        metrics = {
            "row_count": stats["row_count"],
            "usable_row_count": stats["usable_row_count"],
            "skipped_row_count": stats["skipped_row_count"],
            "mean_absolute_error": mean_absolute_error,
            "mean_squared_error": mean_squared_error,
            "category_accuracy": category_accuracy,
            "label_distribution": dict(actual_label_counts),
            "predicted_label_distribution": dict(predicted_label_counts),
            "demo_mode": demo_mode,
            "meaningful": not demo_mode,
            "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "dataset_id": dataset_id,
            "dataset_name": dataset["dataset_name"],
            "model_id": model_version.model_id,
            "model_version_label": model_version.version_label,
            "predictor": "fake" if using_fake else "real",
        }
        log.write(f"Final evaluation metrics: {json.dumps(metrics)}")

        _emit("Saving results", 4, total_steps)
        existing_metrics = {}
        if model_version.metrics_json:
            try:
                existing_metrics = json.loads(model_version.metrics_json)
            except json.JSONDecodeError:
                existing_metrics = {}
        existing_metrics["evaluation"] = metrics
        update_ai_model_version_metrics(conn, teacher_id, model_version.model_id, json.dumps(existing_metrics))

        completion_message = "Evaluation completed successfully."
        if demo_mode:
            completion_message += " (Demo mode - not enough data for meaningful metrics.)"
        complete_ai_training_job(
            conn, teacher_id, job.job_id, output_model_id=model_version.model_id,
            metrics_json=json.dumps(metrics), message=completion_message,
        )
        log.write(f"Evaluation job {job.job_id} completed. Metrics merged into model version {model_version.model_id}.")

        return {
            "job_id": job.job_id, "model_id": model_version.model_id,
            "model_version_label": model_version.version_label, "dataset_id": dataset_id,
            "metrics": metrics, "demo_mode": demo_mode,
        }
    except Exception as exc:
        error_message = str(exc)
        log.write(f"EVALUATION FAILED: {error_message}")
        log.write(traceback.format_exc())
        fail_ai_training_job(conn, teacher_id, job.job_id, error_message)
        raise ValueError(error_message) from exc
    finally:
        log.close()
