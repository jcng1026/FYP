"""Read-only discovery and integrity inspection for Core AI 2 datasets."""
import hashlib, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional
from app.models.core_ai2_dataset_registry_types import DatasetRegistryEntry, IntegrityResult
from app.models.core_ai2_dataset_types import CLASS_MAPPING, CLASS_MAPPING_VERSION

REQUIRED_JSON = ("manifest.json", "class_mapping.json", "validation_report.json",
                 "statistics.json", "checksums.json", "splits/split_plan.json")

def sha256_file(path):
    digest=hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()

def _now(): return datetime.now(timezone.utc).isoformat()
def _problem(code,message,**details): return {"code":code,"message":message,"details":details}

def _safe_path(root, relative):
    if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or PurePosixPath(relative.replace("\\","/")).is_absolute() or ":" in relative:
        raise ValueError("Path must be portable and relative.")
    parts=PurePosixPath(relative.replace("\\","/")).parts
    if ".." in parts: raise ValueError("Path traversal is not allowed.")
    result=(Path(root)/Path(*parts)).resolve(); base=Path(root).resolve()
    if result!=base and base not in result.parents: raise ValueError("Path escapes dataset folder.")
    return result

def _read_json(path):
    with open(path,"r",encoding="utf-8") as stream: return json.load(stream)

def inspect_dataset_integrity(dataset_folder):
    root=Path(dataset_folder); errors=[]; warnings=[]; documents={}
    for relative in REQUIRED_JSON:
        path=root/relative
        if not path.is_file(): errors.append(_problem("missing_required_file",f"Required file is missing: {relative}",path=relative)); continue
        try: documents[relative]=_read_json(path)
        except Exception as exc: errors.append(_problem("corrupted_json",f"JSON is unreadable: {relative}",path=relative,error=str(exc)))
    if "manifest.json" not in documents:
        return IntegrityResult(False,_now(),errors,warnings).to_dict()
    manifest=documents["manifest.json"]; checksums=documents.get("checksums.json",{})
    for relative, expected in checksums.items():
        if relative=="manifest_checksum": continue
        try: path=_safe_path(root,relative)
        except ValueError as exc: errors.append(_problem("non_portable_path",str(exc),path=relative)); continue
        if not path.is_file(): errors.append(_problem("checksummed_file_missing","Checksummed file is missing.",path=relative))
        elif sha256_file(path)!=expected: errors.append(_problem("checksum_mismatch","File checksum does not match.",path=relative))
    expected_manifest=checksums.get("manifest_checksum")
    if not expected_manifest or sha256_file(root/"manifest.json")!=expected_manifest:
        errors.append(_problem("manifest_checksum_mismatch","Manifest checksum does not match."))
    mapping=documents.get("class_mapping.json",{})
    if mapping.get("version")!=manifest.get("class_mapping_version") or mapping.get("version")!=CLASS_MAPPING_VERSION or mapping.get("mapping")!=manifest.get("class_mapping") or mapping.get("mapping")!=CLASS_MAPPING:
        errors.append(_problem("class_mapping_mismatch","Class mapping or declared version is incompatible."))
    pages=manifest.get("pages",[]); profiles=manifest.get("profiles",[]); regions=[r for p in pages for r in p.get("regions",[]) if not r.get("excluded")]
    for page in pages:
        for key,required in (("image_path",True),("label_path",True),("overlay_path",True)):
            value=page.get(key)
            if not value:
                if required: errors.append(_problem("missing_manifest_path",f"Page lacks {key}.",page_id=page.get("page_id")))
                continue
            try: path=_safe_path(root,value)
            except ValueError as exc: errors.append(_problem("non_portable_path",str(exc),path=value,page_id=page.get("page_id"))); continue
            if not path.is_file(): errors.append(_problem("referenced_file_missing","Referenced page file is missing.",path=value,page_id=page.get("page_id")))
    stats=documents.get("statistics.json",{})
    expected=(len(profiles),len(pages),len(regions)); actual=(stats.get("profile_count"),stats.get("page_count"),stats.get("region_count"))
    if expected!=actual: errors.append(_problem("statistics_count_mismatch","Profile/page/region counts do not match statistics.",expected=expected,actual=actual))
    split=documents.get("splits/split_plan.json",{}); assignments=split.get("assignments",{}); page_splits=defaultdict(set); checksum_splits=defaultdict(set)
    for page in pages:
        split_name=assignments.get(str(page.get("profile_id")))
        if split.get("mode")=="three_way" and split_name not in ("train","validation","test"):
            errors.append(_problem("missing_split_assignment","Profile lacks a valid split.",profile_id=page.get("profile_id")))
        if split_name:
            page_splits[page.get("profile_id")].add(split_name)
            if page.get("image_checksum"): checksum_splits[page["image_checksum"]].add(split_name)
        if page.get("split") and split_name and page.get("split")!=split_name:
            page_splits[page.get("profile_id")].add(page.get("split"))
    if any(len(v)>1 for v in page_splits.values()): errors.append(_problem("profile_leakage","A profile appears in multiple splits."))
    leaking={k:sorted(v) for k,v in checksum_splits.items() if len(v)>1}
    if leaking: errors.append(_problem("image_checksum_leakage","Matching images appear in multiple splits.",groups=leaking))
    marker=root/".frozen"; freeze=root/"freeze_manifest.json"
    if marker.exists()!=freeze.exists(): errors.append(_problem("freeze_state_mismatch","Frozen marker and freeze manifest disagree."))
    if freeze.exists():
        try:
            freeze_data=_read_json(freeze)
            if freeze_data.get("source_manifest_checksum")!=expected_manifest: errors.append(_problem("freeze_manifest_mismatch","Freeze manifest points to another source manifest."))
            marker_data=_read_json(marker)
            if marker_data.get("dataset_version")!=freeze_data.get("dataset_version") or marker_data.get("frozen_at")!=freeze_data.get("frozen_at"):
                errors.append(_problem("freeze_marker_mismatch","Frozen marker metadata disagrees with freeze manifest."))
        except Exception as exc: errors.append(_problem("corrupted_freeze_manifest","Freeze manifest is unreadable.",error=str(exc)))
    formats=root/"formats"
    if formats.exists():
        for conversion in formats.glob("*/*/conversion_manifest.json"):
            try:
                data=_read_json(conversion)
                if data.get("source_manifest_checksum")!=expected_manifest: errors.append(_problem("conversion_source_mismatch","Conversion points to another source manifest.",path=conversion.relative_to(root).as_posix()))
                if data.get("source_dataset_version")!=manifest.get("dataset_version"): errors.append(_problem("conversion_dataset_version_mismatch","Conversion names another dataset version."))
                source_page_ids={p.get("page_id") for p in pages}
                if not set(data.get("source_page_ids",[])) <= source_page_ids: errors.append(_problem("conversion_unknown_source_record","Conversion references an unknown source page."))
                for rel,expected in data.get("file_checksums",{}).items():
                    derived=_safe_path(conversion.parent,rel)
                    if not derived.is_file(): errors.append(_problem("conversion_file_missing","Converted file is missing.",path=rel))
                    elif sha256_file(derived)!=expected: errors.append(_problem("conversion_checksum_mismatch","Converted file checksum does not match.",path=rel))
                for record in data.get("records",[]):
                    if record.get("page_id") not in source_page_ids: errors.append(_problem("conversion_unknown_source_record","Conversion record references an unknown page.",page_id=record.get("page_id")))
                    for key in ("image_path","label_path"):
                        if record.get(key): _safe_path(conversion.parent,record[key])
            except Exception as exc: errors.append(_problem("invalid_conversion_manifest","Conversion manifest is invalid.",path=conversion.relative_to(root).as_posix(),error=str(exc)))
    return IntegrityResult(not errors,_now(),errors,warnings).to_dict()

def _available_formats(root):
    result={}
    base=Path(root)/"formats"
    if base.exists():
        for fmt in base.iterdir():
            if fmt.is_dir(): result[fmt.name]=sorted(p.name for p in fmt.iterdir() if p.is_dir() and (p/"conversion_manifest.json").is_file())
    return result

def discover_datasets(dataset_root):
    root=Path(dataset_root); datasets=[]; ignored=[]; problems=[]
    if not root.exists(): return {"datasets":[],"ignored":[],"problems":[]}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith("."):
            ignored.append({"folder_name":folder.name,"reason":"temporary_folder"}); continue
        if not folder.name.startswith("dataset_"): continue
        if not (folder/"manifest.json").is_file(): problems.append({"folder_name":folder.name,"reason":"missing_manifest"}); continue
        try:
            manifest=_read_json(folder/"manifest.json"); stats=_read_json(folder/"statistics.json"); validation=_read_json(folder/"validation_report.json"); checksums=_read_json(folder/"checksums.json")
        except Exception as exc: problems.append({"folder_name":folder.name,"reason":"corrupted_or_incomplete","error":str(exc)}); continue
        integrity=inspect_dataset_integrity(folder); frozen=(folder/".frozen").is_file(); frozen_at=None
        if frozen:
            try: frozen_at=_read_json(folder/"freeze_manifest.json").get("frozen_at")
            except Exception: pass
        entry=DatasetRegistryEntry(str(manifest.get("dataset_version")),folder.name,manifest.get("created_at"),bool(manifest.get("export_valid")),bool(manifest.get("training_ready")),manifest.get("split_mode"),int(stats.get("profile_count",0)),int(stats.get("page_count",0)),int(stats.get("region_count",0)),dict(stats.get("count_by_region_type",{})),int(validation.get("summary",{}).get("error",0)),int(validation.get("summary",{}).get("warning",0)),list(manifest.get("blocking_readiness_reasons",[])),list(manifest.get("readiness_warnings",[])),frozen,frozen_at,checksums.get("manifest_checksum"),manifest.get("source_commit"),manifest.get("class_mapping_version"),manifest.get("schema_version"),_available_formats(folder),bool(integrity["valid"]))
        datasets.append(entry.to_dict())
    return {"datasets":datasets,"ignored":ignored,"problems":problems}

def get_dataset_entry(dataset_root, version):
    matches=[d for d in discover_datasets(dataset_root)["datasets"] if d["version"]==version]
    if not matches: raise ValueError("Completed dataset version not found.")
    return matches[0]
