"""Atomic, canonical and read-only Core AI 2 dataset exporter."""
import hashlib, json, os, shutil, subprocess, tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
from app.models.core_ai2_dataset_types import (CLASS_MAPPING, CLASS_MAPPING_VERSION,
    DATASET_SCHEMA_VERSION, CANONICAL_REGION_TYPES, ExportConfig)
from app.models.subject_profile_model import SOURCE_ANSWER_SCHEME, SOURCE_QUESTION_PAPER, extract_question_number_from_label
from app.services.region_geometry_service import compute_enclosing_bbox
from app.services.subject_profile_service import (get_document_page_image_paths, list_region_groups,
    list_regions, list_subject_profiles_for_teacher)
from app.services.core_ai2_dataset_validation_service import (assess_dataset_readiness,
    validate_pages, validation_report, validate_portable_manifest_paths)
from app.services.core_ai2_dataset_split_service import plan_splits
from app.services.core_ai2_dataset_visualisation_service import render_overlay

def sha256_file(path):
    digest=hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()

def _commit():
    try: return subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
    except Exception: return None

def collect_source_pages(conn, teacher_id, config=None):
    config=config or ExportConfig(); pages=[]; profiles=[]
    for profile in list_subject_profiles_for_teacher(conn,teacher_id):
        all_regions=list_regions(conn,teacher_id,profile.profile_id); groups=list_region_groups(conn,teacher_id,profile.profile_id)
        group_by_region={row["region_id"]:row["group_id"] for row in conn.execute("SELECT group_id, region_id FROM subject_profile_region_group_members WHERE group_id IN (SELECT group_id FROM subject_profile_region_groups WHERE profile_id=?)",(profile.profile_id,)).fetchall()}
        profile_record={"subject_profile_id":profile.profile_id,"profile_name":profile.profile_name,"source_document_identifier":f"subject-profile-{profile.profile_id}","sources":[]}
        for source,pdf_path in ((SOURCE_QUESTION_PAPER,profile.question_paper_path),(SOURCE_ANSWER_SCHEME,profile.answer_scheme_path)):
            image_paths=get_document_page_image_paths(conn,teacher_id,profile.profile_id,source)
            source_regions=[r for r in all_regions if r.source==source]
            if image_paths or source_regions: profile_record["sources"].append({"source_role":source,"source_pdf_reference":Path(pdf_path).name if pdf_path else None,"page_count":len(image_paths)})
            max_page=max([len(image_paths)]+[r.page_number for r in source_regions])
            for page_number in range(1,max_page+1):
                image_path=image_paths[page_number-1] if page_number<=len(image_paths) else None
                dims=None; checksum=None
                if image_path and Path(image_path).is_file():
                    try:
                        with Image.open(image_path) as im: dims=im.size
                        checksum=sha256_file(image_path)
                    except Exception: pass
                page_id=f"profile-{profile.profile_id}-{source}-page-{page_number}"
                records=[]
                for r in [x for x in source_regions if x.page_number==page_number]:
                    bbox=compute_enclosing_bbox(r); polygon=None
                    try: polygon=json.loads(r.polygon_points_json) if r.polygon_points_json else None
                    except Exception: polygon="invalid"
                    pixel=[round(bbox[0]*dims[0]),round(bbox[1]*dims[1]),round(bbox[2]*dims[0]),round(bbox[3]*dims[1])] if bbox and dims else None
                    excluded=r.region_type not in CANONICAL_REGION_TYPES or (r.region_type=="student_info_area" and not config.include_student_info_area)
                    records.append({"region_id":r.region_id,"region_label":r.label,"region_type":r.region_type,"page_id":page_id,
                        "original_geometry":{"x":r.x,"y":r.y,"width":r.width,"height":r.height,"rotation_angle":r.rotation_angle,"shape_type":r.shape_type,"polygon_points_json":r.polygon_points_json},
                        "normalized_bbox":list(bbox) if bbox else None,"pixel_bbox":pixel,"polygon_points":polygon,
                        "logical_question":{"question_number":extract_question_number_from_label(r.label or "")},"group_id":group_by_region.get(r.region_id),
                        "source_mode":"standard","validation_status":"pending","excluded":excluded,"exclusion_reason":"unsupported_region_type" if excluded and r.region_type not in CANONICAL_REGION_TYPES else ("configuration" if excluded else None),"shape_type":r.shape_type})
                pages.append({"profile_id":profile.profile_id,"page_id":page_id,"page_number":page_number,"source_role":source,"source_image_path":image_path,"image_dimensions":list(dims) if dims else None,"image_checksum":checksum,"regions":records})
        profile_record["page_count"]=sum(s["page_count"] for s in profile_record["sources"]); profiles.append(profile_record)
    return profiles,pages

def build_statistics(profiles,pages,issues,config):
    usable=[r for p in pages for r in p["regions"] if not r["excluded"]]
    by_type=Counter(r["region_type"] for r in usable); by_profile=Counter(str(p["profile_id"]) for p in pages for r in p["regions"] if not r["excluded"]); by_page={p["page_id"]:sum(not r["excluded"] for r in p["regions"]) for p in pages}; by_source=Counter(p["source_role"] for p in pages)
    areas=sorted(r["normalized_bbox"][2]*r["normalized_bbox"][3] for r in usable if r["normalized_bbox"])
    under={c:by_type[c] for c in CANONICAL_REGION_TYPES if by_type[c]<config.min_class_examples}
    suitable={p["profile_id"] for p in pages if p.get("image_checksum") and any(not r["excluded"] for r in p["regions"])}
    source_types=Counter(r["region_type"] for p in pages for r in p["regions"])
    type_audit={typ:{"source_count":count,"disposition":"exported" if typ in CANONICAL_REGION_TYPES else "unsupported",
        "canonical_mapping":CLASS_MAPPING.get(typ),"exclusion_reason":None if typ in CANONICAL_REGION_TYPES else "unsupported_region_type"}
        for typ,count in sorted(source_types.items())}
    if not config.include_student_info_area and "student_info_area" in type_audit:
        type_audit["student_info_area"].update({"disposition":"intentionally_excluded","exclusion_reason":"configuration"})
    return {"profile_count":len(profiles),"suitable_profile_count":len(suitable),"page_count":len(pages),"labelled_page_count":sum(bool(p["regions"]) for p in pages),"region_count":len(usable),"count_by_region_type":dict(by_type),"count_by_profile":dict(by_profile),"count_by_page":by_page,"count_by_source_role":dict(by_source),"actual_region_type_audit":type_audit,"bounding_box_area":{"minimum":areas[0] if areas else None,"median":areas[len(areas)//2] if areas else None,"maximum":areas[-1] if areas else None},"invalid_region_count":len({i.region_id for i in issues if i.level=="error" and i.region_id is not None}),"warning_count":sum(i.level=="warning" for i in issues),"excluded_region_count":sum(r["excluded"] for p in pages for r in p["regions"]),"excluded_reasons":dict(Counter(r["exclusion_reason"] for p in pages for r in p["regions"] if r["excluded"])),"profiles_with_no_usable_regions":[p["subject_profile_id"] for p in profiles if not by_profile[str(p["subject_profile_id"])]],"pages_with_no_usable_regions":[k for k,v in by_page.items() if not v],"underrepresented_classes":under,"underrepresented_required_classes":{c:under[c] for c in config.required_region_types if c in under}}

def export_core_ai2_dataset(conn,teacher_id,output_root,version,config=None):
    config=config or ExportConfig(); output_root=Path(output_root); final=output_root/f"dataset_{version}"
    if final.exists(): raise FileExistsError(f"Dataset version already exists: {final}")
    output_root.mkdir(parents=True,exist_ok=True); temp=Path(tempfile.mkdtemp(prefix=f".dataset_{version}_",dir=output_root))
    try:
        profiles,pages=collect_source_pages(conn,teacher_id,config); issues=validate_pages(pages,config); report=validation_report(issues)
        invalid_ids={i.region_id for i in issues if i.level=="error" and i.region_id is not None}
        for p in pages:
            for r in p["regions"]: r["validation_status"]="error" if r["region_id"] in invalid_ids else "valid"
        split=plan_splits(pages,config.split_ratios,config.split_seed,config.allow_three_profile_split)
        checksums={}
        for p in pages:
            if not p["source_image_path"] or not Path(p["source_image_path"]).is_file(): continue
            image_rel=Path("images")/f"{p['page_id']}{Path(p['source_image_path']).suffix or '.png'}"; label_rel=Path("labels")/f"{p['page_id']}.json"; overlay_rel=Path("overlays")/f"{p['page_id']}.png"
            (temp/image_rel).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p["source_image_path"],temp/image_rel)
            (temp/label_rel).parent.mkdir(parents=True,exist_ok=True); (temp/label_rel).write_text(json.dumps(p["regions"],indent=2),encoding="utf-8")
            render_overlay(p,temp/overlay_rel,invalid_ids); p["image_path"]=image_rel.as_posix(); p["label_path"]=label_rel.as_posix(); p["overlay_path"]=overlay_rel.as_posix(); del p["source_image_path"]
        statistics=build_statistics(profiles,pages,issues,config)
        report=assess_dataset_readiness(report,statistics,split,config)
        readiness={key:report[key] for key in ("export_valid","training_ready","split_mode","blocking_readiness_reasons","readiness_warnings")}
        statistics.update(readiness); split.update(readiness)
        manifest={"dataset_version":version,"schema_version":DATASET_SCHEMA_VERSION,"created_at":datetime.now(timezone.utc).isoformat(),"source_commit":_commit(),"class_mapping":CLASS_MAPPING,"class_mapping_version":CLASS_MAPPING_VERSION,"source_profile_count":len(profiles),"page_count":len(pages),"region_count":statistics["region_count"],"validation_summary":report["summary"],**readiness,"export_configuration":config.to_dict(),"integrity":{"checksums_path":"checksums.json","algorithm":"sha256"},"source_profile_identifiers":[p["subject_profile_id"] for p in profiles],"profiles":profiles,"pages":pages}
        portable_issues=validate_portable_manifest_paths(manifest)
        if portable_issues:
            issues.extend(portable_issues); report=validation_report(issues)
            report=assess_dataset_readiness(report,statistics,split,config)
            readiness={key:report[key] for key in ("export_valid","training_ready","split_mode","blocking_readiness_reasons","readiness_warnings")}
            manifest.update(readiness); manifest["validation_summary"]=report["summary"]
            statistics.update(readiness); split.update(readiness)
        payloads={"class_mapping.json":{"mapping":CLASS_MAPPING,"version":CLASS_MAPPING_VERSION},"validation_report.json":report,"statistics.json":statistics,"splits/split_plan.json":split}
        for rel,data in payloads.items(): (temp/rel).parent.mkdir(parents=True,exist_ok=True); (temp/rel).write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8")
        for profile in profiles:
            path=temp/"profiles"/f"profile-{profile['subject_profile_id']}.json"; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(profile,indent=2,sort_keys=True),encoding="utf-8")
        (temp/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8")
        for file in sorted(x for x in temp.rglob("*") if x.is_file()): checksums[file.relative_to(temp).as_posix()]=sha256_file(file)
        checksums["manifest_checksum"]=checksums["manifest.json"]
        (temp/"checksums.json").write_text(json.dumps(checksums,indent=2,sort_keys=True),encoding="utf-8")
        os.replace(temp,final)
        return {"dataset_folder":str(final),"manifest":manifest,"validation":report,"statistics":statistics,"split_plan":split}
    except Exception:
        shutil.rmtree(temp,ignore_errors=True); raise
