"""Subject Profile local export (Data Management Readiness Fix).

Bundles a Subject Profile's accepted/stored data - metadata, original PDFs,
regions, marking rules, answer key, and OCR/extracted text - into one local
.zip file the teacher chooses via a file-save dialog. Read-only against the
Subject Profile: never modifies a profile/region/answer-key row. Uses only
the Python standard library (zipfile/json/csv), matching every other export
service in this codebase (see app/services/main_marking_export_service.py) -
no new dependency was added.

Missing optional data (no answer key yet, no OCR content yet, a PDF file no
longer on disk, etc.) never fails the export - the corresponding zip entry
is simply omitted and a note is recorded in export_manifest.json's
files_missing/warnings lists, so the teacher can see exactly what a given
export does and doesn't contain.
"""

import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.subject_profile_model import get_members_for_group
from app.models.user_model import get_user_by_id
from app.services.subject_profile_service import (
    get_owned_subject_profile,
    list_answer_key_entries,
    list_region_groups,
    list_regions,
)
from app.services.teacher_marking_settings_service import get_teacher_marking_settings

REGIONS_CSV_HEADERS = [
    "profile_id", "profile_name", "pdf_type", "page_number", "region_type",
    "x", "y", "width", "height", "question_number_or_group",
]


def default_export_filename(profile_name: str, now: Optional[datetime] = None) -> str:
    """<profile_name>_subject_profile_export_<YYYYMMDD_HHMMSS>.zip, with any
    filesystem-unsafe character in profile_name replaced by '_'."""
    safe_name = "".join(c if c.isalnum() else "_" for c in profile_name).strip("_") or "profile"
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{safe_name}_subject_profile_export_{timestamp}.zip"


def export_subject_profile(
    conn: sqlite3.Connection, teacher_id: int, profile_id: int, destination_zip_path: str,
) -> dict:
    """Export profile_id to destination_zip_path. Returns the manifest dict
    (files_included / files_missing / warnings / export_timestamp) that is
    also written into the zip as export_manifest.json. Raises ValueError if
    the profile doesn't exist or isn't owned by teacher_id - never partially
    writes a zip file in that case."""
    profile = get_owned_subject_profile(conn, teacher_id, profile_id)

    regions = list_regions(conn, teacher_id, profile_id)
    groups = list_region_groups(conn, teacher_id, profile_id)
    answer_key = list_answer_key_entries(conn, teacher_id, profile_id)
    teacher = get_user_by_id(conn, teacher_id)

    region_to_groups: dict = {}
    for group in groups:
        for member in get_members_for_group(conn, group.group_id):
            region_to_groups.setdefault(member.region_id, []).append(group.group_id)

    included: list = []
    missing: list = []
    warnings: list = []
    export_timestamp = datetime.now(timezone.utc).isoformat()

    # 1. profile_metadata.json - always included (even for a brand-new,
    # otherwise-empty profile, since the profile itself always exists).
    metadata = {
        "profile_id": profile.profile_id,
        "profile_name": profile.profile_name,
        "status": profile.status,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "teacher_id": profile.teacher_id,
        "teacher_username": teacher.username if teacher else None,
        "teacher_full_name": teacher.full_name if teacher else None,
        "region_count": len(regions),
        "region_group_count": len(groups),
        "answer_key_entry_count": len(answer_key),
        "export_timestamp": export_timestamp,
    }
    included.append("profile_metadata.json")

    # 2/3. question_paper.pdf / answer_scheme.pdf
    question_paper_bytes = None
    if profile.question_paper_path and Path(profile.question_paper_path).is_file():
        question_paper_bytes = Path(profile.question_paper_path).read_bytes()
        included.append("question_paper.pdf")
    else:
        missing.append("question_paper.pdf")
        warnings.append("Original question paper PDF not found on disk - question_paper.pdf omitted.")

    answer_scheme_bytes = None
    if profile.answer_scheme_path and Path(profile.answer_scheme_path).is_file():
        answer_scheme_bytes = Path(profile.answer_scheme_path).read_bytes()
        included.append("answer_scheme.pdf")
    else:
        missing.append("answer_scheme.pdf")
        warnings.append("Original answer scheme PDF not found on disk - answer_scheme.pdf omitted.")

    # 4/5. regions.json / regions.csv - always written (as an empty
    # list/header-only CSV) since a profile with zero regions is a normal,
    # valid state, not a "missing data" warning.
    regions_payload = [
        {
            "region_id": region.region_id,
            "profile_id": region.profile_id,
            "source": region.source,
            "label": region.label,
            "region_type": region.region_type,
            "page_number": region.page_number,
            "x": region.x, "y": region.y, "width": region.width, "height": region.height,
            "shape_type": region.shape_type,
            "polygon_points": json.loads(region.polygon_points_json) if region.polygon_points_json else None,
            "rotation_angle": region.rotation_angle,
            "order_index": region.order_index,
            "notes": region.notes,
            "group_ids": region_to_groups.get(region.region_id, []),
            "created_at": region.created_at,
        }
        for region in regions
    ]
    included.append("regions.json")

    answer_key_by_label = {entry.target_label: entry for entry in answer_key}
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(REGIONS_CSV_HEADERS)
    for region in regions:
        entry = answer_key_by_label.get(region.label)
        question_no = entry.question_no if entry and entry.question_no else ""
        group_ids = region_to_groups.get(region.region_id, [])
        question_number_or_group = question_no or (",".join(str(g) for g in group_ids) if group_ids else "")
        writer.writerow([
            profile.profile_id, profile.profile_name, region.source, region.page_number,
            region.region_type, region.x, region.y, region.width, region.height, question_number_or_group,
        ])
    regions_csv_text = csv_buffer.getvalue()
    included.append("regions.csv")

    # Data Management Follow-up: region_groups.json - each group's OWN
    # metadata (label/region_type/notes) plus its ordered member region_ids,
    # not just the per-region "group_ids" backlink above. Without this, a
    # re-imported profile could remap region_ids but had no way to recreate
    # the group rows themselves (a group's target_label - used to match
    # correct_answers.json entries with target_kind='group' - lives on the
    # group row, not on any region). Always written (even an empty list)
    # since a profile with zero groups is a normal, valid state.
    region_groups_payload = [
        {
            "group_id": group.group_id,
            "label": group.label,
            "region_type": group.region_type,
            "notes": group.notes,
            "member_region_ids": [m.region_id for m in get_members_for_group(conn, group.group_id)],
        }
        for group in groups
    ]
    included.append("region_groups.json")

    # 6. marking_rules.json - the teacher's marking settings (spelling
    # deduction / Kertas 2 partial-mark default), the closest existing
    # "marking rules" concept - Subject Profiles have no per-profile rules
    # table of their own.
    marking_rules = None
    try:
        settings = get_teacher_marking_settings(conn, teacher_id)
        marking_rules = {
            "spelling_deduction_enabled": settings.spelling_deduction_enabled,
            "spelling_deduction_points": settings.spelling_deduction_points,
            "kertas2_partial_mark_default": settings.kertas2_partial_mark_default,
        }
        included.append("marking_rules.json")
    except Exception:
        missing.append("marking_rules.json")
        warnings.append("Teacher marking settings unavailable - marking_rules.json omitted.")

    # 7. correct_answers.json
    correct_answers_payload = None
    if answer_key:
        correct_answers_payload = [
            {
                "entry_id": entry.entry_id, "target_label": entry.target_label, "target_kind": entry.target_kind,
                "question_no": entry.question_no, "correct_answer": entry.correct_answer,
                "max_mark": entry.max_mark, "comment": entry.comment,
            }
            for entry in answer_key
        ]
        included.append("correct_answers.json")
    else:
        missing.append("correct_answers.json")
        warnings.append("No answer key entries saved yet - correct_answers.json omitted.")

    # 8. ocr_text.json / extracted_text.json
    ocr_text_payload = None
    if profile.question_paper_ocr_json or profile.answer_scheme_ocr_json:
        ocr_text_payload = {
            "question_paper_ocr": json.loads(profile.question_paper_ocr_json) if profile.question_paper_ocr_json else None,
            "answer_scheme_ocr": json.loads(profile.answer_scheme_ocr_json) if profile.answer_scheme_ocr_json else None,
        }
        included.append("ocr_text.json")
    else:
        missing.append("ocr_text.json")
        warnings.append("No OCR text stored yet - ocr_text.json omitted.")

    extracted_text_payload = None
    if profile.question_paper_extracted_json or profile.answer_scheme_extracted_json:
        extracted_text_payload = {
            "question_paper_extracted": json.loads(profile.question_paper_extracted_json) if profile.question_paper_extracted_json else None,
            "answer_scheme_extracted": json.loads(profile.answer_scheme_extracted_json) if profile.answer_scheme_extracted_json else None,
        }
        included.append("extracted_text.json")
    else:
        missing.append("extracted_text.json")
        warnings.append("No extracted text stored yet - extracted_text.json omitted.")

    manifest = {
        "profile_id": profile.profile_id,
        "profile_name": profile.profile_name,
        "export_timestamp": export_timestamp,
        "files_included": included,
        "files_missing": missing,
        "warnings": warnings,
    }

    destination = Path(destination_zip_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile_metadata.json", json.dumps(metadata, indent=2))
        zf.writestr("regions.json", json.dumps(regions_payload, indent=2))
        zf.writestr("regions.csv", regions_csv_text)
        zf.writestr("region_groups.json", json.dumps(region_groups_payload, indent=2))
        if marking_rules is not None:
            zf.writestr("marking_rules.json", json.dumps(marking_rules, indent=2))
        if correct_answers_payload is not None:
            zf.writestr("correct_answers.json", json.dumps(correct_answers_payload, indent=2))
        if ocr_text_payload is not None:
            zf.writestr("ocr_text.json", json.dumps(ocr_text_payload, indent=2))
        if extracted_text_payload is not None:
            zf.writestr("extracted_text.json", json.dumps(extracted_text_payload, indent=2))
        if question_paper_bytes is not None:
            zf.writestr("question_paper.pdf", question_paper_bytes)
        if answer_scheme_bytes is not None:
            zf.writestr("answer_scheme.pdf", answer_scheme_bytes)
        zf.writestr("export_manifest.json", json.dumps(manifest, indent=2))

    return manifest
