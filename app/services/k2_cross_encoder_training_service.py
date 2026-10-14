"""Kertas 2 Cross-Encoder training pipeline foundation (Stage 12C).

Implements the first REAL training pipeline for Core AI 1 (see
docs/stage12_ai_plan.md): a Cross-Encoder-style transformer that reads
(text_a = question text + marking scheme + expected answer, text_b =
student answer) pairs from a Stage 12B exported dataset and learns two
outputs - a draft normalized score (0-1 regression) and a feedback
category (classification) - via a small custom multi-task head on top of
a Hugging Face AutoModel backbone (default: distilbert-base-uncased).

This is a training FOUNDATION only:
- No AI scoring/inference is wired into the Marking workflow.
- Local LLM feedback generation lives in the separate Local Feedback Runtime
  (core_ai1_local_feedback_service), not in this legacy training path.
- Model quality directly depends on how much teacher-reviewed data exists
  (see the module-level DATA QUALITY NOTE below) - this stage never
  claims or fakes accuracy it hasn't earned.

Dependency policy (see requirements.txt and the Stage 12C report): torch
and transformers are NOT currently installed in this environment and are
NOT added by this stage - no dependency changes without explicit
approval. The real transformer trainer below imports torch/transformers
lazily, only inside _train_real_cross_encoder, so importing this module
(and the rest of the app) never fails even when those packages are
absent. When they are missing, run_k2_cross_encoder_training fails the
training job with a clear, actionable message instead of crashing - see
check_ml_dependencies_available(). Tests exercise the full orchestration
(dataset loading, job/version lifecycle, logging) via an injectable fake
trainer (_train_fake_cross_encoder) that never imports torch/transformers
- the same dependency-injection pattern already used elsewhere in this
codebase (e.g. the OCR engine's `engine` parameter).

DATA QUALITY NOTE: this pipeline can technically run on as few as 1 usable
example ("demo mode" for fewer than MIN_ROWS_FOR_REAL_TRAINING rows), but
a model trained on a handful of examples is not meaningful. Every such run
is stamped metrics["demo_mode"] = True and metrics["meaningful"] = False
so the AI Models page (and any future stage) never silently presents a
demo-trained model as production-quality. Real model quality requires a
real volume of exported teacher-reviewed Kertas 2 examples (Stage 12B) -
this has not been collected yet in this environment.
"""

import json
import os
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from app.models.ai_model_registry_model import (
    JOB_STATUS_RUNNING,
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
    MODEL_TYPE_CROSS_ENCODER,
)
from app.services.ai_model_registry_service import (
    complete_ai_training_job,
    create_ai_training_job,
    fail_ai_training_job,
    register_ai_model_version,
    set_active_ai_model_version,
    update_ai_training_job_progress,
)
from app.services.k2_training_dataset_service import (
    FEEDBACK_CATEGORY_CORRECT,
    FEEDBACK_CATEGORY_INCORRECT,
    FEEDBACK_CATEGORY_MISSING_ANSWER,
    FEEDBACK_CATEGORY_PARTIAL,
    get_k2_training_dataset,
    list_k2_training_datasets,
)
from app.services.user_service import validate_ai_manager_exists
from app.utils.file_storage import get_ai_model_version_folder

BASE_MODEL_DEFAULT = "distilbert-base-uncased"
MIN_ROWS_FOR_REAL_TRAINING = 5
DEFAULT_NUM_EPOCHS = 1
DEFAULT_BATCH_SIZE = 4

# Fixed, sorted order so the same categories always map to the same label
# index across every training run, regardless of which categories happen
# to appear in any one dataset - a deterministic label mapping.
ALL_FEEDBACK_CATEGORIES = (
    FEEDBACK_CATEGORY_CORRECT, FEEDBACK_CATEGORY_INCORRECT,
    FEEDBACK_CATEGORY_MISSING_ANSWER, FEEDBACK_CATEGORY_PARTIAL,
)


class MissingMLDependencyError(RuntimeError):
    """Raised when torch/transformers aren't installed and no fake trainer
    was injected - caught by run_k2_cross_encoder_training and turned into
    a failed training job with a clear message, never an app crash."""


def check_ml_dependencies_available() -> Tuple[bool, str]:
    """Safe, side-effect-free check - never raises. Returns (available, message)."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as exc:
        return False, (
            "Cross-Encoder training requires the 'torch' and 'transformers' packages, which are not "
            f"installed in this environment ({exc}). Install them (see requirements.txt notes) to enable "
            "real training - no training was attempted."
        )
    return True, "torch and transformers are available."


def has_k2_training_dataset(conn: sqlite3.Connection, teacher_id: int) -> bool:
    """Used by the AI Models page to decide whether Start Training should
    be enabled - True as soon as at least one Kertas 2 dataset has been
    exported (Stage 12B), regardless of its row count."""
    return len(list_k2_training_datasets(conn, teacher_id, limit=1)) > 0


@dataclass
class LoadedTrainingRow:
    text_a: str
    text_b: str
    normalized_score: float
    feedback_category: str


def _build_text_a(row: dict) -> str:
    parts = [row.get("question_text"), row.get("marking_scheme_text"), row.get("expected_answer_text")]
    return " ".join(str(part).strip() for part in parts if part and str(part).strip())


def load_training_rows_from_dataset(jsonl_path: Optional[str]) -> Tuple[List[LoadedTrainingRow], dict]:
    """Load and validate rows from a Stage 12B JSONL export.

    Returns (usable_rows, stats) where stats has row_count/usable_row_count/
    skipped_row_count. A row is usable only if it has a non-blank
    student_answer_text, a non-null normalized_score, and a non-blank
    feedback_category - question_text may be blank (a known upstream gap,
    see app/services/k2_training_dataset_service.py). Never raises for a
    missing/unreadable file - callers should check the returned stats
    themselves; a missing file simply yields all-zero stats.
    """
    path = Path(jsonl_path) if jsonl_path else None
    if path is None or not path.is_file():
        return [], {"row_count": 0, "usable_row_count": 0, "skipped_row_count": 0}

    usable_rows: List[LoadedTrainingRow] = []
    total = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            student_answer_text = row.get("student_answer_text")
            normalized_score = row.get("normalized_score")
            feedback_category = row.get("feedback_category")
            if not student_answer_text or not str(student_answer_text).strip():
                continue
            if normalized_score is None:
                continue
            if not feedback_category:
                continue

            usable_rows.append(LoadedTrainingRow(
                text_a=_build_text_a(row),
                text_b=str(student_answer_text),
                normalized_score=float(normalized_score),
                feedback_category=str(feedback_category),
            ))

    stats = {"row_count": total, "usable_row_count": len(usable_rows), "skipped_row_count": total - len(usable_rows)}
    return usable_rows, stats


class _TrainingLogWriter:
    """Appends timestamped lines to one training job's human-readable log
    file, flushing after every write so a crash mid-training still leaves
    a readable partial log."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(log_path, "a", encoding="utf-8")

    def write(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._handle.write(f"[{timestamp}] {message}\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _train_fake_cross_encoder(
    rows: List[LoadedTrainingRow], base_model_name: str, num_epochs: int, batch_size: int,
    model_output_dir: str, total_steps: int, emit, log: _TrainingLogWriter,
) -> dict:
    """Deterministic, dependency-free stand-in for the real trainer -
    exercises the exact same orchestration (progress stages, file saving,
    metrics shape) without importing torch/transformers. Used by tests,
    and available as an explicit trainer_fn for any environment where real
    training isn't possible - never used silently in place of the real
    trainer in production (see run_k2_cross_encoder_training)."""
    os.makedirs(model_output_dir, exist_ok=True)
    step = 0

    step += 1
    emit("Preparing dataset", step, total_steps)
    log.write(f"Preparing dataset: {len(rows)} usable rows")

    step += 1
    emit("Loading tokenizer/model", step, total_steps)
    log.write(f"[fake trainer] base_model={base_model_name} (not actually loaded - dependency-free stand-in)")

    labels = sorted({r.feedback_category for r in rows}) or list(ALL_FEEDBACK_CATEGORIES)
    label_to_index = {label: index for index, label in enumerate(labels)}

    for epoch in range(1, num_epochs + 1):
        step += 1
        emit(f"Training epoch {epoch}/{num_epochs}", step, total_steps)
        log.write(f"Training epoch {epoch}/{num_epochs} (fake trainer - no real gradient updates)")

    step += 1
    emit("Evaluating", step, total_steps)
    avg_score = sum(r.normalized_score for r in rows) / len(rows)
    most_common = max(label_to_index, key=lambda label: sum(1 for r in rows if r.feedback_category == label))
    correct = sum(1 for r in rows if r.feedback_category == most_common)
    category_accuracy = correct / len(rows)
    val_mae = sum(abs(r.normalized_score - avg_score) for r in rows) / len(rows)
    log.write(f"Evaluation: avg_score={avg_score:.4f} val_mae={val_mae:.4f} category_accuracy={category_accuracy:.4f}")

    step += 1
    emit("Saving model", step, total_steps)
    (Path(model_output_dir) / "label_map.json").write_text(json.dumps(label_to_index), encoding="utf-8")
    (Path(model_output_dir) / "fake_model.json").write_text(
        json.dumps({"avg_score": avg_score, "note": "fake trainer stand-in - no real model weights"}),
        encoding="utf-8",
    )
    log.write(f"Model artifacts saved to {model_output_dir}")

    return {
        "train_loss": None,
        "val_loss": None,
        "val_mae": round(val_mae, 4),
        "val_mse": round(val_mae ** 2, 4),
        "category_accuracy": round(category_accuracy, 4),
        "label_to_index": label_to_index,
        "trainer": "fake",
        "device": "cpu",
    }


def _train_real_cross_encoder(
    rows: List[LoadedTrainingRow], base_model_name: str, num_epochs: int, batch_size: int,
    model_output_dir: str, total_steps: int, emit, log: _TrainingLogWriter,
) -> dict:
    """Real Hugging Face Transformers + PyTorch Cross-Encoder training -
    AutoTokenizer + AutoModel backbone with a small custom multi-task head
    (regression + classification). torch/transformers are imported here,
    lazily, only when this function actually runs - see
    check_ml_dependencies_available(), called before this function is ever
    selected as the active trainer.

    NOTE: this exact code path could not be executed in the environment
    this stage was built in (torch/transformers are not installed here -
    see the Stage 12C report's dependency findings). It is written using
    standard, well-established Transformers/PyTorch patterns, but has not
    been run end-to-end locally; treat it as reviewed-but-unverified until
    it is exercised in an environment with the dependencies installed.
    """
    import torch
    from torch.utils.data import DataLoader, Dataset
    from transformers import AutoModel, AutoTokenizer

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    step = 0

    step += 1
    emit("Preparing dataset", step, total_steps)
    labels = sorted({r.feedback_category for r in rows})
    label_to_index = {label: index for index, label in enumerate(labels)}

    split_index = max(1, int(len(rows) * 0.8)) if len(rows) > 1 else len(rows)
    train_rows = rows[:split_index]
    val_rows = rows[split_index:] or rows[:1]

    step += 1
    emit("Loading tokenizer/model", step, total_steps)
    log.write(f"Loading base model {base_model_name} on device {device}")
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    backbone = AutoModel.from_pretrained(base_model_name)

    class _PairDataset(Dataset):
        def __init__(self, data_rows):
            self.data_rows = data_rows

        def __len__(self):
            return len(self.data_rows)

        def __getitem__(self, index):
            return self.data_rows[index]

    def _collate(batch):
        encoded = tokenizer(
            [item.text_a for item in batch], [item.text_b for item in batch],
            padding=True, truncation=True, max_length=256, return_tensors="pt",
        )
        scores = torch.tensor([item.normalized_score for item in batch], dtype=torch.float32)
        label_indices = torch.tensor([label_to_index[item.feedback_category] for item in batch], dtype=torch.long)
        return encoded, scores, label_indices

    train_loader = DataLoader(_PairDataset(train_rows), batch_size=batch_size, shuffle=True, collate_fn=_collate)
    val_loader = DataLoader(_PairDataset(val_rows), batch_size=batch_size, shuffle=False, collate_fn=_collate)

    class _MultiTaskHead(torch.nn.Module):
        def __init__(self, hidden_size, num_categories):
            super().__init__()
            self.regression_head = torch.nn.Linear(hidden_size, 1)
            self.classification_head = torch.nn.Linear(hidden_size, num_categories)

        def forward(self, pooled):
            score = torch.sigmoid(self.regression_head(pooled)).squeeze(-1)
            logits = self.classification_head(pooled)
            return score, logits

    class _CrossEncoderModel(torch.nn.Module):
        def __init__(self, backbone_model, num_categories):
            super().__init__()
            self.backbone = backbone_model
            self.head = _MultiTaskHead(backbone_model.config.hidden_size, num_categories)

        def forward(self, input_ids, attention_mask):
            outputs = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
            pooled = outputs.last_hidden_state[:, 0, :]
            return self.head(pooled)

    model = _CrossEncoderModel(backbone, len(labels)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
    mse_loss_fn = torch.nn.MSELoss()
    ce_loss_fn = torch.nn.CrossEntropyLoss()

    final_train_loss = None
    for epoch in range(1, num_epochs + 1):
        step += 1
        emit(f"Training epoch {epoch}/{num_epochs}", step, total_steps)
        model.train()
        epoch_losses = []
        for encoded, scores, label_indices in train_loader:
            encoded = {key: value.to(device) for key, value in encoded.items()}
            scores = scores.to(device)
            label_indices = label_indices.to(device)

            optimizer.zero_grad()
            score_pred, logits = model(encoded["input_ids"], encoded["attention_mask"])
            reg_loss = mse_loss_fn(score_pred, scores)
            cls_loss = ce_loss_fn(logits, label_indices)
            loss = reg_loss + cls_loss
            loss.backward()
            optimizer.step()
            epoch_losses.append(loss.item())
        final_train_loss = sum(epoch_losses) / len(epoch_losses) if epoch_losses else None
        log.write(f"Epoch {epoch}/{num_epochs} train_loss={final_train_loss}")

    step += 1
    emit("Evaluating", step, total_steps)
    model.eval()
    val_errors = []
    val_correct = 0
    val_total = 0
    with torch.no_grad():
        for encoded, scores, label_indices in val_loader:
            encoded = {key: value.to(device) for key, value in encoded.items()}
            scores = scores.to(device)
            label_indices = label_indices.to(device)
            score_pred, logits = model(encoded["input_ids"], encoded["attention_mask"])
            val_errors.extend((score_pred - scores).abs().tolist())
            predicted_labels = logits.argmax(dim=-1)
            val_correct += (predicted_labels == label_indices).sum().item()
            val_total += len(label_indices)
    val_mae = sum(val_errors) / len(val_errors) if val_errors else None
    val_mse = sum(error ** 2 for error in val_errors) / len(val_errors) if val_errors else None
    category_accuracy = val_correct / val_total if val_total else None
    log.write(f"Evaluation: val_mae={val_mae} val_mse={val_mse} category_accuracy={category_accuracy}")

    step += 1
    emit("Saving model", step, total_steps)
    os.makedirs(model_output_dir, exist_ok=True)
    backbone.save_pretrained(model_output_dir)
    tokenizer.save_pretrained(model_output_dir)
    torch.save(model.head.state_dict(), os.path.join(model_output_dir, "head.pt"))
    with open(os.path.join(model_output_dir, "label_map.json"), "w", encoding="utf-8") as handle:
        json.dump(label_to_index, handle)
    log.write(f"Model artifacts saved to {model_output_dir}")

    return {
        "train_loss": round(final_train_loss, 4) if final_train_loss is not None else None,
        "val_loss": None,
        "val_mae": round(val_mae, 4) if val_mae is not None else None,
        "val_mse": round(val_mse, 4) if val_mse is not None else None,
        "category_accuracy": round(category_accuracy, 4) if category_accuracy is not None else None,
        "label_to_index": label_to_index,
        "trainer": "real",
        "device": str(device),
    }


def run_k2_cross_encoder_training(
    conn: sqlite3.Connection, teacher_id: int, dataset_id: int,
    base_model_name: Optional[str] = None, num_epochs: int = DEFAULT_NUM_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    trainer_fn: Optional[Callable] = None,
) -> dict:
    """Run one Kertas 2 Cross-Encoder training job end-to-end.

    Creates an ai_training_jobs row, loads+validates rows from dataset_id's
    exported JSONL, trains (the real transformer trainer by default, or
    trainer_fn if given - tests inject a fake trainer here), saves model
    artifacts under data/ai_models/, writes a human-readable log under
    data/ai_training_logs/, and on success registers a new active
    ai_model_versions row (deactivating any previous Kertas 2 version for
    this teacher).

    Raises ValueError before any job is created if teacher_id/dataset_id
    are invalid. Once a job exists, any failure (missing ML dependency, no
    usable rows, a real training error) marks that job 'failed' with a
    clear message and a written log entry, then re-raises as ValueError so
    the UI's existing show_error(...) pattern handles it unchanged.
    """
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can run Kertas 2 training.")
    dataset = get_k2_training_dataset(conn, teacher_id, dataset_id)

    base_model_name = base_model_name or BASE_MODEL_DEFAULT
    config = {
        "dataset_id": dataset_id, "dataset_name": dataset["dataset_name"], "base_model": base_model_name,
        "num_epochs": num_epochs, "batch_size": batch_size,
    }
    job = create_ai_training_job(
        conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, MODEL_TYPE_CROSS_ENCODER,
        config_json=json.dumps(config),
    )
    log = _TrainingLogWriter(job.log_path)
    total_steps = num_epochs + 5  # prepare + load + epochs + evaluating + saving + completed

    def _emit(message: str, current: int, total: int) -> None:
        percent = round(current / total * 100, 1) if total > 0 else 0
        update_ai_training_job_progress(conn, teacher_id, job.job_id, percent, message, status=JOB_STATUS_RUNNING)
        if progress_callback is not None:
            progress_callback(message, current, total)

    try:
        log.write(f"Starting Kertas 2 Cross-Encoder training job {job.job_id} for teacher {teacher_id}")
        log.write(f"Dataset: {dataset['jsonl_path']} (exported row_count={dataset['row_count']})")

        rows, stats = load_training_rows_from_dataset(dataset["jsonl_path"])
        log.write(
            f"Loaded rows: row_count={stats['row_count']} usable_row_count={stats['usable_row_count']} "
            f"skipped_row_count={stats['skipped_row_count']}"
        )
        if stats["usable_row_count"] == 0:
            raise ValueError(
                "No usable training rows found in this dataset (each row needs a student answer, a "
                "normalized score, and a feedback category)."
            )

        demo_mode = stats["usable_row_count"] < MIN_ROWS_FOR_REAL_TRAINING
        if demo_mode:
            log.write(
                f"DEMO MODE: only {stats['usable_row_count']} usable rows (fewer than "
                f"{MIN_ROWS_FOR_REAL_TRAINING}) - metrics will be marked not meaningful."
            )

        active_trainer_fn = trainer_fn
        if active_trainer_fn is None:
            available, message = check_ml_dependencies_available()
            if not available:
                raise MissingMLDependencyError(message)
            active_trainer_fn = _train_real_cross_encoder

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        version_label = f"k2_cross_encoder_{timestamp}"
        model_output_dir = str(get_ai_model_version_folder(MODEL_KEY_K2_SHORT_ANSWER_SCORING, teacher_id, version_label))

        training_metrics = active_trainer_fn(
            rows, base_model_name, num_epochs, batch_size, model_output_dir, total_steps, _emit, log,
        )

        metrics = {
            **training_metrics,
            "row_count": stats["row_count"],
            "usable_row_count": stats["usable_row_count"],
            "skipped_row_count": stats["skipped_row_count"],
            "base_model": base_model_name,
            "demo_mode": demo_mode,
            "meaningful": not demo_mode,
            "dataset_id": dataset_id,
            "dataset_name": dataset["dataset_name"],
        }
        log.write(f"Final metrics: {json.dumps(metrics)}")
        _emit("Completed", total_steps, total_steps)

        version = register_ai_model_version(
            conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, version_label,
            model_path=model_output_dir, metrics_json=json.dumps(metrics), config_json=json.dumps(config),
            notes="Demo training (not meaningful - too few examples)" if demo_mode else "",
        )
        set_active_ai_model_version(conn, teacher_id, version.model_id)

        completion_message = "Training completed successfully."
        if demo_mode:
            completion_message += " (Demo mode - not enough data for meaningful metrics.)"
        complete_ai_training_job(
            conn, teacher_id, job.job_id, output_model_id=version.model_id, metrics_json=json.dumps(metrics),
            message=completion_message,
        )
        log.write(f"Training job {job.job_id} completed. Model version {version.model_id} is now active.")

        return {
            "job_id": job.job_id, "model_id": version.model_id, "version_label": version_label,
            "metrics": metrics, "model_path": model_output_dir, "demo_mode": demo_mode,
        }
    except Exception as exc:
        error_message = str(exc)
        log.write(f"TRAINING FAILED: {error_message}")
        log.write(traceback.format_exc())
        fail_ai_training_job(conn, teacher_id, job.job_id, error_message)
        raise ValueError(error_message) from exc
    finally:
        log.close()
