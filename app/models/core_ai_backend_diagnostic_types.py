from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


COMPATIBILITY_STATES = (
    "confirmed_compatible",
    "expected_compatible",
    "unknown",
    "incompatible",
    "runtime_unavailable",
)


@dataclass(frozen=True)
class RuntimeInspectionRequest:
    model_family: str
    model_version: Optional[str] = None
    dataset_version: Optional[str] = None
    local_base_model_path: Optional[str] = None
    configured_batch_size: Optional[int] = None
    configured_image_size: Optional[int] = None
    configured_sequence_length: Optional[int] = None
    detailed_runtime: bool = False
    completed_run_evidence: bool = False
    previous_oom_evidence: bool = False


@dataclass(frozen=True)
class RuntimeInspectionResult:
    model_family: str
    system: Dict[str, Any]
    packages: Dict[str, Any]
    accelerator: Dict[str, Any]
    local_base_model: Dict[str, Any]
    active_model: Dict[str, Any]
    compatibility: Dict[str, Any]
    memory_status: str
    graceful_no_ai_mode: bool
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    blockers: Tuple[str, ...] = field(default_factory=tuple)
