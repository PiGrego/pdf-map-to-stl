"""A plate of fixed size (--plate): the window is made to fill it at the chosen scale."""

import argparse

import pytest
from sample_map import CROP_MM, NAVILE

from pdf_map_to_stl.cli import _plate
from pdf_map_to_stl.config import load_config
from pdf_map_to_stl.pipeline import BuildOptions, build, plate_window
from pdf_map_to_stl.scene import page_size_mm


def _cfg():
    cfg = load_config()
    cfg.map_scale = 5000  # as printed on the Navile map
    return cfg


def test_the_plate_comes_out_at_its_size_centred_on_the_picked_window(tmp_path):
    r = build(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, scale=2500, plate_mm=(120.0, 100.0), validate=False))
    m = r["model"]
    assert m["width_mm"] == pytest.approx(120, abs=0.01) and m["height_mm"] == pytest.approx(100, abs=0.01)
    x0, y0, x1, y1 = r["size"]["window_mm"]
    assert x1 - x0 == pytest.approx(120 / 2, abs=0.002)  # 1:5000 printed at 1:2500: twice the size
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx(((CROP_MM[0] + CROP_MM[2]) / 2, (CROP_MM[1] + CROP_MM[3]) / 2),
                                                           abs=0.002)
    assert r["size"]["source"] == "--plate" and "fissata a 120 per 100 mm" in " ".join(r["size"]["lines"])
    # The scale bar under the title: 100 m is 40 mm at 1:2500, with a tick every 20 m.
    assert r["scale_bar"] == {"metres": 100, "length_mm": 40.0, "divisions": 5, "label": "100 m",
                              "where": "bottom_left"}  # the title takes three lines
    assert "barra in rilievo misura 100 m" in (tmp_path / "description.txt").read_text(encoding="utf-8")
    assert list((tmp_path / "parts").glob("*_scale_bar.stl"))  # its own part, for a colour of its own


def test_a_long_title_or_coordinates_take_room_from_the_map_not_the_plate(tmp_path):
    cfg = _cfg()
    short = plate_window(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, scale=1000, plate_mm=(120.0, 120.0),
                                      title="map"), cfg)
    long = plate_window(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, scale=1000, plate_mm=(120.0, 120.0),
                                     title="a much longer title that needs two lines of braille"), cfg)
    assert short[2] - short[0] == pytest.approx(long[2] - long[0])  # same width
    assert long[3] - long[1] < short[3] - short[1]  # less map height


def test_a_plate_near_the_edge_of_the_page_stays_on_the_page(tmp_path):
    w = plate_window(BuildOptions(NAVILE, tmp_path, crop_mm=(0, 100, 2, 102), scale=1000, plate_mm=(100.0, 100.0)),
                     _cfg())
    assert w[0] == 0 and w[2] == pytest.approx(20)
    page_w, _ = page_size_mm(NAVILE)
    w = plate_window(BuildOptions(NAVILE, tmp_path, crop_mm=(page_w - 2, 100, page_w, 102), scale=1000,
                                  plate_mm=(100.0, 100.0)), _cfg())
    assert w[2] == pytest.approx(page_w, abs=0.001)


@pytest.mark.parametrize(("options", "message"), [
    ({"plate_mm": (100.0, 100.0)}, "--scale"),
    ({"plate_mm": (100.0, 100.0), "scale": 1000, "width_mm": 100}, "--width"),
    ({"plate_mm": (100.0, 100.0), "scale": 1000, "crop_mm": (70, 190, 120, 190, 95, 226)}, "rectangle"),
    ({"plate_mm": (100.0, 50.0), "scale": 1000}, "no room"),
    ({"plate_mm": (200.0, 200.0), "scale": 50000}, "more than the whole page"),
])
def test_a_plate_that_cannot_be_made_says_why(tmp_path, options, message):
    with pytest.raises(ValueError, match=message):
        plate_window(BuildOptions(NAVILE, tmp_path, **{"crop_mm": CROP_MM, **options}), _cfg())


def test_the_plate_size_on_the_command_line():
    assert _plate("170,170") == _plate("170x170") == _plate("170") == (170.0, 170.0)
    assert _plate("180 x 150") == (180.0, 150.0)
    with pytest.raises(argparse.ArgumentTypeError):
        _plate("0,100")
