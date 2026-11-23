"""Uncontracted 6-dot Braille: text to dot positions in millimetres.

Letters a-z, digits (number sign + a-j), space, and a few punctuation marks. Accented
letters are reduced to their base letter, and capitals are written as lowercase (no
capital sign), which keeps labels short. National Braille codes differ for accented
letters; if a label needs them, write it without accents in the config.

Cell layout (dot numbers)::

    1 4
    2 5
    3 6
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

LETTERS = {
    "a": "1", "b": "12", "c": "14", "d": "145", "e": "15", "f": "124", "g": "1245",
    "h": "125", "i": "24", "j": "245", "k": "13", "l": "123", "m": "134", "n": "1345",
    "o": "135", "p": "1234", "q": "12345", "r": "1235", "s": "234", "t": "2345",
    "u": "136", "v": "1236", "w": "2456", "x": "1346", "y": "13456", "z": "1356",
}  # fmt: skip
DIGITS = {str(d): LETTERS["jabcdefghi"[d]] for d in range(10)}
PUNCTUATION = {",": "2", ";": "23", ":": "25", ".": "256", "!": "235", "?": "236", "-": "36", "'": "3", "/": "34"}
NUMBER_SIGN = "3456"
LETTER_SIGN = "56"  # after a number, before a letter a-j, so it is not read as a digit

# (column, row) of each dot inside a cell
DOT_POSITION = {"1": (0, 0), "2": (0, 1), "3": (0, 2), "4": (1, 0), "5": (1, 1), "6": (1, 2)}


@dataclass(frozen=True)
class BrailleSpec:
    """Physical Braille size. Defaults follow common standards for embossed Braille
    (dot base about 1.5 mm, 2.5 mm between dots, 6 mm between cells, 10 mm between
    lines), with dots a little higher than on paper because printed plastic is harder."""

    dot_diameter_mm: float = 1.5
    dot_height_mm: float = 0.6
    dot_spacing_mm: float = 2.5
    cell_spacing_mm: float = 6.0
    line_spacing_mm: float = 10.0

    @property
    def cell_height_mm(self) -> float:
        return 2 * self.dot_spacing_mm + self.dot_diameter_mm


def to_cells(text: str) -> list[str]:
    """Text -> list of cells, each a string of dot numbers ("" = blank cell)."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    cells: list[str] = []
    in_number = False
    for ch in plain:
        if ch.isdigit():
            if not in_number:
                cells.append(NUMBER_SIGN)
                in_number = True
            cells.append(DIGITS[ch])
            continue
        if ch in LETTERS:
            if in_number and ch in "abcdefghij":
                cells.append(LETTER_SIGN)
            cells.append(LETTERS[ch])
        elif ch in PUNCTUATION:
            cells.append(PUNCTUATION[ch])
            if ch in ".,":  # decimal point / thousands separator keep the number going
                continue
        elif ch.isspace():
            cells.append("")
        # anything else is dropped
        in_number = False
    return cells


def wrap(text: str, max_cells: int) -> list[str]:
    """Split text into lines of at most ``max_cells`` cells, breaking at spaces."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(to_cells(candidate)) > max_cells:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def dot_centres(text: str, spec: BrailleSpec, x0: float, y_top: float) -> list[tuple[float, float]]:
    """Centres (mm) of the raised dots of one line of text. ``x0`` is the left edge of the
    first cell, ``y_top`` the top edge of the cells (model y points up)."""
    r = spec.dot_diameter_mm / 2
    out = []
    for i, cell in enumerate(to_cells(text)):
        for dot in cell:
            col, row = DOT_POSITION[dot]
            out.append((x0 + r + i * spec.cell_spacing_mm + col * spec.dot_spacing_mm, y_top - r - row * spec.dot_spacing_mm))
    return out


def width_mm(text: str, spec: BrailleSpec) -> float:
    n = len(to_cells(text))
    return 0.0 if n == 0 else (n - 1) * spec.cell_spacing_mm + spec.dot_spacing_mm + spec.dot_diameter_mm
