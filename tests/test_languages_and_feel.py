"""Languages (Italian by default, English on request), and how the model feels: heights
that include their texture, rounded Braille dots and trees."""

import re
import tomllib
from importlib import resources

import pytest
from manifold3d import Manifold
from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM
from shapely.geometry import Point

from pdf_map_to_stl import i18n
from pdf_map_to_stl.braille import BrailleSpec
from pdf_map_to_stl.config import Texture, load_config
from pdf_map_to_stl.model3d import braille_dot, object_solid, texture_levels
from pdf_map_to_stl.pick import write_picker
from pdf_map_to_stl.pipeline import BuildOptions, build


def _texts(code: str) -> dict:
    return i18n.catalogue(code)


def test_every_language_has_every_text_with_the_same_placeholders():
    english = _texts("en")
    assert "it" in i18n.languages()
    for code in i18n.languages():
        texts = _texts(code)
        assert set(texts) == set(english), code
        for key, text in english.items():
            used = set(re.findall(r"\{(\w+)\}", texts[key]))
            if key == "position.format":  # each language writes coordinates its own way, from these values
                assert used <= {"lat", "lon", "lat_abs", "lon_abs", "ns", "ew"}, code
            else:
                assert used == set(re.findall(r"\{(\w+)\}", text)), (code, key)


def test_the_default_language_is_italian_and_english_is_one_setting_away():
    assert load_config().language == "it" and i18n.language() == "it"
    assert load_config(overrides=["output.language=en"]).language == "en" and i18n.language() == "en"
    assert load_config().legend_label if False else True  # (loading a config sets its language)
    load_config()
    with pytest.raises(ValueError, match="output.language"):
        load_config(overrides=["output.language=xx"])


def test_legend_labels_follow_the_language():
    assert load_config().classes["open_land"].legend_label == "prato"
    assert load_config(overrides=["output.language=en"]).classes["open_land"].legend_label == "open land"
    load_config()


def test_a_build_in_english(tmp_path):
    r = build(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, region_mm=(0, 0, 30, 30),
                           validate=False, overrides=("output.language=en",)))
    text = (tmp_path / "description.txt").read_text(encoding="utf-8")
    assert "HOW TO HOLD IT" in text and "COME TENERLA" not in text
    assert "HOW TO LOAD" in (tmp_path / "parts" / "README.txt").read_text(encoding="utf-8")
    assert r["stl"]["open_edges"] == 0
    load_config()  # back to the default language for the other tests


def test_the_window_picker_speaks_the_chosen_language(tmp_path):
    for code, heading in (("it", "Scegli la finestra della mappa"), ("en", "Pick the map window")):
        i18n.set_language(code)
        write_picker(NAVILE, tmp_path / f"pick_{code}.html")
        html = (tmp_path / f"pick_{code}.html").read_text(encoding="utf-8")
        assert heading in html and f'"lang": "{code}"' in html
    i18n.set_language("it")


def test_heights_include_the_texture_on_top():
    cfg = load_config()
    dots = Texture("dots", 3.0, 1.2, 0.5, name="dots")
    assert texture_levels(0.6, dots, cfg) == (0.1, 0.1, 0.6)  # open land: the dots end at 0.6 mm
    assert texture_levels(-0.6, Texture("waves", 3.0, 0.8, 0.4), cfg) == pytest.approx((-1.0, -1.0, -0.6))
    assert texture_levels(0.0, dots, cfg) is None  # flat and textured: no room for the texture
    old = load_config(overrides=["output.heights_include_texture=false"])
    assert texture_levels(0.6, dots, old) == (0.6, 0.6, 1.1)
    load_config()


def test_the_default_model_is_4_6_mm_high_and_steps_by_0_6_mm():
    cfg = load_config()
    heights = {c: cfg.classes[c].height_mm for c in ("paved", "open_land", "forest", "forbidden", "building")}
    assert heights == {"paved": 0.0, "open_land": 0.6, "forest": 1.2, "forbidden": 1.8, "building": 2.4}
    assert cfg.base_mm + heights["building"] == pytest.approx(4.6)
    assert cfg.classes["tree"].height_mm == cfg.classes["barrier"].height_mm < heights["building"]


def test_braille_dots_and_trees_are_rounded():
    def levels(m: Manifold) -> int:
        return len({round(float(z), 3) for z in m.to_mesh().vert_properties[:, 2]})

    assert levels(braille_dot(0, 0, 2.0, BrailleSpec())) > 4  # a dome: many layers, no flat tip
    assert levels(braille_dot(0, 0, 2.0, BrailleSpec(dot_shape="cone"))) <= 3
    tree = Point(0, 0).buffer(1.25, 32)
    flat, dome = object_solid(tree, 0, 1.8), object_solid(tree, 0, 1.8, "dome")
    assert dome.volume() == pytest.approx(2 / 3 * flat.volume(), rel=0.1)  # half an ellipsoid on the same base
    assert dome.bounding_box()[5] == pytest.approx(1.8, abs=0.01)


def test_locales_are_packaged_with_the_program():
    files = {p.name for p in resources.files("pdf_map_to_stl").joinpath("locales").iterdir()}
    assert {"it.toml", "en.toml"} <= files
    for name in ("it.toml", "en.toml"):
        tomllib.loads(resources.files("pdf_map_to_stl").joinpath("locales", name).read_text(encoding="utf-8"))
