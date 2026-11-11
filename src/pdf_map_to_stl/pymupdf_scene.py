from pathlib import Path
import fitz
from .models import *
def _pt(p):return(float(p.x),float(p.y))
def _rgb(c):return None if c is None else tuple(round(float(x)*255) for x in c[:3])
class PyMuPDFSceneBuilder:
 def __init__(self):self.paths={};self.stats={}
 def build(self,pdf_path:Path,page_number:int):
  doc=fitz.open(pdf_path);page=doc[page_number];ops=[];ds=page.get_drawings()
  for i,d in enumerate(ds):
   cmds=[];last=None
   for it in d.get('items',[]):
    k=it[0]
    if k=='l':
     a,b=_pt(it[1]),_pt(it[2]);
     if last!=a:cmds.append(PathCommand('M',[a]))
     cmds.append(PathCommand('L',[b]));last=b
    elif k=='c':
     p0,p1,p2,p3=map(_pt,it[1:5]);
     if last!=p0:cmds.append(PathCommand('M',[p0]))
     cmds.append(PathCommand('C',[p1,p2,p3]));last=p3
    elif k=='re':
     r=it[1];pts=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1)]
     cmds += [PathCommand('M',[pts[0]])]+[PathCommand('L',[x]) for x in pts[1:]]+[PathCommand('Z',[])];last=None
    elif k=='qu':
     q=it[1];pts=list(map(_pt,[q.ul,q.ur,q.lr,q.ll]));cmds += [PathCommand('M',[pts[0]])]+[PathCommand('L',[x]) for x in pts[1:]]+[PathCommand('Z',[])];last=None
   if d.get('closePath') and cmds and cmds[-1].op!='Z':cmds.append(PathCommand('Z',[]))
   if not cmds:continue
   pid=f'fitz_{i}';r=d.get('rect');bb=(r.x0,r.y0,r.x1,r.y1) if r else None;self.paths[pid]=VectorPath(pid,cmds,bb)
   typ=d.get('type','');op='fill-stroke' if typ=='fs' else ('fill' if 'f' in typ else 'stroke')
   st=GraphicsState(fill_color_rgb=_rgb(d.get('fill')),stroke_color_rgb=_rgb(d.get('color')),stroke_width_pt=float(d.get('width') or 0),fill_rule='evenodd' if d.get('even_odd') else 'nonzero',fill_opacity=float(d.get('fill_opacity') or 1),stroke_opacity=float(d.get('stroke_opacity') or 1))
   ops.append(PaintOperation(int(d.get('seqno',i)),'PyMuPDF',op,pid,st,bb,{}))
  doc.close();ops.sort(key=lambda x:x.sequence);self.stats={'operations':len(ops),'paths':len(self.paths)};return ops
