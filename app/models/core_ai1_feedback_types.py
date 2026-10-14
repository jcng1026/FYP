from dataclasses import dataclass
from typing import Optional

LOCAL_FEEDBACK_PROMPT_VERSION="local-feedback-v2"
@dataclass(frozen=True)
class LocalFeedbackRequest:
    request_id:str; adapter:str; endpoint:str; model_name:str; question_context:str
    marking_scheme:str; effective_student_answer:str; feedback_category:str; score_context:float
    maximum_score:float; paper:str; part:str; input_checksum:str; timeout_seconds:float=15
    maximum_output_tokens:int=180; temperature:float=.2; response_size_limit:int=8192
    requested_feedback_length:int=500; allow_private_network:bool=False
    previous_teacher_feedback:Optional[str]=None
