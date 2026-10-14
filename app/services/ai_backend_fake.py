"""Stage 12G-2 - deterministic in-memory fake of the Core AI 2 dataset backend.

Used by tests and until the real Codex façade is merged. It fabricates NO real
dataset content, model weights or metrics - it only models the state machine
the UI must handle (export-valid vs frozen vs training-ready, freeze rules,
conversion no-overwrite). Real readiness/training/evaluation come only from the
merged Codex backend.
"""
import copy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.services.ai_backend_port import (
    CORE_AI2_CONVERSION_FORMATS,
    MODEL_FAMILY_CORE_AI2,
    BackendError,
    ConversionResult,
    DatasetAuditReport,
    DatasetComparison,
    DatasetDescriptor,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_fake_datasets() -> List[DatasetDescriptor]:
    """Two representative datasets: one export-valid but NOT training-ready
    (has blockers) and unfrozen; one frozen AND training-ready."""
    return [
        DatasetDescriptor(
            family=MODEL_FAMILY_CORE_AI2, version="dataset_0001",
            path="ai/datasets/core_ai2/dataset_0001", export_valid=True, training_ready=False,
            frozen=False, schema_version="s1", mapping_version="m1", split_mode="profile_grouped",
            blockers=["Not frozen", "Too few labelled pages for a leakage-safe split"],
            warnings=["3 regions excluded as unsupported region types"],
            statistics={"profile_count": 2, "page_count": 12, "region_count": 40, "class_count": 4,
                        "excluded_region_count": 3, "unsupported_region_count": 3,
                        "leakage_safe_split": False, "split_ratios": [0.7, 0.15, 0.15],
                        "recommendations": ["Label more pages before training."]},
            supported_formats=list(CORE_AI2_CONVERSION_FORMATS)),
        DatasetDescriptor(
            family=MODEL_FAMILY_CORE_AI2, version="dataset_0002",
            path="ai/datasets/core_ai2/dataset_0002", export_valid=True, training_ready=True,
            frozen=True, schema_version="s1", mapping_version="m1", split_mode="profile_grouped",
            manifest_checksum="deadbeef", blockers=[], warnings=[],
            statistics={"profile_count": 6, "page_count": 120, "region_count": 480, "class_count": 4,
                        "excluded_region_count": 0, "unsupported_region_count": 0,
                        "leakage_safe_split": True, "split_ratios": [0.7, 0.15, 0.15],
                        "recommendations": []},
            supported_formats=list(CORE_AI2_CONVERSION_FORMATS)),
    ]


class FakeCoreAI2DatasetBackend:
    """Deterministic CoreAI2DatasetPort implementation."""

    def __init__(self, datasets: Optional[List[DatasetDescriptor]] = None) -> None:
        seed = datasets if datasets is not None else default_fake_datasets()
        self._datasets: Dict[str, DatasetDescriptor] = {d.version: d for d in seed}
        # conversion_version -> ConversionResult, keyed to enforce no-overwrite.
        self._conversions: Dict[str, ConversionResult] = {}

    def _require_core_ai2(self, model_family: str) -> None:
        if model_family != MODEL_FAMILY_CORE_AI2:
            raise BackendError("unsupported_family", f"This backend only serves {MODEL_FAMILY_CORE_AI2}.")

    def _get(self, version: str) -> DatasetDescriptor:
        dataset = self._datasets.get(version)
        if dataset is None:
            raise BackendError("dataset_not_found", f"Dataset '{version}' was not found.")
        return dataset

    def list_datasets(self, model_family: str) -> List[DatasetDescriptor]:
        self._require_core_ai2(model_family)
        return [copy.deepcopy(d) for d in self._datasets.values()]

    def inspect_dataset(self, model_family: str, version: str) -> DatasetDescriptor:
        self._require_core_ai2(model_family)
        return copy.deepcopy(self._get(version))

    def audit_dataset(self, model_family: str, version: str) -> DatasetAuditReport:
        self._require_core_ai2(model_family)
        d = self._get(version)
        findings = list(d.warnings)
        if not d.export_valid:
            findings.append("Export is not valid.")
        return DatasetAuditReport(
            family=model_family, version=version, ok=d.export_valid, checked_at=_now(),
            findings=findings, recommendations=list(d.statistics.get("recommendations", [])))

    def compare_datasets(self, model_family: str, left: str, right: str) -> DatasetComparison:
        self._require_core_ai2(model_family)
        a, b = self._get(left), self._get(right)
        diffs = []
        for label, va, vb in (
            ("frozen", a.frozen, b.frozen), ("export_valid", a.export_valid, b.export_valid),
            ("training_ready", a.training_ready, b.training_ready),
            ("region_count", a.statistics.get("region_count"), b.statistics.get("region_count")),
            ("page_count", a.statistics.get("page_count"), b.statistics.get("page_count")),
            ("leakage_safe_split", a.statistics.get("leakage_safe_split"),
             b.statistics.get("leakage_safe_split")),
        ):
            if va != vb:
                diffs.append(f"{label}: {va} -> {vb}")
        return DatasetComparison(family=model_family, left_version=left, right_version=right,
                                 differences=diffs, left=copy.deepcopy(a), right=copy.deepcopy(b))

    def freeze_dataset(self, model_family: str, version: str, actor: Optional[str] = None,
                       note: Optional[str] = None) -> DatasetDescriptor:
        self._require_core_ai2(model_family)
        d = self._get(version)
        if not d.export_valid:
            raise BackendError("not_export_valid", "Only an export-valid dataset can be frozen.")
        if d.frozen:
            raise BackendError("already_frozen", "This dataset is already frozen (freezing is permanent).")
        # Freezing does not by itself make a dataset training-ready.
        frozen = DatasetDescriptor(**{**d.__dict__, "frozen": True})
        self._datasets[version] = frozen
        return copy.deepcopy(frozen)

    def convert_dataset(self, model_family: str, version: str, output_format: str,
                        conversion_version: str) -> ConversionResult:
        self._require_core_ai2(model_family)
        d = self._get(version)
        if output_format not in CORE_AI2_CONVERSION_FORMATS:
            raise BackendError("unsupported_format",
                               f"Core AI 2 supports only {', '.join(CORE_AI2_CONVERSION_FORMATS)}.")
        if not d.frozen:
            raise BackendError("not_frozen", "Convert a frozen dataset (freeze it first).")
        key = f"{version}:{output_format}:{conversion_version}"
        if key in self._conversions:
            raise BackendError("conversion_exists",
                               "A conversion with this version already exists (overwrite is not allowed).")
        result = ConversionResult(
            family=model_family, version=version, output_format=output_format,
            conversion_version=conversion_version,
            output_path=f"{d.path}/conversions/{output_format}/{conversion_version}",
            checksum=f"chk_{output_format}_{conversion_version}", created=True)
        self._conversions[key] = result
        return result


# ===========================================================================
# Subsystem 3 - deterministic fake job/model/runtime backend.
# ===========================================================================
import itertools

from app.services.ai_backend_port import (
    JOB_CANCELLED,
    JOB_CANCELLING,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_INTERRUPTED,
    JOB_PUBLISHING,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_VALIDATING,
    NONTERMINAL_JOB_STATES,
    TERMINAL_JOB_STATES,
    EvaluationResult,
    ModelComparison,
    ModelDescriptor,
    RuntimeInspection,
    TrainingJobRecord,
)


class FakeCoreAIJobModelBackend:
    """Deterministic CoreAIJobModelPort implementation.

    Fabricates NO real training/metrics - it models only the state machine the
    UI must handle: validation blockers, the queued->...->completed/failed/
    cancelled/interrupted transitions, structured events (some without a
    progress percentage), evaluation gating for activation, and lineage.
    """

    def __init__(self, model_family: str = MODEL_FAMILY_CORE_AI2,
                 dataset_provider=None, ready_dataset_versions: Optional[List[str]] = None,
                 fail_job: bool = False) -> None:
        self.model_family = model_family
        # Readiness is decided from the REAL dataset descriptor, exactly as the
        # backend facade does - never from an opaque list of version strings.
        # `dataset_provider(version) -> DatasetDescriptor | None`.
        if dataset_provider is None and ready_dataset_versions is None:
            defaults = {d.version: d for d in default_fake_datasets()}
            dataset_provider = defaults.get
        self._dataset_provider = dataset_provider
        self._ready = set(ready_dataset_versions or ())
        self._fail_job = fail_job
        self._jobs: Dict[str, TrainingJobRecord] = {}
        self._models: Dict[str, ModelDescriptor] = {}
        self._evaluations: Dict[str, EvaluationResult] = {}
        self._active_version: Optional[str] = None
        self._ids = itertools.count(1)

    def _require_family(self, model_family: str) -> None:
        if model_family != self.model_family:
            raise BackendError("unsupported_family", f"This backend serves {self.model_family}.")

    # --- validation + jobs --------------------------------------------------

    def validate_training_request(self, model_family: str, dataset_version: str,
                                  configuration: Dict) -> List[str]:
        """Every reason this dataset cannot be trained from. Training requires a
        dataset that is FROZEN and TRAINING-READY with a leakage-safe split; an
        export-valid but unready dataset stays inspectable and freezeable only.
        The dataset's own readiness blockers are surfaced verbatim so the
        rejection tells the admin exactly what to fix."""
        self._require_family(model_family)
        blockers: List[str] = []
        descriptor = self._dataset_provider(dataset_version) if self._dataset_provider else None
        if descriptor is None:
            if dataset_version in self._ready:
                pass  # explicitly declared ready by a caller with no descriptor
            else:
                blockers.append(f"Dataset '{dataset_version}' was not found.")
        else:
            if not descriptor.frozen:
                blockers.append(
                    f"Dataset '{dataset_version}' is not frozen. Freeze it before training.")
            if not descriptor.training_ready:
                blockers.append(f"Dataset '{dataset_version}' is not training-ready.")
            if not descriptor.statistics.get("leakage_safe_split", True):
                blockers.append(
                    f"Dataset '{dataset_version}' does not have a leakage-safe split.")
            blockers.extend(descriptor.blockers)
        if not configuration.get("target_version"):
            blockers.append("A target model version label is required.")
        return blockers

    def create_training_job(self, model_family: str, dataset_version: str,
                            configuration: Dict) -> TrainingJobRecord:
        self._require_family(model_family)
        blockers = self.validate_training_request(model_family, dataset_version, configuration)
        if blockers:
            raise BackendError("validation_failed", "; ".join(blockers))
        job_id = f"job_{next(self._ids):04d}"
        record = TrainingJobRecord(
            job_id=job_id, model_family=model_family, dataset_version=dataset_version,
            requested_model_version=configuration.get("target_version", ""), created_at=_now(),
            status=JOB_QUEUED, progress_message="Queued", progress_value=None,
            configuration=dict(configuration))
        self._jobs[job_id] = record
        return copy.deepcopy(record)

    def get_training_job(self, job_id: str) -> TrainingJobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise BackendError("job_not_found", f"Job '{job_id}' was not found.")
        return copy.deepcopy(job)

    def list_training_jobs(self, model_family: Optional[str] = None) -> List[TrainingJobRecord]:
        return [copy.deepcopy(j) for j in self._jobs.values()
                if model_family is None or j.model_family == model_family]

    def run_training_job(self, job_id: str, configuration: Dict) -> TrainingJobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise BackendError("job_not_found", f"Job '{job_id}' was not found.")
        job.status = JOB_VALIDATING
        job.started_at = _now()
        job.progress_message = "Validating dataset and configuration"
        job.progress_value = None
        job.events.append({"status": JOB_VALIDATING, "message": job.progress_message, "progress": None})
        if job.cancellation_requested:
            return self._finish_cancelled(job)

        job.status = JOB_RUNNING
        for pct, epoch in ((25.0, 1), (60.0, 2), (90.0, 3)):
            if job.cancellation_requested:
                return self._finish_cancelled(job)
            job.progress_message = f"Training epoch {epoch}"
            job.progress_value = pct
            job.current_epoch = epoch
            job.events.append({"status": JOB_RUNNING, "message": job.progress_message, "progress": pct})

        if self._fail_job:
            job.status = JOB_FAILED
            job.completed_at = _now()
            job.failure_code = "training_error"
            job.failure_message = "Deterministic fake failure"
            job.progress_message = "Failed"
            job.events.append({"status": JOB_FAILED, "message": job.failure_message, "progress": None})
            return copy.deepcopy(job)

        job.status = JOB_PUBLISHING
        job.progress_message = "Publishing model"
        job.progress_value = None
        job.events.append({"status": JOB_PUBLISHING, "message": job.progress_message, "progress": None})
        version = job.requested_model_version
        self._models[version] = ModelDescriptor(
            family=job.model_family, version=version, path=f"ai/models/{job.model_family}/{version}",
            checksum=f"chk_{version}", created_at=_now(), source_dataset_version=job.dataset_version,
            source_dataset_checksum=f"chk_{job.dataset_version}", training_job_id=job.job_id,
            base_model_identifier=job.configuration.get("base_model", "local-base"),
            architecture="yolo" if job.model_family == MODEL_FAMILY_CORE_AI2 else "cross-encoder",
            compatible_schema_versions=["s1"], evaluation_status="unevaluated",
            activation_status="inactive", runtime_compatibility="unknown")
        job.status = JOB_COMPLETED
        job.completed_at = _now()
        job.result_model_version = version
        job.progress_message = "Completed"
        job.progress_value = 100.0
        job.events.append({"status": JOB_COMPLETED, "message": "Completed", "progress": 100.0})
        return copy.deepcopy(job)

    def _finish_cancelled(self, job: TrainingJobRecord) -> TrainingJobRecord:
        job.status = JOB_CANCELLED
        job.completed_at = _now()
        job.progress_message = "Cancelled"
        job.result_model_version = None  # cancelled jobs never publish a model
        job.events.append({"status": JOB_CANCELLED, "message": "Cancelled", "progress": None})
        return copy.deepcopy(job)

    def cancel_training_job(self, job_id: str) -> TrainingJobRecord:
        """Request cancellation. A job already cancelling or already in a
        terminal state cannot be cancelled again - the second request is
        refused rather than silently reprocessed."""
        job = self._jobs.get(job_id)
        if job is None:
            raise BackendError("job_not_found", f"Job '{job_id}' was not found.")
        if job.status in TERMINAL_JOB_STATES:
            raise BackendError("cancellation_not_applicable",
                               f"This job already finished as '{job.status}'.")
        if job.status == JOB_CANCELLING:
            raise BackendError("cancellation_already_requested",
                               "Cancellation has already been requested for this job.")
        job.cancellation_requested = True
        job.status = JOB_CANCELLING
        job.progress_message = "Cancelling"
        job.events.append({"status": JOB_CANCELLING, "message": "Cancellation requested",
                           "progress": None})
        return copy.deepcopy(job)

    def finalize_cancellation(self, job_id: str) -> TrainingJobRecord:
        """The worker has stopped: cancelling -> cancelled (TERMINAL).

        No model, evaluation or other artifact is published by a cancelled job,
        and models produced by earlier jobs are untouched.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise BackendError("job_not_found", f"Job '{job_id}' was not found.")
        if job.status == JOB_CANCELLED:
            return copy.deepcopy(job)  # already terminal - idempotent
        if job.status != JOB_CANCELLING:
            raise BackendError("cancellation_not_requested",
                               f"Job '{job_id}' is not cancelling (status '{job.status}').")
        job.status = JOB_CANCELLED
        job.completed_at = _now()
        job.progress_message = "Cancelled"
        job.result_model_version = None
        job.events.append({"status": JOB_CANCELLED, "message": "Cancelled", "progress": None})
        return copy.deepcopy(job)

    def recover_interrupted_jobs(self) -> List[TrainingJobRecord]:
        recovered = []
        for job in self._jobs.values():
            if job.status in NONTERMINAL_JOB_STATES:
                job.status = JOB_INTERRUPTED
                job.completed_at = _now()
                job.progress_message = "Interrupted (recovered after restart)"
                job.events.append({"status": JOB_INTERRUPTED, "message": job.progress_message, "progress": None})
                recovered.append(copy.deepcopy(job))
        return recovered

    # --- models + evaluation + activation -----------------------------------

    def list_models(self, model_family: str) -> List[ModelDescriptor]:
        self._require_family(model_family)
        return [copy.deepcopy(m) for m in self._models.values()]

    def inspect_model(self, model_family: str, version: str) -> ModelDescriptor:
        self._require_family(model_family)
        model = self._models.get(version)
        if model is None:
            raise BackendError("model_not_found", f"Model '{version}' was not found.")
        return copy.deepcopy(model)

    def evaluate_model(self, model_family: str, model_version: str,
                       dataset_version: str) -> EvaluationResult:
        self._require_family(model_family)
        model = self._models.get(model_version)
        if model is None:
            raise BackendError("model_not_found", f"Model '{model_version}' was not found.")
        passed = not self._fail_job
        result = EvaluationResult(
            evaluation_id=f"eval_{next(self._ids):04d}", model_version=model_version,
            dataset_version=dataset_version, dataset_checksum=f"chk_{dataset_version}", split="test",
            metrics={"map50": 0.71} if model_family == MODEL_FAMILY_CORE_AI2 else {"qwk": 0.78},
            per_class_metrics={}, errors=[], warnings=[], passed=passed,
            decision_criteria={"min_map50": 0.5} if model_family == MODEL_FAMILY_CORE_AI2
            else {"min_qwk": 0.5}, evaluated_at=_now())
        self._evaluations[model_version] = result
        self._models[model_version] = ModelDescriptor(
            **{**model.__dict__, "evaluation_status": "passed" if passed else "failed"})
        return result

    def compare_models(self, model_family: str, left: str, right: str) -> ModelComparison:
        self._require_family(model_family)
        a, b = self.inspect_model(model_family, left), self.inspect_model(model_family, right)
        diffs = []
        for label, va, vb in (("evaluation_status", a.evaluation_status, b.evaluation_status),
                              ("activation_status", a.activation_status, b.activation_status),
                              ("source_dataset_version", a.source_dataset_version, b.source_dataset_version)):
            if va != vb:
                diffs.append(f"{label}: {va} -> {vb}")
        return ModelComparison(family=model_family, left_version=left, right_version=right, differences=diffs)

    def _activate(self, version: str, actor: str, reason: str) -> ModelDescriptor:
        model = self._models.get(version)
        if model is None:
            raise BackendError("model_not_found", f"Model '{version}' was not found.")
        evaluation = self._evaluations.get(version)
        if evaluation is None or not evaluation.passed:
            raise BackendError("evaluation_required",
                               "A model can be activated only after a passing evaluation.")
        for v, m in self._models.items():
            if m.activation_status == "active":
                self._models[v] = ModelDescriptor(**{**m.__dict__, "activation_status": "inactive"})
        self._models[version] = ModelDescriptor(**{**self._models[version].__dict__,
                                                   "activation_status": "active"})
        self._active_version = version
        return copy.deepcopy(self._models[version])

    def activate_model(self, model_family: str, version: str, actor: str, reason: str) -> ModelDescriptor:
        self._require_family(model_family)
        return self._activate(version, actor, reason)

    def rollback_model(self, model_family: str, target_version: str, actor: str,
                       reason: str) -> ModelDescriptor:
        self._require_family(model_family)
        return self._activate(target_version, actor, reason)

    def get_active_model(self, model_family: str, required: bool = True) -> Optional[ModelDescriptor]:
        self._require_family(model_family)
        if self._active_version is None:
            if required:
                raise BackendError("no_active_model", "No active model.")
            return None
        return copy.deepcopy(self._models[self._active_version])

    def inspect_runtime(self, model_family: str, model_version: Optional[str] = None) -> RuntimeInspection:
        self._require_family(model_family)
        return RuntimeInspection(
            model_family=model_family, memory_status="unknown", graceful_no_ai_mode=True,
            compatibility={"reason": "runtime not inspected in fake"},
            warnings=["Runtime not measured - real compatibility requires the merged backend."], blockers=[])


# ===========================================================================
# Subsystem 4 - deterministic fake Core AI 2 inference backend.
# ===========================================================================
from app.services.ai_backend_port import (
    INFERENCE_STATUS_FAILED,
    INFERENCE_STATUS_NO_MODEL,
    INFERENCE_STATUS_OK,
    WORKFLOW_SUBJECT_PROFILE,
    CoreAI2InferenceRequest,
    CoreAI2InferenceResult,
    RegionProposal,
)


class FakeCoreAI2InferenceBackend:
    """Deterministic Core AI 2 inference. Fabricates NO real detections - it
    returns fixed geometry so the proposal-review UI can be built/tested. Modes
    let tests exercise the no-model / failure / cancelled paths that must leave
    manual mapping fully usable."""

    def __init__(self, mode: str = "ok", proposals_per_page: int = 2,
                 model_version: str = "model_v1", model_checksum: str = "chk_model_v1",
                 with_rationale: bool = False) -> None:
        self.mode = mode  # "ok" | "no_model" | "fail"
        self.proposals_per_page = proposals_per_page
        self.model_version = model_version
        self.model_checksum = model_checksum
        self.with_rationale = with_rationale

    def run_core_ai2_inference(self, request: CoreAI2InferenceRequest,
                               cancellation_token=None) -> CoreAI2InferenceResult:
        if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
            return CoreAI2InferenceResult(
                request_id=request.request_id, status=INFERENCE_STATUS_FAILED, proposals=[],
                model_version=None, model_checksum=None, page_checksum=request.page_checksum,
                failure_code="cancelled", failure_message="Inference cancelled.")
        if self.mode == "no_model":
            return CoreAI2InferenceResult(
                request_id=request.request_id, status=INFERENCE_STATUS_NO_MODEL, proposals=[],
                model_version=None, model_checksum=None, page_checksum=request.page_checksum,
                failure_code="no_active_model",
                failure_message="No active Core AI 2 model - map regions manually.")
        if self.mode == "fail":
            return CoreAI2InferenceResult(
                request_id=request.request_id, status=INFERENCE_STATUS_FAILED, proposals=[],
                model_version=self.model_version, model_checksum=self.model_checksum,
                page_checksum=request.page_checksum, failure_code="inference_error",
                failure_message="Deterministic fake inference failure - map regions manually.")

        is_profile = request.workflow_context == WORKFLOW_SUBJECT_PROFILE
        classes = (["question_area", "bubble_area"] if is_profile
                   else ["k1_answer_block", "k2_part1"])
        proposals = []
        for i in range(self.proposals_per_page):
            y = round(0.1 + i * 0.2, 4)
            region_class = classes[i % len(classes)]
            px = (0.1 * request.page_width, y * request.page_height,
                  0.3 * request.page_width, 0.1 * request.page_height)
            proposals.append(RegionProposal(
                proposal_id=f"{request.request_id}_p{i}", model_family="core_ai2",
                model_version=self.model_version, model_checksum=self.model_checksum,
                page_checksum=request.page_checksum, region_class=region_class,
                normalized_bbox=(0.1, y, 0.3, 0.1), pixel_bbox=px,
                confidence=round(0.9 - i * 0.15, 4), device_used="cpu",
                provenance={"source": "fake_backend"},
                rationale=("High-confidence bubble grid" if self.with_rationale else None)))
        return CoreAI2InferenceResult(
            request_id=request.request_id, status=INFERENCE_STATUS_OK, proposals=proposals,
            model_version=self.model_version, model_checksum=self.model_checksum,
            page_checksum=request.page_checksum, device_used="cpu")


# ===========================================================================
# Subsystem 5 - deterministic fake Core AI 1 dataset backend.
# ===========================================================================
import hashlib as _hashlib
from collections import Counter as _Counter

from app.services.ai_backend_port import MODEL_FAMILY_CORE_AI1

# Mirrors the Codex core_ai1_dataset_service validation reasons.
_CORE1_KERTAS1 = ("kertas1", "k1")


def _core1_reason(raw, row, config, seen):
    if not raw.get("is_finalized"):
        return "not_finalized", None
    if str(raw.get("paper_type", raw.get("paper_identifier", ""))).lower() in _CORE1_KERTAS1:
        return "not_kertas2", None
    if row["teacher_final_score"] is None:
        return "missing_final_score", None
    if not row["teacher_final_feedback_category"]:
        return "missing_final_category", None
    if row["teacher_final_feedback_category"] not in config.category_mapping:
        return "unknown_category", None
    if not row["marking_scheme_text"]:
        return "missing_marking_scheme", None
    if not row["effective_student_answer"]:
        return "missing_effective_answer", None
    try:
        score = float(row["teacher_final_score"])
        maximum = float(row["maximum_score"])
        if maximum <= 0 or score < 0 or score > maximum:
            return "invalid_score", None
    except Exception:
        return "invalid_score", None
    source = row.get("source_checksum") or _hashlib.sha256(
        repr(sorted(row.items())).encode()).hexdigest()
    sample_id = _hashlib.sha256(
        f"{source}|{row.get('logical_target')}|{row.get('part_identifier')}".encode()).hexdigest()[:24]
    if sample_id in seen:
        return "duplicate_sample", sample_id
    return None, sample_id


class FakeCoreAI1DatasetBackend:
    """Deterministic Core AI 1 dataset backend. `export_dataset` runs the REAL
    Claude finalized-record adapter and computes the real included/excluded
    counts and Part/score/category/mode distributions - it fabricates no
    metrics. Freeze/list/inspect/audit/compare mirror the Core AI 2 backend."""

    def __init__(self, datasets=None):
        self._datasets = {d.version: d for d in (datasets or [])}
        self._counter = 0

    def _require_family(self, model_family):
        if model_family != MODEL_FAMILY_CORE_AI1:
            raise BackendError("unsupported_family", f"This backend serves {MODEL_FAMILY_CORE_AI1}.")

    def _get(self, version):
        d = self._datasets.get(version)
        if d is None:
            raise BackendError("dataset_not_found", f"Dataset '{version}' was not found.")
        return d

    def list_datasets(self, model_family):
        self._require_family(model_family)
        return [copy.deepcopy(d) for d in self._datasets.values()]

    def inspect_dataset(self, model_family, version):
        self._require_family(model_family)
        return copy.deepcopy(self._get(version))

    def audit_dataset(self, model_family, version):
        self._require_family(model_family)
        d = self._get(version)
        return DatasetAuditReport(
            family=model_family, version=version, ok=d.export_valid, checked_at=_now(),
            findings=list(d.warnings), recommendations=list(d.statistics.get("recommendations", [])))

    def compare_datasets(self, model_family, left, right):
        self._require_family(model_family)
        a, b = self._get(left), self._get(right)
        diffs = []
        for label, va, vb in (
            ("frozen", a.frozen, b.frozen), ("training_ready", a.training_ready, b.training_ready),
            ("sample_count", a.statistics.get("included_count"), b.statistics.get("included_count")),
        ):
            if va != vb:
                diffs.append(f"{label}: {va} -> {vb}")
        return DatasetComparison(family=model_family, left_version=left, right_version=right,
                                 differences=diffs, left=copy.deepcopy(a), right=copy.deepcopy(b))

    def freeze_dataset(self, model_family, version, actor=None, note=None):
        self._require_family(model_family)
        d = self._get(version)
        if not d.export_valid:
            raise BackendError("not_export_valid", "Only an export-valid dataset can be frozen.")
        if d.frozen:
            raise BackendError("already_frozen", "This dataset is already frozen (freezing is permanent).")
        frozen = DatasetDescriptor(**{**d.__dict__, "frozen": True})
        self._datasets[version] = frozen
        return copy.deepcopy(frozen)

    def export_dataset(self, adapter, version, config):
        if version in self._datasets:
            raise BackendError("version_exists", "A dataset with this version already exists.")
        included, excluded, seen = [], [], set()
        for index, raw in enumerate(adapter.list_finalized_k2_examples()):
            row = dict(raw)
            reason, sample_id = _core1_reason(raw, row, config, seen)
            if reason:
                excluded.append({"candidate_index": index, "reason": reason})
                continue
            seen.add(sample_id)
            row["sample_id"] = sample_id
            included.append(row)

        parts = _Counter(r.get("part_identifier") for r in included)
        categories = _Counter(r.get("teacher_final_feedback_category") for r in included)
        modes = _Counter(r.get("source_mode") for r in included)
        scores = _Counter(int(round(float(r.get("teacher_final_score") or 0))) for r in included)
        groups = {r.get("student_group_id") for r in included}
        excl_reasons = _Counter(e["reason"] for e in excluded)

        blockers, warnings, recommendations = [], [], []
        if len(included) < config.min_samples:
            blockers.append(f"Only {len(included)} finalized sample(s) - at least {config.min_samples} needed.")
            recommendations.append("Finalise more teacher-reviewed Kertas 2 attempts.")
        if len(groups) < config.min_groups:
            blockers.append(f"Only {len(groups)} attempt group(s) - at least {config.min_groups} needed for a "
                            "leakage-safe split.")
        for category in config.category_mapping:
            if categories.get(category, 0) < config.min_examples_per_category:
                blockers.append(f"Category '{category}' has {categories.get(category, 0)} example(s) "
                                f"(min {config.min_examples_per_category}).")
        missing_parts = [p for p in config.required_parts if parts.get(p, 0) == 0]
        if missing_parts:
            blockers.append(f"Missing required parts: {', '.join(missing_parts)}.")

        leakage_safe = len(groups) >= config.min_groups
        export_valid = len(included) >= 1
        training_ready = export_valid and not blockers
        descriptor = DatasetDescriptor(
            family=MODEL_FAMILY_CORE_AI1, version=version,
            path=f"ai/datasets/core_ai1/{version}", export_valid=export_valid,
            training_ready=training_ready, frozen=False, schema_version="core-ai1-k2-reviewed-v1",
            mapping_version=config.category_mapping_version, split_mode="attempt_grouped",
            blockers=blockers, warnings=warnings,
            statistics={
                "included_count": len(included), "excluded_count": len(excluded),
                "excluded_reasons": dict(excl_reasons), "part_distribution": dict(parts),
                "category_distribution": dict(categories), "score_distribution": dict(sorted(scores.items())),
                "mode_distribution": dict(modes), "attempt_group_count": len(groups),
                "leakage_safe_split": leakage_safe, "split_ratios": list(config.split_ratios),
                "recommendations": recommendations},
            supported_formats=["jsonl"])
        self._datasets[version] = descriptor
        return copy.deepcopy(descriptor)


# ===========================================================================
# Subsystem 6 - deterministic fake Core AI 1 inference backend.
# ===========================================================================
from decimal import Decimal as _Decimal, ROUND_HALF_UP as _ROUND_HALF_UP

from app.services.ai_backend_port import (
    CORE_AI1_FAILURE_BLANK_ANSWER,
    CORE_AI1_FAILURE_INVALID_MAX,
    CORE_AI1_FAILURE_KERTAS1,
    CORE_AI1_FAILURE_NO_ACTIVE_MODEL,
    CORE_AI1_FAILURE_TEACHER_REVIEWED,
    CORE_AI1_STATUS_ATTENTION_REQUIRED,
    CORE_AI1_STATUS_COMPLETED,
    CORE_AI1_STATUS_FAILED,
    CORE_AI1_STATUS_SKIPPED,
    CoreAI1InferenceRequest,
    CoreAI1InferenceResult,
)

_CORE_AI1_CATEGORIES = ("content", "language", "organisation")


def _core1_empty_result(request, status, failure_code, warnings=()):
    return CoreAI1InferenceResult(
        request_id=request.request_id, status=status, draft_raw_score=None, normalized_score=None,
        proposed_application_score=None, feedback_category=None, category_confidence=None,
        score_confidence=None, model_version=request.model_version, model_checksum=None,
        dataset_lineage=None, input_template_version=None, input_checksum=request.input_checksum,
        truncation_warning=False, missing_scheme_warning=not bool(request.marking_scheme),
        warnings=list(warnings), failure_code=failure_code)


class FakeCoreAI1InferenceBackend:
    """Deterministic Core AI 1 draft-scoring backend.

    It invents no model: the normalized score is a stable hash of the request
    input, so the same input always yields the same draft. What it DOES model
    faithfully is the contract the review workspace must handle - existing
    teacher-reviewed answers are skipped rather than overwritten, Kertas 1 is
    unsupported, a blank answer needs teacher attention instead of a score,
    clamping and half-mark rounding are reported, and one failed item never
    removes the others.
    """

    def __init__(self, active_model_version: Optional[str] = "core1_model_v1",
                 model_checksum: str = "core1checksum", dataset_lineage: str = "core1_v1",
                 categories=_CORE_AI1_CATEGORIES, fail_request_ids=()) -> None:
        self.active_model_version = active_model_version
        self.model_checksum = model_checksum
        self.dataset_lineage = dataset_lineage
        self._categories = tuple(categories)
        self._fail = set(fail_request_ids)

    def run_core_ai1_inference(self, request: CoreAI1InferenceRequest) -> CoreAI1InferenceResult:
        warnings: List[str] = []
        if request.existing_teacher_reviewed:
            return _core1_empty_result(request, CORE_AI1_STATUS_SKIPPED,
                                       CORE_AI1_FAILURE_TEACHER_REVIEWED,
                                       ["Existing teacher-reviewed value was not overwritten."])
        if request.paper.lower() not in ("kertas2", "k2"):
            return _core1_empty_result(request, CORE_AI1_STATUS_FAILED, CORE_AI1_FAILURE_KERTAS1)
        if not request.effective_student_answer.strip():
            return _core1_empty_result(request, CORE_AI1_STATUS_ATTENTION_REQUIRED,
                                       CORE_AI1_FAILURE_BLANK_ANSWER,
                                       ["Student answer is blank; no draft score was generated."])
        if request.maximum_score <= 0:
            return _core1_empty_result(request, CORE_AI1_STATUS_FAILED, CORE_AI1_FAILURE_INVALID_MAX)
        if request.request_id in self._fail:
            return _core1_empty_result(request, CORE_AI1_STATUS_FAILED, "runtime_error",
                                       ["Simulated runtime failure."])
        model_version = request.model_version or self.active_model_version
        if not model_version:
            return _core1_empty_result(request, CORE_AI1_STATUS_FAILED,
                                       CORE_AI1_FAILURE_NO_ACTIVE_MODEL,
                                       ["No active Core AI 1 model is configured."])
        if not request.marking_scheme.strip():
            warnings.append("Marking scheme is missing or unclear; teacher attention is required.")

        digest = _hashlib.sha256(
            f"{request.input_checksum}|{request.effective_student_answer}".encode("utf-8")).hexdigest()
        normalized = (int(digest[:8], 16) % 1001) / 1000.0
        raw = normalized * request.maximum_score
        clamped = raw < 0 or raw > request.maximum_score
        raw_clamped = min(request.maximum_score, max(0.0, raw))
        # Same application rounding policy as the backend: nearest half mark,
        # half up, applied AFTER clamping to the valid mark range.
        proposed = float((_Decimal(str(raw_clamped)) * 2).quantize(
            _Decimal("1"), rounding=_ROUND_HALF_UP) / 2)
        if clamped:
            warnings.append("Raw model score was clamped to the valid mark range.")
        category = self._categories[int(digest[8:12], 16) % len(self._categories)]
        confidence = 0.5 + (int(digest[12:16], 16) % 500) / 1000.0
        truncated = len(request.effective_student_answer) > 4000
        if truncated:
            warnings.append("The student answer was truncated for the model input.")
        return CoreAI1InferenceResult(
            request_id=request.request_id, status=CORE_AI1_STATUS_COMPLETED, draft_raw_score=raw,
            normalized_score=normalized, proposed_application_score=proposed,
            feedback_category=category, category_confidence=confidence, score_confidence=confidence,
            model_version=model_version, model_checksum=self.model_checksum,
            dataset_lineage=self.dataset_lineage, input_template_version="core-ai1-input-v1",
            input_checksum=request.input_checksum, truncation_warning=truncated,
            missing_scheme_warning=not bool(request.marking_scheme.strip()), warnings=warnings,
            device="cpu", clamped=clamped,
            category_probabilities={c: (1.0 if c == category else 0.0) for c in self._categories},
            truncation_statistics={"input_tokens": len(request.effective_student_answer.split())})

    def run_core_ai1_attempt_inference(self, requests):
        # One result per request, ordered by part then request id - matching the
        # facade. A failed item never removes the successful ones.
        return [self.run_core_ai1_inference(r)
                for r in sorted(requests, key=lambda r: (r.part, r.request_id))]


# ===========================================================================
# Subsystem 8 - deterministic fake feedback backend.
# ===========================================================================
import re as _re

from app.services.ai_backend_port import (
    FEEDBACK_SOURCE_LOCAL_LLM,
    FEEDBACK_SOURCE_PREVIOUS_TEACHER,
    FEEDBACK_SOURCE_TEMPLATE,
    TEMPLATE_CATEGORY_MAPPING_VERSION,
    TEMPLATE_FEEDBACK_VERSION,
    FeedbackResult,
    LocalFeedbackRequest,
    TemplateFeedbackRequest,
    TemplateFeedbackResult,
)

# The template wording mirrors the backend's deterministic templates.
_CATEGORY_TEXT = {
    "correct": "The response meets the expected standard for this task. The teacher should confirm "
               "that the final feedback reflects the marking scheme.",
    "partial": "The response shows some relevant achievement but needs further development. The "
               "teacher should identify the most useful next step from the marking scheme.",
    "incorrect": "The response does not yet meet the expected standard. The teacher should explain "
                 "the relevant requirement and an appropriate next step.",
    "not_attempted": "No assessable response was provided for this task.",
}

_ISSUE_TEXT = {
    "task_fulfilment": "Check that every required element of the task has been addressed.",
    "organisation": "Review the organisation and sequencing of ideas.",
    "grammar": "Review the grammar issues identified for teacher attention.",
    "spelling": "Review the spelling issues identified for teacher attention.",
    "vocabulary": "Review the vocabulary issue identified for teacher attention.",
}

_PART_TEXT = {"part1": "Part 1 response", "part2": "Part 2 response", "part3": "Part 3 response"}

_TEACHER_REVIEW_NOTICE = ("This is an editable draft for teacher review and must not be released "
                          "to a student until finalised by a teacher.")

# Any wording that looks like a score is stripped: feedback is never a mark.
_SCORE_PATTERN = _re.compile(
    r"(?i)(?:score|mark)\s*(?:is|:|=)?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?")


def _endpoint_allowed(endpoint, allow_private):
    """Same allow-list the backend applies: localhost/loopback always, private
    addresses only by explicit permission, everything else rejected."""
    import ipaddress
    from urllib.parse import urlparse
    parsed = urlparse(endpoint or "")
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    return bool(allow_private and ip.is_private)


def clean_feedback_text(text, limit):
    """Strip control characters and any score-like wording. Returns
    (text, warnings); raises ValueError when nothing usable remains."""
    text = "".join(ch for ch in str(text) if ch in "\n\t" or ord(ch) >= 32).strip()
    if not text:
        raise ValueError("Feedback output is empty.")
    warnings = []
    if _SCORE_PATTERN.search(text):
        text = _SCORE_PATTERN.sub("", text).strip(" .;,-")
        warnings.append("The local model attempted to include a numerical score; that content "
                        "was removed.")
    if not text:
        raise ValueError("Feedback contained only prohibited score content.")
    if len(text) > limit:
        # Mirrors the real LocalFeedbackService: the requested length is a
        # target, not a validity rule - shorten at a sentence boundary when
        # one exists in the second half, else hard-clip.
        clipped = text[:limit]
        cut = max(clipped.rfind(". "), clipped.rfind("! "), clipped.rfind("? "),
                  clipped.rfind(".\n"))
        text = (clipped[:cut + 1] if cut >= limit // 2 else clipped).strip()
        warnings.append("Local model output exceeded the requested feedback length and "
                        "was shortened.")
    return text, warnings


class FakeFeedbackBackend:
    """Deterministic feedback backend.

    The template path reproduces the backend's offline templates exactly and is
    always available. The local path models the failure surface the application
    must handle - a disallowed endpoint, an unsupported adapter, a timeout, an
    oversized response, and a model that tries to state a score - without ever
    opening a connection.
    """

    def __init__(self, local_text=None, failure_code=None,
                 runtime_identifier="local-runtime") -> None:
        self._local_text = local_text
        self._failure_code = failure_code
        self._runtime_identifier = runtime_identifier

    def generate_local_feedback(self, request: LocalFeedbackRequest,
                                cancellation_token=None) -> FeedbackResult:
        warnings: List[str] = []

        def failure(code, message):
            # A failure never invents feedback: it retains the teacher's own
            # previous wording when there is any, and otherwise returns none so
            # the caller falls back to the offline template.
            retained = request.previous_teacher_feedback
            return FeedbackResult(
                generation_source=(FEEDBACK_SOURCE_PREVIOUS_TEACHER if retained
                                   else FEEDBACK_SOURCE_LOCAL_LLM),
                runtime_identifier=request.adapter, model_name=request.model_name,
                input_checksum=request.input_checksum, feedback_category=request.feedback_category,
                generated_feedback=retained, template_fallback_feedback=None,
                warnings=[message], duration_seconds=0.0, failure_status=code)

        if not _endpoint_allowed(request.endpoint, request.allow_private_network):
            return failure("endpoint_not_allowed",
                           "Endpoint is not an approved localhost/private-network address.")
        if request.adapter not in ("openai", "ollama"):
            return failure("adapter_unsupported", "Unsupported local feedback adapter.")
        if self._failure_code:
            return failure(self._failure_code, f"Local runtime reported: {self._failure_code}.")
        if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
            return failure("cancelled", "Feedback generation was cancelled.")

        raw = self._local_text if self._local_text is not None else (
            f"Your {request.part} response addresses the task. Focus next on developing your "
            "supporting details and checking sentence accuracy.")
        try:
            text, cleaning_warnings = clean_feedback_text(raw, request.requested_feedback_length)
        except ValueError as exc:
            return failure("feedback_unusable", str(exc))
        warnings.extend(cleaning_warnings)
        return FeedbackResult(
            generation_source=FEEDBACK_SOURCE_LOCAL_LLM,
            runtime_identifier=self._runtime_identifier, model_name=request.model_name,
            input_checksum=request.input_checksum, feedback_category=request.feedback_category,
            generated_feedback=text, template_fallback_feedback=None, warnings=warnings,
            duration_seconds=0.0)

    def generate_template_feedback(self, request: TemplateFeedbackRequest
                                   ) -> TemplateFeedbackResult:
        warnings = []
        part_text = _PART_TEXT.get(str(request.part).lower(), "Response")
        if request.student_answer_blank:
            category_text = ("No student answer was present for this task. The teacher should "
                             "confirm the blank-answer status.")
        else:
            category_text = _CATEGORY_TEXT.get(request.feedback_category)
            if category_text is None:
                category_text = ("This response requires teacher attention before final feedback "
                                 "is issued.")
                warnings.append("Unknown feedback category was mapped to the neutral "
                                "teacher-attention template.")
        sentences = [f"{part_text}: {category_text}"]
        if not request.marking_scheme_available:
            sentences.append("A marking scheme was not available to this generator, so the teacher "
                             "must verify the feedback against the approved criteria.")
            warnings.append("Marking scheme unavailable.")
        seen = set()
        for tag in request.issue_tags:
            if tag in seen:
                continue
            seen.add(tag)
            text = _ISSUE_TEXT.get(tag)
            if text:
                sentences.append(text)
            else:
                warnings.append(f"Unsupported issue tag ignored: {tag}")
        sentences.append(_TEACHER_REVIEW_NOTICE)
        return TemplateFeedbackResult(
            generated_text=" ".join(sentences), template_version=TEMPLATE_FEEDBACK_VERSION,
            category_mapping_version=TEMPLATE_CATEGORY_MAPPING_VERSION,
            generation_source=FEEDBACK_SOURCE_TEMPLATE, input_checksum=request.input_checksum,
            warnings=tuple(warnings))


def training_ready_core_ai1_dataset(version: str = "core1_ready_v1") -> DatasetDescriptor:
    """A deterministic Core AI 1 dataset that is genuinely FROZEN, TRAINING-READY
    and leakage-safe, with no blockers.

    Training/evaluation/activation may only ever be demonstrated from a dataset
    like this one - an export-valid but unready dataset is inspectable and
    freezeable only.
    """
    return DatasetDescriptor(
        family=MODEL_FAMILY_CORE_AI1, version=version,
        path=f"ai/datasets/core_ai1/{version}", export_valid=True, training_ready=True,
        frozen=True, schema_version="core-ai1-k2-reviewed-v1", mapping_version="seeded-v1",
        manifest_checksum="core1readychecksum", split_mode="attempt_grouped",
        blockers=[], warnings=[],
        statistics={"included_count": 48, "excluded_count": 0, "excluded_reasons": {},
                    "part_distribution": {"part1": 16, "part2": 16, "part3": 16},
                    "category_distribution": {"content": 16, "language": 16, "organisation": 16},
                    "score_distribution": {8: 12, 12: 12, 15: 12, 18: 12},
                    "mode_distribution": {"standard": 40, "separate_answer_paper": 8},
                    "attempt_group_count": 12, "leakage_safe_split": True,
                    "split_ratios": [0.7, 0.15, 0.15], "recommendations": []},
        supported_formats=["jsonl"])


def training_ready_core_ai2_dataset(version: str = "core2_ready_v1") -> DatasetDescriptor:
    """The Core AI 2 equivalent - frozen, training-ready and leakage-safe."""
    return DatasetDescriptor(
        family=MODEL_FAMILY_CORE_AI2, version=version,
        path=f"ai/datasets/core_ai2/{version}", export_valid=True, training_ready=True,
        frozen=True, schema_version="s1", mapping_version="m1",
        manifest_checksum="core2readychecksum", split_mode="profile_grouped",
        blockers=[], warnings=[],
        statistics={"profile_count": 6, "page_count": 120, "region_count": 480, "class_count": 4,
                    "excluded_region_count": 0, "unsupported_region_count": 0,
                    "leakage_safe_split": True, "split_ratios": [0.7, 0.15, 0.15],
                    "recommendations": []},
        supported_formats=list(CORE_AI2_CONVERSION_FORMATS))


# ===========================================================================
# Subsystem 11 - deterministic fake review-capture backend.
# ===========================================================================
from dataclasses import asdict as _asdict


class FakeReviewCaptureBackend:
    """Deterministic review capture mirroring the backend's exclusion rules.

    Core AI 1: a record is excluded when it is not finalized, its draft is
    stale, its marking scheme is missing, its teacher label is incomplete, or it
    duplicates one already captured.

    Core AI 2: deferred/unresolved proposals are excluded; rejected proposals
    are kept as evidence but are not training labels; accepted and edited
    proposals become candidates. Duplicates are excluded.
    """

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.published = {}

    def _publish(self, family, version, candidates, evidence, exclusions, statistics):
        if self._fail:
            raise BackendError("capture_failed", "Review capture is unavailable.")
        if (family, version) in self.published:
            raise BackendError("candidate_version_exists",
                               "Candidate version already exists and is immutable.")
        payload = {"family": family, "candidate_version": version, "candidates": candidates,
                   "evidence": evidence, "exclusions": exclusions, "statistics": statistics}
        self.published[(family, version)] = payload
        return payload

    def capture_core_ai1_reviews(self, candidate_version, records):
        candidates, exclusions, seen = [], [], set()
        counts = _Counter()
        for record in records:
            duplicate_key = (record.input_checksum, record.attempt_group_id)
            reason = None
            if not record.finalized:
                reason = "not_finalized"
            elif record.stale_draft:
                reason = "stale_draft"
            elif not record.marking_scheme_checksum:
                reason = "missing_scheme"
            elif record.teacher_final_score is None or not record.teacher_final_category:
                reason = "missing_teacher_label"
            elif duplicate_key in seen:
                reason = "duplicate"
            if reason:
                exclusions.append({"record_id": record.record_id, "reason": reason})
                counts[reason] += 1
                continue
            seen.add(duplicate_key)
            changed_score = record.original_draft_score != record.teacher_final_score
            changed_category = record.original_draft_category != record.teacher_final_category
            candidates.append({
                "record_id": record.record_id,
                "original_ai_draft_score": record.original_draft_score,
                "original_ai_draft_category": record.original_draft_category,
                "teacher_final_score": record.teacher_final_score,
                "teacher_final_category": record.teacher_final_category,
                "draft_disposition": record.draft_disposition,
                "changed_score": changed_score,
                "changed_category": changed_category,
                "input_checksum": record.input_checksum,
                "source_model_version": record.model_version,
                "teacher_final_student_feedback": (record.teacher_final_student_feedback
                                                   if record.feedback_capture_permitted else None),
                "attempt_group_id": record.attempt_group_id,
                "finalized_at": record.finalized_at,
            })
            counts["changed_score" if changed_score else "score_unchanged"] += 1
            counts["changed_category" if changed_category else "category_unchanged"] += 1
        statistics = dict(counts)
        statistics.update({"input_records": len(records), "candidate_count": len(candidates),
                           "duplicate_candidates": counts["duplicate"]})
        return self._publish("core_ai1", candidate_version, candidates, [], exclusions, statistics)

    def capture_core_ai2_reviews(self, candidate_version, proposals):
        candidates, evidence, exclusions, seen = [], [], [], set()
        counts = _Counter()
        for proposal in proposals:
            key = (proposal.page_checksum, proposal.proposal_id)
            status = (proposal.review_status or "").lower()
            if key in seen:
                exclusions.append({"proposal_id": proposal.proposal_id, "reason": "duplicate"})
                counts["duplicate"] += 1
                continue
            seen.add(key)
            base = {
                "proposal_id": proposal.proposal_id,
                "proposed_class": proposal.proposed_class,
                "proposed_geometry": list(proposal.proposed_geometry),
                "final_teacher_class": proposal.final_teacher_class,
                "final_teacher_geometry": (list(proposal.final_teacher_geometry)
                                           if proposal.final_teacher_geometry is not None else None),
                "review_status": status,
                "source_model_version": proposal.model_version,
                "page_checksum": proposal.page_checksum,
                "attempt_group_id": proposal.attempt_group_id,
                "reason_code": proposal.reason_code,
            }
            if status in ("deferred", "unresolved", "proposed"):
                exclusions.append({"proposal_id": proposal.proposal_id, "reason": status})
                counts[status] += 1
                continue
            if status == "rejected":
                base["training_label_eligible"] = False
                evidence.append(base)
                counts["rejected"] += 1
                continue
            base["training_label_eligible"] = True
            candidates.append(base)
            counts[status] += 1
        statistics = dict(counts)
        statistics.update({"input_proposals": len(proposals), "candidate_count": len(candidates),
                           "evidence_count": len(evidence)})
        return self._publish("core_ai2", candidate_version, candidates, evidence, exclusions,
                             statistics)
