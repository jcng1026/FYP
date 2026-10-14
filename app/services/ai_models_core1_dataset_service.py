"""Stage 12G-5 - admin-only Core AI 1 (Kertas 2 scoring) dataset controls.

Discovery / inspection / integrity audit / comparison / permanent freeze, plus
EXPORT of a new dataset version from finalised teacher-reviewed Kertas 2 records
via the Claude-owned FinalizedK2RecordAdapter. Admin-guarded + audited on the
shared spine. Backend is the deterministic fake until the Codex façade is
merged; export mirrors the façade's direct-adapter call.
"""
import json
from typing import List, Optional

from app.models import ai_admin_audit_model as audit
from app.models.user_model import User
from app.services import ai_admin_access_service as ai_access
from app.services.ai_backend_fake import FakeCoreAI1DatasetBackend
from app.services.ai_backend_port import (
    MODEL_FAMILY_CORE_AI1,
    CoreAI1DatasetConfig,
    CoreAI1DatasetPort,
    DatasetAuditReport,
    DatasetComparison,
    DatasetDescriptor,
)
from app.services.ai_core1_finalized_records import FinalizedK2RecordAdapter

_DEFAULT_BACKEND: Optional[CoreAI1DatasetPort] = None


def get_core_ai1_dataset_backend() -> CoreAI1DatasetPort:
    """The REAL Core AI 1 dataset backend, through the Core AI facade.

    Export runs the backend's own exporter driven by the Claude-owned
    FinalizedK2RecordAdapter. Production never falls back to a fake.
    """
    if _DEFAULT_BACKEND is not None:
        return _DEFAULT_BACKEND
    from app.services.ai_backend_facade_adapters import FacadeCoreAI1DatasetBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeCoreAI1DatasetBackend(get_backend_facade())


def _backend(backend):
    return backend if backend is not None else get_core_ai1_dataset_backend()


def default_category_mapping(conn) -> dict:
    """Stable category->id mapping from the seeded feedback categories."""
    import app.models.subject_profile_model as spm
    return {c.category_key: c.category_id for c in spm.list_feedback_categories(conn)}


def list_datasets(conn, user, backend=None) -> List[DatasetDescriptor]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.core1_dataset_list")
    return _backend(backend).list_datasets(MODEL_FAMILY_CORE_AI1)


def inspect_dataset(conn, user, version, backend=None) -> DatasetDescriptor:
    ai_access.require_ai_models_access(conn, user, action="ai_models.core1_dataset_inspect", target=version)
    return _backend(backend).inspect_dataset(MODEL_FAMILY_CORE_AI1, version)


def audit_dataset(conn, user, version, backend=None) -> DatasetAuditReport:
    ai_access.require_ai_models_access(conn, user, action="ai_models.core1_dataset_audit", target=version)
    return _backend(backend).audit_dataset(MODEL_FAMILY_CORE_AI1, version)


def compare_datasets(conn, user, left, right, backend=None) -> DatasetComparison:
    ai_access.require_ai_models_access(conn, user, action="ai_models.core1_dataset_compare",
                                       target=f"{left} vs {right}")
    return _backend(backend).compare_datasets(MODEL_FAMILY_CORE_AI1, left, right)


def freeze_dataset(conn, user, version, note=None, backend=None) -> DatasetDescriptor:
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_DATASET_FREEZE, target=version)
    descriptor = _backend(backend).freeze_dataset(
        MODEL_FAMILY_CORE_AI1, version, actor=(str(user.user_id) if user else None), note=note)
    audit.record_ai_admin_action(
        conn, actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None), action=ai_access.ACTION_DATASET_FREEZE,
        target=version, note=json.dumps({"family": MODEL_FAMILY_CORE_AI1, "permanent": True}))
    return descriptor


def export_dataset(conn, user, version, config: Optional[CoreAI1DatasetConfig] = None,
                   backend=None) -> DatasetDescriptor:
    """Export a new Core AI 1 dataset version from ALL finalised teacher-reviewed
    Kertas 2 records (global). The finalized-record adapter emits only the
    whitelisted safe fields."""
    ai_access.require_ai_models_access(conn, user, action="ai_models.core1_dataset_export", target=version)
    if config is None:
        config = CoreAI1DatasetConfig(
            category_mapping=default_category_mapping(conn), category_mapping_version="seeded-v1")
    adapter = FinalizedK2RecordAdapter(conn, teacher_id=None)  # global export
    descriptor = _backend(backend).export_dataset(adapter, version, config)
    audit.record_ai_admin_action(
        conn, actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None), action="ai_models.core1_dataset_export",
        target=version, note=json.dumps({"included": descriptor.statistics.get("included_count"),
                                         "excluded": descriptor.statistics.get("excluded_count")}))
    return descriptor
