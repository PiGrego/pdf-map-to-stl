"""The tactile legend: a separate small plate that explains the map by touch.

One row per class used in the map: a sample of the class (its height and texture, or
the shape of the object) followed by its name in Braille. The first line is the word
"key" in Braille, and the top-right corner is cut like on the map, so both plates are
held the same way.
"""

from __future__ import annotations

import statistics

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from . import braille
from .config import Config
from .geometry import polygons
from .model3d import EDGE_PAD_MM, Layer, TactileModel, texture_geometry

SWATCH_W_MM = 16.0
SWATCH_H_MM = 10.0
LABEL_GAP_MM = 6.0
LEGEND_TITLE = "key"


def legend_rows(t: TactileModel, cfg: Config) -> list[Layer]:
    """The map's classes in reading order: terrain from low to high, then objects."""
    terrain = sorted((lyr for lyr in t.layers if lyr.role == "terrain"), key=lambda lyr: lyr.height_mm)
    objects = sorted((lyr for lyr in t.layers if lyr.role == "object"), key=lambda lyr: lyr.height_mm)
    return terrain + objects


def build_legend(t: TactileModel, cfg: Config) -> TactileModel:
    spec = cfg.braille
    rows = legend_rows(t, cfg)
    labels = [cfg.classes[r.cls].legend_label for r in rows]
    label_w = max([braille.width_mm(s, spec) for s in labels + [LEGEND_TITLE]])
    row_h = max(SWATCH_H_MM, spec.cell_height_mm) + 5.0
    title_h = spec.cell_height_mm + 5.0
    w = 2 * EDGE_PAD_MM + SWATCH_W_MM + LABEL_GAP_MM + label_w
    h = 2 * EDGE_PAD_MM + title_h + len(rows) * row_h

    layers: list[Layer] = []
    dots = braille.dot_centres(LEGEND_TITLE, spec, EDGE_PAD_MM, h - EDGE_PAD_MM)
    for i, (row, label) in enumerate(zip(rows, labels)):
        cy = h - EDGE_PAD_MM - title_h - (i + 0.5) * row_h
        x0 = EDGE_PAD_MM
        tc = cfg.classes[row.cls]
        if row.role == "terrain":
            sample = box(x0, cy - SWATCH_H_MM / 2, x0 + SWATCH_W_MM, cy + SWATCH_H_MM / 2)
        else:
            sample = _object_sample(row, tc.min_width_mm, x0, cy)
        layers.append(Layer(row.cls, row.role, row.height_mm, sample))
        if tc.texture and row.height_mm >= 0:
            tex = texture_geometry(sample, tc.texture)
            if not tex.is_empty:
                layers.append(Layer(f"{row.cls} texture", "texture", row.height_mm + tc.texture.height_mm, tex,
                                    z0_mm=row.height_mm, on=row.cls))
        dots += braille.dot_centres(label, spec, x0 + SWATCH_W_MM + LABEL_GAP_MM, cy + spec.cell_height_mm / 2)

    plate = box(0, 0, w, h)
    c = min(cfg.orientation_corner_mm, w / 3, h / 3)
    if c > 0:
        plate = plate.difference(Polygon([(w - c, h), (w + 1, h + 1), (w, h - c)]))
    r = spec.dot_diameter_mm / 2
    layers.append(Layer("braille", "braille", spec.dot_height_mm, unary_union([Point(p).buffer(r, 8) for p in dots])))
    return TactileModel(w, h, cfg.base_mm, 1.0, layers, plate, (0.0, 0.0, w, h), dots, spec, LEGEND_TITLE, c)


def _object_sample(layer: Layer, min_width: float, x0: float, cy: float):
    """Point-like objects (trees) as one typical dot; line-like ones (walls) as a bar."""
    sizes = [max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p in polygons(layer.geom)]
    typical = statistics.median(sizes) if sizes else min_width
    width = max(min_width, 1.0)
    if typical < 3 * width:
        return Point(x0 + SWATCH_W_MM / 2, cy).buffer(max(typical, width) / 2, 16)
    return box(x0, cy - width / 2, x0 + SWATCH_W_MM, cy + width / 2)
