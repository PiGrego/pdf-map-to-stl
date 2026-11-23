"""The whole conversion, step by step. Start reading the project here.

    PDF ──scene──▶ primitives ──config rules──▶ classes ──compose──▶ visible terrain + objects
        ──model3d──▶ tactile layers (mm) + textures + Braille title ──▶ model.stl
        ──legend───▶ tactile legend ──▶ legend.stl
        ──tactile_check──▶ can it be read by touch? ──▶ description.txt, tactile_check.png
        ──▶ tuner.html, previews, report

Each step lives in its own module; this file only calls them in order and writes outputs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .compose import build_map
from .config import load_config
from .describe import describe, write_description
from .legend import build_legend
from .model3d import build_layers, build_solid, layer_summary, write_stl
from .preview import check_image, relief_image
from .report import symbol_inventory, write_csv, write_json, write_layers_svg
from .scene import load_scene
from .tactile_check import check_model
from .tuner import write_tuner
from .validate import class_colours, validate

Rect = tuple[float, float, float, float]

OUTPUT_FILES = [
    "model.stl: the tactile map to print.",
    "legend.stl: the tactile legend to print.",
    "description.txt: this description.",
    "tuner.html: choose heights (works with keyboard and screen reader).",
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
    heights: Path | None = None  # heights.toml from the tuner, overrides the config
    page: int = 0
    crop_mm: Rect | None = None  # part of the PDF page, mm from its top-left corner
    width_mm: float | None = None  # printed model width; overrides the config
    region_mm: Rect | None = None  # test tile on the map, mm from its bottom-left corner
    title: str | None = None  # Braille title; None = from config ("auto" = file name)
    map_scale: float | None = None  # e.g. 4000 for 1:4000, for the description
    validate: bool = True


def resolve_title(option: str | None, config_title: str, pdf: Path) -> str:
    title = config_title if option is None else option
    return pdf.stem.replace("_", " ").replace("-", " ") if title == "auto" else title


def build(o: BuildOptions) -> dict:
    t0 = time.perf_counter()
    o.out.mkdir(parents=True, exist_ok=True)

    # 1. Configuration: symbol rules, tactile classes, tactile rules (+ tuned heights).
    cfg = load_config(o.config, o.heights)
    if o.width_mm:
        cfg.width_mm = o.width_mm
    if o.map_scale is not None:
        cfg.map_scale = o.map_scale

    # 2. Scene: every paint operation of the page (or crop) as a clipped polygon.
    scene = load_scene(o.pdf, o.page, o.crop_mm)

    # 3. Classify and compose: which terrain is visible where; which objects sit on top.
    m = build_map(scene, cfg)

    # 4. Tactile model and legend at print scale, and their 3D solids.
    t = build_layers(m, cfg, o.region_mm, resolve_title(o.title, cfg.title, o.pdf))
    stl = write_stl(build_solid(t), o.out / "model.stl")
    legend = build_legend(t, cfg)
    legend_stl = write_stl(build_solid(legend), o.out / "legend.stl")

    # 5. Can it be read by touch?
    check = check_model(t, cfg)

    # 6. Things to read and look at.
    colours = class_colours(cfg, m.background_class)
    source = f"{o.pdf.name}, page {o.page + 1}" + (f", area {o.crop_mm} mm" if o.crop_mm else "")
    write_description(describe(t, cfg, check.summary, source, OUTPUT_FILES), o.out / "description.txt")
    relief_image(t, colours).save(o.out / "relief_preview.png")
    relief_image(legend, colours).save(o.out / "legend_preview.png")
    check_image(t, check.problems).save(o.out / "tactile_check.png")
    write_layers_svg(t, colours, o.out / "layers.svg")
    write_tuner(t, colours, o.out / "tuner.html", o.pdf.name, str(o.config or "default.toml"), cfg, check.summary)
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
            "braille_title": t.title,
        },
        "layers": layer_summary(t),
        "stl": stl,
        "legend_stl": legend_stl,
        "tactile_check": check.summary,
        "validation": validation,
        "unclassified": [r for r in inventory if r["class"] == "unclassified"],
        "seconds": round(time.perf_counter() - t0, 2),
    }
    write_json(report, o.out / "report.json")
    return report
