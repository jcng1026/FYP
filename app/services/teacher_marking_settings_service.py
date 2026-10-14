"""Per-teacher marking settings orchestration.

Each teacher has independent marking settings (spelling deduction on/off
and its point value, plus a Kertas 2 partial-mark default for a later
stage). If a teacher has no saved settings yet, sensible defaults are
auto-provisioned on first read - this stage never touches marking/review
tables directly.
"""

import sqlite3
from typing import Optional

from app.models.teacher_marking_settings_model import (
    DEFAULT_KERTAS2_PARTIAL_MARK_DEFAULT,
    DEFAULT_SPELLING_DEDUCTION_ENABLED,
    DEFAULT_SPELLING_DEDUCTION_POINTS,
    TeacherMarkingSettings,
    create_default_settings,
    get_settings_by_teacher_id,
    update_settings,
)


def get_teacher_marking_settings(conn: sqlite3.Connection, teacher_id: int) -> TeacherMarkingSettings:
    """Return teacher_id's marking settings, creating default settings first
    if none exist yet."""
    settings = get_settings_by_teacher_id(conn, teacher_id)
    if settings is not None:
        return settings
    return create_default_settings(conn, teacher_id)


def update_teacher_marking_settings(
    conn: sqlite3.Connection,
    teacher_id: int,
    spelling_deduction_enabled: bool,
    spelling_deduction_points: float,
    kertas2_partial_mark_default: float,
) -> TeacherMarkingSettings:
    """Update teacher_id's marking settings (creating the row first if it
    doesn't exist yet).

    Raises ValueError if spelling_deduction_points or
    kertas2_partial_mark_default is negative.
    """
    if spelling_deduction_points < 0:
        raise ValueError("Spelling deduction points cannot be negative.")
    if kertas2_partial_mark_default < 0:
        raise ValueError("Kertas 2 partial mark default cannot be negative.")

    existing = get_settings_by_teacher_id(conn, teacher_id)
    if existing is None:
        create_default_settings(conn, teacher_id)

    update_settings(
        conn, teacher_id, spelling_deduction_enabled, spelling_deduction_points, kertas2_partial_mark_default
    )
    return get_settings_by_teacher_id(conn, teacher_id)


def reset_teacher_marking_settings_to_defaults(
    conn: sqlite3.Connection, teacher_id: int
) -> TeacherMarkingSettings:
    """Reset teacher_id's marking settings back to the default values."""
    return update_teacher_marking_settings(
        conn,
        teacher_id,
        DEFAULT_SPELLING_DEDUCTION_ENABLED,
        DEFAULT_SPELLING_DEDUCTION_POINTS,
        DEFAULT_KERTAS2_PARTIAL_MARK_DEFAULT,
    )
