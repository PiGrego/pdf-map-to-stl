"""The generated HTML pages carry their data and nothing is left of the placeholders."""

import json
import re

from sample_map import CROP_MM, NAVILE, TEST_WIDTH_MM

from pdf_map_to_stl.pick import write_picker
from pdf_map_to_stl.pipeline import BuildOptions, build


def _embedded_json(html: str, var: str) -> dict:
    m = re.search(rf"const {var} = (\{{.*?\}});\n", html, re.DOTALL)
    assert m, f"{var} not found"
    return json.loads(m.group(1))


def test_picker_page_has_page_image_and_size(tmp_path):
    out = tmp_path / "pick.html"
    write_picker(NAVILE, out)
    html = out.read_text(encoding="utf-8")
    assert "__PAGE_DATA__" not in html
    data = _embedded_json(html, "PAGE")
    assert data["image"].startswith("data:image/png;base64,")
    assert data["width_mm"] > 0 and data["height_mm"] > 0
    # Fixed size: the map's scale as printed on the page, and the usual margins of a plate.
    assert data["map_scale"] == 5000 and all(m > 0 for m in data["margins_mm"])
    assert 'value="fixed"' in html and 'id="slopes"' in html  # slopes stay a choice, off by default
    assert '<input type="checkbox" id="slopes" checked' not in html
    assert '<input type="checkbox" id="scalebar" checked' in html  # the scale bar is on unless unticked


def test_tuner_page_lists_every_layer(tmp_path):
    r = build(BuildOptions(NAVILE, crop_mm=CROP_MM, width_mm=TEST_WIDTH_MM, out=tmp_path, validate=False))
    html = (tmp_path / "tuner.html").read_text(encoding="utf-8")
    assert "__MODEL_DATA__" not in html
    data = _embedded_json(html, "MODEL")
    assert {lyr["class"] for lyr in data["layers"]} == {lyr["class"] for lyr in r["layers"]}
    assert data["base_mm"] == r["model"]["base_mm"]
