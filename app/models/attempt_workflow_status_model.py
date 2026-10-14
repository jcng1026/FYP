"""Read-only attempt workflow status data structures (Stage 9A).

Nothing in this module writes to the database - it only defines the shapes
used to report an attempt's pipeline progress and recommended next action.
See app/services/attempt_workflow_status_service.py for the read-only logic
that computes these from existing tables.
"""

from dataclasses import dataclass, field
from typing import List, Optional

STATUS_NOT_STARTED = "not_started"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_FINALIZED = "finalized"
STATUS_AVAILABLE = "available"
STATUS_BLOCKED = "blocked"

ALLOWED_STEP_STATUSES = (
    STATUS_NOT_STARTED,
    STATUS_PENDING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_FINALIZED,
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
)

NEXT_ACTION_WORKFLOW_COMPLETE = "Workflow complete"


@dataclass
class WorkflowStep:
    step_key: str
    step_label: str
    status: str
    related_record_id: Optional[int]
    message: str


@dataclass
class AttemptWorkflowStatus:
    attempt_id: int
    material_title: str
    paper_type: str
    student_id: int
    student_name: str
    class_name: str
    overall_status: str
    next_action: str
    current_stage: str
    steps: List[WorkflowStep] = field(default_factory=list)
