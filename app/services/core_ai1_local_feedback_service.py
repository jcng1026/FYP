"""Local-only OpenAI/Ollama-compatible feedback generation."""
import ipaddress,json,re,time,urllib.error,urllib.request
from urllib.parse import urlparse
from app.models.core_ai1_feedback_types import LOCAL_FEEDBACK_PROMPT_VERSION
from app.models.core_ai_backend_contracts import FeedbackResult
from app.services.core_ai_backend_job_service import CancellationToken

def _endpoint_allowed(endpoint,allow_private):
    parsed=urlparse(endpoint); host=parsed.hostname
    if parsed.scheme not in ("http","https") or not host: return False
    if host.lower()=="localhost": return True
    try:
        ip=ipaddress.ip_address(host)
        if ip.is_loopback: return True
        return bool(allow_private and ip.is_private)
    except ValueError: return False

def _prompt(request):
    return f"""[TEMPLATE {LOCAL_FEEDBACK_PROMPT_VERSION}]
You provide concise constructive feedback for a Malaysian secondary-school English student. This is feedback, not rescoring. Never change or propose a numerical score. Use the supplied category and marking scheme only; do not invent missing criteria. Address relevant task fulfilment, organisation, grammar, spelling, and vocabulary without harsh language or internal model terminology. Keep the feedback under {request.requested_feedback_length} characters. Return strict JSON with one string field named feedback.
[PAPER] {request.paper} [PART] {request.part}
[CATEGORY] {request.feedback_category}
[FIXED_SCORE_CONTEXT] {request.score_context}/{request.maximum_score}
[TASK] {request.question_context}
[MARKING_SCHEME] {request.marking_scheme}
[STUDENT_ANSWER] {request.effective_student_answer}"""

def _clean_feedback(text,limit):
    text="".join(ch for ch in str(text) if ch in "\n\t" or ord(ch)>=32).strip()
    if not text: raise ValueError("Feedback output is empty.")
    warnings=[]
    score_pattern=re.compile(r"(?i)(?:score|mark)\s*(?:is|:|=)?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?")
    if score_pattern.search(text): text=score_pattern.sub("",text).strip(" .;,-"); warnings.append("Local model attempted to include a numerical score; that content was removed.")
    if not text: raise ValueError("Feedback contained only prohibited score content.")
    if len(text)>limit:
        # The requested length is a target, not a validity rule - a chatty model
        # must not randomly fail the whole generation. Shorten at a sentence
        # boundary when one exists in the second half, else hard-clip.
        clipped=text[:limit]
        cut=max(clipped.rfind(". "),clipped.rfind("! "),clipped.rfind("? "),clipped.rfind(".\n"))
        text=(clipped[:cut+1] if cut>=limit//2 else clipped).strip()
        warnings.append("Local model output exceeded the requested feedback length and was shortened.")
    return text,warnings

class LocalFeedbackService:
    def generate(self,request,cancellation_token=None):
        token=cancellation_token or CancellationToken(); started=time.perf_counter(); warnings=[]
        def failure(code,message):
            retained=request.previous_teacher_feedback
            return FeedbackResult("previous_teacher_feedback" if retained else "local_llm",request.adapter,request.model_name,request.input_checksum,request.feedback_category,retained,None,[message],time.perf_counter()-started,code)
        if not _endpoint_allowed(request.endpoint,request.allow_private_network): return failure("endpoint_not_allowed","Endpoint is not an approved localhost/private-network address.")
        if request.adapter not in ("openai","ollama"): return failure("adapter_unsupported","Unsupported local feedback adapter.")
        try:
            token.raise_if_cancelled(); prompt=_prompt(request)
            if request.adapter=="openai": payload={"model":request.model_name,"messages":[{"role":"user","content":prompt}],"temperature":request.temperature,"max_tokens":request.maximum_output_tokens,"response_format":{"type":"json_object"}}
            else: payload={"model":request.model_name,"messages":[{"role":"user","content":prompt}],"stream":False,"options":{"temperature":request.temperature,"num_predict":request.maximum_output_tokens},"format":"json"}
            http=urllib.request.Request(request.endpoint,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"EnglishGradingSystem-LocalAI/1"},method="POST")
            with urllib.request.urlopen(http,timeout=request.timeout_seconds) as response:
                body=response.read(request.response_size_limit+1)
            if len(body)>request.response_size_limit: return failure("response_too_large","Local runtime response exceeded the configured size limit.")
            token.raise_if_cancelled(); envelope=json.loads(body.decode("utf-8"))
            content=envelope.get("choices",[{}])[0].get("message",{}).get("content") if request.adapter=="openai" else envelope.get("message",{}).get("content",envelope.get("response"))
            if not isinstance(content,str): return failure("feedback_field_missing","Local runtime response did not contain feedback content.")
            try:
                parsed=json.loads(content); content=parsed.get("feedback")
            except json.JSONDecodeError:
                # Plain content is accepted only if it is already feedback text.
                if content.lstrip().startswith(("{", "[")):
                    return failure("malformed_json", "Local runtime returned malformed JSON content.")
            if not isinstance(content,str): return failure("feedback_field_missing","Strict feedback field is missing.")
            clean,content_warnings=_clean_feedback(content,request.requested_feedback_length); warnings.extend(content_warnings)
            return FeedbackResult("local_llm",request.adapter,request.model_name,request.input_checksum,request.feedback_category,clean,None,warnings,time.perf_counter()-started,None)
        except Exception as exc:
            code="cancelled" if getattr(exc,"code",None)=="cancelled" else ("timeout" if isinstance(exc,(TimeoutError,urllib.error.URLError)) and "timed out" in str(exc).lower() else "local_runtime_failure")
            return failure(code,"Local feedback generation failed; previous teacher feedback was preserved.")
