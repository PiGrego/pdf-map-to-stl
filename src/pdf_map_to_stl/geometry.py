"""PDF path items (as returned by PyMuPDF ``get_drawings``) to Shapely geometry.

All coordinates stay in PDF points in the page frame PyMuPDF uses for drawings and
rendering (origin top-left, y down). Nothing here rasterizes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np
from shapely import make_valid
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

Point2 = tuple[float, float]

# Maximum chord length (pt) when flattening Bezier curves. 0.1 pt = 0.035 mm on the PDF page.
CURVE_STEP_PT = 0.1
_MAX_CURVE_SEGMENTS = 64

# PDF line cap / join codes -> Shapely buffer styles.
_CAP = {0: "flat", 1: "round", 2: "square"}
_JOIN = {0: "mitre", 1: "round", 2: "bevel"}
PDF_MITER_LIMIT = 10.0


def _xy(p) -> Point2:
    return (float(p.x), float(p.y))


def flatten_cubic(p0: Point2, p1: Point2, p2: Point2, p3: Point2) -> list[Point2]:
    """Points along a cubic Bezier, excluding p0, with chords of about CURVE_STEP_PT."""
    ctrl = np.array([p0, p1, p2, p3])
    length = float(np.sum(np.hypot(*np.diff(ctrl, axis=0).T)))
    n = max(2, min(_MAX_CURVE_SEGMENTS, math.ceil(length / CURVE_STEP_PT)))
    t = np.linspace(0.0, 1.0, n + 1)[1:, None]
    pts = (
        (1 - t) ** 3 * ctrl[0]
        + 3 * (1 - t) ** 2 * t * ctrl[1]
        + 3 * (1 - t) * t**2 * ctrl[2]
        + t**3 * ctrl[3]
    )
    return [tuple(p) for p in pts]


def subpaths(items: Sequence, close_path: bool = False) -> list[tuple[list[Point2], bool]]:
    """Split PyMuPDF path items into polylines.

    Returns ``(points, closed)`` pairs. A new subpath starts when an item does not begin
    where the previous one ended. ``re`` and ``qu`` items are always closed subpaths.
    ``close_path`` marks the last open subpath as closed (PDF ``h`` operator).
    """
    out: list[tuple[list[Point2], bool]] = []
    cur: list[Point2] = []

    def flush(closed: bool = False) -> None:
        nonlocal cur
        if len(cur) >= 2:
            if np.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 1e-6 and len(cur) > 2:
                closed = True
            out.append((cur, closed))
        cur = []

    for it in items:
        kind = it[0]
        if kind == "re":
            flush()
            r = it[1]
            out.append(([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], True))
            continue
        if kind == "qu":
            flush()
            q = it[1]
            out.append(([_xy(q.ul), _xy(q.ur), _xy(q.lr), _xy(q.ll)], True))
            continue
        start = _xy(it[1])
        if cur and math.hypot(cur[-1][0] - start[0], cur[-1][1] - start[1]) > 1e-4:
            flush()
        if not cur:
            cur = [start]
        if kind == "l":
            cur.append(_xy(it[2]))
        elif kind == "c":
            cur.extend(flatten_cubic(start, _xy(it[2]), _xy(it[3]), _xy(it[4])))
    flush(close_path)
    if close_path and out:
        pts, _ = out[-1]
        out[-1] = (pts, True)
    return out


def _signed_area(ring: Sequence[Point2]) -> float:
    a = np.asarray(ring)
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def fill_geometry(items: Sequence, even_odd: bool | None) -> BaseGeometry:
    """Area painted by filling a path. Every subpath is implicitly closed for filling."""
    rings = [pts for pts, _ in subpaths(items) if len(pts) >= 3]
    if not rings:
        return Polygon()
    polys = []
    for r in rings:
        g = make_valid(Polygon(r))
        polys.append((g, _signed_area(r)))
    if even_odd:
        geom: BaseGeometry = Polygon()
        for g, _ in polys:
            geom = geom.symmetric_difference(g)
        return _areal(geom)
    # Non-zero winding: largest rings first; a ring wound opposite to the ring that
    # contains it cuts a hole, otherwise it adds area. Exact for nested, non-crossing
    # rings, which is what map software writes.
    polys.sort(key=lambda p: -abs(p[1]))
    geom = Polygon()
    placed: list[tuple[BaseGeometry, float]] = []
    for g, area in polys:
        container = next(
            (pa for pg, pa in reversed(placed) if pg.buffer(1e-6).contains(g)), None
        )
        if container is not None and (container > 0) != (area > 0):
            geom = geom.difference(g)
        else:
            geom = geom.union(g)
        placed.append((g, area))
    return _areal(geom)


def stroke_geometry(
    items: Sequence,
    width: float,
    line_cap: int = 0,
    line_join: int = 0,
    close_path: bool = False,
    min_width: float = 0.0,
) -> BaseGeometry:
    """Area painted by stroking a path with the given width (pt)."""
    w = max(float(width or 0.0), min_width)
    if w <= 0:
        return Polygon()
    parts = []
    for pts, closed in subpaths(items, close_path):
        line = LineString(pts + [pts[0]] if closed else pts)
        if line.length == 0:
            continue
        parts.append(
            line.buffer(
                w / 2,
                cap_style=_CAP.get(line_cap, "flat"),
                join_style=_JOIN.get(line_join, "mitre"),
                mitre_limit=PDF_MITER_LIMIT,
            )
        )
    return _areal(unary_union(parts)) if parts else Polygon()


def centerlines(items: Sequence, close_path: bool = False) -> list[LineString]:
    return [
        LineString(pts + [pts[0]] if closed else pts)
        for pts, closed in subpaths(items, close_path)
        if len(pts) >= 2
    ]


def _areal(g: BaseGeometry) -> BaseGeometry:
    """Keep only the polygonal part of a geometry."""
    if g.is_empty:
        return Polygon()
    if isinstance(g, (Polygon, MultiPolygon)):
        return g if g.is_valid else make_valid(g)
    polys: list[Polygon] = []
    for part in getattr(g, "geoms", []):
        if isinstance(part, Polygon):
            polys.append(part)
        elif isinstance(part, MultiPolygon):
            polys.extend(part.geoms)
    return unary_union(polys) if polys else Polygon()


def polygons(g: BaseGeometry) -> Iterable[Polygon]:
    """Iterate the polygons of any areal geometry."""
    if g.is_empty:
        return
    if isinstance(g, Polygon):
        yield g
    else:
        for part in getattr(g, "geoms", []):
            yield from polygons(part)
