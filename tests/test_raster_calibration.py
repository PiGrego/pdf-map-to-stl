import math
from shapely.geometry import box
from pdf_map_to_stl.raster_grid import grid_from_bounds

BOUNDS=(0.0,0.0,141.89669799804688,104.67208862304688)
POINTS=[
 (0.0,0.0),(141.89669799804688,0.0),(0.0,104.67208862304688),
 (141.89669799804688,104.67208862304688),(70.948348999,52.336044312),
 (14.1896698,10.4672089),(127.7070282,10.4672089),(14.1896698,94.2048798),
 (127.7070282,94.2048798),(47.2988993,69.7813924),(94.5977987,34.8906962)
]

def test_pdf_pixel_roundtrip_three_dpi():
    for dpi in (300,600,1200):
        g=grid_from_bounds(BOUNDS,dpi)
        assert g.width==math.ceil(BOUNDS[2]*dpi/72)
        assert g.height==math.ceil(BOUNDS[3]*dpi/72)
        for p in POINTS:
            q=g.local_to_pdf(*g.pdf_to_local(*p))
            assert abs(q[0]-p[0])<1e-12
            assert abs(q[1]-p[1])<1e-12

def test_dpi_invariant_pdf_location():
    for p in POINTS:
        recovered=[]
        for dpi in (300,600,1200):
            g=grid_from_bounds(BOUNDS,dpi)
            recovered.append(g.local_to_pdf(*g.pdf_to_local(*p)))
        assert max(abs(q[0]-p[0]) for q in recovered)<1e-12
        assert max(abs(q[1]-p[1]) for q in recovered)<1e-12
