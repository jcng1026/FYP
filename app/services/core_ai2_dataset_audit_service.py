"""Readiness auditing and read-only comparison of Core AI 2 versions."""
from collections import Counter, defaultdict
from pathlib import Path
from app.services.core_ai2_dataset_registry_service import _read_json, inspect_dataset_integrity, sha256_file

def generate_readiness_audit(dataset_folder):
    root=Path(dataset_folder); manifest=_read_json(root/"manifest.json"); stats=_read_json(root/"statistics.json"); split=_read_json(root/"splits/split_plan.json"); validation=_read_json(root/"validation_report.json"); integrity=inspect_dataset_integrity(root)
    missing=sorted(k for k in manifest.get("class_mapping",{}) if not stats.get("count_by_region_type",{}).get(k,0))
    absent={name:classes for name,classes in split.get("missing_classes",{}).items() if name in ("validation","test") and classes}
    checksum_profiles=defaultdict(set)
    for page in manifest.get("pages",[]):
        if page.get("image_checksum"): checksum_profiles[page["image_checksum"]].add(page.get("profile_id"))
    duplicates={k:sorted(v) for k,v in checksum_profiles.items() if len(v)>1}
    actions=[]
    reasons=manifest.get("blocking_readiness_reasons",[])
    if "insufficient_suitable_profiles" in reasons: actions.append("Add more distinct Subject Profiles.")
    for region_type in sorted(stats.get("underrepresented_required_classes",{})): actions.append(f"Add more examples of {region_type}.")
    if validation.get("summary",{}).get("error",0): actions.append("Correct structural validation errors before freezing or training.")
    if stats.get("excluded_region_count",0): actions.append("Review unsupported or intentionally excluded region types.")
    if absent: actions.append("Add profiles that provide classes absent from validation/test splits.")
    return {"dataset_version":manifest.get("dataset_version"),"export_valid":manifest.get("export_valid"),"structural_integrity":integrity["valid"],"training_ready":manifest.get("training_ready"),"frozen":(root/".frozen").is_file(),"split_mode":manifest.get("split_mode"),"suitable_profile_count":stats.get("suitable_profile_count"),"required_minimum_profile_count":manifest.get("export_configuration",{}).get("min_suitable_profiles"),"class_counts":stats.get("count_by_region_type",{}),"required_minimum_count_per_class":manifest.get("export_configuration",{}).get("min_class_examples"),"underrepresented_required_classes":stats.get("underrepresented_required_classes",{}),"missing_classes":missing,"split_class_distribution":split.get("class_distribution",{}),"classes_absent_from_validation_test":absent,"duplicate_checksum_groups":duplicates,"unsupported_or_excluded_region_count":stats.get("excluded_region_count",0),"validation_errors":validation.get("summary",{}).get("error",0),"validation_warnings":validation.get("summary",{}).get("warning",0),"blocking_readiness_reasons":reasons,"readiness_warnings":manifest.get("readiness_warnings",[]),"recommended_next_human_actions":actions}

def _regions(manifest): return {str(r.get("region_id")):{**r,"profile_id":p.get("profile_id")} for p in manifest.get("pages",[]) for r in p.get("regions",[])}
def _pages(manifest): return {str(p.get("page_id")):p for p in manifest.get("pages",[])}

def compare_dataset_versions(left_folder,right_folder):
    left=Path(left_folder); right=Path(right_folder); lm=_read_json(left/"manifest.json"); rm=_read_json(right/"manifest.json"); ls=_read_json(left/"statistics.json"); rs=_read_json(right/"statistics.json"); lv=_read_json(left/"validation_report.json"); rv=_read_json(right/"validation_report.json"); lc=_read_json(left/"checksums.json"); rc=_read_json(right/"checksums.json")
    lp=set(map(str,lm.get("source_profile_identifiers",[]))); rp=set(map(str,rm.get("source_profile_identifiers",[]))); lpages=_pages(lm); rpages=_pages(rm); lr=_regions(lm); rr=_regions(rm)
    common=set(lr)&set(rr); geometry=[]; labels=[]
    for rid in sorted(common):
        if lr[rid].get("original_geometry")!=rr[rid].get("original_geometry"): geometry.append(rid)
        if (lr[rid].get("region_label"),lr[rid].get("region_type"))!=(rr[rid].get("region_label"),rr[rid].get("region_type")): labels.append(rid)
    classes=sorted(set(ls.get("count_by_region_type",{}))|set(rs.get("count_by_region_type",{})))
    image_changes=[pid for pid in sorted(set(lpages)&set(rpages)) if lpages[pid].get("image_checksum")!=rpages[pid].get("image_checksum")]
    return {"left_version":lm.get("dataset_version"),"right_version":rm.get("dataset_version"),"added_profiles":sorted(rp-lp),"removed_profiles":sorted(lp-rp),"added_pages":sorted(set(rpages)-set(lpages)),"removed_pages":sorted(set(lpages)-set(rpages)),"added_regions":sorted(set(rr)-set(lr)),"removed_regions":sorted(set(lr)-set(rr)),"class_count_changes":{c:rs.get("count_by_region_type",{}).get(c,0)-ls.get("count_by_region_type",{}).get(c,0) for c in classes},"validation_error_change":rv.get("summary",{}).get("error",0)-lv.get("summary",{}).get("error",0),"warning_count_change":rv.get("summary",{}).get("warning",0)-lv.get("summary",{}).get("warning",0),"readiness_change":{"from":lm.get("training_ready"),"to":rm.get("training_ready")},"split_mode_change":{"from":lm.get("split_mode"),"to":rm.get("split_mode")},"manifest_checksum_different":lc.get("manifest_checksum")!=rc.get("manifest_checksum"),"class_mapping_compatible":lm.get("class_mapping_version")==rm.get("class_mapping_version") and lm.get("class_mapping")==rm.get("class_mapping"),"source_image_checksum_changes":image_changes,"geometry_changes":geometry,"label_or_type_changes":labels}
