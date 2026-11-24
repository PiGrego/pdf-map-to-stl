# pdf-map-to-stl

Turns a vector orienteering map (a PDF exported from OCAD or similar) into a tactile
map for blind and visually impaired orienteers: a 3D-printable model, as one STL and as
one STL per layer for the slicer, with a tactile legend. Developed by BrailleFly and
Corifea.

How it works inside: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The IOF map
specifications (ISOM, ISSprOM) are in [docs/specifications](docs/specifications). Every setting, and every
decision the tool takes on its own: [docs/SETTINGS.md](docs/SETTINGS.md).

## Made to be read by touch

The default symbol set follows the draft guidebook *Conversion of ISOM and ISSprOM
orienteering maps into tactile orienteering maps* (Norwegian Orienteering Federation
with Tommaso Scalet): a few broad categories a cane user can tell apart, instead of the
full ISOM / ISSprOM set.

| Tactile symbol | How it feels (default) | From map symbols |
|---|---|---|
| paved area | flat, smooth | paved areas, canopy (canopy can be switched on as its own class) |
| open land | raised 0.5 mm, dots | 401, 402, 403, 412, 415 |
| forest | raised 1 mm, small rings | 405, 406, 408 |
| forbidden area | raised 1.5 mm, diagonal ridges | 520 out of bounds, 410 impassable vegetation |
| building | raised 3 mm, smooth | 521 |
| water | recessed 0.8 mm, wavy ridges | water |
| barrier | ridge 3.5 mm high | walls, fences, impassable hedges |
| tree | round dot, 2.5 mm | tree dots and rings |
| man-made object | cross, 3.5 mm | the black × objects |
| boulder | ring, 3 mm | (no rule yet) |

Footpaths and contours are switched off (they can be switched on), and the course and
other symbols with no tactile use are left out. For a richer set with more classes,
build with `-c config/isom_detailed.toml`.

Every model also has:

- **North symbols** at the top-right and bottom-left corners (ring end points north),
  and the **Braille title and scale** at the top left, as in the guidebook. Braille is
  standard size (dots 1.5 mm, 2.5 mm apart, cells 6 mm apart), never scaled with the map.
- **A tactile legend** (`legend.stl`) with one sample of every symbol used, each with
  its name in Braille. Flat symbols get a raised frame so they can be found.
- **Tactile generalisation:** drawing artefacts removed, passages narrower than 3 mm
  widened, areas narrower than 1 mm widened, walls closer than 3 mm merged. Walls are
  redrawn along their centre line at least 1 mm wide, with round ends and corners.
- **A tactile check** of what is still too thin, too close or too similar to feel,
  with locations (`description.txt`, `tactile_check.png`).
- **A plain-text description** (`description.txt`): how to hold the model, the legend
  in words, the scale, every automatic change, the check results.

## Everything is a setting

Each of these choices has a default you can change for one build, without editing the
config: textures on or off (all of them, or per class), which texture goes on which
area, standard symbols or shapes as drawn, round or sharp corners, how much smoothing,
each generalisation step, and which classes are shown (canopy, footpaths, contours).

```
pdf-map-to-stl build MAP.pdf --settings no_textures           all areas smooth: texture them in the slicer
pdf-map-to-stl build MAP.pdf --settings heights_only          only heights; shapes as drawn on the map
pdf-map-to-stl build MAP.pdf --set class.canopy.enabled=true  show canopy (portici, galleries)
```

`tuner.html` does the same with switches and a 3D view. Each build writes
`settings_used.toml` with every value it used. All settings: [docs/SETTINGS.md](docs/SETTINGS.md).

## Where the map is: position points

Blind readers use the map together with a navigation app, so the plate can say where it
is on Earth. Give one or two points of the map with their latitude and longitude:

```
pdf-map-to-stl build MAP.pdf --crop ... --geo 80,200,44.51500,11.34000 --geo "110,220,44°30'50.8\"N,11.341889"
```

`X,Y` is the place on the PDF page in mm from its top-left corner (`pick.html` gives it:
"Add a point", click the place, type the coordinates). Coordinates can be decimal, as a
web map copies them, or degrees, minutes and seconds. On the plate each point gets tall
pins, higher than anything else (point 1: one pin, point 2: two pins side by side), and
its coordinates are written in Braille in the bottom margin, in decimal degrees: the form
navigation apps accept. `description.txt` lists them with a web-map link, and with two
points it checks that their distance agrees with the map (a typing mistake shows there).

## Size and scale

A tactile map can be printed from 100 mm to 1000 mm across; the right size depends on
the map's detail. By default every build uses the **suggested size**: the one at which
90 % of the map's passages are at least 3 mm wide and its raised parts at least 1 mm,
rounded to a round tactile scale. The map scale is read from the page ("Scala 1: 5000")
or given with `--map-scale`. When the plate is larger than the printer bed, the build
also says which `--scale` fits the bed and how much detail that keeps.

```
pdf-map-to-stl size "maps\my map.pdf" --crop 70,190,120,227     the suggestion only, in seconds
```

`--scale 1000` or `--width 250` build at another size. The guidebook recommends
**1:500 to 1:1000**; details are in [docs/SETTINGS.md](docs/SETTINGS.md) (`[size]`). The thresholds (1 mm features, 3 mm gaps, 0.5 mm height
steps) are common tactile-graphics starting values in `[tactile]` of the config: confirm
them with readers, using test tiles (step 5).

## Install (once)

Needs Python 3.11 or newer.

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

Below, `pdf-map-to-stl` means `.venv\Scripts\pdf-map-to-stl` (or just `pdf-map-to-stl`
after `.venv\Scripts\activate`).

## Make a tactile map, step by step

**1. Pick the window**

```
pdf-map-to-stl pick "maps\my map.pdf"
```

Open the `pick.html` it writes and draw the part of the map you want: drag a
**rectangle**, or click the corners of a **polygon** (or type either in millimetres).
Copy the command it shows. Pick only map: a whole page also holds the title, the
control descriptions and logos, which would become terrain.

A polygon window gives a map with the shape of the polygon: the plate stays a
rectangle, a low raised line runs along the polygon's edge so it can be felt, and
outside it the plate is flat (`features.window_edge`).

**2. Build**

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1
```

It builds at the suggested size (see **Size and scale** above), or at `--scale 1000` or
`--width 200` if you give one. Results go to
`outputs\<map name>\` (change with `-o`):

| File | What it is |
|---|---|
| `model.stl` | the tactile map as one body (one-material prints) |
| `parts\*.stl` | the same map, one STL per layer: see **Printing** below |
| `legend.stl`, `legend_parts\*.stl` | the tactile legend, as one body and per layer |
| `description.txt` | how to hold it, the legend in words, scale, every automatic change, tactile check |
| `settings_used.toml` | every setting used; `--settings settings_used.toml` builds the same model again |
| `tactile_check.png` | where the model is still too thin, too close or too similar to feel |
| `relief_preview.png`, `legend_preview.png` | quick look at the models |
| `tuner.html` | heights, on/off, textures and shapes of every layer, with a 3D view |
| `symbols.csv` | every map symbol found and what it became; **check this for a new map** |
| `validation_errors.png` | red = model disagrees with the PDF, grey = not checked |
| `classes.png`, `layers.svg`, `report.json` | details |

**3. Check the symbols** (needed for a map you have not used before)

Open `symbols.csv`. Each row is one kind of symbol found in the map (colour, line
width, dot pattern) and the class it was given. If a row says `unclassified`, or a
symbol got the wrong class, copy `config\default.toml` to e.g. `config\my_map.toml`,
fix the `[[symbol]]` rules there, and build again with `-c config\my_map.toml`.

**4. Tune** in `tuner.html`: per layer, whether it is shown, its height, and its texture
or symbol shape; textures and standard symbols on or off for the whole model. It warns
when two areas would feel the same. Download `settings.toml` into the project folder and
run the build command the page shows (it adds `--settings settings.toml`).

**5. Print a test tile first:** in `tuner.html`, type a rectangle under **Test tile**:
it gives a command with `--region` that builds only that piece. Have it read by touch,
adjust, repeat.

**6. Print** the map and the legend, and give the reader `description.txt` (or read it
to them) with the plates.

## Printing: one STL per layer

`parts\` holds one STL per layer: the base plate, every area (each owns the top 0.6 mm
of the plate under it, so flat areas too), every object, every texture, the north
symbols and the Braille. All files share one coordinate system and touch without
overlapping, so the slicer can give each layer its own filament or colour, fuzzy skin
or ironing, and so on. `parts\README.txt` lists the parts with a suggested colour.

Load them **as one object with several parts**, not as separate objects (the slicer
would drop each one to the bed and move it):

- Bambu Studio, OrcaSlicer: import all files at once and answer Yes to loading them as
  a single object with multiple parts.
- PrusaSlicer: the same question appears when the printer profile has more than one
  extruder; otherwise load `00_base.stl` and add the others with right-click > Add part.

## A stand-alone legend

```
pdf-map-to-stl legend "maps\my map.pdf" --title "key navile"
```

builds a legend plate with every tactile symbol found in the whole map (or `--crop`),
as `legend.stl`, `parts\*.stl` and `legend.txt` (which also lists the map symbols behind
each entry), in `outputs\<map name>\legend\`.

## Command reference

```
pdf-map-to-stl pick   MAP.pdf [--page N] [-o DIR]
pdf-map-to-stl size   MAP.pdf [--page N] [--crop X0,Y0,X1,Y1[,...]] [--map-scale N] [settings options]
pdf-map-to-stl build  MAP.pdf [--page N] [--crop X0,Y0,X1,Y1[,...]] [--width MM]
                              [--map-scale N] [--scale N] [-c CONFIG.toml]
                              [--settings FILE_OR_PROFILE]... [--set SECTION.KEY=VALUE]...
                              [--no-textures] [--region X0,Y0,X1,Y1] [--geo X,Y,LAT,LON]...
                              [--title TEXT] [--no-validate] [-o DIR]
pdf-map-to-stl legend MAP.pdf [--page N] [--crop X0,Y0,X1,Y1[,...]] [-c CONFIG.toml]
                              [--settings FILE_OR_PROFILE]... [--set SECTION.KEY=VALUE]...
                              [--no-textures] [--title TEXT] [-o DIR]
```

- `--crop`: the window on the PDF page, in mm from the page's top-left corner: `X0,Y0,X1,Y1`
  for a rectangle, or `X,Y` of each corner (3 or more) for a polygon.
- `--map-scale`: the printed map's scale (e.g. `5000`); by default read from the page.
- `--scale`: build at this tactile scale (e.g. `1000`) instead of the suggested size.
- `--width`: printed width of the map in mm, instead of the suggested size.
- `--region`: part of the *map* on the model, in mm from its bottom-left corner (test tiles).
- `--title`: Braille title (default: the file name; `--title ""` for none).
- `--settings`: a settings file or a profile (`no_textures`, `as_drawn`, `heights_only`);
  repeatable, applied in order. `--heights` still works for old tuner files.
- `--set`: change one setting, e.g. `--set smoothing.line_join=mitre`; repeatable, applied last.
- `--no-textures`: every area smooth.
- `--geo`: a position point (up to two): `X,Y` on the page in mm, then latitude and longitude.

## Development

```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
```

Version 0.1 (V15: hybrid vector + raster, DXF for Creo) is in the Git history on `main`
before the `rebuild/vector-native` branch.
