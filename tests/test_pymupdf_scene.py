from pathlib import Path
from pdf_map_to_stl.pymupdf_scene import PyMuPDFSceneBuilder

def test_scene_matches_drawings():
    p=Path('samples/sample.pdf')
    if not p.exists():return
    s=PyMuPDFSceneBuilder();ops=s.build(p,0)
    assert len(ops)>90000
    assert min(o.sequence for o in ops)==0
    assert any(o.operation=='fill' for o in ops)
