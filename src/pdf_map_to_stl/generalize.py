"""Tactile generalisation: adjust the layers so the map can be read by touch.

A printed map can show details the finger cannot: hairline strips, passages narrower
than a fingertip, walls so close they feel like one. Tactile cartographers simplify and
exaggerate by hand; this module does the common, safe cases automatically. Terrain
classes keep tiling the map exactly: area is only ever moved from one class to another.

Steps, in order. Each is a setting in ``[generalize]`` or ``[smoothing]`` of the config.

0. ``smoothing.simplify_mm`` (off by default): remove outline detail smaller than this.
1. ``clean_slivers``: terrain strips narrower than ``sliver_mm`` are drawing artefacts
   (fills that do not quite meet). They go to the neighbour they share most edge with.
2. ``open_passages``: where two parts of a raised terrain class (e.g. two buildings)
   are closer than ``tactile.min_gap_mm``, the passage between them is widened to that
   gap by trimming the raised class, so a finger can follow it.
3. ``widen_thin``: raised terrain parts narrower than ``tactile.min_feature_mm`` grow
   into the lower terrain around them until they are about that wide.
4. ``merge_close_objects``: objects of the same class closer than ``merge_gap_mm``
   (double walls, the dashes of a path) merge into one, except classes with
   ``merge_gaps = false`` (trees, which must stay separate). This also fills in the
   inside corners of walls: the most visible rounding the tool does.
5. ``smoothing.round_corners_mm`` (off by default): sharp corners of areas and objects
   are rounded with this radius; a terrain corner goes to the area next to it.

Rounded shapes use ``smoothing.arc_segments`` segments per quarter circle.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import shapely
from shapely import STRtree
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .config import Config
from .geometry import areal, polygons

TINY_MM2 = 0.02  # pieces smaller than this are ignored (numerical dust)
CORNER_AREA = 3.0  # round_corners: removed pieces up to this x radius^2 are corners, not thin parts
GRID = 1e-4  # mm; overlay results are snapped to this grid, which makes them robust


# Overlay helpers: snapped to GRID, and keeping only the area part of the result (snapping
# can leave stray lines or points, which the next overlay would reject).
def _diff(a: BaseGeometry, b: BaseGeometry) -> BaseGeometry:
    return areal(shapely.difference(areal(a), areal(b), grid_size=GRID))


def _union(a: BaseGeometry, b: BaseGeometry) -> BaseGeometry:
    return areal(shapely.union(areal(a), areal(b), grid_size=GRID))


def _inter(a: BaseGeometry, b: BaseGeometry) -> BaseGeometry:
    return areal(shapely.intersection(areal(a), areal(b), grid_size=GRID))


@dataclass
class GeneralizeReport:
    simplified_mm2: float = 0.0  # area that changed class through simplification
    slivers_moved: int = 0
    passages_opened: int = 0
    thin_parts_widened: int = 0
    objects_merged: dict[str, int] = field(default_factory=dict)
    corners_rounded: int = 0

    def as_dict(self) -> dict:
        return {
            "simplified_mm2": round(self.simplified_mm2, 2),
            "slivers_moved": self.slivers_moved,
            "passages_opened": self.passages_opened,
            "thin_parts_widened": self.thin_parts_widened,
            "objects_merged": self.objects_merged,
            "corners_rounded": self.corners_rounded,
        }


class _Terrain:
    """Terrain geometries per class, edited so they always tile the same area."""

    def __init__(self, geoms: dict[str, BaseGeometry], heights: dict[str, float], quad: int):
        self.g = {c: areal(g) for c, g in geoms.items()}
        self.h = heights
        self.quad = quad

    def move(self, piece: BaseGeometry, to: str) -> None:
        if piece.is_empty or piece.area < TINY_MM2:
            return
        for cls in self.g:
            if cls != to and self.g[cls].intersects(piece):
                self.g[cls] = _diff(self.g[cls], piece)
        self.g[to] = _union(self.g[to], piece)

    def give_to_neighbours(self, pieces: list[Polygon], exclude: str) -> int:
        """Move each piece to the class around it most; returns how many were moved."""
        moved = 0
        for piece, shares in zip(pieces, self.neighbour_shares(pieces, exclude)):
            if shares:
                self.move(piece, max(shares, key=shares.get))
                moved += 1
        return moved

    def neighbour_shares(self, pieces: list[Polygon], exclude: str) -> list[dict[str, float]]:
        """For each piece, how much of its surroundings each other class covers."""
        parts, owner = [], []
        for cls, g in self.g.items():
            if cls == exclude:
                continue
            for p in polygons(g):
                parts.append(p)
                owner.append(cls)
        tree = STRtree(parts)
        out = []
        for piece in pieces:
            ring = _diff(piece.buffer(0.1, self.quad), piece)
            shares: dict[str, float] = defaultdict(float)
            for i in tree.query(ring):
                shares[owner[i]] += _inter(ring, parts[i]).area
            out.append(shares)
        return out


def _thin_parts(g: BaseGeometry, width: float, min_area: float, quad: int) -> list[Polygon]:
    opened = g.buffer(-0.45 * width, quad).buffer(0.45 * width, quad)
    return [p for p in polygons(_diff(g, opened.buffer(0.01))) if p.area >= min_area]


def _gaps(g: BaseGeometry, gap: float, min_area: float, quad: int) -> list[Polygon]:
    closed = g.buffer(0.45 * gap, quad).buffer(-0.45 * gap, quad)
    return [p for p in polygons(_diff(closed, g.buffer(0.01))) if p.area >= min_area]


def _corners(g: BaseGeometry, radius: float, quad: int) -> list[Polygon]:
    """Sharp corners of ``g``: what an opening with ``radius`` removes, keeping only small
    pieces (corners), not whole parts narrower than the radius."""
    opened = g.buffer(-radius, quad).buffer(radius, quad)
    return [p for p in polygons(_diff(g, opened)) if TINY_MM2 < p.area <= CORNER_AREA * radius**2]


def _simplify_terrain(t: _Terrain, tol: float) -> float:
    """Simplify every terrain class, then make them tile again: overlaps go to the higher
    class, gaps to the class around them. Returns the area that changed class."""
    before = dict(t.g)
    total = areal(shapely.union_all(list(before.values()), grid_size=GRID))
    placed: BaseGeometry = Polygon()
    out = {}
    for cls in sorted(before, key=lambda c: -t.h[c]):
        g = _diff(_inter(before[cls].simplify(tol, preserve_topology=True), total), placed)
        out[cls] = g
        placed = _union(placed, g)
    t.g = out
    t.give_to_neighbours([p for p in polygons(_diff(total, placed)) if p.area > TINY_MM2 / 10], exclude="")
    return sum(_diff(before[c], t.g.get(c, Polygon())).area for c in before)


def generalize(terrain: dict[str, BaseGeometry], heights: dict[str, float], objects: dict[str, BaseGeometry],
               cfg: Config) -> tuple[dict[str, BaseGeometry], dict[str, BaseGeometry], GeneralizeReport]:
    s, r, sm = cfg.generalize, cfg.tactile, cfg.smoothing
    quad = max(1, sm.arc_segments)
    rep = GeneralizeReport()
    t = _Terrain(terrain, heights, quad)

    if sm.simplify_mm > 0:
        rep.simplified_mm2 = _simplify_terrain(t, sm.simplify_mm)
        objects = {c: g if cfg.shape(c) else areal(g.simplify(sm.simplify_mm, preserve_topology=True))
                   for c, g in objects.items()}

    if s.clean_slivers:
        for cls in sorted(t.g, key=lambda c: t.h[c]):
            rep.slivers_moved += t.give_to_neighbours(_thin_parts(t.g[cls], s.sliver_mm, TINY_MM2, quad), cls)

    if s.open_passages:
        for cls in sorted((c for c in t.g if t.h[c] > 0), key=lambda c: -t.h[c]):
            for piece in _gaps(t.g[cls], r.min_gap_mm, 0.1 * r.min_gap_mm**2, quad):
                inside = {c: _inter(piece, t.g[c]).area for c in t.g if c != cls}
                fill = max(inside, key=inside.get) if any(inside.values()) else None
                if fill is None or t.h[fill] >= t.h[cls]:
                    continue  # not a passage through lower ground
                width = 2 * piece.area / max(piece.length, 1e-6)  # strip width ~ 2 * area / perimeter
                pad = max(0.0, (r.min_gap_mm - width) / 2)
                carve = _inter(piece.buffer(pad, quad), t.g[cls])
                if not carve.is_empty and carve.area > TINY_MM2:
                    t.move(carve, fill)
                    rep.passages_opened += 1

    if s.widen_thin:
        for cls in sorted((c for c in t.g if t.h[c] > 0), key=lambda c: -t.h[c]):
            thin = _thin_parts(t.g[cls], r.min_feature_mm, 0.1 * r.min_feature_mm**2, quad)
            if not thin:
                continue
            lower = areal(shapely.union_all([areal(g) for c, g in t.g.items() if t.h[c] < t.h[cls]], grid_size=GRID))
            for piece in thin:
                grow = _inter(piece.buffer(r.min_feature_mm / 2, quad), lower)
                if not grow.is_empty and grow.area > TINY_MM2:
                    t.move(grow, cls)
                    rep.thin_parts_widened += 1

    merged = {}
    for cls, g in objects.items():
        tc = cfg.classes.get(cls)
        if s.merge_close_objects and s.merge_gap_mm > 0 and tc is not None and tc.merge_gaps:
            closed = g.buffer(0.5 * s.merge_gap_mm, quad).buffer(-0.5 * s.merge_gap_mm, quad)
            before = sum(1 for _ in polygons(g))
            g = _union(g, closed)
            after = sum(1 for _ in polygons(g))
            if after < before:
                rep.objects_merged[cls] = before - after
        merged[cls] = g

    if sm.round_corners_mm > 0:
        for cls in sorted(t.g, key=lambda c: -t.h[c]):
            rep.corners_rounded += t.give_to_neighbours(_corners(t.g[cls], sm.round_corners_mm, quad), cls)
        for cls, g in merged.items():
            if cfg.shape(cls):
                continue  # standard symbols keep their designed shape
            corners = _corners(g, sm.round_corners_mm, quad)
            if corners:
                merged[cls] = _diff(g, shapely.union_all(corners))
                rep.corners_rounded += len(corners)

    cleaned = {c: g for c, g in t.g.items() if not g.is_empty and g.area > TINY_MM2}
    return cleaned, merged, rep
