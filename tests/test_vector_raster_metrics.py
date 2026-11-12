import numpy as np
from shapely.geometry import box
from pdf_map_to_stl.vector_raster_metrics import composite_labels,CLASSES

def test_visible_order_green_over_yellow():
    crop=box(0,0,10,10)
    labels=composite_labels({'7_AREE_GIALLE':box(0,0,10,10),'4_AIUOLE_E_SIEPI':box(4,4,6,6)},None,crop,100,100)
    assert labels[50,50]==CLASSES['4_AIUOLE_E_SIEPI']
    assert labels[5,5]==CLASSES['7_AREE_GIALLE']
