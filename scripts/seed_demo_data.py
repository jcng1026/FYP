"""Create safe artificial demo data for the local prototype.

This script is opt-in demo support. It creates or reuses records in a
specified SQLite database and never calls OCR, preprocessing, extraction,
AI, network, or model-provider services.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.database.seed import seed_default_developer
from app.database.schema import init_schema
from app.models.answer_extraction_model import (
    EXTRACTION_STATUS_EXTRACTED,
    add_extracted_attempt_answer,
    create_answer_extraction_job,
    get_latest_answer_extraction_job_for_attempt,
    mark_answer_extraction_job_completed,
)
from app.models.class_model import get_class_by_name_and_subject
from app.models.class_student_model import add_student_to_class, is_student_in_class
from app.models.extraction_model import (
    create_extraction_job,
    get_latest_extraction_job_for_attempt,
    mark_extraction_job_completed,
)
from app.models.kertas2_ai_feedback_model import (
    AUDIT_STATUS_GENERATED,
    FEEDBACK_STATUS_GENERATED,
    add_feedback_item,
    create_feedback_job,
    get_feedback_items_for_job,
    get_latest_feedback_job_for_attempt,
    mark_feedback_job_completed,
)
from app.models.marking_result_model import (
    add_marking_question_result,
    create_marking_job,
    mark_marking_job_completed,
)
from app.models.marking_setup_model import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_RUBRIC_CRITERION,
    create_marking_question,
    create_marking_setup,
    get_marking_questions_for_setup,
    get_marking_setup_by_material,
)
from app.models.ocr_model import create_ocr_job, get_latest_ocr_job_for_preprocessing_job, mark_ocr_job_completed
from app.models.preprocessing_model import (
    SOURCE_TYPE_REVISION_ATTEMPT_ANSWER,
    create_job as create_preprocessing_job,
    get_latest_job_for_source,
    mark_job_completed as mark_preprocessing_job_completed,
)
from app.models.result_summary_model import RESULT_TYPE_KERTAS1, RESULT_TYPE_KERTAS2
from app.models.revision_attempt_model import create_attempt, get_attempt_by_id
from app.models.revision_material_model import (
    PAPER_TYPE_KERTAS_1,
    PAPER_TYPE_KERTAS_2,
    assign_material_to_class,
    create_material,
)
from app.models.template_model import (
    REGION_TYPE_ANSWER_BOX,
    add_region,
    create_template,
    get_regions_for_template,
)
from app.models.user_model import create_user, get_user_by_username
from app.services.class_service import create_class_for_teacher
from app.services.kertas2_feedback_review_service import finalize_kertas2_review, start_or_get_kertas2_review
from app.services.marking_review_service import finalize_review, start_or_get_review
from app.services.result_summary_service import list_student_finalized_results, list_teacher_finalized_results
from app.services.student_progress_service import get_student_progress_summary
from app.services.teacher_attention_service import get_teacher_attention_summary
from app.utils.password_utils import hash_password

DEFAULT_DEMO_DB = PACKAGE_ROOT / "data" / "demo_app.db"
DEMO_TEACHER_USERNAME = "demo_teacher"
DEMO_STUDENT_USERNAME = "DEMO001"
DEMO_PASSWORD = "demo12345"
DEMO_CLASS_NAME = "Demo English Class"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    seed_default_developer(conn)
    return conn


def _get_or_create_user(conn: sqlite3.Connection, username: str, full_name: str, role: str):
    user = get_user_by_username(conn, username)
    if user is not None:
        return user
    return create_user(conn, username, hash_password(DEMO_PASSWORD), full_name, role)


def _get_or_create_class(conn: sqlite3.Connection, teacher_id: int):
    class_ = get_class_by_name_and_subject(conn, DEMO_CLASS_NAME, "English")
    if class_ is not None:
        return class_
    return create_class_for_teacher(conn, DEMO_CLASS_NAME, teacher_id)


def _get_or_create_material(conn: sqlite3.Connection, teacher_id: int, class_id: int, paper_type: str, title: str):
    row = conn.execute(
        "SELECT material_id FROM revision_materials WHERE teacher_id = ? AND title = ? AND paper_type = ?",
        (teacher_id, title, paper_type),
    ).fetchone()
    if row is None:
        material = create_material(conn, teacher_id, title, paper_type, "English", "demo_question.pdf", "demo_scheme.pdf")
    else:
        material = conn.execute(
            "SELECT material_id, teacher_id, title, paper_type, subject, question_paper_path, marking_scheme_path, created_at "
            "FROM revision_materials WHERE material_id = ?",
            (row["material_id"],),
        ).fetchone()
        from app.models.revision_material_model import RevisionMaterial

        material = RevisionMaterial(**dict(material))

    link = conn.execute(
        "SELECT 1 FROM revision_material_classes WHERE material_id = ? AND class_id = ?",
        (material.material_id, class_id),
    ).fetchone()
    if link is None:
        assign_material_to_class(conn, material.material_id, class_id)
    return material


def _get_or_create_attempt(conn: sqlite3.Connection, material_id: int, student_id: int, class_id: int):
    row = conn.execute(
        "SELECT attempt_id FROM revision_attempts WHERE material_id = ? AND student_id = ? AND class_id = ?",
        (material_id, student_id, class_id),
    ).fetchone()
    if row is not None:
        return get_attempt_by_id(conn, row["attempt_id"])
    return create_attempt(conn, material_id, student_id, class_id, 1, "demo_completed_answer.pdf")


def _get_or_create_template(conn: sqlite3.Connection, teacher_id: int, paper_type: str, title: str):
    row = conn.execute(
        "SELECT template_id FROM answer_templates WHERE teacher_id = ? AND title = ? AND paper_type = ?",
        (teacher_id, title, paper_type),
    ).fetchone()
    if row is None:
        template = create_template(conn, teacher_id, title, paper_type, "demo_template_sample.pdf")
    else:
        from app.models.template_model import get_template_by_id

        template = get_template_by_id(conn, row["template_id"])

    if not get_regions_for_template(conn, template.template_id):
        add_region(conn, template.template_id, "Q1", REGION_TYPE_ANSWER_BOX, 1, 0.1, 0.1, 0.3, 0.2, 1)
    return template


def _get_or_create_setup(conn: sqlite3.Connection, teacher_id: int, material, template):
    setup = get_marking_setup_by_material(conn, material.material_id)
    if setup is None:
        setup = create_marking_setup(
            conn, material.material_id, teacher_id, template.template_id, material.paper_type, -1, 1
        )
    questions = get_marking_questions_for_setup(conn, setup.setup_id)
    if questions:
        return setup, questions[0]
    region = get_regions_for_template(conn, template.template_id)[0]
    question_type = QUESTION_TYPE_MCQ if material.paper_type == PAPER_TYPE_KERTAS_1 else QUESTION_TYPE_RUBRIC_CRITERION
    correct_answer = "C" if material.paper_type == PAPER_TYPE_KERTAS_1 else "The response is relevant and organized."
    question = create_marking_question(
        conn, setup.setup_id, "Q1", correct_answer, 5, question_type, None, region.region_id, 1
    )
    return setup, question


def _ensure_answer_extraction(conn: sqlite3.Connection, attempt, setup, question, answer: str):
    answer_job = get_latest_answer_extraction_job_for_attempt(conn, attempt.attempt_id)
    if answer_job is not None:
        return answer_job

    preprocessing = get_latest_job_for_source(conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, attempt.attempt_id)
    if preprocessing is None:
        preprocessing = create_preprocessing_job(
            conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, attempt.attempt_id, "demo_completed_answer.pdf", "demo_processed"
        )
        mark_preprocessing_job_completed(conn, preprocessing.job_id, 1)

    ocr = get_latest_ocr_job_for_preprocessing_job(conn, preprocessing.job_id)
    if ocr is None:
        ocr = create_ocr_job(conn, preprocessing.job_id, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, attempt.attempt_id)
        mark_ocr_job_completed(conn, ocr.ocr_job_id, 1, answer)

    extraction = get_latest_extraction_job_for_attempt(conn, attempt.attempt_id)
    if extraction is None:
        extraction = create_extraction_job(conn, attempt.attempt_id, ocr.ocr_job_id, setup.template_id, setup.setup_id)
        mark_extraction_job_completed(conn, extraction.extraction_job_id, 1, 1)

    answer_job = create_answer_extraction_job(conn, attempt.attempt_id, extraction.extraction_job_id, setup.setup_id)
    add_extracted_attempt_answer(
        conn,
        answer_job.answer_extraction_job_id,
        question.question_id,
        question.question_no,
        question.question_type,
        question.region_id,
        "Q1",
        answer,
        answer,
        0.95,
        EXTRACTION_STATUS_EXTRACTED,
    )
    mark_answer_extraction_job_completed(conn, answer_job.answer_extraction_job_id, 1, 1)
    return answer_job


def _ensure_kertas1_result(conn: sqlite3.Connection, teacher, student, class_) -> None:
    existing = [result for result in list_student_finalized_results(conn, student.user_id) if result.result_type == RESULT_TYPE_KERTAS1]
    if existing:
        return

    material = _get_or_create_material(conn, teacher.user_id, class_.class_id, PAPER_TYPE_KERTAS_1, "Demo Kertas 1 Practice")
    attempt = _get_or_create_attempt(conn, material.material_id, student.user_id, class_.class_id)
    template = _get_or_create_template(conn, teacher.user_id, PAPER_TYPE_KERTAS_1, "Demo Kertas 1 Template")
    setup, question = _get_or_create_setup(conn, teacher.user_id, material, template)
    answer_job = _ensure_answer_extraction(conn, attempt, setup, question, "C")
    marking_job = create_marking_job(
        conn, attempt.attempt_id, answer_job.answer_extraction_job_id, setup.setup_id, PAPER_TYPE_KERTAS_1
    )
    add_marking_question_result(
        conn,
        marking_job.marking_job_id,
        question.question_id,
        question.region_id,
        "Q1",
        QUESTION_TYPE_MCQ,
        "C",
        "C",
        "C",
        True,
        False,
        5,
        5,
        0.95,
        "Artificial demo answer matches the answer key.",
        "Rule-based Kertas 1 demo result.",
    )
    mark_marking_job_completed(conn, marking_job.marking_job_id, 1, 1, 1, 0, 5, 5)
    review = start_or_get_review(conn, marking_job.marking_job_id, teacher.user_id)
    finalize_review(conn, review.review_id, teacher.user_id)


def _ensure_kertas2_result(conn: sqlite3.Connection, teacher, student, class_) -> None:
    existing = [result for result in list_student_finalized_results(conn, student.user_id) if result.result_type == RESULT_TYPE_KERTAS2]
    if existing:
        return

    material = _get_or_create_material(conn, teacher.user_id, class_.class_id, PAPER_TYPE_KERTAS_2, "Demo Kertas 2 Practice")
    attempt = _get_or_create_attempt(conn, material.material_id, student.user_id, class_.class_id)
    template = _get_or_create_template(conn, teacher.user_id, PAPER_TYPE_KERTAS_2, "Demo Kertas 2 Template")
    setup, question = _get_or_create_setup(conn, teacher.user_id, material, template)
    answer_job = _ensure_answer_extraction(conn, attempt, setup, question, "The response is relevant and organized.")
    feedback_job = get_latest_feedback_job_for_attempt(conn, attempt.attempt_id)
    if feedback_job is None:
        feedback_job = create_feedback_job(conn, attempt.attempt_id, answer_job.answer_extraction_job_id, setup.setup_id)
        add_feedback_item(
            conn,
            feedback_job.feedback_job_id,
            question.question_id,
            None,
            "Content",
            QUESTION_TYPE_RUBRIC_CRITERION,
            "The response is relevant and organized.",
            "The response is relevant and organized.",
            4,
            5,
            "Artificial draft feedback for teacher review.",
            "Demo-only local draft; no model was called.",
            0.8,
            FEEDBACK_STATUS_GENERATED,
            prompt_snapshot="Demo-only prompt snapshot with artificial content.",
            raw_provider_output='{"suggested_score": 4, "feedback_text": "Artificial draft feedback."}',
            parser_error=None,
            audit_status=AUDIT_STATUS_GENERATED,
        )
        mark_feedback_job_completed(
            conn,
            feedback_job.feedback_job_id,
            1,
            1,
            provider_backend="demo_seed",
            provider_model_path="demo-only",
            provider_status="not_called",
            diagnostic_message="Demo seed inserted artificial feedback; no provider was called.",
        )
    elif not get_feedback_items_for_job(conn, feedback_job.feedback_job_id):
        add_feedback_item(
            conn,
            feedback_job.feedback_job_id,
            question.question_id,
            None,
            "Content",
            QUESTION_TYPE_RUBRIC_CRITERION,
            "The response is relevant and organized.",
            "The response is relevant and organized.",
            4,
            5,
            "Artificial draft feedback for teacher review.",
            "Demo-only local draft; no model was called.",
            0.8,
            FEEDBACK_STATUS_GENERATED,
            prompt_snapshot="Demo-only prompt snapshot with artificial content.",
            raw_provider_output='{"suggested_score": 4, "feedback_text": "Artificial draft feedback."}',
            parser_error=None,
            audit_status=AUDIT_STATUS_GENERATED,
        )
    review = start_or_get_kertas2_review(conn, feedback_job.feedback_job_id, teacher.user_id)
    finalize_kertas2_review(conn, review.kertas2_review_id, teacher.user_id)


def seed_demo_database(db_path: Path) -> Dict[str, int]:
    conn = _connect(db_path)
    try:
        teacher = _get_or_create_user(conn, DEMO_TEACHER_USERNAME, "Demo Teacher", "teacher")
        student = _get_or_create_user(conn, DEMO_STUDENT_USERNAME, "Demo Student", "student")
        class_ = _get_or_create_class(conn, teacher.user_id)
        if not is_student_in_class(conn, class_.class_id, student.user_id):
            add_student_to_class(conn, class_.class_id, student.user_id)

        _ensure_kertas1_result(conn, teacher, student, class_)
        _ensure_kertas2_result(conn, teacher, student, class_)

        teacher_results = list_teacher_finalized_results(conn, teacher.user_id)
        student_results = list_student_finalized_results(conn, student.user_id)
        attention = get_teacher_attention_summary(conn, teacher.user_id)
        progress = get_student_progress_summary(conn, student.user_id)

        return {
            "teacher_id": teacher.user_id,
            "student_id": student.user_id,
            "class_id": class_.class_id,
            "teacher_results": len(teacher_results),
            "student_results": len(student_results),
            "attention_items": len(attention.attention_items),
            "student_progress_items": len(progress.recent_items),
        }
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed artificial demo data into a local demo SQLite database.")
    parser.add_argument("--demo-db", type=Path, default=DEFAULT_DEMO_DB, help="SQLite demo database path.")
    parser.add_argument("--confirm-demo", action="store_true", help="Required confirmation for demo-only data seeding.")
    parser.add_argument("--reset-demo-db", action="store_true", help="Delete the selected demo DB before seeding.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = args.demo_db.resolve()

    print("Demo data seed is for local demo databases only. Do not run on real school data.")
    print(f"Demo DB: {db_path}")
    if not args.confirm_demo:
        print("Refusing to seed without --confirm-demo.")
        return 2
    if args.reset_demo_db and db_path.exists():
        db_path.unlink()
        print("Existing demo DB was removed because --reset-demo-db was provided.")

    summary = seed_demo_database(db_path)
    print("Demo records created or found:")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    print(f"- teacher login: {DEMO_TEACHER_USERNAME} / {DEMO_PASSWORD}")
    print(f"- student login: {DEMO_STUDENT_USERNAME} / {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
