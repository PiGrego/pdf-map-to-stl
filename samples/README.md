# Sample maps

- `orienteering-map-sample-Navile.pdf`: the Navile sprint map (ISSprOM, printed at
  1:5000), exported from OCAD, included with the permission of the club that made it.
  The symbol rules in `config/default.toml` are calibrated on it, and the tests run on
  it, on a 50 x 37 mm window of the page (`tests/sample_map.py`).

Try it on that window. The scale is read from the page (1:5000) and the print size is
suggested from the map's details (1:900, or `--scale 1000` to fit a 256 mm bed):

```
pdf-map-to-stl build samples\orienteering-map-sample-Navile.pdf --crop 70,190,120.058,226.926
```

or choose another part with `pdf-map-to-stl pick samples\orienteering-map-sample-Navile.pdf`.
