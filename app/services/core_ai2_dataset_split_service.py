"""Deterministic document-level split planning with checksum leakage guards."""
import hashlib, random
from collections import Counter

def plan_splits(pages, ratios=(.7,.15,.15), seed=42, allow_three_profile_split=False):
    if len(ratios)!=3 or any(r<0 for r in ratios) or abs(sum(ratios)-1)>1e-9: raise ValueError("Split ratios must be three non-negative values summing to 1.")
    profiles={p["profile_id"] for p in pages}
    if len(profiles)<3: return {"mode":"export_only","seed":seed,"ratios":list(ratios),"reason":"Fewer than 3 suitable profiles; train/validation/test split unavailable.","assignments":{},"warnings":["Insufficient distinct profiles for leakage-safe splitting."],"class_distribution":{},"missing_classes":{}}
    if len(profiles)==3 and not allow_three_profile_split: return {"mode":"export_only","seed":seed,"ratios":list(ratios),"reason":"Exactly 3 profiles require explicit opt-in.","assignments":{},"warnings":["A one-profile-per-split evaluation would be weak."],"class_distribution":{},"missing_classes":{}}
    # Checksum-connected profiles form indivisible components.
    parent={p:p for p in profiles}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b: parent[b]=a
    by_checksum={}
    for page in pages:
        cs=page.get("image_checksum")
        if cs and cs in by_checksum: union(page["profile_id"],by_checksum[cs])
        elif cs: by_checksum[cs]=page["profile_id"]
    components={}
    for pid in profiles: components.setdefault(find(pid),[]).append(pid)
    groups=list(components.values()); random.Random(seed).shuffle(groups); groups.sort(key=len,reverse=True)
    if len(groups)<3:
        return {"mode":"export_only","seed":seed,"ratios":list(ratios),
                "reason":"Checksum-linked profiles leave fewer than 3 leakage-safe document groups.",
                "assignments":{},"warnings":["Insufficient checksum-independent profile groups for three-way splitting."],
                "class_distribution":{},"missing_classes":{}}
    names=("train","validation","test"); target=[len(profiles)*r for r in ratios]; counts=[0,0,0]; assignments={}
    # Seed every split with one indivisible document group. This is required
    # for the explicit exactly-three-profile case and prevents a nominal
    # three-way plan with an empty validation or test partition.
    for idx,group in enumerate(groups[:3]):
        for pid in group: assignments[str(pid)]=names[idx]
        counts[idx]+=len(group)
    for group in groups[3:]:
        idx=min(range(3),key=lambda i:(counts[i]-target[i],counts[i],i))
        for pid in group: assignments[str(pid)]=names[idx]
        counts[idx]+=len(group)
    distribution={n:Counter() for n in names}
    for page in pages:
        split=assignments[str(page["profile_id"])]
        distribution[split].update(r["region_type"] for r in page.get("regions",[]) if not r.get("excluded"))
    all_classes=sorted(set().union(*(set(v) for v in distribution.values())))
    return {"mode":"three_way","seed":seed,"ratios":list(ratios),"assignments":assignments,
            "warnings":["Exactly three profiles: evaluation will be weak."] if len(profiles)==3 else [],
            "class_distribution":{k:dict(v) for k,v in distribution.items()},
            "missing_classes":{k:[c for c in all_classes if not v[c]] for k,v in distribution.items()},
            "plan_fingerprint":hashlib.sha256(repr(sorted(assignments.items())).encode()).hexdigest()}
