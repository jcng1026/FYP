"""Kertas 2 Cross-Encoder single-item prediction adapter (Stage 12D).

Produces a DRAFT prediction (predicted normalized score + feedback
category) for ONE Kertas 2 answer item, given an already-trained/active
Cross-Encoder model version (see app/services/k2_cross_encoder_training_
service.py, Stage 12C). This is prediction only:
- It never writes to kertas2_feedback_review_items or any other table.
- It never finalizes a review.
- It is NOT wired into the Marking workflow in this stage.

It exists so Stage 12D's evaluation service (app/services/
k2_cross_encoder_evaluation_service.py) and a later marking-integration
stage share exactly one predictor implementation.

Dependency policy: identical to k2_cross_encoder_training_service - torch/
transformers are imported lazily, only inside _real_predict, so importing
this module never fails when they are absent. Callers without the
dependencies (or tests) inject the deterministic, dependency-free
_fake_predict stand-in via predictor_fn - the same injection pattern
Stage 12C established for _train_fake_cross_encoder.

DATA QUALITY NOTE: _fake_predict is a crude word-overlap heuristic, never
a real model prediction. Every prediction made with it is stamped
demo_mode=True with a "warning" field so callers never mistake it for a
real Cross-Encoder result.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.models.ai_model_registry_model import AIModelVersion
from app.services.k2_cross_encoder_training_service import (
    MissingMLDependencyError,
    check_ml_dependencies_available,
)
from app.services.k2_training_dataset_service import (
    FEEDBACK_CATEGORY_CORRECT,
    FEEDBACK_CATEGORY_INCORRECT,
    FEEDBACK_CATEGORY_MISSING_ANSWER,
    FEEDBACK_CATEGORY_PARTIAL,
)


@dataclass
class K2PredictionInput:
    question_text: Optional[str]
    marking_scheme_text: Optional[str]
    expected_answer_text: Optional[str]
    student_answer_text: Optional[str]
    max_mark: float


def _build_reference_text(item: K2PredictionInput) -> str:
    parts = [item.question_text, item.marking_scheme_text, item.expected_answer_text]
    return " ".join(str(part).strip() for part in parts if part and str(part).strip())


def _fake_predict(item: K2PredictionInput, model_version: AIModelVersion) -> dict:
    """Deterministic, dependency-free stand-in - a crude word-overlap
    heuristic between the student answer and the question/marking-scheme/
    expected-answer text, never a real model prediction. Used by tests and
    by evaluation/prediction whenever no real predictor is available -
    always surfaced to callers as demo_mode=True (see predict_k2_answer_item)."""
    student_answer = (item.student_answer_text or "").strip()
    if not student_answer:
        return {
            "predicted_normalized_score": 0.0,
            "predicted_feedback_category": FEEDBACK_CATEGORY_MISSING_ANSWER,
            "confidence": None,
        }

    reference_text = _build_reference_text(item)
    student_words = set(student_answer.lower().split())
    reference_words = set(reference_text.lower().split())
    overlap = (len(student_words & reference_words) / len(reference_words)) if reference_words else 0.0
    score = max(0.0, min(1.0, overlap))

    if score >= 0.75:
        category = FEEDBACK_CATEGORY_CORRECT
    elif score <= 0.15:
        category = FEEDBACK_CATEGORY_INCORRECT
    else:
        category = FEEDBACK_CATEGORY_PARTIAL

    return {"predicted_normalized_score": round(score, 4), "predicted_feedback_category": category, "confidence": None}


def _real_predict(item: K2PredictionInput, model_version: AIModelVersion) -> dict:
    """Real Cross-Encoder inference using the backbone/tokenizer/head saved
    by _train_real_cross_encoder (see k2_cross_encoder_training_service) at
    model_version.model_path. torch/transformers are imported lazily here
    only - see check_ml_dependencies_available(), called before this
    function is ever selected.

    NOTE: like _train_real_cross_encoder, this exact code path could not be
    executed in the environment this stage was built in (torch/transformers
    are not installed here - see the Stage 12D report's dependency
    findings). It follows the same saved-artifact layout _train_real_
    cross_encoder writes, but has not been run end-to-end locally; treat it
    as reviewed-but-unverified until exercised with the dependencies
    installed and a real trained model version.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not model_version.model_path:
        raise MissingMLDependencyError(
            f"Model version {model_version.version_label} has no saved storage path to load."
        )
    model_dir = Path(model_version.model_path)
    label_map_path = model_dir / "label_map.json"
    head_path = model_dir / "head.pt"
    if not label_map_path.is_file() or not head_path.is_file():
        raise MissingMLDependencyError(
            f"Model version {model_version.version_label} has no real saved model artifacts at "
            f"{model_dir} (label_map.json/head.pt missing) - it may have been trained with the fake "
            "trainer stand-in, or the dependencies were unavailable at training time."
        )

    label_to_index = json.loads(label_map_path.read_text(encoding="utf-8"))
    index_to_label = {index: label for label, index in label_to_index.items()}

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    backbone = AutoModel.from_pretrained(str(model_dir))

    # Must stay structurally identical to _MultiTaskHead in
    # k2_cross_encoder_training_service._train_real_cross_encoder so the
    # saved head.pt state dict loads correctly.
    class _MultiTaskHead(torch.nn.Module):
        def __init__(self, hidden_size, num_categories):
            super().__init__()
            self.regression_head = torch.nn.Linear(hidden_size, 1)
            self.classification_head = torch.nn.Linear(hidden_size, num_categories)

        def forward(self, pooled):
            score = torch.sigmoid(self.regression_head(pooled)).squeeze(-1)
            logits = self.classification_head(pooled)
            return score, logits

    head = _MultiTaskHead(backbone.config.hidden_size, len(label_to_index))
    head.load_state_dict(torch.load(head_path, map_location=device))
    backbone.to(device)
    head.to(device)
    backbone.eval()
    head.eval()

    text_a = _build_reference_text(item)
    text_b = item.student_answer_text or ""
    encoded = tokenizer([text_a], [text_b], padding=True, truncation=True, max_length=256, return_tensors="pt")
    encoded = {key: value.to(device) for key, value in encoded.items()}

    with torch.no_grad():
        outputs = backbone(input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"])
        pooled = outputs.last_hidden_state[:, 0, :]
        score_pred, logits = head(pooled)
        probabilities = torch.softmax(logits, dim=-1)
        predicted_index = int(probabilities.argmax(dim=-1).item())
        confidence = float(probabilities[0, predicted_index].item())

    return {
        "predicted_normalized_score": round(float(score_pred.item()), 4),
        "predicted_feedback_category": index_to_label.get(predicted_index, FEEDBACK_CATEGORY_PARTIAL),
        "confidence": round(confidence, 4),
    }


def predict_k2_answer_item(
    item: K2PredictionInput, model_version: AIModelVersion, predictor_fn: Optional[Callable] = None,
) -> dict:
    """Produce ONE draft prediction for item, scored by model_version.

    Never finalizes anything - the caller owns any review/finalization
    decision. Raises MissingMLDependencyError if predictor_fn is None and
    torch/transformers aren't installed.

    Returns a dict with predicted_normalized_score, predicted_score
    (normalized_score * item.max_mark), predicted_feedback_category,
    confidence (None for the fake predictor), model_version_id, demo_mode,
    and warning (a human-readable caveat, only set when demo_mode is True).
    """
    active_predictor_fn = predictor_fn
    demo_mode = False
    if active_predictor_fn is None:
        available, message = check_ml_dependencies_available()
        if not available:
            raise MissingMLDependencyError(message)
        active_predictor_fn = _real_predict
    else:
        demo_mode = active_predictor_fn is _fake_predict

    raw = active_predictor_fn(item, model_version)
    predicted_normalized_score = raw["predicted_normalized_score"]
    predicted_score = round(predicted_normalized_score * (item.max_mark or 0), 2)

    warning = None
    if demo_mode:
        warning = (
            "This prediction was produced by a dependency-free fake predictor stand-in (torch/transformers "
            "not installed, or explicitly injected for testing/demo purposes) - it is NOT a real model "
            "prediction and must not be treated as accurate."
        )

    return {
        "predicted_normalized_score": predicted_normalized_score,
        "predicted_score": predicted_score,
        "predicted_feedback_category": raw["predicted_feedback_category"],
        "confidence": raw.get("confidence"),
        "model_version_id": model_version.model_id,
        "demo_mode": demo_mode,
        "warning": warning,
    }
