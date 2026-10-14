"""Stage 12G-2 - assemble the AI Models page display data for the two model
families (Core AI 1 cross-encoder scorer, Core AI 2 region detector).

Every field is either a real value read from the registry / a supplied runtime
adapter, or a clearly-labelled "not available" / "not evaluated" / "unknown"
sentinel. This module NEVER fabricates a value it does not have - unresolved
runtime facts (checksum, on-disk availability, schema compatibility) come from
the Codex model-runtime adapter, and default to clearly-unknown when that
adapter is absent (unmerged backend).
"""
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from app.models import ai_model_registry_model as registry
from app.services.ai_model_registry_service import get_supported_ai_model_specs

# Display sentinels - deliberately human-readable and never confused with data.
UNAVAILABLE = "Not available"
NOT_EVALUATED = "Not evaluated"
UNKNOWN = "Unknown"
NOT_TRAINED = "No trained version"

# The application groups the registry model keys into two "families". The
# optional scan-quality classifier is intentionally excluded (not implemented).
FAMILY_CORE_AI_1 = "Core AI 1"
FAMILY_CORE_AI_2 = "Core AI 2"
_KEY_TO_FAMILY = {
    registry.MODEL_KEY_K2_SHORT_ANSWER_SCORING: FAMILY_CORE_AI_1,
    registry.MODEL_KEY_ANSWER_REGION_DETECTION: FAMILY_CORE_AI_2,
}


class ModelRuntimeAdapter(Protocol):
    """Narrow, replaceable contract fulfilled by the Codex model-runtime
    backend after merge. Returns only FACTS about an on-disk model; it must
    never invent availability or a checksum."""

    def describe_runtime(self, version: registry.AIModelVersion) -> Dict[str, Any]:
        """Return keys: runtime_available (bool|None), checksum (str|None),
        supported_schema_version (str|None), compatible (bool|None),
        warnings (list[str]). Any unknown value must be None / omitted."""


class NullRuntimeAdapter:
    """Default adapter used until the Codex runtime backend is merged. Reports
    everything as unknown - it fabricates nothing."""

    def describe_runtime(self, version: registry.AIModelVersion) -> Dict[str, Any]:
        return {"runtime_available": None, "checksum": None,
                "supported_schema_version": None, "compatible": None, "warnings": []}


@dataclass
class ModelVersionRow:
    model_id: int
    version_label: str
    status: str
    is_active: bool
    created_at: str
    dataset_version: str
    evaluation_status: str
    evaluation_summary: str
    supported_schema_version: str
    runtime_available: str
    model_path: str
    checksum: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class ModelFamilyView:
    family: str
    model_key: str
    model_name: str
    model_type: str
    purpose: str
    technique: str
    active_version_label: str
    active_evaluation_status: str
    runtime_available: str
    warnings: List[str]
    versions: List[ModelVersionRow]
    job_history: List[Dict[str, Any]]
    activation_history: List[Dict[str, Any]]

    @property
    def has_trained_version(self) -> bool:
        return bool(self.versions)


def _loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _evaluation(metrics: Dict[str, Any]) -> tuple[str, str]:
    """(status, one-line summary) from a version's metrics_json. Absent metrics
    are reported as not-evaluated, never as a passing evaluation."""
    if not metrics:
        return NOT_EVALUATED, NOT_EVALUATED
    status = metrics.get("evaluation_status") or ("Evaluated" if metrics else NOT_EVALUATED)
    parts = []
    for key in ("accuracy", "f1", "map", "mae", "qwk", "primary_metric"):
        if key in metrics and isinstance(metrics[key], (int, float)):
            parts.append(f"{key}={metrics[key]:.4g}")
    summary = ", ".join(parts) if parts else (metrics.get("summary") or "Evaluated (no headline metric)")
    return str(status), str(summary)


def _version_row(version: registry.AIModelVersion, adapter: ModelRuntimeAdapter) -> ModelVersionRow:
    metrics = _loads(version.metrics_json)
    config = _loads(version.config_json)
    eval_status, eval_summary = _evaluation(metrics)
    runtime = adapter.describe_runtime(version) or {}

    def _runtime_flag(value) -> str:
        if value is True:
            return "Available"
        if value is False:
            return UNAVAILABLE
        return UNKNOWN

    schema_version = (runtime.get("supported_schema_version")
                      or config.get("supported_schema_version") or UNKNOWN)
    warnings = list(runtime.get("warnings") or [])
    if runtime.get("compatible") is False:
        warnings.append("Runtime reports this model is INCOMPATIBLE with the current schema/mapping.")
    return ModelVersionRow(
        model_id=version.model_id,
        version_label=version.version_label,
        status=("Active" if version.is_active else "Inactive"),
        is_active=version.is_active,
        created_at=version.created_at,
        dataset_version=str(config.get("dataset_version") or UNKNOWN),
        evaluation_status=eval_status,
        evaluation_summary=eval_summary,
        supported_schema_version=str(schema_version),
        runtime_available=_runtime_flag(runtime.get("runtime_available")),
        model_path=(version.model_path or UNAVAILABLE),
        checksum=str(runtime.get("checksum") or UNKNOWN),
        warnings=warnings,
    )


def build_model_family_view(
    conn: sqlite3.Connection, owner_user_id: int, model_key: str,
    adapter: Optional[ModelRuntimeAdapter] = None,
) -> ModelFamilyView:
    adapter = adapter or NullRuntimeAdapter()
    spec = next(s for s in get_supported_ai_model_specs() if s.model_key == model_key)
    versions = registry.get_model_versions_for_teacher(conn, owner_user_id, model_key)
    rows = [_version_row(v, adapter) for v in versions]
    active = next((r for r in rows if r.is_active), None)
    jobs = registry.get_training_jobs_for_teacher(conn, owner_user_id, model_key, limit=50)

    job_history = [{
        "job_id": j.job_id, "status": j.status, "progress_percent": j.progress_percent,
        "current_step": j.current_step or "", "message": j.message or "",
        "created_at": j.created_at, "completed_at": j.completed_at or "",
        "output_model_id": j.output_model_id,
    } for j in jobs]
    activation_history = [{
        "model_id": r.model_id, "version_label": r.version_label,
        "is_active": r.is_active, "created_at": r.created_at,
    } for r in rows]

    warnings: List[str] = []
    for r in rows:
        warnings.extend(r.warnings)

    return ModelFamilyView(
        family=_KEY_TO_FAMILY[model_key],
        model_key=model_key,
        model_name=spec.model_name,
        model_type=spec.model_type,
        purpose=spec.purpose,
        technique=spec.technique,
        active_version_label=(active.version_label if active else NOT_TRAINED),
        active_evaluation_status=(active.evaluation_status if active else NOT_EVALUATED),
        runtime_available=(active.runtime_available if active else UNAVAILABLE),
        warnings=warnings,
        versions=rows,
        job_history=job_history,
        activation_history=activation_history,
    )


def build_all_model_family_views(
    conn: sqlite3.Connection, owner_user_id: int,
    adapter: Optional[ModelRuntimeAdapter] = None,
) -> List[ModelFamilyView]:
    """Both managed families in display order (Core AI 1, then Core AI 2). The
    optional scan-quality classifier is deliberately not included."""
    return [
        build_model_family_view(conn, owner_user_id, registry.MODEL_KEY_K2_SHORT_ANSWER_SCORING, adapter),
        build_model_family_view(conn, owner_user_id, registry.MODEL_KEY_ANSWER_REGION_DETECTION, adapter),
    ]
