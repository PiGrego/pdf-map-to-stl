from collections import defaultdict
from dataclasses import dataclass,field
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid
from .path_geometry import path_to_geometry
from .isom_classifier import IsomClassifier
@dataclass
class PaintResult:layers:dict=field(default_factory=dict);surfaces:list=field(default_factory=list);stats:dict=field(default_factory=dict)
class PaintEngine:
 def compose(self,operations,paths,crop_geometry):
  covered=Polygon();d=defaultdict(list);stats=defaultdict(int)
  for op in reversed(operations):
   if op.operation not in ('fill','fill-stroke') or not op.path_id or op.state.fill_opacity<.995:continue
   if op.bbox:
    a,b,c,e=op.bbox;x0,y0,x1,y1=crop_geometry.bounds
    if c<x0 or a>x1 or e<y0 or b>y1:continue
   g=path_to_geometry(paths[op.path_id],op.state.fill_rule,.01).intersection(crop_geometry)
   if g.is_empty:continue
   vis=g.difference(covered);cl=IsomClassifier().classify_rgb(op.state.fill_color_rgb)
   if not vis.is_empty and cl.tactile_layer!='NON_CLASSIFICATO':d[cl.tactile_layer].append(vis);stats['visible_surfaces']+=1
   covered=make_valid(unary_union([covered,g]));stats['opaque_fills_processed']+=1
  return PaintResult({k:make_valid(unary_union(v)) for k,v in d.items()},[],dict(stats))
