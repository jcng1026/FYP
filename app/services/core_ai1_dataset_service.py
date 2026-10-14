"""Immutable Core AI 1 datasets from finalized teacher-reviewed Kertas 2 records."""
import hashlib,json,os,random,shutil,tempfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from app.models.core_ai1_dataset_types import CORE_AI1_DATASET_SCHEMA,CORE_AI1_INPUT_TEMPLATE
from app.models.core_ai_backend_contracts import BackendError
from app.services.core_ai_backend_paths import safe_component
from app.services.core_ai2_dataset_registry_service import sha256_file

SAFE_FIELDS=("paper_identifier","part_identifier","logical_target","selected_part3_question","question_text","marking_scheme_text","maximum_score","effective_student_answer","teacher_final_score","teacher_final_feedback_category","teacher_final_student_feedback","subject_profile_version","attempt_group_id","student_group_id","profile_group_id","source_checksum","finalized_at","source_mode")
def _now(): return datetime.now(timezone.utc).isoformat()
def _atomic_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix=".json_",dir=path.parent); os.close(fd)
    try: Path(name).write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8"); os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)
def _manifest_checksum(folder): return sha256_file(Path(folder)/"manifest.json")

def _prepare(adapter,config):
    included=[]; excluded=[]; seen=set()
    for index,raw in enumerate(adapter.list_finalized_k2_examples()):
        row={key:raw.get(key) for key in SAFE_FIELDS}; reason=None
        if not raw.get("is_finalized"): reason="not_finalized"
        elif str(raw.get("paper_type",raw.get("paper_identifier",""))).lower() in ("kertas1","k1"): reason="not_kertas2"
        elif row["teacher_final_score"] is None: reason="missing_final_score"
        elif not row["teacher_final_feedback_category"]: reason="missing_final_category"
        elif row["teacher_final_feedback_category"] not in config.category_mapping: reason="unknown_category"
        elif not row["marking_scheme_text"]: reason="missing_marking_scheme"
        elif not row["effective_student_answer"]: reason="missing_effective_answer"
        else:
            try:
                score=float(row["teacher_final_score"]); maximum=float(row["maximum_score"])
                if maximum<=0 or score<0 or score>maximum: reason="invalid_score"
            except Exception: reason="invalid_score"
        source=row.get("source_checksum") or hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
        sample_id=hashlib.sha256(f"{source}|{row.get('logical_target')}|{row.get('part_identifier')}".encode()).hexdigest()[:24]
        if sample_id in seen: reason="duplicate_sample"
        if reason: excluded.append({"candidate_index":index,"sample_id":sample_id,"reason":reason}); continue
        seen.add(sample_id); row.update({"sample_id":sample_id,"source_checksum":source,"raw_score":score,"normalized_score":score/maximum,"category_id":config.category_mapping[row["teacher_final_feedback_category"]],"input_template_version":CORE_AI1_INPUT_TEMPLATE})
        included.append(row)
    return sorted(included,key=lambda r:r["sample_id"]),excluded

def _split(samples,config):
    groups=defaultdict(list)
    for sample in samples:
        key="|".join(str(sample.get(k) or "missing") for k in ("student_group_id","attempt_group_id","profile_group_id")); groups[key].append(sample)
    # Duplicate content checksums merge otherwise distinct groups conservatively.
    checksum_group={}; aliases={k:k for k in groups}
    def root(k):
        while aliases[k]!=k: aliases[k]=aliases[aliases[k]]; k=aliases[k]
        return k
    for key,rows in groups.items():
        for row in rows:
            checksum=row["source_checksum"]
            if checksum in checksum_group: aliases[root(key)]=root(checksum_group[checksum])
            else: checksum_group[checksum]=key
    merged=defaultdict(list)
    for key,rows in groups.items(): merged[root(key)].extend(rows)
    keys=sorted(merged); random.Random(config.seed).shuffle(keys)
    if len(keys)<3: return "export_only",{}, {"all":len(samples)},len(keys)
    counts={"train":0,"validation":0,"test":0}; assignments={}; targets=dict(zip(counts,(config.split_ratios[i]*len(samples) for i in range(3))))
    for idx,key in enumerate(keys):
        split=list(counts)[idx] if idx<3 else min(counts,key=lambda name:(counts[name]-targets[name],counts[name],name))
        for row in merged[key]: assignments[row["sample_id"]]=split
        counts[split]+=len(merged[key])
    return "three_way",assignments,counts,len(keys)

def export_core_ai1_dataset(adapter,dataset_root,version,config):
    root=Path(dataset_root); final=root/f"dataset_{safe_component(version)}"
    if final.exists(): raise FileExistsError("Dataset version already exists.")
    root.mkdir(parents=True,exist_ok=True); temp=Path(tempfile.mkdtemp(prefix=f".{version}_",dir=root))
    try:
        samples,excluded=_prepare(adapter,config); mode,assignments,split_counts,group_count=_split(samples,config)
        category_counts=Counter(s["teacher_final_feedback_category"] for s in samples); part_counts=Counter(s["part_identifier"] for s in samples); mode_counts=Counter(s["source_mode"] for s in samples)
        blockers=[]; warnings=[]
        if len(samples)<config.min_samples: blockers.append("insufficient_finalized_samples")
        if group_count<config.min_groups: blockers.append("insufficient_leakage_safe_groups")
        if mode!="three_way": blockers.append("three_way_split_unavailable")
        under={c:category_counts[c] for c in config.category_mapping if category_counts[c]<config.min_examples_per_category}
        if under: blockers.append("underrepresented_feedback_categories")
        missing_parts=[p for p in config.required_parts if not part_counts[p]]
        if missing_parts: blockers.append("missing_required_parts")
        export_valid=bool(samples); training_ready=export_valid and not blockers
        statistics={"candidate_count":len(samples)+len(excluded),"included_count":len(samples),"excluded_count":len(excluded),"exclusions_by_reason":dict(Counter(e["reason"] for e in excluded)),"part_distribution":dict(part_counts),"score_distribution":dict(Counter(str(s["raw_score"]) for s in samples)),"normalized_score_distribution":dict(Counter(f"{s['normalized_score']:.1f}" for s in samples)),"category_distribution":dict(category_counts),"maximum_mark_distribution":dict(Counter(str(s["maximum_score"]) for s in samples)),"source_mode_distribution":dict(mode_counts),"leakage_safe_group_count":group_count,"split_counts":split_counts,"underrepresented_categories":under,"missing_parts":missing_parts,"marking_scheme_coverage":sum(bool(s["marking_scheme_text"]) for s in samples)}
        manifest={"dataset_family":"core_ai1","dataset_version":version,"schema_version":CORE_AI1_DATASET_SCHEMA,"input_template_version":CORE_AI1_INPUT_TEMPLATE,"created_at":_now(),"export_valid":export_valid,"training_ready":training_ready,"frozen":False,"split_mode":mode,"blocking_readiness_reasons":blockers,"readiness_warnings":warnings,"category_mapping_version":config.category_mapping_version,"configuration":config.to_dict(),"sample_count":len(samples),"manifest_checksum_algorithm":"sha256"}
        (temp/"samples.jsonl").write_text("".join(json.dumps(s,sort_keys=True)+"\n" for s in samples),encoding="utf-8"); _atomic_json(temp/"category_mapping.json",{"version":config.category_mapping_version,"mapping":config.category_mapping}); _atomic_json(temp/"statistics.json",statistics); _atomic_json(temp/"exclusions.json",excluded); _atomic_json(temp/"splits.json",{"mode":mode,"assignments":assignments,"counts":split_counts,"seed":config.seed}); _atomic_json(temp/"validation_report.json",{"export_valid":export_valid,"training_ready":training_ready,"errors":[] if export_valid else ["No usable finalized samples."],"warnings":warnings,"blockers":blockers}); _atomic_json(temp/"manifest.json",manifest)
        checks={p.relative_to(temp).as_posix():sha256_file(p) for p in temp.iterdir() if p.is_file()}; checks["manifest_checksum"]=checks["manifest.json"]; _atomic_json(temp/"checksums.json",checks); os.replace(temp,final)
        return {"dataset_folder":str(final),"manifest":manifest,"statistics":statistics}
    except Exception: shutil.rmtree(temp,ignore_errors=True); raise

def inspect_core_ai1_dataset(folder):
    root=Path(folder); errors=[]; required=("manifest.json","samples.jsonl","category_mapping.json","statistics.json","exclusions.json","splits.json","validation_report.json","checksums.json")
    for name in required:
        if not (root/name).is_file(): errors.append(f"missing:{name}")
    if errors: return {"valid":False,"errors":errors,"warnings":[]}
    try:
        checks=json.loads((root/"checksums.json").read_text()); manifest=json.loads((root/"manifest.json").read_text()); samples=[json.loads(line) for line in (root/"samples.jsonl").read_text().splitlines() if line]
        for name,expected in checks.items():
            if name=="manifest_checksum": continue
            if not (root/name).is_file() or sha256_file(root/name)!=expected: errors.append(f"checksum:{name}")
        if checks.get("manifest_checksum")!=sha256_file(root/"manifest.json"): errors.append("manifest_checksum")
        if manifest.get("sample_count")!=len(samples): errors.append("sample_count")
    except Exception as exc: errors.append(f"corrupt:{type(exc).__name__}")
    return {"valid":not errors,"errors":errors,"warnings":[]}

def freeze_core_ai1_dataset(folder,actor=None,note=None):
    root=Path(folder)
    if (root/".frozen").exists() or (root/"freeze_manifest.json").exists(): raise FileExistsError("Dataset already frozen.")
    integrity=inspect_core_ai1_dataset(root); manifest=json.loads((root/"manifest.json").read_text()); checks=json.loads((root/"checksums.json").read_text())
    if not manifest.get("export_valid") or not integrity["valid"]: raise BackendError("dataset_invalid","Export-valid integrity is required for freezing.")
    freeze={"dataset_version":manifest["dataset_version"],"frozen_at":_now(),"frozen_by":actor,"note":note,"training_ready":manifest["training_ready"],"split_mode":manifest["split_mode"],"blockers":manifest["blocking_readiness_reasons"],"source_manifest_checksum":checks["manifest_checksum"],"integrity":integrity,"inventory":[{"path":p.relative_to(root).as_posix(),"sha256":sha256_file(p)} for p in sorted(root.iterdir()) if p.is_file()]}
    _atomic_json(root/"freeze_manifest.json",freeze); (root/".frozen").write_text(freeze["frozen_at"],encoding="utf-8"); return freeze

def discover_core_ai1_datasets(root):
    result=[]
    for folder in sorted(Path(root).glob("dataset_*")):
        if not (folder/"manifest.json").is_file(): continue
        try:
            manifest=json.loads((folder/"manifest.json").read_text()); result.append({**manifest,"folder":folder.name,"integrity_valid":inspect_core_ai1_dataset(folder)["valid"],"frozen":(folder/".frozen").is_file()})
        except Exception: continue
    return result

def audit_core_ai1_dataset(folder):
    root=Path(folder); manifest=json.loads((root/"manifest.json").read_text()); stats=json.loads((root/"statistics.json").read_text()); actions=[]
    if "insufficient_finalized_samples" in manifest["blocking_readiness_reasons"]: actions.append("Add more finalized teacher-reviewed Kertas 2 examples.")
    for category in stats["underrepresented_categories"]: actions.append(f"Add more finalized examples for feedback category {category}.")
    if stats["missing_parts"]: actions.append("Add finalized examples for missing Kertas 2 parts.")
    return {**manifest,"statistics":stats,"integrity":inspect_core_ai1_dataset(root),"recommended_human_actions":actions}

def compare_core_ai1_datasets(left,right):
    def load(folder):
        root=Path(folder); return json.loads((root/"manifest.json").read_text()),{s["sample_id"]:s for s in [json.loads(line) for line in (root/"samples.jsonl").read_text().splitlines() if line]},json.loads((root/"checksums.json").read_text())
    lm,ls,lc=load(left); rm,rs,rc=load(right); common=set(ls)&set(rs)
    return {"left":lm["dataset_version"],"right":rm["dataset_version"],"added_samples":sorted(set(rs)-set(ls)),"removed_samples":sorted(set(ls)-set(rs)),"score_changes":[i for i in common if ls[i]["raw_score"]!=rs[i]["raw_score"]],"category_changes":[i for i in common if ls[i]["teacher_final_feedback_category"]!=rs[i]["teacher_final_feedback_category"]],"source_checksum_changes":[i for i in common if ls[i]["source_checksum"]!=rs[i]["source_checksum"]],"split_mode_change":{"from":lm["split_mode"],"to":rm["split_mode"]},"readiness_change":{"from":lm["training_ready"],"to":rm["training_ready"]},"manifest_checksum_different":lc["manifest_checksum"]!=rc["manifest_checksum"],"mapping_compatible":lm["category_mapping_version"]==rm["category_mapping_version"],"schema_compatible":lm["schema_version"]==rm["schema_version"]}
