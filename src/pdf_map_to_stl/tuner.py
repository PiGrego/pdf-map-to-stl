"""Write ``tuner.html``: choose heights, textures and which features the model shows.

The page has a 3D view for sighted users and, for everyone, a fully labelled form: per
class a switch (show it or not), its height, its texture (areas) or symbol shape
(objects); global switches for textures and standard symbols; the base thickness; a
summary table and the tactile-check results; and fields to type a test-tile rectangle.
Everything works with the keyboard and a screen reader.

Heights and switching objects off show at once in the 3D view (only meshes move in the
browser). Texture, shape and area switches need a new build, and the page says so.
When the values are right, the page downloads ``settings.toml``; the build command it
shows applies it with ``--settings``.
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


def _class_row(cls: str, cfg: Config, colours: dict, areas: dict) -> dict:
    tc = cfg.classes[cls]
    texture = (tc.texture.name or "custom") if tc.texture else "none"
    return {
        "class": cls,
        "role": tc.role,
        "label": tc.legend_label,
        "colour": _hex(colours.get(cls, (255, 255, 255))),
        "enabled": tc.enabled,
        "merge_into": tc.merge_into,
        "merge_label": cfg.classes[tc.merge_into].legend_label if tc.merge_into else "",
        "height_mm": tc.height_mm,
        "texture": texture,
        "texture_text": tc.texture.describe() if tc.texture else "smooth",
        "shape": tc.shape or "as_drawn",
        "point_symbol": bool(tc.shape),
        "size_mm": tc.size_mm,
        "min_width_mm": tc.min_width_mm,
        "area_mm2": round(areas.get(cls, 0.0), 1),
        "on_model": cls in areas,
    }


def tuner_data(t: TactileModel, colours: dict, pdf_name: str, cfg: Config, check: dict,
               switchable: list[str], command: str = "") -> dict:
    layers = []
    for layer in t.layers:
        if layer.role == "texture":
            colour = _hex([c * 0.8 for c in colours.get(layer.on, (255, 255, 255))])
        elif layer.role in ("braille", "north", "frame", "edge", "pin", "scale_bar"):
            colour = "#282828"
        else:
            colour = _hex(colours.get(layer.cls, (255, 255, 255)))
        layers.append({
            "class": layer.cls,
            "role": layer.role,
            "on": layer.on,
            "height_mm": layer.height_mm,
            "z0_mm": layer.z0_mm,
            "colour": colour,
            "polygons": _rings(layer.geom),
        })
    areas = {lyr.cls: lyr.geom.area for lyr in t.tactile_layers()}
    names = sorted(set(switchable) | set(areas))
    return {
        "pdf": pdf_name,
        "config": ", then ".join(cfg.sources),
        "command": command or f"pdf-map-to-stl build {pdf_name} --settings settings.toml",
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
        "features": {"textures": cfg.features.textures, "standard_symbols": cfg.features.standard_symbols},
        "texture_library": [{"name": n, "text": tex.describe()} for n, tex in cfg.textures.items()],
        "classes": [_class_row(c, cfg, colours, areas) for c in names],
        "layers": layers,
    }


def write_tuner(t: TactileModel, colours: dict, path: Path, pdf_name: str, cfg: Config, check: dict,
                switchable: list[str], command: str = "") -> None:
    template = resources.files(__package__).joinpath("tuner_template.html").read_text(encoding="utf-8")
    data = json.dumps(tuner_data(t, colours, pdf_name, cfg, check, switchable, command), separators=(",", ":"))
    path.write_text(template.replace("/*__MODEL_DATA__*/null", data), encoding="utf-8")
