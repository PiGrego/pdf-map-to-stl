"""Position points: coordinates in any common form, pins, Braille, the check."""

import pytest
from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM

from pdf_map_to_stl.geo import GeoPoint, check_points, parse_coordinate, parse_geo, pins
from pdf_map_to_stl.pipeline import BuildOptions, build, rebuild_command


@pytest.mark.parametrize("text, axis, value", [
    ("44.51234", "lat", 44.51234),
    ("44.51234 N", "lat", 44.51234),
    ("N 44.51234", "lat", 44.51234),
    ("44°30'44.4\"N", "lat", 44 + 30 / 60 + 44.4 / 3600),
    ("44 30 44.4 N", "lat", 44 + 30 / 60 + 44.4 / 3600),
    ("33.86 S", "lat", -33.86),
    ("11.3 W", "lon", -11.3),
    ("-11.3", "lon", -11.3),
])
def test_coordinates_in_any_common_form(text, axis, value):
    assert parse_coordinate(text, axis) == pytest.approx(value)


@pytest.mark.parametrize("text, axis", [("11.3 E", "lat"), ("95", "lat"), ("181", "lon"), ("north", "lat")])
def test_a_wrong_coordinate_is_an_error(text, axis):
    with pytest.raises(ValueError):
        parse_coordinate(text, axis)


def test_a_position_point_is_a_place_on_the_page_and_its_coordinates():
    assert parse_geo("80,200,44.515,11.34") == GeoPoint(80, 200, 44.515, 11.34)
    with pytest.raises(ValueError):
        parse_geo("80,200,44.515")


@pytest.mark.parametrize("index", [1, 2])
def test_point_n_has_n_pins(index):
    assert len(list(getattr(pins(index, 10, 10, 3.0), "geoms", [None]))) == index


def test_two_points_are_checked_against_the_map():
    a = GeoPoint(0, 0, 44.5, 11.3)
    b = GeoPoint(0, 100, 44.5 - 500 / 111_195, 11.3)  # 100 mm south on the map = 500 m at 1:5000
    assert "(0 % di differenza)" in check_points([a, b], 5000)[0]
    wrong = GeoPoint(0, 100, 44.6, 11.3)  # a typing mistake: 11 km away
    assert "controlla le coordinate" in check_points([a, wrong], 5000)[0]
    assert check_points([a], 5000) == [] and check_points([a, b], 0) == []


@pytest.fixture(scope="module")
def geo_build(tmp_path_factory):
    out = tmp_path_factory.mktemp("geo")
    points = (GeoPoint(80, 200, 44.515, 11.34), GeoPoint(110, 220, 44.5141111, 11.3418889))
    o = BuildOptions(NAVILE, out, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, validate=False, geo=points)
    return o, build(o)


def test_position_points_become_pins_and_braille(geo_build):
    o, r = geo_build
    assert [p["pins"] for p in r["positions"]] == [1, 2]
    assert [p["text"] for p in r["positions"]] == ["44,51500 N 11,34000 E", "44,51411 N 11,34189 E"]
    assert any(lyr["role"] == "pin" for lyr in r["layers"]) and any(p["kind"] == "pin" for p in r["parts"])
    assert r["stl"]["genus"] == 0
    text = (o.out / "description.txt").read_text(encoding="utf-8")
    assert "DOVE SI TROVA" in text and "openstreetmap.org/?mlat=44.515000" in text
    # The QR code of point 1, in a frame at the bottom right: its own parts, to print dark on light.
    assert r["qr"]["link"] == "https://maps.google.com/?q=44.51500,11.34000" and r["qr"]["modules"] >= 21
    assert {"qr", "qr_frame"} <= {p["kind"] for p in r["parts"]} and "QR code" in text
    assert "--geo 80,200,44.5150000,11.3400000" in rebuild_command(o)


def test_a_point_outside_the_window_or_a_third_point_is_an_error(tmp_path):
    outside = GeoPoint(10, 10, 44.5, 11.3)
    with pytest.raises(ValueError, match="outside the window"):
        build(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, validate=False, geo=(outside,)))
    three = tuple(GeoPoint(80 + i, 200, 44.5, 11.3) for i in range(3))
    with pytest.raises(ValueError, match="at most 2"):
        build(BuildOptions(NAVILE, tmp_path, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, validate=False, geo=three))
