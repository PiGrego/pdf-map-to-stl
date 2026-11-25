"""``description.txt``: the model explained in plain text.

Written for screen readers and for sighted helpers alike: short lines, lists rather
than tables, no colours. It says how to hold the model, what each height and texture
means (the legend), the scale, every change the tool made on its own (and the setting
that controls it), and what the tactile check found.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .compose import Classified
from .config import Config
from .legend import classes_in_model, feel
from .model3d import TactileModel
from .scene import PT_TO_MM
from .tactile_check import summary_lines


def tactile_scale(cfg: Config, t: TactileModel) -> float:
    """Scale of the model (e.g. 1000 for 1:1000), or 0 if the map scale is unknown."""
    return cfg.map_scale / (t.scale / PT_TO_MM) if cfg.map_scale else 0.0


def _name(cfg: Config, cls: str) -> str:
    tc = cfg.classes.get(cls)
    return tc.legend_label if tc and tc.role != "ignore" else cls.replace("_", " ")


def automatic_changes(cfg: Config, t: TactileModel, items: list[Classified]) -> list[str]:
    """Every decision the tool took on its own, in words, with the setting behind it."""
    sm, gen, f = cfg.smoothing, cfg.generalize, cfg.features
    lines = ["Settings used: " + ", then ".join(cfg.sources) + ". All values are in settings_used.toml."]

    # Which map symbols became which tactile class, and which were left out.
    symbols: dict[str, set[str]] = defaultdict(set)
    merged: dict[str, set[str]] = defaultdict(set)
    hidden: Counter = Counter()
    for c in items:
        if c.role == "ignore":
            hidden[c.source or c.cls] += 1
        else:
            symbols[c.cls].add(c.isom)
            if c.source and c.source != c.cls:
                merged[c.cls].add(c.source)
    shown = {lyr.cls for lyr in t.tactile_layers()}
    if cfg.size_scale_used != 1.0:
        lines.append(f"Symbol sizes in the rules (line widths, dot screens) multiplied by {cfg.size_scale_used:g} "
                     f"for this PDF ({cfg.size_scale_note}; recognition.size_scale).")
    nearest = sorted({c.isom for c in items if "[nearest colour" in c.isom})
    if nearest:
        lines.append(f"{len(nearest)} kinds of symbol recognised by the nearest rule colour, not an exact one "
                     "(recognition.colour_match_de): check them in symbols.csv.")
    lines.append("Map symbols grouped into tactile classes (the [[symbol]] rules of the config):")
    for cls in sorted(symbols, key=lambda c: (cfg.classes[c].role, c)):
        if cls not in shown:
            continue
        extra = "".join(f" ({_name(cfg, s)} is switched off, so it is shown as {_name(cfg, cls)}: "
                        f"class.{s}.enabled)" for s in sorted(merged[cls]))
        lines.append(f"- {_name(cfg, cls)}: " + "; ".join(sorted(symbols[cls])) + extra + ".")
    if hidden:
        off = [f"{_name(cfg, s)} (switched off)" if s in cfg.classes and cfg.classes[s].role != "ignore"
               else _name(cfg, s) for s in sorted(hidden)]
        lines.append("Not shown: " + ", ".join(off) + ". Switch a class on with class.NAME.enabled = true; "
                     "classes with role ignore need a role first.")

    # Textures and symbols.
    textured = [f"{_name(cfg, c)}: {cfg.texture(c).describe()}" for c in sorted(shown) if cfg.texture(c)]
    if not f.textures:
        lines.append("Textures: off (features.textures); every area is smooth.")
    elif textured:
        lines.append("Textures (features.textures, class.NAME.texture): " + "; ".join(textured) + ".")
    counts = Counter(c.cls for c in items if c.role == "object")
    standard = [f"{_name(cfg, c)} as a {cfg.classes[c].size_mm:g} mm {cfg.shape(c)} ({counts[c]} on the map)"
                for c in sorted(shown) if cfg.shape(c)]
    if standard:
        lines.append("Point symbols drawn as standard tactile symbols (features.standard_symbols, "
                     "class.NAME.shape): " + "; ".join(standard) + ".")
    elif not f.standard_symbols:
        lines.append("Point symbols: as drawn on the map (features.standard_symbols is off).")

    # Line objects and smoothing.
    drawn = [c for c in sorted(shown) if cfg.classes[c].role == "object" and not cfg.shape(c)]
    if drawn:
        widths = "; ".join(f"{_name(cfg, c)} at least {cfg.classes[c].min_width_mm:g} mm" for c in drawn)
        how = f"widened to their class min_width_mm ({widths})" if gen.widen_objects else \
              "at the width drawn on the map (generalize.widen_objects is off)"
        lines.append(f"Lines are redrawn along their centre line, {how}, with {sm.line_cap} ends and "
                     f"{sm.line_join} corners (smoothing.line_cap, smoothing.line_join).")
    lines.append(f"Curves are read from the PDF with {sm.curve_step_mm:g} mm steps (smoothing.curve_step_mm); "
                 f"rounded shapes use {sm.arc_segments} segments per quarter circle (smoothing.arc_segments).")
    lines.append("Outlines: " + (f"simplified, detail under {sm.simplify_mm:g} mm removed" if sm.simplify_mm
                                 else "exact, as on the map") + " (smoothing.simplify_mm); corners: "
                 + (f"rounded with radius {sm.round_corners_mm:g} mm" if sm.round_corners_mm else "as drawn")
                 + " (smoothing.round_corners_mm).")

    # Generalisation, with what it did on this map.
    g = t.generalized or {}
    steps = []
    if gen.clean_slivers:
        steps.append(f"{g.get('slivers_moved', 0)} strips narrower than {gen.sliver_mm:g} mm given to the area "
                     "next to them (clean_slivers)")
    if gen.open_passages:
        steps.append(f"{g.get('passages_opened', 0)} passages widened to {cfg.tactile.min_gap_mm:g} mm (open_passages)")
    if gen.widen_thin:
        steps.append(f"{g.get('thin_parts_widened', 0)} raised parts widened to {cfg.tactile.min_feature_mm:g} mm "
                     "(widen_thin)")
    if gen.merge_close_objects:
        merges = ", ".join(f"{_name(cfg, c)} {n}" for c, n in sorted(g.get("objects_merged", {}).items())) or "none"
        steps.append(f"objects closer than {gen.merge_gap_mm:g} mm merged, which also rounds their inside "
                     f"corners (merge_close_objects; merges: {merges})")
    if g.get("corners_rounded"):
        steps.append(f"{g['corners_rounded']} corners rounded")
    steps.append(f"pieces smaller than {gen.min_area_mm2:g} square mm dropped (min_area_mm2)")
    lines.append("Generalisation ([generalize]): " + "; ".join(steps) + ".")
    return lines


def position_lines(t: TactileModel, geo_check: list[str]) -> list[str]:
    """Where the position points are, on the plate and on Earth."""
    lines = []
    for p in t.positions:
        pins = "one tall pin" if p["pins"] == 1 else f"{p['pins']} tall pins side by side"
        lines.append(f"Point {p['point']} ({pins}, {p['x_mm']:g} mm from the left and {p['y_mm']:g} mm from the "
                     f"bottom of the plate): {p['text']} (latitude, longitude in decimal degrees, WGS 84). "
                     f"On a web map: https://www.openstreetmap.org/?mlat={p['lat']:.6f}&mlon={p['lon']:.6f}&zoom=18")
    if lines:
        lines.append("The coordinates are also in Braille in the bottom margin, after the point number.")
    return lines + geo_check


def describe(t: TactileModel, cfg: Config, check: dict, source: str, files: list[str],
             items: list[Classified] | None = None, size_lines: list[str] | None = None,
             geo_check: list[str] | None = None) -> str:
    enlarge = t.scale / PT_TO_MM  # model mm per PDF mm
    lines = [
        f"TACTILE MAP: {t.title or 'untitled'}",
        "",
        f"Made from {source}.",
        (f"Plate: {t.width_mm:.0f} mm wide and {t.height_mm:.0f} mm deep. "
         f"Base {t.base_mm:g} mm thick; the highest point is {check['total_height_mm']:g} mm above the table."),
    ]
    if cfg.map_scale:
        ts = tactile_scale(cfg, t)
        lines.append(f"Scale: 1:{ts:.0f} (the printed map is 1:{cfg.map_scale:g}, enlarged {enlarge:.2f} times); "
                     f"1 cm on the model is {ts / 100:.0f} m on the ground.")
    else:
        lines.append(f"Scale: the model is {enlarge:.2f} times the size of the printed map.")
    if size_lines:
        lines += ["", "SIZE"] + size_lines

    lines += ["", "HOW TO HOLD IT"]
    hold = ["North is up."]
    if any(lyr.role == "edge" for lyr in t.layers):
        hold.append("The map has the shape of the chosen window; a low raised line runs along its edge, "
                    "and outside it the plate is flat.")
    if any(lyr.role == "north" for lyr in t.layers):
        hold.append("North symbols are at the top-right and bottom-left corners; their ring end points north.")
    if t.corner_mm:
        hold.append("The top-right corner of the plate is cut off.")
    if t.title:
        hold.append(f'The Braille title "{t.title}" is at the top left.')
    lines.append(" ".join(hold))
    if t.positions:
        lines += ["", "WHERE IT IS"] + position_lines(t, geo_check or [])

    lines += ["", "LEGEND (also printed as legend.stl)"]
    classes = classes_in_model(t, cfg)
    map_area = (t.map_box[2] - t.map_box[0]) * (t.map_box[3] - t.map_box[1])
    areas = {lyr.cls: lyr.geom.area for lyr in t.tactile_layers()}
    for cls in classes:
        label = cfg.classes[cls].legend_label
        share = f" (about {100 * areas[cls] / map_area:.0f} % of the map)" if cfg.classes[cls].role == "terrain" else ""
        lines.append(f"- {label}: {feel(cfg, cls)}{share}.")

    if items is not None:
        lines += ["", "AUTOMATIC CHANGES (each one is a setting; see docs/SETTINGS.md)"]
        lines += automatic_changes(cfg, t, items)

    lines += ["", "TACTILE CHECK"]
    if check["ok"]:
        lines.append("All checks passed.")
    lines += summary_lines(check)
    examples = [(k, check[k]["examples_mm"]) for k in ("thin_parts", "narrow_gaps", "narrow_passages", "hidden_objects")
                if check[k]["count"]]
    if examples:
        lines.append("Example places, in mm from the bottom-left corner of the plate (x to the right, y up):")
        for k, pts in examples:
            lines.append(f"- {k.replace('_', ' ')}: " + "; ".join(f"{x:g}, {y:g}" for x, y in pts))
    if not check["ok"]:
        lines.append("To fix: build at a larger scale (--scale or --width), convert a smaller part (--crop), "
                     "or change heights and textures (tuner.html).")

    lines += ["", "FILES"] + [f"- {f}" for f in files]
    return "\n".join(lines) + "\n"


def write_description(text: str, path: Path) -> None:
    path.write_text(text, encoding="utf-8")
