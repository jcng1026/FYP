"""Stage 12G-10 - startup and packaging readiness checks.

A single, dependency-light report of what this installation can actually do,
built on one principle: the CORE application must start and run with only its
required dependencies present. Everything AI-related is optional, and its
absence is reported as a limitation, never as an error.

Nothing here imports a heavy dependency at module load. Each optional component
is probed lazily, inside its own guard, so importing this module can never drag
in torch, paddle or a model runtime - and can never fail because one is missing.
"""
import importlib.util
import os
import platform
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# Everything the core application genuinely needs to start.
REQUIRED_MODULES = (
    ("PySide6", "the desktop interface"),
    ("bcrypt", "password hashing"),
    ("pymupdf", "reading question and answer PDFs"),
    ("PIL", "image handling"),
    ("cv2", "page image processing"),
)

# Optional components. A missing one limits a feature; it never stops the app.
OPTIONAL_MODULES = (
    ("paddleocr", "handwriting and text extraction",
     "Answers must be typed in manually until this is installed."),
    ("torch", "Core AI 1 scoring and Core AI 2 region detection",
     "AI draft scores and region proposals are unavailable; marking is manual."),
    ("transformers", "Core AI 1 model loading",
     "Core AI 1 draft scoring is unavailable; marking is manual."),
    ("ultralytics", "Core AI 2 region detection",
     "Core AI 2 region proposals are unavailable; regions are drawn manually."),
)

MINIMUM_PYTHON = (3, 10)

STATUS_READY = "ready"
STATUS_LIMITED = "limited"
STATUS_BLOCKED = "blocked"


@dataclass
class ComponentReport:
    name: str
    purpose: str
    available: bool
    required: bool
    detail: str = ""


@dataclass
class RuntimeReport:
    status: str
    python_version: str
    platform_name: str
    database_path: Optional[str]
    database_writable: bool
    components: List[ComponentReport] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    @property
    def can_start(self) -> bool:
        return self.status != STATUS_BLOCKED

    def summary_lines(self) -> List[str]:
        lines = [
            f"Status: {self.status}",
            f"Python: {self.python_version} on {self.platform_name}",
            f"Database: {self.database_path or '-'} "
            f"({'writable' if self.database_writable else 'NOT writable'})",
            "",
        ]
        for component in self.components:
            mark = "OK" if component.available else ("MISSING" if component.required else "absent")
            lines.append(f"[{mark}] {component.name} - {component.purpose}"
                         + (f" ({component.detail})" if component.detail else ""))
        if self.blockers:
            lines.extend(["", "Blockers:"] + [f"- {b}" for b in self.blockers])
        if self.limitations:
            lines.extend(["", "Limitations (the application still runs):"]
                         + [f"- {l}" for l in self.limitations])
        return lines


def module_available(module_name: str) -> bool:
    """Whether a module could be imported, WITHOUT importing it. find_spec does
    not execute the module, so probing torch or paddle costs nothing and cannot
    fail on a broken optional install."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _database_writable(database_path: Optional[str]) -> bool:
    if not database_path:
        return False
    directory = os.path.dirname(os.path.abspath(database_path)) or "."
    if os.path.exists(database_path):
        return os.access(database_path, os.W_OK)
    return os.path.isdir(directory) and os.access(directory, os.W_OK)


def inspect_runtime(database_path: Optional[str] = None) -> RuntimeReport:
    """A full readiness report. Never raises and never imports a heavy
    dependency."""
    if database_path is None:
        try:
            from app.database.db import DB_PATH
            database_path = str(DB_PATH)
        except Exception:
            database_path = None

    components: List[ComponentReport] = []
    blockers: List[str] = []
    limitations: List[str] = []

    if sys.version_info < MINIMUM_PYTHON:
        blockers.append(
            f"Python {'.'.join(str(v) for v in MINIMUM_PYTHON)} or newer is required.")

    for module_name, purpose in REQUIRED_MODULES:
        available = module_available(module_name)
        components.append(ComponentReport(module_name, purpose, available, required=True))
        if not available:
            blockers.append(f"{module_name} is required for {purpose} and is not installed.")

    for module_name, purpose, consequence in OPTIONAL_MODULES:
        available = module_available(module_name)
        components.append(ComponentReport(module_name, purpose, available, required=False,
                                          detail="" if available else consequence))
        if not available:
            limitations.append(f"{module_name} is not installed. {consequence}")

    writable = _database_writable(database_path)
    if not writable:
        blockers.append("The application database location is not writable.")

    status = STATUS_BLOCKED if blockers else (STATUS_LIMITED if limitations else STATUS_READY)
    return RuntimeReport(
        status=status, python_version=platform.python_version(),
        platform_name=f"{platform.system()} {platform.release()}",
        database_path=database_path, database_writable=writable, components=components,
        blockers=blockers, limitations=limitations)


def verify_database_schema(conn) -> List[str]:
    """Confirm the tables this application version needs actually exist.
    Returns the missing ones; an empty list means the schema is current."""
    expected = (
        "users", "subject_profiles", "main_marking_sessions", "main_marking_answer_files",
        "subject_profile_marked_answers", "subject_profile_attempt_reviews",
        "local_ai_settings", "ai_admin_audit", "core_ai2_region_proposals",
        "core_ai1_answer_drafts",
    )
    try:
        present = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    except sqlite3.Error:
        return list(expected)
    return [name for name in expected if name not in present]


def startup_self_check(conn=None, database_path: Optional[str] = None) -> dict:
    """The check main() runs at startup. It reports; it never prevents the
    application from opening unless the core itself cannot function."""
    report = inspect_runtime(database_path)
    missing_tables: List[str] = []
    if conn is not None:
        missing_tables = verify_database_schema(conn)
        if missing_tables:
            report.blockers.append(
                "The database is missing required tables: " + ", ".join(missing_tables))
            report.status = STATUS_BLOCKED
    return {
        "report": report,
        "missing_tables": missing_tables,
        "can_start": report.can_start,
        "summary": "\n".join(report.summary_lines()),
    }
