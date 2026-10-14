"""SQLite connection helper."""

import os
import sqlite3
import sys
from pathlib import Path

# Marking Fix Follow-up: ENGLISH_GRADING_SYSTEM_DATA_ROOT lets an isolated
# test point a spawned subprocess (see app.workers.subject_profile_
# marking_worker_process, launched via QProcess - a genuinely separate OS
# process that does NOT inherit a parent test's monkeypatched module
# attributes) at a throwaway data/ tree, never the real one - unset in
# production, where this is identical to the previous hardcoded path.
# Shared with app.utils.file_storage's own PROJECT_ROOT override so the
# database and any files a test writes land under the SAME isolated root.
_env_data_root = os.environ.get("ENGLISH_GRADING_SYSTEM_DATA_ROOT")
if _env_data_root:
    PROJECT_ROOT = Path(_env_data_root).resolve()
elif getattr(sys, "frozen", False):
    # Frozen build: keep data next to the executable so the DB and models
    # are writable and persist between runs (not inside the bundle/_MEIPASS).
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection, creating the data folder if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
