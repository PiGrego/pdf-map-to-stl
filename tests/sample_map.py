"""The map the end-to-end tests run on: the Navile sprint map (ISSprOM, printed at 1:5000),
a real map exported from OCAD. Most tests use a 50 x 37 mm part of the page (``CROP_MM``)
to stay fast."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAVILE = ROOT / "samples" / "orienteering-map-sample-Navile.pdf"
CROP_MM = (70.0, 190.0, 120.058, 226.926)  # mm from the page's top-left corner
TEST_WIDTH_MM = 120.0  # a fixed, small print width keeps most tests fast; real builds use
                       # the suggested size (tests/test_size.py)
