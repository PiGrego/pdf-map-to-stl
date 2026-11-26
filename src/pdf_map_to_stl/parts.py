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

from .i18n import num, t
from .model3d import (
    TactileModel,
    _cross_section,
    braille_dot,
    lift,
    object_solid,
    recess_depth,
    recess_floors,
    write_stl,
)


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


def build_parts(tm: TactileModel, top_skin_mm: float = 0.6, colours: dict | None = None) -> list[Part]:
    base_z = tm.base_mm
    skin = max(0.2, min(top_skin_mm, base_z - 0.4))
    parts: list[Part] = []
    removed_from_base: list[Manifold] = []
    terrain_cols: list[Manifold] = []

    for layer in (lyr for lyr in tm.layers if lyr.role == "terrain"):
        if layer.height_mm >= 0:
            col = _column(layer.geom, base_z - skin, base_z + layer.height_mm)
            removed_from_base.append(col)
            note = t("parts.flat_skin") if layer.height_mm == 0 else t("parts.raised", height=num(layer.height_mm))
            top = base_z + layer.height_mm
        else:
            depth = recess_depth(layer.height_mm, base_z)
            floor = base_z - depth
            col = _column(layer.geom, max(0.2, floor - skin), floor)
            removed_from_base.append(_column(layer.geom, max(0.2, floor - skin), base_z + 1))
            note, top = t("parts.recess_floor", depth=num(depth)), floor
        terrain_cols.append(col)
        parts.append(Part(layer.cls, "terrain", col, top, note))

    base = _column(tm.plate, 0.0, base_z)
    cut = _union(removed_from_base)
    if cut is not None:
        base = base - cut
    parts.insert(0, Part("base", "base", base, base_z, t("parts.plate")))

    ground = _union(terrain_cols)
    placed: list[Manifold] = []
    floors = recess_floors(tm)
    objects = sorted((lyr for lyr in tm.layers if lyr.role in ("object", "pin")), key=lambda lyr: -lyr.height_mm)
    for layer in objects:
        # Over a recess (water) an object stands on its floor, as in model.stl: no tunnel.
        solid = _union([object_solid(layer.geom, base_z, base_z + layer.height_mm, layer.profile)]
                       + [_column(layer.geom.intersection(g), floor, base_z) for g, floor in floors]) or Manifold()
        if ground is not None:
            solid = solid - ground
        for other in placed:
            solid = solid - other
        if solid.is_empty() or solid.volume() < 1e-3:
            continue
        placed.append(solid)
        note = t("parts.object", height=num(layer.height_mm)) if layer.role == "object" else t("parts.pins")
        parts.append(Part(layer.cls, layer.role, solid, base_z + layer.height_mm, note))

    object_area = unary_union([lyr.geom for lyr in tm.layers if lyr.role == "object"])
    for layer in (lyr for lyr in tm.layers if lyr.role == "texture"):
        geom = layer.geom.difference(object_area) if not object_area.is_empty else layer.geom
        solid = _column(geom, base_z + layer.z0_mm, base_z + layer.height_mm)
        if not solid.is_empty():
            parts.append(Part(layer.cls.replace(" ", "_"), "texture", solid, base_z + layer.height_mm,
                              t("parts.texture", cls=layer.on)))

    notes = {"north": t("parts.north"), "frame": t("parts.frame"), "edge": t("parts.edge"),
             "scale_bar": t("parts.scale_bar", label=tm.scale_bar.get("label", "")),
             "qr": t("parts.qr"), "qr_frame": t("parts.qr_frame")}
    for layer in (lyr for lyr in tm.layers if lyr.role in notes):
        parts.append(Part(layer.role, layer.role, _column(layer.geom, base_z, base_z + layer.height_mm),
                          base_z + layer.height_mm, notes[layer.role]))

    if tm.braille_dots:
        spec = tm.braille_spec
        dots = [braille_dot(x, y, base_z, spec) for x, y in tm.braille_dots]
        parts.append(Part("braille", "braille", _union(dots), base_z + spec.dot_height_mm, t("parts.braille")))
    if tm.relief:  # slopes: every part rises with its band; the plate fills the gap under them
        for p in parts:
            p.solid = lift(p.solid, tm.relief, fill=p.kind == "base")
            if not p.solid.is_empty():
                p.z_top_mm = p.solid.bounding_box()[5]
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
    lines = [t("parts.heading", title=title), "", t("parts.intro"), "", t("parts.how"), "", t("parts.then"), "",
             t("parts.list")]
    for r in rows:
        colour = t("parts.colour", colour=r["colour"]) if r["colour"] else ""
        lines.append(t("parts.row", file=r["file"], kind=r["kind"], top=num(r["top_mm"]), note=r["note"], colour=colour))
    return "\n".join(lines) + "\n"
