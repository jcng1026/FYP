"""Atomic COCO and YOLO derivation from canonical Core AI 2 datasets."""
import json, os, shutil, tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from app.services.core_ai2_dataset_registry_service import (_read_json, _safe_path,
    inspect_dataset_integrity, sha256_file)
from app.services.core_ai_backend_paths import safe_component

def _now(): return datetime.now(timezone.utc).isoformat()

def _source(dataset_folder):
    root=Path(dataset_folder); integrity=inspect_dataset_integrity(root)
    if not integrity["valid"]: raise ValueError("Source dataset integrity inspection failed.")
    manifest=_read_json(root/"manifest.json"); checksums=_read_json(root/"checksums.json"); split=_read_json(root/"splits/split_plan.json")
    if not manifest.get("export_valid"): raise ValueError("Source dataset is not export-valid.")
    return root,manifest,checksums,split

def _start(root,fmt,version):
    version=safe_component(version,"conversion version")
    parent=root/"formats"/fmt; final=parent/version
    if final.exists(): raise FileExistsError("Conversion version already exists.")
    parent.mkdir(parents=True,exist_ok=True)
    return final,Path(tempfile.mkdtemp(prefix=f".{version}_",dir=parent))

def _publish(temp,final,metadata):
    files={p.relative_to(temp).as_posix():sha256_file(p) for p in sorted(temp.rglob("*")) if p.is_file()}
    metadata["file_checksums"]=files
    (temp/"conversion_manifest.json").write_text(json.dumps(metadata,indent=2,sort_keys=True),encoding="utf-8")
    os.replace(temp,final); return {"conversion_folder":str(final),"conversion_manifest":metadata}

def _split_for(page,split):
    return "all" if split.get("mode")=="export_only" else split.get("assignments",{}).get(str(page.get("profile_id")))

def _valid_regions(page):
    return [r for r in page.get("regions",[]) if not r.get("excluded") and r.get("validation_status")!="error"]

def convert_to_coco(dataset_folder,conversion_version):
    root,manifest,checksums,split=_source(dataset_folder); final,temp=_start(root,"coco",conversion_version)
    try:
        categories=[{"id":cid,"name":name,"supercategory":"answer_region"} for name,cid in sorted(manifest["class_mapping"].items(),key=lambda item:item[1])]
        names=("all",) if split.get("mode")=="export_only" else ("train","validation","test")
        docs={name:{"info":{"dataset_version":manifest.get("dataset_version"),"split":name},"images":[],"annotations":[],"categories":categories} for name in names}
        class_counts=Counter(); split_counts=Counter(); excluded=0; annotation_id=0
        for image_id,page in enumerate(sorted(manifest.get("pages",[]),key=lambda p:p["page_id"]),start=1):
            split_name=_split_for(page,split)
            if split_name not in docs: raise ValueError("Page has no valid split assignment.")
            source=_safe_path(root,page["image_path"]); suffix=source.suffix or ".png"; filename=f"{page['page_id']}{suffix}"
            destination=temp/"images"/filename; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,destination)
            width,height=page["image_dimensions"]; docs[split_name]["images"].append({"id":image_id,"file_name":f"images/{filename}","width":width,"height":height,"profile_id":page["profile_id"],"page_id":page["page_id"]}); split_counts[split_name]+=1
            valid=_valid_regions(page); excluded+=len(page.get("regions",[]))-len(valid)
            for region in sorted(valid,key=lambda r:r["region_id"]):
                annotation_id+=1; x,y,w,h=region["pixel_bbox"]; polygon=region.get("polygon_points")
                segmentation=[]
                if isinstance(polygon,list) and len(polygon)>=3: segmentation=[[coord for point in polygon for coord in (point[0]*width,point[1]*height)]]
                cid=manifest["class_mapping"][region["region_type"]]; class_counts[region["region_type"]]+=1
                docs[split_name]["annotations"].append({"id":annotation_id,"image_id":image_id,"category_id":cid,"bbox":[x,y,w,h],"area":w*h,"segmentation":segmentation,"iscrowd":0,"region_id":region["region_id"],"profile_id":page["profile_id"]})
        annotations=temp/"annotations"; annotations.mkdir(parents=True,exist_ok=True)
        for name,document in docs.items(): (annotations/f"instances_{name}.json").write_text(json.dumps(document,indent=2,sort_keys=True),encoding="utf-8")
        metadata={"conversion_version":conversion_version,"source_dataset_version":manifest.get("dataset_version"),"source_manifest_checksum":checksums.get("manifest_checksum"),"source_frozen_state":(root/".frozen").is_file(),"source_page_ids":[p["page_id"] for p in manifest.get("pages",[])],"created_at":_now(),"format":"coco","split_mode":split.get("mode"),"image_count":sum(split_counts.values()),"annotation_count":sum(class_counts.values()),"class_counts":dict(class_counts),"split_counts":dict(split_counts),"excluded_count":excluded,"warnings":[]}
        return _publish(temp,final,metadata)
    except Exception:
        shutil.rmtree(temp,ignore_errors=True); raise

def convert_to_yolo(dataset_folder,conversion_version):
    root,manifest,checksums,split=_source(dataset_folder); final,temp=_start(root,"yolo",conversion_version)
    try:
        names=("all",) if split.get("mode")=="export_only" else ("train","validation","test")
        class_counts=Counter(); split_counts=Counter(); excluded=0
        records=[]
        for page in sorted(manifest.get("pages",[]),key=lambda p:p["page_id"]):
            split_name=_split_for(page,split)
            if split_name not in names: raise ValueError("Page has no valid split assignment.")
            source=_safe_path(root,page["image_path"]); suffix=source.suffix or ".png"; filename=f"{page['page_id']}{suffix}"
            image_rel=Path("images")/split_name/filename; label_rel=Path("labels")/split_name/f"{page['page_id']}.txt"
            (temp/image_rel).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,temp/image_rel)
            lines=[]; valid=_valid_regions(page); excluded+=len(page.get("regions",[]))-len(valid)
            for region in sorted(valid,key=lambda r:r["region_id"]):
                x,y,w,h=region["normalized_bbox"]; cx=x+w/2; cy=y+h/2
                if not all(0<=value<=1 for value in (cx,cy,w,h)): raise ValueError("YOLO coordinates must remain within 0-1.")
                cid=manifest["class_mapping"][region["region_type"]]; lines.append(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"); class_counts[region["region_type"]]+=1
            (temp/label_rel).parent.mkdir(parents=True,exist_ok=True); (temp/label_rel).write_text(("\n".join(lines)+"\n") if lines else "",encoding="utf-8")
            records.append({"page_id":page["page_id"],"profile_id":page["profile_id"],"split":split_name,"image_path":image_rel.as_posix(),"label_path":label_rel.as_posix()}); split_counts[split_name]+=1
        mapping=sorted(manifest["class_mapping"].items(),key=lambda item:item[1]); yaml=["path: ."]
        for name in names: yaml.append(f"{name}: images/{name}")
        yaml.extend([f"nc: {len(mapping)}","names:"]+[f"  {cid}: {name}" for name,cid in mapping])
        if split.get("mode")=="export_only": yaml.append("# export-only dataset; no train/validation/test split is claimed")
        (temp/"data.yaml").write_text("\n".join(yaml)+"\n",encoding="utf-8")
        metadata={"conversion_version":conversion_version,"source_dataset_version":manifest.get("dataset_version"),"source_manifest_checksum":checksums.get("manifest_checksum"),"source_frozen_state":(root/".frozen").is_file(),"source_page_ids":[p["page_id"] for p in manifest.get("pages",[])],"created_at":_now(),"format":"yolo","split_mode":split.get("mode"),"image_count":sum(split_counts.values()),"annotation_count":sum(class_counts.values()),"class_counts":dict(class_counts),"split_counts":dict(split_counts),"excluded_count":excluded,"warnings":[],"records":records}
        return _publish(temp,final,metadata)
    except Exception:
        shutil.rmtree(temp,ignore_errors=True); raise
