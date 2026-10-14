"""Teacher Review & Marking Correction Workspace service (Stage 12G-1A).

The persistence + workflow layer that lets a teacher review one completed
student attempt (a main_marking_answer_files row), correct the extracted
answer text, set final Kertas 1 statuses and Kertas 2 scores, choose
feedback categories, write student-facing feedback and a private note,
adjust overlay markers, override answer-region geometry for this one
attempt, and save the whole review as a Draft or Finalise it (with a
controlled Reopen path). Every action preserves the original machine-
generated result and raw OCR untouched - the teacher's values live in the
separate teacher_* columns / override tables added in Stage 12G-1A - so a
finalised record retains full provenance for later Core AI 1 dataset export
(Stage 12G-2).

Nothing here mutates the shared Subject Profile except the single explicit,
guarded apply_region_override_to_profile action.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models.main_marking_model import get_answer_file_by_id, get_session_by_id
from app.models.subject_profile_model import (
    MARKED_ANSWER_STATUS_FAILED,
    MARKED_ANSWER_STATUS_MARKED,
    MARKED_ANSWER_STATUS_NEEDS_REVIEW,
    REGION_TYPE_ANSWER_BOX,
    REVIEW_ACTION_APPLY_REGION_TO_PROFILE,
    REVIEW_ACTION_FINALISE,
    REVIEW_ACTION_REGION_OVERRIDE_OCR_RERUN,
    REVIEW_ACTION_REGION_OVERRIDE_REMOVED,
    REVIEW_ACTION_REGION_OVERRIDE_SAVED,
    REVIEW_ACTION_REOPEN,
    REVIEW_ACTION_SAVE_DRAFT,
    REVIEW_STATE_DRAFT,
    REVIEW_STATE_FINALISED,
    REVIEW_STATE_NEEDS_REVIEW,
)
import app.models.subject_profile_model as spm
from app.services.subject_profile_service import (
    KERTAS2_WRITING_MAX_SCORE,
    PART3_VALID_QUESTION_NUMBERS,
    _is_part3_answer_box,
    extract_question_number_from_label,
    get_owned_subject_profile,
)


# --- Effective (teacher-corrected) scoring ----------------------------------


def kertas2_part_label(target_label: str, part3_question_no: Optional[str] = None) -> str:
    """Stage 12G-1A: a human-readable Kertas 2 part label for the review
    summary, from the answer_box's own label metadata - "Part 1" (Paper 2
    Question 1), "Part 2" (Question 2), "Part 3 - Question N" (Part 3, with
    the student's selected question number when known). Never the generic
    word "answer"."""
    lbl = target_label.lower()
    if "_q1_" in lbl:
        return "Part 1"
    if "_q2_" in lbl:
        return "Part 2"
    if "part3" in lbl or "_q3_" in lbl:
        return f"Part 3 - Question {part3_question_no}" if part3_question_no else "Part 3"
    qno = extract_question_number_from_label(target_label)
    return f"Part {qno}" if qno else target_label


@dataclass
class ReviewSummary:
    """Attempt-level review summary (Stage 12G-1A requirement 9) computed
    from EFFECTIVE (teacher-corrected where present, else machine) values."""
    kertas1_score: float
    kertas1_max: float
    kertas2_part_scores: Dict[str, Optional[float]]   # label -> teacher score (None if pending)
    kertas2_part_max: Dict[str, float]
    kertas2_part_labels: Dict[str, str]               # label -> friendly "Part N" label
    kertas2_score: float
    kertas2_max: float
    kertas2_total_items: int
    kertas2_scored_items: int
    final_score: Optional[float]        # None while any required K2 mark is pending
    final_max: float
    needs_review_count: int
    pending_teacher_score_count: int
    review_state: str
    finalised: bool
    last_saved_at: Optional[str]
    reviewer_id: Optional[int]
    kertas1_display: str
    kertas2_display: str
    final_display: str
    # Stage 12G-1A Part 3 integrity
    part3_selected_question_no: Optional[str] = None   # effective (teacher>machine) choice
    part3_question_confirmed: bool = True              # False when a Part 3 box exists but has no number
    missing_required_fields: int = 0                   # unresolved K1 + pending K2 + unconfirmed Part 3


def _effective_is_correct(m) -> bool:
    if m.teacher_status is not None:
        return m.teacher_status == spm.TEACHER_STATUS_CORRECT
    return m.status == MARKED_ANSWER_STATUS_MARKED and m.is_correct


def _effective_is_needs_review(m) -> bool:
    if m.teacher_status is not None:
        return m.teacher_status == spm.TEACHER_STATUS_NEEDS_REVIEW
    return m.status == MARKED_ANSWER_STATUS_NEEDS_REVIEW


def _kertas1_representatives(marked_answers: List) -> List:
    """One representative gradeable Kertas 1 marked answer per derived
    question number (a correct one preferred), plus any keyed answer with no
    derivable number. Helper/context/continuation regions and Detection
    Failed rows are excluded - the single source of truth for both the K1
    score and the K1 Needs Review finalisation blocker so they never
    disagree."""
    kertas1_items = [m for m in marked_answers if m.region_type != REGION_TYPE_ANSWER_BOX]
    keyed = [m for m in kertas1_items
             if m.correct_answer_text is not None and m.status != MARKED_ANSWER_STATUS_FAILED]
    grouped: Dict[str, List] = {}
    representatives: List = []
    for m in keyed:
        qno = extract_question_number_from_label(m.target_label)
        if qno is None:
            representatives.append(m)
        else:
            grouped.setdefault(qno, []).append(m)
    for group in grouped.values():
        best = next((g for g in group if _effective_is_correct(g)), group[0])
        representatives.append(best)
    return representatives


def compute_reviewed_score_summary(
    marked_answers: List, *, review_state: str = REVIEW_STATE_DRAFT,
    last_saved_at: Optional[str] = None, reviewer_id: Optional[int] = None,
    part3_question_no: Optional[str] = None,
) -> ReviewSummary:
    """Like compute_score_summary but using each answer's EFFECTIVE status/
    score (teacher value when set, else machine) - the basis for the review
    summary and finalised output. Kertas 1 counts one representative per
    derived question number; a Kertas 2 answer_box contributes to the total
    only once it has a teacher score, so a pending essay never produces a
    misleading final."""
    kertas2_items = [m for m in marked_answers if m.region_type == REGION_TYPE_ANSWER_BOX]

    representatives = _kertas1_representatives(marked_answers)

    kertas1_max = sum(m.max_score for m in representatives)
    kertas1_score = sum(m.max_score for m in representatives if _effective_is_correct(m))
    needs_review_count = sum(1 for m in representatives if _effective_is_needs_review(m))

    part_scores: Dict[str, Optional[float]] = {}
    part_max: Dict[str, float] = {}
    part_labels: Dict[str, str] = {}
    kertas2_score = 0.0
    kertas2_max = 0.0
    scored_k2 = 0
    pending_k2 = 0
    part3_confirmed = True
    for m in kertas2_items:
        part_scores[m.target_label] = m.teacher_score
        part_max[m.target_label] = m.max_score
        # Prefer this box's own effective selected question number (Part 3);
        # fall back to the summary-level part3_question_no for other boxes.
        if _is_part3_answer_box(m.region_type, m.target_label):
            box_qno = m.effective_selected_question_number or part3_question_no
            part_labels[m.target_label] = kertas2_part_label(m.target_label, box_qno)
            if not box_qno:
                part3_confirmed = False
        else:
            part_labels[m.target_label] = kertas2_part_label(m.target_label, part3_question_no)
        if m.teacher_score is not None:
            kertas2_score += m.teacher_score
            kertas2_max += m.max_score
            scored_k2 += 1
        else:
            pending_k2 += 1

    total_k2 = len(kertas2_items)

    # Any unresolved required item makes the overall result Pending, even if
    # the provisional K1/K2 sub-scores are shown: a Kertas 1 answer still
    # Needs Review, a Kertas 2 essay still unscored, or an unconfirmed Part 3
    # question selection all block a final overall score.
    unresolved = needs_review_count > 0 or pending_k2 > 0 or not part3_confirmed
    missing_required = needs_review_count + pending_k2 + (0 if part3_confirmed else 1)

    def _fmt(v: float) -> str:
        return f"{v:g}"

    kertas1_display = f"{_fmt(kertas1_score)}/{_fmt(kertas1_max)}"
    if total_k2 == 0:
        kertas2_display = "N/A"
        provisional_max = kertas1_max
    elif pending_k2 > 0:
        kertas2_display = f"Pending ({scored_k2} of {total_k2} scored)"
        provisional_max = kertas1_max + sum(part_max.values())
    else:
        kertas2_display = f"{_fmt(kertas2_score)}/{_fmt(kertas2_max)}"
        provisional_max = kertas1_max + kertas2_max

    if unresolved:
        final_score: Optional[float] = None
        final_max = provisional_max
        final_display = "Pending"
    elif total_k2 == 0:
        final_score = kertas1_score
        final_max = kertas1_max
        final_display = kertas1_display
    else:
        final_score = kertas1_score + kertas2_score
        final_max = kertas1_max + kertas2_max
        pct = round(final_score / final_max * 100, 1) if final_max > 0 else 0.0
        final_display = f"{_fmt(final_score)}/{_fmt(final_max)} ({pct}%)"

    part3_effective_no = None
    for m in kertas2_items:
        if _is_part3_answer_box(m.region_type, m.target_label):
            part3_effective_no = m.effective_selected_question_number or part3_question_no
            break

    return ReviewSummary(
        kertas1_score=kertas1_score, kertas1_max=kertas1_max,
        kertas2_part_scores=part_scores, kertas2_part_max=part_max, kertas2_part_labels=part_labels,
        kertas2_score=kertas2_score, kertas2_max=kertas2_max,
        kertas2_total_items=total_k2, kertas2_scored_items=scored_k2,
        final_score=final_score, final_max=final_max,
        needs_review_count=needs_review_count, pending_teacher_score_count=pending_k2,
        review_state=review_state, finalised=(review_state == REVIEW_STATE_FINALISED),
        last_saved_at=last_saved_at, reviewer_id=reviewer_id,
        kertas1_display=kertas1_display, kertas2_display=kertas2_display, final_display=final_display,
        part3_selected_question_no=part3_effective_no, part3_question_confirmed=part3_confirmed,
        missing_required_fields=missing_required,
    )


# --- Ownership / lookup helpers ---------------------------------------------


def _owned_answer_file(conn, teacher_id: int, profile_id: int, answer_file_id: int):
    """Validate the profile is owned by teacher_id and the answer file
    belongs to it. Returns the answer file row. Raises ValueError otherwise."""
    get_owned_subject_profile(conn, teacher_id, profile_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Student marking not found.")
    row = conn.execute(
        "SELECT subject_profile_id FROM main_marking_sessions WHERE session_id = ?",
        (answer_file.session_id,),
    ).fetchone()
    if row is None or row[0] != profile_id:
        raise ValueError("Student marking not found for this Subject Profile.")
    return answer_file


def _owned_marked_answer(conn, teacher_id: int, profile_id: int, marked_answer_id: int):
    marked = spm.get_marked_answer_by_id(conn, marked_answer_id)
    if marked is None:
        raise ValueError("Marked answer not found.")
    _owned_answer_file(conn, teacher_id, profile_id, marked.answer_file_id)
    return marked


def _assert_not_finalised(conn, answer_file_id: int) -> None:
    review = spm.get_attempt_review(conn, answer_file_id)
    if review is not None and review.review_state == REVIEW_STATE_FINALISED:
        raise ValueError(
            "This result is finalised. Use 'Reopen for Editing' before making further corrections."
        )


# --- 1. Extracted-content correction ----------------------------------------


def save_corrected_answer_text(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, corrected_text: Optional[str],
) -> "spm.SubjectProfileMarkedAnswer":
    """Persist the teacher's corrected answer text WITHOUT touching the raw
    OCR (raw_ocr_text) or the original detected answer (student_answer_text).
    corrected_text=None or "" clears the correction (reverts to raw)."""
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    value = corrected_text if (corrected_text is not None and corrected_text != "") else None
    return spm.update_marked_answer_review_fields(
        conn, marked_answer_id, corrected_answer_text=value, reviewed_by=teacher_id,
        fields=["corrected_answer_text", "reviewed_by"],
    )


def reset_corrected_answer_text_to_raw(conn, teacher_id: int, profile_id: int, marked_answer_id: int):
    """Clear the teacher correction so the raw OCR / original detected answer
    is used again."""
    return save_corrected_answer_text(conn, teacher_id, profile_id, marked_answer_id, None)


# --- 2. Kertas 1 status correction & Kertas 2 score -------------------------


def set_kertas1_teacher_status(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, teacher_status: str,
) -> "spm.SubjectProfileMarkedAnswer":
    """Record the teacher's final Kertas 1 marking status (Correct / Wrong /
    Needs Review) and recompute the teacher score accordingly (full mark for
    Correct, 0 for Wrong/Needs Review) - the original detected answer and
    automated status are preserved untouched. Rejects answer_box (Kertas 2)
    targets and unknown statuses."""
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    if marked.region_type == REGION_TYPE_ANSWER_BOX:
        raise ValueError("Kertas 2 writing answers are scored with a teacher score, not a Correct/Wrong status.")
    allowed = (spm.TEACHER_STATUS_CORRECT, spm.TEACHER_STATUS_WRONG, spm.TEACHER_STATUS_NEEDS_REVIEW)
    if teacher_status not in allowed:
        raise ValueError(f"Kertas 1 status must be one of {allowed}.")
    teacher_score = marked.max_score if teacher_status == spm.TEACHER_STATUS_CORRECT else 0.0
    updated = spm.update_marked_answer_review_fields(
        conn, marked_answer_id, teacher_status=teacher_status, teacher_score=teacher_score,
        reviewed_by=teacher_id, fields=["teacher_status", "teacher_score", "reviewed_by"],
    )
    # Re-grading is an explicit reconfirmation - clears any extraction-stale flag.
    spm.set_marked_answer_extraction_stale(conn, marked_answer_id, False)
    return updated


def set_kertas2_teacher_score(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, score: float,
) -> "spm.SubjectProfileMarkedAnswer":
    """Record the teacher's final Kertas 2 writing score (0..max_score,
    decimals allowed). Validates the value and marks the answer teacher-
    scored so it counts toward the Kertas 2 / final total (see compute_
    reviewed_score_summary). Rejects non-answer_box targets."""
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    if marked.region_type != REGION_TYPE_ANSWER_BOX:
        raise ValueError("Only Kertas 2 writing answers can be given a teacher score.")
    try:
        score = float(score)
    except (TypeError, ValueError):
        raise ValueError("Score must be a number.")
    if score < 0:
        raise ValueError("Score cannot be below zero.")
    if score > marked.max_score:
        raise ValueError(f"Score cannot exceed the maximum of {marked.max_score:g}.")
    updated = spm.update_marked_answer_review_fields(
        conn, marked_answer_id, teacher_score=score, teacher_status=spm.TEACHER_STATUS_TEACHER_SCORED,
        reviewed_by=teacher_id, fields=["teacher_score", "teacher_status", "reviewed_by"],
    )
    spm.set_marked_answer_extraction_stale(conn, marked_answer_id, False)  # re-scoring reconfirms
    return updated


def set_part3_selected_question_number(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, question_number: Optional[str],
) -> "spm.SubjectProfileMarkedAnswer":
    """Record the teacher's confirmed/corrected Kertas 2 Part 3 question
    choice WITHOUT touching the machine-extracted number (kept for audit and
    dataset provenance). Only valid on the Part 3 answer box; the value must
    be one of the valid Part 3 choices (3/4/5). question_number=None clears
    the teacher correction (reverts to the machine-detected number)."""
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    if not _is_part3_answer_box(marked.region_type, marked.target_label):
        raise ValueError("Only the Kertas 2 Part 3 answer can have a selected question number.")
    value: Optional[str] = None
    if question_number is not None and str(question_number).strip() != "":
        value = "".join(ch for ch in str(question_number) if ch.isdigit())
        if value not in PART3_VALID_QUESTION_NUMBERS:
            raise ValueError(
                f"Part 3 question must be one of: {', '.join(PART3_VALID_QUESTION_NUMBERS)}."
            )
    return spm.update_marked_answer_review_fields(
        conn, marked_answer_id, teacher_selected_question_number=value, reviewed_by=teacher_id,
        fields=["teacher_selected_question_number", "reviewed_by"],
    )


# --- 3/4. Feedback categories, feedback and private comment -----------------


def list_feedback_categories(conn, active_only: bool = True):
    return spm.list_feedback_categories(conn, active_only=active_only)


def set_answer_feedback_categories(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, category_ids: List[int],
) -> None:
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    valid_ids = {c.category_id for c in spm.list_feedback_categories(conn, active_only=False)}
    unknown = [cid for cid in category_ids if cid not in valid_ids]
    if unknown:
        raise ValueError(f"Unknown feedback category id(s): {unknown}.")
    spm.set_answer_feedback_categories(conn, marked_answer_id, category_ids)


def get_answer_feedback_category_ids(conn, marked_answer_id: int) -> List[int]:
    return spm.get_answer_feedback_category_ids(conn, marked_answer_id)


def set_teacher_feedback(
    conn, teacher_id: int, profile_id: int, marked_answer_id: int, *,
    teacher_feedback: Optional[str] = None, private_comment: Optional[str] = None,
) -> "spm.SubjectProfileMarkedAnswer":
    """Save the student-facing final feedback and/or the private (internal)
    teacher comment - stored in separate columns so the private comment is
    never exposed in student-facing output."""
    marked = _owned_marked_answer(conn, teacher_id, profile_id, marked_answer_id)
    _assert_not_finalised(conn, marked.answer_file_id)
    return spm.update_marked_answer_review_fields(
        conn, marked_answer_id, teacher_feedback=teacher_feedback, private_comment=private_comment,
        reviewed_by=teacher_id, fields=["teacher_feedback", "private_comment", "reviewed_by"],
    )


# --- 8. Draft / Finalise / Reopen -------------------------------------------


def _separate_mode_blockers(conn, teacher_id: Optional[int], profile_id: Optional[int],
                            answer_file_id: int) -> List[str]:
    """Stage 12G-1B: separate-answer-paper blockers (unresolved targets,
    parser conflicts, continuation order, stale reviews, Part 3 question).
    Empty for a standard-mode attempt."""
    try:
        from app.services.separate_answer_paper_service import (
            get_separate_mode_blockers, is_separate_mode,
        )
        if not is_separate_mode(conn, answer_file_id):
            return []
        if teacher_id is None or profile_id is None:
            return []
        return get_separate_mode_blockers(conn, teacher_id, profile_id, answer_file_id)
    except Exception:
        return []


def _validate_ready_to_finalise(conn, answer_file_id: int, teacher_id: Optional[int] = None,
                                profile_id: Optional[int] = None) -> List[str]:
    """Return a list of blocking reasons (empty = ready to finalise). Hard
    blocks (each must be resolved before an overall final result is produced):

    - a real gradeable Kertas 1 question whose EFFECTIVE status is still
      Needs Review (an intentionally-blank answer must be confirmed Wrong,
      not left as Needs Review) - helper/context regions never count;
    - a required Kertas 2 writing answer with no valid final teacher score;
    - the Kertas 2 Part 3 question selection not yet confirmed (no machine
      number detected and no teacher confirmation);
    - Stage 12G-1B: for a separate-answer-paper attempt, any unresolved
      required target, parser/mapping conflict or stale review."""
    problems: List[str] = []
    marked = spm.get_marked_answers_for_answer_file(conn, answer_file_id)

    # Kertas 1 Needs Review (real gradeable questions only).
    for rep in _kertas1_representatives(marked):
        if _effective_is_needs_review(rep):
            qno = extract_question_number_from_label(rep.target_label)
            where = f"Question {qno}" if qno else rep.target_label
            problems.append(f"Kertas 1 {where} still Needs Review - confirm Correct or Wrong.")

    # Phase 2C: an extraction that changed (region override / rerun OCR) but
    # whose review has not been reconfirmed blocks finalisation.
    for m in marked:
        if getattr(m, "extraction_review_stale", False):
            paper, label = _paper_and_label(m)
            problems.append(
                f"{paper} {label}: extraction changed (region override / rerun OCR) - reconfirm the review "
                "before finalising.")

    # Kertas 2 missing scores + Part 3 selection confirmation.
    for m in marked:
        if m.region_type != REGION_TYPE_ANSWER_BOX:
            continue
        if m.teacher_score is None:
            label = kertas2_part_label(m.target_label, m.effective_selected_question_number)
            problems.append(f"{label}: Kertas 2 writing answer has no final teacher score yet.")
        if _is_part3_answer_box(m.region_type, m.target_label) and not m.effective_selected_question_number:
            problems.append(
                "Part 3 question selection must be confirmed "
                f"(choose Question {', '.join(PART3_VALID_QUESTION_NUMBERS)})."
            )

    problems.extend(_separate_mode_blockers(conn, teacher_id, profile_id, answer_file_id))
    return problems


def get_finalisation_blockers(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[str]:
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    return _validate_ready_to_finalise(conn, answer_file_id, teacher_id, profile_id)


def save_attempt_review_draft(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, *, note: Optional[str] = None,
) -> "spm.SubjectProfileAttemptReview":
    """Save the attempt review as a Draft (or Needs Review if unresolved
    items remain). Allows an incomplete review; the result is not exposed to
    the student as final. Records an audit entry."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    review = spm.get_or_create_attempt_review(conn, answer_file_id, profile_id)
    if review.review_state == REVIEW_STATE_FINALISED:
        raise ValueError("A finalised result must be reopened before saving a draft.")
    blockers = _validate_ready_to_finalise(conn, answer_file_id, teacher_id, profile_id)
    marked = spm.get_marked_answers_for_answer_file(conn, answer_file_id)
    unresolved = any(_effective_is_needs_review(m) for m in marked) or bool(blockers)
    new_state = REVIEW_STATE_NEEDS_REVIEW if unresolved else REVIEW_STATE_DRAFT
    updated = spm.update_attempt_review_state(conn, answer_file_id, new_state, teacher_id, set_reviewed_at=True)
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_SAVE_DRAFT, from_state=review.review_state,
        to_state=new_state, acted_by=teacher_id, note=note,
    )
    return updated


def finalise_attempt_review(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, *,
    regenerate_outputs: bool = True,
) -> "spm.SubjectProfileAttemptReview":
    """Finalise the reviewed attempt: validate every required Kertas 2 score
    is present, regenerate the final overlays from the teacher-reviewed
    status, optionally regenerate the marked PDF/comments output, record the
    reviewer + finalisation timestamp, and lock the result (silent edits are
    then blocked until Reopen). Raises ValueError listing blockers if not
    ready."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    review = spm.get_or_create_attempt_review(conn, answer_file_id, profile_id)
    blockers = _validate_ready_to_finalise(conn, answer_file_id, teacher_id, profile_id)
    if blockers:
        raise ValueError("Cannot finalise - resolve these first:\n" + "\n".join(blockers))

    regenerate_overlays_from_review(conn, teacher_id, profile_id, answer_file_id)
    if regenerate_outputs:
        # Phase 2B: publish the final outputs ATOMICALLY before locking the
        # state. A failure raises (nothing partial is published, the previous
        # valid final outputs stay intact) and the attempt is NOT finalised -
        # so a finalised attempt always has consistent published outputs.
        try:
            regenerate_reviewed_final_outputs(conn, teacher_id, profile_id, answer_file_id)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Could not publish final reviewed outputs: {exc}")

    updated = spm.update_attempt_review_state(
        conn, answer_file_id, REVIEW_STATE_FINALISED, teacher_id,
        set_reviewed_at=True, set_finalised_at=True,
    )
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_FINALISE, from_state=review.review_state,
        to_state=REVIEW_STATE_FINALISED, acted_by=teacher_id,
    )
    _publish_final_result_snapshot(conn, teacher_id, answer_file_id)
    return updated


def _publish_final_result_snapshot(conn, teacher_id: int, answer_file_id: int) -> None:
    """Snapshot the finalised attempt into main_marking_final_results so the
    teacher's Results page lists it beside every other finalised result.
    Re-finalising replaces the previous snapshot (never duplicates), and
    reopen_attempt_review removes it - the snapshot exists exactly while the
    attempt is finalised."""
    from app.models.main_marking_model import (
        add_final_result_item, create_final_result, delete_final_result_for_answer_file,
    )
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    session = get_session_by_id(conn, answer_file.session_id)
    answers = spm.get_marked_answers_for_answer_file(conn, answer_file_id)
    scoreable = [m for m in answers if m.max_score is not None]
    total = sum(float(m.effective_score or 0.0) for m in scoreable)
    maximum = sum(float(m.max_score or 0.0) for m in scoreable)
    display_name = answer_file.original_filename or f"attempt {answer_file_id}"

    delete_final_result_for_answer_file(conn, answer_file_id)
    result = create_final_result(
        conn,
        session_id=session.session_id,
        answer_file_id=answer_file_id,
        teacher_id=teacher_id,
        paper_type=session.paper_type,
        student_name=answer_file.student_name,
        student_code=answer_file.student_code,
        answer_file_display_name=display_name,
        total_score=total,
        max_score=maximum,
    )
    for m in scoreable:
        add_final_result_item(
            conn,
            result_id=result.result_id,
            marked_answer_id=m.marked_answer_id,
            target_label=m.target_label,
            target_kind=m.target_kind or "region",
            region_type=m.region_type,
            student_answer_text=m.effective_answer_text,
            correct_answer_text=m.correct_answer_text,
            machine_score=m.score,
            teacher_score=m.teacher_score,
            final_score=float(m.effective_score or 0.0),
            max_score=float(m.max_score or 0.0),
            machine_feedback=m.feedback,
            teacher_feedback=m.teacher_feedback,
            final_feedback=m.teacher_feedback or m.feedback,
            reviewed_at=None,
        )


def reopen_attempt_review(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, *, note: Optional[str] = None,
) -> "spm.SubjectProfileAttemptReview":
    """Controlled reopen of a finalised result back to Draft for further
    editing. Preserves the prior finalisation history (the finalise audit
    entry stays) and records who reopened it and when. Raises ValueError if
    the result is not currently finalised."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    review = spm.get_attempt_review(conn, answer_file_id)
    if review is None or review.review_state != REVIEW_STATE_FINALISED:
        raise ValueError("Only a finalised result can be reopened.")
    updated = spm.update_attempt_review_state(
        conn, answer_file_id, REVIEW_STATE_DRAFT, teacher_id, set_finalised_at=False,
    )
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_REOPEN, from_state=REVIEW_STATE_FINALISED,
        to_state=REVIEW_STATE_DRAFT, acted_by=teacher_id, note=note,
    )
    # The Results-page snapshot exists exactly while the attempt is finalised.
    from app.models.main_marking_model import delete_final_result_for_answer_file
    delete_final_result_for_answer_file(conn, answer_file_id)
    return updated


def get_review_audit(conn, teacher_id: int, profile_id: int, answer_file_id: int):
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    return spm.get_review_audit_for_answer_file(conn, answer_file_id)


# --- 9. Attempt review summary ----------------------------------------------


def get_review_summary(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> ReviewSummary:
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    review = spm.get_or_create_attempt_review(conn, answer_file_id, profile_id)
    marked = spm.get_marked_answers_for_answer_file(conn, answer_file_id)
    return compute_reviewed_score_summary(
        marked, review_state=review.review_state,
        last_saved_at=review.updated_at or review.created_at, reviewer_id=review.reviewed_by,
        part3_question_no=_part3_selected_question_no(conn, answer_file_id),
    )


def _part3_selected_question_no(conn, answer_file_id: int) -> Optional[str]:
    """The Part 3 question number the student chose, read from the extracted
    'question_number_field' region (an OCR'd digit) when present - used only
    to label the Part 3 summary row. Returns None (label falls back to plain
    "Part 3") if unavailable."""
    for e in spm.get_extracted_answers_for_answer_file(conn, answer_file_id):
        if "question_number_field" in e.target_label and e.extracted_text:
            digits = "".join(ch for ch in e.extracted_text if ch.isdigit())
            if digits:
                return digits
    return None


# --- 5. Overlay regeneration from teacher-reviewed status -------------------


def regenerate_overlays_from_review(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> None:
    """Rebuild the attempt's overlay markers from each logical target's
    EFFECTIVE (teacher) status, preserving a teacher's manual moves and
    hidden flags where they exist:

    - Correct -> one tick, Wrong -> one cross, Needs Review / Pending
      Teacher Score -> one "?" flag (reuses the percentage kind).
    - Exactly one active status marker per logical answer target (grouped
      by the collision-safe key from create_default_overlays_for_answer_
      file - K1 Q1 and K2 Q1 stay separate; a genuine _cont duplicate
      collapses).
    - A previously teacher-moved marker keeps its position; a hidden marker
      stays hidden.

    Delegates the base generation to the existing default-overlay builder
    (which already computes anchor positions, one-marker-per-logical-target
    grouping, and the auto symbol from the effective status), then re-applies
    the teacher's per-target edits captured before regeneration.

    Phase 2B: edits are keyed by the overlay's logical target_label (robust
    across regeneration), so a teacher-adjusted position and a hidden flag
    survive a status-driven regeneration while the Auto symbol updates. There
    is NO visual-only symbol override to preserve - the symbol always follows
    the effective status (see the consistency fix)."""
    from app.services.subject_profile_service import create_default_overlays_for_answer_file

    # Stage 12G-1B: a separate-answer-paper attempt's markers are anchored on
    # the mapped areas / parsed answer lines of the ANSWER PAPER, never on
    # Subject Profile question-paper regions, so it uses its own builder (which
    # preserves teacher moves and hidden flags in the same way).
    from app.services import separate_answer_paper_service as separate_service
    if separate_service.is_separate_mode(conn, answer_file_id):
        separate_service.sync_separate_mode_overlays(conn, teacher_id, profile_id, answer_file_id)
        return

    prior = spm.get_overlays_for_answer_file(conn, answer_file_id)
    # Remember each target's position/hidden/font-size edits by its logical
    # target_label (feedback notes are keyed by their own "<label>__feedback").
    edits = {}
    for o in prior:
        if o.target_label is None:
            continue
        if o.is_teacher_adjusted or o.is_hidden or o.font_size is not None:
            edits[o.target_label] = dict(
                x=o.x, y=o.y, is_teacher_adjusted=o.is_teacher_adjusted, is_hidden=o.is_hidden,
                font_size=o.font_size,
            )

    create_default_overlays_for_answer_file(conn, teacher_id, profile_id, answer_file_id)

    for o in spm.get_overlays_for_answer_file(conn, answer_file_id):
        edit = edits.get(o.target_label) if o.target_label is not None else None
        if edit is None:
            continue
        if edit["is_teacher_adjusted"]:
            spm.move_overlay_and_mark_adjusted(conn, o.overlay_id, edit["x"], edit["y"])
        if edit["is_hidden"]:
            spm.set_overlay_hidden(conn, o.overlay_id, True)
        if edit.get("font_size") is not None:
            spm.set_overlay_font_size(conn, o.overlay_id, edit["font_size"])


# --- Phase 2B: attempt-specific overlay editing -----------------------------

# The overlay editor only controls Auto (symbol follows effective status) and
# Hidden. There is deliberately NO independent visual symbol override - a
# status marker can never contradict the effective status (consistency fix).
OVERLAY_SYMBOL_MODE_AUTO = "auto"
OVERLAY_SYMBOL_MODE_HIDDEN = "hidden"
OVERLAY_SYMBOL_MODES = (OVERLAY_SYMBOL_MODE_AUTO, OVERLAY_SYMBOL_MODE_HIDDEN)

# Choosing one of these in the overlay editor is a request to change the
# Kertas 1 teacher STATUS (Correct/Wrong/Needs Review), applied through the
# review service with a confirmation - after which the Auto symbol follows.
# Kertas 1 only: a Kertas 2 essay's marker follows its teacher score.
OVERLAY_STATUS_SYMBOL_TICK = "tick"
OVERLAY_STATUS_SYMBOL_CROSS = "cross"
OVERLAY_STATUS_SYMBOL_QUESTION = "question_mark"
OVERLAY_SYMBOL_TO_STATUS = {
    OVERLAY_STATUS_SYMBOL_TICK: spm.TEACHER_STATUS_CORRECT,
    OVERLAY_STATUS_SYMBOL_CROSS: spm.TEACHER_STATUS_WRONG,
    OVERLAY_STATUS_SYMBOL_QUESTION: spm.TEACHER_STATUS_NEEDS_REVIEW,
}
_STATUS_TO_SYMBOL_LABEL = {
    spm.TEACHER_STATUS_CORRECT: "Correct (Tick)",
    spm.TEACHER_STATUS_WRONG: "Wrong (X)",
    spm.TEACHER_STATUS_NEEDS_REVIEW: "Needs Review (Question Mark)",
}


@dataclass
class OverlayEditRow:
    """One editable overlay row (one per real logical answer target) for the
    Phase 2B Overlay Marks workspace."""
    overlay_id: int
    target_label: str
    paper: str                 # "Kertas 1" / "Kertas 2"
    answer_label: str          # friendly Part/question label
    page_number: int
    status_display: str        # effective teacher-reviewed status
    symbol_display: str        # current symbol (always Auto-from-status, or Hidden)
    symbol_mode: str           # 'auto' or 'hidden'
    x: float
    y: float
    hidden: bool
    teacher_adjusted: bool
    is_kertas1: bool           # whether Tick/X/? status-change options apply


def _effective_status_display(m) -> str:
    if m.region_type == REGION_TYPE_ANSWER_BOX:
        return "Teacher Scored" if m.teacher_score is not None else "Pending Teacher Score"
    if _effective_is_correct(m):
        return "Correct"
    if _effective_is_needs_review(m):
        return "Needs Review"
    return "Wrong"


def _overlay_symbol_mode(overlay) -> str:
    return OVERLAY_SYMBOL_MODE_HIDDEN if overlay.is_hidden else OVERLAY_SYMBOL_MODE_AUTO


def _overlay_symbol_display(overlay) -> str:
    if overlay.is_hidden:
        return "Hidden"
    if overlay.kind == spm.OVERLAY_KIND_TICK:
        return "Tick (Auto)"
    if overlay.kind == spm.OVERLAY_KIND_CROSS:
        return "X (Auto)"
    if (overlay.text_value or "") == "?":
        return "Question Mark (Auto)"
    return (overlay.text_value or "?") + " (Auto)"


def _paper_and_label(m) -> Tuple[str, str]:
    if m.region_type == REGION_TYPE_ANSWER_BOX:
        return "Kertas 2", kertas2_part_label(m.target_label, m.effective_selected_question_number)
    qno = extract_question_number_from_label(m.target_label)
    return "Kertas 1", (f"Question {qno}" if qno else m.target_label)


def list_overlay_edit_rows(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[OverlayEditRow]:
    """One editable row per real logical answer target. The headline summary
    overlay (target_label is NULL) and any overlay whose target is no longer a
    marked answer are excluded, so helper/context regions, options legends and
    already-collapsed `_cont` duplicates never appear (they never became a
    target-linked overlay in the first place)."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    rows: List[OverlayEditRow] = []
    for o in spm.get_overlays_for_answer_file(conn, answer_file_id):
        if o.target_label is None:
            continue
        m = marked_by_label.get(o.target_label)
        if m is None:
            continue
        paper, label = _paper_and_label(m)
        rows.append(OverlayEditRow(
            overlay_id=o.overlay_id, target_label=o.target_label, paper=paper, answer_label=label,
            page_number=o.page_number, status_display=_effective_status_display(m),
            symbol_display=_overlay_symbol_display(o), symbol_mode=_overlay_symbol_mode(o),
            x=o.x, y=o.y, hidden=o.is_hidden, teacher_adjusted=o.is_teacher_adjusted,
            is_kertas1=(m.region_type != REGION_TYPE_ANSWER_BOX),
        ))
    return rows


def _owned_editable_overlay(conn, teacher_id: int, profile_id: int, overlay_id: int):
    overlay = spm.get_overlay_by_id(conn, overlay_id)
    if overlay is None:
        raise ValueError("Overlay not found.")
    _owned_answer_file(conn, teacher_id, profile_id, overlay.answer_file_id)
    _assert_not_finalised(conn, overlay.answer_file_id)
    return overlay


def set_overlay_symbol(conn, teacher_id: int, profile_id: int, overlay_id: int, symbol_mode: str):
    """Set one overlay's symbol mode - only Auto (symbol follows the effective
    status) or Hidden. Any legacy visual override is cleared to Auto here, so
    the marker can never disagree with the status. To change the actual final
    symbol, change the teacher status (see apply_overlay_status_symbol)."""
    _owned_editable_overlay(conn, teacher_id, profile_id, overlay_id)
    if symbol_mode not in OVERLAY_SYMBOL_MODES:
        raise ValueError(f"Symbol mode must be one of {OVERLAY_SYMBOL_MODES}.")
    if symbol_mode == OVERLAY_SYMBOL_MODE_HIDDEN:
        spm.set_overlay_hidden(conn, overlay_id, True)
        return spm.get_overlay_by_id(conn, overlay_id)
    spm.set_overlay_hidden(conn, overlay_id, False)
    spm.set_overlay_symbol_override(conn, overlay_id, None)  # migrate any legacy override -> Auto
    return spm.get_overlay_by_id(conn, overlay_id)


def apply_overlay_status_symbol(conn, teacher_id: int, profile_id: int, overlay_id: int, symbol: str):
    """Change a Kertas 1 answer's FINAL teacher status from the overlay editor
    (Tick->Correct, X->Wrong, Question Mark->Needs Review). This updates the
    teacher status + recomputed score through the review service, then
    regenerates the overlays so the Auto symbol follows - so the drawn marker,
    the comments and the summary always agree. Rejected for a Kertas 2 essay
    (its marker follows the teacher score - change the score in Teacher
    Review)."""
    overlay = _owned_editable_overlay(conn, teacher_id, profile_id, overlay_id)
    if symbol not in OVERLAY_SYMBOL_TO_STATUS:
        raise ValueError(f"Status symbol must be one of {tuple(OVERLAY_SYMBOL_TO_STATUS)}.")
    marked = spm.get_marked_answers_for_answer_file(conn, overlay.answer_file_id)
    m = next((mm for mm in marked if mm.target_label == overlay.target_label), None)
    if m is None:
        raise ValueError("Overlay is not linked to a marked answer.")
    if m.region_type == REGION_TYPE_ANSWER_BOX:
        raise ValueError("A Kertas 2 essay marker follows its teacher score - change the score in Teacher Review.")
    set_kertas1_teacher_status(conn, teacher_id, profile_id, m.marked_answer_id, OVERLAY_SYMBOL_TO_STATUS[symbol])
    regenerate_overlays_from_review(conn, teacher_id, profile_id, overlay.answer_file_id)
    return OVERLAY_SYMBOL_TO_STATUS[symbol]


def status_symbol_change_label(symbol: str) -> str:
    """Human label for the status a Tick/X/Question Mark choice would set."""
    return _STATUS_TO_SYMBOL_LABEL.get(OVERLAY_SYMBOL_TO_STATUS.get(symbol, ""), symbol)


def set_overlay_visibility(conn, teacher_id: int, profile_id: int, overlay_id: int, hidden: bool):
    _owned_editable_overlay(conn, teacher_id, profile_id, overlay_id)
    spm.set_overlay_hidden(conn, overlay_id, bool(hidden))
    return spm.get_overlay_by_id(conn, overlay_id)


def move_overlay_position(conn, teacher_id: int, profile_id: int, overlay_id: int, x: float, y: float):
    """Store an attempt-specific position (page-relative 0..1) and flag the
    overlay teacher-adjusted. Rejects non-numeric or out-of-page coordinates
    rather than silently clamping (Phase 2B requirement 6)."""
    _owned_editable_overlay(conn, teacher_id, profile_id, overlay_id)
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        raise ValueError("Overlay position must be numeric.")
    if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
        raise ValueError("Overlay position must be inside the page (X and Y between 0.0 and 1.0).")
    spm.move_overlay_and_mark_adjusted(conn, overlay_id, x, y)
    return spm.get_overlay_by_id(conn, overlay_id)


def restore_overlay_position(conn, teacher_id: int, profile_id: int, overlay_id: int):
    """Revert a teacher-moved overlay to its generated (original) position.
    In this attempt-overlay model the generated anchor IS the original
    position, so 'Restore Original Position' and 'Restore Auto-Generated
    Position' are the same operation."""
    _owned_editable_overlay(conn, teacher_id, profile_id, overlay_id)
    spm.restore_overlay_default_position(conn, overlay_id)
    return spm.get_overlay_by_id(conn, overlay_id)


def _expected_status_marker(m) -> Tuple[str, Optional[str]]:
    from app.services.subject_profile_service import _overlay_marker_for_marked_answer
    kind, text, _w = _overlay_marker_for_marked_answer(m)
    return kind, (text or None)


def overlay_symbols_would_change(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> bool:
    """True if Refresh-Overlays-from-Review would change any visible symbol
    (used to require confirmation). Compares each visible target's current
    drawn symbol against the symbol its current effective status generates."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    for o in spm.get_overlays_for_answer_file(conn, answer_file_id):
        if o.target_label is None or o.is_hidden:
            continue
        m = marked_by_label.get(o.target_label)
        if m is None:
            continue
        exp_kind, exp_text = _expected_status_marker(m)
        if exp_kind != o.kind or exp_text != (o.text_value or None):
            return True
    return False


def verify_overlays_consistent_with_status(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[str]:
    """Publication safeguard: return a list of human-readable mismatches where
    a VISIBLE status overlay's drawn symbol disagrees with the answer's
    effective teacher-reviewed status. Empty list = safe to publish. Hidden
    overlays are exempt (no visible marker, status unchanged)."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    marked_by_label = {m.target_label: m for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)}
    problems: List[str] = []
    for o in spm.get_overlays_for_answer_file(conn, answer_file_id):
        if o.target_label is None or o.is_hidden:
            continue
        m = marked_by_label.get(o.target_label)
        if m is None:
            continue
        exp_kind, exp_text = _expected_status_marker(m)
        if exp_kind != o.kind or exp_text != (o.text_value or None):
            paper, label = _paper_and_label(m)
            problems.append(
                f"{paper} {label}: overlay symbol does not match the {_effective_status_display(m)} status "
                "- refresh overlays from the teacher review first.")
    return problems


# --- 6/7. Attempt-specific region overrides & guarded profile update --------


def _find_profile_region(conn, teacher_id: int, profile_id: int, label: str):
    from app.services.subject_profile_service import list_regions
    for r in list_regions(conn, teacher_id, profile_id):
        if r.label == label:
            return r
    return None


def _marked_answer_for_label(conn, answer_file_id: int, label: str):
    for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        if m.target_label == label:
            return m
    return None


def _validate_region_geometry(x: float, y: float, width: float, height: float) -> Tuple[float, float, float, float]:
    """Phase 2C: reject a non-numeric or out-of-page region rectangle rather
    than silently clamping (page-relative 0..1; positive size; fully inside)."""
    try:
        x, y, width, height = float(x), float(y), float(width), float(height)
    except (TypeError, ValueError):
        raise ValueError("Region geometry must be numeric.")
    if width <= 0 or height <= 0:
        raise ValueError("Region width and height must be greater than zero.")
    if x < 0 or y < 0 or x + width > 1.0 or y + height > 1.0:
        raise ValueError("Region must lie inside the page (0.0-1.0, and x+width / y+height <= 1.0).")
    return x, y, width, height


def _render_crop_png_and_checksum(pdf_path: str, region_like) -> Tuple[Optional[bytes], Optional[str]]:
    """Render one region's raw crop from the student PDF and return
    (png_bytes, sha256). None/None if it can't be rendered - never raises."""
    import hashlib
    try:
        import cv2
        import pymupdf
        from app.services.region_crop_ocr_service import _render_raw_region_crop
    except Exception:
        return None, None
    if not pdf_path or not Path(pdf_path).is_file():
        return None, None
    document = None
    try:
        document = pymupdf.open(pdf_path)
        image = _render_raw_region_crop(document, region_like)
    except Exception:
        return None, None
    finally:
        if document is not None:
            document.close()
    if image is None:
        return None, None
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        return None, None
    png = bytes(buf)
    return png, hashlib.sha256(png).hexdigest()


class _OverrideRegion:
    """Region-like adapter over an AttemptRegionOverride so it can be fed to
    the crop/OCR renderers (region_id/label/region_type/page_number/x/y/
    width/height/shape_type/polygon_points_json/rotation_angle)."""

    def __init__(self, override):
        self.region_id = -(override.override_id)  # negative so it never collides with a real region id
        self.label = override.label
        self.region_type = override.region_type
        self.page_number = override.page_number
        self.x = override.x
        self.y = override.y
        self.width = override.width
        self.height = override.height
        self.shape_type = override.shape_type
        self.polygon_points_json = override.polygon_points_json
        self.rotation_angle = override.rotation_angle


class _GeometryRegion:
    """Minimal region-like for rendering an arbitrary geometry (e.g. the
    ORIGINAL profile geometry snapshot) as a crop."""

    def __init__(self, region_id, label, region_type, page_number, x, y, width, height,
                 shape_type="rectangle", polygon_points_json=None, rotation_angle=0.0):
        self.region_id = region_id
        self.label = label
        self.region_type = region_type
        self.page_number = page_number
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.shape_type = shape_type
        self.polygon_points_json = polygon_points_json
        self.rotation_angle = rotation_angle


def save_region_override(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str, *,
    x: float, y: float, width: float, height: float, shape_type: str = "rectangle",
    polygon_points_json: Optional[str] = None, rotation_angle: float = 0.0,
    correction_reason: Optional[str] = None,
) -> "spm.AttemptRegionOverride":
    """Store an attempt-specific geometry correction for one answer region,
    entirely SEPARATE from the shared Subject Profile region (never modified
    here). Phase 2C: validates the geometry, snapshots the original profile
    geometry + crop checksum, records the new crop checksum, and flags the
    target's teacher review stale (its effective extraction just changed)."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    x, y, width, height = _validate_region_geometry(x, y, width, height)
    profile_region = _find_profile_region(conn, teacher_id, profile_id, label)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    pdf_path = answer_file.file_path if answer_file else None
    page_number = profile_region.page_number if profile_region else 1
    region_type = profile_region.region_type if profile_region else None

    original_crop_checksum = None
    if profile_region is not None:
        _png, original_crop_checksum = _render_crop_png_and_checksum(pdf_path, profile_region)
    override_region = _GeometryRegion(-1, label, region_type, page_number, x, y, width, height,
                                      shape_type, polygon_points_json, rotation_angle)
    _png2, crop_checksum = _render_crop_png_and_checksum(pdf_path, override_region)

    previous = spm.get_region_override(conn, answer_file_id, label)
    override = spm.upsert_region_override(
        conn, answer_file_id, label,
        profile_region_id=profile_region.region_id if profile_region else None,
        source=profile_region.source if profile_region else "question_paper",
        region_type=region_type, page_number=page_number,
        x=x, y=y, width=width, height=height, shape_type=shape_type,
        polygon_points_json=polygon_points_json, rotation_angle=rotation_angle,
        correction_reason=correction_reason, corrected_by=teacher_id,
        original_x=profile_region.x if profile_region else None,
        original_y=profile_region.y if profile_region else None,
        original_width=profile_region.width if profile_region else None,
        original_height=profile_region.height if profile_region else None,
        crop_checksum=crop_checksum, original_crop_checksum=original_crop_checksum,
    )
    # Phase 2C audit: every save (create/move/resize) records previous->new
    # geometry so the correction history is reconstructible.
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_REGION_OVERRIDE_SAVED, acted_by=teacher_id,
        note=json.dumps({
            "label": label, "profile_region_id": override.profile_region_id,
            "previous": ({"x": previous.x, "y": previous.y, "width": previous.width, "height": previous.height}
                         if previous else None),
            "new": {"x": x, "y": y, "width": width, "height": height},
            "original": ({"x": override.original_x, "y": override.original_y,
                          "width": override.original_width, "height": override.original_height}
                         if override.original_x is not None else None),
            "crop_checksum": crop_checksum, "original_crop_checksum": original_crop_checksum,
        }))
    _mark_target_extraction_stale(conn, answer_file_id, label)
    return override


def restore_region_override(conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str) -> None:
    """Remove the attempt-specific override so the shared Subject Profile
    region geometry is used again for this attempt (Restore Original Region /
    Remove Attempt Override). The target's review is flagged stale because its
    effective extraction reverts to the original.

    Phase 2C audit invariant: the ACTIVE override row is deleted, but a
    sanitized snapshot (geometry, checksums, rerun-OCR lineage flags, prior
    stale state - never raw OCR text) is written to the review audit FIRST, so
    evidence that the correction and rerun occurred is never erased."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    existing = spm.get_region_override(conn, answer_file_id, label)
    if existing is not None:
        m = _marked_answer_for_label(conn, answer_file_id, label)
        spm.add_review_audit(
            conn, answer_file_id, REVIEW_ACTION_REGION_OVERRIDE_REMOVED, acted_by=teacher_id,
            note=json.dumps({
                "label": label, "profile_region_id": existing.profile_region_id,
                "original": ({"x": existing.original_x, "y": existing.original_y,
                              "width": existing.original_width, "height": existing.original_height}
                             if existing.original_x is not None else None),
                "removed_effective": {"x": existing.x, "y": existing.y,
                                      "width": existing.width, "height": existing.height},
                "original_crop_checksum": existing.original_crop_checksum,
                "override_crop_checksum": existing.crop_checksum,
                "rerun_ocr_existed": existing.rerun_ocr_text is not None,
                "rerun_ocr_at": existing.rerun_ocr_at,
                "rerun_ocr_method": ("PaddleOCR crop" if existing.rerun_ocr_text is not None else None),
                "previous_stale_state": bool(getattr(m, "extraction_review_stale", False)) if m else None,
            }))
        spm.delete_region_override(conn, existing.override_id)
        _mark_target_extraction_stale(conn, answer_file_id, label)


# 'Restore Original Region' and 'Remove Attempt Override' are the same action.
remove_region_override = restore_region_override


def _mark_target_extraction_stale(conn, answer_file_id: int, label: str) -> None:
    m = _marked_answer_for_label(conn, answer_file_id, label)
    if m is not None:
        spm.set_marked_answer_extraction_stale(conn, m.marked_answer_id, True)


def rerun_ocr_for_region_override(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str, *, engine=None,
) -> Optional[str]:
    """Re-run OCR for an attempt-specific region override's geometry against
    THIS student's PDF. The result is stored as the override's RERUN OCR -
    kept SEPARATE from the original OCR (on the marked answer) and from any
    teacher-corrected text. A geometry-keyed empty cache is used so the old
    crop's cached OCR is never reused. Flags the target stale when the rerun
    text differs from the original. Returns the rerun text (or None)."""
    from app.services.region_crop_ocr_service import LazyOCREngine, run_region_crop_ocr
    from app.services.subject_profile_service import get_default_engine

    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    override = spm.get_region_override(conn, answer_file_id, label)
    if override is None:
        raise ValueError("No region override exists for this target on this attempt.")
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None or not answer_file.file_path or not Path(answer_file.file_path).is_file():
        return None

    region = _OverrideRegion(override)
    lazy = LazyOCREngine(engine=engine, resolver=get_default_engine)
    results = run_region_crop_ocr([region], answer_file.file_path, profile_id, lazy, {})  # empty cache = fresh OCR
    text = results[0].extracted_text if results else None
    confidence = results[0].confidence if results else None
    _png, crop_checksum = _render_crop_png_and_checksum(answer_file.file_path, region)
    spm.set_region_override_rerun_ocr(conn, override.override_id, text, confidence, crop_checksum)

    m = _marked_answer_for_label(conn, answer_file_id, label)
    changed = False
    if m is not None:
        original = m.raw_ocr_text if m.raw_ocr_text is not None else m.student_answer_text
        changed = (text or "") != (original or "")
        if changed:
            spm.set_marked_answer_extraction_stale(conn, m.marked_answer_id, True)
    # Phase 2C audit: the rerun event (sanitized - method/confidence/changed
    # flag/checksum, never the raw OCR text).
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_REGION_OVERRIDE_OCR_RERUN, acted_by=teacher_id,
        note=json.dumps({
            "label": label, "method": "PaddleOCR crop", "confidence": confidence,
            "changed_from_original": changed, "crop_checksum": crop_checksum,
            "geometry": {"x": override.x, "y": override.y, "width": override.width, "height": override.height},
        }))
    return text


@dataclass
class RegionEditRow:
    """One row of the Phase 2C Region Review panel (one per real answer target
    that has a shared-profile region)."""
    target_label: str
    paper: str
    answer_label: str
    page_number: int
    region_type: Optional[str]
    has_override: bool
    original_geometry: Dict[str, float]
    effective_geometry: Dict[str, float]
    stale: bool


def _geom(x, y, w, h) -> Dict[str, float]:
    return {"x": x, "y": y, "width": w, "height": h}


def get_region_geometry(conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str) -> Dict:
    """Return {original, effective, has_override} page-relative geometries for
    a target. Original is the shared-profile geometry snapshot; effective is
    the attempt override when present, else the profile geometry."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    profile_region = _find_profile_region(conn, teacher_id, profile_id, label)
    override = spm.get_region_override(conn, answer_file_id, label)
    if profile_region is not None:
        original = _geom(profile_region.x, profile_region.y, profile_region.width, profile_region.height)
    elif override is not None and override.original_x is not None:
        original = _geom(override.original_x, override.original_y, override.original_width, override.original_height)
    else:
        original = None
    if override is not None:
        effective = _geom(override.x, override.y, override.width, override.height)
    else:
        effective = original
    return {"original": original, "effective": effective, "has_override": override is not None}


def list_region_edit_rows(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[RegionEditRow]:
    """One row per real answer target that has a shared-profile region. Helper/
    context regions (never a marked answer) are excluded, matching the overlay
    panel's logical-target set."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    from app.services.subject_profile_service import list_regions
    regions_by_label = {r.label: r for r in list_regions(conn, teacher_id, profile_id)}
    rows: List[RegionEditRow] = []
    for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id):
        region = regions_by_label.get(m.target_label)
        if region is None:
            continue
        override = spm.get_region_override(conn, answer_file_id, m.target_label)
        paper, label = _paper_and_label(m)
        original = _geom(region.x, region.y, region.width, region.height)
        effective = _geom(override.x, override.y, override.width, override.height) if override else original
        rows.append(RegionEditRow(
            target_label=m.target_label, paper=paper, answer_label=label, page_number=region.page_number,
            region_type=region.region_type, has_override=override is not None,
            original_geometry=original, effective_geometry=effective,
            stale=bool(getattr(m, "extraction_review_stale", False)),
        ))
    return rows


def get_region_override_lineage(conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str) -> Dict:
    """Full OCR + geometry lineage for one target: original OCR, rerun OCR and
    teacher-corrected text kept separate; original vs effective geometry; crop
    checksums; and the stale flag - the basis for the review UI and evidence."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    m = _marked_answer_for_label(conn, answer_file_id, label)
    override = spm.get_region_override(conn, answer_file_id, label)
    geom = get_region_geometry(conn, teacher_id, profile_id, answer_file_id, label)
    paper, answer_label = _paper_and_label(m) if m is not None else ("", label)
    return {
        "label": label, "paper": paper, "answer_label": answer_label,
        "original_ocr": (m.raw_ocr_text if (m and m.raw_ocr_text is not None) else (m.student_answer_text if m else None)),
        "rerun_ocr": override.rerun_ocr_text if override else None,
        "teacher_corrected": m.corrected_answer_text if m else None,
        "effective_text": m.effective_answer_text if m else None,
        "stale": bool(getattr(m, "extraction_review_stale", False)) if m else False,
        "has_override": override is not None,
        "original_geometry": geom["original"], "effective_geometry": geom["effective"],
        "original_crop_checksum": override.original_crop_checksum if override else None,
        "crop_checksum": override.crop_checksum if override else None,
    }


def render_region_crop_to_file(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str, *,
    use_override: bool, out_path,
) -> Optional[str]:
    """Render the ORIGINAL (profile geometry) or EFFECTIVE (override geometry)
    crop for a target to out_path as PNG. Returns the crop's sha256, or None if
    it can't be rendered. Used by the crop-preview UI and the evidence pack."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    pdf_path = answer_file.file_path if answer_file else None
    profile_region = _find_profile_region(conn, teacher_id, profile_id, label)
    override = spm.get_region_override(conn, answer_file_id, label)
    if use_override and override is not None:
        region = _OverrideRegion(override)
    elif not use_override and override is not None and override.original_x is not None:
        region = _GeometryRegion(-2, label, override.region_type, override.page_number,
                                 override.original_x, override.original_y,
                                 override.original_width, override.original_height)
    else:
        region = profile_region
    if region is None:
        return None
    png, checksum = _render_crop_png_and_checksum(pdf_path, region)
    if png is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(png)
    return checksum


def render_region_crop_for_geometry(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str, *,
    x: float, y: float, width: float, height: float, out_path,
) -> Optional[str]:
    """Render a crop for an ARBITRARY (proposed) geometry WITHOUT persisting an
    override - the live preview while the teacher draws/moves/resizes. Returns
    the crop sha256, or None if it can't be rendered. Rejects invalid geometry."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    x, y, width, height = _validate_region_geometry(x, y, width, height)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    pdf_path = answer_file.file_path if answer_file else None
    profile_region = _find_profile_region(conn, teacher_id, profile_id, label)
    page_number = profile_region.page_number if profile_region else 1
    region_type = profile_region.region_type if profile_region else None
    region = _GeometryRegion(-3, label, region_type, page_number, x, y, width, height)
    png, checksum = _render_crop_png_and_checksum(pdf_path, region)
    if png is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(png)
    return checksum


def list_stale_extraction_targets(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> List[str]:
    """Target labels whose teacher review is stale after an extraction change."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    return [m.target_label for m in spm.get_marked_answers_for_answer_file(conn, answer_file_id)
            if getattr(m, "extraction_review_stale", False)]


def reconfirm_extraction_change(conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str) -> None:
    """Teacher explicitly reconfirms the review for a target after its
    extraction changed - clears the stale flag (unblocking finalisation)."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    _assert_not_finalised(conn, answer_file_id)
    m = _marked_answer_for_label(conn, answer_file_id, label)
    if m is None:
        raise ValueError("No marked answer for this target.")
    spm.set_marked_answer_extraction_stale(conn, m.marked_answer_id, False)


def apply_region_override_to_profile(
    conn, teacher_id: int, profile_id: int, answer_file_id: int, label: str, *, confirm: bool,
) -> None:
    """GUARDED action (Stage 12G-1A requirement 7): apply an attempt-specific
    region correction back to the SHARED Subject Profile region, affecting
    future attempts. Never runs automatically - the caller must pass
    confirm=True after showing the teacher a confirmation dialog with the old
    vs new geometry. Records who applied it and when in the audit trail.
    Requires profile ownership (enforced by _owned_answer_file/list_regions)."""
    if not confirm:
        raise ValueError("Applying a correction to the shared Subject Profile requires explicit confirmation.")
    from app.services.subject_profile_service import move_region

    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    override = spm.get_region_override(conn, answer_file_id, label)
    if override is None:
        raise ValueError("No region override exists for this target on this attempt.")
    profile_region = _find_profile_region(conn, teacher_id, profile_id, label)
    if profile_region is None:
        raise ValueError("The matching shared Subject Profile region no longer exists.")
    old_geom = {"x": profile_region.x, "y": profile_region.y, "width": profile_region.width, "height": profile_region.height}
    new_geom = {"x": override.x, "y": override.y, "width": override.width, "height": override.height}
    move_region(
        conn, teacher_id, profile_id, profile_region.region_id,
        override.x, override.y, override.width, override.height,
        polygon_points_json=override.polygon_points_json,
    )
    spm.add_review_audit(
        conn, answer_file_id, REVIEW_ACTION_APPLY_REGION_TO_PROFILE, acted_by=teacher_id,
        note=json.dumps({"label": label, "region_id": profile_region.region_id, "old": old_geom, "new": new_geom}),
    )


# --- 10. Output regeneration (student-facing) -------------------------------


def build_student_facing_comments(marked_answers: List, *, summary: "ReviewSummary" = None,
                                  finalised: Optional[bool] = None) -> str:
    """Student-facing comments text using the teacher-reviewed (effective)
    answer/status/score and the teacher's student-facing feedback - NEVER the
    raw OCR, the original automated result, extraction confidence/method/
    timestamp, the private teacher comment, internal audit data, inactive
    category metadata or database IDs (Phase 2B requirement 11). Friendly
    Part/question labels are used, and when a finalised summary is supplied
    the final overall result is shown as a header."""
    lines: List[str] = []
    show_final = finalised if finalised is not None else (summary is not None and summary.finalised)
    if summary is not None and show_final:
        lines.append("FINAL RESULT (teacher-reviewed)")
        lines.append(f"Kertas 1: {summary.kertas1_display}")
        lines.append(f"Kertas 2: {summary.kertas2_display}")
        lines.append(f"Overall: {summary.final_display}")
        lines.append("")
    for m in marked_answers:
        _paper, label = _paper_and_label(m)
        if m.region_type == REGION_TYPE_ANSWER_BOX:
            score = m.teacher_score
            score_text = f"{score:g}/{m.max_score:g}" if score is not None else f"Pending/{m.max_score:g}"
            status_text = "Teacher Scored" if score is not None else "Pending Teacher Score"
        else:
            if _effective_is_correct(m):
                status_text, score_text = "Correct", f"{m.max_score:g}/{m.max_score:g}"
            elif _effective_is_needs_review(m):
                status_text, score_text = "Needs Review", f"0/{m.max_score:g}"
            else:
                status_text, score_text = "Wrong", f"0/{m.max_score:g}"
        feedback = m.teacher_feedback or ""
        answer = m.effective_answer_text or "(none)"
        line = f"{label}: [{status_text}] {score_text} | Answer: {answer}"
        if feedback:
            line += f" | {feedback}"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


MARKED_PDF_NAME = "marked.pdf"
COMMENTS_NAME = "comments.txt"
MANIFEST_NAME = "manifest.json"


def _attempt_result_folder(profile_id: int, answer_file) -> Path:
    from app.utils.file_storage import get_subject_profile_results_folder
    safe = "".join(c if c.isalnum() else "_" for c in Path(answer_file.original_filename or "student").stem)
    return Path(get_subject_profile_results_folder(profile_id)) / f"{safe}_result"


def _write_reviewed_outputs(conn, teacher_id, profile_id, answer_file_id, dest_dir: Path, *, finalised: bool):
    """Build marked.pdf + comments.txt for this attempt into dest_dir using the
    teacher-reviewed overlay state (hidden markers skipped, symbol always from
    effective status, adjusted positions honoured). `finalised` controls the
    FINAL RESULT header - the state flip happens after this call during
    finalise, so it is passed explicitly. Raises on any failure."""
    from app.services.subject_profile_service import _draw_overlays_on_pdf

    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    if not answer_file.file_path or not Path(answer_file.file_path).exists():
        raise ValueError("Original student PDF is missing - cannot regenerate reviewed outputs.")
    marked = spm.get_marked_answers_for_answer_file(conn, answer_file_id)
    overlays = spm.get_overlays_for_answer_file(conn, answer_file_id)
    summary = get_review_summary(conn, teacher_id, profile_id, answer_file_id)

    dest_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = dest_dir / MARKED_PDF_NAME
    comments_path = dest_dir / COMMENTS_NAME

    # Stage 12G-1B: a separate-answer-paper attempt renders the SEPARATE PAPER
    # as the background with markers from its attempt mappings, and uses the
    # separate-mode comments builder. Standard mode is unchanged.
    try:
        from app.services.separate_answer_paper_service import (
            build_separate_student_comments, is_separate_mode, render_separate_marked_pdf,
        )
        separate = is_separate_mode(conn, answer_file_id)
    except Exception:
        separate = False
    if separate:
        render_separate_marked_pdf(conn, teacher_id, profile_id, answer_file_id, pdf_path)
        comments_path.write_text(
            build_separate_student_comments(conn, teacher_id, profile_id, answer_file_id,
                                            finalised=bool(finalised)), encoding="utf-8")
        if not pdf_path.exists() or not comments_path.exists():
            raise ValueError("Reviewed output generation was incomplete.")
        return pdf_path, comments_path

    _draw_overlays_on_pdf(answer_file.file_path, overlays, pdf_path)
    comments_path.write_text(
        build_student_facing_comments(marked, summary=summary, finalised=finalised), encoding="utf-8")
    if not pdf_path.exists() or not comments_path.exists():
        raise ValueError("Reviewed output generation was incomplete.")
    return pdf_path, comments_path


def _validate_output_version(version_dir: Path, answer_file_id: int, version_id: str) -> None:
    """Validate a freshly-generated output version before it may be published:
    both files exist and are readable (PDF openable), and the manifest belongs
    to this attempt + version. Raises ValueError otherwise."""
    import pymupdf
    pdf_path = version_dir / MARKED_PDF_NAME
    comments_path = version_dir / COMMENTS_NAME
    manifest_path = version_dir / MANIFEST_NAME
    if not (pdf_path.exists() and comments_path.exists() and manifest_path.exists()):
        raise ValueError("Output version is incomplete (missing PDF, comments or manifest).")
    document = pymupdf.open(str(pdf_path))
    try:
        if document.page_count < 1:
            raise ValueError("Generated marked PDF has no pages.")
    finally:
        document.close()
    comments_path.read_text(encoding="utf-8")  # must be readable
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("answer_file_id") != answer_file_id or manifest.get("version_id") != version_id:
        raise ValueError("Output version manifest does not match this attempt/version.")


def _prune_incomplete_versions(versions_root: Path, keep_version: Optional[str]) -> None:
    """Best-effort removal of leftover version folders missing any of their
    three files (truly incomplete, e.g. left by an interrupted run), so failed
    temporary folders never accumulate. A complete version folder is valid
    history and is kept; the active version is never removed."""
    import shutil
    if not versions_root.exists():
        return
    for child in versions_root.iterdir():
        if not child.is_dir() or child.name == keep_version:
            continue
        complete = ((child / MARKED_PDF_NAME).exists() and (child / COMMENTS_NAME).exists()
                    and (child / MANIFEST_NAME).exists())
        if not complete:
            shutil.rmtree(child, ignore_errors=True)


def regenerate_reviewed_final_outputs(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> dict:
    """Publish the FINAL reviewed outputs as ONE atomic version.

    1. Safeguard: block if any visible status overlay disagrees with its
       effective status (lists the affected questions).
    2. Generate marked.pdf + comments.txt + manifest.json into a NEW
       result_versions/<version_id>/ folder - the current active output is
       never touched during generation.
    3. Validate both files (PDF openable, comments readable, manifest matches).
    4. Publish by switching the active PDF path, comments path, version and
       timestamp TOGETHER in one SQLite UPDATE (the atomic pair boundary).
    On any failure the previous active output is unchanged, the incomplete
    version folder is removed, and no path points to an incomplete version."""
    import shutil

    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")

    mismatches = verify_overlays_consistent_with_status(conn, teacher_id, profile_id, answer_file_id)
    if mismatches:
        raise ValueError("Cannot publish - overlay symbols disagree with the final status:\n" + "\n".join(mismatches))

    folder = _attempt_result_folder(profile_id, answer_file)
    versions_root = folder / "result_versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    _prune_incomplete_versions(versions_root, keep_version=None)

    import uuid
    version_id = uuid.uuid4().hex
    version_dir = versions_root / version_id
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        pdf_path, comments_path = _write_reviewed_outputs(
            conn, teacher_id, profile_id, answer_file_id, version_dir, finalised=True)
        (version_dir / MANIFEST_NAME).write_text(json.dumps({
            "answer_file_id": answer_file_id, "version_id": version_id, "generated_at": generated_at,
            "marked_pdf": MARKED_PDF_NAME, "comments": COMMENTS_NAME,
        }, indent=2), encoding="utf-8")
        _validate_output_version(version_dir, answer_file_id, version_id)
        # Atomic publication: switch all active references together (one UPDATE).
        spm.set_attempt_review_final_outputs(
            conn, answer_file_id, marked_pdf_path=str(pdf_path), comments_path=str(comments_path),
            generated_at=generated_at, version=version_id)
    except Exception as exc:
        # Remove the incomplete version; the previous active output is untouched.
        shutil.rmtree(version_dir, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"Could not publish reviewed outputs: {exc}")

    return {"folder": str(version_dir), "marked_pdf": str(pdf_path), "comments": str(comments_path),
            "version_id": version_id}


def generate_draft_preview_outputs(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> dict:
    """Build a TEACHER-ONLY draft preview of the reviewed outputs (in a
    draft_preview/ subfolder). Never published as the student's final result
    and never recorded on the review row - used to let a teacher inspect the
    marked PDF / comments before finalising."""
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    answer_file = get_answer_file_by_id(conn, answer_file_id)
    if answer_file is None:
        raise ValueError("Answer file not found.")
    preview_dir = _attempt_result_folder(profile_id, answer_file) / "draft_preview"
    if preview_dir.exists():
        import shutil
        shutil.rmtree(preview_dir, ignore_errors=True)
    pdf_path, comments_path = _write_reviewed_outputs(
        conn, teacher_id, profile_id, answer_file_id, preview_dir, finalised=False)
    original = comments_path.read_text(encoding="utf-8")
    comments_path.write_text("DRAFT PREVIEW - NOT the student's final result.\n\n" + original, encoding="utf-8")
    return {"folder": str(preview_dir), "marked_pdf": str(pdf_path), "comments": str(comments_path), "is_draft": True}


def get_download_output_folder(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> dict:
    """Resolve which output a download should serve. A finalised attempt with a
    published final version serves that version's folder (marked.pdf +
    comments.txt from the SAME version); every other attempt (draft, reopened,
    or a legacy attempt never finalised through Phase 2B) falls back to the
    historical on-the-fly export so older results keep working. Returns
    {folder, marked_pdf, comments, version, is_final}."""
    from app.services.subject_profile_service import export_student_result
    _owned_answer_file(conn, teacher_id, profile_id, answer_file_id)
    review = spm.get_attempt_review(conn, answer_file_id)
    if (review is not None and review.review_state == REVIEW_STATE_FINALISED
            and review.final_marked_pdf_path and Path(review.final_marked_pdf_path).exists()
            and review.final_comments_path and Path(review.final_comments_path).exists()):
        return {"folder": str(Path(review.final_marked_pdf_path).parent),
                "marked_pdf": review.final_marked_pdf_path, "comments": review.final_comments_path,
                "version": review.final_output_version, "is_final": True}
    folder = export_student_result(conn, teacher_id, profile_id, answer_file_id)
    return {"folder": folder, "is_final": False}


def regenerate_final_outputs(conn, teacher_id: int, profile_id: int, answer_file_id: int) -> str:
    """Backwards-compatible wrapper: publish the reviewed final outputs and
    return the folder path (used by finalise_attempt_review)."""
    return regenerate_reviewed_final_outputs(conn, teacher_id, profile_id, answer_file_id)["folder"]
