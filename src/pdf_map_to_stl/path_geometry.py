import math
from shapely.geometry import Polygon,MultiPolygon,GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
def flat(p0,p1,p2,p3,t=.01):
 n=max(4,min(128,int(max(math.dist(p0,p1)+math.dist(p1,p2)+math.dist(p2,p3),1)/t**.5)));out=[]
 for i in range(n+1):
  u=i/n;v=1-u;out.append((v**3*p0[0]+3*v*v*u*p1[0]+3*v*u*u*p2[0]+u**3*p3[0],v**3*p0[1]+3*v*v*u*p1[1]+3*v*u*u*p2[1]+u**3*p3[1]))
 return out
def parts(g):
 if g.is_empty:return[]
 if isinstance(g,Polygon):return[g]
 if isinstance(g,(MultiPolygon,GeometryCollection)):return[p for x in g.geoms for p in parts(x)]
 return[]
def path_to_geometry(path,fill_rule='nonzero',tolerance_pt=.01):
 rings=[];cur=[];cursor=None;start=None
 for c in path.commands:
  if c.op=='M':
   if len(cur)>=3:rings.append(cur)
   cursor=c.points[0];start=cursor;cur=[cursor]
  elif c.op=='L':cursor=c.points[0];cur.append(cursor)
  elif c.op=='C':
   p1,p2,p3=c.points;cur+=flat(cursor,p1,p2,p3,tolerance_pt)[1:];cursor=p3
  elif c.op=='Z':
   if cur and cur[-1]!=start:cur.append(start)
   if len(cur)>=4:rings.append(cur)
   cur=[];cursor=start=None
 polys=[]
 for r in rings:
  try:polys+=parts(make_valid(Polygon(r)))
  except:pass
 if not polys:return Polygon()
 if fill_rule=='evenodd':
  g=Polygon()
  for p in polys:g=g.symmetric_difference(p)
  return make_valid(g)
 return make_valid(unary_union(polys))
