from dataclasses import dataclass,field
from typing import Any,Dict,List,Optional,Tuple

@dataclass(frozen=True)
class CoreAI2InferenceRequest:
    request_id:str; workflow_context:str; page_image_path:str; page_checksum:str
    page_width:int; page_height:int; model_version:Optional[str]=None; confidence_threshold:float=.25
    nms_threshold:float=.5; allowed_classes:Optional[List[str]]=None; profile_id:Optional[int]=None
    attempt_id:Optional[int]=None

@dataclass(frozen=True)
class RegionProposal:
    proposal_id:str; model_family:str; model_version:str; model_checksum:str; page_checksum:str
    region_class:str; normalized_bbox:Tuple[float,float,float,float]; pixel_bbox:Tuple[float,float,float,float]
    confidence:float; class_probabilities:Optional[Dict[str,float]]; runtime_duration_seconds:float
    device_used:str; warnings:List[str]=field(default_factory=list); provenance:Dict[str,Any]=field(default_factory=dict)
    rationale:Optional[str]=None

@dataclass(frozen=True)
class CoreAI2InferenceResult:
    request_id:str; status:str; proposals:List[RegionProposal]; model_version:Optional[str]
    model_checksum:Optional[str]; page_checksum:str; runtime_duration_seconds:float
    device_used:Optional[str]; warnings:List[str]=field(default_factory=list); failure_code:Optional[str]=None
    failure_message:Optional[str]=None; raw_outputs:Any=None
