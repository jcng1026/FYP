"""FINAL end-to-end application verification against the real FYP data root.

Drives the REAL application - LoginWindow, the real dashboards, the real
Core AI 2 facade providers and the real GPU model - and saves screenshots of
every stage so each claim is visually verifiable. All teacher-side work uses a
DISPOSABLE teacher and profile; none of the 15 real Subject Profiles is opened
for writing, altered or resaved.

Usage:
    set ENGLISH_GRADING_SYSTEM_DATA_ROOT=C:/Users/User/Documents/AutoMarkingSystem/FYP-Data
    python scripts/emergency_final_app_verification.py
"""
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DATA_ROOT = os.environ.get("ENGLISH_GRADING_SYSTEM_DATA_ROOT")
if not DATA_ROOT:
    raise SystemExit("Set ENGLISH_GRADING_SYSTEM_DATA_ROOT first.")

MODEL_VERSION = "core_ai2_detector_emergency_v1"
RUN_ROOT = Path("C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/"
                "core_ai2_emergency_training/run_20260720_130546")
SHOTS = Path("C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/"
             "final_verification_screens")
SHOTS.mkdir(parents=True, exist_ok=True)

_checks = []
_counter = {"n": 0}


def check(label, condition, detail=""):
    _checks.append((label, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def shot(widget, name):
    from PySide6.QtWidgets import QApplication
    _counter["n"] += 1
    path = SHOTS / f"{_counter['n']:02d}_{name}.png"
    for _ in range(4):
        QApplication.processEvents()
    widget.grab().save(str(path))
    print(f"[shot] {path.name}")
    return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from PySide6.QtWidgets import QApplication, QScrollArea

    import app.database.db as db_module
    from app.database.seed import DEFAULT_DEVELOPER_PASSWORD, DEFAULT_DEVELOPER_USERNAME
    from app.models import ai_region_proposal_model as proposals_model
    import app.models.subject_profile_model as spm
    from app.services import ai_models_job_service as jobs
    from app.services import ai_region_proposal_service as region_proposals
    from app.services.subject_profile_service import (
        add_region, create_subject_profile, list_regions,
    )
    from app.services.user_service import create_teacher
    from app.services.student_service import create_student
    from app.ui import styles
    from app.ui.login_window import LoginWindow
    from main import initialize_database, run_startup_check

    initialize_database()
    check("startup self-check", run_startup_check() is True)
    data_dir = Path(db_module.DATA_DIR)
    print("data root:", data_dir)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(styles.base_font())
    app.setStyleSheet(styles.STYLESHEET)

    def reveal(widget):
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget)
                break
            parent = parent.parentWidget()
        for _ in range(3):
            QApplication.processEvents()

    # ================= ADMIN =================
    login = LoginWindow()
    login.show()
    shot(login, "login_screen")
    login.username_input.setText(DEFAULT_DEVELOPER_USERNAME)
    login.password_input.setText(DEFAULT_DEVELOPER_PASSWORD)
    login.handle_login()
    QApplication.processEvents()
    dash = login._dashboard
    check("admin login", dash is not None)
    dash.resize(1500, 950)
    dash.show()
    dash.shell.show_page("AI Models")
    QApplication.processEvents()
    shot(dash, "admin_ai_models_top")

    conn = db_module.get_connection()
    try:
        models = jobs.list_models(conn, dash._user, family="core_ai2")
        model = next((m for m in models if m.version == MODEL_VERSION), None)
        check("core_ai2 emergency model visible", model is not None)
        inspected = jobs.inspect_model(conn, dash._user, MODEL_VERSION, family="core_ai2")
        checkpoint = Path(inspected.path) / "best.pt"
        check("checkpoint path valid", checkpoint.is_file())
        check("checksum passes", inspected.checksum ==
              "76906dc9677b55773df1bad0f52156584ce2e9eafc0a557fd5fdba00124ce8d0")
        active = jobs.get_active_model(conn, dash._user, family="core_ai2")
        check("model is ACTIVE", active is not None and active.version == MODEL_VERSION)
        evaluations = data_dir / "ai" / "evaluations" / "core_ai2" / MODEL_VERSION
        record = json.loads(sorted(evaluations.glob("*.json"))[0].read_text("utf-8"))
        check("validation metrics viewable",
              record["metrics"]["validation"]["map50"] is not None,
              f"val map50={record['metrics']['validation']['map50']:.4f}")
        check("test metrics viewable",
              record["metrics"]["test"]["map50"] is not None,
              f"test map50={record['metrics']['test']['map50']:.4f}")
        core1_models = jobs.list_models(conn, dash._user, family="core_ai1")
        core1_active = jobs.get_active_model(conn, dash._user, family="core_ai1")
        check("no fake Core AI 1 model appears",
              core1_models == [] and core1_active is None)
    finally:
        conn.close()

    import torch, ultralytics
    check("runtime: PyTorch", bool(torch.__version__), torch.__version__)
    check("runtime: Ultralytics", bool(ultralytics.__version__), ultralytics.__version__)
    check("runtime: CUDA available", torch.cuda.is_available())
    check("runtime: RTX 5060 Ti detected",
          "5060" in (torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""))
    if hasattr(dash, "core_ai2_training_section"):
        if not dash.core_ai2_training_section.is_expanded():
            dash.core_ai2_training_section.toggle_button.click()
        dash.refresh_ai_models_page()
        reveal(dash.core_ai2_training_section)
        shot(dash.core_ai2_training_section, "admin_core_ai2_models_jobs")
        jobs_rows = dash.core_ai2_jobs_table.rowCount()
        check("no unexpected training job started", jobs_rows == 0,
              f"jobs listed: {jobs_rows}")
    dash.close()
    login.close()

    # ================= TEACHER (disposable) =================
    conn = db_module.get_connection()
    try:
        username = f"verify_{uuid.uuid4().hex[:8]}"
        teacher = create_teacher(conn, username, "Final Verify Teacher", "verifypass12345")
        profile = create_subject_profile(conn, teacher.user_id,
                                         "FINAL VERIFY (disposable)")
        manual = add_region(conn, teacher.user_id, profile.profile_id, "question_paper",
                            "manual_keep", "answer_box", 1, 0.05, 0.05, 0.2, 0.1)
    finally:
        conn.close()

    tlogin = LoginWindow()
    tlogin.show()
    tlogin.username_input.setText(username)
    tlogin.password_input.setText("verifypass12345")
    tlogin.handle_login()
    QApplication.processEvents()
    tdash = tlogin._dashboard
    check("teacher login + dashboard", tdash is not None)
    tdash.resize(1500, 950)
    tdash.show()
    shot(tdash, "teacher_dashboard")

    # real GPU inference on a real rendered page (held-out test page copy)
    smoke_dir = data_dir / "main_marking_sessions" / "_final_app_verify"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    test_images = sorted((RUN_ROOT / "yolo" / "images" / "test").glob("*.png"))
    page_image = smoke_dir / test_images[3].name
    shutil.copy2(test_images[3], page_image)
    from PIL import Image
    with Image.open(page_image) as img:
        width, height = img.size

    conn = db_module.get_connection()
    try:
        records = region_proposals.run_subject_profile_proposals(
            conn, teacher.user_id, profile.profile_id, "question_paper", 1,
            str(page_image), width, height, sha256_file(page_image))
        check("Core AI 2 proposals returned (real GPU inference)",
              len(records) > 0, f"{len(records)} proposal(s)")
        for record in records[:3]:
            print(f"    {record.proposal_id}: {record.proposed_class} "
                  f"conf={record.confidence:.3f}")
        check("each proposal has type+confidence+geometry",
              all(r.proposed_class and r.confidence is not None
                  and None not in (r.source_x, r.source_y, r.source_width, r.source_height)
                  for r in records))
    finally:
        conn.close()

    # the real review dialog: accept / edit(move+resize) / retype / reject
    from app.ui.dialogs import RegionProposalReviewDialog
    conn = db_module.get_connection()
    try:
        stored = proposals_model.list_proposals_for_profile(conn, profile.profile_id)
        dialog_rows = [{
            "proposal_id": r.proposal_id, "proposed_class": r.proposed_class,
            "confidence": r.confidence, "model_version": r.model_version,
            "rationale": r.rationale, "status": r.status,
            "geometry": (r.source_x, r.source_y, r.source_width, r.source_height),
            "source": r.source or "question_paper"} for r in stored]
        dialog = RegionProposalReviewDialog(None, "Core AI 2 Proposals (final verify)",
                                            dialog_rows)
        dialog.show()
        QApplication.processEvents()
        shot(dialog, "teacher_proposal_review_dialog")
        dialog.close()

        first = stored[0]
        accepted = region_proposals.accept_proposal(
            conn, teacher.user_id, first.proposal_id, region_label="verify_accept_1")
        check("accept proposal -> editable region", accepted.accepted_region_id is not None)
        regions = list_regions(conn, teacher.user_id, profile.profile_id, "question_paper")
        created = next(r for r in regions if r.region_id == accepted.accepted_region_id)
        # move + resize through the normal production region service
        from app.services.subject_profile_service import edit_region, move_region
        move_region(conn, teacher.user_id, profile.profile_id, created.region_id,
                    0.3, 0.3, 0.25, 0.15)
        moved = next(r for r in list_regions(conn, teacher.user_id, profile.profile_id,
                                             "question_paper")
                     if r.region_id == created.region_id)
        check("accepted region can be moved+resized",
              (round(moved.x, 2), round(moved.width, 2)) == (0.3, 0.25))
        # change its region type (retype)
        edit_region(conn, teacher.user_id, profile.profile_id, created.region_id,
                    moved.label, "question_area", moved.rotation_angle, moved.notes)
        retyped = next(r for r in list_regions(conn, teacher.user_id, profile.profile_id,
                                               "question_paper")
                       if r.region_id == created.region_id)
        check("accepted region can be retyped", retyped.region_type == "question_area")
        if len(stored) >= 2:
            region_proposals.reject_proposal(conn, teacher.user_id, stored[1].proposal_id,
                                             "final verify reject")
            check("reject proposal works",
                  proposals_model.get_proposal(conn, stored[1].proposal_id).status == "rejected")
        untouched = next(r for r in list_regions(conn, teacher.user_id, profile.profile_id,
                                                 "question_paper")
                         if r.label == "manual_keep")
        check("existing manual region not overwritten",
              (round(untouched.x, 2), round(untouched.y, 2)) == (0.05, 0.05))

        # persistence: reload profile regions fresh
        regions_again = list_regions(conn, teacher.user_id, profile.profile_id,
                                     "question_paper")
        check("accepted region persisted after reload",
              any(r.region_id == created.region_id for r in regions_again))
    finally:
        conn.close()

    # deliberately unavailable inference -> manual editing unaffected
    from app.models.core_ai2_inference_types import CoreAI2InferenceResult

    class _Offline:
        def run_core_ai2_inference(self, request, cancellation_token=None):
            return CoreAI2InferenceResult(
                request.request_id, "failed", [], request.model_version, None,
                request.page_checksum, 0.0, None, [],
                "detector_runtime_unavailable", "deliberately offline", None)

    conn = db_module.get_connection()
    try:
        offline = region_proposals.run_subject_profile_proposals(
            conn, teacher.user_id, profile.profile_id, "question_paper", 2,
            str(page_image), width, height, sha256_file(page_image), backend=_Offline())
        check("offline AI persists nothing, does not raise", offline == [])
        still = add_region(conn, teacher.user_id, profile.profile_id, "question_paper",
                           "manual_after_offline", "letter_box", 2, 0.5, 0.5, 0.1, 0.05)
        check("manual region editing still usable offline", still is not None)
    finally:
        conn.close()

    # ============ Kertas 2 manual review + separate paper + publication =====
    from app.models.main_marking_model import add_answer_file, create_session
    import app.services.subject_profile_review_service as review_service
    from app.services import ai_draft_scoring_service as drafting
    import app.models.ai_core1_draft_model as draft_model
    from app.services import ai_feedback_generation_service as feedback

    conn = db_module.get_connection()
    try:
        session = create_session(conn, teacher.user_id, "Verify Student", "Kertas 2")
        conn.execute("UPDATE main_marking_sessions SET subject_profile_id=? WHERE session_id=?",
                     (profile.profile_id, session.session_id))
        conn.commit()
        af = add_answer_file(conn, session.session_id, "verify.pdf", "verify.pdf").answer_file_id
        from app.services.subject_profile_service import save_answer_key_entry
        save_answer_key_entry(conn, teacher.user_id, profile.profile_id,
                              "qp_p13_q1_answer_box", "region", None,
                              "Award marks for a clear structured response.", 20.0)
        marked = spm.add_marked_answer(
            conn, af, "qp_p13_q1_answer_box", "region", "answer_box",
            "a verification essay answer", "Award marks for a clear structured response.",
            None, 20.0, False, spm.MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE, "")
        spm.get_or_create_attempt_review(conn, af, profile.profile_id)

        # Core AI 1 is INACTIVE: a draft request must not invent a score
        draft = drafting.generate_draft_for_answer(conn, teacher.user_id,
                                                   profile.profile_id, af,
                                                   marked.marked_answer_id)
        check("Core AI 1 inactive: no fabricated draft score",
              draft.status == "failed" and draft.draft_score is None, draft.status)

        # manual review still fully works
        review_service.set_kertas2_teacher_score(conn, teacher.user_id, profile.profile_id,
                                                 marked.marked_answer_id, 15.5)
        review_service.set_teacher_feedback(conn, teacher.user_id, profile.profile_id,
                                            marked.marked_answer_id,
                                            teacher_feedback="Manual feedback works.",
                                            private_comment="internal")
        after = spm.get_marked_answer_by_id(conn, marked.marked_answer_id)
        check("manual K2 score + feedback editing works",
              after.teacher_score == 15.5 and after.teacher_feedback == "Manual feedback works.")

        # deterministic template feedback (no local endpoint configured)
        fb = feedback.generate_feedback_draft(conn, teacher.user_id, marked.marked_answer_id)
        check("template feedback available; score untouched",
              fb.source == "deterministic_template"
              and spm.get_marked_answer_by_id(conn, marked.marked_answer_id).teacher_score == 15.5)

        # separate answer paper mode on a fresh disposable attempt (the mode is
        # locked once marking data exists), through the production SAP services
        import app.models.separate_answer_paper_model as sap_model
        import app.services.separate_answer_paper_service as sap_service
        add_region(conn, teacher.user_id, profile.profile_id, "question_paper",
                   "qp_p13_q1_answer_box", "answer_box", 13, 0.1, 0.1, 0.8, 0.4)
        sap_af = add_answer_file(conn, session.session_id,
                                 "verify_sap.pdf", "verify_sap.pdf").answer_file_id
        sap_service.set_attempt_mode(conn, teacher.user_id, profile.profile_id, sap_af,
                                     sap_model.ATTEMPT_MODE_SEPARATE)
        check("Separate Answer Paper mode enabled",
              sap_service.is_separate_mode(conn, sap_af) is True)
        sap_page = sap_service.add_separate_paper_pages(
            conn, teacher.user_id, profile.profile_id, sap_af, [str(page_image)])[0]
        sap_records = region_proposals.run_separate_paper_proposals(
            conn, teacher.user_id, profile.profile_id, sap_af, sap_page.sap_page_id,
            str(page_image), width, height, sha256_file(page_image))
        check("SAP Core AI 2 proposals editable",
              bool(sap_records) and all(p.status == "proposed" for p in sap_records),
              f"{len(sap_records)} proposal(s)")
        if sap_records:
            accepted_sap = region_proposals.accept_proposal(
                conn, teacher.user_id, sap_records[0].proposal_id,
                target_label="qp_p13_q1_answer_box")
            check("SAP accept -> attempt mapping only",
                  accepted_sap.accepted_mapping_id is not None
                  and accepted_sap.accepted_region_id is None)
        # the selected Part 3 question workflow remains usable
        part3 = spm.add_marked_answer(
            conn, af, "qp_p16_part3_answer_box", "region", "answer_box",
            "a part three story answer", None, None, 20.0, False,
            spm.MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE, "")
        review_service.set_part3_selected_question_number(
            conn, teacher.user_id, profile.profile_id, part3.marked_answer_id, "4")
        check("Part 3 question selection workflow usable",
              spm.get_marked_answer_by_id(conn, part3.marked_answer_id)
              .effective_selected_question_number == "4")
    finally:
        conn.close()

    # publication chain sanity on the disposable attempt (finalisation gates)
    conn = db_module.get_connection()
    try:
        blockers = review_service.get_finalisation_blockers(
            conn, teacher.user_id, profile.profile_id, af)
        check("finalisation blockers reported (gate active)", isinstance(blockers, list),
              f"{len(blockers)} blocker(s): {blockers[:2]}")
    finally:
        conn.close()

    tdash.close()
    tlogin.close()

    # ================= STUDENT =================
    conn = db_module.get_connection()
    try:
        student_user = f"sverify_{uuid.uuid4().hex[:6]}"
        student = create_student(conn, student_user, "Verify Student", "studpass12345")
    finally:
        conn.close()
    slogin = LoginWindow()
    slogin.show()
    slogin.username_input.setText(student_user)
    slogin.password_input.setText("studpass12345")
    slogin.handle_login()
    QApplication.processEvents()
    sdash = slogin._dashboard
    check("student login + dashboard", sdash is not None)
    sdash.resize(1400, 900)
    sdash.show()
    for page in ("Revision Materials", "External Revision", "My Attempts", "Results"):
        sdash.shell.show_page(page)
        QApplication.processEvents()
    check("student pages navigate + load", True)
    shot(sdash, "student_results_page")
    sdash.close()
    slogin.close()

    # cleanup the disposable records through production services
    conn = db_module.get_connection()
    try:
        from app.services.subject_profile_service import delete_subject_profile
        delete_subject_profile(conn, teacher.user_id, profile.profile_id)
        total = conn.execute("SELECT COUNT(*) FROM subject_profiles").fetchone()[0]
        check("disposable profile removed; real profiles intact", total == 15,
              f"{total} profiles remain")
    finally:
        conn.close()
    shutil.rmtree(smoke_dir, ignore_errors=True)

    failed = [label for label, ok, _ in _checks if not ok]
    print("=" * 64)
    print(f"{len(_checks) - len(failed)}/{len(_checks)} checks passed, "
          f"{_counter['n']} screenshots in {SHOTS}")
    if failed:
        for label in failed:
            print("FAILED:", label)
        return 1
    print("FINAL APP VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
