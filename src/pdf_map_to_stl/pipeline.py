"""The whole conversion, step by step. Start reading the project here.

    PDF ──scene──▶ primitives ──config rules──▶ classes ──compose──▶ visible terrain + objects
        ──size─────▶ suggested print size (from the map's details and scale)
        ──model3d──▶ tactile layers (mm): generalised, textures, Braille title, north symbols
        ──▶ model.stl (one body) + parts/*.stl (one per layer, for the slicer)
        ──legend───▶ legend.stl + legend_parts/*.stl
        ──tactile_check──▶ can it be read by touch? ──▶ description.txt, tactile_check.png
        ──▶ tuner.html, previews, report

``build`` makes a tactile map; ``build_legend_sample`` makes a stand-alone legend with
every tactile symbol found in a map. Each step lives in its own module; this file only
calls them in order and writes outputs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path

from . import i18n
from .compose import build_map, classify
from .config import Config, load_config, settings_dict, to_toml
from .describe import describe, tactile_scale, write_description
from .geo import MAX_POINTS, GeoPoint, check_points
from .legend import DEFAULT_TITLE, build_legend, classes_in_map, classes_in_model, legend_text
from .model3d import TactileModel, build_layers, build_solid, layer_summary, margins, write_stl
from .parts import build_parts, write_parts
from .preview import check_image, relief_image, terraces_image
from .relief import find_relief
from .report import symbol_inventory, write_csv, write_json, write_layers_svg
from .scene import PT_TO_MM, Window, load_scene, page_size_mm, read_map_scale
from .size import SizeSuggestion, describe_size, suggest_size
from .tactile_check import check_model
from .tuner import write_tuner
from .validate import class_colours, validate

Rect = tuple[float, float, float, float]
MIN_PLATE_MAP_MM = 10.0  # a fixed plate (--plate) must leave at least this much height for the map

OUTPUT_FILES = ("model", "parts", "legend", "description", "settings", "tuner", "symbols", "previews", "check", "report")


def output_files() -> list[str]:
    """The files a build writes, in words (the FILES list of description.txt)."""
    return [i18n.t(f"pipeline.file_{f}") for f in OUTPUT_FILES]


@dataclass
class BuildOptions:
    pdf: Path
    out: Path
    config: Path | None = None  # symbol rules + classes; default config/default.toml
    heights: Path | None = None  # heights.toml from the tuner (same as a settings file)
    page: int = 0
    crop_mm: Window | None = None  # window on the PDF page (rectangle or polygon), mm from its top-left
    width_mm: float | None = None  # printed map width; overrides the config and the suggested size
    region_mm: Rect | None = None  # test tile on the map, mm from its bottom-left corner
    title: str | None = None  # Braille title; None = from config ("auto" = file name)
    map_scale: float | None = None  # scale of the printed map, e.g. 5000 for 1:5000
    scale: float | None = None  # wanted scale of the tactile map, e.g. 1000 (needs map_scale)
    validate: bool = True
    settings: tuple = ()  # settings files or profile names, applied in order after the config
    overrides: tuple = ()  # "section.key=value" strings, applied last
    geo: tuple[GeoPoint, ...] = ()  # position points: where the map is on Earth (geo.py)
    plate_mm: tuple[float, float] | None = None  # fixed plate size (--plate): the window is made to fill it


def describe_window(crop_mm) -> str:
    """The window in words, for the description."""
    v = [f"{x:g}" for x in crop_mm]
    if len(v) == 4:
        return i18n.t("pipeline.window_rect", x0=i18n.num(crop_mm[0]), x1=i18n.num(crop_mm[2]),
                      y0=i18n.num(crop_mm[1]), y1=i18n.num(crop_mm[3]))
    return i18n.t("pipeline.window_polygon", n=len(v) // 2, points=",".join(v))


def resolve_title(option: str | None, config_title: str, pdf: Path) -> str:
    title = config_title if option is None else option
    return pdf.stem.replace("_", " ").replace("-", " ") if title == "auto" else title


def set_map_scale(cfg: Config, map_scale: float | None, pdf: Path, page: int) -> str:
    """The printed map's scale: --map-scale, else the config, else read from the page."""
    if map_scale is not None:
        cfg.map_scale = map_scale
        return "--map-scale"
    if cfg.map_scale:
        return "settings"
    if cfg.read_map_scale:
        cfg.map_scale = read_map_scale(pdf, page)
        return "read from the page" if cfg.map_scale else "unknown"
    return "unknown"


def plate_window(o: BuildOptions, cfg: Config) -> Rect:
    """--plate: the window, in mm on the page, that fills a plate of exactly ``o.plate_mm``
    at the tactile scale ``o.scale``. It is centred where the picked window (--crop) is,
    or on the page, and moved inside the page if it would stick out. Its height leaves
    room for the margins (Braille title, north symbols, coordinates) on the plate."""
    w, h = o.plate_mm
    if not o.scale:
        raise ValueError("--plate needs --scale, the scale of the tactile map (for example --scale 1000)")
    if o.width_mm:
        raise ValueError("--plate already sets the width of the map: leave out --width")
    if not cfg.map_scale:
        raise ValueError("--plate needs the scale of the printed map: add --map-scale (for example 5000)")
    if o.crop_mm is not None and len(o.crop_mm) != 4:
        raise ValueError("--plate needs a rectangle window (--crop with 4 numbers), not a polygon")
    page_w, page_h = page_size_mm(o.pdf, o.page)
    if o.crop_mm is None:
        cx, cy = page_w / 2, page_h / 2
    else:
        x0, y0, x1, y1 = o.crop_mm
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    title = resolve_title(o.title, cfg.title, o.pdf)
    if title:
        title += f" 1:{o.scale:.0f}"  # as build() writes it
    mg = margins(cfg, w, title, o.geo, o.region_mm, o.scale / 1000)  # 1:1000 = 1 m on the ground per mm
    map_h = h - mg.top - mg.bottom
    if map_h < MIN_PLATE_MAP_MM:
        raise ValueError(f"a {w:g} by {h:g} mm plate leaves no room for the map: the Braille title, north symbols "
                         f"and coordinates take {mg.top + mg.bottom:g} mm of its height")
    enlarge = cfg.map_scale / o.scale  # mm on the plate per mm on the page
    ww, wh = w / enlarge, map_h / enlarge
    if ww > page_w + 1e-6 or wh > page_h + 1e-6:
        raise ValueError(f"at 1:{o.scale:g} a {w:g} by {h:g} mm plate needs {ww:.0f} by {wh:.0f} mm of the map page, "
                         f"more than the whole page ({page_w:.0f} by {page_h:.0f} mm): use a larger scale number "
                         "or a smaller plate")
    x0 = min(max(cx - ww / 2, 0.0), page_w - ww)
    y0 = min(max(cy - wh / 2, 0.0), page_h - wh)
    # Rounded as the description and the rebuild command write it, so a rebuild is identical.
    return (round(x0, 3), round(y0, 3), round(x0 + ww, 3), round(y0 + wh, 3))


def _set_size(cfg: Config, o: BuildOptions, scene_width_pt: float, sg: SizeSuggestion) -> str:
    """Set the printed map width; returns where it came from."""
    if o.plate_mm:
        cfg.width_mm = float(o.plate_mm[0])
        return "--plate"
    if o.width_mm:
        cfg.width_mm = o.width_mm
        return "--width"
    if o.scale:
        if not cfg.map_scale:
            raise ValueError("--scale needs the scale of the printed map: add --map-scale (e.g. 5000)")
        # Rounded as settings_used.toml writes it, so a rebuild from that file is identical.
        cfg.width_mm = round(scene_width_pt * PT_TO_MM * cfg.map_scale / o.scale, 3)
        return "--scale"
    if cfg.width_mm:
        return "output.width_mm"
    cfg.width_mm = round(sg.width_mm, 3)
    return "suggested"


def _write_model(t: TactileModel, out: Path, name: str, parts_dir: str, cfg: Config) -> tuple[dict, list[dict]]:
    stl = write_stl(build_solid(t), out / f"{name}.stl")
    colours = class_colours(cfg, "forest")
    parts = write_parts(build_parts(t, cfg.top_skin_mm, colours), out / parts_dir, t.title or name)
    return stl, parts


def write_settings(cfg: Config, path: Path, pdf_name: str) -> None:
    header = (i18n.t("pipeline.settings_header", pdf=pdf_name) + "\n"
              + "\n".join(f"  {s}" for s in cfg.sources)
              + "\n" + i18n.t("pipeline.settings_again") + "\n" + i18n.t("pipeline.settings_rules"))
    path.write_text(to_toml(settings_dict(cfg), header), encoding="utf-8")


def switchable_classes(items, cfg: Config) -> list[str]:
    """Classes found in the map that can be shown: on, or switched off (for the tuner)."""
    found = {c.source or c.cls for c in items}
    return sorted(c for c in found if c in cfg.classes and cfg.classes[c].role != "ignore")


def _arg(v) -> str:
    v = str(v)
    return f'"{v}"' if " " in v else v


def rebuild_command(o: BuildOptions) -> str:
    """The command that builds this model again with the tuner's settings.toml on top:
    the same PDF, area and config, and this build's settings_used.toml."""
    cmd = ["pdf-map-to-stl", "build", _arg(o.pdf)]
    if o.page:
        cmd += ["--page", str(o.page)]
    if o.crop_mm:
        cmd += ["--crop", ",".join(f"{v:g}" for v in o.crop_mm)]
    if o.config:
        cmd += ["-c", _arg(o.config)]
    if o.title is not None:
        cmd += ["--title", f'"{o.title}"']
    for p in o.geo:
        cmd += ["--geo", f"{p.x_mm:g},{p.y_mm:g},{p.lat:.7f},{p.lon:.7f}"]
    cmd += ["--settings", _arg(o.out / "settings_used.toml"), "--settings", "settings.toml", "-o", _arg(o.out)]
    return " ".join(cmd)


def input_warnings(validation: dict, cfg: Config, stls: list[dict], inventory: list[dict] = ()) -> list[str]:
    """Signs that the input, not the map, is the problem: a model that disagrees with the
    PDF, a window that could hardly be checked, an STL that is not closed, symbols known
    only by their nearest colour, symbol sizes that differ from the rules."""
    out = []
    nearest = [r for r in inventory if "[nearest colour" in r["isom"]]
    def pct(x: float, spec: str) -> str:
        return format(x, spec).replace(".", i18n.t("number.decimal_mark"))

    if nearest:
        out.append(i18n.t("pipeline.warn_nearest_one") if len(nearest) == 1 else i18n.t("pipeline.warn_nearest", n=len(nearest)))
    if cfg.size_scale_used != 1.0:
        out.append(i18n.t("pipeline.warn_size_scale", factor=i18n.num(cfg.size_scale_used), note=cfg.size_scale_note))
    v = validation.get("metrics") if validation else None
    if v and v["accuracy"] < cfg.validate.min_agreement:
        out.append(i18n.t("pipeline.warn_agreement", pct=pct(v["accuracy"], ".1%"),
                          min=pct(cfg.validate.min_agreement, ".0%")))
    share = v.get("checked_share_of_window") if v else None
    if share is not None and share < cfg.validate.min_checked_share:
        out.append(i18n.t("pipeline.warn_checked", pct=pct(share, ".0%"), min=pct(cfg.validate.min_checked_share, ".0%")))
    for s in stls:
        if s.get("open_edges"):
            out.append(i18n.t("pipeline.warn_open_edges", n=s["open_edges"]))
    return out


def build(o: BuildOptions) -> dict:
    t0 = time.perf_counter()
    o.out.mkdir(parents=True, exist_ok=True)

    # 1. Configuration: symbol rules, tactile classes and every setting (+ settings files).
    cfg = load_config(o.config, o.heights, o.settings, o.overrides)

    # 2. Scene: every paint operation of the page (or crop) as a clipped polygon. A fixed
    #    plate (--plate) first sets the window that fills it.
    map_scale_source = set_map_scale(cfg, o.map_scale, o.pdf, o.page)
    if o.plate_mm:
        o = replace(o, crop_mm=plate_window(o, cfg))
    scene = load_scene(o.pdf, o.page, o.crop_mm, cfg.smoothing.curve_step_mm)

    # 3. Classify and compose: which terrain is visible where; which objects sit on top.
    m = build_map(scene, cfg)

    # 4. Size: suggested from the map's details; --width, --scale or the settings override it.
    suggestion = suggest_size(m, cfg)
    size_source = _set_size(cfg, o, scene.width_pt, suggestion)
    size_lines = describe_size(suggestion, cfg, cfg.width_mm, size_source)
    if o.plate_mm:
        x0, y0, x1, y1 = o.crop_mm
        size_lines.append(i18n.t("size.plate_fixed", w=i18n.num(o.plate_mm[0]), h=i18n.num(o.plate_mm[1]),
                                 scale=f"{o.scale:g}", ww=i18n.num(x1 - x0, ".1f"), wh=i18n.num(y1 - y0, ".1f")))
    write_settings(cfg, o.out / "settings_used.toml", o.pdf.name)

    # 5. Tactile model and legend at print scale; one body and one part per layer each.
    title = resolve_title(o.title, cfg.title, o.pdf)
    if title and cfg.map_scale:
        title += f" 1:{cfg.map_scale * scene.width_pt * PT_TO_MM / cfg.width_mm:.0f}"
    if len(o.geo) > MAX_POINTS:
        raise ValueError(f"at most {MAX_POINTS} position points (--geo)")
    relief = find_relief(m, cfg) if cfg.relief.enabled else None
    t = build_layers(m, cfg, o.region_mm, title, o.geo, relief)
    stl, parts = _write_model(t, o.out, "model", "parts", cfg)
    legend = build_legend(classes_in_model(t, cfg), cfg)
    legend_stl, legend_parts = _write_model(legend, o.out, "legend", "legend_parts", cfg)

    # 6. Can it be read by touch?
    check = check_model(t, cfg)

    # 7. Things to read and look at.
    colours = class_colours(cfg, m.background_class)
    source = i18n.t("pipeline.source", pdf=o.pdf.name, page=o.page + 1) + (
        f", {describe_window(o.crop_mm)}" if o.crop_mm else "")
    write_description(describe(t, cfg, check.summary, source, output_files(), m.items, size_lines,
                               check_points(list(o.geo), cfg.map_scale), relief), o.out / "description.txt")
    if t.relief:
        terraces_image(t, colours).save(o.out / "relief_levels.png")
    relief_image(t, colours).save(o.out / "relief_preview.png")
    relief_image(legend, colours).save(o.out / "legend_preview.png")
    check_image(t, check.problems).save(o.out / "tactile_check.png")
    write_layers_svg(t, colours, o.out / "layers.svg")
    write_tuner(t, colours, o.out / "tuner.html", o.pdf.name, cfg, check.summary, switchable_classes(m.items, cfg),
                rebuild_command(o))
    inventory = symbol_inventory(m)
    write_csv(inventory, o.out / "symbols.csv")
    validation = {}
    if o.validate:
        v = validate(m, cfg)
        v.class_image.save(o.out / "classes.png")
        v.error_image.save(o.out / "validation_errors.png")
        validation = {"metrics": v.metrics, "per_class": v.per_class}

    report = {
        "pdf": str(o.pdf),
        "page": o.page,
        "crop_mm": o.crop_mm,
        "region_mm": o.region_mm,
        "scene": scene.stats,
        "model": {
            "width_mm": round(t.width_mm, 3),
            "height_mm": round(t.height_mm, 3),
            "base_mm": t.base_mm,
            "map_box_mm": [round(v, 3) for v in t.map_box],
            "scale_model_mm_per_pdf_mm": round(t.scale * 72 / 25.4, 4),
            "tactile_scale": round(tactile_scale(cfg, t)),
            "map_scale": cfg.map_scale,
            "map_scale_source": map_scale_source,
            "braille_title": t.title,
        },
        "size": {**suggestion.as_dict(), "used_width_mm": round(cfg.width_mm, 3), "source": size_source,
                 "plate_mm": list(o.plate_mm) if o.plate_mm else None, "window_mm": list(o.crop_mm or ()),
                 "lines": size_lines},
        "positions": t.positions,
        "scale_bar": t.scale_bar,
        "qr": t.qr,
        "relief": None if relief is None else {
            "levels": relief.levels, "lines": relief.lines, "ticks": relief.ticks, "note": relief.note,
            "lift_mm": [round(dz, 3) for _, dz in t.relief]},
        "layers": layer_summary(t),
        "stl": stl,
        "parts": parts,
        "legend_stl": legend_stl,
        "legend_parts": legend_parts,
        "tactile_check": check.summary,
        "generalized": t.generalized,
        "settings": cfg.sources,
        "validation": validation,
        "unclassified": [r for r in inventory if r["class"] == "unclassified"],
        "warnings": input_warnings(validation, cfg, [stl, legend_stl], inventory),
        "recognition": {"size_scale": cfg.size_scale_used, "note": cfg.size_scale_note},
        "seconds": round(time.perf_counter() - t0, 2),
    }
    write_json(report, o.out / "report.json")
    return report


def suggest(pdf: Path, page: int = 0, crop_mm: Window | None = None, config: Path | None = None,
            settings: tuple = (), overrides: tuple = (), map_scale: float | None = None) -> tuple[SizeSuggestion, list[str]]:
    """Only the suggested size of a map (or part of it), without building: quick."""
    cfg = load_config(config, None, settings, overrides)
    scene = load_scene(pdf, page, crop_mm, cfg.smoothing.curve_step_mm)
    set_map_scale(cfg, map_scale, pdf, page)
    sg = suggest_size(build_map(scene, cfg), cfg)
    return sg, describe_size(sg, cfg, sg.width_mm, "")


@dataclass
class LegendOptions:
    pdf: Path
    out: Path
    config: Path | None = None
    heights: Path | None = None
    page: int = 0
    crop_mm: Window | None = None
    title: str = DEFAULT_TITLE
    settings: tuple = ()
    overrides: tuple = ()


def build_legend_sample(o: LegendOptions) -> dict:
    """A stand-alone tactile legend with every tactile symbol found in a map (or crop)."""
    o.out.mkdir(parents=True, exist_ok=True)
    cfg = load_config(o.config, o.heights, o.settings, o.overrides)
    scene = load_scene(o.pdf, o.page, o.crop_mm, cfg.smoothing.curve_step_mm)
    write_settings(cfg, o.out / "settings_used.toml", o.pdf.name)
    classes, sources = classes_in_map(classify(scene, cfg), cfg)
    legend = build_legend(classes, cfg, o.title)
    stl, parts = _write_model(legend, o.out, "legend", "parts", cfg)
    (o.out / "legend.txt").write_text(
        legend_text(classes, cfg, legend, sources) + "\n" + i18n.t("legend_sample.made_from", pdf=o.pdf.name) + "\n"
        + i18n.t("legend_sample.files") + "\n",
        encoding="utf-8",
    )
    relief_image(legend, class_colours(cfg, "forest")).save(o.out / "legend_preview.png")
    report = {"pdf": str(o.pdf), "classes": classes, "sources": {k: sorted(v) for k, v in sources.items()},
              "legend_stl": stl, "parts": parts,
              "size_mm": [round(legend.width_mm, 1), round(legend.height_mm, 1)]}
    write_json(report, o.out / "legend_report.json")
    return report
