from dataclasses import dataclass,field,asdict
from typing import Any
@dataclass
class GraphicsState:
 ctm:tuple=(1,0,0,1,0,0);fill_color_rgb:tuple|None=None;stroke_color_rgb:tuple|None=None;stroke_width_pt:float=1.;fill_rule:str='nonzero';line_join:int=0;line_cap:int=0;dash_pattern:tuple=((),0.);fill_opacity:float=1.;stroke_opacity:float=1.;clipping_ids:list=field(default_factory=list)
@dataclass
class PathCommand:op:str;points:list
@dataclass
class VectorPath:path_id:str;commands:list;bbox:tuple|None=None
@dataclass
class PaintOperation:
 sequence:int;source:str;operation:str;path_id:str|None;state:GraphicsState;bbox:tuple|None=None;metadata:dict=field(default_factory=dict)
 def to_dict(self):return asdict(self)
