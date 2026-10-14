"""Value types for Core AI 2 dataset registry and integrity operations."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class IntegrityResult:
    valid: bool
    checked_at: str
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass(frozen=True)
class DatasetRegistryEntry:
    version: str
    folder_name: str
    created_at: Optional[str]
    export_valid: bool
    training_ready: bool
    split_mode: Optional[str]
    profile_count: int
    page_count: int
    region_count: int
    class_counts: Dict[str, int]
    validation_errors: int
    validation_warnings: int
    blocking_readiness_reasons: List[str]
    readiness_warnings: List[str]
    frozen: bool
    frozen_at: Optional[str]
    manifest_checksum: Optional[str]
    source_commit: Optional[str]
    class_mapping_version: Optional[str]
    dataset_schema_version: Optional[str]
    available_formats: Dict[str, List[str]]
    integrity_valid: bool

    def to_dict(self) -> dict:
        return asdict(self)
