"""Write ``pick.html``: the whole map page as an image, to choose the window to convert.

Drag a rectangle, or click the corners of a polygon, on the page (or type the values);
the page shows the ``--crop`` values (mm from the page's top-left corner) and the full
``build`` command to run.
"""

from __future__ import annotations

import base64
import json
from importlib import resources
from pathlib import Path

import pymupdf

from .scene import PT_TO_MM

PREVIEW_LONG_SIDE_PX = 2400


def write_picker(pdf: Path, out_html: Path, page_number: int = 0) -> None:
    with pymupdf.open(pdf) as doc:
        page = doc[page_number]
        r = page.rect
        zoom = PREVIEW_LONG_SIDE_PX / max(r.width, r.height)
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
        pages = len(doc)
    data = {
        "pdf": str(pdf),
        "page": page_number,
        "pages": pages,
        "width_mm": round(r.width * PT_TO_MM, 2),
        "height_mm": round(r.height * PT_TO_MM, 2),
        "image": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
    }
    template = resources.files(__package__).joinpath("pick_template.html").read_text(encoding="utf-8")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(template.replace("/*__PAGE_DATA__*/null", json.dumps(data)), encoding="utf-8")
