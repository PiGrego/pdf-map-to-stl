"""``description.txt``: the model explained in plain text.

Written for screen readers and for sighted helpers alike: short lines, lists rather
than tables, no colours. It says how to hold the model, what each height and texture
means (the legend), the scale, and what the tactile check found.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .legend import legend_rows
from .model3d import TactileModel
from .scene import PT_TO_MM
from .tactile_check import summary_lines


def _feel(cfg: Config, cls: str, height: float, role: str) -> str:
    tc = cfg.classes[cls]
    tex = f", with {tc.texture.describe()}" if tc.texture and height >= 0 else ", smooth"
    if role == "object":
        return f"{height:g} mm high, at least {tc.min_width_mm:g} mm wide"
    if height < 0:
        return f"recessed {-height:g} mm into the plate"
    if height == 0:
        return f"flat, at plate level{tex}"
    return f"raised {height:g} mm{tex}"


def describe(t: TactileModel, cfg: Config, check: dict, source: str, files: list[str]) -> str:
    title = t.title or "untitled"
    map_w = t.map_box[2] - t.map_box[0]
    map_area = map_w * (t.map_box[3] - t.map_box[1])
    enlarge = t.scale / PT_TO_MM  # model mm per PDF mm
    lines = [
        f"TACTILE MAP: {title}",
        "",
        f"Made from {source}.",
        (f"Plate: {t.width_mm:.0f} mm wide and {t.height_mm:.0f} mm deep. "
         f"Base {t.base_mm:g} mm thick; the highest point is {check['total_height_mm']:g} mm above the table."),
    ]
    if cfg.map_scale:
        metres_per_cm = cfg.map_scale / enlarge / 100
        lines.append(
            f"Scale: the printed map is 1:{cfg.map_scale:g}; the model enlarges it {enlarge:.2f} times, "
            f"so 1 cm on the model is about {metres_per_cm:.0f} m on the ground."
        )
    else:
        lines.append(f"Scale: the model is {enlarge:.2f} times the size of the printed map.")

    lines += ["", "HOW TO HOLD IT"]
    hold = ["North is up."]
    if t.corner_mm:
        hold.append("Hold the plate so the cut corner is at the top right.")
    if t.title:
        hold.append(f'The Braille title "{t.title}" runs along the bottom edge.')
    lines.append(" ".join(hold))

    lines += ["", "LEGEND (also printed as legend.stl, read from top to bottom; same cut corner)"]
    rows = legend_rows(t, cfg)
    terrain = [r for r in rows if r.role == "terrain"]
    objects = [r for r in rows if r.role == "object"]
    if terrain:
        lines.append("Ground, from low to high:")
        for r in terrain:
            share = 100 * r.geom.area / map_area if map_area else 0
            lines.append(f"- {cfg.classes[r.cls].legend_label}: {_feel(cfg, r.cls, r.height_mm, r.role)} "
                         f"(about {share:.0f} % of the map).")
    if objects:
        lines.append("Objects standing on the ground:")
        for r in objects:
            lines.append(f"- {cfg.classes[r.cls].legend_label}: {_feel(cfg, r.cls, r.height_mm, r.role)}.")

    lines += ["", "TACTILE CHECK"]
    if check["ok"]:
        lines.append("All checks passed.")
    lines += summary_lines(check)
    examples = [(k, check[k]["examples_mm"]) for k in ("thin_parts", "narrow_gaps", "hidden_objects") if check[k]["count"]]
    if examples:
        lines.append("Example places, in mm from the bottom-left corner (x to the right, y up):")
        for k, pts in examples:
            lines.append(f"- {k.replace('_', ' ')}: " + "; ".join(f"{x:g}, {y:g}" for x, y in pts))
    if not check["ok"]:
        lines.append("To fix: make the model bigger (--width), convert a smaller part (--crop), "
                     "or change heights and textures (tuner.html).")

    lines += ["", "FILES"] + [f"- {f}" for f in files]
    return "\n".join(lines) + "\n"


def write_description(text: str, path: Path) -> None:
    path.write_text(text, encoding="utf-8")
