"""Pure, read-only validation for canonical Core AI 2 page records."""
import math
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image
from app.models.core_ai2_dataset_types import CANONICAL_REGION_TYPES, ExportConfig, ValidationIssue

def bbox_iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix=max(ax,bx); iy=max(ay,by); ir=min(ax+aw,bx+bw); ib=min(ay+ah,by+bh)
    inter=max(0,ir-ix)*max(0,ib-iy)
    union=aw*ah+bw*bh-inter
    return inter/union if union > 0 else 0.0

def _issue(code, level, message, page, region=None, **details):
    return ValidationIssue(code, level, message, page.get("profile_id"), page.get("page_id"),
                           region.get("region_id") if region else None, details)

def validate_pages(pages, config=None):
    config = config or ExportConfig(); issues=[]; class_counts=Counter(); checksums=defaultdict(list)
    for page in pages:
        path=Path(page.get("source_image_path") or "")
        actual=None
        if not page.get("source_image_path"):
            issues.append(_issue("page_reference_not_found","error","Region page has no source-image reference.",page))
        if not path.is_file(): issues.append(_issue("missing_page_image","error","Page image does not exist.",page))
        else:
            try:
                with Image.open(path) as im: actual=im.size; im.verify()
            except Exception as exc: issues.append(_issue("page_image_unreadable","error","Page image is unreadable.",page,error=str(exc)))
        if actual and tuple(page.get("image_dimensions") or actual) != actual:
            issues.append(_issue("image_dimension_mismatch","error","Recorded and actual image dimensions differ.",page,recorded=page.get("image_dimensions"),actual=list(actual)))
        if page.get("image_checksum"): checksums[page["image_checksum"]].append(page["page_id"])
        regions=page.get("regions",[])
        if not regions: issues.append(_issue("page_no_exported_labels","warning","Page has no exported labels.",page))
        seen=[]; labels=defaultdict(list)
        for r in regions:
            label=(r.get("region_label") or "").strip(); typ=r.get("region_type"); box=r.get("normalized_bbox")
            if not label: issues.append(_issue("missing_region_label","error","Region label is missing.",page,r))
            else: labels[label].append(r)
            if not typ: issues.append(_issue("missing_region_type","error","Region type is missing.",page,r))
            elif typ not in CANONICAL_REGION_TYPES:
                level="warning" if r.get("excluded") and r.get("exclusion_reason")=="unsupported_region_type" else "error"
                issues.append(_issue("unsupported_region_type",level,"Region type is unsupported and explicitly excluded." if level=="warning" else "Region type is unsupported.",page,r,region_type=typ))
            else: class_counts[typ]+=1
            if not box or len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):
                issues.append(_issue("empty_region","error","Region geometry is empty or invalid.",page,r)); continue
            x,y,w,h=box
            if w<=0 or h<=0: issues.append(_issue("zero_area_region","error","Region has zero or negative area.",page,r))
            if min(x,y,w,h)<0: issues.append(_issue("negative_coordinates","error","Region has negative coordinates.",page,r))
            if x+w>1 or y+h>1: issues.append(_issue("out_of_bounds_coordinates","error","Region extends beyond page bounds.",page,r))
            if w*h>config.large_region_area: issues.append(_issue("region_larger_than_expected","warning","Region covers an unusually large page area.",page,r,area=w*h))
            polygon=r.get("polygon_points")
            if r.get("shape_type")=="polygon" and (not isinstance(polygon,list) or len(polygon)<3 or any(not isinstance(p,(list,tuple)) or len(p)!=2 for p in polygon)):
                issues.append(_issue("invalid_polygon","error","Polygon must contain at least three valid points.",page,r))
            for prior in seen:
                pb=prior.get("normalized_bbox")
                if not pb: continue
                if list(box)==list(pb): issues.append(_issue("exact_duplicate_geometry","error","Exact duplicate region geometry.",page,r,other_region_id=prior.get("region_id")))
                else:
                    overlap=bbox_iou(box,pb)
                    if overlap>=config.near_duplicate_iou: issues.append(_issue("near_duplicate_geometry","warning","Near-duplicate region geometry.",page,r,other_region_id=prior.get("region_id"),iou=overlap))
                    elif overlap>=config.suspicious_overlap_iou: issues.append(_issue("suspicious_overlap","warning","Regions overlap suspiciously.",page,r,other_region_id=prior.get("region_id"),iou=overlap))
            seen.append(r)
        for label, same in labels.items():
            if len(same)>1: issues.append(_issue("duplicate_label_same_page","warning","Duplicate label on the same page.",page,same[-1],label=label,count=len(same)))
    for checksum, ids in checksums.items():
        if len(ids)>1: issues.append(ValidationIssue("duplicate_source_checksum","error","Duplicate page image checksum.",details={"checksum":checksum,"page_ids":ids}))
    profiles={p["profile_id"] for p in pages}
    for pid in profiles:
        if not any(p["profile_id"]==pid and p.get("regions") for p in pages): issues.append(ValidationIssue("profile_no_usable_pages","error","Profile has no usable pages.",profile_id=pid))
    for typ in CANONICAL_REGION_TYPES:
        if class_counts[typ] < config.min_class_examples: issues.append(ValidationIssue("class_too_few_examples","warning","Class has too few examples.",details={"region_type":typ,"count":class_counts[typ],"minimum":config.min_class_examples}))
    return issues

def validate_portable_manifest_paths(manifest):
    """Detect non-portable paths after manifest assembly; never rewrites them."""
    issues=[]
    for page in manifest.get("pages",[]):
        for key in ("image_path","label_path","overlay_path"):
            value=page.get(key)
            if value and (Path(value).is_absolute() or ":" in Path(value).drive):
                issues.append(ValidationIssue("non_portable_absolute_path","error",
                    "Exported manifest contains an absolute path.",page.get("profile_id"),page.get("page_id"),details={"field":key}))
    return issues

def validation_report(issues):
    counts=Counter(i.level for i in issues)
    export_valid=counts["error"]==0
    return {"export_valid":export_valid, "training_ready":False, "split_mode":None,
            "blocking_readiness_reasons":[] if export_valid else ["structural_validation_errors"],
            "readiness_warnings":[],
            "summary":{"error":counts["error"],"warning":counts["warning"],"information":counts["information"]},
            "issues":[i.to_dict() for i in issues]}

def assess_dataset_readiness(report, statistics, split_plan, config):
    """Separate canonical export validity from production training readiness."""
    reasons=list(report.get("blocking_readiness_reasons",[])); warnings=list(split_plan.get("warnings",[]))
    suitable=statistics.get("suitable_profile_count",0)
    if suitable < config.min_suitable_profiles:
        reasons.append("insufficient_suitable_profiles")
    if split_plan.get("mode") != "three_way":
        reasons.append("leakage_safe_train_validation_test_split_unavailable")
    if suitable == 3 and split_plan.get("mode") == "three_way":
        reasons.append("three_profile_split_not_production_evaluation_ready")
        warnings.append("Exactly three profiles: one profile per split is technically generated but evaluation is weak and not production-ready.")
    under=statistics.get("underrepresented_required_classes",{})
    if under:
        reasons.append("required_region_classes_below_minimum")
        warnings.append("Required region classes do not meet configured minimum example counts.")
    reasons=list(dict.fromkeys(reasons)); warnings=list(dict.fromkeys(warnings))
    report.update({"export_valid":report.get("summary",{}).get("error",0)==0,
                   "training_ready":not reasons,
                   "split_mode":split_plan.get("mode"),
                   "blocking_readiness_reasons":reasons,
                   "readiness_warnings":warnings})
    return report
