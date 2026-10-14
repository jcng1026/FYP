"""Marking setup and marking question editing logic for the Teacher role.

This stage stores marking setup only (linked template, spelling deduction,
default question mark, Kertas 1 answer key, Kertas 2 rubric placeholders).
No OCR, answer extraction, or actual scoring happens here.
"""

import sqlite3
from typing import List, Optional

from app.models.marking_setup_model import (
    KERTAS_1_QUESTION_TYPES,
    KERTAS_2_QUESTION_TYPES,
    MarkingQuestion,
    MarkingQuestionRow,
    MarkingSetup,
    create_marking_question,
    create_marking_setup as create_marking_setup_record,
    delete_marking_question as delete_marking_question_record,
    get_marking_question_by_id,
    get_marking_questions_for_setup,
    get_marking_setup_by_id,
    get_marking_setup_by_material,
    get_max_question_display_order,
    update_marking_question as update_marking_question_record,
    update_marking_setup as update_marking_setup_record,
)
from app.models.revision_material_model import ALLOWED_PAPER_TYPES, PAPER_TYPE_KERTAS_1, get_material_by_id
from app.models.template_model import get_region_by_id
from app.services.template_service import get_owned_template
from app.services.user_service import validate_teacher_exists

DEFAULT_SPELLING_DEDUCTION = -1.0
DEFAULT_QUESTION_MARK = 1.0


def _get_owned_material(conn: sqlite3.Connection, teacher_id: int, material_id: int):
    material = get_material_by_id(conn, material_id)
    if material is None:
        raise ValueError("Revision material not found.")
    if material.teacher_id != teacher_id:
        raise ValueError("You can only set up marking for your own revision materials.")
    return material


def save_marking_setup(
    conn: sqlite3.Connection,
    teacher_id: int,
    material_id: int,
    template_id: Optional[int],
    spelling_deduction: float,
    default_question_mark: float,
) -> MarkingSetup:
    """Create or update the marking setup for material_id, owned by teacher_id.

    If a setup already exists for this material it is updated in place
    (template_id/spelling_deduction/default_question_mark), rather than
    rejected as a duplicate.

    Raises ValueError if the requester is not a teacher, the material isn't
    owned by teacher_id, the material's paper type isn't Kertas 1/2, the
    template (if given) isn't owned by teacher_id or its paper type doesn't
    match the material's, or default_question_mark isn't greater than zero.
    """
    if not validate_teacher_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can create marking setups.")

    material = _get_owned_material(conn, teacher_id, material_id)

    if material.paper_type not in ALLOWED_PAPER_TYPES:
        raise ValueError("Paper type must be Kertas 1 or Kertas 2.")

    if template_id is not None:
        template = get_owned_template(conn, teacher_id, template_id)
        if template.paper_type != material.paper_type:
            raise ValueError("The linked template's paper type must match the revision material's paper type.")

    spelling_deduction = float(spelling_deduction)
    default_question_mark = float(default_question_mark)
    if default_question_mark <= 0:
        raise ValueError("Default question mark must be greater than zero.")

    existing = get_marking_setup_by_material(conn, material_id)
    if existing is None:
        return create_marking_setup_record(
            conn,
            material_id=material_id,
            teacher_id=teacher_id,
            template_id=template_id,
            paper_type=material.paper_type,
            spelling_deduction=spelling_deduction,
            default_question_mark=default_question_mark,
        )

    update_marking_setup_record(conn, existing.setup_id, template_id, spelling_deduction, default_question_mark)
    return get_marking_setup_by_id(conn, existing.setup_id)


def get_owned_marking_setup(conn: sqlite3.Connection, teacher_id: int, setup_id: int) -> MarkingSetup:
    setup = get_marking_setup_by_id(conn, setup_id)
    if setup is None:
        raise ValueError("Marking setup not found.")
    if setup.teacher_id != teacher_id:
        raise ValueError("You can only manage marking setups for your own revision materials.")
    return setup


def get_marking_setup_for_material(
    conn: sqlite3.Connection, teacher_id: int, material_id: int
) -> Optional[MarkingSetup]:
    """Return the marking setup for material_id, or None if one hasn't been created yet.

    Raises ValueError if the material itself doesn't exist or isn't owned by teacher_id.
    """
    _get_owned_material(conn, teacher_id, material_id)
    return get_marking_setup_by_material(conn, material_id)


def _validate_question_fields(
    paper_type: str,
    question_no: str,
    correct_answer: str,
    max_mark: float,
    question_type: str,
) -> tuple:
    question_no = (question_no or "").strip()
    if not question_no:
        raise ValueError("Question number is required.")

    allowed_types = KERTAS_1_QUESTION_TYPES if paper_type == PAPER_TYPE_KERTAS_1 else KERTAS_2_QUESTION_TYPES
    if question_type not in allowed_types:
        raise ValueError(f"Question type must be one of: {', '.join(allowed_types)} for {paper_type}.")

    correct_answer = (correct_answer or "").strip()
    if paper_type == PAPER_TYPE_KERTAS_1 and not correct_answer:
        raise ValueError("Correct answer is required for Kertas 1 questions.")

    if max_mark <= 0:
        raise ValueError("Max mark must be greater than zero.")

    return question_no, correct_answer


def _validate_region_for_setup(conn: sqlite3.Connection, setup: MarkingSetup, region_id: Optional[int]) -> None:
    if region_id is None:
        return
    if setup.template_id is None:
        raise ValueError("This marking setup has no linked template, so a region cannot be selected.")
    region = get_region_by_id(conn, region_id)
    if region is None or region.template_id != setup.template_id:
        raise ValueError("The selected region does not belong to the linked template.")


def add_marking_question(
    conn: sqlite3.Connection,
    teacher_id: int,
    setup_id: int,
    question_no: str,
    correct_answer: str,
    max_mark: float,
    question_type: str,
    explanation: str = "",
    region_id: Optional[int] = None,
    display_order: Optional[int] = None,
) -> MarkingQuestion:
    """Add a question/criterion row to a marking setup owned by teacher_id.

    display_order defaults to appending after the last existing question; pass
    an explicit value to place it elsewhere.

    Raises ValueError if the setup doesn't exist or isn't owned by
    teacher_id, any field is invalid, or region_id doesn't belong to the
    setup's linked template.
    """
    setup = get_owned_marking_setup(conn, teacher_id, setup_id)

    question_no, correct_answer = _validate_question_fields(
        setup.paper_type, question_no, correct_answer, max_mark, question_type
    )
    _validate_region_for_setup(conn, setup, region_id)

    final_display_order = display_order if display_order is not None else get_max_question_display_order(conn, setup_id) + 1
    return create_marking_question(
        conn, setup_id, question_no, correct_answer, max_mark, question_type,
        (explanation or "").strip() or None, region_id, final_display_order,
    )


def update_marking_question(
    conn: sqlite3.Connection,
    teacher_id: int,
    question_id: int,
    question_no: str,
    correct_answer: str,
    max_mark: float,
    question_type: str,
    explanation: str = "",
    region_id: Optional[int] = None,
    display_order: Optional[int] = None,
) -> MarkingQuestion:
    """Update an existing marking question/criterion.

    Raises ValueError if the question doesn't exist, its setup isn't owned
    by teacher_id, any field is invalid, or region_id doesn't belong to the
    setup's linked template.
    """
    question = get_marking_question_by_id(conn, question_id)
    if question is None:
        raise ValueError("Marking question not found.")
    setup = get_owned_marking_setup(conn, teacher_id, question.setup_id)

    question_no, correct_answer = _validate_question_fields(
        setup.paper_type, question_no, correct_answer, max_mark, question_type
    )
    _validate_region_for_setup(conn, setup, region_id)

    final_display_order = display_order if display_order is not None else question.display_order
    update_marking_question_record(
        conn, question_id, question_no, correct_answer, max_mark, question_type,
        (explanation or "").strip() or None, region_id, final_display_order,
    )
    return get_marking_question_by_id(conn, question_id)


def delete_marking_question(conn: sqlite3.Connection, teacher_id: int, question_id: int) -> None:
    """Delete a marking question/criterion belonging to one of teacher_id's own setups.

    Raises ValueError if the question doesn't exist or its setup isn't owned by teacher_id.
    """
    question = get_marking_question_by_id(conn, question_id)
    if question is None:
        raise ValueError("Marking question not found.")
    get_owned_marking_setup(conn, teacher_id, question.setup_id)

    delete_marking_question_record(conn, question_id)


def list_marking_questions(conn: sqlite3.Connection, teacher_id: int, setup_id: int) -> List[MarkingQuestionRow]:
    get_owned_marking_setup(conn, teacher_id, setup_id)
    return get_marking_questions_for_setup(conn, setup_id)
