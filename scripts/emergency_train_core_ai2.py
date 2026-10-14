"""Emergency Core AI 2 baseline training + evaluation driver.

Runs in the dedicated AI environment (AutoMarkingSystem/AI-Env). Trains one
baseline nano detector on the emergency YOLO dataset, then evaluates the best
checkpoint on the validation AND test splits through the project's REAL
UltralyticsDetectorEvaluationRuntime - not only the Ultralytics CLI - so the
recorded metrics carry the same validation the application applies.

Everything it writes stays inside the run workspace (never the repository):
    <run>/runs/<model_version>/        Ultralytics training output
    <run>/models/<model_version>/      best/last weights + environment record
    <run>/reports/evaluation_*.json    real runtime evaluation output

Usage (from the repository root, with the AI venv python):
    python scripts/emergency_train_core_ai2.py --run-root <workspace run dir> \
        [--batch 4] [--epochs 40] [--resume-batch-retry]
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

MODEL_VERSION = "core_ai2_detector_emergency_v1"
BASE_CHECKPOINT = "yolo11n.pt"  # official Ultralytics nano checkpoint
SEED = 42


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    yolo_root = run_root / "yolo"
    data_yaml = yolo_root / "data.yaml"
    if not data_yaml.is_file():
        print(f"data.yaml not found: {data_yaml}")
        return 1
    (run_root / "models").mkdir(exist_ok=True)
    (run_root / "reports").mkdir(exist_ok=True)

    import torch
    import ultralytics
    from ultralytics import YOLO

    cuda = torch.cuda.is_available()
    device = 0 if cuda else "cpu"
    environment = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "cuda_available": cuda,
        "cuda_version": getattr(torch.version, "cuda", None),
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1) if cuda else None,
    }
    print("ENV:", json.dumps(environment))
    if not cuda:
        print("WARNING: CUDA unavailable - this will be a CPU pipeline check only.")

    # Base checkpoint through the official Ultralytics mechanism. YOLO() will
    # fetch the standard pretrained checkpoint if it is not already local.
    base_dir = run_root / "models" / "base"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_path = base_dir / BASE_CHECKPOINT
    started = datetime.now(timezone.utc).isoformat()
    model = YOLO(BASE_CHECKPOINT)
    ckpt_file = Path(model.ckpt_path) if getattr(model, "ckpt_path", None) else Path(BASE_CHECKPOINT)
    if ckpt_file.is_file() and not base_path.is_file():
        base_path.write_bytes(ckpt_file.read_bytes())
    base_checksum = sha256_file(base_path) if base_path.is_file() else None
    print(f"BASE: {ckpt_file} sha256={base_checksum}")

    train_kwargs = dict(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=device, workers=2, patience=8, seed=SEED,
        pretrained=True, plots=True, save=True, exist_ok=True,
        project=str(run_root / "runs"), name=MODEL_VERSION,
    )
    attempts = []
    t0 = time.perf_counter()
    try:
        results = model.train(**train_kwargs)
        attempts.append({"batch": args.batch, "outcome": "completed"})
    except torch.cuda.OutOfMemoryError as exc:
        # One documented retry at half batch, per the emergency plan.
        attempts.append({"batch": args.batch, "outcome": f"cuda_oom: {exc}"})
        retry_batch = max(1, args.batch // 2)
        print(f"CUDA OOM at batch={args.batch}; retrying once at batch={retry_batch}")
        torch.cuda.empty_cache()
        train_kwargs["batch"] = retry_batch
        model = YOLO(BASE_CHECKPOINT)
        results = model.train(**train_kwargs)
        attempts.append({"batch": retry_batch, "outcome": "completed"})
    duration = time.perf_counter() - t0

    run_dir = run_root / "runs" / MODEL_VERSION
    best = run_dir / "weights" / "best.pt"
    last = run_dir / "weights" / "last.pt"
    if not best.is_file():
        print("training produced no best.pt - aborting")
        return 1

    model_dir = run_root / "models" / MODEL_VERSION
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "best.pt").write_bytes(best.read_bytes())
    (model_dir / "last.pt").write_bytes(last.read_bytes())
    best_checksum = sha256_file(model_dir / "best.pt")

    record = {
        "model_version": MODEL_VERSION,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 1),
        "environment": environment,
        "base_checkpoint": {"name": BASE_CHECKPOINT, "path": str(base_path),
                            "sha256": base_checksum},
        "training_arguments": {k: str(v) for k, v in train_kwargs.items()},
        "attempts": attempts,
        "best_checkpoint": str(model_dir / "best.pt"),
        "best_checksum": best_checksum,
        "last_checkpoint": str(model_dir / "last.pt"),
        "ultralytics_run_dir": str(run_dir),
        "seed": SEED,
    }
    (model_dir / "training_record.json").write_text(json.dumps(record, indent=2),
                                                    encoding="utf-8")
    print(f"TRAINED: best={model_dir / 'best.pt'} sha256={best_checksum[:16]}...")

    # --- evaluation through the PROJECT runtime (validation + test) ---------
    from app.ml.core_ai2_evaluation_runtime import UltralyticsDetectorEvaluationRuntime

    runtime = UltralyticsDetectorEvaluationRuntime(device="auto")
    for split in ("validation", "test"):
        result = runtime.evaluate(model_dir / "best.pt", yolo_root, split)
        out = run_root / "reports" / f"evaluation_{split}.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"EVAL[{split}]: map50={result.get('map50'):.4f} "
              f"map50_95={result.get('map50_95'):.4f} "
              f"precision={result.get('precision'):.4f} "
              f"recall={result.get('recall'):.4f} -> {out.name}")
    runtime.unload()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
