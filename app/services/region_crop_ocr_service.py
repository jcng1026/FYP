"""Region-crop OCR fast path for student marking (Stage 11Y, Stage 11Y-Fix).

Problem this solves: the old student-marking flow ran full-page OCR on
EVERY page of EVERY student's PDF (main_marking_service.run_ocr_for_session),
even though a Subject Profile usually only cares about a handful of small
answer regions per page. Stage 11Y first replaced the full-page OCR call
with per-region crop OCR, but still rendered every page of the student PDF
up front (main_marking_service.run_preprocessing_for_session) before
cropping from those rendered images - for an 11-page paper with a single
answer region, that meant ~19s of full-page rendering to extract ~1 crop.

Stage 11Y-Fix: crops are now rendered DIRECTLY from the student PDF via
PyMuPDF's clip-rendering (page.get_pixmap(matrix=..., clip=...)), which only
rasterizes the small clipped rectangle, not the whole page - see
render_region_crop_from_pdf. Only pages that actually contain an OCR-needed
region are ever touched; a page holding only skipped region types (question_
area, question_number_box, ignore_region, student_info_area,
extra_page_label, bubble_area) is never rendered at all. Full-page rendering
(needed only for the Marking Editor's page-by-page preview) is a completely
separate, deferred concern - see
app.services.subject_profile_service.ensure_full_page_render_for_answer_file,
which is only called when a teacher actually opens the Marking Editor, never
during upload/extraction.

Region filtering (classify_region_for_ocr):
- ignore_region: always excluded.
- question_area: holds the question text, not a student/scheme answer -
  never OCR'd during student marking.
- question_number_box: a structural tick/X anchor only, never OCR'd for
  text content - whether or not it is linked to an answer via a region
  group (matches list_subject_profile_extraction_targets/
  NON_ANSWER_REGION_TYPES, which already excludes it from extraction
  targets entirely); the skip reason text distinguishes "grouped" vs
  "ungrouped" for clearer logs, per the Stage 11Y spec's wording.
- bubble_area: MCQ/circle answers need shape/mark detection, not text
  OCR - left as an explicit image-detection placeholder (never full-page
  OCR'd) until that is implemented.
- answer_region, answer_box, underline_answer, letter_box: OCR-needed.

Coordinate handling reuses region_detection_dataset_service's already-
tested rotation-aware enclosing-bbox helpers (_compute_enclosing_bbox/
_clamp_to_unit_bbox) rather than duplicating that geometry - both take
any region-like object exposing x/y/width/height/rotation_angle/
shape_type/polygon_points_json, which SubjectProfileRegion already
satisfies. The normalized bbox is converted to a PDF-point-space Rect using
the page's own page.rect (PyMuPDF's 72-dpi point space) and rendered at
document_preprocessing.PDF_RENDER_DPI via a zoom Matrix, then run through
the same preprocess_page_image (CLAHE/denoise/threshold) helper the old
full-page flow used, so OCR quality is unchanged - only the (much larger)
full-page rasterization step is skipped.

Caching: a stable key (student PDF content hash + profile_id + page_number
+ region_id + region geometry/rotation) lets a second run against the same
student PDF and Subject Profile reuse previous crop OCR text instead of
OCRing (or even rendering) again - see compute_crop_cache_key/
load_crop_ocr_cache/save_crop_ocr_cache. Region geometry is included in the
key so an edited region's cache entries naturally miss instead of returning
stale text. The cache is checked BEFORE the student PDF is ever opened, so
a fully cache-hit run never opens or renders the PDF at all.

OCR engine reuse: LazyOCREngine defers get_default_engine() until the
first crop that actually needs real OCR (a cache/skip-only run creates no
engine at all), and remembers it for the rest of the run. The student PDF
itself is opened at most once per run_region_crop_ocr call (lazily, only
on the first actual cache-miss render) and reused/closed at the end -
never reopened per region.
"""

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2
import numpy as np
import pymupdf

from app.models.subject_profile_model import (
    REGION_TYPE_ANSWER_BOX,
    REGION_TYPE_ANSWER_REGION,
    REGION_TYPE_BUBBLE_AREA,
    REGION_TYPE_EXTRA_PAGE_LABEL,
    REGION_TYPE_IGNORE,
    REGION_TYPE_LEGEND_OR_SELECTOR_TYPES,
    REGION_TYPE_LETTER_BOX,
    REGION_TYPE_QUESTION_AREA,
    REGION_TYPE_QUESTION_NUMBER_BOX,
    REGION_TYPE_STUDENT_INFO_AREA,
    REGION_TYPE_UNDERLINE_ANSWER,
    extract_question_number_from_label,
)
from app.services.bubble_detection_service import locate_selected_mark, mask_out_selection_mark
from app.services.region_geometry_service import clamp_to_unit_bbox as _clamp_to_unit_bbox
from app.services.region_geometry_service import compute_enclosing_bbox as _compute_enclosing_bbox
from app.utils.document_preprocessing import PDF_RENDER_DPI, preprocess_page_image
from app.utils.file_storage import get_region_crop_ocr_cache_folder

# Marking Fix: a crop smaller than this (in its shorter dimension) is
# upscaled before OCR - a small letter_box/underline_answer region rendered
# at the normal page DPI can be under 50px tall, too small for reliable
# single-character/short-answer OCR. Cubic interpolation gives a smoother
# upscale than the default (nearest-neighbour-ish) resize for this case.
MIN_CROP_DIMENSION_PX = 120

# A small sub-crop around a detected MCQ selection mark, used only to OCR
# the single letter it encircles - padded a bit beyond the mark's own
# bounding box so the printed letter (not just the ring around it) is
# fully included.
MARK_LETTER_CROP_PADDING_RATIO = 0.5
MIN_MARK_LETTER_CROP_PADDING_PX = 6

# Marking Output Fix: a MUCH smaller vertical padding than the horizontal
# one - confirmed necessary against profile_16's real qp_p7_q20_choices,
# where the (correctly detected) mark around "B" used the same generous
# 50%-of-mark-height/6px-floor padding as the horizontal side and ended up
# reaching all the way up into the ADJACENT option's own letter ("A",
# printed just one tightly-spaced row above), so _extract_single_letter's
# "first alphabetic character" picked "A" - a real, confirmed selection of
# "B" scored as Wrong. Real MCQ option rows sit close enough together that
# even the previous 6px floor was already borderline (letter OCR read
# stray noise alongside the correct letter); empirically, 0-4px of extra
# vertical margin reads the target letter cleanly every time, while 8px+
# starts pulling in the neighbouring row - unlike the horizontal direction,
# where there is only ever one column of choices, so no equivalent risk.
MARK_LETTER_CROP_VERTICAL_PADDING_RATIO = 0.08
MIN_MARK_LETTER_CROP_VERTICAL_PADDING_PX = 3

# Marking Determinism Fix (requirements 2-4): the DECISION that an option
# was selected is made purely by deterministic image analysis (blue-ink
# connected-component detection - see bubble_detection_service.locate_
# selected_mark); OCR is used ONLY to read WHICH printed letter the found
# mark encircles, never to decide whether a mark exists. On top of that,
# this is a deterministic confidence floor on that single-letter read: if
# the recognizer's own confidence for the letter is below it, the answer
# is classified as Needs Review (a stable, repeatable outcome for the same
# crop) rather than trusting a shaky read - so a borderline/ambiguous mark
# is CONSISTENTLY flagged for teacher review instead of sometimes scoring
# Correct/Wrong. Set low (0.50) so it only rejects genuinely-unreadable
# glyphs: every real selected letter in the reference FC068024 KM2 student
# answer read at >= 0.61 confidence, so no confidently-legible answer is
# ever downgraded by this floor.
BUBBLE_LETTER_MIN_CONFIDENCE = 0.50

OCR_NEEDED_REGION_TYPES = (
    REGION_TYPE_ANSWER_REGION, REGION_TYPE_ANSWER_BOX, REGION_TYPE_UNDERLINE_ANSWER, REGION_TYPE_LETTER_BOX,
)

BUBBLE_AREA_PLACEHOLDER_NOTE = (
    "bubble_area holds an MCQ/circle answer, which needs shape/mark detection, not text OCR - left as an "
    "image-detection placeholder until that is implemented; not OCR'd."
)

STATUS_OCRED = "ocred"
STATUS_CACHED = "cached"
STATUS_SKIPPED = "skipped"


@dataclass
class RegionCropOcrResult:
    profile_id: int
    answer_file_id: Optional[int]
    page_number: int
    region_id: int
    region_type: str
    group_id: Optional[int]
    question_no: Optional[str]
    crop_path: Optional[str]
    extracted_text: Optional[str]
    confidence: Optional[float]
    timing_ms: float
    status: str
    skip_reason: Optional[str] = None
    render_time_ms: float = 0.0
    ocr_time_ms: float = 0.0
    # Marking Fix: True when this region WAS actively processed (rendered
    # and analyzed - not structurally STATUS_SKIPPED) but the result is
    # uncertain and should be flagged for teacher review rather than
    # trusted outright - e.g. an MCQ bubble_area with no clear selection
    # mark, or more than one competing candidate mark.
    needs_review: bool = False


class LazyOCREngine:
    """Defers engine resolution until first actually needed, then reuses
    the same instance for the rest of the run - see module docstring.

    Pass an already-resolved engine (e.g. an injected fake for tests, or
    one already created earlier in a batch) via engine= to skip lazy
    resolution entirely. Otherwise pass resolver= - a zero-arg callable
    returning an OCREngine - so the CALLER controls exactly which
    get_default_engine binding is used (subject_profile_service.py passes
    its own module-level get_default_engine import here, which is what
    existing tests already monkeypatch; resolving app.utils.ocr_engine.
    get_default_engine directly here instead would silently bypass that
    monkeypatch, since "from X import Y" bindings are per-module - see
    app/services/k2_prediction_service.py's docstring for the same
    lesson learned in Stage 12D). Falls back to app.utils.ocr_engine.
    get_default_engine only if no resolver was given either."""

    def __init__(self, engine=None, resolver: Optional[Callable[[], object]] = None) -> None:
        self._engine = engine
        self._resolver = resolver
        self.was_created = engine is not None

    def get(self):
        if self._engine is None:
            if self._resolver is not None:
                self._engine = self._resolver()
            else:
                from app.utils.ocr_engine import get_default_engine
                self._engine = get_default_engine()
            self.was_created = True
        return self._engine


def _extract_single_letter(raw_text: Optional[str]) -> Optional[str]:
    """The first alphabetic character in raw_text, uppercased - tolerates
    stray whitespace/punctuation OCR sometimes returns around a single
    circled letter. Returns None if raw_text has no alphabetic character
    at all (OCR found nothing legible)."""
    if not raw_text:
        return None
    for character in raw_text:
        if character.isalpha():
            return character.upper()
    return None


def classify_region_for_ocr(region, region_id_to_group_id: Dict[int, int]) -> "tuple[bool, Optional[str]]":
    """Return (needs_ocr, skip_reason) - skip_reason is None iff needs_ocr
    is True. Never raises for an unrecognized region_type - defensively
    skips it with a clear reason instead."""
    if region.region_type == REGION_TYPE_IGNORE:
        return False, "ignore_region is always excluded from OCR/extraction."
    if region.region_type == REGION_TYPE_QUESTION_AREA:
        return False, "question_area holds the question text, not a student/scheme answer - not OCR'd during student marking."
    if region.region_type == REGION_TYPE_QUESTION_NUMBER_BOX:
        if region.region_id in region_id_to_group_id:
            return False, "question_number_box is already linked to its answer via a region group - not OCR'd separately."
        return False, "question_number_box is a structural anchor (tick/X placement only) - never OCR'd for text."
    if region.region_type == REGION_TYPE_BUBBLE_AREA:
        return False, BUBBLE_AREA_PLACEHOLDER_NOTE
    if region.region_type in (REGION_TYPE_STUDENT_INFO_AREA, REGION_TYPE_EXTRA_PAGE_LABEL):
        return False, f"{region.region_type} does not hold gradable answer content - not OCR'd."
    if region.region_type in OCR_NEEDED_REGION_TYPES:
        return True, None
    return False, f"Unrecognized region type {region.region_type!r} - not OCR'd."


def compute_file_hash(file_path: str) -> Optional[str]:
    """Stable content hash of file_path (e.g. a student's uploaded PDF),
    used as part of the crop OCR cache key so re-uploading the identical
    file reuses cached results. Returns None (never raises) if the file
    can't be read - callers should treat that as "caching unavailable for
    this run", not an error."""
    try:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def compute_crop_cache_key(student_pdf_hash: str, profile_id: int, region) -> str:
    """Deterministic cache key covering everything that should invalidate
    a cached crop OCR result: which student file, which Subject Profile,
    which page, which region, and that region's own geometry/rotation (so
    an edited/moved region's old cache entry is naturally never reused)."""
    raw = (
        f"{student_pdf_hash}:{profile_id}:{region.page_number}:{region.region_id}:"
        f"{region.x}:{region.y}:{region.width}:{region.height}:{region.rotation_angle}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_crop_ocr_cache(teacher_id: int, profile_id: int) -> dict:
    """Load the persistent crop-OCR cache for this teacher/profile (a flat
    dict of cache_key -> {"extracted_text", "confidence", "region_type"}).
    Returns {} (never raises) if no cache file exists yet or it's
    unreadable/corrupt - a cache miss is always safe, just slower."""
    cache_path = get_region_crop_ocr_cache_folder(teacher_id, profile_id) / "cache.json"
    if not cache_path.is_file():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_crop_ocr_cache(teacher_id: int, profile_id: int, cache: dict) -> None:
    cache_path = get_region_crop_ocr_cache_folder(teacher_id, profile_id) / "cache.json"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")


def _upscale_if_small(image: np.ndarray) -> np.ndarray:
    """Marking Fix: a small letter_box/underline_answer region can render
    under MIN_CROP_DIMENSION_PX tall/wide at the normal page DPI - too
    small for reliable single-character/short-answer OCR. Upscales
    (cubic interpolation) so the shorter side is at least that big;
    a no-op if the crop is already large enough."""
    height, width = image.shape[:2]
    smaller_dim = min(height, width)
    if smaller_dim <= 0 or smaller_dim >= MIN_CROP_DIMENSION_PX:
        return image
    scale = MIN_CROP_DIMENSION_PX / smaller_dim
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_CUBIC)


def _render_raw_region_crop(document: "pymupdf.Document", region) -> Optional[np.ndarray]:
    """Render region's own area directly from document (an already-open
    PyMuPDF document over the student's original PDF) at OCR-suitable DPI,
    WITHOUT rasterizing the rest of the page - PyMuPDF's clip= parameter to
    get_pixmap only rasterizes the clipped rectangle, so this is dramatically
    cheaper than rendering the whole page first and cropping afterwards
    (the Stage 11Y approach). Returns a raw BGR crop (upscaled if small -
    see _upscale_if_small), or None (never raises) if region.page_number is
    out of range or its bbox is degenerate/off-page. Shared by both the
    text-OCR path (render_region_crop_from_pdf, which preprocesses this
    further) and the MCQ mark-detection path (render_region_crop_color_
    from_pdf, which needs the RAW COLOR - see bubble_detection_service)."""
    page_index = region.page_number - 1
    if page_index < 0 or page_index >= document.page_count:
        return None

    bbox = _compute_enclosing_bbox(region)
    if bbox is None:
        return None
    clamped = _clamp_to_unit_bbox(*bbox)
    if clamped is None:
        return None
    x0, y0, width, height = clamped

    if getattr(region, "region_type", None) in (REGION_TYPE_LETTER_BOX, REGION_TYPE_UNDERLINE_ANSWER):
        # Marking Fix Follow-up: real letter_box/underline_answer regions
        # for this kind of "matching"/fill-in question are routinely drawn
        # a little short or a little low relative to where the student's
        # handwritten/typed letter actually sits (confirmed against
        # profile_14's real Q30/Q34-Q36 - the stored bbox only grazed the
        # answer box's top border, or sat right at the printed underline
        # while the answer itself was written in the blank space ABOVE it)
        # - a plain crop then renders blank and OCR finds nothing. Padding
        # generously upward (most of the miss is in that direction) with a
        # little slack on the other sides recovers the actual ink without
        # needing to touch the stored region geometry itself. See the
        # matching "last non-empty OCR line wins" pickup in
        # run_region_crop_ocr, which keeps this safe against pulling in a
        # neighbouring row's answer.
        top_pad = min(height * 2.2, 0.03)
        bottom_pad = height * 0.8
        side_pad = width * 0.15
        y0 = max(0.0, y0 - top_pad)
        height = min(1.0 - y0, height + top_pad + bottom_pad)
        x0 = max(0.0, x0 - side_pad)
        width = min(1.0 - x0, width + side_pad * 2)
    elif getattr(region, "region_type", None) in (REGION_TYPE_ANSWER_BOX, REGION_TYPE_ANSWER_REGION):
        # Marking Fix Follow-up: a Kertas 2 (Paper 2) writing answer_box's
        # own bbox routinely has student text starting right at (or a
        # pixel or two inside) its left edge - confirmed against
        # profile_14's real Q2/Part 3 boxes, where PaddleOCR's text
        # detection then clips the first character or two of EVERY line
        # ("against"->"ainst", "created"->"eated", "pollution"->"llution",
        # "A Taste of Home"->"e of Home") even though the raw rendered
        # crop visibly contains the full text - a documented behavior for
        # text sitting flush against a crop's edge, not a stored-geometry
        # problem. A small left margin (giving the detector a buffer
        # before the real text starts) fixed every case tried; a little
        # top padding too since the first line can be just as tight
        # vertically. Deliberately modest and NOT applied to the right/
        # bottom - the box's own far edges already have blank margin in
        # every real case seen, and over-padding there risks pulling in
        # unrelated prompt text below/beside the box.
        #
        # Marking Fix Follow-up 3: the answer scheme's own answer_region
        # blocks (used to auto-extract the Kertas 1 answer key - see
        # extract_answer_key_from_answer_scheme) are the SAME kind of
        # tall, multi-line text block as an answer_box, and were found to
        # suffer the identical edge-clipping ("28."->"8.", "30."->"0.")
        # confirmed against profile_14's real answer scheme - so they get
        # the same treatment here.
        left_pad = width * 0.05
        top_pad = height * 0.02
        x0 = max(0.0, x0 - left_pad)
        y0 = max(0.0, y0 - top_pad)
        width = min(1.0 - x0, width + left_pad)
        height = min(1.0 - y0, height + top_pad)

    return _render_clip_from_page(document[page_index], x0, y0, width, height)


def _render_clip_from_page(page: "pymupdf.Page", x0: float, y0: float, width: float, height: float) -> Optional[np.ndarray]:
    """Render one normalized-fraction (x0, y0, width, height) rectangle of
    page directly (PyMuPDF clip-rendering - see _render_raw_region_crop's
    docstring for why), returning a raw BGR crop upscaled if small, or None
    (never raises) for a degenerate/empty rect. Shared by _render_raw_
    region_crop and render_answer_box_title_crop (Marking Fix Follow-up),
    which each compute their own fractional rect but need the identical
    render/color-convert/upscale steps."""
    rect = page.rect
    clip = pymupdf.Rect(
        x0 * rect.width, y0 * rect.height,
        (x0 + width) * rect.width, (y0 + height) * rect.height,
    )
    if clip.width <= 0 or clip.height <= 0:
        return None

    zoom = PDF_RENDER_DPI / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, clip=clip)
    if pixmap.width <= 0 or pixmap.height <= 0:
        return None

    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    if pixmap.n == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    elif pixmap.n == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    return _upscale_if_small(image)


# Marking Fix Follow-up: how much of an answer_box's own height is treated
# as a separate "title" sub-crop - see render_answer_box_title_crop.
ANSWER_BOX_TITLE_ZONE_HEIGHT_FRACTION = 0.09


def _mask_out_other_regions(
    image: np.ndarray, crop_x0: float, crop_y0: float, crop_width: float, crop_height: float, mask_regions: list,
) -> None:
    """Marking Output Fix: white-fill (in place) any part of image that
    falls inside another already-defined region's own bbox - used so
    render_answer_box_title_crop's extended look-above zone can safely
    reach past an answer_box's own stored top edge (to recover a
    handwritten first line that starts above it) without risking picking
    up a NEIGHBOURING region's own printed content instead (a prompt's
    last instructional line, a question-number selector field's value) -
    confirmed necessary against profile_16's real qp_p13_q1_answer_box
    ("Write your answer below." bled in from the adjacent qp_p13_q1_prompt
    region) and qp_p16_part3_answer_box ("Question Number: 4" bled in from
    qp_p16_question_number_field, which sits just above/overlapping it).
    mask_regions is expected to already exclude the target region itself
    and any region from a different page."""
    if not mask_regions:
        return
    img_height, img_width = image.shape[:2]
    if img_height <= 0 or img_width <= 0 or crop_width <= 0 or crop_height <= 0:
        return
    for other in mask_regions:
        bbox = _compute_enclosing_bbox(other)
        if bbox is None:
            continue
        clamped = _clamp_to_unit_bbox(*bbox)
        if clamped is None:
            continue
        ox0, oy0, owidth, oheight = clamped
        ix0 = max(ox0, crop_x0)
        iy0 = max(oy0, crop_y0)
        ix1 = min(ox0 + owidth, crop_x0 + crop_width)
        iy1 = min(oy0 + oheight, crop_y0 + crop_height)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        px0 = int((ix0 - crop_x0) / crop_width * img_width)
        px1 = int((ix1 - crop_x0) / crop_width * img_width)
        py0 = int((iy0 - crop_y0) / crop_height * img_height)
        py1 = int((iy1 - crop_y0) / crop_height * img_height)
        cv2.rectangle(image, (px0, py0), (px1, py1), (255, 255, 255), thickness=-1)


# Marking Output Fix: known non-answer boilerplate that an answer_box's
# extended look-above zone can pick up alongside (or instead of) the real
# missing first line - confirmed against profile_16's real qp_p13_q1_
# answer_box ("Write your answer below." bled in cleanly, no OCR garbling,
# from the adjacent qp_p13_q1_prompt instruction block, which is a
# question_area and therefore deliberately never masked - see
# render_answer_box_title_crop). A residual question-number-selector
# label (e.g. "Question Number:") is normally already removed by masking
# (see REGION_TYPE_LEGEND_OR_SELECTOR_TYPES), so this is defense-in-depth
# for that case too.
_ANSWER_BOX_TITLE_BOILERPLATE_PHRASES = (
    "write your answer", "write your essay", "in the space provided", "question number",
)


def _strip_boilerplate_title_lines(title_text: str) -> str:
    """Drop any line of title_text that looks like non-answer boilerplate
    rather than genuine essay content - see _ANSWER_BOX_TITLE_BOILERPLATE_
    PHRASES. Never raises; "" in, "" out."""
    kept_lines = []
    for line in title_text.split("\n"):
        normalized = line.strip().lower()
        if not normalized:
            continue
        if any(phrase in normalized for phrase in _ANSWER_BOX_TITLE_BOILERPLATE_PHRASES):
            continue
        kept_lines.append(line.strip())
    return "\n".join(kept_lines)


def _trim_title_text_overlap_with_body(title_text: str, body_text: str) -> str:
    """Marking Output Fix: the title crop's taller reach (see render_
    answer_box_title_crop's top_pad increase) now often captures several
    real lines, not just one - including some that the MAIN crop's own
    OCR already read too (confirmed against profile_16's real
    qp_p14_q2_answer_box: the title crop's last 2 lines duplicated the
    body's own first 2 lines verbatim). Keep only the title's lines BEFORE
    the point where a line's first word matches the body's own first
    line's first word - everything from that point on is presumed to be
    the same content the body crop already captured on its own. Never
    raises; returns title_text unchanged if body_text has no usable first
    line to anchor on."""
    body_lines = [line.strip() for line in body_text.split("\n") if line.strip()]
    if not body_lines:
        return title_text
    body_first_words = body_lines[0].lower().split()
    if not body_first_words:
        return title_text
    body_first_word = body_first_words[0]

    kept_lines = []
    for line in title_text.split("\n"):
        words = line.strip().lower().split()
        if words and words[0] == body_first_word:
            break
        kept_lines.append(line)
    return "\n".join(kept_lines)


def render_answer_box_title_crop(
    document: "pymupdf.Document", region, mask_regions: Optional[list] = None,
) -> Optional[np.ndarray]:
    """Marking Fix Follow-up: a Kertas 2 answer_box's title/heading line was
    found to be silently dropped from OCR when read together with the rest
    of a tall, full-height essay crop - confirmed against profile_14's real
    Part 3 box ("A Taste of Home: OldTown White Coffee" went missing
    entirely from the extracted text, not just left-clipped), even though
    the SAME line reads perfectly when OCR'd alone as a small crop, and
    rendering the whole crop at double DPI didn't help either - so this
    isn't a resolution or left-edge-clipping problem, just PaddleOCR's
    detection missing small heading text within a much taller image.
    Rendering just the top slice of the region as its own small, separately
    OCR'd crop (see run_region_crop_ocr's REGION_TYPE_ANSWER_BOX branch,
    which prepends this to the main crop's own text) reliably recovers it
    without needing to alter the main crop's OCR path, which already
    correctly reads the body text below the title. Returns a preprocessed
    crop ready for OCR, or None (never raises) if it can't be rendered.

    Marking Output Fix: top_pad now reaches up to 3% of the page's own
    height (was a flat 2% of the region's OWN height, often under 1% of
    page height) - confirmed necessary against profile_16's real
    qp_p14_q2_answer_box, whose true first handwritten line ("Wildlife
    numbers in Malaysia have declined...") starts about 3% of the page
    above the region's stored top edge; the region itself was simply drawn
    a little low, exactly like the pre-existing letter_box/underline_
    answer "drawn a little short" case this same top_pad cap already
    handles (see _render_raw_region_crop). mask_regions (typically every
    OTHER region on this same page) is used to white out any of THEIR
    content that this larger reach would otherwise also pick up - see
    _mask_out_other_regions."""
    page_index = region.page_number - 1
    if page_index < 0 or page_index >= document.page_count:
        return None

    bbox = _compute_enclosing_bbox(region)
    if bbox is None:
        return None
    clamped = _clamp_to_unit_bbox(*bbox)
    if clamped is None:
        return None
    x0, y0, width, height = clamped

    left_pad = width * 0.05
    top_pad = min(height * 0.15, 0.03)
    title_height = height * ANSWER_BOX_TITLE_ZONE_HEIGHT_FRACTION
    x0 = max(0.0, x0 - left_pad)
    y0 = max(0.0, y0 - top_pad)
    width = min(1.0 - x0, width + left_pad)
    height = min(1.0 - y0, title_height + top_pad)

    image = _render_clip_from_page(document[page_index], x0, y0, width, height)
    if image is None:
        return None
    # Marking Output Fix: only mask a HELPER/SELECTOR region (legend/
    # options-list/question-number-selector - see REGION_TYPE_LEGEND_OR_
    # SELECTOR_TYPES) that has no derivable question number of its own -
    # confirmed against profile_16's real qp_p16_question_number_field
    # bleeding "Question Number: 4" into qp_p16_part3_answer_box's title
    # crop. Deliberately NEVER masks a question_area (prompt/instruction)
    # region - those are stored with generous internal padding that
    # doesn't tightly track their own printed text, so masking their full
    # bbox risks erasing genuine answer content that visually starts
    # within that loose padding (confirmed against profile_16's real
    # qp_p14_q2_answer_box, whose true first line sits inside qp_p14_q2_
    # prompt's own stored bbox despite not being prompt text at all).
    others = [
        r for r in (mask_regions or [])
        if r.region_id != region.region_id and r.page_number == region.page_number
        and r.region_type in REGION_TYPE_LEGEND_OR_SELECTOR_TYPES
        and extract_question_number_from_label(r.label) is None
    ]
    _mask_out_other_regions(image, x0, y0, width, height, others)
    return preprocess_page_image(image)


def render_region_crop_from_pdf(document: "pymupdf.Document", region) -> Optional[np.ndarray]:
    """Render region's own area (see _render_raw_region_crop) and return a
    preprocessed (CLAHE/denoise/threshold, via document_preprocessing.
    preprocess_page_image) binary crop ready for text OCR, or None (never
    raises) if the crop can't be rendered."""
    image = _render_raw_region_crop(document, region)
    if image is None:
        return None
    return preprocess_page_image(image)


# Marking Fix Follow-up 3: chunk height/overlap for ocr_tall_crop_in_chunks
# - tuned against profile_14's real ~1800px-tall answer-scheme block.
TALL_CROP_CHUNK_HEIGHT_PX = 500
TALL_CROP_CHUNK_OVERLAP_PX = 100


def ocr_tall_crop_in_chunks(crop_image: np.ndarray, engine) -> str:
    """OCR crop_image (an already-rendered, already-preprocessed image) in
    overlapping vertical chunks instead of one single call.

    PaddleOCR's detection was found to silently DROP entire lines (not
    just clip their edges) within a single very-tall crop - confirmed
    against profile_14's real ~1800px-tall answer-scheme "Part 2-4
    answers" block, where its first two lines (Q13/Q14) were missing
    from the result entirely, even after left/top edge padding already
    fixed the OTHER lines' clipped leading characters. Splitting into
    short, overlapping chunks and concatenating each chunk's own OCR text
    recovered every line reliably. Lines that fall in the overlap between
    two chunks get read (and returned) twice - harmless for a caller like
    parse_kertas1_answers_from_text that keys off content by dict, since
    a duplicate entry just gets written twice with the same value.
    A crop shorter than one chunk is OCR'd in a single call, unchanged
    from before."""
    height = crop_image.shape[0]
    if height <= TALL_CROP_CHUNK_HEIGHT_PX:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        cv2.imwrite(path, crop_image)
        try:
            return engine.run_page(path).text or ""
        finally:
            Path(path).unlink(missing_ok=True)

    lines: List[str] = []
    y = 0
    step = TALL_CROP_CHUNK_HEIGHT_PX - TALL_CROP_CHUNK_OVERLAP_PX
    while True:
        chunk = crop_image[y:min(height, y + TALL_CROP_CHUNK_HEIGHT_PX), :]
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        cv2.imwrite(path, chunk)
        try:
            chunk_text = engine.run_page(path).text or ""
        finally:
            Path(path).unlink(missing_ok=True)
        lines.extend(line for line in chunk_text.split("\n") if line.strip())
        if y + TALL_CROP_CHUNK_HEIGHT_PX >= height:
            break
        y += step
    return "\n".join(lines)


def render_region_crop_color_from_pdf(document: "pymupdf.Document", region) -> Optional[np.ndarray]:
    """Render region's own area (see _render_raw_region_crop) and return
    the RAW COLOR (BGR) crop, unpreprocessed - used only for bubble_area
    MCQ selection-mark detection (app.services.bubble_detection_service),
    which needs color, not a black/white-thresholded image. Returns None
    (never raises) if the crop can't be rendered."""
    return _render_raw_region_crop(document, region)


def run_region_crop_ocr(
    regions: list,
    pdf_path: Optional[str],
    profile_id: int,
    lazy_engine: LazyOCREngine,
    cache: dict,
    answer_file_id: Optional[int] = None,
    student_pdf_hash: Optional[str] = None,
    region_id_to_group_id: Optional[Dict[int, int]] = None,
    region_id_to_question_no: Optional[Dict[str, str]] = None,
    crop_save_dir: Optional[Path] = None,
    on_progress: Optional[Callable[[RegionCropOcrResult], None]] = None,
    on_render: Optional[Callable[[int], None]] = None,
    page_regions: Optional[list] = None,
) -> List[RegionCropOcrResult]:
    """Crop and OCR only the OCR-needed regions among regions, rendering
    each crop DIRECTLY from pdf_path (the student's original PDF) instead
    of from a pre-rendered full-page image - see render_region_crop_from_
    pdf. Never raises for an individual region's failure, always appends a
    result (status "skipped" with a reason) instead.

    pdf_path's document is opened at most once, lazily - only on the first
    region that is both OCR-needed AND not already cache-hit - so a fully
    cache-hit (or fully skip-only) run never touches the PDF at all.
    on_render(page_number), if given, is called right after a page's crop
    is rendered but before OCR starts (lets a caller show a distinct
    "rendering crop" progress message); on_progress(result) is called once
    per region after it's fully processed (rendered+OCR'd, cached, or
    skipped), same as Stage 11Y.

    page_regions (Marking Output Fix), if given, should be every region
    defined on the Subject Profile's question paper source (not just the
    ones in regions) - passed through to render_answer_box_title_crop for
    an answer_box target so its extended look-above zone can mask out any
    OTHER region (a prompt, a question-number field) it might otherwise
    also pick up. None (the default) disables masking entirely, matching
    the old behavior."""
    region_id_to_group_id = region_id_to_group_id or {}
    region_id_to_question_no = region_id_to_question_no or {}
    results: List[RegionCropOcrResult] = []
    document = None

    try:
        for region in regions:
            start = time.perf_counter()
            group_id = region_id_to_group_id.get(region.region_id)
            question_no = region_id_to_question_no.get(region.label)

            def _finish(
                status: str, skip_reason: Optional[str] = None, crop_path: Optional[str] = None,
                extracted_text: Optional[str] = None, confidence: Optional[float] = None,
                render_time_ms: float = 0.0, ocr_time_ms: float = 0.0, needs_review: bool = False,
            ) -> RegionCropOcrResult:
                result = RegionCropOcrResult(
                    profile_id=profile_id, answer_file_id=answer_file_id, page_number=region.page_number,
                    region_id=region.region_id, region_type=region.region_type, group_id=group_id,
                    question_no=question_no, crop_path=crop_path, extracted_text=extracted_text,
                    confidence=confidence, timing_ms=round((time.perf_counter() - start) * 1000, 3),
                    status=status, skip_reason=skip_reason,
                    render_time_ms=round(render_time_ms, 3), ocr_time_ms=round(ocr_time_ms, 3),
                    needs_review=needs_review,
                )
                results.append(result)
                if on_progress is not None:
                    on_progress(result)
                return result

            if region.region_type == REGION_TYPE_BUBBLE_AREA:
                cache_key = compute_crop_cache_key(student_pdf_hash, profile_id, region) if student_pdf_hash else None
                if cache_key and cache_key in cache:
                    cached = cache[cache_key]
                    _finish(
                        STATUS_CACHED, extracted_text=cached.get("extracted_text"), confidence=cached.get("confidence"),
                        needs_review=bool(cached.get("needs_review")),
                    )
                    continue

                if not pdf_path or not Path(pdf_path).is_file():
                    _finish(STATUS_SKIPPED, skip_reason="Student PDF not found - skipped safely.")
                    continue

                if document is None:
                    try:
                        document = pymupdf.open(pdf_path)
                    except Exception:
                        _finish(STATUS_SKIPPED, skip_reason="Could not open student PDF for crop rendering - skipped safely.")
                        continue

                if region.page_number < 1 or region.page_number - 1 >= document.page_count:
                    _finish(
                        STATUS_SKIPPED,
                        skip_reason=f"Page {region.page_number} not found in this document ({document.page_count} pages) - skipped safely.",
                    )
                    continue

                render_start = time.perf_counter()
                color_crop = render_region_crop_color_from_pdf(document, region)
                bubble_render_time_ms = (time.perf_counter() - render_start) * 1000
                if color_crop is None:
                    _finish(
                        STATUS_SKIPPED,
                        skip_reason="Could not render this region's crop (degenerate bbox) - skipped safely.",
                        render_time_ms=bubble_render_time_ms,
                    )
                    continue

                if on_render is not None:
                    on_render(region.page_number)

                bubble_crop_path = None
                if crop_save_dir is not None:
                    crop_save_dir_path = Path(crop_save_dir)
                    crop_save_dir_path.mkdir(parents=True, exist_ok=True)
                    bubble_crop_path = str(crop_save_dir_path / f"region_{region.region_id}_page_{region.page_number}.png")
                    cv2.imwrite(bubble_crop_path, color_crop)

                location = locate_selected_mark(color_crop)
                if not location.found:
                    if cache_key:
                        cache[cache_key] = {
                            "extracted_text": None, "confidence": None,
                            "region_type": region.region_type, "needs_review": True,
                        }
                    _finish(
                        STATUS_OCRED, crop_path=bubble_crop_path, extracted_text=None, confidence=None,
                        render_time_ms=bubble_render_time_ms, needs_review=True, skip_reason=location.reason,
                    )
                    continue

                mark_x, mark_y, mark_w, mark_h = location.bbox
                pad_x = max(MIN_MARK_LETTER_CROP_PADDING_PX, int(mark_w * MARK_LETTER_CROP_PADDING_RATIO))
                pad_y = max(MIN_MARK_LETTER_CROP_VERTICAL_PADDING_PX, int(mark_h * MARK_LETTER_CROP_VERTICAL_PADDING_RATIO))
                crop_height, crop_width = color_crop.shape[:2]
                letter_x0 = max(0, mark_x - pad_x)
                letter_y0 = max(0, mark_y - pad_y)
                letter_x1 = min(crop_width, mark_x + mark_w + pad_x)
                letter_y1 = min(crop_height, mark_y + mark_h + pad_y)
                # Marking Fix Follow-up: strip the blue ring before
                # preprocessing/OCR - see mask_out_selection_mark's
                # docstring for why the ring itself was confusing OCR into
                # misreading (or failing to read at all) an otherwise
                # perfectly legible circled letter.
                letter_sub_crop = mask_out_selection_mark(color_crop[letter_y0:letter_y1, letter_x0:letter_x1])
                letter_crop = _upscale_if_small(preprocess_page_image(letter_sub_crop))

                bubble_fd, bubble_temp_path = tempfile.mkstemp(suffix=".png")
                os.close(bubble_fd)
                cv2.imwrite(bubble_temp_path, letter_crop)
                bubble_engine = lazy_engine.get()
                bubble_ocr_start = time.perf_counter()
                try:
                    bubble_ocr_result = bubble_engine.run_page(bubble_temp_path)
                    raw_letter_text, letter_confidence = bubble_ocr_result.text, bubble_ocr_result.average_confidence
                finally:
                    bubble_ocr_time_ms = (time.perf_counter() - bubble_ocr_start) * 1000
                    Path(bubble_temp_path).unlink(missing_ok=True)

                selected_letter = _extract_single_letter(raw_letter_text)
                # Marking Determinism Fix: a low-confidence letter read is
                # treated as "unreadable" (Needs Review), not trusted - see
                # BUBBLE_LETTER_MIN_CONFIDENCE. This is a deterministic
                # decision for a given crop (same crop -> same confidence ->
                # same outcome), so a borderline glyph is CONSISTENTLY Needs
                # Review rather than flip-flopping between scored and flagged.
                low_confidence = (
                    letter_confidence is not None and letter_confidence < BUBBLE_LETTER_MIN_CONFIDENCE
                )
                if low_confidence:
                    selected_letter = None
                bubble_needs_review = selected_letter is None
                if bubble_needs_review and low_confidence:
                    bubble_skip_reason = (
                        "Selected-option mark found, but the circled letter could not be read confidently "
                        "- flagged for teacher review."
                    )
                elif bubble_needs_review:
                    bubble_skip_reason = (
                        "Could not read a clear letter from the detected selection mark - flagged for teacher review."
                    )
                else:
                    bubble_skip_reason = None
                if cache_key:
                    cache[cache_key] = {
                        "extracted_text": selected_letter, "confidence": letter_confidence,
                        "region_type": region.region_type, "needs_review": bubble_needs_review,
                    }
                _finish(
                    STATUS_OCRED, crop_path=bubble_crop_path, extracted_text=selected_letter, confidence=letter_confidence,
                    render_time_ms=bubble_render_time_ms, ocr_time_ms=bubble_ocr_time_ms, needs_review=bubble_needs_review,
                    skip_reason=bubble_skip_reason,
                )
                continue

            needs_ocr, skip_reason = classify_region_for_ocr(region, region_id_to_group_id)
            if not needs_ocr:
                _finish(STATUS_SKIPPED, skip_reason=skip_reason)
                continue

            cache_key = compute_crop_cache_key(student_pdf_hash, profile_id, region) if student_pdf_hash else None
            if cache_key and cache_key in cache:
                cached = cache[cache_key]
                _finish(STATUS_CACHED, extracted_text=cached.get("extracted_text"), confidence=cached.get("confidence"))
                continue

            if not pdf_path or not Path(pdf_path).is_file():
                _finish(STATUS_SKIPPED, skip_reason="Student PDF not found - skipped safely.")
                continue

            if document is None:
                try:
                    document = pymupdf.open(pdf_path)
                except Exception:
                    _finish(STATUS_SKIPPED, skip_reason="Could not open student PDF for crop rendering - skipped safely.")
                    continue

            if region.page_number < 1 or region.page_number - 1 >= document.page_count:
                _finish(
                    STATUS_SKIPPED,
                    skip_reason=f"Page {region.page_number} not found in this document ({document.page_count} pages) - skipped safely.",
                )
                continue

            render_start = time.perf_counter()
            crop = render_region_crop_from_pdf(document, region)
            render_time_ms = (time.perf_counter() - render_start) * 1000
            if crop is None:
                _finish(
                    STATUS_SKIPPED,
                    skip_reason="Could not render this region's crop (degenerate bbox) - skipped safely.",
                    render_time_ms=render_time_ms,
                )
                continue

            if on_render is not None:
                on_render(region.page_number)

            crop_path = None
            if crop_save_dir is not None:
                crop_save_dir_path = Path(crop_save_dir)
                crop_save_dir_path.mkdir(parents=True, exist_ok=True)
                crop_path = str(crop_save_dir_path / f"region_{region.region_id}_page_{region.page_number}.png")
                cv2.imwrite(crop_path, crop)

            if crop_path is None:
                # An OCR engine needs a real file path - even when the caller
                # doesn't want crops persisted long-term, still write one to a
                # throwaway location so run_page() has something to read.
                fd, temp_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                cv2.imwrite(temp_path, crop)
                ocr_image_path = temp_path
            else:
                ocr_image_path = crop_path

            engine = lazy_engine.get()
            ocr_start = time.perf_counter()
            try:
                ocr_result = engine.run_page(ocr_image_path)
                text, confidence = ocr_result.text, ocr_result.average_confidence
                if region.region_type in (REGION_TYPE_LETTER_BOX, REGION_TYPE_UNDERLINE_ANSWER):
                    # Marking Fix Follow-up: _render_raw_region_crop pads
                    # these crops generously UPWARD to recover answers
                    # written above a slightly-short/low region box - the
                    # real answer then reliably ends up as the LAST non-
                    # empty recognized line (closest to the crop's bottom,
                    # i.e. nearest the region's own original position),
                    # with any bled-in neighbouring-row text appearing in
                    # earlier lines. Falls back to the full text unchanged
                    # if there's only one line (the common, no-bleed case).
                    non_empty_lines = [line for line in text.split("\n") if line.strip()]
                    if non_empty_lines:
                        text = non_empty_lines[-1].strip()
                elif region.region_type == REGION_TYPE_ANSWER_BOX:
                    # Marking Fix Follow-up: the essay's title/heading line
                    # was found to be silently dropped by PaddleOCR's
                    # detection on the full-height crop (see
                    # render_answer_box_title_crop's docstring) - render
                    # and OCR it separately, then prepend it here, rather
                    # than trusting it to show up in the main crop's text.
                    # Not every answer_box has a distinct title zone though
                    # (a plain paragraph answer's own first line already
                    # starts right at the top) - only prepend when the
                    # title crop's content genuinely ISN'T already present
                    # in the body (a short, normalized prefix comparison:
                    # short enough that an occasional OCR letter-level
                    # misread deeper in the line - "hobitats" vs "habitats" -
                    # doesn't cause a false "not already covered").
                    title_crop = render_answer_box_title_crop(document, region, mask_regions=page_regions)
                    if title_crop is not None:
                        title_fd, title_temp_path = tempfile.mkstemp(suffix=".png")
                        os.close(title_fd)
                        cv2.imwrite(title_temp_path, title_crop)
                        try:
                            title_result = engine.run_page(title_temp_path)
                            title_text = (title_result.text or "").strip()
                        finally:
                            Path(title_temp_path).unlink(missing_ok=True)
                        title_text = _strip_boilerplate_title_lines(title_text)
                        title_text = _trim_title_text_overlap_with_body(title_text, text)
                        title_words = title_text.lower().split()
                        body_words = text.lower().split()
                        title_prefix = " ".join(title_words)[:20]
                        body_prefix = " ".join(body_words)[:80]
                        # A plain paragraph answer's real first line already
                        # starts at the top (no separate title at all) - the
                        # title-zone crop then just re-reads (a fragment of)
                        # that SAME first line, which a full 20-char prefix
                        # match won't always catch if the crop cut it short
                        # ("EMAIL\nTo: Mona" vs "EMAIL\nM") - but the very
                        # first WORD ("email") still reliably matches, so
                        # check that too before deciding this is a genuinely
                        # separate title worth prepending.
                        already_covered = bool(title_words) and bool(body_words) and title_words[0] == body_words[0]
                        already_covered = already_covered or (title_prefix and title_prefix in body_prefix)
                        if title_text and not already_covered:
                            text = f"{title_text}\n{text}" if text else title_text
            finally:
                ocr_time_ms = (time.perf_counter() - ocr_start) * 1000
                if crop_path is None:
                    Path(ocr_image_path).unlink(missing_ok=True)

            if cache_key:
                cache[cache_key] = {"extracted_text": text, "confidence": confidence, "region_type": region.region_type}
            _finish(
                STATUS_OCRED, crop_path=crop_path, extracted_text=text, confidence=confidence,
                render_time_ms=render_time_ms, ocr_time_ms=ocr_time_ms,
            )
    finally:
        if document is not None:
            document.close()

    return results
