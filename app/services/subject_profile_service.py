"""Subject Profile service layer (Stage 11V) - the teacher-facing Marking
tab redesign that replaces the old "choose a Template + paper type"
workflow with a single Subject Profile: a question paper PDF, an answer
scheme PDF, teacher-defined regions/groups, and an answer key, all owned
by one profile.

Student answer PDF handling reuses main_marking_service.py's session/
answer-file machinery (Stage 11L-11N) - one small main_marking_session is
created per uploaded student PDF (each holding exactly that one answer
file), which gives genuine PDF-by-PDF isolation for free: a failure
processing one student's PDF cannot corrupt another student's session/
answer-file rows.

Extraction and marking are Subject-Profile-specific (they read
subject_profile_regions/groups instead of template_regions). Stage 11Y-Fix:
extraction crops each region DIRECTLY from the student's original PDF (see
app.services.region_crop_ocr_service) instead of first rendering every
page - full-page rendering (main_marking_service.run_preprocessing_for_
session) is only ever done lazily, later, the first time a teacher opens
the Marking Editor for that student (see
ensure_full_page_render_for_answer_file), never during upload/extraction.
"""

import json
import re
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pymupdf

from app.models.main_marking_model import (
    MARKED_ANSWER_STATUS_MARKED as MAIN_MARKING_MARKED,
    PAGE_STATUS_PREPROCESSED,
    add_answer_file as add_answer_file_record,
    create_session as create_session_record,
    get_answer_file_by_id,
    get_answer_files_for_session as get_answer_files_for_session_record,
    get_preprocessed_pages_for_answer_file as get_preprocessed_pages_for_answer_file_record,
    get_session_by_id,
)
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1
from app.models.subject_profile_model import (
    ALL_SUBJECT_PROFILE_REGION_TYPES,
    EXTRACTED_ANSWER_STATUS_EXTRACTED,
    EXTRACTED_ANSWER_STATUS_FAILED,
    EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
    EXTRACTED_ANSWER_STATUS_NO_TEXT,
    IGNORED_REGION_TYPES,
    NON_ANSWER_REGION_TYPES,
    REGION_TYPE_BUBBLE_AREA,
    REGION_TYPE_LEGEND_OR_SELECTOR_TYPES,
    REGION_TYPE_LETTER_BOX,
    REGION_TYPE_UNDERLINE_ANSWER,
    extract_question_number_from_label,
    MARKED_ANSWER_STATUS_FAILED,
    MARKED_ANSWER_STATUS_MARKED,
    MARKED_ANSWER_STATUS_MISSING_ANSWER_KEY,
    MARKED_ANSWER_STATUS_NEEDS_REVIEW,
    MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE,
    MARKED_ANSWER_STATUS_TEACHER_SCORED,
    TEACHER_STATUS_CORRECT,
    TEACHER_STATUS_NEEDS_REVIEW,
    TEACHER_STATUS_PENDING_TEACHER_SCORE,
    TEACHER_STATUS_TEACHER_SCORED,
    TEACHER_STATUS_WRONG,
    OVERLAY_KIND_CROSS,
    OVERLAY_KIND_FEEDBACK,
    OVERLAY_KIND_PERCENTAGE,
    OVERLAY_KIND_TICK,
    OVERLAY_SYMBOL_CROSS,
    OVERLAY_SYMBOL_QUESTION,
    OVERLAY_SYMBOL_TICK,
    QUESTION_NUMBER_REGION_TYPES,
    REGION_TYPE_ANSWER_BOX,
    REGION_TYPE_ANSWER_REGION,
    REGION_TYPE_QUESTION_NUMBER_BOX,
    SOURCE_ANSWER_SCHEME,
    SOURCE_QUESTION_PAPER,
    STATUS_DRAFT,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
    TARGET_KIND_GROUP,
    TARGET_KIND_REGION,
    SubjectProfile,
    SubjectProfileAnswerKeyEntry,
    SubjectProfileMarkedAnswer,
    SubjectProfileOverlay,
    SubjectProfileRegion,
    SubjectProfileRegionGroup,
    add_extracted_answer as add_extracted_answer_record,
    add_marked_answer as add_marked_answer_record,
    add_overlay as add_overlay_record,
    add_region_group_member,
    add_subject_profile_region,
    create_or_update_answer_key_entry,
    create_subject_profile as create_subject_profile_record,
    create_subject_profile_region_group,
    delete_extracted_answers_for_answer_file,
    delete_marked_answers_for_answer_file,
    delete_overlay as delete_overlay_record,
    delete_overlays_for_answer_file,
    delete_subject_profile as delete_subject_profile_record,
    delete_subject_profile_region,
    delete_subject_profile_region_group,
    get_answer_key_entries_for_profile,
    get_extracted_answers_for_answer_file,
    get_marked_answer_by_id,
    get_marked_answers_for_answer_file,
    get_max_region_order,
    get_members_for_group,
    get_overlay_by_id,
    get_overlays_for_answer_file,
    get_region_by_id,
    get_region_group_by_id,
    update_region_group,
    get_region_groups_for_profile,
    get_regions_for_profile,
    get_subject_profile_by_id,
    get_subject_profiles_for_teacher,
    rename_subject_profile,
    update_overlay_transform as update_overlay_transform_record,
    update_subject_profile_extracted_content,
    update_subject_profile_files,
    update_subject_profile_ocr_content,
    update_subject_profile_region,
    update_subject_profile_region_geometry,
    update_subject_profile_status,
    update_marked_answer_score as update_marked_answer_score_record,
)
from app.services.main_marking_service import (
    get_answer_file_display_name,
    run_preprocessing_for_session,
)
from app.services.region_crop_ocr_service import (
    OCR_NEEDED_REGION_TYPES,
    LazyOCREngine,
    RegionCropOcrResult,
    STATUS_CACHED,
    STATUS_OCRED,
    STATUS_SKIPPED,
    compute_file_hash,
    load_crop_ocr_cache,
    ocr_tall_crop_in_chunks,
    render_region_crop_from_pdf,
    run_region_crop_ocr,
    save_crop_ocr_cache,
)
import app.services.region_suggestion_service as region_suggestion_service
from app.services.user_service import validate_teacher_exists
from app.utils.document_preprocessing import (
    extract_pdf_text_layer_pages,
    get_pdf_page_count,
    load_page_images,
    preprocess_page_image,
    save_page_image,
)
import app.utils.file_storage as file_storage
from app.utils.file_storage import (
    get_student_marking_processing_log_folder,
    get_subject_profile_answer_crop_folder,
    get_subject_profile_original_folder,
    get_subject_profile_preprocessed_folder,
    get_subject_profile_results_folder,
    store_subject_profile_file,
)
from app.utils.ocr_engine import OCREngine, get_default_engine

MAX_PROFILE_NAME_LENGTH = 150


def _validate_profile_name(profile_name: str) -> str:
    profile_name = (profile_name or "").strip()
    if not profile_name:
        raise ValueError("Subject Profile name is required.")
    if len(profile_name) > MAX_PROFILE_NAME_LENGTH:
        raise ValueError(f"Subject Profile name must be {MAX_PROFILE_NAME_LENGTH} characters or fewer.")
    return profile_name


def get_owned_subject_profile(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> SubjectProfile:
    """Return profile_id if it exists and is owned by teacher_id. Raises
    ValueError otherwise."""
    profile = get_subject_profile_by_id(conn, profile_id)
    if profile is None:
        raise ValueError("Subject Profile not found.")
    if profile.teacher_id != teacher_id:
        raise ValueError("You can only manage your own Subject Profiles.")
    return profile


def create_subject_profile(conn: sqlite3.Connection, teacher_id: int, profile_name: str) -> SubjectProfile:
    """Create a new, empty Subject Profile (status 'draft') owned by
    teacher_id. Raises ValueError if the requester is not a teacher or the
    name is empty/too long."""
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create Subject Profiles.")
    profile_name = _validate_profile_name(profile_name)
    return create_subject_profile_record(conn, teacher_id, profile_name)


def list_subject_profiles_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[SubjectProfile]:
    return get_subject_profiles_for_teacher(conn, teacher_id)


def get_subject_profile(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> SubjectProfile:
    return get_owned_subject_profile(conn, teacher_id, profile_id)


def delete_subject_profile(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> None:
    """Hard delete profile_id and everything it owns (Stage 11W):
    - the subject_profiles row itself
    - its regions / region groups / group members / answer key entries
      (all ON DELETE CASCADE from subject_profiles.profile_id)
    - every main_marking_session created for this profile's student PDF
      uploads (subject_profile_id == profile_id), which cascades to that
      session's answer files, OCR results, preprocessed pages, and (via
      answer_file_id) this profile's own extracted/marked answers and
      overlays for those students
    - the profile's on-disk storage folder (question paper/answer scheme
      files, preprocessed+original page images, and per-student result
      folders/ZIP - all nested under data/subject_profiles/profile_{id}/)
    - each deleted session's own on-disk storage folder
      (data/main_marking_sessions/session_{id}/)

    Never touches any other profile's folder, any other Main Marking
    session not owned by this profile, data/app.db, or any backend table
    definitions. Raises ValueError if the profile doesn't exist, isn't
    owned by teacher_id, or is currently processing."""
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if profile.status == STATUS_PROCESSING:
        raise ValueError("Cannot delete a Subject Profile while it is still processing.")

    session_ids = [
        row[0] for row in conn.execute(
            "SELECT session_id FROM main_marking_sessions WHERE subject_profile_id = ? AND teacher_id = ?",
            (profile_id, teacher_id),
        ).fetchall()
    ]
    for session_id in session_ids:
        # Cascades to that session's answer files, which cascades to OCR
        # results/preprocessed pages/subject_profile_extracted_answers/
        # subject_profile_marked_answers/subject_profile_overlays.
        conn.execute("DELETE FROM main_marking_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        session_folder = file_storage.MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}"
        if session_folder.exists():
            shutil.rmtree(session_folder, ignore_errors=True)

    delete_subject_profile_record(conn, profile_id)

    profile_folder = file_storage.SUBJECT_PROFILES_DIR / f"profile_{profile_id}"
    if profile_folder.exists():
        shutil.rmtree(profile_folder, ignore_errors=True)


# --- Question paper / answer scheme processing (Stage 11V step 2-5) --------


ProgressCallback = Optional[Callable[[str, int, int], None]]


def _report(callback: ProgressCallback, message: str, current: int, total: int) -> None:
    if callback is not None:
        callback(message, current, total)


def _preprocess_and_ocr_document(
    profile_id: int, source: str, file_path: str, callback: ProgressCallback,
    lazy_engine: Optional[LazyOCREngine] = None,
) -> dict:
    """Preprocess every page of file_path (a question paper or answer
    scheme PDF), reporting progress via callback(message, current,
    total_steps). Returns a dict with 'pages': [{"page_number", "text",
    "confidence", "blocks", "image_path", "original_image_path", "source"}]
    - stored as JSON on the Subject Profile row. "source" is one of
    "pdf_text_layer" (no OCR run - see below), "ocr" (OCR ran and
    succeeded), or "ocr_failed" (OCR ran and raised - "error" also set).

    Stage 12E-2-Fix: PREFERS the PDF's own embedded text layer
    (document_preprocessing.extract_pdf_text_layer_pages) over OCR for any
    page that has one - a digitally-generated PDF (e.g. an SPM workbook)
    already has exact text per page, so OCR is both unnecessary AND, per
    manual verification on real samples, a real native-process crash risk
    for the OCR engine on some real inputs. lazy_engine (an already-shared
    LazyOCREngine, or a fresh one created lazily here) means the OCR
    engine is only ever constructed if at least one page genuinely lacks a
    text layer - a fully "digital" PDF (every page has real text) never
    touches the OCR engine at all. An OCR failure on one page is caught and
    recorded ("ocr_failed"/"error") rather than raised, so it can never
    abort the rest of this document's pages or the whole profile creation.

    Stage 11W: also saves each page's ORIGINAL (un-degraded) rendered image
    (original_image_path) alongside the CLAHE/denoise/threshold-processed
    one used for OCR (image_path), so a clean digital PDF's editor preview
    never looks worse than the source - see get_document_page_image_paths,
    which prefers original_image_path.

    This is a from-scratch orchestration (not main_marking_service's
    session-based preprocessing/OCR) since a question paper/answer scheme
    is not itself a "student answer file" - there is no session/answer_file
    row for it, matching the Subject Profile's own suggested schema (JSON
    blob columns directly on subject_profiles)."""
    total_pages = get_pdf_page_count(file_path) or 1
    total_steps = total_pages * 2  # preprocess + OCR-or-text-layer per page
    step = 0

    images = load_page_images(file_path)
    folder = get_subject_profile_preprocessed_folder(profile_id, source)
    original_folder = get_subject_profile_original_folder(profile_id, source)
    text_layer_pages = extract_pdf_text_layer_pages(file_path)
    if lazy_engine is None:
        lazy_engine = LazyOCREngine(resolver=get_default_engine)

    pages_output = []
    for page_number, raw_image in enumerate(images, start=1):
        step += 1
        _report(callback, f"Preprocessing {source.replace('_', ' ')} page {page_number} of {total_pages}", step, total_steps)
        original_path = original_folder / f"page_{page_number}.png"
        save_page_image(raw_image, original_path)

        processed = preprocess_page_image(raw_image)
        image_path = folder / f"page_{page_number}.png"
        save_page_image(processed, image_path)

        step += 1
        text_layer = text_layer_pages.get(page_number)
        if text_layer is not None:
            _report(
                callback,
                f"PDF text layer detected for {source.replace('_', ' ')} page {page_number} of {total_pages} - OCR skipped",
                step, total_steps,
            )
            pages_output.append({
                "page_number": page_number,
                "text": text_layer,
                "confidence": 1.0,
                "blocks": [],
                "image_path": str(image_path),
                "original_image_path": str(original_path),
                "source": "pdf_text_layer",
            })
            continue

        _report(callback, f"Running OCR on {source.replace('_', ' ')} page {page_number} of {total_pages}", step, total_steps)
        try:
            engine = lazy_engine.get()
            result = engine.run_page(str(image_path))
            pages_output.append({
                "page_number": page_number,
                "text": result.text,
                "confidence": result.average_confidence,
                "blocks": [{"text": b.text, "confidence": b.confidence, "box": b.box} for b in result.blocks],
                "image_path": str(image_path),
                "original_image_path": str(original_path),
                "source": "ocr",
            })
        except Exception as exc:
            pages_output.append({
                "page_number": page_number,
                "text": None,
                "confidence": None,
                "blocks": [],
                "image_path": str(image_path),
                "original_image_path": str(original_path),
                "error": str(exc),
                "source": "ocr_failed",
            })

    return {"pages": pages_output}


def process_subject_profile_documents(
    conn: sqlite3.Connection,
    teacher_id: int,
    profile_id: int,
    question_paper_source_path: str,
    answer_scheme_source_path: str,
    progress_callback: ProgressCallback = None,
) -> SubjectProfile:
    """Store and preprocess a Subject Profile's question paper and answer
    scheme PDFs (Stage 11V steps 2-5), preferring each page's own PDF text
    layer over OCR wherever one exists (Stage 12E-2-Fix - see
    _preprocess_and_ocr_document). Reports progress via progress_callback
    (message, current_step, total_steps) if given. A page whose OCR fails
    is recorded, never fatal - see summarize_document_processing for a
    teacher-facing summary of how many pages used the text layer vs. OCR
    vs. failed OCR, to show after this returns.

    Raises ValueError if the profile doesn't exist or isn't owned by
    teacher_id. Only a genuinely unreadable PDF (not just "OCR failed on
    a page") - e.g. load_page_images itself raising - fails profile
    creation outright.
    """
    get_owned_subject_profile(conn, teacher_id, profile_id)
    update_subject_profile_status(conn, profile_id, STATUS_PROCESSING)

    try:
        question_paper_path = store_subject_profile_file(profile_id, question_paper_source_path, "question_paper")
        answer_scheme_path = store_subject_profile_file(profile_id, answer_scheme_source_path, "answer_scheme")
        update_subject_profile_files(conn, profile_id, question_paper_path, answer_scheme_path)

        shared_lazy_engine = LazyOCREngine(resolver=get_default_engine)
        qp_result = _preprocess_and_ocr_document(
            profile_id, SOURCE_QUESTION_PAPER, question_paper_path, progress_callback, lazy_engine=shared_lazy_engine,
        )
        as_result = _preprocess_and_ocr_document(
            profile_id, SOURCE_ANSWER_SCHEME, answer_scheme_path, progress_callback, lazy_engine=shared_lazy_engine,
        )

        _report(progress_callback, "Saving Subject Profile", 1, 1)
        update_subject_profile_ocr_content(
            conn, profile_id,
            question_paper_ocr_json=json.dumps(qp_result),
            answer_scheme_ocr_json=json.dumps(as_result),
        )
        # A naive first-pass "extracted content" is just the per-page OCR text
        # joined together - real per-region extracted content is computed once
        # the teacher defines regions (see build_extracted_content_preview).
        update_subject_profile_extracted_content(
            conn, profile_id,
            question_paper_extracted_json=json.dumps([p.get("text") or "" for p in qp_result["pages"]]),
            answer_scheme_extracted_json=json.dumps([p.get("text") or "" for p in as_result["pages"]]),
        )
    except Exception:
        update_subject_profile_status(conn, profile_id, STATUS_FAILED)
        raise

    update_subject_profile_status(conn, profile_id, STATUS_READY)
    return get_owned_subject_profile(conn, teacher_id, profile_id)


def summarize_document_processing(profile: SubjectProfile) -> dict:
    """Summarize how process_subject_profile_documents resolved each page
    of profile's question paper + answer scheme (Stage 12E-2-Fix): counts
    of pages that used the PDF's own text layer (no OCR needed), pages OCR
    succeeded on, and pages OCR failed on. Lets the UI show a clear,
    accurate, non-scary status message ("PDF text layer detected; OCR
    skipped for setup." / a non-blocking OCR-failure warning) instead of
    guessing. Safe on a profile created before this field existed - those
    pages simply aren't counted in any bucket (all zero is a valid,
    harmless result, not an error)."""
    summary = {"text_layer_pages": 0, "ocr_pages": 0, "ocr_failed_pages": 0, "total_pages": 0}
    for ocr_json in (profile.question_paper_ocr_json, profile.answer_scheme_ocr_json):
        if not ocr_json:
            continue
        try:
            data = json.loads(ocr_json)
        except json.JSONDecodeError:
            continue
        for page in data.get("pages", []):
            summary["total_pages"] += 1
            if page.get("source") == "pdf_text_layer":
                summary["text_layer_pages"] += 1
            elif page.get("error") or page.get("source") == "ocr_failed":
                summary["ocr_failed_pages"] += 1
            elif page.get("source") == "ocr":
                summary["ocr_pages"] += 1
    return summary


def get_document_page_image_paths(conn: sqlite3.Connection, teacher_id: int, profile_id: int, source: str) -> List[str]:
    """Return the stored page image paths for source ('question_paper' or
    'answer_scheme'), in page order, for the Subject Profile editor's page
    preview. Prefers each page's ORIGINAL (un-degraded) rendered image
    (Stage 11W) over the CLAHE/denoise/threshold-processed one used for OCR,
    falling back to the processed image for any profile created before
    original_image_path existed. Raises ValueError if not owned."""
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    ocr_json = profile.question_paper_ocr_json if source == SOURCE_QUESTION_PAPER else profile.answer_scheme_ocr_json
    if not ocr_json:
        return []
    data = json.loads(ocr_json)
    return [p.get("original_image_path") or p["image_path"] for p in data.get("pages", [])]


# --- Region / group management (Stage 11V step 6-8) -------------------------


def add_region(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, source: str, label: str, region_type: str,
    page_number: int, x: float, y: float, width: float, height: float,
    shape_type: str = "rectangle", polygon_points_json: Optional[str] = None,
    rotation_angle: float = 0.0, notes: Optional[str] = None,
) -> SubjectProfileRegion:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    if region_type not in ALL_SUBJECT_PROFILE_REGION_TYPES:
        raise ValueError(f"Unknown region type: {region_type!r}")
    if source not in (SOURCE_QUESTION_PAPER, SOURCE_ANSWER_SCHEME):
        raise ValueError(f"Unknown source: {source!r}")
    order_index = get_max_region_order(conn, profile_id, page_number) + 1
    return add_subject_profile_region(
        conn, profile_id, source, label, region_type, page_number, x, y, width, height,
        shape_type, polygon_points_json, rotation_angle, order_index, notes,
    )


def edit_region(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, region_id: int,
    label: str, region_type: str, rotation_angle: float, notes: Optional[str] = None,
) -> SubjectProfileRegion:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    region = get_region_by_id(conn, region_id)
    if region is None or region.profile_id != profile_id:
        raise ValueError("Region not found.")
    if region_type not in ALL_SUBJECT_PROFILE_REGION_TYPES:
        raise ValueError(f"Unknown region type: {region_type!r}")
    update_subject_profile_region(conn, region_id, label, region_type, rotation_angle, region.order_index, notes)
    return get_region_by_id(conn, region_id)


def move_region(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, region_id: int,
    x: float, y: float, width: float, height: float, polygon_points_json: Optional[str] = None,
) -> SubjectProfileRegion:
    """Persist a region's new position/size (Stage 12E-2 UX Fix 2 drag-to-
    move/resize on the Subject Profile Editor's preview canvas). Used for
    BOTH a move (only x/y actually change, width/height passed through
    unchanged) and a resize (x/y/width/height may all change) - the
    underlying persisted fields are identical either way. Never touches
    label/region_type/notes/order_index, so a suggested region's label and
    review notes survive a geometry edit unchanged."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    region = get_region_by_id(conn, region_id)
    if region is None or region.profile_id != profile_id:
        raise ValueError("Region not found.")
    update_subject_profile_region_geometry(conn, region_id, x, y, width, height, polygon_points_json)
    return get_region_by_id(conn, region_id)


def remove_region(conn: sqlite3.Connection, teacher_id: int, profile_id: int, region_id: int) -> None:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    region = get_region_by_id(conn, region_id)
    if region is None or region.profile_id != profile_id:
        raise ValueError("Region not found.")
    delete_subject_profile_region(conn, region_id)


def list_regions(conn: sqlite3.Connection, teacher_id: int, profile_id: int, source: Optional[str] = None) -> List[SubjectProfileRegion]:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    return get_regions_for_profile(conn, profile_id, source)


# --- Answer scheme preview (Stage 12E-2 requirement 7) ----------------------
#
# region_suggestion_service.py is a pure/stateless text-layer parser (no
# sqlite3.Connection, no ownership checks); these wrappers add the DB-aware
# ownership/path resolution. The former rule-based region-suggestion engine
# was removed in favour of the trained Core AI 2 detector (see
# ai_region_proposal_service).


def preview_answer_scheme_answer_list(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int,
) -> List["region_suggestion_service.ParsedAnswerSchemeEntry"]:
    """Read-only preview of objective answer-list entries parsed from the
    profile's answer scheme PDF (Stage 12E-2 requirement 7) - never writes
    to the answer key. Raises ValueError if not owned; returns [] (never
    raises) if no answer scheme PDF is set yet or parsing finds nothing."""
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if not profile.answer_scheme_path:
        return []
    return region_suggestion_service.parse_answer_scheme_answer_list(profile.answer_scheme_path)


def preview_answer_scheme_formatted_text(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> str:
    """A clean, Part-grouped, human-readable preview string (Stage 12E-2
    Quality Pass requirement 3) for the profile's answer scheme PDF - for
    DISPLAY only (see preview_answer_scheme_answer_list for the structured
    entries apply_parsed_answer_scheme_entries needs). Raises ValueError if
    not owned; returns "" (never raises) if no answer scheme PDF is set
    yet or parsing finds nothing."""
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if not profile.answer_scheme_path:
        return ""
    return region_suggestion_service.parse_answer_scheme_preview(profile.answer_scheme_path)


def apply_parsed_answer_scheme_entries(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int,
    entries: List["region_suggestion_service.ParsedAnswerSchemeEntry"], overwrite: bool = False,
) -> List[str]:
    """Write parsed answer-scheme entries into the Subject Profile's answer
    key, one per question_no (target_label f"Q{question_no}", target_kind
    "region" - matching the existing manual answer-key convention). Never
    overwrites an existing entry that already has a non-empty
    correct_answer UNLESS overwrite=True is explicitly passed (the UI must
    get the teacher's confirmation first) - satisfies the "not overwrite
    existing teacher answer keys without confirmation" requirement. Returns
    the target_labels actually written; an individual bad entry is skipped,
    never aborts the whole batch."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    existing_by_label = {e.target_label: e for e in get_answer_key_entries_for_profile(conn, profile_id)}
    written = []
    for entry in entries:
        target_label = f"Q{entry.question_no}"
        existing_entry = existing_by_label.get(target_label)
        if existing_entry is not None and existing_entry.correct_answer and not overwrite:
            continue
        try:
            save_answer_key_entry(
                conn, teacher_id, profile_id, target_label, TARGET_KIND_REGION,
                entry.question_no, entry.answer,
                existing_entry.max_mark if existing_entry is not None else 1.0,
                existing_entry.comment if existing_entry is not None else None,
            )
        except ValueError:
            continue
        written.append(target_label)
    return written


def create_region_group(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, label: str,
    region_type: str, region_ids: List[int], notes: Optional[str] = None,
) -> SubjectProfileRegionGroup:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    if region_type in IGNORED_REGION_TYPES:
        raise ValueError("A region group cannot use the ignore_region type.")
    if len(set(region_ids)) < 2:
        raise ValueError("A region group needs at least 2 distinct regions.")
    for region_id in region_ids:
        region = get_region_by_id(conn, region_id)
        if region is None or region.profile_id != profile_id:
            raise ValueError("All regions in a group must belong to this Subject Profile.")

    group = create_subject_profile_region_group(conn, profile_id, label, region_type, notes)
    for order, region_id in enumerate(region_ids, start=1):
        add_region_group_member(conn, group.group_id, region_id, order)
    return group


def edit_region_group(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, group_id: int,
    label: str, region_type: str,
) -> None:
    """Rename a region group / change its region type - the group-level
    counterpart of edit_region, with the same ownership check."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    group = get_region_group_by_id(conn, group_id)
    if group is None or group.profile_id != profile_id:
        raise ValueError("Region group not found.")
    if region_type not in ALL_SUBJECT_PROFILE_REGION_TYPES:
        raise ValueError(f"Unknown region type: {region_type!r}")
    if not (label or "").strip():
        raise ValueError("Group name cannot be empty.")
    update_region_group(conn, group_id, label.strip(), region_type)


def remove_region_group(conn: sqlite3.Connection, teacher_id: int, profile_id: int, group_id: int) -> None:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    group = get_region_group_by_id(conn, group_id)
    if group is None or group.profile_id != profile_id:
        raise ValueError("Region group not found.")
    delete_subject_profile_region_group(conn, group_id)


def list_region_groups(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> List[SubjectProfileRegionGroup]:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    return get_region_groups_for_profile(conn, profile_id)


@dataclass
class SubjectProfileExtractionTarget:
    """Mirrors app.services.extraction_target_service.ExtractionTarget, but
    built from subject_profile_regions/groups instead of template_regions -
    the same additive design (region targets AND group targets, each group's
    own members also appearing individually)."""
    kind: str
    label: str
    region_type: str
    region: Optional[SubjectProfileRegion] = None
    members: List["SubjectProfileExtractionTarget"] = field(default_factory=list)
    group_id: Optional[int] = None


def _filter_gradeable_regions(regions: List[SubjectProfileRegion]) -> List[SubjectProfileRegion]:
    """Marking Output Cleanup Fix: drop two categories of non-gradeable
    region rows that NON_ANSWER_REGION_TYPES alone can't catch, since both
    use an otherwise-gradeable region_type (bubble_area/letter_box):

    1. Legend/options-list/selector helper regions with NO derivable
       question number - e.g. qp_p9_part4_options_A_H (the shared A-H
       options list printed once for the whole Part 4, not any single
       question's own answer) or qp_p16_question_number_field ("which
       question did you answer for Part 3", not itself a graded answer).
       Kertas 2 answer_box essays are deliberately EXEMPT from this rule:
       Part 3's own essay legitimately has no "_qN_" in its label (only
       Part 1/2's answer boxes do) and is always a real, gradeable target
       regardless - see run_subject_profile_marking's REGION_TYPE_ANSWER_
       BOX handling, which never depends on a derivable question number.

    2. A '_cont' duplicate/continuation region sharing its derived
       question number with another, non-'_cont' region in this same list
       (e.g. qp_p7_q23_choices_cont alongside qp_p7_q23_choices) - the
       primary region already fully represents that question, so the
       continuation region must never become its own separate extracted/
       scored/comment/overlay item. A '_cont' region is KEPT if it is the
       ONLY region carrying its question number (nothing else to cover
       that question)."""
    kept: List[SubjectProfileRegion] = []
    by_question_no: Dict[str, List[SubjectProfileRegion]] = {}
    for region in regions:
        if region.region_type in REGION_TYPE_LEGEND_OR_SELECTOR_TYPES and extract_question_number_from_label(region.label) is None:
            continue
        kept.append(region)
        question_no = extract_question_number_from_label(region.label)
        if question_no is not None:
            by_question_no.setdefault(question_no, []).append(region)

    excluded_ids = set()
    for question_no, group in by_question_no.items():
        if len(group) < 2:
            continue
        has_primary = any(not r.label.endswith("_cont") for r in group)
        if not has_primary:
            continue
        excluded_ids.update(r.region_id for r in group if r.label.endswith("_cont"))

    return [r for r in kept if r.region_id not in excluded_ids]


def list_subject_profile_extraction_targets(
    conn: sqlite3.Connection, profile_id: int, source: str = SOURCE_QUESTION_PAPER
) -> List[SubjectProfileExtractionTarget]:
    """Return one 'region' target per gradable-answer region from source
    (excluding ignore_region, question_number_box, student_info_area, and
    extra_page_label - none of those hold answer content to extract/mark -
    plus, per _filter_gradeable_regions, legend/selector helper regions and
    redundant '_cont' duplicates of an already-covered question), plus one
    'group' target per region group whose members are region targets from
    that same source. Read-only, no ownership check (matches extraction_
    target_service's own unauthenticated convention)."""
    regions = [r for r in get_regions_for_profile(conn, profile_id, source) if r.region_type not in NON_ANSWER_REGION_TYPES]
    regions = _filter_gradeable_regions(regions)
    region_targets_by_id = {
        r.region_id: SubjectProfileExtractionTarget(kind=TARGET_KIND_REGION, label=r.label, region_type=r.region_type, region=r)
        for r in regions
    }
    targets = list(region_targets_by_id.values())

    for group in get_region_groups_for_profile(conn, profile_id):
        members = []
        for member in get_members_for_group(conn, group.group_id):
            target = region_targets_by_id.get(member.region_id)
            if target is not None:
                members.append(target)
        if members:
            targets.append(SubjectProfileExtractionTarget(
                kind=TARGET_KIND_GROUP, label=group.label, region_type=group.region_type,
                members=members, group_id=group.group_id,
            ))
    return targets


# --- Answer key entries (Stage 11V step 8) -----------------------------------


def save_answer_key_entry(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, target_label: str, target_kind: str,
    question_no: Optional[str], correct_answer: Optional[str], max_mark: float, comment: Optional[str] = None,
) -> SubjectProfileAnswerKeyEntry:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    if max_mark < 0:
        raise ValueError("Max mark cannot be negative.")
    return create_or_update_answer_key_entry(
        conn, profile_id, target_label, target_kind, question_no, correct_answer, max_mark, comment
    )


def list_answer_key_entries(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> List[SubjectProfileAnswerKeyEntry]:
    get_owned_subject_profile(conn, teacher_id, profile_id)
    return get_answer_key_entries_for_profile(conn, profile_id)


def list_missing_answer_key_targets(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, source: str = SOURCE_QUESTION_PAPER,
) -> List[str]:
    """Marking Fix Follow-up (requirements 2/3): return "Question N" for
    every REQUIRED Kertas 1 question with no answer key entry yet - never
    a raw internal region label like "qp_p2_q1_choices", so a teacher can
    act on the warning without knowing the region-naming convention.

    A target only counts as "required" if it isn't a Kertas 2 answer_box
    (explicitly excluded - never answer-key-scored) AND a question number
    can be derived from its label (extract_question_number_from_label) -
    the latter excludes helper/legend/metadata regions with no derivable
    number (e.g. part4_options_A_H, question_number_field), per
    requirement 3's "do not count helper regions ... as answer-key-
    required targets." Multiple regions can share the same question
    number (e.g. a continuation region); the question is only reported
    missing if NONE of its regions have an entry yet - this is a per-
    QUESTION check, not a per-region one, so a plain continuation/duplicate
    region can never appear as its own separate "missing" item.

    Meant to be checked BEFORE marking so the teacher sees exactly what's
    missing instead of silently getting 0.0 scores - see MARKED_ANSWER_
    STATUS_MISSING_ANSWER_KEY, which is what marking itself now reports
    per missing target regardless of whether this was checked first."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    targets = list_subject_profile_extraction_targets(conn, profile_id, source)
    existing_labels = {e.target_label for e in get_answer_key_entries_for_profile(conn, profile_id)}

    labels_by_question_no: Dict[str, List[str]] = {}
    for target in targets:
        if target.region_type == REGION_TYPE_ANSWER_BOX:
            continue  # Kertas 2 writing - never answer-key-scored, see run_subject_profile_marking.
        question_no = extract_question_number_from_label(target.label)
        if question_no is None:
            continue
        labels_by_question_no.setdefault(question_no, []).append(target.label)

    missing_question_numbers = [
        question_no for question_no, labels in labels_by_question_no.items()
        if not any(label in existing_labels for label in labels)
    ]
    return [f"Question {qno}" for qno in sorted(missing_question_numbers, key=int)]


def extract_answer_key_from_answer_scheme(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, engine: Optional[OCREngine] = None,
    progress_callback: ProgressCallback = None,
) -> dict:
    """Marking Fix Follow-up 3 (requirements 1/2/4): OCR every answer_scheme
    answer_region region (the SAME "green answer_region" regions a teacher
    already defined on the answer scheme PDF - see region_suggestion_
    service/the region editor), parse each one's recognized "N.  ANSWER"
    lines (parse_kertas1_answers_from_text), and save/update an answer key
    entry for every Kertas 1 question-paper target whose derived question
    number was found among them. This is the whole job of the "Extract
    Answer Key from Answer Scheme" button - and since it's a plain
    on-demand action (not a one-time profile-creation step), it works
    identically for a profile created before this fix existed (requirement
    4's "backfill") as for a brand new one; there is no separate migration.

    Tall answer-scheme blocks are OCR'd in overlapping chunks (see
    ocr_tall_crop_in_chunks) - a single very tall crop was found to drop
    entire lines, not just clip their edges, confirmed against profile_14's
    real ~1800px "Part 2-4 answers" block. Regions are processed in page
    order and a question number's FIRST successfully parsed answer wins
    (a later region's parse never overwrites an earlier one) - a rare but
    real OCR misread ("27." read as "7.") was found to otherwise silently
    corrupt an already-correctly-parsed Q7 from an earlier region/page.

    Never raises for an individual unreadable/unparseable region or a
    missing engine - only if the profile itself isn't owned or has no
    answer scheme file uploaded yet. Returns a summary dict for the UI,
    each value a list of "Question N" strings (same format as list_
    missing_answer_key_targets):
      "extracted": newly saved (had no entry before)
      "already_set": had the SAME correct answer already (no real change)
      "overwritten": had a DIFFERENT correct answer, now replaced
      "missing": a required Kertas 1 question number never found in the
        parsed answer scheme text at all - still needs a manual answer
    """
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if not profile.answer_scheme_path or not Path(profile.answer_scheme_path).is_file():
        raise ValueError("No answer scheme file has been uploaded for this Subject Profile yet.")

    answer_scheme_regions = sorted(
        (r for r in get_regions_for_profile(conn, profile_id, SOURCE_ANSWER_SCHEME) if r.region_type == REGION_TYPE_ANSWER_REGION),
        key=lambda r: r.page_number,
    )

    total_steps = len(answer_scheme_regions) + 2  # regions + K2 text + saving
    if progress_callback:
        progress_callback("Reading the answer scheme...", 0, total_steps)
    parsed_answers: Dict[str, str] = {}
    if answer_scheme_regions:
        engine = engine or get_default_engine()
        document = pymupdf.open(profile.answer_scheme_path)
        try:
            for region_index, region in enumerate(answer_scheme_regions, start=1):
                if progress_callback:
                    progress_callback(
                        f"Reading answer region {region_index} of {len(answer_scheme_regions)} "
                        f"(page {region.page_number})...", region_index, total_steps)
                crop = render_region_crop_from_pdf(document, region)
                if crop is None:
                    continue
                text = ocr_tall_crop_in_chunks(crop, engine)
                for question_no, answer in parse_kertas1_answers_from_text(text).items():
                    parsed_answers.setdefault(question_no, answer)
        finally:
            document.close()
    if progress_callback:
        progress_callback("Extracting Kertas 2 marking scheme text...",
                          total_steps - 1, total_steps)

    qp_targets = list_subject_profile_extraction_targets(conn, profile_id, SOURCE_QUESTION_PAPER)
    # Option 3: for a target whose label carries no question number (Core AI 2
    # auto-detected 'ai_...' regions accepted straight from Detect Answer
    # Regions), recover the number by OCR'ing the nearest detected
    # question_number_box. Only worthwhile when the scheme actually yielded
    # number-keyed answers to match against; the question paper PDF is opened
    # lazily and each target's number box is OCR'd at most once.
    number_box_regions = ([r for r in get_regions_for_profile(conn, profile_id, SOURCE_QUESTION_PAPER)
                           if r.region_type == REGION_TYPE_QUESTION_NUMBER_BOX] if parsed_answers else [])
    _qp_doc_holder: List = []

    def _qp_doc():
        if not _qp_doc_holder:
            if profile.question_paper_path and Path(profile.question_paper_path).is_file():
                _qp_doc_holder.append(pymupdf.open(profile.question_paper_path))
            else:
                _qp_doc_holder.append(None)
        return _qp_doc_holder[0]

    _recovered_cache: Dict[str, Optional[str]] = {}

    def _recover(target) -> Optional[str]:
        if not number_box_regions:
            return None
        if target.label not in _recovered_cache:
            doc = _qp_doc()
            _recovered_cache[target.label] = (
                _recover_question_number_from_number_box(target, number_box_regions, doc, engine)
                if doc is not None else None)
        return _recovered_cache[target.label]

    labels_by_question_no: Dict[str, List[Tuple[str, str]]] = {}
    recovered_question_nos: set = set()
    for target in qp_targets:
        if target.region_type == REGION_TYPE_ANSWER_BOX:
            continue
        question_no = extract_question_number_from_label(target.label)
        if question_no is None:
            question_no = _recover(target)
            if question_no is not None:
                recovered_question_nos.add(question_no)
        if question_no is None:
            continue
        labels_by_question_no.setdefault(question_no, []).append((target.label, target.kind))

    existing_entries = {e.target_label: e for e in get_answer_key_entries_for_profile(conn, profile_id)}

    extracted: List[str] = []
    already_set: List[str] = []
    overwritten: List[str] = []
    missing: List[str] = []
    unlabelled: List[str] = []
    recovered: List[str] = []  # filled via an OCR'd number box - teacher should verify
    for question_no, label_kinds in sorted(labels_by_question_no.items(), key=lambda kv: int(kv[0])):
        answer = parsed_answers.get(question_no)
        if answer is None:
            missing.append(f"Question {question_no}")
            continue
        if question_no in recovered_question_nos:
            recovered.append(f"Question {question_no}")

        primary_label, _primary_kind = label_kinds[0]
        primary_existing = existing_entries.get(primary_label)
        if primary_existing is None:
            extracted.append(f"Question {question_no}")
        elif _normalize_answer_text(primary_existing.correct_answer) != _normalize_answer_text(answer):
            overwritten.append(f"Question {question_no}")
        else:
            already_set.append(f"Question {question_no}")

        for label, target_kind in label_kinds:
            existing = existing_entries.get(label)
            save_answer_key_entry(
                conn, teacher_id, profile_id, label, target_kind, question_no, answer,
                existing.max_mark if existing else 1.0, existing.comment if existing else None,
            )

    # Kertas 2 writing targets: the scheme's per-Part marking guidance text
    # becomes the answer key entry's scheme text (what Mark Answers copies
    # into each attempt as correct_answer_text, and what Core AI 1 drafting
    # and feedback templates read as the marking scheme).
    k2_targets = [t for t in qp_targets if t.region_type == REGION_TYPE_ANSWER_BOX]
    if k2_targets:
        part_texts = _extract_kertas2_scheme_part_texts(profile.answer_scheme_path)
        for target in sorted(k2_targets, key=lambda t: t.label):
            part_no = _kertas2_part_number_for_label(target.label)
            if part_no is None:
                # No Kertas 2 Part in the label. Option 3: try to recover a
                # question number from the nearest detected number box and fill
                # from the scheme if that number has an answer - this is what
                # makes an auto-detected short-answer box fillable. Only fills a
                # real OCR'd match; otherwise the box stays UNLABELLED (needs a
                # proper label or a manual answer), never wrongly blamed on the
                # scheme.
                recovered_no = _recover(target)
                recovered_answer = parsed_answers.get(recovered_no) if recovered_no else None
                if recovered_answer is not None:
                    existing = existing_entries.get(target.label)
                    qname = f"Question {recovered_no}"
                    if existing is None:
                        extracted.append(qname)
                    elif _normalize_answer_text(existing.correct_answer) != _normalize_answer_text(recovered_answer):
                        overwritten.append(qname)
                    else:
                        already_set.append(qname)
                    recovered.append(qname)
                    save_answer_key_entry(
                        conn, teacher_id, profile_id, target.label, target.kind, recovered_no,
                        recovered_answer, existing.max_mark if existing else 1.0,
                        existing.comment if existing else None)
                    continue
                unlabelled.append(target.label)
                continue
            part_name = f"Part {part_no}"
            scheme_text = part_texts.get(part_no)
            if not scheme_text:
                missing.append(part_name)
                continue
            existing = existing_entries.get(target.label)
            if existing is None:
                extracted.append(part_name)
            elif _normalize_answer_text(existing.correct_answer) != _normalize_answer_text(scheme_text):
                overwritten.append(part_name)
            else:
                already_set.append(part_name)
            save_answer_key_entry(
                conn, teacher_id, profile_id, target.label, target.kind, None, scheme_text,
                existing.max_mark if existing else 20.0, existing.comment if existing else None,
            )

    if _qp_doc_holder and _qp_doc_holder[0] is not None:
        _qp_doc_holder[0].close()
    if progress_callback:
        progress_callback("Answer key updated.", total_steps, total_steps)
    return {"extracted": extracted, "already_set": already_set, "overwritten": overwritten,
            "missing": missing, "unlabelled": unlabelled, "recovered": recovered}


def _kertas2_part_number_for_label(label: str) -> Optional[int]:
    """Which Kertas 2 writing Part an answer_box label belongs to - same label
    metadata convention as subject_profile_review_service.kertas2_part_label."""
    lowered = label.lower()
    if "_q1_" in lowered:
        return 1
    if "_q2_" in lowered:
        return 2
    if "part3" in lowered or "_q3_" in lowered:
        return 3
    return None


def _recover_question_number_from_number_box(target, number_box_regions, qp_document, engine) -> Optional[str]:
    """Recover a target's printed question number by OCR'ing the nearest detected
    question_number_box on the same page. Used for regions whose LABEL carries no
    number - typically Core AI 2 auto-detected 'ai_...' regions accepted straight
    from Detect Answer Regions. The number box directly above a wide answer box,
    or just to the left of a narrow objective region, is chosen. Returns the first
    number OCR actually reads, or None; it never guesses a number that was not
    read, so a recovered number only ever fills an answer when it truly matches
    the scheme."""
    region = getattr(target, "region", None)
    if region is None:
        return None
    page = region.page_number
    candidates = [nb for nb in number_box_regions if nb.page_number == page]
    if not candidates:
        return None
    tx, ty, tw, th = region.x, region.y, region.width, region.height

    def _score(nb):
        nb_bottom, nb_right = nb.y + nb.height, nb.x + nb.width
        horiz_overlap = not (nb_right < tx or nb.x > tx + tw)
        vert_overlap = not (nb_bottom < ty or nb.y > ty + th)
        if nb_bottom <= ty + 0.02 and horiz_overlap:   # directly above the region
            return (0, ty - nb_bottom)
        if nb_right <= tx + 0.02 and vert_overlap:      # to the left, same row
            return (1, tx - nb_right)
        dx = (nb.x + nb.width / 2) - (tx + tw / 2)
        dy = (nb.y + nb.height / 2) - (ty + th / 2)
        return (2, (dx * dx + dy * dy) ** 0.5)          # fallback: nearest centre

    best = min(candidates, key=_score)
    crop = render_region_crop_from_pdf(qp_document, best)
    if crop is None:
        return None
    try:
        text = ocr_tall_crop_in_chunks(crop, engine)
    except Exception:
        return None
    match = re.search(r"\d{1,3}", text or "")
    return match.group(0) if match else None


def _extract_kertas2_scheme_part_texts(answer_scheme_path: str) -> Dict[int, str]:
    """Kertas 2 marking guidance per writing Part, from the answer scheme's
    embedded text layer. Scheme sections are keyed by 'Part N' / 'Question N'
    headings. Returns {} for a scheme with no usable text layer (e.g. a pure
    scan) - writing guidance is never OCR-guessed; those Parts stay 'missing'
    for the teacher to fill in manually."""
    document = pymupdf.open(answer_scheme_path)
    try:
        text = " ".join(document[i].get_text() for i in range(document.page_count))
    finally:
        document.close()
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 40:
        return {}
    # These scheme books cover BOTH papers, and Paper 1 also numbers its
    # sections "Part 1..5" - so when a Kertas 2 heading exists, only the text
    # from there up to the next Paper 1 / next model test is searched.
    k2_heading = re.search(r"1119/2|Paper\s*2\b|Kertas\s*2\b", text, re.IGNORECASE)
    if k2_heading:
        focus = text[k2_heading.end():]
        next_paper = re.search(r"1119/1|Paper\s*1\b|Kertas\s*Model", focus, re.IGNORECASE)
        if next_paper:
            focus = focus[:next_paper.start()]
    else:
        focus = text
    # Slice between consecutive "Part N"/"Question N" headings by position -
    # a full sample answer easily exceeds any bounded regex window.
    markers = []
    for number in (1, 2, 3, 4, 5):
        heading = re.search(rf"(?:Part|Question)\s*{number}\b", focus, re.IGNORECASE)
        if heading:
            markers.append((number, heading.start(), heading.end()))
    markers.sort(key=lambda entry: entry[1])
    parts: Dict[int, str] = {}
    for index, (number, _start, end) in enumerate(markers):
        if number not in (1, 2, 3):
            continue
        stop = markers[index + 1][1] if index + 1 < len(markers) else len(focus)
        section = focus[end:stop].strip()
        if len(section) >= 80:
            parts[number] = section[:1500]
    return parts


# --- Student PDF sequential processing (Stage 11V step 12-13) ---------------


@dataclass
class StudentPdfResult:
    file_path: str
    display_name: str
    answer_file_id: Optional[int]
    session_id: Optional[int]
    succeeded: bool
    error: Optional[str] = None


def mark_student_answer_pdfs_for_profile(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, student_pdf_paths: List[str],
    progress_callback: ProgressCallback = None, engine: Optional[OCREngine] = None,
) -> List[StudentPdfResult]:
    """Process each of student_pdf_paths SEQUENTIALLY, one full PDF at a
    time (validate -> crop+OCR answer regions -> extract) before starting
    the next, exactly matching the Stage 11V spec's PDF-by-PDF requirement.
    Each student PDF gets its own small main_marking_session (reusing
    Stage 11L-11N's session/answer-file machinery unchanged) so pages from
    different students are never mixed and one PDF's failure cannot corrupt
    another's session/answer-file rows or result state - the failed PDF's
    result is recorded with succeeded=False and the loop continues with the
    rest.

    Stage 11Y-Fix: full-page rendering (main_marking_service.run_
    preprocessing_for_session) is no longer run here at all -
    run_subject_profile_extraction's crop-OCR fast path renders each OCR-
    needed region's crop DIRECTLY from the student's original PDF (see
    region_crop_ocr_service.render_region_crop_from_pdf), so a page holding
    only skipped region types (question_area, question_number_box, ignore_
    region, student_info_area, extra_page_label, bubble_area) is never
    rendered at all. Full-page rendering is only ever done later, lazily,
    the first time a teacher opens the Marking Editor for a given student
    (see ensure_full_page_render_for_answer_file) - its time is deliberately
    NOT included in this batch's timing log, since it belongs to preview,
    not extraction. One LazyOCREngine is created (at most once, only if
    some crop actually needs real OCR - not fully cache-hit) and shared
    across every student PDF in this batch, so the OCR engine is never
    reinitialized per student/page/crop. A JSON timing/performance log
    summarizing the whole batch is written under data/processing_logs/
    student_marking/ - see
    app.utils.file_storage.get_student_marking_processing_log_folder.

    progress_callback(message, current, total) reports progress across the
    whole batch (2 steps per PDF: crop/OCR extraction, then prepare result)
    - the crop/OCR step's message is updated in place (without advancing
    the step counter) as each region is rendered/OCR'd/cache-reused, via
    region_crop_ocr_service.run_region_crop_ocr's on_render/on_progress
    callbacks. The Subject Profile's own status is set to 'processing' for
    the duration (blocking deletion - see delete_subject_profile) and back
    to 'ready' (success or failure) in a finally block.

    Raises ValueError up front if the profile doesn't exist/isn't owned,
    or hasn't finished question paper + answer scheme processing yet.
    """
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if profile.status != STATUS_READY:
        raise ValueError("Process the question paper and answer scheme before marking student answers.")

    update_subject_profile_status(conn, profile_id, STATUS_PROCESSING)
    run_started_at = time.perf_counter()
    # Marking Fix: pass an already-constructed engine (built by the caller
    # on the main/GUI thread - see teacher_dashboard.py's
    # handle_upload_student_answer_pdfs) when this runs on a background
    # QThread. Constructing PaddleOCR for the first time INSIDE that
    # worker thread was observed to hang indefinitely (works fine, and
    # fast, when done on the main thread or in a plain script) - a known
    # class of issue for ML frameworks with thread-affinity assumptions in
    # native init code. engine=None (e.g. existing tests) keeps the old
    # lazy-resolve-on-first-use behavior.
    shared_lazy_engine = LazyOCREngine(engine=engine, resolver=get_default_engine)

    qp_regions = get_regions_for_profile(conn, profile_id, SOURCE_QUESTION_PAPER)
    pages_with_ocr_regions = {r.page_number for r in qp_regions if r.region_type in OCR_NEEDED_REGION_TYPES}

    stats = {
        "total_pdf_pages": 0,
        "pages_with_ocr_regions": len(pages_with_ocr_regions),
        "pages_rendered_for_crop_ocr": 0,
        "full_pages_rendered": 0,
        "crop_regions_rendered": 0,
        "full_page_ocr_calls_avoided": 0,
        "crops_ocred": 0,
        "cached_crops_reused": 0,
        "total_crop_render_time_ms": 0.0,
        "total_full_page_render_time_ms": 0.0,
        "total_ocr_time_ms": 0.0,
        "per_student": [],
    }
    try:
        # 2 steps per PDF (crop/OCR extraction, prepare result) - unlike the
        # old full-page-render flow, there is no more per-page render step:
        # crop-render/OCR ticks update the CURRENT step's message only (a
        # Subject Profile's OCR-needed region count varies per profile, not
        # per page, so it isn't part of this step budget).
        total_steps = 2 * len(student_pdf_paths)
        step = 0

        def _tick(message: str) -> None:
            nonlocal step
            step += 1
            _report(progress_callback, message, step, total_steps)

        results = []
        for index, pdf_path in enumerate(student_pdf_paths, start=1):
            display_name = Path(pdf_path).name
            student_stats = {
                "display_name": display_name, "pages": 0, "pages_rendered_for_crop_ocr": 0,
                "crops_ocred": 0, "cached_reused": 0, "skipped": 0,
            }
            _report(progress_callback, f"Processing {display_name} ({index} of {len(student_pdf_paths)})", step, total_steps)
            try:
                # Create the session/answer-file row FIRST (even for a file
                # that turns out to be unreadable) so a failed student still
                # shows up in list_student_results_for_profile - the teacher
                # can see it failed instead of it silently disappearing.
                session = create_session_record(
                    conn, teacher_id, f"{profile.profile_name} - {display_name}", PAPER_TYPE_KERTAS_1,
                    profile.question_paper_path, profile.answer_scheme_path,
                )
                conn.execute(
                    "UPDATE main_marking_sessions SET subject_profile_id = ? WHERE session_id = ?",
                    (profile_id, session.session_id),
                )
                conn.commit()

                answer_file = add_answer_file_record(conn, session.session_id, "", display_name, None, None, None)
                from app.utils.file_storage import store_marking_session_file
                from app.models.main_marking_model import update_answer_file_path, update_answer_file_page_count
                stored_path = store_marking_session_file(session.session_id, pdf_path, f"answer_{answer_file.answer_file_id}")
                update_answer_file_path(conn, answer_file.answer_file_id, stored_path)

                page_count = get_pdf_page_count(stored_path)
                if not page_count:
                    raise ValueError(f"Could not read any pages from {display_name} - the file may not be a valid PDF.")
                student_stats["pages"] = page_count
                stats["total_pdf_pages"] += page_count
                # Every page of the old flow would have gotten its own
                # full-page OCR call (main_marking_service.run_ocr_for_
                # session) - the crop-OCR fast path avoids all of them.
                stats["full_page_ocr_calls_avoided"] += page_count
                update_answer_file_page_count(conn, answer_file.answer_file_id, page_count)

                _tick(f"Cropping answer regions for {display_name}")

                rendered_pages_this_student: set = set()

                def _on_render(page_number: int, name=display_name) -> None:
                    _report(progress_callback, f"Rendering crop for {name} (page {page_number})", step, total_steps)

                def _on_crop_result(
                    result: RegionCropOcrResult, name=display_name, s=student_stats, pages=rendered_pages_this_student,
                ) -> None:
                    if result.status == STATUS_OCRED:
                        s["crops_ocred"] += 1
                        stats["crops_ocred"] += 1
                        stats["crop_regions_rendered"] += 1
                        stats["total_crop_render_time_ms"] += result.render_time_ms
                        stats["total_ocr_time_ms"] += result.ocr_time_ms
                        pages.add(result.page_number)
                        _report(progress_callback, f"OCRing answer crop for {name} (page {result.page_number})", step, total_steps)
                    elif result.status == STATUS_CACHED:
                        s["cached_reused"] += 1
                        stats["cached_crops_reused"] += 1
                        _report(progress_callback, f"Reusing cached OCR for {name} (page {result.page_number})", step, total_steps)
                    else:
                        s["skipped"] += 1

                run_subject_profile_extraction(
                    conn, teacher_id, profile_id, answer_file.answer_file_id,
                    lazy_engine=shared_lazy_engine, progress_callback=_on_crop_result, render_callback=_on_render,
                )

                student_stats["pages_rendered_for_crop_ocr"] = len(rendered_pages_this_student)
                stats["pages_rendered_for_crop_ocr"] += len(rendered_pages_this_student)

                _tick(f"Preparing result for {display_name}")
                # Marking and overlay creation are deliberately NOT run here -
                # the marking editor's Marking/Comment section must stay empty
                # until the teacher explicitly clicks "Mark Answers" there (see
                # run_subject_profile_marking/create_default_overlays_for_
                # answer_file, called from the UI's handle_mark_answers_clicked
                # only). Automatic upload-time processing stops at extraction.

                stats["per_student"].append(student_stats)
                results.append(StudentPdfResult(
                    file_path=pdf_path, display_name=display_name, answer_file_id=answer_file.answer_file_id,
                    session_id=session.session_id, succeeded=True,
                ))
            except Exception as exc:
                # Fast-forward this PDF's step budget so a mid-PDF failure
                # never leaves the overall percentage stuck below 100% at
                # the end of the batch.
                target_step = 2 * index
                if step < target_step:
                    step = target_step
                    _report(progress_callback, f"Failed to process {display_name}", step, total_steps)
                stats["per_student"].append(student_stats)
                results.append(StudentPdfResult(
                    file_path=pdf_path, display_name=display_name, answer_file_id=None, session_id=None,
                    succeeded=False, error=str(exc),
                ))
        _write_student_marking_processing_log(teacher_id, profile_id, student_pdf_paths, stats, run_started_at)
        return results
    finally:
        update_subject_profile_status(conn, profile_id, STATUS_READY)


def _write_student_marking_processing_log(
    teacher_id: int, profile_id: int, student_pdf_paths: List[str], stats: dict, run_started_at: float,
) -> None:
    """Write one JSON timing/performance log summarizing a whole
    mark_student_answer_pdfs_for_profile batch run (Stage 11Y-Fix) under
    data/processing_logs/student_marking/. Never raises - a logging failure
    must never break student marking itself. full_pages_rendered and
    total_full_page_render_time_ms are always 0 here - extraction never
    renders full pages; any later, deferred full-page render (Marking
    Editor preview - see ensure_full_page_render_for_answer_file) is a
    separate, unlogged concern by design, so its cost is never mixed into
    this extraction timing."""
    try:
        total_processing_time_ms = (time.perf_counter() - run_started_at) * 1000
        summary = {
            "teacher_id": teacher_id,
            "profile_id": profile_id,
            "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "student_count": len(student_pdf_paths),
            "total_pdf_pages": stats["total_pdf_pages"],
            "pages_with_ocr_regions": stats["pages_with_ocr_regions"],
            "pages_rendered_for_crop_ocr": stats["pages_rendered_for_crop_ocr"],
            "full_pages_rendered": stats["full_pages_rendered"],
            "crop_regions_rendered": stats["crop_regions_rendered"],
            "full_page_ocr_calls_avoided": stats["full_page_ocr_calls_avoided"],
            "crops_ocred": stats["crops_ocred"],
            "cached_crops_reused": stats["cached_crops_reused"],
            "total_crop_render_time_ms": round(stats["total_crop_render_time_ms"], 2),
            "total_full_page_render_time_ms": round(stats["total_full_page_render_time_ms"], 2),
            "total_ocr_time_ms": round(stats["total_ocr_time_ms"], 2),
            "total_processing_time_ms": round(total_processing_time_ms, 2),
            "per_student": stats["per_student"],
        }
        log_folder = get_student_marking_processing_log_folder(teacher_id, profile_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        log_path = log_folder / f"run_{timestamp}.json"
        log_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except OSError:
        pass


def list_student_results_for_profile(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> List[dict]:
    """Return one row per student answer_file linked (via its session's
    subject_profile_id) to profile_id: display name, score summary, status."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    session_ids = [
        row[0] for row in conn.execute(
            "SELECT session_id FROM main_marking_sessions WHERE subject_profile_id = ? AND teacher_id = ?",
            (profile_id, teacher_id),
        ).fetchall()
    ]
    rows = []
    for session_id in session_ids:
        for answer_file in get_answer_files_for_session_record(conn, session_id):
            marked = get_marked_answers_for_answer_file(conn, answer_file.answer_file_id)
            # Marking Fix Follow-up: used to sum EVERY marked answer's
            # max_score regardless of status/region_type (e.g. 25.0/103.0
            # instead of the correct 25.0/40.0, since helper/continuation
            # regions, Missing Answer Key targets, and un-teacher-scored
            # Kertas 2 essays all inflated the denominator) - now shares the
            # exact same split computation the marked PDF's headline
            # overlay uses (see compute_score_summary).
            summary = compute_score_summary(marked)
            rows.append({
                "answer_file_id": answer_file.answer_file_id,
                "session_id": session_id,
                "display_name": get_answer_file_display_name(answer_file),
                "processing_status": answer_file.processing_status,
                "kertas1_score": summary.kertas1_score,
                "kertas1_max": summary.kertas1_max,
                "kertas1_display": summary.kertas1_display,
                "kertas2_display": summary.kertas2_display,
                "final_display": summary.final_display,
                "marked_count": len(marked),
            })
    return rows


def delete_student_marking(conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int) -> None:
    """Hard delete one student's marking from this Subject Profile's Mark
    Student Answers list (Data Management Follow-up feature 2) - unlike
    main_marking_service.delete_main_marking_final_result, this works
    regardless of processing_status (uploaded, preprocessed, marked, needs
    review), not just a finalized Main Marking Results-page entry.

    Deletes the underlying main_marking_answer_files row - with PRAGMA
    foreign_keys=ON (see app.database.db.get_connection), ON DELETE CASCADE
    removes every row that references it in the same atomic DELETE
    statement: main_marking_preprocessed_pages, main_marking_ocr_results,
    main_marking_extracted_answers, main_marking_marked_answers,
    main_marking_final_results (+ its own main_marking_final_result_items),
    subject_profile_extracted_answers, subject_profile_marked_answers, and
    subject_profile_overlays.

    Each Subject Profile student upload gets its own solo main_marking_
    session (see mark_student_answer_pdfs_for_profile) holding exactly that
    one answer file - so once this is the session's only answer file, the
    now-empty session row is deleted too, in the SAME transaction, never
    touching a session that still has other answer files. Never touches
    the Subject Profile itself, its question paper/answer scheme, its
    regions/answer key, the student account, or any other student's
    marking.

    Raises ValueError (leaving the database completely untouched) if the
    profile isn't owned by teacher_id, or the answer file doesn't exist or
    isn't linked to this profile. On-disk cleanup (the uploaded answer PDF,
    its answer-crop folder, its exported result folder if one exists, and -
    only if the session itself was deleted - that session's whole storage
    folder) is attempted only after the DB delete commits, and is
    best-effort: a disk-cleanup failure is swallowed rather than reported
    as an overall delete failure, since the authoritative database state is
    already correctly deleted by then."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Student marking not found.")
    session_row = conn.execute(
        "SELECT subject_profile_id FROM main_marking_sessions WHERE session_id = ?",
        (answer_file.session_id,),
    ).fetchone()
    if session_row is None or session_row[0] != profile_id:
        raise ValueError("Student marking not found for this Subject Profile.")

    session_id = answer_file.session_id
    sibling_count = conn.execute(
        "SELECT COUNT(*) FROM main_marking_answer_files WHERE session_id = ? AND answer_file_id != ?",
        (session_id, answer_file_id),
    ).fetchone()[0]
    delete_session_too = sibling_count == 0

    try:
        conn.execute("DELETE FROM main_marking_answer_files WHERE answer_file_id = ?", (answer_file_id,))
        if delete_session_too:
            conn.execute("DELETE FROM main_marking_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        if answer_file.file_path and Path(answer_file.file_path).is_file():
            Path(answer_file.file_path).unlink()
    except OSError:
        pass

    crop_folder = get_subject_profile_answer_crop_folder(profile_id, answer_file_id)
    if crop_folder.exists():
        shutil.rmtree(crop_folder, ignore_errors=True)

    safe_name = "".join(c if c.isalnum() else "_" for c in Path(answer_file.original_filename or "student").stem)
    result_folder = get_subject_profile_results_folder(profile_id) / f"{safe_name}_result"
    if result_folder.exists():
        shutil.rmtree(result_folder, ignore_errors=True)

    if delete_session_too:
        session_folder = file_storage.MAIN_MARKING_SESSIONS_DIR / f"session_{session_id}"
        if session_folder.exists():
            shutil.rmtree(session_folder, ignore_errors=True)


# --- Extraction (Stage 11V step 13, subject-profile-region-based) -----------


# Stage 12G-1A Part 3 integrity: the non-gradeable "which Part 3 question did
# you answer?" selector field. It is CONTEXTUAL metadata (its detected number
# labels the Part 3 answer and pairs the right prompt/scheme for dataset
# export) - never itself a marking row, overlay marker or answer-key target.
CONTEXT_QUESTION_NUMBER_LABEL_MARKER = "question_number_field"
# Valid Part 3 question choices for the standard SPM Kertas 2 paper.
PART3_VALID_QUESTION_NUMBERS = ("3", "4", "5")


def _is_context_question_number_label(label: Optional[str]) -> bool:
    return CONTEXT_QUESTION_NUMBER_LABEL_MARKER in (label or "").lower()


def _is_part3_answer_box(region_type: Optional[str], label: Optional[str]) -> bool:
    """True for the Kertas 2 Part 3 writing answer box (Part 1/2 boxes carry
    an explicit _q1_/_q2_; Part 3's box is the part3-labelled one)."""
    if region_type != REGION_TYPE_ANSWER_BOX:
        return False
    lbl = (label or "").lower()
    return "part3" in lbl or "_q3_" in lbl


def _digits_only(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits or None


def run_subject_profile_extraction(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int,
    engine: Optional[OCREngine] = None, lazy_engine: Optional[LazyOCREngine] = None,
    progress_callback: Optional[Callable[[RegionCropOcrResult], None]] = None,
    render_callback: Optional[Callable[[int], None]] = None,
) -> None:
    """Extract each Stage 11V question-paper-source region/group target's
    text, writing subject_profile_extracted_answers rows. Reruns are safe:
    previous rows for this answer file are deleted first. Never raises for
    an individual target failure - each target gets its own needs_review/
    failed status.

    Stage 11Y-Fix fast path: each region's crop is rendered DIRECTLY from
    the student's original PDF (answer_file.file_path) via app.services.
    region_crop_ocr_service.render_region_crop_from_pdf and OCR'd - no
    full-page rendering or full-page OCR/block-matching is ever needed for
    extraction (see run_region_crop_ocr's own docstring for why this is
    dramatically cheaper than Stage 11Y's original "render every page, then
    crop" approach). Pass lazy_engine (preferred over engine) when
    processing many answer files in one batch (mark_student_answer_pdfs_
    for_profile) so ONE already-created OCR engine is shared/reused across
    all of them; left as None here, a fresh LazyOCREngine is created (its
    resolver is this module's own get_default_engine, so existing tests'
    monkeypatching keeps working) and only actually constructs an engine if
    some region needs real OCR (not fully served by cache). progress_
    callback, if given, is called with each RegionCropOcrResult as it's
    produced; render_callback(page_number), if given, is called right after
    a page's crop is rendered but before OCR starts - both used by the UI
    progress dialog to show "Rendering crop"/"OCRing answer crop"/"Reusing
    cached OCR" as they happen. Safe (never crashes) whether the student
    PDF is missing/unreadable, has fewer pages than the profile references,
    or the profile has no regions at all - see run_region_crop_ocr."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")

    delete_extracted_answers_for_answer_file(conn, answer_file_id)

    targets = list_subject_profile_extraction_targets(conn, profile_id, SOURCE_QUESTION_PAPER)

    region_id_to_group_id: dict = {}
    for group in get_region_groups_for_profile(conn, profile_id):
        for member in get_members_for_group(conn, group.group_id):
            region_id_to_group_id[member.region_id] = group.group_id
    region_id_to_question_no = {
        entry.target_label: entry.question_no
        for entry in get_answer_key_entries_for_profile(conn, profile_id) if entry.question_no
    }

    if lazy_engine is None:
        lazy_engine = LazyOCREngine(engine=engine, resolver=get_default_engine)
    cache = load_crop_ocr_cache(teacher_id, profile_id)
    student_pdf_hash = compute_file_hash(answer_file.file_path)
    crop_save_dir = get_subject_profile_answer_crop_folder(profile_id, answer_file_id)
    # Marking Output Fix: the UNFILTERED region list (including helper/
    # legend/selector regions that _filter_gradeable_regions excludes from
    # targets) - an answer_box's extended look-above zone (see render_
    # answer_box_title_crop) needs exactly these "other" regions to mask
    # out, since a neighbouring prompt/question-number field is what it
    # would otherwise risk picking up.
    all_qp_regions = get_regions_for_profile(conn, profile_id, SOURCE_QUESTION_PAPER)

    def _extract(region: SubjectProfileRegion) -> tuple:
        results = run_region_crop_ocr(
            [region], answer_file.file_path, profile_id, lazy_engine, cache,
            answer_file_id=answer_file_id, student_pdf_hash=student_pdf_hash,
            region_id_to_group_id=region_id_to_group_id, region_id_to_question_no=region_id_to_question_no,
            page_regions=all_qp_regions,
            crop_save_dir=crop_save_dir, on_progress=progress_callback, on_render=render_callback,
        )
        result = results[0]
        if result.status == STATUS_SKIPPED:
            return None, None, EXTRACTED_ANSWER_STATUS_NO_TEXT, result.skip_reason
        if result.needs_review:
            # Marking Fix: an MCQ bubble_area (or any other region type)
            # that WAS actively analyzed but came back uncertain (no clear
            # selection mark, multiple competing marks, or the mark's
            # letter couldn't be read) - flagged for teacher review
            # instead of being silently treated as "no answer" -> wrong.
            return (
                result.extracted_text, result.confidence, EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW,
                result.skip_reason or "Detection uncertain - flagged for teacher review.",
            )
        if result.extracted_text:
            return result.extracted_text, result.confidence, EXTRACTED_ANSWER_STATUS_EXTRACTED, None
        return None, result.confidence, EXTRACTED_ANSWER_STATUS_NO_TEXT, "No OCR text found inside this region."

    for target in targets:
        if target.kind == TARGET_KIND_GROUP:
            texts = []
            for member in target.members:
                text, _confidence, _status, _message = _extract(member.region)
                if text:
                    texts.append(text)
            combined = " | ".join(texts)
            add_extracted_answer_record(
                conn, answer_file_id, target.label, TARGET_KIND_GROUP, target.region_type,
                combined or None, None, EXTRACTED_ANSWER_STATUS_EXTRACTED if combined else EXTRACTED_ANSWER_STATUS_NO_TEXT,
                None,
            )
        else:
            text, confidence, status, message = _extract(target.region)
            add_extracted_answer_record(
                conn, answer_file_id, target.label, TARGET_KIND_REGION, target.region_type, text, confidence, status, message,
            )

    # Stage 12G-1A Part 3 integrity: OCR the non-gradeable Part 3 question-
    # number selector as CONTEXTUAL metadata. It is intentionally excluded
    # from `targets` (a legend/selector helper), so extract it separately
    # here; run_subject_profile_marking reads it to set the Part 3 answer
    # box's selected question number, but never turns it into a marking row.
    already_extracted = {t.label for t in targets}
    for region in all_qp_regions:
        if not _is_context_question_number_label(region.label) or region.label in already_extracted:
            continue
        text, confidence, status, message = _extract(region)
        add_extracted_answer_record(
            conn, answer_file_id, region.label, TARGET_KIND_REGION, region.region_type,
            text, confidence, status, message,
        )

    if student_pdf_hash:
        save_crop_ocr_cache(teacher_id, profile_id, cache)


def ensure_full_page_render_for_answer_file(conn: sqlite3.Connection, teacher_id: int, answer_file_id: int) -> float:
    """Lazily render every page of answer_file_id's original student PDF as
    full-page preview images - a no-op (returns 0.0 immediately) if pages
    are already rendered. Stage 11Y-Fix requirement: full-page rendering is
    only ever needed for the Marking Editor's page-by-page preview, so it
    is deferred until a teacher actually opens that editor for this student
    (see app/ui/teacher_dashboard.py's _load_marking_editor_page_paths) -
    never during upload/extraction. Returns the render time spent in ms
    (0.0 if nothing needed to be rendered), which callers should track
    separately from - and never add to - the extraction timing log, since
    this cost belongs to preview, not extraction. Never raises: a missing
    answer file/session is treated as "nothing to render"."""
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        return 0.0
    existing_pages = get_preprocessed_pages_for_answer_file_record(conn, answer_file_id)
    if any(page.status == PAGE_STATUS_PREPROCESSED for page in existing_pages):
        return 0.0
    session = get_session_by_id(conn, answer_file.session_id)
    if session is None:
        return 0.0
    start = time.perf_counter()
    run_preprocessing_for_session(conn, session.session_id, teacher_id)
    return (time.perf_counter() - start) * 1000


# --- Marking (Stage 11V step 13/14, exact-match rule-based foundation) -----


def _normalize_answer_text(text: Optional[str]) -> str:
    return (text or "").strip().lower()


_ANSWER_SCHEME_LINE_PATTERN = re.compile(r"^\s*(\d+)[.)]\s+(\S+)")


def parse_kertas1_answers_from_text(text: str) -> Dict[str, str]:
    """Marking Fix Follow-up 3: parse an answer scheme's own printed
    Kertas 1 answer list out of OCR'd text - confirmed against profile_14's
    real answer scheme (Penerbitan Pelangi SKOR A+ SPM 2024, KERTAS MODEL
    2), every answer line starts with "N.  ANSWER": Parts 1-3 follow with
    a dash and a free-text explanation ("1.  B - The indication in the
    sentence..."), Part 4 is a bare "27.  G", Part 5 is "37.  practicality"
    (a word, not a letter) - this only ever needs the FIRST token after
    the number, so one pattern covers all three shapes. A "Part N" header
    line, or any other surrounding prose, simply doesn't match and is
    ignored - never raises.

    Returns {question_no: answer}; a line that repeats an already-seen
    question number (e.g. the same page OCR'd twice, or an overlapping
    OCR chunk - see region_crop_ocr_service.ocr_tall_crop_in_chunks) just
    overwrites with its own answer - harmless when both agree, and the
    caller (extract_answer_key_from_answer_scheme) is responsible for any
    higher-level "don't let a shakier source override an established
    answer" policy across MULTIPLE regions, not within one text blob."""
    answers: Dict[str, str] = {}
    for line in text.splitlines():
        match = _ANSWER_SCHEME_LINE_PATTERN.match(line)
        if not match:
            continue
        question_no, token = match.group(1), match.group(2)
        token = token.rstrip(".,;:-–—").strip()
        if token:
            answers[question_no] = token
    return answers



# Marking Fix: Kertas 2 (Paper 2) writing answer_box targets - Question 1,
# Question 2, and Part 3 - are essay/free-response spaces marked by a
# human, never a single-value answer-key exact-match target. ALWAYS
# extract-only + Needs Teacher Review, regardless of whether an answer key
# entry happens to exist for that label - "Do not mark Paper 2 Question 1,
# Question 2, and Part 3 answer boxes as 1.0 targets", "Use max score 20".
KERTAS2_WRITING_MAX_SCORE = 20.0


def _extraction_method_for(region_type: Optional[str]) -> Optional[str]:
    """Stage 12G-1A: a human-readable extraction-method/engine label for the
    provenance shown in the teacher review dialog and stored for Core AI 1
    dataset export. None (shown as "Unavailable") for a region type with no
    extraction path."""
    if region_type == REGION_TYPE_BUBBLE_AREA:
        return "bubble_detection + PaddleOCR letter"
    if region_type in (REGION_TYPE_ANSWER_BOX, REGION_TYPE_ANSWER_REGION,
                       REGION_TYPE_LETTER_BOX, REGION_TYPE_UNDERLINE_ANSWER):
        return "PaddleOCR crop"
    return None


def run_subject_profile_marking(conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int) -> None:
    """Mark each extracted answer against the Subject Profile's answer-key
    entries with a simple exact-match rule (Stage 11V foundation - see
    docs/stage12_ai_plan.md for future Kertas 2 AI scoring). Reruns are
    safe: previous marked-answer rows for this answer file are deleted
    first.

    Marking Fix status outcomes (see subject_profile_model.py's MARKED_
    ANSWER_STATUS_* / EXTRACTED_ANSWER_STATUS_* constants):
    - answer_box (Kertas 2 writing): always NEEDS_REVIEW, fixed max score
      KERTAS2_WRITING_MAX_SCORE, never auto-scored against an answer key.
    - extraction came back NEEDS_REVIEW (e.g. an MCQ bubble_area with no
      clear/unambiguous selection mark) or FAILED: carried through as the
      same marked-answer status - never silently scored 0 as if wrong.
    - extraction found no text at all (NO_TEXT): NEEDS_REVIEW, "No student
      answer text found" - unchanged from before, but no longer the ONLY
      way a target ends up unscored (see below).
    - no matching answer key entry: MISSING_ANSWER_KEY (a new, distinct
      status) - never silently falls through to a "wrong" 0.0 score."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    delete_marked_answers_for_answer_file(conn, answer_file_id)

    entries_by_label = {e.target_label: e for e in get_answer_key_entries_for_profile(conn, profile_id)}
    extracted = get_extracted_answers_for_answer_file(conn, answer_file_id)

    # Stage 12G-1A Part 3 integrity: pull the student's selected Part 3
    # question number out of the contextual question_number_field extraction
    # (a helper region, never a marking row) so it can be attached to the
    # Part 3 answer box below.
    part3_selected_qno = None
    for item in extracted:
        if _is_context_question_number_label(item.target_label):
            part3_selected_qno = _digits_only(item.extracted_text) or part3_selected_qno

    for item in extracted:
        # The context question-number field is metadata only - it must never
        # become a marking row, receive a score, or get an overlay marker.
        if _is_context_question_number_label(item.target_label):
            continue
        entry = entries_by_label.get(item.target_label)
        correct_answer = entry.correct_answer if entry is not None else None
        # Stage 12G-1A: carry the raw-extraction provenance onto the marked
        # answer so the teacher review dialog / Core AI 1 export can show
        # exactly how the raw OCR was produced. Genuine values only - a None
        # confidence (extraction path didn't report one) stays None, shown
        # as "Unavailable"; never invented.
        provenance = dict(
            raw_ocr_text=item.extracted_text,
            extraction_confidence=item.confidence,
            extraction_method=_extraction_method_for(item.region_type),
            extraction_timestamp=item.created_at,
            # Only the Part 3 answer box carries a selected question number;
            # None for every other target.
            extracted_selected_question_number=(
                part3_selected_qno if _is_part3_answer_box(item.region_type, item.target_label) else None
            ),
        )

        if item.region_type == REGION_TYPE_ANSWER_BOX:
            # Marking Fix Follow-up: PENDING_TEACHER_SCORE (not the generic
            # NEEDS_REVIEW used for uncertain OCR) - this is a normal essay
            # awaiting a human mark, not an unclear detection, and must be
            # excluded from the Kertas 2/final score until a teacher enters
            # one via set_teacher_score_for_marked_answer.
            feedback = (
                "Pending Teacher Score - Kertas 2 writing answer extracted; awaiting teacher scoring (max 20)."
                if item.extracted_text else
                "Pending Teacher Score - no writing answer text detected yet; awaiting teacher scoring (max 20)."
            )
            add_marked_answer_record(
                conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
                item.extracted_text, correct_answer, None, KERTAS2_WRITING_MAX_SCORE, False,
                MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE, feedback, **provenance,
            )
            continue

        max_score = entry.max_mark if entry is not None else 1.0

        if item.status == EXTRACTED_ANSWER_STATUS_FAILED:
            add_marked_answer_record(
                conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
                item.extracted_text, correct_answer, 0.0, max_score, False,
                MARKED_ANSWER_STATUS_FAILED, item.message or "Detection Failed - could not analyze this target.",
                **provenance,
            )
            continue

        if item.status == EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW:
            add_marked_answer_record(
                conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
                item.extracted_text, correct_answer, 0.0, max_score, False,
                MARKED_ANSWER_STATUS_NEEDS_REVIEW,
                item.message or "Needs Teacher Review - detection uncertain for this target.",
                **provenance,
            )
            continue

        if item.status == EXTRACTED_ANSWER_STATUS_NO_TEXT:
            add_marked_answer_record(
                conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
                item.extracted_text, correct_answer, 0.0, max_score, False,
                MARKED_ANSWER_STATUS_NEEDS_REVIEW, "No student answer text found for this target.",
                **provenance,
            )
            continue

        if entry is None:
            add_marked_answer_record(
                conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
                item.extracted_text, None, 0.0, max_score, False,
                MARKED_ANSWER_STATUS_MISSING_ANSWER_KEY, "Missing Answer Key - no correct answer defined for this target.",
                **provenance,
            )
            continue

        is_correct = _normalize_answer_text(item.extracted_text) == _normalize_answer_text(correct_answer)
        score = max_score if is_correct else 0.0
        feedback = "Correct." if is_correct else "Wrong."

        add_marked_answer_record(
            conn, answer_file_id, item.target_label, item.target_kind, item.region_type,
            item.extracted_text, correct_answer, score, max_score, is_correct,
            MARKED_ANSWER_STATUS_MARKED, feedback, **provenance,
        )


@dataclass
class ScoreSummary:
    """Marking Fix Follow-up: the dashboard row (list_student_results_for_
    profile) and the marked PDF's headline overlay (create_default_overlays_
    for_answer_file) both used to sum EVERY marked answer's max_score
    regardless of status/region_type - inflating the denominator to include
    helper/continuation regions, Missing Answer Key targets, and Kertas 2
    essays that had never been scored (e.g. 25.0/103.0 instead of the
    correct 25.0/40.0). This is the single shared computation both call
    sites now use instead."""
    kertas1_score: float
    kertas1_max: float
    kertas2_score: float
    kertas2_max: float
    kertas2_total_items: int
    kertas2_scored_items: int
    kertas1_display: str
    kertas2_display: str
    final_display: str


def compute_score_summary(marked_answers: List[SubjectProfileMarkedAnswer]) -> ScoreSummary:
    """Split marked_answers into a Kertas 1 (objective) and Kertas 2
    (Paper 2 writing/answer_box) score, each computed so only genuinely
    gradable targets count toward the denominator:

    Kertas 1: a target counts toward kertas1_max only if it has a REAL
    answer key entry (correct_answer_text is not None - this naturally
    excludes helper/continuation/options-list regions and Missing Answer
    Key targets, whichever status label happens to be showing) and wasn't
    a hard Detection Failed. A Needs Review objective answer (uncertain
    OCR) still counts toward the denominator - it's a real, keyed question,
    just not yet confirmed - but only a confirmed MARKED+correct answer
    ever contributes to the numerator, so kertas1_max is a fixed count of
    real questions (40 for a standard Kertas 1 paper) regardless of how
    many are still unconfirmed.

    Kertas 2: an answer_box target counts toward kertas2_max/kertas2_score
    ONLY once a teacher has entered a manual score for it (status ==
    MARKED_ANSWER_STATUS_TEACHER_SCORED, via set_teacher_score_for_marked_
    answer) - a Pending Teacher Score essay contributes nothing until then,
    never a misleading 0/20."""
    kertas1_items = [m for m in marked_answers if m.region_type != REGION_TYPE_ANSWER_BOX]
    kertas2_items = [m for m in marked_answers if m.region_type == REGION_TYPE_ANSWER_BOX]

    kertas1_counted = [
        m for m in kertas1_items
        if m.correct_answer_text is not None and m.status != MARKED_ANSWER_STATUS_FAILED
    ]

    # Marking Fix Follow-up 3: multiple regions can share the same derived
    # question number (e.g. a "_cont" continuation/duplicate detection
    # region alongside its primary one - both legitimately get their own
    # answer key entry via extract_answer_key_from_answer_scheme, since
    # they represent the SAME real question) - confirmed against
    # profile_14's real qp_p7_q23_choices/qp_p7_q23_choices_cont pair,
    # which inflated the denominator to 41 before this grouping. Count
    # each REAL question once (by its derived number), not once per
    # region; prefer a confirmed correct result within the group for the
    # numerator - a correct detection on EITHER the primary or the backup
    # region is enough to award the mark.
    grouped_by_question: Dict[str, List[SubjectProfileMarkedAnswer]] = {}
    representative_items: List[SubjectProfileMarkedAnswer] = []
    for m in kertas1_counted:
        question_no = extract_question_number_from_label(m.target_label)
        if question_no is None:
            representative_items.append(m)
        else:
            grouped_by_question.setdefault(question_no, []).append(m)
    for group in grouped_by_question.values():
        best = next((g for g in group if g.status == MARKED_ANSWER_STATUS_MARKED and g.is_correct), group[0])
        representative_items.append(best)

    kertas1_max = sum(m.max_score for m in representative_items)
    kertas1_score = sum(m.score or 0.0 for m in representative_items if m.status == MARKED_ANSWER_STATUS_MARKED)

    kertas2_scored = [m for m in kertas2_items if m.status == MARKED_ANSWER_STATUS_TEACHER_SCORED]
    kertas2_score = sum(m.score or 0.0 for m in kertas2_scored)
    kertas2_max = sum(m.max_score for m in kertas2_scored)

    def _fmt(value: float) -> str:
        return f"{value:g}"

    kertas1_display = f"{_fmt(kertas1_score)}/{_fmt(kertas1_max)}"

    total_k2 = len(kertas2_items)
    scored_k2 = len(kertas2_scored)
    if total_k2 == 0:
        kertas2_display = "N/A"
        final_display = kertas1_display
    elif scored_k2 == 0:
        kertas2_display = "Needs Teacher Review"
        final_display = "Pending"
    elif scored_k2 < total_k2:
        kertas2_display = f"{_fmt(kertas2_score)}/{_fmt(kertas2_max)} (Partial - {scored_k2} of {total_k2} scored)"
        final_display = f"{_fmt(kertas1_score + kertas2_score)}/{_fmt(kertas1_max + kertas2_max)} (Partial)"
    else:
        kertas2_display = f"{_fmt(kertas2_score)}/{_fmt(kertas2_max)}"
        total_score = kertas1_score + kertas2_score
        total_max = kertas1_max + kertas2_max
        percentage = round(total_score / total_max * 100, 1) if total_max > 0 else 0.0
        final_display = f"{_fmt(total_score)}/{_fmt(total_max)} ({percentage}%)"

    return ScoreSummary(
        kertas1_score=kertas1_score, kertas1_max=kertas1_max,
        kertas2_score=kertas2_score, kertas2_max=kertas2_max,
        kertas2_total_items=total_k2, kertas2_scored_items=scored_k2,
        kertas1_display=kertas1_display, kertas2_display=kertas2_display, final_display=final_display,
    )


def set_teacher_score_for_marked_answer(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, marked_answer_id: int, score: float,
) -> SubjectProfileMarkedAnswer:
    """Record a teacher's manual mark (0..max_score, typically out of
    KERTAS2_WRITING_MAX_SCORE=20) for a Kertas 2 writing answer_box target -
    the ONLY way such a target ever contributes to the Kertas 2/final score
    (see compute_score_summary). Raises ValueError if the marked answer
    isn't an answer_box target, or the score is out of range."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    marked = get_marked_answer_by_id(conn, marked_answer_id)
    if marked is None:
        raise ValueError("Marked answer not found.")
    if marked.region_type != REGION_TYPE_ANSWER_BOX:
        raise ValueError("Only Kertas 2 writing answers can be given a manual teacher score.")
    if score < 0 or score > marked.max_score:
        raise ValueError(f"Score must be between 0 and {marked.max_score:g}.")
    feedback = f"Teacher Scored: {score:g}/{marked.max_score:g}."
    return update_marked_answer_score_record(conn, marked_answer_id, score, MARKED_ANSWER_STATUS_TEACHER_SCORED, feedback)


# --- Overlays (Stage 11V step 16-18) -----------------------------------------


_CONT_LABEL_SUFFIX = "_cont"


def _logical_overlay_key(target_label: str) -> str:
    """Collision-safe grouping key for one marked answer's overlay marker
    (K1/K2 collision fix). Returns the target label with only a genuine
    trailing "_cont" continuation suffix removed - so a primary region and
    its own continuation duplicate (qp_p7_q23_choices + qp_p7_q23_choices_
    cont) share a key and collapse to ONE marker, while every other target
    keeps its own full label as key. Because a full label already encodes
    the paper/page + question + target category, a Kertas 1 objective
    (qp_p2_q1_choices) and a Kertas 2 answer_box (qp_p13_q1_answer_box) that
    merely share question number "1" get DIFFERENT keys and stay separate -
    unlike grouping by the bare question number, which wrongly merged them
    and suppressed the K2 essay's own marker."""
    if target_label.endswith(_CONT_LABEL_SUFFIX):
        return target_label[: -len(_CONT_LABEL_SUFFIX)]
    return target_label


def _overlay_marker_for_marked_answer(marked) -> Tuple[str, Optional[str], float]:
    """Stage 12G-1A: return (kind, text_value, width) for one answer's status
    marker using its EFFECTIVE (teacher-reviewed) status when the teacher has
    set one, else the machine status. tick/cross carry no text; a "?" flag
    and a teacher-scored value reuse the 'percentage' kind's text rendering.
    teacher_status is None for every un-reviewed answer, so the machine
    branch below reproduces the exact pre-Stage-12G behaviour."""
    teacher_status = getattr(marked, "teacher_status", None)
    if teacher_status is not None:
        if teacher_status == TEACHER_STATUS_CORRECT:
            return OVERLAY_KIND_TICK, None, 0.04
        if teacher_status == TEACHER_STATUS_WRONG:
            return OVERLAY_KIND_CROSS, None, 0.04
        if teacher_status == TEACHER_STATUS_TEACHER_SCORED:
            score = marked.teacher_score if marked.teacher_score is not None else 0.0
            return OVERLAY_KIND_PERCENTAGE, f"{score:g}/{marked.max_score:g}", 0.08
        # needs_review / pending_teacher_score
        return OVERLAY_KIND_PERCENTAGE, "?", 0.05

    if marked.status == MARKED_ANSWER_STATUS_MARKED:
        return (OVERLAY_KIND_TICK if marked.is_correct else OVERLAY_KIND_CROSS), None, 0.04
    if marked.status == MARKED_ANSWER_STATUS_TEACHER_SCORED:
        return OVERLAY_KIND_PERCENTAGE, f"{(marked.score or 0.0):g}/{marked.max_score:g}", 0.08
    return OVERLAY_KIND_PERCENTAGE, "?", 0.05


def create_default_overlays_for_answer_file(conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int) -> List[SubjectProfileOverlay]:
    """Create a tick/cross overlay beside each marked answer's
    question_number_box region (falling back to the answer region itself
    if none exists), plus one percentage overlay near the top-right of
    page 1 - the Stage 11V overlay foundation. Safe to call again: clears
    any existing overlays for this answer_file first."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    delete_overlays_for_answer_file(conn, answer_file_id)

    marked_answers = get_marked_answers_for_answer_file(conn, answer_file_id)
    regions_by_label = {r.label: r for r in get_regions_for_profile(conn, profile_id, SOURCE_QUESTION_PAPER)}
    question_number_regions = [r for r in regions_by_label.values() if r.region_type in QUESTION_NUMBER_REGION_TYPES]

    # Marking Determinism Fix (requirement 6) + K1/K2 collision fix: exactly
    # ONE final status marker per LOGICAL TARGET - a target can never show
    # both a "?" and a tick/cross. Group by a COLLISION-SAFE key: the target
    # label with only a genuine trailing "_cont" suffix normalized away (see
    # _logical_overlay_key). Grouping by the bare question NUMBER was wrong -
    # it merged Kertas 1 Q1 (qp_p2_q1_choices) with Kertas 2 Q1 (qp_p13_q1_
    # answer_box), both of which derive question number "1", suppressing the
    # K2 essay's own "?" marker. Because the full label already encodes the
    # paper/page + question + target category, only a real continuation
    # duplicate (qp_p7_q23_choices + qp_p7_q23_choices_cont) collapses into
    # one group; a K1 objective and a K2 answer_box that merely share a
    # question number stay separate. Within a group the representative is a
    # genuinely graded (MARKED, then TEACHER_SCORED) row, then the primary
    # (non-"_cont") region, so the drawn marker always agrees with the score.
    grouped_marked: Dict[str, List[SubjectProfileMarkedAnswer]] = {}
    group_order: List[str] = []
    for marked in marked_answers:
        key = _logical_overlay_key(marked.target_label)
        if key not in grouped_marked:
            grouped_marked[key] = []
            group_order.append(key)
        grouped_marked[key].append(marked)

    overlays = []
    for key in group_order:
        group = grouped_marked[key]
        marked = (
            next((m for m in group if m.status == MARKED_ANSWER_STATUS_MARKED), None)
            or next((m for m in group if m.status == MARKED_ANSWER_STATUS_TEACHER_SCORED), None)
            or next((m for m in group if not m.target_label.endswith("_cont")), None)
            or group[0]
        )
        anchor = regions_by_label.get(marked.target_label)
        # Marking Fix: matching "a question_number_box on the same page" was
        # not enough on its own - a page routinely holds several questions
        # (e.g. profile_14's page 3 has Q5-Q8), so the OLD next(...) here
        # picked the SAME first question_number_box for every one of them,
        # stacking every tick/cross/flag for that page at one spot with the
        # last-drawn one visually hiding the rest - e.g. Q8's cross
        # appearing to sit on top of Q5's tick. Real region labels share a
        # "_q<N>_" token between an answer region and its own number box
        # (qp_p3_q5_choices <-> qp_p3_q5_number), so prefer the box whose
        # label carries the SAME question number.
        #
        # Marking Determinism Fix (requirement 6): when NO number box on the
        # page carries this question's own "_qN_" token (e.g. profile_16's
        # real Part 5 summary blanks qp_p11_q37..q40_answer_line, which have
        # no number box at all), the marker is anchored to the answer region
        # ITSELF - never to an arbitrary "first number box on the page",
        # which previously dumped every unmatched question's marker onto the
        # SAME spot (confirmed: Q37/Q38/Q39/Q40 all stacked on Q33's number
        # box). Each answer region has its own distinct position, so this
        # guarantees one marker per question with no two ever overlapping.
        page_number = anchor.page_number if anchor is not None else 1
        same_page_qn_regions = [r for r in question_number_regions if r.page_number == page_number]
        qn_region = None
        marked_question_no = extract_question_number_from_label(marked.target_label)
        if marked_question_no is not None:
            question_token = f"_q{marked_question_no}_"
            qn_region = next((r for r in same_page_qn_regions if question_token in r.label), None)
        placement = qn_region if qn_region is not None else anchor
        if placement is None:
            continue

        overlay_x = min(0.96, placement.x + placement.width + 0.01)
        overlay_y = placement.y
        # Marking Fix (requirement 6): only a genuinely graded answer gets a
        # hard tick/cross - anything else (Needs Review, Missing Answer Key,
        # Detection Failed, Pending Teacher Score) gets a "?" flag overlay
        # instead of a false red X. Reuses the existing 'percentage' overlay
        # kind's plain-text rendering rather than a new DB-level overlay kind.
        #
        # Stage 12G-1A: the symbol reflects the EFFECTIVE (teacher-reviewed)
        # status when the teacher has set one, else the machine status - so a
        # regenerated marked PDF after review shows the teacher's Correct/
        # Wrong/Needs Review decision. teacher_status is None for every
        # un-reviewed answer, so pre-review behaviour is unchanged.
        overlay_kind, overlay_text, overlay_width = _overlay_marker_for_marked_answer(marked)
        # Phase 2B: link the marker to its logical target so the editable
        # overlay workspace lists one row per target and regeneration can
        # preserve a teacher's per-target symbol/position/hidden edits.
        target_label = marked.target_label
        if overlay_kind in (OVERLAY_KIND_TICK, OVERLAY_KIND_CROSS):
            overlays.append(add_overlay_record(
                conn, answer_file_id, overlay_kind, page_number, overlay_x, overlay_y,
                target_label=target_label,
            ))
        else:
            overlays.append(add_overlay_record(
                conn, answer_file_id, OVERLAY_KIND_PERCENTAGE, page_number, overlay_x, overlay_y,
                width=overlay_width, height=0.04, text_value=overlay_text, target_label=target_label,
            ))

    # Marking Fix Follow-up: the headline now shows Kertas 1 / Kertas 2 /
    # Final on 3 separate lines via the shared compute_score_summary (the
    # same split used by the dashboard's student results table) - a page
    # full of Needs Review/Missing Answer Key/Pending Teacher Score targets
    # must never show a misleadingly low blended percentage (e.g. the old
    # 25.0/103.0), and Kertas 2 essays must never look like confirmed
    # 0/20s before a teacher actually scores them.
    summary = compute_score_summary(marked_answers)
    headline_text = f"K1: {summary.kertas1_display}\nK2: {summary.kertas2_display}\nFinal: {summary.final_display}"
    overlays.append(add_overlay_record(
        conn, answer_file_id, OVERLAY_KIND_PERCENTAGE, 1, 0.78, 0.02,
        width=0.20, height=0.09, text_value=headline_text,
    ))

    # Feedback notes: for each Kertas 2 writing answer that has final feedback
    # (the teacher's saved wording, else the AI/machine feedback), draw a
    # draggable/resizable red note at the bottom-right of that answer's page.
    # Its own "__feedback" target label keeps its position independent of the
    # score marker and preserved across regeneration (see the review service's
    # edit-preserving regeneration).
    feedback_slots: Dict[int, int] = {}
    for marked in marked_answers:
        if marked.region_type != REGION_TYPE_ANSWER_BOX:
            continue
        feedback_text = ((marked.teacher_feedback or marked.feedback) or "").strip()
        if not feedback_text:
            continue
        anchor = regions_by_label.get(marked.target_label)
        page_number = anchor.page_number if anchor is not None else 1
        slot = feedback_slots.get(page_number, 0)
        feedback_slots[page_number] = slot + 1
        # Bottom-right by default; stack upward if several answers share a page.
        feedback_y = max(0.05, 0.80 - slot * 0.20)
        overlays.append(add_overlay_record(
            conn, answer_file_id, OVERLAY_KIND_FEEDBACK, page_number, 0.50, feedback_y,
            width=0.47, height=0.16, text_value=feedback_text,
            target_label=marked.target_label + "__feedback",
        ))
    return overlays


def run_mark_answers_for_answer_file(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int,
    progress_callback: ProgressCallback = None, engine: Optional[OCREngine] = None,
) -> None:
    """Data Management Follow-up (feature 3): the exact same three calls
    the Marking Editor's "Mark Answers" button already made in sequence
    (run_subject_profile_extraction, run_subject_profile_marking,
    create_default_overlays_for_answer_file), now wrapped with progress
    reporting (message, current_step, total_steps) suitable for a
    CircularProgressWidget - see app.ui.subject_profile_worker.
    MarkAnswerFileSubprocessWorker, which runs this in a separate OS
    process (mirroring StudentPdfProcessingSubprocessWorker) so the UI
    thread is never blocked while real OCR runs.

    4 top-level steps are reported ("Preparing pages...", "Running OCR...
    Detecting answers..." - updated per-region as extraction's own crop/
    OCR progress arrives, "Comparing with answer key...", "Generating
    marked PDF..."), plus a final "Saving results..." tick - matching the
    step names suggested by the feature spec, even though the underlying
    work doesn't literally break down into 6 separate phases (extraction
    covers both OCR and answer detection in one pass; there is no separate
    marked-PDF-generation step until a teacher downloads a result, so
    "Generating marked PDF" here really refers to the tick/cross/percentage
    overlay marks the download step later draws onto the PDF).

    Raises ValueError (via the underlying calls) if the profile isn't
    owned by teacher_id or the answer file doesn't exist - nothing is
    partially marked in that case, since get_owned_subject_profile is the
    very first check each underlying call makes."""
    total_steps = 4
    step = 0

    def _tick(message: str) -> None:
        nonlocal step
        step += 1
        _report(progress_callback, message, step, total_steps)

    _tick("Preparing pages...")

    def _on_render(page_number: int) -> None:
        _report(progress_callback, f"Running OCR... (page {page_number})", step, total_steps)

    def _on_crop_result(result: RegionCropOcrResult) -> None:
        if result.status == STATUS_OCRED:
            _report(progress_callback, f"Detecting answers... (page {result.page_number})", step, total_steps)
        elif result.status == STATUS_CACHED:
            _report(progress_callback, f"Detecting answers... (cached, page {result.page_number})", step, total_steps)

    run_subject_profile_extraction(
        conn, teacher_id, profile_id, answer_file_id, engine=engine,
        progress_callback=_on_crop_result, render_callback=_on_render,
    )
    _tick("Comparing with answer key...")
    run_subject_profile_marking(conn, teacher_id, profile_id, answer_file_id)
    _tick("Generating marked PDF...")
    create_default_overlays_for_answer_file(conn, teacher_id, profile_id, answer_file_id)
    _tick("Saving results...")


def list_overlays(conn: sqlite3.Connection, answer_file_id: int) -> List[SubjectProfileOverlay]:
    return get_overlays_for_answer_file(conn, answer_file_id)


def move_overlay(conn: sqlite3.Connection, overlay_id: int, x: float, y: float) -> SubjectProfileOverlay:
    overlay = get_overlay_by_id(conn, overlay_id)
    if overlay is None:
        raise ValueError("Overlay not found.")
    update_overlay_transform_record(conn, overlay_id, x, y, overlay.width, overlay.height, overlay.rotation_angle)
    return get_overlay_by_id(conn, overlay_id)


def resize_overlay(conn: sqlite3.Connection, overlay_id: int, width: float, height: float) -> SubjectProfileOverlay:
    overlay = get_overlay_by_id(conn, overlay_id)
    if overlay is None:
        raise ValueError("Overlay not found.")
    if width <= 0 or height <= 0:
        raise ValueError("Overlay width/height must be positive.")
    update_overlay_transform_record(conn, overlay_id, overlay.x, overlay.y, width, height, overlay.rotation_angle)
    return get_overlay_by_id(conn, overlay_id)


def rotate_overlay(conn: sqlite3.Connection, overlay_id: int, rotation_angle: float) -> SubjectProfileOverlay:
    overlay = get_overlay_by_id(conn, overlay_id)
    if overlay is None:
        raise ValueError("Overlay not found.")
    update_overlay_transform_record(conn, overlay_id, overlay.x, overlay.y, overlay.width, overlay.height, rotation_angle)
    return get_overlay_by_id(conn, overlay_id)


def delete_overlay(conn: sqlite3.Connection, overlay_id: int) -> None:
    overlay = get_overlay_by_id(conn, overlay_id)
    if overlay is None:
        raise ValueError("Overlay not found.")
    delete_overlay_record(conn, overlay_id)


# --- Export / download (Stage 11V step 19-20) --------------------------------


def effective_overlay_kind_text(overlay: SubjectProfileOverlay) -> Optional[Tuple[str, Optional[str]]]:
    """Phase 2B (consistency fix): resolve one overlay's DISPLAYED (kind,
    text_value), or None when it must not be drawn (hidden).

    A status marker's symbol is ALWAYS the generated `kind`/`text_value`,
    which is derived from the answer's effective teacher-reviewed status - so
    a visible marker can never contradict the final status. A legacy
    visual-only symbol override (teacher_symbol_override) is intentionally
    IGNORED here, falling the overlay back safely to Auto without touching the
    machine result. Hidden overlays are not drawn but their status is
    unchanged."""
    if overlay.is_hidden:
        return None
    return overlay.kind, overlay.text_value


def _draw_overlays_on_pdf(pdf_path: str, overlays: List[SubjectProfileOverlay], output_path: Path) -> None:
    """Draw each overlay's tick/cross/percentage mark onto pdf_path (read-
    only source) and save to output_path. Uses pymupdf's page.draw_line /
    page.insert_text - a from-scratch addition (no existing PDF-annotation
    code in this codebase), kept intentionally simple: ticks/crosses are
    drawn as two short red lines, percentage as red text.

    Phase 2B: a HIDDEN overlay is skipped entirely, and a teacher symbol
    override replaces the generated symbol (see effective_overlay_kind_text)."""
    document = pymupdf.open(pdf_path)
    try:
        for overlay in overlays:
            resolved = effective_overlay_kind_text(overlay)
            if resolved is None:
                continue  # hidden - not drawn
            draw_kind, draw_text = resolved
            page_index = overlay.page_number - 1
            if page_index < 0 or page_index >= document.page_count:
                continue
            page = document[page_index]
            rect = page.rect
            cx = overlay.x * rect.width
            cy = overlay.y * rect.height
            w = overlay.width * rect.width
            h = overlay.height * rect.height
            red = (1, 0, 0)

            if draw_kind == "tick":
                page.draw_line(pymupdf.Point(cx, cy + h * 0.5), pymupdf.Point(cx + w * 0.4, cy + h), color=red, width=2)
                page.draw_line(pymupdf.Point(cx + w * 0.4, cy + h), pymupdf.Point(cx + w, cy), color=red, width=2)
            elif draw_kind == "cross":
                page.draw_line(pymupdf.Point(cx, cy), pymupdf.Point(cx + w, cy + h), color=red, width=2)
                page.draw_line(pymupdf.Point(cx, cy + h), pymupdf.Point(cx + w, cy), color=red, width=2)
            elif draw_kind == "percentage":
                text_value = draw_text or ""
                if "\n" in text_value:
                    # Marking Fix Follow-up: the headline K1/K2/Final
                    # summary is 3 lines - a smaller fontsize keeps it
                    # legible/compact instead of overflowing past its box.
                    page.insert_text(pymupdf.Point(cx, cy + 10), text_value, color=red, fontsize=10)
                else:
                    page.insert_text(pymupdf.Point(cx, cy + h * 0.7), text_value, color=red, fontsize=16)
            elif draw_kind == "feedback":
                # Wrapped red feedback note over a faint white panel (so it
                # stays legible over the essay), inside the overlay's own box -
                # the box the teacher positioned/sized in the preview.
                box = pymupdf.Rect(cx, cy, cx + w, cy + h)
                page.draw_rect(box, color=red, fill=(1, 1, 1), fill_opacity=0.82, width=0.5)
                inner = box + (4, 3, -4, -3)
                text_value = draw_text or ""
                # A manual font size (points) is honoured as the starting/maximum
                # size; otherwise 9pt. Shrink-to-fit from there so text never
                # overflows the note's box, measured on a throwaway page.
                fontsize = overlay.font_size if overlay.font_size else 9
                scratch = pymupdf.open()
                try:
                    scratch_page = scratch.new_page(width=rect.width, height=rect.height)
                    while fontsize > 6 and scratch_page.insert_textbox(
                            inner, text_value, fontsize=fontsize, align=0) < 0:
                        fontsize -= 1
                finally:
                    scratch.close()
                page.insert_textbox(inner, text_value, color=red,
                                    fontsize=max(6, fontsize), align=0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output_path))
    finally:
        document.close()


# Marking Fix (requirement 9): human-readable status label per marked
# answer's status/is_correct combination, used by _comments_txt_content.
_MARKED_STATUS_DISPLAY_LABELS = {
    MARKED_ANSWER_STATUS_NEEDS_REVIEW: "Needs Review",
    MARKED_ANSWER_STATUS_MISSING_ANSWER_KEY: "Missing Answer Key",
    MARKED_ANSWER_STATUS_FAILED: "Detection Failed",
    # Marking Fix Follow-up (requirement 3): kept distinct from "Needs
    # Review" - this is a normal essay awaiting a human mark, not unclear
    # handwriting/detection.
    MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE: "Pending Teacher Score",
    MARKED_ANSWER_STATUS_TEACHER_SCORED: "Teacher Scored",
}


def _marked_status_display_label(marked: SubjectProfileMarkedAnswer) -> str:
    if marked.status == MARKED_ANSWER_STATUS_MARKED:
        return "Correct" if marked.is_correct else "Wrong"
    return _MARKED_STATUS_DISPLAY_LABELS.get(marked.status, marked.status)


def _comments_txt_content(marked_answers: List[SubjectProfileMarkedAnswer]) -> str:
    """Marking Fix (requirement 9): reports each target's detected answer,
    expected (answer key) answer, status, and mark clearly - not just a
    bare score, so a teacher can immediately see WHY a target scored what
    it did (e.g. "Missing Answer Key" vs a genuinely wrong answer). Marking
    Fix Follow-up: score is shown as "Pending" (not a bare "None") for a
    Kertas 2 writing answer awaiting a teacher's mark."""
    lines = []
    for marked in marked_answers:
        status_label = _marked_status_display_label(marked)
        detected = marked.student_answer_text or "(none detected)"
        expected = marked.correct_answer_text or "(not set)"
        score_text = f"{marked.score}/{marked.max_score}" if marked.score is not None else f"Pending/{marked.max_score}"
        lines.append(
            f"{marked.target_label}: [{status_label}] {score_text} | "
            f"Detected: {detected} | Expected: {expected} | {marked.feedback or ''}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def export_student_result(conn: sqlite3.Connection, teacher_id: int, profile_id: int, answer_file_id: int) -> str:
    """Build student_<name>_marked.pdf + student_<name>_comments.txt in
    data/subject_profiles/profile_{id}/results/student_<name>_result/ and
    return that folder's path. Raises ValueError if the answer file
    doesn't exist or the profile isn't owned by teacher_id."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")

    safe_name = "".join(c if c.isalnum() else "_" for c in Path(answer_file.original_filename or "student").stem)
    folder = get_subject_profile_results_folder(profile_id) / f"{safe_name}_result"
    folder.mkdir(parents=True, exist_ok=True)

    marked_answers = get_marked_answers_for_answer_file(conn, answer_file_id)
    overlays = get_overlays_for_answer_file(conn, answer_file_id)

    pdf_output_path = folder / f"{safe_name}_marked.pdf"
    try:
        _draw_overlays_on_pdf(answer_file.file_path, overlays, pdf_output_path)
    except Exception:
        # PDF annotation is best-effort (Stage 11V foundation) - fall back
        # to a plain copy of the original PDF so the export never fails
        # outright just because overlay drawing hit an unexpected page
        # layout issue.
        import shutil
        shutil.copyfile(answer_file.file_path, pdf_output_path)

    comments_path = folder / f"{safe_name}_comments.txt"
    comments_path.write_text(_comments_txt_content(marked_answers), encoding="utf-8")

    return str(folder)


def export_all_student_results(conn: sqlite3.Connection, teacher_id: int, profile_id: int) -> str:
    """Export every student result for profile_id and bundle them into one
    marked_outputs.zip (stdlib zipfile, no new dependency). Returns the
    zip file's path. Raises ValueError if there are no student results yet."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    rows = list_student_results_for_profile(conn, teacher_id, profile_id)
    if not rows:
        raise ValueError("No student results available to export yet.")

    folders = [export_student_result(conn, teacher_id, profile_id, row["answer_file_id"]) for row in rows]

    zip_path = get_subject_profile_results_folder(profile_id) / "marked_outputs.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            folder_path = Path(folder)
            for file_path in folder_path.iterdir():
                zf.write(file_path, arcname=f"{folder_path.name}/{file_path.name}")
    return str(zip_path)
