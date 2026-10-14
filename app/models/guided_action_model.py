"""Read-only guided action data structures for revision attempts (Stage 9C)."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class GuidedAttemptAction:
    action_key: str
    label: str
    is_recommended: bool
    is_available: bool
    warning_required: bool
    warning_message: str
    related_issue_keys: List[str] = field(default_factory=list)


@dataclass
class GuidedAttemptActions:
    attempt_id: int
    recommended_action: str
    readiness_status: str
    issue_count: int
    blocker_count: int
    actions: List[GuidedAttemptAction] = field(default_factory=list)
