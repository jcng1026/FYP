"""Document preprocessing pipeline: loads PDF/image files into page images
and applies basic, safe image cleanup (grayscale, contrast enhancement,
denoise, adaptive threshold) so the output is ready for later OCR and
template-alignment stages.

This module does not perform OCR, answer extraction, or marking - it only
produces cleaned page images. It has no database or Qt dependency, so it
can be used and tested standalone.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pymupdf

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp"}

PDF_RENDER_DPI = 200

# A digitally-generated PDF (e.g. an SPM workbook exported from a word
# processor/typesetting tool) embeds a real, exact text layer per page -
# PyMuPDF reads it directly, instantly, with no OCR engine involved at all.
# A scanned/photographed page has no such layer (get_text() returns "" or
# only a stray watermark/page-number fragment) and still needs OCR. This
# threshold distinguishes "real text layer" from noise - see Stage 12E-2-Fix.
MIN_TEXT_LAYER_LENGTH = 20


def is_supported_file(file_path: str) -> bool:
    """Return True if file_path has a supported extension (case-insensitive)."""
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS


def load_page_images(file_path: str) -> List[np.ndarray]:
    """Load file_path into a list of BGR page images (OpenCV arrays).

    PDF files are rendered page-by-page at PDF_RENDER_DPI. Image files
    (PNG/JPG/JPEG/BMP) are loaded as a single page.

    Raises ValueError if the file doesn't exist, isn't a supported type, or
    cannot be decoded/rendered.
    """
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")

    if suffix == ".pdf":
        return _load_pdf_pages(path)
    return [_load_image_page(path)]


def _load_pdf_pages(path: Path) -> List[np.ndarray]:
    images = []
    zoom = PDF_RENDER_DPI / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    with pymupdf.open(str(path)) as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=matrix)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            if pixmap.n == 4:
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            elif pixmap.n == 3:
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            else:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            images.append(image)

    if not images:
        raise ValueError("PDF has no pages.")
    return images


def get_pdf_page_count(file_path: str) -> Optional[int]:
    """Return the page count of a PDF file (Stage 11L), or None if it can't
    be determined - not a PDF, missing, or unreadable. Callers should treat
    None as "unknown" and handle it gracefully rather than assuming a page
    count. Uses pymupdf (already a dependency) - no new dependency added."""
    if Path(file_path).suffix.lower() != ".pdf":
        return None
    try:
        with pymupdf.open(file_path) as document:
            return document.page_count
    except Exception:
        return None


def extract_pdf_text_layer_pages(file_path: str) -> Dict[int, str]:
    """Return {page_number: text} (1-based) for every page of file_path
    (a PDF) whose PyMuPDF text extraction yields at least MIN_TEXT_LAYER_
    LENGTH non-whitespace characters - i.e. pages with a real embedded text
    layer, needing no OCR at all. A page below that threshold (typically a
    scanned/photographed page with no text layer, or a blank page) is
    simply omitted - callers should treat a missing page_number as "OCR
    still needed for this page", not an error.

    Stage 12E-2-Fix: this is the fix for a real native-process crash seen
    running PaddleOCR over real digitally-generated SPM workbook PDFs -
    those PDFs already have a full, exact text layer per page, so OCR was
    both unnecessary AND the actual crash risk. Preferring this text layer
    means OCR is only ever invoked for pages that genuinely need it (a true
    scanned page with no embedded text).

    Never raises - returns {} (meaning "no usable text layer detected
    anywhere", so every page falls back to OCR, matching the pre-Stage-
    12E-2-Fix behavior) for a missing/corrupt/unreadable file."""
    try:
        pages: Dict[int, str] = {}
        with pymupdf.open(file_path) as document:
            for page_number in range(1, document.page_count + 1):
                text = document[page_number - 1].get_text()
                if text and len(text.strip()) >= MIN_TEXT_LAYER_LENGTH:
                    pages[page_number] = text
        return pages
    except Exception:
        return {}


def _load_image_page(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image file: {path}")
    return image


def preprocess_page_image(image: np.ndarray) -> np.ndarray:
    """Apply basic, safe preprocessing to a single page image and return a
    clean binary image ready for later OCR/template alignment.

    Steps: grayscale -> contrast enhancement (CLAHE) -> denoise -> adaptive
    threshold. Deskew and perspective/border correction are intentionally
    left as TODOs - see notes below.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # TODO: auto-orientation / deskew. A generic implementation (e.g. Hough
    # line detection or minAreaRect on text contours) risks rotating clean
    # pages incorrectly without real scanned samples to validate against.
    # Revisit once we have a representative set of skewed submissions.

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast_enhanced = clahe.apply(gray)

    denoised = cv2.fastNlMeansDenoising(contrast_enhanced, h=10)

    binary = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10,
    )

    # TODO: page border detection / perspective correction / shadow
    # correction. Left as future work - risky to implement generically
    # without more real sample papers to validate against.

    return binary


def save_page_image(image: np.ndarray, output_path: Path) -> None:
    """Save image (an OpenCV array) as a PNG at output_path.

    Raises ValueError if the image cannot be written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    success = cv2.imwrite(str(output_path), image)
    if not success:
        raise ValueError(f"Failed to save processed page image to {output_path}")


# --- Stage 11I: ignore-region masking -------------------------------------
#
# These helpers use only cv2/numpy (already dependencies of this module) so
# no new dependency is needed. They accept any duck-typed region object with
# shape_type/x/y/width/height/polygon_points_json attributes - matching
# app.models.template_model.TemplateRegion - without importing it, keeping
# this module free of any app.models/database dependency.


def _region_polygon_points(region) -> List[Tuple[float, float]]:
    if not getattr(region, "polygon_points_json", None):
        return []
    return [(float(x), float(y)) for x, y in json.loads(region.polygon_points_json)]


# --- Stage 11J: manual per-region rotation geometry foundation --------------
#
# Rotation convention: positive rotation_angle is a CLOCKWISE rotation on
# screen, matching Qt's QGraphicsItem.setRotation() used by
# app/ui/template_canvas.py's overlay rendering - so a region's geometry
# helper here visually agrees with what the teacher sees in the Template
# Editor preview. Rotation is always performed in real pixel-aspect space
# (fractional coordinates are converted to pixels using the actual
# image_width/image_height *before* rotating), since a page's width and
# height are rarely equal - rotating directly in normalized 0-1 space would
# visually distort the angle.


def get_region_rotation_angle(region) -> float:
    """Return region's rotation_angle (Stage 11J), defaulting safely to 0.0
    for any region/object that predates rotation support or omits the
    attribute entirely."""
    return float(getattr(region, "rotation_angle", 0.0) or 0.0)


def compute_rotated_region_polygon(region, image_width: int, image_height: int) -> List[Tuple[int, int]]:
    """Return region's shape as a list of (x, y) pixel corner points with
    its rotation_angle applied around its own bounding-box center.

    A rectangle region becomes its 4 rotated corners; a polygon region
    becomes its stored polygon_points_json points rotated the same way.
    Returns the plain (unrotated) pixel corners unchanged if rotation_angle
    is 0 (or missing) - this is the shared geometry foundation for future
    rotated-region extraction/cropping, not a live extraction change."""
    if getattr(region, "shape_type", "rectangle") == "polygon" and getattr(region, "polygon_points_json", None):
        fractional_points = _region_polygon_points(region)
    else:
        x, y, w, h = region.x, region.y, region.width, region.height
        fractional_points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    pixel_points = [(px * image_width, py * image_height) for px, py in fractional_points]

    angle = get_region_rotation_angle(region)
    if angle == 0.0:
        return [(int(round(px)), int(round(py))) for px, py in pixel_points]

    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    rotated = []
    for px, py in pixel_points:
        dx, dy = px - center_x, py - center_y
        rx = dx * cos_t - dy * sin_t
        ry = dx * sin_t + dy * cos_t
        rotated.append((int(round(center_x + rx)), int(round(center_y + ry))))
    return rotated


def crop_rotated_region_from_image(image: np.ndarray, region, image_width: int, image_height: int) -> np.ndarray:
    """Return a de-rotated (straightened) crop of region's area from image,
    as a foundation for future OCR on a rotated region.

    Rotates a COPY of the whole image around region's own center to undo
    its rotation_angle, then crops the region's axis-aligned bounding box
    from that copy - the page/paper is never rotated in place (image is
    never modified), only an in-memory copy used to produce one region's
    crop. Equivalent to a plain bounding-box crop when rotation_angle is 0.

    This is a geometry/cropping foundation only - it is not yet wired into
    the live extraction pipeline (see app/services/extraction_service.py),
    which still only matches OCR blocks against axis-aligned bounding boxes
    for 0-degree regions. Confirming this crop is pixel-accurate for real
    rotated scans is left as later-stage work once extraction actually
    consumes rotated regions.
    """
    x1 = int(region.x * image_width)
    y1 = int(region.y * image_height)
    x2 = int((region.x + region.width) * image_width)
    y2 = int((region.y + region.height) * image_height)
    angle = get_region_rotation_angle(region)

    if angle == 0.0:
        return image[y1:y2, x1:x2].copy()

    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    # cv2.getRotationMatrix2D treats a positive angle as counter-clockwise,
    # so passing rotation_angle directly (positive = clockwise on screen,
    # per this module's convention) rotates the image counter-clockwise by
    # that many degrees - undoing the region's clockwise rotation.
    rotation_matrix = cv2.getRotationMatrix2D((center_x, center_y), angle, 1.0)
    straightened = cv2.warpAffine(image, rotation_matrix, (image.shape[1], image.shape[0]))
    return straightened[y1:y2, x1:x2].copy()


def _fill_region(image: np.ndarray, region, width: int, height: int, value: int) -> None:
    """Paint a solid fill (value, 0-255) over region's area on image, in
    place. Rectangle regions use their x/y/width/height bounding box;
    polygon regions use their actual polygon_points_json outline (not just
    its bounding box), so masking is precise for irregular ignore areas.

    Stage 11J: if region has a non-zero rotation_angle, both rectangle and
    polygon regions are filled using their rotated corner points (see
    compute_rotated_region_polygon) instead - this is unchanged/exactly the
    original Stage 11I behavior whenever rotation_angle is 0."""
    angle = get_region_rotation_angle(region)
    color = (value, value, value) if image.ndim == 3 else value

    if angle != 0.0:
        pixel_points = np.array(compute_rotated_region_polygon(region, width, height), dtype=np.int32)
        cv2.fillPoly(image, [pixel_points], color)
        return

    is_polygon = getattr(region, "shape_type", "rectangle") == "polygon"
    points = _region_polygon_points(region) if is_polygon else []

    if is_polygon and points:
        pixel_points = np.array([[int(x * width), int(y * height)] for x, y in points], dtype=np.int32)
        cv2.fillPoly(image, [pixel_points], color)
        return

    x1 = int(region.x * width)
    y1 = int(region.y * height)
    x2 = int((region.x + region.width) * width)
    y2 = int((region.y + region.height) * height)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness=-1)


def build_ignore_region_mask(image_width: int, image_height: int, ignore_regions: List) -> np.ndarray:
    """Build a single-channel uint8 mask the size of the page image, where
    255 marks pixels that fall inside any of ignore_regions and 0 marks
    everything else. Does not modify any actual page image - pair with
    apply_ignore_regions_to_image (or use directly) when real masking is
    needed by a later OCR/extraction stage."""
    mask = np.zeros((image_height, image_width), dtype=np.uint8)
    for region in ignore_regions:
        _fill_region(mask, region, image_width, image_height, 255)
    return mask


def apply_ignore_regions_to_image(image: np.ndarray, ignore_regions: List, fill_value: int = 255) -> np.ndarray:
    """Return a copy of image with every region in ignore_regions painted
    solid (fill_value, default white), so OCR run on the result never sees
    ignored content. image is never modified in place."""
    result = image.copy()
    height, width = result.shape[:2]
    for region in ignore_regions:
        _fill_region(result, region, width, height, fill_value)
    return result


# --- Stage 11P: answer-extraction geometry helpers --------------------------
#
# match_ocr_blocks_to_region matches Stage 11N's stored per-block OCR output
# (text/confidence/pixel-space box, discarded before Stage 11P) against one
# template region's own geometry, for a first, conservative pass at real
# answer-text extraction. It intentionally only handles the two geometry
# cases this project can already validate with confidence:
#   - plain axis-aligned rectangles (region.shape_type == "rectangle")
#   - polygons (region.shape_type == "polygon"), via their real outline
# Any region with a non-zero rotation_angle is deliberately NOT handled here
# - callers should fall back to page-level OCR text for those, exactly like
# crop_rotated_region_from_image's own docstring already flags rotated-
# region pixel accuracy as an open question pending real scanned samples.


def get_image_dimensions(image_path: str) -> Tuple[int, int]:
    """Return (width, height) in pixels of image_path (Stage 11P), for
    fractional<->pixel geometry conversions. Raises ValueError if the image
    can't be read."""
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    height, width = image.shape[:2]
    return width, height


def match_ocr_blocks_to_region(
    ocr_blocks_json: Optional[str], region, image_width: int, image_height: int
) -> str:
    """Return the space-joined text of every OCR block (Stage 11N's stored
    block data) whose center point falls inside region's plain pixel-space
    geometry - a polygon region uses its real outline (cv2.pointPolygonTest),
    anything else uses region's plain axis-aligned bounding box. Returns ""
    if ocr_blocks_json is empty/None or no block's center falls inside.

    Callers should not use this for a region with a non-zero rotation_angle
    - see this module's Stage 11P section note above."""
    if not ocr_blocks_json:
        return ""
    blocks = json.loads(ocr_blocks_json)
    if not blocks:
        return ""

    is_polygon = getattr(region, "shape_type", "rectangle") == "polygon" and getattr(
        region, "polygon_points_json", None
    )
    if is_polygon:
        points = _region_polygon_points(region)
        pixel_polygon = np.array([[px * image_width, py * image_height] for px, py in points], dtype=np.float32)
    else:
        x1 = region.x * image_width
        y1 = region.y * image_height
        x2 = (region.x + region.width) * image_width
        y2 = (region.y + region.height) * image_height

    matched_texts = []
    for block in blocks:
        box = block.get("box") or []
        if not box:
            continue
        center_x = sum(point[0] for point in box) / len(box)
        center_y = sum(point[1] for point in box) / len(box)

        if is_polygon:
            inside = cv2.pointPolygonTest(pixel_polygon, (center_x, center_y), False) >= 0
        else:
            inside = x1 <= center_x <= x2 and y1 <= center_y <= y2

        if inside and block.get("text"):
            matched_texts.append(block["text"])

    return " ".join(matched_texts)
