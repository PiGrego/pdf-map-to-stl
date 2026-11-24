"""Step 4: tactile layers at print scale, the watertight 3D solid, and the STL file.

Each terrain class and object class becomes a *layer*: its 2D shape in millimetres
plus a height. Some classes also get a *texture* layer (raised dots or ridges on top),
so classes at the same height can still be told apart by touch (``features.textures``
switches all textures off). Line objects (walls) are redrawn along their centre line at
least ``min_width_mm`` wide, with the ends and corners set in ``[smoothing]``; point
objects (trees) become standard symbols (``shape``, ``features.standard_symbols``).
The model also carries what a blind reader needs to use it without help:

* **north symbols** at the top-right and bottom-left corners (``features.north_symbol``),
  and optionally a cut top-right corner (``output.orientation_corner_mm``);
* a **Braille title** (and scale) at the top left, at standard Braille size (never scaled).

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
from shapely.geometry import LineString, Point, Polygon, box
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
    plate: BaseGeometry  # outline of the base plate (with the optional cut corner)
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

    Layout, following the tactile orienteering guidebook: the Braille title (and scale)
    at the top left, north symbols at the top-right and bottom-left corners, in margins
    above and below the map. ``region`` (x0, y0, x1, y1 in map mm, origin bottom-left)
    keeps only that rectangle, for a small test tile (no margins). ``title`` is the
    Braille title text ("" = none).
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

    # Margins: top (title + north symbol), bottom (north symbol). Not on test tiles.
    spec = cfg.braille
    north = cfg.features.north_symbol and region is None
    title = "" if region is not None else (title or "")
    room = w - 2 * EDGE_PAD_MM - (NORTH_W_MM + EDGE_PAD_MM if north else 0)
    lines = braille.wrap(title, _cells_that_fit(room, spec)) if title else []
    title_h = (len(lines) - 1) * spec.line_spacing_mm + spec.cell_height_mm if lines else 0.0
    top = 2 * EDGE_PAD_MM + max(title_h, NORTH_H_MM if north else 0.0) if (lines or north) else 0.0
    bottom = 2 * EDGE_PAD_MM + NORTH_H_MM if north else 0.0
    for layer in layers:
        layer.geom = affinity.translate(layer.geom, 0, bottom)
    total_h = bottom + h + top
    dots: list[tuple[float, float]] = []
    for i, line in enumerate(lines):
        dots += braille.dot_centres(line, spec, EDGE_PAD_MM, total_h - EDGE_PAD_MM - i * spec.line_spacing_mm)

    plate = box(0, 0, w, total_h)
    c = min(cfg.orientation_corner_mm, w / 3, total_h / 3)
    if c > 0:
        plate = plate.difference(Polygon([(w - c, total_h), (w + 1, total_h + 1), (w, total_h - c)]))
    layers = [_clip_layer(lyr, plate) for lyr in layers]
    layers = [lyr for lyr in layers if not lyr.geom.is_empty]

    # Textures on top of the classes that have one (on the floor of recessed ones).
    for layer in list(layers):
        pattern = cfg.texture(layer.cls)
        if pattern is not None:
            tex = texture_geometry(layer.geom, pattern)
            if not tex.is_empty:
                z0 = layer.height_mm if layer.height_mm >= 0 else -recess_depth(layer.height_mm, cfg.base_mm)
                layers.append(Layer(f"{layer.cls} texture", "texture", z0 + pattern.height_mm, tex,
                                    z0_mm=z0, on=layer.cls))
    if north:
        glyphs = unary_union([
            north_symbol(w - EDGE_PAD_MM - NORTH_W_MM / 2 - c, total_h - EDGE_PAD_MM),
            north_symbol(EDGE_PAD_MM + NORTH_W_MM / 2, bottom - EDGE_PAD_MM),
        ])
        layers.append(Layer("north", "north", cfg.north_height_mm, glyphs))
    if dots:
        r = spec.dot_diameter_mm / 2
        layers.append(Layer("braille", "braille", spec.dot_height_mm, unary_union([Point(p).buffer(r, 8) for p in dots])))

    return TactileModel(
        w, total_h, cfg.base_mm, scale, layers, plate, (0.0, bottom, w, bottom + h), dots, spec, " / ".join(lines), c,
        report.as_dict(),
    )


NORTH_W_MM = 7.0
NORTH_H_MM = 20.0


def north_symbol(cx: float, y_top: float) -> BaseGeometry:
    """The tactile north symbol: two dots, then a ring with a stem below it; the ring end
    points north. About 7 x 20 mm, ``y_top`` is its top edge."""
    dots = [Point(cx, y_top - 0.75).buffer(0.75, 8), Point(cx, y_top - 3.25).buffer(0.75, 8)]
    ring_c = (cx, y_top - 5.5 - 3.5)
    ring = Point(ring_c).buffer(3.5, 24).difference(Point(ring_c).buffer(1.8, 24))
    stem = box(cx - 1.0, y_top - NORTH_H_MM, cx + 1.0, ring_c[1] - 3.3)
    return unary_union(dots + [ring, stem])


def recess_depth(height_mm: float, base_mm: float) -> float:
    """How deep a recessed class is actually cut (always leaving a floor)."""
    return min(-height_mm, base_mm - MIN_FLOOR_MM)


def _generalize(layers: list[Layer], cfg: Config):
    terrain = {lyr.cls: lyr.geom for lyr in layers if lyr.role == "terrain"}
    heights = {lyr.cls: lyr.height_mm for lyr in layers}
    objects = {lyr.cls: lyr.geom for lyr in layers if lyr.role == "object"}
    terrain, objects, report = generalize(terrain, heights, objects, cfg)
    # Generalising can leave hairline pieces; nothing that small can be printed or felt.
    out = [Layer(c, "terrain", heights[c], _drop_small(g, cfg.generalize.min_area_mm2)) for c, g in sorted(terrain.items())]
    out += [Layer(c, "object", heights[c], _drop_small(g, cfg.generalize.min_area_mm2)) for c, g in sorted(objects.items())]
    return [lyr for lyr in out if not lyr.geom.is_empty], report


def standard_symbol(shape: str, x: float, y: float, size: float, width: float) -> BaseGeometry:
    """A point symbol drawn the same way everywhere: ``dot``, ``ring`` or ``cross``."""
    if shape == "dot":
        return Point(x, y).buffer(size / 2, 16)
    if shape == "ring":
        return Point(x, y).buffer(size / 2, 16).difference(Point(x, y).buffer(max(size / 2 - width, 0.3), 16))
    if shape == "cross":
        bar = box(-size / 2, -width / 2, size / 2, width / 2)
        cross = unary_union([affinity.rotate(bar, 45, (0, 0)), affinity.rotate(bar, -45, (0, 0))])
        return affinity.translate(cross, x, y)
    raise ValueError(f"unknown shape {shape!r}")


def _map_layers(m: MapModel, cfg: Config, rect, scale: float, frame: BaseGeometry) -> list[Layer]:
    layers: list[Layer] = []
    for cls, g in sorted(m.terrain.items()):
        tc = cfg.classes.get(cls)
        if tc is None or tc.role != "terrain":
            continue
        mg = _drop_small(_to_model(g, rect, scale).intersection(frame), cfg.generalize.min_area_mm2)
        if not mg.is_empty:
            layers.append(Layer(cls, "terrain", tc.height_mm, mg))
    sm, widen = cfg.smoothing, cfg.generalize.widen_objects
    for cls, prims in sorted(m.objects.items()):
        tc = cfg.classes[cls]
        shape = cfg.shape(cls)
        parts = []
        for p in prims:
            if shape:
                # A standard tactile symbol at the centre of each drawn instance.
                src = unary_union(p.lines) if p.kind == "stroke" and p.lines else p.geom
                c = _to_model(src.centroid, rect, scale)
                parts.append(standard_symbol(shape, c.x, c.y, tc.size_mm, tc.min_width_mm))
            elif p.kind == "stroke" and p.lines:
                # Redraw the line along its centre, at a width that can be felt and printed.
                width = p.width_mm / PT_TO_MM * scale
                if widen:
                    width = max(width, tc.min_width_mm)
                lines = [_to_model(ln, rect, scale) for ln in p.lines]
                parts.extend(ln.buffer(width / 2, quad_segs=sm.arc_segments, cap_style=sm.line_cap,
                                       join_style=sm.line_join) for ln in lines)
            else:
                g = _to_model(p.geom, rect, scale)
                minx, miny, maxx, maxy = g.bounds
                short = min(maxx - minx, maxy - miny)
                if widen and short < tc.min_width_mm:
                    g = g.buffer((tc.min_width_mm - short) / 2, quad_segs=sm.arc_segments)
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


def _grid_points(inner: BaseGeometry, p: float) -> np.ndarray:
    minx, miny, maxx, maxy = inner.bounds
    xs = np.arange(math.floor(minx / p) * p + p / 2, maxx + p, p)
    ys = np.arange(math.floor(miny / p) * p + p / 2, maxy + p, p)
    gx, gy = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(inner, gx.ravel(), gy.ravel())
    return np.column_stack([gx.ravel()[inside], gy.ravel()[inside]])


def texture_geometry(area: BaseGeometry, tex: Texture) -> BaseGeometry:
    """Raised pattern inside ``area``, kept clear of its edges so the edge stays crisp.
    The pattern grid is anchored to the model origin, so neighbouring pieces line up."""
    inner = area.buffer(-(tex.size_mm / 2 + 0.3))
    if inner.is_empty:
        return Polygon()
    p = tex.pitch_mm
    if tex.kind in ("dots", "rings"):
        pts = _grid_points(inner, p)
        if not len(pts):
            return Polygon()
        r = tex.size_mm / 2
        if tex.kind == "dots":
            return unary_union([Point(x, y).buffer(r, 4) for x, y in pts])
        hole = max(r - tex.line_mm, 0.2)
        return unary_union([Point(x, y).buffer(r, 8).difference(Point(x, y).buffer(hole, 8)) for x, y in pts])
    if tex.kind in ("lines", "waves"):
        rot = affinity.rotate(inner, -tex.angle_deg, origin=(0, 0))
        rminx, rminy, rmaxx, rmaxy = rot.bounds
        ys = np.arange(math.floor(rminy / p) * p, rmaxy + p, p)
        if tex.kind == "lines":
            ridges = unary_union([box(rminx - 1, y, rmaxx + 1, y + tex.size_mm) for y in ys])
        else:
            xs = np.arange(rminx - 1, rmaxx + 1.25, 0.25)
            amp, wavelength = p / 4, 2 * p
            ridges = unary_union([
                LineString(np.column_stack([xs, y + amp * np.sin(2 * np.pi * xs / wavelength)])).buffer(tex.size_mm / 2, 4)
                for y in ys
            ])
        ridges = affinity.rotate(rot.intersection(ridges), tex.angle_deg, origin=(0, 0))
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
    """Plate + raised layers - recesses, then textures, north symbols and Braille on top.
    Textures come after the recesses, so a texture on a recess floor (water waves) stays."""
    raised = [_cross_section(t.plate).extrude(t.base_mm)]
    recessed, on_top = [], []
    for layer in t.layers:
        if layer.role == "braille":
            continue  # built from braille_dots as domed dots below
        cs = _cross_section(layer.geom)
        if cs.is_empty():
            continue
        if layer.role == "texture":
            overlap = 0.01  # fuse with the surface below
            on_top.append(cs.extrude(layer.height_mm - layer.z0_mm + overlap)
                          .translate((0, 0, t.base_mm + layer.z0_mm - overlap)))
        elif layer.height_mm > 0:
            raised.append(cs.extrude(layer.height_mm).translate((0, 0, t.base_mm)))
        elif layer.height_mm < 0:
            depth = recess_depth(layer.height_mm, t.base_mm)
            recessed.append(cs.extrude(depth + 0.01).translate((0, 0, t.base_mm - depth)))
    solid = Manifold.batch_boolean(raised, OpType.Add)
    if recessed:
        solid = solid - Manifold.batch_boolean(recessed, OpType.Add)
    on_top += [braille_dot(x, y, t.base_mm, t.braille_spec) for x, y in t.braille_dots]
    if on_top:
        solid = Manifold.batch_boolean([solid, *on_top], OpType.Add)
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
