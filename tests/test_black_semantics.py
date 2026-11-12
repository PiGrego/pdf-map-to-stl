import numpy as np
from shapely.geometry import box
from pdf_map_to_stl.vector_raster_metrics import _draw
from pdf_map_to_stl.raster_grid import grid_from_bounds

def test_wall_support_is_local_not_whole_black_class():
    grid=grid_from_bounds((0,0,10,10),72)
    m=_draw(np.zeros((10,10),np.uint8),box(1,1,3,3),grid,1)
    assert m.sum()>0 and m.sum()<100
