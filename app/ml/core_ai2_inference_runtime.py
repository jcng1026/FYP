"""Lazy Ultralytics inference adapter; no downloads and one loaded model."""
import importlib.util
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError

class UltralyticsDetectorInferenceRuntime:
    runtime_name="ultralytics"
    def __init__(self): self._model=None; self._checksum=None
    def inspect(self): return {"available":importlib.util.find_spec("ultralytics") is not None,"runtime":"ultralytics"}
    def load(self,checkpoint,checksum):
        if self._checksum==checksum and self._model is not None: return
        if not Path(checkpoint).is_file(): raise BackendError("model_artifact_missing","Detector checkpoint is missing.")
        if importlib.util.find_spec("ultralytics") is None: raise BackendError("detector_runtime_unavailable","Ultralytics inference runtime is unavailable.")
        from ultralytics import YOLO
        self._model=YOLO(str(checkpoint)); self._checksum=checksum
    def unload(self): self._model=None; self._checksum=None
    def infer(self,image_path,confidence,nms,cancellation_token):
        cancellation_token.raise_if_cancelled()
        results=self._model.predict(source=str(image_path),conf=confidence,iou=nms,verbose=False)
        output=[]
        for result in results:
            boxes=result.boxes
            for xyxy,conf,cls in zip(boxes.xyxy.cpu().tolist(),boxes.conf.cpu().tolist(),boxes.cls.cpu().tolist()): output.append({"class_id":int(cls),"bbox_xyxy":xyxy,"confidence":float(conf),"class_probabilities":None})
        return {"detections":output,"device":str(getattr(self._model,"device","unknown"))}
