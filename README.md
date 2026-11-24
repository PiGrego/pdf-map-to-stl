# pdf-map-to-stl

Turns a vector orienteering map (a PDF exported from OCAD or similar) into a tactile
map for blind and visually impaired orienteers: a 3D-printable model, as one STL and as
one STL per layer for the slicer, with a tactile legend. Developed by BrailleFly and
Corifea.

How it works inside: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Made to be read by touch

The default symbol set follows the draft guidebook *Conversion of ISOM and ISSprOM
orienteering maps into tactile orienteering maps* (Norwegian Orienteering Federation
with Tommaso Scalet): a few broad categories a cane user can tell apart, instead of the
full ISOM / ISSprOM set.

| Tactile symbol | How it feels (default) | From map symbols |
|---|---|---|
| paved area | flat, smooth | paved areas, canopy |
| open land | raised 0.5 mm, dots | 401, 402, 403, 412, 415 |
| forest | raised 1 mm, small rings | 405, 406, 408 |
| forbidden area | raised 1.5 mm, diagonal ridges | 520 out of bounds, 410 impassable vegetation |
| building | raised 3 mm, smooth | 521 |
| water | recessed 0.8 mm, wavy ridges | water |
| barrier | ridge 3.5 mm high | walls, fences, impassable hedges |
| tree | round dot, 2.5 mm | tree dots and rings |
| man-made object | cross, 3.5 mm | the black × objects |
| boulder | ring, 3 mm | (no rule yet) |

Footpaths, contours, the course and other symbols with no tactile use are left out.
For a richer set with more classes, build with `-c config/isom_detailed.toml`.

Every model also has:

- **North symbols** at the top-right and bottom-left corners (ring end points north),
  and the **Braille title and scale** at the top left, as in the guidebook. Braille is
  standard size (dots 1.5 mm, 2.5 mm apart, cells 6 mm apart), never scaled with the map.
- **A tactile legend** (`legend.stl`) with one sample of every symbol used, each with
  its name in Braille. Flat symbols get a raised frame so they can be found.
- **Tactile generalisation:** drawing artefacts removed, passages narrower than 3 mm
  widened, areas narrower than 1 mm widened, walls closer than 3 mm merged.
- **A tactile check** of what is still too thin, too close or too similar to feel,
  with locations (`description.txt`, `tactile_check.png`).
- **A plain-text description** (`description.txt`): how to hold the model, the legend
  in words, the scale, the check results.

The guidebook recommends **1:500 to 1:1000 on A4**; build with `--map-scale` (the printed
map's scale) and `--scale 1000`. The thresholds (1 mm features, 3 mm gaps, 0.5 mm height
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

**1. Pick the area** (skip to convert the whole page)

```
pdf-map-to-stl pick "maps\my map.pdf"
```

Open the `pick.html` it writes, drag a rectangle over the part you want (or type it in
millimetres) and copy the command it shows.

**2. Build** at the tactile scale

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1 --map-scale 5000 --scale 1000
```

(or set the printed width directly with `--width 200`). Results go to
`outputs\<map name>\` (change with `-o`):

| File | What it is |
|---|---|
| `model.stl` | the tactile map as one body (one-material prints) |
| `parts\*.stl` | the same map, one STL per layer: see **Printing** below |
| `legend.stl`, `legend_parts\*.stl` | the tactile legend, as one body and per layer |
| `description.txt` | how to hold it, the legend in words, scale, tactile check |
| `tactile_check.png` | where the model is still too thin, too close or too similar to feel |
| `relief_preview.png`, `legend_preview.png` | quick look at the models |
| `tuner.html` | heights of every layer and the base, with a 3D view |
| `symbols.csv` | every map symbol found and what it became; **check this for a new map** |
| `validation_errors.png` | red = model disagrees with the PDF, grey = not checked |
| `classes.png`, `layers.svg`, `report.json` | details |

**3. Check the symbols** (needed for a map you have not used before)

Open `symbols.csv`. Each row is one kind of symbol found in the map (colour, line
width, dot pattern) and the class it was given. If a row says `unclassified`, or a
symbol got the wrong class, copy `config\default.toml` to e.g. `config\my_map.toml`,
fix the `[[symbol]]` rules there, and build again with `-c config\my_map.toml`.

**4. Tune the heights** in `tuner.html` (fields or sliders; it warns when two areas
would feel the same), download `heights.toml` and build again with `--heights heights.toml`.

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
pdf-map-to-stl build  MAP.pdf [--page N] [--crop X0,Y0,X1,Y1] [--width MM]
                              [--map-scale N] [--scale N] [-c CONFIG.toml]
                              [--heights HEIGHTS.toml] [--region X0,Y0,X1,Y1]
                              [--title TEXT] [--no-validate] [-o DIR]
pdf-map-to-stl legend MAP.pdf [--page N] [--crop X0,Y0,X1,Y1] [-c CONFIG.toml]
                              [--heights HEIGHTS.toml] [--title TEXT] [-o DIR]
```

- `--crop`: part of the PDF page, in mm from the page's top-left corner.
- `--map-scale`: the printed map's scale (e.g. `5000`); adds the scale to the title.
- `--scale`: build at this tactile scale (e.g. `1000`); needs `--map-scale`.
- `--width`: printed width of the map in mm, instead of `--scale`.
- `--region`: part of the *map* on the model, in mm from its bottom-left corner (test tiles).
- `--title`: Braille title (default: the file name; `--title ""` for none).

## Development

```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
```

Version 0.1 (V15: hybrid vector + raster, DXF for Creo) is in the Git history on `main`
before the `rebuild/vector-native` branch.
