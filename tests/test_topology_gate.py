from shapely.geometry import Polygon, box
from pdf_map_to_stl.topology_analyzer import enclosed_holes, safe_fill_holes

def test_only_true_interior_ring_is_candidate():
    donut=Polygon([(0,0),(10,0),(10,10),(0,10)], [[(2,2),(4,2),(4,4),(2,4)]])
    assert len(enclosed_holes(donut))==1
    assert safe_fill_holes(donut,5).area==100

def test_open_gap_is_not_filled():
    open_shape=box(0,0,2,10).union(box(8,0,10,10))
    assert enclosed_holes(open_shape)==[]
    assert safe_fill_holes(open_shape,100).equals(open_shape)
