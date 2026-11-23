"""Step 4: tactile layers at print scale, the watertight 3D solid, and the STL file.

Each terrain class and object class becomes a *layer*: its 2D shape in millimetres
plus a height. The solid is the base plate, plus every raised layer extruded on top of
it, minus every recessed layer cut into it, merged by ``manifold3d`` so the result is
always one closed (printable) mesh.

Coordinates: millimetres on the printed model, origin at the bottom-left, y up.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, FillRule, Manifold, OpType
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .compose import MapModel
from .config import Config
from .geometry import polygons
from .scene import PT_TO_MM


@dataclass
class Layer:
    cls: str
    role: str
    height_mm: float
    geom: BaseGeometry  # model mm


@dataclass
class TactileModel:
    width_mm: float
    height_mm: float
    base_mm: float
    scale: float  # model mm per PDF pt
    layers: list[Layer]


def _to_model(g: BaseGeometry, page_rect, scale: float) -> BaseGeometry:
    x0, _, _, y1 = page_rect
    g = affinity.translate(g, -x0, -y1)
    return affinity.scale(g, scale, -scale, origin=(0, 0))


def _drop_small(g: BaseGeometry, min_area: float) -> BaseGeometry:
    keep = [p for p in polygons(g) if p.area >= min_area]
    return unary_union(keep) if keep else Polygon()


def build_layers(
    m: MapModel, cfg: Config, region: tuple[float, float, float, float] | None = None
) -> TactileModel:
    """Tactile layers at print scale. ``region`` (x0, y0, x1, y1 in model mm, origin
    bottom-left) keeps only that rectangle, for printing a small test tile."""
    rect = m.scene.page_rect
    scale = cfg.width_mm / m.scene.width_pt
    w, h = cfg.width_mm, m.scene.height_pt * scale
    frame = box(0, 0, w, h)
    if region is not None:
        frame = frame.intersection(box(*region))
        if frame.is_empty:
            raise ValueError(f"region {region} lies outside the {w:.1f} x {h:.1f} mm model")
    layers: list[Layer] = []
    for cls, g in sorted(m.terrain.items()):
        tc = cfg.classes.get(cls)
        if tc is None or tc.role != "terrain":
            continue
        mg = _drop_small(_to_model(g, rect, scale).intersection(frame), cfg.min_area_mm2)
        if not mg.is_empty:
            layers.append(Layer(cls, "terrain", tc.height_mm, mg))
    for cls, prims in sorted(m.objects.items()):
        tc = cfg.classes[cls]
        parts = []
        for p in prims:
            if p.kind == "stroke" and p.lines:
                # Re-stroke the centreline at a width that can be felt and printed.
                width = max(p.width_mm / PT_TO_MM * scale, tc.min_width_mm)
                lines = [_to_model(ln, rect, scale) for ln in p.lines]
                parts.extend(ln.buffer(width / 2, cap_style="round", join_style="round") for ln in lines)
            else:
                g = _to_model(p.geom, rect, scale)
                minx, miny, maxx, maxy = g.bounds
                short = min(maxx - minx, maxy - miny)
                if short < tc.min_width_mm:
                    g = g.buffer((tc.min_width_mm - short) / 2)
                parts.append(g)
        mg = unary_union(parts).intersection(frame) if parts else Polygon()
        if not mg.is_empty:
            layers.append(Layer(cls, "object", tc.height_mm, mg))
    if region is not None:
        # A test tile: move its corner to the origin so it prints as a small part.
        x0, y0, x1, y1 = frame.bounds
        for layer in layers:
            layer.geom = affinity.translate(layer.geom, -x0, -y0)
        w, h = x1 - x0, y1 - y0
    return TactileModel(w, h, cfg.base_mm, scale, layers)


def _cross_section(g: BaseGeometry) -> CrossSection:
    contours = []
    for p in polygons(g):
        for ring in (p.exterior, *p.interiors):
            pts = np.asarray(ring.coords)[:-1]
            if len(pts) >= 3:
                contours.append(pts)
    return CrossSection(contours, FillRule.EvenOdd) if contours else CrossSection()


def build_solid(t: TactileModel) -> Manifold:
    plate = Manifold.cube((t.width_mm, t.height_mm, t.base_mm))
    raised = [plate]
    recessed = []
    for layer in t.layers:
        if layer.height_mm == 0:
            continue
        cs = _cross_section(layer.geom)
        if cs.is_empty():
            continue
        if layer.height_mm > 0:
            raised.append(cs.extrude(layer.height_mm).translate((0, 0, t.base_mm)))
        else:
            depth = min(-layer.height_mm, t.base_mm - 0.4)  # keep at least 0.4 mm of floor
            recessed.append(cs.extrude(depth + 0.01).translate((0, 0, t.base_mm - depth)))
    solid = Manifold.batch_boolean(raised, OpType.Add)
    if recessed:
        solid = solid - Manifold.batch_boolean(recessed, OpType.Add)
    return solid


def write_stl(solid: Manifold, path: str | Path) -> dict:
    mesh = solid.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3].astype(np.float32)
    f = np.asarray(mesh.tri_verts, dtype=np.int64)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, norm, out=np.zeros_like(n), where=norm > 0).astype(np.float32)
    rec = np.zeros(len(f), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    path = Path(path)
    with path.open("wb") as fh:
        fh.write(b"pdf-map-to-stl".ljust(80, b" "))
        fh.write(struct.pack("<I", len(f)))
        fh.write(rec.tobytes())
    return {
        "triangles": len(f),
        "vertices": len(v),
        "volume_mm3": round(float(solid.volume()), 3),
        "genus": int(solid.genus()),
        "status": str(solid.status()),
        "bounds_mm": [round(float(x), 3) for x in np.concatenate([v.min(0), v.max(0)])],
    }


def layer_summary(t: TactileModel) -> list[dict]:
    return [
        {
            "class": layer.cls,
            "role": layer.role,
            "height_mm": layer.height_mm,
            "area_mm2": round(layer.geom.area, 3),
            "parts": sum(1 for _ in polygons(layer.geom)),
            "valid": bool(layer.geom.is_valid),
        }
        for layer in t.layers
    ]

