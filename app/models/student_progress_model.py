"""Read-only student progress summary data structures (Stage 9E)."""

from dataclasses import dataclass, field
from typing import List, Optional

ITEM_TYPE_MATERIAL = "material"
ITEM_TYPE_ATTEMPT = "attempt"
ITEM_TYPE_RESULT = "result"

DISPLAY_STATUS_AVAILABLE_MATERIAL = "Available material"
DISPLAY_STATUS_ATTEMPT_SUBMITTED = "Attempt submitted"
DISPLAY_STATUS_PENDING_REVIEW = "Pending teacher review"
DISPLAY_STATUS_FINAL_RESULT_AVAILABLE = "Final result available"

ACTION_VIEW_MATERIAL = "View Material"
ACTION_SUBMIT_ATTEMPT = "Submit Attempt"
ACTION_VIEW_ATTEMPT = "View Attempt"
ACTION_VIEW_RESULT = "View Result"


@dataclass
class StudentProgressItem:
    item_type: str
    material_id: Optional[int]
    attempt_id: Optional[int]
    review_id: Optional[int]
    result_type: Optional[str]
    material_title: str
    paper_type: str
    status: str
    display_status: str
    submitted_at_or_finalized_at: str
    action_label: str


@dataclass
class StudentProgressSummary:
    student_id: int
    student_name: str
    class_count: int
    available_materials: int
    submitted_attempts: int
    pending_attempts: int
    finalized_results: int
    kertas1_attempts: int
    kertas2_attempts: int
    recent_items: List[StudentProgressItem] = field(default_factory=list)
