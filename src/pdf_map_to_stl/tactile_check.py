"""Can the model be read by touch? Checks the tactile model against the rules in
``[tactile]`` of the config and reports where it falls short.

Checks, all on the model at print size:

* **thin parts**: raised (or recessed) parts narrower than ``min_feature_mm``;
* **narrow gaps**: two raised parts of the same class closer than ``min_gap_mm``
  (they feel like one);
* **narrow passages**: lower ground narrower than ``min_gap_mm`` between raised parts of
  different classes (a wall and a strip of grass): a finger cannot follow it;
* **low steps**: two touching terrain classes whose heights differ by less than
  ``min_height_step_mm`` and that have the same texture (they feel the same);
* **hidden objects**: objects (walls, trees…) that rise less than
  ``min_height_step_mm`` above the terrain they stand on;
* **small areas**: isolated raised terrain pieces smaller than ``min_symbol_area_mm2``.

Results come with example locations in mm from the bottom-left corner, so they can be
found with a ruler as well as on ``tactile_check.png``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .config import Config
from .geometry import polygons
from .model3d import TactileModel

MAX_EXAMPLES = 8


@dataclass
class CheckResult:
    summary: dict
    problems: dict[str, BaseGeometry] = field(default_factory=dict)  # for the image

    @property
    def ok(self) -> bool:
        return self.summary["ok"]


def _spots(g: BaseGeometry, min_area: float) -> list[Polygon]:
    return [p for p in polygons(g) if p.area >= min_area]


def _examples(spots: list[Polygon]) -> list[list[float]]:
    biggest = sorted(spots, key=lambda p: -p.area)[:MAX_EXAMPLES]
    return [[round(p.centroid.x, 1), round(p.centroid.y, 1)] for p in biggest]


def _texture_key(cfg: Config, cls: str):
    tex = cfg.texture(cls)
    return None if tex is None else (tex.kind, tex.pitch_mm, tex.size_mm, tex.angle_deg)


def check_model(t: TactileModel, cfg: Config) -> CheckResult:
    rules = cfg.tactile
    layers = t.tactile_layers()
    w, gap, step = rules.min_feature_mm, rules.min_gap_mm, rules.min_height_step_mm

    thin, narrow, small, hidden = {}, {}, {}, {}
    for layer in layers:
        g = layer.geom
        if layer.height_mm == 0:
            continue  # flat: nothing to feel as a shape
        # 0.45 instead of 0.5: a 10 % tolerance, so a part exactly min_feature_mm wide passes.
        opened = g.buffer(-0.45 * w, 4).buffer(0.45 * w, 4)
        # Spots under half a square of min_feature_mm are sharp corner tips, not features.
        thin[layer.cls] = _spots(g.difference(opened.buffer(0.01)), 0.5 * w * w)
        if layer.height_mm > 0:
            closed = g.buffer(0.45 * gap, 4).buffer(-0.45 * gap, 4)
            narrow[layer.cls] = _spots(closed.difference(g.buffer(0.01)), 0.15 * gap * gap)
        if layer.role == "terrain" and layer.height_mm > 0:
            small[layer.cls] = [p for p in polygons(g) if p.area < rules.min_symbol_area_mm2]

    terrain = [lyr for lyr in layers if lyr.role == "terrain"]
    low_steps = []
    step_lines = []
    for i, a in enumerate(terrain):
        for b in terrain[i + 1 :]:
            if abs(a.height_mm - b.height_mm) >= step or _texture_key(cfg, a.cls) != _texture_key(cfg, b.cls):
                continue
            edge = a.geom.boundary.intersection(b.geom.buffer(0.05))
            if edge.length > 1.0:
                low_steps.append({
                    "a": a.cls, "b": b.cls, "step_mm": round(abs(a.height_mm - b.height_mm), 2),
                    "shared_edge_mm": round(edge.length, 1),
                })
                step_lines.append(edge)

    for obj in (lyr for lyr in layers if lyr.role == "object"):
        under = [lyr.geom for lyr in terrain if lyr.height_mm > obj.height_mm - step]
        if under:
            hidden[obj.cls] = _spots(obj.geom.intersection(unary_union(under)), 0.5)

    passages = _cross_class_passages(layers, terrain, narrow, gap, step)

    def block(d: dict[str, list[Polygon]]) -> dict:
        allspots = [p for ps in d.values() for p in ps]
        return {
            "count": len(allspots),
            "by_class": {k: len(v) for k, v in sorted(d.items()) if v},
            "examples_mm": _examples(allspots),
        }

    max_top = max([lyr.height_mm for lyr in t.layers] + [0.0]) + max((dz for _, dz in t.relief), default=0.0)
    summary = {
        "rules": {
            "min_feature_mm": w,
            "min_gap_mm": gap,
            "min_height_step_mm": step,
            "min_symbol_area_mm2": rules.min_symbol_area_mm2,
        },
        "thin_parts": block(thin),
        "narrow_gaps": block(narrow),
        "narrow_passages": block({"between classes": passages} if passages else {}),
        "low_steps": {"count": len(low_steps), "pairs": low_steps},
        "hidden_objects": block(hidden),
        "small_areas": block(small),
        "total_height_mm": round(t.base_mm + max_top, 2),
        "orientation_corner_mm": round(t.corner_mm, 1),
        "braille_title": t.title,
    }
    summary["ok"] = all(summary[k]["count"] == 0
                        for k in ("thin_parts", "narrow_gaps", "narrow_passages", "low_steps", "hidden_objects"))
    problems = {
        "thin_parts": unary_union([p for ps in thin.values() for p in ps]) if thin else Polygon(),
        "narrow_gaps": unary_union([p for ps in narrow.values() for p in ps] + passages),
        "low_steps": unary_union([ln.buffer(0.5) for ln in step_lines]) if step_lines else Polygon(),
        "hidden_objects": unary_union([p for ps in hidden.values() for p in ps]) if hidden else Polygon(),
        "small_areas": unary_union([p for ps in small.values() for p in ps]) if small else Polygon(),
    }
    return CheckResult(summary, problems)


def _cross_class_passages(layers, terrain, narrow: dict, gap: float, step: float) -> list[Polygon]:
    """Lower ground narrower than ``gap`` between raised parts of different classes, at
    least ``step`` below them; places already reported as same-class gaps are left out."""
    raised = [lyr for lyr in layers if lyr.height_mm > 0]
    same = unary_union([p for ps in narrow.values() for p in ps]).buffer(0.1) if narrow else Polygon()
    found: list[Polygon] = []
    for z in sorted({lyr.height_mm for lyr in raised}):
        high = unary_union([lyr.geom for lyr in raised if lyr.height_mm >= z - 1e-9])
        low = unary_union([lyr.geom for lyr in terrain if lyr.height_mm <= z - step + 1e-9])
        if high.is_empty or low.is_empty:
            continue
        closed = high.buffer(0.45 * gap, 4).buffer(-0.45 * gap, 4)
        cand = closed.difference(high.buffer(0.01)).intersection(low).difference(same)
        if found:
            cand = cand.difference(unary_union(found).buffer(0.1))
        found += _spots(cand, 0.15 * gap * gap)
    return found


def summary_lines(s: dict) -> list[str]:
    """Plain-language lines (for the terminal and description.txt)."""
    r = s["rules"]
    out = [
        f"Thin parts (narrower than {r['min_feature_mm']} mm): {s['thin_parts']['count']}",
        f"Narrow gaps (closer than {r['min_gap_mm']} mm): {s['narrow_gaps']['count']}",
        (f"Narrow passages between different raised features (narrower than {r['min_gap_mm']} mm): "
         f"{s['narrow_passages']['count']}"),
        (f"Neighbouring areas that feel the same (height step under {r['min_height_step_mm']} mm, same texture): "
         f"{s['low_steps']['count']}"),
        (f"Objects that barely rise above the ground (under {r['min_height_step_mm']} mm): "
         f"{s['hidden_objects']['count']}"),
        f"Small isolated areas (under {r['min_symbol_area_mm2']} square mm): {s['small_areas']['count']}",
    ]
    for p in s["low_steps"]["pairs"]:
        out.append(f"  - {p['a']} and {p['b']}: step {p['step_mm']} mm along {p['shared_edge_mm']} mm of edge")
    return out
