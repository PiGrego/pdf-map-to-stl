"""Slopes as terraces (optional, experimental): the ground rises one step at every contour.

Contour lines split the map into bands. Each band is raised ``relief.step_mm`` above
the band below it, like the "layer cake" relief of tactile and 3D maps, so a reader
feels a hill rise and a slope fall under the fingers. Everything on the ground (areas,
textures, walls, trees, water) moves up with its band.

How the bands are found, on the map as drawn:

1. **Contour lines**: strokes of the classes in ``relief.classes`` (the brown contour
   rule) at least ``relief.min_width_mm`` wide on the page, so dashed form lines are
   left out. Their pieces are joined; pieces shorter than 2 mm on the page are slope ticks.
2. **Bands**: contour lines are often interrupted where a path or a building crosses
   them. Every loose end is extended along its direction, up to ``relief.close_gaps_mm``
   on the page, until it meets another contour or the window's edge; ends near the
   window's edge are joined to it. The lines then split the window into bands.
3. **Which way is up**: a map does not print the height of each band, so it is inferred:
   the bands that hold water (lakes, canals: ``relief.low = "water"``) are the lowest,
   and the ground rises by one step at every contour crossed going away from them. A
   slope tick (a short stroke on a contour, pointing downhill) reverses that where it
   says so. This fits ground that slopes one way, with hills inside closed contours; it
   can be wrong for a valley between two hills without ticks, so check the result.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from .compose import MapModel
from .config import Config
from .geometry import polygons
from .scene import PT_TO_MM

MM = 1 / PT_TO_MM  # PDF points per mm on the page
TICK_MAX_MM = 2.0  # a contour piece shorter than this is a slope tick
SNAP_PT = 0.02  # contour pieces closer than this join into one line
EDGE_JOIN_MM = 0.5  # a line end this close to the window's edge is joined to it
MIN_BAND_MM2 = 1.0  # bands smaller than this (page mm²) are slivers between lines
MIN_WATER_MM2 = 4.0  # water smaller than this (fountains, wells) does not mark low ground


@dataclass
class Relief:
    bands: list[tuple[BaseGeometry, int]] = field(default_factory=list)  # (area in PDF points, level)
    lines: int = 0
    ticks: int = 0
    note: str = ""  # why there is no relief, if there is none

    @property
    def levels(self) -> int:
        return max((lv for _, lv in self.bands), default=0)


def _contours(m: MapModel, cfg: Config) -> tuple[list[LineString], list[LineString]]:
    """Contour lines (joined, clipped to the window) and slope ticks."""
    r = cfg.relief
    pieces = [ln for c in m.items if c.source in r.classes and c.prim.kind == "stroke"
              and c.prim.width_mm >= r.min_width_mm for ln in c.prim.lines]
    if not pieces:
        return [], []
    merged = shapely.line_merge(shapely.set_precision(unary_union(pieces), SNAP_PT))
    joined = [g for g in getattr(merged, "geoms", [merged]) if g.geom_type == "LineString"]
    ticks = [ln for ln in joined if ln.length < TICK_MAX_MM * MM and not ln.is_closed]
    lines = []
    for ln in joined:
        if ln.length < TICK_MAX_MM * MM and not ln.is_closed:
            continue
        clipped = ln.intersection(m.scene.area)
        lines += [g for g in getattr(clipped, "geoms", [clipped]) if g.geom_type == "LineString" and g.length > 0]
    return lines, ticks


def _close_gaps(lines: list[LineString], window: BaseGeometry, limit: float) -> list[LineString]:
    """Short segments that join each loose line end to the next line or the window's edge."""
    edge = window.exterior if window.geom_type == "Polygon" else window.boundary
    network = unary_union(lines + [edge])
    out = []
    for ln in lines:
        if ln.is_closed or len(ln.coords) < 2:
            continue
        for end, prev in ((ln.coords[-1], ln.coords[-2]), (ln.coords[0], ln.coords[1])):
            p = Point(end)
            if p.distance(edge) < EDGE_JOIN_MM * MM:
                q = edge.interpolate(edge.project(p))
                if p.distance(q) > 1e-9:
                    out.append(LineString([end, q.coords[0]]))
                continue
            d = np.subtract(end, prev)
            n = float(np.hypot(*d))
            if n == 0:
                continue
            u = d / n
            ray = LineString([tuple(np.add(end, u * 0.02 * MM)), tuple(np.add(end, u * limit))])
            hit = ray.intersection(network)
            if hit.is_empty:
                continue  # nothing within reach: the gap stays open
            points = [g for g in getattr(hit, "geoms", [hit]) if g.geom_type == "Point"] or [hit.representative_point()]
            q = min(points, key=p.distance)
            out.append(LineString([end, q.coords[0]]))
    return out


def find_relief(m: MapModel, cfg: Config) -> Relief:
    """The bands between contour lines, each with its level (0 = lowest)."""
    r = cfg.relief
    window = m.scene.area
    lines, ticks = _contours(m, cfg)
    if not lines:
        return Relief(note="no contour lines in the window")
    joins = _close_gaps(lines, window, r.close_gaps_mm * MM)
    edge = window.exterior if window.geom_type == "Polygon" else window.boundary
    bands = [b for b in polygonize(unary_union(lines + joins + [edge]))
             if b.area > MIN_BAND_MM2 * MM**2 and window.contains(b.representative_point())]
    if len(bands) < 2:
        return Relief(lines=len(lines), ticks=len(ticks), note="the contour lines do not split the window into bands")

    # Which bands meet along which contour line.
    tree = shapely.STRtree(bands)
    neighbours: dict[int, set[tuple[int, int]]] = {i: set() for i in range(len(bands))}
    for li, ln in enumerate(lines):
        zone = ln.buffer(0.05 * MM)
        touching = [j for j in tree.query(ln.buffer(0.3 * MM), predicate="intersects")
                    if bands[j].boundary.intersection(zone).length > 0.5 * MM]
        for a in touching:
            for b in touching:
                if a != b:
                    neighbours[a].add((b, li))

    # Slope ticks: the band a tick points into is the lower one across its contour.
    lower: set[tuple[int, int]] = set()  # (line, band) pairs
    for t in ticks:
        a, b = Point(t.coords[0]), Point(t.coords[-1])
        li = min(range(len(lines)), key=lambda i: lines[i].distance(t))
        if lines[li].distance(t) > 0.2 * MM:
            continue
        tip = b if lines[li].distance(a) < lines[li].distance(b) else a
        for j in tree.query(tip, predicate="intersects"):
            lower.add((li, j))

    # Levels: 0 where the water is, one step up for every contour crossed away from it.
    water = unary_union([g for c in m.items if c.cls == "water" for g in polygons(c.prim.geom)
                         if g.area > MIN_WATER_MM2 * MM**2])
    seeds = [i for i, b in enumerate(bands) if not water.is_empty and b.intersects(water)]
    if not seeds:
        return Relief(lines=len(lines), ticks=len(ticks),
                      note="no water in the window to tell low ground from high (relief.low = \"water\")")
    level = {i: 0 for i in seeds}
    queue = deque(seeds)
    while queue:
        a = queue.popleft()
        for b, li in sorted(neighbours[a]):
            if b in level:
                continue
            level[b] = level[a] - 1 if (li, b) in lower else level[a] + 1
            queue.append(b)
    low = min(level.values())
    out = [(bands[i], min(lv - low, r.max_levels)) for i, lv in level.items()]
    return Relief(out, len(lines), len(ticks))
