"""MCQ selected-option mark detection for bubble_area regions (Marking Fix).

Color + connected-component based (OpenCV/numpy only - no ML model, no new
dependency): this project's real SPM student answer PDFs mark the chosen
option by circling the printed option letter in a distinctly colored
(blue) ink, clearly separable from the black printed text by color alone -
confirmed against a real completed student PDF during this fix's
investigation. This module only LOCATES that mark (a bounding box in the
region crop's own pixel coordinates); reading which letter it encircles is
a separate, small OCR call the caller (region_crop_ocr_service.py) makes
against just that small sub-crop, reusing the same OCR engine already used
for every other region type - see run_region_crop_ocr's bubble_area branch.

Deliberately conservative: needs_review=True (never guesses) whenever
detection is ambiguous - no mark found, or multiple similarly-sized marks
far enough apart to plausibly be separate (competing) selections - per the
"flag for teacher review instead of automatically marking 0" requirement.
Never raises; an unusable crop is treated the same as "nothing detected".
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

# Tuned against a real completed student PDF: printed black text renders at
# roughly equal B/G/R (e.g. ~(35,31,32) BGR), while the student's hand-drawn
# selection mark renders distinctly blue (e.g. ~(135,56,41) BGR) - safely on
# opposite sides of both thresholds below.
BLUE_MINUS_RED_THRESHOLD = 30
BLUE_MINUS_GREEN_THRESHOLD = 20

# A real selection mark (a circle/ring drawn around a printed letter) is a
# connected blob of a meaningful size - this filters out stray anti-
# aliasing noise pixels along page rules/borders that pass the color test
# but form only a handful of scattered pixels.
MIN_MARK_AREA_PX = 80

# A second candidate is only "competing" (forcing needs_review) if it's a
# similarly-sized blob AND clearly separated from the best one - two
# distinct marks, not the same mark's ink split into adjacent components.
AMBIGUOUS_SECOND_CANDIDATE_AREA_RATIO = 0.5
AMBIGUOUS_MIN_SEPARATION_PX = 20


@dataclass
class BubbleMarkLocation:
    found: bool
    bbox: Optional[Tuple[int, int, int, int]]  # (x, y, w, h) in crop-pixel coordinates
    needs_review: bool
    reason: str


def locate_selected_mark(color_crop_bgr: Optional[np.ndarray]) -> BubbleMarkLocation:
    """Find the selection mark in color_crop_bgr - a bubble_area region's
    RAW COLOR crop (NOT grayscale/binary-preprocessed; color is exactly the
    signal this needs). Returns the mark's bounding box in the crop's own
    pixel coordinates, or found=False with needs_review=True if none (or
    more than one ambiguous candidate) is detected."""
    if color_crop_bgr is None or color_crop_bgr.size == 0 or color_crop_bgr.ndim != 3:
        return BubbleMarkLocation(False, None, True, "Empty or invalid crop - cannot detect a selected option, flagged for teacher review.")

    b, g, r = cv2.split(color_crop_bgr.astype(np.int16))
    mask = ((b - r) > BLUE_MINUS_RED_THRESHOLD) & ((b - g) > BLUE_MINUS_GREEN_THRESHOLD)
    mask_u8 = mask.astype(np.uint8) * 255

    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    candidates = [
        (int(stats[i][4]), (int(stats[i][0]), int(stats[i][1]), int(stats[i][2]), int(stats[i][3])), tuple(centroids[i]))
        for i in range(1, num_labels) if stats[i][4] >= MIN_MARK_AREA_PX
    ]
    if not candidates:
        return BubbleMarkLocation(False, None, True, "No selected-option mark detected - flagged for teacher review.")

    candidates.sort(key=lambda c: c[0], reverse=True)
    best_area, best_bbox, _best_centroid = candidates[0]

    for area, bbox, _centroid in candidates[1:]:
        if area >= best_area * AMBIGUOUS_SECOND_CANDIDATE_AREA_RATIO:
            vertical_gap = abs(bbox[1] - best_bbox[1])
            horizontal_gap = abs(bbox[0] - best_bbox[0])
            if max(vertical_gap, horizontal_gap) > AMBIGUOUS_MIN_SEPARATION_PX:
                return BubbleMarkLocation(
                    False, None, True,
                    "Multiple possible selected-option marks detected - flagged for teacher review.",
                )

    return BubbleMarkLocation(True, best_bbox, False, "Selected option mark detected.")


def mask_out_selection_mark(color_crop_bgr: np.ndarray) -> np.ndarray:
    """Marking Fix Follow-up: paint every blue selection-mark pixel white,
    leaving just the printed letter glyph on a plain background.

    OCR on the letter sub-crop was found to misread a clearly-legible
    circled letter surprisingly often (a circled "C" confidently read as
    "0"; a circled "C" elsewhere returning no text at all) - confirmed
    against real crops from profile_14. The blue-preprocessed binary image
    (see app.utils.document_preprocessing.preprocess_page_image) renders
    the ring the SAME black as the letter, so the ring visually merges
    with/wraps the glyph in a way that confuses recognition. Removing the
    ring HERE, on the raw color crop, before that preprocessing step,
    reliably fixed every case tried. Safe no-op (returns unchanged) for a
    crop with no blue pixels at all."""
    b, g, r = cv2.split(color_crop_bgr.astype(np.int16))
    mask = ((b - r) > BLUE_MINUS_RED_THRESHOLD) & ((b - g) > BLUE_MINUS_GREEN_THRESHOLD)
    masked = color_crop_bgr.copy()
    masked[mask] = (255, 255, 255)
    return masked
