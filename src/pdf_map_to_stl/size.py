"""The suggested print size: how big the tactile map must be for its details to be felt.

A tactile map can be printed at any size, from a 100 mm tile to a 1000 mm plate; what
decides the size is the map's detail. This module measures the composed map (on the PDF
page, before any generalisation) and suggests the enlargement at which most details
already meet the tactile rules:

* every **passage** between two raised parts of the same class (two buildings, two
  walls, two patches of open land) becomes at least ``tactile.min_gap_mm`` wide; for
  standard symbols (trees) the gap between the printed symbols counts;
* every **raised part** becomes at least ``tactile.min_feature_mm`` wide.

Each passage and part gives the enlargement it needs; the suggestion satisfies
``size.detail_share`` of them (90 %). The few that remain are what generalisation fixes
and the tactile check reports. Details narrower than ``size.ignore_below_mm`` on the PDF
page are drawing artefacts and are not counted.

When the map scale is known (``--map-scale``, or read from the page: "1:5000"), the
tactile scale is rounded to a round number (1:900, 1:1000); otherwise the width is
rounded up to 10 mm. The plate is kept between ``size.min_mm`` and ``size.max_mm`` on its
longer side. A plate wider than ``size.bed_mm`` does not fit the printer bed in one piece.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely import affinity
from shapely.ops import unary_union

from .compose import MapModel
from .config import Config
from .geometry import polygons
from .scene import PT_TO_MM

ROUND_SCALES = (100, 150, 200, 250, 300, 400, 500, 600, 700, 750, 800, 900, 1000,
                1250, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000)
MARGINS_MM = 60.0  # title and north symbols above and below the map (model3d layout)
INSTANCE_MM = 0.05  # drawn pieces closer than this on the page are one object (the two strokes of a cross)


@dataclass
class SizeSuggestion:
    width_mm: float  # map width on the model
    height_mm: float  # map height on the model
    plate_height_mm: float  # with the margins for the title and north symbols
    enlarge: float  # model mm per mm on the PDF page
    tactile_scale: float  # e.g. 900 for 1:900; 0 when the map scale is unknown
    needed_enlarge: float  # what the details ask for, before rounding and limits
    measures: int  # passages and parts measured
    share_ok: float  # share of them wide enough at this size
    limited: str = ""  # "max" or "min" when a size limit decided, else ""
    bed_enlarge: float = 0.0  # the largest enlargement whose plate fits the printer bed
    bed_share: float = 0.0  # share of details wide enough at that size

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _mm(g):
    return affinity.scale(g, PT_TO_MM, PT_TO_MM, origin=(0, 0))


def _nearest(geoms) -> np.ndarray:
    """Distance from each geometry to the nearest other one."""
    if len(geoms) < 2:
        return np.zeros(0)
    _, d = shapely.STRtree(geoms).query_nearest(geoms, exclusive=True, return_distance=True, all_matches=False)
    return d


def needed_enlargements(m: MapModel, cfg: Config) -> np.ndarray:
    """For every passage and raised part of the map, the enlargement it needs."""
    gap, feature, ignore = cfg.tactile.min_gap_mm, cfg.tactile.min_feature_mm, cfg.size.ignore_below_mm
    need: list[float] = []
    for cls, g in m.terrain.items():
        tc = cfg.classes.get(cls)
        if tc is None or tc.height_mm <= 0:
            continue  # flat and recessed areas: no passages to keep open
        parts = [p for p in polygons(_mm(g)) if p.area > ignore**2]
        need += [gap / d for d in _nearest(parts) if d >= ignore]
        need += [feature / w for p in parts if (w := 2 * p.area / p.length) >= ignore]
    for cls, prims in m.objects.items():
        tc = cfg.classes[cls]
        drawn = _mm(unary_union([p.geom for p in prims]).buffer(INSTANCE_MM / PT_TO_MM))
        instances = list(polygons(drawn))
        if cfg.shape(cls):  # standard symbols: the gap between symbols of size_mm
            need += [(gap + tc.size_mm) / d for d in _nearest([p.centroid for p in instances]) if d >= ignore]
        else:
            need += [gap / d for d in _nearest(instances) if d >= ignore]
    return np.asarray(need)


def suggest_size(m: MapModel, cfg: Config) -> SizeSuggestion:
    s = cfg.size
    page_w, page_h = m.scene.width_pt * PT_TO_MM, m.scene.height_pt * PT_TO_MM
    need = needed_enlargements(m, cfg)
    needed = float(np.percentile(need, 100 * s.detail_share)) if len(need) else s.min_mm / max(page_w, page_h)

    # Round: to a round tactile scale if the map scale is known, else the width to 10 mm.
    if cfg.map_scale:
        exact = cfg.map_scale / needed
        scale = max([r for r in ROUND_SCALES if r <= exact], default=exact)
        k = cfg.map_scale / scale
    else:
        k = math.ceil(needed * page_w / 10) * 10 / page_w

    # Keep the plate (map plus margins) between the size limits.
    margins = MARGINS_MM if cfg.features.north_symbol else 0.0
    longest = max(page_w * k, page_h * k + margins)
    limited = ""
    if longest > s.max_mm:
        k = min(s.max_mm / page_w, (s.max_mm - margins) / page_h)
        limited = "max"
    elif longest < s.min_mm:
        k = min(s.min_mm / page_w, (s.min_mm - margins) / page_h)  # the longer side reaches min_mm
        limited = "min"
    # The largest size that fits the printer bed in one piece (a round scale, if known).
    bed = min(s.bed_mm / page_w, (s.bed_mm - margins) / page_h)
    if cfg.map_scale:
        bed = cfg.map_scale / min([r for r in ROUND_SCALES if r >= cfg.map_scale / bed], default=cfg.map_scale / bed)

    def share(e: float) -> float:
        return float(np.mean(need <= e * (1 + 1e-9))) if len(need) else 1.0

    return SizeSuggestion(page_w * k, page_h * k, page_h * k + margins, k,
                          cfg.map_scale / k if cfg.map_scale else 0.0, needed, len(need), share(k), limited,
                          bed, share(bed))


def describe_size(sg: SizeSuggestion, cfg: Config, used_width_mm: float, source: str) -> list[str]:
    """The size decision in words, for the description and the command line."""
    s, r = cfg.size, cfg.tactile
    scale = f", scale 1:{sg.tactile_scale:.0f}" if sg.tactile_scale else ""
    size = (f"Suggested size: map {sg.width_mm:.0f} by {sg.height_mm:.0f} mm{scale} "
            f"(plate about {sg.width_mm:.0f} by {sg.plate_height_mm:.0f} mm with the title and north symbols).")
    wide = (f"passages at least {r.min_gap_mm:g} mm wide and raised parts at least {r.min_feature_mm:g} mm "
            f"(tactile.min_gap_mm, tactile.min_feature_mm)")
    lines = [size]
    if sg.limited == "max":
        k = sg.needed_enlarge
        need_scale = f", scale 1:{cfg.map_scale / k:.0f}" if cfg.map_scale else ""
        lines.append(f"This is the largest size allowed ({s.max_mm:g} mm, size.max_mm). For "
                     f"{100 * s.detail_share:.0f} % of the details to be readable the map would need "
                     f"{sg.width_mm / sg.enlarge * k:.0f} by {sg.height_mm / sg.enlarge * k:.0f} mm{need_scale}; at "
                     f"this size {100 * sg.share_ok:.0f} % of the {sg.measures} details measured have {wide}. "
                     "Convert a smaller part (--crop) to keep more.")
    elif sg.limited == "min":
        lines.append(f"This is the smallest size allowed ({s.min_mm:g} mm, size.min_mm); {100 * sg.share_ok:.0f} % "
                     f"of the {sg.measures} details measured have {wide}.")
    else:
        lines.append(f"At this size {100 * sg.share_ok:.0f} % of the {sg.measures} details measured on the map have "
                     f"{wide}; the suggestion aims at {100 * s.detail_share:.0f} % (size.detail_share). "
                     "Generalisation adjusts the rest, and the tactile check reports what remains.")
    if cfg.map_scale:
        lines.append(f"The map is 1:{cfg.map_scale:g}; the guidebook recommends tactile maps at 1:500 to 1:1000.")
    if source:
        used = "the suggested size" if source == "suggested" else f"a map {used_width_mm:.0f} mm wide ({source})"
        lines.append(f"Built at {used}.")
    plate_h = used_width_mm / sg.width_mm * sg.height_mm + (sg.plate_height_mm - sg.height_mm)
    if max(used_width_mm, plate_h) > s.bed_mm:
        page_w = sg.width_mm / sg.enlarge
        bed_w = page_w * sg.bed_enlarge
        option = f"--scale {cfg.map_scale / sg.bed_enlarge:.0f}" if cfg.map_scale else f"--width {math.floor(bed_w)}"
        lines.append(f"The plate is larger than a {s.bed_mm:g} mm printer bed (size.bed_mm). To print it in one "
                     f"piece, build with {option}: map {bed_w:.0f} mm wide, {100 * sg.bed_share:.0f} % of the details "
                     "readable. Or print it in tiles (--region), or on a larger printer.")
    return lines
