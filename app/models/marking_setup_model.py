"""Marking setup and marking question data model and database access functions."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

QUESTION_TYPE_MCQ = "mcq"
QUESTION_TYPE_WRITTEN_LETTER = "written_letter"
QUESTION_TYPE_SHORT_WORD = "short_word"
QUESTION_TYPE_WRITING_PART = "writing_part"
QUESTION_TYPE_RUBRIC_CRITERION = "rubric_criterion"
QUESTION_TYPE_OTHER = "other"

KERTAS_1_QUESTION_TYPES = [
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_WRITTEN_LETTER,
    QUESTION_TYPE_SHORT_WORD,
    QUESTION_TYPE_OTHER,
]

KERTAS_2_QUESTION_TYPES = [
    QUESTION_TYPE_WRITING_PART,
    QUESTION_TYPE_RUBRIC_CRITERION,
    QUESTION_TYPE_OTHER,
]

DEFAULT_KERTAS_2_RUBRIC_CRITERIA = [
    "Content / Task Fulfilment",
    "Organisation",
    "Grammar",
    "Vocabulary",
    "Spelling and Punctuation",
    "Format / Word Count",
]


@dataclass
class MarkingSetup:
    setup_id: int
    material_id: int
    teacher_id: int
    template_id: Optional[int]
    paper_type: str
    spelling_deduction: float
    default_question_mark: float
    created_at: str
    updated_at: str


@dataclass
class MarkingQuestion:
    question_id: int
    setup_id: int
    question_no: str
    correct_answer: str
    max_mark: float
    explanation: Optional[str]
    question_type: str
    region_id: Optional[int]
    display_order: int


@dataclass
class MarkingQuestionRow:
    """One row per marking question, with the linked region's label joined in."""

    question_id: int
    setup_id: int
    question_no: str
    correct_answer: str
    max_mark: float
    explanation: Optional[str]
    question_type: str
    region_id: Optional[int]
    region_label: Optional[str]
    display_order: int


def create_marking_setup(
    conn: sqlite3.Connection,
    material_id: int,
    teacher_id: int,
    template_id: Optional[int],
    paper_type: str,
    spelling_deduction: float,
    default_question_mark: float,
) -> MarkingSetup:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor = conn.execute(
        "INSERT INTO marking_setups "
        "(material_id, teacher_id, template_id, paper_type, spelling_deduction, default_question_mark, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (material_id, teacher_id, template_id, paper_type, spelling_deduction, default_question_mark, now, now),
    )
    conn.commit()
    return MarkingSetup(
        setup_id=cursor.lastrowid,
        material_id=material_id,
        teacher_id=teacher_id,
        template_id=template_id,
        paper_type=paper_type,
        spelling_deduction=spelling_deduction,
        default_question_mark=default_question_mark,
        created_at=now,
        updated_at=now,
    )


def update_marking_setup(
    conn: sqlite3.Connection,
    setup_id: int,
    template_id: Optional[int],
    spelling_deduction: float,
    default_question_mark: float,
) -> None:
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE marking_setups SET template_id = ?, spelling_deduction = ?, default_question_mark = ?, "
        "updated_at = ? WHERE setup_id = ?",
        (template_id, spelling_deduction, default_question_mark, updated_at, setup_id),
    )
    conn.commit()


def get_marking_setup_by_id(conn: sqlite3.Connection, setup_id: int) -> Optional[MarkingSetup]:
    row = conn.execute(
        "SELECT setup_id, material_id, teacher_id, template_id, paper_type, spelling_deduction, "
        "default_question_mark, created_at, updated_at FROM marking_setups WHERE setup_id = ?",
        (setup_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingSetup(**dict(row))


def get_marking_setup_by_material(conn: sqlite3.Connection, material_id: int) -> Optional[MarkingSetup]:
    row = conn.execute(
        "SELECT setup_id, material_id, teacher_id, template_id, paper_type, spelling_deduction, "
        "default_question_mark, created_at, updated_at FROM marking_setups WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingSetup(**dict(row))


def get_marking_setups_by_template(conn: sqlite3.Connection, template_id: int) -> List[MarkingSetup]:
    """Return every marking setup configured against template_id, most
    recently created first (Stage 11Q - used to find a Kertas 1 marking
    setup/correct-answer source for a Main Marking session linked to the
    same template). Ordinarily at most one revision material is set up
    against a given template, but this is not schema-enforced, so callers
    should treat the first (most recent) row as the one to use."""
    rows = conn.execute(
        "SELECT setup_id, material_id, teacher_id, template_id, paper_type, spelling_deduction, "
        "default_question_mark, created_at, updated_at FROM marking_setups "
        "WHERE template_id = ? ORDER BY created_at DESC, setup_id DESC",
        (template_id,),
    ).fetchall()
    return [MarkingSetup(**dict(row)) for row in rows]


def create_marking_question(
    conn: sqlite3.Connection,
    setup_id: int,
    question_no: str,
    correct_answer: str,
    max_mark: float,
    question_type: str,
    explanation: Optional[str],
    region_id: Optional[int],
    display_order: int,
) -> MarkingQuestion:
    cursor = conn.execute(
        "INSERT INTO marking_questions "
        "(setup_id, question_no, correct_answer, max_mark, explanation, question_type, region_id, display_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (setup_id, question_no, correct_answer, max_mark, explanation, question_type, region_id, display_order),
    )
    conn.commit()
    return MarkingQuestion(
        question_id=cursor.lastrowid,
        setup_id=setup_id,
        question_no=question_no,
        correct_answer=correct_answer,
        max_mark=max_mark,
        explanation=explanation,
        question_type=question_type,
        region_id=region_id,
        display_order=display_order,
    )


def update_marking_question(
    conn: sqlite3.Connection,
    question_id: int,
    question_no: str,
    correct_answer: str,
    max_mark: float,
    question_type: str,
    explanation: Optional[str],
    region_id: Optional[int],
    display_order: int,
) -> None:
    conn.execute(
        "UPDATE marking_questions SET question_no = ?, correct_answer = ?, max_mark = ?, explanation = ?, "
        "question_type = ?, region_id = ?, display_order = ? WHERE question_id = ?",
        (question_no, correct_answer, max_mark, explanation, question_type, region_id, display_order, question_id),
    )
    conn.commit()


def get_marking_question_by_id(conn: sqlite3.Connection, question_id: int) -> Optional[MarkingQuestion]:
    row = conn.execute(
        "SELECT question_id, setup_id, question_no, correct_answer, max_mark, explanation, question_type, "
        "region_id, display_order FROM marking_questions WHERE question_id = ?",
        (question_id,),
    ).fetchone()
    if row is None:
        return None
    return MarkingQuestion(**dict(row))


def get_max_question_display_order(conn: sqlite3.Connection, setup_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(display_order) FROM marking_questions WHERE setup_id = ?", (setup_id,)
    ).fetchone()
    return row[0] if row[0] is not None else 0


def get_marking_questions_for_setup(conn: sqlite3.Connection, setup_id: int) -> List[MarkingQuestionRow]:
    rows = conn.execute(
        """
        SELECT mq.question_id, mq.setup_id, mq.question_no, mq.correct_answer, mq.max_mark, mq.explanation,
               mq.question_type, mq.region_id, tr.label AS region_label, mq.display_order
        FROM marking_questions mq
        LEFT JOIN template_regions tr ON tr.region_id = mq.region_id
        WHERE mq.setup_id = ?
        ORDER BY mq.display_order
        """,
        (setup_id,),
    ).fetchall()
    return [MarkingQuestionRow(**dict(row)) for row in rows]


def delete_marking_question(conn: sqlite3.Connection, question_id: int) -> None:
    conn.execute("DELETE FROM marking_questions WHERE question_id = ?", (question_id,))
    conn.commit()
