"""Side-effect-free Core AI 2 proposal generation for both page workflows."""
import time
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError
from app.models.core_ai2_inference_types import CoreAI2InferenceResult,RegionProposal
from app.services.core_ai2_dataset_registry_service import sha256_file
from app.services.core_ai_backend_job_service import CancellationToken

def _iou(a,b):
    ax,ay,aw,ah=a; bx,by,bw,bh=b; x=max(ax,bx); y=max(ay,by); r=min(ax+aw,bx+bw); d=min(ay+ah,by+bh); inter=max(0,r-x)*max(0,d-y); union=aw*ah+bw*bh-inter
    return inter/union if union else 0

class CoreAI2InferenceService:
    def __init__(self,model_service,runtime,approved_image_root):
        self.models=model_service; self.runtime=runtime
        roots=approved_image_root if isinstance(approved_image_root,(list,tuple,set)) else [approved_image_root]
        self.image_roots=[Path(root).resolve() for root in roots]
        self.image_root=self.image_roots[0]  # kept for existing callers/tests
    def _image(self,path):
        path=Path(path).resolve()
        if not any(root in path.parents or path==root for root in self.image_roots): raise BackendError("unsafe_input_path","Page image is outside the approved root.")
        if not path.is_file(): raise BackendError("input_missing","Page image does not exist.")
        return path
    def run(self,request,cancellation_token=None):
        started=time.perf_counter(); token=cancellation_token or CancellationToken(); raw=None
        try:
            if request.workflow_context not in ("subject_profile","separate_answer_paper"): raise BackendError("unsupported_workflow","Unsupported inference workflow context.")
            if request.page_width<=0 or request.page_height<=0: raise BackendError("invalid_dimensions","Page dimensions must be positive.")
            if not 0<=request.confidence_threshold<=1 or not 0<=request.nms_threshold<=1: raise BackendError("invalid_threshold","Thresholds must be within 0-1.")
            image=self._image(request.page_image_path)
            if sha256_file(image)!=request.page_checksum: raise BackendError("input_checksum_mismatch","Page image checksum does not match request.")
            pointer={"model_version":request.model_version} if request.model_version else self.models.get_active()
            folder,manifest,checksums=self.models._verify_model(pointer["model_version"]); model_checksum=checksums.get("best.pt")
            mapping=manifest.get("class_mapping",{}); reverse={value:key for key,value in mapping.items()}
            allowed=set(request.allowed_classes or mapping)
            unknown_allowed=allowed-set(mapping)
            if unknown_allowed: raise BackendError("unsupported_class","Requested classes are not supported by the model mapping.")
            runtime_info=self.runtime.inspect()
            if not runtime_info.get("available"): raise BackendError("detector_runtime_unavailable","Detector inference runtime is unavailable.")
            if sha256_file(folder/"best.pt")!=model_checksum: raise BackendError("model_checksum_mismatch","Active model checkpoint checksum failed.")
            self.runtime.load(folder/"best.pt",model_checksum); token.raise_if_cancelled()
            raw=self.runtime.infer(image,request.confidence_threshold,request.nms_threshold,token); detections=[]; warnings=[]
            for item in raw.get("detections",[]):
                confidence=float(item.get("confidence",0))
                if confidence<request.confidence_threshold: continue
                class_id=item.get("class_id")
                if class_id not in reverse: raise BackendError("unsupported_class","Detector returned an unknown class ID.")
                region_class=reverse[class_id]
                if region_class not in allowed: continue
                xyxy=item.get("bbox_xyxy")
                if not isinstance(xyxy,(list,tuple)) or len(xyxy)!=4: raise BackendError("invalid_detector_geometry","Detector returned invalid geometry.")
                x1,y1,x2,y2=map(float,xyxy)
                if x2<=x1 or y2<=y1 or x1<-.001 or y1<-.001 or x2>request.page_width+.001 or y2>request.page_height+.001: raise BackendError("invalid_detector_geometry","Detector box is outside valid page geometry.")
                x1=max(0.0,x1); y1=max(0.0,y1); x2=min(float(request.page_width),x2); y2=min(float(request.page_height),y2)
                pixel=(x1,y1,x2-x1,y2-y1); normalized=(x1/request.page_width,y1/request.page_height,(x2-x1)/request.page_width,(y2-y1)/request.page_height)
                detections.append({"class":region_class,"confidence":confidence,"pixel":pixel,"normalized":normalized,"probabilities":item.get("class_probabilities"),"raw":item})
            detections.sort(key=lambda d:(-d["confidence"],d["class"],d["normalized"]))
            kept=[]
            for detection in detections:
                if any(detection["class"]==prior["class"] and _iou(detection["normalized"],prior["normalized"])>request.nms_threshold for prior in kept): continue
                kept.append(detection)
            duration=time.perf_counter()-started; device=raw.get("device","unknown"); proposals=[]
            for index,item in enumerate(kept,1): proposals.append(RegionProposal(f"{request.request_id}-{index:04d}","core_ai2",pointer["model_version"],model_checksum,request.page_checksum,item["class"],item["normalized"],item["pixel"],item["confidence"],item["probabilities"],duration,device,warnings,{"workflow_context":request.workflow_context,"profile_id":request.profile_id,"attempt_id":request.attempt_id},None))
            return CoreAI2InferenceResult(request.request_id,"completed",proposals,pointer["model_version"],model_checksum,request.page_checksum,duration,device,warnings,raw_outputs=raw)
        except BackendError as exc:
            return CoreAI2InferenceResult(request.request_id,"cancelled" if exc.code=="cancelled" else "failed",[],request.model_version,None,request.page_checksum,time.perf_counter()-started,None,[],exc.code,exc.safe_message,raw)
        except Exception as exc:
            return CoreAI2InferenceResult(request.request_id,"failed",[],request.model_version,None,request.page_checksum,time.perf_counter()-started,None,[],"runtime_failure",str(exc)[:500],raw)
