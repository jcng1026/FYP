"""Answer-scheme text parsing (objective answer-list preview).

Pure/stateless PDF text-layer parsing used by the "Preview Answer Scheme
Answers" feature (subject_profile_service.preview_answer_scheme_answer_list /
preview_answer_scheme_formatted_text). The former rule-based region
SUGGESTION engine that used to live in this module was removed once the
trained Core AI 2 detector became the region-proposal source - proposals now
come from ai_region_proposal_service + the Core AI backend.

Column-aware: a real two-column answer list is parsed one column at a time
(the same gap position must repeat across several rows before a split is
believed), so left/right entries sharing a page row never merge into one
garbled line, and an objective/cloze row's own widely-spaced options are
never misread as a column gutter.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pymupdf


QUESTION_NUMBER_PUNCT_PATTERN = re.compile(r"^(?:question\s+)?(\d{1,3})[\.\)]", re.IGNORECASE)
QUESTION_NUMBER_BARE_PATTERN = re.compile(r"^(\d{1,3})\s+[A-D]\b")
OPTION_LETTER_PATTERN = re.compile(r"^([A-D])[\.\)]?$")
PART_HEADER_PATTERN = re.compile(r"^part\s*[1-5]\b", re.IGNORECASE)
ANSWER_SCHEME_ENTRY_PATTERN = re.compile(r"^(\d{1,3})[\.\)]\s*([A-D])\b")
_EMBEDDED_ANSWER_ENTRY_PATTERN = re.compile(r"\d{1,3}[\.\)]\s*[A-D]\b")


@dataclass
class ParsedAnswerSchemeEntry:
    question_no: str
    answer: str
    confidence: float
    source_line: str

@dataclass
class _TextLine:
    text: str
    bbox: Tuple[float, float, float, float]
    words: List[tuple] = field(default_factory=list)

def _group_words_into_lines(words: list, y_tolerance: float = 4.0) -> List[_TextLine]:
    """Group PyMuPDF page.get_text('words') tuples (x0, y0, x1, y1, text,
    block_no, line_no, word_no) into visual lines by Y-coordinate proximity
    - deliberately NOT relying on PyMuPDF's own block_no/line_no grouping,
    which can merge or split lines in ways that don't match visual layout
    for text placed via varying tools/producers. Returns lines top-to-bottom,
    each with its words left-to-right."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    raw_lines: List[list] = []
    current: list = [sorted_words[0]]
    current_y = sorted_words[0][1]
    for w in sorted_words[1:]:
        if abs(w[1] - current_y) <= y_tolerance:
            current.append(w)
        else:
            raw_lines.append(current)
            current = [w]
            current_y = w[1]
    raw_lines.append(current)

    lines = []
    for raw in raw_lines:
        ordered = sorted(raw, key=lambda w: w[0])
        text = " ".join(w[4] for w in ordered)
        x0 = min(w[0] for w in ordered)
        y0 = min(w[1] for w in ordered)
        x1 = max(w[2] for w in ordered)
        y1 = max(w[3] for w in ordered)
        lines.append(_TextLine(text=text, bbox=(x0, y0, x1, y1), words=ordered))
    return lines

def _detect_column_split_x(lines: List[_TextLine], page_width: float) -> Optional[float]:
    """Return the x-coordinate of a real 2-column gutter if the page's
    OWN rows consistently share one, else None (single column). Requires
    a similarly-positioned gap to appear in at least 3 different rows -
    a hallmark of genuine 2-column typesetting (e.g. a real answer
    scheme's left/right answer lists) - so a handful of sparsely-placed
    lines (or one row's own internal word spacing) never gets misread as
    a column split."""
    min_gap_width = page_width * 0.06
    gap_centers = []
    for line in lines:
        if len(line.words) < 2:
            continue
        if _line_is_inline_cloze_row(line):
            # An objective/cloze row's own A/B/C/D options are naturally
            # spread across the full page width - that gap recurs across
            # many rows just like a real column gutter would, but it is
            # NOT one; only a genuine (non-cloze) row may vote.
            continue
        ordered = sorted(line.words, key=lambda w: w[0])
        best_gap, best_center = 0.0, None
        for a, b in zip(ordered, ordered[1:]):
            gap = b[0] - a[2]
            if gap > best_gap:
                best_gap, best_center = gap, (a[2] + b[0]) / 2
        if best_gap >= min_gap_width and page_width * 0.25 <= best_center <= page_width * 0.75:
            gap_centers.append(best_center)

    if len(gap_centers) < 3:
        return None
    gap_centers.sort()
    median = gap_centers[len(gap_centers) // 2]
    close = [c for c in gap_centers if abs(c - median) <= page_width * 0.08]
    if len(close) < 3:
        return None
    return sum(close) / len(close)

def _match_question_number(stripped_text: str) -> Optional[str]:
    """Return the matched question number as a string, or None. Tries the
    punctuated forms ("1.", "1)", "Question 1") first, then a bare number
    immediately followed by an option letter ("10 A ran", "33 B ...") -
    the second form is deliberately narrow (requires the option-letter
    signal) so an ordinary sentence starting with a number never matches."""
    match = QUESTION_NUMBER_PUNCT_PATTERN.match(stripped_text)
    if match:
        return match.group(1)
    match = QUESTION_NUMBER_BARE_PATTERN.match(stripped_text)
    if match:
        return match.group(1)
    return None


def _leading_number_word_count(stripped_text: str) -> int:
    return 2 if stripped_text.lower().startswith("question") else 1


def _line_is_inline_cloze_row(line: "_TextLine") -> bool:
    """True if line starts with a recognized question number AND its own
    remaining words already contain 2+ inline option letters (e.g. "9 A as
    B but C so D and") - the single shared signal used both to skip a
    redundant question_area for such a row (see _suggest_question_numbers_
    and_areas) and to exclude it from column-gutter voting (see
    _detect_column_split_x): a cloze row's options are naturally spread
    wide across the FULL page width, which otherwise looks exactly like a
    real 2-column gutter to a naive gap-position heuristic.

    Before a real 2-column page has actually been split into columns, a
    row's own text is the two columns' rows MERGED onto one line (same Y,
    different X) - e.g. a real answer-key row "1. C ..." merged with a
    same-height "20. B ..." row from the other column becomes "1. C ...
    20. B ...", which ALSO has 2 inline "option letters" (C and B) despite
    being two completely unrelated entries, not a real cloze row. The
    giveaway: a genuine cloze row's remaining text never contains ANOTHER
    "<n>. <letter>"-shaped fragment further along the line, so any such
    embedded match rules this out as a cloze row (letting column
    detection un-merge it correctly instead)."""
    stripped = line.text.strip()
    match = QUESTION_NUMBER_PUNCT_PATTERN.match(stripped) or QUESTION_NUMBER_BARE_PATTERN.match(stripped)
    if match is None or not line.words:
        return False
    if _EMBEDDED_ANSWER_ENTRY_PATTERN.search(stripped[match.end():]):
        return False
    leading_word_count = _leading_number_word_count(stripped)
    remaining = line.words[leading_word_count:]
    return sum(1 for w in remaining if OPTION_LETTER_PATTERN.match(w[4])) >= 2

def _split_words_by_detected_columns(words: list, page_width: float) -> List[list]:
    preliminary_lines = _group_words_into_lines(words)
    split_x = _detect_column_split_x(preliminary_lines, page_width)
    if split_x is None:
        return [words]
    left_words = [w for w in words if (w[0] + w[2]) / 2 < split_x]
    right_words = [w for w in words if (w[0] + w[2]) / 2 >= split_x]
    return [left_words, right_words]

def parse_answer_scheme_answer_list(pdf_path: str, page_number: Optional[int] = None) -> List[ParsedAnswerSchemeEntry]:
    """Detect simple objective answer-list lines ("1. A", "2) C", ...) in
    pdf_path (a Subject Profile's answer scheme PDF) and return a plain,
    structured preview list - never writes to any answer key, never
    raises (returns [] for any unreadable PDF/page or parsing failure).
    Column-aware (Stage 12E-2 Quality Pass): a real two-column answer list
    is parsed one column at a time, so a left-column entry and a right-
    column entry that happen to sit on the same page row never merge into
    one garbled line. "Part 1"/"Part 2" section headers are recognized as
    boundaries only (consistent with region suggestion's own Part-header
    handling) - they do not produce their own entry here (see
    parse_answer_scheme_preview for a Part-grouped display string)."""
    try:
        with pymupdf.open(pdf_path) as document:
            page_numbers = [page_number] if page_number is not None else list(range(1, document.page_count + 1))
            entries: List[ParsedAnswerSchemeEntry] = []
            for page_no in page_numbers:
                if page_no < 1 or page_no > document.page_count:
                    continue
                page = document[page_no - 1]
                words = page.get_text("words")
                if not words:
                    continue
                page_width = page.rect.width
                for column_words in _split_words_by_detected_columns(words, page_width):
                    for line in _group_words_into_lines(column_words):
                        stripped = line.text.strip()
                        match = ANSWER_SCHEME_ENTRY_PATTERN.match(stripped)
                        if match:
                            entries.append(ParsedAnswerSchemeEntry(
                                question_no=match.group(1), answer=match.group(2),
                                confidence=0.75, source_line=stripped,
                            ))
            entries.sort(key=lambda e: int(e.question_no))
            return entries
    except Exception:
        return []

def parse_answer_scheme_preview(pdf_path: str, page_number: Optional[int] = None) -> str:
    """A clean, human-readable, Part-grouped preview string built from
    parse_answer_scheme_answer_list plus each page's own Part/section
    headings (kept where possible, per Stage 12E-2 Quality Pass
    requirement 3) - never writes anything, never raises (returns "" on
    any failure)."""
    try:
        entries = parse_answer_scheme_answer_list(pdf_path, page_number=page_number)
        if not entries:
            return ""

        with pymupdf.open(pdf_path) as document:
            page_numbers = [page_number] if page_number is not None else list(range(1, document.page_count + 1))
            part_headers: List[str] = []
            for page_no in page_numbers:
                if page_no < 1 or page_no > document.page_count:
                    continue
                page = document[page_no - 1]
                words = page.get_text("words")
                if not words:
                    continue
                for line in _group_words_into_lines(words):
                    stripped = line.text.strip()
                    if PART_HEADER_PATTERN.match(stripped) and stripped not in part_headers:
                        part_headers.append(stripped)

        lines = []
        if part_headers:
            lines.append(" / ".join(part_headers))
        for entry in entries:
            lines.append(f"{entry.question_no}. {entry.answer}")
        return "\n".join(lines)
    except Exception:
        return ""
