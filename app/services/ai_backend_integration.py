"""Stage 12G-13 - the application's single entry point to the Core AI backend.

This is the ONE place the application builds `CoreAIBackendRuntimeFacade`. It is
Claude-owned and lives outside every protected `core_ai*` namespace; it adds no
backend behaviour of its own.

Three properties matter here:

- **Lazy.** The facade is built on first use and cached per application data
  root, so importing this module costs nothing and switching data root (tests,
  an isolated verification run) rebuilds cleanly.
- **Optional-dependency safe.** Concrete runtimes live behind
  `app.ml.*` / `app.training.*`, which import PyTorch, Transformers or
  Ultralytics. Each is imported lazily inside its own guard, so a machine
  without them still builds a working facade - the affected capability is simply
  not injected, and the backend then reports
  `BackendError("capability_unavailable")` rather than pretending.
- **Injectable.** `set_backend_facade()` lets tests substitute a deterministic
  double; `reset_backend_facade()` restores normal production construction.

Nothing here ever falls back to a fake in normal application use.
"""
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Facade + paths + job store are dependency-free and safe to import eagerly.
from app.services.core_ai_backend_job_service import AIJobStore
from app.services.core_ai_backend_paths import AIBackendPaths
from app.services.core_ai_backend_runtime_facade import CoreAIBackendRuntimeFacade

_lock = threading.RLock()
_facade: Optional[CoreAIBackendRuntimeFacade] = None
_facade_root: Optional[Path] = None
_injected = False

# Capabilities that could not be wired on this machine, with the reason. Read by
# the interface so a missing runtime is reported factually instead of guessed.
_unavailable: Dict[str, str] = {}


def application_data_root() -> Path:
    """The configured application data root (honours the isolated-run override
    used by tests and verification)."""
    from app.database.db import DATA_DIR
    return Path(DATA_DIR)


def core_ai1_dataset_root(data_root: Optional[Path] = None) -> Path:
    return Path(data_root or application_data_root()) / "ai_datasets" / "core_ai1"


def core_ai2_dataset_root(data_root: Optional[Path] = None) -> Path:
    return Path(data_root or application_data_root()) / "ai_datasets" / "core_ai2"


def approved_image_root(data_root: Optional[Path] = None) -> Path:
    """Core AI 2 inference may only read page images beneath approved roots;
    this is the marking-attempt root (kept for existing callers)."""
    return Path(data_root or application_data_root()) / "main_marking_sessions"


def approved_image_roots(data_root: Optional[Path] = None) -> list:
    """All roots Core AI 2 inference may read page images from - the two page
    workflows: marking attempts (Separate Answer Paper pages) and Subject
    Profile page renders."""
    base = Path(data_root or application_data_root())
    return [base / "main_marking_sessions", base / "subject_profiles"]


def _try(capability: str, build):
    """Wire one optional capability. A missing heavy dependency is recorded and
    the capability is left unwired - never substituted."""
    try:
        service = build()
        _unavailable.pop(capability, None)
        return service
    except Exception as exc:  # ImportError and any runtime construction failure
        _unavailable[capability] = f"{type(exc).__name__}: {exc}"
        return None


def _build_facade(data_root: Path) -> CoreAIBackendRuntimeFacade:
    """Construct the real facade for a data root, wiring every capability whose
    dependencies are actually installed."""
    _unavailable.clear()
    paths = AIBackendPaths(Path(data_root))
    paths.ensure_layout()
    ds1 = core_ai1_dataset_root(data_root)
    ds2 = core_ai2_dataset_root(data_root)
    ds1.mkdir(parents=True, exist_ok=True)
    ds2.mkdir(parents=True, exist_ok=True)
    job_store = AIJobStore(paths)

    def _core_ai1_models():
        from app.ml.core_ai1_inference_runtime import TransformersMultiTaskInferenceRuntime
        from app.services.core_ai1_model_service import CoreAI1ModelService
        return CoreAI1ModelService(paths, ds1, TransformersMultiTaskInferenceRuntime(device="auto"))

    def _core_ai2_models():
        from app.ml.core_ai2_evaluation_runtime import UltralyticsDetectorEvaluationRuntime
        from app.services.core_ai2_model_service import CoreAI2ModelService
        return CoreAI2ModelService(paths, ds2, UltralyticsDetectorEvaluationRuntime(device="auto"))

    def _core_ai1_training():
        from app.ml.core_ai1_cross_encoder_runtime import TransformersMultiTaskRuntime
        from app.training.core_ai1_training import CoreAI1TrainingService
        return CoreAI1TrainingService(paths, ds1, TransformersMultiTaskRuntime(), job_store)

    def _core_ai2_training():
        from app.ml.core_ai2_detector_runtime import UltralyticsDetectorTrainingRuntime
        from app.training.core_ai2_training import CoreAI2TrainingService
        return CoreAI2TrainingService(paths, ds2, UltralyticsDetectorTrainingRuntime(), job_store)

    core_ai1_models = _try("core_ai1_models", _core_ai1_models)
    core_ai2_models = _try("core_ai2_models", _core_ai2_models)

    def _core_ai2_inference():
        from app.ml.core_ai2_inference_runtime import UltralyticsDetectorInferenceRuntime
        from app.services.core_ai2_inference_service import CoreAI2InferenceService
        if core_ai2_models is None:
            raise RuntimeError("Core AI 2 model service is unavailable.")
        return CoreAI2InferenceService(core_ai2_models, UltralyticsDetectorInferenceRuntime(),
                                       approved_image_roots(data_root))

    def _local_feedback():
        from app.services.core_ai1_local_feedback_service import LocalFeedbackService
        return LocalFeedbackService()

    def _template_feedback():
        from app.services.core_ai1_template_feedback_service import TemplateFeedbackService
        return TemplateFeedbackService()

    def _review_capture():
        from app.services.core_ai_backend_review_capture_service import ReviewCaptureService
        return ReviewCaptureService(paths)

    def _diagnostics():
        from app.services.core_ai_backend_diagnostics_service import AIRuntimeDiagnosticsService
        return AIRuntimeDiagnosticsService(paths, ds1, ds2)

    return CoreAIBackendRuntimeFacade(
        paths=paths,
        core_ai1_dataset_root=ds1,
        core_ai2_dataset_root=ds2,
        job_store=job_store,
        core_ai1_training=_try("core_ai1_training", _core_ai1_training),
        core_ai2_training=_try("core_ai2_training", _core_ai2_training),
        core_ai1_models=core_ai1_models,
        core_ai2_models=core_ai2_models,
        core_ai1_inference=core_ai1_models,   # the model service also infers
        core_ai2_inference=_try("core_ai2_inference", _core_ai2_inference),
        local_feedback=_try("local_feedback", _local_feedback),
        template_feedback=_try("template_feedback", _template_feedback),
        review_capture=_try("review_capture", _review_capture),
        diagnostics=_try("diagnostics", _diagnostics),
    )


def get_backend_facade() -> CoreAIBackendRuntimeFacade:
    """The facade for the CURRENT data root, built once and reused.

    A changed data root replaces the cached instance, so an isolated run never
    reads or writes another root's AI artifacts.
    """
    global _facade, _facade_root
    with _lock:
        if _injected and _facade is not None:
            return _facade
        root = application_data_root()
        if _facade is None or _facade_root != root:
            _facade = _build_facade(root)
            _facade_root = root
        return _facade


def set_backend_facade(facade) -> None:
    """Inject a facade (a deterministic double in tests). Production code never
    calls this."""
    global _facade, _facade_root, _injected
    with _lock:
        _facade = facade
        _facade_root = application_data_root()
        _injected = True


def reset_backend_facade() -> None:
    """Drop any cached or injected facade and return to normal construction."""
    global _facade, _facade_root, _injected
    with _lock:
        _facade = None
        _facade_root = None
        _injected = False
        _unavailable.clear()


def unavailable_capabilities() -> Dict[str, str]:
    """Capabilities that could not be wired here, with the reason. Empty when
    every optional dependency is installed."""
    get_backend_facade()
    return dict(_unavailable)


def capability_available(capability: str) -> bool:
    return capability not in unavailable_capabilities()


def missing_dependency_summary() -> List[str]:
    """Teacher/admin-readable lines describing what is unavailable and why."""
    reasons = {
        "core_ai1_models": "Core AI 1 scoring (install torch and transformers)",
        "core_ai1_training": "Core AI 1 training (install torch and transformers)",
        "core_ai2_models": "Core AI 2 evaluation (install ultralytics)",
        "core_ai2_training": "Core AI 2 training (install ultralytics)",
        "core_ai2_inference": "Core AI 2 region proposals (install ultralytics)",
        "local_feedback": "Local natural-language feedback",
        "template_feedback": "Built-in feedback templates",
        "review_capture": "Teacher review capture",
        "diagnostics": "Runtime diagnostics",
    }
    return [reasons.get(name, name) for name in sorted(unavailable_capabilities())]
