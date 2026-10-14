from dataclasses import dataclass,field
from typing import Any,Dict,Optional

@dataclass(frozen=True)
class CoreAI2TrainingConfig:
    local_base_checkpoint:str; model_version:str; conversion_version:str
    image_size:int=640; epochs:int=50; batch_size:int=4; learning_rate:Optional[float]=None
    patience:int=10; workers:int=2; device:str="auto"; seed:int=42; mixed_precision:bool=True
    deterministic:bool=True; resume_checkpoint:Optional[str]=None; safe_oom_retry:bool=False
    training_notes:Optional[str]=None; extra:Dict[str,Any]=field(default_factory=dict)

    def sanitized(self):
        data=dict(self.__dict__); data["local_base_checkpoint"]=str(data["local_base_checkpoint"])
        data["resume_checkpoint"]=str(data["resume_checkpoint"]) if data["resume_checkpoint"] else None
        return data
