"""OCR extraction orchestration for the Teacher role.

Runs OCR on the processed page images of a completed preprocessing job and
stores raw text, per-page average confidence, and per-block bounding boxes.
This stage stores raw OCR output only - no answer extraction, template
region matching, or marking happens here.
"""

import sqlite3
from typing import List, Optional

from app.models.ocr_model import (
    OCRJob,
    OCRPageResult,
    OCRTextBlock,
    add_ocr_page_result,
    add_ocr_text_block,
    create_ocr_job,
    get_latest_ocr_job_for_preprocessing_job,
    get_ocr_job_by_id,
    get_ocr_page_results_for_job,
    get_ocr_text_blocks_for_page,
    mark_ocr_job_completed,
    mark_ocr_job_failed,
)
from app.models.preprocessing_model import (
    STATUS_COMPLETED as PREPROCESSING_STATUS_COMPLETED,
    get_job_by_id,
    get_pages_for_job,
)
from app.utils.ocr_engine import OCREngine, get_default_engine


def run_ocr_for_preprocessing_job(
    conn: sqlite3.Connection,
    preprocessing_job_id: int,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    engine: Optional[OCREngine] = None,
) -> OCRJob:
    """Run OCR on every processed page of preprocessing_job_id and store the results.

    Raises ValueError before any OCR job is created if the preprocessing job
    doesn't exist, isn't completed, or has no processed pages - these are
    invalid requests rather than OCR failures.

    If engine is not supplied, the default engine (PaddleOCR) is constructed
    lazily inside the try block below, so a missing/broken dependency is
    recorded as a failed OCR job with a readable error_message instead of
    raising or crashing the app.
    """
    preprocessing_job = get_job_by_id(conn, preprocessing_job_id)
    if preprocessing_job is None:
        raise ValueError(f"Preprocessing job not found: {preprocessing_job_id}")
    if preprocessing_job.status != PREPROCESSING_STATUS_COMPLETED:
        raise ValueError(
            f"Preprocessing job {preprocessing_job_id} is not completed "
            f"(status: {preprocessing_job.status})."
        )

    pages = get_pages_for_job(conn, preprocessing_job_id)
    if not pages:
        raise ValueError(f"Preprocessing job {preprocessing_job_id} has no processed pages.")

    resolved_source_type = source_type if source_type is not None else preprocessing_job.source_type
    resolved_source_id = source_id if source_id is not None else preprocessing_job.source_id

    ocr_job = create_ocr_job(conn, preprocessing_job_id, resolved_source_type, resolved_source_id)

    try:
        active_engine = engine if engine is not None else get_default_engine()

        page_texts: List[str] = []
        for page in pages:
            result = active_engine.run_page(page.processed_image_path)
            page_result = add_ocr_page_result(
                conn, ocr_job.ocr_job_id, page.page_number, result.text, result.average_confidence
            )
            for block_order, block in enumerate(result.blocks, start=1):
                coords = []
                for corner_index in range(4):
                    if block.box and corner_index < len(block.box):
                        coords.extend([block.box[corner_index][0], block.box[corner_index][1]])
                    else:
                        coords.extend([None, None])
                add_ocr_text_block(
                    conn,
                    page_result.ocr_page_id,
                    block_order,
                    block.text,
                    block.confidence,
                    *coords,
                )
            page_texts.append(result.text or "")

        full_text = "\n\n".join(page_texts)
        mark_ocr_job_completed(conn, ocr_job.ocr_job_id, len(pages), full_text)
    except Exception as exc:
        mark_ocr_job_failed(conn, ocr_job.ocr_job_id, str(exc))

    return get_ocr_job_by_id(conn, ocr_job.ocr_job_id)


def get_ocr_job(conn: sqlite3.Connection, ocr_job_id: int) -> Optional[OCRJob]:
    return get_ocr_job_by_id(conn, ocr_job_id)


def get_latest_ocr_job(conn: sqlite3.Connection, preprocessing_job_id: int) -> Optional[OCRJob]:
    return get_latest_ocr_job_for_preprocessing_job(conn, preprocessing_job_id)


def list_ocr_page_results(conn: sqlite3.Connection, ocr_job_id: int) -> List[OCRPageResult]:
    return get_ocr_page_results_for_job(conn, ocr_job_id)


def list_ocr_text_blocks(conn: sqlite3.Connection, ocr_page_id: int) -> List[OCRTextBlock]:
    return get_ocr_text_blocks_for_page(conn, ocr_page_id)
