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
* a **Braille title** (and scale) at the top left, at standard Braille size (never scaled);
* a **scale bar** under the title: as long as a round distance on the ground, with ticks
  and the distance in Braille (``features.scale_bar``, ``[scale_bar]``).

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
from manifold3d import CrossSection, FillRule, Manifold, Mesh, OpType
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import braille
from .compose import MapModel
from .config import Config, Texture
from .generalize import generalize
from .geo import GeoPoint, pins
from .geometry import polygons
from .relief import Relief
from .scene import PT_TO_MM

MIN_FLOOR_MM = 0.4  # a recess always leaves at least this much plate under it
EDGE_PAD_MM = 5.0  # margin around Braille text
BAR_GAP_MM = 3.0  # scale bar: space between the title and the bar, and between the bar and its label
MIN_PRINT_AREA_MM2 = 0.05  # polygons smaller than this are numerical dust, not features
# Writing the STL (printable_mesh): far below what a printer or a finger can resolve.
MERGE_MM = 1e-4  # edges shorter than this are collapsed
SEPARATE_MM = 0.002  # volumes that touch along an edge are moved at most this far apart there
LIFT_CUT_MM = 0.2  # slopes (relief): everything above this height moves up with its band


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
    positions: list[dict] = field(default_factory=list)  # position points: where they are on the plate
    relief: list[tuple[BaseGeometry, float]] = field(default_factory=list)  # slopes: (area, lift in mm)
    scale_bar: dict = field(default_factory=dict)  # the scale bar: metres, length_mm, divisions, label

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


@dataclass(frozen=True)
class ScaleBar:
    metres: float  # distance on the ground between the end ticks
    length_mm: float  # the same on the model
    divisions: int  # spaces between ticks (1 = ticks at the ends only)
    label: str  # the distance in words, also in Braille right of the bar


def scale_bar(cfg: Config, room_mm: float, metres_per_mm: float | None) -> ScaleBar | None:
    """The longest round distance (1, 2 or 5 times 1, 10, 100... m) whose bar is at most
    ``scale_bar.max_length_mm`` long and fits in ``room_mm`` with its Braille label; None
    if the scale is unknown or not even ``min_length_mm`` fits. A bar of 1 or 5 units has
    5 divisions (50 m: a tick every 10 m), one of 2 has 4, if the ticks are far enough apart."""
    sb, spec = cfg.scale_bar, cfg.braille
    if not metres_per_mm or metres_per_mm <= 0:
        return None
    for metres in sorted((d * 10**k for k in range(6) for d in (1, 2, 5)), reverse=True):
        length = metres / metres_per_mm
        label = f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:g} m"
        label_w = len(braille.to_cells(label)) * spec.cell_spacing_mm
        if length > sb.max_length_mm or sb.width_mm + length + BAR_GAP_MM + label_w > room_mm:
            continue
        if length < sb.min_length_mm:
            return None
        divisions = 4 if str(metres).startswith("2") else 5
        if length / divisions < sb.min_tick_spacing_mm:
            divisions = 1
        return ScaleBar(metres, length, divisions, label)
    return None


def scale_bar_shapes(bar: ScaleBar, cfg: Config, x: float, y_top: float) -> tuple[BaseGeometry, list[tuple[float, float]]]:
    """The raised bar with its ticks, and the Braille dots of its label at its right, in a
    band whose top-left corner is (x, y_top). The distance runs between the centres of
    the end ticks."""
    sb, spec = cfg.scale_bar, cfg.braille
    yc = y_top - max(sb.tick_mm, spec.cell_height_mm) / 2
    half = sb.width_mm / 2
    x0 = x + half
    shapes = [box(x0, yc - half, x0 + bar.length_mm, yc + half)]
    for k in range(bar.divisions + 1):
        tx = x0 + bar.length_mm * k / bar.divisions
        reach = sb.tick_mm / 2 if k in (0, bar.divisions) else sb.tick_mm * 0.3
        shapes.append(box(tx - half, yc - reach, tx + half, yc + reach))
    dots = braille.dot_centres(bar.label, spec, x0 + bar.length_mm + half + BAR_GAP_MM, yc + spec.cell_height_mm / 2)
    return unary_union(shapes), dots


@dataclass
class Margins:
    """The bands above and below the map, in model mm: the Braille title and a north
    symbol at the top; a north symbol and the position points' coordinates at the bottom."""

    top: float
    bottom: float
    north: bool
    title_lines: list[str]
    geo_lines: list[str]
    geo_x: float  # where the coordinates start, right of the bottom north symbol
    bar: ScaleBar | None = None  # the scale bar
    bar_where: str = ""  # "top": under the title; "bottom": beside the bottom-left north symbol
    bar_x: float = 0.0  # left edge of the bar's band
    bar_y: float = 0.0  # top edge of the band: down from the plate's top ("top"), up from its bottom ("bottom")


def margins(cfg: Config, w: float, title: str | None, geo: tuple[GeoPoint, ...] = (),
            region: tuple[float, float, float, float] | None = None,
            metres_per_mm: float | None = None) -> Margins:
    """Margins of a map ``w`` mm wide with this Braille title and these position points,
    and a scale bar if ``metres_per_mm`` (on the ground, per mm on the model) is known.
    Test tiles (``region``) have none."""
    spec = cfg.braille
    north = cfg.features.north_symbol and region is None
    title = "" if region is not None else (title or "")
    room = w - 2 * EDGE_PAD_MM - (NORTH_W_MM + EDGE_PAD_MM if north else 0)
    lines = braille.wrap(title, _cells_that_fit(room, spec)) if title else []
    title_h = (len(lines) - 1) * spec.line_spacing_mm + spec.cell_height_mm if lines else 0.0
    # Bottom margin: north symbol at the left, then the position points' coordinates.
    geo_x = EDGE_PAD_MM + (NORTH_W_MM + EDGE_PAD_MM if north else 0.0)
    geo_cells = _cells_that_fit(w - geo_x - EDGE_PAD_MM, spec)
    geo_lines = [] if region is not None else [
        line for i, p in enumerate(geo, 1) for line in braille.wrap(f"{i}: {p.text(cfg.position.decimals)}", geo_cells)
    ]
    geo_h = (len(geo_lines) - 1) * spec.line_spacing_mm + spec.cell_height_mm if geo_lines else 0.0
    # The scale bar, where the plate does not have to grow for it: under the title, beside
    # the top-right north symbol; under a long title, beside the bottom-left north symbol
    # (if no coordinates are there); else under the title, in a taller top margin.
    bar = scale_bar(cfg, room, metres_per_mm) if cfg.features.scale_bar and region is None else None
    band_h = max(cfg.scale_bar.tick_mm, spec.cell_height_mm)
    under_title = title_h + (BAR_GAP_MM if lines else 0.0) + band_h
    where = ""
    if bar:
        where = "bottom" if north and not geo_lines and under_title > NORTH_H_MM else "top"
    left_h = under_title if where == "top" else title_h
    top = 2 * EDGE_PAD_MM + max(left_h, NORTH_H_MM if north else 0.0) if (lines or north or where) else 0.0
    bottom = 2 * EDGE_PAD_MM + max(NORTH_H_MM if north else 0.0, geo_h) if (north or geo_lines) else 0.0
    bar_x, bar_y = (EDGE_PAD_MM, under_title - band_h + EDGE_PAD_MM) if where == "top" else (geo_x, bottom - EDGE_PAD_MM)
    return Margins(top, bottom, north, lines, geo_lines, geo_x, bar, where, bar_x, bar_y)


def build_layers(
    m: MapModel,
    cfg: Config,
    region: tuple[float, float, float, float] | None = None,
    title: str | None = None,
    geo: tuple[GeoPoint, ...] = (),
    relief: Relief | None = None,
) -> TactileModel:
    """Tactile layers at print scale.

    Layout, following the tactile orienteering guidebook: the Braille title (and scale)
    at the top left, north symbols at the top-right and bottom-left corners, in margins
    above and below the map. ``region`` (x0, y0, x1, y1 in map mm, origin bottom-left)
    keeps only that rectangle, for a small test tile (no margins). ``title`` is the
    Braille title text ("" = none). ``geo`` are position points: pins on the map, and
    their coordinates in Braille in the bottom margin (geo.py).
    """
    if cfg.width_mm <= 0:
        raise ValueError("no print width: set output.width_mm, or let pipeline.build use the suggested size")
    rect = m.scene.page_rect
    scale = cfg.width_mm / m.scene.width_pt
    w, h = cfg.width_mm, m.scene.height_pt * scale
    frame = box(0, 0, w, h)
    if m.scene.is_polygon:  # a polygon window: the map stops at its edge
        frame = frame.intersection(_to_model(m.scene.window, rect, scale))
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

    # Margins: top (title + north symbol), bottom (north symbol, coordinates). Not on test tiles.
    spec = cfg.braille
    metres_per_mm = PT_TO_MM * cfg.map_scale / scale / 1000 if cfg.map_scale else None  # ground m per model mm
    mg = margins(cfg, w, title, geo, region, metres_per_mm)
    north, lines, geo_lines, geo_x, top, bottom = mg.north, mg.title_lines, mg.geo_lines, mg.geo_x, mg.top, mg.bottom
    for layer in layers:
        layer.geom = affinity.translate(layer.geom, 0, bottom)
    total_h = bottom + h + top
    dots: list[tuple[float, float]] = []
    for i, line in enumerate(lines):
        dots += braille.dot_centres(line, spec, EDGE_PAD_MM, total_h - EDGE_PAD_MM - i * spec.line_spacing_mm)
    for i, line in enumerate(geo_lines):
        dots += braille.dot_centres(line, spec, geo_x, bottom - EDGE_PAD_MM - i * spec.line_spacing_mm)

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
    if m.scene.is_polygon and cfg.features.window_edge:
        # A raised line just outside a polygon window, so the edge of the map can be felt
        # (outside it the plate is flat, like paved ground).
        inside = affinity.translate(frame, -x0, -y0 + bottom)
        band = inside.buffer(cfg.window_edge_mm, 4).difference(inside).intersection(box(0, bottom, w, bottom + h))
        if not band.is_empty:
            layers.append(Layer("edge", "edge", cfg.window_edge_height_mm, band))
    positions, pin_shapes = [], []
    inside = affinity.translate(frame, -x0, -y0 + bottom)
    for i, p in enumerate(geo, 1):
        px, py = _to_model(Point(m.scene.page_point(p.x_mm, p.y_mm)), rect, scale).coords[0]
        px, py = px - x0, py - y0 + bottom
        if not inside.buffer(1e-6).contains(Point(px, py)):
            if region is not None:
                continue  # a test tile shows only the points inside it
            raise ValueError(f"position point {i} ({p.x_mm:g}, {p.y_mm:g} mm on the page) lies outside the window")
        pin_shapes.append(pins(i, px, py, cfg.position.pin_mm))
        positions.append({"point": i, "pins": i, "x_mm": round(px, 1), "y_mm": round(py, 1),
                          "lat": p.lat, "lon": p.lon, "text": p.text(cfg.position.decimals)})
    if pin_shapes:
        layers.append(Layer("position", "pin", cfg.position.pin_height_mm, unary_union(pin_shapes)))
    if north:
        glyphs = unary_union([
            north_symbol(w - EDGE_PAD_MM - NORTH_W_MM / 2 - c, total_h - EDGE_PAD_MM),
            north_symbol(EDGE_PAD_MM + NORTH_W_MM / 2, bottom - EDGE_PAD_MM),
        ])
        layers.append(Layer("north", "north", cfg.north_height_mm, glyphs))
    bar_info = {}
    if mg.bar:
        y_top = total_h - mg.bar_y if mg.bar_where == "top" else mg.bar_y
        shape, label_dots = scale_bar_shapes(mg.bar, cfg, mg.bar_x, y_top)
        layers.append(Layer("scale bar", "scale_bar", cfg.scale_bar.height_mm, shape))
        dots += label_dots
        where = ("beside the bottom-left north symbol" if mg.bar_where == "bottom"
                 else "under the title" if lines else "at the top left")
        bar_info = {"metres": mg.bar.metres, "length_mm": round(mg.bar.length_mm, 2), "divisions": mg.bar.divisions,
                    "label": mg.bar.label, "where": where}
    if dots:
        r = spec.dot_diameter_mm / 2
        layers.append(Layer("braille", "braille", spec.dot_height_mm, unary_union([Point(p).buffer(r, 8) for p in dots])))

    terraces = []
    if relief is not None:
        by_level: dict[int, list] = {}
        for g, lv in relief.bands:
            if lv > 0:
                by_level.setdefault(lv, []).append(g)
        for lv, gs in sorted(by_level.items()):
            g = _to_model(unary_union(gs), rect, scale).intersection(frame)
            g = affinity.translate(g, -x0, -y0 + bottom).intersection(plate)
            if not g.is_empty:
                terraces.append((g, lv * cfg.relief.step_mm))

    return TactileModel(
        w, total_h, cfg.base_mm, scale, layers, plate, (0.0, bottom, w, bottom + h), dots, spec, " / ".join(lines), c,
        report.as_dict(), positions, terraces, bar_info,
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
    Textures come after the recesses, so a texture on a recess floor (water waves) stays.
    Where a raised layer (a wall along a lake) crosses a recess, it stands on the recess
    floor, like the position pins: no tunnel under it."""
    raised = [_cross_section(t.plate).extrude(t.base_mm)]
    recessed, on_top = [], _recess_fills(t)
    for layer in t.layers:
        if layer.role == "braille":
            continue  # built from braille_dots as domed dots below
        if layer.role == "pin":  # from the bottom of the plate, so a pin in a recess stands on its floor
            on_top.append(_cross_section(layer.geom).extrude(t.base_mm + layer.height_mm))
            continue
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
    solid = lift(solid, t.relief, fill=True)
    # Safety net: keep only bodies with real volume (one plate with everything on it).
    parts = solid.decompose()
    if len(parts) > 1:
        solid = Manifold.compose([p for p in parts if p.volume() > MIN_PRINT_AREA_MM2 * 0.1])
    return solid


def lift(solid: Manifold, terraces: list[tuple[BaseGeometry, float]], fill: bool) -> Manifold:
    """Slopes: everything above ``LIFT_CUT_MM`` inside each terrace area moves up by its
    lift, so the ground and all that stands on it rise together. With ``fill`` (the plate,
    or the whole model), the gap opened under it is filled."""
    if not terraces or solid.is_empty():
        return solid
    upper, below = solid.split_by_plane((0, 0, 1), LIFT_CUT_MM)
    pieces, prisms = [below], []
    for area, dz in terraces:
        cs = _cross_section(area)
        if cs.is_empty():
            continue
        prism = cs.extrude(1000.0).translate((0, 0, LIFT_CUT_MM))
        prisms.append(prism)
        pieces.append((upper ^ prism).translate((0, 0, dz)))
        if fill:
            pieces.append(cs.extrude(dz).translate((0, 0, LIFT_CUT_MM)))
    if prisms:
        pieces.append(upper - Manifold.batch_boolean(prisms, OpType.Add))
    return Manifold.batch_boolean([p for p in pieces if not p.is_empty()], OpType.Add)


def recess_floors(t: TactileModel) -> list[tuple[BaseGeometry, float]]:
    """Each recessed area with the height of its floor above the table."""
    return [(lyr.geom, t.base_mm - recess_depth(lyr.height_mm, t.base_mm)) for lyr in t.layers
            if lyr.role == "terrain" and lyr.height_mm < 0]


def _recess_fills(t: TactileModel) -> list[Manifold]:
    """Columns that fill a recess under the raised layers crossing it, from just below its
    floor to just above the plate (overlapping both, so they fuse)."""
    fills = []
    for geom, floor in recess_floors(t):
        for layer in t.layers:
            if layer.height_mm <= 0 or layer.role not in ("object", "terrain", "north", "edge", "scale_bar"):
                continue
            cs = _cross_section(layer.geom.intersection(geom))
            if not cs.is_empty():
                fills.append(cs.extrude(t.base_mm - floor + 0.03).translate((0, 0, floor - 0.01)))
    return fills


def _separate_touching(pos: np.ndarray, tri: np.ndarray, step: float) -> tuple[np.ndarray, int]:
    """Move every vertex that shares its float32 position with another vertex a little
    toward the middle of its own triangles. manifold3d keeps volumes that touch along an
    edge (two areas meeting at one corner) apart with such duplicate vertices; an STL
    reader merges them by position, and the edge would then belong to 4 faces."""
    _, inv, counts = np.unique(pos.astype(np.float32), axis=0, return_inverse=True, return_counts=True)
    shared = counts[inv.reshape(-1)] > 1
    if not shared.any():
        return pos, 0
    near = tri[shared[tri].any(axis=1)]  # triangles around the shared vertices
    corner = pos[near]
    centre = corner.mean(axis=1)
    pull = np.zeros_like(pos)
    shortest = np.full(len(pos), np.inf)
    for k in range(3):
        np.add.at(pull, near[:, k], centre - corner[:, k])
        edge = np.linalg.norm(corner[:, (k + 1) % 3] - corner[:, k], axis=1)
        np.minimum.at(shortest, near[:, k], edge)
        np.minimum.at(shortest, near[:, (k + 1) % 3], edge)
    v = np.nonzero(shared)[0]
    length = np.linalg.norm(pull[v], axis=1)
    v, length = v[length > 0], length[length > 0]
    out = pos.copy()
    out[v] += pull[v] / length[:, None] * np.minimum(step, 0.1 * shortest[v])[:, None]
    return out, len(v)


def printable_mesh(solid: Manifold, rounds: int = 3) -> tuple[Manifold, int]:
    """The solid as it can be written to STL (float32) and read back closed by any program.

    Collapses edges shorter than ``MERGE_MM``, moves apart the duplicate vertices where two
    volumes touch along an edge (``SEPARATE_MM``), and rebuilds the solid from the float32
    coordinates, until no two vertices share a position. Returns the solid and how many
    vertices were moved. If a rebuild fails, the solid is returned as it was."""
    moved = 0
    s = solid.simplify(MERGE_MM)
    for _ in range(rounds):
        m = s.to_mesh64()
        pos = np.asarray(m.vert_properties)[:, :3].astype(np.float64)
        tri = np.asarray(m.tri_verts, dtype=np.int64)
        pos, n = _separate_touching(pos, tri, SEPARATE_MM)
        if n == 0:
            return s, moved
        moved += n
        rebuilt = Manifold(Mesh(vert_properties=pos.astype(np.float32), tri_verts=tri.astype(np.uint32)))
        if not str(rebuilt.status()).endswith("NoError") or rebuilt.is_empty():
            return solid, 0
        s = rebuilt.simplify(MERGE_MM)
    return s, moved


def open_edges(tri_xyz: np.ndarray) -> int:
    """Edges not shared by exactly two triangles, after merging vertices by position as an
    STL reader does (0 = closed, watertight)."""
    _, inv = np.unique(tri_xyz.reshape(-1, 3), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, n = np.unique(e, axis=0, return_counts=True)
    return int((n != 2).sum())


def write_stl(solid: Manifold, path: str | Path) -> dict:
    solid, separated = printable_mesh(solid)
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
        "open_edges": open_edges(tri),  # in the file as written: 0 = watertight
        "separated_vertices": separated,
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
