"""Local-files-only Hugging Face inference for published Core AI 1 models."""

from decimal import Decimal, ROUND_HALF_UP
import hashlib
from importlib import import_module, util
import json
import math
from pathlib import Path
import time

from app.ml.core_ai1_cross_encoder_runtime import INPUT_TEMPLATE_VERSION, compose_input
from app.models.core_ai_backend_contracts import BackendError
from app.models.core_ai1_inference_types import ROUNDING_POLICY_VERSION
from app.services.core_ai2_dataset_registry_service import sha256_file


class _HuggingFaceMultiTaskBackend:
    """Heavy implementation instantiated only after all local artifacts validate."""

    def __init__(self, model_folder, manifest, device):
        torch = import_module("torch")
        transformers = import_module("transformers")
        nn = torch.nn
        folder = Path(model_folder)
        encoder = transformers.AutoModel.from_pretrained(str(folder / "encoder"), local_files_only=True)
        tokenizer = transformers.AutoTokenizer.from_pretrained(str(folder / "tokenizer"), local_files_only=True)
        category_count = len(manifest["category_mapping"])
        hidden_size = int(encoder.config.hidden_size)

        class Model(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = encoder
                self.score = nn.Linear(hidden_size, 1)
                self.category = nn.Linear(hidden_size, category_count)

            def forward(self, input_ids, attention_mask):
                encoded = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
                pooled = encoded.last_hidden_state[:, 0]
                return self.score(pooled).squeeze(-1), self.category(pooled)

        model = Model()
        try:
            state = torch.load(folder / "heads.pt", map_location="cpu", weights_only=True)
        except TypeError:  # Older supported PyTorch releases do not expose weights_only.
            state = torch.load(folder / "heads.pt", map_location="cpu")
        if not isinstance(state, dict) or set(state) != {"score_head", "category_head"}:
            raise BackendError("model_heads_incompatible", "Core AI 1 head artifact has an incompatible structure.")
        model.score.load_state_dict(state["score_head"], strict=True)
        model.category.load_state_dict(state["category_head"], strict=True)
        model.to(device)
        model.eval()
        self.torch = torch
        self.tokenizer = tokenizer
        self.model = model
        self.device = device

    def predict(self, text, maximum_length):
        full = self.tokenizer(text, truncation=False)
        token_count = len(full.get("input_ids", []))
        encoded = self.tokenizer(
            text,
            truncation=True,
            max_length=maximum_length,
            padding="max_length",
            return_tensors="pt",
        )
        with self.torch.no_grad():
            score, logits = self.model(
                input_ids=encoded["input_ids"].to(self.device),
                attention_mask=encoded["attention_mask"].to(self.device),
            )
        return {
            "normalized_score": float(score[0].detach().cpu()),
            "category_logits": [float(value) for value in logits[0].detach().cpu().tolist()],
            "truncated": token_count > maximum_length,
            "token_count": token_count,
            "retained_token_count": min(token_count, maximum_length),
        }

    def unload(self):
        self.model = None
        if self.device == "cuda" and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


class TransformersMultiTaskInferenceRuntime:
    """Validates, caches and executes one published Core AI 1 model at a time."""

    runtime_name = "transformers_multitask_inference"

    def __init__(self, device="auto", backend_factory=None, module_finder=None, cuda_available=None):
        self.requested_device = device
        self.backend_factory = backend_factory
        self.module_finder = module_finder or util.find_spec
        self.cuda_available = cuda_available
        self._backend = None
        self._cache_checksum = None
        self._model_folder = None
        self._manifest = None
        self._artifact_checksums = None
        self._device = None

    def inspect(self):
        if self.backend_factory is not None:
            available = True
        else:
            try:
                available = all(self.module_finder(name) is not None for name in ("torch", "transformers"))
            except (ImportError, ValueError):
                available = False
        return {
            "runtime": self.runtime_name,
            "available": available,
            "requested_device": self.requested_device,
            "loaded": self._backend is not None,
            "loaded_model_checksum": self._cache_checksum,
            "device": self._device,
            "local_files_only": True,
        }

    @staticmethod
    def _read_and_validate(folder):
        root = Path(folder).resolve()
        try:
            manifest = json.loads((root / "model_manifest.json").read_text(encoding="utf-8"))
            checksums = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackendError("model_incomplete", "Published Core AI 1 model metadata is incomplete.") from exc
        if manifest.get("model_family") != "core_ai1":
            raise BackendError("model_incompatible", "Published model is not a Core AI 1 model.")
        if manifest.get("input_template_version") != INPUT_TEMPLATE_VERSION:
            raise BackendError("input_template_incompatible", "Core AI 1 input-template version is incompatible.")
        mapping = manifest.get("category_mapping")
        if not isinstance(mapping, dict) or len(mapping) < 2:
            raise BackendError("category_mapping_incompatible", "Core AI 1 category mapping is missing or incomplete.")
        identifiers = list(mapping.values())
        if any(not isinstance(value, int) for value in identifiers) or sorted(identifiers) != list(range(len(identifiers))):
            raise BackendError("category_mapping_incompatible", "Core AI 1 category IDs must be contiguous integers.")
        required = (root / "encoder", root / "tokenizer", root / "heads.pt")
        if not required[0].is_dir() or not required[1].is_dir() or not required[2].is_file():
            raise BackendError("model_artifact_missing", "Encoder, tokenizer or multitask heads are missing.")
        if not isinstance(checksums, dict) or not checksums:
            raise BackendError("model_checksum_missing", "Core AI 1 model checksums are unavailable.")
        actual_files = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "checksums.json"
        }
        if set(checksums) != actual_files:
            raise BackendError("model_checksum_inventory_mismatch", "Core AI 1 checksum inventory is incomplete or unexpected.")
        for relative, expected in checksums.items():
            artifact = (root / relative).resolve()
            if root not in artifact.parents:
                raise BackendError("model_checksum_path_invalid", "Core AI 1 checksum inventory contains an unsafe path.")
            if not artifact.is_file() or sha256_file(artifact) != expected:
                raise BackendError("model_checksum_mismatch", "Core AI 1 model artifact checksum validation failed.")
        aggregate = hashlib.sha256(
            json.dumps(checksums, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return root, manifest, checksums, aggregate

    def _resolve_device(self):
        if self.requested_device not in ("auto", "cpu", "cuda"):
            raise BackendError("device_unsupported", "Core AI 1 device must be auto, cpu or cuda.")
        if self.cuda_available is not None:
            cuda_available = bool(self.cuda_available())
        elif self.backend_factory is not None:
            cuda_available = False
        else:
            torch = import_module("torch")
            cuda_available = bool(torch.cuda.is_available())
        if self.requested_device == "cuda" and not cuda_available:
            raise BackendError("cuda_unavailable", "CUDA was requested but is unavailable.")
        return "cuda" if self.requested_device in ("auto", "cuda") and cuda_available else "cpu"

    def load(self, model_folder):
        if not self.inspect()["available"]:
            raise BackendError("transformer_runtime_unavailable", "PyTorch and Transformers optional dependencies are unavailable.")
        root, manifest, checksums, aggregate = self._read_and_validate(model_folder)
        if self._backend is not None and aggregate == self._cache_checksum:
            return {"cache_hit": True, "model_checksum": aggregate, "device": self._device}
        self.unload()
        device = self._resolve_device()
        factory = self.backend_factory or _HuggingFaceMultiTaskBackend
        try:
            backend = factory(root, manifest, device)
        except BackendError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "out of memory" in message or "cuda oom" in message:
                raise BackendError("out_of_memory", "Core AI 1 model loading ran out of memory.") from exc
            raise BackendError("model_load_failed", "Core AI 1 local model could not be loaded.") from exc
        self._backend = backend
        self._cache_checksum = aggregate
        self._model_folder = root
        self._manifest = manifest
        self._artifact_checksums = checksums
        self._device = device
        return {"cache_hit": False, "model_checksum": aggregate, "device": device}

    def unload(self):
        if self._backend is not None and hasattr(self._backend, "unload"):
            self._backend.unload()
        self._backend = None
        self._cache_checksum = None
        self._model_folder = None
        self._manifest = None
        self._artifact_checksums = None
        self._device = None

    @staticmethod
    def _probabilities(logits):
        if not logits:
            raise BackendError("category_output_missing", "Core AI 1 category logits are unavailable.")
        converted = [float(value) for value in logits]
        if not all(math.isfinite(value) for value in converted):
            raise BackendError("category_output_invalid", "Core AI 1 category logits are invalid.")
        maximum = max(converted)
        values = [math.exp(value - maximum) for value in converted]
        total = sum(values)
        return [value / total for value in values]

    def predict_one(self, model_folder, sample):
        started = time.perf_counter()
        if not isinstance(sample, dict):
            raise BackendError("inference_input_invalid", "Core AI 1 inference sample must be a mapping.")
        load_result = self.load(model_folder)
        try:
            maximum_score = float(sample.get("maximum_score", 0))
        except (TypeError, ValueError) as exc:
            raise BackendError("invalid_maximum_score", "Maximum score must be a positive number.") from exc
        if not math.isfinite(maximum_score) or maximum_score <= 0:
            raise BackendError("invalid_maximum_score", "Maximum score must be positive.")
        try:
            maximum_length = int(self._manifest.get("configuration", {}).get("max_sequence_length", 384))
        except (TypeError, ValueError) as exc:
            raise BackendError("model_configuration_invalid", "Core AI 1 maximum sequence length is invalid.") from exc
        if maximum_length <= 0:
            raise BackendError("model_configuration_invalid", "Core AI 1 maximum sequence length is invalid.")
        try:
            raw = self._backend.predict(compose_input(sample), maximum_length)
            normalized = float(raw["normalized_score"])
            probabilities = self._probabilities(raw.get("category_logits"))
            if not math.isfinite(normalized):
                raise BackendError("score_output_invalid", "Core AI 1 normalized score is invalid.")
            if len(probabilities) != len(self._manifest["category_mapping"]):
                raise BackendError("category_output_incompatible", "Core AI 1 category output size is incompatible.")
        except BackendError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "out of memory" in message or "cuda oom" in message:
                self.unload()
                raise BackendError("out_of_memory", "Core AI 1 inference ran out of memory.") from exc
            raise BackendError("inference_runtime_failure", "Core AI 1 local inference failed.") from exc
        category_id = max(range(len(probabilities)), key=lambda index: (probabilities[index], -index))
        reverse_mapping = {value: key for key, value in self._manifest["category_mapping"].items()}
        raw_mark = normalized * maximum_score
        clamped = raw_mark < 0 or raw_mark > maximum_score
        bounded_mark = min(maximum_score, max(0.0, raw_mark))
        rounded = float((Decimal(str(bounded_mark)) * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
        warnings = []
        if clamped:
            warnings.append("Raw model score was clamped to the valid mark range.")
        if raw.get("truncated"):
            warnings.append("Input exceeded the model sequence length and was truncated.")
        return {
            "status": "completed",
            "raw_normalized_score": normalized,
            "normalized_score": normalized,
            "raw_mark_score": raw_mark,
            "application_rounded_score": rounded,
            "rounding_policy_version": ROUNDING_POLICY_VERSION,
            "clamped": clamped,
            "category_id": category_id,
            "category": reverse_mapping[category_id],
            "category_probabilities": {reverse_mapping[index]: probabilities[index] for index in range(len(probabilities))},
            "category_confidence": probabilities[category_id],
            "truncated": bool(raw.get("truncated")),
            "truncation_statistics": {
                "token_count": raw.get("token_count"),
                "retained_token_count": raw.get("retained_token_count"),
                "maximum_sequence_length": maximum_length,
            },
            "device": self._device,
            "duration_seconds": time.perf_counter() - started,
            "model_version": self._manifest.get("model_version"),
            "model_checksum": self._artifact_checksums.get("heads.pt"),
            "cache_checksum": self._cache_checksum,
            "source_dataset_version": self._manifest.get("source_dataset_version"),
            "input_template_version": self._manifest.get("input_template_version"),
            "lineage": {
                "model_version": self._manifest.get("model_version"),
                "model_checksum": self._artifact_checksums.get("heads.pt"),
                "cache_checksum": self._cache_checksum,
                "source_dataset_version": self._manifest.get("source_dataset_version"),
                "source_dataset_checksum": self._manifest.get("source_dataset_checksum"),
                "category_mapping_version": self._manifest.get("category_mapping_version"),
                "input_template_version": self._manifest.get("input_template_version"),
            },
            "runtime_details": {"adapter": self.runtime_name, "device": self._device, "local_files_only": True},
            "cache_hit": load_result["cache_hit"],
            "warnings": warnings,
        }

    def predict_batch(self, model_folder, samples):
        results = []
        for index, sample in enumerate(samples):
            try:
                results.append({"index": index, **self.predict_one(model_folder, sample)})
            except BackendError as exc:
                results.append({
                    "index": index,
                    "status": "failed",
                    "failure_code": exc.code,
                    "failure_message": exc.safe_message,
                })
            except Exception:
                results.append({
                    "index": index,
                    "status": "failed",
                    "failure_code": "unexpected_item_failure",
                    "failure_message": "Core AI 1 batch item could not be evaluated.",
                })
        return results
