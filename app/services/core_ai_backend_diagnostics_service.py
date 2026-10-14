"""Factual diagnostics that avoid heavy imports unless explicitly requested."""

from importlib import import_module, metadata, util
import json
import platform
from pathlib import Path
import sys

from app.models.core_ai_backend_diagnostic_types import RuntimeInspectionResult
from app.services.core_ai2_dataset_registry_service import sha256_file


_PACKAGE_MODULES = {
    "torch": "torch",
    "transformers": "transformers",
    "ultralytics": "ultralytics",
}


class AIRuntimeDiagnosticsService:
    def __init__(self, paths, core_ai1_dataset_root=None, core_ai2_dataset_root=None,
                 version_provider=None, module_finder=None, torch_loader=None):
        self.paths = paths
        self.dataset_roots = {
            "core_ai1": Path(core_ai1_dataset_root).resolve() if core_ai1_dataset_root else None,
            "core_ai2": Path(core_ai2_dataset_root).resolve() if core_ai2_dataset_root else None,
        }
        self.version_provider = version_provider or metadata.version
        self.module_finder = module_finder or util.find_spec
        self.torch_loader = torch_loader or (lambda: import_module("torch"))

    def _package(self, distribution, module):
        try:
            available = self.module_finder(module) is not None
        except (ImportError, ValueError):
            available = False
        try:
            version = self.version_provider(distribution) if available else None
        except metadata.PackageNotFoundError:
            version = None
        return {"available": available, "version": version}

    def _active_model(self, family, requested_version=None):
        result = {"configured": False, "model_version": requested_version, "integrity": "not_checked", "manifest": None}
        version = requested_version
        if not version:
            pointer = self.paths.active_pointer(family)
            if not pointer.is_file():
                return result
            try:
                version = json.loads(pointer.read_text(encoding="utf-8"))["model_version"]
                result["configured"] = True
            except Exception:
                result["integrity"] = "active_pointer_corrupt"
                return result
        folder = self.paths.model_folder(family, version)
        result["model_version"] = version
        try:
            manifest = json.loads((folder / "model_manifest.json").read_text(encoding="utf-8"))
            checksums = json.loads((folder / "checksums.json").read_text(encoding="utf-8"))
            mismatches = [name for name, expected in checksums.items()
                          if not (folder / name).is_file() or sha256_file(folder / name) != expected]
            result.update({"configured": True, "integrity": "valid" if not mismatches else "invalid",
                           "checksum_mismatches": mismatches, "manifest": manifest,
                           "checkpoint_bytes": sum((folder / name).stat().st_size for name in checksums if (folder / name).is_file())})
        except Exception:
            result["integrity"] = "incomplete_or_unreadable"
        return result

    def _dataset_compatibility(self, family, version, model_manifest):
        if not version:
            return {"checked": False, "schema": "unknown", "mapping": "unknown"}
        root = self.dataset_roots.get(family)
        if root is None:
            return {"checked": False, "schema": "unknown", "mapping": "unknown"}
        candidates = (root / f"dataset_{version}", root / version)
        folder = next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])
        try:
            dataset = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            return {"checked": True, "schema": "dataset_unavailable", "mapping": "dataset_unavailable"}
        if not model_manifest:
            return {"checked": True, "schema": "model_unavailable", "mapping": "model_unavailable"}
        compatible_schemas = model_manifest.get("compatible_schema_versions", [])
        schema = "compatible" if dataset.get("schema_version") in compatible_schemas else "incompatible"
        if family == "core_ai1":
            mapping = "compatible" if dataset.get("category_mapping_version") == model_manifest.get("category_mapping_version") else "incompatible"
        else:
            mapping = "compatible" if dataset.get("class_mapping") == model_manifest.get("class_mapping") else "incompatible"
        return {"checked": True, "schema": schema, "mapping": mapping, "dataset_path": str(folder)}

    def inspect(self, request):
        if request.model_family not in ("core_ai1", "core_ai2"):
            raise ValueError("model_family must be core_ai1 or core_ai2")
        packages = {name: self._package(name, module) for name, module in _PACKAGE_MODULES.items()}
        accelerator = {"cuda_available": None, "cuda_runtime_version": None, "gpu_name": None,
                       "total_vram_bytes": None, "free_vram_bytes": None, "details_loaded": False}
        warnings, blockers = [], []
        if request.detailed_runtime and packages["torch"]["available"]:
            try:
                torch = self.torch_loader()
                accelerator["details_loaded"] = True
                accelerator["cuda_available"] = bool(torch.cuda.is_available())
                accelerator["cuda_runtime_version"] = getattr(getattr(torch, "version", None), "cuda", None)
                if accelerator["cuda_available"]:
                    accelerator["gpu_name"] = torch.cuda.get_device_name(0)
                    try:
                        free, total = torch.cuda.mem_get_info(0)
                        accelerator.update({"free_vram_bytes": int(free), "total_vram_bytes": int(total)})
                    except Exception:
                        warnings.append("CUDA is available but free/total VRAM could not be queried.")
            except Exception:
                warnings.append("Detailed PyTorch runtime inspection failed without loading a model.")
        elif packages["torch"]["available"]:
            warnings.append("CUDA and VRAM remain unknown because detailed runtime inspection was not requested.")

        required_runtime = "transformers" if request.model_family == "core_ai1" else "ultralytics"
        active = self._active_model(request.model_family, request.model_version)
        if active["integrity"] in ("invalid", "incomplete_or_unreadable", "active_pointer_corrupt"):
            blockers.append("Active/requested model artifact integrity is not valid.")
        compatibility = self._dataset_compatibility(request.model_family, request.dataset_version, active.get("manifest"))
        if "incompatible" in (compatibility.get("schema"), compatibility.get("mapping")):
            blockers.append("Model and dataset schema or mapping are incompatible.")
        base_path = Path(request.local_base_model_path).resolve() if request.local_base_model_path else None
        local_base = {"configured": base_path is not None, "exists": bool(base_path and base_path.exists()),
                      "path": str(base_path) if base_path else None}
        if base_path and not base_path.exists():
            blockers.append("Configured local base model/checkpoint path does not exist.")

        if not packages[required_runtime]["available"] or not packages["torch"]["available"]:
            memory_status = "runtime_unavailable"
        elif request.previous_oom_evidence:
            memory_status = "incompatible"
            warnings.append("A previous out-of-memory result was supplied for this configuration.")
        elif request.completed_run_evidence:
            memory_status = "confirmed_compatible"
        else:
            manifest = active.get("manifest") or {}
            required_vram = manifest.get("minimum_vram_bytes")
            total_vram = accelerator.get("total_vram_bytes")
            if required_vram and total_vram:
                memory_status = "expected_compatible" if total_vram >= required_vram else "incompatible"
            else:
                memory_status = "unknown"
                warnings.append("Memory compatibility is unknown; model name/family alone is not evidence for an 8 GB target.")
        if memory_status == "runtime_unavailable":
            blockers.append(f"Optional {required_runtime}/PyTorch runtime is unavailable; graceful no-AI mode remains available.")

        return RuntimeInspectionResult(
            model_family=request.model_family,
            system={"python_version": platform.python_version(), "python_executable": sys.executable,
                    "operating_system": platform.platform(), "architecture": platform.machine()},
            packages=packages,
            accelerator={**accelerator, "cpu_fallback_available": bool(packages["torch"]["available"]),
                         "expected_device": "cuda_or_cpu" if packages["torch"]["available"] else "unavailable",
                         "expected_precision": "runtime/configuration dependent"},
            local_base_model=local_base,
            active_model=active,
            compatibility=compatibility,
            memory_status=memory_status,
            graceful_no_ai_mode=True,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
        )
