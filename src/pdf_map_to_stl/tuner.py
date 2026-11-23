"""Write ``tuner.html``: an interactive 3D view of the tactile model for choosing heights.

The page shows every tactile layer extruded on the base plate, with a slider per layer
and for the base. Changing a slider only moves meshes in the browser; nothing is
recomputed in Python. When the heights feel right, the page downloads ``heights.toml``,
which the CLI applies with ``--heights``. The page can also pick a rectangle for a
small test print (``--region``).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .geometry import polygons
from .model3d import TactileModel

SIMPLIFY_MM = 0.03  # display only; the STL uses the full geometry


def _rings(g) -> list[list[list[list[float]]]]:
    out = []
    for p in polygons(g.simplify(SIMPLIFY_MM, preserve_topology=True)):
        rings = [p.exterior, *p.interiors]
        out.append([[[round(x, 3), round(y, 3)] for x, y in r.coords[:-1]] for r in rings])
    return out


def tuner_data(t: TactileModel, colours: dict, pdf_name: str, config_name: str) -> dict:
    return {
        "pdf": pdf_name,
        "config": config_name,
        "width_mm": round(t.width_mm, 3),
        "height_mm": round(t.height_mm, 3),
        "base_mm": t.base_mm,
        "layers": [
            {
                "class": layer.cls,
                "role": layer.role,
                "height_mm": layer.height_mm,
                "colour": "#{:02x}{:02x}{:02x}".format(*colours.get(layer.cls, (255, 255, 255))),
                "polygons": _rings(layer.geom),
            }
            for layer in t.layers
        ],
    }


def write_tuner(t: TactileModel, colours: dict, path: Path, pdf_name: str, config_name: str) -> None:
    template = resources.files(__package__).joinpath("tuner_template.html").read_text(encoding="utf-8")
    data = json.dumps(tuner_data(t, colours, pdf_name, config_name), separators=(",", ":"))
    path.write_text(template.replace("/*__MODEL_DATA__*/null", data), encoding="utf-8")
