"""Command line.

    pdf-map-to-stl pick  MAP.pdf             choose the area to convert (writes pick.html)
    pdf-map-to-stl build MAP.pdf [options]   convert to STL (+ tuner.html, previews, report)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .pick import write_picker
from .pipeline import BuildOptions, build


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
    b.add_argument("--no-validate", action="store_true", help="skip the pixel check against the PDF")
    b.add_argument("-o", "--out", type=Path, help="output folder (default outputs/<map name>)")

    a = ap.parse_args(argv)
    out = a.out or _default_out(a.pdf)

    if a.command == "pick":
        write_picker(a.pdf, out / "pick.html", a.page)
        print(f"Open {out / 'pick.html'} in a browser, drag a rectangle, and run the command it shows.")
        return

    r = build(BuildOptions(a.pdf, out, a.config, a.heights, a.page, a.crop, a.width, a.region, not a.no_validate))
    print(f"STL      {out / 'model.stl'}  ({r['model']['width_mm']} x {r['model']['height_mm']} mm, "
          f"{r['stl']['triangles']} triangles)")
    print(f"Tune     {out / 'tuner.html'}  (heights; saves heights.toml)")
    print(f"Symbols  {out / 'symbols.csv'}")
    if r["validation"]:
        v = r["validation"]["metrics"]
        print(f"Check    {v['accuracy']:.2%} agreement with the PDF on {v['evaluated_share']:.0%} of the area")
    if r["unclassified"]:
        print(f"WARNING  {len(r['unclassified'])} symbol signatures not recognised: add rules for them "
              f"(rows with class 'unclassified' in symbols.csv)")
    print(f"Done in {r['seconds']} s")


if __name__ == "__main__":
    main()
