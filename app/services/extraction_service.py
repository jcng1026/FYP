"""Template region extraction orchestration for the Teacher role.

Groups a completed OCR job's text blocks by the linked template's regions,
using normalized region coordinates and the processed page image
dimensions to test whether each OCR block falls inside a region. This
stage stores raw region-level OCR text/blocks only - no answer comparison,
mark calculation, spelling deduction, MCQ circle detection, or AI feedback
happens here.
"""

import sqlite3
from typing import Dict, List, Optional, Tuple

from app.models.extraction_model import (
    ExtractionJob,
    add_extracted_region_block,
    add_extracted_region_result,
    create_extraction_job,
    get_extracted_region_results_for_job,
    get_extraction_job_by_id,
    get_extraction_job_for_combination,
    get_latest_extraction_job_for_attempt,
    mark_extraction_job_completed,
    mark_extraction_job_failed,
    EXTRACTION_STATUS_EXTRACTED,
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_NO_TEXT,
    EXTRACTION_STATUS_PENDING_DETECTION,
    STATUS_COMPLETED as EXTRACTION_JOB_STATUS_COMPLETED,
)
from app.models.marking_setup_model import get_marking_setup_by_material
from app.models.ocr_model import (
    OCRTextBlock,
    STATUS_COMPLETED as OCR_STATUS_COMPLETED,
    get_ocr_job_by_id,
    get_ocr_page_results_for_job,
    get_ocr_text_blocks_for_page,
)
from app.models.preprocessing_model import get_pages_for_job
from app.models.revision_attempt_model import get_attempt_by_id
from app.models.revision_material_model import get_material_by_id
from app.models.template_model import (
    REGION_TYPE_MCQ_OPTION_BOX,
    TemplateRegion,
    get_regions_for_template_excluding_ignore,
    get_template_by_id,
)

# Region types whose "selected answer" cannot be determined from OCR text
# alone - they still get their raw OCR text/blocks stored, but with a
# pending_detection status rather than extracted, since that requires
# circle/mark detection not built in this stage.
_PENDING_DETECTION_REGION_TYPES = {REGION_TYPE_MCQ_OPTION_BOX}


def _block_center(block: OCRTextBlock) -> Optional[Tuple[float, float]]:
    coords = (block.x1, block.y1, block.x2, block.y2, block.x3, block.y3, block.x4, block.y4)
    if any(value is None for value in coords):
        return None
    center_x = (block.x1 + block.x2 + block.x3 + block.x4) / 4
    center_y = (block.y1 + block.y2 + block.y3 + block.y4) / 4
    return center_x, center_y


def _point_in_region(x: float, y: float, region: TemplateRegion) -> bool:
    return region.x <= x <= region.x + region.width and region.y <= y <= region.y + region.height


def run_extraction_for_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    ocr_job_id: int,
) -> ExtractionJob:
    """Extract OCR text by template region for attempt_id using ocr_job_id.

    Raises ValueError before any extraction job is created if the attempt,
    OCR job, marking setup, or template prerequisites are invalid - these
    are considered invalid requests rather than extraction failures. Once
    the extraction job is created, any unexpected error during the region
    matching loop is caught and stored as a failed job with a readable
    error_message instead of propagating.
    """
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")

    ocr_job = get_ocr_job_by_id(conn, ocr_job_id)
    if ocr_job is None:
        raise ValueError(f"OCR job not found: {ocr_job_id}")
    if ocr_job.status != OCR_STATUS_COMPLETED:
        raise ValueError(f"OCR job {ocr_job_id} is not completed (status: {ocr_job.status}).")
    if ocr_job.source_id is not None and ocr_job.source_id != attempt_id:
        raise ValueError(f"OCR job {ocr_job_id} does not belong to attempt {attempt_id}.")

    material = get_material_by_id(conn, attempt.material_id)
    if material is None:
        raise ValueError(f"Revision material not found for attempt {attempt_id}.")

    marking_setup = get_marking_setup_by_material(conn, material.material_id)
    if marking_setup is None:
        raise ValueError("No marking setup found for this revision material. Set up marking first.")
    if marking_setup.template_id is None:
        raise ValueError("Link a template in Marking Setup before extracting regions.")

    template = get_template_by_id(conn, marking_setup.template_id)
    if template is None:
        raise ValueError(f"Linked template not found: {marking_setup.template_id}")
    if template.teacher_id != marking_setup.teacher_id:
        raise ValueError("Linked template does not belong to the same teacher as this marking setup.")
    if template.paper_type != material.paper_type:
        raise ValueError(
            f"Template paper type ({template.paper_type}) does not match "
            f"material paper type ({material.paper_type})."
        )

    existing = get_extraction_job_for_combination(conn, attempt_id, ocr_job_id, template.template_id)
    if existing is not None and existing.status == EXTRACTION_JOB_STATUS_COMPLETED:
        raise ValueError(
            "Region extraction has already been completed for this attempt/OCR/template combination. "
            "View the existing extraction result instead of running it again."
        )

    extraction_job = create_extraction_job(
        conn, attempt_id, ocr_job_id, template.template_id, marking_setup.setup_id
    )

    try:
        # Ignore regions (Stage 11I) are exclusion masks, not answer/question/
        # student-id components - excluded here so they never get an
        # extracted_region_result row or feed into extracted_count.
        regions = get_regions_for_template_excluding_ignore(conn, template.template_id)

        preprocessing_pages = get_pages_for_job(conn, ocr_job.preprocessing_job_id)
        page_dimensions: Dict[int, Tuple[int, int]] = {
            page.page_number: (page.width, page.height) for page in preprocessing_pages
        }

        ocr_pages = get_ocr_page_results_for_job(conn, ocr_job.ocr_job_id)
        blocks_by_page: Dict[int, List[OCRTextBlock]] = {
            page.page_number: get_ocr_text_blocks_for_page(conn, page.ocr_page_id) for page in ocr_pages
        }

        extracted_count = 0
        for region in regions:
            dimensions = page_dimensions.get(region.page_number)
            if dimensions is None or dimensions[0] <= 0 or dimensions[1] <= 0:
                add_extracted_region_result(
                    conn,
                    extraction_job.extraction_job_id,
                    region.region_id,
                    region.page_number,
                    region.label,
                    region.region_type or "unknown",
                    None,
                    None,
                    0,
                    EXTRACTION_STATUS_FAILED,
                )
                continue

            width, height = dimensions
            matched_blocks: List[OCRTextBlock] = []
            for block in blocks_by_page.get(region.page_number, []):
                center = _block_center(block)
                if center is None:
                    continue
                normalized_x = center[0] / width
                normalized_y = center[1] / height
                if _point_in_region(normalized_x, normalized_y, region):
                    matched_blocks.append(block)

            combined_text = "\n".join(block.text for block in matched_blocks)
            confidences = [block.confidence for block in matched_blocks if block.confidence is not None]
            average_confidence = sum(confidences) / len(confidences) if confidences else None

            if not matched_blocks:
                extraction_status = EXTRACTION_STATUS_NO_TEXT
            elif region.region_type in _PENDING_DETECTION_REGION_TYPES:
                extraction_status = EXTRACTION_STATUS_PENDING_DETECTION
            else:
                extraction_status = EXTRACTION_STATUS_EXTRACTED

            result = add_extracted_region_result(
                conn,
                extraction_job.extraction_job_id,
                region.region_id,
                region.page_number,
                region.label,
                region.region_type or "unknown",
                combined_text,
                average_confidence,
                len(matched_blocks),
                extraction_status,
            )

            if matched_blocks:
                extracted_count += 1

            for block_order, block in enumerate(matched_blocks, start=1):
                add_extracted_region_block(
                    conn, result.result_id, block.ocr_block_id, block_order, block.text, block.confidence
                )

        mark_extraction_job_completed(conn, extraction_job.extraction_job_id, len(regions), extracted_count)
    except Exception as exc:
        mark_extraction_job_failed(conn, extraction_job.extraction_job_id, str(exc))

    return get_extraction_job_by_id(conn, extraction_job.extraction_job_id)


def get_extraction_job(conn: sqlite3.Connection, extraction_job_id: int) -> Optional[ExtractionJob]:
    return get_extraction_job_by_id(conn, extraction_job_id)


def get_latest_extraction_job(conn: sqlite3.Connection, attempt_id: int) -> Optional[ExtractionJob]:
    return get_latest_extraction_job_for_attempt(conn, attempt_id)


def list_extracted_region_results(conn: sqlite3.Connection, extraction_job_id: int):
    return get_extracted_region_results_for_job(conn, extraction_job_id)
