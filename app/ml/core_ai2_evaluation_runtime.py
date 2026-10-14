"""Local-checkpoint-only Ultralytics evaluation for published Core AI 2 models."""

from importlib import import_module, util
import json
import math
from pathlib import Path
import re
import tempfile
import time

from app.models.core_ai_backend_contracts import BackendError
from app.services.core_ai2_dataset_registry_service import sha256_file


def _plain_sequence(value):
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else None


def _plain_float(value):
    try:
        converted = float(value)
        return converted if math.isfinite(converted) else None
    except (TypeError, ValueError):
        return None


class _UltralyticsEvaluationBackend:
    def __init__(self, checkpoint, device):
        ultralytics = import_module("ultralytics")
        self.model = ultralytics.YOLO(str(checkpoint))
        self.device = device

    def evaluate(self, data_yaml, split):
        started = time.perf_counter()
        source_yaml = Path(data_yaml)
        yaml_lines = source_yaml.read_text(encoding="utf-8").splitlines()
        runtime_lines = []
        path_replaced = False
        for line in yaml_lines:
            stripped = line.strip()
            if stripped.startswith("path:"):
                runtime_lines.append(f"path: {json.dumps(source_yaml.parent.as_posix())}")
                path_replaced = True
            elif stripped.startswith("validation:"):
                runtime_lines.append(f"val:{line.split(':', 1)[1]}")
            else:
                runtime_lines.append(line)
        if not path_replaced:
            runtime_lines.insert(0, f"path: {json.dumps(source_yaml.parent.as_posix())}")
        runtime_split = "val" if split == "validation" else split
        with tempfile.TemporaryDirectory(prefix="core_ai2_evaluation_") as temporary:
            temporary_root = Path(temporary)
            runtime_yaml = temporary_root / "data.yaml"
            runtime_yaml.write_text("\n".join(runtime_lines) + "\n", encoding="utf-8")
            result = self.model.val(
                data=str(runtime_yaml), split=runtime_split, device=self.device,
                project=str(temporary_root / "runs"), name=runtime_split,
                exist_ok=True, save=False, plots=False, verbose=False,
            )
        output = {"runtime": "ultralytics", "device": self.device}
        box = getattr(result, "box", None)
        scalar_fields = {
            "map50": getattr(box, "map50", None),
            "map50_95": getattr(box, "map", None),
            "precision": getattr(box, "mp", None),
            "recall": getattr(box, "mr", None),
        }
        for name, value in scalar_fields.items():
            converted = _plain_float(value)
            if converted is not None:
                output[name] = converted

        names = getattr(result, "names", None) or getattr(self.model, "names", {}) or {}
        class_ids = _plain_sequence(getattr(box, "ap_class_index", None))
        precision = _plain_sequence(getattr(box, "p", None))
        recall = _plain_sequence(getattr(box, "r", None))
        ap50 = _plain_sequence(getattr(box, "ap50", None))
        maps = _plain_sequence(getattr(box, "maps", None))
        support = _plain_sequence(getattr(box, "nt_per_class", None)) or _plain_sequence(getattr(result, "nt_per_class", None))
        lengths = [len(values) for values in (precision, recall, ap50, maps) if values is not None]
        count = min(lengths) if lengths else 0
        if class_ids is None:
            class_ids = list(range(count))
        per_class = {}
        class_support = {}
        for position, raw_class_id in enumerate(class_ids[:count]):
            class_id = int(raw_class_id)
            label = str(names.get(class_id, class_id)) if isinstance(names, dict) else str(class_id)
            metrics = {}
            for key, values in (("precision", precision), ("recall", recall), ("map50", ap50), ("map50_95", maps)):
                value_position = class_id if key == "map50_95" and values is not None and class_id < len(values) else position
                if values is not None and value_position < len(values):
                    converted = _plain_float(values[value_position])
                    if converted is not None:
                        metrics[key] = converted
            per_class[label] = metrics
            if support is not None:
                if len(support) > class_id:
                    class_support[label] = int(support[class_id])
                elif len(support) > position:
                    class_support[label] = int(support[position])
        if per_class:
            output["per_class"] = per_class
        if class_support:
            output["class_support"] = class_support

        results_dict = getattr(result, "results_dict", None)
        if isinstance(results_dict, dict):
            losses = {
                str(key): converted
                for key, value in results_dict.items()
                if "loss" in str(key).lower() and (converted := _plain_float(value)) is not None
            }
            if losses:
                output["losses"] = losses
        speed = getattr(result, "speed", None)
        reported_inference = _plain_float(speed.get("inference")) if isinstance(speed, dict) else None
        if reported_inference is not None:
            output["inference_seconds"] = reported_inference / 1000.0
        else:
            output["evaluation_duration_seconds"] = time.perf_counter() - started
        return output

    def class_mapping(self):
        names = getattr(self.model, "names", {}) or {}
        if isinstance(names, dict):
            return {str(name): int(identifier) for identifier, name in names.items()}
        if isinstance(names, (list, tuple)):
            return {str(name): identifier for identifier, name in enumerate(names)}
        return None

    def unload(self):
        self.model = None


class UltralyticsDetectorEvaluationRuntime:
    """Validates a YOLO conversion and evaluates validation/test without mutation."""

    runtime_name = "ultralytics_detector_evaluation"

    def __init__(self, device="auto", backend_factory=None, module_finder=None, cuda_available=None):
        self.requested_device = device
        self.backend_factory = backend_factory
        self.module_finder = module_finder or util.find_spec
        self.cuda_available = cuda_available
        self._backend = None
        self._checkpoint_checksum = None
        self._device = None

    def inspect(self):
        if self.backend_factory is not None:
            available = True
        else:
            try:
                available = self.module_finder("ultralytics") is not None
            except (ImportError, ValueError):
                available = False
        return {
            "runtime": self.runtime_name,
            "available": available,
            "requested_device": self.requested_device,
            "device": self._device,
            "loaded": self._backend is not None,
            "checkpoint_checksum": self._checkpoint_checksum,
            "local_checkpoint_only": True,
        }

    def _resolve_device(self):
        if self.requested_device not in ("auto", "cpu", "cuda"):
            raise BackendError("device_unsupported", "Detector evaluation device must be auto, cpu or cuda.")
        if self.cuda_available is not None:
            cuda_available = bool(self.cuda_available())
        elif self.backend_factory is not None:
            cuda_available = False
        else:
            try:
                torch = import_module("torch")
                cuda_available = bool(torch.cuda.is_available())
            except ImportError:
                cuda_available = False
        if self.requested_device == "cuda" and not cuda_available:
            raise BackendError("cuda_unavailable", "CUDA was requested for detector evaluation but is unavailable.")
        return "cuda" if self.requested_device in ("auto", "cuda") and cuda_available else "cpu"

    @staticmethod
    def _validate_conversion(conversion_folder, split):
        folder = Path(conversion_folder).resolve()
        if split not in ("validation", "test"):
            raise BackendError("evaluation_split_unsupported", "Detector evaluation split must be validation or test.")
        try:
            manifest = json.loads((folder / "conversion_manifest.json").read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackendError("conversion_incomplete", "YOLO conversion metadata is unavailable.") from exc
        if manifest.get("format") != "yolo":
            raise BackendError("conversion_incompatible", "Detector evaluation requires a YOLO conversion.")
        if manifest.get("split_mode") != "three_way":
            raise BackendError("evaluation_split_missing", "Detector evaluation requires three-way split metadata.")
        data_yaml = folder / "data.yaml"
        if not data_yaml.is_file():
            raise BackendError("conversion_incomplete", "YOLO data.yaml is unavailable.")
        checksums = manifest.get("file_checksums")
        if not isinstance(checksums, dict) or not checksums:
            raise BackendError("conversion_checksum_missing", "YOLO conversion checksums are unavailable.")
        actual_files = {
            path.relative_to(folder).as_posix()
            for path in folder.rglob("*")
            if path.is_file() and path.name != "conversion_manifest.json"
        }
        if set(checksums) != actual_files:
            raise BackendError("conversion_checksum_inventory_mismatch", "YOLO conversion checksum inventory is incomplete or unexpected.")
        for relative, expected in checksums.items():
            artifact = (folder / relative).resolve()
            if folder not in artifact.parents:
                raise BackendError("conversion_checksum_path_invalid", "YOLO conversion checksum inventory contains an unsafe path.")
            if not artifact.is_file() or sha256_file(artifact) != expected:
                raise BackendError("conversion_checksum_mismatch", "YOLO conversion checksum validation failed.")
        yaml_text = data_yaml.read_text(encoding="utf-8")
        identifiers = {}
        declared_count = None
        in_names = False
        for line in yaml_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("nc:"):
                try:
                    declared_count = int(stripped.partition(":")[2].strip())
                except ValueError as exc:
                    raise BackendError("class_mapping_incompatible", "YOLO conversion class count is invalid.") from exc
            if stripped.startswith("names:"):
                in_names = True
                inline = stripped.partition(":")[2].strip()
                if inline.startswith("[") and inline.endswith("]"):
                    labels = [value.strip().strip("'\"") for value in inline[1:-1].split(",") if value.strip()]
                    identifiers = {index: label for index, label in enumerate(labels)}
                continue
            match = re.match(r"^(\d+)\s*:\s*(.+?)\s*$", stripped) if in_names else None
            if match:
                identifiers[int(match.group(1))] = match.group(2).strip().strip("'\"")
            elif in_names and stripped and not line[:1].isspace():
                in_names = False
        class_mapping = {name: identifier for identifier, name in identifiers.items()}
        if (not class_mapping or declared_count != len(identifiers)
                or sorted(identifiers) != list(range(len(identifiers)))
                or len(class_mapping) != len(identifiers)):
            raise BackendError("class_mapping_incompatible", "YOLO conversion class mapping is missing or invalid.")
        records = [record for record in manifest.get("records", []) if record.get("split") == split]
        if not records:
            raise BackendError("evaluation_split_empty", f"{split} conversion split is empty.")
        return folder, manifest, data_yaml, len(records), class_mapping

    def _load(self, checkpoint):
        path = Path(checkpoint).resolve()
        if not path.is_file():
            raise BackendError("model_artifact_missing", "Local detector checkpoint is missing.")
        if not self.inspect()["available"]:
            raise BackendError("evaluation_runtime_unavailable", "Ultralytics optional dependency is unavailable.")
        checksum = sha256_file(path)
        if self._backend is not None and checksum == self._checkpoint_checksum:
            return True
        self.unload()
        device = self._resolve_device()
        factory = self.backend_factory or _UltralyticsEvaluationBackend
        try:
            self._backend = factory(path, device)
        except BackendError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "out of memory" in message or "cuda oom" in message:
                raise BackendError("out_of_memory", "Detector evaluation model loading ran out of memory.") from exc
            raise BackendError("model_load_failed", "Local detector checkpoint could not be loaded for evaluation.") from exc
        self._checkpoint_checksum = checksum
        self._device = device
        return False

    def unload(self):
        if self._backend is not None and hasattr(self._backend, "unload"):
            self._backend.unload()
        self._backend = None
        self._checkpoint_checksum = None
        self._device = None

    def evaluate(self, checkpoint, conversion_folder, split):
        started = time.perf_counter()
        _, manifest, data_yaml, support, class_mapping = self._validate_conversion(conversion_folder, split)
        cache_hit = self._load(checkpoint)
        backend_mapping = self._backend.class_mapping() if hasattr(self._backend, "class_mapping") else None
        if backend_mapping is not None and backend_mapping != class_mapping:
            self.unload()
            raise BackendError("class_mapping_incompatible", "Detector checkpoint and YOLO conversion class mappings differ.")
        try:
            raw = self._backend.evaluate(data_yaml, split)
        except BackendError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "out of memory" in message or "cuda oom" in message:
                self.unload()
                raise BackendError("out_of_memory", "Detector evaluation ran out of memory; reduce image or batch settings.") from exc
            raise BackendError("evaluation_runtime_failure", "Local detector evaluation failed.") from exc
        allowed = ("map50", "map50_95", "precision", "recall", "per_class", "class_support", "losses", "inference_seconds", "evaluation_duration_seconds")
        result = {key: raw[key] for key in allowed if key in raw and raw[key] is not None}
        result.update({
            "split": split,
            "conversion_version": manifest.get("conversion_version"),
            "source_manifest_checksum": manifest.get("source_manifest_checksum"),
            "class_mapping": class_mapping,
            "conversion_record_support": support,
            "runtime": self.runtime_name,
            "runtime_details": {"adapter": self.runtime_name, "backend": raw.get("runtime"), "device": self._device, "local_checkpoint_only": True},
            "device": self._device,
            "checkpoint_checksum": self._checkpoint_checksum,
            "cache_hit": cache_hit,
            "duration_seconds": time.perf_counter() - started,
        })
        return result
