"""Template region group data model and database access functions (Stage 11H).

A region group lets a teacher combine 2+ existing template_regions rows into
one logical unit (e.g. a multi-page answer split across regions on
different pages). Grouping is metadata-only: template_regions rows are
never modified, duplicated, or removed by creating, editing, or deleting a
group - only the group and its membership links are affected.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class TemplateRegionGroup:
    group_id: int
    template_id: int
    label: str
    region_type: str
    notes: Optional[str]
    created_at: str


@dataclass
class TemplateRegionGroupMember:
    group_id: int
    region_id: int
    member_order: int


@dataclass
class TemplateRegionGroupMemberDetail:
    """A group member joined with its region's current label/page/type, for
    display and default-ordering purposes. template_region_group_members
    rows use ON DELETE CASCADE on region_id, so a deleted member region's
    link row is removed automatically - this list will simply not include
    it, without needing any error handling here."""

    region_id: int
    label: str
    page_number: int
    region_type: Optional[str]
    shape_type: str
    member_order: int


def create_group(
    conn: sqlite3.Connection,
    template_id: int,
    label: str,
    region_type: str,
    notes: Optional[str] = None,
) -> TemplateRegionGroup:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO template_region_groups (template_id, label, region_type, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (template_id, label, region_type, notes, created_at),
    )
    conn.commit()
    return TemplateRegionGroup(
        group_id=cursor.lastrowid,
        template_id=template_id,
        label=label,
        region_type=region_type,
        notes=notes,
        created_at=created_at,
    )


def update_group(
    conn: sqlite3.Connection, group_id: int, label: str, region_type: str, notes: Optional[str] = None
) -> None:
    conn.execute(
        "UPDATE template_region_groups SET label = ?, region_type = ?, notes = ? WHERE group_id = ?",
        (label, region_type, notes, group_id),
    )
    conn.commit()


def get_group_by_id(conn: sqlite3.Connection, group_id: int) -> Optional[TemplateRegionGroup]:
    row = conn.execute(
        "SELECT group_id, template_id, label, region_type, notes, created_at "
        "FROM template_region_groups WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if row is None:
        return None
    return TemplateRegionGroup(**dict(row))


def get_groups_for_template(conn: sqlite3.Connection, template_id: int) -> List[TemplateRegionGroup]:
    rows = conn.execute(
        "SELECT group_id, template_id, label, region_type, notes, created_at "
        "FROM template_region_groups WHERE template_id = ? ORDER BY created_at, group_id",
        (template_id,),
    ).fetchall()
    return [TemplateRegionGroup(**dict(row)) for row in rows]


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    """Delete a region group. ON DELETE CASCADE removes its membership link
    rows only - the member template_regions rows themselves are untouched."""
    conn.execute("DELETE FROM template_region_groups WHERE group_id = ?", (group_id,))
    conn.commit()


def add_group_member(
    conn: sqlite3.Connection, group_id: int, region_id: int, member_order: int
) -> TemplateRegionGroupMember:
    conn.execute(
        "INSERT INTO template_region_group_members (group_id, region_id, member_order) VALUES (?, ?, ?)",
        (group_id, region_id, member_order),
    )
    conn.commit()
    return TemplateRegionGroupMember(group_id=group_id, region_id=region_id, member_order=member_order)


def update_member_order(conn: sqlite3.Connection, group_id: int, region_id: int, member_order: int) -> None:
    conn.execute(
        "UPDATE template_region_group_members SET member_order = ? WHERE group_id = ? AND region_id = ?",
        (member_order, group_id, region_id),
    )
    conn.commit()


def get_members_for_group(conn: sqlite3.Connection, group_id: int) -> List[TemplateRegionGroupMember]:
    rows = conn.execute(
        "SELECT group_id, region_id, member_order FROM template_region_group_members "
        "WHERE group_id = ? ORDER BY member_order",
        (group_id,),
    ).fetchall()
    return [TemplateRegionGroupMember(**dict(row)) for row in rows]


def get_group_members_with_region_details(
    conn: sqlite3.Connection, group_id: int
) -> List[TemplateRegionGroupMemberDetail]:
    rows = conn.execute(
        """
        SELECT grm.region_id, tr.label, tr.page_number, tr.region_type, tr.shape_type, grm.member_order
        FROM template_region_group_members grm
        JOIN template_regions tr ON tr.region_id = grm.region_id
        WHERE grm.group_id = ?
        ORDER BY grm.member_order
        """,
        (group_id,),
    ).fetchall()
    return [TemplateRegionGroupMemberDetail(**dict(row)) for row in rows]
