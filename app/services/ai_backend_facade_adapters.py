"""Stage 12G-13 - thin mapping wrappers between the Core AI backend facade and
the application's existing port shapes.

The facade returns the backend's native shapes: registry entries and manifests
as plain dicts, model manifests as dicts, job records as `TrainingJobRecord`.
The interface built in earlier stages consumes the port dataclasses in
`ai_backend_port`. These wrappers translate one into the other.

They are deliberately THIN. They add no behaviour, invent no value, and never
substitute a default for a fact the backend did not state - an absent number
stays absent so the interface can say "-" rather than imply a measurement. Each
class implements exactly the port protocol the application already depends on,
so no call site changes.

UI-only mapping decisions are documented inline and summarised in
`UI_ONLY_MAPPINGS` at the end of this module.
"""
from typing import Any, Dict, List, Optional

from app.services.ai_backend_port import (
    CONVERSION_FORMAT_COCO,
    CONVERSION_FORMAT_YOLO,
    MODEL_FAMILY_CORE_AI1,
    MODEL_FAMILY_CORE_AI2,
    BackendError,
    ConversionResult,
    DatasetAuditReport,
    DatasetComparison,
    DatasetDescriptor,
    EvaluationResult,
    ModelComparison,
    ModelDescriptor,
    RuntimeInspection,
    TrainingJobRecord,
)

# The backend raises its own BackendError; the application catches the port's.
# They are distinct classes, so every wrapper re-raises through this helper.
from app.models.core_ai_backend_contracts import BackendError as CodexBackendError


def _reraise(exc: Exception) -> "BackendError":
    code = getattr(exc, "code", None) or "backend_error"
    message = getattr(exc, "message", None) or str(exc)
    return BackendError(code, message)


def _guard(call, *args, **kwargs):
    """Run a facade call, translating the backend's error type into the port's
    so existing handlers keep working unchanged."""
    try:
        return call(*args, **kwargs)
    except CodexBackendError as exc:
        raise _reraise(exc) from exc
    except (ValueError, KeyError) as exc:
        # get_dataset_entry raises ValueError for an unknown version.
        raise BackendError("dataset_not_found", str(exc)) from exc


# ---------------------------------------------------------------- datasets ---

def _core_ai2_descriptor(entry: Dict[str, Any], integrity: Optional[Dict] = None
                         ) -> DatasetDescriptor:
    """A Core AI 2 registry entry -> DatasetDescriptor.

    export_valid / training_ready / frozen stay three independent facts, exactly
    as the registry reports them.
    """
    statistics: Dict[str, Any] = {
        "profile_count": entry.get("profile_count"),
        "page_count": entry.get("page_count"),
        "region_count": entry.get("region_count"),
        "class_counts": entry.get("class_counts") or {},
        # UI-only: the cards show a class COUNT, the registry reports per-class
        # counts. The count is derived, never invented.
        "class_count": len(entry.get("class_counts") or {}),
        "validation_errors": entry.get("validation_errors"),
        "validation_warnings": entry.get("validation_warnings"),
        "integrity_valid": entry.get("integrity_valid"),
        "leakage_safe_split": bool(entry.get("split_mode")),
    }
    if integrity:
        statistics["integrity_errors"] = list(integrity.get("errors", []))
        statistics["integrity_warnings"] = list(integrity.get("warnings", []))
    return DatasetDescriptor(
        family=MODEL_FAMILY_CORE_AI2,
        version=str(entry.get("version")),
        path=entry.get("folder_name") or "",
        export_valid=bool(entry.get("export_valid")),
        training_ready=bool(entry.get("training_ready")),
        frozen=bool(entry.get("frozen")),
        schema_version=entry.get("dataset_schema_version"),
        mapping_version=entry.get("class_mapping_version"),
        source_commit=entry.get("source_commit"),
        manifest_checksum=entry.get("manifest_checksum"),
        split_mode=entry.get("split_mode"),
        blockers=list(entry.get("blocking_readiness_reasons") or []),
        warnings=list(entry.get("readiness_warnings") or []),
        statistics=statistics,
        supported_formats=list(entry.get("available_formats") or []),
    )


def _core_ai1_descriptor(manifest: Dict[str, Any],
                         statistics: Optional[Dict[str, Any]] = None,
                         integrity: Optional[Dict[str, Any]] = None) -> DatasetDescriptor:
    """A Core AI 1 manifest (+ statistics when available) -> DatasetDescriptor.

    The interface shows included/excluded counts, Part/score/category/mode
    distributions and the leakage-safe split; each maps from a statistic the
    backend actually computed.
    """
    stats = dict(statistics or {})
    mapped: Dict[str, Any] = dict(stats)
    if stats:
        mapped.update({
            "included_count": manifest.get("sample_count", stats.get("sample_count")),
            "excluded_count": stats.get("excluded_count"),
            "part_distribution": stats.get("part_distribution"),
            "category_distribution": stats.get("category_distribution"),
            "score_distribution": stats.get("score_distribution"),
            "mode_distribution": stats.get("source_mode_distribution"),
            "attempt_group_count": stats.get("leakage_safe_group_count"),
            # UI-only: the split is leakage-safe when the backend grouped the
            # samples, which it reports as a group count on an attempt-grouped
            # split mode.
            "leakage_safe_split": bool(stats.get("leakage_safe_group_count")),
            "split_ratios": (manifest.get("configuration") or {}).get("split_ratios"),
            "recommendations": list(manifest.get("recommended_human_actions", [])),
        })
    else:
        mapped["included_count"] = manifest.get("sample_count")
    if integrity:
        mapped["integrity_valid"] = integrity.get("valid")
        mapped["integrity_errors"] = list(integrity.get("errors", []))
        mapped["integrity_warnings"] = list(integrity.get("warnings", []))
    return DatasetDescriptor(
        family=MODEL_FAMILY_CORE_AI1,
        version=str(manifest.get("dataset_version")),
        path=manifest.get("folder") or "",
        export_valid=bool(manifest.get("export_valid")),
        training_ready=bool(manifest.get("training_ready")),
        frozen=bool(manifest.get("frozen")),
        schema_version=manifest.get("schema_version"),
        mapping_version=manifest.get("category_mapping_version"),
        split_mode=manifest.get("split_mode"),
        blockers=list(manifest.get("blocking_readiness_reasons") or []),
        warnings=list(manifest.get("readiness_warnings") or []),
        statistics=mapped,
        supported_formats=["jsonl"],
    )


class FacadeCoreAI2DatasetBackend:
    """CoreAI2DatasetPort over the real facade."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def _entry(self, version: str) -> Dict[str, Any]:
        return _guard(self._facade.inspect_dataset, MODEL_FAMILY_CORE_AI2, version)

    def list_datasets(self, model_family: str) -> List[DatasetDescriptor]:
        result = _guard(self._facade.list_datasets, model_family)
        return [_core_ai2_descriptor(entry) for entry in result.get("datasets", [])]

    def inspect_dataset(self, model_family: str, version: str) -> DatasetDescriptor:
        entry = self._entry(version)
        integrity = _guard(self._facade.inspect_core_ai2_dataset_integrity, version)
        return _core_ai2_descriptor(entry, integrity)

    def audit_dataset(self, model_family: str, version: str) -> DatasetAuditReport:
        """The COMPLETE integrity result - every error and warning, unsummarised."""
        integrity = _guard(self._facade.inspect_core_ai2_dataset_integrity, version)
        audit = _guard(self._facade.audit_dataset, MODEL_FAMILY_CORE_AI2, version)
        recommendations = []
        if isinstance(audit, dict):
            recommendations = list(audit.get("recommended_human_actions", [])
                                   or audit.get("recommendations", []))
        return DatasetAuditReport(
            family=MODEL_FAMILY_CORE_AI2, version=version,
            ok=bool(integrity.get("valid")), checked_at=integrity.get("checked_at") or "",
            findings=list(integrity.get("errors", [])) + list(integrity.get("warnings", [])),
            recommendations=recommendations)

    def compare_datasets(self, model_family: str, left: str, right: str) -> DatasetComparison:
        raw = _guard(self._facade.compare_datasets, MODEL_FAMILY_CORE_AI2, left, right)
        return DatasetComparison(
            family=MODEL_FAMILY_CORE_AI2, left_version=left, right_version=right,
            differences=_differences(raw),
            left=_core_ai2_descriptor(self._entry(left)),
            right=_core_ai2_descriptor(self._entry(right)))

    def freeze_dataset(self, model_family: str, version: str, actor=None,
                       note=None) -> DatasetDescriptor:
        _guard(self._facade.freeze_dataset, MODEL_FAMILY_CORE_AI2, version, actor, note)
        return self.inspect_dataset(model_family, version)

    def convert_dataset(self, model_family: str, version: str, output_format: str,
                        conversion_version: str) -> ConversionResult:
        if output_format not in (CONVERSION_FORMAT_YOLO, CONVERSION_FORMAT_COCO):
            raise BackendError("conversion_format_unsupported",
                               "Supported detector formats are yolo and coco.")
        raw = _guard(self._facade.convert_dataset, MODEL_FAMILY_CORE_AI2, version,
                     output_format, conversion_version)
        data = raw if isinstance(raw, dict) else {}
        return ConversionResult(
            family=MODEL_FAMILY_CORE_AI2, version=version, output_format=output_format,
            conversion_version=conversion_version,
            output_path=str(data.get("output_folder") or data.get("path") or ""),
            checksum=data.get("checksum") or data.get("manifest_checksum"),
            warnings=list(data.get("warnings", [])))


class FacadeCoreAI1DatasetBackend:
    """CoreAI1DatasetPort over the real facade."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def _manifest(self, version: str) -> Dict[str, Any]:
        for entry in _guard(self._facade.list_datasets, MODEL_FAMILY_CORE_AI1):
            if str(entry.get("dataset_version")) == str(version):
                return entry
        raise BackendError("dataset_not_found", f"Dataset '{version}' was not found.")

    def _audit(self, version: str) -> Dict[str, Any]:
        return _guard(self._facade.audit_dataset, MODEL_FAMILY_CORE_AI1, version)

    def list_datasets(self, model_family: str) -> List[DatasetDescriptor]:
        entries = _guard(self._facade.list_datasets, MODEL_FAMILY_CORE_AI1)
        out = []
        for entry in entries:
            try:
                audit = self._audit(str(entry.get("dataset_version")))
                out.append(_core_ai1_descriptor(entry, audit.get("statistics"),
                                                audit.get("integrity")))
            except BackendError:
                out.append(_core_ai1_descriptor(entry))  # listable even if unauditable
        return out

    def inspect_dataset(self, model_family: str, version: str) -> DatasetDescriptor:
        audit = self._audit(version)
        # The audit returns the manifest as written at EXPORT time, whose
        # `frozen` flag is therefore always false. Freezing records a marker
        # file instead, which only the discovery listing reads - so the listing
        # is the authoritative source for frozen state and folder name.
        listed = self._manifest(version)
        merged = {**audit, "frozen": listed.get("frozen"), "folder": listed.get("folder")}
        return _core_ai1_descriptor(merged, audit.get("statistics"), audit.get("integrity"))

    def audit_dataset(self, model_family: str, version: str) -> DatasetAuditReport:
        audit = self._audit(version)
        integrity = audit.get("integrity") or {}
        return DatasetAuditReport(
            family=MODEL_FAMILY_CORE_AI1, version=version, ok=bool(integrity.get("valid")),
            checked_at=audit.get("created_at") or "",
            findings=list(integrity.get("errors", [])) + list(integrity.get("warnings", [])),
            recommendations=list(audit.get("recommended_human_actions", [])))

    def compare_datasets(self, model_family: str, left: str, right: str) -> DatasetComparison:
        raw = _guard(self._facade.compare_datasets, MODEL_FAMILY_CORE_AI1, left, right)
        return DatasetComparison(
            family=MODEL_FAMILY_CORE_AI1, left_version=left, right_version=right,
            differences=_differences(raw),
            left=self.inspect_dataset(model_family, left),
            right=self.inspect_dataset(model_family, right))

    def freeze_dataset(self, model_family: str, version: str, actor=None,
                       note=None) -> DatasetDescriptor:
        _guard(self._facade.freeze_dataset, MODEL_FAMILY_CORE_AI1, version, actor, note)
        return self.inspect_dataset(model_family, version)

    def export_dataset(self, adapter, version: str, config) -> DatasetDescriptor:
        """Export through the REAL backend, driven by the Claude-owned
        finalized-record adapter. A failed export publishes nothing - the
        backend writes to a temporary folder and renames only on success."""
        result = _guard(self._facade.export_core_ai1_dataset, adapter, version,
                        _to_codex_dataset_config(config))
        manifest = dict(result.get("manifest", {}))
        manifest["folder"] = result.get("dataset_folder", "")
        return _core_ai1_descriptor(manifest, result.get("statistics"))


def _to_codex_dataset_config(config):
    """The application's CoreAI1DatasetConfig -> the backend's, field for field.
    Already-native configs pass through untouched."""
    from app.models.core_ai1_dataset_types import CoreAI1DatasetConfig as CodexConfig
    if isinstance(config, CodexConfig):
        return config
    return CodexConfig(
        category_mapping=dict(config.category_mapping),
        category_mapping_version=config.category_mapping_version,
        seed=config.seed,
        split_ratios=tuple(config.split_ratios),
        min_samples=config.min_samples,
        min_groups=config.min_groups,
        min_examples_per_category=config.min_examples_per_category,
        required_parts=tuple(config.required_parts),
    )


def _differences(raw) -> List[str]:
    """Normalise a backend comparison into display lines without discarding
    anything it reported."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, dict):
        for key in ("differences", "changes", "diff"):
            value = raw.get(key)
            if isinstance(value, list):
                return [str(item) for item in value]
            if isinstance(value, dict):
                return [f"{name}: {detail}" for name, detail in value.items()]
        return [f"{name}: {value}" for name, value in sorted(raw.items())]
    return [str(raw)]


# ------------------------------------------------------------ jobs + models ---

def _model_descriptor(family: str, data: Dict[str, Any]) -> ModelDescriptor:
    """A backend model manifest -> ModelDescriptor. Absent facts stay absent."""
    return ModelDescriptor(
        family=family,
        version=str(data.get("model_version") or data.get("version") or ""),
        path=str(data.get("path") or ""),
        checksum=str(data.get("model_checksum") or ""),
        created_at=str(data.get("created_at") or ""),
        source_dataset_version=str(data.get("source_dataset_version") or ""),
        source_dataset_checksum=str(data.get("source_dataset_checksum") or ""),
        training_job_id=str(data.get("training_job_id") or ""),
        base_model_identifier=str(data.get("base_model_identifier") or ""),
        architecture=str(data.get("architecture") or ""),
        mapping=dict(data.get("category_mapping") or data.get("mapping") or {}),
        compatible_schema_versions=list(data.get("compatible_schema_versions") or []),
        evaluation_status=str(data.get("evaluation_status") or "unevaluated"),
        activation_status=str(data.get("activation_status")
                              or ("active" if data.get("active") else "inactive")),
        runtime_compatibility=str(data.get("runtime_compatibility") or "unknown"),
        hardware_requirements=dict(data.get("hardware_requirements") or {}),
        artifact_inventory=list(data.get("artifact_inventory") or []),
        warnings=list(data.get("warnings") or []),
    )


def _evaluation_result(data: Dict[str, Any]) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=str(data.get("evaluation_id") or ""),
        model_version=str(data.get("model_version") or ""),
        dataset_version=str(data.get("dataset_version") or ""),
        dataset_checksum=str(data.get("dataset_checksum") or ""),
        split=str(data.get("split") or ""),
        metrics=dict(data.get("metrics") or {}),
        per_class_metrics=dict(data.get("per_class_metrics") or {}),
        errors=list(data.get("errors") or []),
        warnings=list(data.get("warnings") or []),
        passed=bool(data.get("passed")),
        decision_criteria=dict(data.get("decision_criteria") or {}),
        evaluated_at=str(data.get("evaluated_at") or ""),
    )


def _job_record(record) -> TrainingJobRecord:
    """The backend's TrainingJobRecord -> the port's, field for field.

    `progress_value` is passed through exactly as reported: when the backend
    states no percentage, none is shown. No progress is ever invented.
    """
    if isinstance(record, TrainingJobRecord):
        return record
    data = record if isinstance(record, dict) else record.__dict__
    return TrainingJobRecord(
        job_id=str(data.get("job_id") or ""),
        model_family=str(data.get("model_family") or ""),
        dataset_version=str(data.get("dataset_version") or ""),
        requested_model_version=str(data.get("requested_model_version") or ""),
        created_at=str(data.get("created_at") or ""),
        status=str(data.get("status") or ""),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        cancellation_requested=bool(data.get("cancellation_requested")),
        progress_message=str(data.get("progress_message") or ""),
        progress_value=data.get("progress_value"),
        current_epoch=data.get("current_epoch"),
        current_step=data.get("current_step"),
        configuration=dict(data.get("configuration") or {}),
        hardware_runtime=dict(data.get("hardware_runtime") or {}),
        events=list(data.get("events") or []),
        result_model_version=data.get("result_model_version"),
        failure_code=data.get("failure_code"),
        failure_message=data.get("failure_message"),
    )


class FacadeJobModelBackend:
    """CoreAIJobModelPort over the real facade, for one model family."""

    def __init__(self, facade, model_family: str) -> None:
        self._facade = facade
        self.model_family = model_family

    def _check(self, model_family: str) -> str:
        if model_family != self.model_family:
            raise BackendError("unsupported_family",
                               f"This backend serves {self.model_family}.")
        return model_family

    def validate_training_request(self, model_family, dataset_version, configuration):
        self._check(model_family)
        result = _guard(self._facade.validate_training_request, model_family, dataset_version,
                        configuration)
        return list(result or [])

    def create_training_job(self, model_family, dataset_version, configuration):
        self._check(model_family)
        return _job_record(_guard(self._facade.create_training_job, model_family,
                                  dataset_version, configuration))

    def run_training_job(self, job_id, configuration):
        return _job_record(_guard(self._facade.run_training_job, job_id, configuration))

    def cancel_training_job(self, job_id):
        return _job_record(_guard(self._facade.cancel_training_job, job_id))

    def finalize_cancellation(self, job_id):
        """The backend transitions a cancelling job to cancelled itself once the
        worker stops; reading it back reports the terminal state."""
        return _job_record(_guard(self._facade.get_training_job, job_id))

    def get_training_job(self, job_id):
        return _job_record(_guard(self._facade.get_training_job, job_id))

    def list_training_jobs(self, model_family=None):
        records = _guard(self._facade.list_training_jobs, model_family or self.model_family)
        return [_job_record(record) for record in records]

    def recover_interrupted_jobs(self):
        return [_job_record(record) for record in _guard(self._facade.recover_interrupted_jobs)]

    def list_models(self, model_family):
        self._check(model_family)
        return [_model_descriptor(model_family, model)
                for model in _guard(self._facade.list_models, model_family)]

    def inspect_model(self, model_family, version):
        self._check(model_family)
        return _model_descriptor(model_family,
                                 _guard(self._facade.inspect_model, model_family, version))

    def evaluate_model(self, model_family, model_version, dataset_version):
        self._check(model_family)
        return _evaluation_result(_guard(self._facade.evaluate_model, model_family,
                                         model_version, dataset_version))

    def compare_models(self, model_family, left, right):
        self._check(model_family)
        raw = _guard(self._facade.compare_models, model_family, left, right)
        return ModelComparison(
            family=model_family, left_version=left, right_version=right,
            differences=_differences(raw),
            left=self.inspect_model(model_family, left),
            right=self.inspect_model(model_family, right))

    def activate_model(self, model_family, version, actor, reason):
        self._check(model_family)
        _guard(self._facade.activate_model, model_family, version, actor, reason)
        return self.inspect_model(model_family, version)

    def rollback_model(self, model_family, target_version, actor, reason):
        self._check(model_family)
        _guard(self._facade.rollback_model, model_family, target_version, actor, reason)
        return self.inspect_model(model_family, target_version)

    def get_active_model(self, model_family, required=True):
        self._check(model_family)
        pointer = _guard(self._facade.get_active_model, model_family, required)
        if not pointer:
            return None
        return self.inspect_model(model_family, pointer.get("model_version"))

    def inspect_runtime(self, model_family, model_version=None):
        self._check(model_family)
        raw = _guard(self._facade.inspect_runtime,
                     {"model_family": model_family, "model_version": model_version})
        data = raw if isinstance(raw, dict) else {}
        return RuntimeInspection(
            family=model_family,
            model_version=model_version,
            memory_status=str(data.get("memory_status") or "unknown"),
            graceful_no_ai_mode=bool(data.get("graceful_no_ai_mode", True)),
            warnings=list(data.get("warnings") or []),
            blockers=list(data.get("blockers") or []),
            details=dict(data.get("details") or data or {}),
        )


# --------------------------------------------------------------- inference ---

class FacadeCoreAI2InferenceBackend:
    """CoreAI2InferencePort over the real facade. Cancellation is passed
    straight through to the backend's cooperative token."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def run_core_ai2_inference(self, request, cancellation_token=None):
        return _guard(self._facade.run_core_ai2_inference, request, cancellation_token)


class FacadeCoreAI1InferenceBackend:
    """CoreAI1InferencePort over the real facade. Per-request independence is
    the backend's own guarantee - one failed section never removes the others."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def run_core_ai1_inference(self, request):
        return _guard(self._facade.run_core_ai1_inference, request)

    def run_core_ai1_attempt_inference(self, requests):
        return list(_guard(self._facade.run_core_ai1_attempt_inference, list(requests)))


class FacadeFeedbackBackend:
    """FeedbackPort over the real facade."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def generate_local_feedback(self, request, cancellation_token=None):
        return _guard(self._facade.generate_local_feedback, request, cancellation_token)

    def generate_template_feedback(self, request):
        return _guard(self._facade.generate_template_feedback, request)


class FacadeReviewCaptureBackend:
    """Review capture over the real facade."""

    def __init__(self, facade) -> None:
        self._facade = facade

    def capture_core_ai1_reviews(self, candidate_version, records):
        return _guard(self._facade.capture_core_ai1_reviews, candidate_version, records)

    def capture_core_ai2_reviews(self, candidate_version, records):
        return _guard(self._facade.capture_core_ai2_reviews, candidate_version, records)


# Documented UI-only mappings: everything here is derived from a value the
# backend actually reported, never invented.
UI_ONLY_MAPPINGS = (
    "Core AI 2 statistics.class_count = len(class_counts) - the cards show a "
    "count, the registry reports per-class counts.",
    "Core AI 2 statistics.leakage_safe_split = bool(split_mode) - the registry "
    "states the split mode it applied.",
    "Core AI 1 statistics.mode_distribution = source_mode_distribution, and "
    "attempt_group_count = leakage_safe_group_count - renamed for the column "
    "headings only.",
    "Core AI 1 statistics.leakage_safe_split = bool(leakage_safe_group_count).",
    "DatasetDescriptor.path carries the dataset FOLDER name, which is what the "
    "interface displays.",
    "Comparison differences are flattened to display lines without discarding "
    "any reported difference.",
    "activate_model / rollback_model re-inspect the model so the interface "
    "receives a full descriptor rather than the activation pointer.",
)
