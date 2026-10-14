"""Immutable candidate deltas from explicitly teacher-reviewed outcomes."""

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from app.models.core_ai_backend_contracts import BackendError
from app.models.core_ai_backend_review_types import CandidateCaptureResult
from app.services.core_ai_backend_paths import safe_component


REVIEW_CAPTURE_SCHEMA = "ai-review-candidates-v1"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _candidate_checksum(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class ReviewCaptureService:
    def __init__(self, paths):
        self.paths = paths
        self.paths.ensure_layout()

    def _publish(self, family, version, candidates, evidence, excluded, statistics, source_models):
        version = safe_component(version, "candidate version")
        family = safe_component(family, "model family")
        family_root = self.paths.candidates_root / family
        family_root.mkdir(parents=True, exist_ok=True)
        target = family_root / version
        if target.exists():
            raise BackendError("candidate_version_exists", "Candidate version already exists and is immutable.")
        temporary = Path(tempfile.mkdtemp(prefix=f".{version}_", dir=family_root))
        try:
            (temporary / "candidates.jsonl").write_text(
                "".join(_canonical(row) + "\n" for row in candidates), encoding="utf-8"
            )
            (temporary / "review_evidence.jsonl").write_text(
                "".join(_canonical(row) + "\n" for row in evidence), encoding="utf-8"
            )
            _write_json(temporary / "exclusions.json", excluded)
            _write_json(temporary / "statistics.json", statistics)
            manifest = {
                "schema_version": REVIEW_CAPTURE_SCHEMA,
                "family": family,
                "candidate_version": version,
                "created_at": _now(),
                "candidate_count": len(candidates),
                "review_evidence_count": len(evidence),
                "source_model_versions": sorted(source_models),
                "human_review_required": True,
                "frozen": False,
                "training_started": False,
                "model_activated": False,
            }
            _write_json(temporary / "manifest.json", manifest)
            checksums = {name: _sha256(temporary / name) for name in (
                "candidates.jsonl", "review_evidence.jsonl", "exclusions.json", "statistics.json", "manifest.json"
            )}
            checksums["manifest_checksum"] = checksums["manifest.json"]
            _write_json(temporary / "checksums.json", checksums)
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return CandidateCaptureResult(family, version, str(target), checksums["manifest_checksum"], statistics)

    def capture_core_ai1(self, candidate_version, records):
        candidates, exclusions, seen = [], [], set()
        counts = Counter()
        source_models = set()
        for record in records:
            row = asdict(record)
            reason = None
            duplicate_key = (record.input_checksum, record.attempt_group_id)
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
            source_models.add(record.model_version)
            changed_score = record.original_draft_score != record.teacher_final_score
            changed_category = record.original_draft_category != record.teacher_final_category
            candidate = {
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
                "teacher_final_student_feedback": record.teacher_final_student_feedback if record.feedback_capture_permitted else None,
                "paper": record.paper,
                "part": record.part,
                "question_context": record.question_context,
                "marking_scheme_checksum": record.marking_scheme_checksum,
                "attempt_group_id": record.attempt_group_id,
                "student_group_id": record.student_group_id,
                "profile_group_id": record.profile_group_id,
                "finalized_at": record.finalized_at,
            }
            candidate["candidate_checksum"] = _candidate_checksum(candidate)
            candidates.append(candidate)
            counts["changed_score" if changed_score else "score_unchanged"] += 1
            counts["changed_category" if changed_category else "category_unchanged"] += 1
            counts["accepted_edited" if changed_score or changed_category else "accepted_unchanged"] += 1
        statistics = dict(counts)
        statistics.update({"input_records": len(records), "candidate_count": len(candidates), "duplicate_candidates": counts["duplicate"]})
        return self._publish("core_ai1", candidate_version, candidates, [], exclusions, statistics, source_models)

    def capture_core_ai2(self, candidate_version, proposals):
        candidates, evidence, exclusions, seen = [], [], [], set()
        counts = Counter()
        source_models = set()
        for proposal in proposals:
            source_models.add(proposal.model_version)
            key = (proposal.page_checksum, proposal.proposal_id)
            status = proposal.review_status.lower()
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
                "final_teacher_geometry": list(proposal.final_teacher_geometry) if proposal.final_teacher_geometry is not None else None,
                "review_status": status,
                "source_model_version": proposal.model_version,
                "source_model_checksum": proposal.model_checksum,
                "page_checksum": proposal.page_checksum,
                "profile_group_id": proposal.profile_group_id,
                "attempt_group_id": proposal.attempt_group_id,
                "reason_code": proposal.reason_code,
            }
            if status in ("deferred", "unresolved"):
                exclusions.append({"proposal_id": proposal.proposal_id, "reason": status})
                counts[status] += 1
                continue
            if status == "rejected":
                base["training_label_eligible"] = False
                base["candidate_checksum"] = _candidate_checksum(base)
                evidence.append(base)
                counts["rejected"] += 1
                continue
            if status not in ("accepted", "edited") or not proposal.final_teacher_class or proposal.final_teacher_geometry is None:
                exclusions.append({"proposal_id": proposal.proposal_id, "reason": "invalid_review_label"})
                counts["invalid_review_label"] += 1
                continue
            base["training_label_eligible"] = True
            base["candidate_checksum"] = _candidate_checksum(base)
            candidates.append(base)
            counts[status] += 1
        statistics = dict(counts)
        statistics.update({"input_records": len(proposals), "candidate_count": len(candidates), "review_evidence_count": len(evidence), "duplicate_candidates": counts["duplicate"]})
        return self._publish("core_ai2", candidate_version, candidates, evidence, exclusions, statistics, source_models)
