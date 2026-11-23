"""Tactile readability: generalisation, checks, textures, legend and model features."""

from pathlib import Path

import pytest
from shapely.geometry import Point, box

from pdf_map_to_stl.config import Texture, load_config
from pdf_map_to_stl.generalize import generalize
from pdf_map_to_stl.legend import build_legend
from pdf_map_to_stl.model3d import Layer, TactileModel, build_solid, texture_geometry
from pdf_map_to_stl.pipeline import BuildOptions, build
from pdf_map_to_stl.tactile_check import check_model

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample.pdf"


def model(layers, w=60.0, h=40.0):
    return TactileModel(w, h, 2.0, 1.0, layers, box(0, 0, w, h), (0.0, 0.0, w, h))


@pytest.fixture
def cfg():
    return load_config()


# ----------------------------------------------------------------------------- checks


def test_check_flags_a_thin_raised_strip(cfg):
    t = model([Layer("building", "terrain", 3.0, box(10, 10, 30, 10.5)),
               Layer("paved", "terrain", 0.0, box(0, 0, 60, 40).difference(box(10, 10, 30, 10.5)))])
    s = check_model(t, cfg).summary
    assert s["thin_parts"]["by_class"] == {"building": 1}
    assert not s["ok"]


def test_check_flags_a_narrow_passage_between_buildings(cfg):
    buildings = box(10, 10, 20, 30).union(box(21.5, 10, 30, 30))  # 1.5 mm passage
    t = model([Layer("building", "terrain", 3.0, buildings)])
    assert check_model(t, cfg).summary["narrow_gaps"]["count"] == 1


def test_check_flags_touching_areas_that_feel_the_same(cfg):
    t = model([Layer("open_land", "terrain", 0.5, box(0, 0, 30, 40)),
               Layer("forest", "terrain", 0.7, box(30, 0, 60, 40))])
    pairs = check_model(t, cfg).summary["low_steps"]["pairs"]
    assert [(p["a"], p["b"]) for p in pairs] == [("open_land", "forest")]


def test_a_texture_makes_equal_heights_distinguishable(cfg):
    # open_land and open_land_scattered_trees share a height; the second has dots.
    t = model([Layer("open_land", "terrain", 0.5, box(0, 0, 30, 40)),
               Layer("open_land_scattered_trees", "terrain", 0.5, box(30, 0, 60, 40))])
    assert check_model(t, cfg).summary["low_steps"]["count"] == 0


def test_check_flags_an_object_hidden_in_higher_ground(cfg):
    t = model([Layer("building", "terrain", 3.0, box(0, 0, 60, 40)),
               Layer("tree", "object", 2.0, Point(30, 20).buffer(1.5))])
    assert check_model(t, cfg).summary["hidden_objects"]["by_class"] == {"tree": 1}


# ----------------------------------------------------------------------------- generalisation


def test_generalize_keeps_the_tiling_and_absorbs_slivers(cfg):
    paved = box(0, 0, 60, 40).difference(box(10, 10, 50, 30))
    lawn = box(10, 10, 50, 30).difference(box(29.9, 10, 30.1, 30))  # 0.2 mm artefact strip
    sliver = box(29.9, 10, 30.1, 30)
    terrain = {"paved": paved, "open_land": lawn, "forest": sliver}
    heights = {"paved": 0.0, "open_land": 0.5, "forest": 1.0}
    out, _, rep = generalize(terrain, heights, {}, cfg)
    assert "forest" not in out  # the strip was an artefact
    assert rep.slivers_moved >= 1
    assert sum(g.area for g in out.values()) == pytest.approx(60 * 40, rel=1e-6)


def test_generalize_opens_a_narrow_passage(cfg):
    buildings = box(10, 10, 20, 30).union(box(21.5, 10, 30, 30))
    paved = box(0, 0, 60, 40).difference(buildings)
    out, _, rep = generalize({"building": buildings, "paved": paved}, {"building": 3.0, "paved": 0.0}, {}, cfg)
    assert rep.passages_opened >= 1
    passage = box(15, 15, 25, 25).difference(out["building"])
    assert passage.bounds[2] - passage.bounds[0] >= cfg.tactile.min_gap_mm * 0.9


def test_generalize_merges_double_walls_but_not_trees(cfg):
    walls = box(0, 0, 40, 1).union(box(0, 2.5, 40, 3.5))  # 1.5 mm apart
    trees = Point(10, 10).buffer(1).union(Point(12.5, 10).buffer(1))
    _, objs, rep = generalize({}, {}, {"wall": walls, "tree": trees}, cfg)
    assert objs["wall"].geom_type == "Polygon"
    assert objs["tree"].geom_type == "MultiPolygon"
    assert rep.objects_merged == {"wall": 1}


# ----------------------------------------------------------------------------- textures, legend, solid


def test_dot_texture_stays_inside_the_area():
    area = box(0, 0, 20, 10)
    dots = texture_geometry(area, Texture("dots", pitch_mm=3.0, size_mm=1.2))
    assert area.buffer(-0.5).contains(dots)
    assert len(dots.geoms) >= 12


def test_line_texture_is_ridges():
    ridges = texture_geometry(box(0, 0, 20, 20), Texture("lines", pitch_mm=3.0, size_mm=1.0))
    assert 5 <= len(ridges.geoms) <= 12


def test_legend_has_one_sample_per_class_and_prints(cfg):
    t = model([Layer("open_land", "terrain", 0.5, box(0, 0, 30, 40)),
               Layer("building", "terrain", 3.0, box(30, 0, 60, 40)),
               Layer("wall", "object", 3.5, box(5, 5, 50, 6))])
    legend = build_legend(t, cfg)
    assert {lyr.cls for lyr in legend.tactile_layers()} == {"open_land", "building", "wall"}
    assert len(legend.braille_dots) > 10
    solid = build_solid(legend)
    assert solid.genus() == 0 and str(solid.status()).endswith("NoError")


# ----------------------------------------------------------------------------- whole build


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("built")
    return out, build(BuildOptions(SAMPLE, out, validate=False))


def test_model_has_orientation_corner_and_braille_title(built):
    _, r = built
    assert r["tactile_check"]["orientation_corner_mm"] > 0
    assert r["model"]["braille_title"] == "sample"
    assert r["model"]["map_box_mm"][1] > 0  # map sits above the title strip
    assert r["legend_stl"]["genus"] == 0


def test_description_tells_how_to_hold_the_model(built):
    out, _ = built
    text = (out / "description.txt").read_text(encoding="utf-8")
    assert "cut corner is at the top right" in text
    assert "LEGEND" in text and "TACTILE CHECK" in text


def test_generalisation_leaves_few_problems_on_the_sample(built):
    _, r = built
    c = r["tactile_check"]
    assert c["low_steps"]["count"] == 0
    assert c["thin_parts"]["count"] < 60  # 164 before generalisation
    assert c["narrow_gaps"]["count"] < 15  # 72 before generalisation


def test_test_tile_has_no_title_strip(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, region_mm=(40, 30, 70, 50), validate=False))
    assert r["model"]["braille_title"] == ""
    assert r["model"]["height_mm"] == pytest.approx(20)


def test_tiling_is_unchanged_by_generalisation(built):
    _, r = built
    terrain_area = sum(lyr["area_mm2"] for lyr in r["layers"] if lyr["role"] == "terrain")
    x0, y0, x1, y1 = r["model"]["map_box_mm"]
    corner = r["tactile_check"]["orientation_corner_mm"]
    assert terrain_area == pytest.approx((x1 - x0) * (y1 - y0) - corner**2 / 2, rel=2e-3)

