"""Entry point for the English Grading System prototype (Stage 1)."""

import sys


def _dispatch_worker_if_requested() -> None:
    """Frozen-build worker dispatch. In a PyInstaller build the hang-safe
    marking workers cannot be launched as `python worker.py` (there is no
    python.exe and no loose script), so the GUI relaunches THIS executable
    with `--run-worker <name> <args...>`. Detect that here - before importing
    Qt or showing any window - run the worker's main(), and exit."""
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-worker":
        worker_name = sys.argv[2]
        # Re-shape argv so the worker's main() sees [prog, arg1, arg2, arg3].
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        if worker_name == "subject_profile_marking":
            from app.workers.subject_profile_marking_worker_process import main as worker_main
        elif worker_name == "mark_answer_file":
            from app.workers.mark_answer_file_worker_process import main as worker_main
        else:
            print(f"ERROR|Unknown worker: {worker_name}", flush=True)
            sys.exit(2)
        worker_main()
        sys.exit(0)


def _run_selfcheck_if_requested() -> None:
    """`MarkAssist.exe --selfcheck` verifies the whole bundled stack from
    inside the frozen process and prints a machine-readable report: data
    root, database, the active Core AI 1 / Core AI 2 models (torch +
    transformers + ultralytics all import and load), and the Ollama feedback
    runtime configuration. Exits 0 when the core is usable."""
    if not (len(sys.argv) >= 2 and sys.argv[1] == "--selfcheck"):
        return
    lines = []
    ok = True

    def report(key, value):
        lines.append(f"SELFCHECK|{key}|{value}")

    try:
        from app.database.db import DATA_DIR, get_connection
        report("data_root", DATA_DIR)
        report("data_root_exists", DATA_DIR.exists())
        conn = get_connection()
        try:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            report("db_users", users)
            row = conn.execute(
                "SELECT feedback_adapter, feedback_endpoint, feedback_model_name "
                "FROM local_ai_settings WHERE feedback_adapter IS NOT NULL "
                "AND feedback_adapter != 'none' LIMIT 1").fetchone()
            report("ollama_config", tuple(row) if row else "none")
            from app.database.seed import DEFAULT_DEVELOPER_USERNAME
            from app.models.user_model import get_user_by_username
            from app.services import ai_models_job_service as jobs
            admin = get_user_by_username(conn, DEFAULT_DEVELOPER_USERNAME)
            for fam in ("core_ai1", "core_ai2"):
                try:
                    active = jobs.get_active_model(conn, admin, family=fam)
                    report(f"{fam}_active", active.version if active else "none")
                except Exception as exc:  # noqa: BLE001
                    report(f"{fam}_active", f"ERROR: {exc}")
                    ok = False
        finally:
            conn.close()
        for mod in ("torch", "transformers", "ultralytics", "cv2", "fitz"):
            try:
                m = __import__(mod)
                report(f"import_{mod}", getattr(m, "__version__", "ok"))
            except Exception as exc:  # noqa: BLE001
                report(f"import_{mod}", f"ERROR: {exc}")
                ok = False
        # OCR (PaddleOCR) powers the marking pipeline. Actually CONSTRUCT the
        # engine the way the marking UI does - importing paddleocr succeeds even
        # when a frozen build is missing dependency metadata, but constructing
        # the pipeline is where that surfaces ("dependency error during pipeline
        # creation"). This is the true test of the OCR bundle.
        try:
            from app.utils.ocr_engine import get_default_engine
            get_default_engine()
            report("ocr_engine_init", "ok")
        except Exception as exc:  # noqa: BLE001
            report("ocr_engine_init", f"ERROR: {exc}")
            ok = False
    except Exception as exc:  # noqa: BLE001
        report("fatal", exc)
        ok = False
    report("result", "OK" if ok else "FAIL")
    print("\n".join(lines), flush=True)
    sys.exit(0 if ok else 1)


_dispatch_worker_if_requested()
_run_selfcheck_if_requested()

from PySide6.QtWidgets import QApplication

from app.database.db import get_connection
from app.database.schema import init_schema
from app.database.seed import seed_default_developer
from app.services.student_service import backfill_student_codes
from app.services.user_service import backfill_teacher_codes
from app.ui.styles import STYLESHEET, base_font


def initialize_database() -> None:
    conn = get_connection()
    try:
        init_schema(conn)
        seed_default_developer(conn)
        backfill_teacher_codes(conn)
        backfill_student_codes(conn)
        # Portability self-heal: stored file paths are absolute, so moving,
        # renaming or copying the project folder (e.g. handing it to another
        # PC) leaves them pointing nowhere. Repair them once, here. Never
        # fatal - a failed repair must not stop the application starting.
        from app.services.data_path_repair_service import repair_data_paths

        repair = repair_data_paths(conn)
        if repair.get("repaired"):
            print(f"MarkAssist: the project folder moved - repaired "
                  f"{repair['repaired']} stored file path(s).")
            print(f"  {repair.get('old_base')}  ->  {repair.get('new_base')}")
    finally:
        conn.close()


def run_startup_check() -> bool:
    """Stage 12G-10: report what this installation can actually do before the
    interface opens. A missing OPTIONAL AI component is printed as a limitation
    and the application continues normally; only a genuinely unusable core -
    a missing required dependency or an unwritable database - stops it."""
    from app.services.runtime_environment_service import startup_self_check

    conn = get_connection()
    try:
        result = startup_self_check(conn)
    finally:
        conn.close()
    report = result["report"]
    if report.limitations:
        print("English Grading System - optional components not installed:")
        for limitation in report.limitations:
            print(f"  - {limitation}")
        print("  Manual marking, review, finalisation and results are unaffected.")
    if not result["can_start"]:
        print("English Grading System cannot start:")
        for blocker in report.blockers:
            print(f"  - {blocker}")
    return result["can_start"]


def recover_interrupted_ai_jobs() -> int:
    """Stage 12G-11: abandoned training jobs from a previous run become
    'interrupted' exactly once, at startup, before any worker is scheduled.
    They are never silently resumed. A failure here never stops the
    application - AI is optional, marking is not."""
    from app.database.seed import DEFAULT_DEVELOPER_USERNAME
    from app.models.user_model import get_user_by_username
    from app.services import ai_models_job_service as jobs

    try:
        conn = get_connection()
    except Exception:
        return 0  # even opening the database must not stop startup here
    try:
        admin = get_user_by_username(conn, DEFAULT_DEVELOPER_USERNAME)
        if admin is None:
            return 0
        recovered = 0
        for family in ("core_ai1", "core_ai2"):
            try:
                recovered += len(jobs.recover_interrupted_jobs(conn, admin, family=family))
            except Exception:
                continue
        if recovered:
            print(f"English Grading System - {recovered} interrupted AI training job(s) "
                  "were marked interrupted. They were not resumed automatically.")
        return recovered
    except Exception:
        return 0
    finally:
        conn.close()


def main() -> None:
    # The splash appears first and the real start-up work runs behind it -
    # each set_status line below is the actual step in progress, so the
    # tick-draws-itself animation masks latency that exists anyway.
    app = QApplication(sys.argv)
    app.setFont(base_font())
    app.setStyleSheet(STYLESHEET)
    from app.ui import brand
    app.setWindowIcon(brand.app_icon())

    from app.ui.splash_screen import SplashScreen
    splash = SplashScreen()
    splash.show()
    app.processEvents()

    splash.set_status("Opening database...")
    app.processEvents()
    initialize_database()

    splash.set_status("Checking components...")
    app.processEvents()
    if not run_startup_check():
        splash.close()
        sys.exit(1)
    recover_interrupted_ai_jobs()

    # Best-effort: bring up the local Ollama server so natural-language feedback
    # is ready. Non-blocking - a missing/failed Ollama never delays start-up.
    from app.utils.ollama_launcher import ensure_ollama_running
    ollama_status = ensure_ollama_running()

    splash.set_status("Loading interface...")
    app.processEvents()
    # Deferred import: this pulls in every dashboard module - the heaviest
    # part of start-up - so it belongs behind the splash, not before it.
    from app.ui.login_window import LoginWindow

    window = LoginWindow()

    def _on_ready() -> None:
        window.show()
        if ollama_status == "not_installed":
            _warn_ollama_not_installed(window)

    splash.set_status("Ready")
    splash.finish(_on_ready)
    sys.exit(app.exec())


def _warn_ollama_not_installed(parent) -> None:
    """One-time heads-up when Ollama is absent: AI feedback will use the
    built-in offline templates until Ollama is installed. Marking, review and
    results are unaffected."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    def show() -> None:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Ollama not found")
        box.setText("Ollama is not installed, so AI-generated feedback is unavailable.")
        box.setInformativeText(
            "MarkAssist will still work fully - Kertas 2 feedback falls back to the "
            "built-in offline templates. To enable natural-language AI feedback, install "
            "Ollama from https://ollama.com and pull a model, e.g.  ollama pull llama3.2")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    QTimer.singleShot(500, show)  # after the window has painted


if __name__ == "__main__":
    main()
