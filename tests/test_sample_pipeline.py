"""End-to-end checks on samples/sample.pdf."""

import hashlib
from pathlib import Path

import pytest

from pdf_map_to_stl.compose import build_map
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.pipeline import BuildOptions, build
from pdf_map_to_stl.scene import load_scene

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample.pdf"


@pytest.fixture(scope="module")
def mapmodel():
    return build_map(load_scene(SAMPLE), load_config())


def test_dot_screens_become_402_areas(mapmodel):
    dots = [c for c in mapmodel.items if c.prim.kind == "dots"]
    assert len(dots) == 8
    assert {c.cls for c in dots} == {"open_land_scattered_trees"}
    assert all(c.isom == "402" for c in dots)


def test_every_symbol_on_the_page_is_classified(mapmodel):
    assert [c for c in mapmodel.items if c.cls == "unclassified"] == []


def test_visible_terrain_tiles_the_page_without_overlap(mapmodel):
    page_area = mapmodel.scene.width_pt * mapmodel.scene.height_pt
    geoms = list(mapmodel.terrain.values())
    assert sum(g.area for g in geoms) == pytest.approx(page_area, rel=1e-6)
    for i, a in enumerate(geoms):
        for b in geoms[i + 1 :]:
            assert a.intersection(b).area < 1e-6


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_full_build_is_valid_and_deterministic(tmp_path):
    r1 = build(BuildOptions(SAMPLE, tmp_path / "a"))
    build(BuildOptions(SAMPLE, tmp_path / "b"))
    assert r1["stl"]["genus"] == 0
    assert r1["stl"]["status"].endswith("NoError")
    assert r1["validation"]["metrics"]["accuracy"] >= 0.995
    assert r1["validation"]["metrics"]["evaluated_share"] >= 0.75
    for name in ("model.stl", "legend.stl", "description.txt", "classes.png", "symbols.csv", "layers.svg", "tuner.html"):
        assert _sha(tmp_path / "a" / name) == _sha(tmp_path / "b" / name), name


def test_crop_selects_part_of_the_page():
    scene = load_scene(SAMPLE, crop_mm=(10, 5, 30, 20))
    x0, y0, x1, y1 = scene.page_rect
    assert (x1 - x0) * 25.4 / 72 == pytest.approx(20)
    assert (y1 - y0) * 25.4 / 72 == pytest.approx(15)


def test_heights_file_overrides_config(tmp_path):
    h = tmp_path / "heights.toml"
    h.write_text("[output]\nbase_mm = 3.0\n[class.building]\nheight_mm = 1.5\n", encoding="utf-8")
    cfg = load_config(heights=h)
    assert cfg.base_mm == 3.0
    assert cfg.classes["building"].height_mm == 1.5
    assert cfg.classes["wall"].height_mm == load_config().classes["wall"].height_mm


def test_heights_file_rejects_unknown_class(tmp_path):
    h = tmp_path / "heights.toml"
    h.write_text("[class.not_a_class]\nheight_mm = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(heights=h)


def test_region_makes_a_small_test_tile(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, region_mm=(40, 30, 70, 50), validate=False))
    assert r["model"]["width_mm"] == pytest.approx(30)
    assert r["model"]["height_mm"] == pytest.approx(20)
    assert r["stl"]["genus"] == 0
