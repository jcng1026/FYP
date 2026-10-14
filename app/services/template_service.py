"""Answer template and template region editing logic for the Teacher role."""

import json
import re
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from app.models.revision_material_model import ALLOWED_PAPER_TYPES
from app.models.template_model import (
    AnswerTemplate,
    SHAPE_TYPE_POLYGON,
    SHAPE_TYPE_RECTANGLE,
    TeacherTemplateRow,
    TemplateRegion,
    add_region,
    count_templates_for_teacher as count_templates_for_teacher_record,
    count_templates_for_teacher_by_paper_type as count_templates_for_teacher_by_paper_type_record,
    create_template as create_template_record,
    delete_region,
    get_allowed_region_types,
    get_ignore_regions_for_template as get_ignore_regions_for_template_record,
    get_max_region_order,
    get_region_by_id,
    get_regions_for_template_excluding_ignore as get_regions_for_template_excluding_ignore_record,
    get_template_by_id,
    get_templates_for_teacher as get_templates_for_teacher_record,
    get_regions_for_template as get_regions_for_template_record,
    update_region,
    update_template_sample_path,
)
from app.models.template_region_group_model import get_groups_for_template as get_region_groups_for_template_record
from app.services.user_service import validate_teacher_exists
from app.utils.file_storage import store_template_file

DEFAULT_PAGE_NUMBER = 1
MIN_POLYGON_POINTS = 3

MAX_LABEL_LENGTH = 80
_LABEL_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9 _-]+$")

MIN_ROTATION_ANGLE = -180.0
MAX_ROTATION_ANGLE = 180.0


def _validate_rotation_angle(rotation_angle) -> float:
    """Validate a region's manual rotation angle (Stage 11J).

    Returns the value as a float. Raises ValueError if it isn't numeric or
    falls outside [MIN_ROTATION_ANGLE, MAX_ROTATION_ANGLE] (-180 to 180
    degrees). Rotation is applied around the region's own bounding-box
    center for display/future-extraction only - it never changes the
    stored x/y/width/height geometry and never rotates the whole page.
    """
    try:
        angle = float(rotation_angle)
    except (TypeError, ValueError):
        raise ValueError("Rotation angle must be a number.")
    if angle < MIN_ROTATION_ANGLE or angle > MAX_ROTATION_ANGLE:
        raise ValueError(
            f"Rotation angle must be between {MIN_ROTATION_ANGLE:g} and {MAX_ROTATION_ANGLE:g} degrees."
        )
    return angle


def _validate_label_format(label: str) -> str:
    """Validate a region label's format only (no uniqueness check here).

    Returns the normalized (stripped) label. Raises ValueError if the label
    is empty, too long, or contains characters other than letters, numbers,
    spaces, underscores, and hyphens.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("Region name is required.")
    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"Region name must be {MAX_LABEL_LENGTH} characters or fewer.")
    if not _LABEL_SAFE_PATTERN.match(label):
        raise ValueError(
            "Region name can only contain letters, numbers, spaces, underscores (_), and hyphens (-)."
        )
    return label


def _check_label_is_unique_in_template(
    conn: sqlite3.Connection, template_id: int, label: str, exclude_region_id: Optional[int] = None
) -> None:
    """Raise ValueError if label is already used by another region in
    template_id (case-insensitive), across every page of the template, or
    by a region group in the template (Stage 11H - regions and groups share
    one label namespace per template). exclude_region_id lets editing a
    region keep its own existing label."""
    normalized = label.strip().lower()
    for existing in get_regions_for_template_record(conn, template_id):
        if existing.region_id == exclude_region_id:
            continue
        if existing.label.strip().lower() == normalized:
            raise ValueError("A region with this label already exists in this template.")
    for group in get_region_groups_for_template_record(conn, template_id):
        if group.label.strip().lower() == normalized:
            raise ValueError("A region group with this label already exists in this template.")


def _validate_region_fields(
    label: str,
    region_type: str,
    paper_type: str,
    page_number: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> str:
    """Shared validation for both adding and editing a region (label
    format, page/type/geometry - NOT the whole-template uniqueness check,
    which needs a connection/template_id - see _check_label_is_unique_in_template).

    Returns the normalized (stripped) label. Raises ValueError on any
    invalid field.
    """
    label = _validate_label_format(label)

    if page_number < 1:
        raise ValueError("Page number must be at least 1.")

    allowed_types = get_allowed_region_types(paper_type)
    if region_type not in allowed_types:
        raise ValueError(
            f"Region type must be one of: {', '.join(allowed_types)} for {paper_type}."
        )

    if width <= 0 or height <= 0:
        raise ValueError("Region width and height must be greater than zero.")
    if x < 0 or y < 0:
        raise ValueError("Region x and y must be non-negative.")
    if x + width > 1.0001 or y + height > 1.0001:
        raise ValueError("Region must be within the bounds of the page.")

    return label


def _validate_region_type_and_page(region_type: str, paper_type: str, page_number: int) -> None:
    """Shared by polygon add/update - the non-geometry half of
    _validate_region_fields (region type valid for paper_type, page >= 1)."""
    if page_number < 1:
        raise ValueError("Page number must be at least 1.")

    allowed_types = get_allowed_region_types(paper_type)
    if region_type not in allowed_types:
        raise ValueError(
            f"Region type must be one of: {', '.join(allowed_types)} for {paper_type}."
        )


def _validate_polygon_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Validate and normalize a polygon's points (fractional 0-1 page
    coordinates). Returns the clamped point list. Raises ValueError if
    there are fewer than MIN_POLYGON_POINTS points or any point falls
    outside the page bounds."""
    if len(points) < MIN_POLYGON_POINTS:
        raise ValueError(f"A polygon region needs at least {MIN_POLYGON_POINTS} points.")

    normalized = []
    for x, y in points:
        if x < 0 or x > 1.0001 or y < 0 or y > 1.0001:
            raise ValueError("Polygon points must be within the bounds of the page.")
        normalized.append((max(0.0, min(1.0, x)), max(0.0, min(1.0, y))))
    return normalized


def _polygon_bounding_box(points: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Return (x, y, width, height) of points' bounding box, for storage in
    the same x/y/width/height columns rectangle regions use - so any
    existing rectangle-only consumer (e.g. extraction_service.py) can keep
    treating every region as "at least a bounding rectangle" without
    changes. width/height are floored to a tiny positive value so the
    table's CHECK (width > 0)/(height > 0) constraints are never violated
    by a degenerate (collinear) point set."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    width = max(x_max - x_min, 0.0001)
    height = max(y_max - y_min, 0.0001)
    return x_min, y_min, width, height


def parse_polygon_points(polygon_points_json: Optional[str]) -> List[Tuple[float, float]]:
    """Parse a region's stored polygon_points_json back into a list of
    (x, y) fractional coordinate tuples. Returns [] if polygon_points_json
    is None/empty (e.g. a rectangle region)."""
    if not polygon_points_json:
        return []
    return [(float(x), float(y)) for x, y in json.loads(polygon_points_json)]


def add_polygon_template_region(
    conn: sqlite3.Connection,
    teacher_id: int,
    template_id: int,
    label: str,
    region_type: str,
    points: List[Tuple[float, float]],
    page_number: int = DEFAULT_PAGE_NUMBER,
    notes: str = "",
    rotation_angle: float = 0.0,
) -> TemplateRegion:
    """Add a polygon (freeform) region to a template owned by teacher_id.

    Mirrors add_template_region's validation (label format/uniqueness,
    region type, page number, rotation_angle) but stores a point list
    instead of a plain rectangle. x/y/width/height are still populated from
    the polygon's bounding box, so this region behaves like a rectangle for
    any consumer that hasn't been updated for polygons yet (see
    _polygon_bounding_box).

    Raises ValueError for the same reasons as add_template_region, plus if
    there are fewer than MIN_POLYGON_POINTS points or a point falls outside
    the page bounds.
    """
    template = get_owned_template(conn, teacher_id, template_id)

    label = _validate_label_format(label)
    _validate_region_type_and_page(region_type, template.paper_type, page_number)
    normalized_points = _validate_polygon_points(points)
    rotation_angle = _validate_rotation_angle(rotation_angle)
    _check_label_is_unique_in_template(conn, template_id, label)

    x, y, width, height = _polygon_bounding_box(normalized_points)
    order_index = get_max_region_order(conn, template_id) + 1
    return add_region(
        conn, template_id, label, region_type, page_number, x, y, width, height, order_index, notes or None,
        shape_type=SHAPE_TYPE_POLYGON, polygon_points_json=json.dumps(normalized_points),
        rotation_angle=rotation_angle,
    )


def update_polygon_template_region(
    conn: sqlite3.Connection,
    teacher_id: int,
    region_id: int,
    label: str,
    region_type: str,
    page_number: int,
    points: List[Tuple[float, float]],
    order_index: int,
    notes: str = "",
    rotation_angle: float = 0.0,
) -> TemplateRegion:
    """Redefine an existing region as a polygon with new points (Stage 11G
    polygon Redefine Region). Mirrors update_template_region's validation.

    rotation_angle defaults to 0.0 but callers redefining an existing
    region should pass its current rotation_angle through explicitly (see
    app/ui/teacher_dashboard.py's redefine flow) so Redefine Region does not
    silently reset rotation - it is only changed when the teacher edits it
    separately via the Edit Region dialog.

    Raises ValueError for the same reasons as update_template_region, plus
    the polygon point-count/bounds checks from add_polygon_template_region.
    """
    region = get_region_by_id(conn, region_id)
    if region is None:
        raise ValueError("Region not found.")
    template = get_owned_template(conn, teacher_id, region.template_id)

    label = _validate_label_format(label)
    _validate_region_type_and_page(region_type, template.paper_type, page_number)
    normalized_points = _validate_polygon_points(points)
    rotation_angle = _validate_rotation_angle(rotation_angle)
    _check_label_is_unique_in_template(conn, region.template_id, label, exclude_region_id=region_id)

    x, y, width, height = _polygon_bounding_box(normalized_points)
    update_region(
        conn, region_id, label, region_type, page_number, x, y, width, height, order_index, notes or None,
        shape_type=SHAPE_TYPE_POLYGON, polygon_points_json=json.dumps(normalized_points),
        rotation_angle=rotation_angle,
    )
    return get_region_by_id(conn, region_id)


def create_template(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    sample_source_path: str,
) -> AnswerTemplate:
    """Create a new answer template owned by teacher_id, copying the selected
    sample paper file into a local, template-specific folder under
    data/templates/. No regions are created yet.

    Raises ValueError if the requester is not a teacher, the title is empty,
    the paper type is not Kertas 1/2, or the sample file path is missing or
    does not exist.
    """
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create templates.")

    title = title.strip()
    if not title:
        raise ValueError("Title is required.")

    if paper_type not in ALLOWED_PAPER_TYPES:
        raise ValueError("Paper type must be Kertas 1 or Kertas 2.")

    sample_source_path = (sample_source_path or "").strip()
    if not sample_source_path:
        raise ValueError("A sample paper file is required.")
    if not Path(sample_source_path).is_file():
        raise ValueError("The selected sample paper file could not be found.")

    template = create_template_record(
        conn,
        teacher_id=teacher_id,
        title=title,
        paper_type=paper_type,
        sample_file_path="",
    )

    sample_file_path = store_template_file(template.template_id, sample_source_path, "sample_paper")
    update_template_sample_path(conn, template.template_id, sample_file_path)

    template.sample_file_path = sample_file_path
    return template


def list_templates_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherTemplateRow]:
    return get_templates_for_teacher_record(conn, teacher_id)


def count_templates_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    return count_templates_for_teacher_record(conn, teacher_id)


def count_templates_for_teacher_by_paper_type(conn: sqlite3.Connection, teacher_id: int, paper_type: str) -> int:
    return count_templates_for_teacher_by_paper_type_record(conn, teacher_id, paper_type)


def get_owned_template(conn: sqlite3.Connection, teacher_id: int, template_id: int) -> AnswerTemplate:
    """Return template_id if it exists and is owned by teacher_id.

    Raises ValueError otherwise.
    """
    template = get_template_by_id(conn, template_id)
    if template is None:
        raise ValueError("Template not found.")
    if template.teacher_id != teacher_id:
        raise ValueError("You can only edit your own templates.")
    return template


def add_template_region(
    conn: sqlite3.Connection,
    teacher_id: int,
    template_id: int,
    label: str,
    region_type: str,
    x: float,
    y: float,
    width: float,
    height: float,
    page_number: int = DEFAULT_PAGE_NUMBER,
    notes: str = "",
    rotation_angle: float = 0.0,
) -> TemplateRegion:
    """Add a region to a template owned by teacher_id.

    Raises ValueError if the template doesn't exist or isn't owned by
    teacher_id, the label is empty/unsafe/too long, the label is already
    used by another region anywhere in this template, the region type
    isn't valid for the template's paper type, the region geometry is
    invalid (non-positive size or outside the 0-1 normalized page bounds),
    or rotation_angle is non-numeric or outside -180 to 180 degrees (Stage
    11J - manual rotation applied around the region's own center for
    display/future-extraction only, never changing x/y/width/height or
    rotating the whole page).
    """
    template = get_owned_template(conn, teacher_id, template_id)

    label = _validate_region_fields(label, region_type, template.paper_type, page_number, x, y, width, height)
    rotation_angle = _validate_rotation_angle(rotation_angle)
    _check_label_is_unique_in_template(conn, template_id, label)

    order_index = get_max_region_order(conn, template_id) + 1
    return add_region(
        conn, template_id, label, region_type, page_number, x, y, width, height, order_index, notes or None,
        rotation_angle=rotation_angle,
    )


def list_template_regions(conn: sqlite3.Connection, teacher_id: int, template_id: int) -> List[TemplateRegion]:
    get_owned_template(conn, teacher_id, template_id)
    return get_regions_for_template_record(conn, template_id)


def list_ignore_regions_for_template(
    conn: sqlite3.Connection, teacher_id: int, template_id: int, page_number: Optional[int] = None
) -> List[TemplateRegion]:
    """Return only template_id's ignore_region rows (Stage 11I), optionally
    filtered to a single page_number. Raises ValueError if the template
    doesn't exist or isn't owned by teacher_id."""
    get_owned_template(conn, teacher_id, template_id)
    return get_ignore_regions_for_template_record(conn, template_id, page_number)


def get_non_ignore_regions_for_template(
    conn: sqlite3.Connection, teacher_id: int, template_id: int, page_number: Optional[int] = None
) -> List[TemplateRegion]:
    """Return template_id's regions with ignore_region rows excluded (Stage
    11I), optionally filtered to a single page_number. Raises ValueError if
    the template doesn't exist or isn't owned by teacher_id."""
    get_owned_template(conn, teacher_id, template_id)
    return get_regions_for_template_excluding_ignore_record(conn, template_id, page_number)


def update_template_region(
    conn: sqlite3.Connection,
    teacher_id: int,
    region_id: int,
    label: str,
    region_type: str,
    page_number: int,
    x: float,
    y: float,
    width: float,
    height: float,
    order_index: int,
    notes: str = "",
    rotation_angle: float = 0.0,
) -> TemplateRegion:
    """Update an existing region belonging to one of teacher_id's own templates.

    Validates using the same rules as add_template_region (including the
    whole-template label uniqueness check - keeping a region's own existing
    label is allowed, but renaming it to another region's label is not).

    rotation_angle defaults to 0.0 but callers redefining an existing region
    should pass its current rotation_angle through explicitly (see app/ui/
    teacher_dashboard.py's redefine flow) so Redefine Region does not
    silently reset rotation - it is only changed when the teacher edits it
    separately via the Edit Region dialog.

    Raises ValueError if the region doesn't exist, its template isn't owned
    by teacher_id, or any field is invalid (including rotation_angle
    outside -180 to 180 degrees).
    """
    region = get_region_by_id(conn, region_id)
    if region is None:
        raise ValueError("Region not found.")
    template = get_owned_template(conn, teacher_id, region.template_id)

    label = _validate_region_fields(label, region_type, template.paper_type, page_number, x, y, width, height)
    rotation_angle = _validate_rotation_angle(rotation_angle)
    _check_label_is_unique_in_template(conn, region.template_id, label, exclude_region_id=region_id)

    update_region(
        conn, region_id, label, region_type, page_number, x, y, width, height, order_index, notes or None,
        rotation_angle=rotation_angle,
    )
    return get_region_by_id(conn, region_id)


def remove_template_region(conn: sqlite3.Connection, teacher_id: int, region_id: int) -> None:
    """Remove a region from one of teacher_id's own templates.

    Raises ValueError if the region doesn't exist or its template isn't
    owned by teacher_id.
    """
    region = get_region_by_id(conn, region_id)
    if region is None:
        raise ValueError("Region not found.")
    get_owned_template(conn, teacher_id, region.template_id)

    delete_region(conn, region_id)
