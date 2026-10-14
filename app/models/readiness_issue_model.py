"""Read-only readiness issue data structures (Stage 9B).

These models describe setup and attempt-readiness findings only. They do
not create jobs, reviews, markings, exports, or AI requests.
"""

from dataclasses import dataclass, field
from typing import List, Optional

TARGET_TYPE_REVISION_ATTEMPT = "revision_attempt"

READINESS_STATUS_READY = "ready"
READINESS_STATUS_BLOCKED = "blocked"
READINESS_STATUS_WARNING = "warning"
READINESS_STATUS_COMPLETED = "completed"

ISSUE_SEVERITY_BLOCKER = "blocker"
ISSUE_SEVERITY_WARNING = "warning"

ISSUE_STATUS_OPEN = "open"


@dataclass
class ReadinessIssue:
    issue_key: str
    severity: str
    status: str
    title: str
    message: str
    recommended_action: str
    related_record_id: Optional[int] = None


@dataclass
class AttemptReadinessReport:
    target_type: str
    target_id: int
    paper_type: str
    readiness_status: str
    issue_count: int
    blocker_count: int
    warning_count: int
    issues: List[ReadinessIssue] = field(default_factory=list)
    issue_summary: str = ""
    next_action: str = ""
    current_stage: str = ""
