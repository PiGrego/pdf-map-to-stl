# Settings

Every choice the tool makes on its own is a setting with a default. This page lists them
all: what each one does, its default, and how to change it.

## How to change a setting

The defaults live in `config/default.toml`. You rarely need to edit it; instead, change
values for one build:

| How | Example | Use it for |
|---|---|---|
| a profile | `--settings no_textures` | a ready-made set of changes (below) |
| a settings file | `--settings my_settings.toml` | your own set of changes; only the values you want to change |
| one value | `--set class.canopy.enabled=true` | trying one change |
| the tuner | `tuner.html` → `settings.toml` | heights, switches, textures and shapes, with a 3D view |

They are applied in order: the config file, then each `--settings` (in the order given),
then each `--set`. A later value wins. `--settings` and `--set` can be repeated.

A settings file looks like the config, with only the values you change:

```toml
[features]
textures = false

[class.canopy]
enabled = true
height_mm = 0.3
```

Every build writes **`settings_used.toml`**: all the values it used, and in what order
they were applied. Build the same model again with `--settings settings_used.toml`.
**`description.txt`** has an *Automatic changes* section: what the tool changed on this
map (how many passages it widened, which symbols it merged…) and the setting behind each.

A misspelt setting or an unknown class is an error that names the known values; it is
never silently ignored. `--no-textures` is a shortcut for `--set features.textures=false`.

### Profiles (`config/profiles/`)

| Profile | What it changes |
|---|---|
| `no_textures` | every area smooth; classes differ only by height (texture them in the slicer) |
| `as_drawn` | shapes as close to the map as possible: no standard symbols, drawn line widths, sharp corners and flat ends, no generalisation; textures stay |
| `heights_only` | both of the above: only heights, everything else as on the map |

With `as_drawn` and `heights_only` the tactile check reports more problems: parts may be
too thin or too close to feel. Add your own profile by putting a `.toml` file in
`config/profiles/`.

## The settings

### `[size]`: the suggested print size

A tactile map can be printed at any size; what decides the right size is the map's
detail. With `output.width_mm = "auto"` (the default) every build uses the **suggested
size**, and `--width` or `--scale` override it. `pdf-map-to-stl size MAP.pdf [--crop …]`
prints the suggestion in a few seconds without building.

How it is found, on the map as drawn (before any generalisation):

1. Every **passage** between two raised parts of the same class (two buildings, two
   walls, two patches of open land; for trees, the gap between the printed dots) gives
   the enlargement at which it becomes `tactile.min_gap_mm` (3 mm) wide. Every **raised
   part** gives the enlargement at which it becomes `tactile.min_feature_mm` (1 mm) wide.
2. The suggestion is the enlargement that satisfies `detail_share` (90 %) of them. The
   rest is what generalisation adjusts and the tactile check reports.
3. With a known map scale it is rounded to a round tactile scale (1:900, 1:1000…),
   otherwise the width is rounded up to 10 mm.
4. The plate (map plus about 60 mm for the title and north symbols) is kept between
   `min_mm` and `max_mm` on its longer side. When the maximum decides, the description
   says how big the map would need to be, and what share of the details survive.
5. If the plate is larger than `bed_mm`, the description also gives the `--scale` (or
   `--width`) that fits the printer bed in one piece, and the share of details at that size.

On the Navile sample: the 50 × 37 mm part used by the tests gets 1:900 (map 278 mm wide,
90 % of 373 details), or 1:1000 to fit a 256 mm bed (88 %); the whole A4 page would need
about 1040 × 1470 mm at 1:1012, and is capped at 1000 mm (68 % of its details).

| Setting | Default | What it does |
|---|---|---|
| `min_mm` | `100` | the plate's longer side is at least this |
| `max_mm` | `1000` | ...and at most this |
| `detail_share` | `0.9` | share of passages and parts that must meet the tactile rules |
| `ignore_below_mm` | `0.15` | details narrower than this on the PDF page are drawing artefacts, not counted |
| `bed_mm` | `256` | printer bed; larger plates get a one-piece alternative, or print in tiles with `--region` |

The map scale comes from `--map-scale`, else `output.map_scale`, else the page itself
("Scala 1: 5000", "1:4 000"; `output.read_map_scale`). It sets the tactile scale in the
title and lets the suggestion use round scales.

### `[position]`: position points

Position points (`--geo X,Y,LAT,LON`, one or two) say where the map is on Earth: tall
pins on the map, and the coordinates in Braille in the bottom margin, for the reader's
navigation app.

| Setting | Default | What it does |
|---|---|---|
| `pin_mm` | `3.0` | pin diameter; point 1 is one pin, point 2 two pins side by side |
| `pin_height_mm` | `4.0` | above the plate, higher than anything else on the map, so they are easy to find |
| `decimals` | `5` | decimals of the degrees in Braille; 5 is about 1 m |

### `[relief]`: slopes as terraces (experimental, off by default)

With `--set relief.enabled=true`, every band between two contour lines is raised one
step above the band below it, like the "layer cake" relief of tactile and 3D maps, so a
reader can feel a hill rise and a slope fall. Everything on the ground rises with its
band. In `parts/` every part rises too, and the plate fills the space under them.

A map does not print the height of each band, so the direction is inferred: the bands
with water (lakes, canals) are the lowest, and the ground rises at every contour going
away from them, except where a slope tick on the map says it falls. This fits a park or
a hillside that slopes one way, with hills inside closed contours; a valley between two
hills without slope ticks can come out upside down. Check `relief_levels.png` (darker =
higher) and the SLOPES section of `description.txt`.

| Setting | Default | What it does |
|---|---|---|
| `enabled` | `false` | slopes as terraces |
| `step_mm` | `0.4` | height of one contour step on the model |
| `max_levels` | `12` | at most this many steps |
| `classes` | `["contour"]` | classes whose lines are contours |
| `min_width_mm` | `0.2` | thinner lines (dashed form lines) are left out (mm on the page) |
| `close_gaps_mm` | `10` | contour lines interrupted by paths or buildings are joined across gaps up to this (mm on the page) |
| `low` | `"water"` | how low ground is found: the bands with water |

### `[features]`: what the model contains

| Setting | Default | What it does |
|---|---|---|
| `textures` | `true` | raised patterns on areas; `false` = every area smooth |
| `standard_symbols` | `true` | trees, boulders and man-made objects drawn as standard tactile symbols (dot, ring, cross); `false` = as drawn on the map |
| `north_symbol` | `true` | raised north symbols at the top-right and bottom-left corners |
| `scale_bar` | `true` | a raised scale bar under the Braille title, with its distance in Braille (see `[scale_bar]`) |
| `legend_frames` | `true` | a raised frame around flat samples (paved) on the legend, so they can be found |
| `window_edge` | `true` | polygon windows: a raised line just outside the polygon, so the edge of the map can be felt (outside it the plate is flat, like paved ground) |

### `[scale_bar]`: the scale bar

Under the Braille title, a raised bar as long as a round distance on the ground (1, 2
or 5 times 1, 10, 100... m: at 1:1000, 50 m is 50 mm), with a tick at each end and ticks
between them (50 m: a tick every 10 m), and the distance in Braille at its right. It sits
beside the top-right north symbol, where the plate is usually empty, so it rarely makes
the plate taller. It needs the map's scale (read from the page, or `--map-scale`);
`description.txt` says what the bar measures. Switch it off with
`--set features.scale_bar=false` (or untick it in `pick.html`). Sizes in mm on the model.

| Setting | Default | What it does |
|---|---|---|
| `max_length_mm` | `80` | the longest round distance up to this long |
| `min_length_mm` | `10` | no bar if not even this much fits beside the north symbol |
| `height_mm` | `1.0` | how high the bar and its ticks stand above the plate |
| `width_mm` | `1.5` | width of the bar and of the ticks |
| `tick_mm` | `5.0` | length of the end ticks; the ticks between them are 3/5 as long |
| `min_tick_spacing_mm` | `6.0` | ticks between the ends only if they are at least this far apart |

### `[class.NAME]`: each tactile class

| Setting | What it does |
|---|---|
| `enabled` | `false` = not on the model. A ground class that is off gives its area to `merge_into` (without one, what is painted under it on the map shows instead); an object class that is off is left out |
| `merge_into` | the ground class that takes the area of this class when it is off |
| `role` | `terrain` (areas that tile the map), `object` (on top) or `ignore` (never shown) |
| `height_mm` | top above the base plate; negative = recessed into it |
| `texture` | a name from the texture library, `"none"`, or an inline table |
| `shape` | objects: `dot`, `ring` or `cross` draws every instance as that standard symbol of `size_mm`; `as_drawn` keeps the shape on the map |
| `size_mm` | size of the standard symbol |
| `min_width_mm` | objects: lines and small objects are widened to at least this (see `generalize.widen_objects`) |
| `merge_gaps` | objects: `false` keeps close instances apart (trees) |
| `label` | the Braille label on the legend (short, no accents) |
| `colour` | `[r, g, b]` for previews and the suggested filament colour of the part |

The default classes and how they feel:

| Class | Default | Map symbols | On? |
|---|---|---|---|
| paved | flat, smooth | 501 paved area (two colours) | on |
| open land | raised 0.5 mm, dots | 401, 402, 403, 412, 415 | on |
| forest | raised 1 mm, small rings | 405 (white, and unpainted paper), 406, 408 | on |
| forbidden | raised 1.5 mm, diagonal ridges | 520 out of bounds, 410 impassable vegetation | on |
| building | raised 3 mm, smooth | 521 | on |
| water | recessed 0.8 mm, wavy ridges | water | on |
| **canopy** | off: shown as paved. On: flat, fine east-west stripes | 522 canopy (portici, galleries) | **off** |
| barrier | 3.5 mm high, at least 1 mm wide | walls, fences, impassable hedges, black filled walls | on |
| tree | 2.5 mm dot, 2.5 mm high | green dots and green rings | on |
| man-made object | 3.5 mm cross, 2.5 mm high | the black × | on |
| boulder | 3 mm ring | (no rule matches it yet) | on |
| **footpath** | off. On: a raised line 2 mm high, its dashes joined | 505 footpath | **off** |
| **contour** | off. On: low ridges 1.8 mm high | 101 contour | **off** |

Never shown (role `ignore`): thin black outlines of buildings and areas, dotted lines,
small black dots around vegetation, green vegetation lines, the course overprint, north
lines, grey lines, and anything no rule recognises. To show one of these, give it a role
and a height in a copy of the config.

Examples:

```
--set class.canopy.enabled=true                 canopy on, with its stripes
--set class.canopy.texture=none                 ...or smooth
--set class.canopy.height_mm=0.3                ...or slightly raised
--set class.footpath.enabled=true               footpaths as raised lines
--set class.tree.shape=ring                     trees as rings
--set class.forest.texture=dots                 forest with the open-land dots
```

### `[texture.NAME]`: the texture library

| Texture | Kind | Default | Used by |
|---|---|---|---|
| `dots` | dots | 1.2 mm dots every 3 mm, 0.5 mm high | open land |
| `rings` | rings | 2.4 mm rings every 4 mm, 0.5 mm high | forest |
| `hatching` | lines | 1 mm ridges every 3 mm at 45°, 0.5 mm high | forbidden |
| `waves` | waves | 0.8 mm wavy ridges every 3 mm, 0.4 mm high | water |
| `stripes` | lines | 0.8 mm ridges every 2.5 mm east-west, 0.4 mm high | canopy |

Keys: `kind` (`dots`, `rings`, `lines`, `waves`), `pitch_mm` (distance between dots or
ridges), `size_mm` (dot or ring diameter, ridge width), `height_mm`, `angle_deg` (ridge
direction, 0 = east-west), `line_mm` (ring wall). Add your own as `[texture.my_name]` in
a settings file and use it with `texture = "my_name"`.

Textures keep half their size plus 0.3 mm away from the edge of their area (0.9 mm for
the dots), so the edge stays crisp, and
their grid is anchored to the plate, so neighbouring pieces line up. Pieces of ridge too
short to feel are dropped. On a recessed area (water) the texture stands on the floor.

### `[smoothing]`: how outlines are drawn

| Setting | Default | What it does |
|---|---|---|
| `line_join` | `"round"` | corners of redrawn lines (walls, fences): `round`, `mitre` or `bevel` |
| `line_cap` | `"round"` | ends of redrawn lines: `round`, `flat` or `square` |
| `arc_segments` | `4` | segments per quarter circle wherever the tool rounds a shape |
| `curve_step_mm` | `0.035` | chord length when reading curves from the PDF (mm on the PDF page); smaller = smoother and slower |
| `simplify_mm` | `0` | remove outline detail smaller than this; `0` = exact outlines |
| `round_corners_mm` | `0` | round sharp corners of areas and objects with this radius; `0` = as drawn |

**Where the rounding you see comes from**, with the defaults:

1. Walls and other line objects are not copied from the PDF: they are redrawn along their
   centre line, at least `min_width_mm` wide, with round ends and round corners
   (`line_cap`, `line_join`). Use `mitre` and `flat` for sharp corners.
2. Objects closer than `merge_gap_mm` merge (double walls). This fills in the inside
   corners of walls: the biggest visible rounding (`generalize.merge_close_objects`,
   `generalize.merge_gap_mm`).
3. Generalisation widens passages and thin parts with rounded growth (`[generalize]`).
4. Small objects narrower than their `min_width_mm` grow, with rounded corners.

Area outlines are otherwise exact: they follow the PDF to within `curve_step_mm`.
`simplify_mm` and `round_corners_mm` add more smoothing if you want it. Areas keep
tiling the map exactly: what one loses, its neighbour gains.

### `[generalize]`: automatic changes for touch

Run in this order; each can be switched off. The targets come from `[tactile]`.

| Setting | Default | What it does |
|---|---|---|
| `clean_slivers` | `true` | ground strips narrower than `sliver_mm` are drawing artefacts (fills that do not quite meet): given to the area around them |
| `sliver_mm` | `0.4` | |
| `open_passages` | `true` | passages between parts of a raised area (two buildings) narrower than `tactile.min_gap_mm` are widened to it, by trimming the raised area |
| `widen_thin` | `true` | raised parts narrower than `tactile.min_feature_mm` grow into the lower ground around them |
| `merge_close_objects` | `true` | objects of one class closer than `merge_gap_mm` merge into one (double walls, the dashes of a path); not classes with `merge_gaps = false` (trees) |
| `merge_gap_mm` | `3.0` | |
| `widen_objects` | `true` | lines and small objects are widened to their class `min_width_mm`; `false` = drawn width |
| `min_area_mm2` | `0.4` | pieces smaller than this are dropped (too small to feel or print) |

### `[tactile]`: the tactile check

| Setting | Default | What it checks |
|---|---|---|
| `min_feature_mm` | `1.0` | raised parts narrower than this are hard to feel and to print |
| `min_gap_mm` | `3.0` | raised parts closer than this feel like one |
| `min_height_step_mm` | `0.5` | neighbouring areas whose heights differ less, with the same texture, feel the same |
| `min_symbol_area_mm2` | `9.0` | isolated areas smaller than this are hard to identify |

Starting values from common tactile-graphics practice: confirm them with the people who
read the maps, using test tiles.

The check also reports **narrow passages**: lower ground narrower than `min_gap_mm`
between raised parts of different classes (a wall next to a strip of grass), at least
`min_height_step_mm` below them. A finger cannot follow such a passage. Same-class gaps
are counted as narrow gaps, not here.

### `[recognition]`: other exports of a map

The `[[symbol]]` rules match the exact colours and sizes of the map they were made on.
The same map exported by another program, or printed at another scale, has slightly other
colours and proportionally thicker or thinner lines. These settings let the rules still
work. Every symbol they affect is marked in `symbols.csv` and `description.txt`, and the
build prints a warning, so check those rows.

| Setting | Default | What it does |
|---|---|---|
| `size_scale` | `"auto"` | sizes in the rules (line widths, extents, dot screens) are multiplied by this. `"auto"` measures it on the dot screens of the map (402...): their dots and spacing must both differ by the same factor; within 10 % of 1 it stays 1 |
| `colour_match_de` | `10.0` | a colour that no rule matches takes the nearest rule colour, if within this perceptual distance (CIE delta E; 2 is just visible). `0` = off |
| `colour_margin_de` | `3.0` | ...but only if every other rule colour is at least this much farther; otherwise the symbol stays unrecognised (two rule greys can be close) |

### `[validate]`: warnings from the comparison with the PDF

After a build, the class map is compared with the PDF as rendered (`validation_errors.png`).
A low result means something is wrong with the input, not with the map.

| Setting | Default | What it does |
|---|---|---|
| `min_agreement` | `0.99` | warn when the model agrees with the PDF on less of the checked area |
| `min_checked_share` | `0.3` | warn when less of the window could be checked (colours the rules do not know, a scan) |

### `[output]`: size and layout

| Setting | Default | What it does |
|---|---|---|
| `width_mm` | `"auto"` | printed width of the map in mm; `"auto"` = the suggested size (`[size]`); `--width` and `--scale` override it |
| `base_mm` | `2.0` | base plate thickness; recesses always leave 0.4 mm of plate |
| `top_skin_mm` | `0.6` | per-layer parts: each area owns this much of the plate under it |
| `north_height_mm` | `1.0` | height of the north symbols |
| `window_edge_mm`, `window_edge_height_mm` | `1.5`, `1.0` | width and height of the line along a polygon window's edge |
| `orientation_corner_mm` | `0` | cut off the top-right corner of the plate by this much |
| `title` | `"auto"` | Braille title at the top left: `"auto"` = the file name, `""` = none |
| `map_scale` | `0` | scale of the printed map (or `--map-scale`); 0 = unknown |
| `read_map_scale` | `true` | when the scale is unknown, read it from the page ("1:5000") |
| `legend_max_height_mm` | `200` | the legend plate wraps into columns above this height |

Fixed layout, not settings: 5 mm margins, north symbols 7 × 20 mm, legend samples
16 × 10 mm, legend frames 0.8 mm wide and 0.6 mm high.

Fixed, not settings, because they are far below what a printer or a finger resolves:
before an STL is written, edges shorter than 0.0001 mm are collapsed, and where two
volumes touch along an edge (two areas meeting at one corner) they are moved up to
0.002 mm apart, so the file is closed (watertight) for every program that reads it.
`report.json` gives `open_edges` (0 = closed) and `separated_vertices` for each STL.

### `[braille]`: Braille size

`dot_diameter_mm` 1.5, `dot_height_mm` 0.6, `dot_spacing_mm` 2.5, `cell_spacing_mm` 6,
`line_spacing_mm` 10. Uncontracted Braille, never scaled with the map. Dots are
rounded-off cones, easy to read and to print.

### `[[symbol]]` rules

Which PDF paint operation becomes which class. These belong in the config file, not in
settings files: copy `config/default.toml` and edit the rules for a map with other
colours (see the README, step 3). Two decisions in the rules are worth knowing:

- paper with nothing printed on it counts as **forest** (white is forest in ISOM);
- the first rule that matches wins, so the order of the black rules matters
  (crosses, then footpath dashes, dotted lines, walls, outlines).
