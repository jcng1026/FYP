"""Shared Subject Profile region bbox geometry helpers.

Extracted out of app/services/region_detection_dataset_service.py (Stage
12E) so app/services/region_crop_ocr_service.py (Stage 11Y) can reuse the
exact same rotation-aware enclosing-bbox math without duplicating it.
This module deliberately has NO dependency on subject_profile_service.py
(or anything that does) - region_detection_dataset_service.py itself
imports from subject_profile_service.py, so region_crop_ocr_service.py
importing the bbox helpers directly from region_detection_dataset_service.py
would create an import cycle (subject_profile_service -> region_crop_ocr_
service -> region_detection_dataset_service -> subject_profile_service).
Both call sites import these same two functions from here instead.

See region_detection_dataset_service.py's own module docstring for the
full rationale of why this geometry is correct (confirmed by inspecting
app/ui/template_canvas.py's coordinate system, not assumed).
"""

import json
import math
from typing import Optional, Tuple

from app.models.subject_profile_model import SHAPE_TYPE_POLYGON


def compute_enclosing_bbox(region) -> Optional[Tuple[float, float, float, float]]:
    """Return (x, y, width, height) - the top-left-origin enclosing
    bounding box, in normalized 0-1 fractions - accounting for rotation.
    Returns None if the result has non-positive width/height (caller
    should skip and count it)."""
    x, y, width, height = region.x, region.y, region.width, region.height

    if region.rotation_angle:
        if region.shape_type == SHAPE_TYPE_POLYGON and region.polygon_points_json:
            try:
                points = json.loads(region.polygon_points_json)
            except json.JSONDecodeError:
                points = [(x, y), (x + width, y), (x, y + height), (x + width, y + height)]
        else:
            points = [(x, y), (x + width, y), (x, y + height), (x + width, y + height)]

        cx, cy = x + width / 2, y + height / 2
        theta = math.radians(region.rotation_angle)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        rotated_xs, rotated_ys = [], []
        for px, py in points:
            dx, dy = px - cx, py - cy
            rotated_xs.append(cx + dx * cos_t - dy * sin_t)
            rotated_ys.append(cy + dx * sin_t + dy * cos_t)
        x, y = min(rotated_xs), min(rotated_ys)
        width = max(rotated_xs) - x
        height = max(rotated_ys) - y

    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def clamp_to_unit_bbox(x: float, y: float, width: float, height: float) -> Optional[Tuple[float, float, float, float]]:
    """Clamp an already-validated (non-degenerate) bbox to the valid 0-1
    range. Returns None if clamping collapses it to zero/negative area
    (e.g. a region whose enclosing bbox, after rotation, falls entirely
    outside the page)."""
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(1.0, x + width), min(1.0, y + height)
    clamped_width, clamped_height = x1 - x0, y1 - y0
    if clamped_width <= 0 or clamped_height <= 0:
        return None
    return x0, y0, clamped_width, clamped_height


def compute_iou(box_a: Tuple[float, float, float, float], box_b: Tuple[float, float, float, float]) -> float:
    """Intersection-over-Union of two axis-aligned (x, y, width, height)
    boxes (any consistent unit - Stage 12E-2 uses normalized 0-1 fractions).
    Returns 0.0 for degenerate (non-positive area) boxes or no overlap -
    never raises."""
    ax0, ay0, aw, ah = box_a
    bx0, by0, bw, bh = box_b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh

    inter_x0, inter_y0 = max(ax0, bx0), max(ay0, by0)
    inter_x1, inter_y1 = min(ax1, bx1), min(ay1, by1)
    inter_w, inter_h = inter_x1 - inter_x0, inter_y1 - inter_y0
    if inter_w <= 0 or inter_h <= 0:
        return 0.0

    intersection = inter_w * inter_h
    union = aw * ah + bw * bh - intersection
    if union <= 0:
        return 0.0
    return intersection / union
