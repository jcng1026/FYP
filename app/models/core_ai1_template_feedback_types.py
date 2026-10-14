from dataclasses import dataclass, field
from typing import Optional, Tuple


TEMPLATE_FEEDBACK_VERSION = "core-ai1-feedback-templates-v1"
TEMPLATE_CATEGORY_MAPPING_VERSION = "core-ai1-feedback-categories-v1"


@dataclass(frozen=True)
class TemplateFeedbackRequest:
    feedback_category: str
    paper: str
    part: str
    score: Optional[float]
    maximum_score: Optional[float]
    marking_scheme_available: bool
    student_answer_blank: bool
    input_checksum: str
    issue_tags: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TemplateFeedbackResult:
    generated_text: str
    template_version: str
    category_mapping_version: str
    generation_source: str
    input_checksum: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    teacher_review_required: bool = True
    safe_for_direct_student_output: bool = False
