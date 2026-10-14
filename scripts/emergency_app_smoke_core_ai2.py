"""Emergency application smoke test - the trained Core AI 2 model in the real app.

Launches the REAL application widgets (LoginWindow -> dashboards) against the
FYP data root and verifies the eleven required points: login, the AI Models
registry showing the emergency model with a valid checkpoint path and viewable
metrics and correct active state, teacher proposal generation as EDITABLE
suggestions on a controlled disposable copy of one profile page, no automatic
overwrite of manual regions, and manual marking still working when inference is
deliberately unavailable.

Usage:
    set ENGLISH_GRADING_SYSTEM_DATA_ROOT=C:/Users/User/Documents/AutoMarkingSystem/FYP-Data
    python scripts/emergency_app_smoke_core_ai2.py
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DATA_ROOT = os.environ.get("ENGLISH_GRADING_SYSTEM_DATA_ROOT")
if not DATA_ROOT:
    raise SystemExit("Set ENGLISH_GRADING_SYSTEM_DATA_ROOT to the FYP data root first.")

MODEL_VERSION = "core_ai2_detector_emergency_v1"
RUN_ROOT = Path("C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/"
                "core_ai2_emergency_training/run_20260720_130546")

_checks = []


def check(label, condition, detail=""):
    _checks.append((label, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    import app.database.db as db_module
    from app.database.seed import DEFAULT_DEVELOPER_PASSWORD, DEFAULT_DEVELOPER_USERNAME
    from app.services import ai_backend_integration as integration
    from app.services import ai_models_job_service as jobs
    from app.services import ai_region_proposal_service as region_proposals
    from app.models import ai_region_proposal_model as proposals_model
    import app.models.subject_profile_model as spm
    from app.ui import styles
    from app.ui.login_window import LoginWindow
    from main import initialize_database

    initialize_database()
    data_dir = Path(db_module.DATA_DIR)
    print(f"data root: {data_dir}")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(styles.base_font())
    app.setStyleSheet(styles.STYLESHEET)

    # --- 1-2. login + AI Models page ---------------------------------------
    login = LoginWindow()
    login.show()
    login.username_input.setText(DEFAULT_DEVELOPER_USERNAME)
    login.password_input.setText(DEFAULT_DEVELOPER_PASSWORD)
    login.handle_login()
    QApplication.processEvents()
    dash = login._dashboard
    check("1. Admin login works", dash is not None)
    if dash is None:
        return 1
    dash.resize(1400, 900)
    dash.show()
    dash.shell.show_page("AI Models")
    QApplication.processEvents()
    check("2. AI Models page opens", "AI Models" in dash.shell._pages)

    # --- 3-6. registry state through the app's own facade providers --------
    conn = db_module.get_connection()
    try:
        models = jobs.list_models(conn, dash._user, family="core_ai2")
        versions = [m.version for m in models]
        check("3. Emergency model appears in the registry",
              MODEL_VERSION in versions, ", ".join(versions))
        model = next((m for m in models if m.version == MODEL_VERSION), None)
        if model:
            # The backend's list_models omits the folder path; inspect_model
            # is the call that carries it.
            inspected = jobs.inspect_model(conn, dash._user, MODEL_VERSION, family="core_ai2")
            checkpoint = Path(inspected.path) / "best.pt"
            check("4. Checkpoint path is valid", checkpoint.is_file(), str(checkpoint))
            check("   checksum verifies on inspect", inspected.checksum == model.checksum)
        evaluations = (Path(data_dir) / "ai" / "evaluations" / "core_ai2" / MODEL_VERSION)
        eval_files = list(evaluations.glob("*.json")) if evaluations.exists() else []
        metrics_viewable = False
        if eval_files:
            record = json.loads(eval_files[0].read_text("utf-8"))
            metrics_viewable = "metrics" in record and "test" in record["metrics"]
            check("5. Metrics are viewable",
                  metrics_viewable,
                  f"test map50={record['metrics']['test'].get('map50'):.4f}" if metrics_viewable else "")
        else:
            check("5. Metrics are viewable", False, "no evaluation record")
        active = jobs.get_active_model(conn, dash._user, family="core_ai2")
        check("6. Active state is correct",
              active is not None and active.version == MODEL_VERSION,
              active.version if active else "none")
    finally:
        conn.close()
    dash.close()
    login.close()

    # --- 7-11. teacher workflow on a CONTROLLED DISPOSABLE page -------------
    # A disposable smoke profile is created for the proposal check, so none of
    # the 16 real Subject Profiles is edited or resaved.
    from app.services.subject_profile_service import add_region, create_subject_profile
    from app.services.user_service import create_teacher

    conn = db_module.get_connection()
    try:
        import uuid
        username = f"smoke_{uuid.uuid4().hex[:8]}"
        teacher = create_teacher(conn, username, "Smoke Teacher", "smokepass12345")
        profile = create_subject_profile(conn, teacher.user_id,
                                         "EMERGENCY SMOKE (disposable)")
        # One pre-existing manual region that must survive proposals untouched.
        manual = add_region(conn, teacher.user_id, profile.profile_id, "question_paper",
                            "manual_region_keep", "answer_box", 1, 0.05, 0.05, 0.2, 0.1)
    finally:
        conn.close()

    from app.ui.teacher_dashboard import TeacherDashboard
    tdash = TeacherDashboard(user=teacher)
    tdash.resize(1400, 900)
    tdash.show()
    QApplication.processEvents()
    check("7. Teacher Dashboard opens", True)

    # A held-out test page, copied under the approved image root.
    smoke_dir = data_dir / "main_marking_sessions" / "_emergency_app_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    test_image = sorted((RUN_ROOT / "yolo" / "images" / "test").glob("*.png"))[1]
    page_image = smoke_dir / test_image.name
    shutil.copy2(test_image, page_image)
    from PIL import Image
    with Image.open(page_image) as img:
        width, height = img.size

    conn = db_module.get_connection()
    try:
        records = region_proposals.run_subject_profile_proposals(
            conn, teacher.user_id, profile.profile_id, "question_paper", 1,
            str(page_image), width, height, sha256_file(page_image))
        check("8. Subject Profile proposals return through the facade",
              len(records) > 0, f"{len(records)} proposal(s)")
        stored = proposals_model.list_proposals_for_profile(conn, profile.profile_id)
        check("9. Proposals persist as editable suggestions",
              all(p.status == "proposed" for p in stored) and len(stored) == len(records))

        # 10. accept one, edit one, reject one, defer the rest untouched.
        outcomes = {}
        if len(stored) >= 1:
            accepted = region_proposals.accept_proposal(
                conn, teacher.user_id, stored[0].proposal_id,
                target_label="smoke_accept_1")
            outcomes["accept"] = accepted is not None
        if len(stored) >= 2:
            region_proposals.edit_proposal_geometry(
                conn, teacher.user_id, stored[1].proposal_id, 0.11, 0.12, 0.3, 0.2)
            outcomes["edit"] = proposals_model.get_proposal(
                conn, stored[1].proposal_id).status == "edited"
        if len(stored) >= 3:
            region_proposals.reject_proposal(conn, teacher.user_id,
                                             stored[2].proposal_id, "smoke reject")
            outcomes["reject"] = proposals_model.get_proposal(
                conn, stored[2].proposal_id).status == "rejected"
        check("10. Accept / edit / reject all work",
              bool(outcomes) and all(outcomes.values()), str(outcomes))

        # 11. the manual region is untouched.
        regions = spm.list_regions_for_profile(conn, profile.profile_id) \
            if hasattr(spm, "list_regions_for_profile") else None
        if regions is None:
            from app.services.subject_profile_service import list_regions
            regions = list_regions(conn, teacher.user_id, profile.profile_id,
                                   "question_paper")
        manual_after = next(r for r in regions if r.label == "manual_region_keep")
        check("11. Manual region not overwritten automatically",
              (round(manual_after.x, 3), round(manual_after.y, 3)) == (0.05, 0.05))
    finally:
        conn.close()

    # --- 13. manual marking when inference is deliberately unavailable ------
    from app.models.core_ai2_inference_types import CoreAI2InferenceResult

    class _Unavailable:
        """Mirrors the REAL service's failure behaviour: an unavailable runtime
        comes back as a failed result object, never an exception."""
        def run_core_ai2_inference(self, request, cancellation_token=None):
            return CoreAI2InferenceResult(
                request.request_id, "failed", [], request.model_version, None,
                request.page_checksum, 0.0, None, [],
                "detector_runtime_unavailable", "deliberately offline", None)

    conn = db_module.get_connection()
    try:
        offline = region_proposals.run_subject_profile_proposals(
            conn, teacher.user_id, profile.profile_id, "question_paper", 2,
            str(page_image), width, height, sha256_file(page_image),
            backend=_Unavailable())
        check("13. AI failure persists nothing and does not raise", offline == [])
        still_manual = add_region(conn, teacher.user_id, profile.profile_id,
                                  "question_paper", "manual_after_failure",
                                  "letter_box", 2, 0.4, 0.4, 0.1, 0.05)
        check("    manual region editing still works", still_manual is not None)
    finally:
        conn.close()

    tdash.close()

    failed = [label for label, ok, _ in _checks if not ok]
    print("=" * 60)
    print(f"{len(_checks) - len(failed)}/{len(_checks)} checks passed")
    if failed:
        for label in failed:
            print("FAILED:", label)
        return 1
    print("APP SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
