"""Tactile generalisation: adjust the layers so the map can be read by touch.

A printed map can show details the finger cannot: hairline strips, passages narrower
than a fingertip, walls so close they feel like one. Tactile cartographers simplify and
exaggerate by hand; this module does the common, safe cases automatically. Terrain
classes keep tiling the map exactly: area is only ever moved from one class to another.

Steps, in order (each can be switched off in ``[tactile]`` of the config):

1. ``clean_slivers``: terrain strips narrower than ``sliver_mm`` are drawing artefacts
   (fills that do not quite meet). They go to the neighbour they share most edge with.
2. ``open_passages``: where two parts of a raised terrain class (e.g. two buildings)
   are closer than ``min_gap_mm``, the passage between them is widened to that gap by
   trimming the raised class, so a finger can follow it.
3. ``widen_thin``: raised terrain parts narrower than ``min_feature_mm`` grow into the
   lower terrain around them until they are about that wide.
4. ``merge_close_objects``: objects of the same class closer than ``min_gap_mm`` (double
   walls, hedge segments) merge into one, except classes with ``merge_gaps = false``
   (trees, which must stay separate).
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
QUAD = 4  # buffer resolution: corners are rounded with 4 segments per quarter circle
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
    slivers_moved: int = 0
    passages_opened: int = 0
    thin_parts_widened: int = 0
    objects_merged: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "slivers_moved": self.slivers_moved,
            "passages_opened": self.passages_opened,
            "thin_parts_widened": self.thin_parts_widened,
            "objects_merged": self.objects_merged,
        }


class _Terrain:
    """Terrain geometries per class, edited so they always tile the same area."""

    def __init__(self, geoms: dict[str, BaseGeometry], heights: dict[str, float]):
        self.g = {c: areal(g) for c, g in geoms.items()}
        self.h = heights

    def move(self, piece: BaseGeometry, to: str) -> None:
        if piece.is_empty or piece.area < TINY_MM2:
            return
        for cls in self.g:
            if cls != to and self.g[cls].intersects(piece):
                self.g[cls] = _diff(self.g[cls], piece)
        self.g[to] = _union(self.g[to], piece)

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
            ring = _diff(piece.buffer(0.1, QUAD), piece)
            shares: dict[str, float] = defaultdict(float)
            for i in tree.query(ring):
                shares[owner[i]] += _inter(ring, parts[i]).area
            out.append(shares)
        return out


def _thin_parts(g: BaseGeometry, width: float, min_area: float) -> list[Polygon]:
    opened = g.buffer(-0.45 * width, QUAD).buffer(0.45 * width, QUAD)
    return [p for p in polygons(_diff(g, opened.buffer(0.01))) if p.area >= min_area]


def _gaps(g: BaseGeometry, gap: float, min_area: float) -> list[Polygon]:
    closed = g.buffer(0.45 * gap, QUAD).buffer(-0.45 * gap, QUAD)
    return [p for p in polygons(_diff(closed, g.buffer(0.01))) if p.area >= min_area]


def generalize(terrain: dict[str, BaseGeometry], heights: dict[str, float], objects: dict[str, BaseGeometry],
               cfg: Config) -> tuple[dict[str, BaseGeometry], dict[str, BaseGeometry], GeneralizeReport]:
    r = cfg.tactile
    rep = GeneralizeReport()
    t = _Terrain(terrain, heights)

    if r.clean_slivers:
        for cls in sorted(t.g, key=lambda c: t.h[c]):
            slivers = _thin_parts(t.g[cls], r.sliver_mm, TINY_MM2)
            for piece, shares in zip(slivers, t.neighbour_shares(slivers, cls)):
                if shares:
                    t.move(piece, max(shares, key=shares.get))
                    rep.slivers_moved += 1

    if r.open_passages:
        for cls in sorted((c for c in t.g if t.h[c] > 0), key=lambda c: -t.h[c]):
            for piece in _gaps(t.g[cls], r.min_gap_mm, 0.1 * r.min_gap_mm**2):
                inside = {c: _inter(piece, t.g[c]).area for c in t.g if c != cls}
                fill = max(inside, key=inside.get) if any(inside.values()) else None
                if fill is None or t.h[fill] >= t.h[cls]:
                    continue  # not a passage through lower ground
                width = 2 * piece.area / max(piece.length, 1e-6)  # strip width ~ 2 * area / perimeter
                pad = max(0.0, (r.min_gap_mm - width) / 2)
                carve = _inter(piece.buffer(pad, QUAD), t.g[cls])
                if not carve.is_empty and carve.area > TINY_MM2:
                    t.move(carve, fill)
                    rep.passages_opened += 1

    if r.widen_thin:
        for cls in sorted((c for c in t.g if t.h[c] > 0), key=lambda c: -t.h[c]):
            thin = _thin_parts(t.g[cls], r.min_feature_mm, 0.1 * r.min_feature_mm**2)
            if not thin:
                continue
            lower = areal(shapely.union_all([areal(g) for c, g in t.g.items() if t.h[c] < t.h[cls]], grid_size=GRID))
            for piece in thin:
                grow = _inter(piece.buffer(r.min_feature_mm / 2, QUAD), lower)
                if not grow.is_empty and grow.area > TINY_MM2:
                    t.move(grow, cls)
                    rep.thin_parts_widened += 1

    merged = {}
    for cls, g in objects.items():
        tc = cfg.classes.get(cls)
        if r.merge_close_objects and tc is not None and tc.merge_gaps:
            closed = g.buffer(0.5 * r.min_gap_mm, QUAD).buffer(-0.5 * r.min_gap_mm, QUAD)
            before = sum(1 for _ in polygons(g))
            g = _union(g, closed)
            after = sum(1 for _ in polygons(g))
            if after < before:
                rep.objects_merged[cls] = before - after
        merged[cls] = g

    cleaned = {c: g for c, g in t.g.items() if not g.is_empty and g.area > TINY_MM2}
    return cleaned, merged, rep
