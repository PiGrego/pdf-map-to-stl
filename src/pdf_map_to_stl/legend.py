"""The tactile legend: a separate plate that explains the map's symbols by touch.

One entry per class: a sample (its height and texture, or the standard shape of an
object) followed by its name in Braille. The plate starts with a Braille title ("key"
by default) at the top left; entries follow in Braille reading order, left to right
and top to bottom, wrapping into columns so the plate fits a printer bed.

Flat classes (e.g. paved) get a low raised frame around their sample, as the guidebook
draws "paved area" as an outlined box, so the sample can be found by touch.

The legend can be built from a tactile model (the classes on that map) or, with
``classes_in_map``, from every class found in a whole map: a stand-alone legend sample.
"""

from __future__ import annotations

import math
from collections import defaultdict

from shapely.geometry import Point, box
from shapely.ops import unary_union

from . import braille
from .compose import Classified
from .config import Config
from .i18n import num, t
from .model3d import (
    EDGE_PAD_MM,
    Layer,
    TactileModel,
    standard_symbol,
    texture_geometry,
    texture_levels,
)

SWATCH_W_MM = 16.0
SWATCH_H_MM = 10.0
LABEL_GAP_MM = 6.0
COLUMN_GAP_MM = 8.0
FRAME_MM = 0.8  # width of the frame around flat samples
FRAME_HEIGHT_MM = 0.6
DEFAULT_TITLE = None  # the word for "legend" in the build's language (locales: legend.title)


def order_classes(classes, cfg: Config) -> list[str]:
    """Reading order: ground from low to high, then objects from low to high."""
    present = [c for c in set(classes) if c in cfg.classes and cfg.classes[c].role in ("terrain", "object")]
    return sorted(present, key=lambda c: (cfg.classes[c].role == "object", cfg.classes[c].height_mm, c))


def classes_in_model(t: TactileModel, cfg: Config) -> list[str]:
    return order_classes([lyr.cls for lyr in t.tactile_layers()], cfg)


def classes_in_map(items: list[Classified], cfg: Config) -> tuple[list[str], dict[str, set[str]]]:
    """Classes found in a classified map, and which source symbols (``isom``) led to each."""
    sources: dict[str, set[str]] = defaultdict(set)
    for c in items:
        if c.role in ("terrain", "object"):
            sources[c.cls].add(c.isom)
    return order_classes(sources, cfg), dict(sources)


def _sample(cls: str, cfg: Config, x0: float, cy: float):
    """(geometry, extra frame) of one class sample, left edge x0, centred on cy."""
    tc = cfg.classes[cls]
    if tc.role == "terrain":
        swatch = box(x0, cy - SWATCH_H_MM / 2, x0 + SWATCH_W_MM, cy + SWATCH_H_MM / 2)
        frame = None
        if tc.height_mm == 0 and cfg.features.legend_frames:
            frame = swatch.buffer(FRAME_MM, join_style="mitre").difference(swatch)
        return swatch, frame
    if tc.shape:
        # A point symbol; drawn as a plain dot when standard symbols are switched off.
        shape = cfg.shape(cls) or "dot"
        return standard_symbol(shape, x0 + SWATCH_W_MM / 2, cy, tc.size_mm, tc.min_width_mm), None
    width = max(tc.min_width_mm, 1.0)
    return box(x0, cy - width / 2, x0 + SWATCH_W_MM, cy + width / 2), None


def build_legend(classes: list[str], cfg: Config, title: str | None = DEFAULT_TITLE) -> TactileModel:
    if title is None:
        title = t("legend.title")
    spec = cfg.braille
    labels = [cfg.classes[c].legend_label for c in classes]
    label_w = max([braille.width_mm(s, spec) for s in labels] + [0.0])
    entry_w = SWATCH_W_MM + LABEL_GAP_MM + label_w
    row_h = max(SWATCH_H_MM, spec.cell_height_mm) + 5.0

    title_lines, title_h, n_cols, n_rows = _layout(len(classes), cfg, title)
    w = 2 * EDGE_PAD_MM + n_cols * entry_w + (n_cols - 1) * COLUMN_GAP_MM
    w = max(w, 2 * EDGE_PAD_MM + max([braille.width_mm(s, spec) for s in title_lines] + [0.0]))
    h = 2 * EDGE_PAD_MM + title_h + n_rows * row_h

    dots: list[tuple[float, float]] = []
    for i, line in enumerate(title_lines):
        dots += braille.dot_centres(line, spec, EDGE_PAD_MM, h - EDGE_PAD_MM - i * spec.line_spacing_mm)

    samples: dict[str, list] = defaultdict(list)
    frames = []
    for i, (cls, label) in enumerate(zip(classes, labels)):
        row, col = divmod(i, n_cols)  # reading order: left to right, then the next row
        x0 = EDGE_PAD_MM + col * (entry_w + COLUMN_GAP_MM)
        cy = h - EDGE_PAD_MM - title_h - (row + 0.5) * row_h
        geom, frame = _sample(cls, cfg, x0, cy)
        samples[cls].append(geom)
        if frame is not None:
            frames.append(frame)
        dots += braille.dot_centres(label, spec, x0 + SWATCH_W_MM + LABEL_GAP_MM, cy + spec.cell_height_mm / 2)

    layers: list[Layer] = []
    for cls in classes:
        tc = cfg.classes[cls]
        geom = unary_union(samples[cls])
        area = Layer(cls, tc.role, tc.height_mm, geom, profile=tc.profile)
        layers.append(area)
        pattern = cfg.texture(cls)
        if pattern is not None:
            tex = texture_geometry(geom, pattern)
            levels = None if tex.is_empty else texture_levels(tc.height_mm, pattern, cfg)
            if levels is not None:
                area.height_mm, z0, top = levels
                layers.append(Layer(f"{cls} texture", "texture", top, tex, z0_mm=z0, on=cls))
    if frames:
        layers.append(Layer("frame", "frame", FRAME_HEIGHT_MM, unary_union(frames)))
    r = spec.dot_diameter_mm / 2
    if dots:
        layers.append(Layer("braille", "braille", spec.dot_height_mm, unary_union([Point(p).buffer(r, 8) for p in dots])))
    plate = box(0, 0, w, h)
    return TactileModel(w, h, cfg.base_mm, 1.0, layers, plate, (0.0, 0.0, w, h), dots, spec, " / ".join(title_lines), 0.0)


def _layout(n: int, cfg: Config, title: str) -> tuple[list[str], float, int, int]:
    """Title lines, title block height, columns and rows of a legend with n entries."""
    spec = cfg.braille
    row_h = max(SWATCH_H_MM, spec.cell_height_mm) + 5.0
    title_lines = braille.wrap(title, 40) if title else []
    title_h = (len(title_lines) - 1) * spec.line_spacing_mm + spec.cell_height_mm + 5.0 if title_lines else 0.0
    fit_rows = max(1, int((cfg.legend_max_height_mm - 2 * EDGE_PAD_MM - title_h) // row_h))
    n_cols = max(1, math.ceil(n / fit_rows))
    n_rows = math.ceil(n / n_cols) if n else 0
    return title_lines, title_h, n_cols, n_rows


def feel(cfg: Config, cls: str) -> str:
    """How a class feels, in words."""
    tc = cfg.classes[cls]
    pattern = cfg.texture(cls)
    tex = t("legend.with", pattern=pattern.describe()) if pattern else t("legend.smooth")
    if tc.role == "object":
        shape = cfg.shape(cls)
        if tc.shape and not shape:
            return t("legend.as_drawn", width=num(tc.min_width_mm), height=num(tc.height_mm))
        kind = "dome" if shape == "dot" and tc.profile == "dome" else shape if shape in ("dot", "ring", "cross") else "ridge"
        size = t("legend.across", size=num(tc.size_mm)) if shape else t("legend.min_wide", width=num(tc.min_width_mm))
        return t("legend.object", name=t(f"legend.{kind}"), size=size, height=num(tc.height_mm))
    if tc.height_mm < 0:
        return t("legend.recessed", depth=num(-tc.height_mm), texture=tex)
    if tc.height_mm == 0:
        framed = t("legend.framed") if cfg.features.legend_frames else ""
        return t("legend.flat", texture=tex, framed=framed)
    return t("legend.raised", height=num(tc.height_mm), texture=tex)


def legend_text(classes: list[str], cfg: Config, tm: TactileModel, sources: dict[str, set[str]] | None = None) -> str:
    n_cols = _layout(len(classes), cfg, tm.title)[2]
    lines = [
        t("legend.heading", title=tm.title or t("describe.untitled")),
        "",
        t("legend.plate", w=num(tm.width_mm, ".0f"), h=num(tm.height_mm, ".0f"), base=num(tm.base_mm)),
        t("legend.reading", order=t("legend.order_rows") if n_cols > 1 else t("legend.order_column")),
        "",
        t("legend.entries"),
    ]
    for cls in classes:
        tc = cfg.classes[cls]
        line = t("legend.entry", label=tc.legend_label, feel=feel(cfg, cls))
        if sources and sources.get(cls):
            line += t("legend.sources", list="; ".join(sorted(sources[cls])))
        lines.append(line)
    return "\n".join(lines) + "\n"

