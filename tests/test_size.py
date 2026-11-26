"""The suggested print size, and the map scale read from the page."""

import tomllib

import pytest
from sample_map import CROP_MM, NAVILE

from pdf_map_to_stl.compose import build_map
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.pipeline import BuildOptions, build, set_map_scale, suggest
from pdf_map_to_stl.scene import load_scene, read_map_scale
from pdf_map_to_stl.size import suggest_size


def test_map_scale_is_read_from_the_page():
    assert read_map_scale(NAVILE) == 5000  # "Scala 1: 5000" in the title block


@pytest.fixture(scope="module")
def window():
    return build_map(load_scene(NAVILE, crop_mm=CROP_MM), load_config())


def _suggest(window, *overrides, map_scale=5000):
    cfg = load_config(overrides=overrides)
    cfg.map_scale = map_scale
    return suggest_size(window, cfg)


def test_suggested_size_makes_most_details_readable(window):
    sg = _suggest(window)
    assert sg.share_ok >= 0.9 and not sg.limited
    # A round scale; the guidebook recommends 1:500 to 1:1000. (1:900 with the canopy off:
    # raised, the narrow strips of portici ask for a little more.)
    assert sg.tactile_scale == 800
    assert sg.width_mm == pytest.approx(50.058 * 5000 / 800, rel=1e-3)


def test_without_a_map_scale_the_width_is_rounded_to_10_mm(window):
    sg = _suggest(window, map_scale=0)
    assert sg.tactile_scale == 0
    assert sg.width_mm % 10 == pytest.approx(0, abs=1e-6) or sg.width_mm % 10 == pytest.approx(10, abs=1e-6)
    assert sg.share_ok >= 0.9


def test_size_limits_win_over_the_details(window):
    small = _suggest(window, "size.max_mm=200")
    assert small.limited == "max"
    assert max(small.width_mm, small.plate_height_mm) == pytest.approx(200)
    assert small.share_ok < 0.9
    big = _suggest(window, "size.min_mm=500")
    assert big.limited == "min" and max(big.width_mm, big.plate_height_mm) == pytest.approx(500)


def test_a_larger_detail_share_asks_for_a_larger_map(window):
    assert _suggest(window, "size.detail_share=0.95").width_mm > _suggest(window).width_mm


def test_suggestion_offers_a_size_that_fits_the_printer_bed():
    _, lines = suggest(NAVILE, crop_mm=CROP_MM)
    text = " ".join(lines)
    assert "scala 1:800" in text and "--scale 1000" in text  # 313 mm does not fit a 256 mm bed


def test_set_map_scale_order():
    cfg = load_config()
    assert set_map_scale(cfg, None, NAVILE, 0) == "read from the page" and cfg.map_scale == 5000
    cfg = load_config(overrides=["output.read_map_scale=false"])
    assert set_map_scale(cfg, None, NAVILE, 0) == "unknown" and cfg.map_scale == 0
    cfg = load_config()
    assert set_map_scale(cfg, 4000, NAVILE, 0) == "--map-scale" and cfg.map_scale == 4000


def test_build_uses_the_suggested_size_unless_told_otherwise(tmp_path):
    tile = (0, 0, 40, 30)  # a small tile keeps the build quick; the size is decided on the whole window
    r = build(BuildOptions(NAVILE, tmp_path / "a", crop_mm=CROP_MM, region_mm=tile, validate=False))
    assert r["size"]["source"] == "suggested"
    assert r["size"]["used_width_mm"] == pytest.approx(r["size"]["width_mm"])
    assert r["model"]["tactile_scale"] == 800
    used = tomllib.loads((tmp_path / "a" / "settings_used.toml").read_text(encoding="utf-8"))
    assert used["output"]["width_mm"] == pytest.approx(r["size"]["used_width_mm"], abs=1e-3)  # rebuilds the same
    assert "DIMENSIONI" in (tmp_path / "a" / "description.txt").read_text(encoding="utf-8")

    r = build(BuildOptions(NAVILE, tmp_path / "b", crop_mm=CROP_MM, region_mm=tile, scale=1000, validate=False))
    assert r["size"]["source"] == "--scale" and r["model"]["tactile_scale"] == 1000
