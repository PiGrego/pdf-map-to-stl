"""The whole conversion, step by step. Start reading the project here.

    PDF ──scene──▶ primitives ──config rules──▶ classes ──compose──▶ visible terrain + objects
        ──model3d──▶ tactile layers (mm) ──▶ watertight solid ──▶ model.stl
                                         └─▶ tuner.html, previews, report

Each step lives in its own module; this file only calls them in order and writes outputs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .compose import build_map
from .config import load_config
from .model3d import build_layers, build_solid, layer_summary, write_stl
from .preview import relief_image
from .report import symbol_inventory, write_csv, write_json, write_layers_svg
from .scene import load_scene
from .tuner import write_tuner
from .validate import class_colours, validate

Rect = tuple[float, float, float, float]


@dataclass
class BuildOptions:
    pdf: Path
    out: Path
    config: Path | None = None  # symbol rules + classes; default config/default.toml
    heights: Path | None = None  # heights.toml from the tuner, overrides the config
    page: int = 0
    crop_mm: Rect | None = None  # part of the PDF page, mm from its top-left corner
    width_mm: float | None = None  # printed model width; overrides the config
    region_mm: Rect | None = None  # test tile on the model, mm from its bottom-left corner
    validate: bool = True


def build(o: BuildOptions) -> dict:
    t0 = time.perf_counter()
    o.out.mkdir(parents=True, exist_ok=True)

    # 1. Configuration: symbol rules and tactile classes (+ tuned heights).
    cfg = load_config(o.config, o.heights)
    if o.width_mm:
        cfg.width_mm = o.width_mm

    # 2. Scene: every paint operation of the page (or crop) as a clipped polygon.
    scene = load_scene(o.pdf, o.page, o.crop_mm)

    # 3. Classify and compose: which terrain is visible where; which objects sit on top.
    m = build_map(scene, cfg)

    # 4. Tactile model at print scale, and the 3D solid.
    t = build_layers(m, cfg, o.region_mm)
    stl = write_stl(build_solid(t), o.out / "model.stl")

    # 5. Things to look at: previews, tuner, symbol table, validation.
    colours = class_colours(cfg, m.background_class)
    relief_image(t, colours).save(o.out / "relief_preview.png")
    write_layers_svg(t, colours, o.out / "layers.svg")
    write_tuner(t, colours, o.out / "tuner.html", o.pdf.name, str(o.config or "default.toml"))
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
            "scale_model_mm_per_pdf_mm": round(t.scale * 72 / 25.4, 4),
        },
        "layers": layer_summary(t),
        "stl": stl,
        "validation": validation,
        "unclassified": [r for r in inventory if r["class"] == "unclassified"],
        "seconds": round(time.perf_counter() - t0, 2),
    }
    write_json(report, o.out / "report.json")
    return report
