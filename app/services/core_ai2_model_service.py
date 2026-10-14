"""Core AI 2 evaluation, immutable registry, explicit activation and rollback."""
import json,os,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError
from app.services.core_ai_backend_paths import AIBackendPaths,safe_component
from app.services.core_ai2_dataset_registry_service import _read_json,sha256_file

def _now(): return datetime.now(timezone.utc).isoformat()
def _atomic_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix=".pointer_",suffix=".tmp",dir=path.parent); os.close(fd)
    try: Path(name).write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8"); os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)

class CoreAI2ModelService:
    def __init__(self,paths:AIBackendPaths,dataset_root,evaluation_runtime): self.paths=paths; self.dataset_root=Path(dataset_root); self.runtime=evaluation_runtime; paths.ensure_layout()
    def _model(self,version): return self.paths.model_folder("core_ai2",version)
    def _evaluation_folder(self,version): return self.paths.evaluations_root/"core_ai2"/safe_component(version)
    def _verify_model(self,version):
        folder=self._model(version); manifest_path=folder/"model_manifest.json"; checksums_path=folder/"checksums.json"
        if not manifest_path.is_file() or not checksums_path.is_file(): raise BackendError("model_incomplete","Completed model version not found.")
        manifest=_read_json(manifest_path); checksums=_read_json(checksums_path)
        for name,expected in checksums.items():
            path=folder/name
            if not path.is_file() or sha256_file(path)!=expected: raise BackendError("model_checksum_mismatch","Model artifact checksum validation failed.")
        if manifest.get("model_family")!="core_ai2": raise BackendError("model_incompatible","Model family is incompatible.")
        return folder,manifest,checksums
    def inspect_model(self,version):
        folder,manifest,checksums=self._verify_model(version); return {**manifest,"path":str(folder),"model_checksum":checksums.get("best.pt"),"integrity_valid":True}
    def list_models(self):
        active=self.get_active(required=False); result=[]; root=self.paths.models_root/"core_ai2"
        if not root.exists(): return []
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try:
                _,manifest,checksums=self._verify_model(folder.name); evaluations=self.list_evaluations(folder.name)
                result.append({**manifest,"integrity_valid":True,"active":bool(active and active["model_version"]==folder.name),"evaluation_status":"evaluated" if evaluations else "unevaluated","model_checksum":checksums.get("best.pt")})
            except BackendError as exc: result.append({"model_version":folder.name,"integrity_valid":False,"state":"corrupt_or_incomplete","error_code":exc.code})
        return result
    def evaluate(self,model_version,dataset_version,required_metrics=("map50","precision","recall")):
        folder,model,checksums=self._verify_model(model_version); dataset=self.dataset_root/f"dataset_{safe_component(dataset_version)}"
        if not dataset.is_dir(): raise BackendError("dataset_not_found","Evaluation dataset not found.")
        dm=_read_json(dataset/"manifest.json"); dc=_read_json(dataset/"checksums.json"); split=_read_json(dataset/"splits"/"split_plan.json")
        if dm.get("split_mode")!="three_way": raise BackendError("evaluation_split_missing","Validation and test splits are required.")
        if dm.get("class_mapping")!=model.get("class_mapping"): raise BackendError("mapping_incompatible","Dataset and model class mappings differ.")
        conversion_version=model.get("conversion_version")
        if not conversion_version: raise BackendError("conversion_lineage_missing","Model does not declare its YOLO conversion lineage.")
        conversion=dataset/"formats"/"yolo"/safe_component(conversion_version,"conversion version")
        try: conversion_manifest=_read_json(conversion/"conversion_manifest.json")
        except Exception: raise BackendError("conversion_missing","Model evaluation YOLO conversion is unavailable.")
        if conversion_manifest.get("source_manifest_checksum")!=dc.get("manifest_checksum"): raise BackendError("conversion_incompatible","YOLO conversion does not match the evaluation dataset.")
        expected_conversion_checksum=model.get("conversion_checksum")
        if not expected_conversion_checksum: raise BackendError("conversion_lineage_missing","Model does not declare its YOLO conversion checksum.")
        if sha256_file(conversion/"conversion_manifest.json")!=expected_conversion_checksum: raise BackendError("conversion_checksum_mismatch","Model conversion lineage checksum does not match.")
        runtime_info=self.runtime.inspect()
        if not runtime_info.get("available"): raise BackendError("evaluation_runtime_unavailable","Detector evaluation runtime is unavailable.")
        split_results={}
        for name in ("validation","test"):
            split_results[name]=self.runtime.evaluate(folder/"best.pt",conversion,name)
            runtime_mapping=split_results[name].get("class_mapping")
            if runtime_mapping is not None and runtime_mapping!=dm.get("class_mapping"): raise BackendError("mapping_incompatible","YOLO conversion and dataset class mappings differ.")
        normalized={name:{key:value for key,value in values.items() if key in ("map50","map50_95","precision","recall","per_class","class_support","validation_loss","losses","inference_seconds","evaluation_duration_seconds","memory")} for name,values in split_results.items()}
        missing=[metric for metric in required_metrics if metric not in normalized["validation"] or metric not in normalized["test"]]
        warnings=[]
        for name in ("validation","test"):
            absent=split.get("missing_classes",{}).get(name,[])
            if absent: warnings.append(f"{name} split is missing classes: {', '.join(absent)}")
            support=normalized[name].get("class_support",{})
            for class_name in sorted(dm.get("class_mapping",{})):
                count=support.get(class_name) if isinstance(support,dict) else None
                if count is None: warnings.append(f"{name} split has no reported support for {class_name}")
                elif int(count)<5: warnings.append(f"{name} split has low support for {class_name}: {count}")
        passed=not missing
        evaluation={"evaluation_id":uuid.uuid4().hex,"model_family":"core_ai2","model_version":model_version,"model_checksum":checksums.get("best.pt"),"dataset_version":dataset_version,"dataset_checksum":dc.get("manifest_checksum"),"split_checksums":{"validation":sha256_file(dataset/"splits"/"split_plan.json"),"test":sha256_file(dataset/"splits"/"split_plan.json")},"class_mapping":dm.get("class_mapping"),"raw_runtime_metrics":split_results,"metrics":normalized,"warnings":warnings,"errors":[] if passed else [f"Required metrics unavailable: {', '.join(missing)}"],"passed":passed,"decision_criteria":{"required_metrics":list(required_metrics),"structural_validation":True,"compatible_mapping":True},"evaluated_at":_now(),"runtime":runtime_info}
        target=self._evaluation_folder(model_version)/f"{evaluation['evaluation_id']}.json"; _atomic_json(target,evaluation); return evaluation
    def list_evaluations(self,model_version):
        folder=self._evaluation_folder(model_version)
        if not folder.exists(): return []
        result=[]
        for path in folder.glob("*.json"):
            try: result.append(_read_json(path))
            except Exception: continue
        return sorted(result,key=lambda e:e.get("evaluated_at","") ,reverse=True)
    def get_active(self,required=True):
        path=self.paths.active_pointer("core_ai2")
        if not path.is_file():
            if required: raise BackendError("no_active_model","No active Core AI 2 model is configured.")
            return None
        data=_read_json(path); self._verify_model(data["model_version"]); return data
    def activate(self,version,actor,reason,action="activate"):
        _,manifest,checksums=self._verify_model(version); evaluations=self.list_evaluations(version)
        if not evaluations or not evaluations[0].get("passed"): raise BackendError("evaluation_required","A passing evaluation is required before activation.")
        previous=self.get_active(required=False); now=_now(); pointer={"model_family":"core_ai2","model_version":version,"model_checksum":checksums.get("best.pt"),"activated_at":now,"actor":actor,"reason":reason,"previous_model_version":previous.get("model_version") if previous else None,"action":action}
        _atomic_json(self.paths.active_pointer("core_ai2"),pointer)
        history=self.paths.history_root/f"{now.replace(':','-')}_{action}_{safe_component(version)}.json"; _atomic_json(history,pointer); return pointer
    def rollback(self,target_version,actor,reason): return self.activate(target_version,actor,reason,"rollback")
    def compare(self,left,right):
        _,lm,lc=self._verify_model(left); _,rm,rc=self._verify_model(right); le=self.list_evaluations(left); re=self.list_evaluations(right)
        controlled=bool(le and re and le[0].get("dataset_checksum")==re[0].get("dataset_checksum")); warnings=[] if controlled else ["Models were evaluated on different datasets or lack comparable evaluations; metric deltas are not controlled."]
        def metrics(e): return e[0].get("metrics",{}) if e else {}
        return {"left":left,"right":right,"dataset_lineage":{"left":lm.get("source_dataset_version"),"right":rm.get("source_dataset_version")},"architecture":{"left":lm.get("architecture"),"right":rm.get("architecture")},"training_configuration_differences":{"left":lm.get("training_configuration"),"right":rm.get("training_configuration")},"metrics":{"left":metrics(le),"right":metrics(re)},"artifact_size_difference":sum(a.get("size",0) for a in rm.get("artifact_inventory",[]))-sum(a.get("size",0) for a in lm.get("artifact_inventory",[])),"mapping_compatible":lm.get("class_mapping")==rm.get("class_mapping"),"controlled_comparison":controlled,"warnings":warnings}
