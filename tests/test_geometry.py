from pdf_map_to_stl.models import VectorPath,PathCommand
from pdf_map_to_stl.path_geometry import path_to_geometry

def test_rectangle_geometry():
    p=VectorPath('x',[PathCommand('M',[(0,0)]),PathCommand('L',[(2,0)]),PathCommand('L',[(2,1)]),PathCommand('L',[(0,1)]),PathCommand('Z',[])])
    g=path_to_geometry(p)
    assert abs(g.area-2)<1e-9
