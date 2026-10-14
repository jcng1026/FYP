"""Stable dependency-injected façade for application/UI integration."""

from pathlib import Path

from app.models.core_ai_backend_contracts import BackendError
from app.services.core_ai1_dataset_service import (
    audit_core_ai1_dataset,
    compare_core_ai1_datasets,
    discover_core_ai1_datasets,
    export_core_ai1_dataset as export_core_ai1_dataset_version,
    freeze_core_ai1_dataset,
    inspect_core_ai1_dataset,
)
from app.services.core_ai2_dataset_audit_service import compare_dataset_versions
from app.services.core_ai2_dataset_conversion_service import convert_to_coco, convert_to_yolo
from app.services.core_ai2_dataset_freeze_service import freeze_dataset
from app.services.core_ai2_dataset_registry_service import discover_datasets, get_dataset_entry, inspect_dataset_integrity


class CoreAIBackendRuntimeFacade:
    """UI-safe imports; optional heavy runtimes stay behind injected services."""

    def __init__(self, paths, core_ai1_dataset_root, core_ai2_dataset_root, job_store,
                 core_ai1_training=None, core_ai2_training=None,
                 core_ai1_models=None, core_ai2_models=None,
                 core_ai1_inference=None, core_ai2_inference=None,
                 local_feedback=None, template_feedback=None,
                 review_capture=None, diagnostics=None):
        self.paths = paths
        self.dataset_roots = {"core_ai1": Path(core_ai1_dataset_root), "core_ai2": Path(core_ai2_dataset_root)}
        self.job_store = job_store
        self.training = {"core_ai1": core_ai1_training, "core_ai2": core_ai2_training}
        self.models = {"core_ai1": core_ai1_models, "core_ai2": core_ai2_models}
        self.inference = {"core_ai1": core_ai1_inference or core_ai1_models, "core_ai2": core_ai2_inference}
        self.local_feedback = local_feedback
        self.template_feedback = template_feedback
        self.review_capture = review_capture
        self.diagnostics = diagnostics

    @staticmethod
    def _family(model_family):
        value = getattr(model_family, "value", model_family)
        if value not in ("core_ai1", "core_ai2"):
            raise BackendError("unknown_model_family", "Model family must be core_ai1 or core_ai2.")
        return value

    @staticmethod
    def _require(service, capability):
        if service is None:
            raise BackendError("capability_unavailable", f"{capability} service is not configured.")
        return service

    def _dataset_folder(self, family, version):
        family = self._family(family)
        if family == "core_ai2":
            return self.dataset_roots[family] / get_dataset_entry(self.dataset_roots[family], version)["folder_name"]
        return self.dataset_roots[family] / f"dataset_{version}"

    def list_datasets(self, model_family):
        family = self._family(model_family)
        return discover_core_ai1_datasets(self.dataset_roots[family]) if family == "core_ai1" else discover_datasets(self.dataset_roots[family])

    def export_core_ai1_dataset(self, adapter, version, configuration):
        return export_core_ai1_dataset_version(adapter, self.dataset_roots["core_ai1"], version, configuration)

    def inspect_dataset(self, model_family, version):
        family = self._family(model_family); folder = self._dataset_folder(family, version)
        return inspect_core_ai1_dataset(folder) if family == "core_ai1" else get_dataset_entry(self.dataset_roots[family], version)

    def inspect_core_ai2_dataset_integrity(self, version):
        return inspect_dataset_integrity(self._dataset_folder("core_ai2", version))

    def compare_datasets(self, model_family, left, right):
        family = self._family(model_family); left_folder = self._dataset_folder(family, left); right_folder = self._dataset_folder(family, right)
        return compare_core_ai1_datasets(left_folder, right_folder) if family == "core_ai1" else compare_dataset_versions(left_folder, right_folder)

    def freeze_dataset(self, model_family, version, actor=None, note=None):
        family = self._family(model_family); folder = self._dataset_folder(family, version)
        return freeze_core_ai1_dataset(folder, actor, note) if family == "core_ai1" else freeze_dataset(folder, actor, note)

    def audit_dataset(self, model_family, version):
        family = self._family(model_family); folder = self._dataset_folder(family, version)
        if family == "core_ai1": return audit_core_ai1_dataset(folder)
        from app.services.core_ai2_dataset_audit_service import generate_readiness_audit
        return generate_readiness_audit(folder)

    def convert_dataset(self, model_family, version, output_format, conversion_version):
        family = self._family(model_family)
        if family != "core_ai2": raise BackendError("conversion_unsupported", "Core AI 1 training uses its canonical JSONL export directly.")
        folder = self._dataset_folder(family, version); output_format = output_format.lower()
        if output_format == "yolo": return convert_to_yolo(folder, conversion_version)
        if output_format == "coco": return convert_to_coco(folder, conversion_version)
        raise BackendError("conversion_format_unsupported", "Supported detector formats are yolo and coco.")

    @staticmethod
    def _training_config(family, configuration):
        """Accept either an already-built training-config object (scripts,
        tests) or a plain UI dict, and return the config object the training
        service expects. The UI sends {'target_version', base-model path, ...};
        anything not a dict is passed straight through unchanged."""
        if not isinstance(configuration, dict):
            return configuration
        cfg = dict(configuration)
        model_version = cfg.pop("model_version", None) or cfg.pop("target_version", None)
        if not model_version:
            raise BackendError("invalid_training_config", "A model version label is required.")
        if family == "core_ai1":
            from app.models.core_ai1_training_types import CoreAI1TrainingConfig
            base = cfg.pop("local_base_model_path", None)
            if not base:
                raise BackendError(
                    "base_model_missing",
                    "A local base Transformer folder is required to train Core AI 1.")
            allowed = set(CoreAI1TrainingConfig.__dataclass_fields__) - {
                "local_base_model_path", "model_version"}
            return CoreAI1TrainingConfig(
                local_base_model_path=str(base), model_version=str(model_version),
                **{k: v for k, v in cfg.items() if k in allowed})
        from app.models.core_ai2_training_types import CoreAI2TrainingConfig
        checkpoint = cfg.pop("local_base_checkpoint", None)
        conversion_version = cfg.pop("conversion_version", None)
        if not checkpoint:
            raise BackendError(
                "base_checkpoint_missing",
                "A local base checkpoint (.pt) is required to train Core AI 2.")
        if not conversion_version:
            raise BackendError(
                "conversion_version_required",
                "A YOLO-converted dataset version is required to train Core AI 2.")
        allowed = set(CoreAI2TrainingConfig.__dataclass_fields__) - {
            "local_base_checkpoint", "model_version", "conversion_version"}
        return CoreAI2TrainingConfig(
            local_base_checkpoint=str(checkpoint), model_version=str(model_version),
            conversion_version=str(conversion_version),
            **{k: v for k, v in cfg.items() if k in allowed})

    def validate_training_request(self, model_family, dataset_version, configuration):
        family = self._family(model_family); service = self._require(self.training[family], "training")
        config = self._training_config(family, configuration)
        # Both training services validate by RAISING BackendError and returning
        # an internal (dataset, manifest, ...) tuple on success; the caller
        # wants a blocker-list contract, so adapt: [] means ready to train.
        try:
            if family == "core_ai1":
                service._validate(dataset_version, config)
            else:
                service.validate(dataset_version, config)
        except BackendError as exc:
            return [exc.safe_message]
        return []

    def create_training_job(self, model_family, dataset_version, configuration):
        family = self._family(model_family)
        config = self._training_config(family, configuration)
        return self._require(self.training[family], "training").create_job(dataset_version, config)

    def run_training_job(self, job_id, configuration):
        record = self.job_store.get(job_id); family = self._family(record.model_family)
        config = self._training_config(family, configuration)
        return self._require(self.training[family], "training").run(job_id, config)

    def cancel_training_job(self, job_id):
        record = self.job_store.get(job_id); return self._require(self.training[self._family(record.model_family)], "training").cancel(job_id)

    def get_training_job(self, job_id): return self.job_store.get(job_id)
    def list_training_jobs(self, model_family=None): return self.job_store.list(self._family(model_family) if model_family else None)
    def recover_interrupted_jobs(self): return self.job_store.recover_interrupted()

    def list_models(self, model_family):
        family = self._family(model_family); models = self._require(self.models[family], "model registry").list_models()
        return [model for model in models if model.get("integrity_valid", True)]

    def inspect_model(self, model_family, version):
        family = self._family(model_family); return self._require(self.models[family], "model registry").inspect_model(version)

    def evaluate_model(self, model_family, model_version, dataset_version):
        family = self._family(model_family); return self._require(self.models[family], "evaluation").evaluate(model_version, dataset_version)

    def compare_models(self, model_family, left, right):
        family = self._family(model_family); return self._require(self.models[family], "model registry").compare(left, right)

    def activate_model(self, model_family, version, actor, reason):
        family = self._family(model_family); return self._require(self.models[family], "activation").activate(version, actor, reason)

    def rollback_model(self, model_family, target_version, actor, reason):
        family = self._family(model_family); return self._require(self.models[family], "activation").rollback(target_version, actor, reason)

    def get_active_model(self, model_family, required=True):
        family = self._family(model_family); return self._require(self.models[family], "model registry").get_active(required)

    def inspect_runtime(self, request): return self._require(self.diagnostics, "runtime diagnostics").inspect(request)
    def run_core_ai2_inference(self, request, cancellation_token=None): return self._require(self.inference["core_ai2"], "Core AI 2 inference").run(request, cancellation_token)
    def run_core_ai1_inference(self, request): return self._require(self.inference["core_ai1"], "Core AI 1 inference").infer(request)
    def run_core_ai1_attempt_inference(self, requests): return self._require(self.inference["core_ai1"], "Core AI 1 inference").infer_attempt(requests)
    def generate_local_feedback(self, request, cancellation_token=None): return self._require(self.local_feedback, "local feedback").generate(request, cancellation_token)
    def generate_template_feedback(self, request): return self._require(self.template_feedback, "template feedback").generate(request)
    def capture_core_ai1_reviews(self, candidate_version, records): return self._require(self.review_capture, "review capture").capture_core_ai1(candidate_version, records)
    def capture_core_ai2_reviews(self, candidate_version, records): return self._require(self.review_capture, "review capture").capture_core_ai2(candidate_version, records)
