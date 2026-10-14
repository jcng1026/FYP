"""Template region group (combine multiple regions) editing logic (Stage 11H)."""

import sqlite3
from typing import List, Optional

from app.models.template_model import REGION_TYPE_IGNORE, get_allowed_region_types, get_region_by_id
from app.models.template_model import get_regions_for_template as get_regions_for_template_record
from app.models.template_region_group_model import (
    TemplateRegionGroup,
    TemplateRegionGroupMemberDetail,
    add_group_member,
    create_group as create_group_record,
    delete_group as delete_group_record,
    get_group_by_id,
    get_group_members_with_region_details,
    get_groups_for_template as get_groups_for_template_record,
    update_group as update_group_record,
    update_member_order as update_member_order_record,
)
from app.services.template_service import _validate_label_format, get_owned_template

MIN_GROUP_MEMBERS = 2


def _check_group_label_is_unique(
    conn: sqlite3.Connection, template_id: int, label: str, exclude_group_id: Optional[int] = None
) -> None:
    """Raise ValueError if label is already used by a region or by another
    group in template_id (case-insensitive). exclude_group_id lets editing
    a group keep its own existing label."""
    normalized = label.strip().lower()
    for region in get_regions_for_template_record(conn, template_id):
        if region.label.strip().lower() == normalized:
            raise ValueError("A region with this label already exists in this template.")
    for group in get_groups_for_template_record(conn, template_id):
        if group.group_id == exclude_group_id:
            continue
        if group.label.strip().lower() == normalized:
            raise ValueError("A region group with this label already exists in this template.")


def _validate_group_type(region_type: str, paper_type: str) -> None:
    # A group is itself a logical answer/question/student-id component, so
    # it cannot be typed as ignore_region even though that type is valid
    # for individual regions (Stage 11I).
    allowed_types = [rt for rt in get_allowed_region_types(paper_type) if rt != REGION_TYPE_IGNORE]
    if region_type not in allowed_types:
        raise ValueError(f"Group type must be one of: {', '.join(allowed_types)} for {paper_type}.")


def _default_member_order_key(region):
    """Default group member order: page number ascending, then the
    region's own order_index ascending, then region_id ascending as a
    stable fallback."""
    return (region.page_number, region.order_index, region.region_id)


def create_region_group(
    conn: sqlite3.Connection,
    teacher_id: int,
    template_id: int,
    label: str,
    region_type: str,
    region_ids: List[int],
    notes: str = "",
) -> TemplateRegionGroup:
    """Combine 2+ existing regions (which may span different pages, and may
    mix rectangle and polygon shapes) into a new named, typed region group.

    Raises ValueError if the template doesn't exist or isn't owned by
    teacher_id, the label is empty/unsafe/too long/already used by a region
    or another group in this template, the type isn't valid for the
    template's paper type, fewer than MIN_GROUP_MEMBERS distinct regions
    were selected, a selected region doesn't belong to this template, or any
    selected region is an ignore_region (Stage 11I - ignore regions are
    exclusion masks, not answer/question/student-id components, so they
    cannot be combined into a logical answer group).
    """
    template = get_owned_template(conn, teacher_id, template_id)

    label = _validate_label_format(label)
    _validate_group_type(region_type, template.paper_type)

    unique_ids = list(dict.fromkeys(region_ids))
    if len(unique_ids) < MIN_GROUP_MEMBERS:
        raise ValueError(f"A region group needs at least {MIN_GROUP_MEMBERS} selected regions.")

    regions = []
    for region_id in unique_ids:
        region = get_region_by_id(conn, region_id)
        if region is None or region.template_id != template_id:
            raise ValueError("One or more selected regions could not be found in this template.")
        if region.region_type == REGION_TYPE_IGNORE:
            raise ValueError("Ignore regions cannot be added to region groups.")
        regions.append(region)

    _check_group_label_is_unique(conn, template_id, label)

    ordered_regions = sorted(regions, key=_default_member_order_key)

    group = create_group_record(conn, template_id, label, region_type, notes.strip() or None)
    for member_order, region in enumerate(ordered_regions, start=1):
        add_group_member(conn, group.group_id, region.region_id, member_order)

    return group


def list_region_groups(conn: sqlite3.Connection, teacher_id: int, template_id: int) -> List[TemplateRegionGroup]:
    get_owned_template(conn, teacher_id, template_id)
    return get_groups_for_template_record(conn, template_id)


def get_region_group(conn: sqlite3.Connection, teacher_id: int, group_id: int) -> TemplateRegionGroup:
    """Return group_id if it exists and belongs to a template owned by
    teacher_id. Raises ValueError otherwise."""
    group = get_group_by_id(conn, group_id)
    if group is None:
        raise ValueError("Region group not found.")
    get_owned_template(conn, teacher_id, group.template_id)
    return group


def list_group_members(
    conn: sqlite3.Connection, teacher_id: int, group_id: int
) -> List[TemplateRegionGroupMemberDetail]:
    group = get_region_group(conn, teacher_id, group_id)
    return get_group_members_with_region_details(conn, group.group_id)


def update_region_group(
    conn: sqlite3.Connection,
    teacher_id: int,
    group_id: int,
    label: str,
    region_type: str,
    notes: str = "",
) -> TemplateRegionGroup:
    """Update a group's label/type/notes only - membership and order are
    unaffected. Raises ValueError for the same reasons as
    create_region_group's label/type validation (keeping a group's own
    existing label is allowed, but renaming it to another region's or
    group's label is not)."""
    group = get_region_group(conn, teacher_id, group_id)
    template = get_owned_template(conn, teacher_id, group.template_id)

    label = _validate_label_format(label)
    _validate_group_type(region_type, template.paper_type)
    _check_group_label_is_unique(conn, group.template_id, label, exclude_group_id=group_id)

    update_group_record(conn, group_id, label, region_type, notes.strip() or None)
    return get_group_by_id(conn, group_id)


def delete_region_group(conn: sqlite3.Connection, teacher_id: int, group_id: int) -> None:
    """Delete a region group. Its member regions are never deleted - only
    the group and its membership links are removed."""
    group = get_region_group(conn, teacher_id, group_id)
    delete_group_record(conn, group.group_id)


def move_group_member(conn: sqlite3.Connection, teacher_id: int, group_id: int, region_id: int, direction: str) -> None:
    """Move a group member up or down one position by swapping member_order
    with its immediate neighbor in the current stored order. A no-op if the
    member is already at that end. Raises ValueError if direction isn't
    "up"/"down" or region_id isn't a member of this group."""
    if direction not in ("up", "down"):
        raise ValueError("Direction must be 'up' or 'down'.")

    group = get_region_group(conn, teacher_id, group_id)
    members = get_group_members_with_region_details(conn, group.group_id)
    index = next((i for i, m in enumerate(members) if m.region_id == region_id), None)
    if index is None:
        raise ValueError("This region is not a member of the selected group.")

    neighbor_index = index - 1 if direction == "up" else index + 1
    if neighbor_index < 0 or neighbor_index >= len(members):
        return

    current = members[index]
    neighbor = members[neighbor_index]
    update_member_order_record(conn, group_id, current.region_id, neighbor.member_order)
    update_member_order_record(conn, group_id, neighbor.region_id, current.member_order)
