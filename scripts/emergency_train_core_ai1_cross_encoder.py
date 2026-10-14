"""Train, evaluate and (conditionally) activate the emergency Core AI 1 model.

Runs ONLY against a dataset the REAL production exporter declared
training_ready - no fabricated labels, scores or metrics anywhere:

1. installs the frozen exporter output into the application's Core AI 1
   dataset root and freezes it with the production freeze (integrity
   inventory + .frozen marker);
2. trains through the production CoreAI1TrainingService job pipeline
   (validation gates: frozen + training_ready + three-way split + local base
   model + runtime availability; atomic immutable publication);
3. evaluates through the production CoreAI1ModelService on the dataset's
   validation and test splits with the REAL inference runtime;
4. activates ONLY if the evaluation passed, then proves one real end-to-end
   draft inference on a held-out test sample.

Usage:
    python scripts/emergency_train_core_ai1_cross_encoder.py \
        --dataset-src "<run>/frozen_dataset/dataset_core_ai1_k2_emergency_v2" \
        --data-root  "C:/Users/User/Documents/AutoMarkingSystem/english_grading_system/data" \
        --base-model "C:/Users/User/Documents/AutoMarkingSystem/FYP-Data/core_ai1_emergency_training/base_models/all-MiniLM-L6-v2" \
        [--no-activate]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

MODEL_VERSION = "core_ai1_cross_encoder_emergency_v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-src", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()

    from app.services.core_ai_backend_paths import AIBackendPaths
    from app.services.core_ai_backend_job_service import AIJobStore
    from app.services.core_ai1_dataset_service import (
        freeze_core_ai1_dataset, inspect_core_ai1_dataset,
    )
    from app.models.core_ai1_training_types import CoreAI1TrainingConfig
    from app.ml.core_ai1_cross_encoder_runtime import TransformersMultiTaskRuntime
    from app.ml.core_ai1_inference_runtime import TransformersMultiTaskInferenceRuntime
    from app.training.core_ai1_training import CoreAI1TrainingService
    from app.services.core_ai1_model_service import CoreAI1ModelService

    data_root = Path(args.data_root)
    dataset_src = Path(args.dataset_src)
    dataset_version = dataset_src.name.removeprefix("dataset_")
    dataset_root = data_root / "ai_datasets" / "core_ai1"
    dataset_dst = dataset_root / dataset_src.name

    manifest = json.loads((dataset_src / "manifest.json").read_text("utf-8"))
    if not manifest.get("training_ready"):
        raise SystemExit("REFUSING: the exporter did not declare this dataset training-ready.")

    # [1] install + freeze through production code
    if not dataset_dst.exists():
        dataset_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dataset_src, dataset_dst)
    integrity = inspect_core_ai1_dataset(dataset_dst)
    if not integrity["valid"]:
        raise SystemExit(f"REFUSING: dataset integrity failed: {integrity}")
    if not (dataset_dst / ".frozen").is_file():
        freeze_core_ai1_dataset(dataset_dst, actor="emergency_training_script",
                                note="Emergency Core AI 1 training dataset (34 honest records).")
    print(f"[1] dataset installed+frozen: {dataset_dst}")

    # [2] production training job
    paths = AIBackendPaths(data_root)
    job_store = AIJobStore(paths)
    training = CoreAI1TrainingService(paths, dataset_root,
                                      TransformersMultiTaskRuntime(), job_store)
    config = CoreAI1TrainingConfig(
        local_base_model_path=str(Path(args.base_model)),
        model_version=MODEL_VERSION, seed=42)
    job = training.create_job(dataset_version, config)
    record = training.run(job.job_id, config)
    print(f"[2] training job {job.job_id}: {record.status}")
    if record.status != "completed":
        print(f"    failure: {record.failure_code} - {record.failure_message}")
        return 1

    # [3] production evaluation on validation + test splits
    models = CoreAI1ModelService(paths, dataset_root,
                                 TransformersMultiTaskInferenceRuntime())
    evaluation = models.evaluate(MODEL_VERSION, dataset_version)
    for split in ("validation", "test"):
        metrics = evaluation["metrics"][split]["metrics"]
        print(f"[3] {split}: {json.dumps(metrics)}")
    for warning in evaluation["warnings"]:
        print(f"    warning: {warning}")
    if not evaluation["passed"]:
        print("    evaluation did not pass; NOT activating.")
        return 1

    if args.no_activate:
        print("[4] --no-activate: model remains inactive.")
        return 0

    # [4] activation (gate re-checks integrity + passing evaluation)
    pointer = models.activate(MODEL_VERSION, "emergency_training_script",
                              "Emergency Core AI 1 activation after passing evaluation "
                              "on the honestly-extracted 34-record dataset.")
    print(f"[4] ACTIVATED: {pointer['model_version']} at {pointer['activated_at']}")

    # [5] one real end-to-end inference on a held-out test sample
    samples = [json.loads(line) for line in
               (dataset_dst / "samples.jsonl").read_text("utf-8").splitlines() if line]
    split = json.loads((dataset_dst / "splits.json").read_text("utf-8"))
    test_row = next(s for s in samples
                    if split["assignments"].get(s["sample_id"]) == "test")
    from app.models.core_ai1_inference_types import CoreAI1InferenceRequest
    result = models.infer(CoreAI1InferenceRequest(
        request_id="post-train-smoke",
        task_context=test_row.get("question_text", ""),
        marking_scheme=test_row.get("marking_scheme_text", ""),
        effective_student_answer=test_row["effective_student_answer"],
        paper="kertas2", part=test_row["part_identifier"],
        maximum_score=test_row["maximum_score"], input_checksum="smoke",
        selected_part3_question=test_row.get("selected_part3_question")))
    print(f"[5] smoke inference: status={result.status} "
          f"draft={result.proposed_application_score}/{test_row['maximum_score']} "
          f"category={result.feedback_category} device={result.device}")
    if result.status != "completed":
        print("    smoke inference failed after activation - investigate before use.")
        return 1
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
