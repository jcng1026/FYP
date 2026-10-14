"""Replaceable detector runtime; heavy Ultralytics imports are lazy."""
import importlib.util,platform,sys
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError

class UltralyticsDetectorTrainingRuntime:
    runtime_name="ultralytics"
    def inspect(self):
        available=importlib.util.find_spec("ultralytics") is not None
        result={"runtime":"ultralytics","available":available,"python":sys.version.split()[0],"platform":platform.platform(),"cuda_available":False,"gpu_name":None,"vram_bytes":None}
        if importlib.util.find_spec("torch"):
            import torch
            result.update({"torch_version":torch.__version__,"cuda_available":bool(torch.cuda.is_available()),"cuda_version":torch.version.cuda})
            if torch.cuda.is_available():
                props=torch.cuda.get_device_properties(0); result.update({"gpu_name":props.name,"vram_bytes":props.total_memory})
        return result
    def train(self,dataset_yaml,output_folder,config,progress,cancellation_token):
        checkpoint=Path(config.local_base_checkpoint)
        if not checkpoint.is_file(): raise BackendError("base_checkpoint_missing","Configured local detector checkpoint does not exist.")
        if importlib.util.find_spec("ultralytics") is None: raise BackendError("detector_runtime_unavailable","Ultralytics is not installed; install optional AI dependencies locally.")
        cancellation_token.raise_if_cancelled()
        from ultralytics import YOLO
        model=YOLO(str(checkpoint))
        kwargs={"data":str(dataset_yaml),"project":str(output_folder),"name":"run","exist_ok":False,"imgsz":config.image_size,"epochs":config.epochs,"batch":config.batch_size,"patience":config.patience,"workers":config.workers,"device":config.device,"seed":config.seed,"amp":config.mixed_precision,"deterministic":config.deterministic}
        if config.learning_rate is not None: kwargs["lr0"]=config.learning_rate
        progress("Starting local detector runtime.",None,None)
        model.train(**kwargs); cancellation_token.raise_if_cancelled()
        run=Path(output_folder)/"run"; best=run/"weights"/"best.pt"; last=run/"weights"/"last.pt"
        if not best.is_file(): raise BackendError("training_artifact_missing","Detector runtime did not produce best.pt.")
        return {"best_checkpoint":str(best),"last_checkpoint":str(last) if last.is_file() else None,"raw_metrics":{},"runtime":"ultralytics"}
