from dataclasses import dataclass
from shapely.geometry import Polygon
from shapely.validation import make_valid
from .topology_analyzer import safe_fill_holes
@dataclass
class TactileResult:layers:dict;notes:list[str]
class TactileComposer:
 def compose(self,visible_layers,crop,raster_layers=None):
  raster_layers=raster_layers or {}
  road=visible_layers.get('8_STRADE_BASE',Polygon())
  yellow=raster_layers.get('yellow',visible_layers.get('7_AREE_GIALLE',Polygon()))
  white=raster_layers.get('white',Polygon());beige=raster_layers.get('beige',Polygon())
  # Principal visible classes are taken from the final render in M11. This recovers
  # stroke-based walls and vegetation without turning them into yellow/forest holes.
  mapping={
   '2_EDIFICI':'building','3_PORTICI':'canopy','4_AIUOLE_E_SIEPI':'green',
   '1_MURI_SPESSI':'walls_vector','6_ACQUA_BLU':'water'
  }
  out={}
  for layer,key in mapping.items():
   g=raster_layers.get(key,Polygon())
   if g.is_empty:g=visible_layers.get(layer,Polygon())
   if not g.is_empty:out[layer]=make_valid(g)
  # M4: recover vector-confirmed yellow components lost by strict raster-only extraction.
  vector_yellow=visible_layers.get('7_AREE_GIALLE',Polygon())
  yellow_seed=yellow.union(vector_yellow).difference(beige).difference(road)
  # M5 gate: only genuine enclosed holes may be filled. Default 0 keeps geometry unchanged.
  yellow_hybrid=safe_fill_holes(yellow_seed,0.0)
  out['7_AREE_GIALLE']=make_valid(yellow_hybrid)
  # White is a semantic background. Remove every explicit foreground class, but do
  # not perforate yellow with green or black: these are exported as overlying layers.
  foreground=[beige,out['7_AREE_GIALLE']]
  for k in ('2_EDIFICI','3_PORTICI','6_ACQUA_BLU'):
   if k in out:foreground.append(out[k])
  forest=white
  for g in foreground:forest=forest.difference(g)
  out['5_BOSCO_BIANCO']=make_valid(forest)
  return TactileResult(out,[
   'M5: topology gate rejects open-background promotion; M4 hybrid geometry retained.','M4: raster yellow is unioned with vector-confirmed visible yellow before beige/road clipping.',
   'M11: buildings, canopies, green and water recovered from mutually exclusive 600 dpi rendered masks.',
   'M11: walls use black vector strokes width >= 0.45 pt; thin black outlines are excluded.',
   'M11: green and black remain overlay layers and do not perforate yellow or forest.',
   'ISOM 402 and 404 remain assimilated to yellow.'
  ])

