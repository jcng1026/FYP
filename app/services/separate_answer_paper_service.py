"""Stage 12G-1B - Manual Separate Answer Paper service layer.

Owns the separate-answer-paper workflow: binary mode selection + locking,
attempt-scoped answer pages, required-target derivation from the Subject
Profile, attempt-specific mappings (main + ordered continuation regions),
K1 numbered-block parsing and answer precedence, K2 text assembly, OCR
lineage/staleness, and the finalisation blockers.

The shared Subject Profile is read-only here - nothing in this module writes
to it. Standard-mode attempts are untouched by every function below.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.models.main_marking_model import get_answer_file_by_id
import app.models.separate_answer_paper_model as sap
import app.models.subject_profile_model as spm
from app.services.separate_paper_parser_service import (
    ParseResult, missing_question_numbers, parse_k1_answer_block,
)

# Audit actions (written to the existing subject_profile_review_audit table).
AUDIT_MODE_SELECTED = "sap_mode_selected"
AUDIT_PAGES_ADDED = "sap_pages_added"
AUDIT_PAGES_REORDERED = "sap_pages_reordered"
AUDIT_MAPPING_CREATED = "sap_mapping_created"
AUDIT_MAPPING_UPDATED = "sap_mapping_updated"
AUDIT_MAPPING_DELETED = "sap_mapping_deleted"
AUDIT_TARGET_BLANK_SET = "sap_target_blank_set"
AUDIT_TARGET_BLANK_CLEARED = "sap_target_blank_cleared"
AUDIT_OCR_RERUN = "sap_ocr_rerun"
AUDIT_PARSER_CORRECTION = "sap_parser_correction"
AUDIT_CONTINUATION_ORDER = "sap_continuation_order"
AUDIT_SELECTED_QUESTION_CONFIRMED = "sap_selected_question_confirmed"
AUDIT_TARGET_RECONFIRMED = "sap_target_reconfirmed"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PDF_SUFFIXES = {".pdf"}

# Synthetic label for the Part 3 selected-question metadata target (required
# but NON-gradeable: no score denominator and no overlay marker).
PART3_SELECTED_QUESTION_TARGET = "__part3_selected_question__"


# ============================================================================
# Ownership / mode
# ============================================================================


def _owned(conn, teacher_id: int, profile_id: int, answer_file_id: int):
    from app.services.subject_profile_review_service import _owned_answer_file
    return _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)


def _assert_not_finalised(conn, answer_file_id: int) -> None:
    from app.services.subject_profile_review_service import _assert_not_finalised as guard
    guard(conn, answer_file_id)


def _audit(conn, answer_file_id: int, action: str, teacher_id: Optional[int], payload: dict) -> None:
    """Sanitized audit note - geometry/ids/flags only. Full essays and raw OCR
    text are never written here."""
    spm.add_review_audit(conn, answer_file_id, action, acted_by=teacher_id, note=json.dumps(payload))


def is_separate_mode(conn, answer_file_id: int) -> bool:
    return sap.get_attempt_mode(conn, answer_file_id) == sap.ATTEMPT_MODE_SEPARATE


def mode_lock_reason(conn, answer_file_id: int) -> Optional[str]:
    """Why the attempt mode can no longer be changed, or None if it still can.
    Mode locks as soon as real work exists for the attempt."""
    if sap.get_separate_pages(conn, answer_file_id):
        return "separate answer paper pages have been uploaded"
    if sap.get_mappings_for_answer_file(conn, answer_file_id):
        return "mappings exist"
    if spm.get_extracted_answers_for_answer_file(conn, answer_file_id):
        return "OCR/extraction has run"
    if spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        return "marking/review data exists"
    review = spm.get_attempt_review(conn, answer_file_id)
    if review is not None and (review.review_state != spm.REVIEW_STATE_DRAFT
                               or review.final_output_version is not None):
        return "review or published output exists"
    return None


def set_attempt_mode(conn, teacher_id: int, profile_id: int, answer_file_id: int, mode: str):
    """Select the binary attempt mode. Refused once pages, mappings, OCR,
    review or outputs exist (mode is a structural decision)."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    if mode not in sap.ATTEMPT_MODES:
        raise ValueError(f"Attempt mode must be one of {sap.ATTEMPT_MODES}.")
    current = sap.get_attempt_mode(conn, answer_file_id)
    if current == mode:
        return mode
    locked = mode_lock_reason(conn, answer_file_id)
    if locked:
        raise ValueError(f"The attempt mode is locked because {locked}.")
    sap.set_attempt_mode(conn, answer_file_id, mode)
    _audit(conn, answer_file_id, AUDIT_MODE_SELECTED, teacher_id, {"from": current, "to": mode})
    return mode


# ============================================================================
# Pages
# ============================================================================


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _page_dimensions(path: Path, page_index: int, kind: str) -> Tuple[Optional[int], Optional[int]]:
    try:
        if kind == sap.SOURCE_KIND_PDF:
            import pymupdf
            document = pymupdf.open(str(path))
            try:
                page = document[page_index]
                rect = page.rect
                return int(rect.width), int(rect.height)
            finally:
                document.close()
        import cv2
        image = cv2.imread(str(path))
        if image is None:
            return None, None
        return int(image.shape[1]), int(image.shape[0])
    except Exception:
        return None, None


def add_separate_paper_pages(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                             file_paths: Sequence[str]) -> List[sap.SeparatePaperPage]:
    """Register uploaded separate-answer-paper files as attempt pages, in the
    given order. A PDF contributes one page row per PDF page; each image
    contributes one. Originals are never modified - only their path, checksum,
    dimensions and order are recorded."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    if not is_separate_mode(conn, answer_file_id):
        raise ValueError("This attempt is not in Separate Answer Paper mode.")
    if sap.get_mappings_for_answer_file(conn, answer_file_id):
        raise ValueError("Pages cannot be added once mappings exist.")

    existing = sap.get_separate_pages(conn, answer_file_id)
    next_number = len(existing) + 1
    created: List[sap.SeparatePaperPage] = []
    for raw_path in file_paths:
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"Uploaded file not found: {raw_path}")
        suffix = path.suffix.lower()
        if suffix in PDF_SUFFIXES:
            kind = sap.SOURCE_KIND_PDF
            try:
                import pymupdf
                document = pymupdf.open(str(path))
                page_total = document.page_count
                document.close()
            except Exception as exc:
                raise ValueError(f"Could not read PDF {path.name}: {exc}")
        elif suffix in IMAGE_SUFFIXES:
            kind = sap.SOURCE_KIND_IMAGE
            page_total = 1
        else:
            raise ValueError(f"Unsupported file type '{suffix}'. Use PDF, PNG or JPG/JPEG.")

        checksum = _sha256_file(path)
        for page_index in range(page_total):
            width, height = _page_dimensions(path, page_index, kind)
            created.append(sap.add_separate_page(
                conn, answer_file_id, next_number, str(path),
                source_original_filename=path.name, source_page_index=page_index,
                source_kind=kind, file_checksum=checksum, width_px=width, height_px=height,
                status="uploaded"))
            next_number += 1

    _audit(conn, answer_file_id, AUDIT_PAGES_ADDED, teacher_id,
           {"added": len(created), "total": next_number - 1,
            "files": [Path(p).name for p in file_paths]})
    return created


def reorder_separate_paper_pages(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                                 ordered_page_ids: Sequence[int]) -> List[sap.SeparatePaperPage]:
    """Reorder pages. Allowed ONLY before any mapping or OCR exists, because
    mappings anchor to a specific page."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    if sap.get_mappings_for_answer_file(conn, answer_file_id):
        raise ValueError("Pages cannot be reordered once mappings exist.")
    pages = sap.get_separate_pages(conn, answer_file_id)
    known = {p.sap_page_id for p in pages}
    if set(ordered_page_ids) != known or len(ordered_page_ids) != len(known):
        raise ValueError("The new page order must list every existing page exactly once.")
    before = [p.sap_page_id for p in pages]
    sap.set_separate_page_order(conn, list(ordered_page_ids))
    _audit(conn, answer_file_id, AUDIT_PAGES_REORDERED, teacher_id,
           {"from": before, "to": list(ordered_page_ids)})
    return sap.get_separate_pages(conn, answer_file_id)


def create_separate_paper_attempt(conn, teacher_id: int, profile_id: int, file_paths: Sequence[str],
                                  display_name: Optional[str] = None) -> int:
    """Create a Separate Answer Paper attempt: its own marking session +
    answer-file row, mode set to separate, and the uploaded files registered
    as ordered attempt pages. Deliberately does NOT run Subject Profile region
    extraction - in separate mode all geometry is mapped by the teacher."""
    from app.models.main_marking_model import (
        add_answer_file as add_answer_file_record, create_session as create_session_record,
        update_answer_file_path,
    )
    from app.services.subject_profile_service import PAPER_TYPE_KERTAS_1, get_owned_subject_profile
    from app.utils.file_storage import store_marking_session_file

    profile = get_owned_subject_profile(conn, teacher_id, profile_id)
    if not file_paths:
        raise ValueError("Select at least one answer paper file.")
    name = display_name or Path(file_paths[0]).name
    session = create_session_record(conn, teacher_id, f"{profile.profile_name} - {name}",
                                    PAPER_TYPE_KERTAS_1, profile.question_paper_path,
                                    profile.answer_scheme_path)
    conn.execute("UPDATE main_marking_sessions SET subject_profile_id = ? WHERE session_id = ?",
                 (profile_id, session.session_id))
    conn.commit()
    answer_file = add_answer_file_record(conn, session.session_id, "", name, None, None, None)
    af = answer_file.answer_file_id
    # Store copies of the originals under the session folder (originals on the
    # teacher's disk are never modified) and point the attempt at the first.
    stored_paths = []
    for index, path in enumerate(file_paths):
        stored_paths.append(store_marking_session_file(session.session_id, path, f"sap_{af}_{index}"))
    update_answer_file_path(conn, af, stored_paths[0])
    sap.set_attempt_mode(conn, af, sap.ATTEMPT_MODE_SEPARATE)
    _audit(conn, af, AUDIT_MODE_SELECTED, teacher_id,
           {"from": sap.ATTEMPT_MODE_STANDARD, "to": sap.ATTEMPT_MODE_SEPARATE, "files": len(file_paths)})
    add_separate_paper_pages(conn, teacher_id, profile_id, af, stored_paths)
    return af


def _page_storage_folder(profile_id: int, answer_file_id: int) -> Path:
    from app.utils.file_storage import get_subject_profile_answer_crop_folder
    folder = Path(get_subject_profile_answer_crop_folder(profile_id, answer_file_id)) / "separate_pages"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _page_image_array(page: sap.SeparatePaperPage, dpi: int = 150):
    """Render one separate-paper page to a BGR ndarray (PDF page or image)."""
    import cv2
    import numpy as np
    source = Path(page.source_file_path)
    if not source.is_file():
        return None
    if page.source_kind == sap.SOURCE_KIND_PDF:
        import pymupdf
        document = pymupdf.open(str(source))
        try:
            pdf_page = document[page.source_page_index]
            pix = pdf_page.get_pixmap(dpi=dpi)
            data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                return cv2.cvtColor(data, cv2.COLOR_RGBA2BGR)
            if pix.n == 3:
                return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
            return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
        finally:
            document.close()
    return cv2.imread(str(source))


def render_page_previews(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[str]:
    """Render a preview PNG for every separate-paper page and record its path
    and true pixel dimensions. Safe to re-run."""
    import cv2
    _owned(conn, teacher_id, profile_id, answer_file_id)
    folder = _page_storage_folder(profile_id, answer_file_id)
    written: List[str] = []
    for page in sap.get_separate_pages(conn, answer_file_id):
        image = _page_image_array(page)
        if image is None:
            sap.update_separate_page_render(conn, page.sap_page_id, status="failed",
                                            message="Source file could not be read")
            continue
        out_path = folder / f"page_{page.page_number:03d}.png"
        cv2.imwrite(str(out_path), image)
        sap.update_separate_page_render(
            conn, page.sap_page_id, preview_image_path=str(out_path), original_image_path=str(out_path),
            width_px=int(image.shape[1]), height_px=int(image.shape[0]), status="preprocessed")
        written.append(str(out_path))
    return written


def _geometry_crop_array(conn, sap_page_id: int, x: float, y: float, width_n: float, height_n: float):
    page = sap.get_separate_page(conn, sap_page_id)
    if page is None:
        return None
    image = _page_image_array(page)
    if image is None:
        return None
    height, width = image.shape[:2]
    x0 = max(0, int(x * width))
    y0 = max(0, int(y * height))
    x1 = min(width, int((x + width_n) * width))
    y1 = min(height, int((y + height_n) * height))
    if x1 <= x0 or y1 <= y0:
        return None
    return image[y0:y1, x0:x1]


def _mapping_crop_array(conn, mapping: sap.SeparatePaperMapping):
    return _geometry_crop_array(conn, mapping.sap_page_id, mapping.x, mapping.y,
                                mapping.width, mapping.height)


def _write_crop_png(crop, out_path) -> Optional[str]:
    import cv2
    if crop is None:
        return None
    ok, buffer = cv2.imencode(".png", crop)
    if not ok:
        return None
    data = bytes(buffer)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def render_geometry_crop(conn, teacher_id: int, profile_id: int, answer_file_id: int, sap_page_id: int,
                         x: float, y: float, width: float, height: float, out_path) -> Optional[str]:
    """Render an arbitrary candidate rectangle to PNG so the mapping editor can
    show a live crop preview WITHOUT creating a mapping row first."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    page = sap.get_separate_page(conn, sap_page_id)
    if page is None or page.answer_file_id != answer_file_id:
        raise ValueError("Preview must reference a page of this attempt.")
    x, y, width, height = _validate_geometry(x, y, width, height)
    return _write_crop_png(_geometry_crop_array(conn, sap_page_id, x, y, width, height), out_path)


def render_mapping_crop(conn, teacher_id: int, profile_id: int, answer_file_id: int, mapping_id: int,
                        out_path) -> Optional[str]:
    """Render a mapping's crop to PNG for the crop preview. Returns sha256."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    mapping = sap.get_mapping(conn, mapping_id)
    if mapping is None or mapping.answer_file_id != answer_file_id:
        raise ValueError("Mapping not found for this attempt.")
    return _write_crop_png(_mapping_crop_array(conn, mapping), out_path)


def _mapping_cache_key(conn, mapping: sap.SeparatePaperMapping) -> str:
    """Geometry-aware cache key: page identity + this mapping's rectangle. Any
    geometry or page change produces a different key, so a stale crop's OCR is
    never reused."""
    page = sap.get_separate_page(conn, mapping.sap_page_id)
    raw = (f"{page.file_checksum if page else ''}:{mapping.sap_page_id}:"
           f"{mapping.x}:{mapping.y}:{mapping.width}:{mapping.height}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ocr_crop_with_line_boxes(crop, engine):
    """OCR a crop in ONE call and return (text, line_boxes) where each line box
    is normalised to the crop rectangle. Returns (None, None) when the crop is
    too tall for a single reliable call (the chunked path handles those) or the
    engine reports no geometry - callers then fall back to text-only OCR."""
    import os
    import tempfile
    import cv2
    from app.services.region_crop_ocr_service import TALL_CROP_CHUNK_HEIGHT_PX

    height, width = crop.shape[:2]
    if height > TALL_CROP_CHUNK_HEIGHT_PX or height <= 0 or width <= 0:
        return None, None
    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    cv2.imwrite(path, crop)
    try:
        result = engine.run_page(path)
    finally:
        Path(path).unlink(missing_ok=True)

    blocks = list(getattr(result, "blocks", None) or [])
    if not blocks:
        return (result.text or ""), None
    boxes = []
    for block in blocks:
        corners = getattr(block, "box", None) or []
        xs = [float(point[0]) for point in corners if len(point) >= 2]
        ys = [float(point[1]) for point in corners if len(point) >= 2]
        if not xs or not ys:
            continue
        boxes.append({
            "text": block.text,
            "x": round(max(0.0, min(xs) / width), 5),
            "y": round(max(0.0, min(ys) / height), 5),
            "width": round(min(1.0, (max(xs) - min(xs)) / width), 5),
            "height": round(min(1.0, (max(ys) - min(ys)) / height), 5),
        })
    return (result.text or ""), (boxes or None)


def run_mapping_ocr(conn, teacher_id: int, profile_id: int, answer_file_id: int, mapping_id: int, *,
                    force_rerun: bool = False, engine=None) -> Optional[str]:
    """OCR one mapping's crop. The FIRST successful OCR becomes the mapping's
    original OCR; every later run is stored as the rerun OCR - the two are
    never mixed, and teacher-corrected text is untouched. A geometry-aware
    cache key skips redundant work unless force_rerun is set. A failure raises
    without deleting any existing text."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    mapping = sap.get_mapping(conn, mapping_id)
    if mapping is None or mapping.answer_file_id != answer_file_id:
        raise ValueError("Mapping not found for this attempt.")

    cache_key = _mapping_cache_key(conn, mapping)
    unchanged = mapping.crop_checksum == cache_key
    if unchanged and not force_rerun and mapping.original_ocr_text is not None:
        return mapping.original_ocr_text  # geometry unchanged - no redundant OCR, no new blocker

    crop = _mapping_crop_array(conn, mapping)
    if crop is None:
        raise ValueError("The mapped area could not be rendered from the answer paper page.")
    from app.services.region_crop_ocr_service import LazyOCREngine, ocr_tall_crop_in_chunks
    from app.services.subject_profile_service import get_default_engine
    lazy = LazyOCREngine(engine=engine, resolver=get_default_engine)
    resolved_engine = lazy.get()
    text, line_boxes = _ocr_crop_with_line_boxes(crop, resolved_engine)
    if text is None:
        # No usable line geometry (tall crop, or an engine without boxes) -
        # fall back to the established chunked text-only path.
        text = ocr_tall_crop_in_chunks(crop, resolved_engine)
    text = (text or "").strip() or None

    previous_effective = mapping.effective_text
    if mapping.original_ocr_text is None:
        sap.set_mapping_original_ocr(conn, mapping_id, text, None, cache_key)
    else:
        sap.set_mapping_rerun_ocr(conn, mapping_id, text, None, cache_key)
    sap.set_mapping_ocr_line_boxes(conn, mapping_id, line_boxes)
    _audit(conn, answer_file_id, AUDIT_OCR_RERUN, teacher_id, {
        "mapping_id": mapping_id, "target": mapping.target_label, "forced": bool(force_rerun),
        "changed": (text or "") != (previous_effective or "")})
    if previous_effective is not None and (text or "") != (previous_effective or ""):
        _mark_stale_if_reviewed(conn, answer_file_id, mapping.target_label)
    return text


# ============================================================================
# Required targets
# ============================================================================


@dataclass
class RequiredTarget:
    target_label: str
    paper: str                      # "Kertas 1" / "Kertas 2" / "Metadata"
    display_label: str              # "Question 12" / "Part 1" / "Part 3 selected question"
    question_no: Optional[str]
    is_gradeable: bool
    max_score: float
    state: str                      # unresolved / mapped / explicitly_blank
    blank_confirmed: bool
    review_stale: bool
    mapping_count: int
    has_conflict: bool


def _profile_targets(conn, teacher_id: int, profile_id: int):
    """(k1_labels_by_question, k2_labels, has_part3_selected_question) derived
    from the shared Subject Profile - helpers, legends and `_cont` duplicates
    excluded, so a continuation never becomes its own score target."""
    from app.services.subject_profile_service import (
        SOURCE_QUESTION_PAPER, _filter_gradeable_regions, _is_context_question_number_label,
        get_regions_for_profile, NON_ANSWER_REGION_TYPES,
    )
    from app.models.subject_profile_model import (
        REGION_TYPE_ANSWER_BOX, extract_question_number_from_label,
    )
    regions = [r for r in get_regions_for_profile(conn, profile_id, SOURCE_QUESTION_PAPER)
               if r.region_type not in NON_ANSWER_REGION_TYPES]
    gradeable = _filter_gradeable_regions(regions)
    k1_by_question: Dict[str, str] = {}
    k2_labels: List[str] = []
    for region in gradeable:
        if region.region_type == REGION_TYPE_ANSWER_BOX:
            k2_labels.append(region.label)
            continue
        qno = extract_question_number_from_label(region.label)
        if qno is None:
            continue
        k1_by_question.setdefault(qno, region.label)
    has_part3_field = any(_is_context_question_number_label(r.label) for r in regions)
    return k1_by_question, k2_labels, has_part3_field


def list_required_targets(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[RequiredTarget]:
    """Every logical target a separate-paper attempt must resolve: real scored
    K1 questions, K2 Part 1/2/3, and the (non-gradeable) Part 3
    selected-question metadata."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    from app.services.subject_profile_review_service import kertas2_part_label
    from app.services.subject_profile_service import get_answer_key_entries_for_profile

    k1_by_question, k2_labels, has_part3_field = _profile_targets(conn, teacher_id, profile_id)
    max_by_label = {e.target_label: e.max_mark for e in get_answer_key_entries_for_profile(conn, profile_id)}
    states = {s.target_label: s for s in sap.get_target_states(conn, answer_file_id)}
    mappings_by_target: Dict[str, int] = {}
    for m in sap.get_mappings_for_answer_file(conn, answer_file_id):
        mappings_by_target[m.target_label] = mappings_by_target.get(m.target_label, 0) + 1
    conflicts = {p.question_no for p in sap.get_parsed_answers(conn, answer_file_id) if p.has_conflict}

    targets: List[RequiredTarget] = []

    def _state_of(label: str, mapped: bool) -> Tuple[str, bool, bool]:
        st = states.get(label)
        if st is not None and st.state == sap.TARGET_STATE_EXPLICITLY_BLANK:
            return sap.TARGET_STATE_EXPLICITLY_BLANK, st.blank_confirmed, st.review_stale
        if mapped:
            return sap.TARGET_STATE_MAPPED, bool(st.blank_confirmed) if st else False, bool(st.review_stale) if st else False
        if st is not None:
            return st.state, st.blank_confirmed, st.review_stale
        return sap.TARGET_STATE_UNRESOLVED, False, False

    for qno in sorted(k1_by_question, key=lambda q: int(q) if q.isdigit() else 0):
        label = k1_by_question[qno]
        mapped = _k1_question_is_resolved(conn, answer_file_id, label, qno)
        state, blank_confirmed, stale = _state_of(label, mapped)
        targets.append(RequiredTarget(
            target_label=label, paper="Kertas 1", display_label=f"Question {qno}", question_no=qno,
            is_gradeable=True, max_score=max_by_label.get(label, 1.0), state=state,
            blank_confirmed=blank_confirmed, review_stale=stale,
            mapping_count=mappings_by_target.get(label, 0), has_conflict=qno in conflicts))

    for label in k2_labels:
        state, blank_confirmed, stale = _state_of(label, mappings_by_target.get(label, 0) > 0)
        targets.append(RequiredTarget(
            target_label=label, paper="Kertas 2", display_label=kertas2_part_label(label),
            question_no=None, is_gradeable=True, max_score=max_by_label.get(label, 20.0),
            state=state, blank_confirmed=blank_confirmed, review_stale=stale,
            mapping_count=mappings_by_target.get(label, 0), has_conflict=False))

    if has_part3_field:
        label = PART3_SELECTED_QUESTION_TARGET
        state, blank_confirmed, stale = _state_of(label, mappings_by_target.get(label, 0) > 0)
        targets.append(RequiredTarget(
            target_label=label, paper="Metadata", display_label="Part 3 selected question",
            question_no=None, is_gradeable=False, max_score=0.0, state=state,
            blank_confirmed=blank_confirmed, review_stale=stale,
            mapping_count=mappings_by_target.get(label, 0), has_conflict=False))
    return targets


def _k1_question_is_resolved(conn, answer_file_id: int, label: str, question_no: str) -> bool:
    """A K1 question counts as mapped when an answer exists for it through the
    precedence chain (teacher > individual mapping > confirmed block parse)."""
    answer, _source = resolve_k1_answer(conn, answer_file_id, label, question_no)
    return answer is not None


def target_summary(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> Dict[str, int]:
    targets = list_required_targets(conn, teacher_id, profile_id, answer_file_id)
    return {
        "total": len(targets),
        "mapped": sum(1 for t in targets if t.state == sap.TARGET_STATE_MAPPED),
        "blank": sum(1 for t in targets if t.state == sap.TARGET_STATE_EXPLICITLY_BLANK),
        "unresolved": sum(1 for t in targets if t.state == sap.TARGET_STATE_UNRESOLVED),
        "stale": sum(1 for t in targets if t.review_stale),
        "conflicts": sum(1 for t in targets if t.has_conflict),
    }


# ============================================================================
# Mappings
# ============================================================================


def _validate_geometry(x, y, width, height) -> Tuple[float, float, float, float]:
    try:
        x, y, width, height = float(x), float(y), float(width), float(height)
    except (TypeError, ValueError):
        raise ValueError("Mapping geometry must be numeric.")
    if width <= 0 or height <= 0:
        raise ValueError("Mapping width and height must be greater than zero.")
    if x < 0 or y < 0 or x + width > 1.0 or y + height > 1.0:
        raise ValueError("Mapping must lie inside the page (0.0-1.0, and x+width / y+height <= 1.0).")
    return x, y, width, height


def create_mapping(conn, teacher_id: int, profile_id: int, answer_file_id: int, target_label: str,
                   mapping_type: str, sap_page_id: int, x: float, y: float, width: float, height: float, *,
                   reading_order: Optional[int] = None, is_continuation: bool = False,
                   paper: Optional[str] = None, part: Optional[str] = None,
                   question_no: Optional[str] = None) -> sap.SeparatePaperMapping:
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    if not is_separate_mode(conn, answer_file_id):
        raise ValueError("Mappings only apply to a Separate Answer Paper attempt.")
    x, y, width, height = _validate_geometry(x, y, width, height)
    page = sap.get_separate_page(conn, sap_page_id)
    if page is None or page.answer_file_id != answer_file_id:
        raise ValueError("Mapping must reference a page of this attempt.")

    existing = sap.get_mappings_for_target(conn, answer_file_id, target_label)
    if reading_order is None:
        reading_order = max((m.reading_order for m in existing), default=0) + 1
    if any(m.reading_order == reading_order for m in existing):
        raise ValueError(f"Reading order {reading_order} is already used for this target.")

    mapping = sap.add_mapping(
        conn, answer_file_id, target_label, mapping_type, sap_page_id, x, y, width, height,
        paper=paper, part=part, question_no=question_no,
        page_width_px=page.width_px, page_height_px=page.height_px,
        reading_order=reading_order, is_continuation=is_continuation, created_by=teacher_id)
    sap.upsert_target_state(conn, answer_file_id, target_label, state=sap.TARGET_STATE_MAPPED,
                            blank_confirmed=False, updated_by=teacher_id)
    _mark_stale_if_reviewed(conn, answer_file_id, target_label)
    _audit(conn, answer_file_id, AUDIT_MAPPING_CREATED, teacher_id, {
        "target": target_label, "mapping_id": mapping.mapping_id, "type": mapping_type,
        "page": sap_page_id, "geometry": {"x": x, "y": y, "width": width, "height": height},
        "reading_order": reading_order, "is_continuation": bool(is_continuation)})
    return mapping


def update_mapping(conn, teacher_id: int, profile_id: int, answer_file_id: int, mapping_id: int, *,
                   sap_page_id: Optional[int] = None, x: Optional[float] = None, y: Optional[float] = None,
                   width: Optional[float] = None, height: Optional[float] = None,
                   reading_order: Optional[int] = None) -> sap.SeparatePaperMapping:
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    mapping = sap.get_mapping(conn, mapping_id)
    if mapping is None or mapping.answer_file_id != answer_file_id:
        raise ValueError("Mapping not found for this attempt.")
    new_x = mapping.x if x is None else x
    new_y = mapping.y if y is None else y
    new_w = mapping.width if width is None else width
    new_h = mapping.height if height is None else height
    new_x, new_y, new_w, new_h = _validate_geometry(new_x, new_y, new_w, new_h)
    if sap_page_id is not None:
        page = sap.get_separate_page(conn, sap_page_id)
        if page is None or page.answer_file_id != answer_file_id:
            raise ValueError("Mapping must reference a page of this attempt.")
    if reading_order is not None and reading_order != mapping.reading_order:
        siblings = sap.get_mappings_for_target(conn, answer_file_id, mapping.target_label)
        if any(m.reading_order == reading_order and m.mapping_id != mapping_id for m in siblings):
            raise ValueError(f"Reading order {reading_order} is already used for this target.")
    before = {"x": mapping.x, "y": mapping.y, "width": mapping.width, "height": mapping.height,
              "page": mapping.sap_page_id, "reading_order": mapping.reading_order}
    updated = sap.update_mapping_geometry(
        conn, mapping_id, sap_page_id=sap_page_id, x=new_x, y=new_y, width=new_w, height=new_h,
        reading_order=reading_order)
    _mark_stale_if_reviewed(conn, answer_file_id, mapping.target_label)
    action = AUDIT_CONTINUATION_ORDER if reading_order is not None else AUDIT_MAPPING_UPDATED
    _audit(conn, answer_file_id, action, teacher_id, {
        "target": mapping.target_label, "mapping_id": mapping_id, "before": before,
        "after": {"x": updated.x, "y": updated.y, "width": updated.width, "height": updated.height,
                  "page": updated.sap_page_id, "reading_order": updated.reading_order}})
    return updated


def delete_mapping(conn, teacher_id: int, profile_id: int, answer_file_id: int, mapping_id: int) -> None:
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    mapping = sap.get_mapping(conn, mapping_id)
    if mapping is None or mapping.answer_file_id != answer_file_id:
        raise ValueError("Mapping not found for this attempt.")
    _audit(conn, answer_file_id, AUDIT_MAPPING_DELETED, teacher_id, {
        "target": mapping.target_label, "mapping_id": mapping_id, "type": mapping.mapping_type,
        "geometry": {"x": mapping.x, "y": mapping.y, "width": mapping.width, "height": mapping.height},
        "reading_order": mapping.reading_order, "had_ocr": mapping.original_ocr_text is not None})
    sap.delete_mapping(conn, mapping_id)
    remaining = sap.get_mappings_for_target(conn, answer_file_id, mapping.target_label)
    if not remaining:
        sap.upsert_target_state(conn, answer_file_id, mapping.target_label,
                                state=sap.TARGET_STATE_UNRESOLVED, updated_by=teacher_id)
    _mark_stale_if_reviewed(conn, answer_file_id, mapping.target_label)


def mark_target_blank(conn, teacher_id: int, profile_id: int, answer_file_id: int, target_label: str,
                      *, note: Optional[str] = None):
    """Explicitly blank = the teacher confirms the student left it blank.
    Unmapped is NEVER treated as blank."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    state = sap.upsert_target_state(conn, answer_file_id, target_label,
                                    state=sap.TARGET_STATE_EXPLICITLY_BLANK, blank_confirmed=True,
                                    note=note, updated_by=teacher_id)
    _mark_stale_if_reviewed(conn, answer_file_id, target_label)
    _audit(conn, answer_file_id, AUDIT_TARGET_BLANK_SET, teacher_id,
           {"target": target_label, "confirmed": True})
    return state


def clear_target_blank(conn, teacher_id: int, profile_id: int, answer_file_id: int, target_label: str):
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    mapped = bool(sap.get_mappings_for_target(conn, answer_file_id, target_label))
    state = sap.upsert_target_state(
        conn, answer_file_id, target_label,
        state=sap.TARGET_STATE_MAPPED if mapped else sap.TARGET_STATE_UNRESOLVED,
        blank_confirmed=False, updated_by=teacher_id)
    _audit(conn, answer_file_id, AUDIT_TARGET_BLANK_CLEARED, teacher_id, {"target": target_label})
    return state


# ============================================================================
# K1 parsing + answer precedence
# ============================================================================


def parse_k1_block_mapping(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                           mapping_id: int) -> ParseResult:
    """Parse a k1_answer_block mapping's effective text into per-question rows."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    mapping = sap.get_mapping(conn, mapping_id)
    if mapping is None or mapping.answer_file_id != answer_file_id:
        raise ValueError("Mapping not found for this attempt.")
    if mapping.mapping_type != sap.MAPPING_TYPE_K1_BLOCK:
        raise ValueError("Only a Kertas 1 numbered-answer block can be parsed.")
    k1_by_question, _k2, _p3 = _profile_targets(conn, teacher_id, profile_id)
    result = parse_k1_answer_block(mapping.effective_text,
                                   expected_question_numbers=sorted(k1_by_question, key=lambda q: int(q)))
    rows = [r.as_dict() for r in result.rows]
    _apply_ocr_line_anchors(mapping, rows)
    sap.replace_parsed_answers_for_mapping(conn, answer_file_id, mapping_id, rows)
    return result


def _apply_ocr_line_anchors(mapping, rows: List[dict]) -> None:
    """Upgrade each parsed row's approximate anchor to the REAL OCR line box it
    came from, where the engine reported one.

    The parser can only infer a position from line index and character offset
    in plain text; when the mapping has recognised line geometry we match each
    row's source text to its line and use that box instead. Rows with no match
    keep the parser's approximate anchor, and `anchor_source` records which of
    the two was used so nothing pretends to be exact when it is not."""
    boxes = mapping.ocr_line_boxes
    for row in rows:
        row.setdefault("anchor_source", ANCHOR_SOURCE_APPROXIMATE_ROW)
    if not boxes:
        return

    def _normalise(text):
        return "".join(ch for ch in (text or "").lower() if ch.isalnum())

    remaining = list(enumerate(boxes))
    for row in rows:
        source = _normalise(row.get("source_text"))
        if not source:
            continue
        match = next((entry for entry in remaining if source and source in _normalise(entry[1].get("text"))), None)
        if match is None:
            question = (row.get("question_no") or "").strip()
            answer = _normalise(row.get("parsed_answer"))
            if question and answer:
                match = next((entry for entry in remaining
                              if _normalise(entry[1].get("text")).startswith(_normalise(question) + answer)), None)
        if match is None:
            continue
        remaining.remove(match)
        box = match[1]
        row.update(anchor_x=box.get("x"), anchor_y=box.get("y"),
                   anchor_width=box.get("width"), anchor_height=box.get("height"),
                   anchor_source=ANCHOR_SOURCE_OCR_LINE)


def correct_parsed_answer(conn, teacher_id: int, profile_id: int, answer_file_id: int, parsed_id: int,
                          *, teacher_answer: Optional[str] = None, state: Optional[str] = None):
    """Teacher confirms/corrects/blanks/unresolves one parsed row. This is a
    real teacher decision - the parser output is preserved untouched."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    updated = sap.update_parsed_answer(conn, parsed_id, teacher_answer=teacher_answer, state=state,
                                       has_conflict=False if state == sap.PARSED_STATE_CONFIRMED else None)
    _audit(conn, answer_file_id, AUDIT_PARSER_CORRECTION, teacher_id, {
        "parsed_id": parsed_id, "question_no": updated.question_no if updated else None,
        "state": updated.state if updated else None,
        "teacher_answer_set": bool(updated and updated.teacher_answer is not None)})
    return updated


def resolve_k1_answer(conn, answer_file_id: int, target_label: str,
                      question_no: Optional[str]) -> Tuple[Optional[str], str]:
    """Answer precedence for one K1 question:
    1. teacher final answer on the target state
    2. confirmed individual mapping (its corrected/OCR text)
    3. confirmed block-parser row (teacher answer, else parsed answer)
    4. unresolved (None)
    Explicitly-blank targets resolve to "" (a confirmed blank), which is NOT
    the same as unresolved."""
    state = sap.get_target_state(conn, answer_file_id, target_label)
    if state is not None and state.teacher_final_answer is not None:
        return state.teacher_final_answer, "teacher_final_answer"
    if state is not None and state.state == sap.TARGET_STATE_EXPLICITLY_BLANK and state.blank_confirmed:
        return "", "explicitly_blank"

    for mapping in sap.get_mappings_for_target(conn, answer_file_id, target_label):
        if mapping.mapping_type == sap.MAPPING_TYPE_K1_INDIVIDUAL and mapping.confirmed:
            text = mapping.effective_text
            if text is not None and text.strip():
                return text.strip(), "individual_mapping"

    if question_no is not None:
        for parsed in sap.get_parsed_answers(conn, answer_file_id):
            if parsed.question_no != question_no:
                continue
            if parsed.state == sap.PARSED_STATE_BLANK:
                return "", "parser_blank"
            if parsed.state == sap.PARSED_STATE_CONFIRMED and parsed.effective_answer:
                return parsed.effective_answer, "block_parser"
    return None, "unresolved"


def set_teacher_final_answer(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                             target_label: str, answer: Optional[str]):
    """Highest-precedence teacher answer for a K1 target."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    state = sap.upsert_target_state(conn, answer_file_id, target_label,
                                    teacher_final_answer=answer, updated_by=teacher_id,
                                    clear_teacher_final_answer=(answer is None))
    _audit(conn, answer_file_id, AUDIT_PARSER_CORRECTION, teacher_id,
           {"target": target_label, "teacher_final_answer_set": answer is not None})
    return state


# ============================================================================
# K2 assembly + Part 3 selected question
# ============================================================================


def assemble_k2_text(conn, answer_file_id: int, target_label: str) -> Optional[str]:
    """Combine a K2 target's mapped regions in explicit reading order. Each
    region's own text is the teacher-corrected text when present, else the
    rerun OCR, else the original OCR - joined predictably with newlines."""
    mappings = sap.get_mappings_for_target(conn, answer_file_id, target_label)
    if not mappings:
        return None
    parts = []
    for mapping in sorted(mappings, key=lambda m: (m.reading_order, m.mapping_id)):
        text = mapping.effective_text
        if text:
            parts.append(text.strip())
    return "\n".join(parts) if parts else None


def continuation_order(conn, answer_file_id: int, target_label: str) -> List[Tuple[int, int, bool]]:
    """(reading_order, mapping_id, is_continuation) for a target, in order."""
    return [(m.reading_order, m.mapping_id, m.is_continuation)
            for m in sap.get_mappings_for_target(conn, answer_file_id, target_label)]


def confirm_part3_selected_question(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                                    question_number: Optional[str]):
    """Confirm the Part 3 selected question for a separate-paper attempt. It is
    required but NON-gradeable: no score denominator, no overlay marker."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    from app.services.subject_profile_service import PART3_VALID_QUESTION_NUMBERS
    value = None
    if question_number is not None and str(question_number).strip():
        value = "".join(ch for ch in str(question_number) if ch.isdigit())
        if value not in PART3_VALID_QUESTION_NUMBERS:
            raise ValueError(f"Part 3 question must be one of: {', '.join(PART3_VALID_QUESTION_NUMBERS)}.")
    state = sap.upsert_target_state(conn, answer_file_id, PART3_SELECTED_QUESTION_TARGET,
                                    state=sap.TARGET_STATE_MAPPED if value else sap.TARGET_STATE_UNRESOLVED,
                                    teacher_final_answer=value, updated_by=teacher_id,
                                    clear_teacher_final_answer=(value is None))
    # The teacher confirms the Part 3 question ONCE, in the mapping workspace.
    # Propagate it to the Part 3 answer box so Teacher Review's existing Part 3
    # requirement is satisfied by that same decision rather than asking twice.
    from app.services.subject_profile_service import _is_part3_answer_box
    for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        if _is_part3_answer_box(m.region_type, m.target_label):
            spm.update_marked_answer_review_fields(
                conn, m.marked_answer_id, teacher_selected_question_number=value,
                fields=["teacher_selected_question_number"])
    _audit(conn, answer_file_id, AUDIT_SELECTED_QUESTION_CONFIRMED, teacher_id,
           {"question_number": value})
    return state


def get_part3_selected_question(conn, answer_file_id: int) -> Optional[str]:
    state = sap.get_target_state(conn, answer_file_id, PART3_SELECTED_QUESTION_TARGET)
    return state.teacher_final_answer if state else None


# ============================================================================
# Staleness + blockers
# ============================================================================


def _mark_stale_if_reviewed(conn, answer_file_id: int, target_label: str) -> None:
    """Flag the target's review stale after an input change, but only if a
    teacher review actually exists for it (an unchanged/unreviewed target must
    not create a blocker)."""
    reviewed = False
    for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        if m.target_label == target_label and (m.teacher_status is not None or m.teacher_score is not None):
            reviewed = True
            break
    state = sap.get_target_state(conn, answer_file_id, target_label)
    if state is not None and state.teacher_final_answer is not None:
        reviewed = True
    if reviewed:
        sap.upsert_target_state(conn, answer_file_id, target_label, review_stale=True)


def reconfirm_target(conn, teacher_id: int, profile_id: int, answer_file_id: int, target_label: str):
    _owned(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    state = sap.upsert_target_state(conn, answer_file_id, target_label, review_stale=False,
                                    updated_by=teacher_id)
    _audit(conn, answer_file_id, AUDIT_TARGET_RECONFIRMED, teacher_id, {"target": target_label})
    return state


def get_separate_mode_blockers(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[str]:
    """Separate-mode finalisation blockers (added to the existing Phase 2A/2B/2C
    blockers). Unresolved targets, parser/mapping conflicts, duplicate
    continuation order, stale reviews and an unconfirmed Part 3 question all
    block finalisation."""
    if not is_separate_mode(conn, answer_file_id):
        return []
    problems: List[str] = []
    targets = list_required_targets(conn, teacher_id, profile_id, answer_file_id)
    for target in targets:
        if target.state == sap.TARGET_STATE_UNRESOLVED:
            problems.append(
                f"{target.paper} {target.display_label}: not mapped and not confirmed blank.")
        elif target.state == sap.TARGET_STATE_EXPLICITLY_BLANK and not target.blank_confirmed:
            problems.append(f"{target.paper} {target.display_label}: blank has not been confirmed.")
        if target.has_conflict:
            problems.append(
                f"{target.paper} {target.display_label}: unresolved parser conflict - confirm the answer.")
        if target.review_stale:
            problems.append(
                f"{target.paper} {target.display_label}: inputs changed - reconfirm the review.")

    # Duplicate continuation reading order (defensive - the UNIQUE key also guards).
    seen: Dict[str, set] = {}
    for mapping in sap.get_mappings_for_answer_file(conn, answer_file_id):
        orders = seen.setdefault(mapping.target_label, set())
        if mapping.reading_order in orders:
            problems.append(f"{mapping.target_label}: duplicate continuation reading order "
                            f"{mapping.reading_order}.")
        orders.add(mapping.reading_order)

    if any(t.target_label == PART3_SELECTED_QUESTION_TARGET for t in targets):
        if not get_part3_selected_question(conn, answer_file_id):
            problems.append("Part 3 selected question has not been confirmed.")
    return problems


def sync_separate_mode_marked_answers(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> int:
    """Project the resolved separate-paper data into the standard marked-answer
    rows so the EXISTING Teacher Review workspace, overlays and outputs work
    unchanged. Machine columns are (re)written from the mapped/parsed source;
    teacher columns already recorded in review are never touched here."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    if not is_separate_mode(conn, answer_file_id):
        return 0
    from app.models.subject_profile_model import (
        MARKED_ANSWER_STATUS_MARKED, MARKED_ANSWER_STATUS_NEEDS_REVIEW,
        MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE,
    )
    from app.services.subject_profile_service import (
        KERTAS2_WRITING_MAX_SCORE, get_answer_key_entries_for_profile,
    )
    keys = {e.target_label: e for e in get_answer_key_entries_for_profile(conn, profile_id)}
    existing = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    written = 0
    for target in list_required_targets(conn, teacher_id, profile_id, answer_file_id):
        if target.target_label == PART3_SELECTED_QUESTION_TARGET:
            continue
        if target.paper == "Kertas 2":
            text = assemble_k2_text(conn, answer_file_id, target.target_label)
            if target.state == sap.TARGET_STATE_EXPLICITLY_BLANK:
                text = ""
            detected, correct, score, max_score = text, None, None, KERTAS2_WRITING_MAX_SCORE
            status = MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE
            is_correct = False
            feedback = "Pending Teacher Score - separate answer paper mapping."
        else:
            answer, source = resolve_k1_answer(conn, answer_file_id, target.target_label, target.question_no)
            entry = keys.get(target.target_label)
            correct = entry.correct_answer if entry else None
            max_score = entry.max_mark if entry else target.max_score
            detected = answer
            if answer is None:
                status, is_correct, score = MARKED_ANSWER_STATUS_NEEDS_REVIEW, False, 0.0
                feedback = "Unresolved on the separate answer paper - map it or confirm it blank."
            else:
                is_correct = bool(correct) and answer.strip().lower() == str(correct).strip().lower()
                status = MARKED_ANSWER_STATUS_MARKED
                score = max_score if is_correct else 0.0
                feedback = f"Correct. (separate paper: {source})" if is_correct else f"Wrong. (separate paper: {source})"
        current = existing.get(target.target_label)
        if current is None:
            spm.add_marked_answer(
                conn, answer_file_id, target.target_label, "region",
                "answer_box" if target.paper == "Kertas 2" else "bubble_area",
                detected, correct, score, max_score, bool(is_correct), status, feedback,
                raw_ocr_text=detected)
        else:
            conn.execute(
                "UPDATE subject_profile_marked_answers SET student_answer_text = ?, correct_answer_text = ?, "
                "score = ?, max_score = ?, is_correct = ?, status = ?, feedback = ? WHERE marked_answer_id = ?",
                (detected, correct, score, max_score, int(bool(is_correct)), status, feedback,
                 current.marked_answer_id))
            conn.commit()
        written += 1
    # Carry an already-confirmed Part 3 question onto the (possibly just
    # created) Part 3 answer box, so the order of the teacher's steps does not
    # matter and the question is never asked twice.
    selected = get_part3_selected_question(conn, answer_file_id)
    if selected:
        confirm_part3_selected_question(conn, teacher_id, profile_id, answer_file_id, selected)
    # Refresh the editable overlay markers so the existing overlay editor can
    # move/hide each per-question marker.
    sync_separate_mode_overlays(conn, teacher_id, profile_id, answer_file_id)
    return written


# ============================================================================
# Final outputs (separate-paper background + mapping anchors)
# ============================================================================


@dataclass
class SeparateOverlayMark:
    """One marker to draw on the separate answer paper. Positions come ONLY
    from attempt mappings - never from Subject Profile coordinates."""
    sap_page_id: int
    page_number: int
    target_label: str
    kind: str            # 'tick' | 'cross' | 'question'
    text_value: Optional[str]
    x: float
    y: float


@dataclass
class TargetAnchor:
    """Where ONE logical target's marker belongs on the separate answer paper,
    plus how that position was obtained (never claimed to be exact when it is
    only an estimate)."""
    sap_page_id: int
    x: float
    y: float
    width: float
    height: float
    source: str

    @property
    def is_approximate(self) -> bool:
        return self.source == ANCHOR_SOURCE_APPROXIMATE_ROW


ANCHOR_SOURCE_OWN_MAPPING = "own_mapping"
ANCHOR_SOURCE_OCR_LINE = sap.ANCHOR_SOURCE_OCR_LINE
ANCHOR_SOURCE_APPROXIMATE_ROW = sap.ANCHOR_SOURCE_APPROXIMATE


def _project_block_anchor(block, parsed) -> Optional[TargetAnchor]:
    """Project a parsed row's BLOCK-relative anchor onto the page, using the
    block mapping's own rectangle. Returns None when the row has no anchor."""
    if parsed is None or parsed.anchor_y is None:
        return None
    x = block.x + (parsed.anchor_x or 0.0) * block.width
    y = block.y + parsed.anchor_y * block.height
    width = max((parsed.anchor_width or 0.0) * block.width, 0.005)
    height = max((parsed.anchor_height or 0.0) * block.height, 0.005)
    return TargetAnchor(
        sap_page_id=block.sap_page_id,
        x=round(min(max(x, 0.0), 0.999), 5), y=round(min(max(y, 0.0), 0.999), 5),
        width=round(width, 5), height=round(height, 5),
        source=(ANCHOR_SOURCE_OCR_LINE if parsed.has_exact_anchor else ANCHOR_SOURCE_APPROXIMATE_ROW),
    )


def target_marker_anchor(conn, answer_file_id: int, target: "RequiredTarget") -> Optional[TargetAnchor]:
    """The anchor for ONE logical target's single status marker.

    Precedence:
      1. the target's own first non-continuation mapping (exact - the teacher
         drew it), so a continuation region never produces a second anchor;
      2. for a Kertas 1 question resolved through a numbered-answer block, the
         parsed row's own line - real OCR line geometry when the engine gave
         it, otherwise the parser's approximate row estimate;
      3. nothing - a position is never invented (a confirmed blank with no
         mapped area legitimately gets no marker).
    """
    mappings = sap.get_mappings_for_target(conn, answer_file_id, target.target_label)
    own = sorted([m for m in mappings if not m.is_continuation and m.mapping_type != sap.MAPPING_TYPE_K1_BLOCK],
                 key=lambda m: (m.reading_order, m.mapping_id))
    if own:
        first = own[0]
        return TargetAnchor(sap_page_id=first.sap_page_id, x=first.x, y=first.y,
                            width=first.width, height=first.height, source=ANCHOR_SOURCE_OWN_MAPPING)

    if target.question_no is not None:
        blocks = {m.mapping_id: m for m in sap.get_mappings_for_answer_file(conn, answer_file_id)
                  if m.mapping_type == sap.MAPPING_TYPE_K1_BLOCK}
        for parsed in sap.get_parsed_answers(conn, answer_file_id):
            if parsed.question_no != target.question_no:
                continue
            block = blocks.get(parsed.mapping_id)
            if block is None:
                continue
            projected = _project_block_anchor(block, parsed)
            if projected is not None:
                return projected

    # A block mapping filed under this target, with no per-row anchor at all,
    # is still a real teacher-drawn area - use it, but only for the ONE target
    # it is filed under (callers de-duplicate identical positions).
    block_only = sorted([m for m in mappings if m.mapping_type == sap.MAPPING_TYPE_K1_BLOCK],
                        key=lambda m: (m.reading_order, m.mapping_id))
    if block_only:
        first = block_only[0]
        return TargetAnchor(sap_page_id=first.sap_page_id, x=first.x, y=first.y,
                            width=first.width, height=first.height, source=ANCHOR_SOURCE_OWN_MAPPING)
    return None


def build_separate_overlay_marks(conn, teacher_id: int, profile_id: int,
                                 answer_file_id: int) -> List[SeparateOverlayMark]:
    """At most ONE status marker per logical target, anchored on the separate
    paper. Rules:
      - a Kertas 1 question resolved through a numbered-answer block is
        anchored on ITS OWN parsed line, so Q1 and Q2 get separate markers;
      - a continuation region never produces a second marker;
      - the Part 3 selected-question metadata target never gets a marker;
      - an explicitly-blank target with no mapped area gets NO marker;
      - two markers are never stacked at the same position - if a second
        target resolves to a position already used, it is dropped rather than
        drawn on top of the first.
      - a teacher's overlay edit wins: a moved marker keeps its position and a
        hidden marker is not drawn.
    """
    marks: List[SeparateOverlayMark] = []
    pages = {p.sap_page_id: p for p in sap.get_separate_pages(conn, answer_file_id)}
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    overlays = {o.target_label: o for o in spm.get_overlays_for_answer_file(conn, answer_file_id)
                if o.target_label is not None}
    used_positions = set()

    for target in list_required_targets(conn, teacher_id, profile_id, answer_file_id):
        if target.target_label == PART3_SELECTED_QUESTION_TARGET:
            continue  # required metadata, but never a drawn marker
        anchor = target_marker_anchor(conn, answer_file_id, target)
        if anchor is None:
            continue  # blank/unresolved with no real anchor -> no fabricated marker
        page = pages.get(anchor.sap_page_id)
        if page is None:
            continue

        kind, text = _marker_for_target(conn, answer_file_id, target, marked_by_label)
        if kind is None:
            continue

        overlay = overlays.get(target.target_label)
        if overlay is not None and overlay.is_hidden:
            continue
        if overlay is not None and overlay.is_teacher_adjusted:
            x, y = overlay.x, overlay.y
        else:
            x, y = min(0.96, anchor.x + anchor.width + 0.005), anchor.y

        position = (anchor.sap_page_id, round(x, 4), round(y, 4))
        if position in used_positions:
            continue  # never stack two markers at the same block-level position
        used_positions.add(position)
        marks.append(SeparateOverlayMark(
            sap_page_id=anchor.sap_page_id, page_number=page.page_number,
            target_label=target.target_label, kind=kind, text_value=text, x=x, y=y))
    return marks


def sync_separate_mode_overlays(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> int:
    """Create/refresh one editable overlay row per drawn separate-paper marker
    so the EXISTING overlay editor can move, hide and restore it. A teacher's
    manual move and hidden flag survive a refresh; the symbol always follows
    the effective status (there is no visual-only override)."""
    _owned(conn, teacher_id, profile_id, answer_file_id)
    prior = {o.target_label: o for o in spm.get_overlays_for_answer_file(conn, answer_file_id)
             if o.target_label is not None}
    pages = {p.sap_page_id: p for p in sap.get_separate_pages(conn, answer_file_id)}
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    kept = set()
    written = 0

    for target in list_required_targets(conn, teacher_id, profile_id, answer_file_id):
        if target.target_label == PART3_SELECTED_QUESTION_TARGET:
            continue
        anchor = target_marker_anchor(conn, answer_file_id, target)
        page = pages.get(anchor.sap_page_id) if anchor else None
        if anchor is None or page is None:
            continue
        kind, text = _marker_for_target(conn, answer_file_id, target, marked_by_label)
        if kind is None:
            continue
        default_x = min(0.96, anchor.x + anchor.width + 0.005)
        default_y = anchor.y
        existing = prior.get(target.target_label)
        if existing is None:
            spm.add_overlay(conn, answer_file_id, kind, page.page_number, default_x, default_y,
                            text_value=text, target_label=target.target_label)
        else:
            conn.execute(
                "UPDATE subject_profile_overlays SET kind = ?, text_value = ?, page_number = ?, "
                "original_x = ?, original_y = ?, x = CASE WHEN is_teacher_adjusted = 1 THEN x ELSE ? END, "
                "y = CASE WHEN is_teacher_adjusted = 1 THEN y ELSE ? END WHERE overlay_id = ?",
                (kind, text, page.page_number, default_x, default_y, default_x, default_y,
                 existing.overlay_id))
            conn.commit()
        kept.add(target.target_label)
        written += 1

    # Drop stale markers whose target no longer resolves to an anchor/status.
    for label, overlay in prior.items():
        if label not in kept:
            spm.delete_overlay(conn, overlay.overlay_id)
    return written


def _effective_result(marked) -> Tuple[Optional[str], Optional[float]]:
    """(status word, score) for one marked answer using its EFFECTIVE values -
    the teacher's decision where one exists, otherwise the machine result -
    exactly as standard mode resolves them."""
    if marked is None:
        return None, None
    status = marked.effective_status
    score = marked.effective_score
    if status == spm.TEACHER_STATUS_CORRECT:
        return "correct", score
    if status == spm.TEACHER_STATUS_WRONG:
        return "wrong", score
    if status in (spm.TEACHER_STATUS_TEACHER_SCORED,):
        return "scored", score
    if status == spm.MARKED_ANSWER_STATUS_MARKED:
        return ("correct" if marked.is_correct else "wrong"), score
    if status in (spm.TEACHER_STATUS_PENDING_TEACHER_SCORE,
                  spm.MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE):
        return ("scored" if score is not None else "pending"), score
    return "unresolved", score


def _marker_for_target(conn, answer_file_id: int, target: RequiredTarget,
                       marked_by_label: Dict[str, object]) -> Tuple[Optional[str], Optional[str]]:
    """Marker from the reviewed result, mirroring standard mode."""
    # A confirmed blank has no correct/wrong outcome to show. Drawing a cross
    # would contradict the "(left blank)" line in the student comments, so an
    # explicitly-blank target gets NO status marker (comments and PDF agree).
    if target.state == sap.TARGET_STATE_EXPLICITLY_BLANK:
        return None, None
    marked = marked_by_label.get(target.target_label)
    kind, score = _effective_result(marked)
    if kind == "correct":
        return "tick", None
    if kind == "wrong":
        return "cross", None
    if kind == "scored":
        return "percentage", f"{score if score is not None else 0:g}/{marked.max_score:g}"
    if kind is not None:
        return "percentage", "?"
    if target.state == sap.TARGET_STATE_UNRESOLVED:
        return "percentage", "?"
    return None, None


def render_separate_marked_pdf(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                               out_path) -> str:
    """Build the marked PDF for a separate-paper attempt: the SEPARATE ANSWER
    PAPER is the background (its pages in teacher order), with markers drawn
    from attempt mappings only. Returns the written path."""
    import pymupdf
    _owned(conn, teacher_id, profile_id, answer_file_id)
    pages = sap.get_separate_pages(conn, answer_file_id)
    if not pages:
        raise ValueError("This separate-paper attempt has no pages to render.")
    marks_by_page: Dict[int, List[SeparateOverlayMark]] = {}
    for mark in build_separate_overlay_marks(conn, teacher_id, profile_id, answer_file_id):
        marks_by_page.setdefault(mark.sap_page_id, []).append(mark)

    document = pymupdf.open()
    try:
        for page in pages:
            source = Path(page.source_file_path)
            if not source.is_file():
                raise ValueError(f"Separate answer paper file is missing: {source.name}")
            if page.source_kind == sap.SOURCE_KIND_PDF:
                with pymupdf.open(str(source)) as src:
                    document.insert_pdf(src, from_page=page.source_page_index,
                                        to_page=page.source_page_index)
                target_page = document[-1]
            else:
                pix = pymupdf.Pixmap(str(source))
                target_page = document.new_page(width=pix.width, height=pix.height)
                target_page.insert_image(target_page.rect, filename=str(source))
            rect = target_page.rect
            red = (1, 0, 0)
            for mark in marks_by_page.get(page.sap_page_id, []):
                cx, cy = mark.x * rect.width, mark.y * rect.height
                w = h = 0.03 * rect.width
                if mark.kind == "tick":
                    target_page.draw_line(pymupdf.Point(cx, cy + h * 0.5),
                                          pymupdf.Point(cx + w * 0.4, cy + h), color=red, width=2)
                    target_page.draw_line(pymupdf.Point(cx + w * 0.4, cy + h),
                                          pymupdf.Point(cx + w, cy), color=red, width=2)
                elif mark.kind == "cross":
                    target_page.draw_line(pymupdf.Point(cx, cy), pymupdf.Point(cx + w, cy + h),
                                          color=red, width=2)
                    target_page.draw_line(pymupdf.Point(cx, cy + h), pymupdf.Point(cx + w, cy),
                                          color=red, width=2)
                else:
                    target_page.insert_text(pymupdf.Point(cx, cy + h * 0.7), mark.text_value or "?",
                                            color=red, fontsize=14)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        document.save(str(out_path))
    finally:
        document.close()
    return str(out_path)


def build_separate_student_comments(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                                    *, finalised: bool = False) -> str:
    """Student-facing comments for a separate-paper attempt: final reviewed
    answers, scores, feedback and the confirmed Part 3 question. Excludes OCR
    lineage, parser internals, geometry, checksums, confidence, stale flags,
    private comments, audit data and database ids."""
    from app.services.subject_profile_review_service import kertas2_part_label
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    part3_question = get_part3_selected_question(conn, answer_file_id)
    lines: List[str] = []
    if finalised:
        lines.append("FINAL RESULT (teacher-reviewed, separate answer paper)")
        lines.append("")

    for target in list_required_targets(conn, teacher_id, profile_id, answer_file_id):
        if target.target_label == PART3_SELECTED_QUESTION_TARGET:
            continue
        marked = marked_by_label.get(target.target_label)
        feedback = (marked.teacher_feedback or "") if marked is not None else ""
        if target.paper == "Kertas 1":
            answer, _source = resolve_k1_answer(conn, answer_file_id, target.target_label,
                                                target.question_no)
            kind, value = _effective_result(marked)
            if target.state == sap.TARGET_STATE_EXPLICITLY_BLANK:
                shown, status = "(left blank)", "Blank"
            else:
                shown = answer if answer else "(none)"
                status = {"correct": "Correct", "wrong": "Wrong"}.get(kind, "Reviewed")
            score = (f"{value:g}/{target.max_score:g}" if value is not None
                     else f"-/{target.max_score:g}")
            line = f"{target.display_label}: [{status}] {score} | Answer: {shown}"
        else:
            label = kertas2_part_label(target.target_label, part3_question)
            text = assemble_k2_text(conn, answer_file_id, target.target_label)
            if target.state == sap.TARGET_STATE_EXPLICITLY_BLANK:
                text = "(left blank)"
            _kind, value = _effective_result(marked)
            score = (f"{value:g}/{target.max_score:g}" if value is not None
                     else f"Pending/{target.max_score:g}")
            status = "Teacher Scored" if value is not None else "Pending Teacher Score"
            line = f"{label}: [{status}] {score} | Answer: {text or '(none)'}"
        if feedback:
            line += f" | {feedback}"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")
