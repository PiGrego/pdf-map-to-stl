"""Command line.

    pdf-map-to-stl pick   MAP.pdf             choose the window to convert: rectangle or polygon (pick.html)
    pdf-map-to-stl build  MAP.pdf [options]   convert to STL: one body + one STL per layer,
                                              legend, description, tuner.html, previews
    pdf-map-to-stl legend MAP.pdf [options]   stand-alone tactile legend of every symbol in a map
    pdf-map-to-stl size   MAP.pdf [options]   only the suggested print size (quick, builds nothing)

Settings (build and legend): every value in config/default.toml can be changed for one
build with --settings FILE (or a profile name: no_textures, as_drawn, heights_only) and
--set section.key=value. See docs/SETTINGS.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .pick import write_picker
from .pipeline import BuildOptions, LegendOptions, build, build_legend_sample, suggest


def _rect(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError as e:
        raise argparse.ArgumentTypeError("expected four numbers: x0,y0,x1,y1") from e
    return (x0, y0, x1, y1)


def _window(text: str) -> tuple[float, ...]:
    """--crop: four numbers are a rectangle (two corners), six or more a polygon."""
    try:
        v = tuple(float(x) for x in text.replace(";", ",").split(",") if x.strip())
    except ValueError as e:
        raise argparse.ArgumentTypeError("expected numbers separated by commas") from e
    if len(v) != 4 and (len(v) < 6 or len(v) % 2):
        raise argparse.ArgumentTypeError("expected x0,y0,x1,y1 (a rectangle) or x,y of 3 or more points (a polygon)")
    return v


WINDOW_HELP = ("the window to convert, mm from the page's top-left corner: X0,Y0,X1,Y1 for a rectangle, "
               "or X,Y of each corner of a polygon (3 or more points); get it from pick.html")


def _default_out(pdf: Path) -> Path:
    return Path("outputs") / pdf.stem.replace(" ", "_")


def _settings_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", type=Path, help="symbol rules, classes and defaults (default config/default.toml)")
    p.add_argument("--settings", action="append", default=[], metavar="FILE",
                   help="settings file or profile name (no_textures, as_drawn, heights_only), applied after the "
                        "config; repeat to apply several in order. settings.toml from tuner.html and "
                        "settings_used.toml from a build are settings files")
    p.add_argument("--heights", type=Path, help="same as --settings (heights.toml from older tuner pages)")
    p.add_argument("--set", action="append", default=[], dest="overrides", metavar="SECTION.KEY=VALUE",
                   help="change one setting, e.g. --set class.canopy.enabled=true or --set smoothing.line_join=mitre; "
                        "repeatable, applied last")
    p.add_argument("--no-textures", action="store_true", help="all areas smooth (same as --set features.textures=false)")


def _overrides(a) -> tuple:
    return tuple(a.overrides) + (("features.textures=false",) if a.no_textures else ())


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pdf-map-to-stl", description="Vector orienteering map PDF -> tactile STL.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pick", help="open the map page to choose the window to convert (rectangle or polygon)")
    p.add_argument("pdf", type=Path)
    p.add_argument("--page", type=int, default=0, help="page number, from 0")
    p.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>)")

    b = sub.add_parser("build", help="convert the map (or a part of it) to STL")
    b.add_argument("pdf", type=Path)
    b.add_argument("--page", type=int, default=0, help="page number, from 0")
    b.add_argument("--crop", type=_window, metavar="X0,Y0,X1,Y1[,...]", help=WINDOW_HELP)
    b.add_argument("--width", type=float, metavar="MM",
                   help="printed map width (default: the suggested size, from the map's details)")
    _settings_args(b)
    b.add_argument("--region", type=_rect, metavar="X0,Y0,X1,Y1",
                   help="only this rectangle of the model, mm from its bottom-left corner: a test tile")
    b.add_argument("--title", metavar="TEXT",
                   help='Braille title at the top left (default: the file name; --title "" for none)')
    b.add_argument("--map-scale", type=float, metavar="N",
                   help="scale of the printed map, e.g. 5000 for 1:5000 (default: read from the page)")
    b.add_argument("--scale", type=float, metavar="N",
                   help="build at this tactile scale, e.g. 1000 for 1:1000, instead of the suggested size; "
                        "the guidebook recommends 1:500 to 1:1000")
    b.add_argument("--no-validate", action="store_true", help="skip the pixel check against the PDF")
    b.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>)")

    z = sub.add_parser("size", help="suggested print size of a map or part of it (quick, builds nothing)")
    z.add_argument("pdf", type=Path)
    z.add_argument("--page", type=int, default=0, help="page number, from 0")
    z.add_argument("--crop", type=_window, metavar="X0,Y0,X1,Y1[,...]", help=WINDOW_HELP)
    z.add_argument("--map-scale", type=float, metavar="N", help="scale of the printed map (default: read from the page)")
    _settings_args(z)

    g = sub.add_parser("legend", help="stand-alone tactile legend with every tactile symbol found in a map")
    g.add_argument("pdf", type=Path)
    g.add_argument("--page", type=int, default=0, help="page number, from 0")
    g.add_argument("--crop", type=_window, metavar="X0,Y0,X1,Y1[,...]",
                   help="only symbols in this window (rectangle or polygon, as for build)")
    _settings_args(g)
    g.add_argument("--title", default="key", metavar="TEXT", help='Braille title of the legend (default "key")')
    g.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>/legend)")

    a = ap.parse_args(argv)
    try:
        _run(a)
    except ValueError as e:  # a wrong setting, crop or region: say what, without a traceback
        ap.exit(1, f"Error: {e}\n")


def _run(a: argparse.Namespace) -> None:
    out = getattr(a, "out", None) or _default_out(a.pdf)

    if a.command == "legend":
        out = a.out or _default_out(a.pdf) / "legend"
        r = build_legend_sample(LegendOptions(a.pdf, out, a.config, a.heights, a.page, a.crop, a.title,
                                              tuple(a.settings), _overrides(a)))
        print(f"Legend written to {out / 'legend.stl'}: {r['size_mm'][0]:.0f} by {r['size_mm'][1]:.0f} mm, "
              f"{len(r['classes'])} symbols: {', '.join(r['classes'])}.")
        print(f"One STL per layer in {out / 'parts'} (see README.txt there).")
        print(f"Text version in {out / 'legend.txt'}.")
        return

    if a.command == "size":
        _, lines = suggest(a.pdf, a.page, a.crop, a.config, tuple(a.settings), _overrides(a), a.map_scale)
        for line in lines:
            print(line)
        print("Build at this size by leaving out --width and --scale.")
        return

    if a.command == "pick":
        write_picker(a.pdf, out / "pick.html", a.page)
        print(f"Window picker written to {out / 'pick.html'}.")
        print("Open it in a browser and draw the window: drag a rectangle, or click the corners of a polygon,")
        print("or type it in millimetres; then run the command it shows.")
        return

    r = build(BuildOptions(a.pdf, out, a.config, a.heights, a.page, a.crop, a.width, a.region,
                           a.title, a.map_scale, a.scale, not a.no_validate, tuple(a.settings), _overrides(a)))
    # Plain sentences, one per line: easy to follow with a screen reader.
    m, c = r["model"], r["tactile_check"]
    for line in r["size"]["lines"]:
        print(line)
    print(f"Model written to {out / 'model.stl'}: {m['width_mm']:.0f} by {m['height_mm']:.0f} mm, "
          f"{c['total_height_mm']:g} mm high.")
    scale = f", scale 1:{m['tactile_scale']}" if m["tactile_scale"] else ""
    print(f"One STL per layer in {out / 'parts'} ({len(r['parts'])} parts{scale}); see README.txt there.")
    print(f"Legend written to {out / 'legend.stl'} and {out / 'legend_parts'}.")
    print(f"Description written to {out / 'description.txt'}: how to hold the model, the legend, "
          "every automatic change, and the checks.")
    print(f"Settings used written to {out / 'settings_used.toml'}.")
    problems = [f"{c[k]['count']} {k.replace('_', ' ')}" for k in ("thin_parts", "narrow_gaps", "low_steps", "hidden_objects")
                if c[k]["count"]]
    if problems:
        print(f"Tactile check: {', '.join(problems)}. Details in description.txt and tactile_check.png.")
    else:
        print("Tactile check: passed.")
    print(f"Heights, textures and features can be tuned in {out / 'tuner.html'}.")
    if r["validation"]:
        v = r["validation"]["metrics"]
        print(f"Agreement with the PDF: {v['accuracy']:.2%} of the checked area.")
    if r["unclassified"]:
        print(f"Warning: {len(r['unclassified'])} kinds of map symbol were not recognised. "
              f"Add rules for the rows marked unclassified in {out / 'symbols.csv'}.")
    print(f"Done in {r['seconds']} seconds.")


if __name__ == "__main__":
    main()
