"""Settings: profiles, --set, switches per class, textures, smoothing, settings_used.toml."""

import tomllib
from pathlib import Path

import pytest
from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM
from shapely.geometry import box

from pdf_map_to_stl.compose import build_map
from pdf_map_to_stl.config import PROFILE_DIR, load_config, parse_override, settings_dict, to_toml
from pdf_map_to_stl.generalize import generalize
from pdf_map_to_stl.model3d import build_layers
from pdf_map_to_stl.pipeline import BuildOptions, build, switchable_classes
from pdf_map_to_stl.scene import load_scene
from pdf_map_to_stl.tactile_check import check_model
from pdf_map_to_stl.tuner import tuner_data

ROOT = Path(__file__).resolve().parents[1]
TILE = (40, 30, 70, 50)  # a small test tile of the sample, model mm


# ----------------------------------------------------------------------------- loading


@pytest.mark.parametrize("profile", sorted(p.stem for p in PROFILE_DIR.glob("*.toml")))
def test_every_profile_loads(profile):
    cfg = load_config(settings=[profile])
    assert cfg.sources[-1].endswith(f"{profile}.toml")


def test_no_textures_profile_makes_every_area_smooth():
    cfg = load_config(settings=["no_textures"])
    assert cfg.classes["open_land"].texture is not None  # still configured...
    assert all(cfg.texture(c) is None for c in cfg.classes)  # ...but not used


@pytest.mark.parametrize("text, path, value", [
    ("class.canopy.enabled=true", ["class", "canopy", "enabled"], True),
    ("output.base_mm=2.5", ["output", "base_mm"], 2.5),
    ("smoothing.line_join=mitre", ["smoothing", "line_join"], "mitre"),
    ('class.forest.texture="dots"', ["class", "forest", "texture"], "dots"),
    ("class.paved.colour=[1, 2, 3]", ["class", "paved", "colour"], [1, 2, 3]),
])
def test_set_reads_values_as_toml(text, path, value):
    assert parse_override(text) == (path, value)


def test_set_overrides_one_value():
    cfg = load_config(overrides=["class.building.height_mm=2", "features.standard_symbols=false"])
    assert cfg.classes["building"].height_mm == 2
    assert cfg.shape("tree") == ""
    assert load_config().shape("tree") == "dot"


@pytest.mark.parametrize("override", [
    "smoothing.line_joint=mitre",  # misspelt key
    "class.not_a_class.enabled=true",  # unknown class
    "class.forest.texture=plaid",  # unknown texture
    "class.tree.shape=star",  # unknown shape
    "class.canopy.merge_into=tree",  # not a terrain class
    "colours.forest=red",  # unknown section
])
def test_a_wrong_setting_is_an_error(override):
    with pytest.raises(ValueError):
        load_config(overrides=[override])


def test_settings_used_builds_the_same_config(tmp_path):
    cfg = load_config(overrides=["class.canopy.enabled=true", "smoothing.simplify_mm=0.2"])
    f = tmp_path / "settings_used.toml"
    f.write_text(to_toml(settings_dict(cfg), "test"), encoding="utf-8")
    tomllib.loads(f.read_text(encoding="utf-8"))  # valid TOML
    again = load_config(settings=[f])
    for part in ("classes", "features", "smoothing", "generalize", "tactile", "braille", "textures"):
        assert getattr(again, part) == getattr(cfg, part), part


# ----------------------------------------------------------------------------- switches


def test_canopy_is_shown_unless_switched_off():
    on = load_config()  # the blind testers asked for the portici above the street
    assert on.shown_as("canopy") == "canopy" and on.role("canopy") == "terrain"
    off = load_config(overrides=["class.canopy.enabled=false"])
    assert off.shown_as("canopy") == "paved" and off.role("canopy") == "ignore"
    assert load_config().shown_as("footpath") is None  # an object switched off is not shown


@pytest.fixture(scope="module")
def scene():
    return load_scene(NAVILE, crop_mm=CROP_MM)


def test_canopy_switch_moves_its_area_between_classes(scene):
    off = build_map(scene, load_config(overrides=["class.canopy.enabled=false"]))
    on = build_map(scene, load_config())
    assert "canopy" not in off.terrain and on.terrain["canopy"].area > 0
    assert off.terrain["paved"].area == pytest.approx(on.terrain["paved"].area + on.terrain["canopy"].area, rel=1e-3)
    sources = {c.source for c in off.items if c.cls == "paved"}
    assert "canopy" in sources  # still known as canopy, shown as paved


def test_tuner_offers_classes_that_are_switched_off(scene):
    cfg = load_config(overrides=["class.canopy.enabled=false"])
    cfg.width_mm = TEST_WIDTH_MM
    m = build_map(scene, cfg)
    t = build_layers(m, cfg, TILE)
    names = switchable_classes(m.items, cfg)
    assert "canopy" in names and "outline" not in names  # ignored classes cannot be switched on
    rows = {c["class"]: c for c in tuner_data(t, {}, NAVILE.name, cfg, check_model(t, cfg).summary, names)["classes"]}
    assert rows["canopy"]["enabled"] is False and rows["canopy"]["texture"] == "stripes"
    assert rows["tree"]["shape"] == "dot" and rows["tree"]["point_symbol"]


# ----------------------------------------------------------------------------- generalisation and smoothing


def _two_areas():
    # a raised square with sharp corners in the middle of a flat area
    square = box(10, 10, 30, 30)
    return {"building": square, "paved": box(0, 0, 40, 40).difference(square)}, {"building": 3.0, "paved": 0.0}


def test_round_corners_keeps_the_tiling():
    terrain, heights = _two_areas()
    cfg = load_config(overrides=["smoothing.round_corners_mm=2"])
    out, _, rep = generalize(terrain, heights, {}, cfg)
    assert rep.corners_rounded == 4
    assert sum(g.area for g in out.values()) == pytest.approx(40 * 40, rel=1e-6)
    assert out["building"].area < 20 * 20


def test_simplify_keeps_the_tiling():
    terrain, heights = _two_areas()
    zigzag = box(10, 10, 30, 30).union(box(19.9, 30, 20.1, 30.1))  # a 0.1 mm bump
    terrain = {"building": zigzag, "paved": box(0, 0, 40, 40).difference(zigzag)}
    only_simplify = ["smoothing.simplify_mm=0.3", "generalize.clean_slivers=false", "generalize.widen_thin=false"]
    out, _, rep = generalize(terrain, heights, {}, load_config(overrides=only_simplify))
    assert sum(g.area for g in out.values()) == pytest.approx(40 * 40, rel=1e-6)
    assert rep.simplified_mm2 > 0 and out["building"].area == pytest.approx(20 * 20, abs=1e-3)  # bump gone


def test_merging_objects_can_be_switched_off():
    walls = box(0, 0, 40, 1).union(box(0, 2.5, 40, 3.5))  # 1.5 mm apart
    _, objs, _ = generalize({}, {}, {"barrier": walls}, load_config())
    assert objs["barrier"].geom_type == "Polygon"
    _, objs, rep = generalize({}, {}, {"barrier": walls}, load_config(overrides=["generalize.merge_close_objects=false"]))
    assert objs["barrier"].geom_type == "MultiPolygon" and not rep.objects_merged
    _, objs, _ = generalize({}, {}, {"barrier": walls}, load_config(overrides=["generalize.merge_gap_mm=1"]))
    assert objs["barrier"].geom_type == "MultiPolygon"  # 1.5 mm apart is more than the gap


# ----------------------------------------------------------------------------- whole builds


def _tile(tmp_path, *settings, overrides=()):
    return build(BuildOptions(NAVILE, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, out=tmp_path, region_mm=TILE, validate=False, settings=settings, overrides=overrides))


def test_heights_only_profile_has_no_textures_and_keeps_drawn_shapes(tmp_path):
    default = _tile(tmp_path / "a")
    plain = _tile(tmp_path / "b", "heights_only")
    roles = {lyr["role"] for lyr in plain["layers"]}
    assert "texture" not in roles and "texture" in {lyr["role"] for lyr in default["layers"]}
    area = {r: {lyr["class"]: lyr["area_mm2"] for lyr in rep["layers"]} for r, rep in (("d", default), ("p", plain))}
    assert area["p"]["tree"] != pytest.approx(area["d"]["tree"])  # trees as drawn, not 2.5 mm dots
    assert plain["stl"]["genus"] == 0
    assert not any(p["kind"] == "texture" for p in plain["parts"])


def test_build_writes_settings_used_and_explains_its_changes(tmp_path):
    _tile(tmp_path, overrides=("smoothing.line_join=mitre",))
    used = tomllib.loads((tmp_path / "settings_used.toml").read_text(encoding="utf-8"))
    assert used["smoothing"]["line_join"] == "mitre"
    assert used["class"]["canopy"]["enabled"] is True and used["output"]["language"] == "it"
    text = (tmp_path / "description.txt").read_text(encoding="utf-8")
    assert "SCELTE AUTOMATICHE" in text and "angoli mitre" in text
    assert "--set smoothing.line_join=mitre" in text
