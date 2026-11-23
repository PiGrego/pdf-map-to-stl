"""The generated HTML pages carry their data and nothing is left of the placeholders."""

import json
import re
from pathlib import Path

from pdf_map_to_stl.pick import write_picker
from pdf_map_to_stl.pipeline import BuildOptions, build

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample.pdf"


def _embedded_json(html: str, var: str) -> dict:
    m = re.search(rf"const {var} = (\{{.*?\}});\n", html, re.DOTALL)
    assert m, f"{var} not found"
    return json.loads(m.group(1))


def test_picker_page_has_page_image_and_size(tmp_path):
    out = tmp_path / "pick.html"
    write_picker(SAMPLE, out)
    html = out.read_text(encoding="utf-8")
    assert "__PAGE_DATA__" not in html
    data = _embedded_json(html, "PAGE")
    assert data["image"].startswith("data:image/png;base64,")
    assert data["width_mm"] > 0 and data["height_mm"] > 0


def test_tuner_page_lists_every_layer(tmp_path):
    r = build(BuildOptions(SAMPLE, tmp_path, validate=False))
    html = (tmp_path / "tuner.html").read_text(encoding="utf-8")
    assert "__MODEL_DATA__" not in html
    data = _embedded_json(html, "MODEL")
    assert {lyr["class"] for lyr in data["layers"]} == {lyr["class"] for lyr in r["layers"]}
    assert data["base_mm"] == r["model"]["base_mm"]
