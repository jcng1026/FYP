from dataclasses import dataclass,field
from typing import Dict,List,Optional

ROUNDING_POLICY_VERSION="nearest-half-mark-half-up-v1"
@dataclass(frozen=True)
class CoreAI1InferenceRequest:
    request_id:str; task_context:str; marking_scheme:str; effective_student_answer:str
    paper:str; part:str; maximum_score:float; input_checksum:str; selected_part3_question:Optional[str]=None
    model_version:Optional[str]=None; existing_teacher_reviewed:bool=False
@dataclass(frozen=True)
class CoreAI1InferenceResult:
    request_id:str; status:str; draft_raw_score:Optional[float]; normalized_score:Optional[float]
    proposed_application_score:Optional[float]; feedback_category:Optional[str]; category_confidence:Optional[float]
    score_confidence:Optional[float]; model_version:Optional[str]; model_checksum:Optional[str]
    dataset_lineage:Optional[str]; input_template_version:Optional[str]; input_checksum:str
    truncation_warning:bool; missing_scheme_warning:bool; warnings:List[str]=field(default_factory=list)
    runtime_duration_seconds:float=0; device:Optional[str]=None; clamped:bool=False
    rounding_policy_version:str=ROUNDING_POLICY_VERSION; failure_code:Optional[str]=None
    category_probabilities:Optional[Dict[str,float]]=None; truncation_statistics:Optional[Dict[str,int]]=None
