"""Stage 12G-5 - Claude-owned finalized Kertas 2 record adapter for Core AI 1
dataset export.

The Codex Core AI 1 dataset export is a DIRECT adapter call
(`export_core_ai1_dataset(adapter, dataset_root, version, CoreAI1DatasetConfig)`)
and requires a Claude-owned adapter implementing `list_finalized_k2_examples()`.
This module provides exactly that: it reads FINALISED, teacher-reviewed Kertas 2
answers and yields one dict per whitelisted example.

Only the whitelisted finalized fields the backend accepts are emitted (the
backend's SAFE_FIELDS) plus `is_finalized`/`paper_type` used for filtering.
Never emitted: private teacher comments, raw OCR lineage, audit prose, prompts.
Grouping ids (attempt/student/profile) are provided so the backend can build a
leakage-safe split.
"""
import hashlib
from typing import Iterable, List, Optional

import app.models.subject_profile_model as spm

# The exact whitelist the Codex backend consumes (kept in sync with
# core_ai1_dataset_service.SAFE_FIELDS); documented here as our contract.
SAFE_FIELDS = (
    "paper_identifier", "part_identifier", "logical_target", "selected_part3_question",
    "question_text", "marking_scheme_text", "maximum_score", "effective_student_answer",
    "teacher_final_score", "teacher_final_feedback_category", "teacher_final_student_feedback",
    "subject_profile_version", "attempt_group_id", "student_group_id", "profile_group_id",
    "source_checksum", "finalized_at", "source_mode",
)

_ANSWER_BOX = "answer_box"


def _part_identifier(target_label: Optional[str]) -> str:
    label = (target_label or "").lower()
    if "part1" in label or "_q1_" in label:
        return "part1"
    if "part2" in label or "_q2_" in label:
        return "part2"
    if "part3" in label or "_q3_" in label:
        return "part3"
    return "part_unknown"


class FinalizedK2RecordAdapter:
    """Yields whitelisted finalized Kertas 2 examples for Core AI 1 export.

    Constructed with a live connection and (optionally) an owning teacher_id to
    scope to that teacher's finalised attempts; admin/global export passes
    teacher_id=None to span all finalised attempts.
    """

    def __init__(self, conn, teacher_id: Optional[int] = None) -> None:
        self._conn = conn
        self._teacher_id = teacher_id

    def _finalised_answer_files(self) -> List[dict]:
        clauses = ["r.review_state = 'finalised'"]
        params: list = []
        if self._teacher_id is not None:
            clauses.append("p.teacher_id = ?")
            params.append(self._teacher_id)
        rows = self._conn.execute(
            "SELECT r.answer_file_id, r.profile_id, r.finalised_at, p.teacher_id, p.updated_at AS profile_version, "
            "s.session_id, af.attempt_mode "
            "FROM subject_profile_attempt_reviews r "
            "JOIN main_marking_answer_files af ON af.answer_file_id = r.answer_file_id "
            "JOIN main_marking_sessions s ON s.session_id = af.session_id "
            "LEFT JOIN subject_profiles p ON p.profile_id = r.profile_id "
            f"WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def _category_key(self, answer_file_id: int, marked_answer_id: int) -> Optional[str]:
        try:
            ids = spm.get_answer_feedback_category_ids(self._conn, marked_answer_id)
        except Exception:
            return None
        if not ids:
            return None
        categories = {c.category_id: c.category_key for c in spm.list_feedback_categories(self._conn)}
        return categories.get(ids[0])

    def _scheme_text(self, profile_id: int, target_label: str) -> Optional[str]:
        try:
            entries = {e.target_label: e for e in
                       spm.get_answer_key_entries_for_profile(self._conn, profile_id)}
        except Exception:
            entries = {}
        entry = entries.get(target_label)
        if entry is None:
            return None
        # The answer scheme text for a K2 writing answer is the rubric/criterion
        # recorded as the correct answer / scheme reference.
        return getattr(entry, "correct_answer", None) or getattr(entry, "scheme_text", None)

    def list_finalized_k2_examples(self) -> Iterable[dict]:
        for attempt in self._finalised_answer_files():
            answer_file_id = attempt["answer_file_id"]
            profile_id = attempt["profile_id"]
            marked = spm.get_marked_answers_for_answer_file(self._conn, answer_file_id)
            for m in marked:
                if m.region_type != _ANSWER_BOX:
                    continue  # Kertas 2 writing answers only; K1 is rule-based
                effective_answer = m.effective_answer_text
                category_key = self._category_key(answer_file_id, m.marked_answer_id)
                source_basis = f"{answer_file_id}:{m.target_label}:{m.effective_score}:{effective_answer}"
                yield {
                    "is_finalized": True,
                    "paper_type": "kertas2",
                    "paper_identifier": "Kertas 2",
                    "part_identifier": _part_identifier(m.target_label),
                    "logical_target": m.target_label,
                    "selected_part3_question": m.effective_selected_question_number,
                    "question_text": None,
                    "marking_scheme_text": self._scheme_text(profile_id, m.target_label),
                    "maximum_score": m.max_score,
                    "effective_student_answer": effective_answer,
                    "teacher_final_score": m.effective_score,
                    "teacher_final_feedback_category": category_key,
                    "teacher_final_student_feedback": m.teacher_feedback,
                    "subject_profile_version": str(attempt.get("profile_version") or ""),
                    "attempt_group_id": f"attempt_{answer_file_id}",
                    "student_group_id": f"student_{attempt.get('session_id')}",
                    "profile_group_id": f"profile_{profile_id}",
                    "source_checksum": hashlib.sha256(source_basis.encode("utf-8")).hexdigest(),
                    "finalized_at": attempt.get("finalised_at"),
                    "source_mode": attempt.get("attempt_mode") or "standard",
                }
