from pathlib import Path
import cv2,fitz,numpy as np
from .pattern_homogenizer import homogenize_patterns, remove_linear_components
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid
class RasterRefiner:
 def __init__(self,pdf,page,crop,dpi=600):
  self.crop=crop;self.z=dpi/72;doc=fitz.open(pdf);p=doc[page];pix=p.get_pixmap(matrix=fitz.Matrix(self.z,self.z),alpha=False);arr=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
  x0,y0,x1,y1=crop.bounds;self.off=(int(x0*self.z),int(y0*self.z));self.arr=arr[self.off[1]:int(np.ceil(y1*self.z)),self.off[0]:int(np.ceil(x1*self.z))];doc.close()
 def mask(self,refs,tol):
  a=self.arr.astype(np.int16);d=np.min(np.stack([np.linalg.norm(a-np.array(r),axis=2) for r in refs]),axis=0);return (d<=tol).astype(np.uint8)
 def vectorize(self,m,min_area_px=10):
  cs,h=cv2.findContours(m,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE);pol=[]
  if h is None:return Polygon()
  h=h[0]
  for i,c in enumerate(cs):
   if h[i][3]!=-1 or cv2.contourArea(c)<min_area_px:continue
   ext=[((x+self.off[0])/self.z,(y+self.off[1])/self.z) for [[x,y]] in c];holes=[];j=h[i][2]
   while j!=-1:
    if cv2.contourArea(cs[j])>=min_area_px:holes.append([((x+self.off[0])/self.z,(y+self.off[1])/self.z) for [[x,y]] in cs[j]])
    j=h[j][0]
   if len(ext)>=3:
    try:pol.append(make_valid(Polygon(ext,holes)))
    except:pass
  return make_valid(unary_union(pol)) if pol else Polygon()
 def layers(self):
  # M11 refined: mutually exclusive nearest-colour classification. Previous
  # independent thresholds allowed one antialiased pixel to enter several layers.
  prototypes={
   'yellow':[(255,186,54),(254,191,80)],
   'white':[(255,255,255)],
   'beige':[(246,218,195),(245,220,196)],
   'building':[(115,115,115),(138,140,142)],
   'canopy':[(209,211,212)],
   'green':[(45,180,87),(61,255,23),(143,205,148),(197,228,197),(159,186,0),(180,179,22)],
   'black':[(0,0,0),(35,31,32)],
   'water':[(0,157,221),(0,153,204)],
  }
  names=list(prototypes)
  a=self.arr.astype(np.float32)
  class_dist=[]
  for name in names:
   refs=np.array(prototypes[name],dtype=np.float32)
   class_dist.append(np.min(np.linalg.norm(a[:,:,None,:]-refs[None,None,:,:],axis=3),axis=2))
  stack=np.stack(class_dist,axis=2)
  winner=np.argmin(stack,axis=2);best=np.min(stack,axis=2)
  tolerances={'yellow':35,'white':18,'beige':30,'building':34,'canopy':24,'green':34,'black':32,'water':32}
  minareas={'yellow':18,'white':18,'beige':18,'building':16,'canopy':16,'green':8,'black':5,'water':5}
  masks={}
  artefacts={}
  for i,name in enumerate(names):
   masks[name]=((winner==i)&(best<=tolerances[name])).astype(np.uint8)
  # Blue and brown straight lines are drafting artefacts, not tactile map areas.
  masks['water'],removed_blue=remove_linear_components(masks['water'],min_elongation=7.0,max_thickness_px=18,min_length_px=70)
  # Brown is intentionally not a tactile class. Detect and record its straight components
  # so they cannot enter a future fallback or nearest-colour extension.
  brown_dist=np.linalg.norm(a-np.array((208,117,24),dtype=np.float32),axis=2)
  _,removed_brown=remove_linear_components((brown_dist<=34).astype(np.uint8),min_elongation=6.0,max_thickness_px=18,min_length_px=55)
  masks['yellow'],pattern_stats=homogenize_patterns(masks['yellow'])
  self.processing_stats={'removed_blue_linear':removed_blue,'removed_brown_linear':removed_brown,**pattern_stats}
  out={name:self.vectorize(masks[name],minareas[name]) for name in names}
  return out
