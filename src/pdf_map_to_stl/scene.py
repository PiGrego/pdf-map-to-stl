"""Step 1: read a vector map PDF into an ordered list of painted primitives.

A *primitive* is what one PDF paint operation leaves on the page: a polygon (in PDF
points), already cut by the clip paths it is drawn inside and by the working area
(the page, or a crop of it), plus its colour and stroke width.

One special case matters for orienteering maps: area patterns such as ISOM 402
("open land with scattered trees") are exported as a regular grid of small dots,
trimmed by a clip path that is exactly the area's outline. Such a *dot screen*
becomes a single ``dots`` primitive whose polygon is that clip outline.

Coordinates: PDF points (1/72 inch) in PyMuPDF's page frame, origin at the top-left
of the page, y pointing down. This is the same frame PyMuPDF renders in, so no
calibration between vectors and pixels is ever needed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree
from shapely import make_valid
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry

from .geometry import CURVE_STEP_PT, areal, centerlines, fill_geometry, stroke_geometry

PT_TO_MM = 25.4 / 72.0

# A clip path counts as a dot screen when everything drawn inside it is at least this
# many fills of one colour and (within this relative spread) one size.
MIN_SCREEN_DOTS = 16
SCREEN_SIZE_TOLERANCE = 0.05

Rect = tuple[float, float, float, float]
# A window on the page, in mm from its top-left corner: 4 numbers are a rectangle (two
# opposite corners), 6 or more are a polygon (x, y of each corner, in order).
Window = tuple[float, ...]


@dataclass
class Primitive:
    seqno: float  # paint order; later paints cover earlier ones
    kind: str  # "fill" | "stroke" | "dots"
    rgb: tuple[int, int, int]
    geom: BaseGeometry  # painted area, clipped, in PDF points
    extent_mm: float  # longest side of the source path's bounding box
    width_mm: float = 0.0  # stroke width (strokes only)
    dot_mm: float = 0.0  # dot diameter (dot screens only)
    pitch_mm: float = 0.0  # distance between dots (dot screens only)
    blend: str = "Normal"  # PDF blend mode of the enclosing group
    lines: list[LineString] = field(default_factory=list)  # stroke centrelines, unclipped


@dataclass
class Scene:
    path: Path
    page_number: int
    page_rect: Rect  # working area in PDF points: the page, or the bounding box of the window
    primitives: list[Primitive]  # sorted by paint order
    stats: dict
    window: BaseGeometry | None = None  # the window itself (rectangle or polygon), PDF points
    page_origin: tuple[float, float] = (0.0, 0.0)  # top-left corner of the page, PDF points

    def page_point(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """A point given in mm from the page's top-left corner (like --crop), in PDF points."""
        return self.page_origin[0] + x_mm / PT_TO_MM, self.page_origin[1] + y_mm / PT_TO_MM

    @property
    def area(self) -> BaseGeometry:
        """The part of the page that is converted."""
        return self.window if self.window is not None else box(*self.page_rect)

    @property
    def is_polygon(self) -> bool:
        return self.window is not None and self.window.area < self.window.envelope.area * (1 - 1e-9)

    @property
    def width_pt(self) -> float:
        return self.page_rect[2] - self.page_rect[0]

    @property
    def height_pt(self) -> float:
        return self.page_rect[3] - self.page_rect[1]


# ----------------------------------------------------------------------------- public


# "1:5000", "1 : 4 000", "1:10.000" printed on the page (title block, legend)
_SCALE_TEXT = re.compile(r"(?<![\d.,])1\s*:\s*(\d{1,3}(?:[ .\u00a0\u202f]\d{3})+|\d{3,6})(?![\d,])")


def read_map_scale(pdf_path: str | Path, page_number: int = 0) -> float:
    """The map scale printed on the page ("Scala 1: 5000" gives 5000), or 0 if the page
    states none, or more than one."""
    with pymupdf.open(pdf_path) as doc:
        text = doc[page_number].get_text()
    found = {int(re.sub(r"\D", "", m)) for m in _SCALE_TEXT.findall(text)}
    found = {v for v in found if 500 <= v <= 100_000}
    return float(found.pop()) if len(found) == 1 else 0.0


def window_pt(page_rect, crop_mm: Window | None) -> BaseGeometry:
    """The window in PDF points, clipped to the page: the whole page, a rectangle
    (4 numbers) or a polygon (6 or more), in mm from the page's top-left corner."""
    page = box(*page_rect)
    if crop_mm is None:
        return page
    v = [float(x) / PT_TO_MM for x in crop_mm]
    px0, py0 = page_rect[0], page_rect[1]
    if len(v) == 4:
        g = box(px0 + min(v[0], v[2]), py0 + min(v[1], v[3]), px0 + max(v[0], v[2]), py0 + max(v[1], v[3]))
    elif len(v) >= 6 and len(v) % 2 == 0:
        g = areal(make_valid(Polygon([(px0 + x, py0 + y) for x, y in zip(v[::2], v[1::2])])))
    else:
        raise ValueError(f"a window is 4 numbers (two corners) or 3 or more x,y points, not {len(v)} numbers")
    g = areal(g.intersection(page))
    if g.is_empty or g.area <= 0:
        raise ValueError(f"window {crop_mm} mm lies outside the page")
    return g


def crop_rect_pt(page_rect, crop_mm: Window | None) -> Rect:
    """Bounding box of the window, in PDF points."""
    return tuple(window_pt(page_rect, crop_mm).bounds)


def load_scene(pdf_path: str | Path, page_number: int = 0, crop_mm: Window | None = None,
               curve_step_mm: float | None = None) -> Scene:
    """Read one page (optionally only the window ``crop_mm`` of it: a rectangle or a
    polygon) into a Scene. Curves are drawn with chords of ``curve_step_mm`` (on the PDF
    page; default 0.035 mm)."""
    step = curve_step_mm / PT_TO_MM if curve_step_mm else CURVE_STEP_PT
    pdf_path = Path(pdf_path)
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_number]
        window = window_pt(page.rect, crop_mm)
        area = tuple(window.bounds)
        origin = (float(page.rect.x0), float(page.rect.y0))
        drawings = page.get_drawings(extended=True)
        if page.rotation:
            # PyMuPDF gives drawings in the unrotated page; the window is picked on the page
            # as it is shown (pick.html), and the PDF check renders it as shown too.
            drawings = _rotate_drawings(drawings, page.rotation_matrix)
        images = len(page.get_images())

    paints, clips = _attach_clip_stacks(drawings)
    clip_region = _ClipRegions(clips, window, step)
    screens = _find_dot_screens(paints)

    prims: list[Primitive] = []
    seen_screens: set[int] = set()
    for paint in paints:
        screen = paint.clips[-1] if paint.clips and paint.clips[-1] in screens else None
        if screen is not None:
            # All dots of a screen become one primitive, emitted at the first dot.
            if screen not in seen_screens:
                seen_screens.add(screen)
                prims.extend(_dot_screen_primitive(screens[screen], clip_region(paint.clips), paint.blend))
            continue
        if not _may_reach(paint.d, area):
            continue
        region = clip_region(paint.clips)
        if not region.is_empty:
            prims.extend(_paint_primitives(paint.d, region, paint.blend, step))
    prims.sort(key=lambda p: p.seqno)
    if not prims:
        scan = (f" The page holds {images} image(s) and no vector drawings there: it may be a scan."
                if images and not paints else "")
        raise ValueError("nothing is drawn in the window (no vector paths). The tool needs a vector PDF exported "
                         "from a map program such as OCAD; a scanned map or an image cannot be converted." + scan)

    stats = {
        "drawings": len(drawings),
        "paint_ops": dict(Counter(p.d["type"] for p in paints)),
        "clips": len(clips),
        "dot_screens": len(screens),
        "dot_screens_in_area": sum(p.kind == "dots" for p in prims),
        "primitives_in_area": len(prims),
        "area_pt": [round(v, 4) for v in area],
        "window_points": 0 if crop_mm is None else len(crop_mm) // 2,
    }
    return Scene(pdf_path, page_number, area, prims, stats, window if crop_mm is not None else None, origin)


# ----------------------------------------------------------------------------- steps


def _rotate_drawings(drawings: list[dict], m: pymupdf.Matrix) -> list[dict]:
    """The drawings with every coordinate mapped by ``m`` (the page's rotation matrix).
    Rectangles become quads, which keep the corner order (and so the winding)."""
    out = []
    for d in drawings:
        d = dict(d)
        if d.get("items"):
            items = []
            for it in d["items"]:
                if it[0] == "re":
                    items.append(("qu", pymupdf.Quad(it[1]) * m))
                elif it[0] == "qu":
                    items.append(("qu", it[1] * m))
                else:
                    items.append((it[0], *(pymupdf.Point(p) * m for p in it[1:])))
            d["items"] = items
        if d.get("rect") is not None:
            d["rect"] = pymupdf.Rect(d["rect"]) * m
        out.append(d)
    return out


@dataclass
class _Paint:
    d: dict  # the PyMuPDF drawing
    clips: tuple[int, ...]  # indices of the clip drawings it is nested in, outermost first
    blend: str


def _attach_clip_stacks(drawings: list[dict]) -> tuple[list[_Paint], dict[int, dict]]:
    """PyMuPDF lists clips and groups inline, with a nesting ``level``; turn that into an
    explicit clip stack and blend mode for every fill or stroke."""
    clips: dict[int, dict] = {}
    stack: list[tuple[int, str, int]] = []  # (level, "clip" | "group", drawing index)
    paints: list[_Paint] = []
    for i, d in enumerate(drawings):
        level = d.get("level", 0)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if d["type"] in ("clip", "group"):
            if d["type"] == "clip":
                clips[i] = d
            stack.append((level, d["type"], i))
            continue
        chain = tuple(idx for _, kind, idx in stack if kind == "clip")
        groups = [idx for _, kind, idx in stack if kind == "group"]
        blend = drawings[groups[-1]].get("blendmode", "Normal") if groups else "Normal"
        paints.append(_Paint(d, chain, blend))
    return paints, clips


class _ClipRegions:
    """Area left visible by a clip stack (intersection of its clip paths and the working
    area), computed once per distinct stack."""

    def __init__(self, clips: dict[int, dict], area: BaseGeometry, step: float = CURVE_STEP_PT):
        self.clips = clips
        self.step = step
        self.cache: dict[tuple[int, ...], BaseGeometry] = {(): area}

    def __call__(self, chain: tuple[int, ...]) -> BaseGeometry:
        if chain not in self.cache:
            parent = self(chain[:-1])
            c = self.clips[chain[-1]]
            own = fill_geometry(c["items"], c.get("even_odd"), self.step)
            self.cache[chain] = parent if parent.is_empty else parent.intersection(own)
        return self.cache[chain]


def _find_dot_screens(paints: list[_Paint]) -> dict[int, list[dict]]:
    """Clip index -> its dots, for every clip whose content is a dot screen."""
    children: dict[int, list[dict]] = {}
    for p in paints:
        if p.clips:
            children.setdefault(p.clips[-1], []).append(p.d)
    return {ci: ds for ci, ds in children.items() if _is_dot_screen(ds)}


def _is_dot_screen(children: list[dict]) -> bool:
    if len(children) < MIN_SCREEN_DOTS or any(c["type"] != "f" for c in children):
        return False
    if len({_rgb(c["fill"]) for c in children}) != 1:
        return False
    sizes = np.array([max(c["rect"].width, c["rect"].height) for c in children])
    return float(sizes.std()) <= SCREEN_SIZE_TOLERANCE * float(sizes.mean())


def _dot_screen_primitive(dots: list[dict], region: BaseGeometry, blend: str) -> list[Primitive]:
    if region.is_empty or region.area <= 0:
        return []
    centres = np.array([((d["rect"].x0 + d["rect"].x1) / 2, (d["rect"].y0 + d["rect"].y1) / 2) for d in dots])
    nearest, _ = cKDTree(centres).query(centres, k=2)
    x0, y0, x1, y1 = region.bounds
    return [
        Primitive(
            seqno=min(d["seqno"] for d in dots),
            kind="dots",
            rgb=_rgb(dots[0]["fill"]),
            geom=region,
            extent_mm=max(x1 - x0, y1 - y0) * PT_TO_MM,
            dot_mm=float(np.median([max(d["rect"].width, d["rect"].height) for d in dots])) * PT_TO_MM,
            pitch_mm=float(np.median(nearest[:, 1])) * PT_TO_MM,
            blend=blend,
        )
    ]


def _may_reach(d: dict, area: Rect) -> bool:
    """Cheap bounding-box test; strokes reach half their width beyond the path."""
    r, pad = d["rect"], (d.get("width") or 0) / 2
    return not (r.x1 + pad < area[0] or r.x0 - pad > area[2] or r.y1 + pad < area[1] or r.y0 - pad > area[3])


def _paint_primitives(d: dict, region: BaseGeometry, blend: str, step: float = CURVE_STEP_PT) -> list[Primitive]:
    """A fill, a stroke, or both (``fs``: the stroke is painted over the fill)."""
    out = []
    extent = max(d["rect"].width, d["rect"].height) * PT_TO_MM
    if d["type"] in ("f", "fs"):
        g = _clip(fill_geometry(d["items"], d.get("even_odd"), step), region)
        if g is not None:
            out.append(Primitive(d["seqno"], "fill", _rgb(d["fill"]), g, extent, blend=blend))
    if d["type"] in ("s", "fs"):
        cap = d.get("lineCap") or (0,)
        cap = int(cap[0]) if isinstance(cap, (tuple, list)) else int(cap)
        close = bool(d.get("closePath"))
        g = _clip(stroke_geometry(d["items"], d.get("width") or 0, cap, int(d.get("lineJoin") or 0), close, step=step), region)
        if g is not None:
            out.append(
                Primitive(
                    d["seqno"] + 0.5,
                    "stroke",
                    _rgb(d["color"]),
                    g,
                    extent,
                    width_mm=(d.get("width") or 0) * PT_TO_MM,
                    blend=blend,
                    lines=centerlines(d["items"], close, step),
                )
            )
    return out


def _clip(g: BaseGeometry, region: BaseGeometry) -> BaseGeometry | None:
    if g.is_empty:
        return None
    g = g.intersection(region)
    return g if not g.is_empty and g.area > 0 else None


def _rgb(v) -> tuple[int, int, int]:
    return tuple(round(x * 255) for x in v) if v else (0, 0, 0)
