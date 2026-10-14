"""Answer template and template region data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2

REGION_TYPE_STUDENT_ID = "student_id"
REGION_TYPE_QUESTION_NUMBER_BOX = "question_number_box"
REGION_TYPE_ANSWER_BOX = "answer_box"
REGION_TYPE_MCQ_OPTION_BOX = "mcq_option_box"
REGION_TYPE_WRITING_BOX = "writing_box"
# Stage 11I: an exclusion mask, not an answer/question/student-id component.
# Valid for both paper types - unrelated/ignorable content can appear on
# either Kertas 1 or Kertas 2 sample papers.
REGION_TYPE_IGNORE = "ignore_region"

SHAPE_TYPE_RECTANGLE = "rectangle"
SHAPE_TYPE_POLYGON = "polygon"

REGION_TYPES_BY_PAPER_TYPE = {
    PAPER_TYPE_KERTAS_1: [
        REGION_TYPE_STUDENT_ID,
        REGION_TYPE_QUESTION_NUMBER_BOX,
        REGION_TYPE_ANSWER_BOX,
        REGION_TYPE_MCQ_OPTION_BOX,
        REGION_TYPE_IGNORE,
    ],
    PAPER_TYPE_KERTAS_2: [
        REGION_TYPE_STUDENT_ID,
        REGION_TYPE_WRITING_BOX,
        REGION_TYPE_QUESTION_NUMBER_BOX,
        REGION_TYPE_IGNORE,
    ],
}


def get_allowed_region_types(paper_type: str) -> List[str]:
    """Return the region types a region may use for the given paper type."""
    return REGION_TYPES_BY_PAPER_TYPE.get(paper_type, [])


@dataclass
class AnswerTemplate:
    template_id: int
    teacher_id: int
    title: str
    paper_type: str
    sample_file_path: str
    created_at: str


@dataclass
class TeacherTemplateRow:
    """One row per template owned by a teacher, with its region count."""

    template_id: int
    title: str
    paper_type: str
    sample_file_path: str
    created_at: str
    region_count: int


@dataclass
class TemplateRegion:
    region_id: int
    template_id: int
    label: str
    region_type: Optional[str]
    page_number: int
    x: float
    y: float
    width: float
    height: float
    order_index: int
    notes: Optional[str]
    # Stage 11G: x/y/width/height above always hold the shape's bounding box
    # (for polygons, computed from polygon_points_json) so any existing
    # rectangle-only consumer (e.g. extraction_service.py) keeps working
    # unchanged. shape_type defaults to "rectangle" for every pre-Stage-11G
    # region; polygon_points_json is only set for shape_type="polygon".
    shape_type: str = SHAPE_TYPE_RECTANGLE
    polygon_points_json: Optional[str] = None
    # Stage 11J: manual rotation (degrees, -180 to 180) applied around the
    # region's own bounding-box center for display/future-extraction
    # purposes only - x/y/width/height above are never rotated themselves,
    # and the whole page/paper is never rotated. Defaults to 0.0 (no
    # rotation) for every pre-Stage-11J region.
    rotation_angle: float = 0.0


def create_template(
    conn: sqlite3.Connection,
    teacher_id: int,
    title: str,
    paper_type: str,
    sample_file_path: str,
) -> AnswerTemplate:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO answer_templates (teacher_id, title, paper_type, sample_file_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (teacher_id, title, paper_type, sample_file_path, created_at),
    )
    conn.commit()
    return AnswerTemplate(
        template_id=cursor.lastrowid,
        teacher_id=teacher_id,
        title=title,
        paper_type=paper_type,
        sample_file_path=sample_file_path,
        created_at=created_at,
    )


def update_template_sample_path(conn: sqlite3.Connection, template_id: int, sample_file_path: str) -> None:
    conn.execute(
        "UPDATE answer_templates SET sample_file_path = ? WHERE template_id = ?",
        (sample_file_path, template_id),
    )
    conn.commit()


def get_template_by_id(conn: sqlite3.Connection, template_id: int) -> Optional[AnswerTemplate]:
    row = conn.execute(
        "SELECT template_id, teacher_id, title, paper_type, sample_file_path, created_at "
        "FROM answer_templates WHERE template_id = ?",
        (template_id,),
    ).fetchone()
    if row is None:
        return None
    return AnswerTemplate(**dict(row))


def get_templates_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[TeacherTemplateRow]:
    rows = conn.execute(
        """
        SELECT at.template_id, at.title, at.paper_type, at.sample_file_path, at.created_at,
               COUNT(tr.region_id) AS region_count
        FROM answer_templates at
        LEFT JOIN template_regions tr ON tr.template_id = at.template_id
        WHERE at.teacher_id = ?
        GROUP BY at.template_id, at.title, at.paper_type, at.sample_file_path, at.created_at
        ORDER BY at.created_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [TeacherTemplateRow(**dict(row)) for row in rows]


def count_templates_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM answer_templates WHERE teacher_id = ?", (teacher_id,)
    ).fetchone()
    return row[0]


def count_templates_for_teacher_by_paper_type(conn: sqlite3.Connection, teacher_id: int, paper_type: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM answer_templates WHERE teacher_id = ? AND paper_type = ?",
        (teacher_id, paper_type),
    ).fetchone()
    return row[0]


def add_region(
    conn: sqlite3.Connection,
    template_id: int,
    label: str,
    region_type: Optional[str],
    page_number: int,
    x: float,
    y: float,
    width: float,
    height: float,
    order_index: int,
    notes: Optional[str] = None,
    shape_type: str = SHAPE_TYPE_RECTANGLE,
    polygon_points_json: Optional[str] = None,
    rotation_angle: float = 0.0,
) -> TemplateRegion:
    cursor = conn.execute(
        "INSERT INTO template_regions "
        "(template_id, label, region_type, page_number, x, y, width, height, order_index, notes, "
        "shape_type, polygon_points_json, rotation_angle) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (template_id, label, region_type, page_number, x, y, width, height, order_index, notes,
         shape_type, polygon_points_json, rotation_angle),
    )
    conn.commit()
    return TemplateRegion(
        region_id=cursor.lastrowid,
        template_id=template_id,
        label=label,
        region_type=region_type,
        page_number=page_number,
        x=x,
        y=y,
        width=width,
        height=height,
        order_index=order_index,
        notes=notes,
        shape_type=shape_type,
        polygon_points_json=polygon_points_json,
        rotation_angle=rotation_angle,
    )


def update_region(
    conn: sqlite3.Connection,
    region_id: int,
    label: str,
    region_type: Optional[str],
    page_number: int,
    x: float,
    y: float,
    width: float,
    height: float,
    order_index: int,
    notes: Optional[str] = None,
    shape_type: str = SHAPE_TYPE_RECTANGLE,
    polygon_points_json: Optional[str] = None,
    rotation_angle: float = 0.0,
) -> None:
    conn.execute(
        "UPDATE template_regions "
        "SET label = ?, region_type = ?, page_number = ?, x = ?, y = ?, width = ?, height = ?, "
        "order_index = ?, notes = ?, shape_type = ?, polygon_points_json = ?, rotation_angle = ? "
        "WHERE region_id = ?",
        (label, region_type, page_number, x, y, width, height, order_index, notes,
         shape_type, polygon_points_json, rotation_angle, region_id),
    )
    conn.commit()


def get_regions_for_template(conn: sqlite3.Connection, template_id: int) -> List[TemplateRegion]:
    rows = conn.execute(
        "SELECT region_id, template_id, label, region_type, page_number, x, y, width, height, order_index, notes, "
        "shape_type, polygon_points_json, rotation_angle "
        "FROM template_regions WHERE template_id = ? ORDER BY order_index",
        (template_id,),
    ).fetchall()
    return [TemplateRegion(**dict(row)) for row in rows]


def get_ignore_regions_for_template(
    conn: sqlite3.Connection, template_id: int, page_number: Optional[int] = None
) -> List[TemplateRegion]:
    """Return only template_id's ignore_region rows (Stage 11I), optionally
    filtered to a single page_number. Unauthenticated model-layer helper -
    used by extraction/OCR code that has no teacher_id request context."""
    regions = [r for r in get_regions_for_template(conn, template_id) if r.region_type == REGION_TYPE_IGNORE]
    if page_number is not None:
        regions = [r for r in regions if r.page_number == page_number]
    return regions


def get_regions_for_template_excluding_ignore(
    conn: sqlite3.Connection, template_id: int, page_number: Optional[int] = None
) -> List[TemplateRegion]:
    """Return template_id's regions with ignore_region rows excluded (Stage
    11I), optionally filtered to a single page_number. Unauthenticated
    model-layer helper - used by extraction/OCR code that has no teacher_id
    request context, so ignore regions are never processed as answer/
    question/student-id regions."""
    regions = [r for r in get_regions_for_template(conn, template_id) if r.region_type != REGION_TYPE_IGNORE]
    if page_number is not None:
        regions = [r for r in regions if r.page_number == page_number]
    return regions


def get_max_region_order(conn: sqlite3.Connection, template_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(order_index) FROM template_regions WHERE template_id = ?", (template_id,)
    ).fetchone()
    return row[0] if row[0] is not None else 0


def get_region_by_id(conn: sqlite3.Connection, region_id: int) -> Optional[TemplateRegion]:
    row = conn.execute(
        "SELECT region_id, template_id, label, region_type, page_number, x, y, width, height, order_index, notes, "
        "shape_type, polygon_points_json, rotation_angle "
        "FROM template_regions WHERE region_id = ?",
        (region_id,),
    ).fetchone()
    if row is None:
        return None
    return TemplateRegion(**dict(row))


def delete_region(conn: sqlite3.Connection, region_id: int) -> None:
    conn.execute("DELETE FROM template_regions WHERE region_id = ?", (region_id,))
    conn.commit()
