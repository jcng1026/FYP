"""Validated, cancellable and atomically published Core AI 2 training."""
import json,os,platform,shutil,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError,JobStatus,TrainingRequest
from app.services.core_ai_backend_job_service import AIJobStore,CancellationToken
from app.services.core_ai_backend_paths import AIBackendPaths,safe_component
from app.services.core_ai2_dataset_registry_service import _read_json,inspect_dataset_integrity,sha256_file

def _now(): return datetime.now(timezone.utc).isoformat()
class CoreAI2TrainingService:
    def __init__(self,paths:AIBackendPaths,dataset_root,runtime,job_store=None):
        self.paths=paths; self.dataset_root=Path(dataset_root); self.runtime=runtime; self.jobs=job_store or AIJobStore(paths); self._tokens={}
    def _dataset(self,version): return self.dataset_root/f"dataset_{safe_component(version,'dataset version')}"
    def validate(self,dataset_version,config):
        root=self._dataset(dataset_version)
        if not root.is_dir(): raise BackendError("dataset_not_found","Core AI 2 dataset was not found.")
        integrity=inspect_dataset_integrity(root); manifest=_read_json(root/"manifest.json")
        if not integrity["valid"]: raise BackendError("dataset_integrity_failed","Dataset integrity inspection failed.")
        if not (root/".frozen").is_file(): raise BackendError("dataset_not_frozen","Training requires a frozen dataset.")
        if not manifest.get("training_ready"): raise BackendError("dataset_not_training_ready","Frozen dataset is not training-ready.")
        if manifest.get("split_mode")!="three_way": raise BackendError("split_unavailable","Training requires leakage-safe train/validation/test splits.")
        conversion=root/"formats"/"yolo"/safe_component(config.conversion_version,"conversion version")
        cm=conversion/"conversion_manifest.json"
        if not cm.is_file(): raise BackendError("conversion_missing","Required YOLO conversion does not exist.")
        conversion_manifest=_read_json(cm); checksums=_read_json(root/"checksums.json")
        if conversion_manifest.get("source_manifest_checksum")!=checksums.get("manifest_checksum"): raise BackendError("conversion_incompatible","Conversion does not match this dataset manifest.")
        if config.image_size<=0 or config.epochs<=0 or config.batch_size<=0: raise BackendError("invalid_training_config","Image size, epochs and batch size must be positive.")
        if not Path(config.local_base_checkpoint).is_file(): raise BackendError("base_checkpoint_missing","A local base checkpoint is required; downloads are never automatic.")
        model_folder=self.paths.model_folder("core_ai2",config.model_version)
        if model_folder.exists(): raise BackendError("model_version_exists","Model version already exists.")
        runtime=self.runtime.inspect()
        if not runtime.get("available"): raise BackendError("detector_runtime_unavailable","Detector runtime is unavailable.")
        return root,manifest,conversion,conversion_manifest,runtime
    def create_job(self,dataset_version,config):
        request=TrainingRequest("core_ai2",dataset_version,config.model_version,config.sanitized(),config.conversion_version,config.training_notes)
        return self.jobs.create(request)
    def cancel(self,job_id):
        record=self.jobs.request_cancellation(job_id)
        if job_id in self._tokens: self._tokens[job_id].cancel()
        else: return self.jobs.transition(job_id,JobStatus.CANCELLED,"Training cancelled before worker execution.")
        return record
    def run(self,job_id,config):
        record=self.jobs.get(job_id); token=CancellationToken(); self._tokens[job_id]=token; work=None
        try:
            self.jobs.transition(job_id,JobStatus.VALIDATING,"Validating frozen dataset and runtime.")
            dataset,manifest,conversion,conversion_manifest,runtime_info=self.validate(record.dataset_version,config)
            current=self.jobs.get(job_id)
            if current.cancellation_requested: token.cancel()
            token.raise_if_cancelled(); self.jobs.transition(job_id,JobStatus.RUNNING,"Training detector.",hardware_runtime=runtime_info)
            work=Path(tempfile.mkdtemp(prefix=f"train_{job_id}_",dir=self.paths.temporary_root)); started=time.perf_counter()
            def progress(message,value=None,epoch=None):
                token.raise_if_cancelled(); self.jobs.append_progress(job_id,message,progress_value=value,current_epoch=epoch)
            try: result=self.runtime.train(conversion/"data.yaml",work,config,progress,token)
            except Exception as exc:
                message=str(exc).lower()
                if "out of memory" in message or "cuda oom" in message: raise BackendError("cuda_out_of_memory","CUDA ran out of memory. Reduce batch/image size or explicitly enable a recorded retry.")
                raise
            token.raise_if_cancelled(); self.jobs.transition(job_id,JobStatus.PUBLISHING,"Publishing immutable detector model.")
            final=self.paths.model_folder("core_ai2",config.model_version); final.parent.mkdir(parents=True,exist_ok=True)
            publish=Path(tempfile.mkdtemp(prefix=f".{config.model_version}_",dir=final.parent))
            try:
                artifacts=[]
                for key in ("best_checkpoint","last_checkpoint"):
                    source=result.get(key)
                    if source and Path(source).is_file():
                        target=publish/Path(source).name; shutil.copy2(source,target); artifacts.append({"name":target.name,"sha256":sha256_file(target),"size":target.stat().st_size})
                if not any(a["name"]=="best.pt" for a in artifacts): raise BackendError("training_artifact_missing","best.pt was not available for publication.")
                dataset_checksums=_read_json(dataset/"checksums.json")
                model_manifest={"model_family":"core_ai2","model_version":config.model_version,"created_at":_now(),"training_job_id":job_id,"source_dataset_version":manifest["dataset_version"],"source_dataset_checksum":dataset_checksums["manifest_checksum"],"conversion_version":config.conversion_version,"conversion_checksum":sha256_file(conversion/"conversion_manifest.json"),"base_model_identifier":Path(config.local_base_checkpoint).name,"architecture":"object_detector","class_mapping":manifest["class_mapping"],"class_mapping_version":manifest["class_mapping_version"],"compatible_schema_versions":[manifest["schema_version"]],"training_configuration":config.sanitized(),"runtime":runtime_info,"duration_seconds":time.perf_counter()-started,"artifact_inventory":artifacts,"evaluation_status":"unevaluated","activation_status":"inactive","warnings":["No automatic activation was performed."]}
                (publish/"model_manifest.json").write_text(json.dumps(model_manifest,indent=2,sort_keys=True),encoding="utf-8")
                checks={p.name:sha256_file(p) for p in publish.iterdir() if p.is_file()}; (publish/"checksums.json").write_text(json.dumps(checks,indent=2,sort_keys=True),encoding="utf-8")
                os.replace(publish,final)
            finally:
                if publish.exists(): shutil.rmtree(publish,ignore_errors=True)
                shutil.rmtree(work,ignore_errors=True)
            return self.jobs.transition(job_id,JobStatus.COMPLETED,"Detector training completed; model remains inactive.",result_model_version=config.model_version,progress_value=100)
        except BackendError as exc:
            current=self.jobs.get(job_id)
            if exc.code=="cancelled" or current.cancellation_requested:
                if current.status!="cancelling": self.jobs.transition(job_id,JobStatus.CANCELLING,"Cancelling training.")
                return self.jobs.transition(job_id,JobStatus.CANCELLED,"Training cancelled; no model published.")
            return self.jobs.transition(job_id,JobStatus.FAILED,"Training failed.",failure_code=exc.code,failure_message=exc.safe_message)
        except Exception as exc:
            return self.jobs.transition(job_id,JobStatus.FAILED,"Training failed.",failure_code="runtime_failure",failure_message=str(exc)[:500])
        finally:
            if work and work.exists(): shutil.rmtree(work,ignore_errors=True)
            self._tokens.pop(job_id,None)
