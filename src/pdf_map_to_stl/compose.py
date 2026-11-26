"""Step 3: classify every primitive, then compute the visible terrain map: which
terrain class is on top at every point of the working area.

Pure vector painter's algorithm, run top-down: the visible part of a primitive is its
painted area minus everything painted later that covers it. Objects (walls, hedges,
trees) and ignored symbols (course, contours) do not take part, so they never cut
holes in the terrain underneath them.

Classes switched off in the settings are resolved here: a terrain class that is off
takes part as the class it merges into (canopy -> paved), an object class that is off
is ignored. ``Classified.source`` keeps the class the symbol rules gave.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from shapely import STRtree
from shapely.geometry import MultiLineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .config import Config, estimate_size_scale
from .scene import Primitive, Scene


@dataclass
class Classified:
    prim: Primitive
    cls: str  # the class it is shown as on the model (``source`` unless switched off)
    isom: str
    role: str  # terrain | object | ignore, on the model
    source: str = ""  # the class the symbol rules gave


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
    # Symbol sizes of this PDF relative to the map the rules were made on (recognition.size_scale).
    cfg.size_scale_used, cfg.size_scale_note = estimate_size_scale(cfg, scene.primitives)
    out = []
    for p in scene.primitives:
        source, isom = cfg.classify(p)
        shown = cfg.shown_as(source)
        out.append(Classified(p, shown or source, isom, cfg.role(shown) if shown else "ignore", source))
    return _lone_dashes(_course_halos(out, cfg), cfg)


def _lone_dashes(items: list[Classified], cfg: Config) -> list[Classified]:
    """A class drawn as a cross (``shape = "cross"``) is two short strokes crossing in an X.
    A stroke its rule matched that is not an X by itself and that no other such stroke
    crosses is a dash of a dashed line (a small path, a fence tick), as rules that go by
    width alone cannot tell on maps with other line widths: it takes the class
    ``recognition.lone_dash_class``."""
    target = cfg.recognition.lone_dash_class
    if target not in cfg.classes:
        raise ValueError(f"recognition.lone_dash_class names an undefined class: {target!r}")
    cand = [i for i, c in enumerate(items) if c.prim.kind == "stroke" and c.prim.lines
            and c.source in cfg.classes and cfg.classes[c.source].shape == "cross"]
    if not cand:
        return items
    shapes = [MultiLineString([list(ln.coords) for ln in items[i].prim.lines]) for i in cand]
    tree = STRtree(shapes)
    shown = cfg.shown_as(target)
    out = list(items)
    for k, i in enumerate(cand):
        own = items[i].prim.lines
        if any(a.intersects(b) for a, b in combinations(own, 2)):
            continue  # an X drawn as one path
        if any(j != k for j in tree.query(shapes[k], predicate="intersects")):
            continue  # the other stroke of its X
        c = items[i]
        out[i] = Classified(c.prim, shown or target, f"{c.isom}: no stroke crosses it, so a dash of a line",
                            cfg.role(shown) if shown else "ignore", target)
    return out


WHITE = (255, 255, 255)
HALO_COVER = 0.1  # a halo is at least this much under a course symbol


def _course_halos(items: list[Classified], cfg: Config) -> list[Classified]:
    """White shapes painted after the whole map, under a course overprint that covers them
    in part, are halos of the overprint (around control numbers and lines), not white
    forest. Map programs draw the course on top of the map; a white area that some maps
    paint late, with no course symbol on it, stays what it is."""
    course = [c for c in items if c.source == "course"]
    others = [c.prim.seqno for c in items if c.source != "course" and c.prim.rgb != WHITE]
    if not course or not others or min(c.prim.seqno for c in course) < max(others):
        return items
    last_map = max(others)
    overprint = unary_union([c.prim.geom for c in course])
    shown = cfg.shown_as("course")

    def halo(c: Classified) -> bool:
        g = c.prim.geom
        return (c.prim.rgb == WHITE and c.prim.seqno > last_map and g.area > 0
                and g.intersection(overprint).area >= HALO_COVER * g.area)

    return [Classified(c.prim, shown or "course", "white halo of the course overprint (painted after the map)",
                       cfg.role(shown) if shown else "ignore", "course") if halo(c) else c for c in items]


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
    terrain = visible_terrain(items, scene.area, background_class)
    objects: dict[str, list[Primitive]] = defaultdict(list)
    for c in items:
        if c.role == "object":
            objects[c.cls].append(c.prim)
    return MapModel(scene, items, terrain, dict(objects), background_class)
