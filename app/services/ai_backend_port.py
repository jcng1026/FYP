"""Stage 12G-2 - narrow application-side adapter for the Core AI backend.

The real backend (Codex `app.services.core_ai_backend_runtime_facade.
CoreAIBackendRuntimeFacade`, see AI_BACKEND_INTEGRATION.md) is not merged into
this worktree yet. To let the admin AI Models UI be built and tested now, this
module defines a NARROW port (Protocol) whose method names and dependency-free
result dataclasses MIRROR the Codex façade exactly, plus a deterministic
in-memory fake used by tests and until the real façade is wired.

Integration note (record for final merge):
- `DatasetDescriptor` here mirrors `app.models.core_ai_backend_contracts.
  DatasetDescriptor` field-for-field, so the real façade's return values map
  onto it directly.
- `CoreAI2DatasetPort` mirrors the façade's dataset methods for
  `model_family="core_ai2"`: list_datasets / inspect_dataset / audit_dataset /
  compare_datasets / freeze_dataset / convert_dataset.
- At merge, replace `get_core_ai2_dataset_backend()` with a thin wrapper that
  calls the real façade; no UI/service change should be required.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

MODEL_FAMILY_CORE_AI2 = "core_ai2"
MODEL_FAMILY_CORE_AI1 = "core_ai1"

CONVERSION_FORMAT_YOLO = "yolo"
CONVERSION_FORMAT_COCO = "coco"
CORE_AI2_CONVERSION_FORMATS = (CONVERSION_FORMAT_YOLO, CONVERSION_FORMAT_COCO)


class BackendError(RuntimeError):
    """Mirror of the Codex `BackendError`: inspect `code`, show only
    `safe_message` to users."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class DatasetDescriptor:
    """Mirror of Codex `core_ai_backend_contracts.DatasetDescriptor`.

    `export_valid`, `training_ready` and `frozen` are deliberately three
    independent facts (a dataset can be export-valid and frozen but still not
    training-ready). `statistics` carries the count/split detail the UI shows;
    documented keys (all optional): profile_count, page_count, region_count,
    class_count, excluded_region_count, unsupported_region_count,
    leakage_safe_split (bool), split_ratios, recommendations (list[str])."""
    family: str
    version: str
    path: str
    export_valid: bool
    training_ready: bool
    frozen: bool
    schema_version: Optional[str] = None
    mapping_version: Optional[str] = None
    source_commit: Optional[str] = None
    manifest_checksum: Optional[str] = None
    split_mode: Optional[str] = None
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    supported_formats: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatasetComparison:
    family: str
    left_version: str
    right_version: str
    differences: List[str]
    left: DatasetDescriptor
    right: DatasetDescriptor


@dataclass(frozen=True)
class DatasetAuditReport:
    family: str
    version: str
    ok: bool
    checked_at: str
    findings: List[str]
    recommendations: List[str]


@dataclass(frozen=True)
class ConversionResult:
    family: str
    version: str
    output_format: str
    conversion_version: str
    output_path: str
    checksum: Optional[str]
    created: bool


class CoreAI2DatasetPort(Protocol):
    """Dataset methods the admin Core AI 2 dataset controls call. Mirrors the
    Codex façade's dataset surface for the core_ai2 family."""

    def list_datasets(self, model_family: str) -> List[DatasetDescriptor]: ...

    def inspect_dataset(self, model_family: str, version: str) -> DatasetDescriptor: ...

    def audit_dataset(self, model_family: str, version: str) -> DatasetAuditReport: ...

    def compare_datasets(self, model_family: str, left: str, right: str) -> DatasetComparison: ...

    def freeze_dataset(self, model_family: str, version: str, actor: Optional[str] = None,
                       note: Optional[str] = None) -> DatasetDescriptor: ...

    def convert_dataset(self, model_family: str, version: str, output_format: str,
                        conversion_version: str) -> ConversionResult: ...


# ===========================================================================
# Subsystem 3 - training jobs, model registry, evaluation, activation,
# runtime diagnostics. Mirrors the Codex facade job/model surface so the fake
# is a drop-in. Result-shape mappings for final integration are recorded in
# each dataclass docstring.
# ===========================================================================

# JobStatus mirror (core_ai_backend_contracts.JobStatus values).
JOB_QUEUED = "queued"
JOB_VALIDATING = "validating"
JOB_RUNNING = "running"
JOB_CANCELLING = "cancelling"
JOB_CANCELLED = "cancelled"
JOB_PUBLISHING = "publishing"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_INTERRUPTED = "interrupted"
ALL_JOB_STATUSES = (JOB_QUEUED, JOB_VALIDATING, JOB_RUNNING, JOB_CANCELLING, JOB_CANCELLED,
                    JOB_PUBLISHING, JOB_COMPLETED, JOB_FAILED, JOB_INTERRUPTED)
TERMINAL_JOB_STATES = {JOB_CANCELLED, JOB_COMPLETED, JOB_FAILED, JOB_INTERRUPTED}
NONTERMINAL_JOB_STATES = {JOB_QUEUED, JOB_VALIDATING, JOB_RUNNING, JOB_CANCELLING, JOB_PUBLISHING}


@dataclass
class TrainingJobRecord:
    """Mirror of Codex `TrainingJobRecord`. `progress_value` is Optional - the
    UI must show `progress_message` always and a percentage ONLY when
    progress_value is not None (never invent a percentage)."""
    job_id: str
    model_family: str
    dataset_version: str
    requested_model_version: str
    created_at: str
    status: str = JOB_QUEUED
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancellation_requested: bool = False
    progress_message: str = "Queued"
    progress_value: Optional[float] = None
    current_epoch: Optional[int] = None
    current_step: Optional[int] = None
    configuration: Dict[str, Any] = field(default_factory=dict)
    hardware_runtime: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    result_model_version: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None


@dataclass(frozen=True)
class ModelDescriptor:
    """Mirror of Codex `ModelDescriptor`. Note: the facade `list_models`
    returns filtered dicts, while `inspect_model` returns this shape - the
    integration wrapper maps list dicts onto ModelDescriptor."""
    family: str
    version: str
    path: str
    checksum: str
    created_at: str
    source_dataset_version: str
    source_dataset_checksum: str
    training_job_id: str
    base_model_identifier: str
    architecture: str
    mapping: Dict[str, int] = field(default_factory=dict)
    compatible_schema_versions: List[str] = field(default_factory=list)
    evaluation_status: str = "unevaluated"
    activation_status: str = "inactive"
    runtime_compatibility: str = "unknown"
    hardware_requirements: Dict[str, Any] = field(default_factory=dict)
    artifact_inventory: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationResult:
    """Mirror of Codex `EvaluationResult`."""
    evaluation_id: str
    model_version: str
    dataset_version: str
    dataset_checksum: str
    split: str
    metrics: Dict[str, Any]
    per_class_metrics: Dict[str, Any]
    errors: List[str]
    warnings: List[str]
    passed: bool
    decision_criteria: Dict[str, Any]
    evaluated_at: str


@dataclass(frozen=True)
class ModelComparison:
    family: str
    left_version: str
    right_version: str
    differences: List[str]


@dataclass(frozen=True)
class RuntimeInspection:
    """Simplified projection of Codex `RuntimeInspectionResult` (the fields the
    UI shows). Integration maps RuntimeInspectionResult -> this. `memory_status`
    is exactly one of confirmed_compatible / expected_compatible / unknown /
    incompatible / runtime_unavailable - a family/model name alone never yields
    an 8 GB compatibility claim."""
    model_family: str
    memory_status: str
    graceful_no_ai_mode: bool
    compatibility: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)


MEMORY_STATUS_VALUES = ("confirmed_compatible", "expected_compatible", "unknown",
                        "incompatible", "runtime_unavailable")


class CoreAIJobModelPort(Protocol):
    """Job/model/runtime methods the admin training+activation UI calls.
    Mirrors the Codex facade surface for a model family."""

    def validate_training_request(self, model_family: str, dataset_version: str,
                                  configuration: Dict[str, Any]) -> List[str]: ...

    def create_training_job(self, model_family: str, dataset_version: str,
                            configuration: Dict[str, Any]) -> TrainingJobRecord: ...

    def run_training_job(self, job_id: str, configuration: Dict[str, Any]) -> TrainingJobRecord: ...

    def cancel_training_job(self, job_id: str) -> TrainingJobRecord: ...

    def finalize_cancellation(self, job_id: str) -> TrainingJobRecord:
        """Complete an acknowledged cancellation: cancelling -> cancelled.
        Called once the worker has actually stopped, so the job reaches a
        TERMINAL state rather than sitting in 'cancelling' forever."""
        ...

    def get_training_job(self, job_id: str) -> TrainingJobRecord: ...

    def list_training_jobs(self, model_family: Optional[str] = None) -> List[TrainingJobRecord]: ...

    def recover_interrupted_jobs(self) -> List[TrainingJobRecord]: ...

    def list_models(self, model_family: str) -> List[ModelDescriptor]: ...

    def inspect_model(self, model_family: str, version: str) -> ModelDescriptor: ...

    def evaluate_model(self, model_family: str, model_version: str,
                       dataset_version: str) -> EvaluationResult: ...

    def compare_models(self, model_family: str, left: str, right: str) -> ModelComparison: ...

    def activate_model(self, model_family: str, version: str, actor: str, reason: str) -> ModelDescriptor: ...

    def rollback_model(self, model_family: str, target_version: str, actor: str,
                       reason: str) -> ModelDescriptor: ...

    def get_active_model(self, model_family: str, required: bool = True) -> Optional[ModelDescriptor]: ...

    def inspect_runtime(self, model_family: str, model_version: Optional[str] = None) -> RuntimeInspection: ...


# ===========================================================================
# Subsystem 4 - Core AI 2 region-proposal inference. Mirrors the Codex
# core_ai2_inference_types so the fake is a drop-in.
# ===========================================================================

# The REAL Core AI 2 inference service reports "completed" (see
# core_ai2_inference_service.CoreAI2InferenceResult); the earlier "ok" was a
# fake-era guess and made the application discard every real proposal.
INFERENCE_STATUS_OK = "completed"
INFERENCE_STATUS_FAILED = "failed"
INFERENCE_STATUS_NO_MODEL = "no_active_model"

WORKFLOW_SUBJECT_PROFILE = "subject_profile"
WORKFLOW_SEPARATE_ANSWER_PAPER = "separate_answer_paper"


@dataclass(frozen=True)
class CoreAI2InferenceRequest:
    """Mirror of Codex `CoreAI2InferenceRequest`."""
    request_id: str
    workflow_context: str
    page_image_path: str
    page_checksum: str
    page_width: int
    page_height: int
    model_version: Optional[str] = None
    confidence_threshold: float = 0.25
    nms_threshold: float = 0.5
    allowed_classes: Optional[List[str]] = None
    profile_id: Optional[int] = None
    attempt_id: Optional[int] = None


@dataclass(frozen=True)
class RegionProposal:
    """Mirror of Codex `RegionProposal`. `normalized_bbox` is (x, y, w, h) in
    0-1 page coordinates. `rationale`/`provenance` may be None/empty - the UI
    must not invent them."""
    proposal_id: str
    model_family: str
    model_version: str
    model_checksum: str
    page_checksum: str
    region_class: str
    normalized_bbox: tuple
    pixel_bbox: tuple
    confidence: float
    class_probabilities: Optional[Dict[str, float]] = None
    runtime_duration_seconds: float = 0.0
    device_used: str = "cpu"
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    rationale: Optional[str] = None


@dataclass(frozen=True)
class CoreAI2InferenceResult:
    """Mirror of Codex `CoreAI2InferenceResult`. On failure/no-model the
    proposals list is empty and failure_code/message explain why - manual
    mapping must remain fully usable."""
    request_id: str
    status: str
    proposals: List[RegionProposal]
    model_version: Optional[str]
    model_checksum: Optional[str]
    page_checksum: str
    runtime_duration_seconds: float = 0.0
    device_used: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    # Raw detector output, carried for lineage only. The application never
    # renders it - a proposal is only ever shown through `proposals`.
    raw_outputs: Any = None


class CoreAI2InferencePort(Protocol):
    def run_core_ai2_inference(self, request: CoreAI2InferenceRequest,
                               cancellation_token=None) -> CoreAI2InferenceResult: ...


# ===========================================================================
# Subsystem 5 - Core AI 1 (Kertas 2 scoring) dataset controls. Export is a
# DIRECT adapter call (the backend consumes a Claude-owned finalized-record
# adapter), so this port exposes export_dataset(adapter, ...) rather than the
# convert step Core AI 2 uses. DatasetDescriptor is shared (family="core_ai1").
# ===========================================================================


@dataclass(frozen=True)
class CoreAI1DatasetConfig:
    """Mirror of Codex core_ai1_dataset_types.CoreAI1DatasetConfig."""
    category_mapping: Dict[str, int]
    category_mapping_version: str
    seed: int = 42
    split_ratios: tuple = (0.7, 0.15, 0.15)
    min_samples: int = 30
    min_groups: int = 4
    min_examples_per_category: int = 5
    required_parts: tuple = ("part1", "part2", "part3")


class CoreAI1DatasetPort(Protocol):
    """Core AI 1 dataset methods the admin controls call. `export_dataset`
    takes the Claude-owned finalized-record adapter (list_finalized_k2_examples)
    and produces a new dataset version."""

    def list_datasets(self, model_family: str) -> List[DatasetDescriptor]: ...

    def inspect_dataset(self, model_family: str, version: str) -> DatasetDescriptor: ...

    def audit_dataset(self, model_family: str, version: str) -> "DatasetAuditReport": ...

    def compare_datasets(self, model_family: str, left: str, right: str) -> "DatasetComparison": ...

    def freeze_dataset(self, model_family: str, version: str, actor=None, note=None) -> DatasetDescriptor: ...

    def export_dataset(self, adapter, version: str, config: CoreAI1DatasetConfig) -> DatasetDescriptor: ...


# ===========================================================================
# Subsystem 6 - Core AI 1 inference (Kertas 2 draft scoring + feedback
# category). Mirrors the Codex `core_ai1_inference_types` dataclasses and the
# facade's `run_core_ai1_inference` / `run_core_ai1_attempt_inference`.
# Results are TEACHER-REVIEW DRAFTS ONLY - they never become a final score.
# ===========================================================================

ROUNDING_POLICY_VERSION = "nearest-half-mark-half-up-v1"

CORE_AI1_STATUS_COMPLETED = "completed"
CORE_AI1_STATUS_SKIPPED = "skipped"
CORE_AI1_STATUS_ATTENTION_REQUIRED = "attention_required"
CORE_AI1_STATUS_FAILED = "failed"

CORE_AI1_FAILURE_TEACHER_REVIEWED = "teacher_reviewed"
CORE_AI1_FAILURE_KERTAS1 = "kertas1_unsupported"
CORE_AI1_FAILURE_BLANK_ANSWER = "blank_answer"
CORE_AI1_FAILURE_INVALID_MAX = "invalid_maximum_score"
CORE_AI1_FAILURE_NO_ACTIVE_MODEL = "no_active_model"


@dataclass(frozen=True)
class CoreAI1InferenceRequest:
    """Mirror of Codex `CoreAI1InferenceRequest` (field order preserved)."""
    request_id: str
    task_context: str
    marking_scheme: str
    effective_student_answer: str
    paper: str
    part: str
    maximum_score: float
    input_checksum: str
    selected_part3_question: Optional[str] = None
    model_version: Optional[str] = None
    existing_teacher_reviewed: bool = False


@dataclass(frozen=True)
class CoreAI1InferenceResult:
    """Mirror of Codex `CoreAI1InferenceResult` (field order preserved)."""
    request_id: str
    status: str
    draft_raw_score: Optional[float]
    normalized_score: Optional[float]
    proposed_application_score: Optional[float]
    feedback_category: Optional[str]
    category_confidence: Optional[float]
    score_confidence: Optional[float]
    model_version: Optional[str]
    model_checksum: Optional[str]
    dataset_lineage: Optional[str]
    input_template_version: Optional[str]
    input_checksum: str
    truncation_warning: bool
    missing_scheme_warning: bool
    warnings: List[str] = field(default_factory=list)
    runtime_duration_seconds: float = 0
    device: Optional[str] = None
    clamped: bool = False
    rounding_policy_version: str = ROUNDING_POLICY_VERSION
    failure_code: Optional[str] = None
    category_probabilities: Optional[Dict[str, float]] = None
    truncation_statistics: Optional[Dict[str, int]] = None


class CoreAI1InferencePort(Protocol):
    """Draft-scoring calls. Both may BLOCK - the application always runs them
    in a background worker. Every request yields exactly one result, and a
    failed item never removes the successful ones."""

    def run_core_ai1_inference(self, request: CoreAI1InferenceRequest) -> CoreAI1InferenceResult: ...

    def run_core_ai1_attempt_inference(
            self, requests: List[CoreAI1InferenceRequest]) -> List[CoreAI1InferenceResult]: ...


# ===========================================================================
# Subsystem 8 - Kertas 2 natural-language feedback. Mirrors the Codex
# `LocalFeedbackRequest` / `FeedbackResult` and `TemplateFeedbackRequest` /
# `TemplateFeedbackResult`. Feedback is WORDING ONLY - it never carries,
# derives or changes a score.
# ===========================================================================

LOCAL_FEEDBACK_PROMPT_VERSION = "local-feedback-v2"
TEMPLATE_FEEDBACK_VERSION = "core-ai1-feedback-templates-v1"
TEMPLATE_CATEGORY_MAPPING_VERSION = "core-ai1-feedback-categories-v1"

FEEDBACK_SOURCE_LOCAL_LLM = "local_llm"
FEEDBACK_SOURCE_TEMPLATE = "deterministic_template"
FEEDBACK_SOURCE_PREVIOUS_TEACHER = "previous_teacher_feedback"


@dataclass(frozen=True)
class LocalFeedbackRequest:
    """Mirror of Codex `LocalFeedbackRequest` (field order preserved)."""
    request_id: str
    adapter: str
    endpoint: str
    model_name: str
    question_context: str
    marking_scheme: str
    effective_student_answer: str
    feedback_category: str
    score_context: float
    maximum_score: float
    paper: str
    part: str
    input_checksum: str
    timeout_seconds: float = 15
    maximum_output_tokens: int = 180
    temperature: float = 0.2
    response_size_limit: int = 8192
    requested_feedback_length: int = 500
    allow_private_network: bool = False
    previous_teacher_feedback: Optional[str] = None


@dataclass(frozen=True)
class FeedbackResult:
    """Mirror of Codex `FeedbackResult` (field order preserved)."""
    generation_source: str
    runtime_identifier: str
    model_name: Optional[str]
    input_checksum: str
    feedback_category: str
    generated_feedback: Optional[str]
    template_fallback_feedback: Optional[str]
    warnings: List[str]
    duration_seconds: float
    failure_status: Optional[str] = None


@dataclass(frozen=True)
class TemplateFeedbackRequest:
    """Mirror of Codex `TemplateFeedbackRequest`."""
    feedback_category: str
    paper: str
    part: str
    score: Optional[float]
    maximum_score: Optional[float]
    marking_scheme_available: bool
    student_answer_blank: bool
    input_checksum: str
    issue_tags: tuple = ()


@dataclass(frozen=True)
class TemplateFeedbackResult:
    """Mirror of Codex `TemplateFeedbackResult`."""
    generated_text: str
    template_version: str
    category_mapping_version: str
    generation_source: str
    input_checksum: str
    warnings: tuple = ()
    teacher_review_required: bool = True
    safe_for_direct_student_output: bool = False


class FeedbackPort(Protocol):
    """Natural-language feedback generation. `generate_local_feedback` MAY
    BLOCK on a local runtime and is always called from a background worker;
    `generate_template_feedback` is deterministic, offline and instant."""

    def generate_local_feedback(self, request: LocalFeedbackRequest,
                                cancellation_token=None) -> FeedbackResult: ...

    def generate_template_feedback(
            self, request: TemplateFeedbackRequest) -> TemplateFeedbackResult: ...
