"""Shared formal display-code generation/validation (Stage 10C).

teacher_code (TN0001, TN0002, ...) and student_code (TP0001, TP0002, ...)
are separate, auto-generated identifiers - distinct from the internal
user_id and, for students, from the manually-typed username. Both follow
the same prefix + zero-padded sequential number scheme, so the generation
and format-validation logic is shared here between
app/services/user_service.py (teachers) and app/services/student_service.py
(students).
"""

import sqlite3

TEACHER_CODE_PREFIX = "TN"
STUDENT_CODE_PREFIX = "TP"
CODE_DIGIT_WIDTH = 4


def _max_existing_code_number(conn: sqlite3.Connection, column: str, prefix: str) -> int:
    rows = conn.execute(f"SELECT {column} FROM users WHERE {column} IS NOT NULL").fetchall()
    max_number = 0
    for row in rows:
        code = row[0]
        suffix = code[len(prefix):] if code and code.startswith(prefix) else ""
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return max_number


def generate_next_code(conn: sqlite3.Connection, column: str, prefix: str) -> str:
    """Return the next sequential prefix+code (e.g. 'TN0003'), one higher
    than the largest existing numeric suffix already stored in column."""
    next_number = _max_existing_code_number(conn, column, prefix) + 1
    return f"{prefix}{next_number:0{CODE_DIGIT_WIDTH}d}"


def is_valid_code_format(code: str, prefix: str) -> bool:
    """Return True if code looks like prefix followed by one or more
    digits (e.g. 'TN0001'). Used for validating a manually-entered code -
    foundation for a future Admin edit flow, not called by any UI yet."""
    if not code or not code.startswith(prefix):
        return False
    suffix = code[len(prefix):]
    return suffix.isdigit() and len(suffix) > 0
