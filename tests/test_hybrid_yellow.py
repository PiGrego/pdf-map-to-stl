from shapely.geometry import box
from v15_m5.tactile_composer import TactileComposer

def test_vector_confirmed_yellow_is_recovered():
    visible={'7_AREE_GIALLE':box(0,0,2,2),'8_STRADE_BASE':box(10,10,11,11)}
    raster={'yellow':box(3,0,5,2),'white':box(20,20,21,21),'beige':box(10,10,11,11)}
    out=TactileComposer().compose(visible,box(0,0,30,30),raster).layers['7_AREE_GIALLE']
    assert out.covers(box(0,0,2,2)) and out.covers(box(3,0,5,2))
