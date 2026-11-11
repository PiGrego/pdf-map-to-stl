from __future__ import annotations
from pathlib import Path
import json
import fitz
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt
from .dxf_exporter import polygon_parts
from .raster_grid import grid_from_bounds

COLORS={
 'BASE':(246,218,195),
 '5_BOSCO_BIANCO':(255,255,255),
 '7_AREE_GIALLE':(254,191,80),
 '8_STRADE_BASE':(246,218,195),
 '4_AIUOLE_E_SIEPI':(45,180,87),
 '3_PORTICI':(209,211,212),
 '2_EDIFICI':(138,140,142),
 '6_ACQUA_BLU':(0,157,221),
 '1_MURI_SPESSI':(35,31,32),
}
ORDER=['7_AREE_GIALLE','5_BOSCO_BIANCO','8_STRADE_BASE','4_AIUOLE_E_SIEPI','3_PORTICI','2_EDIFICI','6_ACQUA_BLU','1_MURI_SPESSI']

def _draw_geom(draw,g,grid,color):
 def xy(coords):return [grid.pdf_to_local(x,y) for x,y in coords]
 for p in polygon_parts(g):
  draw.polygon(xy(p.exterior.coords),fill=color)
  for r in p.interiors:draw.polygon(xy(r.coords),fill=COLORS['BASE'])

def composite_image(layers,crop,w,h,include_roads=None,dpi=None,grid=None):
 im=Image.new('RGB',(w,h),COLORS['BASE']);d=ImageDraw.Draw(im)
 if grid is None:
  dpi=72.0*w/max(crop.bounds[2]-crop.bounds[0],1e-12) if dpi is None else dpi
  grid=grid_from_bounds(crop.bounds,dpi)
 all_layers=dict(layers)
 if include_roads is not None:all_layers['8_STRADE_BASE']=include_roads
 for layer in ORDER:
  g=all_layers.get(layer)
  if g is not None and not g.is_empty:_draw_geom(d,g,grid,COLORS[layer])
 return im

def compare_print(pdf_path,page_number,crop,layers,roads,out_dir:Path,dpi=300):
 out_dir.mkdir(parents=True,exist_ok=True);doc=fitz.open(pdf_path);page=doc[page_number];z=dpi/72
 pix=page.get_pixmap(matrix=fitz.Matrix(z,z),alpha=False)
 full=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
 grid=grid_from_bounds(crop.bounds,dpi,full.shape[1],full.shape[0])
 original=full[grid.iy0:grid.iy1,grid.ix0:grid.ix1]
 recon=np.asarray(composite_image(layers,crop,original.shape[1],original.shape[0],roads,grid=grid))
 # Ignore magenta/orange course overprint and text-like colors not represented tactually.
 refs=np.array(list(COLORS.values()),float)
 od=np.min(np.linalg.norm(original[:,:,None,:].astype(float)-refs[None,None,:,:],axis=3),axis=2)
 valid=od<=55
 err=np.linalg.norm(original.astype(float)-recon.astype(float),axis=2)
 good=(err<=45)&valid;bad=(err>45)&valid
 overlay=original.copy();overlay[bad]=(225,0,50);overlay[good]=(30,190,80)
 side=np.concatenate([original,recon,overlay],axis=1)
 Image.fromarray(side).save(out_dir/'CONFRONTO_STAMPA_ORIGINALE_RICOSTRUITA_ERRORI.png')
 Image.fromarray(recon).save(out_dir/'RICOSTRUZIONE_ORDINE_LAYER.png')
 Image.fromarray(overlay).save(out_dir/'MAPPA_ERRORI_STAMPA.png')
 metrics={'valid_pixels':int(valid.sum()),'matching_pixels':int(good.sum()),'mismatching_pixels':int(bad.sum()),'visible_match_rate':float(good.sum()/max(valid.sum(),1)),'mean_rgb_error_valid':float(err[valid].mean()),'p95_rgb_error_valid':float(np.percentile(err[valid],95))}
 (out_dir/'PRINT_COMPARISON.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8');doc.close();return metrics
