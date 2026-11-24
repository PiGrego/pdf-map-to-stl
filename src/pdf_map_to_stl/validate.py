"""Step 5 (quality check): compare the vector class map with the PDF as rendered.

The PDF and the class map are rasterized in the same frame (PDF points times ``px_per_pt``),
so there is a single coordinate transform and nothing to calibrate. Pixels are compared
only where the PDF shows a pure terrain colour: anti-aliased edges and pixels under
objects or ignored symbols (lines, text, course) are excluded and counted separately.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf
from PIL import Image, ImageDraw
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .compose import MapModel
from .config import Config
from .geometry import polygons

COLOUR_TOL = 6
WHITE = (255, 255, 255)


def class_colours(cfg: Config, background: str) -> dict[str, tuple[int, int, int]]:
    """Display colour per class: ``colour`` from the config, else its first rule's colour."""
    out: dict[str, tuple[int, int, int]] = {}
    for r in cfg.rules:
        out.setdefault(r.cls, r.rgb)
    out.setdefault(background, WHITE)
    for name, tc in cfg.classes.items():
        if tc.colour:
            out[name] = tc.colour
    return out


def rule_colours(cfg: Config) -> dict[str, set[tuple[int, int, int]]]:
    """Every PDF colour that a class can come from (for comparing with the rendered PDF)."""
    out: dict[str, set[tuple[int, int, int]]] = {}
    for r in cfg.rules:
        out.setdefault(r.cls, set()).add(r.rgb)
    return out


def rasterize(g: BaseGeometry, size: tuple[int, int], s: float, origin=(0.0, 0.0)) -> np.ndarray:
    img = Image.new("L", size, 0)
    dw = ImageDraw.Draw(img)
    ox, oy = origin
    for p in sorted(polygons(g), key=lambda q: -q.area):
        dw.polygon([((x - ox) * s, (y - oy) * s) for x, y in p.exterior.coords], fill=255)
        for hole in p.interiors:
            dw.polygon([((x - ox) * s, (y - oy) * s) for x, y in hole.coords], fill=0)
    return np.asarray(img) > 0


@dataclass
class Validation:
    metrics: dict
    per_class: list[dict]
    class_image: Image.Image
    error_image: Image.Image


def validate(m: MapModel, cfg: Config, px_per_pt: float = 10.0) -> Validation:
    x0, y0, _, _ = m.scene.page_rect
    with pymupdf.open(m.scene.path) as doc:
        pix = doc[m.scene.page_number].get_pixmap(
            matrix=pymupdf.Matrix(px_per_pt, px_per_pt), clip=pymupdf.Rect(m.scene.page_rect), alpha=False
        )
    size = (pix.width, pix.height)
    pdf = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(np.int16)

    colours = class_colours(cfg, m.background_class)
    names = sorted(m.terrain)
    ours = np.full((size[1], size[0]), -1, np.int16)
    for k, cls in enumerate(names):
        ours[rasterize(m.terrain[cls], size, px_per_pt, (x0, y0))] = k

    # Which of our classes does each PDF pixel's colour support?
    support = np.zeros((len(names), size[1], size[0]), bool)
    pure = np.zeros((size[1], size[0]), bool)
    dot_classes = {c.cls for c in m.items if c.prim.kind == "dots"}
    sources = rule_colours(cfg)
    for k, cls in enumerate(names):
        accepted = sorted(sources.get(cls, set()) | ({WHITE} if cls == m.background_class else set()))
        if cls in dot_classes:
            accepted.append(WHITE)  # paper shows between the dots
        for rgb in accepted:
            hit = np.max(np.abs(pdf - np.array(rgb, np.int16)), axis=2) <= COLOUR_TOL
            support[k] |= hit
            pure |= hit

    # Exclude pixels under anything that is not terrain, grown by one pixel.
    masks = [c.prim.geom for c in m.items if c.role != "terrain"]
    covered = rasterize(unary_union(masks).buffer(1.0 / px_per_pt), size, px_per_pt, (x0, y0)) if masks else np.zeros_like(pure)

    evaluated = pure & ~covered & (ours >= 0)
    idx = np.clip(ours, 0, None)
    correct = evaluated & np.take_along_axis(support, idx[None], 0)[0]
    total = ours.size
    metrics = {
        "px_per_pt": px_per_pt,
        "image_px": list(size),
        "evaluated_share": round(float(evaluated.sum()) / total, 4),
        "excluded_under_objects_share": round(float(covered.sum()) / total, 4),
        "excluded_not_pure_colour_share": round(float((~pure & ~covered).sum()) / total, 4),
        "accuracy": round(float(correct.sum()) / max(1, int(evaluated.sum())), 5),
    }
    per_class = []
    for k, cls in enumerate(names):
        mine = evaluated & (ours == k)
        per_class.append(
            {
                "class": cls,
                "evaluated_px": int(mine.sum()),
                "agreement": round(float((correct & mine).sum()) / max(1, int(mine.sum())), 5),
            }
        )

    rgb = np.zeros((size[1], size[0], 3), np.uint8)
    for k, cls in enumerate(names):
        rgb[ours == k] = colours.get(cls, WHITE)
    class_image = Image.fromarray(rgb)
    err = (rgb.astype(np.float32) * 0.35 + 165).astype(np.uint8)
    err[~evaluated] = (200, 200, 200)
    err[evaluated & ~correct] = (230, 0, 0)
    return Validation(metrics, per_class, class_image, Image.fromarray(err))
