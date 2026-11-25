"""Inputs and outputs that used to fail silently: STL files that other programs read as
open, tunnels under walls at the water, rotated pages, scanned maps, low agreement, and
rebuilding from settings_used.toml."""

import hashlib

import numpy as np
import pymupdf
import pytest
from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM
from shapely.geometry import box

from pdf_map_to_stl.compose import build_map
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.geo import parse_coordinate
from pdf_map_to_stl.model3d import Layer, TactileModel, build_solid, open_edges, write_stl
from pdf_map_to_stl.pipeline import BuildOptions, build
from pdf_map_to_stl.scene import load_scene
from pdf_map_to_stl.tactile_check import check_model


def read_stl(path):
    raw = path.read_bytes()
    n = int(np.frombuffer(raw[80:84], "<u4")[0])
    rec = np.frombuffer(raw[84:84 + 50 * n], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    return rec["v"]


def corner_model():
    """Two raised areas that touch at one corner, and a wall crossing a recess."""
    layers = [
        Layer("building", "terrain", 3.0, box(10, 10, 20, 20).union(box(20, 20, 30, 30))),
        Layer("water", "terrain", -0.8, box(40, 0, 60, 40)),
        Layer("barrier", "object", 3.5, box(35, 18, 55, 20)),
    ]
    return TactileModel(60, 40, 2.0, 1.0, layers, box(0, 0, 60, 40), (0.0, 0.0, 60.0, 40.0))


def test_written_stl_is_closed_where_areas_touch_at_a_corner(tmp_path):
    info = write_stl(build_solid(corner_model()), tmp_path / "m.stl")
    assert info["separated_vertices"] > 0  # the corner contact was repaired
    assert info["open_edges"] == 0
    assert open_edges(read_stl(tmp_path / "m.stl")) == 0  # as any STL reader merges vertices


def test_a_wall_over_water_stands_on_its_floor():
    solid = build_solid(corner_model())
    assert solid.genus() == 0  # no tunnel under the wall
    # at z 1.5, inside the 0.8 mm recess: the plate around the recess, and the wall's column
    assert solid.slice(1.5).area() == pytest.approx(40 * 40 + 15 * 2, rel=1e-3)


def test_sample_model_stl_is_watertight(tmp_path):
    r = build(BuildOptions(NAVILE, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, out=tmp_path, validate=False))
    assert r["stl"]["open_edges"] == 0 and r["legend_stl"]["open_edges"] == 0
    for f in sorted((tmp_path / "parts").glob("*.stl")) + [tmp_path / "model.stl"]:
        assert open_edges(read_stl(f)) == 0, f.name


def _rotated_copy(tmp_path):
    doc = pymupdf.open(NAVILE)
    doc[0].set_rotation(90)
    path = tmp_path / "rotated.pdf"
    doc.save(path)
    return path


def test_rotated_page_converts_the_window_as_shown(tmp_path):
    # the same window on the page as shown, 90 degrees clockwise: x = H - y, y = x
    h = 296.926
    x0, y0, x1, y1 = CROP_MM
    crop = (h - y1, x0, h - y0, x1)
    r = build(BuildOptions(_rotated_copy(tmp_path), crop_mm=crop, width_mm=TEST_WIDTH_MM, out=tmp_path / "out"))
    assert r["validation"]["metrics"]["accuracy"] >= 0.995
    assert r["warnings"] == []


def test_scanned_page_is_refused(tmp_path):
    src = pymupdf.open(NAVILE)
    doc = pymupdf.open()
    page = doc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, pixmap=src[0].get_pixmap(dpi=50))
    path = tmp_path / "scan.pdf"
    doc.save(path)
    with pytest.raises(ValueError, match="vector"):
        load_scene(path, crop_mm=CROP_MM)


def test_low_agreement_gives_a_warning(tmp_path):
    r = build(BuildOptions(NAVILE, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, out=tmp_path,
                           overrides=("validate.min_agreement=1.01", "validate.min_checked_share=0.99")))
    assert any("agrees with the PDF" in w for w in r["warnings"])
    assert any("could be compared" in w for w in r["warnings"])


@pytest.mark.parametrize("text", ["44.5.3", "44 60 00", "44 30 75", "O 11.3"])
def test_coordinates_with_a_typo_are_refused(text):
    with pytest.raises(ValueError):
        parse_coordinate(text, "lon" if "O" in text else "lat")


def test_symbols_of_a_map_printed_smaller_are_still_recognised(tmp_path):
    # the same map placed at 80 % of its size: thinner lines, smaller dot screens
    src = pymupdf.open(NAVILE)
    doc = pymupdf.open()
    page = doc.new_page(width=src[0].rect.width * 0.8, height=src[0].rect.height * 0.8)
    page.show_pdf_page(page.rect, src, 0)
    path = tmp_path / "small.pdf"
    doc.save(path)
    cfg = load_config()
    m = build_map(load_scene(path, crop_mm=tuple(v * 0.8 for v in CROP_MM)), cfg)
    assert cfg.size_scale_used == pytest.approx(0.8, abs=0.01)
    assert [c for c in m.items if c.cls == "unclassified"] == []
    assert {c.isom for c in m.items if c.cls == "man_made_object"} == {"x man-made object"}


def test_an_unknown_colour_close_to_one_rule_colour_takes_it():
    cfg = load_config()
    assert cfg.nearest_rule_colour((250, 185, 55))[0] == (254, 191, 80)  # open land, another export
    assert cfg.nearest_rule_colour((145, 143, 143)) is None  # between building and grey line: ambiguous
    assert cfg.nearest_rule_colour((227, 6, 19)) is None  # red: no rule colour near


def test_check_flags_a_narrow_passage_between_different_features():
    cfg = load_config()
    layers = [Layer("paved", "terrain", 0.0, box(0, 0, 60, 40).difference(box(10, 10, 20, 30))),
              Layer("open_land", "terrain", 0.5, box(10, 10, 20, 30)),
              Layer("barrier", "object", 3.5, box(21.5, 10, 22.5, 30))]  # 1.5 mm from the grass
    t = TactileModel(60, 40, 2.0, 1.0, layers, box(0, 0, 60, 40), (0.0, 0.0, 60.0, 40.0))
    s = check_model(t, cfg).summary
    assert s["narrow_passages"]["count"] == 1 and s["narrow_gaps"]["count"] == 0
    assert not s["ok"]


def test_rebuild_from_settings_used_is_identical(tmp_path):
    build(BuildOptions(NAVILE, crop_mm=CROP_MM, map_scale=5000, scale=1000, out=tmp_path / "a", validate=False))
    build(BuildOptions(NAVILE, crop_mm=CROP_MM, settings=(str(tmp_path / "a" / "settings_used.toml"),),
                       out=tmp_path / "b", validate=False))
    sha = [hashlib.sha256((tmp_path / d / "model.stl").read_bytes()).hexdigest() for d in "ab"]
    assert sha[0] == sha[1]
