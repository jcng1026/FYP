"""Stage 12G-1B - K1 numbered-answer block parser (pure, no database).

Parses a Kertas 1 answer block OCR'd from a separate answer paper into
(question number, answer) pairs, together with the evidence a teacher needs to
judge each one: the exact source text, a documented confidence heuristic, and
explicit warnings/conflicts.

The parser NEVER silently resolves a conflict: a duplicated question number
with different answers is reported on every affected row, and the teacher
decides. It also never invents an answer for a question it did not see.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Separators seen on real answer papers: "1. A", "1) A", "1: A", "1 - A",
# "1 A" (whitespace only). En/em dashes included because OCR emits them.
_PAIR_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"                                   # not mid-token
    r"(?P<num>\d{1,3})"                                   # question number
    r"(?:"
    #  punctuation separator: the answer may be a word OR a lone digit, so an
    #  OCR confusion like "O" read as "0" is still surfaced (never dropped).
    r"(?P<sep_p>\s*[.)\:\-–—]\s*)(?P<ans_p>[A-Za-z][A-Za-z'’\-]*|\d)(?![\d])"
    r"|"
    #  whitespace-only separator: the answer must be alphabetic, otherwise
    #  "1 2" (two question numbers) would be misread as question 1 answer 2.
    r"(?P<sep_w>\s+)(?P<ans_w>[A-Za-z][A-Za-z'’\-]*)"
    r")"
)

# A bare answer-looking token with no number in front of it.
_BARE_ANSWER_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?P<ans>[A-Za-z][A-Za-z'’\-]*)")

# Lines that are headings/labels, not answers.
_HEADING_PATTERN = re.compile(
    r"^\s*(part|section|bahagian|answers?|jawapan|name|nama|class|kelas|kertas|paper|page)\b",
    re.IGNORECASE,
)

# Digits an OCR commonly emits for these letters (and vice versa).
_OCR_DIGIT_FOR_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
_LETTER_FOR_OCR_DIGIT = {v: k for k, v in _OCR_DIGIT_FOR_LETTER.items()}

# A single-letter MCQ answer is normally within this range.
_MCQ_LETTERS = set("ABCDEFGH")

MAX_REASONABLE_ANSWER_LEN = 20


@dataclass
class ParsedAnswerRow:
    """One (question number, answer) candidate plus its evidence."""
    question_no: Optional[str]
    parsed_answer: Optional[str]
    source_text: str
    confidence: float
    reason: str
    warning: Optional[str] = None
    has_conflict: bool = False
    # Block-relative approximate anchor (0-1 within the parsed block), derived
    # from the token's line index and character offset. None when unknown.
    anchor_x: Optional[float] = None
    anchor_y: Optional[float] = None
    anchor_width: Optional[float] = None
    anchor_height: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "question_no": self.question_no, "parsed_answer": self.parsed_answer,
            "source_text": self.source_text, "confidence": self.confidence, "reason": self.reason,
            "warning": self.warning, "has_conflict": self.has_conflict,
            "anchor_x": self.anchor_x, "anchor_y": self.anchor_y,
            "anchor_width": self.anchor_width, "anchor_height": self.anchor_height,
        }


@dataclass
class ParseResult:
    rows: List[ParsedAnswerRow] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unparsed_lines: List[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(r.has_conflict for r in self.rows)

    def by_question(self) -> Dict[str, List[ParsedAnswerRow]]:
        grouped: Dict[str, List[ParsedAnswerRow]] = {}
        for row in self.rows:
            if row.question_no is not None:
                grouped.setdefault(row.question_no, []).append(row)
        return grouped


def _confidence_for(separator: str, answer: str, has_warning: bool) -> Tuple[float, str]:
    """Documented heuristic - not a model score. Punctuation separators and
    short MCQ letters are the most reliable shapes seen on real papers."""
    stripped = separator.strip()
    if stripped and len(answer) == 1 and answer.upper() in _MCQ_LETTERS:
        score, reason = 0.90, f"numbered pair with '{stripped}' separator and a single-letter answer"
    elif stripped:
        score, reason = 0.80, f"numbered pair with '{stripped}' separator and a word answer"
    elif len(answer) == 1 and answer.upper() in _MCQ_LETTERS:
        score, reason = 0.75, "number and single-letter answer separated by spaces only"
    else:
        score, reason = 0.65, "number and word answer separated by spaces only"
    if has_warning:
        score -= 0.20
        reason += "; reduced because a warning was raised"
    return round(max(0.10, min(0.99, score)), 2), reason


def _anchor_for(line_index: int, total_lines: int, start_col: int, end_col: int,
                line_length: int) -> Tuple[float, float, float, float]:
    """Approximate block-relative anchor from the token's line/character
    position. Approximate by construction (plain OCR text carries no word
    boxes) - callers must treat it as a hint, never as exact geometry."""
    total_lines = max(total_lines, 1)
    line_length = max(line_length, 1)
    y = line_index / total_lines
    height = 1.0 / total_lines
    x = start_col / line_length
    width = max((end_col - start_col) / line_length, 0.01)
    return round(x, 4), round(y, 4), round(min(width, 1.0 - x), 4), round(height, 4)


def _looks_like_ocr_confusion(question_no: str, answer: str) -> Optional[str]:
    if len(answer) == 1 and answer in _OCR_DIGIT_FOR_LETTER:
        return (f"answer '{answer}' is a digit - OCR may have read "
                f"'{_OCR_DIGIT_FOR_LETTER[answer]}' as '{answer}'")
    if len(answer) == 1 and answer.upper() in _LETTER_FOR_OCR_DIGIT and answer.upper() not in _MCQ_LETTERS:
        return f"answer '{answer}' may be a misread digit"
    if not question_no.isdigit():
        return f"question number '{question_no}' is not purely numeric"
    return None


def parse_k1_answer_block(
    text: Optional[str],
    *,
    expected_question_numbers: Optional[Sequence[str]] = None,
    valid_answers: Optional[Sequence[str]] = None,
) -> ParseResult:
    """Parse a K1 numbered-answer block.

    expected_question_numbers - question numbers this paper actually has; a
    parsed number outside the set is WARNED about (never dropped).
    valid_answers - allowed answer tokens (e.g. A-D); an answer outside the
    set is WARNED about (never corrected).
    """
    result = ParseResult()
    if not text or not text.strip():
        result.warnings.append("No text to parse - the block OCR returned nothing.")
        return result

    expected = {str(q).strip() for q in expected_question_numbers} if expected_question_numbers else None
    allowed = {str(a).strip().upper() for a in valid_answers} if valid_answers else None

    lines = [ln for ln in text.splitlines()]
    total_lines = len(lines)

    for line_index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if _HEADING_PATTERN.match(line):
            continue

        matches = list(_PAIR_PATTERN.finditer(raw_line))
        if not matches:
            # A line with answer-looking tokens but no numbers at all.
            bare = _BARE_ANSWER_PATTERN.findall(line)
            if bare:
                warning = "answer(s) found without a question number"
                confidence, reason = _confidence_for("", bare[0], True)
                result.rows.append(ParsedAnswerRow(
                    question_no=None, parsed_answer=None, source_text=line,
                    confidence=confidence, reason="unnumbered answer text", warning=warning,
                    has_conflict=False))
                result.warnings.append(f"Line {line_index + 1}: {warning} ({line!r})")
            elif re.search(r"\d", line):
                result.rows.append(ParsedAnswerRow(
                    question_no=re.search(r"\d{1,3}", line).group(0), parsed_answer=None,
                    source_text=line, confidence=0.30, reason="question number without an answer",
                    warning="no answer found for this question number"))
                result.warnings.append(f"Line {line_index + 1}: question number without an answer ({line!r})")
            else:
                result.unparsed_lines.append(line)
            continue

        for match in matches:
            question_no = match.group("num")
            answer = match.group("ans_p") if match.group("ans_p") is not None else match.group("ans_w")
            separator = match.group("sep_p") if match.group("sep_p") is not None else match.group("sep_w")
            warnings: List[str] = []

            confusion = _looks_like_ocr_confusion(question_no, answer)
            if confusion:
                warnings.append(confusion)
            if expected is not None and question_no not in expected:
                warnings.append(f"question {question_no} is not a question in this paper")
            if allowed is not None and answer.strip().upper() not in allowed:
                warnings.append(f"answer '{answer}' is not one of the expected answers")
            if len(answer) > MAX_REASONABLE_ANSWER_LEN:
                warnings.append(f"answer is unusually long ({len(answer)} characters) - check the crop")

            warning_text = "; ".join(warnings) or None
            confidence, reason = _confidence_for(separator, answer, bool(warnings))
            answer_group = "ans_p" if match.group("ans_p") is not None else "ans_w"
            ax, ay, aw, ah = _anchor_for(line_index, total_lines, match.start(answer_group),
                                         match.end(answer_group), len(raw_line))
            result.rows.append(ParsedAnswerRow(
                question_no=question_no, parsed_answer=answer, source_text=match.group(0).strip(),
                confidence=confidence, reason=reason, warning=warning_text,
                anchor_x=ax, anchor_y=ay, anchor_width=aw, anchor_height=ah))
            if warning_text:
                result.warnings.append(f"Q{question_no}: {warning_text}")

    _flag_duplicate_conflicts(result)
    return result


def _flag_duplicate_conflicts(result: ParseResult) -> None:
    """Mark every row of a duplicated question number. Differing answers are a
    CONFLICT the teacher must resolve; identical repeats are only a warning."""
    for question_no, rows in result.by_question().items():
        if len(rows) < 2:
            continue
        answers = {(r.parsed_answer or "").strip().upper() for r in rows}
        if len(answers) > 1:
            listed = ", ".join(sorted(a for a in answers if a))
            message = f"question {question_no} appears {len(rows)} times with different answers ({listed})"
            for row in rows:
                row.has_conflict = True
                row.warning = "; ".join(filter(None, [row.warning, "conflicting duplicate - teacher must resolve"]))
            result.conflicts.append(message)
        else:
            message = f"question {question_no} appears {len(rows)} times with the same answer"
            for row in rows:
                row.warning = "; ".join(filter(None, [row.warning, "duplicate entry"]))
            result.warnings.append(message)


def missing_question_numbers(result: ParseResult, expected_question_numbers: Sequence[str]) -> List[str]:
    """Expected question numbers the parser produced no answer for. These are
    UNRESOLVED - never assumed blank."""
    found = {r.question_no for r in result.rows if r.question_no and r.parsed_answer}
    return [str(q) for q in expected_question_numbers if str(q) not in found]
