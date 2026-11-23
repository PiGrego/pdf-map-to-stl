"""Step 2: configuration. Symbol rules (how to recognise a primitive) and tactile
classes (what each recognised class becomes in 3D), loaded from a TOML file.

All map-specific knowledge lives in the TOML (``config/default.toml``), not in code:
adapting to a new map means editing rules there.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .braille import BrailleSpec
from .scene import Primitive

DOT_TOLERANCE = 0.15
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.toml"


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
class TactileClass:
    name: str
    role: str  # terrain | object | ignore
    height_mm: float = 0.0
    min_width_mm: float = 0.0
    label: str = ""  # Braille label in the legend (defaults to the class name)
    texture: Texture | None = None  # raised pattern on top, to tell same-height classes apart
    merge_gaps: bool = True  # objects: merge parts closer than the minimum gap (not for trees)

    @property
    def legend_label(self) -> str:
        return self.label or self.name.replace("_", " ")


@dataclass(frozen=True)
class Texture:
    """A raised pattern on top of an area: ``dots`` (a grid of small bumps) or ``lines``
    (parallel ridges at ``angle_deg``)."""

    kind: str  # "dots" | "lines"
    pitch_mm: float = 3.0
    size_mm: float = 1.2  # dot diameter or ridge width
    height_mm: float = 0.5
    angle_deg: float = 45.0

    def describe(self) -> str:
        if self.kind == "dots":
            return f"dots every {self.pitch_mm:g} mm"
        return f"ridges every {self.pitch_mm:g} mm"


@dataclass(frozen=True)
class TactileRules:
    """Thresholds the tactile check uses. Starting values from common tactile-graphics
    practice; confirm them with the people who will read the maps."""

    min_feature_mm: float = 1.0  # narrower raised parts are hard to feel and to print
    min_gap_mm: float = 3.0  # raised parts closer than this feel like one
    min_height_step_mm: float = 0.5  # smaller height differences are hard to notice
    min_symbol_area_mm2: float = 9.0  # smaller isolated areas are hard to identify
    # Generalisation (generalize.py): what to adjust automatically before checking.
    sliver_mm: float = 0.4  # terrain strips narrower than this are drawing artefacts
    clean_slivers: bool = True
    open_passages: bool = True
    widen_thin: bool = True
    merge_close_objects: bool = True


@dataclass
class Config:
    width_mm: float
    base_mm: float
    min_area_mm2: float
    classes: dict[str, TactileClass]
    rules: list[SymbolRule] = field(default_factory=list)
    tactile: TactileRules = field(default_factory=TactileRules)
    braille: BrailleSpec = field(default_factory=BrailleSpec)
    orientation_corner_mm: float = 8.0  # cut at the top-right corner; 0 = none
    title: str = ""  # Braille title along the bottom edge ("" = none)
    map_scale: float = 0.0  # e.g. 4000 for 1:4000; 0 = unknown

    def classify(self, p: Primitive) -> tuple[str, str]:
        """(class, isom code) of a primitive; ``unclassified`` if no rule matches."""
        for r in self.rules:
            if r.matches(p):
                return r.cls, r.isom
        return "unclassified", "?"

    def role(self, cls: str) -> str:
        return self.classes[cls].role if cls in self.classes else "ignore"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: str | Path | None = None, heights: str | Path | None = None) -> Config:
    """Load a config. ``heights`` is an optional TOML (as written by the tuner page) whose
    ``[output]`` and ``[class.*]`` values override the config's."""
    data = tomllib.loads(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8"))
    if heights:
        over = tomllib.loads(Path(heights).read_text(encoding="utf-8"))
        unknown = set(over.get("class", {})) - set(data.get("class", {}))
        if unknown:
            raise ValueError(f"heights file names unknown classes: {sorted(unknown)}")
        data = _merge(data, {k: over[k] for k in ("output", "class") if k in over})
    out = data.get("output", {})
    classes = {name: _tactile_class(name, c) for name, c in data.get("class", {}).items()}
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
    return Config(
        width_mm=float(out.get("width_mm", 120.0)),
        base_mm=float(out.get("base_mm", 2.0)),
        min_area_mm2=float(out.get("min_area_mm2", 0.0)),
        classes=classes,
        rules=rules,
        tactile=TactileRules(**data.get("tactile", {})),
        braille=BrailleSpec(**data.get("braille", {})),
        orientation_corner_mm=float(out.get("orientation_corner_mm", 8.0)),
        title=str(out.get("title", "")),
        map_scale=float(out.get("map_scale", 0.0)),
    )


def _tactile_class(name: str, c: dict) -> TactileClass:
    tex = c.get("texture")
    return TactileClass(
        name,
        c.get("role", "ignore"),
        float(c.get("height_mm", 0.0)),
        float(c.get("min_width_mm", 0.0)),
        str(c.get("label", "")),
        Texture(**tex) if isinstance(tex, dict) else None,
        bool(c.get("merge_gaps", True)),
    )
