"""Atomic persistent jobs with factual state transitions and cancellation."""
import json,os,tempfile,threading,uuid
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError,JobStatus,TERMINAL_JOB_STATES,TrainingJobRecord
from app.services.core_ai_backend_paths import AIBackendPaths

TRANSITIONS={
 JobStatus.QUEUED:{JobStatus.VALIDATING,JobStatus.CANCELLING,JobStatus.CANCELLED,JobStatus.FAILED},
 JobStatus.VALIDATING:{JobStatus.RUNNING,JobStatus.CANCELLING,JobStatus.CANCELLED,JobStatus.FAILED,JobStatus.INTERRUPTED},
 JobStatus.RUNNING:{JobStatus.PUBLISHING,JobStatus.CANCELLING,JobStatus.CANCELLED,JobStatus.FAILED,JobStatus.INTERRUPTED},
 JobStatus.CANCELLING:{JobStatus.CANCELLED,JobStatus.FAILED,JobStatus.INTERRUPTED}, JobStatus.PUBLISHING:{JobStatus.COMPLETED,JobStatus.FAILED,JobStatus.INTERRUPTED},
 JobStatus.CANCELLED:set(),JobStatus.COMPLETED:set(),JobStatus.FAILED:set(),JobStatus.INTERRUPTED:set()}
def _now(): return datetime.now(timezone.utc).isoformat()
def _sanitize(value,limit=500):
    text="".join(ch if ord(ch)>=32 else " " for ch in str(value)).replace("\r"," ").replace("\n"," ")
    return text[:limit]

def _sanitize_configuration(value,key=""):
    if any(term in key.lower() for term in ("essay","prompt","student_answer","private_comment","audit_prose")):
        return "[redacted]"
    if isinstance(value,dict): return {str(k)[:100]:_sanitize_configuration(v,str(k)) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [_sanitize_configuration(v,key) for v in value[:100]]
    if isinstance(value,(str,int,float,bool)) or value is None: return _sanitize(value,500) if isinstance(value,str) else value
    return _sanitize(value,200)

class CancellationToken:
    def __init__(self): self._event=threading.Event()
    def cancel(self): self._event.set()
    @property
    def cancelled(self): return self._event.is_set()
    def raise_if_cancelled(self):
        if self.cancelled: raise BackendError("cancelled","Operation cancelled.")

class AIJobStore:
    def __init__(self,paths:AIBackendPaths,max_events=1000):
        self.paths=paths; self.max_events=max(10,int(max_events)); self._lock=threading.RLock(); paths.ensure_layout()
        self._claims_root=self.paths.jobs_root/".target_claims"; self._claims_root.mkdir(parents=True,exist_ok=True)
    def _file(self,job_id): return self.paths.job_folder(job_id)/"job.json"
    def _write(self,record):
        folder=self.paths.job_folder(record.job_id); folder.mkdir(parents=True,exist_ok=True); target=self._file(record.job_id)
        fd,name=tempfile.mkstemp(prefix=".job_",suffix=".tmp",dir=folder); os.close(fd)
        try: Path(name).write_text(json.dumps(asdict(record),indent=2,sort_keys=True),encoding="utf-8"); os.replace(name,target)
        finally: Path(name).unlink(missing_ok=True)
    def _claim_path(self,family,version):
        from app.services.core_ai_backend_paths import safe_component
        return self._claims_root/f"{safe_component(family)}--{safe_component(version)}.claim"
    def _claim_target(self,request,job_id):
        path=self._claim_path(request.model_family,request.requested_model_version)
        try:
            descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
            with os.fdopen(descriptor,"w",encoding="utf-8") as stream: stream.write(job_id)
        except FileExistsError:
            try:
                existing=self.get(path.read_text(encoding="utf-8").strip())
                if JobStatus(existing.status) in TERMINAL_JOB_STATES:
                    path.unlink(missing_ok=True); return self._claim_target(request,job_id)
            except BackendError: pass
            raise BackendError("duplicate_training_target","A non-terminal job already targets this model version.")
        return path
    def _release_claim(self,record):
        path=self._claim_path(record.model_family,record.requested_model_version)
        try:
            if path.read_text(encoding="utf-8").strip()==record.job_id: path.unlink(missing_ok=True)
        except OSError: pass
    def create(self,request,job_id=None):
        with self._lock:
            job_id=job_id or uuid.uuid4().hex; folder=self.paths.job_folder(job_id)
            if folder.exists(): raise BackendError("job_exists","Job already exists.")
            claim=self._claim_target(request,job_id)
            try:
                record=TrainingJobRecord(job_id,request.model_family,request.dataset_version,request.requested_model_version,_now(),configuration=_sanitize_configuration(dict(request.configuration)))
                record.events=[{"at":record.created_at,"state":"queued","message":"Job queued."}]; self._write(record); return record
            except Exception:
                claim.unlink(missing_ok=True); raise
    def get(self,job_id):
        path=self._file(job_id)
        if not path.is_file(): raise BackendError("job_not_found","Job not found.")
        return TrainingJobRecord(**json.loads(path.read_text(encoding="utf-8")))
    def list(self,model_family=None):
        records=[]
        for path in self.paths.jobs_root.glob("*/job.json"):
            try:
                record=TrainingJobRecord(**json.loads(path.read_text(encoding="utf-8")))
                if not model_family or record.model_family==model_family: records.append(record)
            except Exception: continue
        return sorted(records,key=lambda r:(r.created_at,r.job_id),reverse=True)
    def transition(self,job_id,new_status,message,**updates):
        with self._lock:
            record=self.get(job_id); current=JobStatus(record.status); target=JobStatus(new_status)
            if target not in TRANSITIONS[current]: raise BackendError("invalid_job_transition",f"Cannot transition {current.value} to {target.value}.")
            record.status=target.value; record.progress_message=_sanitize(message)
            if target==JobStatus.RUNNING and not record.started_at: record.started_at=_now()
            if target in TERMINAL_JOB_STATES: record.completed_at=_now()
            allowed={"progress_value","current_epoch","current_step","hardware_runtime","result_model_version","failure_code","failure_message"}
            for key,value in updates.items():
                if key in allowed:
                    setattr(record,key,_sanitize(value) if key=="failure_message" else value)
            record.events=(record.events+[{"at":_now(),"state":target.value,"message":_sanitize(message)}])[-self.max_events:]
            self._write(record)
            if target in TERMINAL_JOB_STATES: self._release_claim(record)
            return record
    def append_progress(self,job_id,message,progress_value=None,current_epoch=None,current_step=None,event_type="progress"):
        with self._lock:
            record=self.get(job_id)
            if JobStatus(record.status) in TERMINAL_JOB_STATES: raise BackendError("job_terminal","Terminal jobs cannot report progress.")
            record.progress_message=_sanitize(message)
            if progress_value is not None:
                progress_value=float(progress_value)
                if not 0<=progress_value<=100: raise BackendError("invalid_progress","Progress must be between zero and 100 percent.")
                record.progress_value=progress_value
            if current_epoch is not None: record.current_epoch=max(0,int(current_epoch))
            if current_step is not None: record.current_step=max(0,int(current_step))
            record.events=(record.events+[{"at":_now(),"state":record.status,"type":_sanitize(event_type,40),"message":record.progress_message,"progress_value":record.progress_value,"current_epoch":record.current_epoch,"current_step":record.current_step}])[-self.max_events:]
            self._write(record); return record
    def request_cancellation(self,job_id):
        with self._lock:
            record=self.get(job_id)
            if JobStatus(record.status) in TERMINAL_JOB_STATES: raise BackendError("job_terminal","Completed jobs cannot be cancelled.")
            record.cancellation_requested=True; self._write(record)
            return self.transition(job_id,JobStatus.CANCELLING,"Cancellation requested.")
    def recover_interrupted(self):
        recovered=[]
        for record in self.list():
            if JobStatus(record.status) in (JobStatus.VALIDATING,JobStatus.RUNNING,JobStatus.CANCELLING,JobStatus.PUBLISHING):
                recovered.append(self.transition(record.job_id,JobStatus.INTERRUPTED,"Interrupted by application restart."))
        return recovered

def assert_model_deletable(paths,family,version):
    """Guard for any future deletion adapter; active models are never deletable."""
    pointer=paths.active_pointer(family)
    if pointer.is_file():
        try:
            if json.loads(pointer.read_text(encoding="utf-8")).get("model_version")==version:
                raise BackendError("active_model_delete_forbidden","The active model cannot be deleted.")
        except json.JSONDecodeError:
            raise BackendError("active_pointer_corrupt","Model deletion is blocked while the active pointer is corrupt.")
    return True
