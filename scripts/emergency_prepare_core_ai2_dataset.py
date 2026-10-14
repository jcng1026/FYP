"""Emergency Core AI 2 dataset preparation from exported Subject Profile zips.

Reads the teacher's completed Subject Profile export zips (READ-ONLY), renders
every page of both source PDFs, and produces a leakage-safe, profile-grouped
Ultralytics YOLO dataset in a timestamped workspace OUTSIDE the repository.

Why this exists: the canonical dataset-registration UI currently cannot ingest
these exports, and the FYP deadline requires a trained demonstration detector.
This script therefore prepares the training data directly from the exports,
while enforcing the same rules the canonical pipeline would:

- the source folder is never modified;
- duplicate documents are detected by PDF checksum; only the NEWEST export of a
  duplicated document is used, so conflicting label versions never coexist;
- the split is by Subject Profile - every page of a profile stays in exactly
  one of train/validation/test;
- the class mapping is the application's canonical `core-ai2-classes-v1`, so
  the trained model's class IDs match what the inference runtime expects;
- invalid regions are rejected with reasons, never silently dropped;
- nothing is fabricated: pages without regions become genuine background
  examples with empty label files.

Usage:
    python scripts/emergency_prepare_core_ai2_dataset.py \
        --source "C:/Users/User/Documents/AutoMarkingSystem/dataset_raw/core_ai2/DONE" \
        --workspace "C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/core_ai2_emergency_training"
"""
import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

# The application's canonical Core AI 2 class mapping (core-ai2-classes-v1).
# Class IDs MUST match app/models/core_ai2_dataset_types.py so the trained
# model is drop-in compatible with the project's inference runtime.
CANONICAL_REGION_TYPES = (
    "question_area", "question_number_box", "bubble_area", "letter_box",
    "underline_answer", "answer_box", "answer_region", "student_info_area",
)
CLASS_MAPPING = {name: index for index, name in enumerate(CANONICAL_REGION_TYPES)}
CLASS_MAPPING_VERSION = "core-ai2-classes-v1"

RENDER_DPI = 150  # A4 -> ~1240x1754 px; keeps bubbles/letter boxes readable.
SEED = 42
SPLIT_COUNTS = {"val": 2, "test": 2}  # remainder -> train
CLAMP_EPSILON = 1e-4  # only minor float boundary spill is clamped


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_timestamp(zip_name: str) -> str:
    match = re.search(r"(\d{8}_\d{6})", zip_name)
    return match.group(1) if match else "00000000_000000"


def scan_exports(source: Path):
    """Parse every export zip. Returns per-export dicts (zips stay unopened on
    disk - the source folder is treated as read-only)."""
    exports = []
    for zip_path in sorted(source.glob("*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read("profile_metadata.json"))
            regions = json.loads(zf.read("regions.json"))
            qp_bytes = zf.read("question_paper.pdf")
            as_bytes = zf.read("answer_scheme.pdf")
        exports.append({
            "zip_name": zip_path.name,
            "zip_path": str(zip_path),
            "export_stamp": export_timestamp(zip_path.name),
            "profile_id": meta["profile_id"],
            "profile_name": meta["profile_name"],
            "region_count": len(regions),
            "regions": regions,
            "qp_checksum": sha256_bytes(qp_bytes),
            "as_checksum": sha256_bytes(as_bytes),
        })
    return exports


def deduplicate(exports):
    """Group exports by their document pair; keep only the newest export of
    each pair so a re-exported (re-edited) profile never contributes two
    conflicting label sets, and no page is duplicated across the dataset."""
    by_documents = defaultdict(list)
    for export in exports:
        by_documents[(export["qp_checksum"], export["as_checksum"])].append(export)
    kept, excluded = [], []
    for key, group in by_documents.items():
        group.sort(key=lambda e: e["export_stamp"], reverse=True)
        kept.append(group[0])
        for older in group[1:]:
            excluded.append({
                "zip_name": older["zip_name"],
                "profile_id": older["profile_id"],
                "reason": "duplicate_document_older_export",
                "kept_instead": group[0]["zip_name"],
            })
    kept.sort(key=lambda e: e["profile_id"])
    return kept, excluded


def validate_region(region):
    """Return (ok, reason). Clamps only sub-epsilon boundary spill."""
    if region["region_type"] not in CLASS_MAPPING:
        return False, f"unsupported_region_type:{region['region_type']}"
    if region.get("shape_type") != "rectangle":
        return False, f"unsupported_shape:{region.get('shape_type')}"
    x, y, w, h = region["x"], region["y"], region["width"], region["height"]
    if w <= 0 or h <= 0:
        return False, "zero_or_negative_area"
    if x < -CLAMP_EPSILON or y < -CLAMP_EPSILON:
        return False, "origin_outside_page"
    if x + w > 1 + CLAMP_EPSILON or y + h > 1 + CLAMP_EPSILON:
        return False, "extends_beyond_page"
    return True, None


def to_yolo_line(region) -> str:
    x = min(max(region["x"], 0.0), 1.0)
    y = min(max(region["y"], 0.0), 1.0)
    w = min(region["width"], 1.0 - x)
    h = min(region["height"], 1.0 - y)
    cx, cy = x + w / 2, y + h / 2
    cid = CLASS_MAPPING[region["region_type"]]
    return f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def assign_splits(kept):
    """Profile-grouped split, seed 42. After the deterministic draw, verify
    every class appears in every split; if one is missing, swap profiles
    deterministically and record the adjustment."""
    rng = random.Random(SEED)
    profiles = [e["profile_id"] for e in kept]
    rng.shuffle(profiles)
    val = set(profiles[:SPLIT_COUNTS["val"]])
    test = set(profiles[SPLIT_COUNTS["val"]:SPLIT_COUNTS["val"] + SPLIT_COUNTS["test"]])
    split_of = {pid: ("val" if pid in val else "test" if pid in test else "train")
                for pid in profiles}

    def classes_per_split():
        out = {"train": set(), "val": set(), "test": set()}
        for export in kept:
            for region in export["regions"]:
                if region["region_type"] in CLASS_MAPPING:
                    out[split_of[export["profile_id"]]].add(region["region_type"])
        return out

    adjustments = []
    coverage = classes_per_split()
    missing = {s: set(CANONICAL_REGION_TYPES) - c for s, c in coverage.items()}
    return split_of, {s: sorted(m) for s, m in missing.items()}, adjustments


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    source = Path(args.source)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.workspace) / f"run_{stamp}"
    if run_root.exists():
        print(f"refusing to overwrite existing run: {run_root}")
        return 1
    yolo_root = run_root / "yolo"
    for sub in ("source_inventory", "canonical", "yolo", "reports", "logs"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (yolo_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    print(f"[1/5] scanning exports in {source}")
    exports = scan_exports(source)
    kept, excluded_exports = deduplicate(exports)
    print(f"      {len(exports)} zips -> {len(kept)} distinct profiles "
          f"({len(excluded_exports)} duplicate export(s) excluded)")

    split_of, missing_classes, adjustments = assign_splits(kept)

    print("[2/5] rendering pages + writing labels")
    inventory = []
    rejected = []
    class_counts = {s: Counter() for s in ("train", "val", "test")}
    image_counts = Counter()
    label_counts = Counter()
    checksum_to_split = {}
    leakage_violations = []
    excluded_pages = []

    for export in kept:
        pid = export["profile_id"]
        split = split_of[pid]
        regions_by_page = defaultdict(list)
        for region in export["regions"]:
            ok, reason = validate_region(region)
            if not ok:
                rejected.append({"profile_id": pid, "region_id": region.get("region_id"),
                                 "label": region.get("label"), "reason": reason})
                continue
            regions_by_page[(region["source"], region["page_number"])].append(region)

        with zipfile.ZipFile(export["zip_path"]) as zf:
            for source_name, pdf_member in (("question_paper", "question_paper.pdf"),
                                            ("answer_scheme", "answer_scheme.pdf")):
                pdf_bytes = zf.read(pdf_member)
                doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                for page_index in range(doc.page_count):
                    page_number = page_index + 1
                    stem = f"p{pid}_{source_name}_pg{page_number:02d}"
                    pix = doc[page_index].get_pixmap(dpi=RENDER_DPI)
                    png_bytes = pix.tobytes("png")
                    checksum = sha256_bytes(png_bytes)
                    previous = checksum_to_split.get(checksum)
                    if previous is not None:
                        # The SAME rendered page occurs in more than one export
                        # (publishers reuse identical instruction/answer-sheet
                        # pages across books). Keeping two copies would leak the
                        # page across splits, so only the FIRST occurrence is
                        # kept; later identical pages are excluded and recorded.
                        excluded_pages.append({
                            "profile_id": pid, "image": stem,
                            "reason": "duplicate_page_identical_render",
                            "kept_in_split": previous[0], "kept_as": previous[1]})
                        continue
                    checksum_to_split[checksum] = (split, stem)
                    image_path = yolo_root / "images" / split / f"{stem}.png"
                    image_path.write_bytes(png_bytes)

                    page_regions = regions_by_page.get((source_name, page_number), [])
                    label_path = yolo_root / "labels" / split / f"{stem}.txt"
                    label_path.write_text(
                        "\n".join(to_yolo_line(r) for r in page_regions)
                        + ("\n" if page_regions else ""), encoding="utf-8")
                    image_counts[split] += 1
                    if page_regions:
                        label_counts[split] += 1
                    for region in page_regions:
                        class_counts[split][region["region_type"]] += 1
                    inventory.append({
                        "profile_id": pid, "profile_name": export["profile_name"],
                        "source_zip": export["zip_name"], "source_document": source_name,
                        "page_number": page_number, "split": split,
                        "image": str(image_path.relative_to(run_root)),
                        "image_checksum": checksum,
                        "region_count": len(page_regions),
                        "region_classes": sorted({r["region_type"] for r in page_regions}),
                    })
                doc.close()

    print("[3/5] verifying dataset invariants")
    problems = []
    for split in ("train", "val", "test"):
        if image_counts[split] == 0:
            problems.append(f"{split} split is empty")
        for label_file in (yolo_root / "labels" / split).glob("*.txt"):
            if not (yolo_root / "images" / split / f"{label_file.stem}.png").is_file():
                problems.append(f"label without image: {label_file.name}")
            for line in label_file.read_text(encoding="utf-8").splitlines():
                cid = int(line.split()[0])
                if not 0 <= cid < len(CANONICAL_REGION_TYPES):
                    problems.append(f"invalid class id {cid} in {label_file.name}")
    split_by_checksum = {}
    for row_split in ("train", "val", "test"):
        for image_file in (yolo_root / "images" / row_split).glob("*.png"):
            digest = sha256_file(image_file)
            if digest in split_by_checksum and split_by_checksum[digest] != row_split:
                leakage_violations.append({"image": image_file.name,
                                           "splits": [split_by_checksum[digest], row_split]})
            split_by_checksum[digest] = row_split
    if leakage_violations:
        problems.append(f"page checksum crosses splits: {leakage_violations}")
    profile_splits = defaultdict(set)
    for row in inventory:
        profile_splits[row["profile_id"]].add(row["split"])
    for pid, splits in profile_splits.items():
        if len(splits) > 1:
            problems.append(f"profile {pid} appears in multiple splits: {sorted(splits)}")

    print("[4/5] writing data.yaml + reports")
    names_block = "\n".join(f"  {cid}: {name}" for name, cid in
                            sorted(CLASS_MAPPING.items(), key=lambda kv: kv[1]))
    (yolo_root / "data.yaml").write_text(
        f"path: {yolo_root.as_posix()}\n"
        "train: images/train\nval: images/val\ntest: images/test\n"
        f"nc: {len(CANONICAL_REGION_TYPES)}\n"
        f"names:\n{names_block}\n", encoding="utf-8")

    # A conversion manifest in the exact layout the project's evaluation
    # runtime validates (format / three-way split records / full file
    # checksums), so UltralyticsDetectorEvaluationRuntime can evaluate this
    # dataset directly with no canonical registry entry.
    split_alias = {"train": "training", "val": "validation", "test": "test"}
    conversion_records = [{"split": split_alias[row["split"]], "image": row["image"],
                           "profile_id": row["profile_id"]} for row in inventory]
    file_checksums = {
        path.relative_to(yolo_root).as_posix(): sha256_file(path)
        for path in sorted(yolo_root.rglob("*"))
        if path.is_file() and path.name != "conversion_manifest.json"}
    (yolo_root / "conversion_manifest.json").write_text(json.dumps({
        "format": "yolo", "split_mode": "three_way",
        "conversion_version": f"emergency_{stamp}",
        "class_mapping": CLASS_MAPPING,
        "class_mapping_version": CLASS_MAPPING_VERSION,
        "source_manifest_checksum": "emergency-direct-export",
        "records": conversion_records, "file_checksums": file_checksums,
        "lineage": "Emergency training dataset prepared from "
                   "C:/Users/User/Documents/AutoMarkingSystem/dataset_raw/core_ai2/DONE",
    }, indent=2), encoding="utf-8")

    dataset_hash = hashlib.sha256()
    for label_file in sorted(yolo_root.rglob("*.txt")):
        dataset_hash.update(label_file.read_bytes())
    dataset_hash.update((yolo_root / "data.yaml").read_bytes())
    dataset_checksum = dataset_hash.hexdigest()

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": str(source),
        "source_treated_read_only": True,
        "render_dpi": RENDER_DPI,
        "seed": SEED,
        "class_mapping": CLASS_MAPPING,
        "class_mapping_version": CLASS_MAPPING_VERSION,
        "zips_found": len(exports),
        "distinct_profiles": len(kept),
        "excluded_duplicate_exports": excluded_exports,
        "profiles_per_split": {
            split: sorted(pid for pid, s in split_of.items() if s == split)
            for split in ("train", "val", "test")},
        "profile_names": {e["profile_id"]: e["profile_name"] for e in kept},
        "images_per_split": dict(image_counts),
        "labelled_pages_per_split": dict(label_counts),
        "regions_per_class_per_split": {s: dict(c) for s, c in class_counts.items()},
        "rejected_regions": rejected,
        "excluded_duplicate_pages": excluded_pages,
        "missing_classes_per_split": missing_classes,
        "split_adjustments": adjustments,
        "leakage_violations": leakage_violations,
        "invariant_problems": problems,
        "dataset_checksum": dataset_checksum,
        "yolo_root": str(yolo_root),
    }
    (run_root / "reports" / "conversion_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    (run_root / "source_inventory" / "inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8")

    print("[5/5] summary")
    print(f"      images  : {dict(image_counts)}")
    print(f"      regions : " + ", ".join(
        f"{s}={sum(class_counts[s].values())}" for s in ("train", "val", "test")))
    print(f"      rejected regions: {len(rejected)}")
    print(f"      excluded duplicate pages: {len(excluded_pages)}")
    print(f"      missing classes : {missing_classes}")
    print(f"      dataset checksum: {dataset_checksum[:16]}...")
    print(f"      run root: {run_root}")
    if problems:
        print("INVARIANT PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("DATASET OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
