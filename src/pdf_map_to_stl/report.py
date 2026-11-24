"""Human-readable outputs of a build: symbol inventory, 2D layer SVG, report JSON."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .compose import MapModel
from .geometry import polygons
from .model3d import TactileModel
from .scene import PT_TO_MM


def hex_colour(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def symbol_inventory(m: MapModel) -> list[dict]:
    """One row per distinct symbol signature found in the working area, with the class
    the rules gave it, and what it is shown as on the model (empty = not shown; another
    class = merged into it because its own class is switched off). This is the table to
    check when adapting to a new map."""
    rows: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "area_pt2": 0.0})
    for c in m.items:
        p = c.prim
        key = (
            p.kind,
            hex_colour(p.rgb),
            round(p.width_mm, 3) if p.kind == "stroke" else "",
            f"{p.dot_mm:.3f}/{p.pitch_mm:.3f}" if p.kind == "dots" else "",
            c.source or c.cls,
            c.isom,
            c.role,
            c.cls if c.role != "ignore" else "",
        )
        rows[key]["count"] += 1
        rows[key]["area_pt2"] += p.geom.area
    return [
        {
            "kind": kind,
            "rgb": rgb,
            "stroke_mm": width,
            "dot/pitch_mm": dots,
            "class": cls,
            "isom": isom,
            "role": role,
            "shown_as": shown,
            "count": v["count"],
            "area_mm2_on_pdf": round(v["area_pt2"] * PT_TO_MM**2, 3),
        }
        for (kind, rgb, width, dots, cls, isom, role, shown), v in sorted(rows.items(), key=lambda kv: (kv[0][4], kv[0][1]))
    ]


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            return
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def write_layers_svg(t: TactileModel, colours: dict, path: Path) -> None:
    """2D tactile layers at print scale (mm), lowest first, objects outlined."""
    w, h = t.width_mm, t.height_mm
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.3f} {h:.3f}" width="{w:.1f}mm" height="{h:.1f}mm">',
        f'<rect width="{w:.3f}" height="{h:.3f}" fill="#f2f2f2"/>',
    ]
    for layer in sorted(t.layers, key=lambda lyr: (lyr.role == "object", lyr.height_mm)):
        d = []
        for p in polygons(layer.geom):
            for ring in (p.exterior, *p.interiors):
                d.append("M " + " L ".join(f"{x:.3f} {h - y:.3f}" for x, y in ring.coords) + " Z")
        stroke = ' stroke="#000" stroke-width="0.05"' if layer.role == "object" else ""
        fill = hex_colour(colours.get(layer.cls, (255, 255, 255)))
        parts.append(f'<path id="{layer.cls}" fill="{fill}" fill-rule="evenodd"{stroke} d="{" ".join(d)}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
