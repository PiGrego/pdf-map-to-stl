# pdf-map-to-stl

Turns a vector orienteering map (a PDF exported from OCAD or similar) into a tactile
3D model (STL) for 3D printing. Developed by BrailleFly and Corifea.

How it works inside: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

Open the `pick.html` it writes, drag a rectangle over the part you want, set the
printed width, and copy the command it shows.

**2. Build**

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1 --width 120
```

Results go to `outputs\<map name>\` (change with `-o`):

| File | What it is |
|---|---|
| `model.stl` | the model to print |
| `relief_preview.png` | quick look at the model |
| `tuner.html` | 3D view with a height slider for every layer and the base |
| `symbols.csv` | every map symbol found and what it became; **check this for a new map** |
| `validation_errors.png` | red = model disagrees with the PDF, grey = not checked |
| `classes.png`, `layers.svg`, `report.json` | details |

**3. Check the symbols** (needed for a map you have not used before)

Open `symbols.csv`. Each row is one kind of symbol found in the map (colour, line
width, dot pattern) and the class it was given. If a row says `unclassified`, or a
symbol got the wrong class, copy `config\default.toml` to e.g. `config\my_map.toml`,
fix the `[[symbol]]` rules there, and build again with `-c config\my_map.toml`.
The comments in the TOML explain each field.

**4. Tune the heights**

Open `tuner.html` in a browser (it needs internet for the 3D library). Move the
sliders until the layers are easy to tell apart, then click **Download heights.toml**
and build again with it:

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1 --heights heights.toml
```

**5. Print a test tile first**

In `tuner.html`, click **Pick test tile** and click two corners: it shows a command
with `--region` that builds only that small piece. Print it, feel it, adjust, repeat.
Then build and print the whole model.

## Command reference

```
pdf-map-to-stl pick  MAP.pdf [--page N] [-o DIR]
pdf-map-to-stl build MAP.pdf [--page N] [--crop X0,Y0,X1,Y1] [--width MM]
                             [-c CONFIG.toml] [--heights HEIGHTS.toml]
                             [--region X0,Y0,X1,Y1] [--no-validate] [-o DIR]
```

- `--crop`: part of the PDF page, in mm from the page's top-left corner.
- `--region`: part of the *model*, in mm from its bottom-left corner (test tiles).
- `--width`: printed width of the model in mm (height follows the map's proportions).

## Development

```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
```

Version 0.1 (V15: hybrid vector + raster, DXF for Creo) is in the Git history on `main`
before the `rebuild/vector-native` branch.
