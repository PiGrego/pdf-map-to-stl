from pathlib import Path
import csv
from shapely.geometry import Polygon,MultiPolygon,GeometryCollection
def polygon_parts(g):
 if g is None or g.is_empty:return[]
 if isinstance(g,Polygon):return[g]
 if isinstance(g,(MultiPolygon,GeometryCollection)):return[p for x in g.geoms for p in polygon_parts(x)]
 return[]
def write_dxf(path,layer,loops):
 a=['0','SECTION','2','ENTITIES']
 for pts in loops:
  a+=['0','LWPOLYLINE','8',layer,'90',str(len(pts)),'70','1']
  for x,y in pts:a+=['10',f'{x:.8f}','20',f'{y:.8f}']
 a+=['0','ENDSEC','0','EOF'];path.write_text('\n'.join(a)+'\n',encoding='ascii')
class DxfPolylineExporter:
 def export(self,layers,out_dir,crop,final_width_mm,vertex_filter_mm=.001):
  out_dir.mkdir(parents=True,exist_ok=True);x0,y0,x1,y1=crop.bounds;s=final_width_mm/(x1-x0);rows=[]
  for layer,g in layers.items():
   loops=[]
   for p in polygon_parts(g):
    for r in [p.exterior,*p.interiors]:
     q=[((x-x0)*s,(y1-y)*s) for x,y in r.coords][:-1]
     if len(q)>=3:loops.append(q)
   if loops:write_dxf(out_dir/f'{layer}.dxf',layer,loops);rows.append((layer,len(polygon_parts(g)),len(loops),g.area*s*s,g.is_valid))
  with (out_dir/'_REPORT_DXF.csv').open('w',newline='') as f:w=csv.writer(f);w.writerow(['layer','polygons','closed_loops','area_mm2','valid']);w.writerows(rows)
  return rows
