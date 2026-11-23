# How pdf-map-to-stl works

This page is for anyone changing the code. For using the tool, see the [README](../README.md).

## The idea in one paragraph

An orienteering map exported to PDF (from OCAD or similar) is pure vector data: every
area, line and dot is a path with an exact colour, painted in a fixed order. So the
program never guesses from pixels. It reads the paths, recognises each map symbol from
its exact colour, width and pattern, works out what is visible where by replaying the
paint order with polygons, and turns each kind of area or object into a block of a
chosen height on a base plate. Pixels are used only to *check* the result, never to
make it.

## Pipeline

```
 MAP.pdf
   │  scene.py      every paint operation → polygon, cut by its clip paths and the crop;
   │                dot-grid patterns (ISOM 402…) → one area = their clip outline
   ▼
 primitives (ordered)
   │  config.py     rules in config/*.toml → class (open_land, building, wall, …) + role
   ▼
 classified primitives
   │  compose.py    terrain: painter's algorithm with polygons → each point has one class
   │                objects: kept as drawn (walls, hedges, trees sit on the terrain)
   ▼
 map model (PDF points)
   │  model3d.py    scale to print size, widen thin lines, extrude by height, merge
   ▼
 tactile model (mm) ──▶ model.stl
   │
   ├─ preview.py    relief_preview.png
   ├─ tuner.py      tuner.html   (choose heights interactively → heights.toml)
   ├─ report.py     symbols.csv, layers.svg, report.json
   └─ validate.py   classes.png, validation_errors.png (agreement with the rendered PDF)
```

`pipeline.py` runs these steps in order; read it first. `cli.py` only parses arguments.
`pick.py` is separate: it renders the page so the user can choose a crop.

## Modules

| Module | Does | Main function |
|---|---|---|
| `cli.py` | `pick` and `build` commands | `main` |
| `pipeline.py` | runs all steps, writes outputs | `build(BuildOptions)` |
| `scene.py` | PDF → ordered primitives | `load_scene` |
| `geometry.py` | PDF path items → Shapely polygons (fill rules, stroke caps/joins, Béziers) | `fill_geometry`, `stroke_geometry` |
| `config.py` | loads TOML; matches a primitive to a class | `load_config`, `Config.classify` |
| `compose.py` | visible terrain + objects | `build_map` |
| `model3d.py` | layers in mm, solid, STL | `build_layers`, `build_solid`, `write_stl` |
| `validate.py` | pixel check against the PDF | `validate` |
| `preview.py`, `report.py` | images, CSV, SVG, JSON | |
| `tuner.py` + `tuner_template.html` | interactive height tuner | `write_tuner` |
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

**Terrain vs objects.** Terrain classes (paved, open land, forest, buildings, water…)
tile the map: every point has exactly one. They come from replaying the paint order.
Objects (walls, hedges, trees) are placed on top using their own outline, so a wall
never punches a hole in the open land under it. Ignored symbols (course, contours,
north lines, thin outlines) are dropped before composing, so they never hide anything.

**Configuration, not code.** Everything specific to a map or a symbol set is in
`config/default.toml`: which colour is which symbol, which class is terrain or object,
heights, minimum widths. Supporting a new map should normally need no code change.

**Heights are chosen by touch.** Default heights are placeholders. `tuner.html` lets
the user try heights on a 3D view and saves `heights.toml`; `--region` prints a small
test tile to feel them before printing the whole map.

## Coordinate frames

| Where | Units | Origin | y axis |
|---|---|---|---|
| PDF / scene / compose | points (1/72 in) | page top-left | down |
| `--crop` | mm on the PDF page | page top-left | down |
| model / STL / `--region` | mm on the print | model bottom-left | up |

`model3d._to_model` is the one place that converts PDF points to model millimetres.

## Common changes

- **A symbol is recognised wrongly or not at all:** look at `symbols.csv`, then add or
  reorder a `[[symbol]]` rule in the TOML (first match wins).
- **A new kind of feature:** add a `[class.name]` with a role and height, then point a
  rule at it. Objects can set `min_width_mm`.
- **Change how the solid is built** (e.g. textures for vegetation): `model3d.build_solid`.
- **Change the check:** `validate.py`. Keep `tests/test_sample_pipeline.py` passing: it
  checks the STL is watertight, the agreement is at least 99.5 %, and two runs give
  byte-identical files.

## Tests

`pytest` runs geometry unit tests and end-to-end checks on `samples/sample.pdf`
(about 30 s). `ruff check src tests` must pass.
