"""Stage 12G-3 - admin-only AI training jobs, model registry, evaluation,
activation and rollback (Core AI 2 for now; the same port serves Core AI 1).

Thin permission+audit layer over the narrow CoreAIJobModelPort. Every mutating
action is admin-guarded and audited on the shared sanitized spine. The backend
is the deterministic fake until the Codex façade is merged; swap
`get_job_model_backend()` at integration - no caller change needed.
"""
import json
import sqlite3
from typing import List, Optional

from app.models import ai_admin_audit_model as audit
from app.models.user_model import User
from app.services import ai_admin_access_service as ai_access
from app.services.ai_backend_fake import FakeCoreAIJobModelBackend
from app.services.ai_backend_port import (
    MODEL_FAMILY_CORE_AI1,
    MODEL_FAMILY_CORE_AI2,
    BackendError,
    CoreAIJobModelPort,
    EvaluationResult,
    ModelComparison,
    ModelDescriptor,
    RuntimeInspection,
    TrainingJobRecord,
)

# Back-compat: an explicit core_ai2 override (used by existing tests). Other
# families get a per-family cached fake.
_DEFAULT_BACKEND: Optional[CoreAIJobModelPort] = None
_FAMILY_BACKENDS: dict = {}


def get_job_model_backend(family: str = MODEL_FAMILY_CORE_AI2) -> CoreAIJobModelPort:
    """The REAL training/model backend for a family, through the Core AI facade.

    Production never falls back to a fake. Tests inject one per family through
    `_FAMILY_BACKENDS` (or `_DEFAULT_BACKEND` for core_ai2).
    """
    if family == MODEL_FAMILY_CORE_AI2 and _DEFAULT_BACKEND is not None:
        return _DEFAULT_BACKEND
    if family in _FAMILY_BACKENDS:
        return _FAMILY_BACKENDS[family]
    from app.services.ai_backend_facade_adapters import FacadeJobModelBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeJobModelBackend(get_backend_facade(), family)


def _backend(backend: Optional[CoreAIJobModelPort],
             family: str = MODEL_FAMILY_CORE_AI2) -> CoreAIJobModelPort:
    return backend if backend is not None else get_job_model_backend(family)


def resolve_dataset(conn, user, family: str):
    """The dataset descriptor for a version, or None. Used to gate training on
    the dataset's REAL state rather than on a caller-supplied claim."""
    def _lookup(version):
        try:
            if family == MODEL_FAMILY_CORE_AI1:
                from app.services import ai_models_core1_dataset_service as core1
                return core1.inspect_dataset(conn, user, version)
            from app.services import ai_models_dataset_service as ds
            return ds.inspect_dataset(conn, user, version)
        except Exception:
            return None
    return _lookup


def dataset_readiness_blockers(conn, user, family: str, dataset_version: str) -> List[str]:
    """Every reason this dataset may not be trained from. Training requires a
    FROZEN, TRAINING-READY dataset with a leakage-safe split; an export-valid
    but unready dataset stays inspectable and freezeable only. The dataset's own
    blockers are surfaced verbatim so the rejection says exactly what to fix.

    This is enforced in the SERVICE, so a direct adapter call is rejected too -
    not only a click in the interface.
    """
    descriptor = resolve_dataset(conn, user, family)(dataset_version)
    if descriptor is None:
        return [f"Dataset '{dataset_version}' was not found."]
    blockers: List[str] = []
    if not descriptor.frozen:
        blockers.append(f"Dataset '{dataset_version}' is not frozen. Freeze it before training.")
    if not descriptor.training_ready:
        blockers.append(f"Dataset '{dataset_version}' is not training-ready.")
    if not descriptor.statistics.get("leakage_safe_split", True):
        blockers.append(f"Dataset '{dataset_version}' does not have a leakage-safe split.")
    blockers.extend(descriptor.blockers)
    return blockers


def _mark_core_ai1_drafts_stale(conn, family: str, active_version: Optional[str]) -> int:
    """After a Core AI 1 activation or rollback, every teacher draft produced by
    a different model version becomes stale, so none can be applied against a
    model that is no longer live. Teacher-final scores, categories and feedback
    are never touched."""
    if family != MODEL_FAMILY_CORE_AI1:
        return 0
    try:
        import app.models.ai_core1_draft_model as drafts
        return drafts.mark_drafts_stale_for_other_models(conn, active_version)
    except Exception:
        return 0


def _audit(conn, user: Optional[User], action: str, target: Optional[str], note: dict) -> None:
    audit.record_ai_admin_action(
        conn, actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None), action=action, target=target,
        note=json.dumps(note))


# --- read-only (admin-guarded) ---------------------------------------------

def validate_training_request(conn, user, dataset_version, configuration,
                              family=MODEL_FAMILY_CORE_AI2, backend=None) -> List[str]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.training_validate", target=dataset_version)
    blockers = dataset_readiness_blockers(conn, user, family, dataset_version)
    for extra in _backend(backend, family).validate_training_request(
            family, dataset_version, configuration):
        if extra not in blockers:
            blockers.append(extra)
    return blockers


def list_training_jobs(conn, user, family=MODEL_FAMILY_CORE_AI2, backend=None) -> List[TrainingJobRecord]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.jobs_list")
    return _backend(backend, family).list_training_jobs(family)


def get_training_job(conn, user, job_id, family=MODEL_FAMILY_CORE_AI2, backend=None) -> TrainingJobRecord:
    ai_access.require_ai_models_access(conn, user, action="ai_models.job_get", target=job_id)
    return _backend(backend, family).get_training_job(job_id)


def list_models(conn, user, family=MODEL_FAMILY_CORE_AI2, backend=None) -> List[ModelDescriptor]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.models_list")
    return _backend(backend, family).list_models(family)


def inspect_model(conn, user, version, family=MODEL_FAMILY_CORE_AI2, backend=None) -> ModelDescriptor:
    ai_access.require_ai_models_access(conn, user, action="ai_models.model_inspect", target=version)
    return _backend(backend, family).inspect_model(family, version)


def compare_models(conn, user, left, right, family=MODEL_FAMILY_CORE_AI2, backend=None) -> ModelComparison:
    ai_access.require_ai_models_access(conn, user, action="ai_models.model_compare", target=f"{left} vs {right}")
    return _backend(backend, family).compare_models(family, left, right)


def get_active_model(conn, user, family=MODEL_FAMILY_CORE_AI2, backend=None) -> Optional[ModelDescriptor]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.active_model")
    return _backend(backend, family).get_active_model(family, required=False)


def inspect_runtime(conn, user, family=MODEL_FAMILY_CORE_AI2, model_version=None, backend=None) -> RuntimeInspection:
    ai_access.require_ai_models_access(conn, user, action="ai_models.runtime_inspect")
    return _backend(backend, family).inspect_runtime(family, model_version)


# --- mutating (admin-guarded + audited) ------------------------------------

def create_training_job(conn, user, dataset_version, configuration,
                        family=MODEL_FAMILY_CORE_AI2, backend=None) -> TrainingJobRecord:
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_TRAINING_START, target=dataset_version)
    # Refuse before ANY job, model or evaluation artifact can be created, and
    # report the exact readiness blockers.
    blockers = dataset_readiness_blockers(conn, user, family, dataset_version)
    if blockers:
        _audit(conn, user, ai_access.ACTION_TRAINING_START, dataset_version,
               {"family": family, "rejected": "not_training_ready", "blockers": blockers})
        raise BackendError("dataset_not_training_ready", " ".join(blockers))
    job = _backend(backend, family).create_training_job(family, dataset_version, configuration)
    _audit(conn, user, ai_access.ACTION_TRAINING_START, job.job_id,
           {"family": family, "dataset_version": dataset_version})
    return job


def run_training_job(conn, user, job_id, configuration, family=MODEL_FAMILY_CORE_AI2, backend=None) -> TrainingJobRecord:
    """Execute a created job. This may BLOCK - callers must run it in a
    background worker, never on the UI thread."""
    ai_access.require_ai_models_access(conn, user, action="ai_models.training_run", target=job_id)
    job = _backend(backend, family).run_training_job(job_id, configuration)
    _audit(conn, user, "ai_models.training_run", job_id,
           {"status": job.status, "result_model_version": job.result_model_version})
    return job


def cancel_training_job(conn, user, job_id, family=MODEL_FAMILY_CORE_AI2, backend=None) -> TrainingJobRecord:
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_TRAINING_CANCEL, target=job_id)
    job = _backend(backend, family).cancel_training_job(job_id)
    _audit(conn, user, ai_access.ACTION_TRAINING_CANCEL, job_id, {"status": job.status})
    return job


def finalize_cancelled_job(conn, user, job_id, family=MODEL_FAMILY_CORE_AI2,
                           backend=None) -> TrainingJobRecord:
    """Complete an acknowledged cancellation once the worker has stopped:
    cancelling -> cancelled (TERMINAL). Safe to call repeatedly."""
    ai_access.require_ai_models_access(conn, user, action="ai_models.training_cancel_finalize",
                                       target=job_id)
    job = _backend(backend, family).finalize_cancellation(job_id)
    _audit(conn, user, "ai_models.training_cancel_finalize", job_id, {"status": job.status})
    return job


def evaluate_model(conn, user, model_version, dataset_version,
                   family=MODEL_FAMILY_CORE_AI2, backend=None) -> EvaluationResult:
    ai_access.require_ai_models_access(conn, user, action="ai_models.model_evaluate", target=model_version)
    result = _backend(backend, family).evaluate_model(family, model_version, dataset_version)
    _audit(conn, user, "ai_models.model_evaluate", model_version,
           {"dataset_version": dataset_version, "passed": result.passed})
    return result


def activate_model(conn, user, version, reason, family=MODEL_FAMILY_CORE_AI2, backend=None) -> ModelDescriptor:
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_MODEL_ACTIVATE, target=version)
    model = _backend(backend, family).activate_model(family, version, actor=(str(user.user_id) if user else ""),
                                             reason=reason)
    stale = _mark_core_ai1_drafts_stale(conn, family, version)
    _audit(conn, user, ai_access.ACTION_MODEL_ACTIVATE, version,
           {"reason": reason, "drafts_marked_stale": stale})
    return model


def rollback_model(conn, user, target_version, reason, family=MODEL_FAMILY_CORE_AI2, backend=None) -> ModelDescriptor:
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_MODEL_ROLLBACK, target=target_version)
    model = _backend(backend, family).rollback_model(family, target_version, actor=(str(user.user_id) if user else ""),
                                             reason=reason)
    stale = _mark_core_ai1_drafts_stale(conn, family, target_version)
    _audit(conn, user, ai_access.ACTION_MODEL_ROLLBACK, target_version,
           {"reason": reason, "drafts_marked_stale": stale})
    return model


def recover_interrupted_jobs(conn, user, family=MODEL_FAMILY_CORE_AI2, backend=None) -> List[TrainingJobRecord]:
    """Called once on admin dashboard startup - abandoned nonterminal jobs
    become 'interrupted' (never silently resumed)."""
    ai_access.require_ai_models_access(conn, user, action="ai_models.jobs_recover")
    recovered = _backend(backend, family).recover_interrupted_jobs()
    if recovered:
        _audit(conn, user, "ai_models.jobs_recover", None, {"recovered": [j.job_id for j in recovered]})
    return recovered
