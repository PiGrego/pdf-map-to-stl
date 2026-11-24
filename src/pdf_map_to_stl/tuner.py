"""Write ``tuner.html``: choose the heights of the tactile model.

The page has a 3D view for sighted users and, for everyone, a fully labelled form: a
height field per layer and for the base, a model summary table that updates as heights
change, the tactile-check results, and fields to type a test-tile rectangle. Everything
works with the keyboard and a screen reader. Changing a height only moves meshes in the
browser; nothing is recomputed in Python. When the heights are right, the page
downloads ``heights.toml``, which the CLI applies with ``--heights``.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .config import Config
from .geometry import polygons
from .model3d import TactileModel
from .tactile_check import summary_lines

SIMPLIFY_MM = 0.03  # display only; the STL uses the full geometry


def _rings(g) -> list[list[list[list[float]]]]:
    out = []
    for p in polygons(g.simplify(SIMPLIFY_MM, preserve_topology=True)):
        rings = [p.exterior, *p.interiors]
        out.append([[[round(x, 3), round(y, 3)] for x, y in r.coords[:-1]] for r in rings])
    return out


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in rgb))


def tuner_data(t: TactileModel, colours: dict, pdf_name: str, config_name: str, cfg: Config, check: dict) -> dict:
    layers = []
    for layer in t.layers:
        tc = cfg.classes.get(layer.on or layer.cls)
        if layer.role == "texture":
            colour = _hex([c * 0.8 for c in colours.get(layer.on, (255, 255, 255))])
        elif layer.role in ("braille", "north", "frame"):
            colour = "#282828"
        else:
            colour = _hex(colours.get(layer.cls, (255, 255, 255)))
        layers.append({
            "class": layer.cls,
            "role": layer.role,
            "on": layer.on,
            "height_mm": layer.height_mm,
            "z0_mm": layer.z0_mm,
            "label": tc.legend_label if tc else layer.cls,
            "texture": tc.texture.describe() if tc and tc.texture else "",
            "min_width_mm": tc.min_width_mm if tc else 0,
            "area_mm2": round(layer.geom.area, 1),
            "parts": sum(1 for _ in polygons(layer.geom)),
            "colour": colour,
            "polygons": _rings(layer.geom),
        })
    return {
        "pdf": pdf_name,
        "config": config_name,
        "width_mm": round(t.width_mm, 3),
        "height_mm": round(t.height_mm, 3),
        "base_mm": t.base_mm,
        "map_box": [round(v, 3) for v in t.map_box],
        "plate": _rings(t.plate)[0],
        "title": t.title,
        "corner_mm": round(t.corner_mm, 1),
        "min_step_mm": cfg.tactile.min_height_step_mm,
        "check_lines": summary_lines(check),
        "check_ok": check["ok"],
        "layers": layers,
    }


def write_tuner(t: TactileModel, colours: dict, path: Path, pdf_name: str, config_name: str,
                cfg: Config, check: dict) -> None:
    template = resources.files(__package__).joinpath("tuner_template.html").read_text(encoding="utf-8")
    data = json.dumps(tuner_data(t, colours, pdf_name, config_name, cfg, check), separators=(",", ":"))
    path.write_text(template.replace("/*__MODEL_DATA__*/null", data), encoding="utf-8")
