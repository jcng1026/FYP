"""Kertas 2 training dataset export foundation (Stage 12B).

Prepares Core AI 1's future training source (see docs/stage12_ai_plan.md):
a CSV/JSONL snapshot of teacher-reviewed (finalized) Kertas 2 examples,
suitable for a future Cross-Encoder training stage (12C+). Nothing here
trains a model, runs inference, or generates feedback - this is a data
export/preparation step only, using stdlib csv/json exclusively (no
pandas, no ML dependency).

Only *finalized* kertas2_feedback_reviews rows are ever collected -
draft/unreviewed AI feedback (kertas2_ai_feedback_jobs/items) is never a
training label source, matching the same "finalization, not review, makes
data usable" rule already established by app/models/result_summary_model.py
for the Results page.

Known data gap: this codebase has no stored "question_text" (the actual
question wording) anywhere in the Kertas 2 pipeline - only a question
number (criterion_name) and the marking scheme's correct/sample answer.
question_text is always exported blank until a future stage adds it.
Similarly, there is no separate "marking scheme narrative" distinct from
the expected answer text, so marking_scheme_text and expected_answer_text
are populated from the same underlying field (sample_answer).
"""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from app.models.ai_model_registry_model import (
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
    create_training_dataset,
    get_training_dataset_by_id,
    get_training_datasets_for_teacher,
)
from app.services.user_service import validate_ai_manager_exists
from app.utils.file_storage import get_ai_training_dataset_paths

DATASET_FORMAT_CSV_JSONL = "csv_jsonl"

FEEDBACK_CATEGORY_CORRECT = "correct"
FEEDBACK_CATEGORY_PARTIAL = "partial"
FEEDBACK_CATEGORY_INCORRECT = "incorrect"
FEEDBACK_CATEGORY_MISSING_ANSWER = "missing_answer"

# Exact column order for both the CSV header row and every JSONL row's key
# order - keeping both formats aligned makes the two outputs easy to
# cross-check by hand.
DATASET_ROW_FIELDS = (
    "example_id",
    "source_type",
    "source_id",
    "teacher_id",
    "class_id",
    "class_name",
    "student_id",
    "student_code",
    "student_name",
    "paper_type",
    "question_number",
    "question_text",
    "marking_scheme_text",
    "expected_answer_text",
    "student_answer_text",
    "max_score",
    "teacher_final_score",
    "normalized_score",
    "feedback_category",
    "teacher_feedback_text",
    "reviewed_at",
    "created_at",
)

_COLLECT_EXAMPLES_SQL = """
    SELECT
        kri.kertas2_review_item_id AS source_id,
        kr.teacher_id AS teacher_id,
        ra.class_id AS class_id,
        c.class_name AS class_name,
        u.user_id AS student_id,
        u.student_code AS student_code,
        u.full_name AS student_name,
        rm.paper_type AS paper_type,
        kri.criterion_name AS question_number,
        kri.sample_answer AS expected_answer_text,
        kri.student_answer AS student_answer_text,
        kri.max_mark AS max_score,
        kri.final_score AS teacher_final_score,
        kri.final_feedback AS teacher_feedback_text,
        kr.finalized_at AS reviewed_at,
        kri.created_at AS created_at
    FROM kertas2_feedback_review_items kri
    JOIN kertas2_feedback_reviews kr ON kr.kertas2_review_id = kri.kertas2_review_id
    JOIN revision_attempts ra ON ra.attempt_id = kr.attempt_id
    JOIN revision_materials rm ON rm.material_id = ra.material_id
    JOIN classes c ON c.class_id = ra.class_id
    JOIN users u ON u.user_id = ra.student_id
    WHERE kr.status = 'finalized' AND kr.teacher_id = ?
    ORDER BY kr.finalized_at DESC, kri.kertas2_review_item_id
"""


def _derive_feedback_category(
    student_answer_text: Optional[str], final_score: float, max_score: Optional[float]
) -> str:
    """Dataset-label preparation only - not AI inference, not model
    training. A missing/blank student answer always takes priority over a
    score-based category, per the Stage 12B spec."""
    if not student_answer_text or not student_answer_text.strip():
        return FEEDBACK_CATEGORY_MISSING_ANSWER
    if max_score and max_score > 0:
        if final_score >= max_score:
            return FEEDBACK_CATEGORY_CORRECT
        if final_score <= 0:
            return FEEDBACK_CATEGORY_INCORRECT
        return FEEDBACK_CATEGORY_PARTIAL
    # max_score missing/zero: fall back to a simple score-only split.
    return FEEDBACK_CATEGORY_INCORRECT if not final_score or final_score <= 0 else FEEDBACK_CATEGORY_PARTIAL


def collect_k2_training_examples(conn: sqlite3.Connection, teacher_id: int) -> List[dict]:
    """Collect every teacher-reviewed (finalized) Kertas 2 review item
    owned by teacher_id into one training-example dict per item, matching
    DATASET_ROW_FIELDS exactly. Draft/unreviewed AI feedback and Kertas 1
    rows are never included - only finalized kertas2_feedback_reviews.
    Raises ValueError if teacher_id isn't a teacher account."""
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can export Kertas 2 training datasets.")

    rows = conn.execute(_COLLECT_EXAMPLES_SQL, (teacher_id,)).fetchall()

    examples = []
    for row in rows:
        data = dict(row)
        max_score = data["max_score"]
        final_score = data["teacher_final_score"]
        student_answer_text = data["student_answer_text"]

        normalized_score = round(final_score / max_score, 4) if max_score and max_score > 0 else None
        feedback_category = _derive_feedback_category(student_answer_text, final_score, max_score)

        examples.append({
            "example_id": f"k2_review_item_{data['source_id']}",
            "source_type": "kertas2_feedback_review_item",
            "source_id": data["source_id"],
            "teacher_id": data["teacher_id"],
            "class_id": data["class_id"],
            "class_name": data["class_name"],
            "student_id": data["student_id"],
            "student_code": data["student_code"],
            "student_name": data["student_name"],
            "paper_type": data["paper_type"],
            "question_number": data["question_number"],
            "question_text": None,  # not stored anywhere in this pipeline - see module docstring
            "marking_scheme_text": data["expected_answer_text"],
            "expected_answer_text": data["expected_answer_text"],
            "student_answer_text": student_answer_text,
            "max_score": max_score,
            "teacher_final_score": final_score,
            "normalized_score": normalized_score,
            "feedback_category": feedback_category,
            "teacher_feedback_text": data["teacher_feedback_text"],
            "reviewed_at": data["reviewed_at"],
            "created_at": data["created_at"],
        })
    return examples


def _write_csv(csv_path: str, examples: List[dict]) -> None:
    # utf-8-sig (BOM) so Excel opens the file cleanly, matching the same
    # encoding convention already used by main_marking_export_service.py.
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_ROW_FIELDS)
        writer.writeheader()
        for example in examples:
            writer.writerow(example)


def _write_jsonl(jsonl_path: str, examples: List[dict]) -> None:
    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for example in examples:
            ordered = {field: example.get(field) for field in DATASET_ROW_FIELDS}
            handle.write(json.dumps(ordered, ensure_ascii=False) + "\n")


def _summarize_examples(examples: List[dict]) -> dict:
    category_counts: dict = {}
    for example in examples:
        category = example["feedback_category"]
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "row_count": len(examples),
        "feedback_category_counts": category_counts,
        "distinct_students": len({e["student_id"] for e in examples}),
        "distinct_classes": len({e["class_id"] for e in examples}),
    }


def export_k2_training_dataset(
    conn: sqlite3.Connection, teacher_id: int, dataset_name: Optional[str] = None,
) -> dict:
    """Collect teacher_id's teacher-reviewed Kertas 2 examples and export
    them to CSV + JSONL under data/ai_training_datasets/, recording one
    ai_training_datasets row. Raises ValueError with a clear message if no
    reviewed examples exist yet - never trains anything, never creates an
    ai_model_versions or ai_training_jobs row."""
    examples = collect_k2_training_examples(conn, teacher_id)
    if not examples:
        raise ValueError("No teacher-reviewed Kertas 2 examples available for export.")

    if not dataset_name or not dataset_name.strip():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dataset_name = f"k2_dataset_{timestamp}"
    dataset_name = dataset_name.strip()

    csv_path, jsonl_path = get_ai_training_dataset_paths(teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, dataset_name)
    _write_csv(csv_path, examples)
    _write_jsonl(jsonl_path, examples)

    summary = _summarize_examples(examples)
    dataset = create_training_dataset(
        conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, dataset_name, DATASET_FORMAT_CSV_JSONL,
        len(examples), csv_path, jsonl_path,
        summary_json=json.dumps(summary), source_filter_json=json.dumps({"status": "finalized"}),
    )

    return {
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.dataset_name,
        "row_count": dataset.row_count,
        "csv_path": dataset.csv_path,
        "jsonl_path": dataset.jsonl_path,
        "summary": summary,
    }


def _dataset_to_dict(dataset) -> dict:
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.dataset_name,
        "dataset_format": dataset.dataset_format,
        "row_count": dataset.row_count,
        "csv_path": dataset.csv_path,
        "jsonl_path": dataset.jsonl_path,
        "summary": json.loads(dataset.summary_json) if dataset.summary_json else None,
        "created_at": dataset.created_at,
    }


def list_k2_training_datasets(conn: sqlite3.Connection, teacher_id: int, limit: int = 10) -> List[dict]:
    datasets = get_training_datasets_for_teacher(conn, teacher_id, MODEL_KEY_K2_SHORT_ANSWER_SCORING, limit)
    return [_dataset_to_dict(dataset) for dataset in datasets]


def get_k2_training_dataset(conn: sqlite3.Connection, teacher_id: int, dataset_id: int) -> dict:
    dataset = get_training_dataset_by_id(conn, dataset_id)
    if dataset is None:
        raise ValueError("Training dataset not found.")
    if dataset.teacher_id != teacher_id:
        raise ValueError("You can only view your own training datasets.")
    return _dataset_to_dict(dataset)
