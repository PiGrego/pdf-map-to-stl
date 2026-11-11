from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import csv,json
import fitz
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import binary_dilation,binary_erosion,distance_transform_edt
from .dxf_exporter import polygon_parts
from .raster_grid import grid_from_bounds

# Visible class ids. Extrusion geometries may overlap; composite order resolves visibility.
CLASSES={
 '7_AREE_GIALLE':1,'5_BOSCO_BIANCO':2,'8_STRADE_BASE':3,
 '4_AIUOLE_E_SIEPI':4,'3_PORTICI':5,'2_EDIFICI':6,
 '6_ACQUA_BLU':7,'1_MURI_SPESSI':8,
}
ORDER=['7_AREE_GIALLE','5_BOSCO_BIANCO','8_STRADE_BASE','4_AIUOLE_E_SIEPI','3_PORTICI','2_EDIFICI','6_ACQUA_BLU','1_MURI_SPESSI']
RGB={
 '7_AREE_GIALLE':[(254,191,80),(255,186,54)],
 '5_BOSCO_BIANCO':[(255,255,255)],
 '8_STRADE_BASE':[(245,220,196),(246,218,195)],
 '4_AIUOLE_E_SIEPI':[(45,180,87),(143,205,148),(197,228,197),(180,179,22),(159,186,0)],
 '3_PORTICI':[(209,211,212)],'2_EDIFICI':[(115,115,115),(138,140,142)],
 '6_ACQUA_BLU':[(0,157,221),(0,153,204)],'1_MURI_SPESSI':[(35,31,32),(0,0,0)]}
EXCLUDED={'brown':[(207,117,24)],'magenta':[(180,29,142)]}

@dataclass
class ClassMetric:
 layer:str;tp:int;fp:int;fn:int;precision:float;recall:float;f1:float;iou:float;missing_percent:float;excess_percent:float;asd_mm:float;hd95_mm:float

def _draw(mask,geom,grid,value):
 im=Image.fromarray(mask);d=ImageDraw.Draw(im)
 def xy(coords):return [grid.pdf_to_local(x,y) for x,y in coords]
 for p in polygon_parts(geom):
  d.polygon(xy(p.exterior.coords),fill=int(value))
  for ring in p.interiors:d.polygon(xy(ring.coords),fill=0)
 return np.asarray(im,dtype=np.uint8)

def composite_labels(layers,roads,crop,w,h,dpi=None,grid=None):
 out=np.zeros((h,w),np.uint8);allg=dict(layers);allg['8_STRADE_BASE']=roads
 if grid is None:
  if dpi is None:
   # Backward-compatible synthetic grid used by unit tests.
   x0,y0,x1,y1=crop.bounds
   dpi=72.0*w/max(x1-x0,1e-12)
  grid=grid_from_bounds(crop.bounds,dpi)
 for layer in ORDER:
  g=allg.get(layer)
  if g is not None and not g.is_empty:out=_draw(out,g,grid,CLASSES[layer])
 return out

def nearest_color_labels(arr):
 names=list(CLASSES);refs=[];owners=[]
 for n in names:
  for rgb in RGB[n]:refs.append(rgb);owners.append(CLASSES[n])
 refs=np.asarray(refs,float);a=arr.astype(float)
 dist=np.linalg.norm(a[:,:,None,:]-refs[None,None,:,:],axis=3);idx=np.argmin(dist,axis=2);best=np.min(dist,axis=2)
 labels=np.asarray(owners,np.uint8)[idx];uncertain=best>42
 # Explicit exclusions.
 excluded=np.zeros(arr.shape[:2],bool)
 for values in EXCLUDED.values():
  d=np.min(np.stack([np.linalg.norm(a-np.asarray(v,float),axis=2) for v in values]),axis=0)
  excluded|=d<=38
 return labels,uncertain,excluded,best

def evaluate(pdf_path,page_number,crop,layers,roads,out_dir:Path,dpi=600,final_width_mm=120.0,wall_reference=None):
 out_dir.mkdir(parents=True,exist_ok=True);z=dpi/72;doc=fitz.open(pdf_path);page=doc[page_number]
 pix=page.get_pixmap(matrix=fitz.Matrix(z,z),alpha=False);full=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
 grid=grid_from_bounds(crop.bounds,dpi,full.shape[1],full.shape[0]);ref_rgb=full[grid.iy0:grid.iy1,grid.ix0:grid.ix1];doc.close()
 h,w=ref_rgb.shape[:2];ref,uncertain,excluded,best=nearest_color_labels(ref_rgb);pred=composite_labels(layers,roads,crop,w,h,grid=grid)
 # M3: black in the printed map is not synonymous with tactile walls.
 # Only black pixels close to vector strokes >= the production width are wall truth;
 # other black pixels (text, thin outlines, symbols) are excluded from tactile scoring.
 wall_geom=wall_reference if wall_reference is not None else layers.get('1_MURI_SPESSI')
 if wall_geom is not None and not wall_geom.is_empty:
  support=_draw(np.zeros((h,w),np.uint8),wall_geom.buffer(0.18),grid,1).astype(bool)
  black=ref==CLASSES['1_MURI_SPESSI']
  thin_black=black & ~support
  excluded |= thin_black
  ref[thin_black]=0
  ref[black & support]=CLASSES['1_MURI_SPESSI']
 # Two-pixel anti-alias band around reference boundaries.
 edge=np.zeros((h,w),bool)
 for cid in CLASSES.values():
  m=ref==cid;edge|=m^binary_erosion(m)
 aa=binary_dilation(edge,iterations=2)&(best>10)
 eval_mask=~(excluded|uncertain|aa)
 match=(ref==pred)&eval_mask
 mm_per_px=final_width_mm/max(w,1)
 metrics=[]
 for layer,cid in CLASSES.items():
  r=(ref==cid)&eval_mask;p=(pred==cid)&eval_mask;tp=int((r&p).sum());fp=int((~r&p).sum());fn=int((r&~p).sum())
  precision=tp/max(tp+fp,1);recall=tp/max(tp+fn,1);f1=2*precision*recall/max(precision+recall,1e-12);iou=tp/max(tp+fp+fn,1)
  er=r^binary_erosion(r);ep=p^binary_erosion(p)
  if er.any() and ep.any():
   dr=distance_transform_edt(~er);dp=distance_transform_edt(~ep);vals=np.concatenate([dr[ep],dp[er]])*mm_per_px;asd=float(vals.mean());hd95=float(np.percentile(vals,95))
  else:asd=hd95=0.0
  metrics.append(ClassMetric(layer,tp,fp,fn,precision,recall,f1,iou,100*fn/max(tp+fn,1),100*fp/max(tp+fp,1),asd,hd95))
 global_metrics={'metric_semantics':'M3 tactile-visible; non-wall black excluded','non_wall_black_fraction':float(thin_black.mean()) if 'thin_black' in locals() else 0.0,'accuracy_visible':float(match.sum()/max(eval_mask.sum(),1)),'evaluated_pixels':int(eval_mask.sum()),'excluded_fraction':float(excluded.mean()),'antialias_fraction':float(aa.mean()),'uncertain_fraction':float(uncertain.mean()),'macro_f1':float(np.mean([m.f1 for m in metrics])),'balanced_accuracy':float(np.mean([m.recall for m in metrics]))}
 (out_dir/'global_metrics.json').write_text(json.dumps(global_metrics,indent=2),encoding='utf-8')
 with (out_dir/'per_class_metrics.csv').open('w',newline='',encoding='utf-8') as f:
  wr=csv.DictWriter(f,fieldnames=asdict(metrics[0]).keys());wr.writeheader();wr.writerows(asdict(m) for m in metrics)
 # Confusion matrix.
 with (out_dir/'confusion_matrix.csv').open('w',newline='',encoding='utf-8') as f:
  wr=csv.writer(f);wr.writerow(['reference','predicted','pixel_count'])
  for rname,rid in [('BACKGROUND',0),*[(k,v) for k,v in CLASSES.items()]]:
   for pname,pid in [('BACKGROUND',0),*[(k,v) for k,v in CLASSES.items()]]:
    n=int(((ref==rid)&(pred==pid)&eval_mask).sum())
    if n:wr.writerow([rname,pname,n])
 # Diagnostic RGB: green match, red mismatch, blue excluded/AA/uncertain.
 diagnostic=np.zeros((h,w,3),np.uint8);diagnostic[match]=(30,190,80);diagnostic[eval_mask&~match]=(225,0,50);diagnostic[~eval_mask]=(40,120,235)
 Image.fromarray(diagnostic).save(out_dir/'confusion_map.png')
 for layer,cid in CLASSES.items():Image.fromarray(((pred==cid)*255).astype(np.uint8)).save(out_dir/f'{layer}.png')
 return global_metrics,metrics
