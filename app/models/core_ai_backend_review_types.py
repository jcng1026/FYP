from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence


@dataclass(frozen=True)
class CoreAI1ReviewedRecord:
    record_id: str
    finalized: bool
    stale_draft: bool
    original_draft_score: Optional[float]
    original_draft_category: Optional[str]
    teacher_final_score: Optional[float]
    teacher_final_category: Optional[str]
    draft_disposition: str
    input_checksum: str
    model_version: str
    teacher_final_student_feedback: Optional[str]
    feedback_capture_permitted: bool
    paper: str
    part: str
    question_context: str
    marking_scheme_checksum: Optional[str]
    attempt_group_id: str
    student_group_id: str
    profile_group_id: str
    finalized_at: str


@dataclass(frozen=True)
class CoreAI2ReviewedProposal:
    proposal_id: str
    proposed_class: str
    proposed_geometry: Sequence[float]
    final_teacher_class: Optional[str]
    final_teacher_geometry: Optional[Sequence[float]]
    review_status: str
    model_version: str
    model_checksum: str
    page_checksum: str
    profile_group_id: str
    attempt_group_id: str
    reason_code: Optional[str] = None


@dataclass(frozen=True)
class CandidateCaptureResult:
    family: str
    candidate_version: str
    path: str
    manifest_checksum: str
    statistics: Dict[str, Any]
    frozen: bool = False
    training_started: bool = False
    model_activated: bool = False
