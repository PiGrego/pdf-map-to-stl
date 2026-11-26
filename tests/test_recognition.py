"""Recognition on maps drawn unlike the sample: rows of dots, close shades, north lines."""

from pathlib import Path

import pymupdf
from shapely.geometry import LineString, box

from pdf_map_to_stl.compose import classify
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.scene import PT_TO_MM, Primitive, Scene, load_scene


def _pdf(tmp_path, content: str):
    """A one-page PDF whose page content is ``content`` (PDF drawing operators)."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, content.encode("ascii"))
    page.set_contents(xref)
    path = tmp_path / "dots.pdf"
    doc.save(path)
    return path


def _dots(scene):
    return [p for p in scene.primitives if p.kind == "dots"]


def test_a_row_of_dots_in_a_page_wide_clip_is_a_row_of_single_dots(tmp_path):
    row = " ".join(f"{20 + 6 * i} 150 2 2 re f" for i in range(20))  # 20 dots, 6 pt apart, in one row
    scene = load_scene(_pdf(tmp_path, f"q 0 0 300 300 re W n 0 0.6 0.3 rg {row} Q"))
    assert not _dots(scene)  # not a dot pattern covering the page
    fills = [p for p in scene.primitives if p.kind == "fill"]
    assert len(fills) == 20 and all(abs(p.geom.area - 4) < 1e-6 for p in fills)  # each dot as drawn (a tree)


def test_a_dot_screen_filled_to_its_outline_keeps_its_outline(tmp_path):
    grid = " ".join(f"{x} {y} 2 2 re f" for x in range(40, 170, 6) for y in range(40, 170, 6))
    scene = load_scene(_pdf(tmp_path, f"q 50 50 100 100 re W n 0 0.6 0.3 rg {grid} Q"))
    (dots,) = _dots(scene)
    assert abs(dots.geom.area - 100 * 100) < 1e-6  # exactly the clip outline, as before


def test_two_close_shades_of_one_class_do_not_block_the_guess():
    cfg = load_config()
    near = cfg.nearest_rule_colour((243, 213, 184))  # between the paved shades, no rule's exact colour
    assert near is not None
    assert cfg.classify(Primitive(0, "fill", (243, 213, 184), box(0, 0, 10, 10), 5.0))[0] == "paved"


def test_white_halos_under_the_course_overprint_are_not_forest(tmp_path):
    # Yellow open land, a white forest patch on it, a black path; then, on top of the map,
    # a white halo and the purple course overprint (as map programs export them).
    # A white patch painted late but with no course symbol on it stays forest (some maps do that).
    content = ("0.996 0.749 0.314 rg 0 0 300 300 re f  1 1 1 rg 50 50 40 40 re f  "
               "0.137 0.122 0.125 RG 1 w 0 150 m 300 150 l S  1 1 1 rg 120 30 30 30 re f  "
               "1 1 1 rg 200 200 20 20 re f  0.925 0 0.549 rg 203 203 14 14 re f")
    items = classify(load_scene(_pdf(tmp_path, content)), load_config())
    whites = sorted((c for c in items if c.prim.rgb == (255, 255, 255)), key=lambda c: c.prim.seqno)
    assert [c.source for c in whites] == ["forest", "forest", "course"]  # only the halo under the course
    assert all(c.role == "ignore" for c in items if c.source == "course")


def _black_stroke(seq: float, line: LineString, width_mm: float = 0.22) -> Primitive:
    x0, y0, x1, y1 = line.bounds
    return Primitive(seq, "stroke", (35, 31, 32), line.buffer(0.3), max(x1 - x0, y1 - y0) * PT_TO_MM,
                     width_mm=width_mm, lines=[line])


def test_a_cross_is_two_strokes_crossing_and_a_lone_dash_is_a_path():
    prims = [_black_stroke(1, LineString([(10, 10), (13, 13)])), _black_stroke(2, LineString([(10, 13), (13, 10)])),
             _black_stroke(3, LineString([(50, 10), (53, 10)]))]  # an X, and a dash of the same size and width
    window = box(0, 0, 100, 100)
    items = classify(Scene(Path("synthetic.pdf"), 0, window.bounds, prims, {}, window), load_config())
    assert [c.source for c in items] == ["man_made_object", "man_made_object", "footpath"]


def test_rough_open_land_and_white_dots_on_yellow_are_open_land():
    cfg = load_config()
    area = box(0, 0, 10, 10)
    assert cfg.classify(Primitive(0, "fill", (255, 209, 131), area, 5.0))[0] == "open_land"  # 403, half yellow
    white_dots = Primitive(0, "dots", (255, 255, 255), area, 5.0, dot_mm=0.66, pitch_mm=0.75)
    assert cfg.classify(white_dots)[0] == "open_land"  # 402 / 404: scattered trees as white dots on yellow


def _blue_stroke(line: LineString, width_mm: float = 0.18) -> Primitive:
    x0, y0, x1, y1 = line.bounds
    return Primitive(0, "stroke", (0, 157, 221), line.buffer(0.3), max(x1 - x0, y1 - y0) * PT_TO_MM,
                     width_mm=width_mm, lines=[line])


def test_a_long_straight_upright_blue_line_is_a_north_line_not_water():
    cfg = load_config()
    assert cfg.classify(_blue_stroke(LineString([(100, 0), (101, 400)])))[0] == "north_line"  # 141 mm, upright
    assert cfg.classify(_blue_stroke(LineString([(0, 0), (100, 400)])))[0] == "water"  # 14 degrees off
    assert cfg.classify(_blue_stroke(LineString([(100, 0), (110, 200), (100, 400)])))[0] == "water"  # bends
    assert cfg.classify(_blue_stroke(LineString([(100, 0), (100, 50)])))[0] == "water"  # 18 mm: a ditch
    assert cfg.classify(_blue_stroke(LineString([(100, 0), (101, 400)]), width_mm=0.5))[0] == "water"  # wide
