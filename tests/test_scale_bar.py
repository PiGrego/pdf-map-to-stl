"""The scale bar under the Braille title: a round distance on the ground, to feel distances."""

import pytest
from shapely.geometry import LineString

from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.geo import parse_geo
from pdf_map_to_stl.model3d import EDGE_PAD_MM, NORTH_H_MM, margins, scale_bar, scale_bar_shapes


@pytest.mark.parametrize(("metres_per_mm", "metres", "divisions"), [
    (1.0, 50, 5),  # 1:1000: 50 m is 50 mm, a tick every 10 m
    (1.5, 100, 5),  # 1:1500: 100 m is 66.7 mm, a tick every 20 m
    (0.5, 20, 4),  # 1:500: 20 m is 40 mm, a tick every 5 m
    (5.0, 200, 4),  # 1:5000: 200 m is 40 mm, a tick every 50 m
])
def test_the_bar_is_the_longest_round_distance_that_fits(metres_per_mm, metres, divisions):
    bar = scale_bar(load_config(), 150.0, metres_per_mm)
    assert (bar.metres, bar.divisions) == (metres, divisions)
    assert bar.length_mm == pytest.approx(metres / metres_per_mm)
    assert bar.label == f"{metres} m"


def test_a_narrow_plate_gets_a_shorter_bar_or_none():
    cfg = load_config()
    assert scale_bar(cfg, 60.0, 1.0).metres == 20  # 50 mm and its label do not fit in 60 mm
    assert scale_bar(cfg, 20.0, 1.0) is None
    assert scale_bar(cfg, 150.0, None) is None  # the map's scale is not known


def test_the_bar_fits_beside_the_north_symbol_without_a_taller_plate():
    cfg = load_config()
    with_bar = margins(cfg, 170.0, "navile 1:1000", metres_per_mm=1.0)
    without = margins(cfg, 170.0, "navile 1:1000")
    assert with_bar.bar is not None and without.bar is None and with_bar.bar_where == "top"
    assert with_bar.top == without.top == 2 * EDGE_PAD_MM + NORTH_H_MM


def test_under_a_long_title_the_bar_moves_to_the_bottom_margin():
    cfg = load_config()
    title = "giardini margherita 1:1500"  # two lines of Braille on a 170 mm plate
    longer = margins(cfg, 170.0, title, metres_per_mm=1.5)
    no_bar = margins(cfg, 170.0, title)
    assert len(longer.title_lines) == 2 and longer.bar_where == "bottom"
    assert (longer.top, longer.bottom) == (no_bar.top, no_bar.bottom)  # the bar does not make the plate taller
    # With position points the bottom margin holds their coordinates: the bar stays under the title.
    point = (parse_geo("100,200,44.49,11.35"),)
    with_point = margins(cfg, 170.0, title, point, metres_per_mm=1.5)
    assert with_point.bar_where == "top" and with_point.top > margins(cfg, 170.0, title, point).top


def test_the_ticks_mark_the_ends_and_the_divisions():
    cfg = load_config()
    bar = scale_bar(cfg, 150.0, 1.0)  # 50 m: a tick every 10 m
    shape, dots = scale_bar_shapes(bar, cfg, 5.0, 100.0)
    x0, y0, x1, y1 = shape.bounds
    assert x1 - x0 == pytest.approx(bar.length_mm + cfg.scale_bar.width_mm)  # measured between tick centres
    assert y1 - y0 == pytest.approx(cfg.scale_bar.tick_mm)
    yc = (y0 + y1) / 2
    probe = LineString([(x0 - 1, yc + 1.2), (x1 + 1, yc + 1.2)])  # just above the bar: crosses every tick
    assert len(probe.intersection(shape).geoms) == bar.divisions + 1
    assert dots and min(x for x, _ in dots) > x1  # the Braille label is at the bar's right


def test_the_scale_bar_can_be_switched_off():
    cfg = load_config(None, None, (), ("features.scale_bar=false",))
    assert margins(cfg, 170.0, "navile 1:1000", metres_per_mm=1.0).bar is None
