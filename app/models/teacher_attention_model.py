"""Read-only teacher attention summary data structures (Stage 9D)."""

from dataclasses import dataclass, field
from typing import List

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"
PRIORITY_DONE = "done"


@dataclass
class TeacherAttentionItem:
    attempt_id: int
    student_id: int
    student_name: str
    class_name: str
    material_title: str
    paper_type: str
    readiness_status: str
    workflow_status: str
    recommended_action: str
    issue_count: int
    blocker_count: int
    priority: str
    reason: str
    submitted_at: str


@dataclass
class TeacherAttentionSummary:
    teacher_id: int
    total_attempts: int
    blocked_attempts: int
    warning_attempts: int
    pending_review_attempts: int
    finalized_results: int
    kertas1_attempts: int
    kertas2_attempts: int
    attention_items: List[TeacherAttentionItem] = field(default_factory=list)
