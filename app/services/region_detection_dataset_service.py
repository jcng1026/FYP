"""Answer Region Detection dataset export foundation (Stage 12E).

Exports a YOLO-style image/label training dataset from teacher-owned
Subject Profile regions (Stage 11V/11W) - the only labelled-region data
source in this codebase. Nothing here trains YOLO, runs inference, or
adds a new ML dependency: this is a data export/preparation step only,
using the standard library plus a plain file copy for images (regions are
already stored as normalized fractions - no image processing library is
needed here).

COORDINATE SYSTEM (confirmed by inspection, not assumed - see
app/ui/template_canvas.py's TemplateCanvas.load_image/add_region_overlay/
finish_polygon): subject_profile_regions.x/y/width/height are fractions
(0-1) of whichever page image was loaded into the region editor at
annotation time, normalized independently per axis (x/width against the
loaded image's width; y/height against its height). That loaded image is
itself a proportionally-scaled preview of the page's stored PNG
(render_page_image's scaledToWidth, max_width=900) - but because the
scaling is uniform (same factor on both axes, preserving aspect ratio),
the resulting fractions are scale-invariant and apply identically to ANY
same-aspect-ratio render of the same page, including the full-resolution
ORIGINAL page image (get_document_page_image_paths, Stage 11W) used for
this export. No pixel-dimension conversion is needed or performed: the
stored fractions are already valid YOLO-style normalized coordinates for
the original image.

ENCLOSING BBOX: both rectangle and polygon regions already store their
axis-aligned bounding box in the x/y/width/height columns - see
handle_subject_profile_polygon_region_drawn in app/ui/teacher_dashboard.py,
which computes width/height as max(xs)-min(xs)/max(ys)-min(ys) from the
polygon's points before saving. For rotation_angle == 0 this stored bbox
is exactly what YOLO needs. For a nonzero rotation_angle, the region is
displayed rotated around its own bbox center (Qt QGraphicsItem.setRotation
- see add_region_overlay/add_polygon_region_overlay in template_canvas.py),
so the stored, unrotated x/y/width/height no longer bounds the true
rotated footprint - _compute_enclosing_bbox re-derives the correct
enclosing box by rotating the shape's corner/vertex points around that
same center and taking their min/max, matching what a teacher actually
sees on screen. polygon_points_json/shape_type/rotation_angle are always
preserved in the manifest for traceability, even though only the bbox is
exported for YOLO detection.

DATA QUALITY NOTE: fewer than MIN_IMAGES_FOR_REAL_DATASET exported images
is stamped demo_mode=True/meaningful=False in the summary, exactly
matching the demo-mode convention already established for Kertas 2's
Cross-Encoder training/evaluation (Stage 12C/12D) - this stage never
claims a tiny dataset is production-ready.
"""

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.models.ai_model_registry_model import (
    MODEL_KEY_ANSWER_REGION_DETECTION,
    create_training_dataset,
    get_training_dataset_by_id,
    get_training_datasets_for_teacher,
)
from app.models.subject_profile_model import (
    ALL_SUBJECT_PROFILE_REGION_TYPES,
    SOURCE_ANSWER_SCHEME,
    SOURCE_QUESTION_PAPER,
)
from app.services.region_geometry_service import clamp_to_unit_bbox as _clamp_to_unit_bbox
from app.services.region_geometry_service import compute_enclosing_bbox as _compute_enclosing_bbox
from app.services.subject_profile_service import (
    get_document_page_image_paths,
    list_regions,
    list_subject_profiles_for_teacher,
)
from app.models.subject_profile_model import get_all_active_subject_profiles
from app.services.user_service import validate_ai_manager_exists
from app.utils.file_storage import get_region_detection_dataset_folder

DATASET_FORMAT_YOLO_IMAGE = "yolo_image_dataset"
MIN_IMAGES_FOR_REAL_DATASET = 5
TRAIN_SPLIT_RATIO = 0.8

# Deterministic class mapping - reuses the existing, already-fixed-order
# Subject Profile region type tuple directly (no re-declaration, no drift
# risk) so it always matches exactly what the region editor can create.
REGION_TYPE_TO_CLASS_ID = {name: index for index, name in enumerate(ALL_SUBJECT_PROFILE_REGION_TYPES)}


def has_exportable_subject_profiles(conn, teacher_id: int, *, _profiles=None) -> bool:
    """True if at least one exportable Subject Profile has >=1 saved region AND
    a processed page image for that region's source - used by the AI Models
    page to decide whether Export Training Dataset is enabled. Reads always use
    each profile's OWN owner, so passing a global profile list (admin export)
    works identically to the teacher-scoped default."""
    profiles = _profiles if _profiles is not None else list_subject_profiles_for_teacher(conn, teacher_id)
    for profile in profiles:
        regions = list_regions(conn, profile.teacher_id, profile.profile_id)
        if not regions:
            continue
        for source in (SOURCE_QUESTION_PAPER, SOURCE_ANSWER_SCHEME):
            if not any(r.source == source for r in regions):
                continue
            if get_document_page_image_paths(conn, profile.teacher_id, profile.profile_id, source):
                return True
    return False


def has_exportable_subject_profiles_global(conn) -> bool:
    """Admin/global variant: any teacher's Subject Profile is exportable."""
    return has_exportable_subject_profiles(conn, -1, _profiles=get_all_active_subject_profiles(conn))


# _compute_enclosing_bbox/_clamp_to_unit_bbox are imported above from
# region_geometry_service (extracted there so region_crop_ocr_service.py,
# Stage 11Y, can reuse the same geometry without an import cycle) - kept
# under these same private names here so every existing caller/test in
# this module (and anything importing them FROM this module) keeps working
# unchanged.


@dataclass
class _PageExport:
    profile_id: int
    profile_name: str
    source: str
    page_number: int
    source_image_path: str
    image_stem: str
    label_lines: List[str]
    manifest_regions: List[dict]


def export_region_detection_dataset(conn, teacher_id: int, dataset_name: Optional[str] = None, *, _profiles=None) -> dict:
    """Export a YOLO-style image/label dataset from every owned Subject
    Profile's saved regions + original page images.

    Raises ValueError (never crashes) if no Subject Profiles exist, or if
    none of them have exportable regions/images. Read-only against Subject
    Profile data - never modifies a profile/region/image.
    """
    if not validate_ai_manager_exists(conn, teacher_id):
        raise ValueError("Only teacher accounts can export Answer Region Detection training datasets.")

    profiles = _profiles if _profiles is not None else list_subject_profiles_for_teacher(conn, teacher_id)
    if not profiles:
        raise ValueError("No Subject Profiles available for export - create one with regions first.")

    page_exports: List[_PageExport] = []
    skipped_zero_area = 0
    skipped_no_image = 0

    for profile in profiles:
        regions = list_regions(conn, profile.teacher_id, profile.profile_id)
        if not regions:
            continue

        for source in (SOURCE_QUESTION_PAPER, SOURCE_ANSWER_SCHEME):
            source_regions = [r for r in regions if r.source == source]
            if not source_regions:
                continue
            image_paths = get_document_page_image_paths(conn, profile.teacher_id, profile.profile_id, source)
            if not image_paths:
                continue

            regions_by_page = defaultdict(list)
            for region in source_regions:
                regions_by_page[region.page_number].append(region)

            for page_number, page_regions in sorted(regions_by_page.items()):
                index = page_number - 1
                if index < 0 or index >= len(image_paths):
                    skipped_no_image += len(page_regions)
                    continue
                image_path = image_paths[index]
                if not image_path or not Path(image_path).is_file():
                    skipped_no_image += len(page_regions)
                    continue

                label_lines = []
                manifest_regions = []
                for region in page_regions:
                    bbox = _compute_enclosing_bbox(region)
                    if bbox is None:
                        skipped_zero_area += 1
                        continue
                    clamped = _clamp_to_unit_bbox(*bbox)
                    if clamped is None:
                        skipped_zero_area += 1
                        continue
                    x0, y0, width, height = clamped
                    x_center, y_center = x0 + width / 2, y0 + height / 2
                    class_id = REGION_TYPE_TO_CLASS_ID[region.region_type]
                    label_lines.append(
                        f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
                    )
                    manifest_regions.append({
                        "region_id": region.region_id,
                        "region_label": region.label,
                        "region_type": region.region_type,
                        "shape_type": region.shape_type,
                        "rotation_angle": region.rotation_angle,
                        "polygon_points": json.loads(region.polygon_points_json) if region.polygon_points_json else None,
                    })

                if not label_lines:
                    continue

                page_exports.append(_PageExport(
                    profile_id=profile.profile_id, profile_name=profile.profile_name, source=source,
                    page_number=page_number, source_image_path=image_path,
                    image_stem=f"profile{profile.profile_id}_{source}_page{page_number}",
                    label_lines=label_lines, manifest_regions=manifest_regions,
                ))

    if not page_exports:
        raise ValueError(
            "No exportable regions found - create at least one Subject Profile with saved regions and "
            "processed page images first."
        )

    # Deterministic ordering + deterministic train/val split (no randomness).
    page_exports.sort(key=lambda p: p.image_stem)
    total = len(page_exports)
    split_index = max(1, round(total * TRAIN_SPLIT_RATIO)) if total > 1 else total
    train_exports = page_exports[:split_index]
    val_exports = page_exports[split_index:]

    if not dataset_name or not dataset_name.strip():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dataset_name = f"region_dataset_{timestamp}"
    dataset_name = dataset_name.strip()

    folder = Path(get_region_detection_dataset_folder(teacher_id, dataset_name))
    images_train_dir = folder / "images" / "train"
    images_val_dir = folder / "images" / "val"
    labels_train_dir = folder / "labels" / "train"
    labels_val_dir = folder / "labels" / "val"
    for directory in (images_train_dir, images_val_dir, labels_train_dir, labels_val_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    region_count = 0
    for split_name, exports, images_dir, labels_dir in (
        ("train", train_exports, images_train_dir, labels_train_dir),
        ("val", val_exports, images_val_dir, labels_val_dir),
    ):
        for page_export in exports:
            source_path = Path(page_export.source_image_path)
            image_dest = images_dir / f"{page_export.image_stem}{source_path.suffix or '.png'}"
            shutil.copyfile(source_path, image_dest)

            label_dest = labels_dir / f"{page_export.image_stem}.txt"
            label_dest.write_text("\n".join(page_export.label_lines) + "\n", encoding="utf-8")

            region_count += len(page_export.manifest_regions)
            for region_info in page_export.manifest_regions:
                manifest_entries.append({
                    "profile_id": page_export.profile_id,
                    "profile_name": page_export.profile_name,
                    "source": page_export.source,
                    "page_number": page_export.page_number,
                    "split": split_name,
                    "image_path": str(image_dest),
                    "label_path": str(label_dest),
                    **region_info,
                })

    classes_path = folder / "classes.txt"
    classes_path.write_text("\n".join(ALL_SUBJECT_PROFILE_REGION_TYPES) + "\n", encoding="utf-8")

    yaml_path = folder / "dataset.yaml"
    names_block = "\n".join(f"  {index}: {name}" for index, name in enumerate(ALL_SUBJECT_PROFILE_REGION_TYPES))
    yaml_path.write_text(
        f"path: {folder}\ntrain: images/train\nval: images/val\n"
        f"nc: {len(ALL_SUBJECT_PROFILE_REGION_TYPES)}\nnames:\n{names_block}\n",
        encoding="utf-8",
    )

    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_entries, indent=2), encoding="utf-8")

    demo_mode = total < MIN_IMAGES_FOR_REAL_DATASET
    summary = {
        "image_count": total,
        "train_count": len(train_exports),
        "val_count": len(val_exports),
        "region_count": region_count,
        "skipped_zero_area_count": skipped_zero_area,
        "skipped_no_image_count": skipped_no_image,
        "class_map": REGION_TYPE_TO_CLASS_ID,
        "demo_mode": demo_mode,
        "meaningful": not demo_mode,
    }
    summary_path = folder / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    dataset = create_training_dataset(
        conn, teacher_id, MODEL_KEY_ANSWER_REGION_DETECTION, dataset_name, DATASET_FORMAT_YOLO_IMAGE,
        row_count=total, csv_path=None, jsonl_path=None,
        summary_json=json.dumps(summary), source_filter_json=None, dataset_folder_path=str(folder),
    )

    return {
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.dataset_name,
        "row_count": dataset.row_count,
        "dataset_folder_path": dataset.dataset_folder_path,
        "images_dir": str(folder / "images"),
        "labels_dir": str(folder / "labels"),
        "classes_path": str(classes_path),
        "yaml_path": str(yaml_path),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "summary": summary,
    }


def _dataset_to_dict(dataset) -> dict:
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.dataset_name,
        "dataset_format": dataset.dataset_format,
        "row_count": dataset.row_count,
        "dataset_folder_path": dataset.dataset_folder_path,
        "summary": json.loads(dataset.summary_json) if dataset.summary_json else None,
        "created_at": dataset.created_at,
    }


def list_region_detection_datasets(conn, teacher_id: int, limit: int = 10) -> List[dict]:
    datasets = get_training_datasets_for_teacher(conn, teacher_id, MODEL_KEY_ANSWER_REGION_DETECTION, limit)
    return [_dataset_to_dict(dataset) for dataset in datasets]


def get_region_detection_dataset(conn, teacher_id: int, dataset_id: int) -> dict:
    dataset = get_training_dataset_by_id(conn, dataset_id)
    if dataset is None:
        raise ValueError("Training dataset not found.")
    if dataset.teacher_id != teacher_id:
        raise ValueError("You can only view your own training datasets.")
    return _dataset_to_dict(dataset)


def export_region_detection_dataset_global(conn, owner_id: int, dataset_name=None) -> dict:
    """Stage 12G-2 admin/global export: aggregate EVERY teacher's Subject
    Profile regions into one YOLO dataset, recorded under the admin owner.
    Core AI 2 region detection is a global model, so its training data spans
    all teachers. Teacher-scoped export (owner-only) is unchanged."""
    return export_region_detection_dataset(
        conn, owner_id, dataset_name=dataset_name,
        _profiles=get_all_active_subject_profiles(conn))
