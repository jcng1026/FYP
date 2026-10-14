"""Approved-root filesystem layout and traversal-safe path helpers."""
import re
from dataclasses import dataclass
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError

SAFE_COMPONENT=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

def safe_component(value,label="path component"):
    value=str(value)
    if not SAFE_COMPONENT.fullmatch(value) or value in (".",".."):
        raise BackendError("unsafe_path",f"Invalid {label}.")
    return value

def safe_relative(root,*parts):
    root=Path(root).resolve(); clean=[safe_component(p) for p in parts]; result=root.joinpath(*clean).resolve()
    if result!=root and root not in result.parents: raise BackendError("unsafe_path","Path escapes approved root.")
    return result

@dataclass(frozen=True)
class AIBackendPaths:
    data_root:Path
    def __post_init__(self): object.__setattr__(self,"data_root",Path(self.data_root).resolve())
    @property
    def ai_root(self): return self.data_root/"ai"
    @property
    def jobs_root(self): return self.ai_root/"jobs"
    @property
    def models_root(self): return self.ai_root/"models"
    @property
    def active_root(self): return self.ai_root/"active"
    @property
    def history_root(self): return self.ai_root/"activation_history"
    @property
    def evaluations_root(self): return self.ai_root/"evaluations"
    @property
    def cache_root(self): return self.ai_root/"runtime_cache"
    @property
    def temporary_root(self): return self.ai_root/"temporary"
    @property
    def candidates_root(self): return self.ai_root/"candidates"
    def job_folder(self,job_id): return safe_relative(self.jobs_root,job_id)
    def model_folder(self,family,version): return safe_relative(self.models_root,family,version)
    def active_pointer(self,family): return safe_relative(self.active_root,f"{safe_component(family)}.json")
    def ensure_layout(self):
        for folder in (self.jobs_root,self.models_root,self.active_root,self.history_root,self.evaluations_root,self.cache_root,self.temporary_root,self.candidates_root): folder.mkdir(parents=True,exist_ok=True)
