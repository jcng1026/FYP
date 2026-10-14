from dataclasses import dataclass,field
from typing import Dict,Tuple

CORE_AI1_DATASET_SCHEMA="core-ai1-k2-reviewed-v1"
CORE_AI1_INPUT_TEMPLATE="core-ai1-input-v1"

@dataclass(frozen=True)
class CoreAI1DatasetConfig:
    category_mapping:Dict[str,int]; category_mapping_version:str
    seed:int=42; split_ratios:Tuple[float,float,float]=(.7,.15,.15)
    min_samples:int=30; min_groups:int=4; min_examples_per_category:int=5
    required_parts:Tuple[str,...]=("part1","part2","part3")
    def to_dict(self): return {"category_mapping":dict(self.category_mapping),"category_mapping_version":self.category_mapping_version,"seed":self.seed,"split_ratios":list(self.split_ratios),"min_samples":self.min_samples,"min_groups":self.min_groups,"min_examples_per_category":self.min_examples_per_category,"required_parts":list(self.required_parts)}
