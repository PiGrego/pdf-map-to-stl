import argparse,json,csv,os,hashlib
from pathlib import Path
import fitz
from shapely.geometry import box
from .crop_selector import select_crop,load_crop,save_crop
from .print_comparator import compare_print
from .config import V15Config
from .pymupdf_scene import PyMuPDFSceneBuilder
from .paint_engine import PaintEngine
from .raster_refiner import RasterRefiner
from .tactile_composer import TactileComposer
from .dxf_exporter import DxfPolylineExporter
from .raster_validator import RasterValidator
from .diagnostics import write_paint_preview
from .stroke_geometry import collect_strokes
from .vector_raster_metrics import evaluate as evaluate_vector_raster

def main():
 p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);p.add_argument('--config',type=Path,default=Path('config/config_v15.json'));p.add_argument('--output',type=Path,default=Path('output'));g=p.add_mutually_exclusive_group();g.add_argument('--full-page',action='store_true');g.add_argument('--crop',type=Path);a=p.parse_args();cfg=V15Config.load(a.config);a.output.mkdir(parents=True,exist_ok=True)
 doc=fitz.open(a.pdf);page=doc[cfg.page];crop=load_crop(a.crop) if a.crop else select_crop(page,a.full_page);save_crop(a.output/'ultimo_ritaglio.json',a.pdf,cfg.page,crop);doc.close()
 scene=PyMuPDFSceneBuilder();ops=scene.build(a.pdf,cfg.page);paint=PaintEngine().compose(ops,scene.paths,crop)
 rr=RasterRefiner(a.pdf,cfg.page,crop,dpi=600);rl=rr.layers();wall_min_width=float(os.environ.get('V15_WALL_MIN_WIDTH_PT','0.45')); wall_support_ratio=float(os.environ.get('V15_WALL_SUPPORT_RATIO','0.20')); wall_support=rl.get('black').buffer(0.12) if wall_min_width<0.45 and rl.get('black') is not None else None; rl['walls_vector']=collect_strokes(ops,scene.paths,crop,[(35,31,32),(0,0,0)],wall_min_width,tolerance=42,support=wall_support,min_support_ratio=wall_support_ratio)
 tactile=TactileComposer().compose(paint.layers,crop,raster_layers=rl)
 dxf_rows=DxfPolylineExporter().export(tactile.layers,a.output/'DXF_PRODUZIONE',crop,cfg.final_width_mm,cfg.vertex_filter_mm)
 metrics=RasterValidator().validate(a.pdf,cfg.page,crop,tactile.layers,a.output/'VALIDATION',dpi=300,final_width_mm=cfg.final_width_mm,wall_reference=rl['walls_vector'])
 print_metrics=compare_print(a.pdf,cfg.page,crop,tactile.layers,rl.get('beige'),a.output/'PRINT_COMPARISON',dpi=300)
 vr_global,vr_classes=evaluate_vector_raster(a.pdf,cfg.page,crop,tactile.layers,rl.get('beige'),a.output/'VECTOR_RASTER_METRICS',dpi=600,final_width_mm=cfg.final_width_mm,wall_reference=rl['walls_vector'])
 write_paint_preview(type('R',(),{'layers':tactile.layers})(),crop,a.output/'FINAL_preview.png')
 rp=getattr(rr,'processing_stats',{})
 with (a.output/'ARTEFATTI_RIMOSSI.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.writer(f);w.writerow(['tipo','component','area_px','bbox_px','length_px','thickness_px','elongation','angle_deg','fill_ratio'])
  for typ,key in [('azzurro','removed_blue_linear'),('marrone','removed_brown_linear')]:
   for r in rp.get(key,[]):w.writerow([typ,r.get('component'),r.get('area_px'),r.get('bbox_px'),r.get('length_px'),r.get('thickness_px'),r.get('elongation'),r.get('angle_deg'),r.get('fill_ratio')])
 with (a.output/'PATTERN_OMOGENEIZZATI.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.writer(f);w.writerow(['white_dots_filled','yellow_dot_regions_solidified','white_spacing_px','yellow_spacing_px']);w.writerow([rp.get('white_dots_filled',0),rp.get('yellow_dot_regions_solidified',0),rp.get('white_pattern',{}).get('spacing_px'),rp.get('yellow_pattern',{}).get('spacing_px')])
 manifest={'version':'V15_M5_TOPOLOGY_GATE','wall_min_width_pt':wall_min_width,'wall_support_ratio':wall_support_ratio,'scene':scene.stats,'raster_processing':rp,'notes':tactile.notes,'metrics':[x.__dict__ for x in metrics],'dxf_layers':len(dxf_rows),'print_comparison':print_metrics,'vector_raster_metrics':vr_global}
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
