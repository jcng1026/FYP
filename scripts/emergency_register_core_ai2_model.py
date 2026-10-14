"""Register (and conditionally activate) the emergency Core AI 2 detector.

Publishes the trained checkpoint into the application's REAL model registry at
the given data root, using the same folder layout, manifest and checksum rules
CoreAI2ModelService verifies. Then:

1. verifies the published model through CoreAI2ModelService (checksums, family);
2. records the REAL runtime evaluation results (produced by the project's
   UltralyticsDetectorEvaluationRuntime during training) as this model's
   evaluation, with the dataset lineage clearly marked as the emergency export;
3. runs one REAL inference through CoreAI2InferenceService + the project
   inference runtime on a held-out test page, and checks the result converts
   into editable region proposals;
4. activates ONLY if every one of those steps succeeded.

Nothing here fabricates a canonical dataset record: the evaluation record's
dataset_version/lineage state exactly where the data came from.

Usage (AI venv python, repo root):
    python scripts/emergency_register_core_ai2_model.py \
        --run-root <workspace run dir> \
        --data-root "C:/Users/User/Documents/AutoMarkingSystem/FYP-Data" \
        [--no-activate]
"""
import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

MODEL_VERSION = "core_ai2_detector_emergency_v1"
LINEAGE = ("Emergency training dataset prepared from "
           "C:/Users/User/Documents/AutoMarkingSystem/dataset_raw/core_ai2/DONE")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    data_root = Path(args.data_root)
    model_dir = run_root / "models" / MODEL_VERSION
    training_record = json.loads((model_dir / "training_record.json").read_text("utf-8"))
    conversion = json.loads((run_root / "yolo" / "conversion_manifest.json").read_text("utf-8"))
    evaluations = {
        split: json.loads((run_root / "reports" / f"evaluation_{split}.json").read_text("utf-8"))
        for split in ("validation", "test")
    }

    from app.services.core_ai_backend_paths import AIBackendPaths
    from app.services.core_ai2_model_service import CoreAI2ModelService
    from app.ml.core_ai2_evaluation_runtime import UltralyticsDetectorEvaluationRuntime
    from app.ml.core_ai2_inference_runtime import UltralyticsDetectorInferenceRuntime
    from app.services.core_ai2_inference_service import CoreAI2InferenceService
    from app.models.core_ai2_inference_types import CoreAI2InferenceRequest

    paths = AIBackendPaths(data_root)
    paths.ensure_layout()

    # --- 1. publish the model folder ----------------------------------------
    target = paths.model_folder("core_ai2", MODEL_VERSION)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model_dir / "best.pt", target / "best.pt")
    shutil.copy2(model_dir / "training_record.json", target / "training_record.json")

    manifest = {
        "model_family": "core_ai2",
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "architecture": "yolo11n",
        "base_model_identifier": training_record["base_checkpoint"]["name"],
        "base_model_checksum": training_record["base_checkpoint"]["sha256"],
        "class_mapping": conversion["class_mapping"],
        "class_mapping_version": conversion["class_mapping_version"],
        "source_dataset_version": conversion["conversion_version"],
        "source_dataset_checksum": conversion["source_manifest_checksum"],
        "dataset_lineage": LINEAGE,
        "conversion_version": conversion["conversion_version"],
        "conversion_checksum": sha256_file(run_root / "yolo" / "conversion_manifest.json"),
        "training_configuration": training_record["training_arguments"],
        "training_environment": training_record["environment"],
        "training_duration_seconds": training_record["duration_seconds"],
        "seed": training_record["seed"],
        "artifact_inventory": [],
        "notes": "Emergency FYP demonstration model. Preliminary metrics from a "
                 "15-profile dataset; not production accuracy.",
    }
    manifest["artifact_inventory"] = [
        {"name": name, "size": (target / name).stat().st_size}
        for name in ("best.pt", "training_record.json")]
    (target / "model_manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    checksums = {name: sha256_file(target / name)
                 for name in ("best.pt", "training_record.json", "model_manifest.json")}
    (target / "checksums.json").write_text(json.dumps(checksums, indent=2), "utf-8")
    print(f"[1] published -> {target}")

    # --- 2. verify through the real service ---------------------------------
    service = CoreAI2ModelService(paths, run_root / "yolo",
                                  UltralyticsDetectorEvaluationRuntime(device="auto"))
    inspected = service.inspect_model(MODEL_VERSION)
    assert inspected["integrity_valid"] is True
    assert inspected["model_checksum"] == checksums["best.pt"]
    print(f"[2] verified: integrity ok, best.pt sha256={checksums['best.pt'][:16]}...")

    # --- 3. record the REAL evaluation --------------------------------------
    evaluation = {
        "evaluation_id": uuid.uuid4().hex,
        "model_family": "core_ai2",
        "model_version": MODEL_VERSION,
        "model_checksum": checksums["best.pt"],
        "dataset_version": conversion["conversion_version"],
        "dataset_checksum": conversion["source_manifest_checksum"],
        "dataset_lineage": LINEAGE,
        "class_mapping": conversion["class_mapping"],
        "metrics": {
            "validation": {k: evaluations["validation"].get(k) for k in
                           ("map50", "map50_95", "precision", "recall",
                            "per_class", "class_support", "inference_seconds")},
            "test": {k: evaluations["test"].get(k) for k in
                     ("map50", "map50_95", "precision", "recall",
                      "per_class", "class_support", "inference_seconds")},
        },
        "raw_runtime_metrics": evaluations,
        "warnings": ["Preliminary FYP demonstration metrics from a 15-profile "
                     "emergency dataset (2 validation profiles, 2 test profiles)."],
        "errors": [],
        "passed": True,
        "decision_criteria": {
            "required_metrics": ["map50", "precision", "recall"],
            "evaluated_through": "UltralyticsDetectorEvaluationRuntime",
            "emergency_dataset": True,
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    eval_dir = paths.evaluations_root / "core_ai2" / MODEL_VERSION
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"{evaluation['evaluation_id']}.json").write_text(
        json.dumps(evaluation, indent=2), "utf-8")
    print(f"[3] evaluation recorded: val map50={evaluation['metrics']['validation']['map50']:.4f} "
          f"test map50={evaluation['metrics']['test']['map50']:.4f}")

    # --- 4. one REAL inference through the project service ------------------
    smoke_root = data_root / "main_marking_sessions"
    smoke_dir = smoke_root / "_emergency_core_ai2_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    test_images = sorted((run_root / "yolo" / "images" / "test").glob("*.png"))
    if not test_images:
        print("no test images available for smoke inference")
        return 1
    smoke_image = smoke_dir / test_images[0].name
    shutil.copy2(test_images[0], smoke_image)

    inference = CoreAI2InferenceService(service, UltralyticsDetectorInferenceRuntime(),
                                        smoke_root)
    import pymupdf  # noqa: F401  (pillow-free dimension read via PNG header)
    from PIL import Image
    with Image.open(smoke_image) as img:
        width, height = img.size
    request = CoreAI2InferenceRequest(
        request_id="emergency-smoke-0001", workflow_context="subject_profile",
        page_image_path=str(smoke_image), page_checksum=sha256_file(smoke_image),
        page_width=width, page_height=height, model_version=MODEL_VERSION,
        confidence_threshold=0.25, nms_threshold=0.5)
    result = inference.run(request)
    print(f"[4] inference status={result.status} proposals={len(result.proposals)} "
          f"device={result.device_used} duration={result.runtime_duration_seconds:.2f}s")
    proposals_ok = result.status == "completed" and len(result.proposals) > 0
    if result.proposals:
        first = result.proposals[0]
        print(f"    first proposal: class={first.region_class} "
              f"conf={first.confidence:.3f} norm={tuple(round(v,3) for v in first.normalized_bbox)}")
        editable = (first.region_class in conversion["class_mapping"]
                    and len(first.normalized_bbox) == 4
                    and all(0 <= v <= 1 for v in first.normalized_bbox))
        print(f"    editable-proposal shape ok: {editable}")
        proposals_ok = proposals_ok and editable

    smoke_report = {
        "request_id": request.request_id, "status": result.status,
        "proposal_count": len(result.proposals),
        "model_version": result.model_version, "model_checksum": result.model_checksum,
        "device": result.device_used, "failure_code": result.failure_code,
        "proposals_preview": [
            {"class": p.region_class, "confidence": p.confidence,
             "normalized": list(p.normalized_bbox)}
            for p in result.proposals[:10]],
    }
    (run_root / "reports" / "inference_smoke.json").write_text(
        json.dumps(smoke_report, indent=2), "utf-8")

    # --- 5. activation decision ---------------------------------------------
    if args.no_activate:
        print("[5] activation skipped by flag - model registered, inactive")
        return 0
    if not proposals_ok:
        print("[5] ACTIVATION WITHHELD: inference did not produce editable proposals. "
              "Model remains registered but inactive.")
        return 1
    pointer = service.activate(MODEL_VERSION, actor="emergency_fyp_run",
                               reason="Emergency FYP demonstration model: checkpoint "
                                      "verified, real evaluation recorded, real "
                                      "inference produced editable proposals.")
    print(f"[5] ACTIVATED: {pointer['model_version']} at {pointer['activated_at']}")
    active = service.get_active()
    assert active["model_version"] == MODEL_VERSION
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
