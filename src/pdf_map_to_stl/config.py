"""Step 2: configuration and settings.

A **config file** (``config/default.toml``) holds everything map-specific: the symbol
rules (how to recognise a PDF paint operation) and the tactile classes (what each
recognised class becomes in 3D), plus every setting with its default.

**Settings files** change some of those values without copying the whole config: a
profile (``config/profiles/<name>.toml``, e.g. ``no_textures``), the ``settings.toml``
saved from the tuner, or ``settings_used.toml`` from an earlier build.
``--set section.key=value`` changes a single value. They are applied in that order,
each overriding the one before::

    config file  <-  settings files (in order)  <-  --set values

Every key is checked: a misspelt setting is an error, not silently ignored. Each build
writes ``settings_used.toml`` (``settings_dict``), the complete list of values it used;
pass it back with ``--settings`` to build the same model again.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .braille import BrailleSpec
from .scene import Primitive

DOT_TOLERANCE = 0.15
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_CONFIG = CONFIG_DIR / "default.toml"
PROFILE_DIR = CONFIG_DIR / "profiles"

ROLES = ("terrain", "object", "ignore")
SHAPES = ("dot", "ring", "cross")  # standard symbols; "" or "as_drawn" = as on the map
TEXTURE_KINDS = ("dots", "rings", "lines", "waves")
JOINS = ("round", "mitre", "bevel")
CAPS = ("round", "flat", "square")


@dataclass(frozen=True)
class SymbolRule:
    cls: str
    isom: str
    kind: str
    rgb: tuple[int, int, int]
    rgb_tol: int = 3
    min_width_mm: float | None = None
    max_width_mm: float | None = None
    min_extent_mm: float | None = None
    max_extent_mm: float | None = None
    dot_mm: float | None = None
    pitch_mm: float | None = None

    def matches(self, p: Primitive) -> bool:
        if self.kind != "any" and self.kind != p.kind:
            return False
        if max(abs(a - b) for a, b in zip(self.rgb, p.rgb)) > self.rgb_tol:
            return False
        if self.min_width_mm is not None and p.width_mm < self.min_width_mm:
            return False
        if self.max_width_mm is not None and p.width_mm > self.max_width_mm:
            return False
        if self.min_extent_mm is not None and p.extent_mm < self.min_extent_mm:
            return False
        if self.max_extent_mm is not None and p.extent_mm > self.max_extent_mm:
            return False
        for want, got in ((self.dot_mm, p.dot_mm), (self.pitch_mm, p.pitch_mm)):
            if want is not None and abs(got - want) > DOT_TOLERANCE * want:
                return False
        return True


@dataclass(frozen=True)
class Texture:
    """A raised pattern on top of an area: ``dots`` (a grid of small bumps), ``rings``
    (a grid of small rings), ``lines`` (straight parallel ridges at ``angle_deg``) or
    ``waves`` (wavy parallel ridges). ``name`` is its name in the texture library."""

    kind: str  # "dots" | "rings" | "lines" | "waves"
    pitch_mm: float = 3.0
    size_mm: float = 1.2  # dot or ring diameter, or ridge width
    height_mm: float = 0.5
    angle_deg: float = 45.0
    line_mm: float = 0.6  # ring wall thickness
    name: str = ""

    def describe(self) -> str:
        return {
            "dots": f"dots every {self.pitch_mm:g} mm",
            "rings": f"small rings every {self.pitch_mm:g} mm",
            "lines": f"straight ridges every {self.pitch_mm:g} mm",
            "waves": f"wavy ridges every {self.pitch_mm:g} mm",
        }.get(self.kind, self.kind)


@dataclass(frozen=True)
class TactileClass:
    name: str
    role: str  # terrain | object | ignore
    height_mm: float = 0.0
    min_width_mm: float = 0.0
    label: str = ""  # Braille label in the legend (defaults to the class name)
    texture: Texture | None = None  # raised pattern on top, to tell same-height classes apart
    merge_gaps: bool = True  # objects: merge parts closer than the merge gap (not for trees)
    shape: str = ""  # objects: "dot" | "ring" | "cross" = standard symbol; "" = as drawn
    size_mm: float = 0.0  # size of the standard symbol
    colour: tuple[int, int, int] | None = None  # display colour, suggested filament colour
    enabled: bool = True  # false: not shown (terrain: its area becomes ``merge_into``)
    merge_into: str = ""  # terrain class that takes the area of this class when it is off

    @property
    def legend_label(self) -> str:
        return self.label or self.name.replace("_", " ")


@dataclass(frozen=True)
class Features:
    """What the model contains besides the map's own areas and objects."""

    textures: bool = True  # raised patterns on areas; false = every area smooth
    standard_symbols: bool = True  # trees, boulders, crosses as standard symbols; false = as drawn
    north_symbol: bool = True  # raised north symbols at the top-right and bottom-left
    legend_frames: bool = True  # raised frame around flat samples on the legend


@dataclass(frozen=True)
class Smoothing:
    """How outlines are drawn. Sizes in mm on the model, except ``curve_step_mm``."""

    line_join: str = "round"  # corners of redrawn lines (walls, fences): round | mitre | bevel
    line_cap: str = "round"  # ends of redrawn lines: round | flat | square
    arc_segments: int = 4  # segments per quarter circle wherever the tool rounds a shape
    curve_step_mm: float = 0.035  # chord length when reading curves from the PDF (mm on the PDF)
    simplify_mm: float = 0.0  # remove outline detail smaller than this; 0 = exact outlines
    round_corners_mm: float = 0.0  # round sharp corners of areas and objects; 0 = as drawn


@dataclass(frozen=True)
class Generalize:
    """Automatic changes that make the map readable by touch (generalize.py)."""

    clean_slivers: bool = True  # give strips narrower than sliver_mm to their neighbour
    sliver_mm: float = 0.4
    open_passages: bool = True  # widen passages between raised areas to tactile.min_gap_mm
    widen_thin: bool = True  # widen raised areas narrower than tactile.min_feature_mm
    merge_close_objects: bool = True  # merge objects closer than merge_gap_mm (double walls)
    merge_gap_mm: float = 3.0
    widen_objects: bool = True  # widen lines and small objects to their class min_width_mm
    min_area_mm2: float = 0.4  # drop pieces smaller than this (cannot be felt or printed)


@dataclass(frozen=True)
class TactileRules:
    """Thresholds of the tactile check, and the targets of generalisation. Starting values
    from common tactile-graphics practice; confirm them with the people who read the maps."""

    min_feature_mm: float = 1.0  # narrower raised parts are hard to feel and to print
    min_gap_mm: float = 3.0  # raised parts closer than this feel like one
    min_height_step_mm: float = 0.5  # smaller height differences are hard to notice
    min_symbol_area_mm2: float = 9.0  # smaller isolated areas are hard to identify


@dataclass(frozen=True)
class Output:
    width_mm: float = 120.0  # printed model width
    base_mm: float = 2.0  # base plate thickness
    top_skin_mm: float = 0.6  # parts export: each area owns this much of the plate under it
    north_height_mm: float = 1.0
    orientation_corner_mm: float = 0.0  # cut at the top-right corner; 0 = none
    title: str = ""  # Braille title at the top left ("" = none, "auto" = file name)
    map_scale: float = 0.0  # e.g. 5000 for 1:5000; 0 = unknown
    legend_max_height_mm: float = 200.0


@dataclass
class Config:
    width_mm: float
    base_mm: float
    classes: dict[str, TactileClass]
    rules: list[SymbolRule] = field(default_factory=list)
    tactile: TactileRules = field(default_factory=TactileRules)
    braille: BrailleSpec = field(default_factory=BrailleSpec)
    features: Features = field(default_factory=Features)
    smoothing: Smoothing = field(default_factory=Smoothing)
    generalize: Generalize = field(default_factory=Generalize)
    textures: dict[str, Texture] = field(default_factory=dict)  # the texture library
    orientation_corner_mm: float = 0.0
    title: str = ""
    map_scale: float = 0.0
    north_height_mm: float = 1.0
    top_skin_mm: float = 0.6
    legend_max_height_mm: float = 200.0
    sources: list[str] = field(default_factory=list)  # config and settings files, in order

    def classify(self, p: Primitive) -> tuple[str, str]:
        """(class, isom code) the symbol rules give a primitive; ``unclassified`` if none."""
        for r in self.rules:
            if r.matches(p):
                return r.cls, r.isom
        return "unclassified", "?"

    def shown_as(self, cls: str) -> str | None:
        """The class a source class is shown as on the model, or None if it is not shown.
        A terrain class that is switched off shows as its ``merge_into`` class (or, without
        one, is transparent: what is painted under it shows instead)."""
        seen = set()
        while cls in self.classes and cls not in seen:
            seen.add(cls)
            tc = self.classes[cls]
            if tc.role == "ignore":
                return None
            if tc.enabled:
                return cls
            if tc.role == "object" or not tc.merge_into:
                return None
            cls = tc.merge_into
        return None

    def role(self, cls: str) -> str:
        """Role of a class on the model: ``ignore`` when it is not shown."""
        return self.classes[cls].role if self.shown_as(cls) == cls else "ignore"

    def texture(self, cls: str) -> Texture | None:
        """The texture a class gets on the model (None when textures are switched off)."""
        tc = self.classes.get(cls)
        return tc.texture if tc is not None and self.features.textures else None

    def shape(self, cls: str) -> str:
        """The standard symbol of an object class ("" = drawn as on the map)."""
        tc = self.classes.get(cls)
        return tc.shape if tc is not None and self.features.standard_symbols else ""


# ----------------------------------------------------------------------------- loading


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _shown(p: Path) -> str:
    """A path as the user would type it: relative to the current folder when inside it."""
    try:
        return str(p.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def resolve_settings(name: str | Path) -> Path:
    """A settings file path, or the name of a profile in ``config/profiles``."""
    p = Path(name)
    if p.suffix == "" and not p.exists():
        p = PROFILE_DIR / f"{p.name}.toml"
    if not p.exists():
        profiles = sorted(q.stem for q in PROFILE_DIR.glob("*.toml"))
        raise ValueError(f"settings file {name!s} not found (profiles: {', '.join(profiles)})")
    return p


def parse_override(text: str) -> tuple[list[str], object]:
    """``section.key=value`` (e.g. ``class.canopy.enabled=true``) -> (path, value). The
    value is read as TOML (numbers, true/false, [lists]); anything else is a string."""
    key, sep, raw = text.partition("=")
    path = [k.strip() for k in key.split(".")]
    if not sep or len(path) < 2 or not all(path):
        raise ValueError(f"--set expects section.key=value, got {text!r}")
    try:
        value = tomllib.loads(f"v = {raw.strip()}")["v"]
    except tomllib.TOMLDecodeError:
        value = raw.strip()
    return path, value


def _nested(path: list[str], value) -> dict:
    over: dict = {}
    node = over
    for k in path[:-1]:
        node = node.setdefault(k, {})
    node[path[-1]] = value
    return over


def _check_overlay(over: dict, data: dict, source: str) -> None:
    if "symbol" in over:
        raise ValueError(f"{source}: symbol rules belong in the config file (-c), not in a settings file")
    unknown = set(over.get("class", {})) - set(data.get("class", {}))
    if unknown:
        raise ValueError(f"{source} names unknown classes: {sorted(unknown)}")


def load_config(
    path: str | Path | None = None,
    heights: str | Path | None = None,
    settings: list[str | Path] | tuple = (),
    overrides: list[str] | tuple = (),
) -> Config:
    """Load a config file, then apply settings files and ``--set`` overrides in order.
    ``heights`` (the tuner's file) is applied as the first settings file."""
    path = Path(path or DEFAULT_CONFIG)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = [_shown(path)]
    for s in ([heights] if heights else []) + list(settings):
        p = resolve_settings(s)
        over = tomllib.loads(p.read_text(encoding="utf-8"))
        _check_overlay(over, data, str(p))
        data = _merge(data, over)
        sources.append(_shown(p))
    for text in overrides:
        over = _nested(*parse_override(text))
        _check_overlay(over, data, f"--set {text}")
        data = _merge(data, over)
        sources.append(f"--set {text}")
    return from_dict(data, sources)


def _section(kind, d: dict, name: str):
    known = {f.name for f in fields(kind)} - {"name"}
    unknown = set(d) - known
    if unknown:
        raise ValueError(f"unknown setting(s) in [{name}]: {', '.join(sorted(unknown))}. "
                         f"Known: {', '.join(sorted(known))}")
    return kind(**d)


TOP_SECTIONS = ("output", "features", "smoothing", "generalize", "tactile", "braille", "texture", "class", "symbol")


def from_dict(data: dict, sources: list[str] | None = None) -> Config:
    unknown = set(data) - set(TOP_SECTIONS)
    if unknown:
        raise ValueError(f"unknown section(s): {', '.join(sorted(unknown))}. Known: {', '.join(TOP_SECTIONS)}")
    out = _section(Output, data.get("output", {}), "output")
    library = {name: _texture(t, f"texture.{name}", name) for name, t in data.get("texture", {}).items()}
    classes = {name: _tactile_class(name, c, library) for name, c in data.get("class", {}).items()}
    for tc in classes.values():
        if tc.merge_into and (tc.merge_into not in classes or classes[tc.merge_into].role != "terrain"):
            raise ValueError(f"class {tc.name}: merge_into must name a terrain class, not {tc.merge_into!r}")
    rules = []
    for s in data.get("symbol", []):
        if s["class"] not in classes:
            raise ValueError(f"symbol rule uses undefined class {s['class']!r}")
        rules.append(
            SymbolRule(
                cls=s["class"],
                isom=str(s.get("isom", "?")),
                kind=s.get("kind", "any"),
                rgb=tuple(s["rgb"]),
                rgb_tol=int(s.get("rgb_tol", 3)),
                min_width_mm=s.get("min_width_mm"),
                max_width_mm=s.get("max_width_mm"),
                min_extent_mm=s.get("min_extent_mm"),
                max_extent_mm=s.get("max_extent_mm"),
                dot_mm=s.get("dot_mm"),
                pitch_mm=s.get("pitch_mm"),
            )
        )
    smoothing = _section(Smoothing, data.get("smoothing", {}), "smoothing")
    if smoothing.line_join not in JOINS or smoothing.line_cap not in CAPS:
        raise ValueError(f"smoothing: line_join is one of {JOINS}, line_cap one of {CAPS}")
    return Config(
        width_mm=float(out.width_mm),
        base_mm=float(out.base_mm),
        classes=classes,
        rules=rules,
        tactile=_section(TactileRules, data.get("tactile", {}), "tactile"),
        braille=_section(BrailleSpec, data.get("braille", {}), "braille"),
        features=_section(Features, data.get("features", {}), "features"),
        smoothing=smoothing,
        generalize=_section(Generalize, data.get("generalize", {}), "generalize"),
        textures=library,
        orientation_corner_mm=float(out.orientation_corner_mm),
        title=str(out.title),
        map_scale=float(out.map_scale),
        north_height_mm=float(out.north_height_mm),
        top_skin_mm=float(out.top_skin_mm),
        legend_max_height_mm=float(out.legend_max_height_mm),
        sources=list(sources or []),
    )


def _texture(t: dict, where: str, name: str = "") -> Texture:
    tex = _section(Texture, t, where)
    if tex.kind not in TEXTURE_KINDS:
        raise ValueError(f"{where}: kind must be one of {TEXTURE_KINDS}, not {tex.kind!r}")
    return Texture(**{**asdict(tex), "name": name})


CLASS_KEYS = {"role", "enabled", "merge_into", "height_mm", "min_width_mm", "label", "texture", "merge_gaps",
              "shape", "size_mm", "colour"}


def _tactile_class(name: str, c: dict, library: dict[str, Texture]) -> TactileClass:
    unknown = set(c) - CLASS_KEYS
    if unknown:
        raise ValueError(f"unknown setting(s) in [class.{name}]: {', '.join(sorted(unknown))}. "
                         f"Known: {', '.join(sorted(CLASS_KEYS))}")
    role = c.get("role", "ignore")
    if role not in ROLES:
        raise ValueError(f"class {name}: role must be one of {ROLES}, not {role!r}")
    tex = c.get("texture")
    if isinstance(tex, dict):
        texture = _texture(tex, f"class.{name}.texture")
    elif tex in (None, "", "none"):
        texture = None
    elif tex in library:
        texture = library[tex]
    else:
        raise ValueError(f"class {name}: unknown texture {tex!r} "
                         f"(library: {', '.join(sorted(library)) or 'empty'}; or none)")
    shape = str(c.get("shape", ""))
    shape = "" if shape == "as_drawn" else shape
    if shape and shape not in SHAPES:
        raise ValueError(f"class {name}: shape must be one of {SHAPES} or as_drawn, not {shape!r}")
    return TactileClass(
        name,
        role,
        float(c.get("height_mm", 0.0)),
        float(c.get("min_width_mm", 0.0)),
        str(c.get("label", "")),
        texture,
        bool(c.get("merge_gaps", True)),
        shape,
        float(c.get("size_mm", 0.0)),
        tuple(c["colour"]) if "colour" in c else None,
        bool(c.get("enabled", True)),
        str(c.get("merge_into", "")),
    )


# ----------------------------------------------------------------------------- writing


def _texture_dict(t: Texture) -> dict:
    d = asdict(t)
    d.pop("name")
    return d


def settings_dict(cfg: Config) -> dict:
    """Every setting a build used, in the settings-file layout (without symbol rules)."""
    classes = {}
    for name, tc in cfg.classes.items():
        if tc.role == "ignore":
            classes[name] = {"role": "ignore"}
            continue
        d = {"role": tc.role, "enabled": tc.enabled, "height_mm": tc.height_mm}
        if tc.merge_into:
            d["merge_into"] = tc.merge_into
        if tc.role == "terrain" or tc.texture:
            d["texture"] = (tc.texture.name or _texture_dict(tc.texture)) if tc.texture else "none"
        if tc.role == "object":
            d.update(shape=tc.shape or "as_drawn", size_mm=tc.size_mm, min_width_mm=tc.min_width_mm,
                     merge_gaps=tc.merge_gaps)
        d["label"] = tc.legend_label
        if tc.colour:
            d["colour"] = list(tc.colour)
        classes[name] = d
    return {
        "output": {
            "width_mm": round(cfg.width_mm, 3), "base_mm": cfg.base_mm, "top_skin_mm": cfg.top_skin_mm,
            "north_height_mm": cfg.north_height_mm, "orientation_corner_mm": cfg.orientation_corner_mm,
            "title": cfg.title, "map_scale": cfg.map_scale, "legend_max_height_mm": cfg.legend_max_height_mm,
        },
        "features": asdict(cfg.features),
        "smoothing": asdict(cfg.smoothing),
        "generalize": asdict(cfg.generalize),
        "tactile": asdict(cfg.tactile),
        "braille": asdict(cfg.braille),
        "texture": {name: _texture_dict(t) for name, t in cfg.textures.items()},
        "class": classes,
    }


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"cannot write {v!r} as TOML")


def to_toml(data: dict, header: str = "") -> str:
    """Write a settings dict (sections of scalars; ``texture`` and ``class`` hold one
    section per name) as TOML."""
    lines = [f"# {h}" if h else "#" for h in header.splitlines()]
    for section, body in data.items():
        nested = section in ("texture", "class")
        for name, values in (body.items() if nested else [(None, body)]):
            lines += ["", f"[{section}.{name}]" if nested else f"[{section}]"]
            lines += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    return "\n".join(lines).lstrip("\n") + "\n"
