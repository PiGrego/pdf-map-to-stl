# pdf-map-to-stl

Turns a vector orienteering map (a PDF exported from OCAD or similar) into a tactile
map for blind and visually impaired people: a 3D model (STL) to print, with its tactile
legend. Developed by BrailleFly and Corifea.

How it works inside: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Made to be read by touch

Every model is built for a blind reader, not just converted:

- **Orientation:** the top-right corner of the plate is cut off, so the reader always
  knows which way is up (north).
- **Braille title** along the bottom edge (the map's file name, or `--title`), at
  standard Braille size: dots 1.5 mm across, 2.5 mm apart, cells 6 mm apart. Braille
  is never scaled with the map.
- **Tactile legend** (`legend.stl`): a second small plate with one sample of every area
  and object used in the map, each followed by its name in Braille. Same cut corner.
- **Heights and textures that can be told apart:** areas sit on levels 0.5 mm apart;
  areas sharing a level get a raised texture (dots or ridges). Walkable ground is low,
  things you cannot cross are high, water is recessed.
- **Tactile generalisation:** hairline artefacts are removed, passages narrower than a
  fingertip (3 mm) are widened, areas narrower than 1 mm are widened, and walls closer
  than 3 mm are merged into one.
- **Tactile check:** every build reports what is still too thin, too close, or too similar
  to feel, with locations in mm (`description.txt`) and as a picture (`tactile_check.png`).
- **Plain-text description** (`description.txt`): how to hold the model, the legend in
  words, the scale, and the check results, for a helper or a screen reader.

The thresholds (1 mm features, 3 mm gaps, 0.5 mm height steps) are common tactile-graphics
starting values, set in `[tactile]` of the config. Confirm them with the people who
will read the maps; test tiles (step 5) make that cheap.

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
millimetres), set the printed width, and copy the command it shows.

**2. Build**

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1 --width 120
```

Results go to `outputs\<map name>\` (change with `-o`):

| File | What it is |
|---|---|
| `model.stl` | the tactile map to print |
| `legend.stl` | the tactile legend to print |
| `description.txt` | how to hold it, the legend in words, scale, tactile check |
| `tactile_check.png` | where the model is still too thin, too close or too similar to feel |
| `relief_preview.png`, `legend_preview.png` | quick look at the models |
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

Open `tuner.html` in a browser. Change heights with the fields or sliders; the page
warns when two areas would feel the same. The 3D view needs internet; the rest of the
page works without it. Click **Download heights.toml** and build again with it:

```
pdf-map-to-stl build "maps\my map.pdf" --crop 14.6,14.6,27.8,24.1 --heights heights.toml
```

**5. Print a test tile first**

In `tuner.html`, type a rectangle under **Test tile** (or click **Pick on the 3D view**
and click two corners): it shows a command with `--region` that builds only that small
piece. Print it, have it read by touch, adjust, repeat.

**6. Print** `model.stl` and `legend.stl`, and give the reader `description.txt` (or
read it to them) together with the plates.

Before printing, check `description.txt`: if the tactile check still flags many places,
make the model bigger (`--width`) or convert a smaller part (`--crop`).

## Command reference

```
pdf-map-to-stl pick  MAP.pdf [--page N] [-o DIR]
pdf-map-to-stl build MAP.pdf [--page N] [--crop X0,Y0,X1,Y1] [--width MM]
                             [-c CONFIG.toml] [--heights HEIGHTS.toml]
                             [--region X0,Y0,X1,Y1] [--title TEXT] [--map-scale N]
                             [--no-validate] [-o DIR]
```

- `--crop`: part of the PDF page, in mm from the page's top-left corner.
- `--region`: part of the *model*, in mm from its bottom-left corner (test tiles).
- `--width`: printed width of the model in mm (height follows the map's proportions).
- `--title`: Braille title (default: the file name; `--title ""` for none).
- `--map-scale`: the printed map's scale (e.g. `4000` for 1:4000), so `description.txt`
  can say how many metres 1 cm on the model is.

## Development

```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
```

Version 0.1 (V15: hybrid vector + raster, DXF for Creo) is in the Git history on `main`
before the `rebuild/vector-native` branch.
