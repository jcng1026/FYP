"""Core AI 1 multi-task training orchestration and atomic publication."""
import json,os,shutil,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError,JobStatus,TrainingRequest
from app.services.core_ai_backend_job_service import AIJobStore,CancellationToken
from app.services.core_ai_backend_paths import AIBackendPaths,safe_component
from app.services.core_ai1_dataset_service import inspect_core_ai1_dataset
from app.services.core_ai2_dataset_registry_service import sha256_file

def _now(): return datetime.now(timezone.utc).isoformat()
class CoreAI1TrainingService:
    def __init__(self,paths,dataset_root,runtime,job_store=None): self.paths=paths; self.dataset_root=Path(dataset_root); self.runtime=runtime; self.jobs=job_store or AIJobStore(paths); self._tokens={}
    def create_job(self,dataset_version,config): return self.jobs.create(TrainingRequest("core_ai1",dataset_version,config.model_version,config.sanitized()))
    def cancel(self,job_id):
        record=self.jobs.request_cancellation(job_id)
        if job_id in self._tokens: self._tokens[job_id].cancel()
        else: return self.jobs.transition(job_id,JobStatus.CANCELLED,"Training cancelled before worker execution.")
        return record
    def _validate(self,version,config):
        dataset=self.dataset_root/f"dataset_{safe_component(version)}"
        if not dataset.is_dir(): raise BackendError("dataset_not_found","Core AI 1 dataset not found.")
        integrity=inspect_core_ai1_dataset(dataset); manifest=json.loads((dataset/"manifest.json").read_text())
        if not integrity["valid"]: raise BackendError("dataset_integrity_failed","Dataset integrity failed.")
        if not (dataset/".frozen").is_file(): raise BackendError("dataset_not_frozen","Training requires a frozen dataset.")
        if not manifest.get("training_ready") or manifest.get("split_mode")!="three_way": raise BackendError("dataset_not_training_ready","Dataset is not ready for multi-task training.")
        if not Path(config.local_base_model_path).exists(): raise BackendError("base_model_missing","A local base Transformer path is required.")
        if not self.runtime.inspect().get("available"): raise BackendError("transformer_runtime_unavailable","Optional Transformer runtime is unavailable.")
        final=self.paths.model_folder("core_ai1",config.model_version)
        if final.exists(): raise BackendError("model_version_exists","Model version already exists.")
        return dataset,manifest,final
    def run(self,job_id,config):
        token=CancellationToken(); self._tokens[job_id]=token; work=None
        try:
            record=self.jobs.get(job_id); self.jobs.transition(job_id,JobStatus.VALIDATING,"Validating Core AI 1 dataset and runtime."); dataset,manifest,final=self._validate(record.dataset_version,config)
            if self.jobs.get(job_id).cancellation_requested: token.cancel()
            token.raise_if_cancelled()
            self.jobs.transition(job_id,JobStatus.RUNNING,"Training multi-task Cross-Encoder."); work=Path(tempfile.mkdtemp(prefix="core_ai1_",dir=self.paths.temporary_root)); started=time.perf_counter()
            def progress(message,value=None,epoch=None): token.raise_if_cancelled(); self.jobs.append_progress(job_id,message,progress_value=value,current_epoch=epoch)
            try: result=self.runtime.train(dataset,work,config,progress,token)
            except Exception as exc:
                if "out of memory" in str(exc).lower(): raise BackendError("out_of_memory","Training ran out of memory. Reduce batch/sequence size or use gradient accumulation.")
                raise
            token.raise_if_cancelled(); self.jobs.transition(job_id,JobStatus.PUBLISHING,"Publishing immutable Core AI 1 model."); final.parent.mkdir(parents=True,exist_ok=True); publish=Path(tempfile.mkdtemp(prefix=f".{config.model_version}_",dir=final.parent))
            for artifact in result.get("artifacts",[]):
                artifact=Path(artifact); target=publish/artifact.name
                if artifact.is_dir(): shutil.copytree(artifact,target)
                else: shutil.copy2(artifact,target)
            dataset_checks=json.loads((dataset/"checksums.json").read_text()); mapping=json.loads((dataset/"category_mapping.json").read_text())
            inventory=[{"path":p.relative_to(publish).as_posix(),"sha256":sha256_file(p),"size":p.stat().st_size} for p in publish.rglob("*") if p.is_file()]
            model_manifest={"model_family":"core_ai1","model_version":config.model_version,"created_at":_now(),"source_dataset_version":manifest["dataset_version"],"source_dataset_checksum":dataset_checks["manifest_checksum"],"training_job_id":job_id,"base_model_identifier":Path(config.local_base_model_path).name,"architecture":"multi_task_cross_encoder","category_mapping":mapping["mapping"],"category_mapping_version":mapping["version"],"input_template_version":manifest["input_template_version"],"compatible_schema_versions":[manifest["schema_version"]],"configuration":config.sanitized(),"training_metrics":result.get("training_metrics",{}),"truncation_count":result.get("truncation_count"),"runtime":result.get("runtime",{}),"duration_seconds":time.perf_counter()-started,"artifact_inventory":inventory,"evaluation_status":"unevaluated","activation_status":"inactive","warnings":["Model was not automatically activated."]}
            (publish/"model_manifest.json").write_text(json.dumps(model_manifest,indent=2,sort_keys=True)); checks={p.relative_to(publish).as_posix():sha256_file(p) for p in publish.rglob("*") if p.is_file()}; (publish/"checksums.json").write_text(json.dumps(checks,indent=2,sort_keys=True)); os.replace(publish,final); shutil.rmtree(work,ignore_errors=True)
            return self.jobs.transition(job_id,JobStatus.COMPLETED,"Core AI 1 training completed; model remains inactive.",result_model_version=config.model_version,progress_value=100)
        except BackendError as exc:
            current=self.jobs.get(job_id)
            if exc.code=="cancelled" or current.cancellation_requested:
                if current.status!="cancelling": self.jobs.transition(job_id,JobStatus.CANCELLING,"Cancelling training.")
                return self.jobs.transition(job_id,JobStatus.CANCELLED,"Training cancelled; no model published.")
            return self.jobs.transition(job_id,JobStatus.FAILED,"Training failed.",failure_code=exc.code,failure_message=exc.safe_message)
        except Exception as exc: return self.jobs.transition(job_id,JobStatus.FAILED,"Training failed.",failure_code="runtime_failure",failure_message=str(exc)[:500])
        finally:
            if work and work.exists(): shutil.rmtree(work,ignore_errors=True)
            self._tokens.pop(job_id,None)
