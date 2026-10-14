"""Portable value types and constants for production Core AI 2 datasets."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

DATASET_SCHEMA_VERSION = "core-ai2-canonical-v1"
CLASS_MAPPING_VERSION = "core-ai2-classes-v1"
CANONICAL_REGION_TYPES = (
    "question_area", "question_number_box", "bubble_area", "letter_box",
    "underline_answer", "answer_box", "answer_region", "student_info_area",
)
CLASS_MAPPING = {name: index for index, name in enumerate(CANONICAL_REGION_TYPES)}
REGION_COLOURS = {
    "question_area": "#2563EB", "question_number_box": "#7C3AED",
    "bubble_area": "#DC2626", "letter_box": "#EA580C",
    "underline_answer": "#CA8A04", "answer_box": "#16A34A",
    "answer_region": "#0891B2", "student_info_area": "#64748B",
}

@dataclass(frozen=True)
class ValidationIssue:
    code: str
    level: str
    message: str
    profile_id: Optional[int] = None
    page_id: Optional[str] = None
    region_id: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "message": self.message,
                "profile_id": self.profile_id, "page_id": self.page_id,
                "region_id": self.region_id, "details": self.details}

@dataclass(frozen=True)
class ExportConfig:
    include_student_info_area: bool = True
    min_class_examples: int = 5
    near_duplicate_iou: float = .98
    suspicious_overlap_iou: float = .65
    large_region_area: float = .85
    split_ratios: Tuple[float, float, float] = (.7, .15, .15)
    split_seed: int = 42
    allow_three_profile_split: bool = False
    min_suitable_profiles: int = 4
    required_region_types: Tuple[str, ...] = CANONICAL_REGION_TYPES

    def to_dict(self) -> dict:
        return {"include_student_info_area": self.include_student_info_area,
                "min_class_examples": self.min_class_examples,
                "near_duplicate_iou": self.near_duplicate_iou,
                "suspicious_overlap_iou": self.suspicious_overlap_iou,
                "large_region_area": self.large_region_area,
                "split_ratios": list(self.split_ratios), "split_seed": self.split_seed,
                "allow_three_profile_split": self.allow_three_profile_split,
                "min_suitable_profiles": self.min_suitable_profiles,
                "required_region_types": list(self.required_region_types)}
