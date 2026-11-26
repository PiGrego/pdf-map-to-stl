"""Slopes as terraces (relief.py): bands between contour lines, and lifting the model."""

from pathlib import Path

import pytest
from manifold3d import Manifold
from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM
from shapely.geometry import LineString, box

from pdf_map_to_stl.compose import Classified, MapModel
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.model3d import LIFT_CUT_MM, lift
from pdf_map_to_stl.pipeline import BuildOptions, build
from pdf_map_to_stl.relief import find_relief
from pdf_map_to_stl.scene import PT_TO_MM, Primitive, Scene

MM = 1 / PT_TO_MM


def _stroke(line: LineString) -> Classified:
    p = Primitive(0, "stroke", (207, 117, 24), line.buffer(0.1), 10.0, width_mm=0.26, lines=[line])
    return Classified(p, "contour", "101", "ignore", "contour")


def _slope(*extra) -> MapModel:
    """A 100 x 60 mm window: water at the bottom, contour lines at 20 and 40 mm."""
    window = box(0, 0, 100 * MM, 60 * MM)
    water = Classified(Primitive(0, "fill", (0, 157, 221), box(0, 0, 100 * MM, 8 * MM), 100.0), "water", "301",
                       "terrain", "water")
    lines = [_stroke(LineString([(0, y * MM), (100 * MM, y * MM)])) for y in (20, 40)]
    scene = Scene(Path("synthetic.pdf"), 0, window.bounds, [], {}, window)
    return MapModel(scene, [water, *lines, *extra], {}, {}, "forest")


def _levels(relief) -> list[int]:
    return [lv for _, lv in sorted(relief.bands, key=lambda b: b[0].centroid.y)]


def test_the_ground_rises_away_from_the_water():
    r = find_relief(_slope(), load_config())
    assert _levels(r) == [0, 1, 2] and r.levels == 2


def test_a_slope_tick_says_where_the_ground_falls():
    tick = _stroke(LineString([(50 * MM, 40 * MM), (50 * MM, 41 * MM)]))  # on the 40 mm line, pointing up
    assert _levels(find_relief(_slope(tick), load_config())) == [0, 1, 0]


def test_a_gap_in_a_contour_line_is_closed():
    gap = [_stroke(LineString([(0, 30 * MM), (45 * MM, 30 * MM)])), _stroke(LineString([(52 * MM, 30 * MM), (100 * MM, 30 * MM)]))]
    m = _slope()
    m.items = [m.items[0], *gap]  # one contour line, broken where a path crosses it
    assert _levels(find_relief(m, load_config())) == [0, 1]


def test_without_water_there_is_no_relief():
    m = _slope()
    m.items = m.items[1:]
    r = find_relief(m, load_config())
    assert not r.bands and "water" in r.note


def test_lift_raises_one_side_and_fills_under_it():
    plate = Manifold.cube((100, 60, 2))
    lifted = lift(plate, [(box(0, 30, 100, 60), 0.8)], fill=True)
    assert lifted.bounding_box()[5] == pytest.approx(2.8)
    assert lifted.volume() == pytest.approx(100 * 60 * 2 + 100 * 30 * 0.8, rel=1e-6)
    part = Manifold.cube((10, 10, 1)).translate((0, 40, 1.5))  # a part standing on the lifted side
    assert lift(part, [(box(0, 30, 100, 60), 0.8)], fill=False).bounding_box()[2] == pytest.approx(2.3)
    assert LIFT_CUT_MM < 0.4  # below every recess floor


def test_relief_on_a_flat_map_says_why_it_is_not_shown(tmp_path):
    r = build(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, region_mm=(0, 0, 30, 30),
                           validate=False, overrides=("relief.enabled=true",)))
    assert r["relief"]["levels"] == 0 and r["relief"]["note"]
    assert r["stl"]["genus"] == 0 and r["stl"]["open_edges"] == 0
    assert "PENDENZE" in (tmp_path / "description.txt").read_text(encoding="utf-8")
