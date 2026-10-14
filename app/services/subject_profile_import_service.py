"""Subject Profile local import (Data Management Follow-up - Feature 1).

The counterpart to app/services/subject_profile_export_service.py: takes a
.zip previously produced by export_subject_profile and recreates a fully
usable Subject Profile in THIS local app instance. Always creates a
BRAND-NEW profile_id (never reuses the exported profile_id, which could
already belong to a different local profile) and remaps every imported
region_id/group_id reference accordingly - see _import_regions_and_groups.

Required zip entries (import fails clearly, before writing anything, if
any is missing): profile_metadata.json, question_paper.pdf,
answer_scheme.pdf, regions.json.

Optional zip entries (imported if present, silently skipped otherwise -
never fails the import): region_groups.json, correct_answers.json,
ocr_text.json, extracted_text.json, page_images/<source>/page_N.png.
regions.csv/export_manifest.json are the export's own human-readable/audit
copies of data already covered by regions.json/the return summary here, so
neither is read back on import. marking_rules.json (the EXPORTING
teacher's global spelling-deduction/Kertas-2-partial-mark preferences - see
export_subject_profile's docstring for why there is no per-profile marking
rules table) is deliberately NEVER applied to the importing teacher's own
settings - silently overwriting an unrelated global preference just because
a profile was imported would be surprising, so its presence is only noted
in the returned summary.

If ocr_text.json is missing, the question paper/answer scheme are
reprocessed from scratch (full real OCR, via process_subject_profile_
documents) exactly like a freshly-created profile - slower, but the
imported profile still ends up fully usable rather than stuck without any
page previews or extracted content.
"""

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.subject_profile_model import (
    SOURCE_ANSWER_SCHEME,
    SOURCE_QUESTION_PAPER,
    STATUS_READY,
    TARGET_KIND_GROUP,
    TARGET_KIND_REGION,
    get_subject_profiles_for_teacher,
    update_subject_profile_extracted_content,
    update_subject_profile_files,
    update_subject_profile_ocr_content,
    update_subject_profile_status,
)
from app.services.subject_profile_service import (
    add_region,
    create_region_group,
    create_subject_profile,
    process_subject_profile_documents,
    save_answer_key_entry,
)
from app.utils.document_preprocessing import load_page_images, preprocess_page_image, save_page_image
from app.utils.file_storage import (
    get_subject_profile_original_folder,
    get_subject_profile_preprocessed_folder,
    store_subject_profile_file,
)

REQUIRED_ZIP_ENTRIES = ["profile_metadata.json", "question_paper.pdf", "answer_scheme.pdf", "regions.json"]
PAGE_IMAGES_PREFIX = "page_images/"


class DuplicateProfileNameError(ValueError):
    """Raised when a Subject Profile with the exported name already exists
    for this teacher and the caller hasn't yet decided how to proceed.
    Nothing is written to the database when this is raised - the caller
    (the UI) should ask the teacher to confirm importing as a renamed copy
    (suggested_name) or cancel, then re-call import_subject_profile with
    rename_as_copy=True if they confirm."""

    def __init__(self, message: str, suggested_name: str) -> None:
        super().__init__(message)
        self.suggested_name = suggested_name


def _imported_copy_name(base_name: str, now: Optional[datetime] = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d")
    return f"{base_name} (Imported {timestamp})"


def _read_json(zf: zipfile.ZipFile, name: str) -> Optional[dict]:
    try:
        return json.loads(zf.read(name))
    except (KeyError, json.JSONDecodeError):
        return None


def _extract_zipped_page_images(zf: zipfile.ZipFile, names: set, source: str) -> dict:
    """Return {page_number: raw_bytes} for any page_images/<source>/page_N.*
    entries in the zip - the optional pre-rendered page image export some
    other exporter (or a future version of this one) might include, per the
    "Optional files ... page_images if present" requirement. {} if none
    exist for this source (the normal case for zips from THIS app's current
    export_subject_profile, which doesn't produce page_images itself)."""
    prefix = f"{PAGE_IMAGES_PREFIX}{source}/"
    images: dict = {}
    for name in names:
        if not name.startswith(prefix) or not name.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
        if digits:
            images[int(digits)] = zf.read(name)
    return images


def _regenerate_page_images(
    profile_id: int, source: str, pdf_path: str, ocr_data: Optional[dict], zipped_images: dict,
) -> Optional[dict]:
    """Render (or, if zipped_images has this page, reuse) every page image
    for source and patch ocr_data's page dicts' image_path/original_image_
    path to point at the new profile_id's own storage folder - the
    exported JSON's paths point at the ORIGINAL profile's (possibly
    nonexistent-here) folder. Returns ocr_data unchanged if it has no
    'pages' list to patch (nothing to patch, not an error)."""
    preprocessed_folder = get_subject_profile_preprocessed_folder(profile_id, source)
    original_folder = get_subject_profile_original_folder(profile_id, source)

    if zipped_images:
        page_numbers = sorted(zipped_images.keys())
        for page_number in page_numbers:
            raw_bytes = zipped_images[page_number]
            (preprocessed_folder / f"page_{page_number}.png").write_bytes(raw_bytes)
            (original_folder / f"page_{page_number}.png").write_bytes(raw_bytes)
    else:
        images = load_page_images(pdf_path)
        page_numbers = list(range(1, len(images) + 1))
        for page_number, raw_image in zip(page_numbers, images):
            save_page_image(raw_image, original_folder / f"page_{page_number}.png")
            save_page_image(preprocess_page_image(raw_image), preprocessed_folder / f"page_{page_number}.png")

    if not ocr_data or not ocr_data.get("pages"):
        return ocr_data
    for page in ocr_data["pages"]:
        page_number = page.get("page_number")
        if page_number in page_numbers:
            page["image_path"] = str(preprocessed_folder / f"page_{page_number}.png")
            page["original_image_path"] = str(original_folder / f"page_{page_number}.png")
    return ocr_data


def _import_regions_and_groups(
    conn, teacher_id: int, profile_id: int, regions_payload: list, region_groups_payload: list,
) -> dict:
    old_to_new_region_id: dict = {}
    skipped_regions = []
    for region in regions_payload:
        try:
            polygon_points = region.get("polygon_points")
            new_region = add_region(
                conn, teacher_id, profile_id, region["source"], region["label"], region["region_type"],
                region["page_number"], region["x"], region["y"], region["width"], region["height"],
                shape_type=region.get("shape_type", "rectangle"),
                polygon_points_json=json.dumps(polygon_points) if polygon_points else None,
                rotation_angle=region.get("rotation_angle", 0.0),
                notes=region.get("notes"),
            )
        except (ValueError, KeyError) as exc:
            skipped_regions.append(f"{region.get('label', '(unlabeled)')}: {exc}")
            continue
        old_to_new_region_id[region["region_id"]] = new_region.region_id

    groups_imported = 0
    skipped_groups = []
    for group in region_groups_payload:
        member_ids = [
            old_to_new_region_id[old_id]
            for old_id in group.get("member_region_ids", [])
            if old_id in old_to_new_region_id
        ]
        if len(member_ids) < 2:
            skipped_groups.append(f"{group.get('label', '(unlabeled)')}: fewer than 2 of its regions were restored")
            continue
        try:
            create_region_group(
                conn, teacher_id, profile_id, group["label"], group["region_type"], member_ids,
                notes=group.get("notes"),
            )
            groups_imported += 1
        except (ValueError, KeyError) as exc:
            skipped_groups.append(f"{group.get('label', '(unlabeled)')}: {exc}")

    return {
        "regions_imported": len(old_to_new_region_id),
        "regions_skipped": skipped_regions,
        "groups_imported": groups_imported,
        "groups_skipped": skipped_groups,
    }


def import_subject_profile(
    conn, teacher_id: int, zip_path: str, *, rename_as_copy: bool = False, now: Optional[datetime] = None,
) -> dict:
    """Import a Subject Profile export zip as a brand-new profile owned by
    teacher_id. Raises ValueError (nothing written) if zip_path isn't a
    valid zip, or is missing a required entry. Raises
    DuplicateProfileNameError (nothing written) if a profile with the same
    name already exists and rename_as_copy is False - the caller should ask
    the teacher and, if confirmed, re-call with rename_as_copy=True.

    Returns a summary dict: profile_id, profile_name, renamed (bool),
    regions_imported, regions_skipped (list of reasons), groups_imported,
    groups_skipped, answer_key_entries_imported, marking_rules_present
    (bool - see module docstring for why it's never auto-applied),
    warnings (list of human-readable notes, e.g. "no OCR text in this
    export - reprocessed from scratch")."""
    zip_file_path = Path(zip_path)
    if not zip_file_path.is_file():
        raise ValueError(f"Import file not found: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_file_path)
    except zipfile.BadZipFile:
        raise ValueError("The chosen file is not a valid .zip archive.")

    with zf:
        names = set(zf.namelist())
        missing_required = [entry for entry in REQUIRED_ZIP_ENTRIES if entry not in names]
        if missing_required:
            raise ValueError(
                "This zip is missing required Subject Profile export file(s): " + ", ".join(missing_required)
                + ". Only a .zip created by this app's Subject Profile Export can be imported."
            )

        metadata = _read_json(zf, "profile_metadata.json") or {}
        base_name = (metadata.get("profile_name") or "Imported Subject Profile").strip() or "Imported Subject Profile"

        existing_names = {p.profile_name for p in get_subject_profiles_for_teacher(conn, teacher_id)}
        profile_name = base_name
        renamed = False
        if base_name in existing_names:
            if not rename_as_copy:
                raise DuplicateProfileNameError(
                    f"A Subject Profile named '{base_name}' already exists.",
                    suggested_name=_imported_copy_name(base_name, now),
                )
            profile_name = _imported_copy_name(base_name, now)
            suffix = 2
            while profile_name in existing_names:
                profile_name = f"{_imported_copy_name(base_name, now)} ({suffix})"
                suffix += 1
            renamed = True

        profile = create_subject_profile(conn, teacher_id, profile_name)
        profile_id = profile.profile_id

        warnings: list = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            qp_tmp_path = Path(tmp_dir) / "question_paper.pdf"
            qp_tmp_path.write_bytes(zf.read("question_paper.pdf"))
            as_tmp_path = Path(tmp_dir) / "answer_scheme.pdf"
            as_tmp_path.write_bytes(zf.read("answer_scheme.pdf"))

            ocr_payload = _read_json(zf, "ocr_text.json") if "ocr_text.json" in names else None
            if ocr_payload is not None:
                question_paper_path = store_subject_profile_file(profile_id, str(qp_tmp_path), "question_paper")
                answer_scheme_path = store_subject_profile_file(profile_id, str(as_tmp_path), "answer_scheme")
                update_subject_profile_files(conn, profile_id, question_paper_path, answer_scheme_path)

                extracted_payload = _read_json(zf, "extracted_text.json") if "extracted_text.json" in names else None

                qp_ocr = _regenerate_page_images(
                    profile_id, SOURCE_QUESTION_PAPER, question_paper_path,
                    ocr_payload.get("question_paper_ocr"), _extract_zipped_page_images(zf, names, SOURCE_QUESTION_PAPER),
                )
                as_ocr = _regenerate_page_images(
                    profile_id, SOURCE_ANSWER_SCHEME, answer_scheme_path,
                    ocr_payload.get("answer_scheme_ocr"), _extract_zipped_page_images(zf, names, SOURCE_ANSWER_SCHEME),
                )
                update_subject_profile_ocr_content(
                    conn, profile_id,
                    question_paper_ocr_json=json.dumps(qp_ocr) if qp_ocr else None,
                    answer_scheme_ocr_json=json.dumps(as_ocr) if as_ocr else None,
                )

                if extracted_payload is not None:
                    qp_extracted = extracted_payload.get("question_paper_extracted")
                    as_extracted = extracted_payload.get("answer_scheme_extracted")
                else:
                    qp_extracted = [p.get("text") or "" for p in (qp_ocr or {}).get("pages", [])]
                    as_extracted = [p.get("text") or "" for p in (as_ocr or {}).get("pages", [])]
                update_subject_profile_extracted_content(
                    conn, profile_id,
                    question_paper_extracted_json=json.dumps(qp_extracted) if qp_extracted is not None else None,
                    answer_scheme_extracted_json=json.dumps(as_extracted) if as_extracted is not None else None,
                )
                update_subject_profile_status(conn, profile_id, STATUS_READY)
            else:
                warnings.append(
                    "No ocr_text.json in this export - the question paper and answer scheme were "
                    "reprocessed from scratch (this can take a while for a real scan)."
                )
                process_subject_profile_documents(conn, teacher_id, profile_id, str(qp_tmp_path), str(as_tmp_path))

        regions_payload = _read_json(zf, "regions.json") or []
        region_groups_payload = _read_json(zf, "region_groups.json") or [] if "region_groups.json" in names else []
        region_summary = _import_regions_and_groups(conn, teacher_id, profile_id, regions_payload, region_groups_payload)

        answer_key_entries_imported = 0
        if "correct_answers.json" in names:
            correct_answers_payload = _read_json(zf, "correct_answers.json") or []
            for entry in correct_answers_payload:
                try:
                    save_answer_key_entry(
                        conn, teacher_id, profile_id, entry["target_label"],
                        entry.get("target_kind", TARGET_KIND_REGION), entry.get("question_no"),
                        entry.get("correct_answer"), entry.get("max_mark", 1.0), entry.get("comment"),
                    )
                    answer_key_entries_imported += 1
                except (ValueError, KeyError):
                    continue
        else:
            warnings.append("No correct_answers.json in this export - the Answer Key is empty; fill it in manually "
                             "or use \"Extract Answer Key from Answer Scheme\".")

        marking_rules_present = "marking_rules.json" in names
        if marking_rules_present:
            warnings.append(
                "This export included marking_rules.json (the exporting teacher's global marking preferences) - "
                "not applied automatically, since it isn't specific to this profile. Review Marking Settings "
                "yourself if you want to match it."
            )

    return {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "renamed": renamed,
        "regions_imported": region_summary["regions_imported"],
        "regions_skipped": region_summary["regions_skipped"],
        "groups_imported": region_summary["groups_imported"],
        "groups_skipped": region_summary["groups_skipped"],
        "answer_key_entries_imported": answer_key_entries_imported,
        "marking_rules_present": marking_rules_present,
        "warnings": warnings,
    }
