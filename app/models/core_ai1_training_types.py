from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class CoreAI1TrainingConfig:
    local_base_model_path:str; model_version:str; max_sequence_length:int=384; batch_size:int=2
    gradient_accumulation:int=4; learning_rate:float=2e-5; epochs:int=3; warmup_ratio:float=.1
    weight_decay:float=.01; dropout:float=.1; regression_loss_weight:float=1.0
    classification_loss_weight:float=1.0; seed:int=42; device:str="auto"; mixed_precision:bool=True
    early_stopping_patience:int=2; checkpoint_interval:int=1; best_model_metric:str="validation_combined_loss"
    resume_checkpoint:Optional[str]=None; notes:Optional[str]=None
    def sanitized(self): return dict(self.__dict__)
