"""Step 4: tactile layers at print scale, the watertight 3D solid, and the STL file.

Each terrain class and object class becomes a *layer*: its 2D shape in millimetres
plus a height. Some classes also get a *texture* layer (raised dots or ridges on top),
so classes at the same height can still be told apart by touch. The model also carries
what a blind reader needs to use it without help:

* an **orientation corner**: the top-right corner of the plate is cut off, so the
  reader always knows which way is up (north);
* a **Braille title** along the bottom edge, at standard Braille size (never scaled).

The solid is the base plate, plus every raised layer extruded on top of it, minus every
recessed layer cut into it, plus the Braille dots, merged by ``manifold3d`` so the result
is always one closed (printable) mesh.

Coordinates: millimetres on the printed model, origin at the bottom-left, y up.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from manifold3d import CrossSection, FillRule, Manifold, OpType
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import braille
from .compose import MapModel
from .config import Config, Texture
from .generalize import generalize
from .geometry import polygons
from .scene import PT_TO_MM

MIN_FLOOR_MM = 0.4  # a recess always leaves at least this much plate under it
EDGE_PAD_MM = 5.0  # margin around Braille text
MIN_PRINT_AREA_MM2 = 0.05  # polygons smaller than this are numerical dust, not features


@dataclass
class Layer:
    cls: str
    role: str  # "terrain" | "object" | "texture" | "braille"
    height_mm: float  # top above the base plate (negative = recessed)
    geom: BaseGeometry  # model mm
    z0_mm: float = 0.0  # bottom above the base plate (textures sit on their class)
    on: str = ""  # for textures: the class they belong to


@dataclass
class TactileModel:
    width_mm: float
    height_mm: float
    base_mm: float
    scale: float  # model mm per PDF pt
    layers: list[Layer]
    plate: BaseGeometry  # outline of the base plate (with the orientation corner cut)
    map_box: tuple[float, float, float, float]  # where the map sits on the plate
    braille_dots: list[tuple[float, float]] = field(default_factory=list)
    braille_spec: braille.BrailleSpec = field(default_factory=braille.BrailleSpec)
    title: str = ""
    corner_mm: float = 0.0
    generalized: dict = field(default_factory=dict)  # what generalize.py changed

    def tactile_layers(self) -> list[Layer]:
        """Terrain and object layers (the map's content, without textures and Braille)."""
        return [lyr for lyr in self.layers if lyr.role in ("terrain", "object")]


# ----------------------------------------------------------------------------- layers


def _to_model(g: BaseGeometry, page_rect, scale: float) -> BaseGeometry:
    x0, _, _, y1 = page_rect
    g = affinity.translate(g, -x0, -y1)
    return affinity.scale(g, scale, -scale, origin=(0, 0))


def _drop_small(g: BaseGeometry, min_area: float) -> BaseGeometry:
    keep = [p for p in polygons(g) if p.area >= min_area]
    return unary_union(keep) if keep else Polygon()


def build_layers(
    m: MapModel,
    cfg: Config,
    region: tuple[float, float, float, float] | None = None,
    title: str | None = None,
) -> TactileModel:
    """Tactile layers at print scale.

    ``region`` (x0, y0, x1, y1 in map mm, origin bottom-left) keeps only that rectangle,
    for a small test tile (no title strip). ``title`` is the Braille title ("" = none).
    """
    rect = m.scene.page_rect
    scale = cfg.width_mm / m.scene.width_pt
    w, h = cfg.width_mm, m.scene.height_pt * scale
    frame = box(0, 0, w, h)
    if region is not None:
        frame = frame.intersection(box(*region))
        if frame.is_empty:
            raise ValueError(f"region {region} lies outside the {w:.1f} x {h:.1f} mm model")

    layers = _map_layers(m, cfg, rect, scale, frame)
    layers, report = _generalize(layers, cfg)
    x0, y0, x1, y1 = frame.bounds
    w, h = x1 - x0, y1 - y0
    for layer in layers:
        layer.geom = affinity.translate(layer.geom, -x0, -y0)

    # Braille title strip below the map (not on test tiles).
    spec = cfg.braille
    title = "" if region is not None else (title or "")
    lines = braille.wrap(title, _cells_that_fit(w - 2 * EDGE_PAD_MM, spec)) if title else []
    strip = 0.0
    dots: list[tuple[float, float]] = []
    if lines:
        strip = 2 * EDGE_PAD_MM + (len(lines) - 1) * spec.line_spacing_mm + spec.cell_height_mm
        for layer in layers:
            layer.geom = affinity.translate(layer.geom, 0, strip)
        for i, line in enumerate(lines):
            dots += braille.dot_centres(line, spec, EDGE_PAD_MM, strip - EDGE_PAD_MM - i * spec.line_spacing_mm)

    total_h = h + strip
    plate = box(0, 0, w, total_h)
    c = min(cfg.orientation_corner_mm, w / 3, total_h / 3)
    if c > 0:
        plate = plate.difference(Polygon([(w - c, total_h), (w + 1, total_h + 1), (w, total_h - c)]))
    layers = [_clip_layer(lyr, plate) for lyr in layers]
    layers = [lyr for lyr in layers if not lyr.geom.is_empty]

    # Textures on top of the classes that have one.
    for layer in list(layers):
        tc = cfg.classes.get(layer.cls)
        if tc and tc.texture and layer.height_mm >= 0:
            tex = texture_geometry(layer.geom, tc.texture)
            if not tex.is_empty:
                layers.append(
                    Layer(f"{layer.cls} texture", "texture", layer.height_mm + tc.texture.height_mm, tex,
                          z0_mm=layer.height_mm, on=layer.cls)
                )
    if dots:
        r = spec.dot_diameter_mm / 2
        layers.append(Layer("braille", "braille", spec.dot_height_mm, unary_union([Point(p).buffer(r, 8) for p in dots])))

    return TactileModel(
        w, total_h, cfg.base_mm, scale, layers, plate, (0.0, strip, w, strip + h), dots, spec, " / ".join(lines), c,
        report.as_dict(),
    )


def _generalize(layers: list[Layer], cfg: Config):
    terrain = {lyr.cls: lyr.geom for lyr in layers if lyr.role == "terrain"}
    heights = {lyr.cls: lyr.height_mm for lyr in layers}
    objects = {lyr.cls: lyr.geom for lyr in layers if lyr.role == "object"}
    terrain, objects, report = generalize(terrain, heights, objects, cfg)
    # Generalising can leave hairline pieces; nothing that small can be printed or felt.
    out = [Layer(c, "terrain", heights[c], _drop_small(g, cfg.min_area_mm2)) for c, g in sorted(terrain.items())]
    out += [Layer(c, "object", heights[c], _drop_small(g, cfg.min_area_mm2)) for c, g in sorted(objects.items())]
    return [lyr for lyr in out if not lyr.geom.is_empty], report


def _map_layers(m: MapModel, cfg: Config, rect, scale: float, frame: BaseGeometry) -> list[Layer]:
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
    return layers


def _clip_layer(layer: Layer, plate: BaseGeometry) -> Layer:
    layer.geom = layer.geom.intersection(plate)
    return layer


def _cells_that_fit(width: float, spec: braille.BrailleSpec) -> int:
    return max(1, int((width - spec.dot_spacing_mm - spec.dot_diameter_mm) // spec.cell_spacing_mm) + 1)


def texture_geometry(area: BaseGeometry, tex: Texture) -> BaseGeometry:
    """Raised pattern inside ``area``, kept clear of its edges so the edge stays crisp.
    The pattern grid is anchored to the model origin, so neighbouring pieces line up."""
    inner = area.buffer(-(tex.size_mm / 2 + 0.3))
    if inner.is_empty:
        return Polygon()
    minx, miny, maxx, maxy = inner.bounds
    p = tex.pitch_mm
    if tex.kind == "dots":
        xs = np.arange(math.floor(minx / p) * p + p / 2, maxx + p, p)
        ys = np.arange(math.floor(miny / p) * p + p / 2, maxy + p, p)
        gx, gy = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(inner, gx.ravel(), gy.ravel())
        pts = np.column_stack([gx.ravel()[inside], gy.ravel()[inside]])
        return unary_union([Point(x, y).buffer(tex.size_mm / 2, 4) for x, y in pts]) if len(pts) else Polygon()
    if tex.kind == "lines":
        rot = affinity.rotate(inner, -tex.angle_deg, origin=(0, 0))
        rminx, rminy, rmaxx, rmaxy = rot.bounds
        ys = np.arange(math.floor(rminy / p) * p, rmaxy + p, p)
        strips = unary_union([box(rminx - 1, y, rmaxx + 1, y + tex.size_mm) for y in ys])
        ridges = affinity.rotate(rot.intersection(strips), tex.angle_deg, origin=(0, 0))
        return _drop_small(ridges, 2 * tex.size_mm**2)  # no stubs too short to feel
    raise ValueError(f"unknown texture kind {tex.kind!r}")


# ----------------------------------------------------------------------------- solid


def _cross_section(g: BaseGeometry) -> CrossSection:
    contours = []
    for p in polygons(g):
        if p.area < MIN_PRINT_AREA_MM2:
            continue
        for ring in (p.exterior, *p.interiors):
            pts = np.asarray(ring.coords)[:-1]
            if len(pts) >= 3:
                contours.append(pts)
    return CrossSection(contours, FillRule.EvenOdd) if contours else CrossSection()


def braille_dot(x: float, y: float, z: float, spec: braille.BrailleSpec) -> Manifold:
    """One Braille dot standing on height ``z``: a rounded-off cone (frustum), comfortable
    to read and easy to print. It starts slightly below ``z`` so it fuses with the plate."""
    r = spec.dot_diameter_mm / 2
    return Manifold.cylinder(spec.dot_height_mm + 0.05, r, r * 0.55, 16).translate((x, y, z - 0.05))


def build_solid(t: TactileModel) -> Manifold:
    raised = [_cross_section(t.plate).extrude(t.base_mm)]
    recessed = []
    for layer in t.layers:
        if layer.role == "braille":
            continue  # built from braille_dots as domed dots below
        thickness = layer.height_mm - layer.z0_mm
        if layer.height_mm == 0 and layer.z0_mm == 0:
            continue
        cs = _cross_section(layer.geom)
        if cs.is_empty():
            continue
        if layer.height_mm > 0:
            overlap = 0.01 if layer.z0_mm > 0 else 0.0  # fuse textures with the area below
            raised.append(cs.extrude(thickness + overlap).translate((0, 0, t.base_mm + layer.z0_mm - overlap)))
        else:
            depth = min(-layer.height_mm, t.base_mm - MIN_FLOOR_MM)
            recessed.append(cs.extrude(depth + 0.01).translate((0, 0, t.base_mm - depth)))
    raised += [braille_dot(x, y, t.base_mm, t.braille_spec) for x, y in t.braille_dots]
    solid = Manifold.batch_boolean(raised, OpType.Add)
    if recessed:
        solid = solid - Manifold.batch_boolean(recessed, OpType.Add)
    # Safety net: keep only bodies with real volume (one plate with everything on it).
    parts = solid.decompose()
    if len(parts) > 1:
        solid = Manifold.compose([p for p in parts if p.volume() > MIN_PRINT_AREA_MM2 * 0.1])
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
