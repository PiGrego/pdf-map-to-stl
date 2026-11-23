"""Step 3: classify every primitive, then compute the visible terrain map: which
terrain class is on top at every point of the working area.

Pure vector painter's algorithm, run top-down: the visible part of a primitive is its
painted area minus everything painted later that covers it. Objects (walls, hedges,
trees) and ignored symbols (course, contours) do not take part, so they never cut
holes in the terrain underneath them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .config import Config
from .scene import Primitive, Scene


@dataclass
class Classified:
    prim: Primitive
    cls: str
    isom: str
    role: str


@dataclass
class MapModel:
    scene: Scene
    items: list[Classified]
    terrain: dict[str, BaseGeometry]  # visible terrain per class, PDF points
    objects: dict[str, list[Primitive]]  # object primitives per class
    background_class: str


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def classify(scene: Scene, cfg: Config) -> list[Classified]:
    out = []
    for p in scene.primitives:
        cls, isom = cfg.classify(p)
        out.append(Classified(p, cls, isom, cfg.role(cls)))
    return out


def visible_terrain(items: list[Classified], page: BaseGeometry, background: str) -> dict[str, BaseGeometry]:
    terr = [c for c in items if c.role == "terrain"]
    geoms = [c.prim.geom for c in terr]
    bounds = np.array([g.bounds for g in geoms]) if geoms else np.zeros((0, 4))
    pieces: dict[str, list[BaseGeometry]] = defaultdict(list)
    for i in range(len(terr) - 1, -1, -1):
        g = geoms[i]
        later = np.arange(i + 1, len(terr))
        if later.size:
            b = bounds[later]
            x0, y0, x1, y1 = bounds[i]
            hit = later[(b[:, 0] <= x1) & (b[:, 2] >= x0) & (b[:, 1] <= y1) & (b[:, 3] >= y0)]
            occluders = [
                geoms[j]
                for j in hit
                # Darken blending only hides what is lighter than the new paint.
                if terr[j].prim.blend != "Darken" or _luminance(terr[j].prim.rgb) <= _luminance(terr[i].prim.rgb)
            ]
            if occluders:
                g = g.difference(unary_union(occluders))
        if not g.is_empty and g.area > 0:
            pieces[terr[i].cls].append(g)
    covered = unary_union(geoms) if geoms else Polygon()
    rest = page.difference(covered)
    if not rest.is_empty:
        pieces[background].append(rest)
    return {cls: unary_union(gs) for cls, gs in pieces.items()}


def build_map(scene: Scene, cfg: Config, background_class: str = "forest") -> MapModel:
    """Classify the scene and compose the visible terrain. Unpainted paper counts as
    ``background_class`` (white = forest in ISOM)."""
    items = classify(scene, cfg)
    page = box(*scene.page_rect)
    terrain = visible_terrain(items, page, background_class)
    objects: dict[str, list[Primitive]] = defaultdict(list)
    for c in items:
        if c.role == "object":
            objects[c.cls].append(c.prim)
    return MapModel(scene, items, terrain, dict(objects), background_class)
