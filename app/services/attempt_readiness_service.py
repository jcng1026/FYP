"""Read-only attempt readiness checks and issue flags (Stage 9B).

This service checks whether an attempt has the setup and completed pipeline
records needed before a teacher can trust marking/review/export readiness.
It is intentionally read-only: it does not create preprocessing, OCR,
extraction, marking, review, AI feedback, or export records.
"""

import sqlite3
from typing import List, Optional

from app.models.answer_extraction_model import (
    EXTRACTION_STATUS_EXTRACTED,
    STATUS_COMPLETED as ANSWER_EXTRACTION_STATUS_COMPLETED,
    get_extracted_attempt_answers_for_job,
)
from app.models.class_model import get_class_by_id
from app.models.kertas2_ai_feedback_model import STATUS_FAILED as KERTAS2_FEEDBACK_STATUS_FAILED
from app.models.kertas2_feedback_review_model import STATUS_FINALIZED as KERTAS2_REVIEW_STATUS_FINALIZED
from app.models.marking_review_model import STATUS_FINALIZED as KERTAS1_REVIEW_STATUS_FINALIZED
from app.models.marking_setup_model import (
    QUESTION_TYPE_RUBRIC_CRITERION,
    get_marking_questions_for_setup,
    get_marking_setup_by_material,
)
from app.models.ocr_model import STATUS_COMPLETED as OCR_STATUS_COMPLETED
from app.models.preprocessing_model import (
    SOURCE_TYPE_REVISION_ATTEMPT_ANSWER,
    STATUS_COMPLETED as PREPROCESSING_STATUS_COMPLETED,
)
from app.models.readiness_issue_model import (
    AttemptReadinessReport,
    ISSUE_SEVERITY_BLOCKER,
    ISSUE_SEVERITY_WARNING,
    ISSUE_STATUS_OPEN,
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_COMPLETED,
    READINESS_STATUS_READY,
    READINESS_STATUS_WARNING,
    ReadinessIssue,
    TARGET_TYPE_REVISION_ATTEMPT,
)
from app.models.revision_attempt_model import get_attempt_by_id, get_attempts_for_teacher
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2, get_material_by_id
from app.models.template_model import get_regions_for_template
from app.services.answer_extraction_service import get_latest_answer_extraction_job
from app.services.attempt_workflow_status_service import get_attempt_workflow_status
from app.services.extraction_service import get_latest_extraction_job
from app.services.kertas1_marking_service import get_latest_marking_job
from app.services.kertas2_ai_feedback_service import get_latest_feedback_job
from app.services.kertas2_feedback_review_service import get_latest_kertas2_review
from app.services.marking_review_service import get_latest_review
from app.services.ocr_service import get_latest_ocr_job
from app.services.preprocessing_service import get_latest_preprocessing_job

ISSUE_MISSING_TEMPLATE = "missing_template"
ISSUE_TEMPLATE_HAS_NO_REGIONS = "template_has_no_regions"
ISSUE_MISSING_MARKING_SETUP = "missing_marking_setup"
ISSUE_MARKING_SETUP_HAS_NO_QUESTIONS = "marking_setup_has_no_questions"
ISSUE_KERTAS1_ANSWER_KEY_MISSING = "kertas1_answer_key_missing"
ISSUE_KERTAS2_RUBRIC_MISSING = "kertas2_rubric_missing"
ISSUE_NO_COMPLETED_PREPROCESSING = "no_completed_preprocessing"
ISSUE_NO_COMPLETED_OCR = "no_completed_ocr"
ISSUE_NO_COMPLETED_REGION_EXTRACTION = "no_completed_region_extraction"
ISSUE_NO_COMPLETED_ANSWER_EXTRACTION = "no_completed_answer_extraction"
ISSUE_EXTRACTED_ANSWER_MISSING = "extracted_answer_missing"
ISSUE_FAILED_KERTAS2_FEEDBACK = "failed_kertas2_feedback"
ISSUE_REVIEW_PENDING = "review_pending"


def _issue(
    issue_key: str,
    severity: str,
    title: str,
    message: str,
    recommended_action: str,
    related_record_id: Optional[int] = None,
) -> ReadinessIssue:
    return ReadinessIssue(
        issue_key=issue_key,
        severity=severity,
        status=ISSUE_STATUS_OPEN,
        title=title,
        message=message,
        recommended_action=recommended_action,
        related_record_id=related_record_id,
    )


def _check_attempt_owner(conn: sqlite3.Connection, attempt_id: int, teacher_id: int):
    attempt = get_attempt_by_id(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"Revision attempt not found: {attempt_id}")

    class_ = get_class_by_id(conn, attempt.class_id)
    if class_ is None or class_.teacher_id != teacher_id:
        raise ValueError("You can only view readiness issues for attempts from classes you own.")
    return attempt


def _material_setup_issues(conn: sqlite3.Connection, material, marking_setup) -> List[ReadinessIssue]:
    issues: List[ReadinessIssue] = []
    questions = []

    if marking_setup is None:
        return [
            _issue(
                ISSUE_MISSING_MARKING_SETUP,
                ISSUE_SEVERITY_BLOCKER,
                "Missing marking setup",
                "This revision material has no marking setup.",
                "Open Marking Setup and save a setup for this material.",
            ),
            _issue(
                ISSUE_MISSING_TEMPLATE,
                ISSUE_SEVERITY_BLOCKER,
                "Missing template",
                "No answer template is linked because the marking setup is missing.",
                "Create or link a template before running extraction.",
            ),
        ]

    if marking_setup.template_id is None:
        issues.append(_issue(
            ISSUE_MISSING_TEMPLATE,
            ISSUE_SEVERITY_BLOCKER,
            "Missing template",
            "The marking setup does not have an answer template linked.",
            "Link a template in Marking Setup.",
            marking_setup.setup_id,
        ))
    else:
        regions = get_regions_for_template(conn, marking_setup.template_id)
        if not regions:
            issues.append(_issue(
                ISSUE_TEMPLATE_HAS_NO_REGIONS,
                ISSUE_SEVERITY_BLOCKER,
                "Template has no regions",
                "The linked answer template exists but has no defined regions.",
                "Open the template editor and add answer regions.",
                marking_setup.template_id,
            ))

    questions = get_marking_questions_for_setup(conn, marking_setup.setup_id)
    if not questions:
        issue_key = ISSUE_KERTAS2_RUBRIC_MISSING if material.paper_type == PAPER_TYPE_KERTAS_2 else ISSUE_MARKING_SETUP_HAS_NO_QUESTIONS
        title = "Kertas 2 rubric missing" if material.paper_type == PAPER_TYPE_KERTAS_2 else "Marking setup has no questions"
        message = "No rubric criteria were found." if material.paper_type == PAPER_TYPE_KERTAS_2 else "No marking questions were found."
        issues.append(_issue(
            issue_key,
            ISSUE_SEVERITY_BLOCKER,
            title,
            message,
            "Add questions or rubric criteria in Marking Setup.",
            marking_setup.setup_id,
        ))

    if material.paper_type == PAPER_TYPE_KERTAS_1:
        missing_answers = [q.question_no for q in questions if not (q.correct_answer or "").strip()]
        if missing_answers:
            issues.append(_issue(
                ISSUE_KERTAS1_ANSWER_KEY_MISSING,
                ISSUE_SEVERITY_BLOCKER,
                "Kertas 1 answer key missing",
                f"Correct answers are missing for: {', '.join(missing_answers)}.",
                "Fill in the Kertas 1 answer key before marking.",
                marking_setup.setup_id,
            ))
    elif material.paper_type == PAPER_TYPE_KERTAS_2:
        rubric_questions = [q for q in questions if q.question_type == QUESTION_TYPE_RUBRIC_CRITERION]
        if questions and not rubric_questions:
            issues.append(_issue(
                ISSUE_KERTAS2_RUBRIC_MISSING,
                ISSUE_SEVERITY_BLOCKER,
                "Kertas 2 rubric missing",
                "The marking setup has questions but no rubric criterion rows.",
                "Add Kertas 2 rubric criteria before generating feedback.",
                marking_setup.setup_id,
            ))

    return issues


def _pipeline_issues(conn: sqlite3.Connection, attempt, material, marking_setup) -> List[ReadinessIssue]:
    issues: List[ReadinessIssue] = []

    preprocessing_job = get_latest_preprocessing_job(conn, SOURCE_TYPE_REVISION_ATTEMPT_ANSWER, attempt.attempt_id)
    if preprocessing_job is None or preprocessing_job.status != PREPROCESSING_STATUS_COMPLETED:
        issues.append(_issue(
            ISSUE_NO_COMPLETED_PREPROCESSING,
            ISSUE_SEVERITY_BLOCKER,
            "No completed preprocessing",
            "This attempt has no completed preprocessing job.",
            "Run document preprocessing for the attempt.",
            preprocessing_job.job_id if preprocessing_job else None,
        ))
        return issues

    ocr_job = get_latest_ocr_job(conn, preprocessing_job.job_id)
    if ocr_job is None or ocr_job.status != OCR_STATUS_COMPLETED:
        issues.append(_issue(
            ISSUE_NO_COMPLETED_OCR,
            ISSUE_SEVERITY_BLOCKER,
            "No completed OCR",
            "This attempt has no completed OCR job.",
            "Run OCR after preprocessing completes.",
            ocr_job.ocr_job_id if ocr_job else None,
        ))
        return issues

    extraction_job = get_latest_extraction_job(conn, attempt.attempt_id)
    if extraction_job is None or extraction_job.status != "completed":
        issues.append(_issue(
            ISSUE_NO_COMPLETED_REGION_EXTRACTION,
            ISSUE_SEVERITY_BLOCKER,
            "No completed region extraction",
            "This attempt has no completed template-region extraction job.",
            "Extract template regions for the attempt.",
            extraction_job.extraction_job_id if extraction_job else None,
        ))
        return issues

    answer_job = get_latest_answer_extraction_job(conn, attempt.attempt_id)
    if answer_job is None or answer_job.status != ANSWER_EXTRACTION_STATUS_COMPLETED:
        issues.append(_issue(
            ISSUE_NO_COMPLETED_ANSWER_EXTRACTION,
            ISSUE_SEVERITY_BLOCKER,
            "No completed answer extraction",
            "This attempt has no completed structured answer extraction job.",
            "Extract structured answers before marking or feedback.",
            answer_job.answer_extraction_job_id if answer_job else None,
        ))
        return issues

    if marking_setup is not None:
        questions = get_marking_questions_for_setup(conn, marking_setup.setup_id)
        answers = get_extracted_attempt_answers_for_job(conn, answer_job.answer_extraction_job_id)
        answers_by_question_id = {answer.question_id: answer for answer in answers}
        for question in questions:
            answer = answers_by_question_id.get(question.question_id)
            if answer is None or answer.extraction_status != EXTRACTION_STATUS_EXTRACTED:
                status = "missing" if answer is None else answer.extraction_status
                issues.append(_issue(
                    ISSUE_EXTRACTED_ANSWER_MISSING,
                    ISSUE_SEVERITY_BLOCKER,
                    f"Extracted answer missing for {question.question_no}",
                    f"Required question {question.question_no} has no extracted answer ready for marking (status: {status}).",
                    "Review template regions and rerun answer extraction, or correct the answer manually.",
                    answer.extracted_answer_id if answer else question.question_id,
                ))

    if material.paper_type == PAPER_TYPE_KERTAS_1:
        marking_job = get_latest_marking_job(conn, attempt.attempt_id)
        review = get_latest_review(conn, attempt.attempt_id)
        if review is not None and review.status == KERTAS1_REVIEW_STATUS_FINALIZED:
            return issues
        if marking_job is not None and marking_job.status == "completed":
            issues.append(_issue(
                ISSUE_REVIEW_PENDING,
                ISSUE_SEVERITY_WARNING,
                "Kertas 1 review pending",
                "Kertas 1 marking exists, but the teacher review is not finalized.",
                "Open Review Kertas 1 and finalize the review.",
                review.review_id if review else marking_job.marking_job_id,
            ))
    else:
        feedback_job = get_latest_feedback_job(conn, attempt.attempt_id)
        review = get_latest_kertas2_review(conn, attempt.attempt_id)
        if review is not None and review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            return issues
        if feedback_job is not None and feedback_job.status == KERTAS2_FEEDBACK_STATUS_FAILED:
            diagnostic = feedback_job.diagnostic_message or feedback_job.error_message or "No diagnostic message recorded."
            issues.append(_issue(
                ISSUE_FAILED_KERTAS2_FEEDBACK,
                ISSUE_SEVERITY_BLOCKER,
                "Kertas 2 AI feedback failed",
                f"Latest Kertas 2 AI feedback failed: {diagnostic}",
                "Open the feedback audit, fix the local AI setup or source issue, and regenerate feedback.",
                feedback_job.feedback_job_id,
            ))
        elif feedback_job is not None and feedback_job.status == "completed":
            issues.append(_issue(
                ISSUE_REVIEW_PENDING,
                ISSUE_SEVERITY_WARNING,
                "Kertas 2 review pending",
                "Kertas 2 AI feedback exists, but the teacher review is not finalized.",
                "Open Review Kertas 2 and finalize the review.",
                review.kertas2_review_id if review else feedback_job.feedback_job_id,
            ))

    return issues


def _readiness_status(conn: sqlite3.Connection, attempt, material, issues: List[ReadinessIssue]) -> str:
    if any(issue.severity == ISSUE_SEVERITY_BLOCKER for issue in issues):
        return READINESS_STATUS_BLOCKED
    if any(issue.severity == ISSUE_SEVERITY_WARNING for issue in issues):
        return READINESS_STATUS_WARNING
    if material.paper_type == PAPER_TYPE_KERTAS_1:
        review = get_latest_review(conn, attempt.attempt_id)
        if review is not None and review.status == KERTAS1_REVIEW_STATUS_FINALIZED:
            return READINESS_STATUS_COMPLETED
    else:
        review = get_latest_kertas2_review(conn, attempt.attempt_id)
        if review is not None and review.status == KERTAS2_REVIEW_STATUS_FINALIZED:
            return READINESS_STATUS_COMPLETED
    return READINESS_STATUS_READY


def _summary(issues: List[ReadinessIssue]) -> str:
    if not issues:
        return "No setup or attempt-readiness issues found."
    blockers = sum(1 for issue in issues if issue.severity == ISSUE_SEVERITY_BLOCKER)
    warnings = sum(1 for issue in issues if issue.severity == ISSUE_SEVERITY_WARNING)
    return f"{len(issues)} issue(s): {blockers} blocker(s), {warnings} warning(s)."


def get_attempt_readiness_report(
    conn: sqlite3.Connection, attempt_id: int, teacher_id: int
) -> AttemptReadinessReport:
    attempt = _check_attempt_owner(conn, attempt_id, teacher_id)
    material = get_material_by_id(conn, attempt.material_id)
    if material is None:
        raise ValueError(f"Revision material not found for attempt {attempt_id}.")

    marking_setup = get_marking_setup_by_material(conn, material.material_id)
    issues = []
    issues.extend(_material_setup_issues(conn, material, marking_setup))
    issues.extend(_pipeline_issues(conn, attempt, material, marking_setup))

    workflow_status = get_attempt_workflow_status(conn, attempt_id, teacher_id)
    blocker_count = sum(1 for issue in issues if issue.severity == ISSUE_SEVERITY_BLOCKER)
    warning_count = sum(1 for issue in issues if issue.severity == ISSUE_SEVERITY_WARNING)

    return AttemptReadinessReport(
        target_type=TARGET_TYPE_REVISION_ATTEMPT,
        target_id=attempt.attempt_id,
        paper_type=material.paper_type,
        readiness_status=_readiness_status(conn, attempt, material, issues),
        issue_count=len(issues),
        blocker_count=blocker_count,
        warning_count=warning_count,
        issues=issues,
        issue_summary=_summary(issues),
        next_action=workflow_status.next_action,
        current_stage=workflow_status.current_stage,
    )


def list_teacher_attempt_readiness_reports(
    conn: sqlite3.Connection, teacher_id: int
) -> List[AttemptReadinessReport]:
    reports = []
    for row in get_attempts_for_teacher(conn, teacher_id):
        reports.append(get_attempt_readiness_report(conn, row.attempt_id, teacher_id))
    reports.sort(key=lambda report: report.target_id, reverse=True)
    return reports
