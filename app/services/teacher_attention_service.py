"""Read-only teacher attention summary and queue service (Stage 9D).

This service aggregates teacher-owned attempts with existing workflow,
readiness, guided action, and finalized-result summaries. It never creates
preprocessing, OCR, extraction, marking, review, AI feedback, or export
records.
"""

import sqlite3
from datetime import datetime
from typing import Iterable, List, Set

from app.models.attempt_workflow_status_model import (
    STATUS_AVAILABLE,
    STATUS_FAILED,
    STATUS_FINALIZED,
    STATUS_NEEDS_REVIEW,
)
from app.models.readiness_issue_model import ISSUE_SEVERITY_BLOCKER
from app.models.revision_attempt_model import get_attempts_for_teacher
from app.models.revision_material_model import PAPER_TYPE_KERTAS_1, PAPER_TYPE_KERTAS_2
from app.models.teacher_attention_model import (
    PRIORITY_DONE,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    TeacherAttentionItem,
    TeacherAttentionSummary,
)
from app.services.attempt_readiness_service import (
    ISSUE_FAILED_KERTAS2_FEEDBACK,
    ISSUE_REVIEW_PENDING,
    get_attempt_readiness_report,
)
from app.services.attempt_workflow_status_service import get_attempt_workflow_status
from app.services.guided_attempt_action_service import get_guided_actions_for_attempt
from app.services.result_summary_service import list_teacher_finalized_results

_PRIORITY_ORDER = {
    PRIORITY_HIGH: 0,
    PRIORITY_MEDIUM: 1,
    PRIORITY_LOW: 2,
    PRIORITY_DONE: 3,
}


def _issue_keys(issues: Iterable) -> Set[str]:
    return {issue.issue_key for issue in issues}


def _is_finalized(workflow_status, finalized_attempt_ids: Set[int]) -> bool:
    return (
        workflow_status.attempt_id in finalized_attempt_ids
        or workflow_status.overall_status in (STATUS_AVAILABLE, STATUS_FINALIZED)
    )


def _is_pending_review(workflow_status, readiness_report) -> bool:
    issue_keys = _issue_keys(readiness_report.issues)
    return (
        ISSUE_REVIEW_PENDING in issue_keys
        or workflow_status.overall_status == STATUS_NEEDS_REVIEW
        or workflow_status.next_action in ("Review Kertas 1 marking", "Review Kertas 2 feedback")
    )


def _has_failed_kertas2_feedback(workflow_status, readiness_report) -> bool:
    issue_keys = _issue_keys(readiness_report.issues)
    return ISSUE_FAILED_KERTAS2_FEEDBACK in issue_keys or workflow_status.next_action == "Investigate failed Kertas 2 AI feedback"


def _classify_attention_item(workflow_status, readiness_report, finalized_attempt_ids: Set[int]) -> tuple:
    if _has_failed_kertas2_feedback(workflow_status, readiness_report):
        return PRIORITY_HIGH, "Kertas 2 AI feedback failed and needs investigation."

    if any(issue.severity == ISSUE_SEVERITY_BLOCKER for issue in readiness_report.issues):
        return PRIORITY_HIGH, f"{readiness_report.blocker_count} readiness blocker(s) need attention."

    if _is_pending_review(workflow_status, readiness_report):
        return PRIORITY_MEDIUM, "Teacher review is pending."

    if readiness_report.warning_count > 0:
        return PRIORITY_MEDIUM, f"{readiness_report.warning_count} readiness warning(s) need review."

    if _is_finalized(workflow_status, finalized_attempt_ids):
        return PRIORITY_DONE, "Finalized result is available."

    if workflow_status.overall_status == STATUS_FAILED:
        return PRIORITY_HIGH, "Workflow has a failed step."

    return PRIORITY_LOW, "Ready for the next processing step."


def _sort_attention_items(items: List[TeacherAttentionItem]) -> List[TeacherAttentionItem]:
    def submitted_timestamp(item: TeacherAttentionItem) -> float:
        if not item.submitted_at:
            return 0
        try:
            return datetime.fromisoformat(item.submitted_at).timestamp()
        except ValueError:
            return 0

    return sorted(
        items,
        key=lambda item: (
            _PRIORITY_ORDER[item.priority],
            -submitted_timestamp(item),
            -item.attempt_id,
        )
    )


def get_teacher_attention_summary(conn: sqlite3.Connection, teacher_id: int) -> TeacherAttentionSummary:
    """Return read-only dashboard summary and attention queue for teacher_id.

    Teacher ownership comes from get_attempts_for_teacher and the existing
    per-attempt services. This function only reads existing records.
    """
    attempts = get_attempts_for_teacher(conn, teacher_id)
    finalized_results = list_teacher_finalized_results(conn, teacher_id)
    finalized_attempt_ids = {result.attempt_id for result in finalized_results}

    blocked_attempts = 0
    warning_attempts = 0
    pending_review_attempts = 0
    kertas1_attempts = 0
    kertas2_attempts = 0
    attention_items: List[TeacherAttentionItem] = []

    for attempt in attempts:
        workflow_status = get_attempt_workflow_status(conn, attempt.attempt_id, teacher_id)
        readiness_report = get_attempt_readiness_report(conn, attempt.attempt_id, teacher_id)
        guided_actions = get_guided_actions_for_attempt(conn, attempt.attempt_id, teacher_id)

        if attempt.paper_type == PAPER_TYPE_KERTAS_1:
            kertas1_attempts += 1
        elif attempt.paper_type == PAPER_TYPE_KERTAS_2:
            kertas2_attempts += 1

        if readiness_report.blocker_count > 0:
            blocked_attempts += 1
        if readiness_report.warning_count > 0:
            warning_attempts += 1
        if _is_pending_review(workflow_status, readiness_report):
            pending_review_attempts += 1

        priority, reason = _classify_attention_item(workflow_status, readiness_report, finalized_attempt_ids)
        attention_items.append(
            TeacherAttentionItem(
                attempt_id=attempt.attempt_id,
                student_id=attempt.student_id,
                student_name=attempt.student_name,
                class_name=attempt.class_name,
                material_title=attempt.material_title,
                paper_type=attempt.paper_type,
                readiness_status=readiness_report.readiness_status,
                workflow_status=workflow_status.overall_status,
                recommended_action=guided_actions.recommended_action,
                issue_count=readiness_report.issue_count,
                blocker_count=readiness_report.blocker_count,
                priority=priority,
                reason=reason,
                submitted_at=attempt.submitted_at,
            )
        )

    return TeacherAttentionSummary(
        teacher_id=teacher_id,
        total_attempts=len(attempts),
        blocked_attempts=blocked_attempts,
        warning_attempts=warning_attempts,
        pending_review_attempts=pending_review_attempts,
        finalized_results=len(finalized_results),
        kertas1_attempts=kertas1_attempts,
        kertas2_attempts=kertas2_attempts,
        attention_items=_sort_attention_items(attention_items),
    )
