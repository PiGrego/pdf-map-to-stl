"""The whole conversion, step by step. Start reading the project here.

    PDF ──scene──▶ primitives ──config rules──▶ classes ──compose──▶ visible terrain + objects
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
from dataclasses import dataclass
from pathlib import Path

from .compose import build_map, classify
from .config import Config, load_config, settings_dict, to_toml
from .describe import describe, tactile_scale, write_description
from .legend import DEFAULT_TITLE, build_legend, classes_in_map, classes_in_model, legend_text
from .model3d import TactileModel, build_layers, build_solid, layer_summary, write_stl
from .parts import build_parts, write_parts
from .preview import check_image, relief_image
from .report import symbol_inventory, write_csv, write_json, write_layers_svg
from .scene import PT_TO_MM, load_scene
from .tactile_check import check_model
from .tuner import write_tuner
from .validate import class_colours, validate

Rect = tuple[float, float, float, float]

OUTPUT_FILES = [
    "model.stl: the tactile map to print, as one body.",
    "parts/: the same map as one STL per layer, to load as one multi-part object in the slicer (see parts/README.txt).",
    "legend.stl and legend_parts/: the tactile legend, as one body and per layer.",
    "description.txt: this description, including every automatic change.",
    "settings_used.toml: every setting this build used; build again with --settings settings_used.toml.",
    "tuner.html: choose heights, textures and which features to show; saves settings.toml.",
    "symbols.csv: every map symbol found and the class it became.",
    "relief_preview.png and legend_preview.png: pictures of the models.",
    "tactile_check.png: picture of the places the tactile check flags.",
    "report.json: all numbers.",
]


@dataclass
class BuildOptions:
    pdf: Path
    out: Path
    config: Path | None = None  # symbol rules + classes; default config/default.toml
    heights: Path | None = None  # heights.toml from the tuner (same as a settings file)
    page: int = 0
    crop_mm: Rect | None = None  # part of the PDF page, mm from its top-left corner
    width_mm: float | None = None  # printed model width; overrides the config
    region_mm: Rect | None = None  # test tile on the map, mm from its bottom-left corner
    title: str | None = None  # Braille title; None = from config ("auto" = file name)
    map_scale: float | None = None  # scale of the printed map, e.g. 5000 for 1:5000
    scale: float | None = None  # wanted scale of the tactile map, e.g. 1000 (needs map_scale)
    validate: bool = True
    settings: tuple = ()  # settings files or profile names, applied in order after the config
    overrides: tuple = ()  # "section.key=value" strings, applied last


def resolve_title(option: str | None, config_title: str, pdf: Path) -> str:
    title = config_title if option is None else option
    return pdf.stem.replace("_", " ").replace("-", " ") if title == "auto" else title


def _set_size(cfg: Config, o: BuildOptions, scene_width_pt: float) -> None:
    if o.width_mm:
        cfg.width_mm = o.width_mm
    if o.map_scale is not None:
        cfg.map_scale = o.map_scale
    if o.scale:
        if not cfg.map_scale:
            raise ValueError("--scale needs the scale of the printed map: add --map-scale (e.g. 5000)")
        cfg.width_mm = scene_width_pt * PT_TO_MM * cfg.map_scale / o.scale


def _write_model(t: TactileModel, out: Path, name: str, parts_dir: str, cfg: Config) -> tuple[dict, list[dict]]:
    stl = write_stl(build_solid(t), out / f"{name}.stl")
    colours = class_colours(cfg, "forest")
    parts = write_parts(build_parts(t, cfg.top_skin_mm, colours), out / parts_dir, t.title or name)
    return stl, parts


def write_settings(cfg: Config, path: Path, pdf_name: str) -> None:
    header = (f"Every setting used to build {pdf_name}, from (in this order):\n"
              + "\n".join(f"  {s}" for s in cfg.sources)
              + "\nBuild the same model again with: --settings settings_used.toml\n"
              "Symbol rules are not included: they stay in the config file.")
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
    cmd += ["--settings", _arg(o.out / "settings_used.toml"), "--settings", "settings.toml", "-o", _arg(o.out)]
    return " ".join(cmd)


def build(o: BuildOptions) -> dict:
    t0 = time.perf_counter()
    o.out.mkdir(parents=True, exist_ok=True)

    # 1. Configuration: symbol rules, tactile classes and every setting (+ settings files).
    cfg = load_config(o.config, o.heights, o.settings, o.overrides)

    # 2. Scene: every paint operation of the page (or crop) as a clipped polygon.
    scene = load_scene(o.pdf, o.page, o.crop_mm, cfg.smoothing.curve_step_mm)
    _set_size(cfg, o, scene.width_pt)
    write_settings(cfg, o.out / "settings_used.toml", o.pdf.name)

    # 3. Classify and compose: which terrain is visible where; which objects sit on top.
    m = build_map(scene, cfg)

    # 4. Tactile model and legend at print scale; one body and one part per layer each.
    title = resolve_title(o.title, cfg.title, o.pdf)
    if title and cfg.map_scale:
        title += f" 1:{cfg.map_scale * scene.width_pt * PT_TO_MM / cfg.width_mm:.0f}"
    t = build_layers(m, cfg, o.region_mm, title)
    stl, parts = _write_model(t, o.out, "model", "parts", cfg)
    legend = build_legend(classes_in_model(t, cfg), cfg)
    legend_stl, legend_parts = _write_model(legend, o.out, "legend", "legend_parts", cfg)

    # 5. Can it be read by touch?
    check = check_model(t, cfg)

    # 6. Things to read and look at.
    colours = class_colours(cfg, m.background_class)
    source = f"{o.pdf.name}, page {o.page + 1}" + (f", area {o.crop_mm} mm" if o.crop_mm else "")
    write_description(describe(t, cfg, check.summary, source, OUTPUT_FILES, m.items), o.out / "description.txt")
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
            "braille_title": t.title,
        },
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
        "seconds": round(time.perf_counter() - t0, 2),
    }
    write_json(report, o.out / "report.json")
    return report


@dataclass
class LegendOptions:
    pdf: Path
    out: Path
    config: Path | None = None
    heights: Path | None = None
    page: int = 0
    crop_mm: Rect | None = None
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
        legend_text(classes, cfg, legend, sources) + f"\nMade from {o.pdf.name}.\n"
        "Files: legend.stl (one body), parts/ (one STL per layer, see parts/README.txt), legend_preview.png, "
        "settings_used.toml.\n",
        encoding="utf-8",
    )
    relief_image(legend, class_colours(cfg, "forest")).save(o.out / "legend_preview.png")
    report = {"pdf": str(o.pdf), "classes": classes, "sources": {k: sorted(v) for k, v in sources.items()},
              "legend_stl": stl, "parts": parts,
              "size_mm": [round(legend.width_mm, 1), round(legend.height_mm, 1)]}
    write_json(report, o.out / "legend_report.json")
    return report
