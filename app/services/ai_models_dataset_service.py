"""Stage 12G-2 - admin-only Core AI 2 dataset management (discovery, inspection,
readiness audit, comparison, freeze, COCO/YOLO conversion).

Thin permission+audit layer over the narrow CoreAI2DatasetPort. Every mutating
action is admin-guarded (ai_admin_access_service) and audited (ai_admin_audit).
The backend is the deterministic fake until the Codex façade is merged; swap
`get_core_ai2_dataset_backend()` at integration - no caller change needed.
"""
import json
import sqlite3
from typing import List, Optional

from app.models import ai_admin_audit_model as audit
from app.models.user_model import User
from app.services import ai_admin_access_service as ai_access
from app.services.ai_backend_port import (
    MODEL_FAMILY_CORE_AI2,
    ConversionResult,
    CoreAI2DatasetPort,
    DatasetAuditReport,
    DatasetComparison,
    DatasetDescriptor,
)
from app.services.ai_backend_fake import FakeCoreAI2DatasetBackend

# Until the Codex façade is merged, a single process-wide fake backend backs
# the UI. Tests inject their own via the `backend` argument.
_DEFAULT_BACKEND: Optional[CoreAI2DatasetPort] = None


def get_core_ai2_dataset_backend() -> CoreAI2DatasetPort:
    """The REAL Core AI 2 dataset backend, through the Core AI facade.

    Production never falls back to a fake. A test may inject one by setting
    `_DEFAULT_BACKEND` (or by injecting a facade through
    ai_backend_integration.set_backend_facade).
    """
    if _DEFAULT_BACKEND is not None:
        return _DEFAULT_BACKEND
    from app.services.ai_backend_facade_adapters import FacadeCoreAI2DatasetBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeCoreAI2DatasetBackend(get_backend_facade())


def _backend(backend: Optional[CoreAI2DatasetPort]) -> CoreAI2DatasetPort:
    return backend if backend is not None else get_core_ai2_dataset_backend()


# --- read-only (still admin-guarded) ---------------------------------------

def list_datasets(conn: sqlite3.Connection, user: Optional[User],
                  backend: Optional[CoreAI2DatasetPort] = None) -> List[DatasetDescriptor]:
    ai_access.require_ai_models_access(conn, user, action="ai_models.dataset_list")
    return _backend(backend).list_datasets(MODEL_FAMILY_CORE_AI2)


def inspect_dataset(conn: sqlite3.Connection, user: Optional[User], version: str,
                    backend: Optional[CoreAI2DatasetPort] = None) -> DatasetDescriptor:
    ai_access.require_ai_models_access(conn, user, action="ai_models.dataset_inspect", target=version)
    return _backend(backend).inspect_dataset(MODEL_FAMILY_CORE_AI2, version)


def audit_dataset(conn: sqlite3.Connection, user: Optional[User], version: str,
                  backend: Optional[CoreAI2DatasetPort] = None) -> DatasetAuditReport:
    ai_access.require_ai_models_access(conn, user, action="ai_models.dataset_audit", target=version)
    return _backend(backend).audit_dataset(MODEL_FAMILY_CORE_AI2, version)


def compare_datasets(conn: sqlite3.Connection, user: Optional[User], left: str, right: str,
                     backend: Optional[CoreAI2DatasetPort] = None) -> DatasetComparison:
    ai_access.require_ai_models_access(conn, user, action="ai_models.dataset_compare",
                                       target=f"{left} vs {right}")
    return _backend(backend).compare_datasets(MODEL_FAMILY_CORE_AI2, left, right)


# --- mutating (admin-guarded + audited) ------------------------------------

def freeze_dataset(conn: sqlite3.Connection, user: Optional[User], version: str,
                   note: Optional[str] = None,
                   backend: Optional[CoreAI2DatasetPort] = None) -> DatasetDescriptor:
    """Freeze an export-valid dataset. PERMANENT - there is no unfreeze. The
    caller (UI) must have obtained an explicit human confirmation first."""
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_DATASET_FREEZE, target=version)
    descriptor = _backend(backend).freeze_dataset(
        MODEL_FAMILY_CORE_AI2, version, actor=(str(user.user_id) if user else None), note=note)
    audit.record_ai_admin_action(
        conn, actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None), action=ai_access.ACTION_DATASET_FREEZE,
        target=version, note=json.dumps({"family": MODEL_FAMILY_CORE_AI2, "permanent": True}))
    return descriptor


def convert_dataset(conn: sqlite3.Connection, user: Optional[User], version: str,
                    output_format: str, conversion_version: str,
                    backend: Optional[CoreAI2DatasetPort] = None) -> ConversionResult:
    """Generate a COCO or YOLO conversion of a frozen dataset. Overwriting an
    existing conversion version is rejected by the backend."""
    ai_access.require_ai_models_access(conn, user, action=ai_access.ACTION_DATASET_CONVERT,
                                       target=f"{version}:{output_format}")
    result = _backend(backend).convert_dataset(
        MODEL_FAMILY_CORE_AI2, version, output_format, conversion_version)
    audit.record_ai_admin_action(
        conn, actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None), action=ai_access.ACTION_DATASET_CONVERT,
        target=version, note=json.dumps({"format": output_format, "conversion_version": conversion_version}))
    return result
