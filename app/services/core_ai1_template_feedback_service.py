"""Deterministic, teacher-review-only Core AI 1 feedback templates."""

from app.models.core_ai1_template_feedback_types import (
    TEMPLATE_CATEGORY_MAPPING_VERSION,
    TEMPLATE_FEEDBACK_VERSION,
    TemplateFeedbackResult,
)


_CATEGORY_TEXT = {
    "correct": "The response meets the expected standard for this task. The teacher should confirm that the final feedback reflects the marking scheme.",
    "partial": "The response shows some relevant achievement but needs further development. The teacher should identify the most useful next step from the marking scheme.",
    "incorrect": "The response does not yet meet the expected standard. The teacher should explain the relevant requirement and an appropriate next step.",
    "not_attempted": "No assessable response was provided for this task.",
}

_ISSUE_TEXT = {
    "task_fulfilment": "Check that every required element of the task has been addressed.",
    "organisation": "Review the organisation and sequencing of ideas.",
    "grammar": "Review the grammar issues identified for teacher attention.",
    "spelling": "Review the spelling issues identified for teacher attention.",
    "vocabulary": "Review the vocabulary issue identified for teacher attention.",
}

_PART_TEXT = {
    "part1": "Part 1 response",
    "part2": "Part 2 response",
    "part3": "Part 3 response",
}


class TemplateFeedbackService:
    """Generates deterministic draft text; it never changes or derives a score."""

    def generate(self, request):
        warnings = []
        part_text = _PART_TEXT.get(str(request.part).lower(), "Response")

        if request.student_answer_blank:
            category_text = "No student answer was present for this task. The teacher should confirm the blank-answer status."
        else:
            category_text = _CATEGORY_TEXT.get(request.feedback_category)
            if category_text is None:
                category_text = "This response requires teacher attention before final feedback is issued."
                warnings.append("Unknown feedback category was mapped to the neutral teacher-attention template.")

        sentences = [f"{part_text}: {category_text}"]
        if not request.marking_scheme_available:
            sentences.append("A marking scheme was not available to this generator, so the teacher must verify the feedback against the approved criteria.")
            warnings.append("Marking scheme unavailable.")

        seen = set()
        for tag in request.issue_tags:
            if tag in seen:
                continue
            seen.add(tag)
            text = _ISSUE_TEXT.get(tag)
            if text:
                sentences.append(text)
            else:
                warnings.append(f"Unsupported issue tag ignored: {tag}")

        sentences.append("This is an editable draft for teacher review and must not be released to a student until finalised by a teacher.")
        return TemplateFeedbackResult(
            generated_text=" ".join(sentences),
            template_version=TEMPLATE_FEEDBACK_VERSION,
            category_mapping_version=TEMPLATE_CATEGORY_MAPPING_VERSION,
            generation_source="deterministic_template",
            input_checksum=request.input_checksum,
            warnings=tuple(warnings),
        )
