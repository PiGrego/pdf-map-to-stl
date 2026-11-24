"""One STL per layer, standard symbols, textures, tactile scale, stand-alone legend."""

from pathlib import Path

import pytest
from manifold3d import Manifold, OpType
from shapely.geometry import box

from pdf_map_to_stl.config import Texture, load_config
from pdf_map_to_stl.model3d import (
    Layer,
    TactileModel,
    build_solid,
    standard_symbol,
    texture_geometry,
)
from pdf_map_to_stl.parts import build_parts
from pdf_map_to_stl.pipeline import BuildOptions, LegendOptions, build, build_legend_sample

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "sample.pdf"
NAVILE = ROOT / "samples" / "orienteering-map-sample-Navile.pdf"


def small_model():
    layers = [
        Layer("paved", "terrain", 0.0, box(0, 0, 20, 40)),
        Layer("open_land", "terrain", 0.5, box(20, 0, 40, 40)),
        Layer("water", "terrain", -0.8, box(40, 0, 60, 40)),
        Layer("open_land texture", "texture", 1.0, box(25, 5, 35, 35).difference(box(28, 0, 32, 40)), z0_mm=0.5,
              on="open_land"),
        Layer("barrier", "object", 3.5, box(10, 18, 50, 20)),
    ]
    return TactileModel(60, 40, 2.0, 1.0, layers, box(0, 0, 60, 40), (0.0, 0.0, 60.0, 40.0), [(5, 5), (8, 5)])


def test_parts_cover_the_model_without_overlapping():
    t = small_model()
    parts = build_parts(t, 0.6)
    names = [p.name for p in parts]
    assert names[0] == "base"
    assert {"paved", "open_land", "water", "barrier", "open_land_texture", "braille"} <= set(names)
    union = Manifold.batch_boolean([p.solid for p in parts], OpType.Add)
    total = sum(p.solid.volume() for p in parts)
    assert union.volume() == pytest.approx(total, rel=1e-4)  # no overlaps
    assert union.volume() == pytest.approx(build_solid(t).volume(), rel=0.01)  # same model


def test_each_area_owns_its_top_skin():
    parts = {p.name: p for p in build_parts(small_model(), 0.6)}
    lo, hi = parts["paved"].solid.bounding_box()[2], parts["paved"].solid.bounding_box()[5]
    assert (lo, hi) == pytest.approx((1.4, 2.0))  # flat area: a 0.6 mm skin up to the plate top
    assert parts["water"].z_top_mm == pytest.approx(1.2)  # floor of a 0.8 mm recess
    # the barrier part only rises above the ground it stands on
    assert parts["barrier"].solid.bounding_box()[2] == pytest.approx(2.0)


@pytest.mark.parametrize("shape", ["dot", "ring", "cross"])
def test_standard_symbols_have_their_size(shape):
    g = standard_symbol(shape, 10, 10, 3.0, 0.9)
    x0, y0, x1, y1 = g.bounds
    assert max(x1 - x0, y1 - y0) == pytest.approx(3.0 if shape != "cross" else 3.0 / 2**0.5 + 0.9 / 2**0.5, rel=0.05)
    if shape == "ring":
        assert not g.contains(g.centroid)


@pytest.mark.parametrize("kind", ["rings", "waves"])
def test_new_textures_stay_inside(kind):
    area = box(0, 0, 20, 12)
    tex = texture_geometry(area, Texture(kind, pitch_mm=3.0, size_mm=2.4 if kind == "rings" else 0.8))
    assert not tex.is_empty and area.contains(tex)


def test_scale_option_sets_the_width(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, map_scale=5000, scale=1000, region_mm=(0, 0, 30, 30), validate=False))
    assert r["model"]["scale_model_mm_per_pdf_mm"] == pytest.approx(5.0, rel=1e-3)


def test_scale_option_needs_the_map_scale(tmp_path):
    with pytest.raises(ValueError, match="map-scale"):
        build(BuildOptions(SAMPLE, tmp_path, scale=1000, validate=False))


def test_build_writes_one_stl_per_layer(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, validate=False))
    files = sorted(p.name for p in (tmp_path / "parts").glob("*.stl"))
    assert files[0] == "00_base.stl" and len(files) == len(r["parts"]) >= 10
    assert "Load" in (tmp_path / "parts" / "README.txt").read_text(encoding="utf-8")
    assert (tmp_path / "legend_parts" / "README.txt").exists()


def test_legend_sample_lists_the_symbols_found(tmp_path):
    r = build_legend_sample(LegendOptions(SAMPLE, tmp_path))
    assert {"open_land", "forest", "building", "paved", "barrier", "tree"} <= set(r["classes"])
    assert "boulder" not in r["classes"]  # not on this map
    assert r["legend_stl"]["genus"] == 0
    text = (tmp_path / "legend.txt").read_text(encoding="utf-8")
    assert 'Braille "open land"' in text


@pytest.mark.skipif(not NAVILE.exists(), reason="Navile sample not available")
def test_navile_legend_has_the_guidebook_symbols_of_that_map(tmp_path):
    r = build_legend_sample(LegendOptions(NAVILE, tmp_path, title="key navile"))
    assert set(r["classes"]) == {"water", "paved", "open_land", "forest", "forbidden", "building",
                                 "man_made_object", "tree", "barrier"}
    assert r["size_mm"][1] <= load_config().legend_max_height_mm


def test_detailed_config_still_builds(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, config=ROOT / "config" / "isom_detailed.toml",
                           region_mm=(20, 20, 60, 50), validate=False))
    assert r["stl"]["genus"] == 0
