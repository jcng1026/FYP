"""Subject Profile model (Stage 11V) - raw SQL/dataclasses for the
teacher-facing Marking tab redesign.

A Subject Profile is a self-contained unit (question paper PDF + answer
scheme PDF + their OCR/extracted content + teacher-defined regions/groups/
answer-key entries), deliberately independent from answer_templates/
template_regions/marking_setups (see app/database/schema.py's Stage 11V
comment block for why). Student answer PDF handling still reuses
main_marking_sessions/main_marking_answer_files/preprocessing/OCR - only
the tables in this module are new.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

STATUS_DRAFT = "draft"
STATUS_READY = "ready"
# Stage 11W: observable "busy" states, shown in the Existing Subject Profiles
# table and used to block deletion while work is in flight (no CHECK
# constraint on subject_profiles.status, so no migration needed for these).
STATUS_PROCESSING = "processing"
STATUS_FAILED = "failed"

# Stage 12E-fix: generic, paper-agnostic region vocabulary - the teacher-
# facing workflow no longer separates Kertas 1/Kertas 2 region types (that
# distinction never mattered for what a region actually IS: a bubble area
# is a bubble area whether it appears on a Kertas 1 or Kertas 2 page). The
# five old paper-specific labels below were merged into their generic
# equivalent - see SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP in
# app/database/schema.py for the exact old->new mapping applied to
# existing Subject Profiles:
#   k1_bubble_area         -> bubble_area
#   k1_letter_box          -> letter_box
#   k1_underline_answer    -> underline_answer
#   k2_question_number_box -> question_number_box (merged - already existed)
#   k2_answer_box          -> answer_box
REGION_TYPE_QUESTION_AREA = "question_area"
REGION_TYPE_QUESTION_NUMBER_BOX = "question_number_box"
REGION_TYPE_ANSWER_REGION = "answer_region"
REGION_TYPE_ANSWER_BOX = "answer_box"
REGION_TYPE_BUBBLE_AREA = "bubble_area"
REGION_TYPE_LETTER_BOX = "letter_box"
REGION_TYPE_UNDERLINE_ANSWER = "underline_answer"
REGION_TYPE_STUDENT_INFO_AREA = "student_info_area"
REGION_TYPE_EXTRA_PAGE_LABEL = "extra_page_label"
REGION_TYPE_IGNORE = "ignore_region"

ALL_SUBJECT_PROFILE_REGION_TYPES = (
    REGION_TYPE_QUESTION_AREA,
    REGION_TYPE_QUESTION_NUMBER_BOX,
    REGION_TYPE_ANSWER_REGION,
    REGION_TYPE_ANSWER_BOX,
    REGION_TYPE_BUBBLE_AREA,
    REGION_TYPE_LETTER_BOX,
    REGION_TYPE_UNDERLINE_ANSWER,
    REGION_TYPE_STUDENT_INFO_AREA,
    REGION_TYPE_EXTRA_PAGE_LABEL,
    REGION_TYPE_IGNORE,
)

# Friendly display labels for the region type dropdown/table - internal enum
# values are still what gets stored in the database (Stage 11W). No Kertas
# 1/Kertas 2 wording (Stage 12E-fix) - these are generic question/answer
# region types usable on any paper.
REGION_TYPE_FRIENDLY_LABELS = {
    REGION_TYPE_QUESTION_AREA: "Question Area",
    REGION_TYPE_QUESTION_NUMBER_BOX: "Question Number Box",
    REGION_TYPE_ANSWER_REGION: "Answer Region",
    REGION_TYPE_ANSWER_BOX: "Answer Box",
    REGION_TYPE_BUBBLE_AREA: "Bubble Area",
    REGION_TYPE_LETTER_BOX: "Letter Box",
    REGION_TYPE_UNDERLINE_ANSWER: "Underline Answer",
    REGION_TYPE_STUDENT_INFO_AREA: "Student Info Area",
    REGION_TYPE_EXTRA_PAGE_LABEL: "Extra Page Label",
    REGION_TYPE_IGNORE: "Ignore Region",
}


def region_type_friendly_label(region_type: str) -> str:
    """Return region_type's friendly display label, or the raw value itself
    if it isn't recognised (defensive fallback, never raises)."""
    return REGION_TYPE_FRIENDLY_LABELS.get(region_type, region_type)


# Region types that identify where a question-number tick/X anchor lives.
# A single-element tuple since Stage 12E-fix merged the old k2-specific
# variant into this same generic type - kept as a tuple (not a lone
# constant) so existing "in QUESTION_NUMBER_REGION_TYPES" membership checks
# elsewhere never needed to change.
QUESTION_NUMBER_REGION_TYPES = (REGION_TYPE_QUESTION_NUMBER_BOX,)
# Region types that are never marked/extracted as an answer.
IGNORED_REGION_TYPES = (REGION_TYPE_IGNORE,)
# Structural/reference region types that are never gradable answer content -
# question-number boxes exist only to anchor the tick/X overlay,
# student-info/extra-page regions hold metadata, not answers, and
# question_area holds the question text itself, not a student/scheme answer.
# Excluded from extraction/marking targets (and therefore from tick/X
# overlay creation, which is driven off marked answers), but still fully
# definable/editable/groupable regions.
NON_ANSWER_REGION_TYPES = IGNORED_REGION_TYPES + QUESTION_NUMBER_REGION_TYPES + (
    REGION_TYPE_STUDENT_INFO_AREA, REGION_TYPE_EXTRA_PAGE_LABEL, REGION_TYPE_QUESTION_AREA,
)

# Marking Output Cleanup Fix: MCQ/fill-in region types that, by this
# codebase's own real labeling convention, are ALWAYS uniquely tied to one
# specific question via a "_qN_" token - a region of one of these types
# with no derivable question number (see extract_question_number_from_
# label below) is therefore a legend/options-list/selector helper (e.g.
# qp_p9_part4_options_A_H, qp_p16_question_number_field), never a real
# per-question answer target. Deliberately excludes answer_box: a Kertas 2
# essay is a real, gradeable target regardless of whether its label has a
# "_qN_" token (Part 3's own essay legitimately doesn't).
REGION_TYPE_LEGEND_OR_SELECTOR_TYPES = (REGION_TYPE_BUBBLE_AREA, REGION_TYPE_LETTER_BOX, REGION_TYPE_UNDERLINE_ANSWER)

_QUESTION_NUMBER_LABEL_PATTERN = re.compile(r"_q(\d+)_")


def extract_question_number_from_label(label: str) -> Optional[str]:
    """Marking Fix Follow-up: derive a target's question number straight
    from its region label - real Subject Profile labels follow a
    "..._q<N>_<suffix>" convention (qp_p2_q1_choices -> Question 1,
    qp_p8_q27_blank -> Question 27, qp_p11_q40_answer_line -> Question 40),
    so a teacher/warning dialog never needs to know or guess the raw
    internal label to identify which question is missing a key (requirement
    3: "Correct mapping between region labels and question numbers").
    Returns None for a label with no derivable question number - a helper/
    legend/metadata region (e.g. part4_options_A_H or question_number_field)
    that is never independently "required" for answer-key validation."""
    match = _QUESTION_NUMBER_LABEL_PATTERN.search(label)
    return match.group(1) if match else None


SOURCE_QUESTION_PAPER = "question_paper"
SOURCE_ANSWER_SCHEME = "answer_scheme"

SHAPE_TYPE_RECTANGLE = "rectangle"
SHAPE_TYPE_POLYGON = "polygon"

TARGET_KIND_REGION = "region"
TARGET_KIND_GROUP = "group"

EXTRACTED_ANSWER_STATUS_EXTRACTED = "extracted"
EXTRACTED_ANSWER_STATUS_NEEDS_REVIEW = "needs_review"
EXTRACTED_ANSWER_STATUS_NO_TEXT = "no_text"
EXTRACTED_ANSWER_STATUS_FAILED = "failed"

MARKED_ANSWER_STATUS_MARKED = "marked"
MARKED_ANSWER_STATUS_NEEDS_REVIEW = "needs_review"
MARKED_ANSWER_STATUS_FAILED = "failed"
# Data Management/Marking Fix: a target with no matching answer key entry
# used to fall through to MARKED_ANSWER_STATUS_MARKED with is_correct=False
# (silently scored 0.0, indistinguishable from a genuinely wrong answer) -
# this status makes "the answer key itself is missing" a distinct,
# clearly-reported outcome instead.
MARKED_ANSWER_STATUS_MISSING_ANSWER_KEY = "missing_answer_key"
# Marking Fix Follow-up: a Kertas 2 (Paper 2) writing answer_box target -
# distinct from the generic MARKED_ANSWER_STATUS_NEEDS_REVIEW (uncertain
# OCR detection) so comments/score math can tell "genuinely unclear
# handwriting" apart from "this is a normal essay awaiting a human mark" -
# see run_subject_profile_marking's REGION_TYPE_ANSWER_BOX branch and
# compute_score_summary.
MARKED_ANSWER_STATUS_PENDING_TEACHER_SCORE = "pending_teacher_score"
# Set once a teacher enters a mark (out of KERTAS2_WRITING_MAX_SCORE) for a
# writing answer via set_teacher_score_for_marked_answer - only THEN does
# it count toward the Kertas 2 / final total.
MARKED_ANSWER_STATUS_TEACHER_SCORED = "teacher_scored"

OVERLAY_KIND_TICK = "tick"
OVERLAY_KIND_CROSS = "cross"
OVERLAY_KIND_PERCENTAGE = "percentage"
# A wrapped red feedback note (the AI/teacher natural-language feedback for a
# Kertas 2 writing answer), draggable/resizable like any other overlay.
OVERLAY_KIND_FEEDBACK = "feedback"

# Stage 12G-1A Phase 2B: explicit teacher symbol-override values (stored in
# teacher_symbol_override, separate from the generated `kind`). "question_mark"
# renders via the percentage kind's "?" text; None + use_auto_symbol=1 = Auto.
OVERLAY_SYMBOL_TICK = "tick"
OVERLAY_SYMBOL_CROSS = "cross"
OVERLAY_SYMBOL_QUESTION = "question_mark"
OVERLAY_SYMBOL_OVERRIDES = (OVERLAY_SYMBOL_TICK, OVERLAY_SYMBOL_CROSS, OVERLAY_SYMBOL_QUESTION)

# --- Stage 12G-1A: teacher review workflow --------------------------------------
# ATTEMPT-level review workflow position (subject_profile_attempt_reviews.
# review_state) - deliberately SEPARATE from a per-answer marking status, so
# an attempt can be a "Draft" review whose individual answers are already
# "Correct"/"Wrong" (the "do not overload one field" rule).
REVIEW_STATE_DRAFT = "draft"
REVIEW_STATE_NEEDS_REVIEW = "needs_review"
REVIEW_STATE_FINALISED = "finalised"

# A teacher's FINAL per-answer marking status (subject_profile_marked_answers.
# teacher_status) - explicit correct/wrong so a teacher-confirmed grade is
# never confused with the machine "marked" label. Falls back to the machine
# status when the teacher hasn't set one (see effective_status).
TEACHER_STATUS_CORRECT = "correct"
TEACHER_STATUS_WRONG = "wrong"
TEACHER_STATUS_NEEDS_REVIEW = "needs_review"
TEACHER_STATUS_PENDING_TEACHER_SCORE = "pending_teacher_score"
TEACHER_STATUS_TEACHER_SCORED = "teacher_scored"

# Review audit action names (subject_profile_review_audit.action).
REVIEW_ACTION_SAVE_DRAFT = "save_draft"
REVIEW_ACTION_FINALISE = "finalise"
REVIEW_ACTION_REOPEN = "reopen"
REVIEW_ACTION_APPLY_REGION_TO_PROFILE = "apply_region_to_profile"
# Stage 12G-1A Phase 2C: region-override lifecycle audit (sanitized snapshots
# in the note JSON - geometry/checksums/lineage flags, never raw OCR text).
REVIEW_ACTION_REGION_OVERRIDE_SAVED = "region_override_saved"
REVIEW_ACTION_REGION_OVERRIDE_OCR_RERUN = "region_override_ocr_rerun"
REVIEW_ACTION_REGION_OVERRIDE_REMOVED = "region_override_removed"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SubjectProfile:
    profile_id: int
    teacher_id: int
    profile_name: str
    question_paper_path: Optional[str]
    answer_scheme_path: Optional[str]
    question_paper_ocr_json: Optional[str]
    answer_scheme_ocr_json: Optional[str]
    question_paper_extracted_json: Optional[str]
    answer_scheme_extracted_json: Optional[str]
    status: str
    created_at: str
    updated_at: Optional[str]
    is_active: int = 1


@dataclass
class SubjectProfileRegion:
    region_id: int
    profile_id: int
    source: str
    label: str
    region_type: str
    page_number: int
    x: float
    y: float
    width: float
    height: float
    shape_type: str
    polygon_points_json: Optional[str]
    rotation_angle: float
    order_index: int
    notes: Optional[str]
    created_at: str


@dataclass
class SubjectProfileRegionGroup:
    group_id: int
    profile_id: int
    label: str
    region_type: str
    notes: Optional[str]
    created_at: str


@dataclass
class SubjectProfileRegionGroupMember:
    group_id: int
    region_id: int
    member_order: int


@dataclass
class SubjectProfileAnswerKeyEntry:
    entry_id: int
    profile_id: int
    target_label: str
    target_kind: str
    question_no: Optional[str]
    correct_answer: Optional[str]
    max_mark: float
    comment: Optional[str]
    created_at: str
    updated_at: Optional[str]


@dataclass
class SubjectProfileExtractedAnswer:
    extracted_answer_id: int
    answer_file_id: int
    target_label: str
    target_kind: str
    region_type: Optional[str]
    extracted_text: Optional[str]
    confidence: Optional[float]
    status: str
    message: Optional[str]
    created_at: str


@dataclass
class SubjectProfileMarkedAnswer:
    marked_answer_id: int
    answer_file_id: int
    target_label: str
    target_kind: str
    region_type: Optional[str]
    # --- Original machine-generated marking (NEVER overwritten by a teacher
    # correction - Stage 12G-1A). student_answer_text is the original detected
    # answer; score/status/is_correct/feedback are the automated result.
    student_answer_text: Optional[str]
    correct_answer_text: Optional[str]
    score: Optional[float]
    max_score: float
    is_correct: bool
    status: str
    feedback: Optional[str]
    created_at: str
    # --- Stage 12G-1A raw-extraction provenance + teacher-review fields
    # (defaulted so every existing constructor/caller keeps working). Kept
    # SEPARATE from the machine columns above; the review service reads the
    # teacher_* value when present and falls back to the original otherwise.
    raw_ocr_text: Optional[str] = None
    extraction_confidence: Optional[float] = None
    extraction_method: Optional[str] = None
    extraction_timestamp: Optional[str] = None
    corrected_answer_text: Optional[str] = None
    teacher_score: Optional[float] = None
    teacher_status: Optional[str] = None
    teacher_feedback: Optional[str] = None
    private_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Stage 12G-1A Part 3: the student's selected Part 3 question number
    # (machine-extracted vs teacher-corrected). Only ever set on the Kertas 2
    # Part 3 answer_box; None everywhere else.
    extracted_selected_question_number: Optional[str] = None
    teacher_selected_question_number: Optional[str] = None
    extraction_review_stale: bool = False

    @property
    def effective_selected_question_number(self) -> Optional[str]:
        """The Part 3 question number to use - the teacher's confirmed/
        corrected choice when set, else the machine-extracted one. None when
        neither is known (Part 3 selection still needs confirmation)."""
        if self.teacher_selected_question_number is not None:
            return self.teacher_selected_question_number
        return self.extracted_selected_question_number

    @property
    def effective_answer_text(self) -> Optional[str]:
        """Teacher-corrected answer when the teacher has set one, else the
        original machine-detected answer - the preferred text for review,
        student-facing output and future Core AI 1 dataset export."""
        return self.corrected_answer_text if self.corrected_answer_text is not None else self.student_answer_text

    @property
    def effective_status(self) -> str:
        """Teacher's final marking status when set, else the automated one."""
        return self.teacher_status if self.teacher_status is not None else self.status

    @property
    def effective_score(self) -> Optional[float]:
        """Teacher's final score when set, else the automated score."""
        return self.teacher_score if self.teacher_score is not None else self.score


@dataclass
class SubjectProfileOverlay:
    overlay_id: int
    answer_file_id: int
    kind: str
    page_number: int
    x: float
    y: float
    width: float
    height: float
    rotation_angle: float
    text_value: Optional[str]
    created_at: str
    updated_at: Optional[str]
    is_hidden: bool = False
    is_teacher_adjusted: bool = False
    original_x: Optional[float] = None
    original_y: Optional[float] = None
    # Stage 12G-1A Phase 2B
    target_label: Optional[str] = None
    teacher_symbol_override: Optional[str] = None
    use_auto_symbol: bool = True
    # Optional manual font size (in PDF points) for a 'feedback' note; None =
    # size chosen automatically to fit the note's box.
    font_size: Optional[int] = None

    @property
    def effective_symbol(self) -> Optional[str]:
        """The symbol the teacher wants shown: the explicit override when Auto
        mode is off and an override is set, else None meaning "use the
        generated `kind`/`text_value`". Never mutates the generated symbol."""
        if not self.use_auto_symbol and self.teacher_symbol_override is not None:
            return self.teacher_symbol_override
        return None


# --- Subject Profile CRUD ----------------------------------------------------


def create_subject_profile(conn: sqlite3.Connection, teacher_id: int, profile_name: str) -> SubjectProfile:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profiles "
        "(teacher_id, profile_name, status, created_at, updated_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (teacher_id, profile_name, STATUS_DRAFT, created_at, created_at),
    )
    conn.commit()
    return SubjectProfile(
        profile_id=cursor.lastrowid, teacher_id=teacher_id, profile_name=profile_name,
        question_paper_path=None, answer_scheme_path=None, question_paper_ocr_json=None,
        answer_scheme_ocr_json=None, question_paper_extracted_json=None, answer_scheme_extracted_json=None,
        status=STATUS_DRAFT, created_at=created_at, updated_at=created_at, is_active=1,
    )


def update_subject_profile_files(
    conn: sqlite3.Connection, profile_id: int, question_paper_path: Optional[str], answer_scheme_path: Optional[str]
) -> None:
    conn.execute(
        "UPDATE subject_profiles SET question_paper_path = ?, answer_scheme_path = ?, updated_at = ? "
        "WHERE profile_id = ?",
        (question_paper_path, answer_scheme_path, _now(), profile_id),
    )
    conn.commit()


def update_subject_profile_ocr_content(
    conn: sqlite3.Connection, profile_id: int,
    question_paper_ocr_json: Optional[str] = None, answer_scheme_ocr_json: Optional[str] = None,
) -> None:
    fields = []
    values = []
    if question_paper_ocr_json is not None:
        fields.append("question_paper_ocr_json = ?")
        values.append(question_paper_ocr_json)
    if answer_scheme_ocr_json is not None:
        fields.append("answer_scheme_ocr_json = ?")
        values.append(answer_scheme_ocr_json)
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(profile_id)
    conn.execute(f"UPDATE subject_profiles SET {', '.join(fields)} WHERE profile_id = ?", values)
    conn.commit()


def update_subject_profile_extracted_content(
    conn: sqlite3.Connection, profile_id: int,
    question_paper_extracted_json: Optional[str] = None, answer_scheme_extracted_json: Optional[str] = None,
) -> None:
    fields = []
    values = []
    if question_paper_extracted_json is not None:
        fields.append("question_paper_extracted_json = ?")
        values.append(question_paper_extracted_json)
    if answer_scheme_extracted_json is not None:
        fields.append("answer_scheme_extracted_json = ?")
        values.append(answer_scheme_extracted_json)
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(profile_id)
    conn.execute(f"UPDATE subject_profiles SET {', '.join(fields)} WHERE profile_id = ?", values)
    conn.commit()


def update_subject_profile_status(conn: sqlite3.Connection, profile_id: int, status: str) -> None:
    conn.execute(
        "UPDATE subject_profiles SET status = ?, updated_at = ? WHERE profile_id = ?",
        (status, _now(), profile_id),
    )
    conn.commit()


def rename_subject_profile(conn: sqlite3.Connection, profile_id: int, profile_name: str) -> None:
    conn.execute(
        "UPDATE subject_profiles SET profile_name = ?, updated_at = ? WHERE profile_id = ?",
        (profile_name, _now(), profile_id),
    )
    conn.commit()


def get_subject_profile_by_id(conn: sqlite3.Connection, profile_id: int) -> Optional[SubjectProfile]:
    row = conn.execute(
        "SELECT profile_id, teacher_id, profile_name, question_paper_path, answer_scheme_path, "
        "question_paper_ocr_json, answer_scheme_ocr_json, question_paper_extracted_json, "
        "answer_scheme_extracted_json, status, created_at, updated_at, is_active "
        "FROM subject_profiles WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        return None
    return SubjectProfile(**dict(row))


def get_subject_profiles_for_teacher(conn: sqlite3.Connection, teacher_id: int) -> List[SubjectProfile]:
    rows = conn.execute(
        "SELECT profile_id, teacher_id, profile_name, question_paper_path, answer_scheme_path, "
        "question_paper_ocr_json, answer_scheme_ocr_json, question_paper_extracted_json, "
        "answer_scheme_extracted_json, status, created_at, updated_at, is_active "
        "FROM subject_profiles WHERE teacher_id = ? AND is_active = 1 ORDER BY updated_at DESC, profile_id DESC",
        (teacher_id,),
    ).fetchall()
    return [SubjectProfile(**dict(row)) for row in rows]


def get_all_active_subject_profiles(conn: sqlite3.Connection) -> List[SubjectProfile]:
    """Stage 12G-2: every active Subject Profile across ALL teachers.

    Core AI 2 region-detection training data is global (all teachers'
    regions), so the admin's global dataset export aggregates over all
    profiles. Teacher-scoped listing/export is unchanged (still owner-only)."""
    rows = conn.execute(
        "SELECT profile_id, teacher_id, profile_name, question_paper_path, answer_scheme_path, "
        "question_paper_ocr_json, answer_scheme_ocr_json, question_paper_extracted_json, "
        "answer_scheme_extracted_json, status, created_at, updated_at, is_active "
        "FROM subject_profiles WHERE is_active = 1 ORDER BY teacher_id, updated_at DESC, profile_id DESC",
    ).fetchall()
    return [SubjectProfile(**dict(row)) for row in rows]


def delete_subject_profile(conn: sqlite3.Connection, profile_id: int) -> None:
    conn.execute("DELETE FROM subject_profiles WHERE profile_id = ?", (profile_id,))
    conn.commit()


# --- Region CRUD --------------------------------------------------------------


def add_subject_profile_region(
    conn: sqlite3.Connection, profile_id: int, source: str, label: str, region_type: str,
    page_number: int, x: float, y: float, width: float, height: float,
    shape_type: str = SHAPE_TYPE_RECTANGLE, polygon_points_json: Optional[str] = None,
    rotation_angle: float = 0.0, order_index: int = 0, notes: Optional[str] = None,
) -> SubjectProfileRegion:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profile_regions "
        "(profile_id, source, label, region_type, page_number, x, y, width, height, "
        "shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, source, label, region_type, page_number, x, y, width, height,
         shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at),
    )
    conn.commit()
    return SubjectProfileRegion(
        region_id=cursor.lastrowid, profile_id=profile_id, source=source, label=label, region_type=region_type,
        page_number=page_number, x=x, y=y, width=width, height=height, shape_type=shape_type,
        polygon_points_json=polygon_points_json, rotation_angle=rotation_angle, order_index=order_index,
        notes=notes, created_at=created_at,
    )


def update_subject_profile_region(
    conn: sqlite3.Connection, region_id: int, label: str, region_type: str,
    rotation_angle: float, order_index: int, notes: Optional[str],
) -> None:
    conn.execute(
        "UPDATE subject_profile_regions SET label = ?, region_type = ?, rotation_angle = ?, "
        "order_index = ?, notes = ? WHERE region_id = ?",
        (label, region_type, rotation_angle, order_index, notes, region_id),
    )
    conn.commit()


def update_subject_profile_region_geometry(
    conn: sqlite3.Connection, region_id: int, x: float, y: float, width: float, height: float,
    polygon_points_json: Optional[str] = None,
) -> None:
    """Persist a region's new position/size (Stage 12E-2 UX Fix 2 drag-to-
    move/resize). Only x/y/width/height (and polygon_points_json for a
    moved polygon region) are updated - label/type/rotation/notes are
    untouched, so a suggested region's label/notes survive a geometry
    edit unchanged, matching update_subject_profile_region's own narrow-
    field-update convention."""
    if polygon_points_json is not None:
        conn.execute(
            "UPDATE subject_profile_regions SET x = ?, y = ?, width = ?, height = ?, "
            "polygon_points_json = ? WHERE region_id = ?",
            (x, y, width, height, polygon_points_json, region_id),
        )
    else:
        conn.execute(
            "UPDATE subject_profile_regions SET x = ?, y = ?, width = ?, height = ? WHERE region_id = ?",
            (x, y, width, height, region_id),
        )
    conn.commit()


def get_regions_for_profile(
    conn: sqlite3.Connection, profile_id: int, source: Optional[str] = None
) -> List[SubjectProfileRegion]:
    if source is None:
        rows = conn.execute(
            "SELECT region_id, profile_id, source, label, region_type, page_number, x, y, width, height, "
            "shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at "
            "FROM subject_profile_regions WHERE profile_id = ? ORDER BY source, page_number, order_index, region_id",
            (profile_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT region_id, profile_id, source, label, region_type, page_number, x, y, width, height, "
            "shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at "
            "FROM subject_profile_regions WHERE profile_id = ? AND source = ? "
            "ORDER BY page_number, order_index, region_id",
            (profile_id, source),
        ).fetchall()
    return [SubjectProfileRegion(**dict(row)) for row in rows]


def get_region_by_id(conn: sqlite3.Connection, region_id: int) -> Optional[SubjectProfileRegion]:
    row = conn.execute(
        "SELECT region_id, profile_id, source, label, region_type, page_number, x, y, width, height, "
        "shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at "
        "FROM subject_profile_regions WHERE region_id = ?",
        (region_id,),
    ).fetchone()
    if row is None:
        return None
    return SubjectProfileRegion(**dict(row))


def get_max_region_order(conn: sqlite3.Connection, profile_id: int, page_number: int) -> int:
    row = conn.execute(
        "SELECT MAX(order_index) FROM subject_profile_regions WHERE profile_id = ? AND page_number = ?",
        (profile_id, page_number),
    ).fetchone()
    return (row[0] or 0)


def delete_subject_profile_region(conn: sqlite3.Connection, region_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_regions WHERE region_id = ?", (region_id,))
    conn.commit()


# --- Region group CRUD ---------------------------------------------------------


def create_subject_profile_region_group(
    conn: sqlite3.Connection, profile_id: int, label: str, region_type: str, notes: Optional[str] = None
) -> SubjectProfileRegionGroup:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profile_region_groups (profile_id, label, region_type, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (profile_id, label, region_type, notes, created_at),
    )
    conn.commit()
    return SubjectProfileRegionGroup(
        group_id=cursor.lastrowid, profile_id=profile_id, label=label, region_type=region_type,
        notes=notes, created_at=created_at,
    )


def get_region_groups_for_profile(conn: sqlite3.Connection, profile_id: int) -> List[SubjectProfileRegionGroup]:
    rows = conn.execute(
        "SELECT group_id, profile_id, label, region_type, notes, created_at "
        "FROM subject_profile_region_groups WHERE profile_id = ? ORDER BY group_id",
        (profile_id,),
    ).fetchall()
    return [SubjectProfileRegionGroup(**dict(row)) for row in rows]


def update_region_group(
    conn: sqlite3.Connection, group_id: int, label: str, region_type: str
) -> None:
    conn.execute(
        "UPDATE subject_profile_region_groups SET label = ?, region_type = ? WHERE group_id = ?",
        (label, region_type, group_id),
    )
    conn.commit()


def get_region_group_by_id(conn: sqlite3.Connection, group_id: int) -> Optional[SubjectProfileRegionGroup]:
    row = conn.execute(
        "SELECT group_id, profile_id, label, region_type, notes, created_at "
        "FROM subject_profile_region_groups WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if row is None:
        return None
    return SubjectProfileRegionGroup(**dict(row))


def delete_subject_profile_region_group(conn: sqlite3.Connection, group_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_region_groups WHERE group_id = ?", (group_id,))
    conn.commit()


def add_region_group_member(conn: sqlite3.Connection, group_id: int, region_id: int, member_order: int) -> None:
    conn.execute(
        "INSERT INTO subject_profile_region_group_members (group_id, region_id, member_order) VALUES (?, ?, ?)",
        (group_id, region_id, member_order),
    )
    conn.commit()


def get_members_for_group(conn: sqlite3.Connection, group_id: int) -> List[SubjectProfileRegionGroupMember]:
    rows = conn.execute(
        "SELECT group_id, region_id, member_order FROM subject_profile_region_group_members "
        "WHERE group_id = ? ORDER BY member_order",
        (group_id,),
    ).fetchall()
    return [SubjectProfileRegionGroupMember(**dict(row)) for row in rows]


# --- Answer key entry CRUD -----------------------------------------------------


def create_or_update_answer_key_entry(
    conn: sqlite3.Connection, profile_id: int, target_label: str, target_kind: str,
    question_no: Optional[str], correct_answer: Optional[str], max_mark: float, comment: Optional[str],
) -> SubjectProfileAnswerKeyEntry:
    existing = conn.execute(
        "SELECT entry_id FROM subject_profile_answer_key_entries WHERE profile_id = ? AND target_label = ?",
        (profile_id, target_label),
    ).fetchone()
    now = _now()
    if existing is not None:
        conn.execute(
            "UPDATE subject_profile_answer_key_entries SET target_kind = ?, question_no = ?, "
            "correct_answer = ?, max_mark = ?, comment = ?, updated_at = ? WHERE entry_id = ?",
            (target_kind, question_no, correct_answer, max_mark, comment, now, existing["entry_id"]),
        )
        conn.commit()
        entry_id = existing["entry_id"]
    else:
        cursor = conn.execute(
            "INSERT INTO subject_profile_answer_key_entries "
            "(profile_id, target_label, target_kind, question_no, correct_answer, max_mark, comment, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile_id, target_label, target_kind, question_no, correct_answer, max_mark, comment, now, now),
        )
        conn.commit()
        entry_id = cursor.lastrowid
    return SubjectProfileAnswerKeyEntry(
        entry_id=entry_id, profile_id=profile_id, target_label=target_label, target_kind=target_kind,
        question_no=question_no, correct_answer=correct_answer, max_mark=max_mark, comment=comment,
        created_at=now, updated_at=now,
    )


def get_answer_key_entries_for_profile(conn: sqlite3.Connection, profile_id: int) -> List[SubjectProfileAnswerKeyEntry]:
    rows = conn.execute(
        "SELECT entry_id, profile_id, target_label, target_kind, question_no, correct_answer, max_mark, "
        "comment, created_at, updated_at FROM subject_profile_answer_key_entries "
        "WHERE profile_id = ? ORDER BY entry_id",
        (profile_id,),
    ).fetchall()
    return [SubjectProfileAnswerKeyEntry(**dict(row)) for row in rows]


# --- Extracted / marked answers -------------------------------------------------


def add_extracted_answer(
    conn: sqlite3.Connection, answer_file_id: int, target_label: str, target_kind: str,
    region_type: Optional[str], extracted_text: Optional[str], confidence: Optional[float],
    status: str, message: Optional[str],
) -> SubjectProfileExtractedAnswer:
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profile_extracted_answers "
        "(answer_file_id, target_label, target_kind, region_type, extracted_text, confidence, status, "
        "message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, target_label, target_kind, region_type, extracted_text, confidence, status,
         message, created_at),
    )
    conn.commit()
    return SubjectProfileExtractedAnswer(
        extracted_answer_id=cursor.lastrowid, answer_file_id=answer_file_id, target_label=target_label,
        target_kind=target_kind, region_type=region_type, extracted_text=extracted_text, confidence=confidence,
        status=status, message=message, created_at=created_at,
    )


def get_extracted_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[SubjectProfileExtractedAnswer]:
    rows = conn.execute(
        "SELECT extracted_answer_id, answer_file_id, target_label, target_kind, region_type, extracted_text, "
        "confidence, status, message, created_at FROM subject_profile_extracted_answers "
        "WHERE answer_file_id = ? ORDER BY extracted_answer_id",
        (answer_file_id,),
    ).fetchall()
    return [SubjectProfileExtractedAnswer(**dict(row)) for row in rows]


def delete_extracted_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_extracted_answers WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


def add_marked_answer(
    conn: sqlite3.Connection, answer_file_id: int, target_label: str, target_kind: str,
    region_type: Optional[str], student_answer_text: Optional[str], correct_answer_text: Optional[str],
    score: Optional[float], max_score: float, is_correct: bool, status: str, feedback: Optional[str],
    raw_ocr_text: Optional[str] = None, extraction_confidence: Optional[float] = None,
    extraction_method: Optional[str] = None, extraction_timestamp: Optional[str] = None,
    extracted_selected_question_number: Optional[str] = None,
) -> SubjectProfileMarkedAnswer:
    """Create a marked-answer row. Stage 12G-1A: raw_ocr_text/extraction_*
    capture the raw extraction provenance at mark time (preserved even after
    a teacher later corrects the answer). When raw_ocr_text is not supplied
    it defaults to student_answer_text (the original detected answer), so the
    raw OCR is always available for audit. extracted_selected_question_number
    is the machine-detected Part 3 question choice (only on the Part 3 box)."""
    created_at = _now()
    if raw_ocr_text is None:
        raw_ocr_text = student_answer_text
    cursor = conn.execute(
        "INSERT INTO subject_profile_marked_answers "
        "(answer_file_id, target_label, target_kind, region_type, student_answer_text, correct_answer_text, "
        "score, max_score, is_correct, status, feedback, created_at, raw_ocr_text, extraction_confidence, "
        "extraction_method, extraction_timestamp, extracted_selected_question_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, target_label, target_kind, region_type, student_answer_text, correct_answer_text,
         score, max_score, int(is_correct), status, feedback, created_at, raw_ocr_text, extraction_confidence,
         extraction_method, extraction_timestamp, extracted_selected_question_number),
    )
    conn.commit()
    return SubjectProfileMarkedAnswer(
        marked_answer_id=cursor.lastrowid, answer_file_id=answer_file_id, target_label=target_label,
        target_kind=target_kind, region_type=region_type, student_answer_text=student_answer_text,
        correct_answer_text=correct_answer_text, score=score, max_score=max_score, is_correct=is_correct,
        status=status, feedback=feedback, created_at=created_at, raw_ocr_text=raw_ocr_text,
        extraction_confidence=extraction_confidence, extraction_method=extraction_method,
        extraction_timestamp=extraction_timestamp,
        extracted_selected_question_number=extracted_selected_question_number,
    )


_MARKED_ANSWER_COLUMNS = (
    "marked_answer_id, answer_file_id, target_label, target_kind, region_type, student_answer_text, "
    "correct_answer_text, score, max_score, is_correct, status, feedback, created_at, "
    "raw_ocr_text, extraction_confidence, extraction_method, extraction_timestamp, corrected_answer_text, "
    "teacher_score, teacher_status, teacher_feedback, private_comment, reviewed_by, reviewed_at, updated_at, "
    "extracted_selected_question_number, teacher_selected_question_number, extraction_review_stale"
)


def _row_to_marked_answer(row: sqlite3.Row) -> SubjectProfileMarkedAnswer:
    data = dict(row)
    data["is_correct"] = bool(data["is_correct"])
    data["extraction_review_stale"] = bool(data["extraction_review_stale"])
    return SubjectProfileMarkedAnswer(**data)


def set_marked_answer_extraction_stale(conn: sqlite3.Connection, marked_answer_id: int, stale: bool) -> None:
    """Phase 2C: flag/clear a target's teacher review as stale after its
    effective extraction changed (region override / rerun OCR). Never touches
    the original machine result or the teacher's stored values."""
    conn.execute(
        "UPDATE subject_profile_marked_answers SET extraction_review_stale = ?, updated_at = ? "
        "WHERE marked_answer_id = ?",
        (int(bool(stale)), _now(), marked_answer_id),
    )
    conn.commit()


def get_marked_answer_by_id(conn: sqlite3.Connection, marked_answer_id: int) -> Optional[SubjectProfileMarkedAnswer]:
    row = conn.execute(
        f"SELECT {_MARKED_ANSWER_COLUMNS} FROM subject_profile_marked_answers WHERE marked_answer_id = ?",
        (marked_answer_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_marked_answer(row)


def update_marked_answer_score(
    conn: sqlite3.Connection, marked_answer_id: int, score: float, status: str, feedback: Optional[str],
) -> SubjectProfileMarkedAnswer:
    """Update a marked answer's score/status/feedback in place - used to
    record a teacher's manual mark for a Kertas 2 writing answer (see
    MARKED_ANSWER_STATUS_TEACHER_SCORED). Never touches student_answer_text/
    correct_answer_text/max_score/target_label - only the grading outcome."""
    conn.execute(
        "UPDATE subject_profile_marked_answers SET score = ?, status = ?, feedback = ? WHERE marked_answer_id = ?",
        (score, status, feedback, marked_answer_id),
    )
    conn.commit()
    updated = get_marked_answer_by_id(conn, marked_answer_id)
    if updated is None:
        raise ValueError("Marked answer not found.")
    return updated


def get_marked_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[SubjectProfileMarkedAnswer]:
    rows = conn.execute(
        f"SELECT {_MARKED_ANSWER_COLUMNS} FROM subject_profile_marked_answers "
        "WHERE answer_file_id = ? ORDER BY marked_answer_id",
        (answer_file_id,),
    ).fetchall()
    return [_row_to_marked_answer(row) for row in rows]


def delete_marked_answers_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_marked_answers WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


# --- Overlays -------------------------------------------------------------------


_OVERLAY_COLUMNS = (
    "overlay_id, answer_file_id, kind, page_number, x, y, width, height, rotation_angle, "
    "text_value, created_at, updated_at, is_hidden, is_teacher_adjusted, original_x, original_y, "
    "target_label, teacher_symbol_override, use_auto_symbol, font_size"
)


def _row_to_overlay(row: sqlite3.Row) -> SubjectProfileOverlay:
    data = dict(row)
    data["is_hidden"] = bool(data["is_hidden"])
    data["is_teacher_adjusted"] = bool(data["is_teacher_adjusted"])
    data["use_auto_symbol"] = bool(data["use_auto_symbol"])
    return SubjectProfileOverlay(**data)


def add_overlay(
    conn: sqlite3.Connection, answer_file_id: int, kind: str, page_number: int,
    x: float, y: float, width: float = 0.04, height: float = 0.04,
    rotation_angle: float = 0.0, text_value: Optional[str] = None,
    target_label: Optional[str] = None, font_size: Optional[int] = None,
) -> SubjectProfileOverlay:
    """Create an overlay. Stage 12G-1A: original_x/original_y snapshot the
    generated position so a teacher move can be reverted (Restore Default).
    Phase 2B: target_label links a status marker to its logical answer target
    (NULL for the headline summary overlay). font_size is an optional manual
    font size (PDF points) for a feedback note; None = automatic."""
    created_at = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profile_overlays "
        "(answer_file_id, kind, page_number, x, y, width, height, rotation_angle, text_value, "
        "created_at, updated_at, is_hidden, is_teacher_adjusted, original_x, original_y, "
        "target_label, teacher_symbol_override, use_auto_symbol, font_size) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, NULL, 1, ?)",
        (answer_file_id, kind, page_number, x, y, width, height, rotation_angle, text_value,
         created_at, created_at, x, y, target_label, font_size),
    )
    conn.commit()
    return SubjectProfileOverlay(
        overlay_id=cursor.lastrowid, answer_file_id=answer_file_id, kind=kind, page_number=page_number,
        x=x, y=y, width=width, height=height, rotation_angle=rotation_angle, text_value=text_value,
        created_at=created_at, updated_at=created_at, is_hidden=False, is_teacher_adjusted=False,
        original_x=x, original_y=y, target_label=target_label, teacher_symbol_override=None,
        use_auto_symbol=True, font_size=font_size,
    )


def set_overlay_font_size(
    conn: sqlite3.Connection, overlay_id: int, font_size: Optional[int],
) -> None:
    """Set (or clear, with font_size=None) the manual font size for a feedback
    overlay note. None restores automatic sizing."""
    conn.execute(
        "UPDATE subject_profile_overlays SET font_size = ?, updated_at = ? WHERE overlay_id = ?",
        (font_size, _now(), overlay_id),
    )
    conn.commit()


def set_overlay_symbol_override(
    conn: sqlite3.Connection, overlay_id: int, symbol_override: Optional[str],
) -> None:
    """Stage 12G-1A Phase 2B: set an explicit teacher symbol (Tick/X/Question
    Mark) or clear it back to Auto (symbol_override=None). The generated
    `kind` column is never touched, so the original auto symbol stays
    available for audit and returns immediately when Auto is restored."""
    use_auto = 1 if symbol_override is None else 0
    conn.execute(
        "UPDATE subject_profile_overlays SET teacher_symbol_override = ?, use_auto_symbol = ?, "
        "updated_at = ? WHERE overlay_id = ?",
        (symbol_override, use_auto, _now(), overlay_id),
    )
    conn.commit()


def get_overlays_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[SubjectProfileOverlay]:
    rows = conn.execute(
        f"SELECT {_OVERLAY_COLUMNS} FROM subject_profile_overlays "
        "WHERE answer_file_id = ? ORDER BY overlay_id",
        (answer_file_id,),
    ).fetchall()
    return [_row_to_overlay(row) for row in rows]


def get_overlay_by_id(conn: sqlite3.Connection, overlay_id: int) -> Optional[SubjectProfileOverlay]:
    row = conn.execute(
        f"SELECT {_OVERLAY_COLUMNS} FROM subject_profile_overlays WHERE overlay_id = ?",
        (overlay_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_overlay(row)


def update_overlay_transform(
    conn: sqlite3.Connection, overlay_id: int, x: float, y: float,
    width: float, height: float, rotation_angle: float,
) -> None:
    conn.execute(
        "UPDATE subject_profile_overlays SET x = ?, y = ?, width = ?, height = ?, rotation_angle = ?, "
        "updated_at = ? WHERE overlay_id = ?",
        (x, y, width, height, rotation_angle, _now(), overlay_id),
    )
    conn.commit()


def set_overlay_hidden(conn: sqlite3.Connection, overlay_id: int, hidden: bool) -> None:
    """Stage 12G-1A: hide/show an overlay for this attempt without deleting
    it (so it can be restored)."""
    conn.execute(
        "UPDATE subject_profile_overlays SET is_hidden = ?, updated_at = ? WHERE overlay_id = ?",
        (int(hidden), _now(), overlay_id),
    )
    conn.commit()


def move_overlay_and_mark_adjusted(conn: sqlite3.Connection, overlay_id: int, x: float, y: float) -> None:
    """Stage 12G-1A: record a teacher's manual reposition and flag the
    overlay as teacher-adjusted (so a later default regeneration knows to
    preserve this position - see the review service's overlay handling)."""
    conn.execute(
        "UPDATE subject_profile_overlays SET x = ?, y = ?, is_teacher_adjusted = 1, updated_at = ? "
        "WHERE overlay_id = ?",
        (x, y, _now(), overlay_id),
    )
    conn.commit()


def restore_overlay_default_position(conn: sqlite3.Connection, overlay_id: int) -> None:
    """Stage 12G-1A: revert a teacher-moved overlay to its generated
    (original_x/original_y) position and clear the teacher-adjusted flag."""
    conn.execute(
        "UPDATE subject_profile_overlays SET x = COALESCE(original_x, x), y = COALESCE(original_y, y), "
        "is_teacher_adjusted = 0, updated_at = ? WHERE overlay_id = ?",
        (_now(), overlay_id),
    )
    conn.commit()


def delete_overlay(conn: sqlite3.Connection, overlay_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_overlays WHERE overlay_id = ?", (overlay_id,))
    conn.commit()


def delete_overlays_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_overlays WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


# --- Stage 12G-1A: teacher review model layer -------------------------------


@dataclass
class SubjectProfileAttemptReview:
    review_id: int
    answer_file_id: int
    profile_id: Optional[int]
    review_state: str
    reviewed_by: Optional[int]
    created_at: str
    updated_at: Optional[str]
    reviewed_at: Optional[str]
    finalised_at: Optional[str]
    final_marked_pdf_path: Optional[str] = None
    final_comments_path: Optional[str] = None
    final_output_generated_at: Optional[str] = None
    final_output_version: Optional[str] = None


@dataclass
class FeedbackCategory:
    category_id: int
    category_key: str
    label: str
    display_order: int
    is_active: bool
    created_at: str


@dataclass
class AttemptRegionOverride:
    override_id: int
    answer_file_id: int
    profile_region_id: Optional[int]
    source: str
    label: str
    region_type: Optional[str]
    page_number: int
    x: float
    y: float
    width: float
    height: float
    shape_type: str
    polygon_points_json: Optional[str]
    rotation_angle: float
    corrected_text: Optional[str]
    correction_reason: Optional[str]
    corrected_by: Optional[int]
    corrected_at: Optional[str]
    created_at: str
    # Stage 12G-1A Phase 2C
    original_x: Optional[float] = None
    original_y: Optional[float] = None
    original_width: Optional[float] = None
    original_height: Optional[float] = None
    rerun_ocr_text: Optional[str] = None
    rerun_ocr_confidence: Optional[float] = None
    rerun_ocr_at: Optional[str] = None
    crop_checksum: Optional[str] = None
    original_crop_checksum: Optional[str] = None


@dataclass
class ReviewAuditEntry:
    audit_id: int
    answer_file_id: int
    action: str
    from_state: Optional[str]
    to_state: Optional[str]
    acted_by: Optional[int]
    acted_at: str
    note: Optional[str]


def update_marked_answer_review_fields(
    conn: sqlite3.Connection, marked_answer_id: int, *,
    corrected_answer_text: Optional[str] = None, teacher_score: Optional[float] = None,
    teacher_status: Optional[str] = None, teacher_feedback: Optional[str] = None,
    private_comment: Optional[str] = None, reviewed_by: Optional[int] = None,
    teacher_selected_question_number: Optional[str] = None,
    fields: Optional[List[str]] = None,
) -> SubjectProfileMarkedAnswer:
    """Update ONLY the teacher-review columns, never the original machine
    columns (Stage 12G-1A). `fields` lists which teacher columns to write
    (so a None can explicitly clear a field); omitted, every non-None
    argument is written. reviewed_at/updated_at are always refreshed."""
    now = _now()
    settable = {
        "corrected_answer_text": corrected_answer_text,
        "teacher_score": teacher_score,
        "teacher_status": teacher_status,
        "teacher_feedback": teacher_feedback,
        "private_comment": private_comment,
        "reviewed_by": reviewed_by,
        "teacher_selected_question_number": teacher_selected_question_number,
    }
    to_write = fields if fields is not None else [k for k, v in settable.items() if v is not None]
    set_clauses = [f"{col} = ?" for col in to_write] + ["reviewed_at = ?", "updated_at = ?"]
    values = [settable[col] for col in to_write] + [now, now, marked_answer_id]
    conn.execute(
        f"UPDATE subject_profile_marked_answers SET {', '.join(set_clauses)} WHERE marked_answer_id = ?",
        values,
    )
    conn.commit()
    updated = get_marked_answer_by_id(conn, marked_answer_id)
    if updated is None:
        raise ValueError("Marked answer not found.")
    return updated


def get_attempt_review(conn: sqlite3.Connection, answer_file_id: int) -> Optional[SubjectProfileAttemptReview]:
    row = conn.execute(
        "SELECT review_id, answer_file_id, profile_id, review_state, reviewed_by, created_at, updated_at, "
        "reviewed_at, finalised_at, final_marked_pdf_path, final_comments_path, final_output_generated_at, "
        "final_output_version FROM subject_profile_attempt_reviews WHERE answer_file_id = ?",
        (answer_file_id,),
    ).fetchone()
    return SubjectProfileAttemptReview(**dict(row)) if row is not None else None


def set_attempt_review_final_outputs(
    conn: sqlite3.Connection, answer_file_id: int, *,
    marked_pdf_path: Optional[str], comments_path: Optional[str], generated_at: Optional[str],
    version: Optional[str] = None,
) -> None:
    """Record (or clear) the published final reviewed-output paths + active
    version on the attempt review row. The marked PDF path, comments path,
    version and timestamp are switched TOGETHER in this single UPDATE - one
    SQLite statement is the atomic pair-level publication boundary (Phase 2B
    consistency fix), so a download never sees a mismatched pair."""
    conn.execute(
        "UPDATE subject_profile_attempt_reviews SET final_marked_pdf_path = ?, final_comments_path = ?, "
        "final_output_generated_at = ?, final_output_version = ?, updated_at = ? WHERE answer_file_id = ?",
        (marked_pdf_path, comments_path, generated_at, version, _now(), answer_file_id),
    )
    conn.commit()


def get_or_create_attempt_review(
    conn: sqlite3.Connection, answer_file_id: int, profile_id: Optional[int] = None,
) -> SubjectProfileAttemptReview:
    existing = get_attempt_review(conn, answer_file_id)
    if existing is not None:
        return existing
    now = _now()
    conn.execute(
        "INSERT INTO subject_profile_attempt_reviews (answer_file_id, profile_id, review_state, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?)",
        (answer_file_id, profile_id, REVIEW_STATE_DRAFT, now, now),
    )
    conn.commit()
    return get_attempt_review(conn, answer_file_id)


def update_attempt_review_state(
    conn: sqlite3.Connection, answer_file_id: int, review_state: str, reviewed_by: Optional[int],
    *, set_reviewed_at: bool = False, set_finalised_at: Optional[bool] = None,
) -> SubjectProfileAttemptReview:
    now = _now()
    fields = ["review_state = ?", "reviewed_by = ?", "updated_at = ?"]
    values: list = [review_state, reviewed_by, now]
    if set_reviewed_at:
        fields.append("reviewed_at = ?")
        values.append(now)
    if set_finalised_at is True:
        fields.append("finalised_at = ?")
        values.append(now)
    elif set_finalised_at is False:
        fields.append("finalised_at = ?")
        values.append(None)
    values.append(answer_file_id)
    conn.execute(
        f"UPDATE subject_profile_attempt_reviews SET {', '.join(fields)} WHERE answer_file_id = ?",
        values,
    )
    conn.commit()
    return get_attempt_review(conn, answer_file_id)


def list_feedback_categories(conn: sqlite3.Connection, active_only: bool = True) -> List[FeedbackCategory]:
    sql = ("SELECT category_id, category_key, label, display_order, is_active, created_at "
           "FROM subject_profile_feedback_categories")
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY display_order, category_id"
    result = []
    for row in conn.execute(sql).fetchall():
        data = dict(row)
        data["is_active"] = bool(data["is_active"])
        result.append(FeedbackCategory(**data))
    return result


def set_answer_feedback_categories(conn: sqlite3.Connection, marked_answer_id: int, category_ids: List[int]) -> None:
    """Replace the selected feedback categories for one marked answer with
    the given set (structured link rows, never a CSV string)."""
    now = _now()
    conn.execute(
        "DELETE FROM subject_profile_answer_feedback_categories WHERE marked_answer_id = ?", (marked_answer_id,)
    )
    for category_id in dict.fromkeys(category_ids):
        conn.execute(
            "INSERT OR IGNORE INTO subject_profile_answer_feedback_categories "
            "(marked_answer_id, category_id, created_at) VALUES (?, ?, ?)",
            (marked_answer_id, category_id, now),
        )
    conn.commit()


def get_answer_feedback_category_ids(conn: sqlite3.Connection, marked_answer_id: int) -> List[int]:
    rows = conn.execute(
        "SELECT category_id FROM subject_profile_answer_feedback_categories "
        "WHERE marked_answer_id = ? ORDER BY category_id",
        (marked_answer_id,),
    ).fetchall()
    return [row[0] for row in rows]


_REGION_OVERRIDE_COLUMNS = (
    "override_id, answer_file_id, profile_region_id, source, label, region_type, page_number, "
    "x, y, width, height, shape_type, polygon_points_json, rotation_angle, corrected_text, "
    "correction_reason, corrected_by, corrected_at, created_at, "
    "original_x, original_y, original_width, original_height, "
    "rerun_ocr_text, rerun_ocr_confidence, rerun_ocr_at, crop_checksum, original_crop_checksum"
)


def upsert_region_override(
    conn: sqlite3.Connection, answer_file_id: int, label: str, *, profile_region_id: Optional[int],
    source: str, region_type: Optional[str], page_number: int, x: float, y: float, width: float, height: float,
    shape_type: str = "rectangle", polygon_points_json: Optional[str] = None, rotation_angle: float = 0.0,
    corrected_text: Optional[str] = None, correction_reason: Optional[str] = None, corrected_by: Optional[int] = None,
    original_x: Optional[float] = None, original_y: Optional[float] = None,
    original_width: Optional[float] = None, original_height: Optional[float] = None,
    crop_checksum: Optional[str] = None, original_crop_checksum: Optional[str] = None,
) -> AttemptRegionOverride:
    """Create or replace the attempt-specific geometry override for one
    target label (one override per answer_file+label via the UNIQUE key).
    Phase 2C: original_* snapshots the shared profile region geometry and the
    crop checksums record that the crop changed - preserved across geometry
    edits so 'Restore Original Region' and the evidence comparison stay
    correct (only set on first creation)."""
    now = _now()
    existing = get_region_override(conn, answer_file_id, label)
    if existing is not None:
        # Preserve the first-captured original geometry/checksum snapshot.
        original_x = existing.original_x if existing.original_x is not None else original_x
        original_y = existing.original_y if existing.original_y is not None else original_y
        original_width = existing.original_width if existing.original_width is not None else original_width
        original_height = existing.original_height if existing.original_height is not None else original_height
        original_crop_checksum = existing.original_crop_checksum or original_crop_checksum
        conn.execute(
            "UPDATE subject_profile_attempt_region_overrides SET profile_region_id = ?, source = ?, "
            "region_type = ?, page_number = ?, x = ?, y = ?, width = ?, height = ?, shape_type = ?, "
            "polygon_points_json = ?, rotation_angle = ?, corrected_text = ?, correction_reason = ?, "
            "corrected_by = ?, corrected_at = ?, original_x = ?, original_y = ?, original_width = ?, "
            "original_height = ?, crop_checksum = ?, original_crop_checksum = ? WHERE override_id = ?",
            (profile_region_id, source, region_type, page_number, x, y, width, height, shape_type,
             polygon_points_json, rotation_angle, corrected_text, correction_reason, corrected_by, now,
             original_x, original_y, original_width, original_height, crop_checksum, original_crop_checksum,
             existing.override_id),
        )
    else:
        conn.execute(
            "INSERT INTO subject_profile_attempt_region_overrides "
            "(answer_file_id, profile_region_id, source, label, region_type, page_number, x, y, width, height, "
            "shape_type, polygon_points_json, rotation_angle, corrected_text, correction_reason, corrected_by, "
            "corrected_at, created_at, original_x, original_y, original_width, original_height, crop_checksum, "
            "original_crop_checksum) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (answer_file_id, profile_region_id, source, label, region_type, page_number, x, y, width, height,
             shape_type, polygon_points_json, rotation_angle, corrected_text, correction_reason, corrected_by,
             now, now, original_x, original_y, original_width, original_height, crop_checksum, original_crop_checksum),
        )
    conn.commit()
    return get_region_override(conn, answer_file_id, label)


def set_region_override_corrected_text(conn: sqlite3.Connection, override_id: int, corrected_text: Optional[str]) -> None:
    conn.execute(
        "UPDATE subject_profile_attempt_region_overrides SET corrected_text = ?, corrected_at = ? WHERE override_id = ?",
        (corrected_text, _now(), override_id),
    )
    conn.commit()


def set_region_override_rerun_ocr(
    conn: sqlite3.Connection, override_id: int, rerun_ocr_text: Optional[str],
    confidence: Optional[float] = None, crop_checksum: Optional[str] = None,
) -> None:
    """Phase 2C: store the RERUN OCR result (from the override geometry) kept
    separate from the original OCR (on the marked answer) and from the
    teacher-corrected text."""
    conn.execute(
        "UPDATE subject_profile_attempt_region_overrides SET rerun_ocr_text = ?, rerun_ocr_confidence = ?, "
        "rerun_ocr_at = ?, crop_checksum = COALESCE(?, crop_checksum) WHERE override_id = ?",
        (rerun_ocr_text, confidence, _now(), crop_checksum, override_id),
    )
    conn.commit()


def get_region_override(conn: sqlite3.Connection, answer_file_id: int, label: str) -> Optional[AttemptRegionOverride]:
    row = conn.execute(
        f"SELECT {_REGION_OVERRIDE_COLUMNS} FROM subject_profile_attempt_region_overrides "
        "WHERE answer_file_id = ? AND label = ?",
        (answer_file_id, label),
    ).fetchone()
    return AttemptRegionOverride(**dict(row)) if row is not None else None


def get_region_overrides_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[AttemptRegionOverride]:
    rows = conn.execute(
        f"SELECT {_REGION_OVERRIDE_COLUMNS} FROM subject_profile_attempt_region_overrides "
        "WHERE answer_file_id = ? ORDER BY override_id",
        (answer_file_id,),
    ).fetchall()
    return [AttemptRegionOverride(**dict(row)) for row in rows]


def delete_region_override(conn: sqlite3.Connection, override_id: int) -> None:
    conn.execute("DELETE FROM subject_profile_attempt_region_overrides WHERE override_id = ?", (override_id,))
    conn.commit()


def add_review_audit(
    conn: sqlite3.Connection, answer_file_id: int, action: str, *,
    from_state: Optional[str] = None, to_state: Optional[str] = None,
    acted_by: Optional[int] = None, note: Optional[str] = None,
) -> ReviewAuditEntry:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO subject_profile_review_audit (answer_file_id, action, from_state, to_state, acted_by, "
        "acted_at, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, action, from_state, to_state, acted_by, now, note),
    )
    conn.commit()
    return ReviewAuditEntry(
        audit_id=cursor.lastrowid, answer_file_id=answer_file_id, action=action, from_state=from_state,
        to_state=to_state, acted_by=acted_by, acted_at=now, note=note,
    )


def get_review_audit_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[ReviewAuditEntry]:
    rows = conn.execute(
        "SELECT audit_id, answer_file_id, action, from_state, to_state, acted_by, acted_at, note "
        "FROM subject_profile_review_audit WHERE answer_file_id = ? ORDER BY audit_id",
        (answer_file_id,),
    ).fetchall()
    return [ReviewAuditEntry(**dict(row)) for row in rows]
