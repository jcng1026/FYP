"""Stage 12G-4 - teacher-facing Core AI 2 region-proposal workflows.

Two workflows, both TEACHER-owned (not the admin AI registry):
  A. Subject Profile: propose answer regions on a profile's page; accept ->
     a normal editable Subject Profile region; reject -> retained evidence;
     edit -> teacher geometry kept beside the model's.
  B. Separate Answer Paper: propose regions on an attempt's page; accept ->
     an attempt-specific mapping only (never the shared profile); a changed
     accepted geometry triggers the existing staleness behaviour.

A proposal is never an automatic region/mapping. Manual mapping stays fully
usable when there is no model, the model is incompatible, inference fails, the
hardware is insufficient, or the teacher cancels - those paths simply persist
no proposals. Only geometry/class metadata is stored - never raw essays/OCR.
"""
import uuid
from typing import List, Optional

from app.models import ai_region_proposal_model as proposals
from app.services.ai_backend_fake import FakeCoreAI2InferenceBackend
from app.services.ai_backend_port import (
    INFERENCE_STATUS_OK,
    WORKFLOW_SEPARATE_ANSWER_PAPER,
    WORKFLOW_SUBJECT_PROFILE,
    CoreAI2InferenceRequest,
    CoreAI2InferencePort,
)

_DEFAULT_INFERENCE: Optional[CoreAI2InferencePort] = None


def get_inference_backend() -> CoreAI2InferencePort:
    """The REAL Core AI 2 inference backend, through the Core AI facade.

    A proposal is never accepted automatically and a failure persists nothing,
    so manual mapping stays fully usable. Production never falls back to a fake.
    """
    if _DEFAULT_INFERENCE is not None:
        return _DEFAULT_INFERENCE
    from app.services.ai_backend_facade_adapters import FacadeCoreAI2InferenceBackend
    from app.services.ai_backend_integration import get_backend_facade
    return FacadeCoreAI2InferenceBackend(get_backend_facade())


def _backend(backend):
    return backend if backend is not None else get_inference_backend()


class ProposalError(ValueError):
    pass


# --- run inference + persist ------------------------------------------------

def run_subject_profile_proposals(
    conn, teacher_id: int, profile_id: int, source: str, page_number: int,
    page_image_path: str, page_width: int, page_height: int, page_checksum: str,
    model_version: Optional[str] = None, backend=None, cancellation_token=None,
) -> proposals.RegionProposalRecord:
    """Run Core AI 2 on one Subject Profile page and persist any proposals.
    Returns the persisted proposals. On no-model/failure returns [] and the
    teacher keeps mapping manually."""
    from app.services.subject_profile_service import get_owned_subject_profile
    get_owned_subject_profile(conn, teacher_id, profile_id)
    # A cancelled run persists no proposals - manual mapping is unaffected.
    if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
        return []
    request = CoreAI2InferenceRequest(
        request_id=f"sp_{profile_id}_{source}_{page_number}_{uuid.uuid4().hex[:8]}",
        workflow_context=WORKFLOW_SUBJECT_PROFILE, page_image_path=page_image_path,
        page_checksum=page_checksum, page_width=page_width, page_height=page_height,
        model_version=model_version, profile_id=profile_id)
    result = _backend(backend).run_core_ai2_inference(request)
    if result.status != INFERENCE_STATUS_OK:
        return []
    persisted = []
    for proposal in result.proposals:
        record = proposals.create_proposal(
            conn, proposal_id=proposal.proposal_id, workflow_context=WORKFLOW_SUBJECT_PROFILE,
            model_family=proposal.model_family, profile_id=profile_id, source=source,
            page_number=page_number, model_version=proposal.model_version,
            model_checksum=proposal.model_checksum, input_page_checksum=result.page_checksum,
            proposed_class=proposal.region_class, confidence=proposal.confidence,
            rationale=proposal.rationale, source_geometry=proposal.normalized_bbox,
            actor_user_id=teacher_id)
        persisted.append(record)
    return persisted


def run_separate_paper_proposals(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, sap_page_id: int,
    page_image_path: str, page_width: int, page_height: int, page_checksum: str,
    model_version: Optional[str] = None, backend=None, cancellation_token=None,
) -> List[proposals.RegionProposalRecord]:
    from app.services.separate_answer_paper_service import _owned
    _owned(conn, teacher_id, profile_id, answer_file_id)
    # A cancelled run persists no proposals - manual mapping is unaffected.
    if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
        return []
    request = CoreAI2InferenceRequest(
        request_id=f"sap_{answer_file_id}_{sap_page_id}_{uuid.uuid4().hex[:8]}",
        workflow_context=WORKFLOW_SEPARATE_ANSWER_PAPER, page_image_path=page_image_path,
        page_checksum=page_checksum, page_width=page_width, page_height=page_height,
        model_version=model_version, profile_id=profile_id, attempt_id=answer_file_id)
    result = _backend(backend).run_core_ai2_inference(request)
    if result.status != INFERENCE_STATUS_OK:
        return []
    persisted = []
    for proposal in result.proposals:
        record = proposals.create_proposal(
            conn, proposal_id=proposal.proposal_id, workflow_context=WORKFLOW_SEPARATE_ANSWER_PAPER,
            model_family=proposal.model_family, profile_id=profile_id, answer_file_id=answer_file_id,
            sap_page_id=sap_page_id, model_version=proposal.model_version,
            model_checksum=proposal.model_checksum, input_page_checksum=result.page_checksum,
            proposed_class=proposal.region_class, confidence=proposal.confidence,
            rationale=proposal.rationale, source_geometry=proposal.normalized_bbox,
            actor_user_id=teacher_id)
        persisted.append(record)
    return persisted


# --- teacher decisions ------------------------------------------------------

def edit_proposal_geometry(conn, teacher_id: int, proposal_id: str,
                           x: float, y: float, width: float, height: float) -> None:
    """Record the teacher's edited geometry (source geometry preserved)."""
    _get_owned(conn, teacher_id, proposal_id)
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1
            and x + width <= 1.0001 and y + height <= 1.0001):
        raise ProposalError("Proposal geometry must lie inside the page (0-1).")
    proposals.set_final_geometry(conn, proposal_id, x, y, width, height)


def reject_proposal(conn, teacher_id: int, proposal_id: str, reason: Optional[str] = None) -> None:
    """Reject: retained as review evidence, never silently turned into a
    positive region/mapping."""
    _get_owned(conn, teacher_id, proposal_id)
    proposals.set_status(conn, proposal_id, proposals.STATUS_REJECTED, decision_reason=reason)


def defer_proposal(conn, teacher_id: int, proposal_id: str) -> None:
    _get_owned(conn, teacher_id, proposal_id)
    proposals.set_status(conn, proposal_id, proposals.STATUS_DEFERRED)


def _mapping_type_for_target(conn, teacher_id: int, record, target_label: str) -> str:
    """The attempt-mapping type for an accepted separate-paper proposal.

    The real Core AI 2 detector proposes page-region classes (question_area,
    answer_box, ...), not attempt mapping types, so the mapping type follows
    from the logical target the teacher assigned: a Kertas 1 question, a
    Kertas 2 part, or the Part 3 selected-question metadata. A proposal whose
    class already IS a mapping type keeps it unchanged."""
    import app.models.separate_answer_paper_model as sap
    if record.proposed_class in sap.MAPPING_TYPES:
        return record.proposed_class
    from app.services import separate_answer_paper_service as sap_svc
    for target in sap_svc.list_required_targets(conn, teacher_id, record.profile_id,
                                                record.answer_file_id):
        if target.target_label != target_label:
            continue
        if target.paper == "Kertas 1":
            return sap.MAPPING_TYPE_K1_INDIVIDUAL
        if target.paper == "Kertas 2":
            if target.display_label.startswith("Part 2"):
                return sap.MAPPING_TYPE_K2_PART2
            if target.display_label.startswith("Part 3"):
                return sap.MAPPING_TYPE_K2_PART3
            return sap.MAPPING_TYPE_K2_PART1
        return sap.MAPPING_TYPE_PART3_SELECTED_QUESTION
    raise ProposalError(
        f"Target '{target_label}' is not a required target of this attempt.")


def accept_proposal(conn, teacher_id: int, proposal_id: str, *, target_label: Optional[str] = None,
                    region_label: Optional[str] = None) -> proposals.RegionProposalRecord:
    """Accept one proposal.

    Subject Profile -> create a normal editable region (never replacing an
    existing manual region). Separate Answer Paper -> create an attempt-only
    mapping; a target_label is required (the teacher assigns it when uncertain).
    """
    record = _get_owned(conn, teacher_id, proposal_id)
    if record.status in (proposals.STATUS_ACCEPTED, proposals.STATUS_REJECTED):
        raise ProposalError(f"Proposal already {record.status}.")
    x, y, width, height = record.effective_geometry
    if record.workflow_context == WORKFLOW_SUBJECT_PROFILE:
        from app.services.subject_profile_service import add_region
        label = region_label or f"ai_{record.proposed_class}_p{record.page_number}_{proposal_id[-6:]}"
        region = add_region(
            conn, teacher_id, record.profile_id, record.source, label, record.proposed_class,
            record.page_number, x, y, width, height,
            notes=f"Accepted Core AI 2 proposal {proposal_id} (conf {record.confidence}).")
        proposals.set_status(conn, proposal_id, proposals.STATUS_ACCEPTED,
                             accepted_region_id=region.region_id)
        return proposals.get_proposal(conn, proposal_id)

    # Separate Answer Paper attempt mapping.
    from app.services.separate_answer_paper_service import create_mapping
    if not target_label:
        raise ProposalError("Assign a logical target before accepting a separate-paper proposal.")
    mapping = create_mapping(
        conn, teacher_id, record.profile_id, record.answer_file_id, target_label,
        _mapping_type_for_target(conn, teacher_id, record, target_label),
        record.sap_page_id, x, y, width, height)
    proposals.set_status(conn, proposal_id, proposals.STATUS_ACCEPTED,
                         accepted_mapping_id=mapping.mapping_id)
    return proposals.get_proposal(conn, proposal_id)


def bulk_accept(conn, teacher_id: int, proposal_ids: List[str]) -> int:
    """Accept several Subject Profile proposals at once (UI requires an
    explicit confirmation first). Only proposals that already carry an
    unambiguous class/target are accepted; the rest are left for individual
    review."""
    accepted = 0
    for proposal_id in proposal_ids:
        record = _get_owned(conn, teacher_id, proposal_id)
        if record.workflow_context != WORKFLOW_SUBJECT_PROFILE:
            continue
        if record.status in (proposals.STATUS_ACCEPTED, proposals.STATUS_REJECTED):
            continue
        accept_proposal(conn, teacher_id, proposal_id)
        accepted += 1
    return accepted


def list_profile_proposals(conn, teacher_id: int, profile_id: int, source: Optional[str] = None,
                           status: Optional[str] = None) -> List[proposals.RegionProposalRecord]:
    from app.services.subject_profile_service import get_owned_subject_profile
    get_owned_subject_profile(conn, teacher_id, profile_id)
    return proposals.list_proposals_for_profile(conn, profile_id, status=status, source=source)


def list_attempt_proposals(conn, teacher_id: int, profile_id: int, answer_file_id: int,
                           status: Optional[str] = None) -> List[proposals.RegionProposalRecord]:
    from app.services.separate_answer_paper_service import _owned
    _owned(conn, teacher_id, profile_id, answer_file_id)
    return proposals.list_proposals_for_attempt(conn, answer_file_id, status=status)


def _get_owned(conn, teacher_id: int, proposal_id: str) -> proposals.RegionProposalRecord:
    record = proposals.get_proposal(conn, proposal_id)
    if record is None:
        raise ProposalError("Proposal not found.")
    if record.workflow_context == WORKFLOW_SUBJECT_PROFILE:
        from app.services.subject_profile_service import get_owned_subject_profile
        get_owned_subject_profile(conn, teacher_id, record.profile_id)
    else:
        from app.services.separate_answer_paper_service import _owned
        _owned(conn, teacher_id, record.profile_id, record.answer_file_id)
    return record
