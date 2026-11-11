from shapely.geometry import LineString,GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
from .path_geometry import flat

def path_lines(path,tolerance=.02):
    lines=[];cur=[];cursor=None
    for cmd in path.commands:
        if cmd.op=='M':
            if len(cur)>=2:lines.append(LineString(cur))
            cursor=cmd.points[0];cur=[cursor]
        elif cmd.op=='L' and cursor is not None:
            cursor=cmd.points[0];cur.append(cursor)
        elif cmd.op=='C' and cursor is not None:
            p1,p2,p3=cmd.points;seg=flat(cursor,p1,p2,p3,tolerance);cur.extend(seg[1:]);cursor=p3
        elif cmd.op=='Z':
            if len(cur)>=2:
                if cur[0]!=cur[-1]:cur.append(cur[0])
                lines.append(LineString(cur))
            cur=[];cursor=None
    if len(cur)>=2:lines.append(LineString(cur))
    return lines

def collect_strokes(operations,paths,crop,color_refs,min_width,max_width=10,tolerance=55,support=None,min_support_ratio=0.0):
    geoms=[]
    for op in operations:
        if op.operation not in ('stroke','fill-stroke') or not op.path_id:continue
        c=op.state.stroke_color_rgb
        if c is None or op.state.stroke_width_pt<min_width or op.state.stroke_width_pt>max_width:continue
        if min(sum((a-b)**2 for a,b in zip(c,r))**.5 for r in color_refs)>tolerance:continue
        for line in path_lines(paths[op.path_id]):
            g=line.buffer(op.state.stroke_width_pt/2,cap_style=op.state.line_cap+1 if op.state.line_cap in (0,1,2) else 2,join_style=2)
            if not g.is_empty:
                g=g.intersection(crop)
                if support is not None and not support.is_empty:
                    ratio=g.intersection(support).area/max(g.area,1e-12)
                    if ratio<min_support_ratio:continue
                geoms.append(g)
    return make_valid(unary_union(geoms)) if geoms else GeometryCollection()
