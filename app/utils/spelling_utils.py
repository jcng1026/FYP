"""Conservative, standard-library-only spelling-error heuristics for
Kertas 1 short-word/written answers.

This is a simple rule-based check (normalized edit distance), not a real
spellchecker and not AI - it only flags a small, high-confidence set of
"likely typo" cases so Kertas 1 marking can apply a small spelling
deduction instead of marking a near-correct written answer fully wrong.
When in doubt, these functions favour returning False (not a spelling
error) over incorrectly flagging an unrelated answer.
"""

from typing import Optional

# Below this length, only a very small typo (edit distance <= 2) counts -
# short words differ a lot in meaning per character, so distance must stay
# tiny to avoid flagging unrelated short answers as typos.
_SHORT_ANSWER_LENGTH_THRESHOLD = 5
_SHORT_ANSWER_MAX_DISTANCE = 2
_SHORT_ANSWER_MAX_LENGTH_DIFF = 2

# For longer words/phrases, require both a small absolute edit distance and
# a high similarity ratio, so long unrelated answers never qualify.
_LONG_ANSWER_MAX_DISTANCE = 2
_LONG_ANSWER_MAX_LENGTH_DIFF = 1
_LONG_ANSWER_MIN_SIMILARITY = 0.65


def normalize_answer_text(text: Optional[str]) -> str:
    """Lowercase, strip, remove punctuation, and collapse internal
    whitespace so answers can be compared fairly."""
    if not text:
        return ""
    lowered = text.strip().lower()
    cleaned = "".join(char for char in lowered if char.isalnum() or char.isspace())
    return " ".join(cleaned.split())


def calculate_edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein (single-character insert/delete/substitute)
    edit distance between a and b, using only the Python standard library."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i]
        for j, char_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            substitute_cost = previous_row[j - 1] + (0 if char_a == char_b else 1)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        previous_row = current_row
    return previous_row[-1]


def is_likely_spelling_error(student_answer: Optional[str], correct_answer: Optional[str]) -> bool:
    """Conservatively decide whether student_answer looks like a small typo
    of correct_answer, rather than a genuinely wrong or unrelated answer.

    Returns False (not a spelling error) for: an empty student answer, an
    exact match (that's just correct), a missing correct_answer, or any
    answer whose edit distance/length difference is too large to be
    confident it's "the same word/phrase with a typo" rather than a
    different answer entirely.
    """
    normalized_student = normalize_answer_text(student_answer)
    normalized_correct = normalize_answer_text(correct_answer)

    if not normalized_student or not normalized_correct:
        return False
    if normalized_student == normalized_correct:
        return False

    distance = calculate_edit_distance(normalized_student, normalized_correct)
    length_diff = abs(len(normalized_student) - len(normalized_correct))

    if len(normalized_correct) <= _SHORT_ANSWER_LENGTH_THRESHOLD:
        return distance <= _SHORT_ANSWER_MAX_DISTANCE and length_diff <= _SHORT_ANSWER_MAX_LENGTH_DIFF

    longer_length = max(len(normalized_student), len(normalized_correct))
    similarity = 1 - (distance / longer_length)
    return (
        distance <= _LONG_ANSWER_MAX_DISTANCE
        and length_diff <= _LONG_ANSWER_MAX_LENGTH_DIFF
        and similarity >= _LONG_ANSWER_MIN_SIMILARITY
    )
