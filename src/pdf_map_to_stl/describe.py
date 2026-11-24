"""``description.txt``: the model explained in plain text.

Written for screen readers and for sighted helpers alike: short lines, lists rather
than tables, no colours. It says how to hold the model, what each height and texture
means (the legend), the scale, and what the tactile check found.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .legend import classes_in_model, feel
from .model3d import TactileModel
from .scene import PT_TO_MM
from .tactile_check import summary_lines


def tactile_scale(cfg: Config, t: TactileModel) -> float:
    """Scale of the model (e.g. 1000 for 1:1000), or 0 if the map scale is unknown."""
    return cfg.map_scale / (t.scale / PT_TO_MM) if cfg.map_scale else 0.0


def describe(t: TactileModel, cfg: Config, check: dict, source: str, files: list[str]) -> str:
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

    lines += ["", "HOW TO HOLD IT"]
    hold = ["North is up."]
    if any(lyr.role == "north" for lyr in t.layers):
        hold.append("North symbols are at the top-right and bottom-left corners; their ring end points north.")
    if t.corner_mm:
        hold.append("The top-right corner of the plate is cut off.")
    if t.title:
        hold.append(f'The Braille title "{t.title}" is at the top left.')
    lines.append(" ".join(hold))

    lines += ["", "LEGEND (also printed as legend.stl)"]
    classes = classes_in_model(t, cfg)
    map_area = (t.map_box[2] - t.map_box[0]) * (t.map_box[3] - t.map_box[1])
    areas = {lyr.cls: lyr.geom.area for lyr in t.tactile_layers()}
    for cls in classes:
        label = cfg.classes[cls].legend_label
        share = f" (about {100 * areas[cls] / map_area:.0f} % of the map)" if cfg.classes[cls].role == "terrain" else ""
        lines.append(f"- {label}: {feel(cfg, cls)}{share}.")

    lines += ["", "TACTILE CHECK"]
    if check["ok"]:
        lines.append("All checks passed.")
    lines += summary_lines(check)
    examples = [(k, check[k]["examples_mm"]) for k in ("thin_parts", "narrow_gaps", "hidden_objects") if check[k]["count"]]
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
