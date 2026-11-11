from shapely.geometry import box, LineString
from v15_m5.stroke_geometry import collect_strokes
from v15_m5.models import PaintOperation, GraphicsState, VectorPath, PathCommand

def test_raster_support_rejects_unsupported_thin_stroke():
    path=VectorPath('p',[PathCommand('M',[(0,0)]),PathCommand('L',[(10,0)])])
    state=GraphicsState(stroke_color_rgb=(0,0,0),stroke_width_pt=.25)
    op=PaintOperation(0,'test','stroke','p',state)
    g=collect_strokes([op],{'p':path},box(-1,-1,11,1),[(0,0,0)],.25,support=box(20,20,21,21),min_support_ratio=.2)
    assert g.is_empty
