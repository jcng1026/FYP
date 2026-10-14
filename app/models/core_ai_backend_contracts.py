"""Stable dependency-free contracts shared by all local AI backends."""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class ModelFamily(str,Enum):
    CORE_AI1="core_ai1"
    CORE_AI2="core_ai2"

class DatasetFamily(str,Enum):
    K2_SCORING_FEEDBACK="core_ai1"
    ANSWER_REGION_DETECTION="core_ai2"

class JobStatus(str,Enum):
    QUEUED="queued"; VALIDATING="validating"; RUNNING="running"; CANCELLING="cancelling"
    CANCELLED="cancelled"; PUBLISHING="publishing"; COMPLETED="completed"; FAILED="failed"; INTERRUPTED="interrupted"

TERMINAL_JOB_STATES={JobStatus.CANCELLED,JobStatus.COMPLETED,JobStatus.FAILED,JobStatus.INTERRUPTED}

class BackendError(RuntimeError):
    def __init__(self,code,message): super().__init__(message); self.code=code; self.safe_message=message

@dataclass(frozen=True)
class DatasetDescriptor:
    family:str; version:str; path:str; export_valid:bool; training_ready:bool; frozen:bool
    schema_version:Optional[str]=None; mapping_version:Optional[str]=None; source_commit:Optional[str]=None
    manifest_checksum:Optional[str]=None; split_mode:Optional[str]=None; blockers:List[str]=field(default_factory=list)
    warnings:List[str]=field(default_factory=list); statistics:Dict[str,Any]=field(default_factory=dict)
    supported_formats:List[str]=field(default_factory=list)

@dataclass(frozen=True)
class TrainingRequest:
    model_family:str; dataset_version:str; requested_model_version:str; configuration:Dict[str,Any]
    conversion_version:Optional[str]=None; notes:Optional[str]=None

@dataclass
class TrainingJobRecord:
    job_id:str; model_family:str; dataset_version:str; requested_model_version:str; created_at:str
    status:str=JobStatus.QUEUED.value; started_at:Optional[str]=None; completed_at:Optional[str]=None
    cancellation_requested:bool=False; progress_message:str="Queued"; progress_value:Optional[float]=None
    current_epoch:Optional[int]=None; current_step:Optional[int]=None; configuration:Dict[str,Any]=field(default_factory=dict)
    hardware_runtime:Dict[str,Any]=field(default_factory=dict); events:List[Dict[str,Any]]=field(default_factory=list)
    result_model_version:Optional[str]=None; failure_code:Optional[str]=None; failure_message:Optional[str]=None

@dataclass(frozen=True)
class ModelDescriptor:
    family:str; version:str; path:str; checksum:str; created_at:str; source_dataset_version:str
    source_dataset_checksum:str; training_job_id:str; base_model_identifier:str; architecture:str
    mapping:Dict[str,int]; compatible_schema_versions:List[str]; evaluation_status:str="unevaluated"
    activation_status:str="inactive"; runtime_compatibility:str="unknown"; hardware_requirements:Dict[str,Any]=field(default_factory=dict)
    artifact_inventory:List[Dict[str,Any]]=field(default_factory=list); warnings:List[str]=field(default_factory=list)

@dataclass(frozen=True)
class EvaluationResult:
    evaluation_id:str; model_version:str; dataset_version:str; dataset_checksum:str; split:str
    metrics:Dict[str,Any]; per_class_metrics:Dict[str,Any]; errors:List[str]; warnings:List[str]
    passed:bool; decision_criteria:Dict[str,Any]; evaluated_at:str

@dataclass(frozen=True)
class InferenceEnvelope:
    request_id:str; model_family:str; model_version:str; model_checksum:str; input_checksum:str
    status:str; runtime:str; duration_seconds:float; warnings:List[str]; raw_outputs:Any; draft_outputs:Any

@dataclass(frozen=True)
class FeedbackResult:
    generation_source:str; runtime_identifier:str; model_name:Optional[str]; input_checksum:str
    feedback_category:str; generated_feedback:Optional[str]; template_fallback_feedback:Optional[str]
    warnings:List[str]; duration_seconds:float; failure_status:Optional[str]=None

def contract_to_dict(value): return asdict(value)
