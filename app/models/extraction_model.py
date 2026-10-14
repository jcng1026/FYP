"""Template region extraction job and result data model and database access
functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)

EXTRACTION_STATUS_EXTRACTED = "extracted"
EXTRACTION_STATUS_NO_TEXT = "no_text"
EXTRACTION_STATUS_PENDING_DETECTION = "pending_detection"
EXTRACTION_STATUS_FAILED = "failed"

ALLOWED_EXTRACTION_STATUSES = (
    EXTRACTION_STATUS_EXTRACTED,
    EXTRACTION_STATUS_NO_TEXT,
    EXTRACTION_STATUS_PENDING_DETECTION,
    EXTRACTION_STATUS_FAILED,
)


@dataclass
class ExtractionJob:
    extraction_job_id: int
    attempt_id: int
    ocr_job_id: int
    template_id: int
    marking_setup_id: int
    status: str
    region_count: int
    extracted_count: int
    error_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class ExtractedRegionResult:
    result_id: int
    extraction_job_id: int
    region_id: int
    page_number: int
    region_name: str
    region_type: str
    extracted_text: Optional[str]
    average_confidence: Optional[float]
    matched_block_count: int
    extraction_status: str
    created_at: str


@dataclass
class ExtractedRegionBlock:
    extracted_block_id: int
    result_id: int
    ocr_block_id: int
    block_order: int
    text: str
    confidence: Optional[float]


def create_extraction_job(
    conn: sqlite3.Connection,
    attempt_id: int,
    ocr_job_id: int,
    template_id: int,
    marking_setup_id: int,
) -> ExtractionJob:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO extraction_jobs "
        "(attempt_id, ocr_job_id, template_id, marking_setup_id, status, region_count, "
        "extracted_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, ocr_job_id, template_id, marking_setup_id, STATUS_PENDING, 0, 0, created_at),
    )
    conn.commit()
    return ExtractionJob(
        extraction_job_id=cursor.lastrowid,
        attempt_id=attempt_id,
        ocr_job_id=ocr_job_id,
        template_id=template_id,
        marking_setup_id=marking_setup_id,
        status=STATUS_PENDING,
        region_count=0,
        extracted_count=0,
        error_message=None,
        created_at=created_at,
        completed_at=None,
    )


def mark_extraction_job_completed(
    conn: sqlite3.Connection, extraction_job_id: int, region_count: int, extracted_count: int
) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE extraction_jobs SET status = ?, region_count = ?, extracted_count = ?, completed_at = ? "
        "WHERE extraction_job_id = ?",
        (STATUS_COMPLETED, region_count, extracted_count, completed_at, extraction_job_id),
    )
    conn.commit()


def mark_extraction_job_failed(conn: sqlite3.Connection, extraction_job_id: int, error_message: str) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE extraction_jobs SET status = ?, error_message = ?, completed_at = ? WHERE extraction_job_id = ?",
        (STATUS_FAILED, error_message, completed_at, extraction_job_id),
    )
    conn.commit()


def get_extraction_job_by_id(conn: sqlite3.Connection, extraction_job_id: int) -> Optional[ExtractionJob]:
    row = conn.execute(
        "SELECT extraction_job_id, attempt_id, ocr_job_id, template_id, marking_setup_id, status, "
        "region_count, extracted_count, error_message, created_at, completed_at "
        "FROM extraction_jobs WHERE extraction_job_id = ?",
        (extraction_job_id,),
    ).fetchone()
    if row is None:
        return None
    return ExtractionJob(**dict(row))


def get_latest_extraction_job_for_attempt(conn: sqlite3.Connection, attempt_id: int) -> Optional[ExtractionJob]:
    row = conn.execute(
        "SELECT extraction_job_id, attempt_id, ocr_job_id, template_id, marking_setup_id, status, "
        "region_count, extracted_count, error_message, created_at, completed_at "
        "FROM extraction_jobs WHERE attempt_id = ? ORDER BY created_at DESC, extraction_job_id DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return None
    return ExtractionJob(**dict(row))


def get_extraction_job_for_combination(
    conn: sqlite3.Connection, attempt_id: int, ocr_job_id: int, template_id: int
) -> Optional[ExtractionJob]:
    row = conn.execute(
        "SELECT extraction_job_id, attempt_id, ocr_job_id, template_id, marking_setup_id, status, "
        "region_count, extracted_count, error_message, created_at, completed_at "
        "FROM extraction_jobs WHERE attempt_id = ? AND ocr_job_id = ? AND template_id = ? "
        "ORDER BY created_at DESC, extraction_job_id DESC LIMIT 1",
        (attempt_id, ocr_job_id, template_id),
    ).fetchone()
    if row is None:
        return None
    return ExtractionJob(**dict(row))


def add_extracted_region_result(
    conn: sqlite3.Connection,
    extraction_job_id: int,
    region_id: int,
    page_number: int,
    region_name: str,
    region_type: str,
    extracted_text: Optional[str],
    average_confidence: Optional[float],
    matched_block_count: int,
    extraction_status: str,
) -> ExtractedRegionResult:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO extracted_region_results "
        "(extraction_job_id, region_id, page_number, region_name, region_type, extracted_text, "
        "average_confidence, matched_block_count, extraction_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            extraction_job_id,
            region_id,
            page_number,
            region_name,
            region_type,
            extracted_text,
            average_confidence,
            matched_block_count,
            extraction_status,
            created_at,
        ),
    )
    conn.commit()
    return ExtractedRegionResult(
        result_id=cursor.lastrowid,
        extraction_job_id=extraction_job_id,
        region_id=region_id,
        page_number=page_number,
        region_name=region_name,
        region_type=region_type,
        extracted_text=extracted_text,
        average_confidence=average_confidence,
        matched_block_count=matched_block_count,
        extraction_status=extraction_status,
        created_at=created_at,
    )


def get_extracted_region_results_for_job(
    conn: sqlite3.Connection, extraction_job_id: int
) -> List[ExtractedRegionResult]:
    rows = conn.execute(
        "SELECT result_id, extraction_job_id, region_id, page_number, region_name, region_type, "
        "extracted_text, average_confidence, matched_block_count, extraction_status, created_at "
        "FROM extracted_region_results WHERE extraction_job_id = ? ORDER BY page_number, result_id",
        (extraction_job_id,),
    ).fetchall()
    return [ExtractedRegionResult(**dict(row)) for row in rows]


def add_extracted_region_block(
    conn: sqlite3.Connection,
    result_id: int,
    ocr_block_id: int,
    block_order: int,
    text: str,
    confidence: Optional[float],
) -> ExtractedRegionBlock:
    cursor = conn.execute(
        "INSERT INTO extracted_region_blocks (result_id, ocr_block_id, block_order, text, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        (result_id, ocr_block_id, block_order, text, confidence),
    )
    conn.commit()
    return ExtractedRegionBlock(
        extracted_block_id=cursor.lastrowid,
        result_id=result_id,
        ocr_block_id=ocr_block_id,
        block_order=block_order,
        text=text,
        confidence=confidence,
    )


def get_extracted_region_blocks_for_result(
    conn: sqlite3.Connection, result_id: int
) -> List[ExtractedRegionBlock]:
    rows = conn.execute(
        "SELECT extracted_block_id, result_id, ocr_block_id, block_order, text, confidence "
        "FROM extracted_region_blocks WHERE result_id = ? ORDER BY block_order",
        (result_id,),
    ).fetchall()
    return [ExtractedRegionBlock(**dict(row)) for row in rows]
