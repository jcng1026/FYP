"""Portable data-path repair - the start-up self-heal that makes the project
folder movable.

Every file path in the database is stored ABSOLUTE (a subject profile's question
paper, each preprocessed page image, every marked PDF...). Copying the project
to another PC, renaming the root folder, or moving it to another drive therefore
leaves those paths pointing at a location that no longer exists, and the
application reports things like "The processed page image could not be
rendered" even though the files are present.

This module repairs that once, at start-up, by rewriting the single BASE folder
that every stored path shares to wherever the project actually lives now.

Why a shared base rather than "point everything at the data folder": stored
paths can legitimately reference more than one data root (for example a
packaged build whose database still refers to the development data folder
alongside its own). Those roots all sit inside one common parent, and they move
together, so rewriting that common parent repairs every root at once - whereas
forcing everything to the current data folder would break the paths whose files
live under a different root.

Deliberately conservative:
  * does nothing unless stored paths are actually broken (cheap probe first);
  * only rewrites the ONE base prefix shared by every stored root;
  * never raises - a failed repair must never stop the application starting.
"""
import os
import re
import sqlite3
from typing import Dict, List, Optional, Set

from app.database.db import PROJECT_ROOT

# Every stored data path contains "...<root>\data\..." - the segment that lets a
# stored root be recovered from the value itself.
_MARKER = os.sep + "data" + os.sep

# A stored root must be matched as a real absolute path, not merely "everything
# before the first \data\". Several columns hold serialised JSON whose OCR text
# runs for thousands of characters before an embedded "image_path", so anchoring
# on a drive letter and stopping at quotes is what keeps prose out of the roots.
_ROOT_PATTERN = re.compile(
    r"[A-Za-z]:(?:\\[^\\/:*?\"'<>|\r\n]+)+?(?=\\data\\)", re.IGNORECASE)

# Cheap probe: a few columns that always hold absolute paths when data exists.
_PROBE_COLUMNS = (
    ("subject_profiles", "question_paper_path"),
    ("subject_profiles", "answer_scheme_path"),
    ("main_marking_answer_files", "file_path"),
    ("revision_materials", "question_paper_path"),
    ("answer_templates", "sample_file_path"),
)


def _tables(conn: sqlite3.Connection) -> List[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    except Exception:
        return []


def _needs_repair(conn: sqlite3.Connection) -> bool:
    """True when a sampled stored path points into a data folder that is not
    there any more.

    The test is on the ROOT, not the individual file: a single missing file is
    ordinary (the teacher deleted that material), whereas a stored root whose
    'data' folder does not exist is exactly what moving, renaming or copying the
    project produces. Testing the file instead would run the full scan on every
    launch for any database that has ever had something deleted.
    """
    for table, column in _PROBE_COLUMNS:
        try:
            rows = conn.execute(
                f'SELECT CAST("{column}" AS TEXT) FROM "{table}" '
                f'WHERE CAST("{column}" AS TEXT) LIKE ? LIMIT 5', ("%" + _MARKER + "%",)).fetchall()
        except Exception:
            continue
        for (value,) in rows:
            if not value:
                continue
            for match in _ROOT_PATTERN.finditer(value.replace("\\\\", "\\")):
                if not os.path.isdir(os.path.join(match.group(0), "data")):
                    return True
    return False


def _stored_roots(conn: sqlite3.Connection) -> Set[str]:
    """Every distinct '<root>' appearing as '<root>\\data\\...' in the database."""
    roots: Set[str] = set()
    for table in _tables(conn):
        for column in _columns(conn, table):
            try:
                rows = conn.execute(
                    f'SELECT DISTINCT CAST("{column}" AS TEXT) FROM "{table}" '
                    f'WHERE CAST("{column}" AS TEXT) LIKE ?', ("%" + _MARKER + "%",)).fetchall()
            except Exception:
                continue
            for (value,) in rows:
                if not value:
                    continue
                # Un-escape first, so a path written into JSON with doubled
                # backslashes yields the same root as a plainly stored one.
                for match in _ROOT_PATTERN.finditer(value.replace("\\\\", "\\")):
                    roots.add(match.group(0))
    return roots


def _parts(path: str) -> List[str]:
    return [p for p in os.path.normpath(path).split(os.sep) if p]


def _common_base(roots: Set[str]) -> Optional[str]:
    """Longest path prefix shared by every stored root."""
    listed = [_parts(r) for r in roots if r]
    if not listed:
        return None
    common = listed[0]
    for other in listed[1:]:
        limit = 0
        while limit < min(len(common), len(other)) and common[limit].lower() == other[limit].lower():
            limit += 1
        common = common[:limit]
    if not common:
        return None
    return os.sep.join(common)


def _current_base(old_base: str, roots: Set[str]) -> Optional[str]:
    """Where old_base lives now, derived from this run's own PROJECT_ROOT.

    Each stored root sits at some relative offset under old_base (for a packaged
    build, typically 'dist<sep>MarkAssist'). The root whose offset matches the
    tail of PROJECT_ROOT identifies the move, and stripping that offset gives
    the new base. The longest matching offset wins - it is the most specific.
    """
    current = os.path.normpath(str(PROJECT_ROOT))
    best: Optional[tuple] = None
    for root in roots:
        try:
            relative = os.path.relpath(root, old_base)
        except Exception:
            continue
        relative = "" if relative == "." else relative
        if not relative:
            candidate = current
        else:
            tail = os.sep + relative
            if not current.lower().endswith(tail.lower()):
                continue
            candidate = current[: len(current) - len(tail)]
        if candidate and (best is None or len(relative) > best[0]):
            best = (len(relative), candidate)
    return best[1] if best else None


def _rewrite_base(conn: sqlite3.Connection, old_base: str, new_base: str) -> int:
    """Replace old_base with new_base in every text column. Both the plain and
    the JSON-escaped (doubled-backslash) spelling are handled, because some
    columns store paths inside serialised JSON."""
    pairs = [
        (old_base.replace("\\", "\\\\"), new_base.replace("\\", "\\\\")),
        (old_base, new_base),
    ]
    changed = 0
    for table in _tables(conn):
        for column in _columns(conn, table):
            for old, new in pairs:
                try:
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE CAST("{column}" AS TEXT) LIKE ?',
                        (f"%{old}%",)).fetchone()[0]
                    if count:
                        conn.execute(
                            f'UPDATE "{table}" SET "{column}" = '
                            f'REPLACE(CAST("{column}" AS TEXT), ?, ?) '
                            f'WHERE CAST("{column}" AS TEXT) LIKE ?', (old, new, f"%{old}%"))
                        changed += count
                except Exception:
                    continue
    conn.commit()
    return changed


def repair_data_paths(conn: sqlite3.Connection) -> Dict[str, object]:
    """Repair stored absolute paths after the project folder was moved, renamed
    or copied to another machine. Returns a summary; never raises."""
    try:
        if not _needs_repair(conn):
            return {"repaired": 0, "reason": "paths_ok"}
        roots = _stored_roots(conn)
        if not roots:
            return {"repaired": 0, "reason": "no_stored_paths"}
        old_base = _common_base(roots)
        if not old_base:
            return {"repaired": 0, "reason": "no_common_base"}
        new_base = _current_base(old_base, roots)
        if not new_base:
            return {"repaired": 0, "reason": "current_location_not_derivable"}
        if os.path.normcase(os.path.normpath(old_base)) == os.path.normcase(os.path.normpath(new_base)):
            return {"repaired": 0, "reason": "already_current"}
        changed = _rewrite_base(conn, old_base, new_base)
        return {"repaired": changed, "old_base": old_base, "new_base": new_base}
    except Exception as exc:  # never block start-up
        return {"repaired": 0, "reason": f"error: {type(exc).__name__}: {exc}"}
