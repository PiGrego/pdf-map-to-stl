# How pdf-map-to-stl works

This page is for anyone changing the code. For using the tool, see the [README](../README.md).

## The idea in one paragraph

The goal is a tactile map **for blind and visually impaired readers**: everything is
judged by whether the printed plate can be read by touch. The people running the tool
are usually sighted.

An orienteering map exported to PDF (from OCAD or similar) is pure vector data: every
area, line and dot is a path with an exact colour, painted in a fixed order. So the
program never guesses from pixels. It reads the paths, recognises each map symbol from
its exact colour, width and pattern, works out what is visible where by replaying the
paint order with polygons, and turns each kind of area or object into a block of a
chosen height on a base plate. Then it makes the result readable by touch: it
simplifies what a finger cannot resolve, adds textures, north symbols, Braille
and a tactile legend, and checks what is still too fine. Pixels are used only to
*check* the result, never to make it.

## Pipeline

```
 MAP.pdf
   │  scene.py      every paint operation → polygon, cut by its clip paths and the window
   │                (a rectangle or a polygon chosen in pick.html);
   │                dot-grid patterns (ISOM 402…) → one area = their clip outline
   ▼
 primitives (ordered)
   │  config.py     rules in config/*.toml → class (open_land, building, wall, …) + role;
   │                settings files and --set on top; classes switched off → merge_into
   ▼
 classified primitives
   │  compose.py    terrain: painter's algorithm with polygons → each point has one class
   │                objects: kept as drawn (walls, hedges, trees sit on the terrain)
   ▼
 map model (PDF points)
   │  size.py       suggested print size from the passages and parts of the map
   │  relief.py     slopes (optional): bands between contours, lowest where the water is
   │  model3d.py    scale to print size, redraw lines along their centre (min width,
   │                caps and joins from [smoothing])
   │  generalize.py (simplify), remove artefact slivers, open narrow passages, widen thin
   │                areas, merge walls that are too close, (round corners)
   │  model3d.py    standard point symbols, textures, Braille title, north symbols,
   │                position pins and their coordinates in Braille (geo.py);
   │                extrude and merge
   ▼
 tactile model (mm) ──▶ model.stl (one body)
   │
   ├─ parts.py          parts/*.stl    (one STL per layer, aligned, non-overlapping)
   ├─ legend.py         legend.stl     (tactile key: samples + Braille labels)
   ├─ tactile_check.py  can it be read by touch? thin parts, gaps, height steps…
   ├─ describe.py       description.txt (plain text: holding, legend, scale, automatic
   │                    changes, check)
   ├─ config.py         settings_used.toml (every setting the build used)
   ├─ preview.py    relief_preview.png, legend_preview.png, tactile_check.png,
   │                relief_levels.png (slopes)
   ├─ tuner.py      tuner.html   (heights, switches, textures, shapes → settings.toml)
   ├─ report.py     symbols.csv, layers.svg, report.json
   └─ validate.py   classes.png, validation_errors.png (agreement with the rendered PDF)
```

`pipeline.py` runs these steps in order (`build`), and also makes stand-alone legends
from every symbol in a map (`build_legend_sample`); read it first. `cli.py` only parses
arguments.
`pick.py` is separate: it renders the page so the user can choose a crop.

## Modules

| Module | Does | Main function |
|---|---|---|
| `cli.py` | `pick`, `build` and `legend` commands | `main` |
| `pipeline.py` | runs all steps, writes outputs | `build(BuildOptions)` |
| `scene.py` | PDF → ordered primitives | `load_scene` |
| `geometry.py` | PDF path items → Shapely polygons (fill rules, stroke caps/joins, Béziers) | `fill_geometry`, `stroke_geometry` |
| `config.py` | loads the config and settings files; matches a primitive to a class; writes settings_used.toml | `load_config`, `Config.classify`, `Config.shown_as`, `settings_dict` |
| `compose.py` | visible terrain + objects | `build_map` |
| `model3d.py` | layers in mm, textures, standard symbols, Braille title, north symbols, solid, STL | `build_layers`, `build_solid`, `write_stl` |
| `geo.py` | position points: coordinates in any form, pins, the distance check | `parse_geo`, `pins`, `check_points` |
| `relief.py` | slopes (optional): bands between contour lines and their levels | `find_relief` |
| `size.py` | suggested print size from the map's details and scale | `suggest_size` |
| `generalize.py` | tactile simplification and optional smoothing of the layers | `generalize` |
| `braille.py` | text → Braille cells → dot positions in mm | `to_cells`, `dot_centres` |
| `legend.py` | the tactile legend plate and its text | `build_legend`, `classes_in_map` |
| `parts.py` | one STL per layer for slicers, with a README | `build_parts`, `write_parts` |
| `tactile_check.py` | readability-by-touch checks | `check_model` |
| `describe.py` | plain-text description, including every automatic change | `describe`, `automatic_changes` |
| `validate.py` | pixel check against the PDF | `validate` |
| `preview.py`, `report.py` | images, CSV, SVG, JSON | |
| `tuner.py` + `tuner_template.html` | interactive tuner: heights, switches, textures, shapes | `write_tuner` |
| `pick.py` + `pick_template.html` | interactive area picker | `write_picker` |

## Key decisions

**Vector only.** Earlier versions (V14, V15) mixed vectors with a 600 dpi raster and
fought anti-aliasing, colour thresholds and a pixel/vector misalignment. Here geometry
comes only from paths, and the renderer and the drawings share one coordinate frame,
so there is nothing to calibrate.

**Dot screens are areas.** OCAD exports patterns such as ISOM 402 as thousands of dots
on a page-wide grid, trimmed by a clip path that is the area outline. `scene.py`
detects a clip whose content is only same-colour, same-size dots and uses the clip
outline as the area. The dot diameter and spacing identify the symbol (402 yellow dots,
412 green, 415 black: the ISOM 2000 sizes times the map's enlargement).

**A window, not the whole page.** A map page also holds a title, control descriptions,
logos and a north arrow printed on top of the map; converted, they would become terrain.
So the operator always picks the part to convert: a rectangle, or a polygon that follows
the area of interest (`Scene.window`). Everything outside it is dropped in `scene.py`;
the model keeps a rectangular plate, with a raised line along a polygon's edge.

**Terrain vs objects.** Terrain classes (paved, open land, forest, buildings, water…)
tile the map: every point has exactly one. They come from replaying the paint order.
Objects (walls, hedges, trees) are placed on top using their own outline, so a wall
never punches a hole in the open land under it. Ignored symbols (course, contours,
north lines, thin outlines) are dropped before composing, so they never hide anything.

**Configuration, not code.** Everything specific to a map or a symbol set is in
`config/default.toml`: which colour is which symbol, which class is terrain or object,
heights, minimum widths. Supporting a new map should normally need no code change.

**Every automatic decision is a setting.** Textures, standard symbols, line ends and
corners, smoothing, each generalisation step, and whether a class is shown at all have a
default in the config and can be changed per build (`--settings`, `--set`, the tuner),
without editing it. Settings are checked key by key, so a typo is an error. Each build
writes `settings_used.toml` and lists its automatic changes in `description.txt`, so
nothing happens without a trace. All settings: [SETTINGS.md](SETTINGS.md).

**Switching a class off keeps the map whole.** A terrain class that is off (canopy, by
default) is resolved in `compose.classify` into its `merge_into` class before the painter's
algorithm runs, so its area is not lost; `Classified.source` keeps the original class
for `symbols.csv` and the description. An object class that is off is ignored.

**The guidebook's symbol set by default.** `config/default.toml` follows the draft
guidebook on converting ISOM / ISSprOM maps into tactile orienteering maps (Norwegian
Orienteering Federation): a few broad categories (paved, open land, forest, forbidden,
building, water, barrier, tree, man-made object, boulder), standard point symbols
(`shape = "dot" | "ring" | "cross"`), north symbols at the top-right and bottom-left
corners, title and scale at the top left. `config/isom_detailed.toml` keeps a richer set.

**One part per layer.** 3D printing can do more than a thermoform sheet: each layer can
get its own filament, colour or surface treatment. `parts.py` cuts the model into
touching, non-overlapping solids in one coordinate system: every area owns a top skin
of the plate (so even flat areas are a part), objects only exist above the ground under
them, textures sit on their area, recesses own their floor.

**Readable by touch, by design.** Default heights sit on levels 0.5 mm apart, and
classes that share a level get a raised texture, so no two touching areas feel the
same. Walkable ground is low, barriers are high, water is recessed. The thresholds in
`[tactile]` (1 mm features, 3 mm gaps, 0.5 mm steps) are common tactile-graphics
starting values; they should be confirmed with readers.

**The details decide the size.** A tactile map can be printed at any size, so the
size is not a fixed default: `size.py` measures every passage and raised part of the
composed map and suggests the size at which 90 % of them meet the tactile rules, within
100 to 1000 mm, with a one-piece alternative when the plate exceeds the printer bed.
Generalisation then only has to fix the remaining few. The measurement runs on the map
as drawn and takes seconds, so `pdf-map-to-stl size` can answer before a build.

**Generalise, then check.** `generalize.py` does the safe, common simplifications a
tactile cartographer would do by hand, always moving area between terrain classes so
they keep tiling the map. `tactile_check.py` then reports whatever is still too fine,
with locations, instead of silently hiding it.

**Everything a reader needs is on the plate.** North symbols, Braille title and scale,
separate Braille legend, and optionally where the map is on Earth (position pins with
their coordinates in Braille, for navigation apps); Braille is placed at standard
physical size, never scaled.

**STL files are closed for every reader.** `manifold3d` keeps two volumes that touch
along an edge (two areas meeting at one corner) apart with duplicate vertices at the same
place. An STL has no topology: any reader merges vertices by position, and that edge then
belongs to 4 faces. Float32 coordinates also merge vertices closer than about 0.00003 mm.
`model3d.printable_mesh` (called by `write_stl`) collapses tiny edges, moves those
duplicates up to 0.002 mm apart into their own volume, and rebuilds the mesh from the
float32 coordinates; `report.json` counts the open edges of each file as written.
Raised layers that cross a recess (a wall along a lake) stand on its floor, like the
position pins, so there is no tunnel under them (`_recess_fills`; `parts.py` does the same).

**Bad input is reported, not converted silently.** A page with `/Rotate` is read as it is
shown (`scene._rotate_drawings`), so the window picked in `pick.html` is the one
converted. A window with no vector drawings (a scan) is an error. After the comparison
with the PDF, low agreement or a small checked area is a warning (`[validate]`), and so
is every symbol recognised only by its nearest colour or a measured size scale
(`[recognition]`, `config.estimate_size_scale`, `Config.nearest_rule_colour`).

**Heights are confirmed by touch.** `tuner.html` lets the operator try heights, switches,
textures and shapes on a 3D view (or in a plain form) and saves `settings.toml`;
`--region` prints a small test tile to have them read before printing the whole map.

## Coordinate frames

| Where | Units | Origin | y axis |
|---|---|---|---|
| PDF / scene / compose | points (1/72 in) | page top-left | down |
| `--crop` (window: rectangle or polygon) | mm on the PDF page | page top-left | down |
| model / STL / `--region` | mm on the print | model bottom-left | up |

`model3d._to_model` is the one place that converts PDF points to model millimetres.

## Common changes

- **A symbol is recognised wrongly or not at all:** look at `symbols.csv`, then add or
  reorder a `[[symbol]]` rule in the TOML (first match wins).
- **A new kind of feature:** add a `[class.name]` with a role and height, then point a
  rule at it. Objects can set `min_width_mm`.
- **Textures, symbols, Braille labels, heights, colours:** `texture`, `shape`/`size_mm`,
  `label`, `height_mm`, `colour` of each `[class.*]` in the TOML; texture presets in
  `[texture.*]`; Braille size in `[braille]`; switches in `[features]`; outline drawing
  in `[smoothing]`; generalisation steps in `[generalize]`; check thresholds in
  `[tactile]`; top skin of parts and legend height in `[output]`. See SETTINGS.md.
- **A new setting:** add a field to the matching dataclass in `config.py` (unknown keys
  are rejected, so the TOML cannot use it before), use it, add it to `default.toml` and
  to SETTINGS.md. `settings_dict` writes it to settings_used.toml by itself.
- **Change how the solid is built:** `model3d.build_solid`.
- **Change the check:** `validate.py`. Keep `tests/test_sample_pipeline.py` passing: it
  checks the STL is watertight, the agreement is at least 99.5 %, and two runs give
  byte-identical files.

## Tests

`pytest` runs unit tests (geometry, Braille, generalisation, tactile checks, parts,
legend) and end-to-end checks on `samples/orienteering-map-sample-Navile.pdf`, a real
sprint map, on a 50 x 37 mm window of it (`tests/sample_map.py`), mostly at a fixed
120 mm print width so they stay fast; `tests/test_size.py` checks the suggested size.
`tests/test_robustness.py` covers inputs and outputs that once failed silently: STL files
closed for any reader, walls over water, rotated pages, scans, other export scales and
colours, coordinates with typos, passages between different classes, and identical
rebuilds from `settings_used.toml`.
`ruff check src tests` must pass.
