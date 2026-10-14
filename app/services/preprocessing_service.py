"""Document preprocessing orchestration for the Teacher role.

Converts an uploaded PDF/image file into cleaned page PNGs for later OCR
and template-alignment stages. This stage stores preprocessing outputs
only - no OCR, answer extraction, or marking happens here.
"""

import sqlite3
from pathlib import Path
from typing import List, Optional

from app.models.preprocessing_model import (
    PreprocessingJob,
    PreprocessingPage,
    add_page,
    create_job,
    get_job_by_id,
    get_latest_job_for_source,
    get_pages_for_job,
    mark_job_completed,
    mark_job_failed,
    update_job_output_folder,
)
from app.utils.document_preprocessing import (
    is_supported_file,
    load_page_images,
    preprocess_page_image,
    save_page_image,
)
from app.utils.file_storage import get_preprocessing_output_folder


def preprocess_document(
    conn: sqlite3.Connection,
    original_file_path: str,
    source_type: str,
    source_id: Optional[int] = None,
) -> PreprocessingJob:
    """Preprocess original_file_path (PDF or image) into cleaned page PNGs.

    A job record is created up front (status "pending"), then updated to
    "completed" with a page_count on success, or "failed" with a readable
    error_message if any step of the actual processing raises. The original
    file is only ever read, never moved or modified.

    Raises ValueError before any job is created if original_file_path is
    missing/empty, doesn't exist, or isn't a supported file type - these
    are considered invalid requests rather than processing failures.
    """
    original_file_path = (original_file_path or "").strip()
    if not original_file_path:
        raise ValueError("A file path is required.")
    if not Path(original_file_path).is_file():
        raise ValueError(f"File not found: {original_file_path}")
    if not is_supported_file(original_file_path):
        raise ValueError(f"Unsupported file type: {Path(original_file_path).suffix}")

    job = create_job(conn, source_type, source_id, original_file_path, "")
    output_folder = get_preprocessing_output_folder(job.job_id)
    update_job_output_folder(conn, job.job_id, str(output_folder))

    try:
        pages = load_page_images(original_file_path)
        if not pages:
            raise ValueError("No pages could be loaded from the file.")

        for page_number, page_image in enumerate(pages, start=1):
            processed = preprocess_page_image(page_image)
            output_path = output_folder / f"page_{page_number:03d}.png"
            save_page_image(processed, output_path)
            height, width = processed.shape[:2]
            add_page(conn, job.job_id, page_number, str(output_path), width, height)

        mark_job_completed(conn, job.job_id, len(pages))
    except Exception as exc:
        mark_job_failed(conn, job.job_id, str(exc))

    return get_job_by_id(conn, job.job_id)


def get_preprocessing_job(conn: sqlite3.Connection, job_id: int) -> Optional[PreprocessingJob]:
    return get_job_by_id(conn, job_id)


def get_latest_preprocessing_job(
    conn: sqlite3.Connection, source_type: str, source_id: Optional[int]
) -> Optional[PreprocessingJob]:
    return get_latest_job_for_source(conn, source_type, source_id)


def list_preprocessing_pages(conn: sqlite3.Connection, job_id: int) -> List[PreprocessingPage]:
    return get_pages_for_job(conn, job_id)
