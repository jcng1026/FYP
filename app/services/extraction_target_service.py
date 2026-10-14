"""Extraction target representation (Stage 11K).

A normalized, read-only view over a template's regions and region groups,
built for future OCR/extraction/marking consumption. This module does not
perform OCR, write extraction results, or compute marks/scores - it is a
geometry/metadata foundation layer only, sitting alongside (not replacing)
app/services/extraction_service.py's existing live per-region OCR-block
matching.

Design notes:
- Ignore regions (Stage 11I) are exclusion masks, not answer/question/
  student-id components, so they never appear as extraction targets, either
  individually or as region group members.
- Region groups (Stage 11H) are represented as a single "group" target
  whose ordered `members` are themselves "region" targets - this is
  additive: every member region also remains available as its own
  individual "region" target in the same list. A future Main Marking
  System consumer decides whether to mark each member individually, treat
  the group as one combined answer, or both; this stage does not make that
  choice.
- Rotation (Stage 11J) and polygon (Stage 11G) geometry are carried through
  unchanged on each target's `source_region` (the original TemplateRegion),
  so callers can pass it straight into
  app/utils/document_preprocessing.py's existing
  compute_rotated_region_polygon/crop_rotated_region_from_image helpers
  once a real page image is available - those helpers need actual pixel
  dimensions, which aren't known at this template-metadata-only stage.
- No schema change, no new database table, and no writes: this module only
  reads existing template_regions/template_region_groups data.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.models.template_model import (
    SHAPE_TYPE_POLYGON,
    TemplateRegion,
    get_regions_for_template_excluding_ignore,
)
from app.models.template_region_group_model import (
    get_group_members_with_region_details,
    get_groups_for_template,
)
from app.services.template_service import parse_polygon_points
from app.utils.document_preprocessing import get_region_rotation_angle

TARGET_KIND_REGION = "region"
TARGET_KIND_GROUP = "group"


@dataclass
class ExtractionTarget:
    """One logical unit for future OCR/extraction/marking - either a single
    region ("region") or an ordered set of member regions ("group").

    Region-only fields (region_id, shape_type, rotation_angle, x/y/width/
    height, polygon_points, source_region) are populated for kind="region"
    and left at their defaults for kind="group". Group-only fields
    (group_id, members, member_regions) are populated for kind="group" and
    left at their defaults for kind="region".
    """

    kind: str
    label: str
    region_type: str
    page_numbers: List[int]

    # --- kind == "region" ---
    region_id: Optional[int] = None
    shape_type: Optional[str] = None
    rotation_angle: float = 0.0
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    polygon_points: Optional[List[Tuple[float, float]]] = None
    source_region: Optional[TemplateRegion] = None

    # --- kind == "group" ---
    group_id: Optional[int] = None
    members: List["ExtractionTarget"] = field(default_factory=list)
    member_regions: List[TemplateRegion] = field(default_factory=list)


def _region_to_target(region: TemplateRegion) -> ExtractionTarget:
    polygon_points = (
        parse_polygon_points(region.polygon_points_json) if region.shape_type == SHAPE_TYPE_POLYGON else None
    )
    return ExtractionTarget(
        kind=TARGET_KIND_REGION,
        label=region.label,
        region_type=region.region_type or "unknown",
        page_numbers=[region.page_number],
        region_id=region.region_id,
        shape_type=region.shape_type,
        rotation_angle=get_region_rotation_angle(region),
        x=region.x,
        y=region.y,
        width=region.width,
        height=region.height,
        polygon_points=polygon_points,
        source_region=region,
    )


def list_template_extraction_targets(conn: sqlite3.Connection, template_id: int) -> List[ExtractionTarget]:
    """Return template_id's extraction targets: one "region" target per
    non-ignore region, plus one "group" target per region group (ordered
    members, each also present individually earlier in the list).

    Unauthenticated model-layer helper (no teacher_id) - matches how
    app/services/extraction_service.py already reads regions during live
    extraction, since extraction runs without a requesting-teacher context.
    Ignore regions are excluded from both individual targets and from every
    group's members (a group member that somehow became an ignore_region
    after being added is defensively dropped from the group's members too,
    though template_region_group_service already prevents this at
    creation time).
    """
    non_ignore_regions = get_regions_for_template_excluding_ignore(conn, template_id)
    region_by_id = {region.region_id: region for region in non_ignore_regions}

    targets = [_region_to_target(region) for region in non_ignore_regions]

    for group in get_groups_for_template(conn, template_id):
        member_details = get_group_members_with_region_details(conn, group.group_id)

        member_targets: List[ExtractionTarget] = []
        member_regions: List[TemplateRegion] = []
        page_numbers: List[int] = []
        for member in member_details:
            region = region_by_id.get(member.region_id)
            if region is None:
                continue
            member_targets.append(_region_to_target(region))
            member_regions.append(region)
            page_numbers.append(region.page_number)

        targets.append(
            ExtractionTarget(
                kind=TARGET_KIND_GROUP,
                label=group.label,
                region_type=group.region_type,
                page_numbers=page_numbers,
                group_id=group.group_id,
                members=member_targets,
                member_regions=member_regions,
            )
        )

    return targets
