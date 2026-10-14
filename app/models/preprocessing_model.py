"""Document preprocessing job and page data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALLOWED_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED)

SOURCE_TYPE_REVISION_MATERIAL_QUESTION = "revision_material_question"
SOURCE_TYPE_REVISION_MATERIAL_MARKING_SCHEME = "revision_material_marking_scheme"
SOURCE_TYPE_REVISION_ATTEMPT_ANSWER = "revision_attempt_answer"
SOURCE_TYPE_EXTERNAL_REVISION_QUESTION = "external_revision_question"
SOURCE_TYPE_EXTERNAL_REVISION_MARKING_SCHEME = "external_revision_marking_scheme"
SOURCE_TYPE_EXTERNAL_REVISION_COMPLETED_ANSWER = "external_revision_completed_answer"
SOURCE_TYPE_TEMPLATE_SOURCE = "template_source"
SOURCE_TYPE_MANUAL_TEST = "manual_test"


@dataclass
class PreprocessingJob:
    job_id: int
    source_type: str
    source_id: Optional[int]
    original_file_path: str
    output_folder_path: str
    status: str
    page_count: int
    error_message: Optional[str]
    created_at: str
    completed_at: Optional[str]


@dataclass
class PreprocessingPage:
    page_id: int
    job_id: int
    page_number: int
    processed_image_path: str
    width: int
    height: int
    created_at: str


def create_job(
    conn: sqlite3.Connection,
    source_type: str,
    source_id: Optional[int],
    original_file_path: str,
    output_folder_path: str,
) -> PreprocessingJob:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO document_preprocessing_jobs "
        "(source_type, source_id, original_file_path, output_folder_path, status, page_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source_type, source_id, original_file_path, output_folder_path, STATUS_PENDING, 0, created_at),
    )
    conn.commit()
    return PreprocessingJob(
        job_id=cursor.lastrowid,
        source_type=source_type,
        source_id=source_id,
        original_file_path=original_file_path,
        output_folder_path=output_folder_path,
        status=STATUS_PENDING,
        page_count=0,
        error_message=None,
        created_at=created_at,
        completed_at=None,
    )


def update_job_output_folder(conn: sqlite3.Connection, job_id: int, output_folder_path: str) -> None:
    conn.execute(
        "UPDATE document_preprocessing_jobs SET output_folder_path = ? WHERE job_id = ?",
        (output_folder_path, job_id),
    )
    conn.commit()


def mark_job_completed(conn: sqlite3.Connection, job_id: int, page_count: int) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE document_preprocessing_jobs SET status = ?, page_count = ?, completed_at = ? WHERE job_id = ?",
        (STATUS_COMPLETED, page_count, completed_at, job_id),
    )
    conn.commit()


def mark_job_failed(conn: sqlite3.Connection, job_id: int, error_message: str) -> None:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE document_preprocessing_jobs SET status = ?, error_message = ?, completed_at = ? WHERE job_id = ?",
        (STATUS_FAILED, error_message, completed_at, job_id),
    )
    conn.commit()


def get_job_by_id(conn: sqlite3.Connection, job_id: int) -> Optional[PreprocessingJob]:
    row = conn.execute(
        "SELECT job_id, source_type, source_id, original_file_path, output_folder_path, status, "
        "page_count, error_message, created_at, completed_at "
        "FROM document_preprocessing_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return PreprocessingJob(**dict(row))


def get_latest_job_for_source(
    conn: sqlite3.Connection, source_type: str, source_id: Optional[int]
) -> Optional[PreprocessingJob]:
    row = conn.execute(
        "SELECT job_id, source_type, source_id, original_file_path, output_folder_path, status, "
        "page_count, error_message, created_at, completed_at "
        "FROM document_preprocessing_jobs WHERE source_type = ? AND source_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (source_type, source_id),
    ).fetchone()
    if row is None:
        return None
    return PreprocessingJob(**dict(row))


def add_page(
    conn: sqlite3.Connection,
    job_id: int,
    page_number: int,
    processed_image_path: str,
    width: int,
    height: int,
) -> PreprocessingPage:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO document_preprocessing_pages "
        "(job_id, page_number, processed_image_path, width, height, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, page_number, processed_image_path, width, height, created_at),
    )
    conn.commit()
    return PreprocessingPage(
        page_id=cursor.lastrowid,
        job_id=job_id,
        page_number=page_number,
        processed_image_path=processed_image_path,
        width=width,
        height=height,
        created_at=created_at,
    )


def get_pages_for_job(conn: sqlite3.Connection, job_id: int) -> List[PreprocessingPage]:
    rows = conn.execute(
        "SELECT page_id, job_id, page_number, processed_image_path, width, height, created_at "
        "FROM document_preprocessing_pages WHERE job_id = ? ORDER BY page_number",
        (job_id,),
    ).fetchall()
    return [PreprocessingPage(**dict(row)) for row in rows]
