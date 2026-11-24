"""Windows: the part of the page to convert, a rectangle or a polygon."""

import argparse

import pytest
from sample_map import NAVILE, TEST_WIDTH_MM
from shapely.geometry import Polygon

from pdf_map_to_stl.cli import _window
from pdf_map_to_stl.pipeline import BuildOptions, build
from pdf_map_to_stl.scene import PT_TO_MM, load_scene, window_pt

PAGE = (0.0, 0.0, 595.44, 841.68)  # A4 in points
POLYGON = (75, 192, 118, 195, 116, 224, 95, 226, 72, 212)  # mm from the page's top-left corner


def test_four_numbers_are_a_rectangle_more_are_a_polygon():
    rect = window_pt(PAGE, (10, 20, 30, 40))
    assert rect.area == pytest.approx((20 / PT_TO_MM) ** 2)
    assert rect.area == pytest.approx(rect.envelope.area)
    poly = window_pt(PAGE, (10, 10, 30, 10, 10, 30))  # a right triangle
    assert poly.area == pytest.approx(0.5 * (20 / PT_TO_MM) ** 2)


@pytest.mark.parametrize("bad", [(1, 2, 3), (1, 2, 3, 4, 5), (900, 900, 1000, 1000)])
def test_a_wrong_window_is_an_error(bad):
    with pytest.raises(ValueError):
        window_pt(PAGE, bad)


def test_command_line_reads_both_shapes():
    assert _window("10,20,30,40") == (10, 20, 30, 40)
    assert len(_window("1,2, 3,4, 5,6")) == 6
    with pytest.raises(argparse.ArgumentTypeError):
        _window("1,2,3,4,5")


@pytest.fixture(scope="module")
def polygon_build(tmp_path_factory):
    out = tmp_path_factory.mktemp("polygon")
    return out, build(BuildOptions(NAVILE, out, crop_mm=POLYGON, width_mm=TEST_WIDTH_MM, validate=False))


def test_everything_stays_inside_the_polygon():
    scene = load_scene(NAVILE, crop_mm=POLYGON)
    assert scene.is_polygon
    inside = scene.window.buffer(1e-6)
    assert all(inside.contains(p.geom) for p in scene.primitives)


def test_polygon_map_fills_the_polygon_and_has_an_edge(polygon_build):
    _, r = polygon_build
    assert r["stl"]["genus"] == 0 and r["stl"]["status"].endswith("NoError")
    xs, ys = POLYGON[::2], POLYGON[1::2]
    enlarge = TEST_WIDTH_MM / (max(xs) - min(xs))  # the window's bounding box is the map's width
    polygon_mm2 = Polygon(list(zip(xs, ys))).area * enlarge**2
    terrain = sum(lyr["area_mm2"] for lyr in r["layers"] if lyr["role"] == "terrain")
    assert terrain == pytest.approx(polygon_mm2, rel=5e-3)  # the areas tile the polygon, nothing outside
    assert any(lyr["role"] == "edge" for lyr in r["layers"])
    assert any(p["kind"] == "edge" for p in r["parts"])


def test_description_tells_the_map_has_the_window_shape(polygon_build):
    out, _ = polygon_build
    text = (out / "description.txt").read_text(encoding="utf-8")
    assert "polygon window of 5 points" in text and "raised line runs along its edge" in text


def test_edge_line_can_be_switched_off(tmp_path):
    r = build(BuildOptions(NAVILE, tmp_path, crop_mm=POLYGON, width_mm=TEST_WIDTH_MM, region_mm=(0, 0, 40, 40),
                           validate=False, overrides=("features.window_edge=false",)))
    assert not any(lyr["role"] == "edge" for lyr in r["layers"])
