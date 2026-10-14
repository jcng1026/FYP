"""Stage 12G-2 - permission boundary for the global AI Models registry.

The AI Models page (model families, datasets, training jobs, activation,
proposals) is owned by the technical developer/admin account only. Teachers and
students must never reach it through navigation or a direct UI/service call.

This module is the single choke-point that enforces that boundary and records
an audited, explicit denial. It never mutates account or class permissions.
"""
import sqlite3
from typing import Optional

from app.models import ai_admin_audit_model as audit
from app.models.user_model import User
from app.services.user_service import ADMIN_ROLE

# Stable action names for the audit trail (reused by later subsystems).
ACTION_OPEN_AI_MODELS = "ai_models.open"
ACTION_DATASET_FREEZE = "ai_models.dataset_freeze"
ACTION_DATASET_CONVERT = "ai_models.dataset_convert"
ACTION_MODEL_ACTIVATE = "ai_models.model_activate"
ACTION_MODEL_ROLLBACK = "ai_models.model_rollback"
ACTION_TRAINING_START = "ai_models.training_start"
ACTION_TRAINING_CANCEL = "ai_models.training_cancel"
ACTION_PROPOSAL_ACCEPT = "ai_proposal.accept"
ACTION_PROPOSAL_REJECT = "ai_proposal.reject"
ACTION_LOCAL_AI_FALLBACK = "local_ai.fallback"


class AIPermissionError(PermissionError):
    """Raised when a non-admin actor attempts an AI-admin action."""


def can_access_ai_models(user: Optional[User]) -> bool:
    """True only for the technical developer/admin account. Pure check with no
    side effects - safe to drive UI enable/visible state."""
    return user is not None and user.role == ADMIN_ROLE


def require_ai_models_access(
    conn: sqlite3.Connection, user: Optional[User], *, action: str = ACTION_OPEN_AI_MODELS,
    target: Optional[str] = None,
) -> None:
    """Enforce admin-only access to an AI-admin action.

    On success this is silent (individual actions record their own success
    audit where meaningful). On denial it records an explicit audited denial
    and raises AIPermissionError, so a teacher/student calling an AI service
    directly is rejected exactly like the hidden navigation.
    """
    if can_access_ai_models(user):
        return
    audit.record_ai_admin_action(
        conn,
        actor_user_id=(user.user_id if user else None),
        actor_role=(user.role if user else None),
        action=action,
        outcome=audit.OUTCOME_DENIED,
        target=target,
        note='{"reason": "ai_models_admin_only"}',
    )
    raise AIPermissionError("Only the technical developer/admin account can access AI Models.")
