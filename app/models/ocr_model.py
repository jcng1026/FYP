"""OCR job and result data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)


@dataclass
class OCRJob:
    ocr_job_id: int
    preprocessing_job_id: int
    source_type: str
    source_id: Optional[int]
    status: str
    page_count: int
    full_text: Optional[str]
    error_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class OCRPageResult:
    ocr_page_id: int
    ocr_job_id: int
    page_number: int
    text: Optional[str]
    average_confidence: Optional[float]
    created_at: str


@dataclass
class OCRTextBlock:
    ocr_block_id: int
    ocr_page_id: int
    block_order: int
    text: str
    confidence: Optional[float]
    x1: Optional[float]
    y1: Optional[float]
    x2: Optional[float]
    y2: Optional[float]
    x3: Optional[float]
    y3: Optional[float]
    x4: Optional[float]
    y4: Optional[float]
    created_at: str


def create_ocr_job(
    conn: sqlite3.Connection,
    preprocessing_job_id: int,
    source_type: str,
    source_id: Optional[int],
) -> OCRJob:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO ocr_jobs "
        "(preprocessing_job_id, source_type, source_id, status, page_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (preprocessing_job_id, source_type, source_id, STATUS_PENDING, 0, created_at),
    )
    conn.commit()
    return OCRJob(
        ocr_job_id=cursor.lastrowid,
        preprocessing_job_id=preprocessing_job_id,
        source_type=source_type,
        source_id=source_id,
        status=STATUS_PENDING,
        page_count=0,
        full_text=None,
        error_message=None,
        created_at=created_at,
        completed_at=None,
    )


def mark_ocr_job_completed(
    conn: sqlite3.Connection, ocr_job_id: int, page_count: int, full_text: str
) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE ocr_jobs SET status = ?, page_count = ?, full_text = ?, completed_at = ? "
        "WHERE ocr_job_id = ?",
        (STATUS_COMPLETED, page_count, full_text, completed_at, ocr_job_id),
    )
    conn.commit()


def mark_ocr_job_failed(conn: sqlite3.Connection, ocr_job_id: int, error_message: str) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE ocr_jobs SET status = ?, error_message = ?, completed_at = ? WHERE ocr_job_id = ?",
        (STATUS_FAILED, error_message, completed_at, ocr_job_id),
    )
    conn.commit()


def get_ocr_job_by_id(conn: sqlite3.Connection, ocr_job_id: int) -> Optional[OCRJob]:
    row = conn.execute(
        "SELECT ocr_job_id, preprocessing_job_id, source_type, source_id, status, page_count, "
        "full_text, error_message, created_at, completed_at FROM ocr_jobs WHERE ocr_job_id = ?",
        (ocr_job_id,),
    ).fetchone()
    if row is None:
        return None
    return OCRJob(**dict(row))


def get_latest_ocr_job_for_preprocessing_job(
    conn: sqlite3.Connection, preprocessing_job_id: int
) -> Optional[OCRJob]:
    row = conn.execute(
        "SELECT ocr_job_id, preprocessing_job_id, source_type, source_id, status, page_count, "
        "full_text, error_message, created_at, completed_at FROM ocr_jobs "
        "WHERE preprocessing_job_id = ? ORDER BY created_at DESC, ocr_job_id DESC LIMIT 1",
        (preprocessing_job_id,),
    ).fetchone()
    if row is None:
        return None
    return OCRJob(**dict(row))


def add_ocr_page_result(
    conn: sqlite3.Connection,
    ocr_job_id: int,
    page_number: int,
    text: Optional[str],
    average_confidence: Optional[float],
) -> OCRPageResult:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO ocr_page_results (ocr_job_id, page_number, text, average_confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ocr_job_id, page_number, text, average_confidence, created_at),
    )
    conn.commit()
    return OCRPageResult(
        ocr_page_id=cursor.lastrowid,
        ocr_job_id=ocr_job_id,
        page_number=page_number,
        text=text,
        average_confidence=average_confidence,
        created_at=created_at,
    )


def get_ocr_page_results_for_job(conn: sqlite3.Connection, ocr_job_id: int) -> List[OCRPageResult]:
    rows = conn.execute(
        "SELECT ocr_page_id, ocr_job_id, page_number, text, average_confidence, created_at "
        "FROM ocr_page_results WHERE ocr_job_id = ? ORDER BY page_number",
        (ocr_job_id,),
    ).fetchall()
    return [OCRPageResult(**dict(row)) for row in rows]


def add_ocr_text_block(
    conn: sqlite3.Connection,
    ocr_page_id: int,
    block_order: int,
    text: str,
    confidence: Optional[float],
    x1: Optional[float],
    y1: Optional[float],
    x2: Optional[float],
    y2: Optional[float],
    x3: Optional[float],
    y3: Optional[float],
    x4: Optional[float],
    y4: Optional[float],
) -> OCRTextBlock:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO ocr_text_blocks "
        "(ocr_page_id, block_order, text, confidence, x1, y1, x2, y2, x3, y3, x4, y4, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ocr_page_id, block_order, text, confidence, x1, y1, x2, y2, x3, y3, x4, y4, created_at),
    )
    conn.commit()
    return OCRTextBlock(
        ocr_block_id=cursor.lastrowid,
        ocr_page_id=ocr_page_id,
        block_order=block_order,
        text=text,
        confidence=confidence,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        x3=x3,
        y3=y3,
        x4=x4,
        y4=y4,
        created_at=created_at,
    )


def get_ocr_text_blocks_for_page(conn: sqlite3.Connection, ocr_page_id: int) -> List[OCRTextBlock]:
    rows = conn.execute(
        "SELECT ocr_block_id, ocr_page_id, block_order, text, confidence, "
        "x1, y1, x2, y2, x3, y3, x4, y4, created_at "
        "FROM ocr_text_blocks WHERE ocr_page_id = ? ORDER BY block_order",
        (ocr_page_id,),
    ).fetchall()
    return [OCRTextBlock(**dict(row)) for row in rows]
