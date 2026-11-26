"""``description.txt``: the model explained in plain text, in the build's language.

Written for screen readers and for sighted helpers alike: short lines, lists rather
than tables, no colours. It says how to hold the model, what each height and texture
means (the legend), the scale, every change the tool made on its own (and the setting
that controls it), and what the tactile check found. The texts are in ``locales/``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .compose import Classified
from .config import Config
from .i18n import num, t
from .legend import classes_in_model, feel
from .model3d import TactileModel
from .scene import PT_TO_MM
from .tactile_check import summary_lines


def tactile_scale(cfg: Config, tm: TactileModel) -> float:
    """Scale of the model (e.g. 1000 for 1:1000), or 0 if the map scale is unknown."""
    return cfg.map_scale / (tm.scale / PT_TO_MM) if cfg.map_scale else 0.0


def _name(cfg: Config, cls: str) -> str:
    tc = cfg.classes.get(cls)
    return tc.legend_label if tc and tc.role != "ignore" else cls.replace("_", " ")


def automatic_changes(cfg: Config, tm: TactileModel, items: list[Classified]) -> list[str]:
    """Every decision the tool took on its own, in words, with the setting behind it."""
    sm, gen, f = cfg.smoothing, cfg.generalize, cfg.features
    lines = [t("describe.settings_used", sources=t("describe.then").join(cfg.sources))]

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
    shown = {lyr.cls for lyr in tm.tactile_layers()}
    if cfg.size_scale_used != 1.0:
        lines.append(t("describe.size_scale", factor=num(cfg.size_scale_used), note=cfg.size_scale_note))
    nearest = sorted({c.isom for c in items if "[nearest colour" in c.isom})
    if nearest:
        lines.append(t("describe.nearest_one") if len(nearest) == 1 else t("describe.nearest", n=len(nearest)))
    lines.append(t("describe.grouped"))
    for cls in sorted(symbols, key=lambda c: (cfg.classes[c].role, c)):
        if cls not in shown:
            continue
        extra = "".join(t("describe.merged", off=_name(cfg, s), shown=_name(cfg, cls), cls=s) for s in sorted(merged[cls]))
        lines.append(f"- {_name(cfg, cls)}: " + "; ".join(sorted(symbols[cls])) + extra + ".")
    if hidden:
        off = [t("describe.switched_off", name=_name(cfg, s)) if s in cfg.classes and cfg.classes[s].role != "ignore"
               else _name(cfg, s) for s in sorted(hidden)]
        lines.append(t("describe.not_shown", names=", ".join(off)))

    # Textures and symbols.
    textured = [f"{_name(cfg, c)}: {cfg.texture(c).describe()}" for c in sorted(shown) if cfg.texture(c)]
    if not f.textures:
        lines.append(t("describe.textures_off"))
    elif textured:
        lines.append(t("describe.textures", list="; ".join(textured)))
    counts = Counter(c.cls for c in items if c.role == "object")
    standard = [t("describe.standard_item", name=_name(cfg, c), size=num(cfg.classes[c].size_mm),
                  shape=t(f"shape.{cfg.shape(c)}"), count=counts[c])
                for c in sorted(shown) if cfg.shape(c)]
    if standard:
        lines.append(t("describe.standard", list="; ".join(standard)))
    elif not f.standard_symbols:
        lines.append(t("describe.as_drawn_points"))

    # Line objects and smoothing.
    drawn = [c for c in sorted(shown) if cfg.classes[c].role == "object" and not cfg.shape(c)]
    if drawn:
        widths = "; ".join(t("describe.width_item", name=_name(cfg, c), width=num(cfg.classes[c].min_width_mm))
                           for c in drawn)
        how = t("describe.widened", widths=widths) if gen.widen_objects else t("describe.not_widened")
        lines.append(t("describe.lines", how=how, cap=sm.line_cap, join=sm.line_join))
    lines.append(t("describe.curves", step=num(sm.curve_step_mm), segments=sm.arc_segments))
    outline = t("describe.simplified", mm=num(sm.simplify_mm)) if sm.simplify_mm else t("describe.exact")
    corners = t("describe.rounded", mm=num(sm.round_corners_mm)) if sm.round_corners_mm else t("describe.as_drawn")
    lines.append(t("describe.outlines", outline=outline, corners=corners))

    # Generalisation, with what it did on this map.
    g = tm.generalized or {}
    steps = []
    if gen.clean_slivers:
        steps.append(t("describe.slivers", n=g.get("slivers_moved", 0), mm=num(gen.sliver_mm)))
    if gen.open_passages:
        steps.append(t("describe.passages", n=g.get("passages_opened", 0), mm=num(cfg.tactile.min_gap_mm)))
    if gen.widen_thin:
        steps.append(t("describe.widen_thin", n=g.get("thin_parts_widened", 0), mm=num(cfg.tactile.min_feature_mm)))
    if gen.merge_close_objects:
        merges = ", ".join(f"{_name(cfg, c)} {n}" for c, n in sorted(g.get("objects_merged", {}).items()))
        steps.append(t("describe.merges", mm=num(gen.merge_gap_mm), merges=merges or t("describe.none")))
    if g.get("corners_rounded"):
        steps.append(t("describe.corners_rounded", n=g["corners_rounded"]))
    steps.append(t("describe.min_area", mm2=num(gen.min_area_mm2)))
    lines.append(t("describe.generalisation", steps="; ".join(steps)))
    return lines


def position_lines(tm: TactileModel, geo_check: list[str]) -> list[str]:
    """Where the position points are, on the plate and on Earth."""
    lines = []
    for p in tm.positions:
        pins = t("describe.one_pin") if p["pins"] == 1 else t("describe.n_pins", n=p["pins"])
        url = f"https://www.openstreetmap.org/?mlat={p['lat']:.6f}&mlon={p['lon']:.6f}&zoom=18"
        lines.append(t("describe.point", point=p["point"], pins=pins, x=num(p["x_mm"]), y=num(p["y_mm"]), text=p["text"],
                       url=url))
    if lines:
        lines.append(t("describe.coordinates_in_braille"))
    if tm.qr:
        lines.append(t("describe.qr", link=tm.qr["link"]))
    return lines + geo_check


def relief_lines(relief, cfg: Config, tm: TactileModel) -> list[str]:
    """The slopes (relief.py) in words."""
    if relief is None:
        return []
    if not tm.relief:
        return [t("relief.not_shown", note=relief.note or t("relief.flat"))]
    top = max(dz for _, dz in tm.relief)
    return [t("relief.steps", step=num(cfg.relief.step_mm), levels=relief.levels, top=num(top)),
            t("relief.direction", ticks=relief.ticks)]


def describe(tm: TactileModel, cfg: Config, check: dict, source: str, files: list[str],
             items: list[Classified] | None = None, size_lines: list[str] | None = None,
             geo_check: list[str] | None = None, relief=None) -> str:
    enlarge = tm.scale / PT_TO_MM  # model mm per PDF mm
    lines = [
        t("describe.heading", title=tm.title or t("describe.untitled")),
        "",
        t("describe.made_from", source=source),
        t("describe.plate", w=num(tm.width_mm, ".0f"), h=num(tm.height_mm, ".0f"), base=num(tm.base_mm),
          top=num(check["total_height_mm"])),
    ]
    if cfg.map_scale:
        ts = tactile_scale(cfg, tm)
        lines.append(t("describe.scale", scale=f"{ts:.0f}", map_scale=f"{cfg.map_scale:g}", enlarge=num(enlarge, ".2f"),
                       metres=num(ts / 100, ".0f")))
    else:
        lines.append(t("describe.scale_unknown", enlarge=num(enlarge, ".2f")))
    if size_lines:
        lines += ["", t("describe.size_heading")] + size_lines

    lines += ["", t("describe.hold_heading")]
    hold = [t("describe.north_up")]
    if any(lyr.role == "edge" for lyr in tm.layers):
        hold.append(t("describe.edge"))
    if any(lyr.role == "north" for lyr in tm.layers):
        hold.append(t("describe.north_symbols"))
    if tm.corner_mm:
        hold.append(t("describe.corner"))
    if tm.title:
        hold.append(t("describe.title", title=tm.title))
    if tm.scale_bar:
        b = tm.scale_bar
        where = t(f"bar.{b['where']}")
        ticks = t("describe.bar_ticks", metres=num(b["metres"] / b["divisions"])) if b["divisions"] > 1 else ""
        hold.append(t("describe.bar", where=where[0].upper() + where[1:], label=b["label"], ticks=ticks))
    elif cfg.features.scale_bar and not cfg.map_scale:
        hold.append(t("describe.no_bar"))
    lines.append(" ".join(hold))
    if tm.positions:
        lines += ["", t("describe.where_heading")] + position_lines(tm, geo_check or [])
    if relief is not None:
        lines += ["", t("describe.slopes_heading")] + relief_lines(relief, cfg, tm)

    lines += ["", t("describe.legend_heading")]
    classes = classes_in_model(tm, cfg)
    map_area = (tm.map_box[2] - tm.map_box[0]) * (tm.map_box[3] - tm.map_box[1])
    areas = {lyr.cls: lyr.geom.area for lyr in tm.tactile_layers()}
    for cls in classes:
        share = t("describe.share", pct=num(100 * areas[cls] / map_area, ".0f")) if cfg.classes[cls].role == "terrain" else ""
        lines.append(t("describe.legend_line", label=cfg.classes[cls].legend_label, feel=feel(cfg, cls), share=share))

    if items is not None:
        lines += ["", t("describe.changes_heading")]
        lines += automatic_changes(cfg, tm, items)

    lines += ["", t("describe.check_heading")]
    if check["ok"]:
        lines.append(t("describe.all_passed"))
    lines += summary_lines(check)
    examples = [(k, check[k]["examples_mm"]) for k in ("thin_parts", "narrow_gaps", "narrow_passages", "hidden_objects")
                if check[k]["count"]]
    if examples:
        lines.append(t("describe.examples"))
        for k, pts in examples:
            lines.append(f"- {t(f'check.{k}')}: " + "; ".join(f"{num(x)}, {num(y)}" for x, y in pts))
    if not check["ok"]:
        lines.append(t("describe.to_fix"))

    lines += ["", t("describe.files_heading")] + [f"- {f}" for f in files]
    return "\n".join(lines) + "\n"


def write_description(text: str, path: Path) -> None:
    path.write_text(text, encoding="utf-8")
