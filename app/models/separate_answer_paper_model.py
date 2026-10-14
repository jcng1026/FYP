"""Stage 12G-1B - Manual Separate Answer Paper persistence layer.

Attempt-scoped storage for a separate-answer-paper attempt: its own page rows
(NEVER Subject Profile pages), the teacher-owned state of each required
logical target, the mapped rectangles (main + ordered continuation regions)
with their OCR lineage, and the K1 numbered-answer parser output.

Nothing here ever writes to the shared Subject Profile.
"""
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

# --- Attempt mode (strictly binary) -----------------------------------------
ATTEMPT_MODE_STANDARD = "standard"
ATTEMPT_MODE_SEPARATE = "separate_answer_paper"
ATTEMPT_MODES = (ATTEMPT_MODE_STANDARD, ATTEMPT_MODE_SEPARATE)

# --- Target states -----------------------------------------------------------
TARGET_STATE_UNRESOLVED = "unresolved"
TARGET_STATE_MAPPED = "mapped"
TARGET_STATE_EXPLICITLY_BLANK = "explicitly_blank"
TARGET_STATES = (TARGET_STATE_UNRESOLVED, TARGET_STATE_MAPPED, TARGET_STATE_EXPLICITLY_BLANK)

# --- Mapping types -----------------------------------------------------------
MAPPING_TYPE_K1_BLOCK = "k1_answer_block"
MAPPING_TYPE_K1_INDIVIDUAL = "k1_individual_answer"
MAPPING_TYPE_K2_PART1 = "k2_part1"
MAPPING_TYPE_K2_PART2 = "k2_part2"
MAPPING_TYPE_K2_PART3 = "k2_part3"
MAPPING_TYPE_PART3_SELECTED_QUESTION = "part3_selected_question"
MAPPING_TYPE_CONTINUATION = "continuation"
MAPPING_TYPES = (
    MAPPING_TYPE_K1_BLOCK, MAPPING_TYPE_K1_INDIVIDUAL, MAPPING_TYPE_K2_PART1,
    MAPPING_TYPE_K2_PART2, MAPPING_TYPE_K2_PART3, MAPPING_TYPE_PART3_SELECTED_QUESTION,
    MAPPING_TYPE_CONTINUATION,
)

# --- Parsed-answer states ----------------------------------------------------
PARSED_STATE_UNCONFIRMED = "unconfirmed"
PARSED_STATE_CONFIRMED = "confirmed"
PARSED_STATE_BLANK = "blank"
PARSED_STATE_UNRESOLVED = "unresolved"

# Where a parsed answer's marker anchor came from. Approximate is never
# presented as exact.
ANCHOR_SOURCE_OCR_LINE = "ocr_line_geometry"
ANCHOR_SOURCE_APPROXIMATE = "approximate_block_row"

SOURCE_KIND_PDF = "pdf"
SOURCE_KIND_IMAGE = "image"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ============================================================================
# Attempt mode
# ============================================================================


def get_attempt_mode(conn: sqlite3.Connection, answer_file_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT attempt_mode FROM main_marking_answer_files WHERE answer_file_id = ?",
        (answer_file_id,),
    ).fetchone()
    return row[0] if row is not None else None


def set_attempt_mode(conn: sqlite3.Connection, answer_file_id: int, mode: str) -> None:
    if mode not in ATTEMPT_MODES:
        raise ValueError(f"Attempt mode must be one of {ATTEMPT_MODES}.")
    conn.execute(
        "UPDATE main_marking_answer_files SET attempt_mode = ? WHERE answer_file_id = ?",
        (mode, answer_file_id),
    )
    conn.commit()


# ============================================================================
# Separate answer paper pages
# ============================================================================


@dataclass
class SeparatePaperPage:
    sap_page_id: int
    answer_file_id: int
    page_number: int
    source_file_path: str
    source_original_filename: Optional[str]
    source_page_index: int
    source_kind: str
    file_checksum: Optional[str]
    width_px: Optional[int]
    height_px: Optional[int]
    original_image_path: Optional[str]
    preview_image_path: Optional[str]
    status: str
    message: Optional[str]
    created_at: str
    updated_at: Optional[str]


_PAGE_COLUMNS = (
    "sap_page_id, answer_file_id, page_number, source_file_path, source_original_filename, "
    "source_page_index, source_kind, file_checksum, width_px, height_px, original_image_path, "
    "preview_image_path, status, message, created_at, updated_at"
)


def add_separate_page(
    conn: sqlite3.Connection, answer_file_id: int, page_number: int, source_file_path: str, *,
    source_original_filename: Optional[str] = None, source_page_index: int = 0,
    source_kind: str = SOURCE_KIND_PDF, file_checksum: Optional[str] = None,
    width_px: Optional[int] = None, height_px: Optional[int] = None,
    original_image_path: Optional[str] = None, preview_image_path: Optional[str] = None,
    status: str = "uploaded", message: Optional[str] = None,
) -> SeparatePaperPage:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO separate_answer_paper_pages "
        "(answer_file_id, page_number, source_file_path, source_original_filename, source_page_index, "
        "source_kind, file_checksum, width_px, height_px, original_image_path, preview_image_path, "
        "status, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (answer_file_id, page_number, source_file_path, source_original_filename, source_page_index,
         source_kind, file_checksum, width_px, height_px, original_image_path, preview_image_path,
         status, message, now, now),
    )
    conn.commit()
    return get_separate_page(conn, cursor.lastrowid)


def get_separate_page(conn: sqlite3.Connection, sap_page_id: int) -> Optional[SeparatePaperPage]:
    row = conn.execute(
        f"SELECT {_PAGE_COLUMNS} FROM separate_answer_paper_pages WHERE sap_page_id = ?",
        (sap_page_id,),
    ).fetchone()
    return SeparatePaperPage(**dict(row)) if row is not None else None


def get_separate_pages(conn: sqlite3.Connection, answer_file_id: int) -> List[SeparatePaperPage]:
    rows = conn.execute(
        f"SELECT {_PAGE_COLUMNS} FROM separate_answer_paper_pages WHERE answer_file_id = ? "
        "ORDER BY page_number, sap_page_id",
        (answer_file_id,),
    ).fetchall()
    return [SeparatePaperPage(**dict(r)) for r in rows]


def set_separate_page_order(conn: sqlite3.Connection, ordered_page_ids: List[int]) -> None:
    """Renumber pages 1..N in the given order, atomically. Uses a temporary
    negative offset so the (answer_file_id, page_number) UNIQUE key never
    collides mid-update."""
    now = _now()
    for index, page_id in enumerate(ordered_page_ids, start=1):
        conn.execute(
            "UPDATE separate_answer_paper_pages SET page_number = ?, updated_at = ? WHERE sap_page_id = ?",
            (-index, now, page_id),
        )
    for index, page_id in enumerate(ordered_page_ids, start=1):
        conn.execute(
            "UPDATE separate_answer_paper_pages SET page_number = ? WHERE sap_page_id = ?",
            (index, page_id),
        )
    conn.commit()


def update_separate_page_render(
    conn: sqlite3.Connection, sap_page_id: int, *, original_image_path: Optional[str] = None,
    preview_image_path: Optional[str] = None, width_px: Optional[int] = None,
    height_px: Optional[int] = None, status: Optional[str] = None, message: Optional[str] = None,
) -> None:
    sets, values = [], []
    for column, value in (("original_image_path", original_image_path), ("preview_image_path", preview_image_path),
                          ("width_px", width_px), ("height_px", height_px), ("status", status), ("message", message)):
        if value is not None:
            sets.append(f"{column} = ?")
            values.append(value)
    if not sets:
        return
    sets.append("updated_at = ?")
    values.append(_now())
    values.append(sap_page_id)
    conn.execute(f"UPDATE separate_answer_paper_pages SET {', '.join(sets)} WHERE sap_page_id = ?", values)
    conn.commit()


def delete_separate_pages_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> None:
    conn.execute("DELETE FROM separate_answer_paper_pages WHERE answer_file_id = ?", (answer_file_id,))
    conn.commit()


# ============================================================================
# Target states
# ============================================================================


@dataclass
class SeparatePaperTargetState:
    target_state_id: int
    answer_file_id: int
    target_label: str
    state: str
    blank_confirmed: bool
    review_stale: bool
    teacher_final_answer: Optional[str]
    note: Optional[str]
    updated_by: Optional[int]
    created_at: str
    updated_at: Optional[str]


_TARGET_STATE_COLUMNS = (
    "target_state_id, answer_file_id, target_label, state, blank_confirmed, review_stale, "
    "teacher_final_answer, note, updated_by, created_at, updated_at"
)


def _row_to_target_state(row) -> SeparatePaperTargetState:
    data = dict(row)
    data["blank_confirmed"] = bool(data["blank_confirmed"])
    data["review_stale"] = bool(data["review_stale"])
    return SeparatePaperTargetState(**data)


def get_target_state(conn: sqlite3.Connection, answer_file_id: int, target_label: str) -> Optional[SeparatePaperTargetState]:
    row = conn.execute(
        f"SELECT {_TARGET_STATE_COLUMNS} FROM separate_paper_target_states "
        "WHERE answer_file_id = ? AND target_label = ?",
        (answer_file_id, target_label),
    ).fetchone()
    return _row_to_target_state(row) if row is not None else None


def get_target_states(conn: sqlite3.Connection, answer_file_id: int) -> List[SeparatePaperTargetState]:
    rows = conn.execute(
        f"SELECT {_TARGET_STATE_COLUMNS} FROM separate_paper_target_states WHERE answer_file_id = ? "
        "ORDER BY target_state_id",
        (answer_file_id,),
    ).fetchall()
    return [_row_to_target_state(r) for r in rows]


def upsert_target_state(
    conn: sqlite3.Connection, answer_file_id: int, target_label: str, *,
    state: Optional[str] = None, blank_confirmed: Optional[bool] = None,
    review_stale: Optional[bool] = None, teacher_final_answer: Optional[str] = None,
    note: Optional[str] = None, updated_by: Optional[int] = None,
    clear_teacher_final_answer: bool = False,
) -> SeparatePaperTargetState:
    if state is not None and state not in TARGET_STATES:
        raise ValueError(f"Target state must be one of {TARGET_STATES}.")
    now = _now()
    existing = get_target_state(conn, answer_file_id, target_label)
    if existing is None:
        conn.execute(
            "INSERT INTO separate_paper_target_states (answer_file_id, target_label, state, blank_confirmed, "
            "review_stale, teacher_final_answer, note, updated_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (answer_file_id, target_label, state or TARGET_STATE_UNRESOLVED, int(bool(blank_confirmed)),
             int(bool(review_stale)), teacher_final_answer, note, updated_by, now, now),
        )
    else:
        sets, values = [], []
        if state is not None:
            sets.append("state = ?"); values.append(state)
        if blank_confirmed is not None:
            sets.append("blank_confirmed = ?"); values.append(int(bool(blank_confirmed)))
        if review_stale is not None:
            sets.append("review_stale = ?"); values.append(int(bool(review_stale)))
        if clear_teacher_final_answer:
            sets.append("teacher_final_answer = ?"); values.append(None)
        elif teacher_final_answer is not None:
            sets.append("teacher_final_answer = ?"); values.append(teacher_final_answer)
        if note is not None:
            sets.append("note = ?"); values.append(note)
        if updated_by is not None:
            sets.append("updated_by = ?"); values.append(updated_by)
        sets.append("updated_at = ?"); values.append(now)
        values.append(existing.target_state_id)
        conn.execute(f"UPDATE separate_paper_target_states SET {', '.join(sets)} WHERE target_state_id = ?", values)
    conn.commit()
    return get_target_state(conn, answer_file_id, target_label)


def set_all_targets_stale(conn: sqlite3.Connection, answer_file_id: int, stale: bool) -> None:
    conn.execute(
        "UPDATE separate_paper_target_states SET review_stale = ?, updated_at = ? WHERE answer_file_id = ?",
        (int(bool(stale)), _now(), answer_file_id),
    )
    conn.commit()


# ============================================================================
# Mappings
# ============================================================================


@dataclass
class SeparatePaperMapping:
    mapping_id: int
    answer_file_id: int
    target_label: str
    paper: Optional[str]
    part: Optional[str]
    question_no: Optional[str]
    mapping_type: str
    sap_page_id: int
    x: float
    y: float
    width: float
    height: float
    page_width_px: Optional[int]
    page_height_px: Optional[int]
    reading_order: int
    is_continuation: bool
    original_ocr_text: Optional[str]
    original_ocr_confidence: Optional[float]
    rerun_ocr_text: Optional[str]
    rerun_ocr_confidence: Optional[float]
    rerun_ocr_at: Optional[str]
    corrected_text: Optional[str]
    crop_checksum: Optional[str]
    ocr_line_boxes_json: Optional[str]
    confirmed: bool
    created_by: Optional[int]
    created_at: str
    updated_at: Optional[str]

    @property
    def effective_text(self) -> Optional[str]:
        """Teacher-corrected text wins, then the rerun OCR, then the original
        OCR - the three are always stored separately."""
        if self.corrected_text is not None:
            return self.corrected_text
        if self.rerun_ocr_text is not None:
            return self.rerun_ocr_text
        return self.original_ocr_text

    @property
    def ocr_line_boxes(self) -> List[dict]:
        """Recognised line boxes for this crop, each normalised to the mapping
        rectangle. Empty when the engine returned no geometry."""
        if not self.ocr_line_boxes_json:
            return []
        try:
            boxes = json.loads(self.ocr_line_boxes_json)
        except (TypeError, ValueError):
            return []
        return boxes if isinstance(boxes, list) else []


_MAPPING_COLUMNS = (
    "mapping_id, answer_file_id, target_label, paper, part, question_no, mapping_type, sap_page_id, "
    "x, y, width, height, page_width_px, page_height_px, reading_order, is_continuation, "
    "original_ocr_text, original_ocr_confidence, rerun_ocr_text, rerun_ocr_confidence, rerun_ocr_at, "
    "corrected_text, crop_checksum, ocr_line_boxes_json, confirmed, created_by, created_at, updated_at"
)


def _row_to_mapping(row) -> SeparatePaperMapping:
    data = dict(row)
    data["is_continuation"] = bool(data["is_continuation"])
    data["confirmed"] = bool(data["confirmed"])
    return SeparatePaperMapping(**data)


def add_mapping(
    conn: sqlite3.Connection, answer_file_id: int, target_label: str, mapping_type: str,
    sap_page_id: int, x: float, y: float, width: float, height: float, *,
    paper: Optional[str] = None, part: Optional[str] = None, question_no: Optional[str] = None,
    page_width_px: Optional[int] = None, page_height_px: Optional[int] = None,
    reading_order: int = 1, is_continuation: bool = False, created_by: Optional[int] = None,
) -> SeparatePaperMapping:
    if mapping_type not in MAPPING_TYPES:
        raise ValueError(f"Mapping type must be one of {MAPPING_TYPES}.")
    now = _now()
    cursor = conn.execute(
        "INSERT INTO separate_paper_mappings (answer_file_id, target_label, paper, part, question_no, "
        "mapping_type, sap_page_id, x, y, width, height, page_width_px, page_height_px, reading_order, "
        "is_continuation, confirmed, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (answer_file_id, target_label, paper, part, question_no, mapping_type, sap_page_id,
         x, y, width, height, page_width_px, page_height_px, reading_order, int(bool(is_continuation)),
         created_by, now, now),
    )
    conn.commit()
    return get_mapping(conn, cursor.lastrowid)


def get_mapping(conn: sqlite3.Connection, mapping_id: int) -> Optional[SeparatePaperMapping]:
    row = conn.execute(
        f"SELECT {_MAPPING_COLUMNS} FROM separate_paper_mappings WHERE mapping_id = ?", (mapping_id,),
    ).fetchone()
    return _row_to_mapping(row) if row is not None else None


def get_mappings_for_target(conn: sqlite3.Connection, answer_file_id: int, target_label: str) -> List[SeparatePaperMapping]:
    rows = conn.execute(
        f"SELECT {_MAPPING_COLUMNS} FROM separate_paper_mappings "
        "WHERE answer_file_id = ? AND target_label = ? ORDER BY reading_order, mapping_id",
        (answer_file_id, target_label),
    ).fetchall()
    return [_row_to_mapping(r) for r in rows]


def get_mappings_for_answer_file(conn: sqlite3.Connection, answer_file_id: int) -> List[SeparatePaperMapping]:
    rows = conn.execute(
        f"SELECT {_MAPPING_COLUMNS} FROM separate_paper_mappings WHERE answer_file_id = ? "
        "ORDER BY target_label, reading_order, mapping_id",
        (answer_file_id,),
    ).fetchall()
    return [_row_to_mapping(r) for r in rows]


def update_mapping_geometry(
    conn: sqlite3.Connection, mapping_id: int, *, sap_page_id: Optional[int] = None,
    x: Optional[float] = None, y: Optional[float] = None,
    width: Optional[float] = None, height: Optional[float] = None,
    page_width_px: Optional[int] = None, page_height_px: Optional[int] = None,
    reading_order: Optional[int] = None,
) -> SeparatePaperMapping:
    sets, values = [], []
    for column, value in (("sap_page_id", sap_page_id), ("x", x), ("y", y), ("width", width),
                          ("height", height), ("page_width_px", page_width_px),
                          ("page_height_px", page_height_px), ("reading_order", reading_order)):
        if value is not None:
            sets.append(f"{column} = ?")
            values.append(value)
    if sets:
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(mapping_id)
        conn.execute(f"UPDATE separate_paper_mappings SET {', '.join(sets)} WHERE mapping_id = ?", values)
        conn.commit()
    return get_mapping(conn, mapping_id)


def set_mapping_original_ocr(conn: sqlite3.Connection, mapping_id: int, text: Optional[str],
                             confidence: Optional[float] = None, crop_checksum: Optional[str] = None) -> None:
    """Record the FIRST OCR for a mapping. Never overwritten by a rerun."""
    conn.execute(
        "UPDATE separate_paper_mappings SET original_ocr_text = ?, original_ocr_confidence = ?, "
        "crop_checksum = COALESCE(?, crop_checksum), updated_at = ? WHERE mapping_id = ?",
        (text, confidence, crop_checksum, _now(), mapping_id),
    )
    conn.commit()


def set_mapping_rerun_ocr(conn: sqlite3.Connection, mapping_id: int, text: Optional[str],
                          confidence: Optional[float] = None, crop_checksum: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE separate_paper_mappings SET rerun_ocr_text = ?, rerun_ocr_confidence = ?, rerun_ocr_at = ?, "
        "crop_checksum = COALESCE(?, crop_checksum), updated_at = ? WHERE mapping_id = ?",
        (text, confidence, _now(), crop_checksum, _now(), mapping_id),
    )
    conn.commit()


def set_mapping_ocr_line_boxes(conn: sqlite3.Connection, mapping_id: int,
                               boxes: Optional[List[dict]]) -> None:
    """Store (or clear) the OCR engine's per-line geometry for this mapping's
    crop, normalised to the mapping rectangle. Kept separate from the OCR text
    columns so it can be absent without affecting the text lineage."""
    payload = json.dumps(boxes) if boxes else None
    conn.execute(
        "UPDATE separate_paper_mappings SET ocr_line_boxes_json = ?, updated_at = ? WHERE mapping_id = ?",
        (payload, _now(), mapping_id),
    )
    conn.commit()


def set_mapping_corrected_text(conn: sqlite3.Connection, mapping_id: int, corrected_text: Optional[str]) -> None:
    conn.execute(
        "UPDATE separate_paper_mappings SET corrected_text = ?, updated_at = ? WHERE mapping_id = ?",
        (corrected_text, _now(), mapping_id),
    )
    conn.commit()


def set_mapping_confirmed(conn: sqlite3.Connection, mapping_id: int, confirmed: bool) -> None:
    conn.execute(
        "UPDATE separate_paper_mappings SET confirmed = ?, updated_at = ? WHERE mapping_id = ?",
        (int(bool(confirmed)), _now(), mapping_id),
    )
    conn.commit()


def delete_mapping(conn: sqlite3.Connection, mapping_id: int) -> None:
    conn.execute("DELETE FROM separate_paper_mappings WHERE mapping_id = ?", (mapping_id,))
    conn.commit()


# ============================================================================
# K1 parsed answers
# ============================================================================


@dataclass
class SeparatePaperParsedAnswer:
    parsed_id: int
    answer_file_id: int
    mapping_id: Optional[int]
    question_no: Optional[str]
    parsed_answer: Optional[str]
    source_text: Optional[str]
    confidence: Optional[float]
    reason: Optional[str]
    warning: Optional[str]
    has_conflict: bool
    teacher_answer: Optional[str]
    state: str
    anchor_x: Optional[float]
    anchor_y: Optional[float]
    anchor_width: Optional[float]
    anchor_height: Optional[float]
    anchor_source: str
    created_at: str
    updated_at: Optional[str]

    @property
    def has_exact_anchor(self) -> bool:
        """True only when the anchor came from real recognised OCR geometry."""
        return self.anchor_source == ANCHOR_SOURCE_OCR_LINE and self.anchor_y is not None

    @property
    def effective_answer(self) -> Optional[str]:
        """Teacher's answer wins over the parser's."""
        return self.teacher_answer if self.teacher_answer is not None else self.parsed_answer


_PARSED_COLUMNS = (
    "parsed_id, answer_file_id, mapping_id, question_no, parsed_answer, source_text, confidence, reason, "
    "warning, has_conflict, teacher_answer, state, anchor_x, anchor_y, anchor_width, anchor_height, "
    "anchor_source, created_at, updated_at"
)


def _row_to_parsed(row) -> SeparatePaperParsedAnswer:
    data = dict(row)
    data["has_conflict"] = bool(data["has_conflict"])
    return SeparatePaperParsedAnswer(**data)


def replace_parsed_answers_for_mapping(conn: sqlite3.Connection, answer_file_id: int, mapping_id: int,
                                       rows: List[dict]) -> List[SeparatePaperParsedAnswer]:
    """Replace this block mapping's parsed rows. Any teacher answer/state
    already recorded for a question number is carried across so a re-parse
    never silently discards a teacher decision."""
    previous = {p.question_no: p for p in get_parsed_answers_for_mapping(conn, mapping_id)}
    conn.execute("DELETE FROM separate_paper_parsed_answers WHERE mapping_id = ?", (mapping_id,))
    now = _now()
    for row in rows:
        prior = previous.get(row.get("question_no"))
        conn.execute(
            "INSERT INTO separate_paper_parsed_answers (answer_file_id, mapping_id, question_no, parsed_answer, "
            "source_text, confidence, reason, warning, has_conflict, teacher_answer, state, anchor_x, anchor_y, "
            "anchor_width, anchor_height, anchor_source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (answer_file_id, mapping_id, row.get("question_no"), row.get("parsed_answer"),
             row.get("source_text"), row.get("confidence"), row.get("reason"), row.get("warning"),
             int(bool(row.get("has_conflict"))),
             prior.teacher_answer if prior else None,
             (prior.state if prior and prior.teacher_answer is not None else PARSED_STATE_UNCONFIRMED),
             row.get("anchor_x"), row.get("anchor_y"), row.get("anchor_width"), row.get("anchor_height"),
             row.get("anchor_source") or ANCHOR_SOURCE_APPROXIMATE,
             now, now),
        )
    conn.commit()
    return get_parsed_answers_for_mapping(conn, mapping_id)


def get_parsed_answers_for_mapping(conn: sqlite3.Connection, mapping_id: int) -> List[SeparatePaperParsedAnswer]:
    rows = conn.execute(
        f"SELECT {_PARSED_COLUMNS} FROM separate_paper_parsed_answers WHERE mapping_id = ? "
        "ORDER BY CAST(question_no AS INTEGER), parsed_id",
        (mapping_id,),
    ).fetchall()
    return [_row_to_parsed(r) for r in rows]


def get_parsed_answers(conn: sqlite3.Connection, answer_file_id: int) -> List[SeparatePaperParsedAnswer]:
    rows = conn.execute(
        f"SELECT {_PARSED_COLUMNS} FROM separate_paper_parsed_answers WHERE answer_file_id = ? "
        "ORDER BY CAST(question_no AS INTEGER), parsed_id",
        (answer_file_id,),
    ).fetchall()
    return [_row_to_parsed(r) for r in rows]


def update_parsed_answer(conn: sqlite3.Connection, parsed_id: int, *, teacher_answer: Optional[str] = None,
                         state: Optional[str] = None, clear_teacher_answer: bool = False,
                         has_conflict: Optional[bool] = None) -> SeparatePaperParsedAnswer:
    sets, values = [], []
    if clear_teacher_answer:
        sets.append("teacher_answer = ?"); values.append(None)
    elif teacher_answer is not None:
        sets.append("teacher_answer = ?"); values.append(teacher_answer)
    if state is not None:
        sets.append("state = ?"); values.append(state)
    if has_conflict is not None:
        sets.append("has_conflict = ?"); values.append(int(bool(has_conflict)))
    if sets:
        sets.append("updated_at = ?"); values.append(_now())
        values.append(parsed_id)
        conn.execute(f"UPDATE separate_paper_parsed_answers SET {', '.join(sets)} WHERE parsed_id = ?", values)
        conn.commit()
    row = conn.execute(f"SELECT {_PARSED_COLUMNS} FROM separate_paper_parsed_answers WHERE parsed_id = ?",
                       (parsed_id,)).fetchone()
    return _row_to_parsed(row) if row is not None else None
