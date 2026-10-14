"""Per-teacher marking settings data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

DEFAULT_SPELLING_DEDUCTION_ENABLED = True
DEFAULT_SPELLING_DEDUCTION_POINTS = 1.0
DEFAULT_KERTAS2_PARTIAL_MARK_DEFAULT = 1.0


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class TeacherMarkingSettings:
    setting_id: int
    teacher_id: int
    spelling_deduction_enabled: bool
    spelling_deduction_points: float
    kertas2_partial_mark_default: float
    created_at: str
    updated_at: str


def _row_to_settings(row) -> TeacherMarkingSettings:
    data = dict(row)
    data["spelling_deduction_enabled"] = bool(data["spelling_deduction_enabled"])
    return TeacherMarkingSettings(**data)


def create_default_settings(conn: sqlite3.Connection, teacher_id: int) -> TeacherMarkingSettings:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO teacher_marking_settings "
        "(teacher_id, spelling_deduction_enabled, spelling_deduction_points, "
        "kertas2_partial_mark_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            teacher_id,
            1 if DEFAULT_SPELLING_DEDUCTION_ENABLED else 0,
            DEFAULT_SPELLING_DEDUCTION_POINTS,
            DEFAULT_KERTAS2_PARTIAL_MARK_DEFAULT,
            now,
            now,
        ),
    )
    conn.commit()
    return TeacherMarkingSettings(
        setting_id=cursor.lastrowid,
        teacher_id=teacher_id,
        spelling_deduction_enabled=DEFAULT_SPELLING_DEDUCTION_ENABLED,
        spelling_deduction_points=DEFAULT_SPELLING_DEDUCTION_POINTS,
        kertas2_partial_mark_default=DEFAULT_KERTAS2_PARTIAL_MARK_DEFAULT,
        created_at=now,
        updated_at=now,
    )


def get_settings_by_teacher_id(conn: sqlite3.Connection, teacher_id: int) -> Optional[TeacherMarkingSettings]:
    row = conn.execute(
        "SELECT setting_id, teacher_id, spelling_deduction_enabled, spelling_deduction_points, "
        "kertas2_partial_mark_default, created_at, updated_at "
        "FROM teacher_marking_settings WHERE teacher_id = ?",
        (teacher_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_settings(row)


def update_settings(
    conn: sqlite3.Connection,
    teacher_id: int,
    spelling_deduction_enabled: bool,
    spelling_deduction_points: float,
    kertas2_partial_mark_default: float,
) -> None:
    conn.execute(
        "UPDATE teacher_marking_settings SET spelling_deduction_enabled = ?, spelling_deduction_points = ?, "
        "kertas2_partial_mark_default = ?, updated_at = ? WHERE teacher_id = ?",
        (
            1 if spelling_deduction_enabled else 0,
            spelling_deduction_points,
            kertas2_partial_mark_default,
            _now(),
            teacher_id,
        ),
    )
    conn.commit()
