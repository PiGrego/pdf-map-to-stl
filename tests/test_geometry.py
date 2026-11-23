import math

import pytest
from pymupdf import Point, Rect

from pdf_map_to_stl.geometry import fill_geometry, flatten_cubic, stroke_geometry, subpaths


def square(x0, y0, x1, y1, ccw=True):
    pts = [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]
    if not ccw:
        pts = pts[::-1]
    return [("l", pts[i], pts[(i + 1) % 4]) for i in range(4)]


def test_rect_item_fills_its_area():
    g = fill_geometry([("re", Rect(0, 0, 10, 5), 1)], even_odd=False)
    assert g.area == pytest.approx(50)


def test_nonzero_opposite_winding_makes_a_hole():
    items = square(0, 0, 10, 10) + square(2, 2, 8, 8, ccw=False)
    assert fill_geometry(items, even_odd=False).area == pytest.approx(64)


def test_nonzero_same_winding_does_not_make_a_hole():
    items = square(0, 0, 10, 10) + square(2, 2, 8, 8)
    assert fill_geometry(items, even_odd=False).area == pytest.approx(100)


def test_even_odd_always_makes_a_hole():
    items = square(0, 0, 10, 10) + square(2, 2, 8, 8)
    assert fill_geometry(items, even_odd=True).area == pytest.approx(64)


def test_stroke_width_is_respected():
    g = stroke_geometry([("l", Point(0, 0), Point(10, 0))], width=2.0, line_cap=0)
    assert g.area == pytest.approx(20)


def test_round_cap_adds_half_discs():
    g = stroke_geometry([("l", Point(0, 0), Point(10, 0))], width=2.0, line_cap=1)
    assert g.area == pytest.approx(20 + math.pi, rel=1e-2)


def test_disjoint_items_split_into_subpaths():
    items = [("l", Point(0, 0), Point(1, 0)), ("l", Point(5, 5), Point(6, 5))]
    assert len(subpaths(items)) == 2


def test_bezier_quarter_circle_stays_on_circle():
    k = 0.5523
    pts = flatten_cubic((1, 0), (1, k), (k, 1), (0, 1))
    radii = [math.hypot(x, y) for x, y in pts]
    assert max(abs(r - 1) for r in radii) < 1e-3
