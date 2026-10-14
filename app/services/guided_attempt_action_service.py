"""Read-only guided teacher actions for revision attempts (Stage 9C).

This service combines Stage 9A workflow status and Stage 9B readiness
issues to tell the UI which existing action is recommended and which
actions should warn the teacher first. It never executes actions and never
creates jobs, reviews, AI feedback, exports, or marking records.
"""

import sqlite3
from typing import Dict, Iterable, List

from app.models.guided_action_model import GuidedAttemptAction, GuidedAttemptActions
from app.models.readiness_issue_model import ISSUE_SEVERITY_BLOCKER
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1
from app.services.attempt_readiness_service import (
    ISSUE_EXTRACTED_ANSWER_MISSING,
    ISSUE_FAILED_KERTAS2_FEEDBACK,
    ISSUE_KERTAS1_ANSWER_KEY_MISSING,
    ISSUE_KERTAS2_RUBRIC_MISSING,
    ISSUE_MARKING_SETUP_HAS_NO_QUESTIONS,
    ISSUE_MISSING_MARKING_SETUP,
    ISSUE_MISSING_TEMPLATE,
    ISSUE_NO_COMPLETED_ANSWER_EXTRACTION,
    ISSUE_NO_COMPLETED_OCR,
    ISSUE_NO_COMPLETED_PREPROCESSING,
    ISSUE_NO_COMPLETED_REGION_EXTRACTION,
    ISSUE_REVIEW_PENDING,
    ISSUE_TEMPLATE_HAS_NO_REGIONS,
    get_attempt_readiness_report,
)
from app.services.attempt_workflow_status_service import get_attempt_workflow_status

ACTION_VIEW_DETAILS = "view_details"
ACTION_PREPROCESS = "preprocess"
ACTION_RUN_OCR = "run_ocr"
ACTION_VIEW_OCR = "view_ocr"
ACTION_EXTRACT_REGIONS = "extract_regions"
ACTION_VIEW_EXTRACTION = "view_extraction"
ACTION_EXTRACT_ANSWERS = "extract_answers"
ACTION_VIEW_ANSWERS = "view_answers"
ACTION_MARK_KERTAS1 = "mark_kertas1"
ACTION_VIEW_MARKING = "view_marking"
ACTION_REVIEW_KERTAS1 = "review_kertas1"
ACTION_VIEW_KERTAS1_REVIEW = "view_kertas1_review"
ACTION_GENERATE_KERTAS2_FEEDBACK = "generate_kertas2_feedback"
ACTION_VIEW_KERTAS2_FEEDBACK = "view_kertas2_feedback"
ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT = "view_kertas2_feedback_audit"
ACTION_REVIEW_KERTAS2 = "review_kertas2"
ACTION_VIEW_KERTAS2_REVIEW = "view_kertas2_review"
ACTION_VIEW_WORKFLOW = "view_workflow"
ACTION_VIEW_ISSUES = "view_issues"
ACTION_VIEW_RESULT = "view_result"
ACTION_EXPORT_RESULT = "export_result"

_SAFE_VIEW_ACTIONS = {
    ACTION_VIEW_DETAILS,
    ACTION_VIEW_OCR,
    ACTION_VIEW_EXTRACTION,
    ACTION_VIEW_ANSWERS,
    ACTION_VIEW_MARKING,
    ACTION_VIEW_KERTAS1_REVIEW,
    ACTION_VIEW_KERTAS2_FEEDBACK,
    ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT,
    ACTION_VIEW_KERTAS2_REVIEW,
    ACTION_VIEW_WORKFLOW,
    ACTION_VIEW_ISSUES,
    ACTION_VIEW_RESULT,
}

_ACTION_LABELS = [
    (ACTION_VIEW_DETAILS, "View Details"),
    (ACTION_PREPROCESS, "Preprocess"),
    (ACTION_RUN_OCR, "Run OCR"),
    (ACTION_VIEW_OCR, "View OCR"),
    (ACTION_EXTRACT_REGIONS, "Extract Regions"),
    (ACTION_VIEW_EXTRACTION, "View Extraction"),
    (ACTION_EXTRACT_ANSWERS, "Extract Answers"),
    (ACTION_VIEW_ANSWERS, "View Answers"),
    (ACTION_MARK_KERTAS1, "Mark Kertas 1"),
    (ACTION_VIEW_MARKING, "View Marking"),
    (ACTION_REVIEW_KERTAS1, "Review Marking"),
    (ACTION_VIEW_KERTAS1_REVIEW, "View Review"),
    (ACTION_GENERATE_KERTAS2_FEEDBACK, "Generate Kertas 2 Feedback"),
    (ACTION_VIEW_KERTAS2_FEEDBACK, "View Kertas 2 Feedback"),
    (ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT, "View Kertas 2 Feedback Audit"),
    (ACTION_REVIEW_KERTAS2, "Review Kertas 2"),
    (ACTION_VIEW_KERTAS2_REVIEW, "View Kertas 2 Review"),
    (ACTION_VIEW_WORKFLOW, "View Workflow"),
    (ACTION_VIEW_ISSUES, "View Issues"),
    (ACTION_VIEW_RESULT, "View Result"),
    (ACTION_EXPORT_RESULT, "Export Result"),
]

_NEXT_ACTION_TO_ACTION_KEY = {
    "Preprocess document": ACTION_PREPROCESS,
    "Run OCR": ACTION_RUN_OCR,
    "Extract template regions": ACTION_EXTRACT_REGIONS,
    "Extract answers": ACTION_EXTRACT_ANSWERS,
    "Mark Kertas 1": ACTION_MARK_KERTAS1,
    "Review Kertas 1 marking": ACTION_REVIEW_KERTAS1,
    "Generate Kertas 2 feedback": ACTION_GENERATE_KERTAS2_FEEDBACK,
    "Review Kertas 2 feedback": ACTION_REVIEW_KERTAS2,
    "Investigate failed Kertas 2 AI feedback": ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT,
    "Export finalized result": ACTION_VIEW_RESULT,
    "View finalized result": ACTION_VIEW_RESULT,
}

_ISSUE_FIX_ACTIONS = {
    ISSUE_MISSING_MARKING_SETUP: (None, "Open Marking Setup"),
    ISSUE_MARKING_SETUP_HAS_NO_QUESTIONS: (None, "Open Marking Setup"),
    ISSUE_KERTAS1_ANSWER_KEY_MISSING: (None, "Open Marking Setup"),
    ISSUE_KERTAS2_RUBRIC_MISSING: (None, "Open Marking Setup"),
    ISSUE_MISSING_TEMPLATE: (None, "Create Template"),
    ISSUE_TEMPLATE_HAS_NO_REGIONS: (None, "Create Template"),
    ISSUE_NO_COMPLETED_PREPROCESSING: (ACTION_PREPROCESS, "Preprocess document"),
    ISSUE_NO_COMPLETED_OCR: (ACTION_RUN_OCR, "Run OCR"),
    ISSUE_NO_COMPLETED_REGION_EXTRACTION: (ACTION_EXTRACT_REGIONS, "Extract template regions"),
    ISSUE_NO_COMPLETED_ANSWER_EXTRACTION: (ACTION_EXTRACT_ANSWERS, "Extract answers"),
    ISSUE_EXTRACTED_ANSWER_MISSING: (ACTION_EXTRACT_ANSWERS, "Extract answers"),
    ISSUE_FAILED_KERTAS2_FEEDBACK: (ACTION_VIEW_KERTAS2_FEEDBACK_AUDIT, "View Kertas 2 Feedback Audit"),
    ISSUE_REVIEW_PENDING: (None, "Review pending result"),
}


def _recommended_from_issues(readiness_report, workflow_status) -> tuple:
    for issue in readiness_report.issues:
        if issue.severity != ISSUE_SEVERITY_BLOCKER:
            continue
        action_key, label = _ISSUE_FIX_ACTIONS.get(issue.issue_key, (ACTION_VIEW_ISSUES, "View Issues"))
        return action_key, label

    workflow_action_key = _NEXT_ACTION_TO_ACTION_KEY.get(workflow_status.next_action)
    if workflow_action_key is not None:
        return workflow_action_key, workflow_status.next_action

    if workflow_status.paper_type == PAPER_TYPE_KERTAS_1:
        return ACTION_VIEW_RESULT, "View Result"
    return ACTION_VIEW_RESULT, "View Result"


def _issue_keys(issues: Iterable) -> List[str]:
    return [issue.issue_key for issue in issues]


def _warning_message(action_label: str, blocker_issues: List) -> str:
    titles = "\n".join(f"- {issue.title}: {issue.message}" for issue in blocker_issues)
    return (
        f"{action_label} may be blocked by current readiness issue(s):\n"
        f"{titles}\n\n"
        "Fix the listed issue(s), or use the existing action only if the normal service validation allows it."
    )


def get_guided_actions_for_attempt(
    conn: sqlite3.Connection, attempt_id: int, teacher_id: int
) -> GuidedAttemptActions:
    """Return recommended and warned actions for an owned attempt.

    Ownership validation is inherited from the workflow/readiness services.
    This function only reads status/report data and returns guidance.
    """
    workflow_status = get_attempt_workflow_status(conn, attempt_id, teacher_id)
    readiness_report = get_attempt_readiness_report(conn, attempt_id, teacher_id)

    recommended_key, recommended_label = _recommended_from_issues(readiness_report, workflow_status)
    blocker_issues = [issue for issue in readiness_report.issues if issue.severity == ISSUE_SEVERITY_BLOCKER]
    blocker_issue_keys = _issue_keys(blocker_issues)
    issue_keys_by_action: Dict[str, List[str]] = {}
    for issue in readiness_report.issues:
        action_key, _label = _ISSUE_FIX_ACTIONS.get(issue.issue_key, (None, "View Issues"))
        if action_key is not None:
            issue_keys_by_action.setdefault(action_key, []).append(issue.issue_key)

    actions: List[GuidedAttemptAction] = []
    for action_key, label in _ACTION_LABELS:
        is_recommended = action_key == recommended_key
        is_safe_view = action_key in _SAFE_VIEW_ACTIONS
        warning_required = bool(blocker_issues) and not is_safe_view and not is_recommended
        is_available = is_safe_view or is_recommended or not blocker_issues
        warning_message = _warning_message(label, blocker_issues) if warning_required else ""
        related_issue_keys = issue_keys_by_action.get(action_key, blocker_issue_keys if warning_required else [])
        actions.append(
            GuidedAttemptAction(
                action_key=action_key,
                label=label,
                is_recommended=is_recommended,
                is_available=is_available,
                warning_required=warning_required,
                warning_message=warning_message,
                related_issue_keys=related_issue_keys,
            )
        )

    return GuidedAttemptActions(
        attempt_id=attempt_id,
        recommended_action=recommended_label,
        readiness_status=readiness_report.readiness_status,
        issue_count=readiness_report.issue_count,
        blocker_count=readiness_report.blocker_count,
        actions=actions,
    )
