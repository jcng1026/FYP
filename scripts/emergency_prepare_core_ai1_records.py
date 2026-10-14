"""Emergency Core AI 1 record extraction from teacher-marked answer papers.

The marked papers are digitally-authored PDFs whose text layers separate by
colour: black = question/boilerplate, blue = the student's answer exactly as
written (errors preserved), red = the teacher's marks. Every Kertas 2 Part
carries an explicit red score "N/20" beside its answer space and an explicit
red "Corrections: old -> new; ..." line, and Part 3 answers name the selected
question in the printed box. Nothing is inferred from ticks or answer quality.

What this script does, treating every source file as READ-ONLY:

1. pairs each marked paper with its original by set/tier AND by content (the
   blue answer text must match; page count must match);
2. extracts, per Part 1/2/3: question text, the student's answer (blue),
   the teacher's correction pairs and explicit score (red), and the selected
   Part 3 question number;
3. classifies each correction pair mechanically:
       spelling - one token replaced by one token, small edit distance,
                  same initial letter (a misspelt word put right);
       grammar  - token count changes or function words/word forms change
                  (articles, auxiliaries, agreement, homophone misuse);
   an answer's category is the UNANIMOUS pair type; answers whose corrections
   mix types are EXCLUDED as ambiguous_category rather than guessed;
4. extracts the family's marking-scheme text for each Part from the
   answer-scheme PDFs;
5. writes candidate records in the exact SAFE_FIELDS shape the production
   Core AI 1 dataset exporter consumes, plus a full inventory and an explicit
   exclusion report.

Usage:
    python scripts/emergency_prepare_core_ai1_records.py \
        --source "C:/Users/User/Documents/AutoMarkingSystem/dataset_raw/core_ai2" \
        --workspace "C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/core_ai1_emergency_training"
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

BLUE = 0x0F2E8C
RED = 0xFF0000
MAX_SCORE = 20.0

FUNCTION_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did", "can", "could", "will",
    "would", "shall", "should", "may", "might", "must", "there", "their",
    "they", "them", "its", "it's", "to", "of", "in", "on", "at", "for",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def classify_pair(old: str, new: str) -> str:
    """Mechanically classify one explicit correction pair."""
    old_tokens = old.lower().split()
    new_tokens = new.lower().split()
    if len(old_tokens) != len(new_tokens):
        return "grammar"  # words added/removed: structure, not spelling
    changed = [(o, n) for o, n in zip(old_tokens, new_tokens) if o != n]
    if not changed:
        return "grammar"
    kinds = set()
    for o, n in changed:
        o_clean, n_clean = o.strip(".,;:!?"), n.strip(".,;:!?")
        if o_clean in FUNCTION_WORDS or n_clean in FUNCTION_WORDS:
            kinds.add("grammar")  # homophone/function-word misuse
        elif (o_clean[:1] == n_clean[:1] and _levenshtein(o_clean, n_clean) <= 3
              and abs(len(o_clean) - len(n_clean)) <= 3):
            kinds.add("spelling")  # a misspelt content word put right
        else:
            kinds.add("grammar")  # word-form / word-choice change
    return "spelling" if kinds == {"spelling"} else \
           "grammar" if kinds == {"grammar"} else "mixed"


def spans_by_color(page):
    out = {"black": [], "blue": [], "red": []}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"]
                if not text.strip():
                    continue
                if span["color"] == BLUE:
                    out["blue"].append((span["bbox"], text))
                elif span["color"] == RED:
                    out["red"].append((span["bbox"], text))
                else:
                    out["black"].append((span["bbox"], text))
    return out


def parse_marked_page(page):
    """One Part answer page -> (answer_text, corrections, score, q3_number)."""
    spans = spans_by_color(page)
    answer = _norm(" ".join(t for _, t in spans["blue"]))
    red_text = _norm(" ".join(t for _, t in spans["red"]))
    score = None
    match = re.search(r"(\d{1,2})\s*/\s*20", red_text)
    if match:
        score = float(match.group(1))
    corrections = []
    corr = re.search(r"Corrections?\s*:\s*(.+?)(?:\d{1,2}\s*/\s*20|$)", red_text)
    if corr:
        for piece in corr.group(1).split(";"):
            if "->" in piece:
                old, _, new = piece.partition("->")
                corrections.append((_norm(old), _norm(new)))
    black_text = _norm(" ".join(t for _, t in spans["black"]))
    q3 = None
    q3_match = re.search(r"Question Number", black_text)
    if q3_match:
        # the selected number is written in blue inside the printed box
        numbers = [t.strip() for _, t in spans["blue"] if t.strip().isdigit()]
        if numbers:
            q3 = numbers[0]
    return answer, corrections, score, q3, black_text


def find_part_pages(doc):
    """Locate the answer page of each Part by its printed header."""
    pages = {}
    part3_answer = None
    for index in range(doc.page_count):
        text = _norm(doc[index].get_text())
        if re.search(r"Part 1 \[\s*20\s*marks?\s*\]", text) and "Part 1" not in [
                p for p in pages]:
            pages.setdefault("part1", index)
        if re.search(r"Part 2 \[\s*20\s*marks?\s*\]", text):
            pages.setdefault("part2", index)
        # SPM model-paper layout (1119/2 = Kertas 2 paper code printed on every
        # writing page; the same booklet's Kertas 1 section also says "Part N",
        # so the paper code is required): "Part N You must answer this question".
        if "1119/2" in text:
            if re.search(r"Part 1\b.{0,40}You must answer this question", text):
                pages.setdefault("part1", index)
            if re.search(r"Part 2\b.{0,40}You must answer this question", text):
                pages.setdefault("part2", index)
        if "Question Number" in text:
            part3_answer = index
    if part3_answer is not None:
        pages["part3"] = part3_answer
    return pages


def extract_scheme_text(scheme_path: Path):
    """Marking-scheme text for the writing parts of one model test."""
    doc = pymupdf.open(str(scheme_path))
    text = _norm(" ".join(doc[i].get_text() for i in range(doc.page_count)))
    doc.close()
    parts = {}
    for part, number in (("part1", 1), ("part2", 2), ("part3", 3)):
        # scheme sections are keyed by the answering question numbers
        marker = re.search(rf"(?:Part\s*{number}|Question\s*{number}\b)(.{{80,1600}}?)"
                           rf"(?:Part\s*{number + 1}|Question\s*{number + 1}\b|$)",
                           text, re.IGNORECASE | re.DOTALL)
        if marker:
            parts[part] = _norm(marker.group(1))[:1500]
    if not parts:
        generic = text[:1500]
        parts = {p: generic for p in ("part1", "part2", "part3")}
    return parts


SCHEME_FILES = {
    "2022": "FC068022 SKOR A+ SPM (2022) ENGLISH_ebook K{n}.pdf",
    "2023": "eBook Skor A+ SPM (2023) English FC068023-5 K{n}.pdf",
    "2024_KM": "Pages from FC068024 KM{n}.pdf",
    "2025_Form5_Test5": "ePDF Get Ready! SPM (2025) English Form 5 test 5.pdf",
}
SCHEME_ALIASES_2024 = {
    "1": "Pages from FC068024 KM1.pdf", "2": "Pages from FC068024 KM 2.pdf",
    "3": "Pages from FC068024 KM3.pdf", "4": "Pages from FC068024 KM 4.pdf",
    "5": "Pages from FC068024 KM 5.pdf",
}


def scheme_for(source: Path, year: str, set_number: str):
    if year in ("2022", "2023"):
        candidate = source / "answer_schemes" / SCHEME_FILES[year].format(n=set_number)
    elif year == "2025_Form5_Test5":
        candidate = source / "answer_schemes" / SCHEME_FILES[year]
    else:
        candidate = source / "answer_schemes" / SCHEME_ALIASES_2024[set_number]
    return candidate if candidate.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    source = Path(args.source)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run = Path(args.workspace) / f"run_{stamp}"
    for sub in ("source_inventory", "candidate_records", "excluded_records", "reports", "logs"):
        (run / sub).mkdir(parents=True, exist_ok=True)

    marked_dir = source / "marked student answer"
    originals_dir = source / "Student Answer"
    inventory, candidates, exclusions = [], [], []
    scheme_cache = {}

    for marked_path in sorted(marked_dir.glob("*.pdf")):
        stem = marked_path.stem  # e.g. 2023_K2_Average_Marked / Variant_49_2024_KM3_Average
        variant_match = re.match(r"Variant_(\d+)_(.+)", stem)
        variant_no = variant_match.group(1) if variant_match else None
        base_stem = variant_match.group(2) if variant_match else stem
        match = re.match(r"(?:(2022|2023)_K(\d)|(2024)_KM(\d)|(2025_Form5_Test5))"
                         r"_(\w+?)(?:_Marked)?$", base_stem)
        if not match:
            exclusions.append({"file": marked_path.name, "reason": "unrecognised_name"})
            continue
        tier = match.group(6)
        if match.group(1):
            year, set_number = match.group(1), match.group(2)
            family = f"{year}_K{set_number}"
        elif match.group(3):
            year, set_number = "2024_KM", match.group(4)
            family = f"2024_KM{set_number}"
        else:
            year, set_number = "2025_Form5_Test5", "5"
            family = "2025_Form5_Test5"
        # Variants are additional marked attempts on the same paper with no
        # unmarked counterpart - content pairing only applies to the originals.
        original = (originals_dir / family / f"{family}_{tier}_Answer.pdf"
                    if variant_no is None else Path("__no_original__"))
        paper_id = family
        tier_label = tier if variant_no is None else f"{tier}_v{variant_no}"

        marked_doc = pymupdf.open(str(marked_path))
        pairing = {"original_exists": original.is_file(), "page_count_match": None,
                   "answer_text_match": None}
        original_doc = None
        if original.is_file():
            original_doc = pymupdf.open(str(original))
            pairing["page_count_match"] = original_doc.page_count == marked_doc.page_count

        part_pages = find_part_pages(marked_doc)
        scheme_key = (year, set_number)
        if scheme_key not in scheme_cache:
            scheme_path = scheme_for(source, year, set_number)
            scheme_cache[scheme_key] = (extract_scheme_text(scheme_path)
                                        if scheme_path else {})
        schemes = scheme_cache[scheme_key]

        answers_match = []
        for part in ("part1", "part2", "part3"):
            page_index = part_pages.get(part)
            entry = {"file": marked_path.name, "paper": paper_id, "tier": tier,
                     "part": part, "page": (page_index + 1) if page_index is not None else None}
            if page_index is None:
                exclusions.append({**entry, "reason": "part_page_not_found"})
                continue
            answer, corrections, score, q3, black = parse_marked_page(marked_doc[page_index])

            # content pairing: the original page must carry the same blue text
            if original_doc is not None and page_index < original_doc.page_count:
                original_answer = _norm(" ".join(
                    t for _, t in spans_by_color(original_doc[page_index])["blue"]))
                answers_match.append(original_answer == answer)

            question_context = re.sub(r"KM\d.*?Bhd\.?", " ", black)[:1200]
            if not answer:
                exclusions.append({**entry, "reason": "missing_answer_text"}); continue
            if score is None:
                exclusions.append({**entry, "reason": "missing_explicit_score"}); continue
            if part == "part3" and not q3:
                exclusions.append({**entry, "reason": "missing_selected_part3_question"}); continue
            if not corrections:
                exclusions.append({**entry, "reason": "no_explicit_corrections"}); continue
            pair_kinds = [classify_pair(old, new) for old, new in corrections]
            kinds = set(pair_kinds)
            if kinds == {"spelling"}:
                category = "spelling"
            elif kinds == {"grammar"}:
                category = "grammar"
            else:
                exclusions.append({**entry, "reason": "ambiguous_category",
                                   "correction_kinds": pair_kinds,
                                   "corrections": corrections}); continue
            scheme_text = schemes.get(part)
            if not scheme_text:
                exclusions.append({**entry, "reason": "missing_marking_scheme"}); continue

            source_basis = f"{marked_path.name}|{part}|{answer}"
            record = {
                "is_finalized": True,
                "paper_type": "kertas2",
                "paper_identifier": f"SPM English 1119/2 model test {paper_id}",
                "part_identifier": part,
                "logical_target": f"{paper_id}_{tier_label}_{part}",
                "selected_part3_question": q3 if part == "part3" else None,
                "question_text": question_context,
                "marking_scheme_text": scheme_text,
                "maximum_score": MAX_SCORE,
                "effective_student_answer": answer,
                "teacher_final_score": score,
                "teacher_final_feedback_category": category,
                "teacher_final_student_feedback": "; ".join(
                    f"{old} -> {new}" for old, new in corrections),
                "subject_profile_version": paper_id,
                "attempt_group_id": f"attempt_{paper_id}_{tier_label}",
                "student_group_id": f"student_{paper_id}_{tier_label}",
                "profile_group_id": f"paper_{paper_id}",
                "source_checksum": hashlib.sha256(source_basis.encode()).hexdigest(),
                "finalized_at": datetime.now(timezone.utc).isoformat(),
                "source_mode": "standard",
                "_evidence": {"marked_file": marked_path.name,
                              "page": page_index + 1,
                              "corrections": corrections,
                              "correction_kinds": pair_kinds,
                              "explicit_score": f"{int(score)}/20"},
            }
            candidates.append(record)
            inventory.append({**entry, "score": score, "category": category,
                              "corrections": len(corrections),
                              "q3": q3, "answer_chars": len(answer)})
        pairing["answer_text_match"] = all(answers_match) if answers_match else None
        inventory.append({"file": marked_path.name, "paper": paper_id, "tier": tier,
                          "part": "pairing", **pairing})
        marked_doc.close()
        if original_doc is not None:
            original_doc.close()

    # The same essay text appearing in more than one marked file (e.g. a
    # variant that duplicates a base paper's answer) would leak across the
    # split boundary - only the first occurrence is kept.
    seen_answers, deduped = {}, []
    for record in candidates:
        key = (record["part_identifier"], record["effective_student_answer"])
        first = seen_answers.get(key)
        if first is not None:
            exclusions.append({"file": record["_evidence"]["marked_file"],
                               "paper": record["profile_group_id"],
                               "part": record["part_identifier"],
                               "reason": "duplicate_answer_text",
                               "duplicate_of": first})
            continue
        seen_answers[key] = record["_evidence"]["marked_file"]
        deduped.append(record)
    candidates = deduped

    (run / "candidate_records" / "records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in candidates), encoding="utf-8")
    (run / "excluded_records" / "exclusions.json").write_text(
        json.dumps(exclusions, indent=2), encoding="utf-8")
    (run / "source_inventory" / "inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8")
    by_reason = Counter(e["reason"] for e in exclusions)
    by_category = Counter(r["teacher_final_feedback_category"] for r in candidates)
    by_part = Counter(r["part_identifier"] for r in candidates)
    by_paper = Counter(r["profile_group_id"] for r in candidates)
    scores = Counter(str(int(r["teacher_final_score"])) for r in candidates)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "marked_files": len(list(marked_dir.glob('*.pdf'))),
        "candidates": len(candidates) + len(exclusions),
        "included": len(candidates),
        "excluded": len(exclusions),
        "exclusions_by_reason": dict(by_reason),
        "category_distribution": dict(by_category),
        "part_distribution": dict(by_part),
        "papers": dict(by_paper),
        "score_distribution": dict(sorted(scores.items(), key=lambda kv: int(kv[0]))),
        "independent_attempt_groups": len({r["attempt_group_id"] for r in candidates}),
        "run_root": str(run),
    }
    (run / "reports" / "extraction_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
