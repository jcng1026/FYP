"""Atomic freeze and source immutability controls for Core AI 2 datasets."""
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from app.services.core_ai2_dataset_registry_service import (_read_json, _safe_path,
    inspect_dataset_integrity, sha256_file)

def is_frozen(dataset_folder):
    root=Path(dataset_folder)
    return (root/".frozen").is_file() and (root/"freeze_manifest.json").is_file()

def assert_source_mutable(dataset_folder):
    if is_frozen(dataset_folder): raise PermissionError("Frozen datasets are immutable; create a new dataset version.")

def replace_source_file(dataset_folder, relative_path, content):
    """Guarded backend write used only for explicit pre-freeze maintenance."""
    assert_source_mutable(dataset_folder); path=_safe_path(dataset_folder,relative_path)
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(content if isinstance(content,bytes) else str(content).encode("utf-8"))

def freeze_dataset(dataset_folder, frozen_by=None, approval_note=None):
    root=Path(dataset_folder)
    if is_frozen(root) or (root/".frozen").exists() or (root/"freeze_manifest.json").exists():
        raise FileExistsError("Dataset is already frozen or has conflicting freeze metadata.")
    manifest=_read_json(root/"manifest.json"); checksums=_read_json(root/"checksums.json")
    integrity=inspect_dataset_integrity(root)
    if not manifest.get("export_valid"): raise ValueError("Only export-valid datasets may be frozen.")
    if not integrity["valid"]: raise ValueError("Dataset integrity inspection failed; freezing is blocked.")
    inventory=[]
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel=path.relative_to(root).as_posix()
        if rel in (".frozen","freeze_manifest.json") or rel.startswith("formats/"): continue
        inventory.append({"path":rel,"sha256":sha256_file(path),"size":path.stat().st_size})
    now=datetime.now(timezone.utc).isoformat()
    freeze={"dataset_version":manifest.get("dataset_version"),"frozen_at":now,"frozen_by":frozen_by,
            "approval_note":approval_note,"source_manifest_checksum":checksums.get("manifest_checksum"),
            "source_checksums_file_checksum":sha256_file(root/"checksums.json"),"file_inventory":inventory,
            "integrity_result":integrity,"export_valid":manifest.get("export_valid"),
            "training_ready":manifest.get("training_ready"),"split_mode":manifest.get("split_mode"),
            "blocking_readiness_reasons":manifest.get("blocking_readiness_reasons",[]),
            "readiness_warnings":manifest.get("readiness_warnings",[]),"source_commit":manifest.get("source_commit")}
    manifest_tmp=None; marker_tmp=None
    published_manifest=False
    try:
        fd,name=tempfile.mkstemp(prefix=".freeze_manifest_",suffix=".tmp",dir=root); os.close(fd); manifest_tmp=Path(name)
        manifest_tmp.write_text(json.dumps(freeze,indent=2,sort_keys=True),encoding="utf-8")
        fd,name=tempfile.mkstemp(prefix=".frozen_",suffix=".tmp",dir=root); os.close(fd); marker_tmp=Path(name)
        marker_tmp.write_text(json.dumps({"dataset_version":manifest.get("dataset_version"),"frozen_at":now}),encoding="utf-8")
        os.replace(manifest_tmp,root/"freeze_manifest.json"); manifest_tmp=None; published_manifest=True
        os.replace(marker_tmp,root/".frozen"); marker_tmp=None
    except Exception:
        if published_manifest and not (root/".frozen").exists(): (root/"freeze_manifest.json").unlink(missing_ok=True)
        raise
    finally:
        if manifest_tmp: manifest_tmp.unlink(missing_ok=True)
        if marker_tmp: marker_tmp.unlink(missing_ok=True)
    return freeze
