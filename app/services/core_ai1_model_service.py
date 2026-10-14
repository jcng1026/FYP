"""Core AI 1 evaluation, activation and draft-only inference."""
import json,math,os,tempfile,time,uuid
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError
from app.models.core_ai1_inference_types import CoreAI1InferenceResult
from app.ml.core_ai1_cross_encoder_runtime import compose_input
from app.services.core_ai_backend_paths import safe_component
from app.services.core_ai2_dataset_registry_service import sha256_file

def _now(): return datetime.now(timezone.utc).isoformat()
def _atomic(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix=".json_",dir=path.parent); os.close(fd)
    try: Path(name).write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8"); os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)
def _metrics(rows,predictions,mapping):
    n=len(rows); raw_true=[float(r["raw_score"]) for r in rows]; raw_pred=[float(p["normalized_score"])*float(r["maximum_score"]) for r,p in zip(rows,predictions)]; errors=[abs(a-b) for a,b in zip(raw_true,raw_pred)]
    truth=[int(r["category_id"]) for r in rows]; predicted=[int(p["category_id"]) for p in predictions]; labels=sorted(mapping.values()); confusion=[[sum(t==a and p==b for t,p in zip(truth,predicted)) for b in labels] for a in labels]
    per={}; total=n
    for label in labels:
        tp=sum(t==label and p==label for t,p in zip(truth,predicted)); fp=sum(t!=label and p==label for t,p in zip(truth,predicted)); fn=sum(t==label and p!=label for t,p in zip(truth,predicted)); support=sum(t==label for t in truth); precision=tp/(tp+fp) if tp+fp else 0; recall=tp/(tp+fn) if tp+fn else 0; f1=2*precision*recall/(precision+recall) if precision+recall else 0; per[str(label)]={"precision":precision,"recall":recall,"f1":f1,"support":support}
    macro=sum(v["f1"] for v in per.values())/len(per) if per else 0; weighted=sum(v["f1"]*v["support"] for v in per.values())/total if total else 0
    return {"support":n,"mae_raw_marks":sum(errors)/n,"rmse_raw_marks":math.sqrt(sum((a-b)**2 for a,b in zip(raw_true,raw_pred))/n),"normalized_mae":sum(abs(float(r["normalized_score"])-float(p["normalized_score"])) for r,p in zip(rows,predictions))/n,"exact_score_accuracy":sum(round(a,6)==round(b,6) for a,b in zip(raw_true,raw_pred))/n,"within_one_mark_accuracy":sum(abs(a-b)<=1 for a,b in zip(raw_true,raw_pred))/n,"category_accuracy":sum(a==b for a,b in zip(truth,predicted))/n,"macro_f1":macro,"weighted_f1":weighted,"per_category":per,"confusion_matrix":confusion}

class CoreAI1ModelService:
    def __init__(self,paths,dataset_root,runtime): self.paths=paths; self.dataset_root=Path(dataset_root); self.runtime=runtime; paths.ensure_layout()
    def _model(self,v): return self.paths.model_folder("core_ai1",v)
    def _verify(self,v):
        folder=self._model(v)
        try: manifest=json.loads((folder/"model_manifest.json").read_text()); checks=json.loads((folder/"checksums.json").read_text())
        except Exception: raise BackendError("model_incomplete","Completed Core AI 1 model not found.")
        for rel,expected in checks.items():
            if not (folder/rel).is_file() or sha256_file(folder/rel)!=expected: raise BackendError("model_checksum_mismatch","Core AI 1 model integrity failed.")
        return folder,manifest,checks
    def inspect_model(self,version):
        folder,manifest,checks=self._verify(version); return {**manifest,"path":str(folder),"model_checksum":checks.get("heads.pt"),"integrity_valid":True}
    def list_models(self):
        root=self.paths.models_root/"core_ai1"; result=[]
        if not root.exists(): return result
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try: result.append(self.inspect_model(folder.name))
            except BackendError: continue
        return result
    def compare(self,left,right):
        left_model=self.inspect_model(left); right_model=self.inspect_model(right); left_eval=self._evaluations(left); right_eval=self._evaluations(right)
        controlled=bool(left_eval and right_eval and left_eval[0].get("dataset_checksum")==right_eval[0].get("dataset_checksum"))
        return {"left":left,"right":right,"source_dataset_versions":{"left":left_model.get("source_dataset_version"),"right":right_model.get("source_dataset_version")},"mapping_compatible":left_model.get("category_mapping_version")==right_model.get("category_mapping_version"),"template_compatible":left_model.get("input_template_version")==right_model.get("input_template_version"),"controlled_comparison":controlled,"metrics":{"left":left_eval[0].get("metrics") if left_eval else None,"right":right_eval[0].get("metrics") if right_eval else None},"warnings":[] if controlled else ["Models lack evaluations on the same dataset; metric comparison is uncontrolled."]}
    def _evaluations(self,v):
        folder=self.paths.evaluations_root/"core_ai1"/safe_component(v)
        return sorted([json.loads(p.read_text()) for p in folder.glob("*.json")],key=lambda e:e["evaluated_at"],reverse=True) if folder.exists() else []
    def evaluate(self,model_version,dataset_version):
        folder,model,checks=self._verify(model_version); dataset=self.dataset_root/f"dataset_{safe_component(dataset_version)}"; dm=json.loads((dataset/"manifest.json").read_text()); dc=json.loads((dataset/"checksums.json").read_text()); mapping=json.loads((dataset/"category_mapping.json").read_text()); split=json.loads((dataset/"splits.json").read_text())
        if dm["split_mode"]!="three_way": raise BackendError("evaluation_split_missing","Validation and test splits are required.")
        if model["category_mapping_version"]!=mapping["version"] or model["input_template_version"]!=dm["input_template_version"]: raise BackendError("model_dataset_incompatible","Category mapping or input template differs.")
        samples=[json.loads(line) for line in (dataset/"samples.jsonl").read_text().splitlines() if line]; results={}; warnings=[]
        for name in ("validation","test"):
            rows=[s for s in samples if split["assignments"].get(s["sample_id"])==name]
            if not rows: raise BackendError("evaluation_split_empty",f"{name} split is empty.")
            predictions=self.runtime.predict_batch(folder,rows)
            if any(prediction.get("status")=="failed" or "normalized_score" not in prediction for prediction in predictions): raise BackendError("evaluation_inference_failed",f"{name} evaluation inference failed for one or more samples.")
            results[name]={"metrics":_metrics(rows,predictions,mapping["mapping"]),"raw_predictions":predictions}
            if len(rows)<10: warnings.append(f"{name} split has small support ({len(rows)}); interpret metrics cautiously.")
        evaluation={"evaluation_id":uuid.uuid4().hex,"model_family":"core_ai1","model_version":model_version,"model_checksum":checks.get("heads.pt"),"dataset_version":dataset_version,"dataset_checksum":dc["manifest_checksum"],"category_mapping_version":mapping["version"],"input_template_version":dm["input_template_version"],"metrics":results,"warnings":warnings,"errors":[],"passed":True,"evaluated_at":_now()}; target=self.paths.evaluations_root/"core_ai1"/model_version/f"{evaluation['evaluation_id']}.json"; _atomic(target,evaluation); return evaluation
    def get_active(self,required=True):
        path=self.paths.active_pointer("core_ai1")
        if not path.is_file():
            if required: raise BackendError("no_active_model","No active Core AI 1 model is configured.")
            return None
        data=json.loads(path.read_text()); self._verify(data["model_version"]); return data
    def activate(self,version,actor,reason,action="activate"):
        _,model,checks=self._verify(version); evaluations=self._evaluations(version)
        if not evaluations or not evaluations[0].get("passed"): raise BackendError("evaluation_required","Passing Core AI 1 evaluation is required.")
        previous=self.get_active(False); pointer={"model_family":"core_ai1","model_version":version,"model_checksum":checks.get("heads.pt"),"actor":actor,"reason":reason,"activated_at":_now(),"previous_model_version":previous.get("model_version") if previous else None,"action":action}; _atomic(self.paths.active_pointer("core_ai1"),pointer); _atomic(self.paths.history_root/f"{pointer['activated_at'].replace(':','-')}_{action}_core_ai1.json",pointer); return pointer
    def rollback(self,version,actor,reason): return self.activate(version,actor,reason,"rollback")
    def infer(self,request):
        started=time.perf_counter(); warnings=[]
        if request.existing_teacher_reviewed: return CoreAI1InferenceResult(request.request_id,"skipped",None,None,None,None,None,None,request.model_version,None,None,None,request.input_checksum,False,not bool(request.marking_scheme),["Existing teacher-reviewed value was not overwritten."],failure_code="teacher_reviewed")
        if request.paper.lower() not in ("kertas2","k2"): return CoreAI1InferenceResult(request.request_id,"failed",None,None,None,None,None,None,request.model_version,None,None,None,request.input_checksum,False,False,[],failure_code="kertas1_unsupported")
        if not request.effective_student_answer.strip(): return CoreAI1InferenceResult(request.request_id,"attention_required",None,None,None,None,None,None,request.model_version,None,None,None,request.input_checksum,False,not bool(request.marking_scheme),["Student answer is blank; no draft score was generated."],failure_code="blank_answer")
        if request.maximum_score<=0: return CoreAI1InferenceResult(request.request_id,"failed",None,None,None,None,None,None,request.model_version,None,None,None,request.input_checksum,False,False,[],failure_code="invalid_maximum_score")
        if not request.marking_scheme.strip(): warnings.append("Marking scheme is missing or unclear; teacher attention is required.")
        try:
            pointer={"model_version":request.model_version} if request.model_version else self.get_active(); folder,model,checks=self._verify(pointer["model_version"]); sample={"paper_identifier":request.paper,"part_identifier":request.part,"question_text":request.task_context,"marking_scheme_text":request.marking_scheme,"maximum_score":request.maximum_score,"selected_part3_question":request.selected_part3_question,"effective_student_answer":request.effective_student_answer}; prediction=self.runtime.predict_one(folder,sample); normalized=float(prediction["normalized_score"]); raw=normalized*request.maximum_score; clamped=raw<0 or raw>request.maximum_score; raw_clamped=min(request.maximum_score,max(0,raw)); proposed=float((Decimal(str(raw_clamped))*2).quantize(Decimal("1"),rounding=ROUND_HALF_UP)/2); reverse={v:k for k,v in model["category_mapping"].items()}; category=reverse.get(int(prediction["category_id"]));
            if category is None: raise BackendError("unknown_category","Model returned an unknown category ID.")
            if clamped: warnings.append("Raw model score was clamped to the valid mark range.")
            warnings.extend(warning for warning in prediction.get("warnings",[]) if warning not in warnings)
            return CoreAI1InferenceResult(request.request_id,"completed",raw,normalized,proposed,category,prediction.get("category_confidence"),None,pointer["model_version"],checks.get("heads.pt"),model.get("source_dataset_version"),model.get("input_template_version"),request.input_checksum,bool(prediction.get("truncated")),not bool(request.marking_scheme.strip()),warnings,time.perf_counter()-started,prediction.get("device"),clamped,category_probabilities=prediction.get("category_probabilities"),truncation_statistics=prediction.get("truncation_statistics"))
        except BackendError as exc: return CoreAI1InferenceResult(request.request_id,"failed",None,None,None,None,None,None,request.model_version,None,None,None,request.input_checksum,False,not bool(request.marking_scheme),warnings,failure_code=exc.code)
    def infer_attempt(self,requests): return [self.infer(request) for request in sorted(requests,key=lambda r:(r.part,r.request_id))]
