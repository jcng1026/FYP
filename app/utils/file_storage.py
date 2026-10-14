"""Local file storage helpers for revision materials and external revisions.

Selected files are copied into a per-record folder under data/, so the
originals stay untouched. No processing of file contents happens here -
only storage of paths and metadata.
"""

import os
import shutil
import sys
from pathlib import Path

# Marking Fix Follow-up: ENGLISH_GRADING_SYSTEM_DATA_ROOT lets an isolated
# test point a spawned subprocess (see app.workers.subject_profile_
# marking_worker_process, launched via QProcess - a genuinely separate OS
# process that does NOT inherit a parent test's monkeypatched module
# attributes) at a throwaway data/ tree, never the real one - unset in
# production, where every path below is identical to before.
_env_data_root = os.environ.get("ENGLISH_GRADING_SYSTEM_DATA_ROOT")
if _env_data_root:
    PROJECT_ROOT = Path(_env_data_root).resolve()
elif getattr(sys, "frozen", False):
    # Frozen build: data lives next to the executable (see app/database/db.py).
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REVISION_MATERIALS_DIR = PROJECT_ROOT / "data" / "revision_materials"
EXTERNAL_REVISIONS_DIR = PROJECT_ROOT / "data" / "external_revisions"
REVISION_ATTEMPTS_DIR = PROJECT_ROOT / "data" / "revision_attempts"
TEMPLATES_DIR = PROJECT_ROOT / "data" / "templates"
PREPROCESSED_DOCUMENTS_DIR = PROJECT_ROOT / "data" / "preprocessed_documents"
EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
MAIN_MARKING_SESSIONS_DIR = PROJECT_ROOT / "data" / "main_marking_sessions"
SUBJECT_PROFILES_DIR = PROJECT_ROOT / "data" / "subject_profiles"
AI_MODELS_DIR = PROJECT_ROOT / "data" / "ai_models"
AI_TRAINING_LOGS_DIR = PROJECT_ROOT / "data" / "ai_training_logs"
AI_TRAINING_DATASETS_DIR = PROJECT_ROOT / "data" / "ai_training_datasets"
OCR_CROP_CACHE_DIR = PROJECT_ROOT / "data" / "ocr_crop_cache"
PROCESSING_LOGS_DIR = PROJECT_ROOT / "data" / "processing_logs"

# Stage 12A: short, stable on-disk directory names for each model_key -
# kept separate from the model_key enum stored in the database so a future
# rename of the DB-facing key never requires renaming existing folders on
# disk. Falls back to the raw model_key for any key not listed here.
_AI_MODEL_KEY_DIR_NAMES = {
    "k2_short_answer_scoring": "k2_scoring",
    "answer_region_detection": "region_detection",
}


def _copy_into_folder(folder: Path, source_path: str, destination_name: str) -> str:
    """Copy source_path into folder as destination_name, keeping its extension.

    Returns the stored file's absolute path as a string.
    """
    source = Path(source_path)
    folder.mkdir(parents=True, exist_ok=True)

    destination = folder / f"{destination_name}{source.suffix}"
    shutil.copyfile(source, destination)
    return str(destination)


def store_material_file(material_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the material's storage folder as destination_name."""
    folder = REVISION_MATERIALS_DIR / f"material_{material_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def store_external_revision_file(external_revision_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the external revision's storage folder as destination_name."""
    folder = EXTERNAL_REVISIONS_DIR / f"external_{external_revision_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def store_attempt_file(attempt_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the attempt's storage folder as destination_name."""
    folder = REVISION_ATTEMPTS_DIR / f"attempt_{attempt_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def store_template_file(template_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the template's storage folder as destination_name."""
    folder = TEMPLATES_DIR / f"template_{template_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def store_marking_session_file(session_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the marking session's storage folder as
    destination_name (Stage 11L). Used for the session's question paper,
    answer key, and each uploaded student answer PDF - destination_name
    should be unique per file within the session (e.g. an answer file's own
    row id) so multiple uploads never collide, even if their original
    filenames match."""
    folder = MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def get_marking_answer_file_preprocessed_folder(session_id: int, answer_file_id: int) -> Path:
    """Return (creating if needed) the folder for one answer file's
    preprocessed page images (Stage 11M), nested under that same session's
    storage folder so all of a session's files - uploaded originals and
    generated pages alike - live together on disk:
    data/main_marking_sessions/session_{id}/answer_file_{id}/preprocessed/.
    Never touches the uploaded original PDF."""
    folder = MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}" / f"answer_file_{answer_file_id}" / "preprocessed"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_marking_answer_file_original_folder(session_id: int, answer_file_id: int) -> Path:
    """Return (creating if needed) the folder for one answer file's ORIGINAL
    (un-degraded) rendered page images (Stage 11W), kept alongside its
    preprocessed/ folder so the Marking Editor preview can show the clean
    page instead of the CLAHE/denoise/threshold output used for OCR:
    data/main_marking_sessions/session_{id}/answer_file_{id}/original/."""
    folder = MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}" / f"answer_file_{answer_file_id}" / "original"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_preprocessing_output_folder(job_id: int) -> Path:
    """Return (creating if needed) the output folder for a preprocessing job."""
    folder = PREPROCESSED_DOCUMENTS_DIR / f"job_{job_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def store_subject_profile_file(profile_id: int, source_path: str, destination_name: str) -> str:
    """Copy source_path into the Subject Profile's storage folder as
    destination_name (Stage 11V). Used for the profile's question paper and
    answer scheme PDFs."""
    folder = SUBJECT_PROFILES_DIR / f"profile_{profile_id}"
    return _copy_into_folder(folder, source_path, destination_name)


def get_subject_profile_preprocessed_folder(profile_id: int, source: str) -> Path:
    """Return (creating if needed) the folder for one Subject Profile's
    question-paper or answer-scheme preprocessed page images:
    data/subject_profiles/profile_{id}/{source}/preprocessed/."""
    folder = SUBJECT_PROFILES_DIR / f"profile_{profile_id}" / source / "preprocessed"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_subject_profile_original_folder(profile_id: int, source: str) -> Path:
    """Return (creating if needed) the folder for one Subject Profile's
    question-paper or answer-scheme ORIGINAL (un-degraded) rendered page
    images (Stage 11W): data/subject_profiles/profile_{id}/{source}/original/.
    Kept separate from .../preprocessed/ (the CLAHE/denoise/threshold output
    used for OCR) so the editor/preview can always show the clean page."""
    folder = SUBJECT_PROFILES_DIR / f"profile_{profile_id}" / source / "original"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_subject_profile_results_folder(profile_id: int) -> Path:
    """Return (creating if needed) the folder for one Subject Profile's
    generated per-student export outputs (marked PDF + comments TXT +
    Download-All ZIP) - never committed to git (see .gitignore)."""
    folder = SUBJECT_PROFILES_DIR / f"profile_{profile_id}" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_subject_profile_answer_crop_folder(profile_id: int, answer_file_id: int) -> Path:
    """Return (creating if needed) the folder for one student answer file's
    saved region crops (Stage 11Y region-crop OCR fast path):
    data/subject_profiles/profile_{id}/answer_crops/answer_file_{id}/.
    Nested under the existing subject_profiles folder so the existing
    .gitignore entry (data/subject_profiles/) already covers it - no new
    entry needed."""
    folder = SUBJECT_PROFILES_DIR / f"profile_{profile_id}" / "answer_crops" / f"answer_file_{answer_file_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_region_crop_ocr_cache_folder(teacher_id: int, profile_id: int) -> Path:
    """Return (creating if needed) the folder holding one teacher's Subject
    Profile's region-crop OCR cache (Stage 11Y):
    data/ocr_crop_cache/teacher_{teacher_id}/profile_{profile_id}/."""
    folder = OCR_CROP_CACHE_DIR / f"teacher_{teacher_id}" / f"profile_{profile_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_student_marking_processing_log_folder(teacher_id: int, profile_id: int) -> Path:
    """Return (creating if needed) the folder for one teacher's Subject
    Profile's student-marking timing/performance logs (Stage 11Y):
    data/processing_logs/student_marking/teacher_{teacher_id}/profile_{profile_id}/."""
    folder = PROCESSING_LOGS_DIR / "student_marking" / f"teacher_{teacher_id}" / f"profile_{profile_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_exports_dir() -> Path:
    """Return (creating if needed) the shared folder for exported CSV files."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def get_ai_model_version_folder(model_key: str, teacher_id: int, version_label: str) -> Path:
    """Return (creating if needed) the storage folder for one trained AI
    model version (Stage 12A registry foundation - no real model files are
    created or trained yet):
    data/ai_models/{model_key_dir}/teacher_{teacher_id}/{version_label}/.
    Only paths are ever stored in the database - never model blobs."""
    key_dir = _AI_MODEL_KEY_DIR_NAMES.get(model_key, model_key)
    folder = AI_MODELS_DIR / key_dir / f"teacher_{teacher_id}" / version_label
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_ai_training_log_folder(teacher_id: int, model_key: str) -> Path:
    """Return (creating if needed) the folder for one teacher's training
    job logs for model_key (Stage 12A foundation - no real training runs
    yet): data/ai_training_logs/teacher_{teacher_id}/{model_key}/."""
    folder = AI_TRAINING_LOGS_DIR / f"teacher_{teacher_id}" / model_key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_ai_training_job_log_path(teacher_id: int, model_key: str, job_id: int) -> Path:
    """Return the log file path for one training job (the file itself is
    not created here - a future training stage writes to it):
    data/ai_training_logs/teacher_{teacher_id}/{model_key}/job_{job_id:03d}.log."""
    folder = get_ai_training_log_folder(teacher_id, model_key)
    return folder / f"job_{job_id:03d}.log"


def get_ai_training_dataset_folder(teacher_id: int, model_key: str) -> str:
    """Return (creating if needed) the storage folder for one teacher's
    exported training datasets for model_key (Stage 12B - dataset export
    foundation only, no training happens here):
    data/ai_training_datasets/teacher_{teacher_id}/{model_key}/."""
    folder = AI_TRAINING_DATASETS_DIR / f"teacher_{teacher_id}" / model_key
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def get_ai_training_dataset_paths(teacher_id: int, model_key: str, dataset_name: str) -> tuple:
    """Return (csv_path, jsonl_path) for one exported dataset - the files
    themselves are not created here, only the folder they will live in:
    data/ai_training_datasets/teacher_{teacher_id}/{model_key}/{dataset_name}.csv
    and the matching .jsonl file."""
    folder = Path(get_ai_training_dataset_folder(teacher_id, model_key))
    csv_path = folder / f"{dataset_name}.csv"
    jsonl_path = folder / f"{dataset_name}.jsonl"
    return str(csv_path), str(jsonl_path)


def get_region_detection_dataset_folder(teacher_id: int, dataset_name: str) -> str:
    """Return (creating if needed) the folder for one exported Answer
    Region Detection YOLO-style image/label dataset (Stage 12E) - a whole
    folder of files (images/, labels/, dataset.yaml, classes.txt,
    manifest.json), unlike Kertas 2's single CSV/JSONL pair:
    data/ai_training_datasets/teacher_{teacher_id}/answer_region_detection/{dataset_name}/."""
    folder = Path(get_ai_training_dataset_folder(teacher_id, "answer_region_detection")) / dataset_name
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def get_safe_display_path(path: str) -> str:
    """Return a presentation-safe version of a locally stored file path, for
    user-facing detail dialogs (never the actual full local absolute path).

    Returns the path relative to the project root (e.g.
    "data/revision_materials/material_5/question_paper.pdf") when the file
    is stored under the project's own data/ folder, or just the filename if
    it isn't. Does not touch storage, upload, or export behavior - this is
    display formatting only.
    """
    if not path:
        return "Not available"
    try:
        relative = Path(path).resolve().relative_to(PROJECT_ROOT)
        return str(relative).replace("\\", "/")
    except ValueError:
        return Path(path).name
