from pathlib import Path
import json
from .dxf_exporter import polygon_parts
def write_layer_stats(result,out):out.write_text(json.dumps({k:{'area_pt2':g.area,'components':len(polygon_parts(g)),'valid':g.is_valid} for k,g in result.layers.items()},indent=2))
def write_paint_preview(result,crop,out):
 import matplotlib.pyplot as plt
 from matplotlib.patches import Polygon
 colors={'7_AREE_GIALLE':'#ffba36','5_BOSCO_BIANCO':'white','4_AIUOLE_E_SIEPI':'#2db457','2_EDIFICI':'#737373','3_PORTICI':'#d1d3d4','1_MURI_SPESSI':'black'}
 fig,ax=plt.subplots(figsize=(12,9))
 for k,g in result.layers.items():
  for p in polygon_parts(g):ax.add_patch(Polygon(list(p.exterior.coords),facecolor=colors.get(k,'gray'),edgecolor='none'))
 x0,y0,x1,y1=crop.bounds;ax.set(xlim=(x0,x1),ylim=(y1,y0));ax.set_aspect('equal');ax.axis('off');fig.savefig(out,dpi=180);plt.close(fig)
