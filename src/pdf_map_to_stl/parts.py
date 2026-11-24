"""One STL per layer, for slicers.

``model.stl`` is the whole model as one body. For printing at its best, the slicer
should see each layer as its own *part* of one object, so each can get its own
settings: filament or colour, fuzzy skin or ironing for texture, layer height, speed.
This module splits the model into such parts:

* ``base``: the plate under everything (and the Braille title strip);
* one part per terrain class: its column from ``top_skin_mm`` below the plate surface
  up to its height, so even flat classes (paved) own the visible top of their area;
  recessed classes (water) own the floor of their recess;
* one part per object class (walls, trees…): only the part above the ground under it;
* one part per texture, one for the north symbols, one for the line along a polygon
  window's edge, and one for the Braille dots.

Parts touch but never overlap, and all share one coordinate system (mm, origin at the
plate's bottom-left corner, z up from the table), so loaded together as one object
they line up exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manifold3d import Manifold, OpType
from shapely.ops import unary_union

from .model3d import TactileModel, _cross_section, recess_depth, write_stl


@dataclass
class Part:
    name: str
    kind: str  # base | terrain | object | texture | north | frame | braille
    solid: Manifold
    z_top_mm: float  # highest point above the table
    note: str = ""
    colour: str = ""  # suggested filament colour (#rrggbb)


def _union(solids: list[Manifold]) -> Manifold | None:
    solids = [s for s in solids if not s.is_empty()]
    return Manifold.batch_boolean(solids, OpType.Add) if solids else None


def _column(geom, z0: float, z1: float) -> Manifold:
    cs = _cross_section(geom)
    if cs.is_empty() or z1 <= z0:
        return Manifold()
    return cs.extrude(z1 - z0).translate((0, 0, z0))


def build_parts(t: TactileModel, top_skin_mm: float = 0.6, colours: dict | None = None) -> list[Part]:
    base_z = t.base_mm
    skin = max(0.2, min(top_skin_mm, base_z - 0.4))
    parts: list[Part] = []
    removed_from_base: list[Manifold] = []
    terrain_cols: list[Manifold] = []

    for layer in (lyr for lyr in t.layers if lyr.role == "terrain"):
        if layer.height_mm >= 0:
            col = _column(layer.geom, base_z - skin, base_z + layer.height_mm)
            removed_from_base.append(col)
            note = "flat top skin" if layer.height_mm == 0 else f"raised {layer.height_mm:g} mm"
            top = base_z + layer.height_mm
        else:
            depth = recess_depth(layer.height_mm, base_z)
            floor = base_z - depth
            col = _column(layer.geom, max(0.2, floor - skin), floor)
            removed_from_base.append(_column(layer.geom, max(0.2, floor - skin), base_z + 1))
            note, top = f"floor of a {depth:g} mm recess", floor
        terrain_cols.append(col)
        parts.append(Part(layer.cls, "terrain", col, top, note))

    base = _column(t.plate, 0.0, base_z)
    cut = _union(removed_from_base)
    if cut is not None:
        base = base - cut
    parts.insert(0, Part("base", "base", base, base_z, "plate under everything"))

    ground = _union(terrain_cols)
    placed: list[Manifold] = []
    objects = sorted((lyr for lyr in t.layers if lyr.role == "object"), key=lambda lyr: -lyr.height_mm)
    for layer in objects:
        solid = _column(layer.geom, base_z, base_z + layer.height_mm)
        if ground is not None:
            solid = solid - ground
        for other in placed:
            solid = solid - other
        if solid.is_empty() or solid.volume() < 1e-3:
            continue
        placed.append(solid)
        parts.append(Part(layer.cls, "object", solid, base_z + layer.height_mm, f"{layer.height_mm:g} mm high"))

    object_area = unary_union([lyr.geom for lyr in t.layers if lyr.role == "object"])
    for layer in (lyr for lyr in t.layers if lyr.role == "texture"):
        geom = layer.geom.difference(object_area) if not object_area.is_empty else layer.geom
        solid = _column(geom, base_z + layer.z0_mm, base_z + layer.height_mm)
        if not solid.is_empty():
            parts.append(Part(layer.cls.replace(" ", "_"), "texture", solid, base_z + layer.height_mm,
                              f"texture of {layer.on}"))

    notes = {"north": "north symbols (the ring end points north)", "frame": "frames around flat legend samples",
             "edge": "raised line along the edge of the map window"}
    for layer in (lyr for lyr in t.layers if lyr.role in notes):
        parts.append(Part(layer.role, layer.role, _column(layer.geom, base_z, base_z + layer.height_mm),
                          base_z + layer.height_mm, notes[layer.role]))

    if t.braille_dots:
        spec = t.braille_spec
        r = spec.dot_diameter_mm / 2
        dots = [Manifold.cylinder(spec.dot_height_mm, r, r * 0.55, 16).translate((x, y, base_z)) for x, y in t.braille_dots]
        parts.append(Part("braille", "braille", _union(dots), base_z + spec.dot_height_mm, "Braille dots"))
    colours = colours or {}
    for p in parts:
        rgb = colours.get(p.name) or colours.get(p.name.removesuffix("_texture"))
        if rgb:
            p.colour = "#{:02x}{:02x}{:02x}".format(*rgb)
    return [p for p in parts if not p.solid.is_empty()]


def write_parts(parts: list[Part], folder: Path, title: str) -> list[dict]:
    """Write ``NN_name.stl`` per part and a README for loading them in a slicer."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.stl"):
        old.unlink()
    rows = []
    for i, p in enumerate(parts):
        name = f"{i:02d}_{p.name}.stl"
        info = write_stl(p.solid, folder / name)
        rows.append({"file": name, "kind": p.kind, "top_mm": round(p.z_top_mm, 2), "note": p.note,
                     "colour": p.colour, "volume_mm3": info["volume_mm3"]})
    (folder / "README.txt").write_text(_readme(rows, title), encoding="utf-8")
    return rows


def _readme(rows: list[dict], title: str) -> str:
    lines = [
        f"PARTS OF: {title}",
        "",
        "Each file is one layer of the same object. All files share one coordinate system",
        "(millimetres, origin at the plate's bottom-left corner, z up from the table), and the",
        "parts touch without overlapping. Loaded together as ONE object with several parts,",
        "they line up exactly.",
        "",
        "HOW TO LOAD",
        "- Bambu Studio, OrcaSlicer: import all files at once; when asked whether to load them",
        "  as a single object with multiple parts, answer Yes.",
        "- PrusaSlicer: import all files at once; it asks the same question when the printer",
        "  profile has more than one extruder. Otherwise load 00_base.stl and add the others",
        "  with right-click > Add part > Load, and check that they line up.",
        "- Do not load them as separate objects: the slicer drops each one to the bed and moves it.",
        "",
        "Then give each part its own settings: filament or colour, fuzzy skin or ironing for",
        "texture, and so on. model.stl is the same model as a single body, for one-material prints.",
        "",
        "PARTS (top = highest point above the table)",
    ]
    for r in rows:
        colour = f" Suggested colour {r['colour']} (as on the map)." if r["colour"] else ""
        lines.append(f"- {r['file']}: {r['kind']}, top {r['top_mm']:g} mm. {r['note']}.{colour}")
    return "\n".join(lines) + "\n"
