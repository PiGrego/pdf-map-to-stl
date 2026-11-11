from dataclasses import dataclass
from pathlib import Path
import json
@dataclass(frozen=True)
class V15Config:
    page:int=0; final_width_mm:float=120.; curve_error_mm:float=.005; vertex_filter_mm:float=.001
    raster_validation_dpi:int=1200; uncertainty_threshold:float=.85
    merge_isom_402_into_yellow:bool=True; merge_isom_404_into_yellow:bool=True
    export_forest_white:bool=True; export_road_base:bool=False; thin_feature_gap_mm:float=.08
    target_iou_large_areas:float=.97; target_area_error_percent:float=1.5
    target_mean_border_error_mm:float=.03; target_p95_border_error_mm:float=.10
    @classmethod
    def load(cls,path:Path):return cls(**json.loads(path.read_text()))
