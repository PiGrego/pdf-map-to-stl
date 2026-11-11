from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json
import numpy as np
import fitz
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt,binary_erosion
from .dxf_exporter import polygon_parts
from .raster_grid import grid_from_bounds

@dataclass
class LayerMetrics:
    layer:str;iou:float;precision:float;recall:float;missing_percent:float;excess_percent:float;mean_border_error_mm:float;p95_border_error_mm:float

# Same mutually exclusive semantic palette used by the M12 refiner.
CLASS_REFS={
 '7_AREE_GIALLE':[(255,186,54),(254,191,80)],
 '5_BOSCO_BIANCO':[(255,255,255)],
 '8_STRADE_BASE':[(246,218,195),(245,220,196)],
 '2_EDIFICI':[(115,115,115),(138,140,142)],
 '3_PORTICI':[(209,211,212)],
 '4_AIUOLE_E_SIEPI':[(45,180,87),(61,255,23),(143,205,148),(197,228,197),(159,186,0),(180,179,22)],
 '1_MURI_SPESSI':[(0,0,0),(35,31,32)],
 '6_ACQUA_BLU':[(0,157,221),(0,153,204)],
}
TOL={'7_AREE_GIALLE':35,'5_BOSCO_BIANCO':18,'8_STRADE_BASE':30,'2_EDIFICI':34,'3_PORTICI':24,'4_AIUOLE_E_SIEPI':34,'1_MURI_SPESSI':32,'6_ACQUA_BLU':32}

def _mask_geom(g,grid,w,h):
    im=Image.new('1',(w,h),0);d=ImageDraw.Draw(im)
    def xy(coords):return [grid.pdf_to_local(x,y) for x,y in coords]
    for p in polygon_parts(g):
        d.polygon(xy(p.exterior.coords),fill=1)
        for r in p.interiors:d.polygon(xy(r.coords),fill=0)
    return np.array(im,dtype=bool)

def _exclusive_reference(ref):
    names=list(CLASS_REFS)
    a=ref.astype(np.float32)
    ds=[]
    for name in names:
        refs=np.array(CLASS_REFS[name],dtype=np.float32)
        ds.append(np.min(np.linalg.norm(a[:,:,None,:]-refs[None,None,:,:],axis=3),axis=2))
    stack=np.stack(ds,axis=2);winner=np.argmin(stack,axis=2);best=np.min(stack,axis=2)
    return {name:((winner==i)&(best<=TOL[name])) for i,name in enumerate(names)}

class RasterValidator:
    def validate(self,pdf_path,page_number,crop,layers,out_dir:Path,dpi=300,final_width_mm=120.0,wall_reference=None):
        out_dir.mkdir(parents=True,exist_ok=True);doc=fitz.open(pdf_path);p=doc[page_number]
        zoom=dpi/72;pix=p.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False)
        arr=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
        grid=grid_from_bounds(crop.bounds,dpi,arr.shape[1],arr.shape[0])
        ref=arr[grid.iy0:grid.iy1,grid.ix0:grid.ix1];h,w=ref.shape[:2];refs=_exclusive_reference(ref);results=[]
        wall_geom=wall_reference if wall_reference is not None else layers.get('1_MURI_SPESSI')
        if wall_geom is not None and not wall_geom.is_empty and '1_MURI_SPESSI' in refs:
            support=_mask_geom(wall_geom.buffer(0.18),grid,w,h)
            refs['1_MURI_SPESSI'] &= support
        mm_per_pixel=final_width_mm/max(w,1)
        for layer,g in layers.items():
            if layer not in refs or h==0 or w==0:continue
            rm=refs[layer];gm=_mask_geom(g,grid,w,h)
            inter=np.logical_and(rm,gm).sum();union=np.logical_or(rm,gm).sum();gp=gm.sum();rp=rm.sum()
            precision=inter/max(gp,1);recall=inter/max(rp,1);iou=inter/max(union,1)
            edge_r=rm ^ binary_erosion(rm);edge_g=gm ^ binary_erosion(gm)
            if edge_r.any() and edge_g.any():
                dt_r=distance_transform_edt(~edge_r);dt_g=distance_transform_edt(~edge_g);vals=np.concatenate([dt_r[edge_g],dt_g[edge_r]])
            else:vals=np.array([0.0])
            results.append(LayerMetrics(layer,float(iou),float(precision),float(recall),100*(rp-inter)/max(rp,1),100*(gp-inter)/max(gp,1),float(vals.mean()*mm_per_pixel),float(np.percentile(vals,95)*mm_per_pixel)))
        (out_dir/'accuracy.json').write_text(json.dumps([asdict(r) for r in results],indent=2),encoding='utf-8');doc.close();return results
