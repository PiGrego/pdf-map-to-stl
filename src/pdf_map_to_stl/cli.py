"""Command line.

    pdf-map-to-stl pick   MAP.pdf             choose the area to convert (writes pick.html)
    pdf-map-to-stl build  MAP.pdf [options]   convert to STL: one body + one STL per layer,
                                              legend, description, tuner.html, previews
    pdf-map-to-stl legend MAP.pdf [options]   stand-alone tactile legend of every symbol in a map
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .pick import write_picker
from .pipeline import BuildOptions, LegendOptions, build, build_legend_sample


def _rect(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError as e:
        raise argparse.ArgumentTypeError("expected four numbers: x0,y0,x1,y1") from e
    return (x0, y0, x1, y1)


def _default_out(pdf: Path) -> Path:
    return Path("outputs") / pdf.stem.replace(" ", "_")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pdf-map-to-stl", description="Vector orienteering map PDF -> tactile STL.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pick", help="open the map page to choose the area to convert")
    p.add_argument("pdf", type=Path)
    p.add_argument("--page", type=int, default=0, help="page number, from 0")
    p.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>)")

    b = sub.add_parser("build", help="convert the map (or a part of it) to STL")
    b.add_argument("pdf", type=Path)
    b.add_argument("--page", type=int, default=0, help="page number, from 0")
    b.add_argument("--crop", type=_rect, metavar="X0,Y0,X1,Y1",
                   help="part of the PDF page to convert, mm from its top-left corner (get it from pick.html)")
    b.add_argument("--width", type=float, metavar="MM", help="printed model width (default from config)")
    b.add_argument("-c", "--config", type=Path, help="symbol rules and classes (default config/default.toml)")
    b.add_argument("--heights", type=Path, help="heights.toml saved from tuner.html")
    b.add_argument("--region", type=_rect, metavar="X0,Y0,X1,Y1",
                   help="only this rectangle of the model, mm from its bottom-left corner: a test tile")
    b.add_argument("--title", metavar="TEXT",
                   help='Braille title at the top left (default: the file name; --title "" for none)')
    b.add_argument("--map-scale", type=float, metavar="N",
                   help="scale of the printed map, e.g. 5000 for 1:5000 (adds the scale to the title)")
    b.add_argument("--scale", type=float, metavar="N",
                   help="build at this tactile scale, e.g. 1000 for 1:1000 (needs --map-scale); "
                        "the guidebook recommends 1:500 to 1:1000")
    b.add_argument("--no-validate", action="store_true", help="skip the pixel check against the PDF")
    b.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>)")

    g = sub.add_parser("legend", help="stand-alone tactile legend with every tactile symbol found in a map")
    g.add_argument("pdf", type=Path)
    g.add_argument("--page", type=int, default=0, help="page number, from 0")
    g.add_argument("--crop", type=_rect, metavar="X0,Y0,X1,Y1", help="only symbols in this part of the page")
    g.add_argument("-c", "--config", type=Path, help="symbol rules and classes (default config/default.toml)")
    g.add_argument("--heights", type=Path, help="heights.toml saved from tuner.html")
    g.add_argument("--title", default="key", metavar="TEXT", help='Braille title of the legend (default "key")')
    g.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>/legend)")

    a = ap.parse_args(argv)
    out = a.out or _default_out(a.pdf)

    if a.command == "legend":
        out = a.out or _default_out(a.pdf) / "legend"
        r = build_legend_sample(LegendOptions(a.pdf, out, a.config, a.heights, a.page, a.crop, a.title))
        print(f"Legend written to {out / 'legend.stl'}: {r['size_mm'][0]:.0f} by {r['size_mm'][1]:.0f} mm, "
              f"{len(r['classes'])} symbols: {', '.join(r['classes'])}.")
        print(f"One STL per layer in {out / 'parts'} (see README.txt there).")
        print(f"Text version in {out / 'legend.txt'}.")
        return

    if a.command == "pick":
        write_picker(a.pdf, out / "pick.html", a.page)
        print(f"Area picker written to {out / 'pick.html'}.")
        print("Open it in a browser, choose the area by dragging or by typing it in millimetres,")
        print("then run the command it shows.")
        return

    r = build(BuildOptions(a.pdf, out, a.config, a.heights, a.page, a.crop, a.width, a.region,
                           a.title, a.map_scale, a.scale, not a.no_validate))
    # Plain sentences, one per line: easy to follow with a screen reader.
    m, c = r["model"], r["tactile_check"]
    print(f"Model written to {out / 'model.stl'}: {m['width_mm']:.0f} by {m['height_mm']:.0f} mm, "
          f"{c['total_height_mm']:g} mm high.")
    scale = f", scale 1:{m['tactile_scale']}" if m["tactile_scale"] else ""
    print(f"One STL per layer in {out / 'parts'} ({len(r['parts'])} parts{scale}); see README.txt there.")
    print(f"Legend written to {out / 'legend.stl'} and {out / 'legend_parts'}.")
    print(f"Description written to {out / 'description.txt'}: how to hold the model, the legend, and the checks.")
    problems = [f"{c[k]['count']} {k.replace('_', ' ')}" for k in ("thin_parts", "narrow_gaps", "low_steps", "hidden_objects")
                if c[k]["count"]]
    if problems:
        print(f"Tactile check: {', '.join(problems)}. Details in description.txt and tactile_check.png.")
    else:
        print("Tactile check: passed.")
    print(f"Heights can be tuned in {out / 'tuner.html'}.")
    if r["validation"]:
        v = r["validation"]["metrics"]
        print(f"Agreement with the PDF: {v['accuracy']:.2%} of the checked area.")
    if r["unclassified"]:
        print(f"Warning: {len(r['unclassified'])} kinds of map symbol were not recognised. "
              f"Add rules for the rows marked unclassified in {out / 'symbols.csv'}.")
    print(f"Done in {r['seconds']} seconds.")


if __name__ == "__main__":
    main()
